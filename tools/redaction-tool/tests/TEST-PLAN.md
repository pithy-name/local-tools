# Test Plan — redaction-tool

**Tool under test:** `tools/redaction-tool/redact.py` (the folder-of-files contract)
**Sandbox:** `/tmp/redaction-dogfood/` — run against a copy; the live workspace is untouched.
**Status:** Runnable — a reusable acceptance-/gap-criteria plan you can run against `redact.py`. The mock corpus, configs, and expected outputs are in this folder; see `README.md` → "How to re-run".

---

## 1. Objective

Two goals from one run:
1. **Validate** the tool does what its README claims (NER + custom_keywords redaction on `.md`/`.html`; copy-through for other types; originals safe; dry-run; local-only).
2. **Confirm the known non-coverage** (gaps): session IDs, secrets, hardware specs, codenames, and *code/text file contents* are NOT handled by NER alone. The corpus is planted to prove both at once.

## 2. Scope

- **In:** `.md` + `.html` redaction path; copy-through behavior; dry-run; custom_keywords; originals-untouched; output layout; offline check.
- **Out:** OCR path (images/PDF) — out of scope for this plan, which covers the text-redaction path.

## 3. Environment

| Item | Value |
|---|---|
| Machine | Apple Silicon Mac, 16GB |
| spaCy model | Defaults to `en_core_web_sm` (small/fast). `en_core_web_lg` is available for higher recall, but noisier — more false positives. |
| Network | Required once for install (PyPI + model). Runtime = offline. |

## 4. Test artifacts

All under `/tmp/redaction-dogfood/input/`:

| File | Type | Purpose | Planted ground-truth (summary) |
|---|---|---|---|
| `meeting-notes.md` | `.md` (processed) | Core NER + gap cases | names, 2 emails, phone, 3 orgs, 2 locations + API key, session ID, hardware, codename |
| `contact-page.html` | `.html` (processed) | NER inside markup | names, 2 emails, intl phone, org, locations + hostname, IP |
| `deploy.py` | `.py` (copied unchanged) | Prove code-file leak | name, email, abs path, GitHub token, DB DSN w/ password, codename |
| `readme.txt` | `.txt` (copied unchanged) | Prove non-included leak | names, email, phone, hardware, codename |
| `config.dogfood.yaml` | config | Exercise custom_keywords (`Project Falcon`→`[PROJECT-1]`, exact session ID) | *(created at run time)* |

Full per-file ground-truth in **Appendix A** (used to score recall).

## 5. Acceptance criteria & tests

### Functional (the tool's claimed contract)

| ID | Acceptance criterion | Test | Expected result |
|---|---|---|---|
| AC1 | PERSON redacted in `.md`/`.html` | Run on corpus; grep output for planted names | All planted person names replaced by `█████` (or mapped) |
| AC2 | EMAIL_ADDRESS redacted | grep output for `@` addresses | No planted email survives in `.md`/`.html` output |
| AC3 | PHONE_NUMBER redacted | grep output for phone strings | Planted phones gone in `.md`/`.html` output |
| AC4 | ORGANIZATION redacted | grep for Acme/Globex | Org names gone (note: NER may miss bare "Globex") |
| AC5 | LOCATION redacted | grep for Berlin/SF/London | Locations gone (street address may partially survive) |
| AC6 | custom_keywords exact-match + mapping | Add `config.dogfood.yaml`; rerun | `Project Falcon`→`[PROJECT-1]`; exact session ID → `█████` |
| AC7 | Non-included types copied **unchanged** | diff `deploy.py`/`readme.txt` in vs out | Byte-identical to input |
| AC8 | Originals never modified | sha256 input files before/after | Hashes identical |
| AC9 | Output layout preserved | inspect `input/redacted/` | Mirror of input tree under `redacted/` |
| AC10 | `--dry-run` writes nothing | run `--dry-run`; check no `redacted/` created | No files written; counts reported |
| AC11 | No runtime network calls | run real pass under network monitor (or assert offline) | Zero outbound connections |
| AC12 | Summary report | observe stdout | Counts per type + output path printed |

### Gap criteria (expected NON-coverage)

| ID | Gap criterion | Test | Expected result (today) |
|---|---|---|---|
| GAP1 | Session IDs not detected by NER | grep `sess_…` in `.md` output (no keyword) | **Survives** (leak) unless added to custom_keywords |
| GAP2 | API keys / tokens not detected | grep `sk-proj-…`, `ghp_…` | **Survives** (leak) |
| GAP3 | Hardware specs not detected | grep `ThinkPad X1 Carbon`, `16GB` | **Survives** unless custom_keywords |
| GAP4 | Codenames not detected by NER | grep `Project Falcon` (NER-only run) | **Survives** unless custom_keywords |
| GAP5 | Code/text file *contents* not redacted | grep names/emails/secrets in copied `deploy.py`/`readme.txt` | **All survive** (copy-through) |

> GAP1–GAP5 passing (leaks confirmed) demonstrates that NER alone ≠ repo-safe: full coverage needs secret-scanning + expanded `include_extensions` + seeded `custom_keywords`.

## 6. Pass/fail rule

- **Functional block (AC1–AC12):** all must pass for the tool to be "working as documented." Known soft spots (bare "Globex", street address) are noted, not auto-fails — re-score with `en_core_web_lg` (higher recall but noisier — more false positives) to tell a recall-limit miss from a real bug.
- **Gap block (GAP1–GAP5):** expected to confirm leaks. If any gap is *unexpectedly covered*, update the README — less work than thought.

---

## Appendix A — Ground-truth (planted entities, for recall scoring)

**meeting-notes.md** — PERSON: Sarah Chen, Marcus Webb, Priya Nair, Sarah, Marcus | EMAIL: sarah.chen@acmecorp.com, legal@acmecorp.com | PHONE: +1 (415) 555-0142 | ORG: Acme Corporation, Globex Industries, Globex | LOCATION: Berlin, San Francisco | GAP: `sk-proj-9f8a7b6c5d4e3f2a1b0c`, `sess_a1b2c3d4e5f6g7h8`, "ThinkPad X1 Carbon, 16GB", "Project Falcon"

**contact-page.html** — PERSON: Dr. Elena Vasquez, James O'Brien | EMAIL: elena.vasquez@globex.io, james.obrien@acmecorp.com | PHONE: +44 20 7946 0958 | ORG: Globex Industries | LOCATION: London, 221B Baker Street | GAP: hostname `workstation-m4-02`, IP `192.168.1.47` (IP_ADDRESS not in default entities)

**deploy.py** (copy-through → everything leaks) — PERSON: Marcus Webb, Sarah Chen | EMAIL: marcus.webb@globex.io | PATH: `/Users/mwebb/projects/falcon` | SECRET: `ghp_AbC123…`, `postgres://admin:hunter2@…` | codename: Project Falcon

**readme.txt** (copy-through → everything leaks) — PERSON: Priya Nair, Sarah Chen | EMAIL: priya.nair@acmecorp.com | PHONE: +1 (415) 555-0142 | HARDWARE: ThinkPad X1 Carbon, 16GB | codename: Project Falcon
