"""Isolated VascX adapter: reuse the research environment without changing it."""

import json
import logging
import os
from pathlib import Path
import subprocess
from time import monotonic
from uuid import uuid4

from PyQt6.QtCore import QStandardPaths
from PyQt6.QtGui import QImage

from rop_insight.models.analysis_result import AnalysisOutput, MaskData
from rop_insight.inference.base import AdapterError

logger = logging.getLogger("rop_insight.analysis")


class VascXAdapter:
    supported_devices = ("cpu", "cuda:0")

    def validate(self, image, config):
        if image.isNull():
            raise ValueError("需要有效 RGB 图像")
        if not config.runtime_python or not Path(config.runtime_python).is_file():
            raise AdapterError("runtime_missing", "VascX 原实验环境不存在，请检查 runtime_python")
        if not config.weights_path or not Path(config.weights_path).is_file():
            raise FileNotFoundError("VascX 权重不存在")
        if not config.weights_sha256 or not config.model_version:
            raise ValueError("必须明确模型版本及权重 SHA-256")
        if config.preprocessing or config.postprocessing:
            raise ValueError("本适配器固定复用原实验流程，不接受隐式预处理或阈值覆盖")

    def execute(self, image, upstream, config, cancel):
        root = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
        return self._execute(image, config, cancel, root / "vascx_runs")

    def _execute(self, image, config, cancel, root):
        folder = Path(root) / str(uuid4())
        folder.mkdir(parents=True)
        input_path = folder / "input.png"
        try:
            if not image.save(str(input_path), "PNG"):
                raise OSError("无法创建 VascX 输入快照")
            request = dict(input_path=str(input_path), output_dir=str(folder),
                           weights_path=config.weights_path, weights_sha256=config.weights_sha256,
                           model_version=config.model_version, device=config.device)
            request_path = folder / "request.json"
            request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
            env = os.environ.copy()
            env.update(PYTHONDONTWRITEBYTECODE="1", HF_HUB_OFFLINE="1", PYTHONNOUSERSITE="1",
                       MPLCONFIGDIR=str(folder / "matplotlib"), NUMBA_CACHE_DIR=str(folder / "numba"))
            # Do not leak the UI environment's packages into the research interpreter.
            env.pop("PYTHONPATH", None)
            env.pop("PYTHONHOME", None)
            command = [config.runtime_python, "-B", str(Path(__file__).with_name("vascx_backend.py")), str(request_path)]
            with (folder / "backend.log").open("w", encoding="utf-8") as log:
                process = subprocess.Popen(command, cwd=folder, env=env, stdout=log, stderr=log,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                started = monotonic()
                try:
                    while process.poll() is None:
                        if cancel.wait(0.05):
                            return AnalysisOutput({"cancelled": True})
                        if monotonic() - started > 600:
                            raise AdapterError("timeout", "VascX 推理超过 600 秒，请检查原实验环境与设备")
                    if process.returncode:
                        error = folder / "error.json"
                        if error.exists():
                            logger.error("VascX backend error: %s", error.read_text(encoding="utf-8"))
                        raise AdapterError("vascx_failed", f"VascX 执行失败，详见日志：{folder / 'backend.log'}")
                finally:
                    # Only this adapter's child process is stopped, never a QThread.
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
            metadata = json.loads((folder / "result.json").read_text(encoding="utf-8"))
            mask = QImage(str(folder / "aligned_mask.png")).convertToFormat(QImage.Format.Format_Grayscale8)
            if mask.isNull() or mask.size() != image.size():
                raise ValueError("VascX 原图 Mask 无效")
            raw = mask.constBits().asstring(mask.sizeInBytes())
            width, height, stride = mask.width(), mask.height(), mask.bytesPerLine()
            pixels = b''.join(raw[y * stride:y * stride + width] for y in range(height))
            metadata["artifacts_dir"] = str(folder)
            return AnalysisOutput(metadata, masks=(MaskData("vessel", width, height, pixels),))
        finally:
            # Remove only the owned transient RGB copy; retained artifacts contain results.
            input_path.unlink(missing_ok=True)
