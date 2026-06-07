"""Tests for the scan extraction plumbing (no analyzer needed for text formats).

    .venv/bin/python -m unittest tests.test_scan -v
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import redact


class TestIterJsonStrings(unittest.TestCase):
    def test_yields_string_values_only(self):
        obj = {"a": "x", "n": 5, "l": ["y", {"d": "z"}], "none": None}
        self.assertEqual(sorted(redact._iter_json_strings(obj)), ["x", "y", "z"])


class TestTextsForScan(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def _f(self, name, content):
        p = self.tmp / name
        p.write_text(content, encoding="utf-8")
        return p

    def test_md(self):
        p = self._f("a.md", "hello world")
        self.assertEqual(list(redact._texts_for_scan(p, ".md", {})), ["hello world"])

    def test_json_yields_values(self):
        p = self._f("a.json", json.dumps({"x": "alice", "n": 1, "y": "bob"}))
        self.assertEqual(sorted(redact._texts_for_scan(p, ".json", {})), ["alice", "bob"])

    def test_csv_yields_cells(self):
        p = self._f("a.csv", "name,note\nalice,hi\n")
        self.assertEqual(list(redact._texts_for_scan(p, ".csv", {})),
                         ["name", "note", "alice", "hi"])

    def test_html_yields_visible_text(self):
        p = self._f("a.html", "<p>hello</p><b>world</b>")
        out = " ".join(redact._texts_for_scan(p, ".html", {}))
        self.assertIn("hello", out)
        self.assertIn("world", out)


if __name__ == "__main__":
    unittest.main()
