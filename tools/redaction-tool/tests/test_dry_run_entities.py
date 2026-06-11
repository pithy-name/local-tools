"""run()'s unified end-of-run report — dry-run AND real write run (real==dry).

The report is the SAME for `--dry-run` and a real run (real==dry), printed in every
mode. It itemizes matched text by section (PATTERN MATCHES / MODEL ENTITIES / CUSTOM
KEYWORDS blacked out / replaced). Per the 2026-06-11 decision, matched PII IS printed
in the real run too (audit visibility, same exposure as --scan) — this intentionally
reverses the earlier guards that hid entity text from live runs and keyword text from
the list. See tools/redaction-tool/decisions.md.

build_analyzer is patched so no spaCy model loads; analyze() is patched to return known
spans, so these run fast under system python3.

    python3 -m unittest tests.test_dry_run_entities -v
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import redact


def _ner_cfg(**over):
    cfg = dict(redact.DEFAULT_CONFIG)
    cfg["entities"] = ["PERSON"]
    cfg["custom_keywords"] = []
    cfg.update(over)
    return cfg


def _span(start, end, entity_type):
    r = MagicMock()
    r.start = start
    r.end = end
    r.entity_type = entity_type
    return r


def _run(tc, text, spans, cfg, dry_run):
    """Run run() over one note.md with build_analyzer/analyze patched; return log text."""
    tmpdir = Path(tempfile.mkdtemp())
    (tmpdir / "note.md").write_text(text, encoding="utf-8")
    with patch("redact.build_analyzer", return_value=(MagicMock(), {})):
        with patch("redact.analyze", return_value=spans):
            with tc.assertLogs("redact", level="INFO") as cm:
                redact.run(tmpdir, cfg, dry_run=dry_run)
    return "\n".join(cm.output)


class TestUnifiedReportNER(unittest.TestCase):
    def test_dry_run_shows_ner_entity_under_model_section(self):
        out = _run(self, "Hello John Smith today", [_span(6, 16, "PERSON")],
                   _ner_cfg(), dry_run=True)
        self.assertIn("MODEL ENTITIES", out)
        self.assertIn("PERSON", out)
        self.assertIn("John Smith", out)         # matched text itemized

    def test_real_run_shows_entity_text_too(self):
        """Reversed guard: the live run now prints the matched text (real==dry)."""
        out = _run(self, "Hello John Smith today", [_span(6, 16, "PERSON")],
                   _ner_cfg(), dry_run=False)
        self.assertIn("John Smith", out)
        self.assertIn("REDACTION COMPLETE", out)
        self.assertIn("Output at:", out)

    def test_real_equals_dry_body_identical(self):
        text, spans = "Hello John Smith today", [_span(6, 16, "PERSON")]
        dry = _run(self, text, spans, _ner_cfg(), dry_run=True)
        real = _run(self, text, spans, _ner_cfg(), dry_run=False)

        def body(s):
            start = s.index("PATTERN MATCHES")
            end = s.index("GRAND TOTAL")
            end = s.index("\n", end)
            return s[start:end]

        self.assertEqual(body(dry), body(real))

    def test_grand_total_matches_total_redactions(self):
        out = _run(self, "Hello John Smith today", [_span(6, 16, "PERSON")],
                   _ner_cfg(), dry_run=True)
        self.assertIn("Total redactions : 1", out)
        self.assertIn("GRAND TOTAL: 1", out)


class TestFailedFileInvariant(unittest.TestCase):
    def test_partial_matches_from_a_raising_handler_are_discarded(self):
        """A handler that populates the collector then raises must NOT leak its partial
        matches into the report — grand_total stays equal to total_redactions."""
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "bad.md").write_text("anything", encoding="utf-8")

        def boom(src, dst, analyzer, cfg, kw_replacements, dry_run, kr=None, collector=None):
            collector.setdefault("PERSON", {})["Leaked Name"] = 1   # partial populate
            raise RuntimeError("handler blew up mid-file")

        with patch("redact.build_analyzer", return_value=(MagicMock(), {})):
            with patch("redact.process_markdown", boom):
                with self.assertLogs("redact", level="INFO") as cm:
                    redact.run(tmpdir, _ner_cfg(), dry_run=True)
        out = "\n".join(cm.output)

        self.assertNotIn("Leaked Name", out)     # partial match discarded
        self.assertIn("GRAND TOTAL: 0", out)     # failed file contributes nothing
        self.assertIn("Total redactions : 0", out)


class TestCustomKeywordsShown(unittest.TestCase):
    def test_keyword_find_shown_internal_label_hidden(self):
        """Custom keywords ARE now itemized (find + pseudonym); the internal KW_i
        label is NOT exposed."""
        cfg = _ner_cfg(custom_keywords=[{"find": "John Smith", "replace": "J.S."}])
        out = _run(self, "Hello John Smith today", [_span(6, 16, "KW_0")], cfg, dry_run=True)
        self.assertIn("CUSTOM KEYWORDS — replaced", out)
        self.assertIn("John Smith", out)         # the find, itemized
        self.assertIn("J.S.", out)               # its pseudonym
        self.assertNotIn("KW_0", out)            # internal label stays hidden


class TestKeywordOnlyModeUnified(unittest.TestCase):
    def test_keyword_only_mode_prints_unified_report(self):
        """Keyword-only mode (entities=[]) uses the SAME unified report — no model,
        no patching; kr drives the counts."""
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "note.md").write_text("Hello secret secret today", encoding="utf-8")
        cfg = dict(redact.DEFAULT_CONFIG)
        cfg["entities"] = []
        cfg["custom_keywords"] = [{"find": "secret", "replace": "[X]"}]

        with self.assertLogs("redact", level="INFO") as cm:
            redact.run(tmpdir, cfg, dry_run=True)
        out = "\n".join(cm.output)

        self.assertIn("CUSTOM KEYWORDS — replaced", out)
        self.assertIn("secret", out)
        self.assertIn("[X]", out)
        self.assertIn("×2", out)                 # matched twice
        self.assertIn("GRAND TOTAL: 2", out)


if __name__ == "__main__":
    unittest.main()
