from dataclasses import replace
import sqlite3
from uuid import uuid4
import pytest
from rop_insight.services.local_records import LocalRecords
from rop_insight.services.image_loader import ImageLoader
from rop_insight.models.analysis_result import ImageContext,AnalysisRun
from rop_insight.services.analysis_config import AnalysisConfig
from rop_insight.services.result_exporter import ExportSnapshot
from rop_insight.services.report_builder import build_report


@pytest.fixture
def saved_input(tmp_path,image_file):
    store=LocalRecords(tmp_path/'data');case=store.create_case('TEST-001','left','2026-11-26')
    context=ImageContext.from_document(ImageLoader().load(image_file('原图.png',24,16)))
    run=AnalysisRun(str(uuid4()),context.image_id,AnalysisConfig(()),{},status='success',finished_at='2026-11-26T00:00:00+00:00')
    return store,case,ExportSnapshot.capture(context,run)


def test_cases_duplicate_reopen_and_two_table_schema(saved_input):
    store,case,snapshot=saved_input
    assert LocalRecords(store.root).cases()==(case,)
    with pytest.raises(ValueError):store.create_case('test-001')
    for code in ('',' '*3,'x'*65):
        with pytest.raises(ValueError):store.create_case(code)
    with pytest.raises(ValueError):store.create_case('DATE','left','2026-02-30')
    with sqlite3.connect(store.root/'rop_insight.db') as db:assert {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}=={'cases','analysis_records'}


@pytest.mark.parametrize('status',['success','partial_success','failed','cancelled'])
def test_explicit_save_duplicate_multi_run_and_source_deleted(saved_input,status):
    store,case,snapshot=saved_input;snapshot.run.status=status
    row=store.save_record(case,snapshot)
    again=store.save_record(case,snapshot);assert again==row and row['report_path'] is None
    other=ExportSnapshot.capture(snapshot.context,replace(snapshot.run,run_id=str(uuid4())))
    second=store.save_record(case,other);assert row['record_id']!=second['record_id']
    from pathlib import Path
    Path(snapshot.context.source).unlink()
    assert store.save_record(case,snapshot)==row
    assert ImageLoader().load(store.root/row['image_path']).file_sha256==snapshot.context.file_sha256
    assert LocalRecords(store.root).verify_record(row['record_id'])==row


def test_report_save_and_later_attach_preserve_p5(saved_input,qapp):
    store,case,snapshot=saved_input
    row=store.save_record(case,snapshot)
    report=build_report(snapshot)
    row=store.save_record(case,snapshot,report)
    assert row['report_path'] and (store.root/row['report_path']).is_file()
    assert store.save_record(case,snapshot,report)==row
    other=build_report(ExportSnapshot.capture(snapshot.context,replace(snapshot.run,run_id=str(uuid4()))))
    with pytest.raises(ValueError):store.save_record(case,snapshot,other)


def test_changed_case_and_changed_source_and_corruption(saved_input):
    store,case,snapshot=saved_input
    other=store.create_case('OTHER')
    row=store.save_record(case,snapshot)
    with pytest.raises(ValueError):store.save_record(other,snapshot)
    (store.root/row['result_path']).write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError):store.verify_record(row['record_id'])


def test_source_changed_and_export_failure_no_valid_row(saved_input,monkeypatch):
    store,case,snapshot=saved_input
    import rop_insight.services.local_records as module
    with monkeypatch.context() as patch:
        patch.setattr(module,'export_bundle',lambda *args:(_ for _ in ()).throw(PermissionError('injected')))
        with pytest.raises(PermissionError):store.save_record(case,snapshot)
    assert store.get_record(snapshot.run.run_id) is None
    from pathlib import Path
    Path(snapshot.context.source).write_bytes(b'changed')
    with pytest.raises(ValueError):store.save_record(case,snapshot)
    assert store.get_record(snapshot.run.run_id) is None


def test_publish_then_db_failure_retry_without_source(saved_input,monkeypatch):
    from contextlib import contextmanager
    from pathlib import Path
    store,case,snapshot=saved_input;original=store._db
    @contextmanager
    def failing(write=False):
        with original(write) as db:
            yield db
            if write:raise sqlite3.OperationalError('injected commit failure')
    with monkeypatch.context() as patch:
        patch.setattr(store,'_db',failing)
        with pytest.raises(sqlite3.OperationalError):store.save_record(case,snapshot)
    assert store.get_record(snapshot.run.run_id) is None
    Path(snapshot.context.source).unlink()
    assert store.save_record(case,snapshot)['record_id']==snapshot.run.run_id


def test_wrong_library_and_unsafe_paths(saved_input,tmp_path):
    from rop_insight.services.local_records import _safe
    store,case,snapshot=saved_input
    other=LocalRecords(tmp_path/'other')
    with pytest.raises(ValueError):other.save_record(case,snapshot)
    for relative in ('../a','C:/a','/a','a/../b','a\\b'):
        with pytest.raises(ValueError):_safe(store.root,relative)
    with sqlite3.connect(store.root/'rop_insight.db') as db:db.execute('PRAGMA user_version=99')
    with pytest.raises(ValueError):LocalRecords(store.root)
