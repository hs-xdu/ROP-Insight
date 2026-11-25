"""Reference review must stay portable and distinguish reuse from implementation."""

from pathlib import Path
import re


def test_reference_review_links_and_source_inventory():
    docs=Path(__file__).resolve().parents[1]/'docs'
    text=(docs/'ROPAI_REUSE_REVIEW.md').read_text(encoding='utf-8')
    for link in re.findall(r'\]\(([^)]+\.md)\)',text):
        assert (docs/link).is_file()
    inventory=re.findall(r'^\| ([^|]+\.(?:py|html)) \| ([a-f0-9]{64}) \|$',text,re.MULTILINE)
    assert {path.strip() for path,_ in inventory}=={
        'ropaih5/index.html','ropaiweb/main.py','ropaiweb/worker_ropai.py',
        'ropaiweb/vascular_bridge.py','ropaiweb/vascular_analyze.py',
        'ROP_Classifier_App/rop_app/aggregate.py'}
    assert '尚未核对，P5模板暂不定稿' in text
    assert '没有开始 P5—P7 功能实现' in text


def test_reference_reuse_preserves_current_platform_and_algorithms():
    text=(Path(__file__).resolve().parents[1]/'docs/ROPAI_REUSE_REVIEW.md').read_text(encoding='utf-8')
    for boundary in ('保留当前 ROP-Insight','不迁入旧平台整体','11项特征','A6 单图概率',
                     '病例信息不进入分类模型','不迁移SQL','不迁移旧病例数据库','不连接旧数据库'):
        assert boundary in text
    for doc in ('DESIGN_V2.md','IMPLEMENTATION_ROADMAP.md','TECHNICAL_PLAN.md'):
        content=(Path(__file__).resolve().parents[1]/'docs'/doc).read_text(encoding='utf-8')
        assert '(ROPAI_REUSE_REVIEW.md)' in content
