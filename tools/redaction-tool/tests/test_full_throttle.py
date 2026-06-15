"""--full-throttle orchestrator: dupe-check names_file → propagate into config.yaml →
redact, in one call. Real run writes config.yaml + redacted/; --dry-run propagates
IN-MEMORY (config.yaml untouched) + writes no redacted/ but STILL writes the report;
duplicate names ABORT before any write. All fixtures synthetic; keyword-only (no spaCy).

    .venv/bin/python -m unittest tests.test_full_throttle -v
"""
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import redact

CONFIG_TEMPLATE = """\
entities: []
regex_only: false
replacement: "X"
output_dir: redacted
include_extensions:
  - .md
names_file: "{names}"
custom_keywords:
  # >>> gen_keywords:begin >>>
  - find: "OLD"
    replace: "CO99"
  # <<< gen_keywords:end <<<
"""


def _args(config_path, dry_run, report=None):
    return types.SimpleNamespace(
        dry_run=dry_run, include=None, report=report,
        full_throttle=True, config=config_path)


class TestFullThrottle(unittest.TestCase):
    def _scaffold(self, names_body):
        tmp = Path(tempfile.mkdtemp())
        names = tmp / "names.md"
        names.write_text(names_body, encoding="utf-8")
        config = tmp / "config.yaml"
        config.write_text(CONFIG_TEMPLATE.format(names=names), encoding="utf-8")
        inp = tmp / "input"
        inp.mkdir()
        (inp / "a.md").write_text("Acme Corp and Secret here", encoding="utf-8")
        return tmp, config, inp

    def test_real_run_propagates_and_redacts(self):
        tmp, config, inp = self._scaffold("# CO\nAcme Corp\n# BLACKOUT\nSecret\n")
        cfg = redact.load_config(str(config))
        rc = redact.full_throttle(inp, cfg, _args(str(config), dry_run=False), str(config))
        self.assertEqual(rc, 0)
        # config.yaml propagated: new term in, placeholder out
        cfg_text = config.read_text(encoding="utf-8")
        self.assertIn("Acme Corp", cfg_text)
        self.assertNotIn("OLD", cfg_text)
        self.assertTrue((config.parent / "config.yaml.bak").exists())
        # redacted output written + actually redacted
        out = inp / "redacted" / "a.md"
        self.assertTrue(out.exists())
        red = out.read_text(encoding="utf-8")
        self.assertNotIn("Acme Corp", red)
        self.assertIn("CO01", red)

    def test_dry_run_inmemory_no_config_write_but_report_written(self):
        tmp, config, inp = self._scaffold("# CO\nAcme Corp\n# BLACKOUT\nSecret\n")
        before = config.read_text(encoding="utf-8")
        cfg = redact.load_config(str(config))
        rc = redact.full_throttle(inp, cfg, _args(str(config), dry_run=True, report=""), str(config))
        self.assertEqual(rc, 0)
        # config.yaml UNCHANGED on disk
        self.assertEqual(config.read_text(encoding="utf-8"), before)
        self.assertFalse((config.parent / "config.yaml.bak").exists())
        # no redacted output
        self.assertFalse((inp / "redacted").exists())
        # but the report file IS written (dry-run still reports)
        self.assertTrue((inp / "redaction-report.md").exists())

    def test_duplicate_names_abort_before_any_write(self):
        tmp, config, inp = self._scaffold("# CO\nAcme Corp\nAcme Corp\n")
        before = config.read_text(encoding="utf-8")
        cfg = redact.load_config(str(config))
        with self.assertRaises(SystemExit):
            redact.full_throttle(inp, cfg, _args(str(config), dry_run=False), str(config))
        self.assertEqual(config.read_text(encoding="utf-8"), before)   # untouched
        self.assertFalse((inp / "redacted").exists())                  # no redaction


if __name__ == "__main__":
    unittest.main()
