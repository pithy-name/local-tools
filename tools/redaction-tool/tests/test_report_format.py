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


class TestRenderMarkdownReport(unittest.TestCase):
    """`--report` markdown: SENSITIVE banner + optional meta + Summary table +
    the full itemized text report in a fence. Synthetic tally only."""

    def _report(self):
        from report_format import build_redaction_report
        entity_tally = {"EMAIL_ADDRESS": {"a@b.test": 2}, "URL": {"http://x.test": 1}}
        keyword_tally = [{"find": "Foo", "replace": None, "count": 3},
                         {"find": "Bar", "replace": "ENG01", "count": 5}]
        return build_redaction_report(entity_tally, keyword_tally,
                                      entity_replacements={"URL": "[URL]"})

    def test_structure_banner_table_and_fenced_itemized(self):
        from report_format import render_markdown_report
        md = render_markdown_report(self._report(), title="REDACTION COMPLETE",
                                    files_scanned=2, files_matched=2)
        self.assertIn("# REDACTION COMPLETE", md)        # H1
        self.assertIn("SENSITIVE", md)                    # keep-local banner
        self.assertIn("## Summary", md)
        self.assertIn("| GRAND TOTAL |", md)              # summary table row
        self.assertIn("PATTERN — EMAIL_ADDRESS", md)      # per-entity summary row
        self.assertIn("Keywords — replaced", md)
        self.assertIn("```", md)                          # fenced itemized block
        self.assertIn("PATTERN MATCHES", md)              # the itemized text is embedded

    def test_meta_bullets_included(self):
        from report_format import render_markdown_report
        md = render_markdown_report(self._report(), title="REDACTION COMPLETE",
                                    files_scanned=1, files_matched=1,
                                    meta=["Mode: regex-only", "entities: EMAIL_ADDRESS, URL"])
        self.assertIn("- Mode: regex-only", md)
        self.assertIn("- entities: EMAIL_ADDRESS, URL", md)


if __name__ == "__main__":
    unittest.main()
