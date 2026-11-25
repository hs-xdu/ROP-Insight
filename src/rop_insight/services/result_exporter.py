"""Portable, immutable result bundles published atomically in a new directory."""

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from uuid import uuid4

from PyQt6.QtGui import QImage, QColor, QPainter
from rop_insight.inference.base import validate_output

CLASSES = ('Normal', 'Stage 1', 'Stage 2', 'Stage 3')
# Explicit fields prevent accidental export of local runtime artifacts and paths.
VALUE_FIELDS = {'source', 'file_sha256', 'metrics', 'score', 'feature_values',
    'auxiliary_classification', 'classes', 'probabilities', 'logits', 'weights_sha256',
    'source_hashes', 'model_sha256', 'model_version', 'epoch', 'device', 'torch',
    'input_size', 'cudnn_deterministic', 'cudnn_tf32', 'matmul_tf32', 'input_sha256',
    'ridge_sha256', 'vessel_sha256', 'posterior_config_sha256', 'geometry_512',
    'text_exclusion', 'environment', 'native_size', 'original_size', 'threshold',
    'transform', 'preprocessing', 'postprocessing', 'model', 'input_snapshot_sha256',
    'rgb_pixels_sha256', 'backend_sha256', 'packages', 'seed', 'source_size', 'bounds',
    'embedded_config', 'protocol', 'native_mask_sha256', 'aligned_mask_sha256'}


class ExportError(ValueError):
    pass


def portable(value):
    """Remove paths even from free-text values or absolute source-hash keys."""
    if isinstance(value, dict):
        return {('source_' + hashlib.sha256(key.encode()).hexdigest()[:16] if _has_path(key) else key): portable(child)
                for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [portable(child) for child in value]
    if isinstance(value, str) and _has_path(value):
        return '[local path omitted]'
    return value


def _has_path(text):
    return bool(re.search(r'[A-Za-z]:[\\/]|\\\\|(?:^|\s)/[^\s]', text))


def pixel_hash(image):
    rgb = image.convertToFormat(QImage.Format.Format_RGB888)
    raw = rgb.constBits().asstring(rgb.sizeInBytes())
    digest = hashlib.sha256()
    for y in range(rgb.height()):
        digest.update(raw[y * rgb.bytesPerLine():y * rgb.bytesPerLine() + rgb.width() * 3])
    return digest.hexdigest()


@dataclass(frozen=True)
class ExportSnapshot:
    context: object
    run: object

    @classmethod
    def capture(cls, context, run):
        if context is None or run is None or context.image_id != run.image_id:
            raise ExportError('没有与当前图像对应的分析结果')
        if run.status == 'running' or not run.finished_at or any(
                item.state in ('pending', 'running') for item in run.modules.values()):
            raise ExportError('请等待分析结束后导出')
        if context.image.isNull():
            raise ExportError('原图快照无效')
        return cls(replace(context,image=context.image.copy()), deepcopy(run))


def _save_png(image, path):
    if not image.save(str(path), 'PNG'):
        raise OSError('PNG 写入失败')
    check = QImage(str(path))
    if check.isNull() or check.size() != image.size():
        raise OSError('PNG 读回验证失败')


def export_bundle(snapshot, parent):
    # Recapture so direct construction cannot bypass lifecycle validation.
    snapshot = ExportSnapshot.capture(snapshot.context, snapshot.run)
    context, run = snapshot.context, snapshot.run
    parent = Path(parent).resolve()
    if not parent.is_dir():
        raise ExportError('导出位置必须是已存在的文件夹')
    suffix = uuid4().hex
    destination = parent / ('rop-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + suffix)
    staging = Path(tempfile.mkdtemp(prefix='.rop-export-', dir=parent))
    try:
        artifacts, modules, masks = {}, {}, {}
        def artifact(path, kind, **extra):
            artifacts[path.name] = dict(kind=kind, sha256=hashlib.sha256(path.read_bytes()).hexdigest(), **extra)
        configs = {item.module_id: item for item in run.config.modules}
        for name, result in run.modules.items():
            cfg = configs[name]
            entry = dict(state=str(result.state), enabled=cfg.enabled, elapsed_seconds=result.elapsed_seconds,
                model_version=result.model_version, adapter_id=cfg.adapter_id, device=cfg.device,
                weights_sha256=cfg.weights_sha256, dependencies=list(cfg.dependencies),
                source_hashes=portable(cfg.source_hashes), preprocessing=portable(cfg.preprocessing),
                postprocessing=portable(cfg.postprocessing), masks=[])
            if result.error:
                entry['error'] = dict(code=portable(result.error.code), message='模块未成功，详情见本机日志')
            if result.state == 'success' and result.output:
                output = result.output
                validate_output(output, (context.image.width(), context.image.height()))
                entry['values'] = portable({key: value for key, value in output.values.items() if key in VALUE_FIELDS})
                if output.classification:
                    probabilities = list(output.classification.probabilities)
                    entry['deep_classification'] = dict(classes=list(CLASSES), probabilities=probabilities,
                        prediction=CLASSES[max(range(4), key=lambda index: probabilities[index])])
                for mask in output.masks:
                    if mask.structure in masks:
                        raise ExportError('多个模块提供相同图层，不能导出来源冲突的结果')
                    masks[mask.structure] = mask
                    image = QImage(mask.pixels.translate(bytes([0] + [255]*255)), mask.width, mask.height,
                                   mask.width, QImage.Format.Format_Grayscale8).copy()
                    filename = mask.structure + '_mask.png'
                    _save_png(image, staging / filename)
                    artifact(staging / filename, 'binary_mask', structure=mask.structure,
                             width=mask.width, height=mask.height, encoding=[0,255], coordinates='decoded_original')
                    entry['masks'].append(filename)
            modules[name] = entry
        visualization = None
        if masks:
            canvas = context.image.convertToFormat(QImage.Format.Format_RGB32)
            painter = QPainter(canvas)
            try:
                painter.setOpacity(.5)
                for name, color in (('ridge', '#fb7185'), ('vessel', '#22d3ee')):
                    if name not in masks:
                        continue
                    mask = masks[name]
                    layer = QImage(mask.pixels, mask.width, mask.height, mask.width, QImage.Format.Format_Indexed8).copy()
                    layer.setColorTable([0, QColor(color).rgba()])
                    painter.drawImage(0, 0, layer)
            finally:
                painter.end()
            visualization = 'analysis_overlay.png'
            _save_png(canvas, staging / visualization)
            artifact(staging / visualization, 'analysis_visualization', width=canvas.width(),height=canvas.height(),
                     coordinates='decoded_original',opacity=.5,colors=dict(ridge='#fb7185',vessel='#22d3ee'))
        data = dict(schema_version=1, purpose='research_prototype_not_confirmed_diagnosis',
            image=dict(image_id=context.image_id, width=context.image.width(),height=context.image.height(),
                       format=context.format, file_sha256=context.file_sha256,
                       rgb_pixel_sha256=pixel_hash(context.image), pixel_encoding='RGB888_rows_without_padding'),
            run=dict(run_id=run.run_id,status=run.status,started_at=run.started_at,finished_at=run.finished_at,
                     software_version=run.software_version,code_revision=run.code_revision,code_dirty=run.code_dirty),
            modules=modules, artifacts=artifacts,visualization=visualization,
            privacy=dict(original_file_copied=False,local_paths_included=False,
                         visualization_contains_retinal_image=bool(visualization)))
        target = staging / 'result.json'
        with target.open('x',encoding='utf-8') as stream:
            json.dump(data,stream,ensure_ascii=False,allow_nan=False,indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        if json.loads(target.read_text(encoding='utf-8')) != data:
            raise ExportError('JSON 读回不一致')
        if destination.exists():
            raise FileExistsError('导出目录已存在，请重试')
        os.rename(staging,destination)
        return destination
    except BaseException:
        # Only remove this call's freshly allocated staging directory.
        shutil.rmtree(staging,ignore_errors=True)
        raise
