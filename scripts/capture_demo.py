"""Create a shareable synthetic UI screenshot; no patient data or model outputs."""

from pathlib import Path
import argparse
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QImage,QPainter,QColor
from rop_insight.ui.main_window import MainWindow


def capture(output):
    app=QApplication.instance() or QApplication([])
    output.mkdir(parents=True,exist_ok=True)
    image=QImage(800,600,QImage.Format.Format_RGB32);image.fill(QColor('#102132'))
    painter=QPainter(image)
    painter.setBrush(QColor('#c87b56'));painter.setPen(QColor('#efb18c'));painter.drawEllipse(145,45,510,510)
    painter.setPen(QColor('#6c3d37'))
    for endpoint in [(270,130),(550,170),(580,420),(310,480)]:painter.drawLine(380,300,*endpoint)
    painter.end()
    source=output/'synthetic_demo.png';image.save(str(source))
    window=MainWindow();window.setWindowTitle('ROP-Insight · 合成界面示例，无模型推理结果')
    window.show();window.load_image(source)
    window.statusBar().showMessage('合成图像 · 仅展示查看与导出入口布局 · 未运行模型')
    for _ in range(10):app.processEvents()
    window.grab().save(str(output/'platform_demo.png'))
    window.close();app.processEvents()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    capture(parser.parse_args().output)
