"""Integration tests: redact.py keyword-only mode routed through keyword_redactor.

Run under the venv (importing redact.py needs yaml/presidio), though the
keyword path itself loads no spaCy:

    .venv/bin/python -m unittest tests.test_keyword_integration -v
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import redact


class TestKeywordRedactorFromConfig(unittest.TestCase):
    def test_reproduces_pinned_keyword_only_output(self):
        cfg = dict(redact.DEFAULT_CONFIG)
        cfg["entities"] = []
        cfg["custom_keywords"] = [{"find": "Mary Bello", "replace": "[PERSON_A]"}]
        r = redact.make_keyword_redactor_from_config(cfg)
        self.assertEqual(r.redact("Met Mary Bello today."), "Met [PERSON_A] today.")
        self.assertEqual(r.redact("Met Bob Reyes today."), "Met Bob Reyes today.")

    def test_plain_string_keyword_uses_default_replacement(self):
        cfg = dict(redact.DEFAULT_CONFIG)
        cfg["entities"] = []
        cfg["custom_keywords"] = ["Acme Corp"]  # no replace -> default
        cfg["replacement"] = "█████"
        r = redact.make_keyword_redactor_from_config(cfg)
        self.assertEqual(r.redact("At Acme Corp now"), "At █████ now")


class TestKeywordOnlyRun(unittest.TestCase):
    def test_text_only_run_skips_model_and_redacts(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "note.md").write_text("Met Mary Bello today.", encoding="utf-8")
        cfg = dict(redact.DEFAULT_CONFIG)
        cfg["entities"] = []
        cfg["custom_keywords"] = [{"find": "Mary Bello", "replace": "[PERSON_A]"}]
        # If run() loads the spaCy model in a text-only keyword run, this raises.
        with mock.patch.object(redact, "build_analyzer",
                               side_effect=AssertionError("model loaded in text-only keyword run")):
            redact.run(tmp, cfg, dry_run=False)
        out = (tmp / "redacted" / "note.md").read_text(encoding="utf-8")
        self.assertEqual(out, "Met [PERSON_A] today.")

    def test_keyword_run_with_image_present_loads_model(self):
        # config-enabled image present → model loads (it's needed for the image)
        tmp = Path(tempfile.mkdtemp())
        (tmp / "note.md").write_text("hi", encoding="utf-8")
        (tmp / "pic.png").write_bytes(b"\x89PNG not-a-real-image")
        cfg = dict(redact.DEFAULT_CONFIG)
        cfg["entities"] = []
        cfg["custom_keywords"] = [{"find": "x", "replace": "[X]"}]
        with mock.patch.object(redact, "build_analyzer", return_value=(None, {})) as ba, \
                mock.patch.object(redact, "process_image", return_value=(0, {})):
            redact.run(tmp, cfg, dry_run=True)
        ba.assert_called_once()

    def test_ner_mode_loads_model(self):
        # NER on → model loads regardless of file types
        tmp = Path(tempfile.mkdtemp())
        (tmp / "note.md").write_text("hi", encoding="utf-8")
        cfg = dict(redact.DEFAULT_CONFIG)
        cfg["entities"] = ["PERSON"]
        with mock.patch.object(redact, "build_analyzer", return_value=(None, {})) as ba, \
                mock.patch.object(redact, "process_markdown", return_value=0):
            redact.run(tmp, cfg, dry_run=True)
        ba.assert_called_once()


if __name__ == "__main__":
    unittest.main()
