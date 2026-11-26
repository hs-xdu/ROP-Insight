"""Historical records in a separate read-only view; active analysis stays untouched."""
from threading import Event
import json
from PyQt6.QtCore import Qt,QTimer
from PyQt6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLineEdit,QPushButton,QLabel,QTableWidget,QTableWidgetItem,QAbstractItemView,QFileDialog,QPlainTextEdit,QTabWidget,QWidget,QScrollArea,QSizePolicy,QLayout)
from rop_insight.services.export_controller import ExportController
from rop_insight.ui.image_view import ImageView
from rop_insight.ui.result_panel import ResultPanel
from rop_insight.ui.saved_report import SavedReportWindow
from rop_insight.services.record_history import history_job,STATES,EYES


class HistoryWindow(QDialog):
    def __init__(self,root=None,parent=None):
        super().__init__(parent)
        self.root=str(root) if root else None;self._closing=False;self.cancel=Event();self.active_key=None;self.report_dialog=None;self.active_kind=None
        self.setWindowTitle('历史分析记录 · 只读');self.resize(1100,760)
        self.worker=ExportController(self,job=history_job);self.worker.finished.connect(self._finished)
        layout=QVBoxLayout(self);bar=QHBoxLayout();layout.addLayout(bar)
        self.choose=QPushButton('选择资料库');self.choose.clicked.connect(self.choose_root);bar.addWidget(self.choose)
        self.refresh_button=QPushButton('刷新');self.refresh_button.clicked.connect(self.refresh);bar.addWidget(self.refresh_button)
        self.search=QLineEdit();self.search.setPlaceholderText('输入病例编号，清空显示全部');bar.addWidget(self.search)
        self.status=QLabel('请选择保存记录时使用的资料库文件夹');self.status.setWordWrap(True);self.status.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(self.status)
        self.table=QTableWidget(0,7);self.table.setHorizontalHeaderLabels(['病例编号','左右眼','检查日期','分析时间','A6预测','状态','文件提示'])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        layout.addWidget(self.table)
        actions=QHBoxLayout();layout.addLayout(actions)
        self.open_button=QPushButton('查看分析结果');self.open_button.clicked.connect(lambda:self.open_selected('analysis'));actions.addWidget(self.open_button)
        self.report_button=QPushButton('查看已有报告');self.report_button.clicked.connect(lambda:self.open_selected('report'));actions.addWidget(self.report_button)
        self.pdf_button=QPushButton('导出已有PDF');self.pdf_button.clicked.connect(self.export_pdf);actions.addWidget(self.pdf_button)
        self.tabs=QTabWidget();layout.addWidget(self.tabs,2)
        page=QWidget();body=QHBoxLayout(page)
        self.panel=ResultPanel();self.panel.setFixedWidth(250);self.panel.layout().setSizeConstraints(QLayout.SizeConstraint.SetNoConstraint,QLayout.SizeConstraint.SetMinimumSize);scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(self.panel);scroll.setFixedWidth(285);body.addWidget(scroll)
        preview=QWidget();column=QVBoxLayout(preview);controls=QHBoxLayout();column.addLayout(controls)
        for label,factor in (('缩小',1/1.2),('放大',1.2),('适应窗口',None)):
            button=QPushButton(label);button.clicked.connect(lambda checked=False,f=factor:self.view.fit_image() if f is None else self.view.zoom(f));controls.addWidget(button)
        self.view=ImageView();column.addWidget(self.view,1);body.addWidget(preview,1)
        self.tabs.addTab(page,'历史图像与结果')
        self.details=QPlainTextEdit();self.details.setReadOnly(True);self.tabs.addTab(self.details,'模型版本与原始记录')
        self.t1=QLabel('T1：未提供');column.addWidget(self.t1)
        self.panel.layers_changed.connect(self._layers)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.back=QPushButton('返回当前分析');self.back.clicked.connect(self.close);layout.addWidget(self.back)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(250);self.timer.timeout.connect(self.refresh)
        self.search.textChanged.connect(self._search_changed)
        self._buttons()
        if self.root:self.refresh()

    def choose_root(self):
        root=QFileDialog.getExistingDirectory(self,'选择已有精简版资料库')
        if root:self.root=root;self.refresh()

    def _search_changed(self):
        self.table.setRowCount(0);self._clear_detail();self.timer.start()

    def refresh(self):
        if not self.root or self._closing:return False
        if self.worker.busy:return False
        self.timer.stop()
        self.cancel=Event();self.active_key=(self.root,self.search.text());self.active_kind='list'
        self.choose.setEnabled(False);self.refresh_button.setEnabled(False)
        self.table.setRowCount(0);self._clear_detail();self.status.setText('正在后台读取历史记录…')
        started=self.worker.start(dict(kind='list',root=self.root,code=self.search.text()),self.cancel)
        self._buttons();return started

    def _finished(self,result,error):
        self.choose.setEnabled(True);self.refresh_button.setEnabled(True)
        self._buttons()
        if self._closing:self.close();return
        if self.active_key!=(self.root,self.search.text()):self.refresh();return
        if error or not result['ok']:self.status.setText(error or result['message']);return
        if result['kind']!='list':
            row=self.selected()
            if row is None or (result['root'],result['record_id'])!=(self.root,row['record_id']):
                self.status.setText('选择已变化，请打开当前选中记录');return
            try:
                if result['kind']=='analysis':self._show_analysis(result['result'])
                elif result['kind']=='report':
                    if result['result'] is None:self.status.setText('未生成报告')
                    else:
                        if self.report_dialog is not None:self.report_dialog.close();self.report_dialog.deleteLater()
                        self.report_dialog=SavedReportWindow(result['result'],self);self.report_dialog.show()
                        self.status.setText('已打开原报告，未重新生成内容')
                else:self.status.setText('已有PDF已导出：'+result['result'])
            except ValueError as exc:self.status.setText(str(exc))
            return
        rows=result['result']['rows']
        self.status.setText(('无匹配记录' if self.search.text() else '暂无保存记录') if not rows else f'找到 {len(rows)} 条记录 · {self.root}')
        if result['result']['more']:self.status.setText(self.status.text()+'；最多显示1000条，请按病例编号缩小范围')
        for row in rows:
            index=self.table.rowCount();self.table.insertRow(index)
            values=(row['case_code'],EYES.get(row['eye'],'未指定'),row['exam_date'] or '未填写',row['analysis_time'],row['prediction'],STATES.get(row['status'],'未知'),row['issue'])
            for column,value in enumerate(values):
                item=QTableWidgetItem(str(value));item.setData(Qt.ItemDataRole.UserRole,row);self.table.setItem(index,column,item)
        self.table.resizeColumnsToContents()

    def _buttons(self):
        row=self.selected();ready=row is not None and not self.worker.busy
        self.open_button.setEnabled(ready)
        self.report_button.setEnabled(bool(ready and row['report_path']))
        self.pdf_button.setEnabled(bool(ready and row['report_path']))

    def _clear_detail(self):
        self.view.clear_image();self.panel.reset();self.details.clear();self.t1.setText('T1：未提供')
        if self.report_dialog is not None:self.report_dialog.close()
        self._buttons()

    def _selection_changed(self):
        self._clear_detail()
        row=self.selected()
        if row:
            self.details.setPlainText('记录ID：'+row['record_id']+'\n'+('未生成报告' if not row['report_path'] else '已保存报告')+'\n'+(row['issue'] or '打开记录将校验关联文件'))

    def open_selected(self,kind,destination=None):
        row=self.selected()
        if row is None or self.worker.busy or self._closing:return False
        self.cancel=Event();self.active_key=(self.root,self.search.text());self.active_kind=kind
        if kind=='analysis':self._clear_detail()
        elif kind=='report' and self.report_dialog is not None:self.report_dialog.close()
        self.status.setText('正在后台校验并读取原保存文件…')
        self.choose.setEnabled(False);self.refresh_button.setEnabled(False)
        started=self.worker.start(dict(kind=kind,root=self.root,code=self.search.text(),record_id=row['record_id'],destination=destination),self.cancel)
        self._buttons();return started

    def export_pdf(self):
        destination,_=QFileDialog.getSaveFileName(self,'另存已有PDF（不覆盖旧文件）','','PDF (*.pdf)')
        if destination:self.open_selected('export_pdf',destination)

    def _show_analysis(self,saved):
        self.view.set_image(saved['image']);available=set()
        for result in saved['run'].modules.values():
            if result.state=='success' and result.output:
                for mask in result.output.masks:self.view.set_mask(mask);available.add(mask.structure)
                value=result.output.values.get('feature_values',{}).get('T1')
                if type(value) in (int,float):self.t1.setText('血管迂曲指数 T1：'+format(value,'.12g'))
        self.panel.set_available(available);self.panel.show_run(saved['run'])
        self.details.setPlainText('病例：'+saved['case']['case_code']+'\n原保存记录（只读）：\n'+json.dumps(saved['data'],ensure_ascii=False,indent=2))
        self.tabs.setCurrentIndex(0);self.status.setText('已恢复原图、图层及保存结果；未运行模型。'+('未生成报告' if not saved['row']['report_path'] else '可查看已有报告'))

    def _layers(self):
        self.view.display_mode=self.panel.mode.currentData();self.view.overlay_opacity=self.panel.opacity.value()/100
        self.view.overlay_enabled={name:check.isChecked() for name,check in self.panel.checks.items()};self.view.update_layers()

    def selected(self):
        item=self.table.item(self.table.currentRow(),0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def closeEvent(self,event):
        self.timer.stop()
        if self.worker.busy:self._closing=True;self.cancel.set();event.ignore()
        else:
            if self.report_dialog is not None:self.report_dialog.close()
            event.accept()
