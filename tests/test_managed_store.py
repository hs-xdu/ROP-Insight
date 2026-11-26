"""P6-B file/SQLite publication acceptance using only synthetic temporary images."""
from contextlib import contextmanager
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from threading import Event,Thread
from uuid import uuid4
import pytest
from PyQt6.QtGui import QImage
from rop_insight.models.managed_data import CaseRequest,StoreError
from rop_insight.models.managed_image import ImageImportRequest
from rop_insight.services.database import initialize_new_store,open_store,DataStore
from rop_insight.services.data_repository import CaseRepository
from rop_insight.services.image_loader import ImageLoader
from rop_insight.services import managed_store as managed
from rop_insight.services.managed_store import ManagedImageStore
from rop_insight.services.image_import_controller import ImageImportController


def uid():return str(uuid4())


@pytest.fixture
def setup(tmp_path,image_file):
    store=initialize_new_store(tmp_path/'data')
    repo=CaseRepository(store)
    case=repo.create_case(CaseRequest(uid(),uid(),'RESEARCH-B','2026-11-26T00:00:00+00:00',default_eye='right'))
    source=image_file('中文原图.png',32,24)
    ridge=tmp_path/'Ridge.png';mask=QImage(32,24,QImage.Format.Format_Grayscale8);mask.fill(255);assert mask.save(str(ridge),'PNG')
    request=ImageImportRequest.capture(ImageLoader().load(source),case.case_id,case.revision.revision_id,'left','2026-11-26',ridge)
    return store,repo,case,request,ManagedImageStore(store)


def test_original_and_ridge_survive_source_removal_and_root_move(setup,tmp_path):
    store,repo,case,request,service=setup
    before=request.source.read_bytes();ridge_before=request.ridge.source.read_bytes()
    record=service.import_image(request)
    assert record.save_state=='ready' and record.integrity_state=='valid' and record.eye=='left'
    folder=store.root/'images'/request.image_id
    assert (store.root/record.managed_relpath).read_bytes()==before
    assert (folder/'inputs/ridge-source.png').read_bytes()==ridge_before
    binary_image=QImage(str(folder/'inputs/ridge-binary.png'))
    assert binary_image.pixelColor(0,0).red()==255 and binary_image.size()==QImage(str(folder/'inputs/ridge-source.png')).size()
    request.source.unlink();request.ridge.source.unlink()
    assert service.open_image(request.image_id).file_sha256==request.file_sha256
    ridge=service.open_ridge(request.image_id)
    assert hashlib.sha256(ridge.masks[0].pixels).hexdigest()==request.ridge.binary_pixel_sha256
    assert service.import_image(request).image_id==record.image_id
    with store.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM artifacts').fetchone()[0]==2
        assert connection.execute('SELECT count(*) FROM analysis_runs').fetchone()[0]==0
    moved=tmp_path/'moved';store.root.rename(moved)
    moved_service=ManagedImageStore(open_store(moved))
    assert moved_service.open_image(request.image_id).file_sha256==record.file_sha256
    text=(moved/'images'/request.image_id/'image_manifest.json').read_text(encoding='utf-8')
    assert str(request.source) not in text and request.original_filename in text


@pytest.mark.parametrize('fmt,suffix',[('PNG','.png'),('JPEG','.jpg'),('JPEG','.jpeg')])
def test_formats_no_ridge_and_duplicate_lookup(setup,image_file,fmt,suffix):
    store,repo,case,_,service=setup
    source=image_file('原图'+suffix,33,21,fmt)
    request=ImageImportRequest.capture(ImageLoader().load(source),case.case_id,case.revision.revision_id)
    record=service.import_image(request)
    assert service.open_ridge(request.image_id) is None
    assert service.open_image(request.image_id).format==fmt
    assert tuple(item.image_id for item in service.find_duplicates(case.case_id,request.file_sha256))==(record.image_id,)
    assert service.find_duplicates(uid(),request.file_sha256)==()
    other=replace(request,image_id=uid(),operation_id=uid(),eye='right')
    service.import_image(other)
    assert len(service.find_duplicates(case.case_id,request.file_sha256))==2


def test_case_edit_does_not_change_image_and_no_merge_across_cases(setup):
    store,repo,case,request,service=setup
    first=service.import_image(request)
    repo.update_case(case.case_id,case.revision.revision_id,CaseRequest(case.case_id,uid(),'RENAMED','2026-11-26T01:00:00+00:00',default_eye='right',default_exam_date='2026-12-01'))
    assert service.get_image(request.image_id)==first
    other=repo.create_case(CaseRequest(uid(),uid(),'OTHER','2026-11-26T00:00:00+00:00'))
    second=service.import_image(replace(request,image_id=uid(),operation_id=uid(),case_id=other.case_id,case_revision_id=other.revision.revision_id))
    assert first.case_id!=second.case_id and first.managed_relpath!=second.managed_relpath


@pytest.mark.parametrize('change',[dict(eye='right'),dict(exam_date='2026-11-27'),dict(operation_id=None),dict(ridge=None),dict(rgb_pixel_sha256='a'*64)])
def test_idempotency_conflicts_do_not_modify_ready_image(setup,change):
    store,repo,case,request,service=setup
    first=service.import_image(request)
    if change.get('operation_id','not-none') is None:change['operation_id']=uid()
    with pytest.raises(StoreError):service.import_image(replace(request,**change))
    current=service.get_image(request.image_id)
    assert current.save_state=='ready' and current.case_id==first.case_id
    assert service.open_image(request.image_id).file_sha256==request.file_sha256


@pytest.mark.parametrize('change',['source','ridge','pixels','dimensions','ridge_pixels'])
def test_changed_inputs_and_false_snapshot_never_become_ready(setup,change):
    store,repo,case,request,service=setup
    if change=='source':request.source.write_bytes(b'changed')
    if change=='ridge':request.ridge.source.write_bytes(b'changed')
    if change=='pixels':request=replace(request,rgb_pixel_sha256='a'*64)
    if change=='dimensions':request=replace(request,width=31)
    if change=='ridge_pixels':request=replace(request,ridge=replace(request.ridge,binary_pixel_sha256='a'*64))
    with pytest.raises(StoreError):service.import_image(request)
    assert service.get_image(request.image_id).save_state=='write_failed'
    assert not (store.root/'images'/request.image_id).exists()
    assert service.incomplete_images()[0].image_id==request.image_id
    with store.transaction() as connection:assert connection.execute('SELECT count(*) FROM artifacts').fetchone()[0]==0


@pytest.mark.parametrize('target',['original','ridge','binary','manifest','manifest_identity'])
def test_missing_or_corrupt_file_blocks_read_and_updates_integrity(setup,target):
    store,repo,case,request,service=setup
    row=service.import_image(request);folder=store.root/'images'/row.image_id
    path={'original':folder/'original.png','ridge':folder/'inputs/ridge-source.png','binary':folder/'inputs/ridge-binary.png','manifest':folder/'image_manifest.json','manifest_identity':folder/'image_manifest.json'}[target]
    if target in ('original','manifest'):path.unlink()
    else:path.write_bytes(b'bad')
    with pytest.raises(StoreError):service.open_image(row.image_id)
    record=service.get_image(row.image_id)
    assert record.integrity_state in ('missing','corrupt')
    with pytest.raises(StoreError):service.import_image(request)
    assert record.save_state=='ready'  # historical publication preserved; validity is separately revoked


@pytest.mark.parametrize('failure',['copy','publish','insert','commit'])
def test_failure_and_published_db_failure_retry_consistency(setup,monkeypatch,failure):
    store,repo,case,request,service=setup
    original_transaction=DataStore.transaction
    with monkeypatch.context() as patch:
        if failure=='copy':patch.setattr(managed,'_copy',lambda *args:(_ for _ in ()).throw(PermissionError('injected')))
        elif failure=='publish':patch.setattr(service,'_publish',lambda *args:(_ for _ in ()).throw(PermissionError('injected')))
        else:
            @contextmanager
            def injected(self,write=False):
                with original_transaction(self,write=write) as connection:
                    if write and failure=='insert':connection.execute("CREATE TEMP TRIGGER fail_artifact BEFORE INSERT ON artifacts BEGIN SELECT RAISE(ABORT,'injected'); END")
                    yield connection
                    if write and failure=='commit' and connection.execute('SELECT count(*) FROM artifacts').fetchone()[0]:
                        connection.execute('INSERT INTO cases(case_id,case_code,case_code_key,current_revision_id,created_at,updated_at) VALUES (?,?,?,?,?,?)',(uid(),'BAD','bad',uid(),'now','now'))
            patch.setattr(DataStore,'transaction',injected)
        with pytest.raises(StoreError):service.import_image(request)
    row=service.get_image(request.image_id)
    assert row.save_state=='write_failed'
    with store.transaction() as connection:assert connection.execute('SELECT count(*) FROM artifacts').fetchone()[0]==0
    target=store.root/'images'/request.image_id
    assert target.exists()==(failure in ('insert','commit'))
    if target.exists():request.source.unlink();request.ridge.source.unlink()
    assert service.import_image(request).save_state=='ready'
    assert service.open_image(request.image_id).file_sha256==request.file_sha256
    with store.transaction() as connection:assert connection.execute('SELECT count(*) FROM artifacts').fetchone()[0]==2


def test_cancel_during_copy_and_retry_without_false_ready(setup,monkeypatch):
    store,repo,case,request,service=setup
    cancel=Event();original=managed._copy
    def copy_then_cancel(*args):original(*args);cancel.set()
    with monkeypatch.context() as patch:
        patch.setattr(managed,'_copy',copy_then_cancel)
        with pytest.raises(StoreError) as caught:service.import_image(request,cancel)
        assert caught.value.code=='CANCELLED'
    assert service.get_image(request.image_id).save_state=='write_failed'
    assert not (store.root/'images'/request.image_id).exists()
    assert service.import_image(request).save_state=='ready'


def test_cancel_before_start_and_cancelled_inspection_do_not_corrupt(setup,monkeypatch):
    store,repo,case,request,service=setup
    event=Event();event.set()
    with pytest.raises(StoreError):service.import_image(request,event)
    assert service.get_image(request.image_id) is None
    service.import_image(request)
    with monkeypatch.context() as patch:
        patch.setattr(managed,'digest',lambda *args:(_ for _ in ()).throw(InterruptedError('cancel')))
        with pytest.raises(StoreError) as caught:service.inspect_image(request.image_id)
        assert caught.value.code=='CANCELLED'
    assert service.get_image(request.image_id).integrity_state=='valid'


def test_stale_lock_and_unknown_staging_or_published_directory_not_deleted(setup):
    store,repo,case,request,service=setup
    staging=store.root/'.staging';staging.mkdir();lock=staging/'.image-writer.lock';lock.write_text('owner')
    with pytest.raises(StoreError) as caught:service.import_image(request)
    assert caught.value.code=='STORE_BUSY' and lock.read_text()=='owner'
    lock.unlink()
    # First make an incomplete row and its immutable request evidence.
    source=request.source;source.rename(source.with_suffix('.moved'))
    with pytest.raises(StoreError):service.import_image(request)
    operation=staging/request.operation_id;payload=operation/'payload';payload.mkdir();(payload/'keep.txt').write_text('not ours')
    with pytest.raises(StoreError) as caught:service.import_image(request)
    assert caught.value.code=='REVIEW_REQUIRED' and (payload/'keep.txt').read_text()=='not ours'
    (payload/'keep.txt').unlink();payload.rmdir()
    target=store.root/'images'/request.image_id;target.mkdir(parents=True);(target/'keep.txt').write_text('published')
    with pytest.raises(StoreError):service.import_image(request)
    assert (target/'keep.txt').read_text()=='published'


def test_concurrent_writers_return_busy_without_wrong_association(setup,monkeypatch):
    store,repo,case,request,service=setup
    entered=Event();release=Event();original=managed._copy;outcomes=[]
    def blocking(*args):
        entered.set();assert release.wait(3);return original(*args)
    monkeypatch.setattr(managed,'_copy',blocking)
    def run():
        try:outcomes.append(service.import_image(request))
        except Exception as error:outcomes.append(error)
    worker=Thread(target=run);worker.start()
    assert entered.wait(3)
    try:
        with pytest.raises(StoreError) as caught:service.import_image(replace(request,image_id=uid(),operation_id=uid()))
        assert caught.value.code=='STORE_BUSY'
    finally:release.set();worker.join(5)
    assert len(outcomes)==1 and outcomes[0].image_id==request.image_id


def test_background_import_cancel_and_safe_thread_finish(setup,qtbot,monkeypatch):
    store,repo,case,request,service=setup
    original=managed._copy;entered=Event()
    def waiting(source,target,expected,cancel):
        entered.set();cancel.wait(3);return original(source,target,expected,cancel)
    monkeypatch.setattr(managed,'_copy',waiting)
    controller=ImageImportController(service)
    outcomes=[];controller.finished.connect(lambda record,error:outcomes.append((record,error)))
    assert controller.start_request(request)
    qtbot.waitUntil(entered.is_set,timeout=3000)
    assert not controller.start_request(request)
    controller.cancel();qtbot.waitUntil(lambda:not controller.busy,timeout=5000)
    assert outcomes[0][0] is None and 'CANCELLED' in outcomes[0][1]
    assert service.get_image(request.image_id).save_state=='write_failed'


@pytest.mark.parametrize('patch',[dict(image_id='../x'),dict(eye='both'),dict(exam_date='2026-02-30'),dict(width=0),dict(original_filename='../x.png'),dict(format='BMP'),dict(file_sha256='X'*64)])
def test_invalid_requests_create_no_image(setup,patch):
    store,repo,case,request,service=setup
    with pytest.raises(StoreError):service.import_image(replace(request,**patch))
    with store.transaction() as connection:assert connection.execute('SELECT count(*) FROM images').fetchone()[0]==0


def test_case_revision_mismatch_and_operation_collision(setup):
    store,repo,case,request,service=setup
    with pytest.raises(StoreError):service.import_image(replace(request,case_id=uid()))
    assert service.get_image(request.image_id) is None
    service.import_image(request)
    with pytest.raises(StoreError) as caught:service.import_image(replace(request,image_id=uid()))
    assert caught.value.code=='IDEMPOTENCY_CONFLICT'
    with store.transaction() as connection:assert connection.execute('SELECT count(*) FROM images').fetchone()[0]==1


def test_oversized_input_and_permission_check_revoke_validity(setup,monkeypatch):
    store,repo,case,request,service=setup
    with monkeypatch.context() as patch:
        patch.setattr(managed,'MAX_FILE_BYTES',10)
        with pytest.raises(StoreError):service.import_image(request)
    assert service.get_image(request.image_id).save_state=='write_failed'
    service.import_image(request)
    with monkeypatch.context() as patch:
        patch.setattr(managed,'digest',lambda *args:(_ for _ in ()).throw(PermissionError('denied')))
        with pytest.raises(StoreError) as caught:service.inspect_image(request.image_id)
        assert caught.value.code=='STORE_IO_ERROR'
    assert service.get_image(request.image_id).integrity_state=='unchecked'
    assert service.inspect_image(request.image_id).integrity_state=='valid'


@pytest.mark.parametrize('path',['../outside','C:/outside.png','https://outside/file','images/../../outside'])
def test_tampered_database_paths_cannot_open_outside_store(setup,path,tmp_path):
    store,repo,case,request,service=setup
    service.import_image(request)
    # Simulate external database corruption with check constraints disabled, not a supported writer API.
    with store.transaction(write=True) as connection:
        connection.execute('PRAGMA ignore_check_constraints=ON')
        connection.execute("UPDATE artifacts SET relpath=? WHERE artifact_kind='original_image'",(path,))
    with pytest.raises(StoreError):service.open_image(request.image_id)
    assert service.get_image(request.image_id).integrity_state=='corrupt'


def test_tampered_identity_and_incomplete_artifact_rows_block_read(setup):
    store,repo,case,request,service=setup
    service.import_image(request)
    with store.transaction(write=True) as connection:connection.execute("UPDATE images SET eye='right' WHERE image_id=?",(request.image_id,))
    with pytest.raises(StoreError):service.inspect_image(request.image_id)
    assert service.get_image(request.image_id).integrity_state=='corrupt'
    with store.transaction(write=True) as connection:
        connection.execute("UPDATE images SET eye='left' WHERE image_id=?",(request.image_id,))
        connection.execute("DELETE FROM artifacts WHERE artifact_kind='image_manifest'")
    with pytest.raises(StoreError):service.inspect_image(request.image_id)


def test_existing_junction_in_managed_path_is_rejected_without_touching_target(setup,tmp_path):
    import os,subprocess
    store,repo,case,request,service=setup
    outside=tmp_path/'outside';outside.mkdir();(outside/'keep.txt').write_text('unchanged')
    link=store.root/'images'
    subprocess.run(['powershell','-NoProfile','-Command','New-Item -ItemType Junction -Path $env:ROP_LINK -Target $env:ROP_TARGET | Out-Null'],
        env={**os.environ,'ROP_LINK':str(link),'ROP_TARGET':str(outside)},capture_output=True,check=True)
    try:
        with pytest.raises(StoreError):service.import_image(request)
        assert (outside/'keep.txt').read_text()=='unchanged' and list(outside.iterdir())==[outside/'keep.txt']
    finally:link.rmdir()


def test_pending_request_evidence_conflict_and_interrupted_operation_detection(setup):
    store,repo,case,request,service=setup
    request.source.unlink()
    with pytest.raises(StoreError):service.import_image(request)
    assert service.incomplete_images()[0].save_state=='write_failed'
    # Same image identity with a changed Ridge payload must not reuse a failed operation.
    with pytest.raises(StoreError) as caught:service.import_image(replace(request,ridge=None))
    assert caught.value.code=='IDEMPOTENCY_CONFLICT'
    evidence=store.root/'.staging'/request.operation_id/'request.json';evidence.unlink()
    with pytest.raises(StoreError) as caught:service.import_image(request)
    assert caught.value.code=='REVIEW_REQUIRED'


def test_background_controller_success_runs_off_gui_thread(setup,qtbot,monkeypatch):
    from PyQt6.QtCore import QThread
    from PyQt6.QtWidgets import QApplication
    store,repo,case,request,service=setup
    original=service.import_image;threads=[];results=[]
    def checked(*args):threads.append(QThread.currentThread());return original(*args)
    monkeypatch.setattr(service,'import_image',checked)
    controller=ImageImportController(service);controller.finished.connect(lambda result,error:results.append((result,error,QThread.currentThread())))
    controller.start_request(request);qtbot.waitUntil(lambda:not controller.busy,timeout=5000)
    assert threads[0]!=QApplication.instance().thread()
    assert results[0][0].image_id==request.image_id and results[0][1]=='' and results[0][2]==QApplication.instance().thread()


def test_corruption_during_publish_is_not_registered_ready(setup,monkeypatch):
    store,repo,case,request,service=setup
    original=service._publish
    def corrupt(payload,target):
        original(payload,target);(target/'original.png').write_bytes(b'changed during publication')
    monkeypatch.setattr(service,'_publish',corrupt)
    with pytest.raises(StoreError):service.import_image(request)
    assert service.get_image(request.image_id).save_state=='write_failed'
    with store.transaction() as connection:assert connection.execute('SELECT count(*) FROM artifacts').fetchone()[0]==0


def test_original_change_between_inspection_and_open_is_blocked(setup,monkeypatch):
    store,repo,case,request,service=setup;service.import_image(request)
    original=service.inspect_image
    def changed(*args):
        row=original(*args)
        image=QImage(32,24,QImage.Format.Format_RGB32);image.fill(0xffff0000);image.save(str(store.root/row.managed_relpath),'PNG')
        return row
    monkeypatch.setattr(service,'inspect_image',changed)
    with pytest.raises(StoreError):service.open_image(request.image_id)
    assert service.get_image(request.image_id).integrity_state=='corrupt'


def test_undeclared_ridge_file_is_never_used(setup):
    store,repo,case,request,service=setup
    request=replace(request,ridge=None);service.import_image(request)
    inputs=store.root/'images'/request.image_id/'inputs';inputs.mkdir()
    mask=QImage(32,24,QImage.Format.Format_Grayscale8);mask.fill(255);mask.save(str(inputs/'ridge-source.png'),'PNG')
    assert service.open_ridge(request.image_id) is None


def test_ridge_changed_between_inspection_and_open_is_rejected(setup,monkeypatch):
    store,repo,case,request,service=setup;service.import_image(request)
    original=service.inspect_image
    def changed(*args):
        row=original(*args)
        mask=QImage(32,24,QImage.Format.Format_Grayscale8);mask.fill(0)
        mask.save(str(store.root/'images'/row.image_id/'inputs/ridge-source.png'),'PNG')
        return row
    monkeypatch.setattr(service,'inspect_image',changed)
    with pytest.raises(StoreError):service.open_ridge(request.image_id)
    assert service.get_image(request.image_id).integrity_state=='corrupt'


def test_malformed_uncommitted_manifest_is_detected_not_repaired(setup,monkeypatch):
    store,repo,case,request,service=setup
    with monkeypatch.context() as patch:
        patch.setattr(service,'_finish',lambda *args:(_ for _ in ()).throw(StoreError('STORE_IO_ERROR','injected')))
        with pytest.raises(StoreError):service.import_image(request)
    manifest_path=store.root/'images'/request.image_id/'image_manifest.json'
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'));manifest['files']=list(manifest['files'])
    manifest_path.write_text(json.dumps(manifest),encoding='utf-8')
    with pytest.raises(StoreError) as caught:service.import_image(request)
    assert caught.value.code=='FILE_CORRUPT'
    assert service.get_image(request.image_id).save_state=='write_failed'
