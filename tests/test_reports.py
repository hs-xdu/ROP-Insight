from copy import deepcopy
import hashlib
import json
import re
from pathlib import Path
from threading import Event

import pytest
from PyQt6.QtGui import QImage
from rop_insight.inference.svm_backend import FEATURES
from rop_insight.models.analysis_result import (AnalysisOutput,ClassificationData,ModuleState,
    ImageContext,AnalysisRun,ModuleResult,MaskData)
from rop_insight.services.analysis_config import AnalysisConfig,ModuleConfig
from rop_insight.services.image_loader import ImageLoader
from rop_insight.services.report_builder import build_report,report_from_result,snapshot_result
from rop_insight.services.report_template import render_html,render_text,number
from rop_insight.services import report_exporter
from rop_insight.services.result_exporter import ExportSnapshot,export_bundle
from rop_insight.ui.main_window import MainWindow


@pytest.fixture
def report_source():
    feature_values={name:1.2345678901234567 for name in FEATURES}
    metrics={name:dict(value=value,unit='无量纲',grid=1024 if name in ('T3','B3','S_median') else 512,status='available',reason=None)
             for name,value in feature_values.items() if name!='T1'}
    def module(adapter,values=None):
        return dict(state='success',enabled=True,adapter_id=adapter,model_version='test_v1',device='cpu',
            weights_sha256='a'*64,dependencies=[],source_hashes={},preprocessing={},postprocessing={},masks=[],values=values or {})
    modules=dict(ridge=module('imported_ridge',{'source':'user_imported_ridge'}),vessel=module('vascx_native'),
        staging=module('a6_shenzhen'),quantification=module('chapter5_quant',dict(metrics=metrics,feature_values=feature_values,
            score=dict(status='available',median=feature_values['S_median'],lower=1.,upper=2.,ci95_width=1.,valid_segments=12))),
        auxiliary=module('chapter5_svm',dict(auxiliary_classification=dict(status='available',prediction='Stage 2',
            probabilities=None,probability_calibrated=False))))
    modules['ridge']['masks']=['ridge_mask.png'];modules['vessel']['masks']=['vessel_mask.png']
    modules['staging']['deep_classification']=dict(classes=['Normal','Stage 1','Stage 2','Stage 3'],
        probabilities=[.1,.2,.3,.4],prediction='Stage 3')
    return dict(schema_version=1,image=dict(image_id='image-test',width=12,height=8,format='PNG',file_sha256='b'*64,rgb_pixel_sha256='c'*64),
        run=dict(run_id='run-test',status='success',started_at='2026-11-25T00:00:00+00:00',finished_at='2026-11-25T00:01:00+00:00',
            software_version='test',code_revision='d'*40,code_dirty=False),modules=modules)


def test_all_report_values_keep_precision_and_independent_sources(report_source):
    before=deepcopy(report_source)
    report=report_from_result(report_source)
    data=report.data
    assert [f['key'] for f in data['features']]==list(FEATURES)
    assert data['features'][3]['grid']==1024
    assert data['features'][3]['value']==report_source['modules']['quantification']['values']['feature_values']['T1']
    assert data['a6']['prediction']=='Stage 3'
    assert data['svm']['prediction']=='Stage 2' and data['svm']['probabilities'] is None
    assert data['structures'][0]['source']=='用户导入'
    assert data['score']['median']==1.2345678901234567
    assert report_source==before
    data['a6']['prediction']='changed'
    assert report.data['a6']['prediction']=='Stage 3'


@pytest.mark.parametrize('state',['failed','skipped','cancelled'])
def test_failed_module_never_publishes_stale_success(report_source,state):
    report_source['run']['status']='partial_success'
    for name in ('staging','quantification','auxiliary'):report_source['modules'][name]['state']=state
    data=report_from_result(report_source).data
    assert data['a6']['probabilities'] is None
    assert all(item['value'] is None for item in data['features'])
    assert data['score']['median'] is None and data['svm']['prediction'] is None
    text=render_text(report_from_result(report_source))
    assert '报告包含未完成模块' in text and '常见范围' not in text


@pytest.mark.parametrize('value',[None,float('nan'),float('inf'),float('-inf'),True])
def test_missing_and_nonfinite_values_are_not_zero_or_normal(report_source,value):
    quant=report_source['modules']['quantification']['values']
    quant['feature_values']['T1']=value
    quant['metrics']['T3']['value']=value
    quant['score']['median']=value
    data=report_from_result(report_source).data
    assert data['features'][3]['value'] is None
    assert next(f for f in data['features'] if f['key']=='T3')['value'] is None
    assert data['score']['status']=='unavailable'
    assert all(term not in render_text(report_from_result(report_source)) for term in ('大致处于常见范围','plus样','综合印象'))


def test_html_escaping_paths_and_shared_preview_sections(report_source):
    report_source['modules']['staging']['model_version']='<b>中文&</b>'
    report_source['modules']['quantification']['values']['metrics']['T3'].update(value=None,status='unavailable',reason='<script>alert(1)</script>')
    report_source['modules']['vessel']['values']['artifacts_dir']=r'E:\private\patient'
    report=report_from_result(report_source)
    html=render_html(report);text=render_text(report)
    assert '<script>' not in html and '<img src=' not in html
    assert '&lt;script&gt;' in html and '&lt;b&gt;' in html
    assert 'private' not in report.payload_json
    for term in ('A6分期模型结果','连续评分与后验区间','SVM结构辅助分类','结果限制说明','版本与来源追溯'):
        assert term in html and term in text
    assert '固定11项特征' in render_text(report,False)


@pytest.mark.parametrize('change',[dict(schema_version=2),dict(run=dict(run_id='run',status='running',finished_at=None)),
    dict(modules={'pending':dict(state='pending')})])
def test_invalid_or_unfinished_analysis_rejected(report_source,change):
    report_source.update(change)
    with pytest.raises(ValueError):report_from_result(report_source)


def test_conflicting_sources_and_uncalibrated_probabilities_rejected(report_source):
    report_source['modules']['other_a6']=deepcopy(report_source['modules']['staging'])
    report_source['modules']['auxiliary']['values']['auxiliary_classification']['probabilities']=[.1,.2,.3,.4]
    data=report_from_result(report_source).data
    assert data['a6']['status']=='unavailable' and data['svm']['status']=='unavailable'


def test_pdf_content_roundtrip_and_atomic_manifest(report_source,tmp_path,qtbot):
    report=report_from_result(report_source)
    folder=report_exporter.export_report_bundle(report,tmp_path)
    pages,text=report_exporter.pdf_text(folder/'report.pdf')
    assert pages>=2
    normalized=''.join(text.split())
    for term in ('血管迂曲指数T1','95%后验区间','SVM辅助类别：Stage2','不是临床诊断',number(report.data['score']['median'])):
        assert ''.join(term.split()) in normalized
    assert (folder/'report_detail.txt').read_text(encoding='utf-8')==render_text(report)
    assert json.loads((folder/'report.json').read_text(encoding='utf-8'))==report.data
    manifest=json.loads((folder/'report_manifest.json').read_text(encoding='utf-8'))
    assert manifest['run_id']=='run-test' and manifest['input_file_sha256']=='b'*64
    for name,item in manifest['artifacts'].items():
        assert hashlib.sha256((folder/name).read_bytes()).hexdigest()==item['sha256']
    again=report_exporter.export_report_bundle(report,tmp_path)
    assert folder!=again and (folder/'report.pdf').is_file()


def test_long_chinese_unavailable_reasons_paginate_without_dropping_text(report_source,tmp_path,qtbot):
    quant=report_source['modules']['quantification']['values']
    reason='长文本核对：该指标缺失，应结合本次模块状态查看。'*12
    for metric in quant['metrics'].values():metric.update(value=None,status='unavailable',reason=reason)
    quant['feature_values']['T1']=None
    quant['score']=dict(status='unavailable',reason='有效血管段不足',median=None,lower=None,upper=None,ci95_width=None)
    report_source['modules']['auxiliary']['values']['auxiliary_classification']=dict(status='unavailable',reason='评分未通过质量规则')
    report=report_from_result(report_source)
    folder=report_exporter.export_report_bundle(report,tmp_path)
    pages,text=report_exporter.pdf_text(folder/'report.pdf')
    compact=''.join(text.split())
    assert pages>=3
    assert compact.count('长文本核对')==render_text(report).count('长文本核对')
    assert 'SVM结果不可用' in compact and '版本与来源追溯' in compact
    from PyQt6.QtPdf import QPdfDocument
    pdf=QPdfDocument(None)
    try:
        pdf.load(str(folder/'report.pdf'))
        svm_pages=[''.join(pdf.getAllText(i).text().split()) for i in range(pdf.pageCount())
                   if 'SVM结构辅助分类' in ''.join(pdf.getAllText(i).text().split())]
        assert len(svm_pages)==1 and '未经概率校准' in svm_pages[0]
    finally:pdf.close()


@pytest.mark.parametrize('failure',['pdf','json','publish','collision'])
def test_report_write_failure_publishes_nothing(report_source,tmp_path,monkeypatch,failure,qtbot):
    def fail(*args,**kwargs):raise OSError('disk full')
    if failure=='pdf':monkeypatch.setattr(report_exporter,'write_pdf',fail)
    elif failure=='json':monkeypatch.setattr(report_exporter,'_write_text',fail)
    elif failure=='publish':monkeypatch.setattr(report_exporter.os,'rename',fail)
    else:
        class Fixed:
            hex='fixed'
        monkeypatch.setattr(report_exporter,'uuid4',Fixed)
        (tmp_path/'rop-report-fixed').mkdir()
        (tmp_path/'rop-report-fixed/keep.txt').write_text('keep')
    before=set(tmp_path.iterdir())
    with pytest.raises(OSError):report_exporter.export_report_bundle(report_from_result(report_source),tmp_path)
    assert set(tmp_path.iterdir())==before


def _live_result(source,image_file):
    document=ImageLoader().load(image_file('synthetic_report.png',12,8))
    context=ImageContext.from_document(document)
    configs=[];modules={}
    for name,item in source['modules'].items():
        configs.append(ModuleConfig(module_id=name,enabled=True,adapter_id=item['adapter_id'],device='cpu',
            model_version=item['model_version'],weights_sha256=item['weights_sha256']))
        masks=tuple(MaskData(name,12,8,b'\0'*95+b'\1') for f in item['masks'])
        classification=ClassificationData(tuple(item['deep_classification']['probabilities'])) if 'deep_classification' in item else None
        modules[name]=ModuleResult(name,ModuleState.SUCCESS,output=AnalysisOutput(deepcopy(item['values']),masks,classification),model_version=item['model_version'])
    run=AnalysisRun('live-run',context.image_id,AnalysisConfig(tuple(configs)),modules,status='success',finished_at='done')
    return context,run


def test_live_snapshot_matches_p4_json_and_survives_clear(report_source,image_file,tmp_path,qtbot,monkeypatch):
    context,run=_live_result(report_source,image_file)
    snapshot=ExportSnapshot.capture(context,run)
    live=build_report(snapshot)
    folder=export_bundle(snapshot,tmp_path)
    saved=report_from_result(json.loads((folder/'result.json').read_text(encoding='utf-8')))
    assert live.data['source_snapshot_sha256']==saved.data['source_snapshot_sha256']
    assert live.data['features']==saved.data['features']
    window=MainWindow();qtbot.addWidget(window);window.show()
    assert not window.report_button.isEnabled()
    window.analysis.context=context;window.analysis.current_run=run;window._update_analysis()
    assert window.report_button.isEnabled()
    dialog=window.preview_report()
    assert dialog is not None and dialog.isVisible()
    assert '固定11项' in dialog.browsers[1].toPlainText()
    assert not dialog.browsers[1].openExternalLinks()
    before=dialog.report.payload_json
    window.clear_image()
    assert not dialog.isVisible() and not window.report_button.isEnabled()
    assert dialog.report.payload_json==before


def test_report_export_thread_failure_retry_and_close(report_source,image_file,tmp_path,qtbot):
    context,run=_live_result(report_source,image_file)
    window=MainWindow();qtbot.addWidget(window);window.show()
    window.analysis.context=context;window.analysis.current_run=run;window._update_analysis()
    dialog=window.preview_report()
    def fail(*args):raise OSError('failure')
    window.report_exporter.job=fail
    with qtbot.waitSignal(window.report_exporter.finished):assert dialog.export_to(tmp_path)
    assert '导出失败' in dialog.status.text() and dialog.export_button.isEnabled()
    entered,release=Event(),Event()
    def slow(report,parent):
        entered.set();release.wait(5)
        return report_exporter.export_report_bundle(report,parent)
    window.report_exporter.job=slow
    assert dialog.export_to(tmp_path)
    qtbot.waitUntil(entered.is_set)
    window.close();assert window.isVisible() and not window.report_button.isEnabled()
    release.set()
    qtbot.waitUntil(lambda:not window.report_exporter.busy and not window.isVisible(),timeout=10000)
    assert len(list(tmp_path.glob('rop-report-*/report.pdf')))==1


def test_shared_feature_descriptions_are_limited_to_three_and_do_not_grade(report_source):
    before=deepcopy(report_source)
    report=report_from_result(report_source)
    description=report.data['feature_descriptions']
    assert report.data['template_version']=='p5-factual-3'
    assert [item['key'] for item in description['items']]==[
        'vessel_area_density_fov','fractal_dimension','sliding_window_max_density_gradient']
    assert description['grading_applied'] is False
    assert all(item['grade'] is None and item['reference_interval'] is None for item in description['items'])
    assert report_source==before
    for item in description['items']:
        assert item['value']==before['modules']['quantification']['values']['metrics'][item['key']]['value']
        assert item['explanation'] and item['review_hint'] and item['grid']==512
    for detailed in (True,False):
        assert '血管量化文字摘要' in render_text(report,detailed)
        assert '整体血管覆盖方面' in render_html(report,detailed)
        assert '血管网络形态复杂程度方面' in render_text(report,detailed)
    assert '重合指标分项说明' in render_text(report)
    assert '重合指标分项说明' not in render_text(report,False)


@pytest.mark.parametrize('value',[None,float('nan'),float('inf'),float('-inf'),True])
def test_shared_description_missing_values_do_not_produce_morphology(report_source,value):
    metrics=report_source['modules']['quantification']['values']['metrics']
    for key in ('vessel_area_density_fov','fractal_dimension','sliding_window_max_density_gradient'):
        metrics[key]['value']=value
    report=report_from_result(report_source)
    for item in report.data['feature_descriptions']['items']:
        assert item['status']=='unavailable' and item['value'] is None
    summary=render_text(report,False)
    assert summary.count('本次不作对应形态描述')==3
    assert '为0（' not in summary


def test_shared_description_zero_is_valid_and_reasons_are_escaped(report_source):
    metrics=report_source['modules']['quantification']['values']['metrics']
    metrics['vessel_area_density_fov']['value']=0.
    metrics['fractal_dimension'].update(value=None,status='unavailable',reason='<script>缺失原因</script>')
    report=report_from_result(report_source)
    assert report.data['feature_descriptions']['items'][0]['status']=='available'
    assert '血管密度 VD为0（512网格）' in render_text(report,False)
    for detailed in (True,False):
        html=render_html(report,detailed)
        assert '<script>' not in html
        if detailed:assert '&lt;script&gt;缺失原因&lt;/script&gt;' in html
        else:assert '具体不可用原因见详细报告' in html


def test_shared_descriptions_survive_pdf_and_source_precision_is_preserved(report_source,tmp_path,qtbot):
    report=report_from_result(report_source)
    folder=report_exporter.export_report_bundle(report,tmp_path)
    _,text=report_exporter.pdf_text(folder/'report.pdf')
    compact=''.join(text.split())
    for term in ('血管量化文字摘要','重合指标分项说明','整体血管覆盖方面','形态复杂性','分割连续性','指标文字规则版本'):
        assert term in compact
    saved=json.loads((folder/'report.json').read_text(encoding='utf-8'))
    assert saved['feature_descriptions']==report.data['feature_descriptions']
    assert saved['features']==report.data['features']
    assert saved['feature_descriptions']['items'][0]['value']==1.2345678901234567


def test_oversized_reason_row_preserves_every_line_across_pages(report_source,tmp_path,qtbot):
    metric=report_source['modules']['quantification']['values']['metrics']['sliding_window_max_density_gradient']
    metric.update(value=None,status='unavailable',reason='超长原因校验。'*800)
    report=report_from_result(report_source)
    folder=report_exporter.export_report_bundle(report,tmp_path)
    pages,text=report_exporter.pdf_text(folder/'report.pdf')
    # A marker may wrap between pages, with the known footer/header inserted
    # between its characters in extracted text. Compare the body without them.
    text=re.sub(r'ROP-Insight\s*\|\s*研究辅助分析报告','',text)
    text=re.sub(r'研究用途\s*-\s*非临床诊断\s*第\s*\d+\s*/\s*\d+\s*页','',text)
    compact=''.join(text.split()).replace('指标数值/状态单位网格','')
    assert pages>3
    assert compact.count('超长原因校验')==render_text(report).count('超长原因校验')
    assert '版本与来源追溯' in compact and report.data['source']['image']['file_sha256'] in compact
