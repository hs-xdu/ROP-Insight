from threading import Event

import pytest
from PyQt6.QtCore import QThread, QTimer, Qt
from PyQt6.QtWidgets import QApplication

from rop_insight.models.analysis_result import AnalysisOutput, ModuleState
from rop_insight.services.analysis_config import parse_config
from rop_insight.services.analysis_controller import AnalysisController
from rop_insight.services.image_loader import ImageLoader
from rop_insight.ui.main_window import MainWindow


@pytest.fixture
def harness(qtbot, image_file):
    controllers, gates = [], []

    def make(specs=None, block=False, failure=False, invalid=False):
        entered, release = Event(), Event()
        gates.append(release)
        executions = []

        class TestAdapter:
            supported_devices = ("cpu",)

            def validate(self, image, config):
                assert not image.isNull()

            def execute(self, image, upstream, config, cancel):
                executions.append((config.module_id, QThread.currentThread(), upstream))
                entered.set()
                if block and config.module_id == "ridge":
                    assert release.wait(5), "test gate timed out"
                if failure and config.module_id == "ridge":
                    raise RuntimeError("private traceback details")
                if invalid:
                    return object()
                return AnalysisOutput({"module": config.module_id, "parameter": config.preprocessing.get("value")})

        registry = {"test": TestAdapter}
        data = {"schema_version": 1, "modules": specs or [
            {"module_id": "ridge", "enabled": True, "adapter_id": "test", "device": "cpu"}
        ]}
        parsed = parse_config(data, registry)
        controller = AnalysisController(parsed, registry)
        controllers.append(controller)
        controller.set_document(ImageLoader().load(image_file()))
        return controller, entered, release, executions

    yield make
    for gate in gates:
        gate.set()
    for controller in controllers:
        controller.cancel()
        qtbot.waitUntil(lambda c=controller: not c.busy, timeout=6000)


def wait_finished(qtbot, controller):
    qtbot.waitUntil(lambda: not controller.busy, timeout=6000)
    return controller.current_run


def test_background_responsiveness_snapshots_and_main_thread_publication(qtbot, harness):
    controller, entered, release, executions = harness(block=True)
    publications = []
    controller.result_changed.connect(lambda run: publications.append((run, QThread.currentThread())))
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(1)
    assert controller.start()
    qtbot.waitUntil(entered.is_set)
    assert not controller.start()
    assert executions[0][1] != QApplication.instance().thread()
    controller.config.modules[0].preprocessing["value"] = "changed after start"
    qtbot.waitUntil(lambda: len(ticks) >= 3)
    assert controller.busy
    release.set()
    run = wait_finished(qtbot, controller)
    timer.stop()
    assert run.status == "success"
    assert run.modules["ridge"].output.values["parameter"] is None
    assert run.config.modules[0].preprocessing == {}
    assert run.started_at and run.finished_at and run.software_version
    assert run.image_id == controller.context.image_id
    assert all(thread == QApplication.instance().thread() for _, thread in publications)
    first_id = run.run_id
    assert controller.start()
    assert wait_finished(qtbot, controller).run_id != first_id


def test_partial_failure_dependencies_and_disabled_modules(qtbot, harness):
    specs = [dict(module_id=name, enabled=True, adapter_id="test", device="cpu", dependencies=deps)
             for name, deps in [("staging", ["ridge"]), ("ridge", []), ("vessel", [])]]
    specs.append({"module_id": "unused"})
    controller, _, _, executions = harness(specs=specs, failure=True)
    assert controller.start()
    run = wait_finished(qtbot, controller)
    assert run.status == "partial_success"
    assert run.modules["ridge"].state == ModuleState.FAILED
    assert "private" not in run.modules["ridge"].error.message
    assert run.modules["staging"].state == ModuleState.SKIPPED
    assert run.modules["unused"].error.code == "unconfigured"
    assert run.modules["vessel"].state == ModuleState.SUCCESS
    assert [item[0] for item in executions] == ["ridge", "vessel"]


def test_upstream_outputs_and_signal_snapshots_are_independent(qtbot, harness):
    specs = [dict(module_id=name, enabled=True, adapter_id="test", device="cpu", dependencies=deps)
             for name, deps in [("staging", ["ridge"]), ("ridge", [])]]
    controller, _, _, executions = harness(specs=specs)

    def mutate_notification(run):
        run.modules.clear()

    controller.result_changed.connect(mutate_notification)
    assert controller.start()
    run = wait_finished(qtbot, controller)
    assert run.status == "success"
    assert executions[1][2]["ridge"].values["module"] == "ridge"
    assert len(run.modules) == 2


def test_disabled_modules_do_not_make_success_partial(qtbot, harness):
    specs = [{"module_id": "ridge"}, {"module_id": "vessel", "enabled": True,
             "adapter_id": "test", "device": "cpu"}, {"module_id": "staging"}]
    controller, _, _, _ = harness(specs=specs)
    assert controller.start()
    run = wait_finished(qtbot, controller)
    assert run.status == "success"
    assert run.modules["ridge"].state == ModuleState.SKIPPED


def test_image_context_is_a_pixel_snapshot(qtbot, harness, image_file):
    from PyQt6.QtGui import QColor
    controller, _, _, _ = harness()
    document = ImageLoader().load(image_file())
    controller.set_document(document)
    expected = controller.context.image.pixelColor(0, 0)
    document.image.fill(QColor("black"))
    assert controller.context.image.pixelColor(0, 0) == expected


def test_missing_weights_and_invalid_output(qtbot, harness, tmp_path):
    controller, _, _, _ = harness(specs=[dict(module_id="ridge", enabled=True,
        adapter_id="test", device="cpu", weights_path=str(tmp_path / "missing.pt"))])
    assert controller.start()
    assert wait_finished(qtbot, controller).modules["ridge"].error.code == "model_missing"
    invalid, _, _, _ = harness(invalid=True)
    assert invalid.start()
    assert wait_finished(qtbot, invalid).status == "failed"


def test_cancel_preserves_published_success(qtbot, harness):
    specs = [dict(module_id=name, enabled=True, adapter_id="test", device="cpu")
             for name in ("vessel", "ridge", "staging")]
    controller, _, release, _ = harness(specs=specs, block=True)
    assert controller.start()
    qtbot.waitUntil(lambda: controller.current_run.modules["ridge"].state == ModuleState.RUNNING)
    assert controller.current_run.modules["vessel"].state == ModuleState.SUCCESS
    controller.cancel()
    assert controller.busy and controller.cancelling
    assert not controller.start()
    release.set()
    run = wait_finished(qtbot, controller)
    assert run.status == "cancelled"
    assert run.modules["vessel"].state == ModuleState.SUCCESS
    for name in ("ridge", "staging"):
        assert run.modules[name].state == ModuleState.CANCELLED
        assert run.modules[name].output is None


@pytest.mark.parametrize("clear", [True, False])
def test_context_invalidation_filters_late_results(qtbot, harness, image_file, clear):
    controller, entered, release, _ = harness(block=True)
    original_id = controller.context.image_id
    controller.start()
    qtbot.waitUntil(entered.is_set)
    controller.set_document(None if clear else ImageLoader().load(image_file("new.png")))
    assert controller.current_run is None
    if not clear:
        assert controller.context.image_id != original_id
    release.set()
    assert wait_finished(qtbot, controller) is None


def test_window_unconfigured_controls(qtbot, image_file):
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.load_image(image_file())
    assert not window.analyze_button.isEnabled()
    assert not window.cancel_analysis_button.isEnabled()
    assert window.analysis_label.text() == "分析模块未配置"
    window.resize(800, 560)
    window.show()
    QApplication.processEvents()
    assert window.analyze_button.height() >= window.analyze_button.sizeHint().height()
    assert window.cancel_analysis_button.height() >= window.cancel_analysis_button.sizeHint().height()


def test_window_failed_import_keeps_context_and_close_waits(qtbot, harness, image_file, tmp_path):
    controller, entered, release, _ = harness(block=True)
    window = MainWindow(controller=controller)
    qtbot.addWidget(window)
    window.show()
    window.load_image(image_file())
    identifier = controller.context.image_id
    assert not window.load_image(tmp_path / "missing.png")
    assert controller.context.image_id == identifier
    qtbot.mouseClick(window.analyze_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(entered.is_set)
    assert window.cancel_analysis_button.isEnabled()
    window.close()
    assert window.isVisible()
    assert controller.cancelling
    release.set()
    qtbot.waitUntil(lambda: not window.isVisible())
    assert not controller.busy
