# migrate-cowork-sessions

> **Status:** v0.1 — works; validated against live data. **Caveat emptor:** macOS + Claude "Cowork" (local agent mode) only; read the dry-run output before the real run.

Migrate your historical **Cowork** (Claude desktop local-agent-mode) sessions — transcripts, tool-results, and memory — into a **Claude Code** project so they show up in your normal history. One-time, copy-only, safe to re-run.

## Requirements

- **macOS** with the Claude desktop app (Cowork / local agent mode) installed — sessions live under `~/Library/Application Support/Claude/local-agent-mode-sessions/`.
- **Python 3.9+** (the system `python3` on current macOS works).
- **No dependencies to install** — stdlib only. No `pip install`, no virtualenv.

## Getting the tool

This tool is one folder inside the `local-tools` repo. Clone the repo (or copy the
`tools/migrate-cowork-sessions/` folder), then **work from inside that folder** — the scripts
read their config from a `.env` that lives *beside them*, so every command below assumes you've:

```bash
cd tools/migrate-cowork-sessions
```

These are plain Python CLI scripts — run them in **any terminal**; you do *not* need Claude Code open. (The companion runbook uses a Claude Code session for an integrated verify/assess flow, but that's optional.)

**TL;DR:** Copies Cowork session transcripts + memory into a Claude Code project dir. One-time, copy-only, safe to re-run. Run all commands from the tool folder above, after creating your `.env` (see *Setup*).

```bash
# See what spaces exist
python3 migrate_cowork_sessions.py --list
# ^ copy a Space name from the table; quote it if it contains spaces

# Preview (no files changed)
python3 migrate_cowork_sessions.py --space "<space-name>" --target ~/.claude/projects/<target-dir> --dry-run

# Run it
python3 migrate_cowork_sessions.py --space "<space-name>" --target ~/.claude/projects/<target-dir>
```

(or set `--space` / `--target` once in `.env` — see `demo.env`)

**Finding `<target-dir>`** — Claude Code stores each project under an *encoded* directory name
(your project's filesystem path with `/` turned into `-`). The directory exists only after you've
opened that project in Claude Code at least once (or you pass `--create-target` — see *Prerequisites*).
List them and use the **whole** name:

```bash
ls ~/.claude/projects/ | grep <keyword-from-your-project-name>
#   e.g. prints:   -Users-alice-dev-my-project
#   then pass the full path:
#     --target ~/.claude/projects/-Users-alice-dev-my-project
```

## Setup (first run)

This tool reads your Cowork account location from a local `.env` (gitignored). Copy the template and fill in your values:

```bash
cp demo.env .env
# edit .env — see the comments in demo.env for how to find COWORK_WORKSPACE
```

`COWORK_WORKSPACE` is required; `COWORK_SPACE` / `COWORK_TARGET` are optional defaults (CLI flags override). See `demo.env` for the values to fill in.

---

One-time migration of historical Cowork session transcripts, tool-results, and memory into the Claude Code project directory. This consolidates the past — it does not sync the two tools going forward.

## Prerequisites

1. **Quit Cowork entirely** (not just close individual sessions). Avoids file handle issues during copy.
2. **Create + verify the Claude Code target directory.** Claude Code creates a project's directory the first time you open that project in it — so open the project in Claude Code once, then list the encoded dir name:
   ```bash
   ls ~/.claude/projects/ | grep <keyword-from-your-project-name>
   ```
   Pass the **full** path (e.g. `~/.claude/projects/-Users-alice-dev-my-project`) as `--target`. **If `--target` doesn't exist, the script exits with an error** — either open the project in Claude Code first (recommended, so the encoded name is correct), or pass `--create-target` to let the script create it (only after you've confirmed the encoded path is right).

## How discovery works

Reads **sidecar** files (`local_*.json`) to find each session's `spaceId`, then filters to sessions belonging to the target project. (A *sidecar* is the small `local_<uuid>.json` metadata file next to each session directory `local_<uuid>/` — one per session.)

Steps:
1. Read `spaces.json` to resolve space names → IDs
2. Glob `local_*.json` sidecars; extract `spaceId` and title from each
3. Match `--space` (name or UUID) to a space ID
4. Collect session dirs whose sidecar `spaceId` matches
5. For each session, `rglob *.jsonl` and **keep a file only if all of these hold** (failing any one skips it):
   - its path contains `/.claude/projects/` (the location Claude wrote transcripts to). A `.jsonl` elsewhere in the session dir is excluded and counted as `non_project` — and the script prints a warning — so a layout mismatch is never silent.
   - it is **not** under a `/subagents/` path
   - it is **not** named `audit.jsonl`
   - it is **not** an `agent-*.jsonl` (a subagent transcript). Such a file under `/.claude/projects/` is excluded **and counted** (the script warns), matching verifier invariant **I4**.
6. Copy the kept transcripts, each transcript's `<uuid>/tool-results/`, and the space's memory files

`MEMORY.md` is excluded from the memory copy (it's an index file — copying it would overwrite the Claude Code project's own index).

Safe to re-run: all copies skip existing files (a 0-byte file left by an interrupted prior copy is re-copied, not skipped, so a re-run heals it).

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
| `--space` | from `COWORK_SPACE` | Cowork project name (matched in full, case-insensitively — **quote it if it contains spaces**: `--space "My Project"`) or a space UUID. Omit (or use `--list`) to list spaces. |
| `--list` | off | List available Cowork spaces and exit |
| `--target` | from `COWORK_TARGET` | Claude Code project directory to copy into |
| `--workspace` | from `COWORK_WORKSPACE` (required) | Cowork workspace: `<outer>/<inner>` relative to the standard base, or an absolute path |
| `--memory-target` | `<target>/memory/` | Memory destination directory |
| `--create-target` | off | Allow script to create `--target` if it doesn't exist |
| `--dry-run` | off | Preview without copying |

## What the output looks like

`--list` prints a table of spaces (name, session count, space ID) — pick the one you want to migrate:

```
Available Cowork spaces in:
  /Users/alice/Library/Application Support/Claude/local-agent-mode-sessions/<outer>/<inner>

  Space name                                 Sessions  Space ID
  ------------------------------------------ --------  ------------------------------------
  My Project                                        7  11111111-1111-1111-1111-111111111111
  Scratch                                           2  22222222-2222-2222-2222-222222222222
```

A `--dry-run` previews exactly what a real run would copy, writing nothing: a `[BEFORE]` snapshot of the target, a per-session list of what *would* copy, an ASCII summary, then an unchanged `[AFTER]`/`[DIFF]` (since nothing changed). The last line is the machine-readable summary the verifier reads:

```
MACHINE_SUMMARY {"transcripts_copied": 7, "transcripts_skipped": 0, "tool_results_copied": 12, "memory_copied": 3, "errors": 0, "dry_run": true}
```

The dry-run counts should match the real run; `errors` must be `0`, and `dry_run` is `true` only on a preview. (All values above are illustrative placeholders.)

## After running

1. **Verify** — check Claude Code's history panel for migrated sessions. Spot-check that at least one transcript opens correctly.
2. **Index memory** — Claude Code auto-loads context from the files listed in `<target>/memory/MEMORY.md` (the index; each line is a relative path + a short description). The migration copies the memory *files* but deliberately does NOT touch `MEMORY.md`, so add one index line per migrated file or they won't be surfaced in future sessions. **Do this AFTER you run `--verify`** (the runbook's step 5) — updating `MEMORY.md` before verifying trips invariant **I5** and produces a false FAIL. Format + sequencing in *After verification passes* below.
3. **Archive** — archive the Cowork project via the Cowork UI (removes entry from `spaces.json`; session dirs on disk remain untouched). Only do this after verifying step 1.

## Known limitations (both versions)

- **Stale `cwd` paths** — migrated transcripts contain the original working directory paths from Cowork. Claude Code will show them but the paths may not resolve locally.
- **MEMORY.md requires manual update** — the script reminds you, but index entries must be added by hand.
- **Post-archive re-run** — if the Cowork project is archived (removed from `spaces.json`), use `--space <uuid>` to match sessions by UUID directly against sidecars.
- **Partial failure re-run** — safe; skip-existing makes re-runs idempotent (a 0-byte file from an interrupted copy is re-copied, not skipped).
- **Tool-results completeness isn't independently verified** — I2 cross-checks transcript counts, but no invariant cross-checks how many `tool-results/` files were copied. If a path assumption ever mismatched, the verdict could still be PASS with tool-results missing. Spot-check that a migrated session's tool calls render.
- **Memory copy is non-recursive** — only `*.md` at the top level of the space's `memory/` is copied; files in subdirectories of `memory/` are not. (Cowork's memory dir is flat in practice; flagged for completeness.)

## Why certain files are excluded

The migration script copies transcripts, tool-results, and memory files. It explicitly excludes three categories:

- **Subagent transcripts** — any file under a `/subagents/` path, **and** any `agent-*.jsonl` anywhere under `/.claude/projects/` (not only those under `/subagents/`). These are internal workstreams Claude spawned during a session; their results are already folded back into the main transcript via `tool_reference` pointers, so copying them as standalone files would clutter Claude Code's history panel with context-less fragments. Invariant **I4** (clean delta) in `verify_migration.py` confirms none were added.
- **`audit.jsonl`** — Cowork's system-events log (init records with tool lists, MCP servers, model/version, plugins, agents, plus a flattened event stream). Cowork-specific format; not a Claude Code transcript; can't render in history view. Invariant **I4** confirms absence.
- **Credentials** (e.g. `.credentials.json`) — Cowork auth tokens at the workspace root. The realistic vector is safe: `.credentials.json` lives at the workspace root (not under a session dir) and isn't a `.jsonl`, so discovery never globs it. As belt-and-suspenders, the migrate side **also** skips any `*credentials*` file it encounters under `/.claude/projects/`, and invariant **I4** flags any newly-added file whose name contains `credentials` (case-insensitive) — so the copier can't copy what the checker forbids.

`MEMORY.md` in the source memory dir is also excluded from the memory copy — it's an index file specific to its project; copying it would overwrite Claude Code's own MEMORY.md.

## Companion verification script

`verify_migration.py` (also in this directory) captures pre-migration state and checks **6 property-based invariants (I1–I6)** against the post-migration state — no hardcoded fixtures; works for any space. Config comes from `.env` (or `--space`/`--target` flags). Pass the SAME `--target` to both phases. (`<ts>` below is any label you pick to group one run's reports under `verification-reports/` — e.g. the output of `date +%Y%m%d-%H%M%S`; the operator runbook sets it once and reuses it across steps. The `tee` in the middle command is **required** — its `MACHINE_SUMMARY` line is invariant I2's oracle.)

```bash
# Before migration: capture baseline
python3 verify_migration.py --baseline --space "<SPACE_NAME>" --target <CLAUDE_PROJECT_DIR> --output-dir verification-reports/<ts>/

# Run the migration, capturing stdout — the MACHINE_SUMMARY line is invariant I2's oracle:
python3 migrate_cowork_sessions.py --space "<SPACE_NAME>" --target <CLAUDE_PROJECT_DIR> 2>&1 | tee verification-reports/<ts>/migration-output.txt

# After migration: check invariants (--baseline-dir is the REPORTS dir, not baseline/)
python3 verify_migration.py --verify --space "<SPACE_NAME>" --target <CLAUDE_PROJECT_DIR> --baseline-dir verification-reports/<ts>/
```

If you skip the `tee` (or save it to a path other than the one `--baseline-dir` points at), `--verify` FAILs with *"no MACHINE_SUMMARY found"* — that captured stdout is I2's only oracle.

Exit codes: `0` PASS (all 6 invariants), `1` PARTIAL PASS (you verified a dry-run — not a real verification; run the real migration and re-verify), `2` FAIL. A PASS confirms the migration was *consistent + clean*, NOT that the *right* sessions were selected — spot-check one session in the Claude Code UI.

For the full operator runbook (sequence, who-runs-what, recovery on FAIL), see `cowork-migration-runbook.md` (this directory). For methodology + per-invariant limits, see `VERIFICATION.md`.

## After verification passes — MEMORY.md index update

The migration copies new memory files into `<target>/memory/` but does NOT modify `<target>/memory/MEMORY.md` (the index). Without index entries, Claude Code's auto-memory system may not surface the new files in future sessions — they exist on disk but aren't discovered.

**Tradeoff:**
- Skip the update: files exist, won't be auto-loaded. Acceptable for low-impact archived context.
- Do the update: open each migrated file, read its content, write a one-line index entry to `MEMORY.md`. Claude can do this on request. Recommended for any memory files you want surfaced in future sessions.

**Sequence matters.** Invariant **I5** asserts `MEMORY.md` was unchanged by the migration script (sha256 matches baseline). Updating `MEMORY.md` BEFORE running `--verify` would cause I5 to falsely FAIL. Order: run `--verify` first (I5 PASS = migration was non-destructive on MEMORY.md), THEN update intentionally.
