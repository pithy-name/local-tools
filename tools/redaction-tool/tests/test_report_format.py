import sys
import unittest
from collections import Counter, namedtuple
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_Span = namedtuple("_Span", ["entity_type", "start", "end"])


def _fake_analyze(text):
    """Flag every 'Alice' as PERSON."""
    out, i = [], text.find("Alice")
    while i != -1:
        out.append(_Span("PERSON", i, i + 5))
        i = text.find("Alice", i + 1)
    return out


class TestCollectEntities(unittest.TestCase):
    def test_groups_by_type_dedups_and_counts(self):
        from report_format import collect_entities
        found = collect_entities(["Alice and Alice", "no name", "Alice"], _fake_analyze)
        self.assertEqual(found["PERSON"]["Alice"], 3)


class TestRenderScanReport(unittest.TestCase):
    def test_render_groups_with_unique_count(self):
        from report_format import render_scan_report
        found = {"PERSON": Counter({"Alice": 3, "Bob": 1}),
                 "ORGANIZATION": Counter({"Acme Corp": 2})}
        s = render_scan_report(found)
        self.assertIn("PERSON  (2 unique)", s)
        self.assertIn("Alice", s)
        self.assertIn("ORGANIZATION  (1 unique)", s)

    def test_render_empty(self):
        from report_format import render_scan_report
        self.assertIn("No candidate", render_scan_report({}))


if __name__ == "__main__":
    unittest.main()
