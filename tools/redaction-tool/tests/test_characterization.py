"""Characterization (pin-down) tests for redact.py's CURRENT behavior.

NOT TDD red-green — these capture what redact.py does TODAY, so the upcoming
keyword_redactor integration can't silently change a working path. Run under
the redaction-tool venv (redact.py imports yaml/presidio at module load):

    .venv/bin/python -m unittest tests.test_characterization -v
"""
import sys
import tempfile
import unittest
from collections import namedtuple
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import redact

Span = namedtuple("Span", ["start", "end", "entity_type"])


class TestNormalizeKeywords(unittest.TestCase):
    def test_plain_string_and_mapping_forms(self):
        cfg = {"custom_keywords": ["Acme Corp",
                                   {"find": "John Smith", "replace": "J.S."}]}
        self.assertEqual(redact.normalize_keywords(cfg), [
            {"find": "Acme Corp", "replace": None},
            {"find": "John Smith", "replace": "J.S."},
        ])


class TestAnonymize(unittest.TestCase):
    def test_spans_replaced_high_to_low_with_kw_and_default(self):
        text = "Hi Mary and Bob"
        results = [Span(3, 7, "KW_0"), Span(12, 15, "PERSON")]
        out = redact.anonymize(text, results, "█████", {"KW_0": "[A]"})
        self.assertEqual(out, "Hi [A] and █████")


class TestKeywordOnlyTextPath(unittest.TestCase):
    """The path keyword_redactor will replace: keyword-only (entities=[]) text redaction."""

    def test_keyword_only_swaps_term(self):
        cfg = dict(redact.DEFAULT_CONFIG)
        cfg["entities"] = []
        cfg["custom_keywords"] = [{"find": "Mary Bello", "replace": "[PERSON_A]"}]
        analyzer, kw_repl = redact.build_analyzer(cfg)
        text = "Met Mary Bello today."
        results = redact.analyze(text, analyzer, cfg, kw_repl)
        out = redact.anonymize(text, results, cfg["replacement"], kw_repl)
        self.assertEqual(out, "Met [PERSON_A] today.")

    def test_keyword_only_fires_no_ner(self):
        # entities=[] → an unlisted name is NOT detected (no NER), so passes through
        cfg = dict(redact.DEFAULT_CONFIG)
        cfg["entities"] = []
        cfg["custom_keywords"] = [{"find": "Mary Bello", "replace": "[PERSON_A]"}]
        analyzer, kw_repl = redact.build_analyzer(cfg)
        text = "Met Bob Reyes today."  # Bob Reyes is not a keyword
        results = redact.analyze(text, analyzer, cfg, kw_repl)
        out = redact.anonymize(text, results, cfg["replacement"], kw_repl)
        self.assertEqual(out, "Met Bob Reyes today.")  # unchanged


class TestHandlerNerPath(unittest.TestCase):
    """process_markdown/process_html with kr=None go through analyze+anonymize
    (the path my _redact_text refactor touched). Pin it deterministically with a
    keyword via the analyzer — no NER guessing, but exercises the same handler."""

    def _analyzer(self):
        cfg = dict(redact.DEFAULT_CONFIG)
        cfg["entities"] = []
        cfg["custom_keywords"] = [{"find": "Mary Bello", "replace": "[PERSON_A]"}]
        analyzer, kw_repl = redact.build_analyzer(cfg)
        return analyzer, cfg, kw_repl

    def test_markdown_handler_redacts_via_analyzer(self):
        analyzer, cfg, kw_repl = self._analyzer()
        tmp = Path(tempfile.mkdtemp())
        src = tmp / "a.md"
        src.write_text("Met Mary Bello.", encoding="utf-8")
        dst = tmp / "out.md"
        n = redact.process_markdown(src, dst, analyzer, cfg, kw_repl, dry_run=False)
        self.assertEqual(dst.read_text(encoding="utf-8"), "Met [PERSON_A].")
        self.assertEqual(n, 1)

    def test_html_handler_redacts_text_node_and_mailto(self):
        analyzer, cfg, kw_repl = self._analyzer()
        tmp = Path(tempfile.mkdtemp())
        src = tmp / "a.html"
        src.write_text('<p>Mary Bello here</p><a href="mailto:Mary Bello">x</a>',
                       encoding="utf-8")
        dst = tmp / "out.html"
        redact.process_html(src, dst, analyzer, cfg, kw_repl, dry_run=False)
        out = dst.read_text(encoding="utf-8")
        self.assertNotIn("Mary Bello", out)
        self.assertIn("[PERSON_A]", out)


if __name__ == "__main__":
    unittest.main()
