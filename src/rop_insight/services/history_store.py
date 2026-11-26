"""Read-only, bounded local history. No inference, report regeneration or database."""
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
from threading import Event
from rop_insight.services.case_store import validate_case_link

MAX_JSON=4*1024*1024
MAX_ARTIFACT=256*1024*1024


def reject_links(path):
    for part in (path,*path.parents):
        if part.is_symlink() or part.is_junction():raise ValueError('不允许链接目录或文件')
        if part.exists() and getattr(part.lstat(),'st_file_attributes',0)&0x400:
            raise ValueError('不允许重解析点')


def safe_file(folder,name):
    if not isinstance(name,str) or not name or name in ('.','..') or any(c in name for c in '/\\:'):
        raise ValueError('非法文件关联')
    path=folder/name
    reject_links(path)
    if path.is_symlink() or path.is_junction() or path.resolve().parent!=folder.resolve():
        raise ValueError('文件关联越界')
    if not path.is_file():raise ValueError('关联文件缺失：'+name)
    return path


def read_json(path):
    if path.stat().st_size>MAX_JSON:raise ValueError('JSON超过读取上限')
    return json.loads(path.read_text(encoding='utf-8'),parse_constant=lambda x: (_ for _ in ()).throw(ValueError('非法数值')))


def digest(path,cancel=None):
    if path.stat().st_size>MAX_ARTIFACT:raise ValueError('文件超过校验上限')
    sha=hashlib.sha256()
    with path.open('rb') as stream:
        while chunk:=stream.read(1024*1024):
            if cancel and cancel.is_set():raise InterruptedError('已取消')
            sha.update(chunk)
    return sha.hexdigest()


@dataclass
class HistoryRecord:
    folder: Path
    kind: str
    document: dict=field(default_factory=dict)
    case: object=None
    issues: list=field(default_factory=list)
    artifacts: dict=field(default_factory=dict)

    @property
    def source(self):
        value=self.document.get('source',{}) if self.kind=='report' else self.document
        return value if isinstance(value,dict) else {}
    @property
    def case_id(self):return self.case.case_id if self.case else '未关联病例'
    @property
    def status(self):return '；'.join(self.issues) if self.issues else '记录内哈希一致（未签名）'


def inspect_bundle(folder,cancel=None):
    folder=Path(folder).absolute()
    reject_links(folder)
    kind='report' if (folder/'report.json').exists() else 'analysis'
    record=HistoryRecord(folder,kind)
    try:
        document=read_json(safe_file(folder,'report.json' if kind=='report' else 'result.json'))
        if not isinstance(document,dict):raise ValueError('记录格式无效')
        key='report_schema_version' if kind=='report' else 'schema_version'
        if type(document.get(key)) is not int or document[key]!=1:raise ValueError('不支持的记录版本')
        record.document=document
        source=record.source
        image,run=source['image'],source['run']
        if not isinstance(image,dict) or not isinstance(run,dict):raise ValueError('图像或运行结构无效')
        if not isinstance(image['image_id'],str) or not isinstance(run['run_id'],str):raise ValueError('缺少图像/运行编号')
        if run['status'] not in ('success','partial_success','failed','cancelled'):raise ValueError('记录未完成')
        if not isinstance(source['modules'],dict):raise ValueError('模块来源无效')
        if kind=='report':
            manifest=read_json(safe_file(folder,'report_manifest.json'))
            expected=dict(report_schema_version=1,report_id=document['report_id'],template_version=document['template_version'],
                source_snapshot_sha256=document['source_snapshot_sha256'],run_id=run['run_id'],image_id=image['image_id'],input_file_sha256=image.get('file_sha256'))
            if any(manifest.get(k)!=v for k,v in expected.items()):raise ValueError('报告清单关联不一致')
            canonical=json.dumps(source,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
            if hashlib.sha256(canonical.encode()).hexdigest()!=document['source_snapshot_sha256']:raise ValueError('分析快照哈希不一致')
            artifacts=manifest['artifacts']
            if not {'report.json','report.pdf','report_detail.txt'}.issubset(artifacts):raise ValueError('报告清单缺少必需文件')
        else:artifacts=document.get('artifacts',{})
        if not isinstance(artifacts,dict):raise ValueError('文件清单无效')
        if kind=='analysis':
            references=[]
            for module in source['modules'].values():
                if not isinstance(module,dict) or not isinstance(module.get('masks',[]),list):raise ValueError('图层引用格式无效')
                references.extend(module.get('masks',[]))
            if document.get('visualization'):references.append(document['visualization'])
            if document.get('case_metadata_file'):
                if document['case_metadata_file']!='case_metadata.json':raise ValueError('病例关联文件名无效')
                references.append(document['case_metadata_file'])
            if any(not isinstance(name,str) or name not in artifacts for name in references):raise ValueError('关联文件未纳入校验清单')
        record.artifacts=artifacts
        for name,info in artifacts.items():
            path=safe_file(folder,name)
            if not isinstance(info,dict) or digest(path,cancel)!=info.get('sha256'):raise ValueError('文件哈希不一致：'+name)
            if 'bytes' in info and path.stat().st_size!=info['bytes']:raise ValueError('文件大小不一致：'+name)
        has_case=document.get('case_metadata') is not None or document.get('case_metadata_file') is not None
        if has_case:
            if 'case_metadata.json' not in artifacts:raise ValueError('病例关联未纳入校验清单')
            case=validate_case_link(read_json(safe_file(folder,'case_metadata.json')),image,run['run_id'],document.get('report_id'))
            if kind=='report' and case.to_dict()!=document['case_metadata']:raise ValueError('报告与病例资料不一致')
            revision=(manifest if kind=='report' else document).get('case_revision_id')
            if revision!=case.revision_id:raise ValueError('病例资料版本不一致')
            record.case=case
    except InterruptedError:raise
    except (ValueError,OSError,KeyError,TypeError,AttributeError,RecursionError) as exc:
        record.document={} if not isinstance(record.source.get('run'),dict) else record.document
        record.case=None;record.issues.append('记录不可复核：'+str(exc))
    return record


def scan_history(root,cancel=None):
    root=Path(root).absolute()
    cancel=cancel or Event()
    if not root.is_dir() or root==Path(root.anchor) or root.is_symlink() or root.is_junction():
        raise ValueError('请选择具体的本地成果目录，不能选择整个磁盘或链接目录')
    reject_links(root)
    records=[];visited=0;json_bytes=0
    def onerror(error):raise error
    for current,dirs,files in os.walk(root,followlinks=False,onerror=onerror):
        if cancel.is_set():raise InterruptedError('已取消历史读取')
        visited+=1
        if visited>10000:raise ValueError('子目录超过10000，请选择更小的成果目录')
        folder=Path(current)
        depth=len(folder.relative_to(root).parts)
        dirs[:]=[d for d in sorted(dirs) if not d.startswith('.') and not (folder/d).is_symlink() and not (folder/d).is_junction()] if depth<8 else []
        if 'report.json' in files or 'result.json' in files:
            for name in ('report.json','result.json','report_manifest.json','case_metadata.json'):
                if name in files:
                    json_bytes+=(folder/name).lstat().st_size
            if json_bytes>64*1024*1024:raise ValueError('记录JSON总量超过64MB，请缩小目录范围')
            records.append(inspect_bundle(folder,cancel));dirs[:]=[]
            if len(records)>5000:raise ValueError('记录超过5000，请缩小目录范围')
    return records


def verified_artifact(record,name,cancel=None):
    fresh=inspect_bundle(record.folder,cancel)
    if fresh.issues or fresh.document!=record.document or fresh.artifacts!=record.artifacts:raise ValueError('记录已改变或校验失败，请刷新列表')
    if name not in fresh.artifacts:raise ValueError('文件未纳入校验清单')
    return safe_file(fresh.folder,name)


def verify_input(record,path,cancel=None):
    expected=record.source.get('image',{}).get('file_sha256')
    if not expected:return '旧记录没有原始文件哈希，无法核对'
    return '原始文件哈希一致' if digest(Path(path),cancel)==expected else '原始文件哈希不一致，未更改关联'
