# redaction-tool — tests

Dogfood test suite for `../redact.py`. Fixed mock corpus + expected redacted outputs + a written test plan and results report. Use it to verify the tool still behaves after any change (a manual golden-test until P1.7 automates it).

## What's here

| Path | What |
|---|---|
| `TEST-PLAN.md` | Acceptance criteria (AC1–12), gap criteria (GAP1–5), per-criterion tests + expected results, ground-truth appendix. |
| `TEST-RESULTS.md` | Executed run (2026-05-29, `en_core_web_sm`). Verdict, evidence, 8 bugs (B1–B8), and **§10 production roadmap**. Canonical report. |
| `baseline.sha256` | Hashes of the corpus — proves originals are never modified (AC8). |
| `corpus/` | 5 mock input files (see ground-truth below). |
| `configs/` | `config.ner-only.yaml` (Run A) and `config.dogfood.yaml` (Run B, with `custom_keywords`). |
| `run-a-ner-only/` | Expected output — NER only. |
| `run-b-with-keywords/` | Expected output — NER + custom_keywords. |

## TL;DR of the result

Plumbing passes (dry-run, originals-safe, copy-through, layout, keywords, summary). **Accuracy does not** on the small model: missed names/orgs, and the engine over-redacts (eats adjacent text + newlines). Secrets/IDs/IPs/paths leak under NER as expected. **Not yet repo-safe.** Full detail + next steps in `TEST-RESULTS.md`.

## ⚠️ Before you commit this anywhere

`corpus/` and the `run-*` outputs contain **fake, synthetic** secret-shaped strings on purpose — `ghp_…` (GitHub-token shape), `sk-proj-…` (API-key shape), `postgres://admin:hunter2@…` (DSN). They are not real. But **gitleaks / secret scanners will flag them.** When you add gitleaks (Phase 2), allowlist this directory via `.gitleaksignore`.

## What the corpus proves (ground-truth)

Each file is planted with both easy cases (NER should catch) and hard cases (NER can't — the gaps):

- `meeting-notes.md` — names, emails, phone, orgs, locations **+** API key, session ID, hardware spec, codename.
- `contact-page.html` — same entity classes inside HTML markup **+** hostname, IP.
- `incident-postmortem.md` — a realistic SEV-2 post-mortem; dense names/emails **+** API key, session ID, DB DSN, IP, absolute path, codename.
- `deploy.py` — **copy-through leak demo**: `.py` isn't in `include_extensions`, so it's copied verbatim → name, email, token, DSN, `/Users/…` path all survive.
- `readme.txt` — copy-through leak demo for `.txt`.

Full per-file ground-truth: `TEST-PLAN.md` → Appendix A.

## How to re-run

The tool's `.venv` is **not** committed. Rebuild in a sandbox (live workspace stays clean):

```bash
# 1. sandbox + venv  — use python3.11+, NOT system python3 (3.9 can't build current spaCy; see bug B6)
DST=/tmp/redaction-dogfood/tool
mkdir -p "$DST"
cp ../redact.py ../requirements.txt "$DST/"
/opt/homebrew/bin/python3.11 -m venv "$DST/.venv"
PY="$DST/.venv/bin/python"
"$PY" -m pip install --upgrade pip
"$PY" -m pip install "presidio-analyzer>=2.2" "presidio-anonymizer>=2.2" "spacy>=3.7" \
  "pymupdf>=1.24" "Pillow>=10.0" "beautifulsoup4>=4.12" "PyYAML>=6.0" "click>=8.0" "typer>=0.9"
"$PY" -m spacy download en_core_web_sm          # or en_core_web_lg for the accuracy run

# 2. run both passes against a COPY of the corpus
cp -R corpus /tmp/redaction-dogfood/input
"$PY" "$DST/redact.py" /tmp/redaction-dogfood/input --config configs/config.ner-only.yaml
"$PY" "$DST/redact.py" /tmp/redaction-dogfood/input --config configs/config.dogfood.yaml

# 3. diff produced output against the expected run-*/ dirs in this folder
```

For a true accuracy verdict, swap `en_core_web_sm` → `en_core_web_lg` (~750 MB) and re-score — the small model's misses are recall, not design.

## Walkthrough for non-technical readers

1. **Why this exists.** Before trusting the redaction tool to hide sensitive info, we tested it on fake data where we know exactly what *should* be hidden.
2. **The fake files** (`corpus/`) contain made-up people, emails, and secrets — nothing real.
3. **We ran the tool twice:** once using only its smart "name detector" (`run-a-ner-only/`), once with an extra exact-match list added (`run-b-with-keywords/`).
4. **We compared** what it hid vs. what it should have hidden. The scorecard is in `TEST-RESULTS.md`.
5. **The takeaway:** it hides emails and phone numbers reliably, but it missed some names, mangled some text, and (by design) didn't touch passwords or ID codes. So it's not ready to trust on a real project yet — `TEST-RESULTS.md` §10 lists what has to happen first.
