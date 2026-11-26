"""Local history browser: read saved facts and PDFs without running models."""
import json
from threading import Event
from PyQt6.QtCore import Qt,pyqtSignal
from PyQt6.QtPdf import QPdfDocument
from PyQt6.QtPdfWidgets import QPdfView
from PyQt6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QPushButton,QLineEdit,QLabel,QTableWidget,QTableWidgetItem,QAbstractItemView,QPlainTextEdit,QFileDialog)
from rop_insight.services.export_controller import ExportController
from rop_insight.services.history_store import scan_history,verified_artifact,verify_input
from rop_insight.models.case_metadata import EYES


class HistoryDialog(QDialog):
    idle=pyqtSignal()
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setWindowTitle('历史分析记录与来源复核');self.resize(1050,760)
        self.records=[];self.root=None;self.cancel_event=Event();self.pdf_windows=[];self._closing=False
        self.scanner=ExportController(self,job=lambda root,event:scan_history(root,event),error_message='历史读取失败')
        self.verify_cancel=Event()
        self.verifier=ExportController(self,job=lambda request,event:verify_input(*request,event),error_message='原图核对失败或已取消')
        self.verifier.finished.connect(self._input_finished)
        self.open_cancel=Event()
        self.opener=ExportController(self,job=lambda request,event:(verified_artifact(*request,event),request[1]),error_message='历史文件校验失败或已取消，请刷新列表后查看问题')
        self.opener.finished.connect(self._opened)
        self.scanner.finished.connect(self._finished)
        layout=QVBoxLayout(self);bar=QHBoxLayout();layout.addLayout(bar)
        self.choose_button=QPushButton('选择成果目录');self.choose_button.clicked.connect(self.choose_root);bar.addWidget(self.choose_button)
        self.refresh_button=QPushButton('刷新 / 重建列表');self.refresh_button.clicked.connect(lambda:self.load_root(self.root) if self.root else None);bar.addWidget(self.refresh_button)
        self.cancel_button=QPushButton('取消读取');self.cancel_button.clicked.connect(self.cancel_reads);bar.addWidget(self.cancel_button)
        self.search=QLineEdit();self.search.setPlaceholderText('按病例编号筛选');self.search.textChanged.connect(self.populate);bar.addWidget(self.search)
        self.label=QLabel('选择本地导出目录；历史复核不代表医生签审。');self.label.setWordWrap(True);self.label.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(self.label)
        self.table=QTableWidget(0,8);self.table.setHorizontalHeaderLabels(['病例编号','眼别','检查日期','记录类型','分析状态','保存/完成时间','运行编号','校验状态'])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.itemSelectionChanged.connect(self.show_details);layout.addWidget(self.table)
        self.details=QPlainTextEdit();self.details.setReadOnly(True);layout.addWidget(self.details)
        actions=QHBoxLayout();layout.addLayout(actions)
        self.pdf_button=QPushButton('重开已有 PDF');self.pdf_button.clicked.connect(self.open_pdf);actions.addWidget(self.pdf_button)
        self.text_button=QPushButton('查看已有文字报告');self.text_button.clicked.connect(self.open_text);actions.addWidget(self.text_button)
        self.input_button=QPushButton('选择原图核对哈希');self.input_button.clicked.connect(self.check_input);actions.addWidget(self.input_button)
        self.show_details()

    def cancel_reads(self):
        self.cancel_event.set();self.verify_cancel.set();self.open_cancel.set()

    def choose_root(self):
        root=QFileDialog.getExistingDirectory(self,'选择具体的本地分析成果目录')
        if root:self.load_root(root)

    def load_root(self,root):
        if self.busy:return False
        self._closing=False
        self.root=root;self.cancel_event=Event();self.label.setText('正在读取和校验；取消或失败会保留上次列表。')
        self.choose_button.setEnabled(False);self.refresh_button.setEnabled(False)
        return self.scanner.start(root,self.cancel_event)

    def _finished(self,records,error):
        self.choose_button.setEnabled(True);self.refresh_button.setEnabled(True)
        if not error:self.records=records;self.populate()
        self.label.setText(('读取已取消，保留上次列表' if self.cancel_event.is_set() else error+'；请检查所选目录及本地日志') if error else f'读取 {len(records)} 条记录；目录：{self.root}。哈希仅验证记录内一致性，不是签名认证。')
        if not self.busy:self.idle.emit()
        if self._closing:self.close()

    @property
    def busy(self):return self.scanner.busy or self.verifier.busy or self.opener.busy

    def _input_finished(self,result,error):
        self.label.setText(error or result)
        self.show_details()
        if not self.busy:self.idle.emit()
        if self._closing:self.close()

    def populate(self):
        self.table.setRowCount(0)
        for record in self.records:
            if self.search.text().casefold() not in record.case_id.casefold():continue
            row=self.table.rowCount();self.table.insertRow(row)
            values=[record.case_id,EYES.get(record.case.eye,'') if record.case else '—',record.case.exam_date or '—' if record.case else '—',
                '报告' if record.kind=='report' else '分析（报告未生成）',
                {'success':'完成','partial_success':'部分完成','failed':'失败','cancelled':'取消'}.get(record.source.get('run',{}).get('status'),'未知'),
                record.document.get('generated_at') or record.source.get('run',{}).get('finished_at','—'),
                record.source.get('run',{}).get('run_id','—'),record.status]
            for col,value in enumerate(values):
                item=QTableWidgetItem(str(value));item.setData(Qt.ItemDataRole.UserRole,record);self.table.setItem(row,col,item)
        self.table.resizeColumnsToContents();self.show_details()

    def selected(self):
        item=self.table.item(self.table.currentRow(),0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def show_details(self):
        record=self.selected()
        valid=record is not None and not record.issues
        for button,name in ((self.pdf_button,'report.pdf'),(self.text_button,'report_detail.txt')):
            button.setEnabled(valid and record.kind=='report' and name in record.artifacts and not self.opener.busy)
        self.input_button.setEnabled(bool(valid) and not self.verifier.busy)
        self.details.setPlainText(self.record_details(record) if record else '请选择一条记录；没有 PDF 的旧分析仍可查看来源和模型版本。')

    def record_details(self,record):
        image=record.source.get('image',{})
        if not isinstance(image,dict):image={}
        lines=[f'病例：{record.case_id}',f'校验：{record.status}',f'保存目录：{record.folder}',
            '图像编号：'+str(image.get('image_id','未知')),
            '原图文件 SHA256：'+str(image.get('file_sha256') or '未记录'),
            '解码像素 SHA256：'+str(image.get('rgb_pixel_sha256') or '未记录')]
        if record.case:
            lines.extend(['病例资料版本：'+record.case.revision_id,'备注：'+record.case.notes])
        modules=record.source.get('modules',{})
        if isinstance(modules,dict):
            lines.append('模型与模块来源：')
            for name,module in modules.items():
                if isinstance(module,dict):
                    lines.append(f"  {name}：{module.get('model_version') or '未记录版本'}；状态 {module.get('state','未知')}；权重 SHA256 {module.get('weights_sha256') or '未记录'}")
        if record.kind=='report':lines.append('报告模板：'+str(record.document.get('template_version','未知')))
        lines.extend(['','原始保存记录（只读）：',json.dumps(record.document,ensure_ascii=False,indent=2)])
        return '\n'.join(lines)

    def open_saved(self,name):
        record=self.selected()
        if record is None or record.issues or self.busy:return False
        self.open_cancel=Event()
        self.label.setText('正在后台重新校验历史文件…')
        started=self.opener.start((record,name),self.open_cancel)
        self.show_details()
        return started

    def open_pdf(self):return self.open_saved('report.pdf')

    def open_text(self):return self.open_saved('report_detail.txt')

    def _opened(self,result,error):
        self.show_details()
        try:
            if error:raise ValueError(error)
            if self._closing:return
            path,name=result
            if name=='report_detail.txt':
                if path.stat().st_size>4*1024*1024:raise ValueError('文字报告超过4MiB读取上限')
                self.details.setPlainText(path.read_text(encoding='utf-8'))
            else:
                dialog=QDialog(self);dialog.setWindowTitle('历史报告（只读）');dialog.resize(850,850)
                layout=QVBoxLayout(dialog);view=QPdfView(dialog);pdf=QPdfDocument(dialog)
                if pdf.load(str(path))!=QPdfDocument.Error.None_:raise ValueError('PDF读取失败')
                view.setDocument(pdf);view.setPageMode(QPdfView.PageMode.MultiPage);view.setZoomMode(QPdfView.ZoomMode.FitToWidth);layout.addWidget(view)
                dialog.pdf=pdf;dialog.view=view
                def release_pdf():
                    view.setDocument(None)
                    pdf.close()
                dialog.finished.connect(release_pdf)
                self.pdf_windows.append(dialog);dialog.show()
            self.label.setText('已打开通过记录内哈希校验的原报告；未重新生成或推理。')
        except (OSError,ValueError) as exc:self.label.setText(str(exc))
        finally:
            if not self.busy:self.idle.emit()
            if self._closing:self.close()

    def check_input(self):
        record=self.selected()
        if not record:return
        path,_=QFileDialog.getOpenFileName(self,'选择原始输入文件以核对哈希')
        if path and not self.verifier.busy:
            self.verify_cancel=Event()
            self.label.setText('正在核对选定原图；不会更改历史关联。')
            self.verifier.start((record,path),self.verify_cancel)
            self.show_details()

    def closeEvent(self,event):
        if self.busy:
            self._closing=True;self.cancel_reads();event.ignore()
        else:
            for dialog in self.pdf_windows:dialog.close()
            self.pdf_windows.clear()
            event.accept()
