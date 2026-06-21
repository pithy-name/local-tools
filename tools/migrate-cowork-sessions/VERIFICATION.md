# Migration Verification — Test Spec (property-based)

Test specification for `verify_migration.py`. Audience: a reviewer evaluating the methodology, or a contributor modifying the verifier.

For execution sequence (who runs what), see `cowork-migration-runbook.md`. For migration-script usage, see `README.md`.

## Scope

`verify_migration.py` checks that `migrate_cowork_sessions.py` produced a clean copy-only migration into the Claude Code target dir AND left the Cowork sources untouched — **for any space**, with **no hardcoded fixtures**. It asserts *properties* of the migration, never an enumerated "expected" set of transcript UUIDs.

Two phases, baseline-driven:
- `--baseline` (pre-migration) snapshots target + Cowork-source state into `<output-dir>/baseline/`.
- `--verify` (post-migration) compares live state to the baseline files and checks 6 invariants.

The comparison source is always the runtime baseline file, never a value written into this spec. Config (`workspace` / `target` / `space`) resolves from CLI flags > OS env > `.env` (see `demo.env`).

## Run order

1. **Quit Cowork** entirely (no file-handle races during copy).
2. `python3 verify_migration.py --baseline --space <SPACE> --target <CLAUDE_PROJECT_DIR> --output-dir <REPORTS_DIR>` — writes `<REPORTS_DIR>/baseline/`. The target need not exist yet (an empty baseline is captured; the migration creates it).
3. Run the migration and **capture stdout**: `python3 migrate_cowork_sessions.py --space <SPACE> --target <CLAUDE_PROJECT_DIR> 2>&1 | tee <REPORTS_DIR>/migration-output.txt`. The captured `MACHINE_SUMMARY {…}` line is I2's oracle.
4. `python3 verify_migration.py --verify --space <SPACE> --target <CLAUDE_PROJECT_DIR> --baseline-dir <REPORTS_DIR>` — runs I1–I6, writes `summary.json` + per-invariant `I#.txt`.

**Two gotchas (both cause a misleading result if ignored):**
- **`--baseline-dir` is the REPORTS dir** (the parent containing `baseline/` + `migration-output.txt`), *not* the `baseline/` subdir. `--migration-output <FILE>` overrides the default `<REPORTS_DIR>/migration-output.txt`.
- **Pass the SAME target to baseline AND verify** (or set `COWORK_TARGET` in `.env` so both inherit it). If `--baseline` and `--verify` resolve different targets, the delta is computed against the wrong dir and I2 FAILs spuriously.

## Preconditions (at `--verify` time)

- **No concurrent Claude Code sessions wrote to the target between `--baseline` and `--verify`.** A stray session appends a new `<uuid>.jsonl` to the target root, inflating the measured delta → I2 reports `added > copied` (its message flags this as likely external churn). Run the migration with no other sessions open on that project.

## The 6 invariants

All are **CRITICAL** (verdict is PASS only if all pass). Each writes an `I#.txt` with computed vs expected values.

| ID | Property | Consumes | FAILs when |
|----|----------|----------|-----------|
| **I1** | **Conservation** — no pre-migration target path was deleted/moved | `baseline/target_listing.txt` | any baseline path is absent post-migration |
| **I2** | **Count cross-check** *(independent oracle)* — new root `.jsonl` count == migrate's reported `transcripts_copied` | `migration-output.txt` `MACHINE_SUMMARY` + live target | counts differ, or no summary found. SKIPPED on a dry-run. |
| **I3** | **Well-formed** — every newly-added `.jsonl` is non-empty and parses as JSON | live target delta | any added transcript is empty/corrupt |
| **I4** | **Clean delta** — no newly-added path is a subagent/`audit.jsonl`/credentials artifact | live target delta | a forbidden file was added: anything under `/subagents/`, `audit.jsonl`, any `agent-*.jsonl` (anywhere), or any filename containing `credentials` |
| **I5** | **MEMORY.md unchanged** — target `memory/MEMORY.md` sha256 == baseline | `baseline/memory_md.sha256` | the migration modified the index (operator updates it separately, *after* verify) |
| **I6** | **Cowork sources unchanged** — `spaces.json` sha256 + cowork memory listing + session-dir count all == baseline | the three baseline source files | any Cowork source was mutated (copy-only invariant broken) |

`history.jsonl` (which Claude Code rewrites at the target root) is excluded from the `.jsonl` delta — it is never "copied," so counting it would make I2 false-FAIL on a live target.

### I2 — the independent oracle, and its honest limits

I2 compares two **independent** measurements: the migrate script's self-*reported* count (the `MACHINE_SUMMARY` line, from its bookkeeping code) vs the *measured* new-root-`.jsonl` delta (from the filesystem). Agreement means the report is consistent with what landed.

**I2 is a CONSISTENCY check, not a completeness check.** It does **not** detect:
- a **no-op** (`copied=0`, `added=0` → PASS — correct for a consistency check, but it can't tell a legitimately-empty migration from one that wrongly did nothing; I2 emits a NOTE when `copied=0`);
- a **drop masked by skip-existing** (a transcript whose stem already exists at the target — or a same-stem collision across two sessions — is skipped, so reported/measured counts stay consistent);
- **tool-results completeness** — I2 cross-checks `transcripts_copied` only. No invariant cross-checks the `tool_results_copied` count against a measured `tool-results/` delta, so a tool-results copy that silently did nothing (e.g. a path-assumption mismatch) would not be caught. Spot-check that a migrated session's tool calls render.

Neither I2 nor any invariant here certifies that discovery selected the **right** sessions — that is unverifiable without a ground-truth fixture (which is exactly what makes this suite generic). The migrate script's runtime BEFORE/AFTER/DIFF + the operator's dry-run eyeball remain the human check on *selection*.

## Dry-run handling

If `migration-output.txt` reports `dry_run: true`, the verifier prints a WARNING, marks **I2 SKIPPED**, and returns **PARTIAL PASS** (exit 1) — a dry-run copies nothing, so the structural invariants are vacuous. Verify a real migration. **A dry-run never masks a real problem:** if any CRITICAL invariant FAILs or `migration_errors > 0`, the verdict is FAIL regardless of the dry-run flag (real failures take precedence over PARTIAL PASS).

## Verdict & exit codes

Verdict precedence (computed by `compute_verdict`, highest first):

1. **FAIL** (exit 2): any CRITICAL invariant FAILed — including I2, which FAILs when its `MACHINE_SUMMARY` oracle is missing — OR `migration_errors > 0` (the migration's `MACHINE_SUMMARY` reported copy errors). Real failures and copy-errors are checked **before** the dry-run downgrade, so they are never hidden.
2. **PARTIAL PASS** (exit 1): the migration output was a dry-run AND nothing above failed (see *Dry-run handling*).
3. **PASS** (exit 0): all 6 invariants pass, no copy errors.

`summary.json` records `verdict`, `verdict_note`, per-invariant status + raw-output paths, `critical_failures`, `critical_skipped`, and `migration_errors`.

## Unit + integration tests (the tool's own test suite)

Separate from the per-run invariant checks above, the tool ships a stdlib `unittest` suite under `tests/` — run it from the tool dir after any code change:

```bash
python3 -m unittest discover -s tests
```

- `tests/fixtures.py` — the **single source of truth** for test input: `build_synthetic_workspace(root)` materializes a fully synthetic Cowork workspace (no real data) in a temp dir; the integration + end-to-end tests reuse it. Also runnable standalone to eyeball a sample: `python3 tests/fixtures.py /tmp/sample`.
- `tests/test_cowork_config.py` — `.env` loading + precedence resolution.
- `tests/test_verify_migration.py` — verifier predicates (`parse_machine_summary`, `is_wellformed_jsonl`, `is_forbidden_added_path`), the invariant functions (I1–I6), `resolve_space_uuid`, `compute_verdict` precedence, and an end-to-end baseline→migrate→verify run (PASS + a forbidden-artifact FAIL).
- `tests/test_migrate_cowork_sessions.py` — discovery/classification + space-resolution helpers, copy bookkeeping (incl. 0-byte re-copy), snapshots, the `MACHINE_SUMMARY` line, and an integration test that subprocess-runs the migration (exclusions, idempotency, 0-byte heal). All fixtures are synthetic placeholders — no real data.
