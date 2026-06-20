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


class ComputeVerdict(unittest.TestCase):
    """FIX: BLOCKER 4 + Finding 1 — verdict precedence.

    Real CRITICAL failures and migration copy-errors must take precedence over
    a dry-run PARTIAL PASS (so an accidental dry-run cannot mask a real FAIL),
    and migration errors>0 must FAIL even when all invariants pass.
    """

    def test_clean_pass(self):
        verdict, code, _ = vm.compute_verdict([], [], dry_run_mode=False, migration_errors=0)
        self.assertEqual((verdict, code), ("PASS", 0))

    def test_critical_failure_fails(self):
        verdict, code, _ = vm.compute_verdict(["I3"], [], dry_run_mode=False, migration_errors=0)
        self.assertEqual((verdict, code), ("FAIL", 2))

    def test_clean_dry_run_is_partial(self):
        # dry-run with I2 skipped, no real failures → PARTIAL PASS
        verdict, code, _ = vm.compute_verdict([], ["I2"], dry_run_mode=True, migration_errors=0)
        self.assertEqual((verdict, code), ("PARTIAL PASS", 1))

    def test_dry_run_does_not_mask_real_failure(self):
        # BLOCKER 4: even with dry_run output present, a real I5 failure → FAIL
        verdict, code, note = vm.compute_verdict(["I5"], ["I2"], dry_run_mode=True, migration_errors=0)
        self.assertEqual((verdict, code), ("FAIL", 2))
        self.assertIn("I5", note)

    def test_migration_errors_fail_even_when_invariants_pass(self):
        # Finding 1: errors>0 in MACHINE_SUMMARY → FAIL despite green invariants
        verdict, code, note = vm.compute_verdict([], [], dry_run_mode=False, migration_errors=2)
        self.assertEqual((verdict, code), ("FAIL", 2))
        self.assertIn("error", note.lower())

    def test_non_dry_run_skipped_is_fail(self):
        verdict, code, _ = vm.compute_verdict([], ["I2"], dry_run_mode=False, migration_errors=0)
        self.assertEqual((verdict, code), ("FAIL", 2))


class BaselineDirHint(unittest.TestCase):
    """FIX: Finding 6 — clearer message when the operator passes baseline/ itself."""

    def test_hint_when_path_ends_in_baseline(self):
        self.assertIn("parent", vm._baseline_dir_hint(Path("/x/reports/baseline")).lower())

    def test_no_hint_for_normal_reports_dir(self):
        self.assertEqual(vm._baseline_dir_hint(Path("/x/reports/20260620")), "")


class Invariants(unittest.TestCase):
    """Direct coverage of the invariant functions (previously only predicates)."""

    def _baseline(self, **files) -> Path:
        d = Path(tempfile.mkdtemp())
        for name, text in files.items():
            (d / name.replace("__", ".")).write_text(text, encoding="utf-8")
        return d

    def test_i1_pass_and_fail(self):
        self.assertEqual(vm.inv_i1(["a", "b"], {"a", "b", "c"})["status"], "PASS")
        self.assertEqual(vm.inv_i1(["a", "b"], {"a"})["status"], "FAIL")

    def test_i3_flags_malformed(self):
        target = Path(tempfile.mkdtemp())
        (target / "good.jsonl").write_text('{"a":1}\n')
        (target / "bad.jsonl").write_text("")
        self.assertEqual(vm.inv_i3({"good"}, target)["status"], "PASS")
        self.assertEqual(vm.inv_i3({"good", "bad"}, target)["status"], "FAIL")

    def test_i4_flags_forbidden(self):
        self.assertEqual(vm.inv_i4({"abc.jsonl"})["status"], "PASS")
        self.assertEqual(vm.inv_i4({"x/subagents/a.jsonl"})["status"], "FAIL")

    def test_i5_absent_both_sides_passes(self):
        # FIX (Finding 9): lock the documented behavior — absent baseline AND
        # absent post both hash to "" → PASS (no false alarm).
        bdir = self._baseline(memory_md__sha256="")
        target = Path(tempfile.mkdtemp())  # no memory/MEMORY.md
        self.assertEqual(vm.inv_i5(bdir, target)["status"], "PASS")

    def test_i5_changed_fails(self):
        target = Path(tempfile.mkdtemp())
        (target / "memory").mkdir()
        (target / "memory" / "MEMORY.md").write_text("new content\n")
        post = vm.sha256_of_file(target / "memory" / "MEMORY.md")
        bdir = self._baseline(memory_md__sha256="0" * 64 + "\n")  # different hash
        self.assertEqual(vm.inv_i5(bdir, target)["status"], "FAIL")
        # and a matching baseline passes
        bdir2 = self._baseline(memory_md__sha256=post + "\n")
        self.assertEqual(vm.inv_i5(bdir2, target)["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
