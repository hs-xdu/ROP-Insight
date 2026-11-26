"""Immutable P6-A case requests and records; no image or inference side effects."""
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
import re
from uuid import UUID


class StoreError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def require(condition, message):
    if not condition:
        raise StoreError('VALIDATION_ERROR', message)


def valid_uuid(value):
    try:
        require(isinstance(value, str) and str(UUID(value)) == value, 'UUID无效')
    except (ValueError, AttributeError, TypeError):
        raise StoreError('VALIDATION_ERROR', 'UUID无效') from None
    return value


def valid_time(value):
    try:
        parsed = datetime.fromisoformat(value)
        require(parsed.tzinfo is not None and parsed.utcoffset().total_seconds() == 0, '时间必须是UTC时区')
    except (ValueError, TypeError, AttributeError):
        raise StoreError('VALIDATION_ERROR', 'UTC时间无效') from None
    return parsed.astimezone(timezone.utc).isoformat(timespec='microseconds')


def normalize_code(value):
    require(isinstance(value, str), '病例编号必须是文本')
    value = value.strip()
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', value) is not None, '病例编号格式无效')
    return value


def valid_date(value):
    if value is None or value == '':
        return None
    try:
        require(isinstance(value, str) and date.fromisoformat(value).isoformat() == value, '日期格式无效')
    except (ValueError, TypeError):
        raise StoreError('VALIDATION_ERROR', '检查日期无效') from None
    return value


def valid_hash(value):
    require(isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value) is not None, 'SHA256无效')
    return value


def valid_relpath(value):
    require(isinstance(value, str) and bool(value) and not any(c in value for c in '\\:\x00'), '相对路径无效')
    require(all(part not in ('', '.', '..') for part in value.split('/')), '相对路径越界')
    require(not any(ord(c) < 32 for c in value), '路径含控制字符')
    return value


@dataclass(frozen=True)
class CaseRequest:
    case_id: str
    revision_id: str
    case_code: str
    created_at: str
    notes: str = ''
    default_eye: str | None = None
    default_exam_date: str | None = None

    def validated(self):
        valid_uuid(self.case_id)
        valid_uuid(self.revision_id)
        require(isinstance(self.notes, str) and len(self.notes) <= 2000 and
                not any((ord(c) < 32 and c not in '\n\t') or 127 <= ord(c) <= 159 for c in self.notes), '备注无效或超过2000字符')
        require(self.default_eye is None or isinstance(self.default_eye, str) and
                self.default_eye in ('left', 'right', 'unspecified'), '默认眼别无效')
        return replace(self, case_code=normalize_code(self.case_code), created_at=valid_time(self.created_at),
                       default_exam_date=valid_date(self.default_exam_date))

    @property
    def content(self):
        return (self.case_code, self.notes, self.default_eye, self.default_exam_date)


@dataclass(frozen=True)
class CaseRevision:
    revision_id: str
    case_id: str
    previous_revision_id: str | None
    case_code: str
    case_code_key: str
    notes: str
    default_eye: str | None
    default_exam_date: str | None
    created_at: str


@dataclass(frozen=True)
class CaseRecord:
    case_id: str
    case_code: str
    created_at: str
    updated_at: str
    archived_at: str | None
    revision: CaseRevision
