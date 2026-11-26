"""Simplified P6-B workflows in the actual workbench, without model inference."""
from threading import Event
import sqlite3
from uuid import uuid4
import pytest
from rop_insight.models.analysis_result import AnalysisOutput
from rop_insight.services.analysis_controller import AnalysisController
from rop_insight.services.analysis_config import parse_config
from rop_insight.services.local_records import LocalRecords
from rop_insight.ui.main_window import MainWindow


@pytest.fixture
def workbench(qtbot,tmp_path,image_file):
    class Adapter:
        supported_devices=('cpu',)
        def validate(self,image,config):pass
        def execute(self,image,upstream,config,cancel):return AnalysisOutput({})
    config=parse_config(dict(schema_version=1,modules=[dict(module_id='ridge',enabled=True,adapter_id='test',device='cpu')]),{'test':Adapter})
    analysis=AnalysisController(config,{'test':Adapter})
    window=MainWindow(controller=analysis);qtbot.addWidget(window);window.show()
    store=LocalRecords(tmp_path/'library');case=store.create_case('UI-001','left','2026-11-26')
    window.apply_case(store.root,case);window.load_image(image_file('fundus.png',32,24))
    yield window,store,case
    qtbot.waitUntil(lambda:not window.records_worker.busy and not analysis.busy,timeout=5000)
    window.close()


def analyze(qtbot,window):
    window.start_analysis();qtbot.waitUntil(lambda:not window.analysis.busy,timeout=5000)
    return window.analysis.current_run


def save(qtbot,window):
    assert window.save_record();qtbot.waitUntil(lambda:not window.records_worker.busy,timeout=5000)


def test_real_workbench_save_and_attach_report(qtbot,workbench):
    window,store,case=workbench
    run=analyze(qtbot,window)
    assert window.save_record_button.isEnabled()
    save(qtbot,window)
    row=store.verify_record(run.run_id);assert row['case_id']==case['case_id'] and row['report_path'] is None
    window.preview_report();save(qtbot,window)
    assert store.verify_record(run.run_id)['report_path']
    save(qtbot,window)
    with sqlite3.connect(store.root/'rop_insight.db') as db:assert db.execute('SELECT count(*) FROM analysis_records').fetchone()[0]==1


def test_switch_case_image_and_temporary_analysis_isolation(qtbot,workbench,image_file):
    window,store,case=workbench
    old=analyze(qtbot,window)
    other=store.create_case('UI-002','right')
    window.apply_case(store.root,other)
    assert not window.save_record_button.isEnabled() and not window.save_record()
    assert 'UI-001' in window.case_label.text()
    new=analyze(qtbot,window);save(qtbot,window)
    assert store.get_record(old.run_id) is None
    assert store.get_record(new.run_id)['case_id']==other['case_id']
    window.load_image(image_file('next.png',31,23))
    assert not window.save_record_button.isEnabled()
    dialog=window.choose_case()
    qtbot.waitUntil(lambda:not dialog.worker.busy,timeout=5000)
    dialog.use_temporary()
    assert window.current_case is None
    temporary=analyze(qtbot,window)
    assert temporary.status=='success' and not window.save_record_button.isEnabled()


def test_case_selector_actual_create_select_and_reopen(qtbot,tmp_path):
    window=MainWindow();qtbot.addWidget(window)
    dialog=window.choose_case();assert dialog.load_root(tmp_path/'library')
    qtbot.waitUntil(lambda:not dialog.worker.busy,timeout=5000)
    dialog.code.setText('CASE-DEMO');dialog.eye.setCurrentIndex(1);dialog.create_case()
    qtbot.waitUntil(lambda:not dialog.worker.busy,timeout=5000)
    assert dialog.existing.count()==1
    dialog.apply();assert window.current_case['case_code']=='CASE-DEMO'
    again=window.choose_case();qtbot.waitUntil(lambda:not again.worker.busy,timeout=5000)
    assert again.existing.count()==1
    again.code.setText('case-demo');again.create_case()
    qtbot.waitUntil(lambda:not again.worker.busy,timeout=5000)
    assert '已存在' in again.status.text() and again.existing.count()==1
    again.reject();window.close()


def test_save_failure_preserves_current_analysis(qtbot,workbench,monkeypatch):
    window,store,case=workbench;run=analyze(qtbot,window)
    import rop_insight.services.local_records as module
    monkeypatch.setattr(module,'export_bundle',lambda *args:(_ for _ in ()).throw(PermissionError('injected')))
    save(qtbot,window)
    assert window.analysis.current_run.run_id==run.run_id
    assert store.get_record(run.run_id) is None and '失败' in window.error_label.text()


def test_close_waits_for_record_save(qtbot,workbench,monkeypatch):
    window,store,case=workbench;run=analyze(qtbot,window)
    import rop_insight.services.local_records as module
    original=module.export_bundle;entered=Event();release=Event()
    def waiting(*args):entered.set();assert release.wait(3);return original(*args)
    monkeypatch.setattr(module,'export_bundle',waiting)
    window.save_record();qtbot.waitUntil(entered.is_set,timeout=3000)
    window.close();assert window._closing and window.isVisible()
    release.set();qtbot.waitUntil(lambda:not window.records_worker.busy,timeout=5000)
    assert not window.isVisible() and store.get_record(run.run_id)
