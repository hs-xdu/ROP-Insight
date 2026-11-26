"""Qt PDF rendering and atomic, versioned report bundles; no source rewriting."""

import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
from uuid import uuid4

from PyQt6.QtCore import QMarginsF, QRectF, QSizeF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPageLayout, QPageSize, QPdfWriter, QGuiApplication, QImage
from PyQt6.QtPdf import QPdfDocument

from rop_insight.services.report_template import render_html, render_text, STYLESHEET
from rop_insight.services.pdf_report_layout import ReportPageLayout


def pdf_text(path):
    pdf=QPdfDocument(None)
    try:
        if pdf.load(str(path))!=QPdfDocument.Error.None_ or pdf.pageCount()<1:
            raise OSError('PDF读回验证失败')
        return pdf.pageCount(), '\n'.join(pdf.getAllText(page).text() for page in range(pdf.pageCount()))
    finally:
        pdf.close()


def write_pdf(report,path):
    if not isinstance(QGuiApplication.instance(),QGuiApplication):
        raise ValueError('PDF生成需要Qt图形应用环境')
    writer=QPdfWriter(str(path))
    writer.setResolution(144)
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageMargins(QMarginsF(18,16,18,16),QPageLayout.Unit.Millimeter)
    writer.setTitle('ROP-Insight 结构化辅助分析报告')
    writer.setCreator('ROP-Insight '+report.data['template_version'])
    writer.setPdfVersion(QPdfWriter.PdfVersion.PdfVersion_1_6)
    measure_device=QImage(1,1,QImage.Format.Format_ARGB32)
    measure_device.setDotsPerMeterX(round(96/.0254));measure_device.setDotsPerMeterY(round(96/.0254))
    scale=writer.logicalDpiX()/measure_device.logicalDpiX()
    width,height=writer.width(),writer.height()
    header,footer=38,35
    body_height=height-header-footer
    logical_width,logical_body_height=width/scale,math.floor(body_height/scale)
    layout=ReportPageLayout(report,logical_width,logical_body_height,measure_device)
    pages=len(layout.pages)
    painter=QPainter()
    if not painter.begin(writer):raise OSError('无法创建PDF')
    try:
        for page in range(pages):
            if page and not writer.newPage():raise OSError('无法写入PDF分页')
            painter.setFont(QFont('Microsoft YaHei',8));painter.setPen(QColor('#64748b'))
            painter.drawText(QRectF(0,0,width,header-8),Qt.AlignmentFlag.AlignLeft,'ROP-Insight | 研究辅助分析报告')
            painter.save()
            painter.setClipRect(QRectF(0,header,width,body_height))
            painter.translate(0,header)
            painter.scale(scale,scale)
            layout.paint_page(painter,page)
            painter.restore()
            painter.drawText(QRectF(0,height-footer+10,width,footer-10),
                Qt.AlignmentFlag.AlignRight,f'研究用途 - 非临床诊断     第 {page+1} / {pages} 页')
    finally:
        painter.end()
        del writer
    count,text=pdf_text(path)
    if count!=pages or 'ROP-Insight' not in text:raise OSError('PDF内容校验失败')
    return count


def _write_text(path,text):
    with path.open('x',encoding='utf-8') as stream:
        stream.write(text);stream.flush();os.fsync(stream.fileno())


def export_report_bundle(report,parent):
    parent=Path(parent).resolve()
    if not parent.is_dir():raise ValueError('报告导出位置必须是已存在的目录')
    destination=parent/('rop-report-'+uuid4().hex)
    staging=Path(tempfile.mkdtemp(prefix='.rop-report-',dir=parent))
    try:
        _write_text(staging/'report.json',json.dumps(report.data,ensure_ascii=False,allow_nan=False,indent=2))
        _write_text(staging/'report_summary.txt',render_text(report,False))
        _write_text(staging/'report_detail.txt',render_text(report))
        _write_text(staging/'report.html',render_html(report).replace('<head>','<head><style>'+STYLESHEET+'</style>',1))
        if report.data.get('case_metadata') is not None:
            from rop_insight.services.case_store import write_case_link
            write_case_link(staging/'case_metadata.json',report.data['case_metadata'],
                report.data['source']['run']['run_id'],report.data['report_id'])
        pages=write_pdf(report,staging/'report.pdf')
        if json.loads((staging/'report.json').read_text(encoding='utf-8'))!=report.data:
            raise ValueError('报告JSON读回不一致')
        artifacts={p.name:dict(sha256=hashlib.sha256(p.read_bytes()).hexdigest(),bytes=p.stat().st_size)
                   for p in staging.iterdir()}
        data=report.data
        manifest=dict(report_schema_version=1,report_id=data['report_id'],template_version=data['template_version'],
            source_snapshot_sha256=data['source_snapshot_sha256'],run_id=data['source']['run']['run_id'],
            image_id=data['source']['image']['image_id'],input_file_sha256=data['source']['image']['file_sha256'],
            pdf_pages=pages,artifacts=artifacts)
        if data.get('case_metadata') is not None:manifest['case_revision_id']=data['case_metadata']['revision_id']
        _write_text(staging/'report_manifest.json',json.dumps(manifest,ensure_ascii=False,allow_nan=False,indent=2))
        if destination.exists():raise FileExistsError('报告目录已存在，未覆盖')
        os.rename(staging,destination)
        return destination
    except BaseException:
        shutil.rmtree(staging,ignore_errors=True)
        raise
