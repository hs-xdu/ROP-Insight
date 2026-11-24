"""Validate the saved MVP specification without application dependencies."""

from pathlib import Path
import re
import unittest


class MvpDocumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (Path(__file__).resolve().parents[1] / "docs" / "MVP.md").read_text(
            encoding="utf-8"
        )

    def test_section_numbers_are_complete_and_ordered(self):
        sections = re.findall(r"^## (\d+)\. \S.*$", self.text, re.MULTILINE)
        self.assertEqual(sections, [str(number) for number in range(1, 7)])
        self.assertEqual(len(re.findall(r"^# \S.*$", self.text, re.MULTILINE)), 1)

    def test_acceptance_criteria_are_seven_nonempty_items(self):
        acceptance = self.text.split("## 6. 验收标准\n", 1)[1]
        items = re.findall(r"^(\d+)\. (\S.*)$", acceptance, re.MULTILINE)
        self.assertEqual([number for number, _ in items], list("1234567"))
        self.assertEqual(len({description for _, description in items}), 7)

    def test_original_technology_proposal_is_preserved(self):
        technology = self.text.split("## 4. 技术方案\n", 1)[1].split("## 5.", 1)[0]
        self.assertIn("Windows 本地运行", technology)
        self.assertIn("PyQt6", technology)
        self.assertIn("Python 3.12", technology)
        self.assertIn("Pillow、OpenCV（按需使用）", technology)


if __name__ == "__main__":
    unittest.main()
