# migrate-cowork-sessions

> **Status:** v0.1 — works; validated against live data. **Caveat emptor:** macOS + Claude "Cowork" (local agent mode) only; read the dry-run output before the real run.

Migrate your historical **Cowork** (Claude desktop local-agent-mode) sessions — transcripts, tool-results, and memory — into a **Claude Code** project so they show up in your normal history. One-time, copy-only, safe to re-run.

## Requirements

- **macOS** with the Claude desktop app (Cowork / local agent mode) installed — sessions live under `~/Library/Application Support/Claude/local-agent-mode-sessions/`.
- **Python 3.9+** (the system `python3` on current macOS works).
- **No dependencies to install** — stdlib only. No `pip install`, no virtualenv. Clone and run.

**TL;DR:** Copies Cowork session transcripts + memory into a Claude Code project dir. One-time, copy-only, safe to re-run.

```bash
# See what spaces exist
python3 migrate_cowork_sessions.py --list

# Preview (no files changed)
python3 migrate_cowork_sessions.py --space <space-name> --target ~/.claude/projects/<target-dir> --dry-run

# Run it
python3 migrate_cowork_sessions.py --space <space-name> --target ~/.claude/projects/<target-dir>
```

(or set these once in `.env` — see `demo.env`)

Get `<target-dir>` with: `ls ~/.claude/projects/ | grep <project-name>`

## Setup (first run)

This tool reads your Cowork account location from a local `.env` (gitignored). Copy the template and fill in your values:

```bash
cp demo.env .env
# edit .env — see the comments in demo.env for how to find COWORK_WORKSPACE
```

`COWORK_WORKSPACE` is required; `COWORK_SPACE` / `COWORK_TARGET` are optional defaults (CLI flags override). See `demo.env` for the values to fill in.

---

One-time migration of historical Cowork session transcripts, tool-results, and memory into the Claude Code project directory. This consolidates the past — it does not sync the two tools going forward.

## How discovery works

Reads **sidecar** files (`local_*.json`) to find each session's `spaceId`, then filters to sessions belonging to the target project. (A *sidecar* is the small `local_<uuid>.json` metadata file that rides next to its session directory `local_<uuid>/`, like a motorcycle sidecar — one per session.)

Steps:
1. Read `spaces.json` to resolve space names → IDs
2. Glob `local_*.json` sidecars; extract `spaceId` and title from each
3. Match `--space` (name or UUID) to a space ID
4. Collect session dirs whose sidecar `spaceId` matches
5. For each session: `rglob *.jsonl`, exclude `/subagents/` and `audit.jsonl`
6. Copy transcripts, associated `<uuid>/tool-results/`, and memory files

Subagent transcripts are explicitly excluded. MEMORY.md is excluded from memory copy (it's an index file — copying it would overwrite the Claude Code project's own index).

Safe to re-run: all copies skip existing files.

## Prerequisites

1. **Quit Cowork entirely** (not just close individual sessions). Avoids file handle issues during copy.
2. **Verify the Claude Code target directory** by opening the project in Claude Code at least once, then running:
   ```bash
   ls ~/.claude/projects/ | grep <project-name>
   ```
   Pass the exact path as `--target`. **If the target path is wrong, the script exits with an error** (use `--create-target` to allow it to create the dir, but only after confirming the path encoding is correct).

## Usage

```bash
# Step 0: list available Cowork spaces
python3 migrate_cowork_sessions.py --list

# Step 1: dry run — verify session titles and counts match expectations
python3 migrate_cowork_sessions.py \
    --space <space-name> \
    --target ~/.claude/projects/<target-dir> \
    --dry-run

# Step 2: run for real
python3 migrate_cowork_sessions.py \
    --space <space-name> \
    --target ~/.claude/projects/<target-dir>

# Non-default Cowork workspace
python3 migrate_cowork_sessions.py \
    --space <space-name> \
    --target ~/.claude/projects/<target-dir> \
    --workspace ~/Library/Application\ Support/Claude/local-agent-mode-sessions/<org>/<account>

# Post-archive recovery (space removed from spaces.json — use UUID directly)
python3 migrate_cowork_sessions.py \
    --space <space-uuid> \
    --target ~/.claude/projects/<target-dir>
```

## All options

| Flag | Default | Description |
|---|---|---|
| `--space` | from `COWORK_SPACE` | Cowork project name (exact, case-insensitive) or space UUID. Omit (or use `--list`) to list spaces. |
| `--list` | off | List available Cowork spaces and exit |
| `--target` | from `COWORK_TARGET` | Claude Code project directory to copy into |
| `--workspace` | from `COWORK_WORKSPACE` (required) | Cowork workspace: `<outer>/<inner>` relative to the standard base, or an absolute path |
| `--memory-target` | `<target>/memory/` | Memory destination directory |
| `--create-target` | off | Allow script to create `--target` if it doesn't exist |
| `--dry-run` | off | Preview without copying |

## After running

1. **Verify** — check Claude Code's history panel for migrated sessions. Spot-check that at least one transcript opens correctly.
2. **Index memory** — add entries for the migrated Cowork memory files to `MEMORY.md` in the Claude Code memory directory so the auto-memory system indexes them.
3. **Archive** — archive the Cowork project via the Cowork UI (removes entry from `spaces.json`; session dirs on disk remain untouched). Only do this after verifying step 1.

## Known limitations (both versions)

- **Stale `cwd` paths** — migrated transcripts contain the original working directory paths from Cowork. Claude Code will show them but the paths may not resolve locally.
- **MEMORY.md requires manual update** — the script reminds you, but index entries must be added by hand.
- **Post-archive re-run** — if the Cowork project is archived (removed from `spaces.json`), use `--space <uuid>` to match sessions by UUID directly against sidecars.
- **Partial failure re-run** — safe; skip-existing makes re-runs idempotent.

## Why certain files are excluded

The migration script copies transcripts, tool-results, and memory files. It explicitly excludes three categories:

- **Subagent transcripts** (`agent-*.jsonl` under `subagents/` paths in each session dir) — internal workstreams Claude spawned during a session. Their results are already folded back into the main transcript via `tool_reference` pointers; copying them as standalone files would clutter Claude Code's history panel with context-less fragments. Invariant **I4** (clean delta) in `verify_migration.py` confirms none were added.
- **`audit.jsonl`** — Cowork's system-events log (init records with tool lists, MCP servers, model/version, plugins, agents, plus a flattened event stream). Cowork-specific format; not a Claude Code transcript; can't render in history view. Invariant **I4** confirms absence.
- **`.credentials.json`** — Cowork auth tokens at the workspace root. The script's discovery globs (`local_*.json` sidecars and `*.jsonl` transcripts under session dirs) never reach this file by design. Invariant **I4** verifies as defense-in-depth.

`MEMORY.md` in the source memory dir is also excluded from the memory copy — it's an index file specific to its project; copying it would overwrite Claude Code's own MEMORY.md.

## Companion verification script

`verify_migration.py` (also in this directory) captures pre-migration state and checks **6 property-based invariants (I1–I6)** against the post-migration state — no hardcoded fixtures; works for any space. Config comes from `.env` (or `--space`/`--target` flags). Pass the SAME `--target` to both phases.

```bash
# Before migration: capture baseline
python3 verify_migration.py --baseline --space "<SPACE_NAME>" --target <CLAUDE_PROJECT_DIR> --output-dir verification-reports/<ts>/

# Run the migration, capturing stdout — the MACHINE_SUMMARY line is invariant I2's oracle:
python3 migrate_cowork_sessions.py --space "<SPACE_NAME>" --target <CLAUDE_PROJECT_DIR> 2>&1 | tee verification-reports/<ts>/migration-output.txt

# After migration: check invariants (--baseline-dir is the REPORTS dir, not baseline/)
python3 verify_migration.py --verify --space "<SPACE_NAME>" --target <CLAUDE_PROJECT_DIR> --baseline-dir verification-reports/<ts>/
```

Exit codes: `0` PASS (all 6 invariants), `1` PARTIAL PASS (you verified a dry-run — not a real verification; run the real migration and re-verify), `2` FAIL. A PASS confirms the migration was *consistent + clean*, NOT that the *right* sessions were selected — spot-check one session in the Claude Code UI.

For the full operator runbook (sequence, who-runs-what, recovery on FAIL), see `cowork-migration-runbook.md` (this directory). For methodology + per-invariant limits, see `TESTING.md`.

## After verification passes — MEMORY.md index update

The migration copies new memory files into `<target>/memory/` but does NOT modify `<target>/memory/MEMORY.md` (the index). Without index entries, Claude Code's auto-memory system may not surface the new files in future sessions — they exist on disk but aren't discovered.

**Tradeoff:**
- Skip the update: files exist, won't be auto-loaded. Acceptable for low-impact archived context.
- Do the update: open each migrated file, read its content, write a one-line index entry to `MEMORY.md`. Claude can do this on request. Recommended for any memory files you want surfaced in future sessions.

**Sequence matters.** Invariant **I5** asserts `MEMORY.md` was unchanged by the migration script (sha256 matches baseline). Updating `MEMORY.md` BEFORE running `--verify` would cause I5 to falsely FAIL. Order: run `--verify` first (I5 PASS = migration was non-destructive on MEMORY.md), THEN update intentionally.
