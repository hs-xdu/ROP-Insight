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
            r"^\| (P\d-[A-Z]) \| (V[\d.]+) \| (MVP|P\d-[A-Z]) \| [^|]+ \| [^|]+ \|$",
            self.text, re.MULTILINE,
        )
        expected = ["P2-A", "P2-B", "P2-C", "P2-D", "P2-E", "P3-A", "P3-B", "P4-A", "P4-B"]
        self.assertEqual([stage for stage, _, _ in rows], expected)
        details = re.findall(r"^### (P\d-[A-Z]) ", self.text, re.MULTILINE)
        self.assertEqual(details, expected)
        seen = {"MVP"}
        for stage, version, dependency in rows:
            self.assertIn(dependency, seen)
            self.assertEqual(version, {"P2": "V0.2", "P3": "V0.3", "P4": "V1.0"}[stage[:2]])
            seen.add(stage)


if __name__ == "__main__":
    unittest.main()
