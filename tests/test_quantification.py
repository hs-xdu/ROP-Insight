import json
from pathlib import Path
from types import SimpleNamespace
from PyQt6.QtGui import QImage
import pytest

from rop_insight.inference.quantification import QuantificationAdapter, validate_score
from rop_insight.inference.quantification_backend import definitions, FEATURES
from rop_insight.models.analysis_result import AnalysisOutput, AnalysisRun, ModuleResult, ModuleState, MaskData
from rop_insight.ui.result_panel import ResultPanel


def test_selected_functions_do_not_execute_script_side_effects(tmp_path):
    source = tmp_path / "original.py"
    source.write_text("raise RuntimeError('script must not run')\ndef feature(x):\n return x*2\n")
    namespace = {}
    definitions(source, ["feature"], namespace)
    assert namespace['feature'](3) == 6
    with pytest.raises(ValueError):
        definitions(source, ["missing"], {})


def test_native_artifacts_required(tmp_path):
    masks = {name: AnalysisOutput({}, (MaskData(name, 2, 2, b'\x00'*4),)) for name in ['ridge','vessel']}
    with pytest.raises(ValueError, match="原生"):
        QuantificationAdapter().make_request(tmp_path, SimpleNamespace(model_source='test',source_hashes={}), masks)


def test_metric_values_units_and_unavailable_render(qtbot):
    panel = ResultPanel();qtbot.addWidget(panel)
    metrics = {name: {'value': None if name.startswith('ridge') else .12,
        'unit':'无量纲','status':'unavailable' if name.startswith('ridge') else 'available',
        'reason':'Ridge为空' if name.startswith('ridge') else None,'grid':512} for name in FEATURES}
    run=AnalysisRun('run','image',None,{'quantification':ModuleResult('quantification',
        state=ModuleState.SUCCESS,output=AnalysisOutput({'metrics':metrics}))})
    panel.show_run(run)
    assert 'Ridge为空' in panel.metrics_label.text()
    assert '0.12' in panel.metrics_label.text()
    panel.reset()
    assert panel.metrics_label.text()=='量化指标：未提供'


def test_invalid_quantification_response_rejected(tmp_path):
    path=tmp_path/'result.json'
    path.write_text(json.dumps({'metrics':{}}))
    with pytest.raises(ValueError,match='缺少'):
        QuantificationAdapter().read_output(tmp_path,None)
    metrics={name:{'value':None,'status':'unavailable','reason':None,'unit':'fraction','grid':512} for name in FEATURES}
    path.write_text(json.dumps({'metrics':metrics}))
    with pytest.raises(ValueError,match='原因'):
        QuantificationAdapter().read_output(tmp_path,None)


@pytest.mark.parametrize('change', [dict(lower=4), dict(median=float('nan')),
    dict(ci95_width=-1), dict(status='unknown')])
def test_invalid_score_rejected(change):
    score=dict(status='available',lower=1.,median=2.,upper=3.,ci95_width=2.)
    score.update(change)
    with pytest.raises(ValueError):
        validate_score(score)


def test_score_quality_failure_cannot_publish_a_value():
    validate_score(dict(status='unavailable',reason='有效血管段不足',median=None))
    with pytest.raises(ValueError):
        validate_score(dict(status='unavailable',reason='有效血管段不足',median=0.))


def test_score_and_auxiliary_are_independent_of_deep_prediction(qtbot):
    from rop_insight.models.analysis_result import ClassificationData
    panel=ResultPanel(); qtbot.addWidget(panel)
    run=AnalysisRun('run','image',None,{
        'quantification':ModuleResult('quantification',state=ModuleState.SUCCESS,
            output=AnalysisOutput({'score':dict(status='available',lower=1.,median=2.,upper=3.),
                'auxiliary_classification':dict(status='available',prediction='Stage 3')})),
        'staging':ModuleResult('staging',state=ModuleState.SUCCESS,
            output=AnalysisOutput({},classification=ClassificationData((1.,0.,0.,0.))))})
    panel.show_run(run)
    assert '95%后验区间：[1, 3]' in panel.score_label.text()
    assert 'Stage 3' in panel.auxiliary_label.text()
    assert 'Normal' in panel.prediction.text()
    panel.reset()
    assert '未提供' in panel.score_label.text()
    assert '未提供' in panel.auxiliary_label.text()


def test_unavailable_score_and_auxiliary_show_reasons(qtbot):
    panel=ResultPanel(); qtbot.addWidget(panel)
    run=AnalysisRun('run','image',None,{'quantification':ModuleResult('quantification',state=ModuleState.SUCCESS,
        output=AnalysisOutput({'score':dict(status='unavailable',reason='有效血管段不足'),
            'auxiliary_classification':dict(status='unavailable',reason='评分未通过质量检查')}))})
    panel.show_run(run)
    assert '有效血管段不足' in panel.score_label.text()
    assert '评分未通过质量检查' in panel.auxiliary_label.text()
    panel.show_run(AnalysisRun('new','image',None,{}))
    assert '未提供' in panel.score_label.text()
    assert '未提供' in panel.auxiliary_label.text()


def test_feature_vector_must_match_displayed_score_and_metrics(tmp_path):
    data=dict(metrics={name:dict(value=2.,unit='u',grid=512,status='available') for name in FEATURES},
        score=dict(status='available',lower=1.,median=2.,upper=3.,ci95_width=2.),
        feature_values=dict.fromkeys((*FEATURES,'T1'),2.))
    path=tmp_path/'result.json'
    path.write_text(json.dumps(data))
    assert QuantificationAdapter().read_output(tmp_path,None).values['score']['median']==2.
    data['feature_values']['T3']=0.
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='不一致'):
        QuantificationAdapter().read_output(tmp_path,None)
