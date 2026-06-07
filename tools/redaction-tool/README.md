# redaction-tool

> **Status:** v0.1 — early and experimental.
>
> **Caveat emptor:** evals are still a TODO — verify redaction completeness yourself before trusting it on sensitive data.

A fully local, air-gapped PII redaction tool for Notion exports. Scans a Notion export folder and produces a clean copy with names, emails, phone numbers, and other sensitive data removed — no network calls, no cloud APIs, no data leaving your machine.

## How it works

- **Text files** (`.md`, `.txt`, `.html`, `.json`, `.csv`) — redacted by deterministic find→replace from your keyword list (case-insensitive), and/or spaCy + [Presidio](https://github.com/microsoft/presidio) NER. JSON is **values-only** (keys/numbers untouched) and re-serialized as valid JSON; CSV redacts every cell. Replacement is a configurable placeholder (default `█████`) or your own per-keyword pseudonyms.
- **PDFs** — digital text pages use PyMuPDF's native redaction annotations to permanently remove text from the PDF structure; scanned pages are OCR'd and PII regions are blacked out as pixels
- **Images** (`.png`, `.jpg`, `.gif`, `.webp`) — OCR locates PII, then black filled rectangles are drawn over those regions
- **Unhandled types** (`.zip`, `.xlsx`, …) are **not** copied into `redacted/` by default (leak guard — an unredacted file there looks safe and isn't); set `copy_unhandled: true` to mirror them. Originals are never modified.

There are two find modes: **keyword-only** (`entities: []` — no spaCy model for text-only input, fast + auditable) and **NER**. A discovery mode, **`--scan`**, lists candidate identities without redacting (see below).

OCR runs via Apple Vision (on-device Neural Engine, preferred) with an automatic fallback to Tesseract.

## Requirements

- **Python 3.10+ for the venv** — build it with `python3.11`. The spaCy stack needs `thinc>=8.3.12`, which requires Python ≥3.10; a 3.9 venv fails to install. (The stdlib-only parts run on 3.9.)
- macOS (Apple Silicon recommended for Vision OCR; Intel Macs and Linux work via Tesseract fallback)
- Homebrew (optional, for Tesseract)

## Setup

> **Note:** `setup.sh` currently hardcodes `python3` and **fails on a system Python 3.9** (the spaCy install needs ≥3.10). Use the manual setup with `python3.11` below until that's fixed.

**Manual setup:**

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt click       # 'click' is required by `spacy download`
python -m spacy download en_core_web_lg
```

This creates a `.venv`, installs dependencies, and downloads the spaCy model (~750 MB).

**Tesseract fallback (non-macOS or older macOS):**

```bash
brew install tesseract
# Uncomment pytesseract in requirements.txt, then re-run pip install -r requirements.txt
```

## Usage

```bash
source .venv/bin/activate

# Preview what would be redacted — no files are written
python redact.py /path/to/notion-export --dry-run

# Redact — output goes to /path/to/notion-export/redacted/
python redact.py /path/to/notion-export

# Discover: list candidate identities (NER) without redacting — to seed custom_keywords
python redact.py /path/to/notion-export --scan

# Use a specific config file
python redact.py /path/to/notion-export --config /path/to/config.yaml
```

Recommended flow for trustworthy keyword redaction: `--scan` to surface candidates → curate them into `custom_keywords` (with `entities: []`) → redact → **review the output yourself** before sharing.

After a run, a summary is printed:

```
Total redactions : 142
Markdown files   : 38
HTML files       : 12
PDF files        : 5
Image files      : 8
Copied unchanged : 201
Skipped entirely : 3
Errors           : 0
Output at        : /path/to/notion-export/redacted
```

## Configuration

Edit `config.yaml` to adjust behavior. All keys are optional — the tool ships with sensible defaults.

```yaml
# Entity types for Presidio/spaCy to detect
entities:
  - PERSON
  - EMAIL_ADDRESS
  - PHONE_NUMBER
  - ORGANIZATION
  - LOCATION
  # Additional options: US_SSN, CREDIT_CARD, IBAN_CODE, IP_ADDRESS, NRP

# Exact strings to always redact, regardless of NLP confidence
custom_keywords:
  - "Contoso"                    # replaced with the default placeholder
  - find: "John Smith"           # replaced with a custom string
    replace: "J.S."
  - find: "Acme Corp"
    replace: "[CLIENT-A]"

replacement: "█████"             # placeholder text for Markdown/HTML output
spacy_model: en_core_web_lg      # en_core_web_sm (~12 MB) or en_core_web_md (~43 MB) for faster/smaller
output_dir: "redacted"           # created inside the input directory

include_extensions:              # file types to actively process
  - .md
  - .html
  - .htm
  - .pdf
  - .png
  - .jpg
  - .jpeg
  - .gif
  - .webp

skip_extensions:                 # excluded entirely — not copied either
  - .mp4
  - .mov
  - .m4v

ocr:
  use_apple_vision: true         # preferred on macOS
  fallback_tesseract: true       # used if Apple Vision is unavailable
  dpi: 200                       # resolution for rendering scanned PDF pages before OCR
```

**Changing the spaCy model:** update `spacy_model` in `config.yaml` and re-run `setup.sh` (or `python -m spacy download <model>`) to download the new model.

## Leak guard: unhandled file types

By default, files redact.py doesn't handle (e.g. `.zip`, `.xlsx`, `.docx`) are **not** copied into `redacted/` — they're reported as "Not copied (unhandled)" and left in the source. Reason: an *unredacted* file sitting in a folder named `redacted/` looks safe and isn't (a leak vector if you share or feed `redacted/` to a cloud RAG). To mirror the input instead (copy unhandled files through unchanged), set `copy_unhandled: true` in `config.yaml`.

## Keyword-only mode (no-spaCy fast path)

Set `entities: []` in `config.yaml` to run **keyword-only** — deterministic find→replace from your `custom_keywords`, no NER. Text files (Markdown, HTML) are redacted by a small stdlib engine (`keyword_redactor`), and the 750 MB spaCy model is loaded **only when it's actually needed** — i.e. when an image or PDF is present (those still need the analyzer to match keywords against OCR'd text):

| Mode | Image/PDF in the input? | spaCy model |
|---|---|---|
| Keyword-only (`entities: []`) | none (or all in `skip_extensions`) | **not loaded** — fast |
| Keyword-only (`entities: []`) | yes (not skipped) | loaded (for the image/PDF path) |
| NER (`entities` non-empty) | any | loaded |

So a **text-only keyword run loads no model at all**. To guarantee the fast path even if stray images are present, add image/PDF types to `skip_extensions`.

## Supported entity types

| Type | Examples |
|---|---|
| `PERSON` | Names of individuals |
| `EMAIL_ADDRESS` | `user@example.com` |
| `PHONE_NUMBER` | `+1 (555) 000-0000` |
| `ORGANIZATION` | Company and institution names |
| `LOCATION` | Cities, addresses, countries |
| `US_SSN` | `123-45-6789` |
| `CREDIT_CARD` | Card numbers |
| `IBAN_CODE` | Bank account numbers |
| `IP_ADDRESS` | `192.168.1.1` |
| `NRP` | Nationalities, religions, political groups |

## Privacy guarantee

No network requests are made at runtime. The spaCy model and all OCR inference run locally. The tool is safe to use on air-gapped machines or with data that cannot leave your environment.

## Backlog — repo-anonymizer adaptation (deferred)

Goal: reuse this tool to scrub a code repo of identifying info before making it public. Investigated 2026-05-28; deferred (no easy fix — needs build + a complementary secret-scanner). Two distinct problems, two tools:

- **Identity entities** (names, person, company, location, hardware specs, codenames, "a work") → this tool.
- **Secrets / session IDs / tokens** → [gitleaks](https://github.com/gitleaks/gitleaks), NOT this tool. Presidio/spaCy is weak on high-entropy tokens and has no `API_KEY` entity.

Backlog items:

- [ ] **Test this tool end-to-end manually first** (against a sample dir in `/tmp/`) to understand its behavior before adapting. Prerequisite for everything below.
- [ ] **Add code/config types to `include_extensions`** (`.py .yaml .json .sh .toml .txt`). Today `.py` files are *copied unchanged* — names in comments, docstrings, and paths leak straight through.
- [ ] **Exclude `.git/` from the walk.** The tool reads file contents and ignores git; commit author name/email is untouched otherwise. Git metadata (author/email in `git log`, `.git/config`) is a separate scrub from file content.
- [ ] **Seed `custom_keywords` with personal tells**: name, email, `/Users/<name>` home path, hardware specs (e.g. `MacBook Air M4`, `16GB`), company, project codenames. NER cannot *infer* "this is a hardware spec" — exact-match `custom_keywords` is the only thing that catches these, so this list IS the safety net for everything NER misses.
- [ ] **Don't use `█████` in code files** — the block char can break syntax. Use comment-safe `find→replace` mappings for code.
- [ ] **Integrate gitleaks** as a pre-push hook for secrets/session IDs (build-vs-buy: battle-tested, local, no build).
- [ ] **Mandatory human review pass** before any public push. NER false-negatives + anything not in the keyword list will slip through; no tool gives a guarantee.

Recommended stack once built: gitleaks (secrets) + this tool in repo-mode (identity) + human eyeball pass.

> **Status update (2026-05-29):** the "test end-to-end" item above is **done** — dogfooded in a sandbox; see `tests/TEST-RESULTS.md` (verdict: plumbing passes, but recall misses names/orgs on the small model and the engine over-redacts; gap premise confirmed). The full production roadmap lives in `tests/TEST-RESULTS.md` §10.

### Enforcement & integration paths (where each guard runs — and when)

For "stop PII/secrets before a public push," **timing is everything**. For a public repo, `git push` = instantly public; anything that runs *after* the push is too late to prevent the leak (and git history remembers it even after deletion). Candidate paths, from earliest/strongest to latest:

- [ ] **Local pre-commit hook (block).** Runs on your machine before the commit is even recorded. Earliest gate. Scans the staged diff; refuses the commit if it finds secrets/PII. Tool: [gitleaks](https://github.com/gitleaks/gitleaks) (via [pre-commit](https://pre-commit.com/) framework or a raw git hook). **This is the primary "before it hits GitHub" guard.**
- [ ] **Local pre-push hook (block).** Last gate on your machine before bytes leave for GitHub. Same scanner, catches anything committed before the hook existed. Belt-and-suspenders with pre-commit.
- [ ] **GitHub CI secret-scan (backstop, NOT a first line).** GitHub Actions runs *after* the push — so for a **public** repo it cannot prevent the leak, only alert. Useful as: (a) a backstop while the repo is still **private** (push isn't public yet), and (b) catching what slipped a missing/disabled local hook. Also consider GitHub **Push Protection / secret scanning** (server-side, can block pushes of known secret patterns).
- [ ] **GitHub CI golden tests (tests the *tool*, not your content).** Separate job: run `tests/` golden corpus + recall benchmark on every change to `redact.py` so a regression (e.g. over-redaction, dependency drift like the Python 3.9→3.11 break) is caught automatically. This is the Tier-B "CI" item from the roadmap — it verifies the redactor's own correctness, it does **not** scan your repo for PII.
- [ ] **`redact.py` to produce a shareable *copy* (rewrite, not a gate).** Use only when you want a redacted duplicate to hand out (e.g. a Notion export). Do **not** wire it into commit/push — it rewrites content (`█████`) and would mangle your real source files. Destructive by design; wrong tool for a push gate.
- [ ] **Mandatory human review (final, irreplaceable).** Scanners only catch pattern-shaped things; novel PII — your name, codenames, idiosyncratic tells — needs eyes. No automated layer removes this step before a public push.

**Defense in depth:** local hook (block) **+** human review **+** CI backstop. The local hook is the piece that actually answers "scan every push and stop PII before it reaches GitHub." CI is for *testing the tool* and as a *private-repo backstop* — never the first line for a public repo.

> **Distinction worth keeping straight:** *redaction* (rewrite content → `█████`, this tool) vs *scanning* (detect + block, gitleaks) vs *CI* (run tests after push, GitHub Actions). Three different jobs; only the scanner-as-local-hook prevents a public leak.
