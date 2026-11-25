import json
from dataclasses import replace
from pathlib import Path
from threading import Event
import sys

import pytest
from PyQt6.QtGui import QImage, QColor

from rop_insight.inference.vascx import VascXAdapter
from rop_insight.inference.vascx_backend import sha256
from rop_insight.inference.base import validate_output
from rop_insight.services.analysis_config import ModuleConfig, load_config


@pytest.fixture
def adapter_input(tmp_path):
    image = QImage(19, 13, QImage.Format.Format_RGB32)
    image.fill(QColor("orange"))
    weights = tmp_path / "model.pt"
    weights.write_bytes(b"test model, never executed")
    config = ModuleConfig("vessel", enabled=True, adapter_id="vascx_native", device="cpu",
                          runtime_python=sys.executable, weights_path=str(weights),
                          weights_sha256=sha256(weights), model_version="test-only")
    return image, config


def test_validation_and_config_example(adapter_input):
    image, config = adapter_input
    adapter = VascXAdapter()
    adapter.validate(image, config)
    for invalid in (replace(config, runtime_python="missing"), replace(config, weights_path=None),
                    replace(config, weights_sha256=None), replace(config, preprocessing={"threshold": 0.5})):
        with pytest.raises((ValueError, FileNotFoundError, RuntimeError)):
            adapter.validate(image, invalid)
    path = Path(__file__).resolve().parents[1] / "configs" / "vascx.example.json"
    parsed = load_config(path, {"vascx_native": VascXAdapter})
    vessel = parsed.modules[1]
    assert vessel.dependencies == ()
    assert vessel.weights_sha256.startswith("bdabae77")


def test_subprocess_protocol_and_transient_input_cleanup(tmp_path, monkeypatch, adapter_input):
    image, config = adapter_input
    captured = {}

    class FakeProcess:
        returncode = 0

        def poll(self):
            return 0

    def launch(command, **options):
        captured.update(options)
        request = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
        folder = Path(request["output_dir"])
        mask = QImage(19, 13, QImage.Format.Format_Grayscale8)
        mask.fill(QColor(1, 1, 1))
        assert mask.save(str(folder / "aligned_mask.png"))
        (folder / "result.json").write_text(json.dumps({"weights_sha256": config.weights_sha256}))
        return FakeProcess()

    monkeypatch.setattr("rop_insight.inference.vascx.subprocess.Popen", launch)
    result = VascXAdapter()._execute(image, config, Event(), tmp_path / "runs")
    validate_output(result, (19, 13))
    assert result.masks[0].pixels == bytes([1] * 19 * 13)
    assert captured["env"]["HF_HUB_OFFLINE"] == "1"
    assert "PYTHONPATH" not in captured["env"]
    folder = Path(result.values["artifacts_dir"])
    assert not (folder / "input.png").exists()
    assert (folder / "aligned_mask.png").exists()


def test_cancellation_stops_only_owned_process(tmp_path, monkeypatch, adapter_input):
    image, config = adapter_input
    cancel = Event()

    class Process:
        stopped = False

        def poll(self):
            return 0 if self.stopped else None

        def terminate(self):
            self.stopped = True

        def wait(self, timeout=None):
            return 0

    process = Process()

    def launch(*args, **kwargs):
        cancel.set()
        return process

    monkeypatch.setattr("rop_insight.inference.vascx.subprocess.Popen", launch)
    result = VascXAdapter()._execute(image, config, cancel, tmp_path / "runs")
    assert process.stopped
    assert result.values == {"cancelled": True}
    assert not list((tmp_path / "runs").rglob("input.png"))


def test_backend_failure_is_reported(tmp_path, monkeypatch, adapter_input):
    image, config = adapter_input

    class FailedProcess:
        returncode = 1

        def poll(self):
            return 1

    monkeypatch.setattr("rop_insight.inference.vascx.subprocess.Popen", lambda *a, **kw: FailedProcess())
    with pytest.raises(RuntimeError, match="VascX"):
        VascXAdapter()._execute(image, config, Event(), tmp_path / "runs")
    assert not list((tmp_path / "runs").rglob("input.png"))


def test_request_write_failure_cleans_input(tmp_path, monkeypatch, adapter_input):
    image, config = adapter_input
    original_write = Path.write_text

    def fail_request(path, *args, **kwargs):
        if path.name == "request.json":
            raise OSError("disk error")
        return original_write(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_request)
    with pytest.raises(OSError, match="disk"):
        VascXAdapter()._execute(image, config, Event(), tmp_path / "runs")
    assert not list((tmp_path / "runs").rglob("input.png"))
