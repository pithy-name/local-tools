#!/usr/bin/env python3
"""
migrate_cowork_sessions.py

Migrates Cowork session transcripts (JSONL), tool-results, and memory files
from a specific Cowork project (space) into a Claude Code project directory.

Discovery uses sidecar JSON files (local_*.json) with spaceId field matching —
not glob-based discovery. This ensures only sessions belonging to the target
project are copied.

Run AFTER closing all Cowork sessions for the project being migrated.
Safe to re-run: existing files are skipped.

Usage:
    # List available spaces
    python3 migrate_cowork_sessions.py --list

    # Dry run — verify session titles and counts
    python3 migrate_cowork_sessions.py \\
        --space "<SPACE_NAME>" \\
        --target <CLAUDE_PROJECT_DIR> \\
        --dry-run

    # Full migration (values may instead come from .env — see demo.env)
    python3 migrate_cowork_sessions.py --space "<SPACE_NAME>" --target <CLAUDE_PROJECT_DIR>

    # Post-archive recovery: pass the space UUID directly (bypasses spaces.json)
    python3 migrate_cowork_sessions.py --space "<SPACE_UUID>" --target <CLAUDE_PROJECT_DIR>

Config: COWORK_WORKSPACE (required), COWORK_SPACE / COWORK_TARGET (optional)
are read from a .env beside this script (copy demo.env -> .env). CLI flags override.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Optional

# ── Config: resolved from CLI flag > OS env > .env (see cowork_config.py) ───────
sys.path.insert(0, str(Path(__file__).resolve().parent))
from cowork_config import COWORK_BASE, load_dotenv, resolve, resolve_workspace

# ── Discovery helpers (ported from extract-cowork-projects.py) ─────────────────

def load_spaces(spaces_file: Path) -> dict:
    """Read spaces.json. Return dict: spaceId -> full space record.
    Handles 3 JSON shapes: list, dict keyed by id, or {"spaces": [...]}.
    Exits on parse failure."""
    try:
        with open(spaces_file, "r", encoding="utf-8-sig", errors="replace") as f:
            data = json.load(f)
    except Exception as e:
        print(f"ERROR: failed to parse {spaces_file}: {e}", file=sys.stderr)
        sys.exit(1)
    if isinstance(data, list):
        return {s.get("id", s.get("spaceId", f"_idx{i}")): s for i, s in enumerate(data)}
    if isinstance(data, dict):
        if "spaces" in data and isinstance(data["spaces"], list):
            return {s.get("id", s.get("spaceId", f"_idx{i}")): s
                    for i, s in enumerate(data["spaces"])}
        if data and not all(isinstance(v, dict) for v in data.values()):
            print(f"WARNING: {spaces_file} has an unexpected shape (not a list, not "
                  "a {'spaces':[...]} wrapper, and not an id->record map). Space-name "
                  "resolution may fail; pass --space <uuid> to match sidecars directly.",
                  file=sys.stderr)
        return data
    return {}


def list_session_metadata_files(workspace: Path) -> list[Path]:
    """Return sorted list of local_<uuid>.json sidecar files in workspace."""
    return sorted(
        p for p in workspace.glob("local_*.json")
        if p.is_file()
    )


def candidate_space_id(session_meta: dict) -> str:
    """Try several plausible field names for the space/project ID."""
    for k in ("spaceId", "space_id", "projectId", "project_id", "space", "project"):
        if k in session_meta:
            v = session_meta[k]
            if isinstance(v, str):
                return v
            if isinstance(v, dict):
                for kk in ("id", "spaceId", "uuid"):
                    if kk in v:
                        return v[kk]
    return ""


def candidate_title(session_meta: dict) -> str:
    for k in ("title", "name", "summary", "subject"):
        if k in session_meta and isinstance(session_meta[k], str):
            return session_meta[k]
    return ""


def _classify_session_jsonls(session_dir: Path) -> dict:
    """Classify every *.jsonl under a session dir (filesystem read only).
    Returns counts/lists:
      - transcripts:  list[Path] kept (under /.claude/projects/, not subagent/audit/agent-*)
      - subagents:    count excluded as subagent transcripts (incl. agent-*.jsonl anywhere)
      - audit:        count excluded as audit.jsonl
      - non_project:  count of would-be transcripts excluded ONLY by the
                      /.claude/projects/ path filter (signals silent exclusion)
    A file is kept iff: '/.claude/projects/' in path AND not a subagent AND not audit.
    agent-*.jsonl under /.claude/projects/ but NOT under /subagents/ is silently
    excluded (I4 forbids them) without incrementing any diagnostic counter.
    agent-*.jsonl under /subagents/ is counted in subagents."""
    result: dict = {"transcripts": [], "subagents": 0, "audit": 0, "non_project": 0}
    if not session_dir.is_dir():
        return result
    for p in session_dir.rglob("*.jsonl"):
        sp = str(p)
        base = p.name
        is_subagent_path = "/subagents/" in sp
        is_agent_star = base.startswith("agent-")
        is_audit = sp.endswith("/audit.jsonl")
        in_projects = "/.claude/projects/" in sp
        if is_subagent_path:
            result["subagents"] += 1
        elif is_audit:
            result["audit"] += 1
        elif not in_projects:
            result["non_project"] += 1
        elif is_agent_star:
            # agent-*.jsonl inside /.claude/projects/ but NOT under /subagents/:
            # excluded (I4 forbids them) but not counted in any diagnostic bucket.
            pass
        else:
            result["transcripts"].append(p)
    return result


def find_transcripts_for_session(workspace: Path, session_id: str) -> list[Path]:
    """Return main transcript paths for a given local_<uuid> session dir.
    Skips subagent transcripts, audit.jsonl, and agent-*.jsonl (see
    _classify_session_jsonls)."""
    return _classify_session_jsonls(workspace / session_id)["transcripts"]


def _space_display_name(space_record: dict) -> str:
    return (space_record.get("name") or space_record.get("title")
            or space_record.get("displayName") or "")


# ── UUID detection ─────────────────────────────────────────────────────────────

def _looks_like_uuid(s: str) -> bool:
    return bool(re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        s.lower(),
    ))


# ── Sidecar scan (shared by list mode and --space mode) ───────────────────────

def _scan_sidecars(workspace: Path) -> tuple[list[dict], int, int, set[str]]:
    """Parse all sidecar files. Returns:
      - sessions: list of {session_id, space_id, title}
      - parse_errors: count of sidecars that failed to parse
      - empty_space_id: count of sidecars with no spaceId
      - sidecar_stems: set of session_id values seen in sidecars
    """
    sidecar_files = list_session_metadata_files(workspace)
    sessions = []
    parse_errors = 0
    empty_space_id = 0
    sidecar_stems: set[str] = set()

    for sf in sidecar_files:
        sidecar_stems.add(sf.stem)
        try:
            with open(sf, "r", encoding="utf-8-sig", errors="replace") as f:
                meta = json.load(f)
        except Exception as e:
            print(f"WARNING: failed to parse sidecar {sf.name}: {e}", file=sys.stderr)
            parse_errors += 1
            continue

        space_id = candidate_space_id(meta)
        title = candidate_title(meta)
        if not space_id:
            empty_space_id += 1
        sessions.append({"session_id": sf.stem, "space_id": space_id, "title": title})

    return sessions, parse_errors, empty_space_id, sidecar_stems


# ── List mode ──────────────────────────────────────────────────────────────────

def _print_space_table(workspace: Path, spaces: dict) -> None:
    sessions, _parse_errors, unassigned, _stems = _scan_sidecars(workspace)

    space_counts: Counter = Counter()
    for s in sessions:
        if s["space_id"]:
            space_counts[s["space_id"]] += 1

    rows = []
    for space_id, count in space_counts.most_common():
        space_record = spaces.get(space_id, {})
        name = _space_display_name(space_record) or f"(unknown: {space_id[:8]}...)"
        rows.append((name, count, space_id))
    rows.sort(key=lambda r: r[0].lower())

    print(f"\nAvailable Cowork spaces in:\n  {workspace}\n")
    print(f"  {'Space name':<42} {'Sessions':>8}  Space ID")
    print(f"  {'-'*42} {'-'*8}  {'-'*36}")
    for name, count, space_id in rows:
        print(f"  {name:<42} {count:>8}  {space_id}")
    if unassigned:
        print(f"  {'(unassigned — no spaceId)':<42} {unassigned:>8}")
    print()


# ── Migration ──────────────────────────────────────────────────────────────────

def _dest_is_complete(dest: Path) -> bool:
    """True if dest exists and is non-empty (safe to skip on a re-run). A 0-byte
    dest is treated as an interrupted prior copy → re-copy it so an idempotent
    re-run heals it (verifier I3 would otherwise FAIL on the empty file)."""
    try:
        return dest.exists() and dest.stat().st_size > 0
    except OSError:
        return False


def migrate_transcripts(
    transcripts: list[Path], target_dir: Path, dry_run: bool
) -> tuple[list[str], list[str], list[str]]:
    """Copy JSONL transcripts to target_dir. Returns (copied_stems, skipped_stems, error_stems)."""
    copied: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []
    for src in transcripts:
        dest = target_dir / src.name
        if _dest_is_complete(dest):
            print(f"  skip   {src.name}")
            skipped.append(src.stem)
        else:
            print(f"  copy   {src.name}")
            if not dry_run:
                try:
                    shutil.copy2(src, dest)
                except OSError as e:
                    print(f"  ERROR  {src.name}: {e}")
                    errors.append(src.stem)
                    continue
            copied.append(src.stem)
    return copied, skipped, errors


def migrate_tool_results(
    transcripts: list[Path], target_dir: Path, dry_run: bool
) -> tuple[list[str], list[str], list[str]]:
    """Copy tool-results dirs for each transcript. Returns (copied_paths, skipped_paths, error_paths)."""
    copied: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []
    for src_transcript in transcripts:
        # Source: <session_dir>/.claude/projects/<key>/<uuid>/tool-results/
        tool_results_src = src_transcript.parent / src_transcript.stem / "tool-results"
        if not tool_results_src.exists():
            continue
        # Dest: <target>/<uuid>/tool-results/
        tool_results_dest = target_dir / src_transcript.stem / "tool-results"
        for src_file in sorted(tool_results_src.rglob("*")):
            if not src_file.is_file():
                continue
            rel = src_file.relative_to(tool_results_src)
            dest_file = tool_results_dest / rel
            label = f"{src_transcript.stem}/tool-results/{rel}"
            if _dest_is_complete(dest_file):
                print(f"  skip   {label}")
                skipped.append(label)
            else:
                print(f"  copy   {label}")
                if not dry_run:
                    try:
                        dest_file.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src_file, dest_file)
                    except OSError as e:
                        print(f"  ERROR  {label}: {e}")
                        errors.append(label)
                        continue
                copied.append(label)
    return copied, skipped, errors


def migrate_memory(
    memory_source: Path, memory_target: Path, dry_run: bool
) -> tuple[list[str], list[str], list[str]]:
    """Copy *.md from memory_source to memory_target, excluding MEMORY.md.
    Returns (copied_names, skipped_names, error_names)."""
    if not memory_source.exists():
        print(f"  Source not found: {memory_source}")
        print("  (Normal if the Cowork project has no memory files.)")
        return [], [], []

    if not dry_run:
        try:
            memory_target.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            print(f"  ERROR  could not create {memory_target}: {e}")
            return [], [], ["<mkdir failed>"]

    copied: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []
    for src in sorted(memory_source.glob("*.md")):
        if src.name == "MEMORY.md":
            # MEMORY.md is an index file, not content. Copying it would overwrite
            # the Claude Code project's own index with Cowork's stale version.
            print(f"  skip   {src.name}  (index file — excluded)")
            skipped.append(src.name)
            continue
        dest = memory_target / src.name
        if _dest_is_complete(dest):
            print(f"  skip   {src.name}  (already exists)")
            skipped.append(src.name)
        else:
            print(f"  copy   {src.name}")
            if not dry_run:
                try:
                    shutil.copy2(src, dest)
                except OSError as e:
                    print(f"  ERROR  {src.name}: {e}")
                    errors.append(src.name)
                    continue
            copied.append(src.name)
    return copied, skipped, errors


# ── ASCII summary ──────────────────────────────────────────────────────────────

def print_ascii_summary(
    space_name: str,
    dry_run: bool,
    target_sessions: list[dict],
    session_transcript_map: dict[str, list[Path]],
    copied_stems: set[str],
    skipped_stems: set[str],
    error_stems: set[str],
    tr_copied: list[str],
    tr_skipped: list[str],
    tr_errors: list[str],
    mem_copied: list[str],
    mem_skipped: list[str],
    mem_errors: list[str],
) -> None:
    mode = "DRY RUN" if dry_run else "RESULT"
    sep = "─" * 68
    legend = "  legend: ✓ copied   → skipped (already present)   ✗ error"
    print()
    print(f"  {mode} — {space_name}")
    print(legend)
    print(f"  {sep}")

    for s in target_sessions:
        txs = session_transcript_map[s["session_id"]]
        title = s["title"] or "(untitled)"
        title_q = f'"{title[:33]}..."' if len(title) > 36 else f'"{title}"'
        if not txs:
            print(f"  {title_q:<42} {'(no transcripts)':<18} ✗")
            continue
        for i, tx in enumerate(txs):
            stem = tx.stem
            uuid_col = stem[:8] + "....jsonl"
            if stem in error_stems:
                status = "✗"
            elif stem in skipped_stems:
                status = "→"
            else:
                status = "✓"
            row_title = title_q if i == 0 else ""
            print(f"  {row_title:<42} {uuid_col:<18} {status}")

    def _tr_row(label: str, status: str) -> None:
        parts = label.split("/tool-results/", 1)
        stem_short = parts[0][:8] + "..."
        fname = parts[1] if len(parts) > 1 else label
        fname_col = (fname[:22] + "...") if len(fname) > 25 else fname
        print(f"    {stem_short}/tool-results/{fname_col}  {status}")

    if tr_copied or tr_skipped or tr_errors:
        print()
        print("  tool-results:")
        for tr in tr_copied:
            _tr_row(tr, "✓")
        for tr in tr_skipped:
            _tr_row(tr, "→")
        for tr in tr_errors:
            _tr_row(tr, "✗")

    if mem_copied or mem_skipped or mem_errors:
        print()
        print("  memory:")
        for m in mem_copied:
            print(f"    {m}  ✓")
        for m in mem_skipped:
            print(f"    {m}  →")
        for m in mem_errors:
            print(f"    {m}  ✗")

    print(f"  {sep}")


# ── Snapshot / diff helpers ────────────────────────────────────────────────────

def _retry_scan(scan_fn, label: str, max_attempts: int = 3, base_delay: float = 0.2) -> bool:
    """Run scan_fn with bounded retry on OSError. Returns True if any attempt
    succeeded, False if all attempts failed (caller marks snapshot partial).

    Prints a WARNING per failed attempt + a final summary if all fail. The
    operator sees the full retry trace + decides whether the partial snapshot
    is safe to act on.
    """
    last_error: Optional[OSError] = None
    for attempt in range(1, max_attempts + 1):
        try:
            scan_fn()
            if attempt > 1:
                print(f"  [retry succeeded on attempt {attempt}/{max_attempts}] {label}")
            return True
        except OSError as e:
            last_error = e
            if attempt < max_attempts:
                print(f"  WARNING: scan failed on attempt {attempt}/{max_attempts} for {label} ({e}); retrying after {base_delay * attempt:.1f}s")
                time.sleep(base_delay * attempt)
    print(f"  WARNING: all {max_attempts} scan attempts failed for {label} ({last_error}); snapshot will be marked PARTIAL")
    return False


def snapshot_target_dir(target_dir: Path) -> dict:
    """Capture a snapshot of target_dir's top-level shape.

    Returns a dict with:
      - jsonl_count:  count of *.jsonl files at root (excluding history.jsonl)
      - jsonl_uuids:  sorted list of *.jsonl stems (excluding history)
      - subdir_count: count of subdirs at root (excluding 'memory')
      - subdir_names: sorted list of subdir names (excluding 'memory')
      - memory_count: count of *.md files in target/memory/ (0 if dir missing)
      - memory_files: sorted list of memory/*.md filenames
      - other_files:  sorted list of non-jsonl, non-hidden, non-dir files at root
    """
    snap: dict = {
        "jsonl_count": 0,
        "jsonl_uuids": [],
        "subdir_count": 0,
        "subdir_names": [],
        "memory_count": 0,
        "memory_files": [],
        "other_files": [],
        "partial": False,  # set True if any scan failed after retries; signals downstream that counts/lists may be incomplete
    }
    if not target_dir.exists() or not target_dir.is_dir():
        return snap

    jsonl_uuids: list[str] = []
    subdir_names: list[str] = []
    other_files: list[str] = []

    # Bounded retry for transient OSError (e.g. brief lock contention from
    # another process touching the dir, momentary permission flap). If all
    # retries fail, snap["partial"] = True so the operator sees the warning
    # and decides what to do — the operator is the authoritative gate.
    # Each closure invocation MUST clear its outer-scope lists first: if
    # attempt 1 appended N entries then raised, attempt 2 would otherwise
    # accumulate duplicates on top of attempt 1's partial results.
    def scan_target() -> None:
        jsonl_uuids.clear()
        subdir_names.clear()
        other_files.clear()
        for entry in os.scandir(target_dir):
            name = entry.name
            if entry.is_dir(follow_symlinks=False):
                if name == "memory":
                    continue
                subdir_names.append(name)
            elif entry.is_file(follow_symlinks=False):
                if name.startswith("."):
                    # hidden files (e.g. .DS_Store) filtered out
                    continue
                if name.endswith(".jsonl"):
                    if name == "history.jsonl":
                        continue
                    jsonl_uuids.append(name[: -len(".jsonl")])
                else:
                    other_files.append(name)

    if not _retry_scan(scan_target, label=str(target_dir)):
        snap["partial"] = True

    memory_dir = target_dir / "memory"
    memory_files: list[str] = []
    if memory_dir.exists() and memory_dir.is_dir():
        def scan_memory() -> None:
            memory_files.clear()
            for entry in os.scandir(memory_dir):
                if entry.is_file(follow_symlinks=False) and entry.name.endswith(".md"):
                    memory_files.append(entry.name)

        if not _retry_scan(scan_memory, label=str(memory_dir)):
            snap["partial"] = True

    jsonl_uuids.sort()
    subdir_names.sort()
    other_files.sort()
    memory_files.sort()

    snap["jsonl_count"] = len(jsonl_uuids)
    snap["jsonl_uuids"] = jsonl_uuids
    snap["subdir_count"] = len(subdir_names)
    snap["subdir_names"] = subdir_names
    snap["memory_count"] = len(memory_files)
    snap["memory_files"] = memory_files
    snap["other_files"] = other_files
    return snap


def snapshot_memory_md(target_dir: Path) -> Optional[str]:
    """Return sha256 hex digest of target/memory/MEMORY.md, or None if missing/unreadable.

    Bounded retry on OSError (permission flap, transient I/O error). Returns
    None after retries exhausted rather than crashing the migration. Operator
    sees the WARNING trace and decides whether to trust the snapshot.
    """
    memory_md = target_dir / "memory" / "MEMORY.md"
    if not memory_md.is_file():
        return None
    last_error: Optional[OSError] = None
    for attempt in range(1, 4):
        try:
            h = hashlib.sha256()
            with open(memory_md, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            if attempt > 1:
                print(f"  [retry succeeded on attempt {attempt}/3] MEMORY.md hash")
            return h.hexdigest()
        except OSError as e:
            last_error = e
            if attempt < 3:
                delay = 0.2 * attempt
                print(f"  WARNING: MEMORY.md hash failed on attempt {attempt}/3 ({e}); retrying after {delay:.1f}s")
                time.sleep(delay)
    print(f"  WARNING: all 3 attempts to hash MEMORY.md failed ({last_error}); snapshot will show 'not present'")
    return None


def _print_snapshot_block(label: str, snap: dict, memory_md_sha: Optional[str]) -> None:
    """Render a single BEFORE/AFTER snapshot as an ~80-col ASCII block."""
    bar = "═" * 78
    print()
    print(bar)
    print(f"  {label}")
    if snap.get("partial"):
        print("  ⚠ PARTIAL SNAPSHOT — one or more directory scans failed after retries; counts/lists may be incomplete.")
        print("    Your call as operator: investigate the OSError shown in the WARNING above (permission change,")
        print("    concurrent writer, disk error). The counts in this block may understate reality. You can run")
        print("    `verify_migration.py --verify` to get a structured comparison against the captured baseline —")
        print("    that's additional data to inform your decision, not a verdict that overrides your judgment.")
    print(bar)
    print(f"  jsonl files (root, excl. history.jsonl):  {snap['jsonl_count']}")
    if snap["jsonl_uuids"]:
        for u in snap["jsonl_uuids"]:
            print(f"    • {u[:8]}....jsonl")
    print(f"  subdirs (root, excl. memory/):            {snap['subdir_count']}")
    if snap["subdir_names"]:
        for d in snap["subdir_names"]:
            print(f"    • {d[:60]}/")
    print(f"  memory/*.md files:                        {snap['memory_count']}")
    if snap["memory_files"]:
        for m in snap["memory_files"]:
            print(f"    • memory/{m}")
    if memory_md_sha is None:
        print("  memory/MEMORY.md:                         (not present)")
    else:
        print(f"  memory/MEMORY.md sha256:                  {memory_md_sha[:16]}…")
    if snap["other_files"]:
        print(f"  other files at root:                      {len(snap['other_files'])}")
        for o in snap["other_files"]:
            print(f"    • {o}")
    print(bar)


def print_diff(
    before: dict,
    after: dict,
    memory_md_before: Optional[str],
    memory_md_after: Optional[str],
) -> None:
    """Print a visual diff between two snapshots from snapshot_target_dir.

    Uses ✓/✗/+/- glyphs in an ~80-col ASCII block. Designed to make
    real-run additions/removals jump out and to read as 'no changes'
    on a dry-run (where before == after).
    """
    bar = "═" * 78
    sep = "─" * 78

    before_jsonls = set(before.get("jsonl_uuids", []))
    after_jsonls = set(after.get("jsonl_uuids", []))
    jsonls_added = sorted(after_jsonls - before_jsonls)
    jsonls_removed = sorted(before_jsonls - after_jsonls)

    before_subdirs = set(before.get("subdir_names", []))
    after_subdirs = set(after.get("subdir_names", []))
    subdirs_added = sorted(after_subdirs - before_subdirs)
    subdirs_removed = sorted(before_subdirs - after_subdirs)

    before_mem = set(before.get("memory_files", []))
    after_mem = set(after.get("memory_files", []))
    mem_added = sorted(after_mem - before_mem)
    mem_removed = sorted(before_mem - after_mem)

    no_changes = not (
        jsonls_added or jsonls_removed
        or subdirs_added or subdirs_removed
        or mem_added or mem_removed
        or memory_md_before != memory_md_after
    )

    print()
    print(bar)
    print("  [DIFF]  before  →  after")

    # If either snapshot is partial, the set differences below are computed
    # against incomplete data — a file present in reality but missed by the
    # partial scan would appear as a false "removed" entry. Flag this so the
    # operator can interpret the display accordingly. Operator is the gate.
    before_partial = before.get("partial", False)
    after_partial = after.get("partial", False)
    if before_partial or after_partial:
        which = []
        if before_partial:
            which.append("BEFORE")
        if after_partial:
            which.append("AFTER")
        print(f"  ⚠ DIFF MAY BE INCOMPLETE — {' + '.join(which)} snapshot was partial; entries below could be missing or spuriously 'removed'.")
        print("    Your call: cross-check against `verify_migration.py --verify` output (additional data) before deciding what to do.")
    print(bar)

    if no_changes:
        print("  ✓ no changes  (target dir identical before vs after)")
        print(bar)
        return

    print("  jsonl files at root")
    print(f"  {sep}")
    if jsonls_added:
        print(f"  + added   ({len(jsonls_added)}):")
        for u in jsonls_added:
            print(f"      + {u}.jsonl")
    if jsonls_removed:
        print(f"  - removed ({len(jsonls_removed)}):")
        for u in jsonls_removed:
            print(f"      - {u}.jsonl")
    if not jsonls_added and not jsonls_removed:
        print("    (no jsonl changes)")

    print()
    print("  subdirs at root")
    print(f"  {sep}")
    if subdirs_added:
        print(f"  + added   ({len(subdirs_added)}):")
        for d in subdirs_added:
            print(f"      + {d}/")
    if subdirs_removed:
        print(f"  - removed ({len(subdirs_removed)}):")
        for d in subdirs_removed:
            print(f"      - {d}/")
    if not subdirs_added and not subdirs_removed:
        print("    (no subdir changes)")

    print()
    print("  memory/*.md files")
    print(f"  {sep}")
    if mem_added:
        print(f"  + added   ({len(mem_added)}):")
        for m in mem_added:
            print(f"      + memory/{m}")
    if mem_removed:
        print(f"  - removed ({len(mem_removed)}):")
        for m in mem_removed:
            print(f"      - memory/{m}")
    if not mem_added and not mem_removed:
        print("    (no memory file changes)")

    print()
    print("  memory/MEMORY.md")
    print(f"  {sep}")
    if memory_md_before is None and memory_md_after is None:
        print("    ✗ not present (neither before nor after)")
    elif memory_md_before is None and memory_md_after is not None:
        print("    + CREATED (was not present before)")
        print(f"      sha256: {memory_md_after[:16]}…")
    elif memory_md_before is not None and memory_md_after is None:
        print("    - REMOVED (was present before)")
    elif memory_md_before == memory_md_after:
        print("    ✓ unchanged (sha256 match)")
        print(f"      sha256: {memory_md_after[:16]}…")
    else:
        print("    ✗ CHANGED (sha256 mismatch)")
        print(f"      before: {memory_md_before[:16]}…")
        print(f"      after:  {memory_md_after[:16]}…")

    print(bar)


def build_machine_summary_line(*, transcripts_copied: int, transcripts_skipped: int,
                               tool_results_copied: int, memory_copied: int,
                               errors: int, dry_run: bool) -> str:
    """Build the greppable MACHINE_SUMMARY line (verify_migration.py's I2 oracle).
    Pure: returned as a string so main() can emit it even if the post-copy
    display crashes (BLOCKER 3)."""
    return "MACHINE_SUMMARY " + json.dumps({
        "transcripts_copied": transcripts_copied,
        "transcripts_skipped": transcripts_skipped,
        "tool_results_copied": tool_results_copied,
        "memory_copied": memory_copied,
        "errors": errors,
        "dry_run": dry_run,
    })


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--space",
        metavar="NAME_OR_UUID",
        help="Cowork project name or space UUID. Overrides COWORK_SPACE. "
             "Omit (or use --list) to list spaces.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available Cowork spaces and exit (works even if COWORK_SPACE is set).",
    )
    parser.add_argument(
        "--target",
        default=None,
        metavar="DIR",
        help="Claude Code project dir. Overrides COWORK_TARGET.",
    )
    parser.add_argument(
        "--workspace",
        default=None,
        metavar="DIR",
        help="Cowork workspace: <outer>/<inner> (relative to the standard base) "
             "or an absolute path. Overrides COWORK_WORKSPACE.",
    )
    parser.add_argument(
        "--memory-target",
        type=Path,
        metavar="DIR",
        help="Memory destination (default: <target>/memory/)",
    )
    parser.add_argument(
        "--create-target",
        action="store_true",
        help="Allow script to create --target if it does not exist.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview actions without copying any files.",
    )
    args = parser.parse_args()

    # ── Resolve config: CLI flag > OS env > .env > default/error ────────────────
    _dotenv = load_dotenv()
    workspace = resolve_workspace(args.workspace, _dotenv)
    if workspace is None:
        print("ERROR: Cowork workspace not set.", file=sys.stderr)
        print("  Copy demo.env -> .env and set COWORK_WORKSPACE, or pass --workspace.", file=sys.stderr)
        print(f"  Find it:  ls '{COWORK_BASE}'   (the UUID dir = <outer>)", file=sys.stderr)
        print(f"            ls '{COWORK_BASE}/<outer>'   (the UUID dir inside = <inner>)", file=sys.stderr)
        print("  Then set  COWORK_WORKSPACE=<outer>/<inner>", file=sys.stderr)
        sys.exit(1)
    args.workspace = workspace
    args.space = resolve(args.space, "COWORK_SPACE", _dotenv)
    _target = resolve(args.target, "COWORK_TARGET", _dotenv)
    args.target = Path(_target).expanduser() if _target else None

    workspace = args.workspace
    if not workspace.exists():
        print(f"ERROR: workspace not found: {workspace}", file=sys.stderr)
        sys.exit(1)

    spaces_file = workspace / "spaces.json"

    # ── List mode (--list, or no --space) ──────────────────────────────────────
    if args.list or not args.space:
        if spaces_file.exists():
            spaces = load_spaces(spaces_file)
        else:
            print(
                f"WARNING: spaces.json not found at {spaces_file}.\n"
                "  Space names cannot be resolved; showing raw IDs from sidecars.",
                file=sys.stderr,
            )
            spaces = {}
        _print_space_table(workspace, spaces)
        print("Use --space <name_or_uuid> --target <dir> to migrate a specific project.")
        return

    # ── --space mode ───────────────────────────────────────────────────────────
    if not args.target:
        print("ERROR: --target is required when --space is given.", file=sys.stderr)
        sys.exit(1)

    use_uuid_mode = _looks_like_uuid(args.space)

    if use_uuid_mode:
        # UUID mode: spaces.json optional (used only for display name)
        if spaces_file.exists():
            spaces = load_spaces(spaces_file)
        else:
            print(
                "NOTE: spaces.json not found; space display name will show as UUID.",
                file=sys.stderr,
            )
            spaces = {}
    else:
        # Name mode: spaces.json required to resolve the name
        if not spaces_file.exists():
            print(f"ERROR: spaces.json not found at {spaces_file}.", file=sys.stderr)
            print("  Space names cannot be resolved without spaces.json.", file=sys.stderr)
            print("  If the project was archived (removed from spaces.json),", file=sys.stderr)
            print("  pass the raw space UUID with --space to match sidecars directly.", file=sys.stderr)
            sys.exit(1)
        spaces = load_spaces(spaces_file)

    # ── Target validation ──────────────────────────────────────────────────────
    if not args.target.exists():
        if args.create_target:
            if args.dry_run:
                print(f"NOTE: --target does not exist. A real run would create it: {args.target}")
                print("      (dry-run changes nothing — keep --create-target on the real run.)")
            else:
                print(f"NOTE: --target does not exist; creating: {args.target}")
                args.target.mkdir(parents=True, exist_ok=True)
        else:
            print(f"ERROR: --target does not exist: {args.target}", file=sys.stderr)
            print("  Verify the path with:", file=sys.stderr)
            print("    ls ~/.claude/projects/ | grep <project-name>", file=sys.stderr)
            print("  Use --create-target to allow the script to create it.", file=sys.stderr)
            sys.exit(1)

    memory_target = args.memory_target or (args.target / "memory")

    # ── Sidecar scan ───────────────────────────────────────────────────────────
    sessions, parse_errors, empty_space_id_count, sidecar_stems = _scan_sidecars(workspace)

    # Warn about session dirs on disk that have no sidecar
    session_dirs_on_disk = {
        p.name for p in workspace.iterdir()
        if p.is_dir() and p.name.startswith("local_")
    }
    sidecar_missing = session_dirs_on_disk - sidecar_stems
    if sidecar_missing:
        print(
            f"WARNING: {len(sidecar_missing)} session dir(s) on disk have no sidecar — "
            "cannot be assigned to any project.",
            file=sys.stderr,
        )
        for s in sorted(sidecar_missing)[:5]:
            print(f"  {s}", file=sys.stderr)
        if len(sidecar_missing) > 5:
            print(f"  ... and {len(sidecar_missing) - 5} more", file=sys.stderr)

    if empty_space_id_count:
        print(
            f"WARNING: {empty_space_id_count} session(s) have a sidecar but no spaceId — "
            "unassigned, excluded from all projects.",
            file=sys.stderr,
        )

    # ── Space matching ─────────────────────────────────────────────────────────
    matched_space_id: str = ""
    matched_space_name: str = ""

    if use_uuid_mode:
        # Match directly against sidecar spaceIds
        ids_in_sidecars = {s["space_id"] for s in sessions if s["space_id"]}
        normalized = {sid.lower(): sid for sid in ids_in_sidecars}
        matched_space_id = normalized.get(args.space.lower(), "")
        if not matched_space_id:
            print(
                f"ERROR: space UUID '{args.space}' not found in any sidecar spaceId.",
                file=sys.stderr,
            )
            sys.exit(1)
        space_record = spaces.get(matched_space_id, {})
        matched_space_name = _space_display_name(space_record) or matched_space_id
    else:
        # Exact case-insensitive name match against spaces.json
        arg_lower = args.space.lower()
        matches = [
            (sid, _space_display_name(rec))
            for sid, rec in spaces.items()
            if _space_display_name(rec).lower() == arg_lower
        ]
        if len(matches) == 0:
            available = sorted(
                _space_display_name(rec)
                for rec in spaces.values()
                if _space_display_name(rec)
            )
            print(f"ERROR: no space named '{args.space}' (exact, case-insensitive).", file=sys.stderr)
            print("  Available space names:", file=sys.stderr)
            for n in available:
                print(f"    {n}", file=sys.stderr)
            sys.exit(1)
        if len(matches) > 1:
            print(
                f"ERROR: '{args.space}' matches {len(matches)} spaces (should be unique):",
                file=sys.stderr,
            )
            for sid, name in matches:
                print(f"  {name}  ({sid})", file=sys.stderr)
            print("  Use --space <uuid> to select one directly.", file=sys.stderr)
            sys.exit(1)
        matched_space_id, matched_space_name = matches[0]

    # ── Filter sessions for matched space ──────────────────────────────────────
    target_sessions = [s for s in sessions if s["space_id"] == matched_space_id]

    # ── Gather transcripts ─────────────────────────────────────────────────────
    all_transcripts: list[Path] = []
    session_transcript_map: dict[str, list[Path]] = {}
    for s in target_sessions:
        txs = find_transcripts_for_session(workspace, s["session_id"])
        session_transcript_map[s["session_id"]] = txs
        all_transcripts.extend(txs)

    memory_source = workspace / "spaces" / matched_space_id / "memory"

    # Surface silent exclusion: session dirs containing *.jsonl that were dropped
    # ONLY by the /.claude/projects/ path filter (Finding 8). copied=0 alone is
    # ambiguous; this names the cause.
    non_project_total = sum(
        _classify_session_jsonls(workspace / s["session_id"])["non_project"]
        for s in target_sessions
    )
    if non_project_total:
        print(
            f"WARNING: {non_project_total} *.jsonl file(s) in matched session dirs were "
            "excluded because they are not under a /.claude/projects/ path. If you expected "
            "transcripts here, the Cowork layout may differ from this tool's assumption.",
            file=sys.stderr,
        )

    # ── Pre-flight summary ─────────────────────────────────────────────────────
    if args.dry_run:
        print("=== DRY RUN — no files will be copied ===\n")

    print("[pre-flight]")
    print(f"  space:        {matched_space_name}")
    print(f"  space id:     {matched_space_id}")
    print(f"  sessions:     {len(target_sessions)}")
    print(f"  transcripts:  {len(all_transcripts)}")
    print(f"  target:       {args.target}")
    print(f"  memory src:   {memory_source}  ({'exists' if memory_source.exists() else 'not found'})")
    print(f"  memory dest:  {memory_target}")
    print()

    # ── BEFORE snapshot ────────────────────────────────────────────────────────
    # Captures target dir shape pre-copy so the user can visually diff against
    # the AFTER snapshot at the end of the run. On --dry-run this is the same
    # state as AFTER (nothing is copied) — the dry-run's would-copy preview is
    # provided by print_ascii_summary, not by print_diff.
    before = snapshot_target_dir(args.target)
    mem_md_before = snapshot_memory_md(args.target)
    _print_snapshot_block("[BEFORE TARGET STATE]", before, mem_md_before)
    print()

    # ── [1/3] Transcripts ──────────────────────────────────────────────────────
    print("[1/3] Transcripts")
    if not target_sessions:
        print("  No sessions found for this space.")
    else:
        for s in target_sessions:
            txs = session_transcript_map[s["session_id"]]
            title = s["title"] or "(untitled)"
            print(f"  session: {title!r}  ({len(txs)} transcript(s))")
        print()

    copied, skipped, errors = migrate_transcripts(all_transcripts, args.target, args.dry_run)
    print(f"  {len(copied)} copied, {len(skipped)} skipped, {len(errors)} errors\n")

    # ── [2/3] Tool-results ─────────────────────────────────────────────────────
    print("[2/3] Tool-results")
    tr_copied, tr_skipped, tr_errors = migrate_tool_results(all_transcripts, args.target, args.dry_run)
    if len(tr_copied) + len(tr_skipped) + len(tr_errors) == 0:
        print("  (none found)")
    else:
        print(f"  {len(tr_copied)} copied, {len(tr_skipped)} skipped, {len(tr_errors)} errors")
    print()

    # ── [3/3] Memory ───────────────────────────────────────────────────────────
    print("[3/3] Memory")
    print(f"  source: {memory_source}")
    print(f"  dest:   {memory_target}")
    mem_copied, mem_skipped, mem_errors = migrate_memory(memory_source, memory_target, args.dry_run)
    print(f"  {len(mem_copied)} copied, {len(mem_skipped)} skipped, {len(mem_errors)} errors\n")

    # ── Done ───────────────────────────────────────────────────────────────────
    print("Done.")
    if errors:
        print(f"\nWARNING: {len(errors)} transcript error(s) — check output above.")
    if tr_errors:
        print(f"\nWARNING: {len(tr_errors)} tool-results error(s) — check output above.")
    if mem_errors:
        print(f"\nWARNING: {len(mem_errors)} memory error(s) — check output above.")
    if mem_copied:
        print(f"\nOperator action (the script does NOT do this): update MEMORY.md in {memory_target}")
        print("  Add index entries for the migrated memory files.")

    print_ascii_summary(
        space_name=matched_space_name,
        dry_run=args.dry_run,
        target_sessions=target_sessions,
        session_transcript_map=session_transcript_map,
        copied_stems=set(copied),
        skipped_stems=set(skipped),
        error_stems=set(errors),
        tr_copied=tr_copied,
        tr_skipped=tr_skipped,
        tr_errors=tr_errors,
        mem_copied=mem_copied,
        mem_skipped=mem_skipped,
        mem_errors=mem_errors,
    )

    # ── AFTER snapshot + diff ──────────────────────────────────────────────────
    # Build the MACHINE_SUMMARY line FIRST (all counts are already known), then
    # render the display inside a guard so a crash in snapshot/diff (BLOCKER 3)
    # can never strip the I2 oracle from the teed output.
    summary_line = build_machine_summary_line(
        transcripts_copied=len(copied),
        transcripts_skipped=len(skipped),
        tool_results_copied=len(tr_copied),
        memory_copied=len(mem_copied),
        errors=len(errors) + len(tr_errors) + len(mem_errors),
        dry_run=bool(args.dry_run),
    )
    try:
        after = snapshot_target_dir(args.target)
        mem_md_after = snapshot_memory_md(args.target)
        _print_snapshot_block("[AFTER TARGET STATE]", after, mem_md_after)
        print_diff(before, after, mem_md_before, mem_md_after)
    except Exception as e:  # noqa: BLE001 — display is best-effort; summary must survive
        print(f"WARNING: post-copy display failed ({e}); the MACHINE_SUMMARY below is still authoritative.",
              file=sys.stderr)

    # ── Machine-readable summary (consumed by verify_migration.py's count cross-check) ──
    # Stable, greppable, emitted on success AND error (and even if the display above crashed).
    print(summary_line)

    if errors or tr_errors or mem_errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
