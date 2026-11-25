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
        data["artifacts_dir"] = str(folder)
        return AnalysisOutput(data)
