"""Versioned local case sidecars. Never overwrite a saved analysis or report."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from rop_insight.models.case_metadata import CaseMetadata


def metadata_digest(data):
    return hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')).hexdigest()


def case_link(metadata,run_id=None,report_id=None):
    case=metadata if isinstance(metadata,CaseMetadata) else CaseMetadata.from_dict(metadata)
    data=case.to_dict()
    return dict(schema_version=1,metadata=data,metadata_sha256=metadata_digest(data),
        association=dict(image_id=case.image_id,input_file_sha256=case.input_file_sha256,
            rgb_pixel_sha256=case.rgb_pixel_sha256,run_id=run_id,report_id=report_id))


def validate_case_link(link,image,run_id=None,report_id=None):
    if not isinstance(link,dict) or link.get('schema_version')!=1:raise ValueError('病例关联版本无效')
    case=CaseMetadata.from_dict(link.get('metadata'))
    if link.get('metadata_sha256')!=metadata_digest(case.to_dict()):raise ValueError('病例资料哈希不一致')
    case.assert_binding(image.get('image_id'),image.get('file_sha256'),image.get('rgb_pixel_sha256'))
    expected=case_link(case,run_id,report_id)['association']
    if link.get('association')!=expected:raise ValueError('病例与图像/运行/报告关联不一致')
    return case


def write_case_link(path,metadata,run_id=None,report_id=None):
    data=case_link(metadata,run_id,report_id)
    with Path(path).open('x',encoding='utf-8') as stream:
        json.dump(data,stream,ensure_ascii=False,allow_nan=False,indent=2);stream.flush();os.fsync(stream.fileno())
    return data


def save_case_revision(metadata,parent,run_id=None):
    metadata.validated()
    parent=Path(parent).resolve()
    if not parent.is_dir():raise ValueError('请选择已存在的病例资料保存目录')
    destination=parent/('rop-case-'+metadata.revision_id)
    staging=Path(tempfile.mkdtemp(prefix='.rop-case-',dir=parent))
    try:
        write_case_link(staging/'case_metadata.json',metadata,run_id)
        if destination.exists():raise FileExistsError('该病例资料版本已保存，未覆盖')
        os.rename(staging,destination)
        return destination
    except BaseException:
        shutil.rmtree(staging,ignore_errors=True)
        raise
