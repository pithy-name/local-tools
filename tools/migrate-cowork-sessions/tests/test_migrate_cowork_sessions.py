"""Unit + integration tests for migrate_cowork_sessions.py.

Stdlib unittest only (Python 3.9+). Two layers:
  - Unit tests for pure/extractable helpers (discovery, classification,
    copy bookkeeping, snapshots, machine-summary line).
  - One integration test that builds a synthetic Cowork workspace on disk and
    subprocess-runs the migration end-to-end (exclusions, idempotency,
    0-byte heal, MACHINE_SUMMARY emission).

No real PII/paths: every fixture value is an invented placeholder.
"""
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # tool dir: tool modules
sys.path.insert(0, str(Path(__file__).resolve().parent))         # tests dir: fixtures

import migrate_cowork_sessions as m
from fixtures import build_synthetic_workspace, SPACE_UUID, SESS_UUID, TX_UUID

TOOL = Path(__file__).resolve().parent.parent / "migrate_cowork_sessions.py"


def _tmp() -> Path:
    return Path(tempfile.mkdtemp())


# ── load_spaces (3 valid shapes + unexpected shape) ────────────────────────────

class LoadSpaces(unittest.TestCase):
    def _write(self, obj) -> Path:
        p = _tmp() / "spaces.json"
        p.write_text(json.dumps(obj), encoding="utf-8")
        return p

    def test_list_shape(self):
        spaces = m.load_spaces(self._write([{"id": "s1", "name": "One"}]))
        self.assertEqual(spaces["s1"]["name"], "One")

    def test_wrapped_spaces_key_shape(self):
        spaces = m.load_spaces(self._write({"spaces": [{"id": "s2", "name": "Two"}]}))
        self.assertEqual(spaces["s2"]["name"], "Two")

    def test_id_keyed_dict_shape(self):
        spaces = m.load_spaces(self._write({"s3": {"name": "Three"}}))
        self.assertEqual(spaces["s3"]["name"], "Three")

    def test_unexpected_shape_warns(self):
        # FIX (Finding 14): a dict that is neither {"spaces":[...]} nor an
        # id->record map (values aren't all dicts) must emit a diagnostic.
        buf = io.StringIO()
        with redirect_stderr(buf):
            m.load_spaces(self._write({"version": 1, "data": []}))
        self.assertIn("unexpected shape", buf.getvalue().lower())

    def test_id_keyed_dict_does_not_warn(self):
        buf = io.StringIO()
        with redirect_stderr(buf):
            m.load_spaces(self._write({"s3": {"name": "Three"}}))
        self.assertNotIn("unexpected shape", buf.getvalue().lower())

    def test_parse_error_exits(self):
        p = _tmp() / "spaces.json"
        p.write_text("{not json", encoding="utf-8")
        with self.assertRaises(SystemExit):
            m.load_spaces(p)


# ── candidate_space_id / candidate_title / uuid / display name ──────────────────

class CandidateSpaceId(unittest.TestCase):
    def test_direct_string(self):
        self.assertEqual(m.candidate_space_id({"spaceId": "x"}), "x")

    def test_alt_keys(self):
        self.assertEqual(m.candidate_space_id({"project_id": "y"}), "y")

    def test_nested_dict(self):
        self.assertEqual(m.candidate_space_id({"space": {"id": "z"}}), "z")

    def test_absent(self):
        self.assertEqual(m.candidate_space_id({"unrelated": 1}), "")


class CandidateTitle(unittest.TestCase):
    def test_first_match_wins(self):
        self.assertEqual(m.candidate_title({"title": "T"}), "T")

    def test_alt_key(self):
        self.assertEqual(m.candidate_title({"name": "N"}), "N")

    def test_absent(self):
        self.assertEqual(m.candidate_title({}), "")


class LooksLikeUuid(unittest.TestCase):
    def test_valid(self):
        self.assertTrue(m._looks_like_uuid(SPACE_UUID))

    def test_uppercase_ok(self):
        self.assertTrue(m._looks_like_uuid(SPACE_UUID.upper()))

    def test_name_is_not_uuid(self):
        self.assertFalse(m._looks_like_uuid("My Project"))


class SpaceDisplayName(unittest.TestCase):
    def test_name_preferred(self):
        self.assertEqual(m._space_display_name({"name": "A", "title": "B"}), "A")

    def test_fallbacks(self):
        self.assertEqual(m._space_display_name({"displayName": "D"}), "D")

    def test_empty(self):
        self.assertEqual(m._space_display_name({}), "")


# ── _classify_session_jsonls (FIX: Findings 8 + 11) ────────────────────────────

class ClassifySessionJsonls(unittest.TestCase):
    def _session(self) -> Path:
        ws = _tmp()
        sess = ws / f"local_{SESS_UUID}"
        proj = sess / ".claude" / "projects" / "proj"
        proj.mkdir(parents=True)
        (proj / f"{TX_UUID}.jsonl").write_text('{"a":1}\n')              # transcript
        (proj / "subagents").mkdir()
        (proj / "subagents" / "agent-x.jsonl").write_text('{"s":1}\n')   # subagent path
        (proj / "audit.jsonl").write_text('{"audit":1}\n')               # audit
        (proj / "agent-root.jsonl").write_text('{"a":1}\n')              # agent-* at non-subagent path
        return sess

    def test_transcripts_kept(self):
        c = m._classify_session_jsonls(self._session())
        names = sorted(p.name for p in c["transcripts"])
        self.assertEqual(names, [f"{TX_UUID}.jsonl"])

    def test_subagents_excluded(self):
        c = m._classify_session_jsonls(self._session())
        self.assertEqual(c["subagents"], 1)

    def test_audit_excluded(self):
        c = m._classify_session_jsonls(self._session())
        self.assertEqual(c["audit"], 1)

    def test_agent_star_at_root_excluded(self):
        # FIX (Finding 11): agent-*.jsonl NOT under /subagents/ must still be
        # excluded so the migration never copies what verifier invariant I4 forbids.
        c = m._classify_session_jsonls(self._session())
        kept = [p.name for p in c["transcripts"]]
        self.assertNotIn("agent-root.jsonl", kept)

    def test_non_project_counted(self):
        # FIX (Finding 8): a would-be transcript outside /.claude/projects/ is
        # counted so the caller can warn about silent exclusion.
        ws = _tmp()
        sess = ws / f"local_{SESS_UUID}"
        other = sess / "elsewhere"
        other.mkdir(parents=True)
        (other / "stray.jsonl").write_text('{"a":1}\n')
        c = m._classify_session_jsonls(sess)
        self.assertEqual(c["non_project"], 1)
        self.assertEqual(c["transcripts"], [])

    def test_missing_dir(self):
        c = m._classify_session_jsonls(_tmp() / "nope")
        self.assertEqual(c["transcripts"], [])
        self.assertEqual(c["non_project"], 0)


class FindTranscripts(unittest.TestCase):
    def test_delegates_to_classifier(self):
        ws = _tmp()
        sess_id = f"local_{SESS_UUID}"
        proj = ws / sess_id / ".claude" / "projects" / "proj"
        proj.mkdir(parents=True)
        (proj / f"{TX_UUID}.jsonl").write_text('{"a":1}\n')
        (proj / "audit.jsonl").write_text('{"x":1}\n')
        out = m.find_transcripts_for_session(ws, sess_id)
        self.assertEqual([p.name for p in out], [f"{TX_UUID}.jsonl"])


# ── _dest_is_complete (FIX: Finding 7) ─────────────────────────────────────────

class DestIsComplete(unittest.TestCase):
    def test_missing_is_not_complete(self):
        self.assertFalse(m._dest_is_complete(_tmp() / "missing"))

    def test_nonempty_is_complete(self):
        p = _tmp() / "f"
        p.write_text("data")
        self.assertTrue(m._dest_is_complete(p))

    def test_zero_byte_is_not_complete(self):
        p = _tmp() / "f"
        p.write_text("")
        self.assertFalse(m._dest_is_complete(p))


# ── migrate_transcripts ────────────────────────────────────────────────────────

class MigrateTranscripts(unittest.TestCase):
    def _src(self, text='{"a":1}\n') -> Path:
        src_dir = _tmp()
        src = src_dir / f"{TX_UUID}.jsonl"
        src.write_text(text)
        return src

    def test_copies_new(self):
        src = self._src()
        target = _tmp()
        copied, skipped, errors = m.migrate_transcripts([src], target, dry_run=False)
        self.assertEqual(copied, [TX_UUID])
        self.assertTrue((target / src.name).is_file())

    def test_skips_existing_nonempty(self):
        src = self._src()
        target = _tmp()
        (target / src.name).write_text('{"old":1}\n')
        copied, skipped, errors = m.migrate_transcripts([src], target, dry_run=False)
        self.assertEqual(skipped, [TX_UUID])
        self.assertEqual(copied, [])
        # existing content preserved (skip = no overwrite)
        self.assertIn("old", (target / src.name).read_text())

    def test_recopies_zero_byte_dest(self):
        # FIX (Finding 7): a 0-byte dest from an interrupted prior copy must be
        # re-copied on a re-run, not skipped.
        src = self._src('{"real":1}\n')
        target = _tmp()
        (target / src.name).write_text("")  # interrupted prior copy
        copied, skipped, errors = m.migrate_transcripts([src], target, dry_run=False)
        self.assertEqual(copied, [TX_UUID])
        self.assertEqual(skipped, [])
        self.assertIn("real", (target / src.name).read_text())

    def test_dry_run_writes_nothing(self):
        src = self._src()
        target = _tmp()
        copied, skipped, errors = m.migrate_transcripts([src], target, dry_run=True)
        self.assertEqual(copied, [TX_UUID])           # bookkeeping still records it
        self.assertFalse((target / src.name).exists())  # but no file written


# ── migrate_tool_results ───────────────────────────────────────────────────────

class MigrateToolResults(unittest.TestCase):
    def _transcript_with_results(self) -> Path:
        base = _tmp()
        tx = base / f"{TX_UUID}.jsonl"
        tx.write_text('{"a":1}\n')
        tr = base / TX_UUID / "tool-results"
        tr.mkdir(parents=True)
        (tr / "r1.json").write_text('{"r":1}')
        return tx

    def test_copies_nested(self):
        tx = self._transcript_with_results()
        target = _tmp()
        copied, skipped, errors = m.migrate_tool_results([tx], target, dry_run=False)
        self.assertEqual(len(copied), 1)
        self.assertTrue((target / TX_UUID / "tool-results" / "r1.json").is_file())

    def test_dry_run_writes_nothing(self):
        tx = self._transcript_with_results()
        target = _tmp()
        copied, skipped, errors = m.migrate_tool_results([tx], target, dry_run=True)
        self.assertEqual(len(copied), 1)
        self.assertFalse((target / TX_UUID).exists())

    def test_recopies_zero_byte(self):
        tx = self._transcript_with_results()
        target = _tmp()
        dest = target / TX_UUID / "tool-results" / "r1.json"
        dest.parent.mkdir(parents=True)
        dest.write_text("")
        copied, skipped, errors = m.migrate_tool_results([tx], target, dry_run=False)
        self.assertEqual(len(copied), 1)
        self.assertEqual(len(skipped), 0)


# ── migrate_memory ─────────────────────────────────────────────────────────────

class MigrateMemory(unittest.TestCase):
    def _src(self) -> Path:
        src = _tmp()
        (src / "note.md").write_text("# note\n")
        (src / "MEMORY.md").write_text("# index\n")
        return src

    def test_copies_md_excludes_index(self):
        src = self._src()
        target = _tmp() / "memory"
        copied, skipped, errors = m.migrate_memory(src, target, dry_run=False)
        self.assertIn("note.md", copied)
        self.assertIn("MEMORY.md", skipped)
        self.assertTrue((target / "note.md").is_file())
        self.assertFalse((target / "MEMORY.md").exists())

    def test_missing_source(self):
        copied, skipped, errors = m.migrate_memory(_tmp() / "nope", _tmp(), dry_run=False)
        self.assertEqual((copied, skipped, errors), ([], [], []))

    def test_dry_run_writes_nothing(self):
        src = self._src()
        target = _tmp() / "memory"
        m.migrate_memory(src, target, dry_run=True)
        self.assertFalse(target.exists())


# ── snapshot_target_dir / snapshot_memory_md ───────────────────────────────────

class SnapshotTargetDir(unittest.TestCase):
    def test_counts_and_exclusions(self):
        target = _tmp()
        (target / f"{TX_UUID}.jsonl").write_text('{"a":1}\n')
        (target / "history.jsonl").write_text("x")          # excluded
        (target / ".DS_Store").write_text("x")              # hidden, excluded
        (target / "memory").mkdir()                          # excluded subdir
        (target / "memory" / "note.md").write_text("n")
        (target / TX_UUID).mkdir()                            # counted subdir
        snap = m.snapshot_target_dir(target)
        self.assertEqual(snap["jsonl_count"], 1)
        self.assertEqual(snap["jsonl_uuids"], [TX_UUID])
        self.assertEqual(snap["subdir_names"], [TX_UUID])
        self.assertEqual(snap["memory_count"], 1)
        self.assertFalse(snap["partial"])

    def test_missing_dir(self):
        snap = m.snapshot_target_dir(_tmp() / "nope")
        self.assertEqual(snap["jsonl_count"], 0)


class SnapshotMemoryMd(unittest.TestCase):
    def test_hash_present(self):
        target = _tmp()
        (target / "memory").mkdir()
        (target / "memory" / "MEMORY.md").write_text("index\n")
        self.assertIsNotNone(m.snapshot_memory_md(target))

    def test_missing_returns_none(self):
        self.assertIsNone(m.snapshot_memory_md(_tmp()))


# ── build_machine_summary_line (FIX: BLOCKER 3 — extract for guaranteed emit) ───

class BuildMachineSummary(unittest.TestCase):
    def test_emits_valid_json_line(self):
        line = m.build_machine_summary_line(
            transcripts_copied=3, transcripts_skipped=1,
            tool_results_copied=2, memory_copied=4, errors=0, dry_run=False,
        )
        self.assertTrue(line.startswith("MACHINE_SUMMARY "))
        payload = json.loads(line[len("MACHINE_SUMMARY "):])
        self.assertEqual(payload["transcripts_copied"], 3)
        self.assertEqual(payload["errors"], 0)
        self.assertFalse(payload["dry_run"])


# ── Integration: full migration against a synthetic workspace ──────────────────

class Integration(unittest.TestCase):
    def _build_workspace(self) -> Path:
        ws = _tmp()
        build_synthetic_workspace(ws)  # single source of truth (tests/fixtures.py)
        return ws

    def _run(self, ws: Path, target: Path):
        return subprocess.run(
            [sys.executable, str(TOOL), "--space", SPACE_UUID,
             "--workspace", str(ws), "--target", str(target), "--create-target"],
            capture_output=True, text=True,
        )

    @staticmethod
    def _summary(stdout: str) -> dict:
        for line in stdout.splitlines():
            if line.startswith("MACHINE_SUMMARY "):
                return json.loads(line[len("MACHINE_SUMMARY "):])
        raise AssertionError("no MACHINE_SUMMARY in output")

    def test_full_run(self):
        ws = self._build_workspace()
        target = _tmp() / "proj-target"
        r = self._run(ws, target)
        self.assertEqual(r.returncode, 0, r.stderr)

        # transcript + tool-results + memory copied; index + subagent + audit excluded
        self.assertTrue((target / f"{TX_UUID}.jsonl").is_file())
        self.assertTrue((target / TX_UUID / "tool-results" / "r1.json").is_file())
        self.assertTrue((target / "memory" / "note.md").is_file())
        self.assertFalse((target / "memory" / "MEMORY.md").exists())
        self.assertFalse((target / "audit.jsonl").exists())
        self.assertFalse(any(target.rglob("agent-x.jsonl")))

        s = self._summary(r.stdout)
        self.assertEqual(s["transcripts_copied"], 1)
        self.assertEqual(s["memory_copied"], 1)
        self.assertEqual(s["errors"], 0)
        self.assertFalse(s["dry_run"])

    def test_idempotent_rerun(self):
        ws = self._build_workspace()
        target = _tmp() / "proj-target"
        self._run(ws, target)
        r2 = self._run(ws, target)
        s = self._summary(r2.stdout)
        self.assertEqual(s["transcripts_copied"], 0)
        self.assertEqual(s["transcripts_skipped"], 1)

    def test_zero_byte_heal_on_rerun(self):
        # FIX (Finding 7) end-to-end: truncate a copied transcript to 0 bytes,
        # re-run, and confirm it is re-copied (not skipped).
        ws = self._build_workspace()
        target = _tmp() / "proj-target"
        self._run(ws, target)
        (target / f"{TX_UUID}.jsonl").write_text("")  # simulate interrupted copy
        r2 = self._run(ws, target)
        s = self._summary(r2.stdout)
        self.assertEqual(s["transcripts_copied"], 1)
        self.assertGreater((target / f"{TX_UUID}.jsonl").stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
