"""Adapters are registered in Python code, never imported from config paths."""

import json
import math
from typing import Protocol

from rop_insight.models.analysis_result import AnalysisOutput, MaskData, ClassificationData


class AdapterError(RuntimeError):
    """An explicitly safe error code and message for the GUI."""
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class AnalysisAdapter(Protocol):
    supported_devices: tuple[str, ...]

    def validate(self, image, config) -> None: ...

    def execute(self, image, upstream, config, cancel) -> AnalysisOutput: ...


def validate_output(output, image_size=None):
    if not isinstance(output, AnalysisOutput) or not isinstance(output.values, dict):
        raise ValueError("适配器输出不符合 AnalysisOutput 契约")

    def check(value):
        if isinstance(value, dict):
            if any(not isinstance(key, str) for key in value):
                raise ValueError("结果字段名必须为字符串")
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)
        elif value is not None and type(value) not in (str, bool, int, float):
            raise ValueError("结果包含不支持的数据类型")

    check(output.values)
    json.dumps(output.values, allow_nan=False)
    if not isinstance(output.masks, tuple):
        raise ValueError("Mask 列表必须为 tuple")
    seen = set()
    for mask in output.masks:
        if not isinstance(mask, MaskData) or mask.structure not in ("ridge", "vessel"):
            raise ValueError("不支持的 Mask 类型")
        if mask.structure in seen:
            raise ValueError("Mask 类型重复")
        seen.add(mask.structure)
        if (type(mask.width) is not int or type(mask.height) is not int
                or mask.width <= 0 or mask.height <= 0
                or not isinstance(mask.pixels, bytes)
                or len(mask.pixels) != mask.width * mask.height
                or mask.pixels.translate(bytes([0, 0] + list(range(2, 256)))).strip(b'\x00')):
            raise ValueError("Mask 必须是 H×W、0/1 编码的 bytes")
        if image_size is not None and (mask.width, mask.height) != image_size:
            raise ValueError("Mask 必须映射到原图尺寸")
    if output.classification is not None:
        classification = output.classification
        if not isinstance(classification, ClassificationData):
            raise ValueError("分类结果类型错误")
        probabilities = classification.probabilities
        if (not isinstance(probabilities, tuple) or len(probabilities) != 4
                or any(type(p) not in (float, int) or not math.isfinite(p) or not 0 <= p <= 1
                       for p in probabilities)
                or not math.isclose(sum(probabilities), 1.0, abs_tol=1e-6)):
            raise ValueError("四分类概率必须为有限值、范围 0~1 且和为 1")
