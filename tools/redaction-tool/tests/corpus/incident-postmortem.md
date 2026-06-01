# Incident Post-Mortem — INC-2026-0312 Staging Credential Leak

**Severity:** SEV-2
**Date:** 2026-03-12
**Author:** Sarah Chen (sarah.chen@acmecorp.com)
**Reviewers:** Marcus Webb, Priya Nair, Dr. Elena Vasquez

## Summary

On 2026-03-12 a staging API key for **Project Falcon** was committed to the repo and surfaced in CI logs. Acme Corporation's on-call (Priya Nair) caught it within 40 minutes. No production data at Globex was accessed.

## Timeline

- **09:14** — Marcus Webb pushed the build from his MacBook Air M4, 16GB; the key `sk-proj-9f8a7b6c5d4e3f2a1b0c` landed in `deploy.py`.
- **09:52** — Alert fired to oncall@acmecorp.com; Priya Nair paged Sarah Chen at +1 (415) 555-0142.
- **10:05** — Session `sess_a1b2c3d4e5f6g7h8` invalidated; DSN `postgres://admin:hunter2@prod-db-01.acmecorp.internal:5432/prod` rotated.
- **10:40** — Host `prod-db-01` (10.0.4.12) confirmed clean from the San Francisco office.

## Root cause

Secrets committed in plaintext; no pre-commit secret scan. The redaction tooling we have catches names and emails but **not** high-entropy tokens or session IDs.

## Action items

- [ ] Add gitleaks pre-commit hook (owner: Marcus Webb).
- [ ] Rotate all Project Falcon credentials (owner: Elena Vasquez, elena.vasquez@globex.io).
- [ ] Document the runbook on the workstation at /Users/schen/runbooks/falcon.md.
