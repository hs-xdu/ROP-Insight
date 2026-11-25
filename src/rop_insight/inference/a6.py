"""Selected A6 Shenzhen classifier using the frozen original implementation."""

import json
from pathlib import Path
from PyQt6.QtCore import QStandardPaths
from PyQt6.QtGui import QImage

from rop_insight.inference.vascx import VascXAdapter
from rop_insight.models.analysis_result import AnalysisOutput, ClassificationData


class A6Adapter(VascXAdapter):
    backend_filename = "a6_backend.py"
    display_name = "A6 分类"

    def validate(self, image, config):
        super().validate(image, config)
        if not config.model_source or not Path(config.model_source).is_dir() or not config.source_hashes:
            raise ValueError("A6 需要已固定哈希的原模型代码")

    def execute(self, image, upstream, config, cancel):
        root = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
        return self._execute(image, config, cancel, root / "a6_runs", upstream)

    def make_request(self, folder, config, upstream):
        for name in ("ridge", "vessel"):
            output = upstream.get(name)
            masks = [m for m in output.masks if m.structure == name] if output else []
            if len(masks) != 1:
                raise ValueError(f"A6 缺少有效的 {name} 输入")
            mask = masks[0]
            picture = QImage(mask.pixels, mask.width, mask.height, mask.width,
                             QImage.Format.Format_Grayscale8).copy()
            if not picture.save(str(folder / f"{name}.png")):
                raise OSError("无法保存分类 Mask 输入")
        return {"model_source": config.model_source, "source_hashes": config.source_hashes}

    def read_output(self, folder, image):
        data = json.loads((folder / "result.json").read_text(encoding="utf-8"))
        if data["classes"] != ["Normal", "Stage1", "Stage2", "Stage3"]:
            raise ValueError("A6 标签顺序不匹配")
        data["artifacts_dir"] = str(folder)
        return AnalysisOutput(data, classification=ClassificationData(tuple(data["probabilities"])))
