"""Tests for the blanket URL recognizer.

A case-insensitive `https?://\\S+` pattern, opt-in by adding `URL` to `entities`,
redacted to the literal token `[URL]` (wired through kw_replacements so
anonymize() emits it). These avoid loading spaCy by testing the regex, the
registration helper (mock analyzer), and anonymize() directly.

    .venv/bin/python -m unittest tests.test_url_recognizer -v
"""
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import redact


def _span(start, end, entity_type):
    r = MagicMock()
    r.start, r.end, r.entity_type = start, end, entity_type
    return r


class TestUrlRegex(unittest.TestCase):
    def test_matches_http_https_any_case(self):
        self.assertTrue(re.search(redact.URL_REGEX, "see https://example.com/a/b?x=1"))
        self.assertTrue(re.search(redact.URL_REGEX, "http://foo.io"))
        self.assertTrue(re.search(redact.URL_REGEX, "HTTPS://FOO.IO"))   # case-insensitive

    def test_grabs_whole_url_token(self):
        m = re.search(redact.URL_REGEX, "go to https://example.com/path?q=2 now")
        self.assertEqual(m.group(0), "https://example.com/path?q=2")

    def test_trailing_punctuation_is_captured_known(self):
        # Blanket \\S+ greedily includes trailing punctuation. Acceptable (over-redacts
        # a char or two); pinned so it's an intentional trade-off, not a surprise.
        m = re.search(redact.URL_REGEX, "(see https://example.com).")
        self.assertEqual(m.group(0), "https://example.com).")

    def test_ignores_non_urls(self):
        self.assertIsNone(re.search(redact.URL_REGEX, "no link here"))
        self.assertIsNone(re.search(redact.URL_REGEX, "email a@b.com"))
        self.assertIsNone(re.search(redact.URL_REGEX, "ftp://host/file"))  # http(s) only


class TestRegisterUrlRecognizer(unittest.TestCase):
    def test_registered_when_url_enabled(self):
        cfg = {"entities": ["PERSON", "URL"]}
        kw = {}
        analyzer = MagicMock()
        self.assertTrue(redact._register_url_recognizer(analyzer, cfg, kw))
        self.assertEqual(kw["URL"], "[URL]")             # drives anonymize() -> [URL]
        analyzer.registry.add_recognizer.assert_called_once()
        # The recognizer must actually emit the "URL" entity type, or the [URL]
        # replacement in kw_replacements would never apply.
        rec = analyzer.registry.add_recognizer.call_args.args[0]
        self.assertEqual(rec.supported_entities, ["URL"])

    def test_skipped_when_url_not_enabled(self):
        cfg = {"entities": ["PERSON"]}
        kw = {}
        analyzer = MagicMock()
        self.assertFalse(redact._register_url_recognizer(analyzer, cfg, kw))
        self.assertNotIn("URL", kw)
        analyzer.registry.add_recognizer.assert_not_called()


class TestAnonymizeUrl(unittest.TestCase):
    def test_url_span_becomes_bracket_token_in_context(self):
        text = "see https://example.com today"
        start = text.index("https")
        end = start + len("https://example.com")
        out = redact.anonymize(text, [_span(start, end, "URL")], "█████", {"URL": "[URL]"})
        self.assertEqual(out, "see [URL] today")

    def test_mixed_entities_use_their_own_replacements(self):
        # URL -> [URL] while a non-URL entity still gets the default block char.
        text = "Bob at https://x.io"
        spans = [_span(0, 3, "PERSON"), _span(7, len(text), "URL")]
        out = redact.anonymize(text, spans, "█████", {"URL": "[URL]"})
        self.assertEqual(out, "█████ at [URL]")


if __name__ == "__main__":
    unittest.main()
