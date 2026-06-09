"""include_extensions acts as an allowlist: only listed (and handled) types get processed.
A `--include` CLI flag overrides the configured list per run.

    .venv/bin/python -m unittest tests.test_include_extensions -v
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import redact


class TestIncludeExtensions(unittest.TestCase):
    def _dir(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "a.md").write_text("Mary Bello", encoding="utf-8")
        (tmp / "b.json").write_text(json.dumps({"x": "Mary Bello"}), encoding="utf-8")
        return tmp

    def _cfg(self, include):
        cfg = dict(redact.DEFAULT_CONFIG)
        cfg["entities"] = []
        cfg["custom_keywords"] = [{"find": "Mary Bello", "replace": "[P]"}]
        cfg["include_extensions"] = include
        return cfg

    def test_restricts_to_listed_types(self):
        tmp = self._dir()
        redact.run(tmp, self._cfg([".md"]), dry_run=False)   # only .md allowed
        self.assertIn("[P]", (tmp / "redacted" / "a.md").read_text(encoding="utf-8"))
        # .json is NOT in the allowlist → unhandled → not copied (copy_unhandled false)
        self.assertFalse((tmp / "redacted" / "b.json").exists())

    def test_listed_types_are_processed(self):
        tmp = self._dir()
        redact.run(tmp, self._cfg([".md", ".json"]), dry_run=False)
        self.assertTrue((tmp / "redacted" / "a.md").exists())
        out = json.loads((tmp / "redacted" / "b.json").read_text(encoding="utf-8"))
        self.assertEqual(out, {"x": "[P]"})

    def test_normalize_extensions(self):
        self.assertEqual(redact._normalize_extensions(["MD", ".Json", "csv"]),
                         [".md", ".json", ".csv"])


if __name__ == "__main__":
    unittest.main()
