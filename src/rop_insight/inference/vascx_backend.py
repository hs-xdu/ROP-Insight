"""Executed with the original research interpreter, with no Qt dependency."""

import argparse
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import random
import traceback


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(request):
    import cv2
    import numpy as np
    import torch
    from PIL import Image
    from rtnls_fundusprep.mask_extraction import get_cfi_bounds
    from rtnls_fundusprep.transformation import Interpolation
    from rtnls_inference.ensembles.ensemble_segmentation import SegmentationEnsemble

    destination = Path(request["output_dir"])
    weights = Path(request["weights_path"])
    digest = sha256(weights)
    if digest != request["weights_sha256"]:
        raise ValueError("模型权重 SHA-256 与配置不一致")
    if request["device"] == "cuda:0" and not torch.cuda.is_available():
        raise RuntimeError("CUDA 不可用，未自动切换 CPU")
    packages = {p: metadata.version(p) for p in ("retinalysis-inference", "retinalysis-fundusprep", "numpy", "torch")}
    random.seed(20261029)
    np.random.seed(20261029)
    torch.manual_seed(20261029)
    torch.set_num_threads(8)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    rgb = np.array(Image.open(request["input_path"]).convert("RGB"))
    bounds = get_cfi_bounds(rgb)
    transform, cropped = bounds.crop(1024)
    prepared = transform.warp(rgb, (1024, 1024))
    enhanced = cropped.contrast_enhanced_5
    Image.fromarray(prepared).save(destination / "preprocessed.png")
    Image.fromarray(enhanced.astype(np.uint8)).save(destination / "contrast_enhanced.png")
    ensemble = SegmentationEnsemble.from_torchscript(
        str(weights), batch_size=1, tile_batch_size=2).to(request["device"]).eval()
    # Match the native reference_refresh pipeline; no custom thresholds or resizing.
    with torch.inference_mode():
        item = ensemble.preprocess_item({"id": "input", "image": str(destination / "preprocessed.png"),
                                        "contrast_enhanced": str(destination / "contrast_enhanced.png")},
                                       input_space="preprocessed")
        batch = ensemble.make_batch([item])
        prediction = ensemble.predict_batch(batch)
        result = ensemble.postprocess_batch(prediction, batch)[0]
    native = np.asarray(result["output"])
    probabilities = np.asarray(result["probabilities"])
    if (result["output_space"] != "preprocessed" or native.shape != (1024, 1024)
            or not np.isin(native, [0, 1]).all()
            or probabilities.shape != (1024, 1024, 2) or not np.isfinite(probabilities).all()):
        raise ValueError("VascX 原生分割输出无效")
    aligned = transform.warp_inverse(native.astype(np.uint8), out_size=rgb.shape[:2],
                                     mode=Interpolation.NEAREST)
    if aligned.shape != rgb.shape[:2] or not np.isin(aligned, [0, 1]).all():
        raise ValueError("原图坐标逆映射失败")
    Image.fromarray(native.astype(np.uint8)).save(destination / "native_mask.png")
    Image.fromarray(aligned.astype(np.uint8)).save(destination / "aligned_mask.png")
    np.savez_compressed(destination / "native_probabilities.npz", probabilities=probabilities)
    info = {"model": request["model_version"], "weights_sha256": digest,
            "input_snapshot_sha256": sha256(request["input_path"]),
            "rgb_pixels_sha256": hashlib.sha256(rgb.tobytes()).hexdigest(),
            "backend_sha256": sha256(__file__),
            "device": request["device"], "packages": packages, "seed": 20261029,
            "source_size": list(rgb.shape[:2]), "transform": transform.to_dict(),
            "bounds": bounds.to_dict(), "embedded_config": ensemble.config,
            "protocol": "reference_refresh native preprocessing + nearest inverse mapping",
            "native_mask_sha256": sha256(destination / "native_mask.png"),
            "aligned_mask_sha256": sha256(destination / "aligned_mask.png")}
    (destination / "result.json").write_text(json.dumps(info, ensure_ascii=False, indent=2,
        allow_nan=False, default=lambda value: value.tolist()), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("request", type=Path)
    args = parser.parse_args()
    request = json.loads(args.request.read_text(encoding="utf-8"))
    try:
        run(request)
    except Exception as exc:
        (Path(request["output_dir"]) / "error.json").write_text(json.dumps({
            "type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()
        }, ensure_ascii=False), encoding="utf-8")
        raise


if __name__ == "__main__":
    main()
