"""Shared factual sections for preview, plain text and PDF. No clinical bins."""

from html import escape
from rop_insight.services.report_builder import STATES, MODULE_NAMES


def number(value):
    return format(value,'.12g') if value is not None else '不可用'


def report_sections(report, detailed=True):
    data=report.data
    source=data['source'];image=source['image'];run=source['run']
    a6=data['a6'];score=data['score'];svm=data['svm']
    sections=[('分析标识',[
        '报告ID：'+data['report_id'], '图像ID：'+str(image['image_id']), '运行ID：'+str(run['run_id']),
        f"图像：{image['width']} × {image['height']} px；格式：{image.get('format') or '未提供'}",
        '运行状态：'+STATES.get(run['status'],run['status']), '分析完成时间（UTC）：'+str(run['finished_at']),
        '报告生成时间（UTC）：'+data['generated_at']])]
    lines=['A6模型预测：'+a6['prediction']] if a6['status']=='available' else ['A6模型结果不可用：'+a6['reason']]
    if a6['status']=='available':
        lines.extend(f"{label}：{number(probability)}（{probability:.2%}）" for label,probability in zip(a6['classes'],a6['probabilities']))
    lines.append('类别及概率来自A6模型，不代表医生确认的临床分期。')
    sections.append(('A6分期模型结果',lines))
    sections.append(('Ridge / Vessel结构信息',[
        f"{item['name'].capitalize()}：{item['source']}；{item['width']} × {item['height']} px；解码原图坐标"
        if item['status']=='available' else f"{item['name'].capitalize()}：不可用；{item['reason']}"
        for item in data['structures']]))
    descriptions=data.get('feature_descriptions')
    if descriptions:
        observations=[]
        for item in descriptions['items']:
            grid=f"{item['grid']}网格" if item['grid'] else '网格未提供'
            observations.append(f"{item['summary_context']}，{item['title']}为{number(item['value'])}（{grid}）"
                if item['status']=='available' else f"{item['summary_context']}，{item['title']}不可用，本次不作对应形态描述")
        summary='本次分析中，'+'；'.join(observations)+'。'
        if any(item['status']!='available' for item in descriptions['items']):summary+='具体不可用原因见详细报告。'
        sections.append(('血管量化文字摘要',[summary,
            '本段记录指标数值和可用性，不按旧平台经验区间进行偏低、中等或偏高分档。']))
    if detailed:
        sections.append(('量化特征（固定11项）',[
            f"{item['title']}：{number(item['value'])}；单位：{item['unit']}；网格：{item['grid'] or '未提供'}"
            if item['status']=='available' else f"{item['title']}：不可用；{item['reason']}；单位：{item['unit']}；网格：{item['grid'] or '未提供'}"
            for item in data['features']]))
    else:
        available=sum(item['status']=='available' for item in data['features'])
        sections.append(('量化概况',[f'固定11项特征中有{available}项可用；逐项数值、单位和网格见详细报告。']))
    if detailed and descriptions:
        lines=[]
        for item in descriptions['items']:
            observation=(f"本次数值：{number(item['value'])}；单位：{item['unit']}；网格：{item['grid'] or '未提供'}。"
                if item['status']=='available' else '本次不可用；原因：'+item['reason']+'。')
            lines.append(item['title']+'：'+item['explanation']+'\n'+observation+'\n核对提示：'+item['review_hint'])
        sections.append(('重合指标分项说明',lines))
    lines=([f"连续严重程度评分：{number(score['median'])}",
            f"95%后验区间：[{number(score['lower'])}, {number(score['upper'])}]",
            '区间宽度：'+number(score['ci95_width'])]
           if score['status']=='available' else ['连续评分与后验区间不可用：'+score['reason']])
    lines.append('原后验相对尺度，不转换为临床分期。')
    sections.append(('连续评分与后验区间',lines))
    sections.append(('SVM结构辅助分类',[
        'SVM辅助类别：'+svm['prediction'] if svm['status']=='available' else 'SVM结果不可用：'+svm['reason'],
        '独立于A6展示；未经概率校准，不提供SVM百分比。']))
    sections.append(('结果限制说明',data['limitations']))
    if detailed:
        generator=data['generator']
        lines=['模板版本：'+data['template_version'],
            '报告生成代码提交：'+str(generator.get('code_revision') or '未记录'),
            '报告生成代码存在未提交改动：'+('是' if generator.get('code_dirty') is True else '否' if generator.get('code_dirty') is False else '未知'),
            f"报告生成环境：软件{generator['software_version']}；PyQt {generator['pyqt']}；Qt {generator['qt']}",
            '分析软件版本：'+str(run.get('software_version') or '未知'),
            '分析代码提交：'+str(run.get('code_revision') or '未记录'),
            '分析代码存在未提交改动：'+('是' if run.get('code_dirty') is True else '否' if run.get('code_dirty') is False else '未知'),
            '输入文件SHA-256：'+str(image.get('file_sha256') or '未记录'),
            'RGB像素SHA-256：'+str(image.get('rgb_pixel_sha256') or '未记录'),
            '报告来源快照SHA-256：'+data['source_snapshot_sha256']]
        if descriptions:lines.insert(1,'指标文字规则版本：'+descriptions['rule_version'])
        for name,item in source['modules'].items():
            lines.extend([f"{MODULE_NAMES.get(name,name)}：{STATES.get(item.get('state'),item.get('state'))}；设备：{item.get('device') or '未记录'}",
                '模型版本：'+str(item.get('model_version') or '未记录'),
                '权重SHA-256：'+str(item.get('weights_sha256') or '不适用或未记录')])
            if item.get('error'):lines.append('模块错误码：'+str(item['error'].get('code') or '未知'))
        sections.append(('版本与来源追溯',lines))
    return sections


def render_text(report,detailed=True):
    lines=['ROP-Insight 结构化辅助分析报告','研究模型输出 - 不是临床诊断','']
    for title,items in report_sections(report,detailed):
        lines.extend(['【'+title+'】',*items,''])
    return '\n'.join(lines)


def render_html(report,detailed=True):
    parts=['<html><head><meta charset="utf-8"></head><body>',
        '<h1>ROP-Insight</h1><p class="subtitle">结构化辅助分析报告</p>',
        '<p class="notice">研究模型输出 - 不是临床诊断</p>']
    for title,items in report_sections(report,detailed):
        parts.append('<h2>'+escape(title)+'</h2>')
        if title=='量化特征（固定11项）':
            parts.append('<table width="100%" cellspacing="0" cellpadding="6"><thead><tr>'
                '<th width="33%">指标</th><th width="24%">数值 / 状态</th><th width="29%">单位</th><th width="14%">网格</th></tr></thead>')
            for item in report.data['features']:
                value=number(item['value']) if item['status']=='available' else '不可用'
                parts.append('<tr>'+''.join('<td>'+escape(str(text))+'</td>' for text in
                    (item['title'],value,item['unit'],item['grid'] or '未提供'))+'</tr>')
                if item['status']!='available':parts.append('<tr><td colspan="4" class="muted">原因：'+escape(item['reason'])+'</td></tr>')
            parts.append('</table>')
        elif title in ('连续评分与后验区间','SVM结构辅助分类'):
            parts.append('<p>'+'<br/>'.join(escape(str(item)) for item in items)+'</p>')
        else:
            parts.extend('<p>'+escape(str(item)).replace('\n','<br/>')+'</p>' for item in items)
    parts.append('</body></html>')
    return ''.join(parts)


STYLESHEET = '''
body { color: #243544; font-family: 'Microsoft YaHei', 'Noto Sans CJK SC', sans-serif; }
h1 { color: #0f766e; font-size: 22pt; margin-bottom: 2pt; }
.subtitle { font-size: 15pt; color: #334155; margin-top: 2pt; }
.notice { color: #7c4a12; background-color: #fff8e5; padding: 8pt; }
h2 { color: #0f766e; font-size: 12pt; margin-top: 16pt; margin-bottom: 7pt; page-break-after: avoid; }
p { margin-top: 3pt; margin-bottom: 5pt; line-height: 125%; }
table { border-collapse: collapse; margin-top: 8pt; }
th { background-color: #e7f3f0; color: #134e4a; font-weight: bold; text-align: left; }
td { border-bottom: 1px solid #dbe5e9; }
.muted { color: #64748b; font-size: 8pt; }
'''
