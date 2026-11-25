"""Synthetic overlays and probabilities, strictly for engineering acceptance."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPainter, QColor, QPen
from PyQt6.QtWidgets import QApplication
from rop_insight.models.analysis_result import AnalysisOutput, MaskData, ClassificationData
from rop_insight.services.analysis_config import parse_config
from rop_insight.services.analysis_controller import AnalysisController
from rop_insight.ui.main_window import MainWindow


class SyntheticAdapter:
    supported_devices = ("cpu",)

    def validate(self, image, config):
        if image.isNull():
            raise ValueError("需要测试图像")

    def execute(self, image, upstream, config, cancel):
        cancel.wait(1)
        width, height = image.width(), image.height()
        masks = []
        for name in ("ridge", "vessel"):
            binary = QImage(width, height, QImage.Format.Format_Grayscale8)
            binary.fill(0)
            painter = QPainter(binary)
            painter.setPen(QPen(QColor(1, 1, 1), max(1, width // 60)))
            if name == "ridge":
                painter.drawEllipse(width // 4, height // 4, width // 2, height // 2)
            else:
                painter.drawLine(width // 2, height // 2, width // 5, height // 5)
                painter.drawLine(width // 2, height // 2, width * 4 // 5, height * 4 // 5)
            painter.end()
            raw = binary.constBits().asstring(binary.sizeInBytes())
            stride = binary.bytesPerLine()
            pixels = b''.join(raw[y * stride:y * stride + width] for y in range(height))
            masks.append(MaskData(name, width, height, pixels))
        return AnalysisOutput({"source": "synthetic_acceptance"}, tuple(masks),
                              ClassificationData((0.1, 0.2, 0.6, 0.1)))


def main():
    app = QApplication(sys.argv)
    registry = {"synthetic_only": SyntheticAdapter}
    config = parse_config({"schema_version": 1, "modules": [{
        "module_id": "synthetic_acceptance", "enabled": True,
        "adapter_id": "synthetic_only", "device": "cpu"
    }]}, registry)
    window = MainWindow(controller=AnalysisController(config, registry))
    window.setWindowTitle("P2-B 工程验收 · 合成 Mask/概率，非模型预测")
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
