from dataclasses import replace
import hashlib
import json
from pathlib import Path
from threading import Event

from PyQt6.QtGui import QColor
import pytest

from rop_insight.models.analysis_result import (AnalysisRun, ModuleResult, ModuleState, ModuleError,
    AnalysisOutput, MaskData, ClassificationData, ImageContext)
from rop_insight.services.analysis_config import AnalysisConfig, ModuleConfig
from rop_insight.services.image_loader import ImageLoader
from rop_insight.services import result_exporter as exporter
from rop_insight.services.result_exporter import ExportSnapshot, ExportError, export_bundle
from rop_insight.ui.image_view import ImageView
from rop_insight.ui.main_window import MainWindow


@pytest.fixture
def completed(image_file):
    document=ImageLoader().load(image_file('private_patient.png',13,9))
    context=ImageContext.from_document(document)
    mask=MaskData('ridge',13,9,bytes([0,1]*58+[1]))
    cfg=ModuleConfig('ridge',True,'test','original',weights_sha256='a'*64,device='cpu',
        weights_path=r'E:\secret\model.pt',runtime_python=r'C:\private\python.exe',
        source_hashes={r'E:\private\code.py':'b'*64})
    result=ModuleResult('ridge',ModuleState.SUCCESS,.25,AnalysisOutput(
        dict(source='user_imported_ridge',file_sha256='c'*64,
             metrics={'empty':dict(value=None,status='unavailable',reason='empty')},
             artifacts_dir=r'E:\secret\patient',input_path='/private/patient.png'),(mask,),
        ClassificationData((.1,.2,.3,.4))),model_version='original')
    run=AnalysisRun('run','unused',AnalysisConfig((cfg,)),{'ridge':result},finished_at='done',
        status='success',software_version='test',code_revision='d'*40,code_dirty=False)
    run.image_id=context.image_id
    return context,run


def test_roundtrip_hashes_binary_pixels_and_private_paths(completed,tmp_path):
    from PyQt6.QtGui import QImage
    context,run=completed
    destination=export_bundle(ExportSnapshot.capture(context,run),tmp_path)
    text=(destination/'result.json').read_text(encoding='utf-8')
    data=json.loads(text)
    assert data['image']['file_sha256']==context.file_sha256
    color=context.image.pixelColor(0,0)
    assert data['image']['rgb_pixel_sha256']==hashlib.sha256(bytes([color.red(),color.green(),color.blue()])*117).hexdigest()
    assert data['run']['code_revision']=='d'*40
    assert data['modules']['ridge']['deep_classification']['probabilities']==[.1,.2,.3,.4]
    assert data['modules']['ridge']['values']['metrics']['empty']['value'] is None
    assert all(s not in text for s in ['E:\\','C:\\','/private','private_patient','artifacts_dir'])
    assert set(p.name for p in destination.iterdir())=={'result.json','ridge_mask.png','analysis_overlay.png'}
    image=QImage(str(destination/'ridge_mask.png'))
    assert (image.width(),image.height())==(13,9)
    assert [image.pixelColor(x,y).red() for y in range(9) for x in range(13)]==[
        p*255 for p in run.modules['ridge'].output.masks[0].pixels]
    for name,artifact in data['artifacts'].items():
        assert hashlib.sha256((destination/name).read_bytes()).hexdigest()==artifact['sha256']


def test_snapshot_survives_source_deletion_and_result_mutation(completed,tmp_path):
    context,run=completed
    snapshot=ExportSnapshot.capture(context,run)
    Path(context.source).unlink()
    context.image.fill(QColor('green'))
    run.modules['ridge'].output.values['source']='changed'
    folder=export_bundle(snapshot,tmp_path)
    data=json.loads((folder/'result.json').read_text(encoding='utf-8'))
    assert data['image']['file_sha256']==snapshot.context.file_sha256
    assert data['modules']['ridge']['values']['source']=='user_imported_ridge'
    assert exporter.pixel_hash(context.image)!=data['image']['rgb_pixel_sha256']


def test_png_independent_of_zoom_pan_opacity_and_mode(completed,tmp_path,qtbot):
    context,run=completed
    view=ImageView();qtbot.addWidget(view);view.set_image(context.image)
    view.set_mask(run.modules['ridge'].output.masks[0])
    first=export_bundle(ExportSnapshot.capture(context,run),tmp_path)
    view.zoom(3);view.centerOn(2,3);view.overlay_opacity=.1;view.display_mode='ridge';view.update_layers()
    second=export_bundle(ExportSnapshot.capture(context,run),tmp_path)
    assert first!=second
    assert (first/'analysis_overlay.png').read_bytes()==(second/'analysis_overlay.png').read_bytes()


def test_partial_failure_keeps_success_and_sanitizes_errors(completed,tmp_path):
    context,run=completed
    run.config=AnalysisConfig((*run.config.modules,ModuleConfig('staging',True,'test',device='cpu')))
    run.modules['staging']=ModuleResult('staging',ModuleState.FAILED,error=ModuleError('execution_failed',r'bad E:\patient\image.png'))
    run.status='partial_success'
    folder=export_bundle(ExportSnapshot.capture(context,run),tmp_path)
    data=json.loads((folder/'result.json').read_text(encoding='utf-8'))
    assert data['run']['status']=='partial_success'
    assert data['modules']['staging']['state']=='failed'
    assert data['modules']['staging']['masks']==[]
    assert 'patient' not in json.dumps(data)
    assert (folder/'ridge_mask.png').is_file()


@pytest.mark.parametrize('state',['failed','cancelled'])
def test_terminal_no_output_exports_status_only(completed,tmp_path,state):
    context,run=completed
    run.status=state;run.modules['ridge'].state=ModuleState(state);run.modules['ridge'].output=None
    folder=export_bundle(ExportSnapshot.capture(context,run),tmp_path)
    data=json.loads((folder/'result.json').read_text(encoding='utf-8'))
    assert not data['artifacts'] and data['visualization'] is None
    assert list(folder.iterdir())==[folder/'result.json']


def test_running_mismatched_and_missing_results_rejected(completed):
    context,run=completed
    for c,r in [(None,run),(context,None),(replace(context,image_id='other'),run),(context,replace(run,status='running'))]:
        with pytest.raises(ExportError):ExportSnapshot.capture(c,r)


@pytest.mark.parametrize('failure',['png','json','publish','permission'])
def test_failed_export_publishes_nothing(completed,tmp_path,monkeypatch,failure):
    def fail(*args,**kwargs):raise PermissionError('simulated disk/permission error')
    if failure=='png':monkeypatch.setattr(exporter,'_save_png',fail)
    elif failure=='json':monkeypatch.setattr(exporter.json,'dump',fail)
    elif failure=='publish':monkeypatch.setattr(exporter.os,'rename',fail)
    else:monkeypatch.setattr(exporter.tempfile,'mkdtemp',fail)
    before=set(tmp_path.iterdir())
    with pytest.raises(OSError):export_bundle(ExportSnapshot.capture(*completed),tmp_path)
    assert set(tmp_path.iterdir())==before


def test_existing_destination_never_overwritten(completed,tmp_path,monkeypatch):
    class Constant:
        hex='constant'
    class Clock:
        @staticmethod
        def now(*args):return Clock()
        def strftime(self,*args):return 'fixed-'
    monkeypatch.setattr(exporter,'uuid4',Constant)
    monkeypatch.setattr(exporter,'datetime',Clock)
    snapshot=ExportSnapshot.capture(*completed)
    folder=export_bundle(snapshot,tmp_path)
    before=(folder/'result.json').read_bytes()
    with pytest.raises(FileExistsError):export_bundle(snapshot,tmp_path)
    assert (folder/'result.json').read_bytes()==before
    assert not list(tmp_path.glob('.rop-export-*'))


def test_export_thread_uses_snapshot_and_close_waits(completed,tmp_path,qtbot,monkeypatch):
    from rop_insight.services import export_controller
    context,run=completed
    entered,release=Event(),Event()
    original=export_controller.export_bundle
    def slow(snapshot,parent):
        entered.set();release.wait(5)
        return original(snapshot,parent)
    monkeypatch.setattr(export_controller,'export_bundle',slow)
    window=MainWindow();qtbot.addWidget(window);window.show()
    window.analysis.context=context;window.analysis.current_run=run;window._update_analysis()
    assert window.export_button.isEnabled()
    assert window.export_results(tmp_path)
    qtbot.waitUntil(entered.is_set)
    assert not window.export_button.isEnabled()
    assert not window.export_results(tmp_path)
    window.clear_image()
    window.close();assert window.isVisible()
    release.set()
    qtbot.waitUntil(lambda:not window.exporter.busy and not window.isVisible())
    data=json.loads(next(tmp_path.glob('rop-*/result.json')).read_text(encoding='utf-8'))
    assert data['image']['image_id']==context.image_id


def test_export_failure_allows_retry(completed,tmp_path,qtbot,monkeypatch):
    from rop_insight.services import export_controller
    context,run=completed
    window=MainWindow();qtbot.addWidget(window)
    window.analysis.context=context;window.analysis.current_run=run;window._update_analysis()
    original=export_controller.export_bundle
    def fail(*args):raise OSError('disk full')
    monkeypatch.setattr(export_controller,'export_bundle',fail)
    with qtbot.waitSignal(window.exporter.finished):assert window.export_results(tmp_path)
    assert window.export_button.isEnabled()
    assert '导出失败' in window.error_label.text()
    monkeypatch.setattr(export_controller,'export_bundle',original)
    with qtbot.waitSignal(window.exporter.finished):assert window.export_results(tmp_path)
    assert not window.error_label.isVisible()
    assert len(list(tmp_path.glob('rop-*')))==1
