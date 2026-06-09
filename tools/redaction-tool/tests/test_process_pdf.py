"""L1 regression: digital-PDF count must only increment when search_for places a redaction.

Currently process_pdf does `total += len(results)` BEFORE calling search_for. If
search_for returns [] (line-wrapped phrase, ligature, whitespace mismatch), the PDF is
unchanged but the report claims a redaction happened — a silent leak with false assurance.

    .venv/bin/python -m unittest tests.test_process_pdf -v
"""
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import redact


def _kw_cfg(find_word):
    cfg = dict(redact.DEFAULT_CONFIG)
    cfg["entities"] = []
    cfg["custom_keywords"] = [{"find": find_word, "replace": "[REDACTED]"}]
    return cfg


def _pdf_with_text(text: str) -> Path:
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 100), text)
    p = Path(tempfile.mkdtemp()) / "test.pdf"
    doc.save(str(p))
    doc.close()
    return p


class TestProcessPdfCountL1(unittest.TestCase):
    def test_count_zero_when_search_for_finds_no_quads(self):
        """L1: search_for returns [] → total must be 0 (phrase unplaceable in layout)."""
        import fitz
        src = _pdf_with_text("Marcus Webb is here")
        dst = src.parent / "redacted" / "test.pdf"
        cfg = _kw_cfg("Marcus Webb")
        analyzer, _ = redact.build_analyzer(cfg)

        with unittest.mock.patch.object(fitz.Page, "search_for", return_value=[]):
            total, blackout = redact.process_pdf(src, dst, analyzer, cfg, dry_run=True)

        self.assertEqual(total, 0,
                         "count must NOT increment when search_for finds no quads")
        self.assertEqual(dict(blackout), {},
                         "blackout must NOT increment when search_for finds no quads")

    def test_count_one_when_search_for_places_redaction(self):
        """Counterpart: a real match increments the count exactly once."""
        src = _pdf_with_text("Marcus Webb is here")
        dst = src.parent / "redacted" / "test.pdf"
        cfg = _kw_cfg("Marcus Webb")
        analyzer, _ = redact.build_analyzer(cfg)

        total, blackout = redact.process_pdf(src, dst, analyzer, cfg, dry_run=True)

        self.assertGreaterEqual(total, 1, "placed redaction must increment total")

    def test_no_detect_returns_zero(self):
        """keyword-only + no keywords → early return, count 0."""
        src = _pdf_with_text("Marcus Webb is here")
        dst = src.parent / "redacted" / "test.pdf"
        cfg = _kw_cfg("Marcus Webb")
        cfg["custom_keywords"] = []   # no keywords → nothing to detect
        analyzer, _ = redact.build_analyzer(cfg)

        total, blackout = redact.process_pdf(src, dst, analyzer, cfg, dry_run=True)

        self.assertEqual(total, 0)
        self.assertEqual(dict(blackout), {})


if __name__ == "__main__":
    unittest.main()
