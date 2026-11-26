"""Validate the saved second design document's structure and phase coverage."""

from pathlib import Path
import re
import unittest


class DesignV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (Path(__file__).resolve().parents[1] / "docs" / "DESIGN_V2.md").read_text(
            encoding="utf-8"
        )

    def test_original_and_incremental_sections_are_in_order(self):
        sections = re.findall(r"^## (\d+)\. \S.*$", self.text, re.MULTILINE)
        self.assertEqual(sections, [str(number) for number in range(1, 15)])
        self.assertEqual(len(re.findall(r"^# \S.*$", self.text, re.MULTILINE)), 1)

    def test_phase_table_preserves_milestones(self):
        phases = re.findall(
            r"^\| (P\d) \| [^\n|]+ \| ([^\n|]+) \|$", self.text, re.MULTILINE
        )
        self.assertEqual(phases, [
            ("P1", "MVP（已完成）"), ("P2", "V0.2"),
            ("P3", "V0.3"), ("P4", "V1.0"),
            ("P5", "增量（待定）"), ("P6", "增量（待定）"), ("P7", "增量（待定）"),
        ])

    def test_new_scope_preserves_reporting_and_privacy_boundaries(self):
        report = self.text.split('## 12.', 1)[1].split('## 13.', 1)[0]
        case = self.text.split('## 13.', 1)[1].split('## 14.', 1)[0]
        history = self.text.split('## 14.', 1)[1]
        for term in ('固定规则与模板', 'PDF', '11 项', 'T1', '95% 后验区间', '不让大语言模型自由作出临床判断'):
            self.assertIn(term, report)
        for term in ('匿名研究编号', '不强制录入姓名', '患者临床信息不进入分类模型', '左右眼', '检查日期', '备注'):
            self.assertIn(term, case)
        for term in ('result.json', 'SQLite', '不触发模型推理', '报告未生成'):
            self.assertIn(term, history)
        self.assertNotIn('指定的 10 项结构特征', self.text)


if __name__ == "__main__":
    unittest.main()
