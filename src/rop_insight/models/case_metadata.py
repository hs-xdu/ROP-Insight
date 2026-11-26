"""Anonymous research metadata, separate from all inference inputs."""

from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
import re
from uuid import uuid4, UUID
from rop_insight.models.analysis_result import timestamp

EYES = {'unspecified':'未填写','left':'左眼','right':'右眼'}


@dataclass(frozen=True)
class CaseMetadata:
    case_id: str
    image_id: str
    input_file_sha256: str | None
    rgb_pixel_sha256: str
    eye: str = 'unspecified'
    exam_date: str | None = None
    notes: str = ''
    revision_id: str = ''
    previous_revision_id: str | None = None
    created_at: str = ''
    schema_version: int = 1

    def validated(self):
        if type(self.schema_version) is not int or self.schema_version!=1:raise ValueError('不支持的病例资料版本')
        if not isinstance(self.case_id,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',self.case_id):
            raise ValueError('病例编号需为1—64个英文字母、数字、下划线或连字符，首位为字母或数字')
        if not isinstance(self.image_id,str) or not 1<=len(self.image_id)<=128:raise ValueError('图像关联编号无效')
        if not isinstance(self.eye,str) or self.eye not in EYES:raise ValueError('请选择左眼、右眼或未填写')
        if self.exam_date is not None:
            if not isinstance(self.exam_date,str) or date.fromisoformat(self.exam_date).isoformat()!=self.exam_date:
                raise ValueError('检查日期应为合法的YYYY-MM-DD')
        if not isinstance(self.notes,str) or len(self.notes)>2000 or any(ord(c)<32 and c not in '\n\t' for c in self.notes):
            raise ValueError('备注最多2000字符，不能含无效控制字符')
        for digest in (self.input_file_sha256,self.rgb_pixel_sha256):
            if digest is not None and (not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest)):
                raise ValueError('输入哈希无效')
        if self.rgb_pixel_sha256 is None:raise ValueError('缺少解码像素哈希')
        if not isinstance(self.revision_id,str) or self.previous_revision_id==self.revision_id:raise ValueError('病例资料版本链无效')
        for revision in (self.revision_id,self.previous_revision_id):
            if revision is not None and (not isinstance(revision,str) or str(UUID(revision))!=revision):
                raise ValueError('病例资料版本编号无效')
        if not isinstance(self.created_at,str) or datetime.fromisoformat(self.created_at).tzinfo is None:
            raise ValueError('病例资料时间缺少时区')
        return self

    def to_dict(self):
        return asdict(self.validated())

    @classmethod
    def from_dict(cls,data):
        if not isinstance(data,dict) or set(data)!=set(cls.__dataclass_fields__):raise ValueError('病例资料字段无效')
        return cls(**data).validated()

    def revised(self,case_id,eye,exam_date,notes):
        return replace(self,case_id=case_id.strip(),eye=eye,exam_date=exam_date.strip() or None,notes=notes,
            revision_id=str(uuid4()),previous_revision_id=self.revision_id,created_at=timestamp()).validated()

    def assert_binding(self,image_id,file_sha256,pixel_sha256):
        self.validated()
        if (self.image_id,self.input_file_sha256,self.rgb_pixel_sha256)!=(image_id,file_sha256,pixel_sha256):
            raise ValueError('病例资料与当前图像/输入哈希不对应')


def new_case(context,pixel_sha256):
    return CaseMetadata(case_id='R-'+uuid4().hex[:12],image_id=context.image_id,input_file_sha256=context.file_sha256,
        rgb_pixel_sha256=pixel_sha256,revision_id=str(uuid4()),created_at=timestamp()).validated()
