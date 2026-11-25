"""Original chapter-five feature extraction, isolated from the GUI runtime."""

import json
import math
from pathlib import Path
from PyQt6.QtCore import QStandardPaths
from rop_insight.inference.a6 import A6Adapter
from rop_insight.models.analysis_result import AnalysisOutput
from rop_insight.inference.quantification_backend import FEATURES


class QuantificationAdapter(A6Adapter):
    backend_filename = "quantification_backend.py"
    display_name = "结构量化"

    def execute(self, image, upstream, config, cancel):
        root = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
        return self._execute(image, config, cancel, root / "quantification_runs", upstream)

    def make_request(self, folder, config, upstream):
        request = super().make_request(folder, config, upstream)
        artifact = Path(upstream["vessel"].values.get("artifacts_dir", ""))
        if not (artifact / "native_mask.png").is_file() or not (artifact / "preprocessed.png").is_file():
            raise ValueError("量化需要真实 Vessel 的原生网格与预处理工件")
        request["vessel_artifacts"] = str(artifact)
        return request

    def read_output(self, folder, image):
        data = json.loads((folder / "result.json").read_text(encoding="utf-8"))
        metrics = data.get("metrics")
        if not isinstance(metrics, dict) or set(metrics) != set(FEATURES):
            raise ValueError("量化结果缺少约定指标")
        for metric in metrics.values():
            if not isinstance(metric, dict) or not isinstance(metric.get("unit"), str) or metric.get("grid") not in (512, 1024):
                raise ValueError("量化单位或网格无效")
            value = metric.get("value")
            if value is None:
                if metric.get("status") != "unavailable" or not metric.get("reason"):
                    raise ValueError("缺失指标必须记录不可用原因")
            elif type(value) not in (float, int) or not math.isfinite(value) or metric.get("status") != "available":
                raise ValueError("量化指标数值无效")
        if "score" in data:
            validate_score(data["score"])
            values = data.get('feature_values')
            if not isinstance(values, dict) or set(values) != {*FEATURES, 'T1'}:
                raise ValueError('量化结果缺少冻结模型特征')
            if any(value is not None and (type(value) not in (int, float) or not math.isfinite(value))
                   for value in values.values()):
                raise ValueError('冻结模型特征数值无效')
            if any(values[name] != metrics[name]['value'] for name in FEATURES):
                raise ValueError('冻结模型特征与量化显示不一致')
            if values['S_median'] != data['score']['median']:
                raise ValueError('评分与模型输入不一致')
        data["artifacts_dir"] = str(folder)
        return AnalysisOutput(data)


def validate_score(score):
    if not isinstance(score, dict):
        raise ValueError("连续评分格式无效")
    fields = ("lower", "median", "upper", "ci95_width")
    if score.get("status") == "unavailable":
        if not score.get("reason") or any(score.get(key) is not None for key in fields):
            raise ValueError("不可用评分必须为空并说明原因")
    elif score.get("status") == "available":
        if any(type(score.get(key)) not in (float, int) or not math.isfinite(score[key]) for key in fields):
            raise ValueError("连续评分数值无效")
        if not score['lower'] <= score['median'] <= score['upper'] or not math.isclose(
                score['ci95_width'], score['upper']-score['lower'], rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError("连续评分区间无效")
    else:
        raise ValueError("连续评分状态无效")
