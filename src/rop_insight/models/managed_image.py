"""Frozen image import identity, independent of current GUI selection or models."""
from dataclasses import dataclass, replace, asdict
from pathlib import Path
import hashlib
import json
from uuid import uuid4
from rop_insight.models.managed_data import require, valid_uuid, valid_time, valid_hash, valid_date


@dataclass(frozen=True)
class RidgeInput:
    source: Path
    original_filename: str
    file_sha256: str
    binary_pixel_sha256: str


@dataclass(frozen=True)
class ImageImportRequest:
    image_id: str
    operation_id: str
    case_id: str
    case_revision_id: str
    eye: str
    exam_date: str | None
    imported_at: str
    original_filename: str
    source: Path
    width: int
    height: int
    format: str
    file_sha256: str
    rgb_pixel_sha256: str
    ridge: RidgeInput | None = None

    @classmethod
    def capture(cls, document, case_id, case_revision_id, eye='unspecified', exam_date=None, ridge_path=None):
        from rop_insight.services.result_exporter import pixel_hash
        from rop_insight.models.analysis_result import timestamp
        from rop_insight.inference.imported_ridge import load_ridge
        ridge = None
        if ridge_path is not None:
            output = load_ridge(ridge_path, document.image.size())
            ridge = RidgeInput(Path(ridge_path).absolute(), Path(ridge_path).name,
                               output.values['file_sha256'], hashlib.sha256(output.masks[0].pixels).hexdigest())
        return cls(str(uuid4()), str(uuid4()), case_id, case_revision_id, eye, exam_date, timestamp(),
                   document.path.name, document.path, document.image.width(), document.image.height(), document.format,
                   document.file_sha256, pixel_hash(document.image), ridge).validated()

    def validated(self):
        for value in (self.image_id, self.operation_id, self.case_id, self.case_revision_id):valid_uuid(value)
        require(isinstance(self.eye, str) and self.eye in ('left','right','unspecified'), '眼别无效')
        require(type(self.width) is int and type(self.height) is int and self.width>0 and self.height>0 and self.width*self.height<=40_000_000, '图像尺寸无效')
        require(isinstance(self.format,str) and self.format in ('PNG','JPEG'), '图像格式无效')
        for value in (self.file_sha256, self.rgb_pixel_sha256):valid_hash(value)
        for filename in (self.original_filename,) + ((self.ridge.original_filename,) if isinstance(self.ridge,RidgeInput) else ()):
            require(isinstance(filename,str) and filename not in ('','.','..') and not any(c in filename for c in '/\\:') and not any(ord(c)<32 for c in filename), '原文件名无效')
        require(isinstance(self.source,Path), '图像源路径无效')
        if self.ridge is not None:
            require(isinstance(self.ridge,RidgeInput) and isinstance(self.ridge.source,Path), 'Ridge输入无效')
            valid_hash(self.ridge.file_sha256);valid_hash(self.ridge.binary_pixel_sha256)
        return replace(self,source=self.source.absolute(),ridge=replace(self.ridge,source=self.ridge.source.absolute()) if self.ridge is not None else None,exam_date=valid_date(self.exam_date),imported_at=valid_time(self.imported_at))

    def payload(self):
        data=asdict(self.validated())
        data.pop('source')
        if data['ridge'] is not None:data['ridge'].pop('source')
        return data

    @property
    def digest(self):
        return hashlib.sha256(json.dumps(self.payload(),sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


@dataclass(frozen=True)
class ManagedImage:
    image_id: str
    case_id: str
    case_revision_id: str
    eye: str
    exam_date: str | None
    original_filename: str
    managed_relpath: str
    width: int
    height: int
    format: str
    file_sha256: str
    rgb_pixel_sha256: str
    imported_at: str
    operation_id: str
    save_state: str
    integrity_state: str
    failure_code: str | None
    failure_message: str | None
    last_verified_at: str | None
