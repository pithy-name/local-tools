# migrate-cowork-sessions

Reusable, project-agnostic Cowork→Claude Code transcript+memory migration + a property-based verifier. Config via a gitignored `.env` (see `demo.env`). Full detail in `README.md` + `TESTING.md`; operator runbook at `cowork-migration-runbook.md` (same dir).

## Commands

```bash
# config first: cp demo.env .env  and fill in COWORK_WORKSPACE (+ optional COWORK_SPACE/COWORK_TARGET)
python3 migrate_cowork_sessions.py --list                                                       # lists spaces
python3 migrate_cowork_sessions.py --space <name> --target ~/.claude/projects/<dir> --dry-run
python3 migrate_cowork_sessions.py --space <name> --target ~/.claude/projects/<dir>
# verify (property-based): pass the SAME --space/--target to BOTH baseline and verify
python3 verify_migration.py --baseline --space <name> --target ~/.claude/projects/<dir> --output-dir verification-reports/<ts>/
python3 verify_migration.py --verify   --space <name> --target ~/.claude/projects/<dir> --baseline-dir verification-reports/<ts>/
```

`verify_migration.py` is the property-based structural verifier (6 invariants I1–I6; no hardcoded fixtures — works for any space). Run executions in a sandbox (`/tmp/`), not the live workspace. "Done" = actually run, not just written.
