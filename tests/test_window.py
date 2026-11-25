import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QApplication, QFileDialog

from rop_insight.ui.main_window import MainWindow, LoadState


@pytest.fixture
def window(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    return window


def assert_fits(view):
    item_rect = view.mapFromScene(view.item.sceneBoundingRect()).boundingRect()
    assert item_rect.width() <= view.viewport().width() + 2
    assert item_rect.height() <= view.viewport().height() + 2
    assert view.transform().m11() == pytest.approx(view.transform().m22())


def test_initial_state(window):
    assert window.state == LoadState.EMPTY
    assert window.document is None
    assert not window.clear_button.isEnabled()
    assert not window.zoom_in_button.isEnabled()
    assert not window.fit_button.isEnabled()


@pytest.mark.parametrize("size", [(1180, 780), (800, 560)])
def test_sidebar_geometry_survives_repeated_long_names(window, qtbot, image_file, monkeypatch, size):
    from PyQt6.QtWidgets import QScrollArea
    window.resize(*size)
    scroll = window.findChild(QScrollArea)
    sidebar = scroll.widget()
    controls = (window.import_button, window.clear_button,
                window.analyze_button, window.cancel_analysis_button)
    QApplication.processEvents()
    initial = [(button.x(), button.width(), button.height()) for button in controls]
    names = ["short.png", "1区2期_20240273-20240807_OS_" + "189fc1ef-4309-40c4-9d3e-670baf29e855" + ".png",
             "a" * 150 + ".png", "short-again.png"]
    for name in names:
        path = image_file(name)
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, p=path: (str(p), ""))
        qtbot.mouseClick(window.import_button, Qt.MouseButton.LeftButton)
        QApplication.processEvents()
        assert sidebar.width() == 250
        assert scroll.horizontalScrollBar().maximum() == 0
        assert [(b.x(), b.width(), b.height()) for b in controls] == initial
        assert window.name_label.text() == name
        assert window.name_label.toolTip() == str(path.resolve())
        assert window.name_label.width() <= sidebar.width() - 36
        assert window.name_label.height() >= window.name_label.heightForWidth(window.name_label.width())
        for button in controls:
            assert button.geometry().right() < sidebar.width()
    window.clear_image()
    QApplication.processEvents()
    assert [(b.x(), b.width(), b.height()) for b in controls] == initial


def test_long_analysis_error_does_not_widen_sidebar(window):
    from PyQt6.QtWidgets import QScrollArea
    scroll = window.findChild(QScrollArea)
    window.analysis_label.setText("模块异常：" + "very_long_model_identifier_" * 12)
    QApplication.processEvents()
    assert scroll.widget().width() == 250
    assert window.analyze_button.geometry().right() < 250


@pytest.mark.parametrize("width,height", [(1400, 600), (600, 1400)])
def test_fit_and_resize(window, image_file, qtbot, width, height):
    assert window.load_image(image_file(width=width, height=height))
    assert_fits(window.view)
    window.resize(900, 600)
    QApplication.processEvents()
    assert_fits(window.view)
    qtbot.mouseClick(window.zoom_in_button, Qt.MouseButton.LeftButton)
    scale = window.view.scale_factor
    window.resize(1100, 720)
    QApplication.processEvents()
    assert window.view.scale_factor == pytest.approx(scale)
    qtbot.mouseClick(window.fit_button, Qt.MouseButton.LeftButton)
    assert window.view.fit_mode
    assert_fits(window.view)


def test_selection_replacement_failure_cancel_clear(window, image_file, tmp_path, qtbot, monkeypatch):
    path = image_file()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: (str(path), ""))
    qtbot.mouseClick(window.import_button, Qt.MouseButton.LeftButton)
    assert window.state == LoadState.READY
    assert window.name_label.text() == path.name
    assert window.resolution_label.text() == "1200 × 800 px"
    assert window.format_label.text() == "PNG"
    document = window.document
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: ("", ""))
    qtbot.mouseClick(window.import_button, Qt.MouseButton.LeftButton)
    assert window.document is document
    assert window.state == LoadState.READY
    assert not window.load_image(tmp_path / "missing.png")
    assert window.state == LoadState.FAILED
    assert window.document is document
    assert window.name_label.text() == path.name
    assert window.error_label.isVisible()
    assert "上一张" in window.error_label.text()
    replacement = image_file("replacement.jpeg", 200, 300, "JPEG")
    assert window.load_image(replacement)
    assert window.format_label.text() == "JPEG"
    assert window.resolution_label.text() == "200 × 300 px"
    assert window.view.fit_mode
    assert not window.error_label.isVisible()
    qtbot.mouseClick(window.clear_button, Qt.MouseButton.LeftButton)
    assert window.document is None
    assert window.view.item is None
    assert window.state == LoadState.EMPTY
    assert window.name_label.text() == "—"
    assert window.name_label.toolTip() == ""
    assert window.zoom_label.text() == "—"
    assert not window.clear_button.isEnabled()


def test_first_failure_can_recover(window, image_file, tmp_path):
    assert not window.load_image(tmp_path / "missing.png")
    assert window.view.item is None
    assert not window.zoom_in_button.isEnabled()
    assert window.load_image(image_file())
    assert window.state == LoadState.READY


def test_loading_state_and_keyboard_import(window, image_file, monkeypatch, qtbot):
    path = image_file()
    original_load = window.loader.load

    def inspect_loading(path):
        assert window.state == LoadState.LOADING
        assert "加载中" in window.statusBar().currentMessage()
        return original_load(path)

    monkeypatch.setattr(window.loader, "load", inspect_loading)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: (str(path), ""))
    window.activateWindow()
    window.import_button.setFocus()
    qtbot.waitUntil(window.isActiveWindow)
    qtbot.keyClick(window, Qt.Key.Key_O, Qt.KeyboardModifier.ControlModifier)
    assert window.state == LoadState.READY


def test_zoom_wheel_limits_and_pan(window, image_file, qtbot):
    window.load_image(image_file())
    view = window.view
    original_pixels = window.document.image.cacheKey()
    initial = view.scale_factor
    qtbot.mouseClick(window.zoom_in_button, Qt.MouseButton.LeftButton)
    assert view.scale_factor > initial
    qtbot.mouseClick(window.zoom_out_button, Qt.MouseButton.LeftButton)
    assert view.scale_factor == pytest.approx(initial)
    pos = QPointF(view.viewport().rect().center())
    wheel = QWheelEvent(pos, QPointF(view.viewport().mapToGlobal(pos.toPoint())),
                        QPoint(), QPoint(0, 120), Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(view.viewport(), wheel)
    assert view.scale_factor > initial
    view.zoom(10)
    before = view.mapToScene(view.viewport().rect().center())
    center = view.viewport().rect().center()
    qtbot.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=center)
    qtbot.mouseMove(view.viewport(), center + QPoint(80, 50), delay=50)
    qtbot.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=center + QPoint(80, 50))
    after = view.mapToScene(view.viewport().rect().center())
    assert after != before
    view.zoom(1e10)
    assert view.scale_factor == pytest.approx(view.max_scale)
    view.zoom(1e-20)
    assert view.scale_factor == pytest.approx(view.min_scale)
    assert window.document.image.cacheKey() == original_pixels
