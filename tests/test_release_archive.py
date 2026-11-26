"""Release metadata and archive checks, independent of local editable-install metadata."""
from pathlib import Path
import re,subprocess,tomllib
from rop_insight import __version__

ROOT=Path(__file__).resolve().parents[1]


def test_declared_release_version_matches_source():
    package=tomllib.loads((ROOT/'pyproject.toml').read_text(encoding='utf-8'))
    assert package['project']['version']==__version__=='0.2.0'
    assert '研究预发布' in (ROOT/'docs/releases/v0.2.0.md').read_text(encoding='utf-8')


def test_new_analysis_and_report_use_source_version(qtbot,image_file,monkeypatch):
    import importlib.metadata
    from rop_insight.services.analysis_controller import AnalysisController
    from rop_insight.services.analysis_config import parse_config
    from rop_insight.models.analysis_result import AnalysisOutput
    from rop_insight.services.image_loader import ImageLoader
    from rop_insight.services.result_exporter import ExportSnapshot
    from rop_insight.services.report_builder import build_report
    monkeypatch.setattr(importlib.metadata,'version',lambda *args:'0.1.0')
    class Adapter:
        supported_devices=('cpu',)
        def validate(self,image,config):pass
        def execute(self,image,upstream,config,cancel):return AnalysisOutput({})
    config=parse_config(dict(schema_version=1,modules=[dict(module_id='ridge',enabled=True,adapter_id='test',device='cpu')]),{'test':Adapter})
    controller=AnalysisController(config,{'test':Adapter})
    controller.set_document(ImageLoader().load(image_file('release.png',24,16)))
    assert controller.start()
    qtbot.waitUntil(lambda:not controller.busy,timeout=5000)
    assert controller.current_run.software_version==__version__
    report=build_report(ExportSnapshot.capture(controller.context,controller.current_run))
    assert report.data['generator']['software_version']==__version__
    assert report.data['source']['run']['software_version']==__version__


def test_archived_docs_and_relative_markdown_links_resolve():
    assert not (ROOT/'tests/manual_p2_a.py').exists()
    assert (ROOT/'tests/manual_p2_b.py').is_file()
    assert (ROOT/'docs/archive/P5_ROLLBACK.md').is_file()
    for path in [ROOT/'README.md',*list((ROOT/'docs').rglob('*.md'))]:
        for target in re.findall(r'\]\(([^)]+\.md)(?:#[^)]*)?\)',path.read_text(encoding='utf-8-sig')):
            if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:',target) or target.startswith('/'):continue
            assert (path.parent/target).is_file(),(path,target)


def test_private_research_files_are_not_tracked():
    ignore=(ROOT/'.gitignore').read_text(encoding='utf-8')
    for item in ('*.db','*.sqlite3','*.bundle','*.pt','**/records/'):assert item in ignore
    git=subprocess.run(['git','ls-files','-z'],cwd=ROOT,capture_output=True,check=False)
    if git.returncode:return  # Source ZIPs have no Git index; ignore rules still checked above.
    for name in git.stdout.decode('utf-8').split('\x00'):
        if not name:continue
        path=Path(name)
        assert not name.startswith(('.runtime/','.venv/'))
        assert not name.endswith('.local.json')
        assert path.suffix.lower() not in ('.db','.sqlite','.sqlite3','.bundle','.pt','.pth','.onnx','.pkl')
