"""Independent frozen structural classifier; never supplies A6 probabilities."""

import json
from pathlib import Path
from PyQt6.QtCore import QStandardPaths
from rop_insight.inference.vascx import VascXAdapter
from rop_insight.models.analysis_result import AnalysisOutput

LABELS = ('Normal', 'Stage 1', 'Stage 2', 'Stage 3')


class FrozenSVMAdapter(VascXAdapter):
    supported_devices = ('cpu',)
    backend_filename = 'svm_backend.py'
    display_name = 'RBF-SVM 辅助分类'

    def execute(self, image, upstream, config, cancel):
        root = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
        return self._execute(image, config, cancel, root / 'svm_runs', upstream)

    def make_request(self, folder, config, upstream):
        values = upstream['quantification'].values
        if not isinstance(values.get('feature_values'), dict):
            raise ValueError('辅助分类缺少原量化特征')
        return dict(feature_values=values['feature_values'], score=values.get('score'),
                    model_source=config.model_source, source_hashes=config.source_hashes)

    def read_output(self, folder, image):
        data = json.loads((folder / 'result.json').read_text(encoding='utf-8'))
        auxiliary = data.get('auxiliary_classification', {})
        if auxiliary.get('status') == 'available':
            if auxiliary.get('prediction') not in LABELS or auxiliary.get('probabilities') is not None:
                raise ValueError('SVM 类别无效或包含未经校准的概率')
        elif auxiliary.get('status') != 'unavailable' or not auxiliary.get('reason'):
            raise ValueError('SVM 不可用原因缺失')
        data['artifacts_dir'] = str(folder)
        return AnalysisOutput(data)
