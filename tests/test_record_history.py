"""Simplified P7-A query and actual list UI. No inference or production data."""
from dataclasses import replace
from pathlib import Path
from threading import Event
from uuid import uuid4
import pytest
from test_local_records import saved_input
from rop_insight.services.record_history import query_records
from rop_insight.ui.record_history import HistoryWindow


def test_query_search_clear_empty_missing_and_broken_record(saved_input,tmp_path):
    store,case,snapshot=saved_input
    assert query_records(store.root)['rows']==[]
    row=store.save_record(case,snapshot)
    found=query_records(store.root,'test-001')['rows']
    assert len(found)==1 and found[0]['case_code']==case['case_code'] and found[0]['prediction']=='不可用'
    assert query_records(store.root,'absent')['rows']==[]
    assert len(query_records(store.root,'')['rows'])==1
    (store.root/row['result_path']).write_text('{}',encoding='utf-8')
    assert query_records(store.root)['rows'][0]['issue']
    empty=tmp_path/'not-a-library'
    with pytest.raises(ValueError):query_records(empty)
    assert not empty.exists()


def test_query_analysis_time_order_and_cancellation(saved_input):
    store,case,snapshot=saved_input
    for time in ('2026-01-02T00:00:00+00:00','2026-01-01T00:00:00+00:00'):
        store.save_record(case,replace(snapshot,run=replace(snapshot.run,run_id=str(uuid4()),finished_at=time)))
    assert [r['analysis_time'] for r in query_records(store.root)['rows']]==['2026-01-02T00:00:00+00:00','2026-01-01T00:00:00+00:00']
    event=Event();event.set()
    with pytest.raises(InterruptedError):query_records(store.root,cancel=event)


def test_history_window_search_and_current_analysis_preserved(qtbot,saved_input):
    from rop_insight.ui.main_window import MainWindow
    store,case,snapshot=saved_input;store.save_record(case,snapshot)
    main=MainWindow();qtbot.addWidget(main)
    main.library_root=str(store.root);main.analysis.context=snapshot.context;main.analysis.current_run=snapshot.run
    window=main.open_history();qtbot.waitUntil(lambda:not window.worker.busy,timeout=5000)
    assert window.table.rowCount()==1
    assert main.case_button.isEnabled()
    window.search.setText('not-found')
    qtbot.waitUntil(lambda:window.table.rowCount()==0 and '无匹配' in window.status.text(),timeout=5000)
    window.search.clear();qtbot.waitUntil(lambda:window.table.rowCount()==1,timeout=5000)
    window.close()
    assert main.analysis.context is snapshot.context and main.analysis.current_run is snapshot.run
    main.close()
