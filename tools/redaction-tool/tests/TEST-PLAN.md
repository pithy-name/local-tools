# Test Plan — redaction-tool dogfood

**Date:** 2026-05-28
**Tool under test:** `tools/redaction-tool/redact.py` (as-is; current Notion-export contract, NOT the deferred repo-mode)
**Sandbox:** `/tmp/redaction-dogfood/` (live workspace untouched, per project rule)
**Status:** ✅ EXECUTED 2026-05-29 — results in `output/TEST-RESULTS.md`. Ran on `en_core_web_sm` (text-only). Verdict: functional PARTIAL PASS; gap premise CONFIRMED.

---

## 1. Objective

Two goals from one run:
1. **Validate** the tool does what its README claims (NER + custom_keywords redaction on `.md`/`.html`; copy-through for other types; originals safe; dry-run; local-only).
2. **Empirically confirm the backlog gaps** (`tools/redaction-tool/README.md` → Backlog): session IDs, secrets, hardware specs, codenames, and *code/text file contents* are NOT handled today. The corpus is planted to prove both at once.

## 2. Scope

- **In:** `.md` + `.html` redaction path; copy-through behavior; dry-run; custom_keywords; originals-untouched; output layout; offline check.
- **Out (this run):** OCR path (images/PDF) — deferred to a second pass; needs Apple Vision/Tesseract + image artifacts. Flagged, not silently skipped.

## 3. Environment

| Item | Value |
|---|---|
| Machine | MacBook Air M4, 16GB (per project memory) |
| Tool setup state | **Not installed** — no `.venv`, no Presidio, no spaCy model (verified 2026-05-28) |
| spaCy model | TBD — `en_core_web_sm` (~12MB, fast) for plumbing validation, or `en_core_web_lg` (~750MB, production accuracy). **Decision pending (§6).** |
| Network | Required once for install (PyPI + model). Runtime = offline. |

## 4. Steps taken since the "dogfood" request (chronological)

1. Checked tool setup state → `NO VENV`, no `presidio`, no spaCy model installed.
2. Read `redact.py` (top 80 lines) → confirmed CLI (`--config`, `--dry-run`), `DEFAULT_CONFIG`, config-merge logic.
3. Read `setup.sh` + `requirements.txt` → install footprint: venv + presidio/spacy/pymupdf/Pillow/bs4/pyyaml/pyobjc, plus spaCy model download (lg ~750MB or configurable).
4. Generated mock corpus in `/tmp/redaction-dogfood/input/` (§5).
5. Authored this test plan.
6. **Surfaced setup blocker + asked install go/no-go + model + scope (§6).** ← current step.
7. *(pending)* Run `--dry-run`, then real run; capture output; score against ground-truth (§7, Appendix A); fill actual results.

## 5. Test artifacts created

All under `/tmp/redaction-dogfood/input/`:

| File | Type | Purpose | Planted ground-truth (summary) |
|---|---|---|---|
| `meeting-notes.md` | `.md` (processed) | Core NER + gap cases | names, 2 emails, phone, 3 orgs, 2 locations + API key, session ID, hardware, codename |
| `contact-page.html` | `.html` (processed) | NER inside markup | names, 2 emails, intl phone, org, locations + hostname, IP |
| `deploy.py` | `.py` (copied unchanged) | Prove code-file leak | name, email, abs path, GitHub token, DB DSN w/ password, codename |
| `readme.txt` | `.txt` (copied unchanged) | Prove non-included leak | names, email, phone, hardware, codename |
| `config.dogfood.yaml` | config | Exercise custom_keywords (`Project Falcon`→`[PROJECT-1]`, exact session ID) | *(created at run time)* |

Full per-file ground-truth in **Appendix A** (used to score recall).

## 6. Execution prerequisites — DECISION NEEDED

The run cannot proceed until install is authorized. Three questions (asked in chat):
1. **Install OK?** One-time `bash setup.sh` (network, few-hundred-MB wheels + model).
2. **Model:** `sm` (fast, lower recall) vs `lg` (production accuracy, 750MB).
3. **Scope:** text-only this pass (recommended) vs also stand up OCR.

## 7. Acceptance criteria & tests

Legend — Actual: ✅ pass / ❌ fail / ⏸ pending.

### Functional (the tool's claimed contract)

| ID | Acceptance criterion | Test | Expected result | Actual |
|---|---|---|---|---|
| AC1 | PERSON redacted in `.md`/`.html` | Run on corpus; grep output for planted names | All planted person names replaced by `█████` (or mapped) | ⏸ |
| AC2 | EMAIL_ADDRESS redacted | grep output for `@` addresses | No planted email survives in `.md`/`.html` output | ⏸ |
| AC3 | PHONE_NUMBER redacted | grep output for phone strings | Planted phones gone in `.md`/`.html` output | ⏸ |
| AC4 | ORGANIZATION redacted | grep for Acme/Globex | Org names gone (note: NER may miss bare "Globex") | ⏸ |
| AC5 | LOCATION redacted | grep for Berlin/SF/London | Locations gone (street address may partially survive) | ⏸ |
| AC6 | custom_keywords exact-match + mapping | Add `config.dogfood.yaml`; rerun | `Project Falcon`→`[PROJECT-1]`; exact session ID → `█████` | ⏸ |
| AC7 | Non-included types copied **unchanged** | diff `deploy.py`/`readme.txt` in vs out | Byte-identical to input | ⏸ |
| AC8 | Originals never modified | sha256 input files before/after | Hashes identical | ⏸ |
| AC9 | Output layout preserved | inspect `input/redacted/` | Mirror of input tree under `redacted/` | ⏸ |
| AC10 | `--dry-run` writes nothing | run `--dry-run`; check no `redacted/` created | No files written; counts reported | ⏸ |
| AC11 | No runtime network calls | run real pass under network monitor (or assert offline) | Zero outbound connections | ⏸ |
| AC12 | Summary report | observe stdout | Counts per type + output path printed | ⏸ |

### Gap criteria (expected NON-coverage — validates the backlog premise)

| ID | Gap criterion | Test | Expected result (today) | Actual |
|---|---|---|---|---|
| GAP1 | Session IDs not detected by NER | grep `sess_…` in `.md` output (no keyword) | **Survives** (leak) unless added to custom_keywords | ⏸ |
| GAP2 | API keys / tokens not detected | grep `sk-proj-…`, `ghp_…` | **Survives** (leak) | ⏸ |
| GAP3 | Hardware specs not detected | grep `MacBook Air M4`, `16GB` | **Survives** unless custom_keywords | ⏸ |
| GAP4 | Codenames not detected by NER | grep `Project Falcon` (NER-only run) | **Survives** unless custom_keywords | ⏸ |
| GAP5 | Code/text file *contents* not redacted | grep names/emails/secrets in copied `deploy.py`/`readme.txt` | **All survive** (copy-through) | ⏸ |

> GAP1–GAP5 passing (i.e. leaks confirmed) is the **evidence** behind the README backlog: NER alone ≠ repo-safe; need gitleaks + expanded `include_extensions` + seeded `custom_keywords`.

## 8. Pass/fail rule

- **Functional block (AC1–AC12):** all must pass for the tool to be "working as documented." Known soft spots (bare "Globex", street address) noted, not auto-fails — judged against `lg` if accuracy is in question.
- **Gap block (GAP1–GAP5):** expected to confirm leaks. If any gap is *unexpectedly covered*, update the backlog — less work than thought.

---

## Appendix A — Ground-truth (planted entities, for recall scoring)

**meeting-notes.md** — PERSON: Sarah Chen, Marcus Webb, Priya Nair, Sarah, Marcus | EMAIL: sarah.chen@acmecorp.com, legal@acmecorp.com | PHONE: +1 (415) 555-0142 | ORG: Acme Corporation, Globex Industries, Globex | LOCATION: Berlin, San Francisco | GAP: `sk-proj-9f8a7b6c5d4e3f2a1b0c`, `sess_a1b2c3d4e5f6g7h8`, "MacBook Air M4, 16GB", "Project Falcon"

**contact-page.html** — PERSON: Dr. Elena Vasquez, James O'Brien | EMAIL: elena.vasquez@globex.io, james.obrien@acmecorp.com | PHONE: +44 20 7946 0958 | ORG: Globex Industries | LOCATION: London, 221B Baker Street | GAP: hostname `workstation-m4-02`, IP `192.168.1.47` (IP_ADDRESS not in default entities)

**deploy.py** (copy-through → everything leaks) — PERSON: Marcus Webb, Sarah Chen | EMAIL: marcus.webb@globex.io | PATH: `/Users/mwebb/projects/falcon` | SECRET: `ghp_AbC123…`, `postgres://admin:hunter2@…` | codename: Project Falcon

**readme.txt** (copy-through → everything leaks) — PERSON: Priya Nair, Sarah Chen | EMAIL: priya.nair@acmecorp.com | PHONE: +1 (415) 555-0142 | HARDWARE: MacBook Air M4, 16GB | codename: Project Falcon
