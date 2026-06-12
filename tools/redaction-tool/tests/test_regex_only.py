"""regex_only config toggle — _RegexAnalyzer, build_regex_analyzer, run() integration.

Tests verify:
  - _RegexAnalyzer dispatches to the right recognizers and skips ones it doesn't hold
  - build_regex_analyzer smoke: returns a _RegexAnalyzer that can match an email
  - run() with regex_only:true calls build_regex_analyzer (not build_analyzer)
  - run() report shows MODEL ENTITIES → N/A when regex_only:true
  - NER types in `entities` don't cause model load when regex_only:true

    .venv/bin/python -m unittest tests.test_regex_only -v
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import redact


def _regex_cfg(**over):
    cfg = dict(redact.DEFAULT_CONFIG)
    cfg["entities"] = ["EMAIL_ADDRESS"]
    cfg["custom_keywords"] = []
    cfg["regex_only"] = True
    cfg.update(over)
    return cfg


def _run_regex(tc, text, cfg, dry_run=True):
    """Run run() over one note.md with build_regex_analyzer patched; return log text."""
    tmpdir = Path(tempfile.mkdtemp())
    (tmpdir / "note.md").write_text(text, encoding="utf-8")
    mock_analyzer = MagicMock()
    mock_analyzer.analyze.return_value = []
    with patch("redact.build_regex_analyzer", return_value=(mock_analyzer, {})) as br:
        with tc.assertLogs("redact", level="INFO") as cm:
            redact.run(tmpdir, cfg, dry_run=dry_run)
    return "\n".join(cm.output), br


class TestRegexAnalyzer(unittest.TestCase):
    def _make_analyzer(self, entity_type, hit_span):
        """Build a _RegexAnalyzer with a single mock recognizer for entity_type."""
        rec = MagicMock()
        rec.supported_entities = [entity_type]
        rec.analyze.return_value = [hit_span]
        return redact._RegexAnalyzer([rec])

    def test_analyze_calls_recognizer_for_matching_entity(self):
        span = MagicMock()
        a = self._make_analyzer("EMAIL_ADDRESS", span)
        results = a.analyze("hi@example.com", ["EMAIL_ADDRESS"])
        self.assertEqual(results, [span])

    def test_analyze_skips_recognizer_when_entity_not_requested(self):
        span = MagicMock()
        a = self._make_analyzer("EMAIL_ADDRESS", span)
        results = a.analyze("hi@example.com", ["PERSON"])
        self.assertEqual(results, [])

    def test_analyze_empty_text_returns_empty(self):
        rec = MagicMock()
        rec.supported_entities = ["EMAIL_ADDRESS"]
        a = redact._RegexAnalyzer([rec])
        self.assertEqual(a.analyze("", ["EMAIL_ADDRESS"]), [])
        self.assertEqual(a.analyze("   ", ["EMAIL_ADDRESS"]), [])
        rec.analyze.assert_not_called()

    def test_analyze_aggregates_multiple_recognizers(self):
        s1, s2 = MagicMock(), MagicMock()
        r1 = MagicMock(supported_entities=["EMAIL_ADDRESS"])
        r1.analyze.return_value = [s1]
        r2 = MagicMock(supported_entities=["URL"])
        r2.analyze.return_value = [s2]
        a = redact._RegexAnalyzer([r1, r2])
        results = a.analyze("text", ["EMAIL_ADDRESS", "URL"])
        self.assertIn(s1, results)
        self.assertIn(s2, results)


class TestBuildRegexAnalyzer(unittest.TestCase):
    def test_smoke_email_address_recognized(self):
        cfg = dict(redact.DEFAULT_CONFIG)
        cfg["entities"] = ["EMAIL_ADDRESS"]
        cfg["custom_keywords"] = []
        analyzer, kw_repl = redact.build_regex_analyzer(cfg)
        self.assertIsInstance(analyzer, redact._RegexAnalyzer)
        results = analyzer.analyze("reach me at test@example.com today", ["EMAIL_ADDRESS"])
        self.assertTrue(any(r.entity_type == "EMAIL_ADDRESS" for r in results))

    def test_ner_type_in_entities_not_added_as_recognizer(self):
        cfg = dict(redact.DEFAULT_CONFIG)
        cfg["entities"] = ["PERSON", "EMAIL_ADDRESS"]
        cfg["custom_keywords"] = []
        analyzer, _ = redact.build_regex_analyzer(cfg)
        # PERSON is NER — no recognizer for it; EMAIL hits but PERSON never fires
        results = analyzer.analyze("John Smith emailed test@example.com", ["PERSON", "EMAIL_ADDRESS"])
        types = {r.entity_type for r in results}
        self.assertIn("EMAIL_ADDRESS", types)
        self.assertNotIn("PERSON", types)

    def test_keyword_recognizer_added(self):
        cfg = dict(redact.DEFAULT_CONFIG)
        cfg["entities"] = []
        cfg["custom_keywords"] = [{"find": "acmecorp", "replace": "[CLIENT]"}]
        analyzer, kw_repl = redact.build_regex_analyzer(cfg)
        results = analyzer.analyze("contact acmecorp today", ["KW_0"])
        self.assertTrue(any(r.entity_type == "KW_0" for r in results))
        self.assertEqual(kw_repl["KW_0"], "[CLIENT]")


class TestRegexOnlyRun(unittest.TestCase):
    def test_build_regex_analyzer_called_not_build_analyzer(self):
        cfg = _regex_cfg()
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "note.md").write_text("hello", encoding="utf-8")
        mock_analyzer = MagicMock()
        mock_analyzer.analyze.return_value = []
        with patch("redact.build_regex_analyzer", return_value=(mock_analyzer, {})) as br:
            with patch("redact.build_analyzer") as ba:
                with self.assertLogs("redact", level="INFO"):
                    redact.run(tmpdir, cfg, dry_run=True)
        br.assert_called_once()
        ba.assert_not_called()

    def test_model_entities_na_in_report(self):
        """regex_only:true → MODEL ENTITIES subsection shows N/A (not engaged)."""
        out, _ = _run_regex(self, "no matches here", _regex_cfg())
        self.assertIn("MODEL ENTITIES", out)
        self.assertIn("N/A", out)

    def test_ner_type_in_entities_still_skips_model(self):
        """NER types in entities don't trigger model load when regex_only:true."""
        cfg = _regex_cfg(entities=["PERSON", "EMAIL_ADDRESS"])
        out, br = _run_regex(self, "hello", cfg)
        br.assert_called_once()  # build_regex_analyzer, not build_analyzer
        self.assertIn("N/A", out)  # model not engaged

    def test_regex_only_false_uses_build_analyzer(self):
        cfg = _regex_cfg(regex_only=False)
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "note.md").write_text("hello", encoding="utf-8")
        with patch("redact.build_regex_analyzer") as br:
            with patch("redact.build_analyzer", return_value=(MagicMock(), {})) as ba:
                with patch("redact.analyze", return_value=[]):
                    with self.assertLogs("redact", level="INFO"):
                        redact.run(tmpdir, cfg, dry_run=True)
        br.assert_not_called()
        ba.assert_called_once()


if __name__ == "__main__":
    unittest.main()
