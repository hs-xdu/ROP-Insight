"""Check that the plan links to the requirements and covers their acceptance IDs."""

from pathlib import Path
import re
import unittest


class TechnicalPlanTests(unittest.TestCase):
    def setUp(self):
        self.docs = Path(__file__).resolve().parents[1] / "docs"
        self.plan = (self.docs / "TECHNICAL_PLAN.md").read_text(encoding="utf-8")

    def test_requirement_link_resolves(self):
        links = re.findall(r"\]\(([^)]+\.md)\)", self.plan)
        self.assertIn("MVP.md", links)
        self.assertIn("DESIGN_V2.md", links)
        for target in links:
            self.assertTrue((self.docs / target).is_file(), target)

    def test_acceptance_mapping_matches_mvp(self):
        mvp = (self.docs / "MVP.md").read_text(encoding="utf-8")
        acceptance = mvp.split("## 6. 验收标准\n", 1)[1]
        expected = re.findall(r"^(\d+)\. ", acceptance, re.MULTILINE)
        actual = re.findall(r"^\| (\d+) \| \S.+ \|$", self.plan, re.MULTILINE)
        self.assertTrue(expected)
        self.assertEqual(actual, expected)

    def test_v2_acceptance_mapping_matches_design(self):
        design = (self.docs / "DESIGN_V2.md").read_text(encoding="utf-8")
        acceptance = design.split("### 9.2 总体验收条件\n", 1)[1].split("## 10.", 1)[0]
        expected = re.findall(r"^(\d+)\. ", acceptance, re.MULTILINE)
        actual = re.findall(r"^\| V2-(\d+) \| \S.+ \|$", self.plan, re.MULTILINE)
        self.assertTrue(expected)
        self.assertEqual(actual, expected)

    def test_sections_are_complete_and_ordered(self):
        sections = re.findall(r"^## (\d+)\. \S.*$", self.plan, re.MULTILINE)
        self.assertEqual(sections, [str(number) for number in range(1, 16)])

    def test_incremental_implementation_choices_and_backwards_compatibility(self):
        reporting = self.plan.split('## 13.', 1)[1].split('## 14.', 1)[0]
        cases = self.plan.split('## 14.', 1)[1].split('## 15.', 1)[0]
        history = self.plan.split('## 15.', 1)[1]
        for term in ('QTextDocument', 'QPdfWriter', '同一报告数据', '模板', '95%后验区间'):
            self.assertIn(term, reporting)
        self.assertIn('患者临床信息不进入分类模型', cases)
        self.assertIn('schema_version=1', history)
        self.assertIn('可重建的 JSON 索引', history)
        self.assertIn('不重新推理', history)


if __name__ == "__main__":
    unittest.main()
