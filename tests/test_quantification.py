import json
from pathlib import Path
from types import SimpleNamespace
from PyQt6.QtGui import QImage
import pytest

from rop_insight.inference.quantification import QuantificationAdapter
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
