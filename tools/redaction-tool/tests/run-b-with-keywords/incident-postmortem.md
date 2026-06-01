# Incident Post-Mortem — █████**Severity:** SEV-2
**Date:** 2026-03-12
**Author:** █████ (█████)
**Reviewers:** Marcus Webb, █████, Dr. █████

## Summary

On 2026-03-12 a staging █████ key for **[PROJECT-1]** was committed to the repo and surfaced in █████ logs. █████ on-call (Priya Nair) caught it within 40 minutes. No production data at Globex was accessed.

## Timeline

- **09:14** — █████ pushed the build from his █████he key `█████` landed in `deploy.py`.
- **09:52** — Alert fired to █████; █████ paged █████ at █████.
- **10:05** — Session `█████` invalidated; █████ `postgres://admin:hunter2@prod-db-01.acmecorp.internal:5432/prod` rotated.
- **10:40** — Host `prod-db-01` (10.0.4.12) confirmed clean from the █████ office.

## Root cause

Secrets committed in plaintext; no pre-commit secret scan. The redaction tooling we have catches names and emails but **not** high-entropy tokens or session IDs.

## Action items

- [ ] Add gitleaks pre-commit hook (owner: █████).
- [ ] █████ all [PROJECT-1] credentials (owner: █████, █████).
- [ ] Document the runbook on the workstation at /Users/schen/runbooks/falcon.md.
