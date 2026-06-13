"""Opt-in report file: redact.run(..., report_path=...) writes a markdown report;
default (report_path=None) writes none. Keyword-only config → no spaCy. Synthetic only.

    .venv/bin/python -m unittest tests.test_report_flag -v
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import redact


class TestReportFlag(unittest.TestCase):
    def _setup(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "a.md").write_text("Call Mary Bello", encoding="utf-8")
        cfg = dict(redact.DEFAULT_CONFIG)
        cfg["entities"] = []
        cfg["custom_keywords"] = [{"find": "Mary Bello", "replace": "[P]"}]
        cfg["include_extensions"] = [".md"]
        return tmp, cfg

    def test_no_report_when_flag_absent(self):
        tmp, cfg = self._setup()
        redact.run(tmp, cfg, dry_run=False)                       # no report_path
        self.assertFalse((tmp / "redaction-report.md").exists())

    def test_empty_path_writes_default_location(self):
        tmp, cfg = self._setup()
        redact.run(tmp, cfg, dry_run=False, report_path="")       # "" → default beside input
        rpt = tmp / "redaction-report.md"
        self.assertTrue(rpt.exists())
        md = rpt.read_text(encoding="utf-8")
        self.assertIn("## Summary", md)
        self.assertIn("GRAND TOTAL", md)
        self.assertIn("SENSITIVE", md)

    def test_explicit_path(self):
        tmp, cfg = self._setup()
        dest = tmp / "myreport.md"
        redact.run(tmp, cfg, dry_run=False, report_path=str(dest))
        self.assertTrue(dest.exists())

    def test_report_not_redacted_on_subsequent_run(self):
        # end-to-end: a report written into the folder must not be scanned/redacted
        # into redacted/ on the next run (the _is_report_file skip).
        tmp, cfg = self._setup()
        redact.run(tmp, cfg, dry_run=False, report_path="")       # writes tmp/redaction-report.md
        redact.run(tmp, cfg, dry_run=False, report_path="")       # 2nd run: .md included
        self.assertFalse((tmp / "redacted" / "redaction-report.md").exists())


if __name__ == "__main__":
    unittest.main()
