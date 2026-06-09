"""load_config + normalize_keywords must tolerate empty/null YAML keys.

A config.yaml with `custom_keywords:` and all examples commented out parses as
None (null), not []. The tool must fall back to the default, not crash.

    .venv/bin/python -m unittest tests.test_config -v
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import redact


class TestConfigNullKeys(unittest.TestCase):
    def _cfg_file(self, text):
        p = Path(tempfile.mkdtemp()) / "config.yaml"
        p.write_text(text, encoding="utf-8")
        return str(p)

    def test_null_custom_keywords_falls_back_to_default(self):
        # `custom_keywords:` with nothing under it → YAML null
        cfg = redact.load_config(self._cfg_file("entities:\n  - PERSON\ncustom_keywords:\n"))
        self.assertEqual(cfg["custom_keywords"], [])      # not None
        self.assertEqual(cfg["entities"], ["PERSON"])
        self.assertEqual(redact.normalize_keywords(cfg), [])  # must not raise

    def test_normalize_keywords_tolerates_none(self):
        self.assertEqual(redact.normalize_keywords({"custom_keywords": None}), [])

    def test_explicit_empty_entities_preserved(self):
        # explicit [] (keyword-only) must NOT be clobbered back to the default
        cfg = redact.load_config(self._cfg_file("entities: []\ncustom_keywords:\n  - find: A\n    replace: B\n"))
        self.assertEqual(cfg["entities"], [])


if __name__ == "__main__":
    unittest.main()
