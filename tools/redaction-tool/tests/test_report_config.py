"""Config-driven report toggle: `resolve_report_path(cli_report, cfg_report)` decides
the effective report path from the CLI --report value and the config `report` key.
The CLI flag, when given, always wins (runtime intent > config). Pure fn, no PII.

    .venv/bin/python -m unittest tests.test_report_config -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import redact


class TestResolveReportPath(unittest.TestCase):
    # ── config only (no CLI flag → cli_report is None) ──
    def test_off_when_both_absent(self):
        self.assertIsNone(redact.resolve_report_path(None, None))

    def test_config_false_is_off(self):
        self.assertIsNone(redact.resolve_report_path(None, False))

    def test_config_true_writes_default_location(self):
        self.assertEqual(redact.resolve_report_path(None, True), "")

    def test_config_path_string(self):
        self.assertEqual(redact.resolve_report_path(None, "/tmp/r.md"), "/tmp/r.md")

    def test_config_empty_string_is_off(self):
        self.assertIsNone(redact.resolve_report_path(None, ""))

    def test_config_whitespace_string_is_off(self):
        self.assertIsNone(redact.resolve_report_path(None, "   "))

    # ── CLI flag present → always wins over config ──
    def test_cli_bare_overrides_config_off(self):
        # bare --report ("") with config off → still write (default location)
        self.assertEqual(redact.resolve_report_path("", False), "")

    def test_cli_bare_overrides_config_path(self):
        # bare --report means "default location" even if config named a path
        self.assertEqual(redact.resolve_report_path("", "/tmp/from_cfg.md"), "")

    def test_cli_path_overrides_config_true(self):
        self.assertEqual(redact.resolve_report_path("/tmp/cli.md", True), "/tmp/cli.md")

    def test_cli_path_overrides_config_off(self):
        self.assertEqual(redact.resolve_report_path("/tmp/cli.md", False), "/tmp/cli.md")


class TestDefaultConfigHasReportKey(unittest.TestCase):
    def test_default_report_is_off(self):
        self.assertIn("report", redact.DEFAULT_CONFIG)
        self.assertIs(redact.DEFAULT_CONFIG["report"], False)


if __name__ == "__main__":
    unittest.main()
