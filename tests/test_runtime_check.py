import json
import hashlib
from rop_insight.services.runtime_check import check_runtime


def test_read_only_check_detects_missing_and_changed_artifacts(tmp_path):
    weights=tmp_path/'weights.pt';weights.write_bytes(b'frozen')
    code=tmp_path/'models.py';code.write_bytes(b'original')
    config=tmp_path/'models.json'
    data=dict(schema_version=1,modules=[dict(module_id='vessel',enabled=True,adapter_id='vascx_native',
        device='cpu',model_version='test',weights_path=str(weights),weights_sha256=hashlib.sha256(b'frozen').hexdigest(),
        model_source=str(tmp_path),source_hashes={'models.py':hashlib.sha256(b'original').hexdigest()},
        runtime_python=str(tmp_path/'missing.exe'))])
    config.write_text(json.dumps(data))
    report=check_runtime(config)
    assert not report['ok'] and report['modules'][0]['errors']==['runtime_missing']
    code.write_bytes(b'changed');weights.unlink()
    report=check_runtime(config)
    assert set(report['modules'][0]['errors'])=={'source_hash_mismatch','runtime_missing','weights_unreadable'}
    assert str(tmp_path) not in json.dumps(report)


def test_disabled_module_not_required_and_imported_input_explicit(tmp_path):
    config=tmp_path/'models.json'
    config.write_text(json.dumps(dict(schema_version=1,modules=[
        dict(module_id='ridge',enabled=True,adapter_id='imported_ridge',device='cpu'),
        dict(module_id='unused',enabled=False,weights_path='missing.pt')])))
    assert check_runtime(config)['ok']


def test_unconfigured_model_is_not_reported_healthy(tmp_path):
    config=tmp_path/'models.json'
    config.write_text(json.dumps(dict(schema_version=1,modules=[
        dict(module_id='staging',enabled=True,adapter_id='a6_shenzhen',device='cpu')])))
    report=check_runtime(config)
    assert not report['ok']
    assert set(report['modules'][0]['errors'])=={'weights_unconfigured','runtime_unconfigured','version_unconfigured','source_unconfigured'}
