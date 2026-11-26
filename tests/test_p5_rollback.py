"""Keep the approved P5-only boundary after retiring the earlier P6/P7 implementation."""
from pathlib import Path
from rop_insight.ui.main_window import MainWindow
from rop_insight.services.report_builder import TEMPLATE_VERSION


def test_p5_analysis_and_reports_survive_simplified_case_entry(qtbot):
    window=MainWindow();qtbot.addWidget(window)
    assert hasattr(window,'analyze_button') and hasattr(window,'export_button')
    assert hasattr(window,'report_button')
    assert hasattr(window,'case_button') and hasattr(window,'save_record_button')
    assert hasattr(window,'history_button')
    assert TEMPLATE_VERSION=='p5-factual-2'
    window.close()


def test_retired_p6_sources_and_sql_resources_are_absent():
    source=Path(__file__).resolve().parents[1]/'src'/'rop_insight'
    for relative in ('models/case_metadata.py','models/managed_data.py','models/managed_image.py',
        'services/database.py','services/data_repository.py','services/managed_store.py',
        'services/history_store.py','services/case_store.py','services/image_import_controller.py',
        'ui/case_dialog.py','ui/history_dialog.py','migrations/001_initial.sql'):
        assert not (source/relative).exists(),relative
