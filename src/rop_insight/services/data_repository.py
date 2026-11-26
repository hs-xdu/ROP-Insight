"""P6-A case-only repository. No artifact/Image/Run writer or inference integration."""
from rop_insight.models.managed_data import (
    CaseRecord, CaseRequest, CaseRevision, StoreError, normalize_code, require, valid_uuid, valid_time,
)

_REVISION_FIELDS = tuple(CaseRevision.__dataclass_fields__)


def _revision(row):
    return CaseRevision(**{name: row[name] for name in _REVISION_FIELDS})


def _get(connection, case_id, revision_id=None):
    case = connection.execute('SELECT * FROM cases WHERE case_id=?', (case_id,)).fetchone()
    if case is None:
        return None
    revision = connection.execute('SELECT * FROM case_revisions WHERE case_id=? AND revision_id=?',
                                  (case_id, revision_id or case['current_revision_id'])).fetchone()
    if revision is None:
        raise StoreError('STORE_CORRUPT', '病例资料版本缺失')
    if revision_id is None and (case['case_code'], case['case_code_key']) != (revision['case_code'], revision['case_code_key']):
        raise StoreError('STORE_CORRUPT', '病例身份与当前版本不一致')
    return CaseRecord(case['case_id'], revision['case_code'], case['created_at'],
                      revision['created_at'] if revision_id else case['updated_at'], case['archived_at'], _revision(revision))


def _content(revision):
    return (revision.case_code, revision.notes, revision.default_eye, revision.default_exam_date)


def _insert_revision(connection, request, previous):
    connection.execute('''INSERT INTO case_revisions
        (revision_id,case_id,previous_revision_id,case_code,case_code_key,notes,default_eye,default_exam_date,created_at)
        VALUES (?,?,?,?,?,?,?,?,?)''',
        (request.revision_id, request.case_id, previous, request.case_code, request.case_code.lower(),
         request.notes, request.default_eye, request.default_exam_date, request.created_at))


def _ensure_code_available(connection, request):
    row = connection.execute('SELECT case_id FROM cases WHERE case_code_key=?', (request.case_code.lower(),)).fetchone()
    if row and row['case_id'] != request.case_id:
        raise StoreError('CASE_CODE_CONFLICT', '研究编号已被其他病例使用')


class CaseRepository:
    def __init__(self, store):
        self.store = store

    def create_case(self, request):
        require(isinstance(request, CaseRequest), '请求类型无效')
        request = request.validated()
        with self.store.transaction(write=True) as connection:
            existing = connection.execute('SELECT * FROM case_revisions WHERE revision_id=?', (request.revision_id,)).fetchone()
            if existing:
                revision = _revision(existing)
                if (revision.case_id, revision.previous_revision_id, _content(revision), revision.created_at) != (
                        request.case_id, None, request.content, request.created_at):
                    raise StoreError('IDEMPOTENCY_CONFLICT', '同一创建请求ID的内容不同')
                return _get(connection, request.case_id, request.revision_id)
            if connection.execute('SELECT 1 FROM cases WHERE case_id=?', (request.case_id,)).fetchone():
                raise StoreError('IDEMPOTENCY_CONFLICT', '病例UUID已存在')
            _ensure_code_available(connection, request)
            connection.execute('''INSERT INTO cases
                (case_id,case_code,case_code_key,current_revision_id,created_at,updated_at)
                VALUES (?,?,?,?,?,?)''', (request.case_id, request.case_code, request.case_code.lower(),
                                        request.revision_id, request.created_at, request.created_at))
            _insert_revision(connection, request, None)
            return _get(connection, request.case_id)

    def update_case(self, case_id, expected_revision_id, request):
        valid_uuid(case_id)
        valid_uuid(expected_revision_id)
        require(isinstance(request, CaseRequest), '请求类型无效')
        request = request.validated()
        require(request.case_id == case_id, '请求病例UUID不匹配')
        with self.store.transaction(write=True) as connection:
            existing = connection.execute('SELECT * FROM case_revisions WHERE revision_id=?', (request.revision_id,)).fetchone()
            if existing:
                revision = _revision(existing)
                if (revision.case_id, revision.previous_revision_id, _content(revision), revision.created_at) != (
                        case_id, expected_revision_id, request.content, request.created_at):
                    raise StoreError('IDEMPOTENCY_CONFLICT', '同一更新请求ID的内容不同')
                return _get(connection, case_id, request.revision_id)
            current = _get(connection, case_id)
            require(current is not None, '病例不存在')
            if current.revision.revision_id != expected_revision_id:
                raise StoreError('STALE_REVISION', '病例已被修改，请重新读取')
            if request.content == _content(current.revision):
                return current
            require(request.created_at >= current.updated_at, '新版本时间不能早于当前版本')
            _ensure_code_available(connection, request)
            _insert_revision(connection, request, expected_revision_id)
            cursor = connection.execute('''UPDATE cases SET case_code=?,case_code_key=?,updated_at=?,current_revision_id=?
                WHERE case_id=? AND current_revision_id=?''',
                (request.case_code, request.case_code.lower(), request.created_at, request.revision_id, case_id, expected_revision_id))
            if cursor.rowcount != 1:
                raise StoreError('STALE_REVISION', '病例更新冲突')
            return _get(connection, case_id)

    def get_case(self, case_id):
        valid_uuid(case_id)
        with self.store.transaction() as connection:
            return _get(connection, case_id)

    def find_case_by_code(self, code):
        code = normalize_code(code)
        with self.store.transaction() as connection:
            row = connection.execute('SELECT case_id FROM cases WHERE case_code_key=?', (code.lower(),)).fetchone()
            return _get(connection, row['case_id']) if row else None

    def get_case_revision(self, revision_id):
        valid_uuid(revision_id)
        with self.store.transaction() as connection:
            row = connection.execute('SELECT * FROM case_revisions WHERE revision_id=?', (revision_id,)).fetchone()
            return _revision(row) if row else None

    def list_cases(self, filter=None, limit=50, cursor=None):
        require(type(limit) is int and 1 <= limit <= 200, '分页大小应为1—200')
        require(filter is None or isinstance(filter, str), '查询条件无效')
        query, values = "SELECT case_id,created_at FROM cases WHERE instr(case_code_key,?)>0", [(filter or '').strip().lower()]
        if cursor is not None:
            require(isinstance(cursor, tuple) and len(cursor) == 2, '分页游标无效')
            time, case_id = valid_time(cursor[0]), valid_uuid(cursor[1])
            query += ' AND (created_at,case_id)>(?,?)'
            values.extend((time, case_id))
        query += ' ORDER BY created_at,case_id LIMIT ?'
        values.append(limit)
        with self.store.transaction() as connection:
            rows = connection.execute(query, values).fetchall()
            return tuple(_get(connection, row['case_id']) for row in rows)

    def health_check(self):
        return self.store.health_check()
