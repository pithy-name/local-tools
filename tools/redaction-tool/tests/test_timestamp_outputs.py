"""timestamp_outputs (boolean toggle): when on, run() suffixes a per-run timestamp
onto the redacted dir + the default report file. Pure seam: add_timestamp(name, ts).
Also pins the two new config defaults. Synthetic only; keyword-only (no spaCy).

    .venv/bin/python -m unittest tests.test_timestamp_outputs -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import redact


class TestAddTimestamp(unittest.TestCase):
    TS = "20260614-134507"

    def test_no_suffix_dir_name(self):
        self.assertEqual(redact.add_timestamp("redacted", self.TS), "redacted-20260614-134507")

    def test_md_report_inserts_before_extension(self):
        self.assertEqual(
            redact.add_timestamp("redaction-report.md", self.TS),
            "redaction-report-20260614-134507.md")

    def test_custom_output_dir_name(self):
        self.assertEqual(redact.add_timestamp("myout", self.TS), "myout-20260614-134507")


class TestNewConfigDefaults(unittest.TestCase):
    def test_timestamp_outputs_default_off(self):
        self.assertIn("timestamp_outputs", redact.DEFAULT_CONFIG)
        self.assertIs(redact.DEFAULT_CONFIG["timestamp_outputs"], False)

    def test_names_file_default(self):
        self.assertEqual(redact.DEFAULT_CONFIG.get("names_file"), "names.md")


class TestTimestampRunIntegration(unittest.TestCase):
    """End-to-end: timestamp_outputs=True → a redacted-<ts>/ dir and a
    redaction-report-<ts>.md (ts is now(), so match by glob)."""

    def _setup(self, tmp):
        (tmp / "a.md").write_text("Call Mary Bello", encoding="utf-8")
        cfg = dict(redact.DEFAULT_CONFIG)
        cfg["entities"] = []
        cfg["custom_keywords"] = [{"find": "Mary Bello", "replace": "[P]"}]
        cfg["include_extensions"] = [".md"]
        cfg["timestamp_outputs"] = True
        return cfg

    def test_timestamped_dir_and_report(self):
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        cfg = self._setup(tmp)
        redact.run(tmp, cfg, dry_run=False, report_path="")
        dirs = list(tmp.glob("redacted-20*-*"))
        reports = list(tmp.glob("redaction-report-20*-*.md"))
        self.assertEqual(len(dirs), 1, f"expected one timestamped dir, got {dirs}")
        self.assertEqual(len(reports), 1, f"expected one timestamped report, got {reports}")
        # plain (un-timestamped) names must NOT exist when the toggle is on
        self.assertFalse((tmp / "redacted").exists())
        self.assertFalse((tmp / "redaction-report.md").exists())


if __name__ == "__main__":
    unittest.main()
