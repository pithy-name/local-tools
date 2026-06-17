"""run() must never re-process its OWN prior output. Pre-timestamp this worked because
output was always 'redacted/' (self-excluded); with timestamp_outputs each run's dir is
unique, so prior outputs (redacted/, redacted-ogu, redacted-<ts>/) leaked back in as
input and got re-redacted + nested. Fix: skip any nested dir named `redacted` or
`redacted-*` (relative to input_dir) — but NEVER the selected input_dir itself, so you
can still point the tool AT a redacted dir to re-run with new keywords. Synthetic only.

    .venv/bin/python -m unittest tests.test_output_dir_exclusion -v
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import redact


class TestIsOwnOutputDir(unittest.TestCase):
    def test_exact_base(self):
        self.assertTrue(redact._is_own_output_dir("redacted", "redacted"))

    def test_nontimestamp_suffix(self):           # the redacted-ogu case
        self.assertTrue(redact._is_own_output_dir("redacted-ogu", "redacted"))

    def test_timestamp_suffix(self):
        self.assertTrue(redact._is_own_output_dir("redacted-20260614-193919", "redacted"))

    def test_similar_but_not_output(self):        # must NOT over-match
        self.assertFalse(redact._is_own_output_dir("redactions", "redacted"))
        self.assertFalse(redact._is_own_output_dir("notes", "redacted"))


class TestNestedOutputExcluded(unittest.TestCase):
    def _cfg(self):
        cfg = dict(redact.DEFAULT_CONFIG)
        cfg["entities"] = []
        cfg["custom_keywords"] = [{"find": "Mary Bello", "replace": "[P]"}]
        cfg["include_extensions"] = [".md"]
        cfg["timestamp_outputs"] = True
        return cfg

    def test_prior_output_dirs_not_reprocessed(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "a.md").write_text("Call Mary Bello", encoding="utf-8")
        # prior outputs that must be skipped as input:
        prior = ("redacted", "redacted-ogu", "redacted-20260101-000000")
        for d in prior:
            (tmp / d).mkdir()
            (tmp / d / "old.md").write_text("Call Mary Bello", encoding="utf-8")
        before = {p for p in tmp.glob("redacted*") if p.is_dir()}
        redact.run(tmp, self._cfg(), dry_run=False, report_path=None)
        # the new output dir = the one that didn't exist before (robust vs the fake priors)
        new_dirs = [p for p in tmp.glob("redacted*") if p.is_dir() and p not in before]
        self.assertEqual(len(new_dirs), 1, f"expected one new output dir, got {new_dirs}")
        out = new_dirs[0]
        # the original IS redacted into the new output
        self.assertTrue((out / "a.md").exists())
        # NONE of the prior output dirs were swept in + nested under the new output
        for d in prior:
            self.assertFalse((out / d).exists(), f"prior output {d} was re-processed + nested")

    def test_directly_selected_redacted_dir_is_processed(self):
        # input_dir itself is named like an output dir → user chose it → must process it
        base = Path(tempfile.mkdtemp())
        inp = base / "redacted-ogu"
        inp.mkdir()
        (inp / "b.md").write_text("Call Mary Bello", encoding="utf-8")
        redact.run(inp, self._cfg(), dry_run=False, report_path=None)
        out = next(inp.glob("redacted-20??????-??????"))
        self.assertTrue((out / "b.md").exists())   # processed, not skipped


if __name__ == "__main__":
    unittest.main()
