"""Engineering acceptance only: no model inference or diagnosis."""

import sys
from pathlib import Path
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PyQt6.QtWidgets import QApplication
from rop_insight.models.analysis_result import AnalysisOutput
from rop_insight.services.analysis_config import parse_config
from rop_insight.services.analysis_controller import AnalysisController
from rop_insight.ui.main_window import MainWindow


class AcceptanceTask:
    supported_devices = ("cpu",)

    def validate(self, image, config):
        if image.isNull():
            raise ValueError("验收任务需要图像")

    def execute(self, image, upstream, config, cancel):
        deadline = monotonic() + 5
        while monotonic() < deadline:
            if cancel.wait(0.05):
                break
        return AnalysisOutput({"engineering_check": True})


def main():
    app = QApplication(sys.argv)
    registry = {"acceptance_only": AcceptanceTask}
    config = parse_config({"schema_version": 1, "modules": [
        {"module_id": "engineering_task", "enabled": True,
         "adapter_id": "acceptance_only", "device": "cpu"}
    ]}, registry)
    controller = AnalysisController(config, registry)
    window = MainWindow(controller=controller)
    window.setWindowTitle("P2-A 工程验收 · 无模型推理、无诊断结果")
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
