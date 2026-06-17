"""L2 regression: ocr_image must raise when no backend available — not return [].

Currently ocr_image returns [] when both backends are disabled/missing. process_image
then has count==0 → shutil.copy2 copies the ORIGINAL into redacted/ as "0 redactions".
An OCR failure masquerades as a clean image — silent leak.

Fix: ocr_image raises RuntimeError so the per-file try/except in run() catches it, tallies
the error, and does NOT copy the original. Also: _ocr_backend_available() preflight in
run() aborts before writing anything when has_binary but no OCR backend.

    .venv/bin/python -m unittest tests.test_ocr_preflight -v
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import redact


class TestOcrImageNoBackend(unittest.TestCase):
    def _no_ocr_cfg(self):
        cfg = dict(redact.DEFAULT_CONFIG)
        cfg["ocr"] = {"use_apple_vision": False, "fallback_tesseract": False}
        return cfg

    def test_ocr_image_raises_when_no_backend(self):
        """L2: ocr_image must raise RuntimeError, not silently return []."""
        from PIL import Image
        img = Image.new("RGB", (10, 10), "white")
        with self.assertRaises(RuntimeError):
            redact.ocr_image(img, self._no_ocr_cfg())

    def test_process_image_does_not_copy_original_on_ocr_failure(self):
        """L2: when ocr_image raises, process_image must propagate the error (not copy src)."""
        from PIL import Image
        import io
        # Write a tiny valid PNG
        tmpdir = Path(tempfile.mkdtemp())
        src = tmpdir / "photo.png"
        img = Image.new("RGB", (10, 10), color=(255, 0, 0))
        img.save(str(src))
        dst = tmpdir / "redacted" / "photo.png"

        cfg = self._no_ocr_cfg()
        cfg["entities"] = []
        cfg["custom_keywords"] = [{"find": "secret", "replace": "[X]"}]
        analyzer, _ = redact.build_analyzer(cfg)

        with self.assertRaises(RuntimeError):
            redact.process_image(src, dst, analyzer, cfg, dry_run=False)

        # Original must NOT have been copied into redacted/
        self.assertFalse(dst.exists(),
                         "original image must not be copied when OCR fails")

    def test_ocr_backend_available_false_when_both_disabled(self):
        """_ocr_backend_available returns False when both backends off."""
        orig_av = redact.apple_vision_available
        redact.apple_vision_available = lambda: False
        try:
            self.assertFalse(redact._ocr_backend_available(self._no_ocr_cfg()))
        finally:
            redact.apple_vision_available = orig_av

    def test_ocr_backend_available_true_when_apple_vision_on(self):
        """_ocr_backend_available returns True when Apple Vision is available."""
        orig_av = redact.apple_vision_available
        redact.apple_vision_available = lambda: True
        try:
            cfg = dict(redact.DEFAULT_CONFIG)
            cfg["ocr"] = {"use_apple_vision": True, "fallback_tesseract": False}
            self.assertTrue(redact._ocr_backend_available(cfg))
        finally:
            redact.apple_vision_available = orig_av


class TestHasBinaryIncludeSet(unittest.TestCase):
    """Review finding: has_binary ignores include_extensions, so a binary excluded by the
    allowlist still triggers sys.exit(1) when no OCR backend is present.
    """

    def _text_only_cfg(self):
        cfg = dict(redact.DEFAULT_CONFIG)
        cfg["entities"] = []
        cfg["custom_keywords"] = [{"find": "X", "replace": "[X]"}]
        cfg["include_extensions"] = [".md"]   # PDFs/images excluded from processing
        cfg["ocr"] = {"use_apple_vision": False, "fallback_tesseract": False}
        return cfg

    def test_run_does_not_abort_when_binary_excluded_by_include_set(self):
        """Binary present but outside include_extensions must NOT trigger OCR preflight abort."""
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "note.md").write_text("hello world", encoding="utf-8")
        (tmpdir / "photo.pdf").write_bytes(b"%PDF-1.4 fake")

        cfg = self._text_only_cfg()
        orig_av = redact.apple_vision_available
        redact.apple_vision_available = lambda: False
        try:
            # Must complete without SystemExit — the PDF is excluded by include_extensions
            result = redact.run(tmpdir, cfg, dry_run=True)
            self.assertEqual(result, 0, "text-only run with excluded binary must report 0 errors")
        finally:
            redact.apple_vision_available = orig_av


class TestOcrBackendFalsePositive(unittest.TestCase):
    """Review finding: _ocr_backend_available returns True when pytesseract is importable
    but the tesseract CLI binary is absent — false all-clear for broken installations.
    """

    def test_backend_available_false_when_tesseract_binary_absent(self):
        """_ocr_backend_available must return False when shutil.which('tesseract') is None."""
        import sys
        from unittest.mock import MagicMock, patch

        cfg = dict(redact.DEFAULT_CONFIG)
        cfg["ocr"] = {"use_apple_vision": False, "fallback_tesseract": True}

        orig_av = redact.apple_vision_available
        redact.apple_vision_available = lambda: False
        # Inject a fake pytesseract module so the import succeeds
        fake_pytesseract = MagicMock()
        sys.modules.setdefault("pytesseract", None)   # in case already absent
        sys.modules["pytesseract"] = fake_pytesseract
        try:
            # shutil.which returns None → binary absent despite package importable
            with patch("shutil.which", return_value=None):
                result = redact._ocr_backend_available(cfg)
            self.assertFalse(result,
                             "_ocr_backend_available must be False when tesseract binary absent")
        finally:
            redact.apple_vision_available = orig_av
            del sys.modules["pytesseract"]


if __name__ == "__main__":
    unittest.main()
