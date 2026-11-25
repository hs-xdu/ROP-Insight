"""Serial worker. No widget or QPixmap access is allowed here."""

from copy import deepcopy
import logging
from time import monotonic

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from rop_insight.inference.base import validate_output
from rop_insight.models.analysis_result import ModuleError, ModuleResult, ModuleState

logger = logging.getLogger("rop_insight.analysis")


class AnalysisWorker(QObject):
    updated = pyqtSignal(str, str, object)
    done = pyqtSignal()

    def __init__(self, context, run_id, modules, registry, cancel):
        super().__init__()
        self.context, self.run_id = context, run_id
        self.modules, self.registry, self.cancel = modules, registry, cancel

    @pyqtSlot()
    def run(self):
        completed = {}
        try:
            for config in self.modules:
                result = ModuleResult(config.module_id, model_version=config.model_version)
                started = monotonic()
                if self.cancel.is_set():
                    result.state = ModuleState.CANCELLED
                    result.error = ModuleError("cancelled", "任务已取消")
                elif not config.enabled:
                    result.state = ModuleState.SKIPPED
                    result.error = ModuleError("unconfigured", "分析模块未配置或已禁用")
                elif any(completed[dep].state != ModuleState.SUCCESS for dep in config.dependencies):
                    result.state = ModuleState.SKIPPED
                    result.error = ModuleError("dependency_unavailable", "所需上游结果不可用")
                else:
                    result.state = ModuleState.RUNNING
                    self._emit(result)
                    try:
                        if config.weights_path:
                            from pathlib import Path
                            if not Path(config.weights_path).is_file():
                                raise FileNotFoundError("模型文件不存在")
                        adapter = self.registry[config.adapter_id]()
                        image = self.context.image.copy()
                        adapter.validate(image, config)
                        output = adapter.execute(image, deepcopy({
                            dep: completed[dep].output for dep in config.dependencies
                        }), deepcopy(config), self.cancel)
                        if self.cancel.is_set():
                            result.state = ModuleState.CANCELLED
                            result.error = ModuleError("cancelled", "任务已取消")
                        else:
                            validate_output(output, (image.width(), image.height()))
                            result.output = deepcopy(output)
                            result.state = ModuleState.SUCCESS
                    except Exception as exc:
                        logger.exception("Analysis module %s failed in run %s", config.module_id, self.run_id)
                        result.state = ModuleState.FAILED
                        code = "model_missing" if isinstance(exc, FileNotFoundError) else "execution_failed"
                        result.error = ModuleError(code, "模型文件缺失" if code == "model_missing" else "模块执行失败，请检查配置和本地日志")
                result.elapsed_seconds = monotonic() - started
                completed[config.module_id] = deepcopy(result)
                self._emit(result)
        except Exception:
            logger.exception("Analysis worker failed in run %s", self.run_id)
        finally:
            self.done.emit()

    def _emit(self, result):
        self.updated.emit(self.context.image_id, self.run_id, deepcopy(result))
