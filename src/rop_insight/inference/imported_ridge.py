"""An explicitly user-provided Ridge mask, never claimed as model inference."""

import hashlib
from pathlib import Path

from PyQt6.QtGui import QImage

from rop_insight.models.analysis_result import AnalysisOutput, MaskData
from rop_insight.inference.base import AdapterError


def load_ridge(path, size):
    path = Path(path)
    if path.suffix.lower() != ".png":
        raise ValueError("Ridge Mask 仅支持二值 PNG")
    image = QImage(str(path))
    if image.isNull() or image.size() != size:
        raise ValueError("Ridge Mask 读取失败或尺寸与原图不一致")
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    raw = image.constBits().asstring(image.sizeInBytes())
    red, green, blue, alpha = raw[0::4], raw[1::4], raw[2::4], raw[3::4]
    if red != green or red != blue or set(red) - {0, 1, 255} or set(alpha) != {255}:
        raise ValueError("Mask 必须是不透明的灰度二值图，像素只允许 0、1 或 255")
    pixels = red.translate(bytes([0] + [1] * 255))
    return AnalysisOutput({"source": "user_imported_ridge", "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
                          (MaskData("ridge", image.width(), image.height(), pixels),))


class ImportedRidgeAdapter:
    supported_devices = ("cpu",)
    requires_input = True

    def validate(self, image, config):
        pass

    def execute(self, image, upstream, config, cancel):
        if "$provided" not in upstream:
            raise AdapterError("ridge_missing", "请先导入对应当前图像的 Ridge Mask")
        return upstream["$provided"]
