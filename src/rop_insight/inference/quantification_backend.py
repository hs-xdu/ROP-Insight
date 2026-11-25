"""Reuse frozen original function bodies, excluding script-level file writes."""

import argparse
import ast
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
import types
import warnings

FEATURES = ("ridge_area_ratio_fov", "ridge_solidity", "ridge_outer_vessel_density",
            "ridge_max_radius_ratio", "vessel_area_density_fov", "fractal_dimension",
            "sliding_window_max_density_gradient", "T3", "B3", "S_median")


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def definitions(path, names, namespace):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    if {node.name for node in nodes} != set(names):
        raise ValueError("原函数定义缺失")
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)


def run(request):
    # This script lives beside our vascx.py adapter; do not shadow the native package.
    sys.path[:] = [p for p in sys.path if Path(p).resolve() != Path(__file__).parent.resolve()]
    import cv2
    import numpy as np
    from PIL import Image
    from vascx.shared.segment import Segment
    from vascx.shared.sknw.sknw import build_sknw
    from vascx.fundus.features.tortuosity import Tortuosity, TortuosityMeasure
    from vascx.shared.aggregators import LengthWeightedAggregator
    root = Path(request["model_source"])
    archive = Path(request["weights_path"]).parent.parent
    out = Path(request["output_dir"])
    for relative, expected in request["source_hashes"].items():
        if digest(root / relative) != expected:
            raise ValueError("量化原代码哈希不一致")
    if digest(archive / "selected_model/full26.json") != request["weights_sha256"]:
        raise ValueError("量化后验配置哈希不一致")
    sys.path.insert(0, str(root))
    from common.spatial import SpatialTransform
    namespace = dict(np=np, cv2=cv2, math=math, warnings=warnings, json=json,
                     Image=Image, Path=Path, OUT=out, ARCH=archive, sha=digest)
    namespace["mask"] = lambda p: np.array(Image.open(p).convert("L")) > 0
    namespace["save"] = lambda p, obj: Path(p).write_text(json.dumps(obj, default=lambda x: x.item()),encoding="utf-8")
    stage = archive / "a1_vascular_severity"
    s1 = types.ModuleType("a1_v2_stage1")
    s1.DIST = Tortuosity(measure=TortuosityMeasure.Distance, max_tortuosity=float('inf'), spline_error_fraction=.05)
    s1.CURV = Tortuosity(measure=TortuosityMeasure.Curvature, spline_error_fraction=.25)
    s1.AGG = LengthWeightedAggregator()
    sys.modules["a1_v2_stage1"] = s1
    skeleton = types.ModuleType("v3b_extract")
    skeleton.__dict__.update(np=np, math=math, Segment=Segment, build_sknw=build_sknw)
    definitions(stage / "v3b_extract.py", ["unique_links", "skeleton_length", "nx_selfloops"], skeleton.__dict__)
    sys.modules["v3b_extract"] = skeleton
    definitions(root / "phase1_preprocess/preprocess_512.py", ["_largest_cc", "_mask_bz", "compute_fov_mask"], namespace)
    definitions(root / "fusion_stage34/prepare.py", ["native_features", "extract"], namespace)
    for name in ("features", "native_rgb", "native_vessels", "aligned_vessel", "aligned_ridge", "aligned_fov"):
        (out / name).mkdir(exist_ok=True)
    artifact = Path(request["vessel_artifacts"])
    shutil.copyfile(artifact / "native_mask.png", out / "native_vessels/input.png")
    shutil.copyfile(artifact / "preprocessed.png", out / "native_rgb/input.png")
    rgb = np.array(Image.open(request["input_path"]).convert("RGB"))
    fov = namespace["compute_fov_mask"](cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY))
    if not fov.any():
        raise ValueError("有效 FOV 为空，不能计算量化指标")
    transform = SpatialTransform.from_fov(fov, 512)
    row = {"image_id": "input", "source_rgb": request["input_path"],
           "ridge_source": str(out / "ridge.png"), "geometry": transform.to_json()}
    result = namespace["extract"](row)
    if result["status"] != "ok":
        raise RuntimeError("原特征提取失败：" + result.get("error", "unknown"))
    # Replay the same frozen posterior; expose its interval without fitting anything.
    state = json.loads((archive / "selected_model/full26.json").read_text())
    posterior = archive / "selected_model/full26_posterior.npz"
    if digest(posterior) != state["posterior_sha256"]:
        raise ValueError("评分后验哈希不一致")
    score = {"status": "unavailable", "reason": "原评分质量规则未通过（至少5条有效血管段且特征有限）",
             "median": None, "lower": None, "upper": None, "ci95_width": None,
             "valid_segments": int(result["T_segments"]), "posterior_sha256": state["posterior_sha256"]}
    if result["score_qc_pass"]:
        with np.load(posterior) as samples:
            x = np.array([result[name] for name in ("L3", "B3", "T1", "T3")])
            draws = ((x - state["mean"]) / state["std"]) @ samples["w"].reshape(-1, 4).T + samples["b"].reshape(-1)
        lower, median, upper = np.quantile(draws, [.025, .5, .975])
        if not np.isfinite([lower, median, upper]).all() or float(median) != result["S_median"]:
            raise ValueError("连续评分与原提取结果不一致")
        score.update(status="available", reason=None, median=float(median), lower=float(lower),
                     upper=float(upper), ci95_width=float(upper-lower))
    units = {name: "无量纲" for name in FEATURES}
    units.update(T3="model_px^-1", B3="count/model_px²", S_median="原后验相对评分")
    metrics = {}
    for name in FEATURES:
        value = result.get(name)
        valid = value is not None and bool(np.isfinite(value))
        metrics[name] = {"value": float(value) if valid else None, "unit": units[name],
                         "status": "available" if valid else "unavailable",
                         "reason": None if valid else ("Ridge 为空或几何退化" if name.startswith("ridge") else "原实验质量规则未通过或指标不可定义"),
                         "grid": 1024 if name in ("T3", "B3", "S_median") else 512}
    feature_values = {name: float(value) if value is not None and np.isfinite(value) else None
                      for name in (*FEATURES, "T1") for value in [result.get(name)]}
    (out / "result.json").write_text(json.dumps({"metrics": metrics, "score": score,
         "feature_values": feature_values, "source_hashes": request["source_hashes"],
         "posterior_config_sha256": request["weights_sha256"], "geometry_512": json.loads(transform.to_json()),
         "text_exclusion": "zero mask as original Shenzhen protocol"}, ensure_ascii=False,allow_nan=False,indent=2),encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("request", type=Path)
    args = parser.parse_args()
    request = json.loads(args.request.read_text(encoding="utf-8"))
    run(request)
