"""Read-only history queries for the simplified two-table library."""
from pathlib import Path
import sqlite3
from rop_insight.services.local_records import LocalRecords,_safe,_hash,_json

STATES={'success':'成功','partial_success':'部分成功','failed':'失败','cancelled':'已取消'}
EYES={'left':'左眼','right':'右眼','unspecified':'未指定'}


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():raise InterruptedError('历史读取已取消')


def query_records(root,code='',cancel=None):
    store=LocalRecords(root,create=False)
    with store._db() as db:
        rows=[dict(row) for row in db.execute('''SELECT r.*,c.case_code,c.eye,c.exam_date FROM analysis_records r
            JOIN cases c ON c.case_id=r.case_id WHERE instr(c.code_key,?)>0
            ORDER BY r.created_at DESC,r.record_id DESC LIMIT 1001''',(code.strip().casefold(),))]
    more=len(rows)>1000;rows=rows[:1000]
    for row in rows:
        check_cancel(cancel)
        row.update(prediction='不可用',analysis_time=row['created_at'],issue='')
        try:
            folder=_safe(store.root,'records/'+row['record_id']);path=folder/'record_manifest.json'
            if _hash(path,cancel)!=row['manifest_sha256']:raise ValueError('记录清单哈希不一致')
            manifest=_json(path);identity=manifest['identity']
            if manifest.get('schema_version')!=1 or identity['run_id']!=row['record_id'] or identity['case']['case_id']!=row['case_id']:raise ValueError('记录身份/版本不匹配')
            result=_safe(store.root,row['result_path'])
            if _hash(result,cancel)!=manifest['files']['result.json']:raise ValueError('分析JSON缺失或损坏')
            source=_json(result)
            if type(source.get('schema_version')) is not int or source['schema_version']!=1 or source['run']['run_id']!=row['record_id'] or source['run']['status']!=row['status']:raise ValueError('分析记录版本或编号不匹配')
            if not _source_matches(source,identity['source']):raise ValueError('分析JSON与冻结来源不一致')
            row.update(case_code=identity['case']['case_code'],eye=identity['case']['eye'],exam_date=identity['case']['exam_date'],analysis_time=source['run'].get('finished_at') or source['run'].get('started_at') or row['created_at'])
            classes=[m['deep_classification'] for m in source['modules'].values() if m.get('state')=='success' and m.get('deep_classification')]
            if len(classes)==1:
                _classification(classes[0]);row['prediction']=classes[0]['prediction']
        except InterruptedError:raise
        except (OSError,ValueError,TypeError,KeyError,AttributeError,RecursionError):row['issue']='记录文件异常，打开时查看原因';row['prediction']='不可用'
    rows.sort(key=lambda row:(row['analysis_time'],row['record_id']),reverse=True)
    return dict(rows=rows,more=more)


def history_job(job,cancel=None):
    try:
        check_cancel(cancel)
        if job['kind']=='list':result=query_records(job['root'],job.get('code',''),cancel)
        elif job['kind']=='analysis':result=load_analysis(job['root'],job['record_id'],cancel)
        elif job['kind']=='report':result=load_report(job['root'],job['record_id'],cancel)
        elif job['kind']=='export_pdf':result=export_saved_pdf(job['root'],job['record_id'],job['destination'],cancel)
        else:raise ValueError('未知历史操作')
        return dict(ok=True,kind=job['kind'],root=job['root'],code=job.get('code',''),record_id=job.get('record_id'),result=result)
    except (OSError,sqlite3.Error,ValueError,TypeError,KeyError,AttributeError,RecursionError) as error:
        return dict(ok=False,kind=job['kind'],message=str(error) if isinstance(error,ValueError) else '历史读取失败或已取消，请检查资料库及关联文件')


def _source_matches(data,expected):
    if not isinstance(data,dict) or not isinstance(expected,dict):return False
    for key in ('image','run'):
        if not isinstance(data.get(key),dict) or any(data[key].get(k)!=v for k,v in expected[key].items()):return False
    if not isinstance(data.get('modules'),dict) or set(data['modules'])!=set(expected['modules']):return False
    return all(
        isinstance(data['modules'][name],dict) and all(data['modules'][name].get(k)==v for k,v in item.items()) for name,item in expected['modules'].items())


def _classification(data):
    from rop_insight.models.analysis_result import AnalysisOutput,ClassificationData
    from rop_insight.services.result_exporter import CLASSES
    from rop_insight.inference.base import validate_output
    if data.get('classes')!=list(CLASSES):raise ValueError('分类标签顺序无效')
    result=ClassificationData(tuple(data['probabilities']))
    validate_output(AnalysisOutput({},classification=result))
    if data.get('prediction')!=CLASSES[max(range(4),key=lambda i:result.probabilities[i])]:raise ValueError('分类概率与类别不一致')
    return result


def _read_bytes(path,expected,cancel,limit=64*1024*1024):
    import hashlib
    if path.stat().st_size>limit:raise ValueError('文件超过读取上限')
    with path.open('rb') as stream:
        chunks=[];size=0
        while chunk:=stream.read(1024*1024):
            check_cancel(cancel);size+=len(chunk)
            if size>limit:raise ValueError('文件超过读取上限')
            chunks.append(chunk)
    data=b''.join(chunks)
    if hashlib.sha256(data).hexdigest()!=expected:raise ValueError('文件在读取时变化，已阻止使用')
    return data


def load_analysis(root,record_id,cancel=None):
    """Rehydrate saved display contracts only. Never instantiate an inference adapter."""
    import hashlib,json,math
    from PyQt6.QtGui import QImage
    from rop_insight.models.analysis_result import AnalysisRun,ModuleResult,ModuleError,AnalysisOutput,ClassificationData,MaskData
    from rop_insight.services.analysis_config import AnalysisConfig
    from rop_insight.services.result_exporter import pixel_hash,CLASSES
    from rop_insight.inference.base import validate_output
    from rop_insight.services.image_loader import ImageLoader
    store=LocalRecords(root,create=False);row=store.verify_record(record_id,include_report=False,cancel=cancel)
    folder=_safe(store.root,'records/'+record_id);manifest=_json(folder/'record_manifest.json');identity=manifest['identity']
    result_path=_safe(store.root,row['result_path'])
    data=json.loads(_read_bytes(result_path,manifest['files']['result.json'],cancel,4*1024*1024))
    if type(data.get('schema_version')) is not int or data['schema_version']!=1:raise ValueError('分析JSON版本不支持')
    if data['image']['image_id']!=identity['image_id'] or data['run']['run_id']!=record_id or data['run']['status']!=row['status']:raise ValueError('分析JSON身份不匹配')
    if not _source_matches(data,identity['source']):raise ValueError('分析JSON与冻结来源不一致')
    original=manifest['original'];image_path=_safe(store.root,row['image_path'])
    # Decode from the exact hashed byte snapshot, not a second unverified path read.
    image_bytes=_read_bytes(image_path,manifest['files'][original],cancel,256*1024*1024)
    if len(image_bytes)>256*1024*1024:raise ValueError('原图过大')
    ImageLoader()  # Preserve the established bounded Qt image allocation limit.
    image=QImage.fromData(image_bytes)
    info=data['image']
    if image.isNull() or image.width()!=info['width'] or image.height()!=info['height'] or hashlib.sha256(image_bytes).hexdigest()!=info['file_sha256'] or pixel_hash(image)!=info['rgb_pixel_sha256']:raise ValueError('原图与保存的图像身份不一致')
    modules={};used=set()
    if not isinstance(data['modules'],dict):raise ValueError('分析模块结构无效')
    for name,item in data['modules'].items():
        check_cancel(cancel)
        state=item['state']
        if state not in ('success','failed','skipped','cancelled'):raise ValueError('保存的模块不是终态')
        output=None;error=None
        if item.get('error'):error=ModuleError(item['error']['code'],item['error']['message'])
        if state=='success':
            values=item.get('values',{});masks=[];classification=None
            if not isinstance(values,dict):raise ValueError('保存的模块输出无效')
            features=values.get('feature_values',{})
            if not isinstance(features,dict) or any(value is not None and (type(value) not in (int,float) or not math.isfinite(value)) for value in features.values()):raise ValueError('特征数值无效')
            metrics=values.get('metrics',{})
            if not isinstance(metrics,dict):raise ValueError('量化特征格式无效')
            for metric in metrics.values():
                if not isinstance(metric,dict) or not {'value','unit','grid'}.issubset(metric):raise ValueError('量化指标字段缺失')
                if metric['value'] is None and 'reason' not in metric:raise ValueError('不可用指标缺少原因')
                if metric['value'] is not None and (type(metric['value']) not in (int,float) or not math.isfinite(metric['value'])):raise ValueError('量化指标数值无效')
            score=values.get('score')
            if score:
                if score.get('status')=='available':
                    if any(type(score.get(k)) not in (int,float) or not math.isfinite(score[k]) for k in ('median','lower','upper')) or not score['lower']<=score['median']<=score['upper']:raise ValueError('连续评分字段无效')
                elif 'reason' not in score:raise ValueError('不可用评分缺少原因')
            auxiliary=values.get('auxiliary_classification')
            if auxiliary:
                if auxiliary.get('status')=='available' and auxiliary.get('prediction') not in CLASSES:raise ValueError('SVM类别无效')
                if auxiliary.get('status')!='available' and 'reason' not in auxiliary:raise ValueError('不可用SVM缺少原因')
            for filename in item.get('masks',[]):
                if filename not in ('ridge_mask.png','vessel_mask.png') or filename not in manifest['files']:raise ValueError('未登记或未知的Mask引用')
                structure=filename.split('_')[0]
                if structure in used:raise ValueError('同一图层来自多个模块')
                used.add(structure)
                mask_bytes=_read_bytes(_safe(folder,filename),manifest['files'][filename],cancel)
                mask=QImage.fromData(mask_bytes).convertToFormat(QImage.Format.Format_RGBA8888)
                if mask.size()!=image.size():raise ValueError('Mask与原图尺寸不一致')
                raw=mask.constBits().asstring(mask.sizeInBytes());red,green,blue,alpha=raw[::4],raw[1::4],raw[2::4],raw[3::4]
                if red!=green or red!=blue or set(red)-{0,255} or set(alpha)!={255}:raise ValueError('保存的Mask不是二值图')
                masks.append(MaskData(structure,image.width(),image.height(),red.translate(bytes([0]+[1]*255))))
            cls=item.get('deep_classification')
            if cls:
                if cls.get('classes')!=list(CLASSES):raise ValueError('分类标签顺序无效')
                classification=_classification(cls)
            output=AnalysisOutput(values,tuple(masks),classification);validate_output(output,(image.width(),image.height()))
            if cls and cls.get('prediction')!=CLASSES[max(range(4),key=lambda i:classification.probabilities[i])]:raise ValueError('分类结果与概率不一致')
        elif item.get('masks') or item.get('deep_classification'):raise ValueError('失败模块不能携带有效图层或分类')
        modules[name]=ModuleResult(name,state,item.get('elapsed_seconds'),output,error,item.get('model_version'))
    run_data=data['run']
    run=AnalysisRun(record_id,identity['image_id'],AnalysisConfig(()),modules,status=row['status'],
        started_at=run_data.get('started_at'),finished_at=run_data.get('finished_at'),software_version=run_data.get('software_version'),code_revision=run_data.get('code_revision'),code_dirty=run_data.get('code_dirty'))
    check_cancel(cancel)
    return dict(row=row,case=identity['case'],image=image,run=run,data=data)


def load_report(root,record_id,cancel=None):
    store=LocalRecords(root,create=False);row=store.get_record(record_id)
    if row is None:raise ValueError('记录不存在')
    if not row['report_path']:return None
    path=_safe(store.root,'records/'+record_id+'/record_manifest.json')
    if _hash(path,cancel)!=row['manifest_sha256']:raise ValueError('记录清单损坏')
    identity=_json(path)['identity']
    if identity['run_id']!=record_id or identity['case']['case_id']!=row['case_id']:raise ValueError('报告所属记录身份不一致')
    pdf_path=_safe(store.root,row['report_path']);folder=pdf_path.parent
    store._verify_report(folder,row['report_sha256'],identity,cancel)
    manifest=_json(folder/'report_manifest.json')
    required={'report.pdf','report_detail.txt','report.json'}
    if not required.issubset(manifest['artifacts']) or pdf_path.name!='report.pdf':raise ValueError('报告清单缺少必要文件')
    detail=_read_bytes(_safe(folder,'report_detail.txt'),manifest['artifacts']['report_detail.txt']['sha256'],cancel,4*1024*1024).decode('utf-8')
    pdf=_read_bytes(pdf_path,manifest['artifacts']['report.pdf']['sha256'],cancel)
    return dict(text=detail,pdf=pdf,report_id=manifest['report_id'])


def export_saved_pdf(root,record_id,destination,cancel=None):
    import hashlib,os
    report=load_report(root,record_id,cancel)
    if report is None:raise ValueError('未生成报告')
    path=Path(destination)
    created=False
    try:
        with path.open('xb') as stream:
            created=True;check_cancel(cancel);stream.write(report['pdf']);stream.flush();os.fsync(stream.fileno())
        if _hash(path,cancel)!=hashlib.sha256(report['pdf']).hexdigest():raise ValueError('PDF副本校验失败')
        return str(path)
    except BaseException:
        if created:path.unlink(missing_ok=True)
        raise
