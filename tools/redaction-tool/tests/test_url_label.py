"""Tests for url_token(): domain-aware URL replacement.

A redacted URL keeps its SERVICE as context — `https://notion.so/QA-1508ab04` →
`[Notion URL]` — instead of a bare `[URL]`. The label is the URL's registrable
domain, run through keyword redaction first (so a keyword domain → its alias).
Unknown/unparseable → plain `[URL]` (no domain leaked beyond the chosen label).

Stdlib-only (urllib + keyword_redactor); runs under system python3.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from redact import url_token
from keyword_redactor import KeywordRedactor


class TestUrlToken(unittest.TestCase):
    def test_known_domain_verbatim_lowercase(self):
        self.assertEqual(url_token("https://notion.so/QA-1508ab04"), "[notion URL]")

    def test_subdomain_uses_registrable_domain(self):
        # acme.atlassian.net → atlassian (the service), NOT the acme subdomain
        self.assertEqual(url_token("https://acme.atlassian.net/browse/QQ-42"),
                         "[atlassian URL]")

    def test_hyphenated_domain(self):
        self.assertEqual(url_token("https://random-co.com/x"), "[random-co URL]")

    def test_keyword_domain_uses_alias(self):
        kr = KeywordRedactor([{"find": "atlassian", "replace": "[FOO-26]"}])
        self.assertEqual(url_token("https://acme.atlassian.net/x", kr.redact),
                         "[FOO-26 URL]")

    def test_non_url_falls_back_to_plain(self):
        self.assertEqual(url_token("not a url"), "[URL]")

    def test_non_http_scheme_falls_back(self):
        # mailto/relative get no label here (emails handled elsewhere)
        self.assertEqual(url_token("mailto:a@b.com"), "[URL]")

    def test_trailing_punctuation_tolerated(self):
        # the blanket URL regex greedily grabs trailing punctuation; still label cleanly
        self.assertEqual(url_token("https://notion.so/x)."), "[notion URL]")


if __name__ == "__main__":
    unittest.main()
