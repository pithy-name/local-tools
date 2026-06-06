import sys
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from report_format import build_count_report


class TestBuildCountReport(unittest.TestCase):
    def test_text_only_groups_by_pseudonym_with_subtotals(self):
        mappings = [{"find": "mary", "replace": "[A]"},
                    {"find": "mary bello", "replace": "[A]"},
                    {"find": "bob", "replace": "[B]"}]
        counts = Counter({"mary": 5, "mary bello": 3, "bob": 2})
        r = build_count_report(mappings, counts)  # no blackout data → N/A
        self.assertEqual(r["total_text"], 10)
        self.assertIsNone(r["total_blackout"])
        self.assertEqual([g["pseudonym"] for g in r["groups"]], ["[A]", "[B]"])
        self.assertEqual(r["groups"][0]["rows"][0],
                         {"find": "mary", "text": 5, "blackout": None})
        self.assertEqual(r["groups"][0]["subtotal"], {"text": 8, "blackout": None})
        self.assertEqual(r["groups"][1]["subtotal"], {"text": 2, "blackout": None})

    def test_blackout_counts_when_provided(self):
        mappings = [{"find": "mary", "replace": "[A]"}]
        r = build_count_report(mappings, Counter({"mary": 5}), Counter({"mary": 2}))
        self.assertEqual(r["groups"][0]["rows"][0],
                         {"find": "mary", "text": 5, "blackout": 2})
        self.assertEqual(r["total_blackout"], 2)


class TestRender(unittest.TestCase):
    def test_render_text_only_shows_na_and_subtotals(self):
        from report_format import render_count_report
        rep = build_count_report(
            [{"find": "mary", "replace": "[A]"},
             {"find": "mary bello", "replace": "[A]"}],
            Counter({"mary": 5, "mary bello": 3}))
        s = render_count_report(rep)
        self.assertIn("[A]  (mary)  text-sub: 5  blackout: N/A", s)
        self.assertIn("[A] subtotal  text-sub: 8  blackout: N/A", s)
        self.assertIn("Total text-subs : 8", s)
        self.assertIn("Total blackouts : N/A", s)

    def test_render_blackout_zero_distinct_from_na(self):
        from report_format import render_count_report
        rep = build_count_report([{"find": "x", "replace": "[X]"}],
                                 Counter({"x": 1}), Counter())  # engaged, none found → 0
        s = render_count_report(rep)
        self.assertIn("blackout: 0", s)
        self.assertNotIn("blackout: N/A", s)


if __name__ == "__main__":
    unittest.main()
