"""Tests for redacting URLs/emails/keywords inside <a href> ATTRIBUTES (not just
visible text). Regression target: process_html previously scrubbed only `mailto:`
hrefs, so `<a href="https://…">` link targets leaked even with URL in `entities` —
the URL is often only in the attribute, never in the visible text.

Needs the venv (bs4 + the regex analyzer). Run:
    .venv/bin/python -m unittest tests.test_html_href -v
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import redact


def _process(html, entities, keywords=None):
    cfg = {**redact.DEFAULT_CONFIG,
           "entities": entities, "regex_only": True,
           "custom_keywords": keywords or []}
    analyzer, kw = redact.build_regex_analyzer(cfg)
    with tempfile.TemporaryDirectory() as d:
        src, dst = Path(d) / "in.html", Path(d) / "out.html"
        src.write_text(html, encoding="utf-8")
        redact.process_html(src, dst, analyzer, cfg, kw, dry_run=False)
        return dst.read_text(encoding="utf-8")


class TestHtmlHrefRedaction(unittest.TestCase):
    def test_http_href_attribute_is_redacted(self):
        # URL lives ONLY in the href, not the visible text — the reported leak.
        out = _process('<a href="https://example.com/secret-page">click here</a>',
                       entities=["URL"])
        self.assertNotIn("https://example.com/secret-page", out)
        self.assertIn("[URL]", out)

    def test_mailto_href_still_redacted(self):
        # Regression guard: the original mailto behavior must survive the generalization.
        out = _process('<a href="mailto:bob@example.com">email</a>',
                       entities=["EMAIL_ADDRESS"])
        self.assertNotIn("bob@example.com", out)

    def test_keyword_in_href_is_redacted(self):
        # A custom keyword embedded in a link target gets redacted too.
        out = _process('<a href="https://site.test/u/acme">x</a>',
                       entities=["URL"],
                       keywords=[{"find": "acme", "replace": "[CLIENT]"}])
        self.assertNotIn("acme", out)


class TestUrlLabelInHtml(unittest.TestCase):
    def test_bare_url_in_text_gets_domain_label(self):
        out = _process('<p>see https://notion.so/QA-1508ab04 today</p>', ["URL"])
        self.assertIn("[notion URL]", out)
        self.assertNotIn("notion.so/QA-1508ab04", out)

    def test_descriptive_link_keeps_text_appends_label_href_plain(self):
        out = _process('<a href="https://notion.so/QA-1508ab04">QA Sync Notes</a>', ["URL"])
        self.assertIn("QA Sync Notes", out)        # descriptive text kept
        self.assertIn("[notion URL]", out)         # service label appended for context
        self.assertIn('href="[URL]"', out)         # href redacted to PLAIN [URL]
        self.assertNotIn("notion.so", out)

    def test_url_as_text_link_becomes_label_not_doubled(self):
        out = _process('<a href="https://notion.so/x">https://notion.so/x</a>', ["URL"])
        self.assertEqual(out.count("[notion URL]"), 1)   # text→label, no appended duplicate
        self.assertIn('href="[URL]"', out)

    def test_keyword_domain_label_uses_alias(self):
        out = _process('<a href="https://acme.atlassian.net/x">Ticket</a>', ["URL"],
                       keywords=[{"find": "atlassian", "replace": "[FOO-26]"}])
        self.assertIn("Ticket [FOO-26 URL]", out)


if __name__ == "__main__":
    unittest.main()
