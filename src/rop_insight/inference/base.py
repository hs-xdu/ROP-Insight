"""Adapters are registered in Python code, never imported from config paths."""

import json
from typing import Protocol

from rop_insight.models.analysis_result import AnalysisOutput


class AnalysisAdapter(Protocol):
    supported_devices: tuple[str, ...]

    def validate(self, image, config) -> None: ...

    def execute(self, image, upstream, config, cancel) -> AnalysisOutput: ...


def validate_output(output):
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
