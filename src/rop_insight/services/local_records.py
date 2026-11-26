"""Simplified P6: two tables, explicit saves, existing P4/P5 serializers."""
from contextlib import contextmanager
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from threading import Lock
from uuid import UUID,uuid4
from rop_insight.models.analysis_result import timestamp
from rop_insight.services.result_exporter import ExportSnapshot,export_bundle,pixel_hash
from rop_insight.services.report_builder import snapshot_result
from rop_insight.services.report_exporter import export_report_bundle
from rop_insight.services.image_loader import ImageLoader

_SAVE_LOCK=Lock()


def _hash(path):
    for part in (path,*path.parents):
        if part.is_symlink() or part.is_junction() or (part.exists() and getattr(part.lstat(),'st_file_attributes',0)&0x400):raise ValueError('文件不能使用链接')
    if path.stat().st_size>256*1024*1024:raise ValueError('文件超过256MiB上限')
    sha=hashlib.sha256()
    with path.open('rb') as stream:
        while chunk:=stream.read(1024*1024):sha.update(chunk)
    return sha.hexdigest()


def _safe(root,relative):
    if not isinstance(relative,str) or any(c in relative for c in '\\:') or any(p in ('','.','..') for p in relative.split('/')):raise ValueError('资料路径无效')
    path=root/relative
    for part in (path,*path.parents):
        if part.is_symlink() or part.is_junction() or (part.exists() and getattr(part.lstat(),'st_file_attributes',0)&0x400):raise ValueError('资料路径不能使用链接')
    if not path.resolve().is_relative_to(root.resolve()):raise ValueError('资料路径越界')
    return path


def _json(path):
    _hash(path)
    if path.stat().st_size>4*1024*1024:raise ValueError('JSON文件过大')
    return json.loads(path.read_text(encoding='utf-8'),parse_constant=lambda value:(_ for _ in ()).throw(ValueError('非法JSON数值')))


def _write(path,value):
    with path.open('x',encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=False,allow_nan=False,sort_keys=True,indent=2);stream.flush();os.fsync(stream.fileno())


class LocalRecords:
    def __init__(self,root):
        self.root=Path(root).absolute()
        self.root.mkdir(parents=True,exist_ok=True)
        path=_safe(self.root,'rop_insight.db')
        if (self.root/'catalog.sqlite3').exists():raise ValueError('这是旧五表资料库，请选择新的精简版目录')
        with self._db(True) as db:
            version=db.execute('PRAGMA user_version').fetchone()[0]
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if version==0 and not tables:
                db.execute('''CREATE TABLE cases(case_id TEXT PRIMARY KEY NOT NULL,case_code TEXT NOT NULL,
                    code_key TEXT NOT NULL UNIQUE,eye TEXT NOT NULL CHECK(eye IN ('left','right','unspecified')),
                    exam_date TEXT,created_at TEXT NOT NULL)''')
                db.execute('''CREATE TABLE analysis_records(record_id TEXT PRIMARY KEY NOT NULL,case_id TEXT NOT NULL REFERENCES cases(case_id),
                    image_path TEXT NOT NULL,result_path TEXT NOT NULL,report_path TEXT, status TEXT NOT NULL CHECK(status IN ('success','partial_success','failed','cancelled')),
                    created_at TEXT NOT NULL,manifest_sha256 TEXT NOT NULL,report_sha256 TEXT)''')
                db.execute('PRAGMA user_version=1')
            elif version!=1 or tables!={'cases','analysis_records'}:raise ValueError('不支持的资料库版本或结构')
            expected={'cases':{'case_id','case_code','code_key','eye','exam_date','created_at'},
                      'analysis_records':{'record_id','case_id','image_path','result_path','report_path','status','created_at','manifest_sha256','report_sha256'}}
            for table,columns in expected.items():
                if {row[1] for row in db.execute(f'PRAGMA table_info({table})')}!=columns:raise ValueError('资料库结构不兼容')
            if list(db.execute('PRAGMA foreign_key_check')) or db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('资料库检查失败')
        _safe(self.root,'records').mkdir(exist_ok=True)

    @contextmanager
    def _db(self,write=False):
        path=_safe(self.root,'rop_insight.db')
        db=sqlite3.connect(path,isolation_level=None,timeout=5)
        db.row_factory=sqlite3.Row
        try:
            db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield db;db.commit()
        except BaseException:
            if db.in_transaction:db.rollback()
            raise
        finally:db.close()

    def cases(self):
        with self._db() as db:return tuple(dict(row) for row in db.execute('SELECT case_id,case_code,eye,exam_date,created_at FROM cases ORDER BY created_at,case_id'))

    def create_case(self,code,eye='unspecified',exam_date=None):
        code=code.strip()
        if not code or len(code)>64 or any(ord(c)<32 for c in code):raise ValueError('请填写1—64字符匿名病例编号')
        if eye not in ('left','right','unspecified'):raise ValueError('眼别无效')
        exam_date=exam_date or None
        if exam_date is not None and date.fromisoformat(exam_date).isoformat()!=exam_date:raise ValueError('日期应为YYYY-MM-DD')
        case=dict(case_id=str(uuid4()),case_code=code,eye=eye,exam_date=exam_date,created_at=timestamp())
        try:
            with self._db(True) as db:db.execute('INSERT INTO cases VALUES (?,?,?,?,?,?)',(case['case_id'],code,code.casefold(),eye,exam_date,case['created_at']))
        except sqlite3.IntegrityError:raise ValueError('病例编号已存在') from None
        return case

    def get_record(self,record_id):
        with self._db() as db:
            row=db.execute('SELECT * FROM analysis_records WHERE record_id=?',(record_id,)).fetchone()
            return dict(row) if row else None

    def verify_record(self,record_id):
        row=self.get_record(record_id)
        if row is None:raise ValueError('记录不存在')
        folder=_safe(self.root,f'records/{record_id}')
        manifest=folder/'record_manifest.json'
        if _hash(manifest)!=row['manifest_sha256']:raise ValueError('记录清单损坏')
        data=_json(manifest)
        if data['identity']['run_id']!=record_id or data['identity']['case']['case_id']!=row['case_id']:raise ValueError('记录身份不匹配')
        for name,sha in data['files'].items():
            if _hash(_safe(folder,name))!=sha:raise ValueError('记录文件缺失或损坏：'+name)
        if row['image_path']!=f'records/{record_id}/'+data['original'] or row['result_path']!=f'records/{record_id}/result.json':raise ValueError('记录路径关联错误')
        if row['report_path']:
            self._verify_report(_safe(self.root,row['report_path']).parent,row['report_sha256'],data['identity'])
        return row

    def _verify_report(self,folder,expected,identity):
        manifest=folder/'report_manifest.json'
        if _hash(manifest)!=expected:raise ValueError('报告清单损坏')
        data=_json(manifest)
        if data['run_id']!=identity['run_id'] or data['image_id']!=identity['image_id']:raise ValueError('报告不属于此分析')
        for name,info in data['artifacts'].items():
            if _hash(_safe(folder,name))!=info['sha256']:raise ValueError('报告文件损坏')

    def save_record(self,case,snapshot,report=None):
        snapshot=ExportSnapshot.capture(snapshot.context,snapshot.run)
        record_id=snapshot.run.run_id
        if str(UUID(record_id))!=record_id:raise ValueError('分析记录ID无效')
        identity=dict(case=dict(case),run_id=record_id,image_id=snapshot.context.image_id,source=snapshot_result(snapshot))
        if report is not None and report.data['source']!=identity['source']:raise ValueError('报告与当前分析快照不一致')
        with _SAVE_LOCK:
            with self._db() as db:
                stored=db.execute('SELECT * FROM cases WHERE case_id=?',(case['case_id'],)).fetchone()
                if stored is None or any(dict(stored)[key]!=value for key,value in case.items()):raise ValueError('病例不属于当前资料库')
            target=_safe(self.root,f'records/{record_id}')
            existing=self.get_record(record_id)
            if target.exists():
                manifest=_json(target/'record_manifest.json')
                if manifest['identity']!=identity:raise ValueError('同一分析已关联其他病例或内容，不允许覆盖')
                if existing:self.verify_record(record_id)
                else:
                    for name,sha in manifest['files'].items():
                        if _hash(_safe(target,name))!=sha:raise ValueError('上次未完成记录校验失败')
            else:
                staging=Path(tempfile.mkdtemp(prefix='.save-',dir=_safe(self.root,'records')))
                try:
                    bundle=export_bundle(snapshot,staging)
                    original='original.png' if snapshot.context.format=='PNG' else 'original.jpg'
                    source=Path(snapshot.context.source)
                    destination=bundle/original
                    with source.open('rb') as src,destination.open('xb') as dst:
                        total=0
                        while chunk:=src.read(1024*1024):
                            total+=len(chunk)
                            if total>256*1024*1024:raise ValueError('原图超过256MiB')
                            dst.write(chunk)
                        dst.flush();os.fsync(dst.fileno())
                    document=ImageLoader().load(destination)
                    if document.file_sha256!=snapshot.context.file_sha256 or pixel_hash(document.image)!=pixel_hash(snapshot.context.image):raise ValueError('源文件已变化，请重新导入')
                    manifest=dict(schema_version=1,identity=identity,original=original,files={p.name:_hash(p) for p in bundle.iterdir() if p.is_file()})
                    _write(bundle/'record_manifest.json',manifest)
                    os.rename(bundle,target)
                finally:
                    # This call owns this freshly allocated staging directory, never a published record.
                    if staging.resolve().parent!=_safe(self.root,'records').resolve():raise ValueError('临时目录越界')
                    shutil.rmtree(staging)
            manifest_path=target/'record_manifest.json'
            with self._db(True) as db:
                db.execute('''INSERT OR IGNORE INTO analysis_records VALUES (?,?,?,?,NULL,?,?,?,NULL)''',
                    (record_id,case['case_id'],f'records/{record_id}/'+manifest['original'],f'records/{record_id}/result.json',snapshot.run.status,snapshot.run.finished_at,_hash(manifest_path)))
            self.verify_record(record_id)
            if report is not None and self.get_record(record_id)['report_path'] is None:
                parent=_safe(self.root,f'records/{record_id}/report');parent.mkdir(exist_ok=True)
                folder=export_report_bundle(report,parent)
                sha=_hash(folder/'report_manifest.json');self._verify_report(folder,sha,identity)
                relative=(folder/'report.pdf').relative_to(self.root).as_posix()
                with self._db(True) as db:db.execute('UPDATE analysis_records SET report_path=?,report_sha256=? WHERE record_id=? AND report_path IS NULL',(relative,sha,record_id))
            return self.verify_record(record_id)
