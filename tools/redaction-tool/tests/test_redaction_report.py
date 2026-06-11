"""The unified end-of-run redaction report (build + render), stdlib only.

This is the report that a --dry-run preview and a real write run BOTH print —
byte-identical bodies, only the title/Output-at lines differ (the real==dry
requirement; see plans/decisions.md). Four fixed subsections, always rendered,
empty prints "none":

    PATTERN MATCHES (regex)  ·  MODEL ENTITIES (NER)
    CUSTOM KEYWORDS — blacked out  ·  CUSTOM KEYWORDS — replaced

Pure functions over a synthetic tally — no spaCy, no model, no files.

    python3 -m unittest tests.test_redaction_report -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from report_format import (
    entity_engine,
    build_redaction_report,
    render_redaction_report,
    assemble_report_inputs,
)


# ── entity_engine: regex (pattern recognizer) vs NER (spaCy model) ──────────────

class TestEntityEngine(unittest.TestCase):
    def test_email_and_url_are_regex(self):
        self.assertEqual(entity_engine("EMAIL_ADDRESS"), "regex")
        self.assertEqual(entity_engine("URL"), "regex")

    def test_phone_ssn_creditcard_are_regex(self):
        for t in ("PHONE_NUMBER", "US_SSN", "CREDIT_CARD", "IP_ADDRESS"):
            self.assertEqual(entity_engine(t), "regex", t)

    def test_person_org_location_are_ner(self):
        for t in ("PERSON", "ORGANIZATION", "LOCATION", "NRP", "DATE_TIME"):
            self.assertEqual(entity_engine(t), "NER", t)


# ── build_redaction_report: structure, subtotals, grand total, sorting ──────────

def _sample_tally():
    """A synthetic tally exercising every subsection. No real PII."""
    entity_tally = {
        "EMAIL_ADDRESS": {
            "jane.doe@example.com": 4,
            "mary.bello@example.org": 2,
            "support@acme.test": 1,
        },
        "URL": {
            "https://acme.test/dashboard": 3,
            "http://example.org/login": 2,
        },
    }
    # replace=None → blacked out; replace=str → pseudonym. Two aliases share [CLIENT-A].
    keyword_tally = [
        {"find": "Acme Corporation", "replace": None, "count": 6},
        {"find": "Project Falcon", "replace": None, "count": 2},
        {"find": "Acme Corp", "replace": "[CLIENT-A]", "count": 12},
        {"find": "Acme", "replace": "[CLIENT-A]", "count": 3},
        {"find": "Alex", "replace": "[ENG01]", "count": 4},
    ]
    return entity_tally, keyword_tally


class TestBuildReport(unittest.TestCase):
    def setUp(self):
        et, kt = _sample_tally()
        self.report = build_redaction_report(
            et, kt, replacement_char="█████",
            entity_replacements={"URL": "[URL]"})

    def test_pattern_matches_contains_email_and_url_blocks(self):
        types = [b["entity_type"] for b in self.report["pattern_matches"]]
        self.assertEqual(types, ["EMAIL_ADDRESS", "URL"])  # A-Z by type

    def test_model_entities_empty_when_no_ner_types(self):
        self.assertEqual(self.report["model_entities"], [])

    def test_email_subtotals(self):
        email = next(b for b in self.report["pattern_matches"]
                     if b["entity_type"] == "EMAIL_ADDRESS")
        self.assertEqual(email["unique"], 3)
        self.assertEqual(email["hits"], 7)
        self.assertEqual(email["replacement"], "█████")

    def test_url_replacement_token(self):
        url = next(b for b in self.report["pattern_matches"]
                   if b["entity_type"] == "URL")
        self.assertEqual(url["replacement"], "[URL]")
        self.assertEqual(url["hits"], 5)

    def test_entity_rows_sorted_by_count_desc(self):
        email = next(b for b in self.report["pattern_matches"]
                     if b["entity_type"] == "EMAIL_ADDRESS")
        counts = [r["count"] for r in email["rows"]]
        self.assertEqual(counts, sorted(counts, reverse=True))
        self.assertEqual(email["rows"][0]["text"], "jane.doe@example.com")

    def test_keywords_blackout_block(self):
        bo = self.report["keywords_blackout"]
        self.assertEqual(bo["unique"], 2)
        self.assertEqual(bo["hits"], 8)
        self.assertEqual(bo["replacement"], "█████")
        # highest count first
        self.assertEqual(bo["rows"][0]["text"], "Acme Corporation")

    def test_keywords_replaced_grouped_by_pseudonym(self):
        groups = self.report["keywords_replaced"]
        pseudos = [g["pseudonym"] for g in groups]
        self.assertEqual(pseudos, ["[CLIENT-A]", "[ENG01]"])  # A-Z

    def test_many_aliases_one_pseudonym_subtotal(self):
        client_a = next(g for g in self.report["keywords_replaced"]
                        if g["pseudonym"] == "[CLIENT-A]")
        self.assertEqual(client_a["aliases"], 2)
        self.assertEqual(client_a["hits"], 15)
        # aliases by hit-count desc
        self.assertEqual([r["text"] for r in client_a["rows"]], ["Acme Corp", "Acme"])

    def test_grand_total_is_sum_of_all_hits(self):
        # 7 (email) + 5 (url) + 8 (blackout) + 15 + 4 (replaced) = 39
        self.assertEqual(self.report["grand_total"], 39)


class TestBuildReportEmpty(unittest.TestCase):
    def test_all_subsections_empty(self):
        report = build_redaction_report({}, [], replacement_char="█████")
        self.assertEqual(report["pattern_matches"], [])
        self.assertEqual(report["model_entities"], [])
        self.assertEqual(report["keywords_blackout"]["rows"], [])
        self.assertEqual(report["keywords_replaced"], [])
        self.assertEqual(report["grand_total"], 0)

    def test_ner_entities_routed_to_model_section(self):
        report = build_redaction_report(
            {"PERSON": {"John Smith": 2, "Mary Bello": 1}}, [],
            replacement_char="█████")
        self.assertEqual(report["pattern_matches"], [])
        person = next(b for b in report["model_entities"]
                      if b["entity_type"] == "PERSON")
        self.assertEqual(person["hits"], 3)
        self.assertEqual(person["replacement"], "█████")


# ── render_redaction_report: subsections, none, real==dry body equality ─────────

class TestRenderReport(unittest.TestCase):
    def setUp(self):
        et, kt = _sample_tally()
        self.report = build_redaction_report(
            et, kt, replacement_char="█████",
            entity_replacements={"URL": "[URL]"})

    def _render(self, title, output_dir=None):
        return render_redaction_report(
            self.report, title=title, extensions=[".json"],
            files_scanned=12, files_matched=8, output_dir=output_dir)

    def test_all_four_subsection_headers_present(self):
        out = self._render("REDACTION PREVIEW (--dry-run)")
        self.assertIn("PATTERN MATCHES", out)
        self.assertIn("MODEL ENTITIES", out)
        self.assertIn("CUSTOM KEYWORDS — blacked out", out)
        self.assertIn("CUSTOM KEYWORDS — replaced", out)

    def test_empty_subsection_prints_none(self):
        out = self._render("REDACTION PREVIEW (--dry-run)")
        # MODEL ENTITIES is empty in the sample → must render "none"
        model_idx = out.index("MODEL ENTITIES")
        kw_idx = out.index("CUSTOM KEYWORDS — blacked out")
        self.assertIn("none", out[model_idx:kw_idx])

    def test_matched_text_and_counts_render(self):
        out = self._render("REDACTION PREVIEW (--dry-run)")
        self.assertIn("jane.doe@example.com", out)
        self.assertIn("×4", out)
        self.assertIn("[CLIENT-A]", out)
        self.assertIn("[URL]", out)

    def test_grand_total_line(self):
        out = self._render("REDACTION PREVIEW (--dry-run)")
        self.assertIn("GRAND TOTAL: 39", out)

    def test_extensions_line(self):
        out = self._render("REDACTION PREVIEW (--dry-run)")
        self.assertIn("Extensions scanned: .json", out)

    def test_real_run_has_output_line(self):
        out = self._render("REDACTION COMPLETE", output_dir="/tmp/x/redacted")
        self.assertIn("Output at:", out)
        self.assertIn("/tmp/x/redacted", out)

    def test_dry_run_has_no_output_line(self):
        out = self._render("REDACTION PREVIEW (--dry-run)")
        self.assertNotIn("Output at:", out)

    def test_multiline_match_collapsed_in_render(self):
        """A matched span crossing a line break must not inject literal newlines into
        the report body (regression: the rewrite once dropped this)."""
        rep = build_redaction_report(
            {"PERSON": {"John\nSmith": 1}}, [], replacement_char="█████")
        out = render_redaction_report(rep, title="T", files_scanned=1, files_matched=1)
        self.assertIn("John Smith", out)        # collapsed onto one line
        self.assertNotIn("John\nSmith", out)    # no embedded newline

    def test_real_equals_dry_body_byte_identical(self):
        """THE requirement: the body (PATTERN MATCHES … GRAND TOTAL) is identical
        between a dry-run and a real run — only title/Output-at differ."""
        dry = self._render("REDACTION PREVIEW (--dry-run)")
        real = self._render("REDACTION COMPLETE", output_dir="/tmp/x/redacted")

        def body(s):
            start = s.index("PATTERN MATCHES")
            end = s.index("GRAND TOTAL")
            end = s.index("\n", end)
            return s[start:end]

        self.assertEqual(body(dry), body(real))


# ── assemble_report_inputs: collector + kr.counts → builder inputs ──────────────

class TestAssembleReportInputs(unittest.TestCase):
    def test_non_kw_types_become_entity_tally(self):
        collector = {
            "EMAIL_ADDRESS": {"a@x.com": 2},
            "PERSON": {"John Smith": 1},
        }
        keywords = []
        entity_tally, keyword_tally = assemble_report_inputs(collector, keywords)
        self.assertEqual(entity_tally,
                         {"EMAIL_ADDRESS": {"a@x.com": 2}, "PERSON": {"John Smith": 1}})
        self.assertEqual(keyword_tally, [])

    def test_kw_types_map_to_keywords_and_sum_variants(self):
        # KW_0 matched two cased variants → summed under keyword 0's find.
        collector = {"KW_0": {"acme corp": 3, "ACME CORP": 1}, "KW_1": {"alex": 2}}
        keywords = [
            {"find": "Acme Corp", "replace": "[CLIENT-A]"},
            {"find": "Alex", "replace": "[ENG01]"},
        ]
        _, keyword_tally = assemble_report_inputs(collector, keywords)
        self.assertEqual(keyword_tally, [
            {"find": "Acme Corp", "replace": "[CLIENT-A]", "count": 4},
            {"find": "Alex", "replace": "[ENG01]", "count": 2},
        ])

    def test_zero_hit_keywords_omitted(self):
        collector = {"KW_0": {"acme corp": 1}}
        keywords = [
            {"find": "Acme Corp", "replace": "[CLIENT-A]"},
            {"find": "Unmatched", "replace": None},   # 0 hits → dropped
        ]
        _, keyword_tally = assemble_report_inputs(collector, keywords)
        finds = [k["find"] for k in keyword_tally]
        self.assertEqual(finds, ["Acme Corp"])

    def test_kr_counts_merged_with_collector(self):
        # keyword matched in a text file (kr) AND an image (collector KW_0) → summed.
        collector = {"KW_0": {"secret": 2}}            # image hits
        keywords = [{"find": "secret", "replace": None}]
        kr_counts = {"secret": 5}                       # text hits
        _, keyword_tally = assemble_report_inputs(collector, keywords, kr_counts=kr_counts)
        self.assertEqual(keyword_tally,
                         [{"find": "secret", "replace": None, "count": 7}])

    def test_keyword_only_text_mode_uses_kr_counts_alone(self):
        # No collector (text-only keyword mode) → tally comes purely from kr.counts.
        keywords = [{"find": "Acme", "replace": "[CLIENT-A]"},
                    {"find": "Bob", "replace": None}]
        kr_counts = {"Acme": 3, "Bob": 1}
        entity_tally, keyword_tally = assemble_report_inputs(None, keywords, kr_counts=kr_counts)
        self.assertEqual(entity_tally, {})
        self.assertEqual(keyword_tally, [
            {"find": "Acme", "replace": "[CLIENT-A]", "count": 3},
            {"find": "Bob", "replace": None, "count": 1},
        ])

    def test_end_to_end_assemble_then_build(self):
        collector = {
            "URL": {"https://x.test/a": 2},
            "KW_0": {"acme": 4},
        }
        keywords = [{"find": "Acme", "replace": "[CLIENT-A]"}]
        et, kt = assemble_report_inputs(collector, keywords)
        report = build_redaction_report(et, kt, replacement_char="█████",
                                        entity_replacements={"URL": "[URL]"})
        self.assertEqual(report["grand_total"], 6)
        self.assertEqual(report["pattern_matches"][0]["entity_type"], "URL")
        self.assertEqual(report["keywords_replaced"][0]["pseudonym"], "[CLIENT-A]")


if __name__ == "__main__":
    unittest.main()
