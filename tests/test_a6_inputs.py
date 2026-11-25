from pathlib import Path

import pytest
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QImage, QColor

from rop_insight.inference.imported_ridge import load_ridge, ImportedRidgeAdapter
from rop_insight.services.analysis_config import parse_config
from rop_insight.services.analysis_controller import AnalysisController
from rop_insight.ui.main_window import MainWindow


def save_mask(path, value, width=19, height=13):
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(value, value, value))
    assert image.save(str(path))


@pytest.mark.parametrize("value", [0, 1, 255])
def test_imported_mask_normalization(tmp_path, value):
    path = tmp_path / "ridge.png"
    save_mask(path, value)
    output = load_ridge(path, QSize(19, 13))
    assert output.masks[0].pixels == bytes([int(value > 0)] * 19 * 13)
    assert output.values["source"] == "user_imported_ridge"


@pytest.mark.parametrize("case", ["gray", "color", "size", "missing", "extension", "transparent"])
def test_bad_ridge_inputs_rejected(tmp_path, case):
    path = tmp_path / "ridge.png"
    save_mask(path, 100 if case == "gray" else 255)
    if case in ("color", "transparent"):
        image = QImage(19, 13, QImage.Format.Format_ARGB32)
        image.fill(QColor("red") if case == "color" else QColor(0, 0, 0, 0))
        image.save(str(path))
    if case == "missing":
        path = tmp_path / "missing.png"
    if case == "extension":
        path = tmp_path / "ridge.jpg"
    with pytest.raises(ValueError):
        load_ridge(path, QSize(20, 13) if case == "size" else QSize(19, 13))


def test_imported_input_flow_and_image_invalidation(qtbot, image_file, tmp_path):
    registry = {"imported_ridge": ImportedRidgeAdapter}
    config = parse_config({"schema_version": 1, "modules": [{
        "module_id": "ridge", "enabled": True, "adapter_id": "imported_ridge", "device": "cpu"
    }]}, registry)
    controller = AnalysisController(config, registry)
    window = MainWindow(controller=controller)
    qtbot.addWidget(window)
    window.show()
    window.load_image(image_file(width=19, height=13))
    assert not window.analyze_button.isEnabled()
    path = tmp_path / "provided.png"
    save_mask(path, 255)
    assert window.import_ridge(path)
    assert window.analyze_button.isEnabled()
    assert "ridge" in window.view.mask_items
    assert controller.start()
    qtbot.waitUntil(lambda: not controller.busy)
    assert controller.current_run.modules["ridge"].output.values["source"] == "user_imported_ridge"
    assert not window.import_ridge(tmp_path / "missing.png")
    assert "ridge" in controller.input_outputs
    window.load_image(image_file("new.png", width=19, height=13))
    assert not controller.input_outputs
    assert not window.analyze_button.isEnabled()
    assert not window.view.mask_items


def test_a6_request_requires_both_masks(tmp_path):
    from rop_insight.inference.a6 import A6Adapter
    from rop_insight.services.analysis_config import ModuleConfig
    with pytest.raises(ValueError, match="ridge"):
        A6Adapter().make_request(tmp_path, ModuleConfig("staging"), {})
