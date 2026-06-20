"""Unit tests for the generic verify suite + the migrate script's MACHINE_SUMMARY line.

Stdlib unittest only. The MachineSummary class (Task 1) subprocess-runs the migrate
script and needs no import of verify_migration. The Predicates class (Task 3) imports
verify_migration once it's rewritten.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import verify_migration as vm

TOOL = Path(__file__).resolve().parent / "migrate_cowork_sessions.py"


class MachineSummary(unittest.TestCase):
    def test_list_mode_emits_no_machine_summary(self):
        # --list returns before any migration → must never print MACHINE_SUMMARY.
        out = subprocess.run(
            [sys.executable, str(TOOL), "--list"],
            capture_output=True, text=True,
        ).stdout
        self.assertNotIn("MACHINE_SUMMARY", out)


class Predicates(unittest.TestCase):
    def test_parse_ok(self):
        out = 'noise\nMACHINE_SUMMARY {"transcripts_copied": 3, "dry_run": false}\nmore'
        self.assertEqual(vm.parse_machine_summary(out)["transcripts_copied"], 3)

    def test_parse_absent(self):
        self.assertIsNone(vm.parse_machine_summary("no summary here"))

    def test_parse_malformed_only(self):
        self.assertIsNone(vm.parse_machine_summary("MACHINE_SUMMARY {not json"))

    def test_parse_last_wins_over_dryrun(self):
        out = ('MACHINE_SUMMARY {"transcripts_copied": 1, "dry_run": true}\n'
               'MACHINE_SUMMARY {"transcripts_copied": 5, "dry_run": false}')
        s = vm.parse_machine_summary(out)
        self.assertEqual(s["transcripts_copied"], 5)
        self.assertFalse(s["dry_run"])

    def test_parse_skips_malformed_keeps_valid(self):
        out = 'MACHINE_SUMMARY {bad\nMACHINE_SUMMARY {"transcripts_copied": 2, "dry_run": false}'
        self.assertEqual(vm.parse_machine_summary(out)["transcripts_copied"], 2)

    def test_forbidden_paths(self):
        for p in ["x/subagents/a.jsonl", "subagents/b.jsonl", "agent-12.jsonl",
                  "audit.jsonl", "y/.credentials.json"]:
            self.assertTrue(vm.is_forbidden_added_path(p), p)

    def test_allowed_paths(self):
        for p in ["abc.jsonl", "uuid/tool-results/t.json", "memory/x.md"]:
            self.assertFalse(vm.is_forbidden_added_path(p), p)

    def test_wellformed_jsonl(self):
        d = Path(tempfile.mkdtemp())
        (d / "good.jsonl").write_text('{"a": 1}\n{"b": 2}\n')
        (d / "empty.jsonl").write_text("")
        (d / "bad.jsonl").write_text("not json\n")
        self.assertTrue(vm.is_wellformed_jsonl(d / "good.jsonl"))
        self.assertFalse(vm.is_wellformed_jsonl(d / "empty.jsonl"))
        self.assertFalse(vm.is_wellformed_jsonl(d / "bad.jsonl"))
        self.assertFalse(vm.is_wellformed_jsonl(d / "missing.jsonl"))


if __name__ == "__main__":
    unittest.main()
