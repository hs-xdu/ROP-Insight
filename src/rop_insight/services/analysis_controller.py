"""GUI-thread controller with one active worker and stale-result filtering."""

from copy import deepcopy
from rop_insight import __version__
from threading import Event
from uuid import uuid4

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal, pyqtSlot

from rop_insight.models.analysis_result import (
    AnalysisRun, ImageContext, ModuleError, ModuleResult, ModuleState, timestamp,
)
from rop_insight.services.analysis_config import default_config, ordered_modules, parse_config
from rop_insight.services.analysis_worker import AnalysisWorker
from rop_insight.services.build_info import code_identity


class AnalysisController(QObject):
    changed = pyqtSignal()
    result_changed = pyqtSignal(object)
    idle = pyqtSignal()

    def __init__(self, config=None, registry=None, parent=None):
        super().__init__(parent)
        self.registry = dict(registry or {})
        self.config = deepcopy(config if config is not None else default_config())
        self.context = None
        self.current_run = None
        self.input_outputs = {}
        self._thread = self._worker = None
        self._cancel = Event()

    @property
    def busy(self):
        return self._thread is not None

    @property
    def available(self):
        enabled = [m for m in self.config.modules if m.enabled and m.adapter_id in self.registry]
        return bool(enabled) and all(not getattr(self.registry[m.adapter_id], "requires_input", False)
                                     or m.module_id in self.input_outputs for m in enabled)

    def set_document(self, document):
        self.cancel()
        self.context = ImageContext.from_document(document) if document else None
        self.current_run = None
        self.input_outputs.clear()
        self.changed.emit()

    def provide_input(self, module_id, output):
        from rop_insight.inference.base import validate_output
        if self.context is None:
            raise ValueError("请先导入原图")
        validate_output(output, (self.context.image.width(), self.context.image.height()))
        self.cancel()
        self.current_run = None
        self.input_outputs[module_id] = deepcopy(output)
        self.changed.emit()

    def start(self):
        if self.busy or self.context is None or not self.available:
            return False
        # Revalidate even programmatically supplied configuration at the boundary.
        from dataclasses import asdict
        data = asdict(self.config)
        data["modules"] = [dict(item, dependencies=list(item["dependencies"])) for item in data["modules"]]
        config = parse_config(data, self.registry)
        modules = ordered_modules(config)
        from dataclasses import replace
        context = replace(self.context, image=self.context.image.copy())
        software_version = __version__
        self.current_run = AnalysisRun(str(uuid4()), context.image_id, deepcopy(config), {
            m.module_id: ModuleResult(m.module_id, model_version=m.model_version) for m in modules
        }, software_version=software_version)
        self.current_run.code_revision, self.current_run.code_dirty = code_identity()
        self._cancel = Event()
        thread = QThread(self)
        worker = AnalysisWorker(context, self.current_run.run_id, deepcopy(modules),
                                dict(self.registry), self._cancel, deepcopy(self.input_outputs))
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.updated.connect(self._update, Qt.ConnectionType.QueuedConnection)
        worker.done.connect(thread.quit, Qt.ConnectionType.DirectConnection)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._finished)
        self._thread, self._worker = thread, worker
        thread.start()
        self.changed.emit()
        return True

    def cancel(self):
        if self.busy:
            self._cancel.set()
            self.changed.emit()

    @property
    def cancelling(self):
        return self.busy and self._cancel.is_set()

    @pyqtSlot(str, str, object)
    def _update(self, image_id, run_id, result):
        run = self.current_run
        if not run or not self.context or (image_id, run_id) != (self.context.image_id, run.run_id):
            return
        result = deepcopy(result)
        if self._cancel.is_set() and result.state in (ModuleState.RUNNING, ModuleState.SUCCESS):
            result.state = ModuleState.CANCELLED
            result.output = None
            result.error = ModuleError("cancelled", "任务已取消")
        run.modules[result.module_id] = result
        self.result_changed.emit(deepcopy(run))
        self.changed.emit()

    @pyqtSlot()
    def _finished(self):
        thread = self._thread
        self._thread = self._worker = None
        if self.current_run:
            run = self.current_run
            for result in run.modules.values():
                if result.state in (ModuleState.PENDING, ModuleState.RUNNING):
                    result.state = ModuleState.CANCELLED if self._cancel.is_set() else ModuleState.FAILED
                    result.error = ModuleError("cancelled" if self._cancel.is_set() else "worker_failed",
                                               "任务已取消" if self._cancel.is_set() else "任务意外结束")
            # Intentionally disabled modules do not turn a successful Vessel run partial.
            states = [run.modules[m.module_id].state for m in run.config.modules if m.enabled]
            run.status = ("cancelled" if self._cancel.is_set() else
                          "success" if all(s == ModuleState.SUCCESS for s in states) else
                          "partial_success" if ModuleState.SUCCESS in states else "failed")
            run.finished_at = timestamp()
            self.result_changed.emit(deepcopy(run))
        thread.deleteLater()
        self.changed.emit()
        self.idle.emit()
