"""S1 regression: run() must return error count; main() must exit nonzero on errors.

Currently run() returns None regardless of how many files errored. A wrapping script
or CI treats a partially-failed run as success.

    .venv/bin/python -m unittest tests.test_exit_code -v
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import redact


def _kw_cfg():
    cfg = dict(redact.DEFAULT_CONFIG)
    cfg["entities"] = []
    cfg["custom_keywords"] = [{"find": "X", "replace": "[X]"}]
    return cfg


class TestRunReturnsErrorCount(unittest.TestCase):
    def test_run_returns_zero_on_clean_run(self):
        """S1: run() returns 0 when all files process cleanly."""
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "note.md").write_text("hello world", encoding="utf-8")
        result = redact.run(tmpdir, _kw_cfg(), dry_run=True)
        self.assertEqual(result, 0)

    def test_run_returns_error_count_on_bad_json(self):
        """S1: run() returns 1 when a JSON file is malformed."""
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "bad.json").write_text("{{not valid json!!", encoding="utf-8")
        result = redact.run(tmpdir, _kw_cfg(), dry_run=True)
        self.assertEqual(result, 1)

    def test_run_returns_count_across_multiple_errors(self):
        """S1: error count reflects ALL failing files."""
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "a.json").write_text("{{bad", encoding="utf-8")
        (tmpdir / "b.json").write_text("{{bad", encoding="utf-8")
        result = redact.run(tmpdir, _kw_cfg(), dry_run=True)
        self.assertEqual(result, 2)


if __name__ == "__main__":
    unittest.main()
