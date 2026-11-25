"""A6 Shenzhen native FP32 inference in the frozen research environment."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import traceback


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(request):
    import numpy as np
    import torch
    from PIL import Image
    from torchvision.transforms import functional as TF
    source = Path(request["model_source"])
    required = ("models.py", "source_snapshot/cross_attention_study/model.py")
    for relative in required:
        if digest(source / relative) != request["source_hashes"].get(relative):
            raise ValueError("A6 原模型代码哈希不一致")
    if digest(request["weights_path"]) != request["weights_sha256"]:
        raise ValueError("A6 权重哈希不一致")
    sys.path.insert(0, str(source / "source_snapshot"))
    sys.path.insert(0, str(source))
    from models import RGBExtension
    checkpoint = torch.load(request["weights_path"], map_location="cpu", weights_only=True)
    config = checkpoint["config"]
    if (config["group"] != "A6" or config["dataset"] != "shenzhen_v2"
            or config["image_size"] != 512 or config["backbone"] != "vgg16_bn"):
        raise ValueError("不是选定的 A6 深圳模型")
    device = request["device"]
    if device == "cuda:0" and not torch.cuda.is_available():
        raise RuntimeError("CUDA 不可用")
    torch.set_num_threads(4)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    torch.backends.cuda.matmul.allow_tf32 = False
    # The original A6 seed_all retained PyTorch's cuDNN TF32 default (True).
    torch.backends.cudnn.allow_tf32 = True
    model = RGBExtension(config, "A6", weights=False).to(device).eval()
    model.load_state_dict(checkpoint["model"], strict=True)
    image = Image.open(request["input_path"]).convert("RGB")
    folder = Path(request["output_dir"])
    masks = []
    for name in ("ridge", "vessel"):
        array = np.array(Image.open(folder / f"{name}.png").convert("L"))
        if array.shape != (image.height, image.width) or not np.isin(array, [0, 1, 255]).all():
            raise ValueError("Mask 尺寸或二值编码错误")
        masks.append(Image.fromarray((array > 0).astype("uint8") * 255))
    rgb = TF.normalize(TF.to_tensor(image.resize((512, 512), Image.Resampling.BILINEAR)),
                       [.485, .456, .406], [.229, .224, .225])
    inputs = [rgb] + [TF.to_tensor(mask.resize((512, 512), Image.Resampling.NEAREST)) for mask in masks]
    with torch.inference_mode():
        logits = model(*(tensor.unsqueeze(0).to(device) for tensor in inputs))
        probabilities = logits.softmax(1)[0].cpu().tolist()
    if not torch.isfinite(logits).all():
        raise ValueError("A6 输出包含非有限数值")
    result = {"classes": ["Normal", "Stage1", "Stage2", "Stage3"],
              "probabilities": probabilities, "logits": logits[0].cpu().tolist(),
              "weights_sha256": request["weights_sha256"], "source_hashes": request["source_hashes"],
              "model_version": request["model_version"], "epoch": checkpoint["epoch"],
              "device": device, "torch": torch.__version__, "input_size": 512,
              "cudnn_deterministic": True, "cudnn_tf32": True, "matmul_tf32": False,
              "input_sha256": digest(request["input_path"]),
              "ridge_sha256": digest(folder / "ridge.png"), "vessel_sha256": digest(folder / "vessel.png")}
    (folder / "result.json").write_text(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2),encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("request", type=Path)
    args = parser.parse_args()
    request = json.loads(args.request.read_text(encoding="utf-8"))
    try:
        run(request)
    except Exception as exc:
        (Path(request["output_dir"]) / "error.json").write_text(json.dumps({
            "message": str(exc), "traceback": traceback.format_exc()}, ensure_ascii=False),encoding="utf-8")
        raise
