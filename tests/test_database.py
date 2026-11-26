"""P6-A database constraints and fault injection. Only pytest temporary stores."""
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import sqlite3
from threading import Thread
from uuid import uuid4
import pytest
from rop_insight.models.managed_data import CaseRequest,StoreError
from rop_insight.services import database as db
from rop_insight.services.data_repository import CaseRepository


def uid():return str(uuid4())


@pytest.fixture
def store(tmp_path):return db.initialize_new_store(tmp_path/'store')


@pytest.fixture
def case_request():return CaseRequest(uid(),uid(),'RESEARCH-001','2026-11-26T00:00:00+00:00')


@pytest.fixture
def registered(store,case_request):
    CaseRepository(store).create_case(case_request)
    return case_request


def raw(store):
    connection=sqlite3.connect(store.path,isolation_level=None)
    connection.execute('PRAGMA foreign_keys=ON')
    return connection


def insert(connection,table,**values):
    fields=','.join(values)
    connection.execute(f"INSERT INTO {table} ({fields}) VALUES ({','.join('?' for _ in values)})",tuple(values.values()))


def image_values(case):
    return dict(image_id=uid(),case_id=case.case_id,case_revision_id=case.revision_id,eye='left',
        exam_date='2026-11-26',original_filename='synthetic.png',imported_at=case.created_at,operation_id=uid())


def run_values(case,image):
    return dict(run_id=uid(),case_id=case.case_id,image_id=image['image_id'],case_revision_id=case.revision_id,
        source_image_id=uid(),eye_snapshot='left',exam_date_snapshot='2026-11-26',association_snapshot_json='{}',
        started_at=case.created_at,analysis_status='running',module_states_json='{}',operation_id=uid())


def test_initialize_reopen_schema_no_overwrite_and_no_implicit_creation(tmp_path,store):
    assert db.open_store(store.root).health_check()==dict(schema_version=1,database='ok',files='not_checked')
    with store.transaction() as connection:
        assert connection.execute('PRAGMA foreign_keys').fetchone()[0]==1
        assert connection.execute('PRAGMA journal_mode').fetchone()[0]=='delete'
        assert connection.execute('PRAGMA synchronous').fetchone()[0]==2
        assert connection.execute('PRAGMA busy_timeout').fetchone()[0]==5000
        assert {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}=={'cases','case_revisions','images','analysis_runs','artifacts'}
    original=store.path.read_bytes()
    with pytest.raises(StoreError):db.initialize_new_store(store.root)
    assert store.path.read_bytes()==original
    missing=tmp_path/'never-created'
    with pytest.raises(StoreError):db.open_store(missing)
    assert not missing.exists()


@pytest.mark.parametrize('failure',['ddl','commit','publish','destination_race'])
def test_initialization_failure_does_not_publish_half_database(tmp_path,monkeypatch,failure):
    root=tmp_path/'store'
    if failure=='ddl':
        original=db._apply_initial_schema
        def fail(connection):
            original(connection);connection.execute('CREATE TABLE cases(bad)')
        monkeypatch.setattr(db,'_apply_initial_schema',fail)
    elif failure=='commit':
        original=db._apply_initial_schema
        def fail(connection):
            original(connection)
            # Deferred cycle succeeds at INSERT, fails only at COMMIT.
            insert(connection,'cases',case_id=uid(),case_code='BAD',case_code_key='bad',current_revision_id=uid(),created_at='now',updated_at='now')
        monkeypatch.setattr(db,'_apply_initial_schema',fail)
    elif failure=='publish':
        monkeypatch.setattr(db,'_publish',lambda *args:(_ for _ in ()).throw(PermissionError('injected')))
    else:
        original=db._publish
        def race(temporary,destination):
            destination.write_bytes(b'other-owner')
            original(temporary,destination)
        monkeypatch.setattr(db,'_publish',race)
    with pytest.raises(StoreError):db.initialize_new_store(root)
    assert not list(root.glob('.p6-init-*'))
    if failure=='destination_race':assert (root/'catalog.sqlite3').read_bytes()==b'other-owner'
    else:assert not (root/'catalog.sqlite3').exists()


def test_deferred_case_revision_cycle_and_commit_rollback(store):
    case_id,revision_id=uid(),uid()
    with pytest.raises(StoreError) as caught:
        with store.transaction(write=True) as connection:
            insert(connection,'cases',case_id=case_id,case_code='A',case_code_key='a',current_revision_id=revision_id,created_at='now',updated_at='now')
            assert connection.execute('SELECT count(*) FROM cases').fetchone()[0]==1
            assert list(connection.execute('PRAGMA foreign_key_check'))
    assert caught.value.code=='VALIDATION_ERROR'
    with store.transaction() as connection:assert connection.execute('SELECT count(*) FROM cases').fetchone()[0]==0
    with store.transaction(write=True) as connection:
        insert(connection,'cases',case_id=case_id,case_code='A',case_code_key='a',current_revision_id=revision_id,created_at='now',updated_at='now')
        insert(connection,'case_revisions',case_id=case_id,revision_id=revision_id,case_code='A',case_code_key='a',created_at='now')
    assert store.health_check()['database']=='ok'


def test_revision_parent_immediate_cross_case_fk_and_immutability(store,registered):
    other=CaseRequest(uid(),uid(),'OTHER',registered.created_at);CaseRepository(store).create_case(other)
    connection=raw(store)
    try:
        with pytest.raises(sqlite3.IntegrityError):insert(connection,'case_revisions',case_id=uid(),revision_id=uid(),case_code='X',case_code_key='x',created_at='now')
        with pytest.raises(sqlite3.IntegrityError):insert(connection,'case_revisions',case_id=registered.case_id,revision_id=uid(),previous_revision_id=other.revision_id,case_code='X',case_code_key='x',created_at='now')
        for sql in ('UPDATE case_revisions SET notes=? WHERE revision_id=?','DELETE FROM case_revisions WHERE notes=? AND revision_id=?'):
            with pytest.raises(sqlite3.IntegrityError):connection.execute(sql,('changed' if sql.startswith('UPDATE') else '',registered.revision_id))
        with pytest.raises(sqlite3.IntegrityError):connection.execute('DELETE FROM cases WHERE case_id=?',(registered.case_id,))
    finally:connection.close()


@pytest.mark.parametrize('status,kind',[('success','p4_bundle'),('partial_success','p4_bundle'),('failed','terminal_record'),('cancelled','terminal_record'),('failed','p4_bundle'),('cancelled','p4_bundle')])
def test_ready_accepts_all_terminal_contracts_without_masks_or_report(store,registered,status,kind):
    with store.transaction(write=True) as connection:
        image=image_values(registered);insert(connection,'images',**image)
        run=run_values(registered,image)
        run.update(analysis_status=status,finished_at=registered.created_at,save_state='ready',integrity_state='valid',
            result_kind=kind,result_relpath='runs/result.json',result_sha256='a'*64,
            run_manifest_relpath='runs/run_manifest.json',run_manifest_sha256='b'*64)
        insert(connection,'analysis_runs',**run)
        assert connection.execute('SELECT a6_stage FROM analysis_runs').fetchone()[0] is None
        assert connection.execute('SELECT count(*) FROM artifacts').fetchone()[0]==0
    # Schema fixture only, not a claim that actual files have been checked/published.


@pytest.mark.parametrize('mutation',[dict(analysis_status='running'),dict(finished_at=None),dict(result_kind=None),dict(result_relpath=None),dict(result_sha256=None),dict(run_manifest_sha256=None),dict(result_kind='terminal_record'),dict(analysis_status='unknown'),dict(module_states_json='[]')])
def test_ready_rejects_missing_terminal_prerequisites(store,registered,mutation):
    with store.transaction(write=True) as connection:
        image=image_values(registered);insert(connection,'images',**image)
        run=run_values(registered,image)
        run.update(analysis_status='success',finished_at=registered.created_at,save_state='ready',integrity_state='valid',
            result_kind='p4_bundle',result_relpath='runs/result.json',result_sha256='a'*64,
            run_manifest_relpath='runs/manifest.json',run_manifest_sha256='b'*64)
        run.update(mutation)
        with pytest.raises(sqlite3.IntegrityError):insert(connection,'analysis_runs',**run)


def test_image_run_artifact_constraints_and_report_group_uniqueness(store,registered):
    other=CaseRequest(uid(),uid(),'OTHER',registered.created_at);CaseRepository(store).create_case(other)
    with store.transaction(write=True) as connection:
        image=image_values(registered);insert(connection,'images',**image)
        second=image_values(other);insert(connection,'images',**second)
        run=run_values(registered,image);insert(connection,'analysis_runs',**run)
        invalid=run_values(registered,second)
        with pytest.raises(sqlite3.IntegrityError):insert(connection,'analysis_runs',**invalid)
        artifact=dict(artifact_id=uid(),image_id=image['image_id'],run_id=run['run_id'],report_id=uid(),artifact_kind='report_pdf',source_kind='generated',operation_id=uid(),created_at='now')
        insert(connection,'artifacts',**artifact)
        with pytest.raises(sqlite3.IntegrityError):insert(connection,'artifacts',**{**artifact,'artifact_id':uid()})
        insert(connection,'artifacts',**{**artifact,'artifact_id':uid(),'report_id':uid()})
        for patch in (dict(image_id=second['image_id']),dict(save_state='ready'),dict(byte_size=-1),dict(artifact_kind='unknown'),dict(relpath='../escape'),dict(sha256='bad')):
            with pytest.raises(sqlite3.IntegrityError):insert(connection,'artifacts',**{**artifact,'artifact_id':uid(),'report_id':uid(),**patch})
        with pytest.raises(sqlite3.IntegrityError):insert(connection,'images',**{**image,'image_id':uid(),'operation_id':uid(),'save_state':'ready'})


@pytest.mark.parametrize('change',['higher_version','missing_index','changed_table','broken_bytes','wrong_current_code'])
def test_open_rejects_unknown_or_damaged_structure(store,registered,change):
    if change=='broken_bytes':store.path.write_bytes(b'not a database')
    else:
        connection=raw(store)
        if change=='higher_version':connection.execute('PRAGMA user_version=42')
        if change=='missing_index':connection.execute('DROP INDEX runs_stage')
        if change=='changed_table':connection.execute('ALTER TABLE cases ADD COLUMN unexpected TEXT')
        if change=='wrong_current_code':connection.execute("UPDATE cases SET case_code='CHANGED',case_code_key='changed'")
        connection.close()
    with pytest.raises(StoreError) as caught:db.open_store(store.root)
    assert caught.value.code in ('SCHEMA_UNSUPPORTED','STORE_CORRUPT')


def test_busy_timeout_and_readonly_io_failures(store,registered,monkeypatch):
    monkeypatch.setattr(db,'BUSY_TIMEOUT_MS',10)
    connection=raw(store);connection.execute('BEGIN IMMEDIATE')
    try:
        with pytest.raises(StoreError) as caught:CaseRepository(store).create_case(CaseRequest(uid(),uid(),'LOCKED',registered.created_at))
        assert caught.value.code=='STORE_BUSY'
    finally:connection.rollback();connection.close()
    original=db._connect
    def readonly(path):
        connection=original(path);connection.execute('PRAGMA query_only=ON');return connection
    monkeypatch.setattr(db,'_connect',readonly)
    with pytest.raises(StoreError) as caught:CaseRepository(store).create_case(CaseRequest(uid(),uid(),'READONLY',registered.created_at))
    assert caught.value.code=='STORE_IO_ERROR'
    monkeypatch.setattr(db,'_connect',original)
    assert CaseRepository(store).find_case_by_code('READONLY') is None


def test_connection_thread_affinity(store):
    with store.transaction() as connection:
        errors=[]
        def cross_thread():
            try:connection.execute('SELECT 1')
            except Exception as error:errors.append(error)
        worker=Thread(target=cross_thread);worker.start();worker.join()
        assert len(errors)==1 and isinstance(errors[0],sqlite3.ProgrammingError)


def test_rollback_failure_closes_connection_and_no_partial_rows(store,monkeypatch):
    original=db._connect;closed=[]
    class BrokenRollback:
        def __init__(self,connection):self.connection=connection
        def __getattr__(self,name):return getattr(self.connection,name)
        def rollback(self):raise sqlite3.OperationalError('injected rollback failure')
        def close(self):self.connection.close();closed.append(True)
    monkeypatch.setattr(db,'_connect',lambda path:BrokenRollback(original(path)))
    with pytest.raises(StoreError) as caught:
        with store.transaction(write=True) as connection:
            insert(connection,'cases',case_id=uid(),case_code='BROKEN',case_code_key='broken',current_revision_id=uid(),created_at='now',updated_at='now')
            raise RuntimeError('abort')
    assert caught.value.code=='STORE_IO_ERROR' and closed==[True]
    monkeypatch.setattr(db,'_connect',original)
    assert CaseRepository(store).list_cases()==()


def test_initialization_permission_and_open_access_errors(tmp_path,monkeypatch):
    original=db._reject_links
    monkeypatch.setattr(db,'_reject_links',lambda *args:(_ for _ in ()).throw(PermissionError('injected')))
    for operation in (db.initialize_new_store,db.open_store):
        with pytest.raises(StoreError) as caught:operation(tmp_path/'denied')
        assert caught.value.code=='STORE_IO_ERROR'
    monkeypatch.setattr(db,'_reject_links',original)
    for path in (None,'',123):
        with pytest.raises(StoreError) as caught:db.initialize_new_store(path)
        assert caught.value.code=='VALIDATION_ERROR'


def test_foreign_key_health_check_detects_externally_damaged_records(store):
    connection=sqlite3.connect(store.path)
    insert(connection,'cases',case_id=uid(),case_code='ORPHAN',case_code_key='orphan',current_revision_id=uid(),created_at='now',updated_at='now')
    connection.commit();connection.close()
    with pytest.raises(StoreError) as caught:db.open_store(store.root)
    assert caught.value.code=='STORE_CORRUPT'


@pytest.mark.parametrize('patch',[dict(width=0),dict(width=-1),dict(width=1.5),dict(eye='both'),dict(save_state='ready'),dict(format='BMP'),dict(file_sha256='A'*64),dict(managed_relpath='C:/outside.png')])
def test_image_checks(store,registered,patch):
    with store.transaction(write=True) as connection:
        with pytest.raises(sqlite3.IntegrityError):insert(connection,'images',**{**image_values(registered),**patch})


def test_schema_resource_and_api_surface():
    from importlib.resources import files
    script=files('rop_insight.migrations').joinpath('001_initial.sql').read_text(encoding='utf-8')
    assert 'DEFERRABLE INITIALLY DEFERRED' in script
    assert not hasattr(CaseRepository,'set_ready') and not hasattr(CaseRepository,'save_run')


def test_existing_temporary_ui_does_not_initialize_store(qtbot,tmp_path,image_file,monkeypatch):
    from rop_insight.ui.main_window import MainWindow
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(db,'initialize_new_store',lambda *args:pytest.fail('implicit initialization'))
    window=MainWindow();qtbot.addWidget(window)
    assert window.load_image(image_file('temporary.png',20,10))
    window.clear_image();window.close()
    assert not list(tmp_path.rglob('*.sqlite3'))


def test_sqlite_full_error_rolls_back_without_orphan_revision(store,monkeypatch):
    original=db._connect
    def limited(path):
        connection=original(path)
        count=connection.execute('PRAGMA page_count').fetchone()[0]
        connection.execute(f'PRAGMA max_page_count={count}')
        return connection
    monkeypatch.setattr(db,'_connect',limited)
    repo=CaseRepository(store);saved=0
    for number in range(100):
        try:
            repo.create_case(CaseRequest(uid(),uid(),f'FULL-{number}','2026-11-26T00:00:00+00:00',notes='x'*2000))
            saved+=1
        except StoreError as error:
            assert error.code=='STORE_IO_ERROR'
            assert error.__cause__.sqlite_errorcode==sqlite3.SQLITE_FULL
            break
    else:pytest.fail('SQLite storage limit was not exercised')
    monkeypatch.setattr(db,'_connect',original)
    with store.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM cases').fetchone()[0]==saved
        assert connection.execute('SELECT count(*) FROM case_revisions').fetchone()[0]==saved
        assert not list(connection.execute('PRAGMA foreign_key_check'))
    assert store.health_check()['database']=='ok'
