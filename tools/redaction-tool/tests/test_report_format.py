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

    # ── restored wrapper: folder-named H1, bold meta pairs, file-type summary,
    #    two-line SENSITIVE banner (parity with the hand-saved prototype) ──

    def test_heading_sets_h1_and_keeps_itemized_banner(self):
        """heading drives the markdown H1 (identical dry-vs-real); the dry/real
        `title` still appears as the itemized banner inside the fence."""
        from report_format import render_markdown_report
        md = render_markdown_report(self._report(), title="REDACTION PREVIEW (--dry-run)",
                                    files_scanned=2, files_matched=2,
                                    heading="Redaction Report — sample-folder")
        self.assertIn("# Redaction Report — sample-folder", md)   # H1 = heading
        self.assertNotIn("# REDACTION PREVIEW", md)               # title NOT used as H1
        self.assertIn("REDACTION PREVIEW (--dry-run)", md)        # title is the itemized banner

    def test_heading_defaults_to_title(self):
        """Back-compat: with no heading, H1 falls back to title."""
        from report_format import render_markdown_report
        md = render_markdown_report(self._report(), title="REDACTION COMPLETE",
                                    files_scanned=1, files_matched=1)
        self.assertIn("# REDACTION COMPLETE", md)

    def test_meta_bold_pairs(self):
        """meta items may be (label, value) tuples → bold-key bullets."""
        from report_format import render_markdown_report
        md = render_markdown_report(self._report(), title="REDACTION COMPLETE",
                                    files_scanned=1, files_matched=1,
                                    meta=[("Generated", "2026-06-13 17:30 PDT"),
                                          ("Mode", "regex-only (no model)")])
        self.assertIn("- **Generated:** 2026-06-13 17:30 PDT", md)
        self.assertIn("- **Mode:** regex-only (no model)", md)

    def test_file_stats_rows_in_summary(self):
        """file_stats rows appear in the Summary, above GRAND TOTAL."""
        from report_format import render_markdown_report
        md = render_markdown_report(self._report(), title="REDACTION COMPLETE",
                                    files_scanned=15, files_matched=6,
                                    file_stats=[("JSON files", 4), ("PDF files", 14),
                                                ("Errors", 0)])
        self.assertIn("| JSON files | 4 |", md)
        self.assertIn("| PDF files | 14 |", md)
        self.assertIn("| Errors | 0 |", md)
        self.assertLess(md.index("| JSON files | 4 |"), md.index("| GRAND TOTAL |"))

    def test_two_line_sensitive_banner(self):
        """The keep-local banner is a two-line blockquote."""
        from report_format import render_markdown_report
        md = render_markdown_report(self._report(), title="REDACTION COMPLETE",
                                    files_scanned=1, files_matched=1)
        self.assertIn("SENSITIVE", md)
        self.assertIn("\n> Keep it local", md)                    # a genuine 2nd blockquote line


if __name__ == "__main__":
    unittest.main()
