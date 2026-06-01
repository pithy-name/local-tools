# Test Results — redaction-tool dogfood

**Run date:** 2026-05-29
**Tool:** `tools/redaction-tool/redact.py` (as-is; Notion-export contract)
**Companion plan:** `../TEST-PLAN.md`
**Sandbox:** `/tmp/redaction-dogfood/` — live workspace never touched (tool was copied out; no `.venv` written to the repo)
**Model used:** `en_core_web_sm` (~12 MB, fast). ⚠️ **`en_core_web_lg` (~750 MB) is available and would very likely improve recall** — several misses below are small-model recall failures and should be re-tested on `lg` before any verdict on accuracy.
**Scope:** text only (`.md`/`.html` processed; `.py`/`.txt` copy-through). OCR (image/PDF) and `.mp4` (video) NOT tested — deferred.

---

## 1. Executive summary

**Functional verdict: PARTIAL PASS.** Plumbing is sound (dry-run, originals-safe, copy-through, layout, custom_keywords, summary — all pass). **But the tool's *core* job — entity recall — is unreliable on the `sm` model**, and the redaction engine **over-redacts and corrupts formatting** when detectors overlap.

Headline findings:
1. **PERSON recall misses, inconsistently.** `Marcus Webb` and `Priya Nair` leaked in *both* runs — and `Marcus Webb` was redacted in one sentence but left intact two lines up in the same file. (`sm` model; re-test on `lg`.)
2. **ORGANIZATION recall is poor.** `Globex` / `Globex Industries` survived in all three processed files.
3. **Over-redaction eats adjacent text & whitespace.** Overlapping detectors (custom keyword + spaCy `PRODUCT` + `CARDINAL`) merge into one span that swallowed real words and newlines — e.g. `(█████efore the offsite`, `from his █████he key`, and an H1 glued to the next line. This is **data/format corruption**, not just imperfect redaction.
4. **Gaps confirmed (the backlog premise holds):** API keys, session IDs, DB connection strings (`postgres://admin:hunter2@…`), IPs, hostnames, and absolute paths all leaked under NER. Only the ones explicitly added as `custom_keywords` were caught.
5. **Copy-through = total leak by design.** `.py`/`.txt` are copied byte-identical, so every secret/name/path inside them survives. For a *repo* scrub this is the dominant risk.
6. **Environment bug:** `requirements.txt` pins `spacy>=3.7` unbounded; on the machine's default `python3` (**3.9.6**) this fails to build (`thinc>=8.3.12` requires Python ≥3.10), despite the README/`setup.sh` claiming "Python 3.9+". Had to rebuild on `python3.11`.

**Gap verdict: CONFIRMED.** GAP1–GAP5 all reproduced → NER + keywords alone is **not** repo-safe. gitleaks (secrets) + expanded `include_extensions` + a seeded keyword list + human review remain required (matches the README backlog).

---

## 2. Environment & how it was built

| Item | Value |
|---|---|
| Machine `python3` | 3.9.6 — **insufficient** for current spaCy (see bug B6) |
| Interpreter used | `/opt/homebrew/bin/python3.11` → venv at `/tmp/redaction-dogfood/tool/.venv` |
| Key versions | spaCy 3.8.14, model `en_core_web_sm`, presidio-analyzer/anonymizer ≥2.2 |
| Deps installed | presidio-analyzer, presidio-anonymizer, spacy, pymupdf, Pillow, beautifulsoup4, PyYAML (+ click, typer). **pyobjc/OCR deliberately skipped** (text-only). |
| Network | Used once for install; redaction run itself loads a local model (no runtime calls observed — see AC11 caveat). |

---

## 3. Acceptance criteria — results

Evidence excerpts in §5. Legend: ✅ pass · ⚠️ partial · ❌ fail · ℹ️ by-design.

| ID | Criterion | Result | Evidence |
|---|---|---|---|
| AC1 | PERSON redacted | ⚠️ **partial** | `Sarah Chen`/`Elena Vasquez`/`James O'Brien` caught; **`Marcus Webb`, `Priya Nair` leaked in both runs**, inconsistently within a file |
| AC2 | EMAIL redacted | ✅ | all planted addresses → `█████` in `.md`/`.html` (incl. `mailto:` not present here) |
| AC3 | PHONE redacted | ✅ | `+1 (415) 555-0142`, `+44 20 7946 0958` → `█████` |
| AC4 | ORGANIZATION redacted | ❌ **fail** | `Globex` (meeting + postmortem) and `Globex Industries` (HTML) survived |
| AC5 | LOCATION redacted | ⚠️ partial | `Berlin`/`San Francisco`/`London` caught; address `221B █████ Street` only partially (kept `221B`, `Street`) |
| AC6 | custom_keywords (exact + mapping) | ✅ (with caveat) | `Project Falcon`→`[PROJECT-1]`; session ID + API key → `█████`. **Caveat:** overlap caused over-redaction (B3) |
| AC7 | non-included types copied unchanged | ✅ | `deploy.py`, `readme.txt` byte-identical (diff clean) |
| AC8 | originals never modified | ✅ | all 5 input hashes match baseline after both runs |
| AC9 | output layout preserved | ✅ | `redacted/` mirrors input (flat tree here) |
| AC10 | `--dry-run` writes nothing | ✅ | no `redacted/` dir created; counts reported |
| AC11 | no runtime network calls | ⚠️ **not instrumented** | run completed with a local model; **I did not attach a network monitor**, so this is asserted-by-design, not independently verified this run |
| AC12 | summary report | ✅ | per-file + totals printed (45 then 54 redactions) |

## 4. Gap criteria — results (expected NON-coverage)

| ID | Gap | Run A (NER) | Run B (+KW) | Confirmed? |
|---|---|---|---|---|
| GAP1 | Session IDs | SURVIVED | redacted (keyword) | ✅ leak without keyword |
| GAP2 | API keys / tokens | SURVIVED | redacted (keyword) | ✅ leak without keyword |
| GAP3 | Hardware specs | `MacBook Air M4` caught *incidentally* as `PRODUCT`; `16GB` leaked in A | both → `█████` (over-redacted) | ⚠️ partial/unreliable |
| GAP4 | Codenames | `Project Falcon` SURVIVED | `[PROJECT-1]` | ✅ needs keyword |
| GAP5 | Code/text file contents | SURVIVED (copied) | SURVIVED (copied) | ✅ total leak by design |
| — | DB DSN `hunter2`, hostnames, IPs, `/Users/…` paths | SURVIVED | SURVIVED | ✅ none covered (IP_ADDRESS not in `entities`) |

> GAP confirmation is the **evidence** behind the repo-anonymizer backlog: NER + keywords ≠ repo-safe.

---

## 5. Evidence — before/after excerpts

**PERSON inconsistency (incident-postmortem.md, both runs):**
```
Reviewers: Marcus Webb, █████, Dr. █████        ← "Marcus Webb" LEAKED
...
- 09:14 — █████ pushed the build ...             ← same name, REDACTED
... on-call (Priya Nair) caught it ...           ← "Priya Nair" LEAKED
```

**ORG miss (contact-page.html):**
```
<li>Office: Globex Industries, 221B █████ Street, █████</li>   ← org + "221B"/"Street" survive
<p>Internal note: provisioned on host workstation-m4-02, IP 192.168.1.47.</p>  ← host+IP survive
```

**Over-redaction / format corruption (Run B):**
```
# Incident Post-Mortem — █████**Severity:** SEV-2     ← heading text + newlines eaten, H1 glued
- ... from his █████he key `█████` landed ...          ← "MacBook Air M4, 16GB; t" consumed
(█████efore the offsite.                                ← "MacBook Air M4, 16GB) b" consumed (meeting-notes)
```

**Gap leaks present in both runs (incident-postmortem.md):**
```
key `sk-proj-9f8a7b6c5d4e3f2a1b0c` ...            (Run A; redacted by keyword in B)
Session `sess_a1b2c3d4e5f6g7h8` ...               (Run A; keyword in B)
`postgres://admin:hunter2@prod-db-01.acmecorp.internal:5432/prod`   (BOTH)
Host `prod-db-01` (10.0.4.12) ...                 (BOTH)
/Users/schen/runbooks/falcon.md                   (BOTH)
```

**Copy-through total leak (`deploy.py`, identical in/out):**
```
2: # Deploy script — maintained by Marcus Webb (marcus.webb@globex.io)
3: # Runs from /Users/mwebb/projects/falcon on the build box.
5: API_TOKEN = "ghp_AbC123dEf456GhI789jKl012MnO345pQr678"
6: DB_DSN = "postgres://admin:hunter2@db.acmecorp.internal:5432/prod"
```

---

## 6. Bugs / findings

| # | Severity | Finding | Suggested fix |
|---|---|---|---|
| B1 | High | PERSON recall misses (`Marcus Webb`, `Priya Nair`), inconsistent within a file | Re-test on `en_core_web_lg`; for known names use `custom_keywords` as backstop; consider higher-recall NER |
| B2 | High | ORGANIZATION recall poor (`Globex`, `Globex Industries`) | Same as B1; keyword-list critical clients |
| B3 | High | Over-redaction: overlapping spans (keyword + `PRODUCT` + `CARDINAL`) consume adjacent characters and newlines → corrupts content & Markdown structure | Clamp/merge spans to detected bounds; don't extend across whitespace/newlines; add a test |
| B4 | Med | IPs/hostnames not redacted — `IpRecognizer` loads but `IP_ADDRESS` absent from `entities` | Add `IP_ADDRESS` (and consider `URL`) to config `entities` |
| B5 | Med | Secrets (API keys, DB DSNs, tokens) not covered by any recognizer | Out of scope for this tool → **gitleaks** (matches backlog) |
| B6 | Med | `requirements.txt` `spacy>=3.7` unbounded fails on Python 3.9.6 (machine default) despite "Python 3.9+" claim | Pin a 3.9-compatible spaCy, or bump documented floor to 3.10/3.11; fix `setup.sh` check |
| B7 | Low | `en_core_web_sm` warns on unmapped `CARDINAL`/`PRODUCT`/`MONEY` entities (noise) | Set `labels_to_ignore` in NER config |
| B8 | Info | `.py`/`.txt` copied verbatim → full leak; fine for Notion exports, **fatal for a repo scrub** | Repo-mode: add code/config extensions + don't use `█████` in code |

---

## 7. Recommendations

1. **Before trusting accuracy, re-run on `en_core_web_lg`** and re-score B1/B2. `sm` is a plumbing check, not an accuracy verdict.
2. **Fix B3 (over-redaction) first** — it's a correctness bug that corrupts output regardless of model.
3. **For the repo-anonymizer goal:** confirm the stack from the README backlog — gitleaks (secrets/IDs) + this tool on `lg` with `IP_ADDRESS` added + a seeded `custom_keywords` list of personal tells + **human review**. This run empirically shows no single layer suffices.
4. **Add `IP_ADDRESS` to `entities`** (B4) — cheap, closes a whole class.
5. **Instrument AC11** (network) properly next time — e.g. run under `Little Snitch`/`nettop` or in a network-namespace — to actually verify the "no network" guarantee rather than assert it.

---

## 8. Steps & commands executed (verbatim, chronological since "dogfood" request)

> Captured per request. Reads of `redact.py` (lines 1–80, 80–240, 240–560, 559–608) omitted — inspection, not execution.

**1. Check tool setup state**
```bash
ls -d .venv 2>/dev/null && echo VENV EXISTS || echo NO VENV   # → NO VENV
.venv/bin/python -c "import presidio_analyzer" 2>/dev/null || echo "no presidio"
```

**2. Copy tool to sandbox + create venv (first attempt, Python 3.9 — FAILED)**
```bash
SRC=/Users/<redacted>/.../tools/redaction-tool
DST=/tmp/redaction-dogfood/tool
mkdir -p "$DST"; cp "$SRC/redact.py" "$SRC/requirements.txt" "$SRC/config.yaml" "$DST/"
python3 -m venv "$DST/.venv"                       # python3 = 3.9.6
"$DST/.venv/bin/python" -m pip install --quiet --upgrade pip
# pip install of spacy>=3.7 → ERROR: No matching distribution for thinc<8.4.0,>=8.3.12 (needs Py>=3.10)
```

**3. Find a newer interpreter**
```bash
for p in python3.13 python3.12 python3.11 python3.10; do command -v $p && $p --version; done
# → python3.11 = 3.11.15 @ /opt/homebrew/bin/python3.11
```

**4. Rebuild venv on 3.11 + install text-only deps + model**
```bash
rm -rf "$DST/.venv"; /opt/homebrew/bin/python3.11 -m venv "$DST/.venv"
PY="$DST/.venv/bin/python"
"$PY" -m pip install --quiet --upgrade pip
"$PY" -m pip install --quiet "presidio-analyzer>=2.2" "presidio-anonymizer>=2.2" "spacy>=3.7" \
  "pymupdf>=1.24" "Pillow>=10.0" "beautifulsoup4>=4.12" "PyYAML>=6.0"
"$PY" -m pip install --quiet "click>=8.0" "typer>=0.9"     # spaCy CLI needed click (didn't resolve)
"$PY" -m spacy download en_core_web_sm --quiet
"$PY" -c "import presidio_analyzer,presidio_anonymizer,spacy,fitz,PIL,bs4,yaml,en_core_web_sm; print('OK', spacy.__version__)"
```

**5. Baseline hashes (AC8) + dry-run (AC10)**
```bash
shasum -a 256 "$IN"/* | tee "$BASE/baseline.sha256"
"$PY" "$RED" "$IN" --config "$BASE/config.dogfood.yaml" --dry-run
[ -d "$IN/redacted" ] && echo "FAIL" || echo "PASS: no redacted/ dir"     # → PASS
```

**6. Two real runs (move output aside between)**
```bash
"$PY" "$RED" "$IN" --config "$BASE/config.ner-only.yaml"
mv "$IN/redacted" "$BASE/output/run-a-ner-only"          # 45 redactions
"$PY" "$RED" "$IN" --config "$BASE/config.dogfood.yaml"
mv "$IN/redacted" "$BASE/output/run-b-with-keywords"     # 54 redactions
```

**7. Verify originals (AC8) + copy-through (AC7)**
```bash
shasum -a 256 -c "$BASE/baseline.sha256"                 # → all OK
for f in deploy.py readme.txt; do diff -q "$IN/$f" "$B/$f"; done   # → identical
```

**8. Scoring + inspection**
```bash
# coarse per-string survival grep across processed .md/.html (both runs)  [later refined by eyeball]
# then full-file inspection:
cat "$A/meeting-notes.md"; cat "$B/meeting-notes.md"
cat "$A/incident-postmortem.md"; cat "$B/incident-postmortem.md"
cat "$A/contact-page.html"; cat "$B/contact-page.html"
grep -nE "ghp_|hunter2|marcus|/Users/" "$B/deploy.py"
```

> **Process note:** the coarse full-string grep initially mis-reported `MacBook Air M4` as "redacted" in Run A and flagged "Acme" as surviving (it was `acmecorp.internal` inside the un-redacted DSN, matched case-insensitively). Full-file inspection corrected both. Lesson: substring greps over-/under-count redaction; eyeball the output.

---

## 9. Artifacts produced

```
/tmp/redaction-dogfood/
├── TEST-PLAN.md                      # acceptance criteria + plan
├── baseline.sha256                   # AC8 reference hashes
├── config.ner-only.yaml              # Run A config
├── config.dogfood.yaml               # Run B config (custom_keywords)
├── input/                            # mock corpus (5 files; originals, unmodified)
│   ├── meeting-notes.md
│   ├── contact-page.html
│   ├── incident-postmortem.md        # mock post-mortem
│   ├── deploy.py                     # copy-through leak demo
│   └── readme.txt                    # copy-through leak demo
├── tool/                             # sandboxed copy of redact.py + .venv (NOT the repo)
└── output/
    ├── TEST-RESULTS.md               # this file
    ├── run-a-ner-only/               # redacted output, NER only
    └── run-b-with-keywords/          # redacted output, NER + custom_keywords
```

---

## 10. Next steps — path to production

Staged roadmap (both targets, sequenced) + two trust bars shown side-by-side. **Phase 1 must finish before Phase 2** — no point repo-scrubbing with an engine that over-redacts and misses names.

### Phase 1 — make the *current* tool (Notion-export contract) trustworthy

Blocking correctness + accuracy work surfaced by this dogfood:

| Step | Addresses | Type | Notes |
|---|---|---|---|
| P1.1 | B3 over-redaction | **Correctness blocker** | Stop merged/overlapping spans eating adjacent chars + newlines. Clamp spans to detected bounds; add a regression test that asserts no non-PII char is removed. |
| P1.2 | B1/B2 recall | **Accuracy blocker** | Re-run on `en_core_web_lg`, re-score. If recall still misses, evaluate a transformer model (`en_core_web_trf`) or GLiNER. Keyword-backstop for known entities. Set a recall target (see "exit gate"). |
| P1.3 | B4 IP/URL | Coverage | Add `IP_ADDRESS` (and likely `URL`) to `entities`. |
| P1.4 | B6 Python floor | Env/repro | Pin a 3.9-compatible spaCy OR bump documented floor to 3.11; fix `setup.sh` version check + README claim. |
| P1.5 | B7 warnings | Polish | `labels_to_ignore` for `CARDINAL`/`PRODUCT`/`MONEY`. |
| P1.6 | AC11 | Verification | Actually instrument the "no network" guarantee (run under `nettop`/Little Snitch or a network-denied namespace), don't assert it. |
| P1.7 | regression | Test harness | Promote this dogfood corpus → **golden test**: fixed inputs + expected outputs + a runner that diffs. Re-runnable on every change. |

**Phase 1 exit gate:** golden tests pass, over-redaction fixed, recall measured ≥ target on `lg`, no-network verified.

### Phase 2 — repo-anonymizer (the end goal; the README backlog, now sequenced)

Only after Phase 1. Layers the repo use-case on the hardened engine:

| Step | Addresses | Notes |
|---|---|---|
| P2.1 | repo-mode | Add code/config extensions to `include_extensions`; exclude `.git/`; scrub to a clean *copy*, push that. |
| P2.2 | code safety | Don't write `█████` into code (breaks syntax) — comment-safe `find→replace`. |
| P2.3 | git metadata | Scrub commit author name/email + `.git/config` — file-content redaction ignores these entirely. |
| P2.4 | secrets (B5) | Integrate **gitleaks** (pre-push hook) for tokens/session IDs/DSNs. Add `.gitleaksignore` for the `tests/` fixtures (they contain fake secret-shaped strings by design). |
| P2.5 | personal tells | Seed `custom_keywords` with name, email, `/Users/<name>`, hardware specs, codenames — the safety net for everything NER can't infer. |
| P2.6 | human gate | **Mandatory manual review** before any public push. Non-negotiable; no tool guarantees zero leaks. |

**Phase 2 exit gate:** repo-mode + gitleaks + git-metadata scrub all green on a representative repo, keyword list built, human review checklist in place.

### Trust-bar difference — what "production" demands at each level

You asked to see the gap. Same roadmap; the bar decides how much rigor each step needs.

| Dimension | **Tier A — personal, attended** (only you, your data) | **Tier B — others depend on it / unattended** (adds to Tier A) |
|---|---|---|
| Bug fixes | P1.1–P1.6 done | same |
| Tests | Golden regression passes locally (P1.7) | **+ CI** runs golden + recall benchmark on every change |
| Failure mode | Dry-run first; you eyeball output | **+ fail-loud:** error/exit on low-confidence spans or unknown file types — never silent copy-through |
| Accuracy proof | Recall "good enough" on your corpus | **+ benchmark** on a labeled dataset with a published recall threshold + per-entity-type breakdown |
| Error handling | OK to crash on a weird file, you re-run | **+ robust:** per-file error isolation, no half-written output, structured run report |
| Packaging | venv + README | **+ pinned lockfile, versioned releases, entry point, `--version`** |
| Docs | README + this report | **+ explicit threat model + "what this does NOT catch"** stated up front |
| Config | hand-edited YAML | **+ schema validation** with clear errors |
| Security review | self-review | **+ adversarial false-negative testing** across diverse data (one corpus ≠ proof) |

**Blunt exit definition.** A redaction tool can't promise zero leaks. "Production-ready" here =
1. **measured** recall above a stated threshold (not "looks fine on one file"),
2. **fail-loud** on uncertainty rather than silently passing data through,
3. a **secret-scanner layer** (gitleaks) for the high-entropy class NER can't do, and
4. a **human review gate** for anything going public.
Tier A satisfies 1, 3, 4 informally + a golden test. Tier B makes all four enforced, automated, and documented.

### Immediate next action (this session's priority)

Repo init + public is the active goal — **independent of finishing the tool.** Decouple: the repo can go public *now* via a one-time manual gitleaks + eyeball pass on the actual repo contents. The tool roadmap above is for *repeatable* future scrubs, not a blocker for the first publish.

