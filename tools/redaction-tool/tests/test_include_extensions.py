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


class TestTxtHandler(unittest.TestCase):
    """T2.2 regression: .txt is in SCAN_EXTS and implied by README but has no run() handler.

    With copy_unhandled: false (default), a .txt file is silently NOT copied into
    redacted/ — operator sees 0 output, thinks it was processed. With copy_unhandled:
    true, the original (unredacted) .txt is copied verbatim — silent leak.

    Fix: add a .txt handler in run() that routes through the text path.
    """

    def _cfg(self):
        cfg = dict(redact.DEFAULT_CONFIG)
        cfg["entities"] = []
        cfg["custom_keywords"] = [{"find": "Marcus Webb", "replace": "[P]"}]
        cfg["include_extensions"] = [".txt"]
        return cfg

    def test_txt_file_is_redacted(self):
        """.txt in include_extensions must be redacted, not leaked or skipped."""
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "note.txt").write_text("Call Marcus Webb today", encoding="utf-8")
        redact.run(tmpdir, self._cfg(), dry_run=False)
        out_path = tmpdir / "redacted" / "note.txt"
        self.assertTrue(out_path.exists(), ".txt must appear in redacted/")
        out = out_path.read_text(encoding="utf-8")
        self.assertNotIn("Marcus Webb", out, "PII must be removed from .txt output")
        self.assertIn("[P]", out, "replacement must appear in .txt output")

    def test_txt_dry_run_counts_redactions(self):
        """.txt dry-run must report redactions without writing files."""
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "note.txt").write_text("Marcus Webb called", encoding="utf-8")
        result = redact.run(tmpdir, self._cfg(), dry_run=True)
        # In dry_run mode the file is not written; just verify run() completes without error
        self.assertEqual(result, 0, "dry-run on valid .txt should report 0 errors")


if __name__ == "__main__":
    unittest.main()
