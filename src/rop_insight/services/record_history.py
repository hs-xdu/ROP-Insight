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
            if source.get('schema_version')!=1 or source['run']['run_id']!=row['record_id']:raise ValueError('分析记录版本或编号不匹配')
            row.update(case_code=identity['case']['case_code'],eye=identity['case']['eye'],exam_date=identity['case']['exam_date'],analysis_time=source['run'].get('finished_at') or source['run'].get('started_at') or row['created_at'])
            classes=[m['deep_classification'] for m in source['modules'].values() if m.get('state')=='success' and m.get('deep_classification')]
            if len(classes)==1 and classes[0].get('prediction') in ('Normal','Stage 1','Stage 2','Stage 3'):row['prediction']=classes[0]['prediction']
        except InterruptedError:raise
        except (OSError,ValueError,TypeError,KeyError,AttributeError,RecursionError):row['issue']='记录文件异常，打开时查看原因';row['prediction']='不可用'
    rows.sort(key=lambda row:(row['analysis_time'],row['record_id']),reverse=True)
    return dict(rows=rows,more=more)


def history_job(job,cancel=None):
    try:
        check_cancel(cancel)
        if job['kind']=='list':result=query_records(job['root'],job.get('code',''),cancel)
        else:raise ValueError('未知历史操作')
        return dict(ok=True,kind=job['kind'],root=job['root'],code=job.get('code',''),result=result)
    except (OSError,sqlite3.Error,ValueError,TypeError,KeyError,AttributeError,RecursionError) as error:
        return dict(ok=False,kind=job['kind'],message=str(error) if isinstance(error,ValueError) else '历史读取失败或已取消，请检查资料库及关联文件')
