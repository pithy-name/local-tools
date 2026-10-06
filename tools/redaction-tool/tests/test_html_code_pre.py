"""Tests for redacting keywords/emails/URLs inside HTML <code> and <pre> elements.
Regression target: process_html skipped every text node whose parent was <code> or
<pre> (alongside <script>/<style>), so a term shown in a code block leaked verbatim
into the redacted output — while the same term in a <p> was redacted.

Needs the venv (bs4 + the regex analyzer). Run:
    .venv/bin/python -m unittest tests.test_html_code_pre -v
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import redact

KEYWORDS = ["Zorblatt", {"find": "Quendle Marsh", "replace": "[ENG-01]"}]


def _process(html, entities=(), keywords=KEYWORDS, dry_run=False, keyword_only=False):
    """Run process_html → (output html or None on dry-run, n_redactions)."""
    cfg = {**redact.DEFAULT_CONFIG,
           "entities": list(entities), "regex_only": True,
           "custom_keywords": keywords}
    analyzer, kw = redact.build_regex_analyzer(cfg)
    kr = redact.make_keyword_redactor_from_config(cfg) if keyword_only else None
    with tempfile.TemporaryDirectory() as d:
        src, dst = Path(d) / "in.html", Path(d) / "out.html"
        src.write_text(html, encoding="utf-8")
        n = redact.process_html(src, dst, analyzer, cfg, kw, dry_run=dry_run, kr=kr)
        return (dst.read_text(encoding="utf-8") if dst.exists() else None), n


class TestHtmlCodePreRedaction(unittest.TestCase):
    def test_keyword_in_inline_code_is_redacted(self):
        out, n = _process("<p>run <code>deploy Zorblatt</code> now</p>")
        self.assertNotIn("Zorblatt", out)
        self.assertEqual(n, 1)

    def test_keyword_in_pre_is_redacted(self):
        out, _ = _process("<pre>owner = Quendle Marsh\nhost = Zorblatt</pre>")
        self.assertNotIn("Quendle Marsh", out)
        self.assertNotIn("Zorblatt", out)
        self.assertIn("[ENG-01]", out)

    def test_keyword_in_pre_code_block_is_redacted(self):
        # The fenced-code-block shape most Markdown→HTML exporters emit.
        out, _ = _process('<pre><code class="language-py">name = "Zorblatt"</code></pre>')
        self.assertNotIn("Zorblatt", out)

    def test_keyword_in_highlighted_span_inside_code_is_redacted(self):
        # Syntax highlighters wrap tokens in <span>s inside <pre><code>.
        out, _ = _process('<pre><code><span class="s">Zorblatt</span></code></pre>')
        self.assertNotIn("Zorblatt", out)

    def test_pre_whitespace_and_markup_preserved(self):
        # Only the matched span changes — line breaks/indentation in <pre> survive.
        out, _ = _process("<pre>a = 1\n    b = Zorblatt\nc = 3</pre>")
        self.assertIn("<pre>a = 1\n    b = █████\nc = 3</pre>", out)

    def test_email_and_url_in_code_are_redacted(self):
        out, _ = _process(
            "<code>curl https://example.com/secret -u bob@example.com</code>",
            entities=["EMAIL_ADDRESS", "URL"], keywords=[])
        self.assertNotIn("bob@example.com", out)
        self.assertNotIn("https://example.com/secret", out)

    def test_keyword_only_engine_redacts_code(self):
        # entities: [] routes text through keyword_redactor (kr) instead of the analyzer.
        out, n = _process("<code>Zorblatt</code>", keyword_only=True)
        self.assertNotIn("Zorblatt", out)
        self.assertEqual(n, 1)

    def test_dry_run_counts_code_and_pre_matches(self):
        # The report is built from this count — dry-run must see the same matches.
        out, n = _process("<p>Zorblatt</p><code>Zorblatt</code><pre>Zorblatt</pre>",
                          dry_run=True)
        self.assertIsNone(out)
        self.assertEqual(n, 3)

    def test_script_and_style_still_skipped(self):
        # Scope guard: this change covers <code>/<pre> only; <script>/<style> bodies
        # are still passed through untouched.
        out, n = _process("<script>var a = 'Zorblatt';</script>"
                          "<style>.Zorblatt{color:red}</style>")
        self.assertIn("var a = 'Zorblatt';", out)
        self.assertIn(".Zorblatt{color:red}", out)
        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
