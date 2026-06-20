#!/usr/bin/env python3
"""verify_migration.py — property-based structural verifier for a Cowork → Claude Code migration.

GENERIC (Approach E): asserts PROPERTIES of any copy-only migration — no hardcoded fixtures,
no per-project UUIDs/titles. Works for any space, validated against live data.

Modes:
    --baseline   capture pre-migration state into <output-dir>/baseline/
    --verify     run the 6 invariants against current state, compare to baseline

Config (workspace / target / space) is resolved from CLI flags > OS env > .env, via
cowork_config.py (copy demo.env -> .env). Stdlib only, Python 3.9+. READ-ONLY: never
writes into the live project — only into the reports/baseline dir you point it at.

The 6 invariants (all CRITICAL):
    I1 Conservation        every pre-migration target path still present (no deletions)
    I2 Count cross-check   #(new root *.jsonl, excl. history.jsonl) == migrate's reported
                           transcripts_copied (independent oracle). SKIPPED on a dry-run.
    I3 Well-formed         every newly-added *.jsonl is non-empty and parses as JSON
    I4 Clean delta         no newly-added path is a subagent / audit / credentials artifact
    I5 MEMORY.md unchanged  target memory/MEMORY.md sha256 == baseline
    I6 Cowork sources       spaces.json sha256 + cowork memory listing + session-dir count
                           all unchanged (copy-only invariant)

Honest limit: I2 is a CONSISTENCY check (report agrees with the gross new-stem delta), not
completeness — it cannot detect a no-op or a drop masked by skip-existing, and nothing here
certifies that discovery selected the *right* sessions (no ground truth without a fixture).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cowork_config import load_dotenv, resolve, resolve_workspace  # noqa: E402
# Space-IDENTITY reuse ONLY (name->uuid). NEVER import transcript-DISCOVERY
# (find_transcripts_for_session/_scan_sidecars) — that would make the oracle
# self-referential (Approach A, which was rejected).
from migrate_cowork_sessions import (  # noqa: E402
    load_spaces, _looks_like_uuid, _space_display_name,
)

HISTORY_JSONL = "history.jsonl"  # Claude Code rewrites this at the target root; never "copied".

BASELINE_FILES = [
    "target_listing.txt",
    "target_jsonls.txt",
    "memory_md.sha256",
    "memory_listing.txt",
    "cowork_spaces_json.sha256",
    "cowork_memory_listing.txt",
    "cowork_session_dir_count.txt",
]


# ── Utilities ─────────────────────────────────────────────────────────────────

def info(msg: str) -> None:
    print(f"[verify] {msg}", flush=True)


def fail_precondition(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(2)


def sha256_of_file(path: Path) -> str:
    """sha256 hex of a file; '' if missing."""
    if not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def find_files(root: Path) -> list[str]:
    """`find <root> -type f`, sorted, relative paths. [] if root missing."""
    if not root.is_dir():
        return []
    out: list[str] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            out.append(os.path.relpath(os.path.join(dirpath, fn), str(root)))
    out.sort()
    return out


def list_jsonl_stems(root: Path) -> list[str]:
    """Sorted *.jsonl stems at root (top-level), EXCLUDING history.jsonl.
    Claude Code rewrites history.jsonl at the project root on activity; the migrate
    snapshot excludes it too, so the verifier must — else its churn inflates the delta."""
    if not root.is_dir():
        return []
    return sorted(
        p.stem for p in root.iterdir()
        if p.is_file() and p.suffix == ".jsonl" and p.name != HISTORY_JSONL
    )


def list_md_files(root: Path) -> list[str]:
    """Sorted *.md filenames at root. [] if missing."""
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_file() and p.suffix == ".md")


def count_local_dirs(root: Path) -> int:
    """Count `local_*` dirs at root (Cowork session dirs)."""
    if not root.is_dir():
        return 0
    return sum(1 for p in root.iterdir() if p.is_dir() and p.name.startswith("local_"))


# ── Pure predicates (unit-tested in test_verify_migration.py) ──────────────────

def parse_machine_summary(migration_output: str) -> Optional[dict]:
    """Return the LAST well-formed 'MACHINE_SUMMARY {json}' line from migrate stdout.
    LAST, not first: a dry-run + real run teed together → the real run wins; a malformed
    earlier line never shadows a valid later one. None if none found."""
    prefix = "MACHINE_SUMMARY "
    found = None
    for line in migration_output.splitlines():
        line = line.strip()
        if line.startswith(prefix):
            try:
                found = json.loads(line[len(prefix):])
            except json.JSONDecodeError:
                continue
    return found


def is_wellformed_jsonl(path: Path) -> bool:
    """size > 0 and first line parses as JSON."""
    try:
        if path.stat().st_size == 0:
            return False
        with path.open(encoding="utf-8") as f:
            json.loads(f.readline())
        return True
    except (OSError, json.JSONDecodeError):
        return False


def is_forbidden_added_path(rel_path: str) -> bool:
    """True if a newly-added path is a subagent / audit / credentials artifact."""
    base = rel_path.rsplit("/", 1)[-1]
    if "/subagents/" in rel_path or rel_path.startswith("subagents/"):
        return True
    if base == "audit.jsonl":
        return True
    if base.startswith("agent-") and base.endswith(".jsonl"):
        return True
    if "credentials" in base.lower():
        return True
    return False


# ── Config resolution (flags > OS env > .env) ─────────────────────────────────

def resolve_space_uuid(space: Optional[str], spaces_json: Path) -> Optional[str]:
    """Map a space name-or-uuid to its UUID. None if unset / unresolvable / ambiguous.
    Reuses the migrate script's space-IDENTITY logic (NOT transcript discovery)."""
    if not space:
        return None
    if _looks_like_uuid(space):
        return space
    spaces = load_spaces(spaces_json) if spaces_json.is_file() else {}
    target = space.strip().lower()
    matches = [sid for sid, rec in spaces.items()
               if _space_display_name(rec).strip().lower() == target]
    return matches[0] if len(matches) == 1 else None


def resolve_config(args) -> dict:
    dotenv = load_dotenv()
    workspace = resolve_workspace(getattr(args, "workspace", None), dotenv)
    if workspace is None:
        fail_precondition("COWORK_WORKSPACE not set (copy demo.env -> .env, or pass --workspace).")
    target_raw = resolve(getattr(args, "target", None), "COWORK_TARGET", dotenv)
    if not target_raw:
        fail_precondition("COWORK_TARGET not set (set it in .env or pass --target).")
    space = resolve(getattr(args, "space", None), "COWORK_SPACE", dotenv)
    spaces_json = workspace / "spaces.json"
    space_uuid = resolve_space_uuid(space, spaces_json)
    memory_source = (workspace / "spaces" / space_uuid / "memory") if space_uuid else None
    return {
        "workspace": workspace,
        "target": Path(target_raw).expanduser(),
        "space": space,
        "spaces_json": spaces_json,
        "space_uuid": space_uuid,
        "memory_source": memory_source,
    }


# ── Baseline mode ─────────────────────────────────────────────────────────────

def run_baseline(cfg: dict, output_dir: Path) -> None:
    info("Mode: --baseline")
    if output_dir.exists():
        fail_precondition(f"--output-dir already exists; refusing to overwrite: {output_dir}")
    target = cfg["target"]
    if not target.is_dir():
        info(f"NOTE: target does not exist yet ({target}); capturing an empty baseline "
             "(the migration will create it).")

    baseline_dir = output_dir / "baseline"
    baseline_dir.mkdir(parents=True, exist_ok=False)
    info(f"Created {baseline_dir}")

    def write(name: str, text: str) -> None:
        (baseline_dir / name).write_text(text, encoding="utf-8")

    def lines(items: list[str]) -> str:
        return "\n".join(items) + ("\n" if items else "")

    write("target_listing.txt", lines(find_files(target)))
    write("target_jsonls.txt", lines(list_jsonl_stems(target)))
    md_hash = sha256_of_file(target / "memory" / "MEMORY.md")
    write("memory_md.sha256", (md_hash + "\n") if md_hash else "")
    write("memory_listing.txt", lines(list_md_files(target / "memory")))
    spaces_hash = sha256_of_file(cfg["spaces_json"])
    write("cowork_spaces_json.sha256", (spaces_hash + "\n") if spaces_hash else "")
    mem_src = cfg["memory_source"]
    if mem_src is None:
        info("NOTE: space unset/unresolved → cowork_memory_listing left empty (I6 sub-check skips).")
    write("cowork_memory_listing.txt", lines(list_md_files(mem_src) if mem_src else []))
    write("cowork_session_dir_count.txt", f"{count_local_dirs(cfg['workspace'])}\n")

    info(f"Baseline capture complete. Wrote {len(BASELINE_FILES)} files to {baseline_dir}")
    for fn in BASELINE_FILES:
        p = baseline_dir / fn
        info(f"  {fn}  ({p.stat().st_size if p.exists() else -1} bytes)")


# ── Result helpers ────────────────────────────────────────────────────────────

def make_result(test_id: str, criticality: str, status: str, computed: dict,
                expected: dict, operation: str, notes: str = "", acceptance: str = "") -> dict:
    return {
        "id": test_id, "criticality": criticality, "status": status,
        "computed": computed, "expected": expected, "operation": operation,
        "notes": notes, "acceptance": acceptance,
    }


def write_test_file(reports_dir: Path, result: dict) -> Path:
    out_path = reports_dir / f"{result['id']}.txt"
    lines = [
        f"Test: {result['id']}",
        f"Criticality: {result['criticality']}",
        f"Status: {result['status']}",
        f"Acceptance Criterion: {result.get('acceptance', '')}",
        "", "Computed values:",
    ]
    for k, v in result["computed"].items():
        lines.append(f"  {k}: {v}")
    lines += ["", "Expected values:"]
    for k, v in result["expected"].items():
        lines.append(f"  {k}: {v}")
    lines += ["", f"Operation: {result['operation']}", "", f"Notes: {result.get('notes', '')}", ""]
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def read_baseline_file(baseline_dir: Path, name: str) -> str:
    p = baseline_dir / name
    if not p.is_file():
        raise FileNotFoundError(f"Baseline file missing: {p}")
    return p.read_text(encoding="utf-8")


def read_baseline_lines(baseline_dir: Path, name: str) -> list[str]:
    raw = read_baseline_file(baseline_dir, name).strip("\n")
    if not raw:
        return []
    return [line.rstrip("\r") for line in raw.split("\n")]


# ── Invariants ────────────────────────────────────────────────────────────────

def inv_i1(baseline_listing: list[str], post_listing: set) -> dict:
    missing = sorted(p for p in baseline_listing if p not in post_listing)
    status = "PASS" if not missing else "FAIL"
    return make_result(
        "I1", "CRITICAL", status,
        computed={"missing_count": len(missing), "missing": missing[:20]},
        expected={"missing_count": 0},
        operation="every path in baseline target_listing.txt still present at target",
        acceptance="No pre-migration target path was deleted or moved by the migration.",
    )


def inv_i2(added: set, migration_output: Optional[str]) -> dict:
    summary = parse_machine_summary(migration_output) if migration_output else None
    if summary is None:
        return make_result(
            "I2", "CRITICAL", "FAIL",
            computed={"added": len(added), "summary": None},
            expected={"added_equals_transcripts_copied": True},
            operation="parse MACHINE_SUMMARY from migration output; compare to new-stem delta",
            notes="No MACHINE_SUMMARY line found — was the REAL migration teed to migration-output.txt?",
            acceptance="The migrate script's reported transcripts_copied equals the measured new-jsonl delta.",
        )
    if summary.get("dry_run"):
        return make_result(
            "I2", "CRITICAL", "SKIPPED",
            computed={"added": len(added), "dry_run": True,
                      "transcripts_copied": summary.get("transcripts_copied")},
            expected={"note": "count check is N/A on a dry-run"},
            operation="dry-run detected — count cross-check skipped",
            notes="migration-output reports dry_run=true; a dry-run copies nothing. Verify a REAL migration.",
            acceptance="(skipped on dry-run)",
        )
    copied = summary.get("transcripts_copied")
    n = len(added)
    if n == copied:
        notes = "" if copied else "migration reported 0 transcripts copied — confirm that's expected."
        status = "PASS"
    elif n > copied:
        status = "FAIL"
        notes = (f"added ({n}) > reported copied ({copied}) — likely EXTERNAL churn: a concurrent "
                 "Claude Code session wrote a transcript to the target between --baseline and --verify. "
                 "Re-baseline with no other sessions open.")
    else:
        status = "FAIL"
        notes = (f"added ({n}) < reported copied ({copied}) — SHORTFALL: files the migrate script "
                 "reported copying are not present at the target root.")
    return make_result(
        "I2", "CRITICAL", status,
        computed={"added": n, "transcripts_copied": copied},
        expected={"added_equals_transcripts_copied": True},
        operation="len(new root *.jsonl stems, excl. history.jsonl) == MACHINE_SUMMARY.transcripts_copied",
        notes=notes,
        acceptance="Independent oracle: the script's self-reported count agrees with the filesystem delta.",
    )


def inv_i3(added: set, target: Path) -> dict:
    offenders = sorted(s for s in added if not is_wellformed_jsonl(target / f"{s}.jsonl"))
    status = "PASS" if not offenders else "FAIL"
    return make_result(
        "I3", "CRITICAL", status,
        computed={"malformed_count": len(offenders), "malformed": offenders[:20]},
        expected={"malformed_count": 0},
        operation="each newly-added <stem>.jsonl: size>0 and first line parses as JSON",
        acceptance="Every transcript the migration added is non-empty and valid JSONL.",
    )


def inv_i4(added_paths: set) -> dict:
    forbidden = sorted(p for p in added_paths if is_forbidden_added_path(p))
    status = "PASS" if not forbidden else "FAIL"
    return make_result(
        "I4", "CRITICAL", status,
        computed={"forbidden_count": len(forbidden), "forbidden": forbidden[:20]},
        expected={"forbidden_count": 0},
        operation="no newly-added path is agent-*.jsonl / audit.jsonl / *credentials* / under /subagents/",
        acceptance="The migration leaked no subagent, audit, or credential artifacts into the target.",
    )


def inv_i5(baseline_dir: Path, target: Path) -> dict:
    baseline_hash = read_baseline_file(baseline_dir, "memory_md.sha256").strip()
    post_hash = sha256_of_file(target / "memory" / "MEMORY.md")
    status = "PASS" if baseline_hash == post_hash else "FAIL"
    return make_result(
        "I5", "CRITICAL", status,
        computed={"post_sha256": post_hash or "(absent)"},
        expected={"baseline_sha256": baseline_hash or "(absent)"},
        operation="sha256(target/memory/MEMORY.md) == baseline memory_md.sha256",
        notes="The migration must not modify the index; the operator updates MEMORY.md separately, after verify.",
        acceptance="MEMORY.md was unchanged by the migration script.",
    )


def inv_i6(cfg: dict, baseline_dir: Path) -> dict:
    sub = {}
    # a. spaces.json sha256
    base_spaces = read_baseline_file(baseline_dir, "cowork_spaces_json.sha256").strip()
    now_spaces = sha256_of_file(cfg["spaces_json"])
    sub["spaces_json_match"] = (base_spaces == now_spaces)
    # b. cowork memory listing (skip if space unresolved)
    mem_src = cfg["memory_source"]
    if mem_src is None:
        sub["cowork_memory_match"] = "SKIPPED (space unresolved)"
    else:
        base_mem = read_baseline_lines(baseline_dir, "cowork_memory_listing.txt")
        now_mem = list_md_files(mem_src)
        sub["cowork_memory_match"] = (base_mem == now_mem)
    # c. session-dir count
    base_count = read_baseline_file(baseline_dir, "cowork_session_dir_count.txt").strip()
    now_count = str(count_local_dirs(cfg["workspace"]))
    sub["session_dir_count_match"] = (base_count == now_count)

    failed = [k for k, v in sub.items() if v is False]
    status = "PASS" if not failed else "FAIL"
    return make_result(
        "I6", "CRITICAL", status,
        computed={**sub, "now_session_dir_count": now_count},
        expected={"all_cowork_sources_unchanged": True, "baseline_session_dir_count": base_count},
        operation="spaces.json sha256 + cowork memory listing + session-dir count all == baseline",
        notes="Copy-only invariant: the migration must never modify Cowork sources.",
        acceptance="The migration read Cowork sources without mutating them.",
    )


# ── Verify mode ───────────────────────────────────────────────────────────────

def run_verify(cfg: dict, reports_dir: Path, migration_output_arg: Optional[Path]) -> int:
    info("Mode: --verify")
    baseline_dir = reports_dir / "baseline"
    if not baseline_dir.is_dir():
        fail_precondition(f"baseline/ subdir not found under --baseline-dir: {baseline_dir}")
    missing = [fn for fn in BASELINE_FILES if not (baseline_dir / fn).is_file()]
    if missing:
        fail_precondition(f"baseline/ is missing expected files: {missing}")
    info(f"Baseline OK at {baseline_dir}")

    # Migration output: explicit --migration-output wins, else sibling of baseline/.
    mo_path = migration_output_arg or (reports_dir / "migration-output.txt")
    migration_output: Optional[str] = None
    if mo_path.is_file():
        migration_output = mo_path.read_text(encoding="utf-8", errors="replace")
        info(f"Loaded migration output: {mo_path} ({len(migration_output)} chars)")
    else:
        info(f"migration output not found at {mo_path}; I2 will FAIL (no oracle).")

    target = cfg["target"]
    baseline_listing = read_baseline_lines(baseline_dir, "target_listing.txt")
    baseline_jsonls = set(read_baseline_lines(baseline_dir, "target_jsonls.txt"))
    post_listing = set(find_files(target))
    post_jsonls = set(list_jsonl_stems(target))
    added = post_jsonls - baseline_jsonls
    added_paths = post_listing - set(baseline_listing)

    summary = parse_machine_summary(migration_output) if migration_output else None
    dry_run_mode = bool(summary and summary.get("dry_run"))
    if dry_run_mode:
        info("WARNING: migration output reports dry_run=true — this is NOT a real verification.")

    results = [
        inv_i1(baseline_listing, post_listing),
        inv_i2(added, migration_output),
        inv_i3(added, target),
        inv_i4(added_paths),
        inv_i5(baseline_dir, target),
        inv_i6(cfg, baseline_dir),
    ]
    for r in results:
        info(f"  {r['id']} → {r['status']}")
        write_test_file(reports_dir, r)

    critical_failures = [r["id"] for r in results
                         if r["criticality"] == "CRITICAL" and r["status"] == "FAIL"]
    critical_skipped = [r["id"] for r in results
                        if r["criticality"] == "CRITICAL" and r["status"] == "SKIPPED"]

    if dry_run_mode:
        verdict, exit_code = "PARTIAL PASS", 1
        verdict_note = ("migration output was a DRY RUN — structural invariants are vacuous "
                        "(nothing copied). Run a REAL migration to verify.")
    elif critical_failures:
        verdict, exit_code = "FAIL", 2
        verdict_note = f"CRITICAL failures: {critical_failures}"
    elif critical_skipped:
        verdict, exit_code = "FAIL", 2
        verdict_note = f"CRITICAL tests skipped (missing input): {critical_skipped}"
    else:
        verdict, exit_code = "PASS", 0
        verdict_note = "all invariants passed"

    summary_out = {
        "verdict": verdict,
        "verdict_note": verdict_note,
        "timestamp": reports_dir.name,
        "tests": [{"id": r["id"], "criticality": r["criticality"],
                   "status": r["status"], "raw_output_path": f"{r['id']}.txt"} for r in results],
        "critical_failures": critical_failures,
        "critical_skipped": critical_skipped,
    }
    (reports_dir / "summary.json").write_text(json.dumps(summary_out, indent=2) + "\n", encoding="utf-8")
    info(f"Wrote {reports_dir / 'summary.json'}")
    info(f"Verdict: {verdict} (exit {exit_code}) — {verdict_note}")
    return exit_code


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Property-based verifier for a Cowork → Claude Code migration (Approach E).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--baseline", action="store_true", help="Capture pre-migration baseline.")
    mode.add_argument("--verify", action="store_true", help="Run the 6 invariants against baseline.")

    parser.add_argument("--output-dir", type=Path,
                        help="(--baseline) dir to write baseline/ into (must not exist).")
    parser.add_argument("--baseline-dir", type=Path,
                        help="(--verify) reports dir containing baseline/ + migration-output.txt.")
    parser.add_argument("--migration-output", type=Path,
                        help="(--verify) explicit path to the real migration's stdout capture "
                             "(overrides <baseline-dir>/migration-output.txt).")
    # Config overrides (else from .env):
    parser.add_argument("--workspace", default=None,
                        help="Cowork workspace '<outer>/<inner>' or absolute path. Overrides COWORK_WORKSPACE.")
    parser.add_argument("--target", default=None,
                        help="Claude Code project dir. Overrides COWORK_TARGET.")
    parser.add_argument("--space", default=None,
                        help="Cowork space name or UUID (for the I6 cowork-memory sub-check). Overrides COWORK_SPACE.")

    args = parser.parse_args()
    cfg = resolve_config(args)

    if args.baseline:
        if args.output_dir is None:
            parser.error("--baseline requires --output-dir")
        run_baseline(cfg, args.output_dir)
        return 0
    else:
        if args.baseline_dir is None:
            parser.error("--verify requires --baseline-dir")
        return run_verify(cfg, args.baseline_dir, args.migration_output)


if __name__ == "__main__":
    sys.exit(main())
