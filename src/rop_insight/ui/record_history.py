"""Historical records in a separate read-only view; active analysis stays untouched."""
from threading import Event
from PyQt6.QtCore import Qt,QTimer
from PyQt6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLineEdit,QPushButton,QLabel,QTableWidget,QTableWidgetItem,QAbstractItemView,QFileDialog,QPlainTextEdit)
from rop_insight.services.export_controller import ExportController
from rop_insight.services.record_history import history_job,STATES,EYES


class HistoryWindow(QDialog):
    def __init__(self,root=None,parent=None):
        super().__init__(parent)
        self.root=str(root) if root else None;self._closing=False;self.cancel=Event();self.active_key=None
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
        self.details=QPlainTextEdit();self.details.setReadOnly(True);layout.addWidget(self.details)
        self.back=QPushButton('返回当前分析');self.back.clicked.connect(self.close);layout.addWidget(self.back)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(250);self.timer.timeout.connect(self.refresh)
        self.search.textChanged.connect(self._search_changed)
        if self.root:self.refresh()

    def choose_root(self):
        root=QFileDialog.getExistingDirectory(self,'选择已有精简版资料库')
        if root:self.root=root;self.refresh()

    def _search_changed(self):
        self.table.setRowCount(0);self.details.clear();self.timer.start()

    def refresh(self):
        if not self.root or self._closing:return False
        if self.worker.busy:return False
        self.cancel=Event();self.active_key=(self.root,self.search.text())
        self.choose.setEnabled(False);self.refresh_button.setEnabled(False)
        self.table.setRowCount(0);self.details.clear();self.status.setText('正在后台读取历史记录…')
        return self.worker.start(dict(kind='list',root=self.root,code=self.search.text()),self.cancel)

    def _finished(self,result,error):
        self.choose.setEnabled(True);self.refresh_button.setEnabled(True)
        if self._closing:self.close();return
        if self.active_key!=(self.root,self.search.text()):self.refresh();return
        if error or not result['ok']:self.status.setText(error or result['message']);return
        rows=result['result']['rows']
        self.status.setText(('无匹配记录' if self.search.text() else '暂无保存记录') if not rows else f'找到 {len(rows)} 条记录 · {self.root}')
        if result['result']['more']:self.status.setText(self.status.text()+'；最多显示1000条，请按病例编号缩小范围')
        for row in rows:
            index=self.table.rowCount();self.table.insertRow(index)
            values=(row['case_code'],EYES.get(row['eye'],'未指定'),row['exam_date'] or '未填写',row['analysis_time'],row['prediction'],STATES.get(row['status'],'未知'),row['issue'])
            for column,value in enumerate(values):
                item=QTableWidgetItem(str(value));item.setData(Qt.ItemDataRole.UserRole,row);self.table.setItem(index,column,item)
        self.table.resizeColumnsToContents()

    def selected(self):
        item=self.table.item(self.table.currentRow(),0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def closeEvent(self,event):
        self.timer.stop()
        if self.worker.busy:self._closing=True;self.cancel.set();event.ignore()
        else:event.accept()
