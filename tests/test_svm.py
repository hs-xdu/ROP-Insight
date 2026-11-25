import json
import math
from types import SimpleNamespace
import pytest
from rop_insight.inference.svm import FrozenSVMAdapter
from rop_insight.inference.svm_backend import FEATURES, predict_frozen
from rop_insight.models.analysis_result import AnalysisOutput


def test_frozen_order_and_training_imputer_only():
    observed = {}
    class Vector(list):
        def tolist(self):
            return list(self)
    def frame(rows, columns):
        observed.update(rows=rows, columns=columns)
        return rows
    class Preprocessor:
        def transform(self, rows):
            return [Vector([42 if math.isnan(v) else v for v in rows[0]])]
    class Model:
        feature_names_in_ = FEATURES
        named_steps = {'preprocess': Preprocessor()}
        def predict(self, X):
            return ['Stage2']
    values = dict.fromkeys(FEATURES, 1.)
    values['ridge_solidity'] = None
    result = predict_frozen(Model(), list(FEATURES), values, frame)
    assert observed['columns'] == list(FEATURES)
    assert math.isnan(observed['rows'][0][7])
    assert result['transformed_values'][7] == 42
    assert result['prediction'] == 'Stage 2'
    assert result['probabilities'] is None
    with pytest.raises(ValueError, match='顺序'):
        predict_frozen(Model(), list(reversed(FEATURES)), values, frame)
    del values['T1']
    with pytest.raises(ValueError, match='缺少'):
        predict_frozen(Model(), FEATURES, values, frame)


def test_requires_quantification_features(tmp_path):
    with pytest.raises(ValueError, match='特征'):
        FrozenSVMAdapter().make_request(tmp_path, None, {'quantification':AnalysisOutput({})})


@pytest.mark.parametrize('value', [dict(status='available',prediction='Stage 2',probabilities=[.1,.2,.6,.1]),
    dict(status='available',prediction='Unknown'), dict(status='unavailable')])
def test_invalid_auxiliary_rejected(tmp_path,value):
    (tmp_path/'result.json').write_text(json.dumps({'auxiliary_classification':value}))
    with pytest.raises(ValueError):
        FrozenSVMAdapter().read_output(tmp_path,None)


def test_auxiliary_does_not_replace_deep_classification(tmp_path):
    (tmp_path/'result.json').write_text(json.dumps({'auxiliary_classification':dict(status='available',prediction='Stage 2',probabilities=None)}))
    result=FrozenSVMAdapter().read_output(tmp_path,None)
    assert result.classification is None
    assert result.values['auxiliary_classification']['prediction']=='Stage 2'
