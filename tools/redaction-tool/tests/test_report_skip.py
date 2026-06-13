"""redact.py must never scan/redact its own report files (redaction-report*.md),
so an emitted report sitting in the input folder isn't re-redacted into redacted/
(which inflated counts once `.md` was an included extension).

Synthetic only.  .venv/bin/python -m unittest tests.test_report_skip -v
Stdlib + PyYAML (redact.py imports yaml at top; spaCy/Presidio are lazy).
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import redact


class TestIsReportFile(unittest.TestCase):
    def test_base_report_name(self):
        self.assertTrue(redact._is_report_file("redaction-report.md"))

    def test_versioned_names(self):
        self.assertTrue(redact._is_report_file("redaction-report-2.md"))
        self.assertTrue(redact._is_report_file("redaction-report-13.md"))

    def test_case_insensitive(self):
        self.assertTrue(redact._is_report_file("Redaction-Report.md"))

    def test_plain_md_not_matched(self):
        self.assertFalse(redact._is_report_file("notes.md"))
        self.assertFalse(redact._is_report_file("README.md"))

    def test_only_at_prefix(self):
        # must START with redaction-report — not match it mid-name
        self.assertFalse(redact._is_report_file("my-redaction-report.md"))


if __name__ == "__main__":
    unittest.main()
