"""Map one completed analysis to factual report data; no inference or binning."""

from copy import deepcopy
import hashlib
import json
import math
from uuid import uuid4
from importlib.metadata import PackageNotFoundError, version
from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR

from rop_insight.models.analysis_result import timestamp
from rop_insight.models.report import ReportDocument
from rop_insight.services.result_exporter import ExportSnapshot, portable, pixel_hash, VALUE_FIELDS, CLASSES
from rop_insight.inference.svm_backend import FEATURES
from rop_insight.services.build_info import code_identity
from rop_insight.services.feature_descriptions import describe_features

TEMPLATE_VERSION = 'p5-factual-3'
METRIC_NAMES = {'fractal_dimension':'分形维数 FD','vessel_area_density_fov':'血管密度 VD',
    'sliding_window_max_density_gradient':'最大局部密度变化','T3':'血管迂曲度 T3','B3':'血管分支 B3',
    'ridge_area_ratio_fov':'Ridge面积比例','ridge_solidity':'Ridge实心度',
    'ridge_outer_vessel_density':'Ridge外环血管密度','ridge_max_radius_ratio':'Ridge最大径向位置','S_median':'S_median'}
MODULE_NAMES = {'ridge':'Ridge结构','vessel':'Vessel结构','staging':'A6分期',
                'quantification':'结构量化与评分','auxiliary':'SVM辅助分类'}
STATES = {'success':'成功','failed':'失败','skipped':'跳过','cancelled':'已取消',
          'partial_success':'部分成功'}
RUN_FIELDS = ('run_id','status','started_at','finished_at','software_version','code_revision','code_dirty')
IMAGE_FIELDS = ('image_id','width','height','format','file_sha256','rgb_pixel_sha256')
MODULE_FIELDS = ('state','enabled','elapsed_seconds','model_version','adapter_id','device',
                 'weights_sha256','dependencies','source_hashes','preprocessing','postprocessing',
                 'masks','values','deep_classification','error')


def finite(value):
    return type(value) in (int,float) and math.isfinite(value)


def _clean(value):
    if isinstance(value,dict):return {key:_clean(child) for key,child in value.items()}
    if isinstance(value,(list,tuple)):return [_clean(child) for child in value]
    if type(value) is float and not math.isfinite(value):return None
    return value


def snapshot_result(snapshot):
    """Same portable fields as P4 JSON, without writing PNG or reading sources."""
    snapshot=ExportSnapshot.capture(snapshot.context,snapshot.run,snapshot.case_metadata)
    context,run=snapshot.context,snapshot.run
    configs={cfg.module_id:cfg for cfg in run.config.modules}
    modules={}
    for name,item in run.modules.items():
        cfg=configs[name]
        entry=dict(state=str(item.state),enabled=cfg.enabled,elapsed_seconds=item.elapsed_seconds,
            model_version=item.model_version,adapter_id=cfg.adapter_id,device=cfg.device,
            weights_sha256=cfg.weights_sha256,dependencies=list(cfg.dependencies),
            source_hashes=portable(cfg.source_hashes),preprocessing=portable(cfg.preprocessing),
            postprocessing=portable(cfg.postprocessing),masks=[])
        if item.error:entry['error']=dict(code=portable(item.error.code),message='模块未成功，详情见本机日志')
        if item.state=='success' and item.output:
            from rop_insight.inference.base import validate_output
            validate_output(item.output,(context.image.width(),context.image.height()))
            entry['values']=portable({key:value for key,value in item.output.values.items() if key in VALUE_FIELDS})
            entry['masks']=[mask.structure+'_mask.png' for mask in item.output.masks]
            if item.output.classification:
                probabilities=list(item.output.classification.probabilities)
                entry['deep_classification']=dict(classes=list(CLASSES),probabilities=probabilities,
                    prediction=CLASSES[max(range(4),key=lambda i:probabilities[i])])
        modules[name]=entry
    return dict(schema_version=1,image=dict(image_id=context.image_id,width=context.image.width(),
        height=context.image.height(),format=context.format,file_sha256=context.file_sha256,
        rgb_pixel_sha256=pixel_hash(context.image)),run={key:getattr(run,key) for key in RUN_FIELDS},modules=modules)


def build_report(snapshot):
    return report_from_result(snapshot_result(snapshot),case_metadata=snapshot.case_metadata)


def report_from_result(result, *, report_id=None, generated_at=None, case_metadata=None):
    """Accept P4 schema 1 as well as live snapshots; do not open linked files."""
    if result.get('schema_version')!=1:raise ValueError('不支持的分析结果版本')
    image,run,modules=result.get('image',{}),result.get('run',{}),result.get('modules',{})
    if not image.get('image_id') or not run.get('run_id') or not run.get('finished_at'):
        raise ValueError('报告缺少图像或已结束任务关联')
    if run.get('status') not in ('success','partial_success','failed','cancelled'):
        raise ValueError('仅支持已结束的分析结果')
    if not isinstance(modules,dict) or any(m.get('state') not in ('success','failed','skipped','cancelled') for m in modules.values()):
        raise ValueError('模块仍在运行或状态无效')
    source=dict(schema_version=1,image={key:image.get(key) for key in IMAGE_FIELDS},
        run={key:run.get(key) for key in RUN_FIELDS},modules={name:{key:value for key,value in item.items()
            if key in MODULE_FIELDS} for name,item in modules.items()})
    source=portable(_clean(deepcopy(source)))
    case=None
    if case_metadata is not None:
        from rop_insight.models.case_metadata import CaseMetadata
        case=CaseMetadata.from_dict(case_metadata)
        case.assert_binding(source['image']['image_id'],source['image']['file_sha256'],source['image']['rgb_pixel_sha256'])
    canonical=json.dumps(source,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
    modules=source['modules']

    def module(adapter, fallback):
        found=[item for item in modules.values() if item.get('adapter_id')==adapter]
        if len(found)==1:return found[0]
        if len(found)>1:return dict(state='failed',error=dict(code='source_conflict'))
        candidate=modules.get(fallback,{})
        return candidate if candidate.get('adapter_id') in (None,adapter) else {}

    def reason(item):
        state=item.get('state')
        if state=='success':return '未提供有效输出'
        return STATES.get(state,'未配置或未提供')+'；错误码：'+str(item.get('error',{}).get('code') or '无')

    staging=module('a6_shenzhen','staging')
    classification=staging.get('deep_classification',{}) if staging.get('state')=='success' else {}
    probabilities=classification.get('probabilities')
    valid=(classification.get('classes')==list(CLASSES) and isinstance(probabilities,list) and len(probabilities)==4
        and all(finite(p) and 0<=p<=1 for p in probabilities) and math.isclose(sum(probabilities),1.,abs_tol=1e-6))
    a6=dict(status='available' if valid else 'unavailable',reason=None if valid else reason(staging),
        prediction=CLASSES[max(range(4),key=lambda i:probabilities[i])] if valid else None,
        classes=list(CLASSES),probabilities=probabilities if valid else None)
    quant=module('chapter5_quant','quantification')
    values=quant.get('values',{}) if quant.get('state')=='success' else {}
    metrics=values.get('metrics',{})
    feature_values=values.get('feature_values',{})
    features=[]
    for name in FEATURES:
        metric=metrics.get(name,{})
        value=feature_values.get(name) if name=='T1' else metric.get('value')
        available=finite(value) and (name=='T1' or metric.get('status')=='available')
        features.append(dict(key=name,title='血管迂曲指数 T1' if name=='T1' else METRIC_NAMES[name],
            value=value if available else None,status='available' if available else 'unavailable',
            reason=None if available else (metric.get('reason') or
                ('原指标缺失、非有限或未通过质量规则' if quant.get('state')=='success' else reason(quant))),
            unit='无量纲' if name=='T1' else metric.get('unit','未提供'),
            grid=1024 if name=='T1' else metric.get('grid')))
    score=values.get('score',{})
    valid_score=(score.get('status')=='available' and all(finite(score.get(k)) for k in ('median','lower','upper','ci95_width'))
        and score['lower']<=score['median']<=score['upper'] and math.isclose(score['ci95_width'],score['upper']-score['lower'],abs_tol=1e-9))
    if valid_score and features[-1]['value']!=score['median']:valid_score=False
    scoring=dict(status='available' if valid_score else 'unavailable',
        reason=None if valid_score else (score.get('reason') or '评分缺失、无效或与S_median不一致'),
        **{key:score.get(key) if valid_score else None for key in ('median','lower','upper','ci95_width')},
        valid_segments=score.get('valid_segments'),posterior_sha256=score.get('posterior_sha256'))
    auxiliary=module('chapter5_svm','auxiliary')
    svm=auxiliary.get('values',{}).get('auxiliary_classification',{}) if auxiliary.get('state')=='success' else {}
    valid_svm=(svm.get('status')=='available' and svm.get('prediction') in CLASSES
        and svm.get('probabilities') is None and svm.get('probability_calibrated') is not True)
    svm_result=dict(status='available' if valid_svm else 'unavailable',prediction=svm.get('prediction') if valid_svm else None,
        reason=None if valid_svm else (svm.get('reason') or reason(auxiliary)),probabilities=None)
    structures=[]
    for name in ('ridge','vessel'):
        providers=[(key,m) for key,m in modules.items() if m.get('state')=='success' and name+'_mask.png' in m.get('masks',[])]
        valid_structure=len(providers)==1
        provider=providers[0][1] if valid_structure else {}
        imported=provider.get('values',{}).get('source')=='user_imported_ridge'
        structures.append(dict(name=name,status='available' if valid_structure else 'unavailable',
            source='用户导入' if imported else '模型分割' if valid_structure else '未提供',
            width=image.get('width') if valid_structure else None,height=image.get('height') if valid_structure else None,
            reason=None if valid_structure else '结构未生成或来源冲突'))
    limitations=['本报告为固定模板生成的研究辅助分析，不是医生确认的诊断，不提供治疗建议。',
        'A6、连续评分与SVM分别展示，不融合为临床结论；SVM未校准概率，不显示百分比。',
        '连续评分及95%后验区间为原模型相对尺度，不等同于临床分期。',
        '自动Ridge仍暂缓；用户导入Mask的质量和对齐会影响后续结果。']
    if run['status']!='success':limitations.append('本次分析'+STATES.get(run['status'],run['status'])+'，报告包含未完成模块，不能视为完整分析。')
    if any(f['status']!='available' for f in features):limitations.append('存在不可用特征；未提供的值不解释为0、正常或中等。')
    revision,dirty=code_identity()
    try:software_version=version('rop-insight')
    except PackageNotFoundError:software_version='unknown'
    data=dict(report_schema_version=1,template_version=TEMPLATE_VERSION,report_id=report_id or str(uuid4()),
        generator=dict(software_version=software_version,code_revision=revision,code_dirty=dirty,
                       pyqt=PYQT_VERSION_STR,qt=QT_VERSION_STR),
        generated_at=generated_at or timestamp(),source_snapshot_sha256=hashlib.sha256(canonical.encode('utf-8')).hexdigest(),
        source=source,a6=a6,structures=structures,features=features,score=scoring,svm=svm_result,limitations=limitations,
        feature_descriptions=describe_features(features))
    if case is not None:data['case_metadata']=case.to_dict()
    return ReportDocument(json.dumps(data,ensure_ascii=False,allow_nan=False,sort_keys=True))
