"""Characterization (pin-down) tests for redact.py's CURRENT behavior.

NOT TDD red-green — these capture what redact.py does TODAY, so the upcoming
keyword_redactor integration can't silently change a working path. Run under
the redaction-tool venv (redact.py imports yaml/presidio at module load):

    .venv/bin/python -m unittest tests.test_characterization -v
"""
import sys
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


if __name__ == "__main__":
    unittest.main()
