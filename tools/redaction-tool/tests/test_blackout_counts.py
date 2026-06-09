"""redact_image_pixels attributes each blacked-out match to the right keyword,
so the report's `blackout` column can show real per-keyword counts.

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
        # `count` also includes NER hits from the loaded model (the image path runs the
        # full analyzer); the per-keyword `blackout` attributes ONLY the keyword (KW_*)
        # matches — that's what the report column needs.
        self.assertEqual(dict(blackout), {"Marcus Webb": 1, "Acme Corp": 1})
        self.assertGreaterEqual(count, 2)

    def test_run_report_shows_real_blackout_counts(self):
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
        self.assertIn("(Marcus Webb)  text-sub: 0  blackout: 1", report)
        self.assertNotIn("blackout: N/A", report)   # image engaged → real counts, not N/A


if __name__ == "__main__":
    unittest.main()
