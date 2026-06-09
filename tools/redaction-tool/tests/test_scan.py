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


class TestTextsForScanPdf(unittest.TestCase):
    """`--scan` must OCR scanned (image-only) PDF pages, not just digital text."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def _pdf(self, name, page_texts):
        # each entry: page text; "" = an empty page standing in for a scanned page
        import fitz
        doc = fitz.open()
        for t in page_texts:
            page = doc.new_page()
            if t:
                page.insert_text((72, 72), t)
        p = self.tmp / name
        doc.save(str(p))
        doc.close()
        return p

    def test_scanned_page_is_ocred(self):
        p = self._pdf("scan.pdf", [""])            # one image-only (scanned) page
        orig = redact.ocr_image
        redact.ocr_image = lambda img, cfg: [{"text": "Marcus Webb", "bbox_pixels": (0, 0, 1, 1)}]
        try:
            out = list(redact._texts_for_scan(p, ".pdf", {}))
        finally:
            redact.ocr_image = orig
        self.assertEqual(out, ["Marcus Webb"])

    def test_digital_page_uses_text_not_ocr(self):
        p = self._pdf("digital.pdf", ["Hello Alice"])
        called = []
        orig = redact.ocr_image
        redact.ocr_image = lambda img, cfg: called.append(1) or []
        try:
            out = list(redact._texts_for_scan(p, ".pdf", {}))
        finally:
            redact.ocr_image = orig
        self.assertIn("Hello Alice", " ".join(out))
        self.assertEqual(called, [])               # digital page must not invoke OCR


if __name__ == "__main__":
    unittest.main()
