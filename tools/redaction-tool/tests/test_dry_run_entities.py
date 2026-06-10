"""dry-run in NER mode must print detected entity names (not just counts).

run() with dry_run=True and entities set should log the actual text spans that
would be redacted — so the user can seed custom_keywords without writing anything.

    .venv/bin/python -m unittest tests.test_dry_run_entities -v
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import redact


def _ner_cfg():
    cfg = dict(redact.DEFAULT_CONFIG)
    cfg["entities"] = ["PERSON"]
    cfg["custom_keywords"] = []
    return cfg


def _span(start, end, entity_type):
    r = MagicMock()
    r.start = start
    r.end = end
    r.entity_type = entity_type
    return r


class TestDryRunEntityList(unittest.TestCase):
    """run() dry-run NER mode must log detected entity names."""

    def test_dry_run_logs_detected_person_name(self):
        """Detected entity text must appear in run() log output during dry-run."""
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "note.md").write_text("Hello John Smith today", encoding="utf-8")

        cfg = _ner_cfg()
        # Patch analyze to return a known PERSON span covering "John Smith" (6:16)
        r = _span(6, 16, "PERSON")
        with patch("redact.analyze", return_value=[r]):
            with self.assertLogs("redact", level="INFO") as cm:
                redact.run(tmpdir, cfg, dry_run=True)

        all_output = "\n".join(cm.output)
        self.assertIn("John Smith", all_output,
                      "dry-run must log detected entity names; got:\n" + all_output)

    def test_dry_run_entity_list_not_shown_in_live_run(self):
        """Entity list output is dry-run only — live run must not log it."""
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "note.md").write_text("Hello John Smith today", encoding="utf-8")

        cfg = _ner_cfg()
        r = _span(6, 16, "PERSON")
        with patch("redact.analyze", return_value=[r]):
            with self.assertLogs("redact", level="INFO") as cm:
                redact.run(tmpdir, cfg, dry_run=False)

        all_output = "\n".join(cm.output)
        self.assertNotIn("John Smith", all_output,
                         "live run must not log original entity text (would expose PII in logs)")

    def test_dry_run_entity_list_skipped_in_keyword_only_mode(self):
        """Keyword-only mode (entities=[]) uses keyword_redactor, no NER entities to list."""
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "note.md").write_text("Hello secret today", encoding="utf-8")

        cfg = dict(redact.DEFAULT_CONFIG)
        cfg["entities"] = []
        cfg["custom_keywords"] = [{"find": "secret", "replace": "[X]"}]

        with self.assertLogs("redact", level="INFO") as cm:
            redact.run(tmpdir, cfg, dry_run=True)

        all_output = "\n".join(cm.output)
        # keyword-only uses kr path — entity collector must not be active
        self.assertNotIn("Entities detected", all_output)


class TestDryRunKwFilter(unittest.TestCase):
    """KW_i entity types (custom keywords) must not appear in the dry-run entity list.

    Custom keywords are user-configured — they already know about them. The dry-run
    entity list exists to surface NER discoveries the user does NOT know about.
    """

    def test_kw_entity_type_not_shown_in_dry_run_list(self):
        """KW_0 label must not appear in dry-run output — it's an internal label."""
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "note.md").write_text("Hello John Smith today", encoding="utf-8")

        cfg = dict(redact.DEFAULT_CONFIG)
        cfg["entities"] = ["PERSON"]
        cfg["custom_keywords"] = [{"find": "John Smith", "replace": "J.S."}]

        # Return a KW_0 span (custom keyword match)
        r = _span(6, 16, "KW_0")
        with patch("redact.analyze", return_value=[r]):
            with self.assertLogs("redact", level="INFO") as cm:
                redact.run(tmpdir, cfg, dry_run=True)

        all_output = "\n".join(cm.output)
        self.assertNotIn("KW_0", all_output,
                         "internal KW_i labels must not appear in dry-run entity list")
        self.assertNotIn("John Smith", all_output,
                         "custom keyword text must not appear — user already knows it")


class TestFlatEntityList(unittest.TestCase):
    """The dry-run entity list is ONE alphabetical list across all entity types,
    with the type shown inline on the same line (not grouped under TYPE: headers),
    and each entity collapsed to a single line."""

    def _run_with_spans(self, text, spans, cfg=None):
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "note.md").write_text(text, encoding="utf-8")
        cfg = cfg or _ner_cfg()
        with patch("redact.analyze", return_value=spans):
            with self.assertLogs("redact", level="INFO") as cm:
                redact.run(tmpdir, cfg, dry_run=True)
        return "\n".join(cm.output)

    def test_type_shown_inline_not_grouped(self):
        out = self._run_with_spans(
            "John Smith met Acme",
            [_span(0, 10, "PERSON"), _span(15, 19, "ORGANIZATION")])
        person_line = next(l for l in out.splitlines() if "John Smith" in l)
        self.assertIn("(PERSON)", person_line)        # type inline, same line
        acme_line = next(l for l in out.splitlines() if "Acme" in l)
        self.assertIn("(ORGANIZATION)", acme_line)
        # Old grouped "TYPE:" headers are gone.
        self.assertNotIn("PERSON:", out)
        self.assertNotIn("ORGANIZATION:", out)

    def test_single_alphabetical_order_across_types(self):
        # Names chosen to not substring-collide with summary lines (e.g. "Markdown").
        out = self._run_with_spans(
            "Zara Acme Quinn",
            [_span(0, 4, "PERSON"), _span(5, 9, "ORGANIZATION"), _span(10, 15, "PERSON")])
        # Scope to entity rows only — they carry an inline "(TYPE)" marker.
        rows = [l for l in out.splitlines() if "(" in l and ")" in l]
        i_acme = next(i for i, l in enumerate(rows) if "Acme" in l)
        i_quinn = next(i for i, l in enumerate(rows) if "Quinn" in l)
        i_zara = next(i for i, l in enumerate(rows) if "Zara" in l)
        self.assertLess(i_acme, i_quinn)              # one A-Z run, not per-type
        self.assertLess(i_quinn, i_zara)

    def test_newline_in_span_collapsed_to_one_line(self):
        out = self._run_with_spans("Foo\nBar baz", [_span(0, 7, "PERSON")])  # "Foo\nBar"
        line = next(l for l in out.splitlines() if "(PERSON)" in l)
        self.assertIn("Foo Bar", line)                # collapsed onto the type's line
        self.assertNotIn("\nBar\n", "\n" + out + "\n")  # no bare carryover line

    def test_repeat_count_suffix(self):
        out = self._run_with_spans(
            "Sam and Sam", [_span(0, 3, "PERSON"), _span(8, 11, "PERSON")])
        line = next(l for l in out.splitlines() if "Sam" in l and "(PERSON)" in l)
        self.assertIn("×2", line)


if __name__ == "__main__":
    unittest.main()
