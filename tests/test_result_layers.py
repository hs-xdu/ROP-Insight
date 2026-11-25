from copy import deepcopy
import math

import pytest
from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QImage, QColor

from rop_insight.inference.base import validate_output
from rop_insight.models.analysis_result import AnalysisOutput, MaskData, ClassificationData
from rop_insight.ui.image_view import ImageView
from rop_insight.ui.main_window import MainWindow
from rop_insight.services.analysis_config import parse_config
from rop_insight.services.analysis_controller import AnalysisController


def mask(name="ridge", width=20, height=10):
    return MaskData(name, width, height, bytes([0, 1] * (width * height // 2)))


@pytest.mark.parametrize("bad", [MaskData("other", 1, 1, b'\x01'),
    MaskData("ridge", 2, 2, b'\x00'), MaskData("ridge", 1, 1, b'\xff'),
    MaskData("ridge", 0, 1, b''), MaskData("ridge", True, 1, b'\x01')])
def test_invalid_masks_rejected(bad):
    with pytest.raises(ValueError):
        validate_output(AnalysisOutput({}, masks=(bad,)))


@pytest.mark.parametrize("values", [(0.1, 0.2, 0.3), (0.1, 0.2, 0.3, 0.3),
    (math.nan, 0, 0, 1), (-0.1, 0.1, 0, 1), (True, 0, 0, 0)])
def test_invalid_probabilities_rejected(values):
    with pytest.raises(ValueError):
        validate_output(AnalysisOutput({}, classification=ClassificationData(values)))


def test_layers_align_and_keep_transform(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.resize(400, 300)
    view.show()
    image = QImage(20, 10, QImage.Format.Format_RGB32)
    image.fill(QColor("orange"))
    view.set_image(image)
    original = view.item.pixmap().toImage()
    view.zoom(2)
    before = view.transform()
    center = view.mapToScene(view.viewport().rect().center())
    for name in ("ridge", "vessel"):
        source = mask(name)
        view.set_mask(source)
        assert source.pixels == mask(name).pixels
        assert view.mask_items[name].pos() == QPointF(0, 0)
        assert view.mask_items[name].boundingRect() == view.item.boundingRect()
        assert view.mask_items[name].pixmap().toImage().pixelColor(0, 0) == QColor("black")
        assert view.mask_items[name].pixmap().toImage().pixelColor(1, 0) == QColor("white")
        overlay = view.overlay_items[name].pixmap().toImage()
        assert overlay.pixelColor(0, 0).alpha() == 0
        assert overlay.pixelColor(1, 0).alpha() == 255
    for mode in ("ridge", "vessel", "overlay", "original"):
        view.display_mode = mode
        view.overlay_opacity = 0.25
        view.update_layers()
        assert view.item.isVisible() == (mode in ("original", "overlay"))
        assert view.mask_items["ridge"].isVisible() == (mode == "ridge")
        assert view.overlay_items["ridge"].isVisible() == (mode == "overlay")
        assert view.overlay_items["ridge"].opacity() == 0.25
        assert view.transform() == before
        assert view.mapToScene(view.viewport().rect().center()) == center
    assert view.item.pixmap().toImage() == original
    view.clear_image()
    assert not view.mask_items and not view.overlay_items
    with pytest.raises(ValueError):
        view.set_mask(mask())


def test_misaligned_mask_rejected(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    image = QImage(21, 10, QImage.Format.Format_RGB32)
    image.fill(0)
    view.set_image(image)
    with pytest.raises(ValueError, match="尺寸"):
        view.set_mask(mask())
    assert not view.mask_items


@pytest.mark.parametrize("width,height", [(19, 13), (20, 10)])
def test_manual_acceptance_masks_have_valid_row_alignment(width, height):
    from threading import Event
    from manual_p2_b import SyntheticAdapter
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("orange"))
    cancel = Event()
    cancel.set()
    output = SyntheticAdapter().execute(image, {}, None, cancel)
    validate_output(output, (width, height))
    assert {m.structure for m in output.masks} == {"ridge", "vessel"}


def test_results_flow_from_worker_and_clear_on_new_image(qtbot, image_file):
    class Adapter:
        supported_devices = ("cpu",)

        def validate(self, image, config):
            pass

        def execute(self, image, upstream, config, cancel):
            return AnalysisOutput({}, masks=(mask(), mask("vessel")),
                                  classification=ClassificationData((0.1, 0.2, 0.6, 0.1)))

    registry = {"test": Adapter}
    config = parse_config({"schema_version": 1, "modules": [
        {"module_id": "test_result", "enabled": True, "adapter_id": "test", "device": "cpu"}
    ]}, registry)
    controller = AnalysisController(config, registry)
    window = MainWindow(controller=controller)
    qtbot.addWidget(window)
    window.show()
    assert window.load_image(image_file(width=20, height=10))
    assert window.result_panel.prediction.text() == "分期：未提供"
    assert controller.start()
    qtbot.waitUntil(lambda: not controller.busy)
    stale = deepcopy(controller.current_run)
    panel = window.result_panel
    assert panel.prediction.text() == "预测：Stage 2"
    assert [bar.format() for bar in panel.bars] == ["10.0%", "20.0%", "60.0%", "10.0%"]
    assert set(window.view.mask_items) == {"ridge", "vessel"}
    panel.mode.setCurrentIndex(3)
    panel.opacity.setValue(30)
    assert window.view.overlay_items["ridge"].opacity() == 0.3
    panel.checks["vessel"].setChecked(False)
    assert not window.view.overlay_items["vessel"].isVisible()
    window.load_image(image_file("second.png", width=20, height=10))
    window._show_results(stale)
    assert not window.view.mask_items
    assert panel.prediction.text() == "分期：未提供"
    assert not panel.mode.model().item(1).isEnabled()
    window.clear_image()
    assert not window.view.overlay_items
