"""Case revisions, idempotency and rollback under actual SQLite transactions."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError,replace
from threading import Barrier
import sqlite3
from uuid import uuid4
import pytest
from rop_insight.models.managed_data import CaseRequest,StoreError,valid_hash,valid_relpath
from rop_insight.services.database import initialize_new_store,open_store
from rop_insight.services.data_repository import CaseRepository
from rop_insight.services import data_repository as repository
from test_database import insert,image_values,run_values


def uid():return str(uuid4())


@pytest.fixture
def repo(tmp_path):return CaseRepository(initialize_new_store(tmp_path/'store'))


@pytest.fixture
def case_request():return CaseRequest(uid(),uid(),'  Research-001  ','2026-11-26T00:00:00+00:00',notes='研究备注 <b>原样</b>',default_eye='left',default_exam_date='2026-11-26')


def updated(case_request,**changes):
    return replace(case_request,revision_id=uid(),created_at='2026-11-26T01:00:00+00:00',notes='updated',**changes)


def test_case_create_reopen_read_versions_and_defaults(repo,case_request):
    record=repo.create_case(case_request)
    assert record.case_code=='Research-001'
    assert record.revision.default_eye=='left'
    assert repo.find_case_by_code(' research-001 ')==record
    assert CaseRepository(open_store(repo.store.root)).get_case(case_request.case_id)==record
    with pytest.raises(FrozenInstanceError):record.case_code='other'
    new=repo.update_case(case_request.case_id,case_request.revision_id,updated(case_request))
    assert new.revision.previous_revision_id==case_request.revision_id
    assert repo.get_case_revision(case_request.revision_id)==record.revision
    assert repo.get_case(case_request.case_id)==new
    assert repo.get_case(uid()) is None and repo.get_case_revision(uid()) is None


@pytest.mark.parametrize('field,value',[('case_code',''),('case_code','a'*65),('case_code','名字'),('case_code',"x'); DROP TABLE cases;--"),('notes','a'*2001),('notes','\x00'),('default_eye',[]),('default_eye','both'),('default_exam_date','2026-02-30'),('default_exam_date','2026-1-1'),('case_id','not-uuid'),('revision_id',None),('created_at','2026-11-26'),('created_at','2026-11-26T00:00:00+08:00')])
def test_validation_rejects_without_rows(repo,case_request,field,value):
    with pytest.raises(StoreError) as caught:repo.create_case(replace(case_request,**{field:value}))
    assert caught.value.code=='VALIDATION_ERROR'
    assert repo.list_cases()==()


def test_duplicate_code_rename_and_noop(repo,case_request):
    first=repo.create_case(case_request)
    other=replace(case_request,case_id=uid(),revision_id=uid(),case_code='RESEARCH-001')
    with pytest.raises(StoreError) as caught:repo.create_case(other)
    assert caught.value.code=='CASE_CODE_CONFLICT'
    assert repo.update_case(case_request.case_id,case_request.revision_id,replace(case_request,revision_id=uid()))==first
    renamed=repo.update_case(case_request.case_id,case_request.revision_id,updated(case_request,case_code='NEW'))
    assert repo.find_case_by_code('Research-001') is None
    assert repo.find_case_by_code('new')==renamed
    assert repo.get_case_revision(case_request.revision_id).case_code=='Research-001'


def test_create_and_update_idempotency_across_newer_revision(repo,case_request):
    first=repo.create_case(case_request)
    assert repo.create_case(case_request)==first
    change=updated(case_request)
    second=repo.update_case(case_request.case_id,case_request.revision_id,change)
    assert repo.update_case(case_request.case_id,case_request.revision_id,change)==second
    third=repo.update_case(case_request.case_id,change.revision_id,replace(change,revision_id=uid(),notes='third'))
    assert repo.update_case(case_request.case_id,case_request.revision_id,change)==second
    assert repo.get_case(case_request.case_id)==third
    assert repo.create_case(case_request)==first
    for bad in (replace(case_request,notes='different'),replace(case_request,created_at='2026-11-26T02:00:00+00:00'),replace(case_request,revision_id=uid())):
        with pytest.raises(StoreError) as caught:repo.create_case(bad)
        assert caught.value.code=='IDEMPOTENCY_CONFLICT'
    with pytest.raises(StoreError) as caught:repo.update_case(case_request.case_id,case_request.revision_id,replace(change,notes='changed retry'))
    assert caught.value.code=='IDEMPOTENCY_CONFLICT'


@pytest.mark.parametrize('phase',['after_case','after_revision','before_update','commit','disk_full'])
def test_fault_injection_rolls_back_case_and_revision(repo,case_request,monkeypatch,phase):
    original=repository._insert_revision
    if phase in ('after_case','after_revision','disk_full'):
        def fail(connection,case_request,previous):
            if phase!='after_case':original(connection,case_request,previous)
            if phase=='disk_full':raise sqlite3.OperationalError('injected disk full')
            raise RuntimeError('injected')
        monkeypatch.setattr(repository,'_insert_revision',fail)
        with pytest.raises((RuntimeError,StoreError)):repo.create_case(case_request)
        assert repo.get_case(case_request.case_id) is None and repo.get_case_revision(case_request.revision_id) is None
    else:
        first=repo.create_case(case_request);change=updated(case_request)
        def fail(connection,case_request,previous):
            original(connection,case_request,previous)
            if phase=='before_update':raise RuntimeError('injected')
            # Append an invalid deferred current pointer to fail COMMIT after repository code completes.
            insert(connection,'cases',case_id=uid(),case_code='BAD',case_code_key='bad',current_revision_id=uid(),created_at='now',updated_at='now')
        monkeypatch.setattr(repository,'_insert_revision',fail)
        with pytest.raises((RuntimeError,StoreError)):repo.update_case(case_request.case_id,case_request.revision_id,change)
        assert repo.get_case(case_request.case_id)==first and repo.get_case_revision(change.revision_id) is None
    assert repo.health_check()['database']=='ok'


def test_concurrent_updates_no_lost_update(repo,case_request):
    repo.create_case(case_request);barrier=Barrier(2)
    def update(note):
        other=CaseRepository(open_store(repo.store.root))
        change=replace(updated(case_request),notes=note)
        barrier.wait()
        try:return other.update_case(case_request.case_id,case_request.revision_id,change)
        except StoreError as error:return error.code
    with ThreadPoolExecutor(2) as executor:outcomes=list(executor.map(update,['one','two']))
    assert outcomes.count('STALE_REVISION')==1
    with repo.store.transaction() as connection:assert connection.execute('SELECT count(*) FROM case_revisions').fetchone()[0]==2


def test_concurrent_duplicate_create_and_rename_conflict_rollback(repo,case_request):
    barrier=Barrier(2)
    def create(_):
        other=CaseRepository(open_store(repo.store.root));new=replace(case_request,case_id=uid(),revision_id=uid())
        barrier.wait()
        try:return other.create_case(new)
        except StoreError as error:return error.code
    with ThreadPoolExecutor(2) as executor:outcomes=list(executor.map(create,[1,2]))
    assert outcomes.count('CASE_CODE_CONFLICT')==1
    existing=repo.list_cases()[0]
    other=repo.create_case(replace(case_request,case_id=uid(),revision_id=uid(),case_code='OTHER'))
    change=replace(case_request,case_id=other.case_id,revision_id=uid())
    with pytest.raises(StoreError) as caught:repo.update_case(other.case_id,other.revision.revision_id,change)
    assert caught.value.code=='CASE_CODE_CONFLICT' and repo.get_case_revision(change.revision_id) is None
    assert repo.get_case(other.case_id)==other


@pytest.mark.parametrize('value',['','A'*64,'a'*63,None])
def test_hash_contract(value):
    with pytest.raises(StoreError):valid_hash(value)


def test_edit_case_never_changes_historical_image_or_run(repo,case_request):
    record=repo.create_case(case_request)
    with repo.store.transaction(write=True) as connection:
        image=image_values(case_request);insert(connection,'images',**image)
        run=run_values(case_request,image);insert(connection,'analysis_runs',**run)
        before_image=tuple(connection.execute('SELECT * FROM images').fetchone())
        before_run=tuple(connection.execute('SELECT * FROM analysis_runs').fetchone())
    repo.update_case(case_request.case_id,case_request.revision_id,updated(case_request,case_code='CHANGED',default_eye='right',default_exam_date='2026-11-27'))
    with repo.store.transaction() as connection:
        assert tuple(connection.execute('SELECT * FROM images').fetchone())==before_image
        assert tuple(connection.execute('SELECT * FROM analysis_runs').fetchone())==before_run
    assert repo.get_case_revision(case_request.revision_id)==record.revision


def test_stable_pagination_filters_sql_text_and_time_order(repo,case_request):
    for index in range(5):repo.create_case(replace(case_request,case_id=uid(),revision_id=uid(),case_code=f'CASE-{index}',notes="'); DROP TABLE cases; --"))
    page1=repo.list_cases(filter='case-',limit=2)
    page2=repo.list_cases(filter='CASE-',limit=2,cursor=(page1[-1].created_at,page1[-1].case_id))
    page3=repo.list_cases(limit=2,cursor=(page2[-1].created_at,page2[-1].case_id))
    assert len({record.case_id for record in (*page1,*page2,*page3)})==5
    assert repo.list_cases(filter="'); DROP TABLE cases; --")==()
    assert repo.health_check()['database']=='ok'
    for arguments in (dict(limit=True),dict(limit=201),dict(cursor=('bad',uid())),dict(cursor=('x',))):
        with pytest.raises(StoreError):repo.list_cases(**arguments)
    first=page1[0]
    with pytest.raises(StoreError):repo.update_case(first.case_id,first.revision.revision_id,CaseRequest(first.case_id,uid(),first.case_code,'2025-01-01T00:00:00+00:00',notes='backdated'))


@pytest.mark.parametrize('path',['/outside','../outside','a/../b','C:/outside','file:///outside','a\\b','a//b','./a','a/./b','a\x00b'])
def test_relative_path_contract(path):
    with pytest.raises(StoreError):valid_relpath(path)
