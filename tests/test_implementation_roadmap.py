"""Check roadmap links, stage dependencies, and coverage of the release phases."""

from pathlib import Path
import re
import unittest


class ImplementationRoadmapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = Path(__file__).resolve().parents[1] / "docs"
        cls.text = (cls.docs / "IMPLEMENTATION_ROADMAP.md").read_text(encoding="utf-8")

    def test_local_links_resolve(self):
        links = re.findall(r"\]\(([^)]+\.md)\)", self.text)
        self.assertIn("DESIGN_V2.md", links)
        self.assertIn("TECHNICAL_PLAN.md", links)
        for target in links:
            self.assertTrue((self.docs / target).is_file(), target)

    def test_stages_have_details_and_prior_dependencies(self):
        rows = re.findall(
            r"^\| (P\d(?:-[A-Z])?) \| ([^\n|]+) \| (MVP|P\d(?:-[A-Z])?) \| [^|]+ \| [^|]+ \|$",
            self.text, re.MULTILINE,
        )
        expected = ["P2-A", "P2-B", "P2-C", "P2-D", "P2-E", "P3-A", "P3-B", "P4-A", "P4-B", "P5", "P6", "P7"]
        self.assertEqual([stage for stage, _, _ in rows], expected)
        details = re.findall(r"^### (P\d(?:-[A-Z])?) ", self.text, re.MULTILINE)
        self.assertEqual(details, expected)
        seen = {"MVP"}
        for stage, version, dependency in rows:
            self.assertIn(dependency, seen)
            self.assertEqual(version.strip(), {"P2": "V0.2", "P3": "V0.3", "P4": "V1.0"}.get(stage[:2], '增量（待定）'))
            seen.add(stage)

    def test_incremental_phases_keep_priorities_and_actual_status(self):
        for stage, priority in [('P5', '优先'), ('P6', '建议'), ('P7', '可选')]:
            row = next(line for line in self.text.splitlines() if line.startswith('| '+stage+' |'))
            self.assertIn(priority, row)
            self.assertIn('工程实现及自审通过' if stage=='P5' else '已规划未实施', row)
        self.assertIn('不依赖 P6', self.text)


if __name__ == "__main__":
    unittest.main()
