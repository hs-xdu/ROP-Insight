"""Actual service flow through the independent P6-B acceptance window."""
from pathlib import Path
import runpy
from threading import Event
from rop_insight.services import managed_store


def make_window(qtbot,tmp_path):
    window_type=runpy.run_path(str(Path(__file__).with_name('manual_p6_b.py')))['AcceptanceWindow']
    window=window_type(tmp_path);qtbot.addWidget(window);window.show();return window


def test_acceptance_import_move_and_corrupt_flow(qtbot,tmp_path):
    window=make_window(qtbot,tmp_path)
    window.start_import();qtbot.waitUntil(lambda:not window.importer.busy,timeout=5000)
    assert window.move_button.isEnabled() and 'ready / valid' in window.info.text()
    window.move_and_open();qtbot.waitUntil(lambda:not window.reader.busy,timeout=5000)
    assert not window.request.source.exists() and '验收通过' in window.info.text()
    assert window.corrupt_button.isEnabled()
    assert window.view.overlay_items['ridge'].isVisible()
    window.corrupt_and_check();qtbot.waitUntil(lambda:not window.reader.busy,timeout=5000)
    assert '损坏副本未打开' in window.info.text()
    assert window.service.get_image(window.request.image_id).integrity_state=='corrupt'
    window.close()


def test_acceptance_window_waits_for_cancel_on_close(qtbot,tmp_path,monkeypatch):
    window=make_window(qtbot,tmp_path);entered=Event();original=managed_store._copy
    def block(source,target,expected,cancel):
        entered.set();cancel.wait(3);return original(source,target,expected,cancel)
    monkeypatch.setattr(managed_store,'_copy',block)
    window.start_import();qtbot.waitUntil(entered.is_set,timeout=3000)
    window.close();assert window._closing
    qtbot.waitUntil(lambda:not window.importer.busy,timeout=5000)
    assert not window.isVisible()
    assert window.service.get_image(window.request.image_id).save_state=='write_failed'
