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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # tool dir: tool modules
sys.path.insert(0, str(Path(__file__).resolve().parent))         # tests dir: fixtures

import verify_migration as vm
from fixtures import build_synthetic_workspace, SPACE_UUID

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

    def _baseline(self, files: dict) -> Path:
        # files maps REAL baseline filenames (e.g. "memory_md.sha256") to content —
        # no kwarg-name munging, so a future filename with odd chars can't be mangled.
        d = Path(tempfile.mkdtemp())
        for name, text in files.items():
            (d / name).write_text(text, encoding="utf-8")
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
        bdir = self._baseline({"memory_md.sha256": ""})
        target = Path(tempfile.mkdtemp())  # no memory/MEMORY.md
        self.assertEqual(vm.inv_i5(bdir, target)["status"], "PASS")

    def test_i5_created_fails(self):
        # Guards the absent==absent case from passing vacuously: baseline had no
        # MEMORY.md but one EXISTS post-migration → I5 must FAIL (proves the check
        # actually compares, rather than always-passing on an empty baseline).
        bdir = self._baseline({"memory_md.sha256": ""})  # absent at baseline
        target = Path(tempfile.mkdtemp())
        (target / "memory").mkdir()
        (target / "memory" / "MEMORY.md").write_text("created post-baseline\n")
        self.assertEqual(vm.inv_i5(bdir, target)["status"], "FAIL")

    def test_i5_changed_fails(self):
        target = Path(tempfile.mkdtemp())
        (target / "memory").mkdir()
        (target / "memory" / "MEMORY.md").write_text("new content\n")
        post = vm.sha256_of_file(target / "memory" / "MEMORY.md")
        bdir = self._baseline({"memory_md.sha256": "0" * 64 + "\n"})  # different hash
        self.assertEqual(vm.inv_i5(bdir, target)["status"], "FAIL")
        # and a matching baseline passes
        bdir2 = self._baseline({"memory_md.sha256": post + "\n"})
        self.assertEqual(vm.inv_i5(bdir2, target)["status"], "PASS")


class InvI2(unittest.TestCase):
    def test_no_oracle_fails(self):
        self.assertEqual(vm.inv_i2(set(), None)["status"], "FAIL")

    def test_dry_run_skipped(self):
        out = 'MACHINE_SUMMARY {"transcripts_copied": 0, "dry_run": true}'
        self.assertEqual(vm.inv_i2(set(), out)["status"], "SKIPPED")

    def test_equal_passes(self):
        out = 'MACHINE_SUMMARY {"transcripts_copied": 3, "dry_run": false}'
        self.assertEqual(vm.inv_i2({"a", "b", "c"}, out)["status"], "PASS")

    def test_equal_zero_passes_with_note(self):
        out = 'MACHINE_SUMMARY {"transcripts_copied": 0, "dry_run": false}'
        r = vm.inv_i2(set(), out)
        self.assertEqual(r["status"], "PASS")
        self.assertIn("0", r["notes"])

    def test_added_gt_copied_fails(self):
        out = 'MACHINE_SUMMARY {"transcripts_copied": 1, "dry_run": false}'
        self.assertEqual(vm.inv_i2({"a", "b"}, out)["status"], "FAIL")

    def test_added_lt_copied_fails(self):
        out = 'MACHINE_SUMMARY {"transcripts_copied": 3, "dry_run": false}'
        self.assertEqual(vm.inv_i2({"a"}, out)["status"], "FAIL")


class InvI6(unittest.TestCase):
    def _setup(self, mutate_after=False, memory_source=True):
        ws = Path(tempfile.mkdtemp())
        (ws / "spaces.json").write_text('{"s":1}', encoding="utf-8")
        (ws / "local_a").mkdir()
        (ws / "local_b").mkdir()
        mem = ws / "spaces" / "sp" / "memory"
        mem.mkdir(parents=True)
        (mem / "x.md").write_text("x")
        reports = Path(tempfile.mkdtemp())
        bdir = reports / "baseline"
        bdir.mkdir(parents=True)
        (bdir / "cowork_spaces_json.sha256").write_text(
            vm.sha256_of_file(ws / "spaces.json") + "\n")
        (bdir / "cowork_memory_listing.txt").write_text("x.md\n")
        (bdir / "cowork_session_dir_count.txt").write_text("2\n")
        if mutate_after:
            (ws / "spaces.json").write_text('{"s":2}', encoding="utf-8")
        cfg = {"spaces_json": ws / "spaces.json",
               "memory_source": (mem if memory_source else None), "workspace": ws}
        return cfg, bdir

    def test_all_match_pass(self):
        cfg, bdir = self._setup()
        self.assertEqual(vm.inv_i6(cfg, bdir)["status"], "PASS")

    def test_spaces_json_mutation_fails(self):
        cfg, bdir = self._setup(mutate_after=True)
        self.assertEqual(vm.inv_i6(cfg, bdir)["status"], "FAIL")

    def test_memory_source_none_skips_subcheck(self):
        cfg, bdir = self._setup(memory_source=False)
        r = vm.inv_i6(cfg, bdir)
        self.assertEqual(r["status"], "PASS")
        self.assertEqual(r["computed"]["cowork_memory_match"], "SKIPPED (space unresolved)")


class ResolveSpaceUuid(unittest.TestCase):
    def _spaces_file(self, obj):
        p = Path(tempfile.mkdtemp()) / "spaces.json"
        p.write_text(json.dumps(obj), encoding="utf-8")
        return p

    def test_none_space(self):
        self.assertIsNone(vm.resolve_space_uuid(None, Path("/nope/spaces.json")))

    def test_uuid_passthrough(self):
        u = "11111111-1111-1111-1111-111111111111"
        self.assertEqual(vm.resolve_space_uuid(u, Path("/nope/spaces.json")), u)

    def test_name_resolves(self):
        f = self._spaces_file([{"id": "sp1", "name": "My Space"}])
        self.assertEqual(vm.resolve_space_uuid("My Space", f), "sp1")

    def test_ambiguous_returns_none(self):
        f = self._spaces_file([{"id": "a", "name": "Dup"}, {"id": "b", "name": "Dup"}])
        self.assertIsNone(vm.resolve_space_uuid("Dup", f))

    def test_missing_file_name_unresolved(self):
        self.assertIsNone(vm.resolve_space_uuid("Whatever", Path("/nope/spaces.json")))


class VerifySuiteEndToEnd(unittest.TestCase):
    MIGRATE = Path(__file__).resolve().parent.parent / "migrate_cowork_sessions.py"
    VERIFY = Path(__file__).resolve().parent.parent / "verify_migration.py"

    def _ws_and_target(self):
        ws = Path(tempfile.mkdtemp())
        build_synthetic_workspace(ws)
        target = Path(tempfile.mkdtemp()) / "target"
        return ws, target, SPACE_UUID

    def _baseline(self, ws, target, space, reports):
        return subprocess.run(
            [sys.executable, str(self.VERIFY), "--baseline", "--workspace", str(ws),
             "--target", str(target), "--space", space, "--output-dir", str(reports)],
            capture_output=True, text=True)

    def _migrate(self, ws, target, space, reports):
        r = subprocess.run(
            [sys.executable, str(self.MIGRATE), "--space", space, "--workspace", str(ws),
             "--target", str(target), "--create-target"], capture_output=True, text=True)
        (reports / "migration-output.txt").write_text(r.stdout, encoding="utf-8")
        return r

    def _verify(self, ws, target, space, reports):
        return subprocess.run(
            [sys.executable, str(self.VERIFY), "--verify", "--workspace", str(ws),
             "--target", str(target), "--space", space, "--baseline-dir", str(reports)],
            capture_output=True, text=True)

    def test_end_to_end_pass(self):
        ws, target, space = self._ws_and_target()
        reports = Path(tempfile.mkdtemp()) / "reports"
        self.assertEqual(self._baseline(ws, target, space, reports).returncode, 0)
        self.assertEqual(self._migrate(ws, target, space, reports).returncode, 0)
        v = self._verify(ws, target, space, reports)
        self.assertEqual(v.returncode, 0, v.stderr + v.stdout)
        summary = json.loads((reports / "summary.json").read_text())
        self.assertEqual(summary["verdict"], "PASS")
        self.assertEqual(summary["migration_errors"], 0)

    def test_end_to_end_fail_on_forbidden_artifact(self):
        ws, target, space = self._ws_and_target()
        reports = Path(tempfile.mkdtemp()) / "reports"
        self._baseline(ws, target, space, reports)
        self._migrate(ws, target, space, reports)
        (target / "agent-evil.jsonl").write_text('{"x":1}\n', encoding="utf-8")
        v = self._verify(ws, target, space, reports)
        self.assertEqual(v.returncode, 2, v.stdout)
        summary = json.loads((reports / "summary.json").read_text())
        self.assertEqual(summary["verdict"], "FAIL")
        self.assertIn("I4", summary["critical_failures"])


if __name__ == "__main__":
    unittest.main()
