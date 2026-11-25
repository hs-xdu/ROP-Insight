"""Load only hash-locked research artifacts in their original environment."""

import hashlib
import json
from pathlib import Path
import sys


FEATURES = ('fractal_dimension', 'vessel_area_density_fov', 'sliding_window_max_density_gradient',
            'T1', 'T3', 'B3', 'ridge_area_ratio_fov', 'ridge_solidity',
            'ridge_outer_vessel_density', 'ridge_max_radius_ratio', 'S_median')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def predict_frozen(model, features, values, frame):
    if tuple(features) != FEATURES or tuple(model.feature_names_in_) != tuple(features):
        raise ValueError('冻结模型特征顺序与清单不一致')
    if set(features) - values.keys():
        raise ValueError('缺少原始特征，不允许隐式补零')
    row = [float('nan') if values[name] is None else values[name] for name in features]
    X = frame([row], columns=features)
    transformed = model.named_steps['preprocess'].transform(X)
    prediction = str(model.predict(X)[0])
    labels = {'Normal':'Normal','Stage1':'Stage 1','Stage2':'Stage 2','Stage3':'Stage 3'}
    if prediction not in labels:
        raise ValueError('冻结模型类别无效')
    return dict(status='available', prediction=labels[prediction], probabilities=None,
                features=list(features), input_values=[values[name] for name in features],
                transformed_values=transformed[0].tolist(),
                missing_rule='frozen training median imputer', probability_calibrated=False)


def run(request):
    import joblib
    import numpy as np
    import pandas as pd
    import scipy
    import sklearn
    root = Path(request['model_source'])
    required = ('RBF_SVM_final_lock.json', 'protocol_lock.json', 'experiment_summary.json')
    if any(name not in request['source_hashes'] for name in required):
        raise ValueError('必须锁定模型清单及原环境记录')
    for name, expected in request['source_hashes'].items():
        if digest(root / name) != expected:
            raise ValueError('SVM 来源工件哈希不一致')
    model_path = Path(request['weights_path'])
    if digest(model_path) != request['weights_sha256']:
        raise ValueError('SVM 模型哈希不一致')
    protocol = json.loads((root / 'protocol_lock.json').read_text(encoding='utf-8'))
    environment = protocol['environment']
    actual = dict(numpy=np.__version__, pandas=pd.__version__, scipy=scipy.__version__, sklearn=sklearn.__version__)
    if any(environment.get(name) != value for name, value in actual.items()) or not environment['python'].startswith(sys.version.split()[0] + ' '):
        raise ValueError('SVM 环境版本与原实验不一致')
    lock = json.loads((root / 'RBF_SVM_final_lock.json').read_text(encoding='utf-8'))
    summary = json.loads((root / 'experiment_summary.json').read_text(encoding='utf-8'))
    record = next(item for item in summary['final_models'] if item['family'] == 'RBF_SVM')
    if tuple(lock['features']) != FEATURES or lock['features'] != record['features'] or record['final_model_sha256'] != request['weights_sha256']:
        raise ValueError('冻结 SVM 清单与模型不一致')
    if (request.get('score') or {}).get('status') != 'available':
        auxiliary = dict(status='unavailable', reason='连续评分未通过原质量规则，暂停辅助分类')
    else:
        # Loading pickle/joblib happens only after verifying trusted artifact hashes.
        model = joblib.load(model_path)
        classifier = model.named_steps['model']
        # sklearn 1.9 uses the truthy default sentinel 'deprecated' for probability.
        if classifier.kernel != 'rbf' or classifier.probability not in (False, 'deprecated'):
            raise ValueError('工件不是约定的未校准 RBF-SVM')
        auxiliary = predict_frozen(model, lock['features'], request['feature_values'], pd.DataFrame)
        if not np.isfinite(auxiliary['transformed_values']).all():
            raise ValueError('冻结预处理输出非有限值')
    result = dict(auxiliary_classification=auxiliary, model_sha256=request['weights_sha256'],
                  model_version=request['model_version'], source_hashes=request['source_hashes'], environment=actual)
    (Path(request['output_dir']) / 'result.json').write_text(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    run(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')))
