"""P6-B checked file publication. No Run, report or model execution integration."""
from contextlib import contextmanager
from dataclasses import fields
import hashlib
import json
import logging
import os
from pathlib import Path
from threading import Event
from uuid import UUID, uuid5
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QImage
from rop_insight.models.analysis_result import timestamp
from rop_insight.models.managed_data import StoreError, require, valid_uuid, valid_relpath, valid_hash
from rop_insight.models.managed_image import ImageImportRequest, ManagedImage
from rop_insight.services.database import _reject_links
from rop_insight.services.history_store import digest, read_json
from rop_insight.services.image_loader import ImageLoader
from rop_insight.services.result_exporter import pixel_hash
from rop_insight.inference.imported_ridge import load_ridge

MAX_FILE_BYTES=256*1024*1024
LOG=logging.getLogger(__name__)


def _check(cancel):
    if cancel.is_set():raise StoreError('CANCELLED','图像托管已取消，未发布有效记录')


def _path(root,relative):
    valid_relpath(relative)
    path=root/relative
    _reject_links(path)
    if not path.resolve().is_relative_to(root.resolve()):raise StoreError('VALIDATION_ERROR','托管路径越界')
    return path


def _write_json(path,data):
    with path.open('x',encoding='utf-8') as stream:
        json.dump(data,stream,ensure_ascii=False,sort_keys=True,allow_nan=False,indent=2)
        stream.flush();os.fsync(stream.fileno())


def _copy(source,target,expected,cancel):
    _reject_links(source)
    if not source.is_file():raise StoreError('SOURCE_MISSING','输入文件不存在')
    if source.stat().st_size>MAX_FILE_BYTES:raise StoreError('VALIDATION_ERROR','输入文件超过256MiB托管上限')
    sha=hashlib.sha256();size=0
    with source.open('rb') as src,target.open('xb') as dst:
        while chunk:=src.read(1024*1024):
            _check(cancel);size+=len(chunk)
            if size>MAX_FILE_BYTES:raise StoreError('VALIDATION_ERROR','输入文件超过256MiB托管上限')
            sha.update(chunk);dst.write(chunk)
        dst.flush();os.fsync(dst.fileno())
    if sha.hexdigest()!=expected:raise StoreError('SOURCE_CHANGED','输入文件与加载快照不一致，请重新选择')
    if digest(target,cancel)!=expected:raise StoreError('FILE_CORRUPT','托管副本读回哈希不一致')


def _names(request):
    names={'original.png' if request.format=='PNG' else 'original.jpg'}
    if request.ridge is not None:names.update(('inputs/ridge-source.png','inputs/ridge-binary.png'))
    return names


def _validate_files(folder,request,cancel):
    _check(cancel)
    original=folder/('original.png' if request.format=='PNG' else 'original.jpg')
    for name in _names(request):
        path=folder/name;_reject_links(path)
        if not path.is_file():raise StoreError('FILE_MISSING','托管图像或输入文件缺失')
    document=ImageLoader().load(original)
    _check(cancel)
    if (document.file_sha256,pixel_hash(document.image),document.image.width(),document.image.height(),document.format)!=(request.file_sha256,request.rgb_pixel_sha256,request.width,request.height,request.format):
        raise StoreError('FILE_CORRUPT','图像副本与冻结的图像身份不一致')
    if request.ridge is not None:
        raw=load_ridge(folder/'inputs/ridge-source.png',QSize(request.width,request.height))
        binary=load_ridge(folder/'inputs/ridge-binary.png',QSize(request.width,request.height))
        if raw.values['file_sha256']!=request.ridge.file_sha256 or hashlib.sha256(raw.masks[0].pixels).hexdigest()!=request.ridge.binary_pixel_sha256 or raw.masks[0].pixels!=binary.masks[0].pixels:
            raise StoreError('FILE_CORRUPT','Ridge原文件、二值副本或图像对齐校验失败')
    _check(cancel)
    return document


def _record(row):
    return ManagedImage(**{field.name:row[field.name] for field in fields(ManagedImage)})


class ManagedImageStore:
    def __init__(self,store):self.store=store

    def get_image(self,image_id):
        valid_uuid(image_id)
        with self.store.transaction() as connection:
            row=connection.execute('SELECT * FROM images WHERE image_id=?',(image_id,)).fetchone()
            return _record(row) if row else None

    def find_duplicates(self,case_id,file_sha256):
        valid_uuid(case_id);valid_hash(file_sha256)
        with self.store.transaction() as connection:
            return tuple(_record(row) for row in connection.execute('SELECT * FROM images WHERE case_id=? AND file_sha256=? ORDER BY imported_at,image_id',(case_id,file_sha256)))

    def incomplete_images(self):
        with self.store.transaction() as connection:
            return tuple(_record(row) for row in connection.execute("SELECT * FROM images WHERE save_state<>'ready' OR integrity_state<>'valid' ORDER BY imported_at,image_id"))

    @contextmanager
    def _writer(self):
        staging=_path(self.store.root,'.staging');staging.mkdir(exist_ok=True)
        lock=_path(self.store.root,'.staging/.image-writer.lock')
        try:descriptor=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
        except FileExistsError:raise StoreError('STORE_BUSY','另一项图像托管尚未结束；异常退出的锁需人工核对') from None
        try:
            os.close(descriptor)
            yield staging
        finally:
            try:lock.unlink()
            except OSError:LOG.warning('Image writer lock retained; manual inspection required')

    def _reserve(self,request):
        data=request.payload();data.pop('ridge')
        data['managed_relpath']=f"images/{request.image_id}/"+('original.png' if request.format=='PNG' else 'original.jpg')
        with self.store.transaction(write=True) as connection:
            revision=connection.execute('SELECT 1 FROM case_revisions WHERE case_id=? AND revision_id=?',(request.case_id,request.case_revision_id)).fetchone()
            require(revision is not None,'病例资料版本不存在或不属于该病例')
            row=connection.execute('SELECT * FROM images WHERE image_id=? OR operation_id=?',(request.image_id,request.operation_id)).fetchone()
            if row:
                if any(row[key]!=value for key,value in data.items()):raise StoreError('IDEMPOTENCY_CONFLICT','同一图像或操作ID关联了不同的请求内容')
                return _record(row),False
            keys=','.join(data)
            connection.execute(f"INSERT INTO images ({keys}) VALUES ({','.join('?' for _ in data)})",tuple(data.values()))
            return None,True

    def _finish(self,request,manifest,folder):
        original='original.png' if request.format=='PNG' else 'original.jpg'
        verified=timestamp()
        artifacts=[('original_image',original,manifest['files'][original]['sha256'],manifest['files'][original]['bytes'],'imported'),
                   ('image_manifest','image_manifest.json',digest(folder/'image_manifest.json'),(folder/'image_manifest.json').stat().st_size,'generated')]
        with self.store.transaction(write=True) as connection:
            for kind,name,sha,size,source in artifacts:
                connection.execute('''INSERT INTO artifacts
                    (artifact_id,image_id,artifact_kind,source_kind,relpath,sha256,byte_size,schema_version,save_state,integrity_state,operation_id,created_at,last_verified_at)
                    VALUES (?,?,?,?,?,?,?,'1','ready','valid',?,?,?)''',
                    (str(uuid5(UUID(request.operation_id),kind)),request.image_id,kind,source,f'images/{request.image_id}/{name}',sha,size,request.operation_id,request.imported_at,verified))
            cursor=connection.execute("""UPDATE images SET save_state='ready',integrity_state='valid',failure_code=NULL,failure_message=NULL,last_verified_at=?
                WHERE image_id=? AND operation_id=? AND save_state<>'ready'""",(verified,request.image_id,request.operation_id))
            if cursor.rowcount!=1:raise StoreError('IDEMPOTENCY_CONFLICT','图像保存状态发生变化，未覆盖记录')

    def _mark_failed(self,request,error):
        try:
            with self.store.transaction(write=True) as connection:
                connection.execute("""UPDATE images SET save_state='write_failed',integrity_state='unchecked',failure_code=?,failure_message=?
                    WHERE image_id=? AND operation_id=? AND save_state<>'ready'""",(getattr(error,'code','CANCELLED' if isinstance(error,InterruptedError) else 'STORE_IO_ERROR'),'本次托管未完成，请检查输入和本地存储后重试',request.image_id,request.operation_id))
        except StoreError:LOG.exception('Could not persist import failure; record remains incomplete')

    def _verify_manifest(self,folder,request,cancel):
        path=folder/'image_manifest.json';_reject_links(path)
        if not path.is_file():raise StoreError('FILE_MISSING','图像管理清单缺失')
        manifest=read_json(path)
        if not isinstance(manifest,dict) or type(manifest.get('schema_version')) is not int or manifest.get('schema_version')!=1 or manifest.get('kind')!='managed_image' or manifest.get('request')!=request.payload() or manifest.get('request_sha256')!=request.digest:
            raise StoreError('FILE_CORRUPT','图像清单身份或请求摘要不一致')
        if not isinstance(manifest.get('files'),dict) or set(manifest['files'])!=_names(request):raise StoreError('FILE_CORRUPT','图像清单文件集合不一致')
        for name,info in manifest['files'].items():
            path=folder/name;_reject_links(path)
            if not path.is_file():raise StoreError('FILE_MISSING','图像清单关联文件缺失')
            if not isinstance(info,dict) or digest(path,cancel)!=info.get('sha256') or path.stat().st_size!=info.get('bytes'):
                raise StoreError('FILE_CORRUPT','图像清单关联文件校验失败')
        _validate_files(folder,request,cancel)
        return manifest

    def import_image(self,request,cancel=None):
        require(isinstance(request,ImageImportRequest),'图像托管请求类型无效')
        request=request.validated();cancel=cancel or Event();_check(cancel)
        try:
            with self._writer() as staging:
                row,fresh=self._reserve(request)
                if row and row.save_state=='ready':
                    self.inspect_image(request.image_id,cancel)
                    folder=_path(self.store.root,f'images/{request.image_id}')
                    manifest=read_json(folder/'image_manifest.json')
                    if manifest.get('request_sha256')!=request.digest:raise StoreError('IDEMPOTENCY_CONFLICT','同一操作的Ridge或请求内容不同')
                    return self.get_image(request.image_id)
                operation=_path(self.store.root,f'.staging/{request.operation_id}')
                operation.mkdir(exist_ok=True)
                evidence=_path(self.store.root,f'.staging/{request.operation_id}/request.json')
                if fresh:_write_json(evidence,request.payload())
                elif not evidence.is_file():raise StoreError('REVIEW_REQUIRED','未完成操作缺少请求证据，请人工核对')
                elif read_json(evidence)!=request.payload():raise StoreError('IDEMPOTENCY_CONFLICT','同一操作的请求内容不同')
                payload=operation/'payload'
                created_payload=False
                target=_path(self.store.root,f'images/{request.image_id}')
                try:
                    with self.store.transaction(write=True) as connection:
                        connection.execute("UPDATE images SET save_state='saving' WHERE image_id=? AND save_state<>'ready'",(request.image_id,))
                    _check(cancel)
                    if target.exists():
                        manifest=self._verify_manifest(target,request,cancel)
                    else:
                        if payload.exists():raise StoreError('REVIEW_REQUIRED','未完成临时目录尚未核对，未自动清除')
                        payload.mkdir()
                        created_payload=True
                        original='original.png' if request.format=='PNG' else 'original.jpg'
                        _copy(request.source,payload/original,request.file_sha256,cancel)
                        if request.ridge is not None:
                            (payload/'inputs').mkdir()
                            _copy(request.ridge.source,payload/'inputs/ridge-source.png',request.ridge.file_sha256,cancel)
                            ridge=load_ridge(payload/'inputs/ridge-source.png',QSize(request.width,request.height))
                            mask=ridge.masks[0]
                            image=QImage(mask.pixels.translate(bytes([0]+[255]*255)),mask.width,mask.height,mask.width,QImage.Format.Format_Grayscale8).copy()
                            if not image.save(str(payload/'inputs/ridge-binary.png'),'PNG'):raise StoreError('STORE_IO_ERROR','Ridge二值副本保存失败')
                        _validate_files(payload,request,cancel)
                        files={name:dict(sha256=digest(payload/name,cancel),bytes=(payload/name).stat().st_size) for name in sorted(_names(request))}
                        manifest=dict(schema_version=1,kind='managed_image',request=request.payload(),request_sha256=request.digest,files=files)
                        _write_json(payload/'image_manifest.json',manifest)
                        self._verify_manifest(payload,request,cancel)
                        images=_path(self.store.root,'images');images.mkdir(exist_ok=True)
                        _check(cancel)
                        self._publish(payload,target)
                    _check(cancel)
                    manifest=self._verify_manifest(target,request,cancel)
                    self._finish(request,manifest,target)
                except BaseException as error:
                    self._mark_failed(request,error)
                    raise
                finally:
                    if created_payload:self._cleanup_payload(payload,request)
                # Removing only our evidence after successful publication; unexpected files are preserved.
                try:evidence.unlink();operation.rmdir()
                except OSError:LOG.warning('Completed operation evidence retained for inspection')
                return self.get_image(request.image_id)
        except StoreError:raise
        except InterruptedError as error:raise StoreError('CANCELLED','图像托管或检查已取消') from error
        except (OSError,ValueError,TypeError,KeyError) as error:raise StoreError('STORE_IO_ERROR','图像托管失败，请检查输入、目录权限和本地存储') from error

    @staticmethod
    def _publish(payload,target):
        if target.exists():raise StoreError('REVIEW_REQUIRED','目标目录已存在，未覆盖')
        os.rename(payload,target)

    def _cleanup_payload(self,payload,request):
        if not payload.exists():return
        # No recursive delete: only known files from this operation, with path/link checks.
        try:
            _reject_links(payload)
            for name in _names(request)|{'image_manifest.json'}:
                path=payload/name;_reject_links(path)
                if path.is_file():path.unlink()
            if (payload/'inputs').is_dir():(payload/'inputs').rmdir()
            payload.rmdir()
        except (OSError,StoreError):LOG.warning('Incomplete staging retained; manual inspection required')

    def inspect_image(self,image_id,cancel=None):
        cancel=cancel or Event();_check(cancel)
        row=self.get_image(image_id)
        require(row is not None,'图像记录不存在')
        if row.save_state!='ready':raise StoreError('REVIEW_REQUIRED','图像尚未完整保存，不能作为有效图像打开')
        try:
            folder=_path(self.store.root,f'images/{image_id}')
            with self.store.transaction() as connection:
                artifacts=connection.execute("SELECT * FROM artifacts WHERE image_id=? AND run_id IS NULL",(image_id,)).fetchall()
            by_kind={item['artifact_kind']:item for item in artifacts}
            if set(by_kind)!={'original_image','image_manifest'} or len(artifacts)!=2:raise StoreError('FILE_CORRUPT','图像工件登记不完整或有冲突')
            for item in artifacts:
                path=_path(self.store.root,item['relpath'])
                if not path.is_file():raise StoreError('FILE_MISSING','托管文件缺失')
                if item['save_state']!='ready' or digest(path,cancel)!=item['sha256'] or path.stat().st_size!=item['byte_size']:raise StoreError('FILE_CORRUPT','托管文件哈希或登记状态不一致')
            manifest=read_json(_path(self.store.root,by_kind['image_manifest']['relpath']))
            if not isinstance(manifest,dict) or not isinstance(manifest.get('request'),dict):raise StoreError('FILE_CORRUPT','图像清单结构无效')
            data=manifest['request'];ridge=data.get('ridge')
            from rop_insight.models.managed_image import RidgeInput
            request=ImageImportRequest(**{**data,'source':folder/'unused', 'ridge':RidgeInput(source=folder/'unused-ridge',**ridge) if ridge is not None else None}).validated()
            expected=request.payload();expected.pop('ridge')
            if any(getattr(row,key)!=value for key,value in expected.items()) or row.managed_relpath!=f'images/{image_id}/'+('original.png' if row.format=='PNG' else 'original.jpg') or by_kind['original_image']['relpath']!=row.managed_relpath or by_kind['image_manifest']['relpath']!=f'images/{image_id}/image_manifest.json':raise StoreError('FILE_CORRUPT','数据库与图像清单身份不一致')
            self._verify_manifest(folder,request,cancel)
        except InterruptedError as error:raise StoreError('CANCELLED','图像检查已取消') from error
        except (OSError,ValueError,TypeError,KeyError,StoreError) as error:
            if isinstance(error,StoreError) and error.code in ('CANCELLED','STORE_BUSY'):raise
            state='missing' if isinstance(error,FileNotFoundError) or getattr(error,'code','')=='FILE_MISSING' else 'corrupt'
            if (isinstance(error,OSError) and not isinstance(error,FileNotFoundError)) or getattr(error,'code','')=='STORE_IO_ERROR':state='unchecked'
            self._set_integrity(image_id,state)
            code={'missing':'FILE_MISSING','corrupt':'FILE_CORRUPT','unchecked':'STORE_IO_ERROR'}[state]
            raise StoreError(code,'托管图像校验失败，已阻止打开') from error
        self._set_integrity(image_id,'valid')
        return self.get_image(image_id)

    def _set_integrity(self,image_id,state):
        with self.store.transaction(write=True) as connection:
            connection.execute('UPDATE images SET integrity_state=?,last_verified_at=? WHERE image_id=?',(state,timestamp(),image_id))
            connection.execute('UPDATE artifacts SET integrity_state=?,last_verified_at=? WHERE image_id=? AND run_id IS NULL',(state,timestamp(),image_id))

    def open_image(self,image_id,cancel=None):
        cancel=cancel or Event()
        row=self.inspect_image(image_id,cancel)
        try:
            _check(cancel)
            document=ImageLoader().load(_path(self.store.root,row.managed_relpath))
            _check(cancel)
            if document.file_sha256!=row.file_sha256 or pixel_hash(document.image)!=row.rgb_pixel_sha256:raise ValueError('changed while opening')
            return document
        except (OSError,ValueError) as error:
            self._set_integrity(image_id,'missing' if isinstance(error,FileNotFoundError) else 'corrupt')
            raise StoreError('FILE_CORRUPT','托管原图在打开时发生变化，已阻止使用') from error

    def open_ridge(self,image_id,cancel=None):
        cancel=cancel or Event()
        row=self.inspect_image(image_id,cancel)
        folder=_path(self.store.root,f'images/{image_id}')
        try:
            _check(cancel)
            manifest_path=_path(self.store.root,f'images/{image_id}/image_manifest.json')
            with self.store.transaction() as connection:
                artifact=connection.execute("SELECT sha256 FROM artifacts WHERE image_id=? AND artifact_kind='image_manifest' AND run_id IS NULL",(image_id,)).fetchone()
            if artifact is None or digest(manifest_path,cancel)!=artifact['sha256']:raise ValueError('manifest changed while opening')
            metadata=read_json(manifest_path)['request']['ridge']
            if metadata is None:return None
            path=_path(self.store.root,f'images/{image_id}/inputs/ridge-source.png')
            output=load_ridge(path,QSize(row.width,row.height))
            _check(cancel)
            if output.values['file_sha256']!=metadata['file_sha256'] or hashlib.sha256(output.masks[0].pixels).hexdigest()!=metadata['binary_pixel_sha256']:
                raise ValueError('ridge changed while opening')
            return output
        except StoreError:
            raise
        except InterruptedError as error:raise StoreError('CANCELLED','Ridge读取已取消') from error
        except (OSError,ValueError,TypeError,KeyError) as error:
            self._set_integrity(image_id,'corrupt')
            raise StoreError('FILE_CORRUPT','Ridge输入在打开时发生变化，已阻止使用') from error
