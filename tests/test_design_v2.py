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

    def test_all_eleven_sections_are_preserved_in_order(self):
        sections = re.findall(r"^## (\d+)\. \S.*$", self.text, re.MULTILINE)
        self.assertEqual(sections, [str(number) for number in range(1, 12)])
        self.assertEqual(len(re.findall(r"^# \S.*$", self.text, re.MULTILINE)), 1)

    def test_phase_table_preserves_milestones(self):
        phases = re.findall(
            r"^\| (P\d) \| [^\n|]+ \| ([^\n|]+) \|$", self.text, re.MULTILINE
        )
        self.assertEqual(phases, [
            ("P1", "MVP（已完成）"), ("P2", "V0.2"),
            ("P3", "V0.3"), ("P4", "V1.0"),
        ])


if __name__ == "__main__":
    unittest.main()
