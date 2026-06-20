# Cowork Migration Verification — Runbook

Operator runbook for migrating one Cowork space into a Claude Code project dir and verifying the result. Audience: the human operating the migration + the Claude assisting with assessment. Stand-alone — no prior setup is assumed beyond having the tool and Cowork installed.

For the test methodology (what each invariant checks + its limits), see `TESTING.md`. For script usage, see `README.md`.

## Placeholders

Fill these in for your environment (the tools read several from `.env` — see `demo.env`):

- `<SPACE_NAME>` — your Cowork space name (the `--space` value; or `COWORK_SPACE` in `.env`).
- `<CLAUDE_PROJECT_DIR>` — your Claude Code project dir, e.g. `~/.claude/projects/<encoded-path>` (or `COWORK_TARGET` in `.env`).
- `<CLAUDE_PROJECT_DIRNAME>` — just the final segment of `<CLAUDE_PROJECT_DIR>` (the encoded `-Users-…` dir name); used only by the optional backup-restore in Recovery.
- `<TOOL_DIR>` — the directory holding `migrate_cowork_sessions.py` (and `verify_migration.py`, `.env`).

## Setup: `.env` (once)

Both `migrate_cowork_sessions.py` and `verify_migration.py` read config from a `.env` that lives **beside the scripts** (in `<TOOL_DIR>`) — NOT from your current working directory. Create it once:

```bash
cd <TOOL_DIR> && cp demo.env .env
# edit .env: set COWORK_WORKSPACE (required); COWORK_SPACE / COWORK_TARGET optional (CLI flags override)
```

If you ever move the tool, `.env` must move with the scripts or config resolution fails.

## Transparency rule (BLOCKING for Claude)

**Claude MUST print raw command output BEFORE any interpretation.** No summarization-only responses. Every Bash command Claude runs as part of verification must show its complete unedited output first; analysis comes after. This is non-negotiable.

## Kickoff prompt for fresh Claude sessions

If you (the operator) open a NEW Claude Code session to handle verify/assess or the MEMORY.md update, paste this as your first message:

```
We're resuming the Cowork → Claude Code migration.

FIRST: Read this tool's cowork-migration-runbook.md end-to-end — especially the Transparency rule (BLOCKING) and the Order of operations. The runbook is the complete, self-contained source for verification + recovery; do not consult other docs during assessment.

After you've read it: I'll tell you which step we're on and paste the relevant command output. You assess per the runbook — no shortcuts, no summarization without raw output first.

If anything in the runbook conflicts with your default behavior, the runbook wins.
```

## Model recommendation

- **Baseline → migrate → verify (operator runs commands via `!`):** a fast/cheap model is fine — mechanical work; Claude observes.
- **Assessing the verdict (step 6):** PASS is mechanical. On **FAIL**, switch to your most capable model — recovery proposals can be destructive (restore from backup, selective deletion). (PARTIAL PASS only means a dry-run was verified — benign; no recovery.)

## Operator preconditions

- **Cowork is fully quit** (whole app, not just sessions) — avoids file-handle races during copy.
- **`.env` exists** in `<TOOL_DIR>` with `COWORK_WORKSPACE` set (see Setup).
- **Pass the SAME `--target` to BOTH `--baseline` and `--verify`** (or set `COWORK_TARGET` in `.env` so both inherit it). Different targets → the delta is computed against the wrong dir and I2 FAILs spuriously.
- **Do not open or relaunch any other Claude Code session in `<CLAUDE_PROJECT_DIR>` between step 3 (`--baseline`) and step 5 (`--verify`)** — including closing/reopening VS Code or the Claude Code window. A relaunch appends a new `<uuid>.jsonl` to the target root, inflating the measured delta → **I2** reports `added > copied` (flagged as likely external churn). The single session running this runbook is fine.
- **Target must be on a LOCAL, non-synced filesystem.** `~/.claude/projects/` normally is. If your target lives under iCloud Drive (`~/Library/Mobile Documents/…`), Dropbox, or another sync provider, the verifier can read a **stale directory view** (sync lag between `shutil.copy2` finishing and the file appearing in a later `os.scandir`), producing a spurious I1/I2/I3 PASS *or* FAIL. If you must migrate into a synced dir, pause syncing (or wait for it to settle) before running `--verify`.

## Order of operations

Run these in order. Steps marked `(via !)` are shell commands the operator runs from Claude Code's `!` prompt (each `!` is a fresh subshell, which is why the timestamp is read from a file, not an env var). Steps marked OPTIONAL can be skipped.

**0a. Open a fresh Claude Code session in `<TOOL_DIR>`** *(USER)* — one session for the whole runbook.

**0b. Paste the kickoff prompt** (above) as the first message *(USER)* — so Claude reads the runbook + the BLOCKING transparency rule before any work.

**1. Quit Cowork entirely** (whole app) *(USER)* — avoids file-handle issues during the copy.

**2a. Capture one shared timestamp** *(USER via `!`)* — every later command reads it via `$(cat /tmp/cowork-ts.txt)`; survives across `!` subshells.

```bash
date +%Y%m%d-%H%M%S > /tmp/cowork-ts.txt && cat /tmp/cowork-ts.txt
```

**2b. (OPTIONAL) Make a rollback backup** *(USER via `!`)* — optional operator safety; the verifier does NOT require or read it. Skip if you don't want one. The `mkdir -p` + no-trailing-slash form produces `<backup>/<CLAUDE_PROJECT_DIRNAME>/…`, which the Recovery `mv` assumes.

```bash
mkdir -p ~/.claude/backups/pre-cowork-migration-<SPACE_NAME>-$(cat /tmp/cowork-ts.txt)/ \
  && cp -r <CLAUDE_PROJECT_DIR> ~/.claude/backups/pre-cowork-migration-<SPACE_NAME>-$(cat /tmp/cowork-ts.txt)/
```

**3. Capture the baseline** *(USER via `!`)* — snapshots pre-migration state to `verification-reports/<ts>/baseline/`. The target need NOT exist yet (an empty baseline is captured; the migration creates it). Aborts only if `--output-dir` already exists.

```bash
cd <TOOL_DIR> && python3 verify_migration.py --baseline \
  --space "<SPACE_NAME>" --target <CLAUDE_PROJECT_DIR> \
  --output-dir verification-reports/$(cat /tmp/cowork-ts.txt)/
```

**3b. (OPTIONAL) Dry-run preview** *(USER via `!`)* — same plumbing as step 4, no files copied. Shows `[BEFORE]` target state, `[1/3]/[2/3]/[3/3]` what WOULD copy, an ASCII summary, then `[AFTER]`/`[DIFF]`. (On a dry-run, `[AFTER]` == `[BEFORE]` and `[DIFF]` shows "no changes" — nothing is copied; the **ASCII summary** is the prediction of what the real run will do.) **Note the counts** — they should match step 4.

```bash
cd <TOOL_DIR> && python3 migrate_cowork_sessions.py \
  --space "<SPACE_NAME>" --target <CLAUDE_PROJECT_DIR> --dry-run \
  2>&1 | tee verification-reports/$(cat /tmp/cowork-ts.txt)/dry-run-output.txt
```

**4. Run the migration** *(USER via `!`)* — **the `tee` is load-bearing**: the `MACHINE_SUMMARY {…}` line in this capture is I2's independent oracle. If you skip the tee (or don't save stdout), I2 FAILs with "no MACHINE_SUMMARY found."

```bash
cd <TOOL_DIR> && python3 migrate_cowork_sessions.py \
  --space "<SPACE_NAME>" --target <CLAUDE_PROJECT_DIR> \
  2>&1 | tee verification-reports/$(cat /tmp/cowork-ts.txt)/migration-output.txt
```

**5. Verify** *(USER via `!`)* — runs invariants I1–I6, writes `summary.json` + per-invariant `I#.txt`. `--baseline-dir` is the **reports dir** (parent of `baseline/`), not `baseline/` itself; it auto-finds `migration-output.txt` there (or pass `--migration-output <file>`). Exit 0/1/2 = PASS/PARTIAL/FAIL.

```bash
cd <TOOL_DIR> && python3 verify_migration.py --verify \
  --space "<SPACE_NAME>" --target <CLAUDE_PROJECT_DIR> \
  --baseline-dir verification-reports/$(cat /tmp/cowork-ts.txt)/
```

**6. Claude assesses** *(CLAUDE)* — reads `summary.json` and reports the verdict (see "How Claude reports the verdict" below).

**7. UI spot-check** *(USER)* — **the selection check.** Open one migrated session in the Claude Code history panel and confirm it loads. A PASS verdict proves the migration was *consistent + clean*, NOT that the *right* sessions were chosen — only you can confirm that. Pick a UUID from the migration ASCII summary, or via `ls <CLAUDE_PROJECT_DIR>/*.jsonl`.

**8. Update MEMORY.md** *(CLAUDE, on USER request)* — Claude reads each migrated memory file and appends one-line index entries to `<CLAUDE_PROJECT_DIR>/memory/MEMORY.md`, matching the existing format. **Must run AFTER step 5** (I5 verifies the migration left MEMORY.md unchanged; this is the intentional human-directed edit).

**9. Archive the `<SPACE_NAME>` Cowork project** *(USER)* — **two passes, in order:** (1) archive each **session conversation** individually first, THEN (2) archive the **project** overall. Cowork's project-archive does NOT cascade to its sessions — archiving the project alone leaves orphaned session entries. Only do this after step 7 succeeds (archiving is hard to undo).

**10. (OPTIONAL) Delete the step-2b backup** *(USER via `!`)* — only if you made one, and only after step 7.

```bash
rm -rf ~/.claude/backups/pre-cowork-migration-<SPACE_NAME>-$(cat /tmp/cowork-ts.txt)/
```

## Critical sequencing

- **I5 → step 8 (NOT reversed):** run step 5 (verify) BEFORE step 8, so any I5 FAIL points unambiguously at the migration script, not your MEMORY.md edit.
- **Step 5 → step 7 → step 9:** don't archive Cowork before the UI spot-check confirms transcripts open.
- **Step 7 → step 10:** don't delete the backup until the spot-check confirms the migration is good.

## How Claude reports the verdict (step 6)

After USER runs `--verify`, USER asks Claude to assess. Claude:

1. Runs `cat <TOOL_DIR>/verification-reports/$(cat /tmp/cowork-ts.txt)/summary.json` and prints it verbatim. (If `$(cat /tmp/cowork-ts.txt)` isn't in shell env, USER pastes the timestamp, or Claude finds the latest via `ls -t <TOOL_DIR>/verification-reports/ | head -1`.)
2. Prints the verdict on one line: `Verdict: PASS` / `Verdict: PARTIAL PASS` / `Verdict: FAIL`, plus the `verdict_note`.
3. If FAIL: reads BOTH `critical_failures` AND `critical_skipped` from `summary.json`, lists each failing/skipped invariant ID, and `cat`s its raw `I#.txt`.
4. Recommends the next step per the table below.

`summary.json` keys: `verdict`, `verdict_note`, `timestamp`, `tests[]` (`{id, criticality, status, raw_output_path}`), `critical_failures`, `critical_skipped`, `migration_errors`. All 6 invariants are CRITICAL; there is no SECONDARY tier. `migration_errors` is the count from the migration's `MACHINE_SUMMARY` (copy errors across transcripts + tool-results + memory) — **any value > 0 forces a FAIL verdict even if all six invariants pass**, and is never masked by a dry-run PARTIAL PASS.

## Verdict-driven recommendations

| Verdict | Meaning | Recommended next step |
|---------|---------|----------------------|
| **PASS** | All 6 invariants passed. | Proceed to step 7 (UI spot-check). **Caveat:** PASS confirms the migration is *consistent with its own report and clean* — it does NOT prove the *right* sessions were selected. Step 7 is your selection check; do not skip it before archiving (step 9). |
| **PARTIAL PASS** | The migration output was a **dry-run** — structural invariants are vacuous (nothing copied). **Only** reported when no real failure/error is present; a real CRITICAL failure or `migration_errors > 0` overrides it to FAIL (an accidental dry-run can never hide a real problem). | Not a real verification. Run the real migration (step 4, no `--dry-run`, teed to `migration-output.txt`) and re-verify (step 5). |
| **FAIL** | A CRITICAL invariant failed, OR `migration_errors > 0` (the migration reported copy errors), OR I2 had no `MACHINE_SUMMARY` oracle. | STOP. Do NOT proceed to step 7 or archive. See "Recovery on FAIL". |

## Recovery on FAIL

**Claude does NOT re-run the migration automatically.** It may propose actions after reading the failing `I#.txt`, but execution requires explicit USER confirmation.

- **I2 FAIL "no MACHINE_SUMMARY found" → re-TEE, don't just re-run.** The oracle is missing because the migration's stdout wasn't captured. Re-running won't help (it's idempotent → skip-existing → `copied=0`). Fix: re-run the migration capturing stdout to `migration-output.txt`, OR point `--migration-output <file>` at wherever the real stdout was saved, then re-verify.
- **I2 FAIL `added > copied` (external churn).** A concurrent session wrote to the target between baseline and verify. Re-baseline with no other sessions open, then re-migrate/verify.
- **Re-run migration script.** Idempotent — skip-existing protects already-copied files. **A 0-byte destination (interrupted prior copy) is NOT skipped — the re-run re-copies it**, so an I3 FAIL on an empty `.jsonl` self-heals on re-run; no manual cleanup needed. (A *partially-written but non-empty* file would still be skipped — if I3 flags a malformed non-empty transcript, delete that file from the target, then re-run.) Claude must NOT re-run without USER saying "yes, re-run."
- **Selectively delete bad files from target.** Cowork sources are read-only from the script's perspective. Safe to remove from target and re-run.
- **Full restore from the optional pre-migration backup** (only if you made one in step 2b). `rm -rf <CLAUDE_PROJECT_DIR>/` then `mv ~/.claude/backups/pre-cowork-migration-<SPACE_NAME>-<ts>/<CLAUDE_PROJECT_DIRNAME>/ ~/.claude/projects/`. **Destructive — USER confirms first.**
- **Restore MEMORY.md only** (if I5 FAILs and you made a backup): `cp ~/.claude/backups/pre-cowork-migration-<SPACE_NAME>-<ts>/<CLAUDE_PROJECT_DIRNAME>/memory/MEMORY.md <CLAUDE_PROJECT_DIR>/memory/MEMORY.md`. **Destructive — USER confirms first.**

When interpreting verify output (step 6) and deciding recovery, Claude works ONLY from this runbook + `summary.json` + the per-invariant `I#.txt` files.

## What an I2 PASS does and does NOT prove

I2 cross-checks the migrate script's *reported* copy count against the *measured* new-`.jsonl` delta — a **consistency** check. It catches count-changing drops/dups, but it CANNOT detect a no-op (nothing copied), a drop masked by skip-existing, or a wrong-but-valid session selection. No invariant here certifies *which* sessions were migrated — the step-7 UI spot-check is that check. See `TESTING.md` for the full limits.

## What this runbook does NOT cover

- Per-invariant acceptance criteria + methodology — see `TESTING.md`.
- Migration-script flags — see `README.md`.
- Architecture / design rationale — see `plans/generic-cowork-migration/cowork-migration-project-agnostic-design.md` and `…-verify-suite-design.md`.
