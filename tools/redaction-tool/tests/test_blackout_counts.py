"""redact_image_pixels attributes each blacked-out match to the right keyword
(the `blackout` Counter return) AND, via the threaded collector, itemizes image/PDF
matches in the unified end-of-run report.

    .venv/bin/python -m unittest tests.test_blackout_counts -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import redact


class TestBlackoutCounts(unittest.TestCase):
    def _analyzer(self, keywords):
        cfg = dict(redact.DEFAULT_CONFIG)
        cfg["entities"] = []
        cfg["custom_keywords"] = keywords
        analyzer, _ = redact.build_analyzer(cfg)
        return analyzer, cfg

    def test_redact_image_pixels_returns_per_keyword_counts(self):
        from PIL import Image
        analyzer, cfg = self._analyzer([
            {"find": "Marcus Webb", "replace": "[P]"},
            {"find": "Acme Corp", "replace": "[C]"},
        ])
        img = Image.new("RGB", (60, 20), "white")
        orig = redact.ocr_image
        redact.ocr_image = lambda im, c: [
            {"text": "call Marcus Webb at Acme Corp now", "bbox_pixels": (0, 0, 59, 19)},
        ]
        try:
            _img, count, blackout = redact.redact_image_pixels(img, analyzer, cfg)
        finally:
            redact.ocr_image = orig
        # keyword-only mode: the image path is restricted to keyword (KW_*) matches — no
        # NER — so count == the keyword matches and blackout attributes each one.
        self.assertEqual(count, 2)
        self.assertEqual(dict(blackout), {"Marcus Webb": 1, "Acme Corp": 1})

    def test_keyword_only_image_path_skips_ner(self):
        from PIL import Image
        analyzer, cfg = self._analyzer([{"find": "Acme Corp", "replace": "[C]"}])  # keyword-only
        img = Image.new("RGB", (60, 20), "white")
        orig = redact.ocr_image
        redact.ocr_image = lambda im, c: [
            {"text": "Marcus Webb at Acme Corp", "bbox_pixels": (0, 0, 59, 19)},
        ]
        try:
            _img, count, blackout = redact.redact_image_pixels(img, analyzer, cfg)
        finally:
            redact.ocr_image = orig
        # "Marcus Webb" is an NER-only name (not a keyword) → must NOT be redacted here.
        self.assertEqual(count, 1)
        self.assertEqual(dict(blackout), {"Acme Corp": 1})

    def test_keyword_only_no_keywords_does_not_run_ner(self):
        from PIL import Image
        analyzer, cfg = self._analyzer([])  # keyword-only, NO keywords
        img = Image.new("RGB", (60, 20), "white")
        orig = redact.ocr_image
        redact.ocr_image = lambda im, c: [{"text": "Marcus Webb here", "bbox_pixels": (0, 0, 59, 19)}]
        try:
            _img, count, blackout = redact.redact_image_pixels(img, analyzer, cfg)
        finally:
            redact.ocr_image = orig
        self.assertEqual(count, 0)          # no keywords → nothing detected (no NER leak)
        self.assertEqual(dict(blackout), {})

    def test_ner_mode_also_applies_custom_keywords_on_images(self):
        from PIL import Image
        cfg = dict(redact.DEFAULT_CONFIG)
        cfg["entities"] = ["PERSON"]
        cfg["custom_keywords"] = [{"find": "Acme Corp", "replace": "[C]"}]
        analyzer, _ = redact.build_analyzer(cfg)
        img = Image.new("RGB", (90, 20), "white")
        orig = redact.ocr_image
        redact.ocr_image = lambda im, c: [
            {"text": "Marcus Webb at Acme Corp", "bbox_pixels": (0, 0, 89, 19)},
        ]
        try:
            _img, count, blackout = redact.redact_image_pixels(img, analyzer, cfg)
        finally:
            redact.ocr_image = orig
        # NER mode must ALSO apply custom keywords to images: "Acme Corp" is blacked out.
        self.assertEqual(dict(blackout), {"Acme Corp": 1})
        self.assertGreaterEqual(count, 2)   # PERSON (Marcus Webb) + keyword (Acme Corp)

    def test_run_report_itemizes_image_keyword_match(self):
        """An image keyword match is itemized in the unified report (via the threaded
        collector) — same report every mode."""
        import tempfile
        from PIL import Image
        tmp = Path(tempfile.mkdtemp())
        Image.new("RGB", (60, 20), "white").save(tmp / "pic.png")
        cfg = dict(redact.DEFAULT_CONFIG)
        cfg["entities"] = []
        cfg["custom_keywords"] = [{"find": "Marcus Webb", "replace": "[P]"}]
        orig = redact.ocr_image
        redact.ocr_image = lambda im, c: [{"text": "Marcus Webb here", "bbox_pixels": (0, 0, 59, 19)}]
        try:
            with self.assertLogs(redact.log, level="INFO") as cm:
                redact.run(tmp, cfg, dry_run=True)
        finally:
            redact.ocr_image = orig
        report = "\n".join(cm.output)
        self.assertIn("CUSTOM KEYWORDS — replaced", report)
        self.assertIn("Marcus Webb", report)        # itemized from the image
        self.assertIn("[P]", report)                # its pseudonym
        self.assertIn("GRAND TOTAL: 1", report)


if __name__ == "__main__":
    unittest.main()
