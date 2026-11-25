"""Read-only model/environment checks; never install or change research assets."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR
from rop_insight.inference.registry import production_registry
from rop_insight.services.analysis_config import load_config
from rop_insight.services.build_info import code_identity


def file_hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def check_runtime(config_path, probe=False):
    config=load_config(Path(config_path),production_registry())
    entries=[]
    probes={}
    for cfg in config.modules:
        errors=[]
        if cfg.enabled:
            if cfg.adapter_id != 'imported_ridge':
                if not cfg.weights_path:errors.append('weights_unconfigured')
                if not cfg.runtime_python:errors.append('runtime_unconfigured')
                if not cfg.model_version:errors.append('version_unconfigured')
                if cfg.adapter_id in ('a6_shenzhen','chapter5_quant','chapter5_svm') and (
                        not cfg.model_source or not cfg.source_hashes):errors.append('source_unconfigured')
            if cfg.weights_path:
                try:
                    if not cfg.weights_sha256 or file_hash(cfg.weights_path)!=cfg.weights_sha256:
                        errors.append('weights_hash_mismatch')
                except OSError:errors.append('weights_unreadable')
            for name,expected in cfg.source_hashes.items():
                try:
                    if file_hash(Path(cfg.model_source or '')/name)!=expected:errors.append('source_hash_mismatch')
                except OSError:errors.append('source_unreadable')
            if cfg.runtime_python and not Path(cfg.runtime_python).is_file():errors.append('runtime_missing')
            if probe and cfg.runtime_python and not errors and cfg.runtime_python not in probes:
                env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
                env.pop('PYTHONPATH',None);env.pop('PYTHONHOME',None)
                code="""import sys,json,importlib,importlib.metadata as m
d={}
for name in ['torch','torchvision','numpy','pandas','scipy','scikit-learn','opencv-python','scikit-image']:
    try:d[name]=m.version(name)
    except m.PackageNotFoundError:pass
observed={}
cuda=None
for package,module in [('torch','torch'),('torchvision','torchvision'),('numpy','numpy'),('pandas','pandas'),('scipy','scipy'),('scikit-learn','sklearn')]:
    if package in d:
        try:
            imported=importlib.import_module(module)
            observed[package]=imported.__version__
            if module=='torch':cuda=dict(available=imported.cuda.is_available(),build=imported.version.cuda)
        except Exception:observed[package]='import_failed'
warnings=[name for name in observed if observed[name]!=d[name]]
print(json.dumps(dict(python=sys.version.split()[0],package_metadata=d,imported_packages=observed,cuda=cuda,metadata_mismatches=warnings)))
"""
                try:
                    result=subprocess.run([cfg.runtime_python,'-B','-c',code],capture_output=True,text=True,
                        timeout=60,env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    probes[cfg.runtime_python]=json.loads(result.stdout) if result.returncode==0 else dict(error='runtime_probe_failed')
                except (OSError,subprocess.TimeoutExpired,ValueError):probes[cfg.runtime_python]=dict(error='runtime_probe_failed')
            if probe and cfg.runtime_python and probes.get(cfg.runtime_python,{}).get('error'):errors.append('runtime_probe_failed')
            runtime=probes.get(cfg.runtime_python,{})
            if any(version=='import_failed' for version in runtime.get('imported_packages',{}).values()):errors.append('package_import_failed')
            if probe and cfg.device and cfg.device.startswith('cuda') and (runtime.get('cuda') or {}).get('available') is not True:
                errors.append('cuda_unavailable')
        entries.append(dict(module_id=cfg.module_id,enabled=cfg.enabled,adapter_id=cfg.adapter_id,device=cfg.device,
            model_version=cfg.model_version,weights_sha256=cfg.weights_sha256,status='failed' if errors else 'ok',errors=errors,
            runtime=probes.get(cfg.runtime_python)))
    revision,dirty=code_identity()
    return dict(schema_version=1,ok=all(item['status']=='ok' for item in entries),
        gui=dict(python=sys.version.split()[0],pyqt=PYQT_VERSION_STR,qt=QT_VERSION_STR),
        code_revision=revision,code_dirty=dirty,modules=entries,
        limitations=['Artifact checks do not replace inference verification','Automatic Ridge remains deferred'])


def main():
    import argparse
    parser=argparse.ArgumentParser(description='Read-only ROP-Insight model/environment check')
    parser.add_argument('--config',required=True,type=Path)
    parser.add_argument('--probe',action='store_true',help='Read package versions in original Python environments')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    try:report=check_runtime(args.config,args.probe)
    except (ValueError,OSError):report=dict(ok=False,error='Configuration unreadable or invalid')
    text=json.dumps(report,ensure_ascii=False,indent=2)
    if args.output:args.output.write_text(text,encoding='utf-8')
    print(text)
    return 0 if report['ok'] else 1


if __name__=='__main__':
    raise SystemExit(main())
