"""Explicit local reference verification; writes evidence only to --output.

Run with the GUI interpreter. Original images, masks and model assets stay read-only.
"""

import argparse
import ctypes
import json
import math
import os
from pathlib import Path
import subprocess
from threading import Event, Thread
import time

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QScrollArea
from rop_insight.inference.registry import production_registry
from rop_insight.services.analysis_config import load_config
from rop_insight.services.analysis_controller import AnalysisController
from rop_insight.services.result_exporter import ExportSnapshot, export_bundle
from rop_insight.ui.main_window import MainWindow


def gui_peak_memory():
    if os.name!='nt':return None
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[
            (name,ctypes.c_size_t) for name in ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage',
            'QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetCurrentProcess.restype=wintypes.HANDLE
    psapi=ctypes.WinDLL('psapi',use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
    counters=Counters();counters.cb=ctypes.sizeof(counters)
    return counters.PeakWorkingSetSize if psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(counters),counters.cb) else None


def sample_gpu(stop,samples):
    while not stop.is_set():
        try:
            result=subprocess.run(['nvidia-smi','--query-gpu=name,driver_version,memory.used,memory.total',
                '--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=3,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if result.returncode==0:
                for line in result.stdout.splitlines():
                    name,driver,used,total=[part.strip() for part in line.split(',')]
                    samples.append(dict(name=name,driver=driver,used_mib=int(used),total_mib=int(total)))
        except (OSError,ValueError,subprocess.TimeoutExpired):pass
        stop.wait(1)


def verify(args):
    args.output.mkdir(parents=True,exist_ok=True)
    app=QApplication.instance() or QApplication([])
    app.setApplicationName('ROP-Insight-System-Validation')
    registry=production_registry()
    controller=AnalysisController(load_config(args.config,registry),registry)
    window=MainWindow(controller=controller);window.show()
    stop=Event();samples=[]
    sampler=Thread(target=sample_gpu,args=(stop,samples),daemon=True);sampler.start()
    heartbeats=[]
    timer=QTimer();timer.setInterval(50);timer.timeout.connect(lambda:heartbeats.append(time.monotonic()));timer.start()
    started=time.monotonic()
    try:
        if not window.load_image(args.image) or not window.import_ridge(args.ridge):
            raise ValueError('Reference image or Ridge input rejected')
        if not controller.start():raise ValueError('Analysis cannot start')
        deadline=time.monotonic()+args.timeout
        while controller.busy:
            app.processEvents();time.sleep(.01)
            if time.monotonic()>deadline:controller.cancel()
        app.processEvents()
        run=controller.current_run
        expected_status='partial_success' if args.expect_partial else 'success'
        if run.status!=expected_status:raise ValueError('Unexpected pipeline status; inspect local analysis logs')
        elapsed=time.monotonic()-started
        differences={}
        if args.reference:
            reference=json.loads(args.reference.read_text(encoding='utf-8'))
            metrics=run.modules['quantification'].output.values['metrics']
            for name,metric in metrics.items():
                expected=reference.get(name)
                if metric['value'] is None:
                    if expected is not None and math.isfinite(expected):raise ValueError('Reference availability mismatch: '+name)
                    differences[name]=None
                else:
                    if expected is None or not math.isclose(metric['value'],expected,rel_tol=1e-6,abs_tol=1e-8):
                        raise ValueError('Reference value mismatch: '+name)
                    differences[name]=abs(metric['value']-expected)
        snapshot=ExportSnapshot.capture(controller.context,run)
        bundle=export_bundle(snapshot,args.output)
        window.grab().save(str(args.output/'platform.png'))
        scroll=window.findChild(QScrollArea)
        scroll.ensureWidgetVisible(window.result_panel.auxiliary_label)
        app.processEvents();window.grab().save(str(args.output/'results.png'))
        labels=dict(score=window.result_panel.score_label.text(),svm=window.result_panel.auxiliary_label.text(),a6=window.result_panel.prediction.text())
        if not ('后验区间' in labels['score'] and '未校准概率' in labels['svm']):
            raise ValueError('Independent result labels missing')
        if run.modules['staging'].state=='success' and 'A6 预测' not in labels['a6']:
            raise ValueError('A6 result missing')
        if run.modules['staging'].state!='success' and '未提供' not in labels['a6']:
            raise ValueError('Failed A6 produced a prediction')
        window.view.zoom(2);window.view.centerOn(20,20)
        again=export_bundle(snapshot,args.output)
        if (bundle/'analysis_overlay.png').read_bytes()!=(again/'analysis_overlay.png').read_bytes():
            raise ValueError('View transform affected export')
        window.clear_image();app.processEvents()
        if window.export_button.isEnabled() or '未提供' not in window.result_panel.score_label.text():
            raise ValueError('Old result remained after clear')
        gaps=[right-left for left,right in zip(heartbeats,heartbeats[1:])]
        report=dict(ok=True,pipeline_seconds=elapsed,module_seconds={name:r.elapsed_seconds for name,r in run.modules.items()},
            states={name:str(r.state) for name,r in run.modules.items()},reference_abs_differences=differences,
            labels=labels,bundle=bundle.name,view_independent_export=True,clear_invalidates_export=True,
            heartbeat=dict(samples=len(heartbeats),max_gap_seconds=max(gaps,default=None)),
            gui_peak_working_set_bytes=gui_peak_memory(),gpu_samples=len(samples),gpu_devices=list({s['name'] for s in samples}),
            gpu_observed_max_used_mib=max((s['used_mib'] for s in samples),default=None),
            gpu_memory_scope='Whole device including other processes; sampled each second, not exact per-model peak',
            memory_scope='GUI process peak working set, excludes isolated inference child processes',
            scope='Single local engineering reference run; no clinical or device-wide performance claim')
        (args.output/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        return report
    finally:
        timer.stop();stop.set();sampler.join(4)
        controller.cancel()
        while controller.busy:app.processEvents();time.sleep(.02)
        window.close();app.processEvents()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('config','image','ridge','output'):parser.add_argument('--'+name,required=True,type=Path)
    parser.add_argument('--reference',type=Path,help='Original cached feature JSON (optional)')
    parser.add_argument('--timeout',type=float,default=600)
    parser.add_argument('--expect-partial',action='store_true',help='Verify retained quantification/SVM when A6 fails')
    arguments=parser.parse_args()
    result=verify(arguments)
    print(json.dumps({key:result[key] for key in ('ok','pipeline_seconds','states','reference_abs_differences','heartbeat','gui_peak_working_set_bytes','gpu_observed_max_used_mib')},ensure_ascii=False))
