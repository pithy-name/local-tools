"""Word-level image redaction (`tight_image_boxes`): black only the matched word's
box (via Apple Vision's per-range box, supplied as `word_box_fn` on each OCR
observation), falling back to the whole OCR line when the range box is missing.
Default OFF = the conservative whole-line blackout. Synthetic observations + a
mocked analyzer — pure, no real Vision/OCR/Presidio needed.

    .venv/bin/python -m unittest tests.test_tight_image_boxes -v
"""
import sys
import unittest
from collections import namedtuple
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import redact

_Match = namedtuple("_Match", ["entity_type", "start", "end"])


def _is_black(img, x, y):
    return img.getpixel((x, y)) == (0, 0, 0)


class TightImageBoxes(unittest.TestCase):
    """A 100x20 white image with one OCR 'line' box (x=0..100) for the text
    'secret word here'; the word 'secret' occupies x=0..30 (its word_box_fn)."""

    def _run(self, *, tight, word_box=(0, 0, 30, 10)):
        from PIL import Image
        img = Image.new("RGB", (100, 20), "white")
        obs = {
            "text": "secret word here",
            "confidence": 0.99,
            "bbox_pixels": (0, 0, 100, 10),                 # whole LINE
            "word_box_fn": (lambda s, e: word_box),         # box for the matched word
        }
        cfg = dict(redact.DEFAULT_CONFIG)
        cfg["entities"] = []
        cfg["custom_keywords"] = [{"find": "secret", "replace": "[X]"}]
        cfg["tight_image_boxes"] = tight
        orig_ocr, orig_analyze = redact.ocr_image, redact.analyze
        redact.ocr_image = lambda im, c: [obs]
        redact.analyze = lambda text, an, c, ef: [_Match("KW_0", 0, 6)]   # 'secret'
        try:
            out, count, _ = redact.redact_image_pixels(img, None, cfg)
        finally:
            redact.ocr_image, redact.analyze = orig_ocr, orig_analyze
        return out, count

    def test_tight_blacks_only_the_word(self):
        out, count = self._run(tight=True)
        self.assertEqual(count, 1)
        self.assertTrue(_is_black(out, 15, 5), "matched word (x=15) must be blacked")
        self.assertFalse(_is_black(out, 60, 5),
                         "rest of the line (x=60) must stay visible in tight mode")

    def test_default_is_whole_line(self):
        out, count = self._run(tight=False)   # the default
        self.assertEqual(count, 1)
        self.assertTrue(_is_black(out, 15, 5))
        self.assertTrue(_is_black(out, 60, 5),
                        "whole line blacked (conservative default unchanged)")

    def test_tight_falls_back_to_line_when_no_word_box(self):
        """word_box_fn returns None (collapse / API None) -> whole line, never under-redact."""
        from PIL import Image
        img = Image.new("RGB", (100, 20), "white")
        obs = {"text": "secret word here", "confidence": 0.99,
               "bbox_pixels": (0, 0, 100, 10),
               "word_box_fn": (lambda s, e: None)}
        cfg = dict(redact.DEFAULT_CONFIG)
        cfg["entities"] = []
        cfg["custom_keywords"] = [{"find": "secret", "replace": "[X]"}]
        cfg["tight_image_boxes"] = True
        orig_ocr, orig_analyze = redact.ocr_image, redact.analyze
        redact.ocr_image = lambda im, c: [obs]
        redact.analyze = lambda text, an, c, ef: [_Match("KW_0", 0, 6)]
        try:
            out, count, _ = redact.redact_image_pixels(img, None, cfg)
        finally:
            redact.ocr_image, redact.analyze = orig_ocr, orig_analyze
        self.assertEqual(count, 1)
        self.assertTrue(_is_black(out, 60, 5),
                        "no usable word box -> fall back to whole line")

    def test_default_config_has_toggle_off(self):
        self.assertFalse(redact.DEFAULT_CONFIG.get("tight_image_boxes", False),
                         "tight_image_boxes must default to False (conservative)")


if __name__ == "__main__":
    unittest.main()
