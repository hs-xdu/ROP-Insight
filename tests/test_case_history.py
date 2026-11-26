"""P6/P7 acceptance: independent metadata, legacy history, integrity and GUI lifecycle."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from threading import Event
import shutil
import pytest
from PyQt6.QtGui import QImage
from rop_insight.models.analysis_result import ImageContext,AnalysisRun
from rop_insight.services.analysis_config import AnalysisConfig
from rop_insight.models.case_metadata import new_case,CaseMetadata
from rop_insight.services.case_store import save_case_revision,validate_case_link
from rop_insight.services.result_exporter import ExportSnapshot,pixel_hash,export_bundle
from rop_insight.services.report_builder import build_report
from rop_insight.services.report_template import render_html,render_text
from rop_insight.services.report_exporter import export_report_bundle,pdf_text
from rop_insight.services import history_store as history
from rop_insight.ui.main_window import MainWindow


@pytest.fixture
def completed(image_file):
    path=image_file('synthetic.png',20,12)
    image=QImage(str(path))
    context=ImageContext('image-1',image,str(path),hashlib.sha256(path.read_bytes()).hexdigest(),'PNG')
    run=AnalysisRun('run-1',context.image_id,AnalysisConfig(()),{},status='success',finished_at='2026-11-26T10:00:00+08:00')
    return context,run


def case_for(context):return new_case(context,pixel_hash(context.image)).revised('RESEARCH-001','left','2026-11-26','研究测试备注 <b>原样文字</b>')


def test_revisions_binding_and_atomic_save(completed,tmp_path,monkeypatch):
    context,run=completed;case=case_for(context)
    revised=case.revised(case.case_id,'right','2026-11-27','第二次')
    assert revised.previous_revision_id==case.revision_id and revised.revision_id!=case.revision_id
    assert case.eye=='left'
    folder=save_case_revision(case,tmp_path,run.run_id)
    link=json.loads((folder/'case_metadata.json').read_text(encoding='utf-8'))
    image=dict(image_id=context.image_id,file_sha256=context.file_sha256,rgb_pixel_sha256=pixel_hash(context.image))
    assert validate_case_link(link,image,run.run_id)==case
    with pytest.raises(FileExistsError):save_case_revision(case,tmp_path)
    assert not list(tmp_path.glob('.rop-case-*'))
    link['association']['run_id']='wrong'
    with pytest.raises(ValueError):validate_case_link(link,image,run.run_id)
    from rop_insight.services import case_store
    monkeypatch.setattr(case_store.os,'rename',lambda *args:(_ for _ in ()).throw(PermissionError('blocked')))
    with pytest.raises(PermissionError):save_case_revision(revised,tmp_path)
    assert not list(tmp_path.glob('.rop-case-*'))
    assert (folder/'case_metadata.json').is_file()


@pytest.mark.parametrize('field,value',[('case_id','../unsafe'),('case_id','姓名'),('case_id','a'*65),('eye',[]),('exam_date','2026-02-30'),('notes','a'*2001),('notes','\x00'),('schema_version',2),('created_at','2026-11-26'),('rgb_pixel_sha256',None)])
def test_invalid_case(completed,field,value):
    with pytest.raises(ValueError):replace(case_for(completed[0]),**{field:value}).validated()


def test_metadata_changes_do_not_change_inference_source(completed):
    context,run=completed;case=case_for(context)
    before=deepcopy(run)
    plain=build_report(ExportSnapshot.capture(context,run))
    selected=build_report(ExportSnapshot.capture(context,run,case))
    revised=case.revised('OTHER','right','','edited')
    changed=build_report(ExportSnapshot.capture(context,run,revised))
    assert plain.data['source']==selected.data['source']==changed.data['source']
    assert plain.data['source_snapshot_sha256']==selected.data['source_snapshot_sha256']==changed.data['source_snapshot_sha256']
    assert run==before and selected.data['case_metadata']['eye']=='left'
    assert '&lt;b&gt;' in render_html(selected) and '<b>原样文字</b>' not in render_html(selected)
    with pytest.raises(ValueError):ExportSnapshot.capture(replace(context,image_id='other'),replace(run,image_id='other'),case)


def test_report_bundle_case_and_pdf_and_legacy(completed,tmp_path,qtbot):
    context,run=completed;case=case_for(context)
    report=build_report(ExportSnapshot.capture(context,run,case))
    folder=export_report_bundle(report,tmp_path)
    record=history.inspect_bundle(folder)
    assert not record.issues,record.issues
    assert record.case==case and record.kind=='report'
    assert history.verified_artifact(record,'report.pdf')==folder/'report.pdf'
    pages,text=pdf_text(folder/'report.pdf')
    assert pages>0 and case.case_id in text and '左眼' in text and '研究测试备注' in text
    plain=export_report_bundle(build_report(ExportSnapshot.capture(context,run)),tmp_path)
    old=history.inspect_bundle(plain)
    assert not old.issues and old.case is None
    from rop_insight.ui.history_dialog import HistoryDialog
    dialog=HistoryDialog();dialog.records=[record];dialog.populate();dialog.table.selectRow(0)
    dialog.open_pdf()
    qtbot.waitUntil(lambda:not dialog.opener.busy,timeout=5000)
    assert len(dialog.pdf_windows)==1 and dialog.pdf_windows[0].pdf.pageCount()==pages
    dialog.open_text()
    qtbot.waitUntil(lambda:not dialog.opener.busy,timeout=5000)
    assert case.case_id in dialog.details.toPlainText()
    dialog.close()


def test_analysis_history_legacy_duplicate_cases_migration_and_input(completed,tmp_path):
    context,run=completed;case=case_for(context)
    old=export_bundle(ExportSnapshot.capture(context,run),tmp_path)
    folder=export_bundle(ExportSnapshot.capture(context,run,case),tmp_path)
    other_context=replace(context,image_id='image-2')
    other_case=new_case(other_context,pixel_hash(context.image)).revised(case.case_id,'right','2026-11-27','')
    export_bundle(ExportSnapshot.capture(other_context,replace(run,image_id='image-2',run_id='run-2'),other_case),tmp_path)
    records=history.scan_history(tmp_path)
    assert len(records)==3 and all(not r.issues for r in records)
    cases=[r.case for r in records if r.case]
    assert len(cases)==2 and {c.eye for c in cases}=={'left','right'}
    assert history.inspect_bundle(old).case_id=='未关联病例'
    record=history.inspect_bundle(folder)
    assert history.verify_input(record,context.source)=='原始文件哈希一致'
    bad=tmp_path/'other.png';bad.write_bytes(b'wrong')
    assert '不一致' in history.verify_input(record,bad)
    moved=tmp_path/'moved';shutil.move(str(folder),str(moved))
    assert history.inspect_bundle(moved).case==case
    assert len(history.scan_history(tmp_path))==3


@pytest.mark.parametrize('mutation',['broken','version','source','missing','tamper','case','traversal','absolute'])
def test_bad_records_are_visible_not_openable(completed,tmp_path,mutation):
    context,run=completed
    folder=export_bundle(ExportSnapshot.capture(context,run,case_for(context)),tmp_path)
    path=folder/'result.json';data=json.loads(path.read_text(encoding='utf-8'))
    if mutation=='broken':path.write_text('{',encoding='utf-8')
    else:
        if mutation=='version':data['schema_version']=99
        if mutation=='source':data['run']=[]
        if mutation=='missing':(folder/'case_metadata.json').unlink()
        if mutation=='tamper':(folder/'case_metadata.json').write_text('{}',encoding='utf-8')
        if mutation=='case':data['case_revision_id']='other'
        if mutation in ('traversal','absolute'):data['artifacts']['../secret' if mutation=='traversal' else 'C:\\secret']=dict(sha256='0'*64)
        path.write_text(json.dumps(data),encoding='utf-8')
    records=history.scan_history(tmp_path)
    assert len(records)==1 and records[0].issues and records[0].case is None
    with pytest.raises(ValueError):history.verified_artifact(records[0],'case_metadata.json')
    from rop_insight.ui.history_dialog import HistoryDialog
    # Malformed records remain displayable; no model or report rebuilding.
    dialog=HistoryDialog();dialog.records=records;dialog.populate();dialog.table.selectRow(0)
    assert not dialog.pdf_button.isEnabled()
    dialog.close()


def test_scan_cancel_root_and_hidden_staging(tmp_path):
    stop=Event();stop.set()
    with pytest.raises(InterruptedError):history.scan_history(tmp_path,stop)
    with pytest.raises(ValueError):history.scan_history(Path(tmp_path.anchor))
    staged=tmp_path/'.rop-report-unfinished';staged.mkdir();(staged/'report.json').write_text('{}')
    assert history.scan_history(tmp_path)==[]


def test_case_ui_save_cancel_reset_and_history_without_image(qtbot,image_file,tmp_path):
    window=MainWindow();qtbot.addWidget(window)
    assert window.open_history() is not None and not window.case_button.isEnabled()
    window.load_image(image_file('first.png'))
    original=window.case_metadata;context=window.analysis.context
    dialog=window.edit_case();dialog.case_id.setText('CHANGED');dialog.reject()
    assert window.case_metadata==original
    dialog=window.edit_case();dialog.case_id.setText('SAVED-001');dialog.eye.setCurrentIndex(dialog.eye.findData('left'))
    assert not dialog.save_to(tmp_path/'missing') and window.case_metadata==original
    assert dialog.save_to(tmp_path) and window.case_metadata.case_id=='SAVED-001'
    assert window.analysis.context is context and window.analysis.current_run is None
    window.load_image(image_file('second.png'))
    assert window.case_metadata.case_id!='SAVED-001' and window.case_metadata.eye=='unspecified'
    dialog=window.edit_case();window.clear_image()
    assert window.case_metadata is None and not dialog.isVisible()
    window.close()


def test_background_history_filter_cancel_preserves_and_close(qtbot,completed,tmp_path,monkeypatch):
    context,run=completed
    export_bundle(ExportSnapshot.capture(context,run,case_for(context)),tmp_path)
    window=MainWindow();qtbot.addWidget(window);dialog=window.open_history()
    assert dialog.load_root(tmp_path)
    qtbot.waitUntil(lambda:not dialog.scanner.busy,timeout=5000)
    assert dialog.table.rowCount()==1
    dialog.search.setText('no-match');assert dialog.table.rowCount()==0
    dialog.search.setText('research');assert dialog.table.rowCount()==1
    import rop_insight.ui.history_dialog as ui
    entered=Event()
    def blocking(root,cancel):
        entered.set();cancel.wait(3);raise InterruptedError('cancelled')
    monkeypatch.setattr(ui,'scan_history',blocking)
    dialog.load_root(tmp_path);qtbot.waitUntil(entered.is_set,timeout=3000)
    window.show();window.close()
    assert window._closing
    qtbot.waitUntil(lambda:not dialog.scanner.busy,timeout=5000)
    assert not window.isVisible() and len(dialog.records)==1

@pytest.mark.parametrize('field,value',[('revision_id',None),('previous_revision_id','same')])
def test_invalid_revision_chain(completed,field,value):
    case=case_for(completed[0])
    if value=='same':value=case.revision_id
    with pytest.raises(ValueError):replace(case,**{field:value}).validated()


@pytest.mark.parametrize('name',['../x','C:\\data.pdf','https://x','file:///x','..','a/b','a\\b'])
def test_unsafe_artifact_names(tmp_path,name):
    with pytest.raises(ValueError):history.safe_file(tmp_path,name)


def test_external_link_artifact_rejected(tmp_path):
    import os
    import subprocess
    real=tmp_path/'outside';real.mkdir();(real/'private').write_text('outside')
    folder=tmp_path/'bundle';folder.mkdir();link=folder/'linked'
    try:link.symlink_to(real,target_is_directory=True)
    except OSError:
        subprocess.run(['powershell','-NoProfile','-Command',
            'New-Item -ItemType Junction -Path $env:ROP_TEST_LINK -Target $env:ROP_TEST_TARGET | Out-Null'],
            env={**os.environ,'ROP_TEST_LINK':str(link),'ROP_TEST_TARGET':str(real)},check=True,capture_output=True)
    try:
        with pytest.raises(ValueError):history.safe_file(folder,'linked')
        assert history.scan_history(folder)==[]
    finally:
        if link.is_symlink():link.unlink()
        else:link.rmdir()
    assert (real/'private').read_text()=='outside'


def test_declared_mask_not_in_manifest_is_invalid(completed,tmp_path):
    context,run=completed;folder=export_bundle(ExportSnapshot.capture(context,run),tmp_path)
    path=folder/'result.json';data=json.loads(path.read_text(encoding='utf-8'))
    data['modules']['ridge']=dict(state='success',masks=['ridge_mask.png'])
    path.write_text(json.dumps(data),encoding='utf-8')
    assert history.inspect_bundle(folder).issues


def test_report_integrity_and_stale_open(completed,tmp_path,qapp):
    context,run=completed
    folder=export_report_bundle(build_report(ExportSnapshot.capture(context,run,case_for(context))),tmp_path)
    record=history.inspect_bundle(folder);assert not record.issues
    pdf=folder/'report.pdf';pdf.write_bytes(pdf.read_bytes()+b'changed')
    assert history.inspect_bundle(folder).issues
    with pytest.raises(ValueError):history.verified_artifact(record,'report.pdf')
    # Even a new matching file hash cannot silently replace the snapshot selected in the table.
    manifest_path=folder/'report_manifest.json';manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest['artifacts']['report.pdf']=dict(sha256=history.digest(pdf),bytes=pdf.stat().st_size)
    manifest_path.write_text(json.dumps(manifest),encoding='utf-8')
    assert not history.inspect_bundle(folder).issues
    with pytest.raises(ValueError):history.verified_artifact(record,'report.pdf')
    manifest['run_id']='different-run';manifest_path.write_text(json.dumps(manifest),encoding='utf-8')
    assert history.inspect_bundle(folder).issues


def test_long_case_notes_keep_full_detail_and_old_snapshot(completed):
    context,run=completed;case=case_for(context)
    notes='中文研究备注'*300
    case=case.revised(case.case_id,'left','','BEGIN'+notes+'END')
    report=build_report(ExportSnapshot.capture(context,run,case))
    assert '完整备注见详细报告' in render_text(report,False)
    assert notes in render_text(report) and 'END' in render_text(report)
    case=case.revised('NEW','right','','new')
    assert report.data['case_metadata']['case_id']=='RESEARCH-001'


def test_background_input_check_closes_safely(qtbot,completed,tmp_path,monkeypatch):
    context,run=completed
    folder=export_bundle(ExportSnapshot.capture(context,run),tmp_path)
    window=MainWindow();qtbot.addWidget(window);dialog=window.open_history()
    dialog.records=[history.inspect_bundle(folder)];dialog.populate();dialog.table.selectRow(0)
    import rop_insight.ui.history_dialog as ui
    monkeypatch.setattr(ui.QFileDialog,'getOpenFileName',lambda *args:(context.source,''))
    entered=Event()
    def blocking(record,path,cancel):
        entered.set();cancel.wait(3);raise InterruptedError('cancelled')
    monkeypatch.setattr(ui,'verify_input',blocking)
    dialog.check_input();qtbot.waitUntil(entered.is_set,timeout=3000)
    window.show();window.close()
    qtbot.waitUntil(lambda:not dialog.busy,timeout=5000)
    assert not window.isVisible()


def test_long_notes_flow_across_pdf_pages_without_blank_gap(completed,tmp_path,qapp):
    from PyQt6.QtPdf import QPdfDocument
    context,run=completed;case=case_for(context)
    notes='\n'.join(f'备注{i:02d}：用于验证中文长备注分页及文字完整性。' for i in range(35))
    case=case.revised(case.case_id,'left','','BEGIN-NOTES\n'+notes+'\nEND-NOTES')
    report=build_report(ExportSnapshot.capture(context,run,case))
    folder=export_report_bundle(report,tmp_path)
    pdf=QPdfDocument(None);assert pdf.load(str(folder/'report.pdf'))==QPdfDocument.Error.None_
    assert '备注00' in pdf.getAllText(0).text()
    text=''.join(pdf.getAllText(i).text() for i in range(pdf.pageCount()))
    assert all(f'备注{i:02d}' in text for i in range(35)) and text.count('BEGIN-NOTES')==text.count('END-NOTES')==1
    pdf.close()


def test_history_reopen_verification_cancels_on_close(qtbot,completed,tmp_path,monkeypatch):
    context,run=completed
    folder=export_bundle(ExportSnapshot.capture(context,run),tmp_path)
    window=MainWindow();qtbot.addWidget(window);dialog=window.open_history()
    dialog.records=[history.inspect_bundle(folder)];dialog.populate();dialog.table.selectRow(0)
    import rop_insight.ui.history_dialog as ui
    entered=Event()
    def blocking(record,name,cancel):
        entered.set();cancel.wait(3);raise InterruptedError('cancelled')
    monkeypatch.setattr(ui,'verified_artifact',blocking)
    dialog.open_saved('report.pdf');qtbot.waitUntil(entered.is_set,timeout=3000)
    window.show();window.close()
    qtbot.waitUntil(lambda:not dialog.busy,timeout=5000)
    assert not window.isVisible() and not dialog.pdf_windows


def test_repeated_pdf_window_release_and_collection(qtbot,completed,tmp_path):
    import gc
    from PyQt6.QtCore import QCoreApplication,QEvent
    from PyQt6.QtPdf import QPdfDocument
    from rop_insight.ui.history_dialog import HistoryDialog
    context,run=completed
    folder=export_report_bundle(build_report(ExportSnapshot.capture(context,run)),tmp_path)
    for _ in range(4):
        dialog=HistoryDialog();dialog.records=[history.inspect_bundle(folder)];dialog.populate();dialog.table.selectRow(0)
        dialog.open_pdf();qtbot.waitUntil(lambda:not dialog.busy,timeout=5000)
        pdf_window=dialog.pdf_windows[0]
        dialog.close()
        assert pdf_window.view.document() is None
        assert pdf_window.pdf.status()==QPdfDocument.Status.Null
        dialog.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        del dialog,pdf_window
        gc.collect()
