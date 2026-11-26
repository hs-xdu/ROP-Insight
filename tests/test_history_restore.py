"""P7-B restores immutable files into a separate view; inference is forbidden."""
from dataclasses import replace
from pathlib import Path
from threading import Event
from uuid import uuid4
import gc,hashlib,json,sqlite3
import pytest
from rop_insight.models.analysis_result import AnalysisRun,ModuleResult,ModuleError,AnalysisOutput,ClassificationData,MaskData,ImageContext
from rop_insight.services.analysis_config import AnalysisConfig,ModuleConfig
from rop_insight.services.image_loader import ImageLoader
from rop_insight.services.result_exporter import ExportSnapshot
from rop_insight.services.report_builder import build_report
from rop_insight.services.local_records import LocalRecords
from rop_insight.services.record_history import load_analysis,load_report,export_saved_pdf,query_records
from rop_insight.ui.record_history import HistoryWindow


@pytest.fixture
def rich_saved(tmp_path,image_file,qapp):
    store=LocalRecords(tmp_path/'library');case=store.create_case('ROP-DEMO','left','2026-11-26')
    context=ImageContext.from_document(ImageLoader().load(image_file('synthetic.png',24,16)))
    ridge=MaskData('ridge',24,16,bytes([0,1]*192));vessel=MaskData('vessel',24,16,bytes([1,0]*192))
    metrics={key:dict(value=value,unit='无量纲',grid=512,status='available',reason=None) for key,value in [('fractal_dimension',1.4321),('vessel_area_density_fov',.1234),('S_median',.8)]}
    modules={
        'ridge':ModuleResult('ridge','success',output=AnalysisOutput(dict(source='user_imported_ridge'),(ridge,))),
        'vessel':ModuleResult('vessel','success',output=AnalysisOutput({},(vessel,))),
        'staging':ModuleResult('staging','success',output=AnalysisOutput({},classification=ClassificationData((.1,.2,.3,.4)))),
        'quantification':ModuleResult('quantification','success',output=AnalysisOutput(dict(metrics=metrics,feature_values=dict(T1=1.123456789,S_median=.8),score=dict(status='available',median=.8,lower=.4,upper=1.2,ci95_width=.8,valid_segments=3)))),
        'auxiliary':ModuleResult('auxiliary','success',output=AnalysisOutput(dict(auxiliary_classification=dict(status='available',prediction='Stage 1',probabilities=None,probability_calibrated=False))))}
    for module in modules.values():module.model_version='fixture-v1'
    adapters=['imported_ridge','vascx_native','a6_shenzhen','chapter5_quant','chapter5_svm']
    config=AnalysisConfig(tuple(ModuleConfig(name,True,adapter,'fixture-v1',weights_sha256='a'*64,device='cpu') for name,adapter in zip(modules,adapters)))
    run=AnalysisRun(str(uuid4()),context.image_id,config,modules,status='success',finished_at='2026-11-26T00:00:00+00:00')
    snapshot=ExportSnapshot.capture(context,run);row=store.save_record(case,snapshot)
    return store,case,snapshot,row


def test_restore_all_values_masks_and_source_without_inference(rich_saved,monkeypatch):
    store,case,snapshot,row=rich_saved
    from rop_insight.services.analysis_controller import AnalysisController
    monkeypatch.setattr(AnalysisController,'start',lambda *args:pytest.fail('inference started'))
    Path(snapshot.context.source).unlink()
    restored=load_analysis(store.root,row['record_id'])
    assert restored['case']==case and restored['image'].size()==snapshot.context.image.size()
    for name,result in snapshot.run.modules.items():
        actual=restored['run'].modules[name]
        assert actual.output.values==result.output.values
        assert actual.output.masks==result.output.masks and actual.output.classification==result.output.classification
    assert restored['data']['modules']['staging']['model_version']=='fixture-v1'
    assert query_records(store.root)['rows'][0]['prediction']=='Stage 3'
    assert load_report(store.root,row['record_id']) is None


def test_history_ui_restores_layers_probabilities_features_and_clears_selection(qtbot,rich_saved):
    store,case,snapshot,row=rich_saved
    window=HistoryWindow(store.root);qtbot.addWidget(window);window.show()
    qtbot.waitUntil(lambda:not window.worker.busy,timeout=5000)
    window.table.selectRow(0);assert window.open_selected('analysis')
    qtbot.waitUntil(lambda:not window.worker.busy,timeout=5000)
    assert window.view.item is not None and set(window.view.mask_items)=={'ridge','vessel'}
    assert 'Stage 3' in window.panel.prediction.text()
    assert '1.4321' in window.panel.metrics_label.text() and '1.123456789' in window.t1.text()
    assert '0.8' in window.panel.score_label.text() and 'Stage 1' in window.panel.auxiliary_label.text()
    assert 'fixture-v1' in window.details.toPlainText()
    assert window.panel.status.height()>=len(window.panel.status.text().splitlines())*window.panel.status.fontMetrics().height()
    window.panel.mode.setCurrentIndex(window.panel.mode.findData('overlay'))
    assert window.view.overlay_items['ridge'].isVisible()
    window.search.setText('no-match');assert window.view.item is None
    qtbot.waitUntil(lambda:'无匹配' in window.status.text(),timeout=5000)
    window.close()


def test_exact_saved_report_pdf_copy_and_lifecycle(qtbot,rich_saved,tmp_path):
    from PyQt6.QtCore import QCoreApplication,QEvent
    from rop_insight.ui.saved_report import SavedReportWindow
    store,case,snapshot,row=rich_saved
    report=build_report(snapshot);row=store.save_record(case,snapshot,report)
    saved=load_report(store.root,row['record_id'])
    original=store.root/row['report_path']
    assert saved['pdf']==original.read_bytes() and 'Stage 3' in saved['text']
    destination=tmp_path/'copied.pdf';export_saved_pdf(store.root,row['record_id'],destination)
    assert destination.read_bytes()==original.read_bytes()
    with pytest.raises(FileExistsError):export_saved_pdf(store.root,row['record_id'],destination)
    for _ in range(3):
        window=SavedReportWindow(saved);window.show();qtbot.waitUntil(lambda:window.pdf.pageCount()>0,timeout=3000)
        window.close();assert window.view.document() is None
        window.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);del window;gc.collect()


@pytest.mark.parametrize('target',['original.png','ridge_mask.png','vessel_mask.png','result.json','record_manifest.json'])
def test_missing_or_corrupt_files_fail_closed(rich_saved,target):
    store,case,snapshot,row=rich_saved
    folder=store.root/'records'/row['record_id'];(folder/target).unlink()
    with pytest.raises((OSError,ValueError)):load_analysis(store.root,row['record_id'])


def test_missing_report_does_not_block_saved_analysis(rich_saved):
    store,case,snapshot,row=rich_saved
    row=store.save_record(case,snapshot,build_report(snapshot));(store.root/row['report_path']).unlink()
    assert load_analysis(store.root,row['record_id'])['run'].run_id==row['record_id']
    with pytest.raises((OSError,ValueError)):load_report(store.root,row['record_id'])


def test_missing_original_still_allows_its_valid_report(rich_saved):
    store,case,snapshot,row=rich_saved
    row=store.save_record(case,snapshot,build_report(snapshot));(store.root/row['image_path']).unlink()
    assert load_report(store.root,row['record_id'])['pdf']


def test_failed_modules_are_unavailable_and_other_runs_do_not_leak(rich_saved):
    store,case,snapshot,row=rich_saved
    run=replace(snapshot.run,run_id=str(uuid4()),status='partial_success',modules={**snapshot.run.modules,
        'staging':ModuleResult('staging','failed',error=ModuleError('fixture_failed','synthetic failure'))})
    failed=store.save_record(case,ExportSnapshot.capture(snapshot.context,run))
    saved=load_analysis(store.root,failed['record_id'])
    assert saved['run'].modules['staging'].output is None and saved['run'].modules['staging'].error.code=='fixture_failed'
    assert next(item for item in query_records(store.root)['rows'] if item['record_id']==failed['record_id'])['prediction']=='不可用'
    assert load_analysis(store.root,row['record_id'])['run'].modules['staging'].output.classification.probabilities==(.1,.2,.3,.4)


def test_cancellation_leaves_files_unchanged(rich_saved):
    store,case,snapshot,row=rich_saved
    event=Event();event.set();before=(store.root/row['result_path']).read_bytes()
    with pytest.raises(InterruptedError):load_analysis(store.root,row['record_id'],event)
    assert (store.root/row['result_path']).read_bytes()==before


def test_history_pdf_button_and_export_actual_saved_bytes(qtbot,rich_saved,tmp_path):
    store,case,snapshot,row=rich_saved
    row=store.save_record(case,snapshot,build_report(snapshot))
    window=HistoryWindow(store.root);qtbot.addWidget(window);window.show()
    qtbot.waitUntil(lambda:not window.worker.busy,timeout=5000)
    window.table.selectRow(0);assert window.report_button.isEnabled()
    assert window.open_selected('report');qtbot.waitUntil(lambda:not window.worker.busy,timeout=5000)
    assert window.report_dialog.pdf.pageCount()>0
    destination=tmp_path/'ui-copy.pdf'
    assert window.open_selected('export_pdf',str(destination))
    qtbot.waitUntil(lambda:not window.worker.busy,timeout=5000)
    assert destination.read_bytes()==(store.root/row['report_path']).read_bytes()
    window.close();assert window.report_dialog.view.document() is None


def test_late_restore_for_another_selection_is_discarded(qtbot,rich_saved):
    from rop_insight.services.record_history import history_job
    store,case,snapshot,row=rich_saved
    second=store.save_record(case,ExportSnapshot.capture(snapshot.context,replace(snapshot.run,run_id=str(uuid4()))))
    window=HistoryWindow(store.root);qtbot.addWidget(window);window.show()
    qtbot.waitUntil(lambda:not window.worker.busy,timeout=5000)
    entered=Event();release=Event()
    def blocked(job,cancel):
        entered.set();assert release.wait(3);return history_job(job,cancel)
    window.worker.job=blocked
    window.table.selectRow(0);window.open_selected('analysis');qtbot.waitUntil(entered.is_set,timeout=3000)
    window.table.selectRow(1);release.set();qtbot.waitUntil(lambda:not window.worker.busy,timeout=5000)
    assert window.view.item is None and '选择已变化' in window.status.text()
    window.close()


def test_close_during_history_io_waits_and_does_not_change_active_analysis(qtbot,rich_saved):
    from rop_insight.ui.main_window import MainWindow
    from rop_insight.services.record_history import history_job
    store,case,snapshot,row=rich_saved
    main=MainWindow();qtbot.addWidget(main);main.library_root=str(store.root)
    main.analysis.context=snapshot.context;main.analysis.current_run=snapshot.run;main.show()
    window=main.open_history();qtbot.waitUntil(lambda:not window.worker.busy,timeout=5000)
    entered=Event()
    def wait_cancel(job,cancel):
        entered.set();cancel.wait(3);return history_job(job,cancel)
    window.worker.job=wait_cancel
    window.table.selectRow(0);window.open_selected('analysis');qtbot.waitUntil(entered.is_set,timeout=3000)
    main.close();assert main._closing
    qtbot.waitUntil(lambda:not window.worker.busy,timeout=5000)
    assert not main.isVisible() and main.analysis.current_run is snapshot.run


@pytest.mark.parametrize('damage',['version','classification','path'])
def test_invalid_saved_contracts_rejected_even_with_matching_file_hashes(rich_saved,damage):
    store,case,snapshot,row=rich_saved
    result_path=store.root/row['result_path'];data=json.loads(result_path.read_text(encoding='utf-8'))
    manifest_path=result_path.parent/'record_manifest.json';manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    if damage=='version':data['schema_version']=99
    if damage=='classification':
        data['modules']['staging']['deep_classification']['probabilities']=[2.,0.,0.,0.]
        manifest['identity']['source']['modules']['staging']['deep_classification']=data['modules']['staging']['deep_classification']
    if damage=='path':
        data['modules']['ridge']['masks']=['../outside.png']
        manifest['identity']['source']['modules']['ridge']['masks']=['../outside.png']
    result_path.write_text(json.dumps(data),encoding='utf-8');manifest['files']['result.json']=hashlib.sha256(result_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest),encoding='utf-8')
    with store._db(True) as db:db.execute('UPDATE analysis_records SET manifest_sha256=? WHERE record_id=?',(hashlib.sha256(manifest_path.read_bytes()).hexdigest(),row['record_id']))
    with pytest.raises(ValueError):load_analysis(store.root,row['record_id'])
