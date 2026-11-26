"""Plan searchable Qt text line by line; no cross-page clipping of rich text."""

import math
from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtGui import QColor, QFont, QTextLayout, QTextOption
from rop_insight.services.report_template import report_sections,number


class ReportPageLayout:
    def __init__(self,report,width,height,device):
        self.width,self.height,self.device=width,height,device
        self.pages=[[]];self.y=0.;self.layouts=[]
        self.body=QFont('Microsoft YaHei',9)
        self.heading=QFont('Microsoft YaHei',12);self.heading.setBold(True)
        self.title=QFont('Microsoft YaHei',22);self.title.setBold(True)
        self.subtitle=QFont('Microsoft YaHei',15)
        self.muted=QFont('Microsoft YaHei',8)
        self.paragraph('ROP-Insight',self.title,'#0f766e',5)
        self.paragraph('结构化辅助分析报告',self.subtitle,'#334155',8)
        self.paragraph('研究模型输出 - 不是临床诊断',self.body,'#7c4a12',10)
        for title,items in report_sections(report):
            if title=='量化特征（固定11项）':
                self.ensure(85);self.section(title)
                self.feature_table(report.data['features'])
                continue
            if title in ('连续评分与后验区间','SVM结构辅助分类'):
                items=['\n'.join(items)]
            first_height=self.text_height(items[0],self.body,self.width) if items else 0
            self.ensure(min(self.height,42+first_height))
            self.section(title)
            for text in items:
                self.paragraph(text,keep_together=not (title=='匿名病例信息' and text.startswith('备注（用户录入）：')))

    def lines(self,text,font,width):
        result=[]
        for segment in str(text).split('\n'):
            layout=QTextLayout(segment or ' ',font,self.device)
            option=QTextOption();option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
            layout.setTextOption(option);layout.beginLayout()
            while True:
                line=layout.createLine()
                if not line.isValid():break
                line.setLineWidth(width);line.setPosition(QPointF(0,0));result.append(line)
            layout.endLayout();self.layouts.append(layout)
        return result

    def text_height(self,text,font,width):
        return sum(math.ceil(line.height()*1.2) for line in self.lines(text,font,width))+5

    def ensure(self,height):
        if self.y and self.y+height>self.height:self.pages.append([]);self.y=0.

    def paragraph(self,text,font=None,color='#243544',space=5,keep_together=True):
        lines=self.lines(text,font or self.body,self.width)
        total=sum(math.ceil(line.height()*1.2) for line in lines)
        if keep_together and total<=self.height:self.ensure(total)
        for line in lines:
            step=math.ceil(line.height()*1.2);self.ensure(step)
            self.pages[-1].append(('text',line,0.,self.y,color));self.y+=step
        self.y+=space

    def section(self,title):
        if self.y:self.y+=7
        self.paragraph(title,self.heading,'#0f766e',6)

    def feature_table(self,features):
        columns=[self.width*f for f in (.33,.24,.29,.14)]
        header=('指标','数值 / 状态','单位','网格')

        def header_row():
            row(header,True)

        def row(cells,header=False,reason=False):
            widths=[self.width] if reason else columns
            font=self.heading if header else self.muted if reason else self.body
            # Table headings use body size with bold weight.
            if header:font=QFont(self.body);font.setBold(True)
            line_sets=[self.lines(text,font,width-12) for text,width in zip(cells,widths)]
            step=max((math.ceil(line.height()*1.2) for lines in line_sets for line in lines),default=16)
            count=max(map(len,line_sets),default=1);offset=0
            height=count*step+12
            if height<=self.height and self.y+height>self.height:
                self.ensure(height)
                if not header:header_row()
            while offset<count:
                capacity=int((self.height-self.y-12)//step)
                if capacity<1:
                    self.pages.append([]);self.y=0.
                    if not header:header_row()
                    capacity=max(1,int((self.height-self.y-12)//step))
                length=min(count-offset,capacity);height=length*step+12
                self.pages[-1].append(('rect',QRectF(0,self.y,self.width,height),'#e7f3f0' if header else '#ffffff'))
                x=0.
                for lines,width in zip(line_sets,widths):
                    for index in range(offset,min(offset+length,len(lines))):
                        self.pages[-1].append(('text',lines[index],x+6,self.y+6+(index-offset)*step,
                            '#134e4a' if header else '#64748b' if reason else '#243544'))
                    x+=width
                self.pages[-1].append(('rule',self.y+height));self.y+=height;offset+=length
                if offset<count:
                    self.pages.append([]);self.y=0.
                    if not header:header_row()
        header_row()
        for item in features:
            row((item['title'],number(item['value']) if item['status']=='available' else '不可用',
                 item['unit'],item['grid'] or '未提供'))
            if item['status']!='available':row(('原因：'+item['reason'],),reason=True)
        self.y+=8

    def paint_page(self,painter,index):
        for action in self.pages[index]:
            if action[0]=='text':
                _,line,x,y,color=action;painter.setPen(QColor(color));line.draw(painter,QPointF(x,y))
            elif action[0]=='rect':painter.fillRect(action[1],QColor(action[2]))
            else:
                painter.setPen(QColor('#dbe5e9'));painter.drawLine(QPointF(0,action[1]),QPointF(self.width,action[1]))
