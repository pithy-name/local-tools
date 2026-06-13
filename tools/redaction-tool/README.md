# redaction-tool

> **Status:** v0.2 — early and experimental.

A fully local, air-gapped PII redaction tool. Point it at a folder of files; it writes a redacted copy with names, emails, phone numbers, and other sensitive data removed. No network calls, no cloud — nothing leaves your machine.

> **Caveat emptor:** text redaction is deterministic — it replaces exactly the terms you configure — but it only catches what you list (and NER auto-detection, if enabled, still misses some names/orgs). **Image and PDF redaction rely on OCR, which can miss text or misplace the black boxes.** Always review the output — especially redacted images and PDFs — before trusting it on sensitive data.

## Prerequisites

- **macOS** (Apple Silicon recommended — OCR runs on the Neural Engine; Intel/Linux fall back to Tesseract, **untested**).
- **Python 3.11** — install with `brew install python@3.11`. Tested on 3.11 only; `setup.sh` accepts a newer 3.x but it's untested.

## Setup

```bash
bash setup.sh    # picks python3.11, builds .venv, installs deps, downloads the spaCy model (once)
```

**Then create your config** (one-time). `config.yaml` is gitignored — it's where your real redaction terms live — so the repo ships only the `demo.config.yaml` template. Copy it:

```bash
cp demo.config.yaml config.yaml    # then edit config.yaml with your terms
```
The tool defaults to `config.yaml`, so `python redact.py <dir>` picks up your local config automatically. Keep your real names/addresses in `config.yaml` (never committed), not in `demo.config.yaml`. Choose the NER model via `spacy_model` (the size/accuracy trade-off is documented in `demo.config.yaml`); run `setup.sh` *after* creating `config.yaml` so it downloads the model you picked — otherwise it defaults to `en_core_web_lg`.

<details><summary>Manual setup / non-macOS OCR</summary>

```bash
python3.11 -m venv .venv                   # create the virtual environment
source .venv/bin/activate                  # activate it
pip install -r requirements.txt            # install dependencies
python -m spacy download en_core_web_sm    # download the NER model (match spacy_model in config.yaml)
```
Non-macOS OCR: `brew install tesseract`, then uncomment `pytesseract` in `requirements.txt`. **Untested** — only Apple Vision OCR (macOS) has been verified; the Tesseract fallback path has not been exercised.
</details>

## Redact a folder

The tool runs on a **folder** (not a single file — that's a known TODO). Finish Setup, then:

```bash
source .venv/bin/activate            # 0. activate the venv (once per terminal)

python redact.py <folder> --dry-run  # 1. preview: reports what WOULD change, writes nothing
python redact.py <folder>            # 2. redact for real: writes to <folder>/redacted/
```

Both `--dry-run` and a real run print the same itemized report — totals, per-file-type counts, and the grouped breakdown of every match (see *After a run*). After a real run, **open `<folder>/redacted/` and review it yourself** before sharing — recall isn't guaranteed (see the caveat).

**Optional — discover terms first.** `--scan` lists candidate names/orgs it detects, but **writes nothing and changes no config**:

```bash
python redact.py <folder> --scan     # lists candidate identities to the screen
```
You then copy the ones you want into `custom_keywords` in `config.yaml` yourself, and redact.

## Which mode do I want?

Two independent choices decide everything:

1. **Detection mode** — set by `entities` + `regex_only`:
   - **Keyword-only** (`entities: []`) — redact only your `custom_keywords`; no model.
   - **Regex-only** (`regex_only: true`) — redact the regex entity types you list (`EMAIL_ADDRESS`, `URL`, …) plus keywords; no model.
   - **NER** (Named Entity Recognition — `entities` populated, `regex_only: false`) — the spaCy model detects names/orgs/locations, *plus* everything regex-only does.
2. **File types present** — independently decide which I/O tools run (OCR, PyMuPDF, Pillow, BeautifulSoup), regardless of detection mode.

The matrix crosses those two axes. (`--scan` discovery mode is separate — see *Redact a folder*.)

**Scenarios:**

| | Config |
|---|---|
| **S1** Keyword-only · text | `entities: []`, keywords set, text files only |
| **S2** Keyword-only · +media (default) | `entities: []`, `regex_only: false`, keywords, images/PDFs present |
| **S3** Keyword-only · +media (lean) | `entities: []`, `regex_only: true`, keywords, images/PDFs present |
| **S4** Regex-only · text | `entities: [regex types]`, `regex_only: true`, text only |
| **S5** Regex-only · +media | `entities: [regex types]`, `regex_only: true`, images/PDFs present |
| **S6** NER · text | `entities: [NER types]`, `regex_only: false`, text only |
| **S7** NER · +media | `entities: [NER types]`, `regex_only: false`, images/PDFs present |

**Which engine runs** (columns ordered by `regex_only`: `any` → `true` → `false`):

| Tech stack ↓ / Config → | S1 | S3 | S4 | S5 | S2 | S6 | S7 |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| `entities` | `[]` | `[]` | regex | regex | `[]` | NER | NER |
| `regex_only` | any | `true` | `true` | `true` | `false` | `false` | `false` |
| `custom_keywords` | req | req | opt | opt | req | opt | opt |
| input | text | +media | text | +media | +media | text | +media |
| **keyword_redactor** | ✅ | 🟡ᵗ | ❌ | ❌ | 🟡ᵗ | ❌ | ❌ |
| **regex_analyzer** | ❌ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| **spaCy + NER model** | ❌ | ❌ | ❌ | ❌ | ✅\* | ✅ | ✅ |
| **Presidio** | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **OCR** | ❌ | 🟡ᵐ | ❌ | 🟡ᵐ | 🟡ᵐ | ❌ | 🟡ᵐ |
| **PyMuPDF** | ❌ | 🟡ᵖ | ❌ | 🟡ᵖ | 🟡ᵖ | ❌ | 🟡ᵖ |
| **Pillow** | ❌ | 🟡ⁱ | ❌ | 🟡ⁱ | 🟡ⁱ | ❌ | 🟡ⁱ |
| **BeautifulSoup** | 🟡ʰ | 🟡ʰ | 🟡ʰ | 🟡ʰ | 🟡ʰ | 🟡ʰ | 🟡ʰ |

**Marks:** ✅ used · ❌ not used · 🟡 used only if that file type is in the folder
- 🟡ᵗ any text file present (`.md .txt .json .csv`) · 🟡ʰ `.html`/`.htm` present · 🟡ᵖ any PDF · 🟡ⁱ an image or a scanned PDF · 🟡ᵐ an image or a scanned PDF
- `req` = keywords required or the run is a no-op · `opt` = optional · "+media" = images/PDFs present (± text files)
- **regex** = `entities` lists only regex types (`EMAIL_ADDRESS, URL, PHONE_NUMBER, CREDIT_CARD, CRYPTO, IBAN_CODE, IP_ADDRESS, US_SSN, US_BANK_NUMBER, US_DRIVER_LICENSE, US_ITIN, US_PASSPORT, MEDICAL_LICENSE`). **NER** = lists NER types (`PERSON, ORGANIZATION, LOCATION, NRP`), optionally plus regex types.

**Under the hood:**

| Tool | Job | Media | How it works |
|---|---|---|---|
| `keyword_redactor` | Keyword find→replace | Any text file | Stdlib, no deps. Sole text engine when `entities: []`. On images/PDFs, keywords go through Presidio instead. |
| `regex_analyzer` | Pattern + keyword detect, no model | Any text file, image, any PDF | Wraps Presidio recognizers — needs **Presidio**. Built only if `regex_only: true`. Never loads spaCy/model. |
| NER model (`en_core_web_*`) | Entity recognition (PERSON, ORG…) | Any text file, image, any PDF | The weights. **spaCy** runs it; inert alone. Skipped if `regex_only: true`. |
| spaCy | Load + run the NER model | Any text file, image, any PDF | The harness. No output without the **NER model**. Skipped if `regex_only: true`. |
| Presidio | Orchestrate detect → anonymize | Any text file, image, any PDF | Runs own regex recognizers + drives spaCy in NER mode, merges results. Supplies what `regex_analyzer` wraps. Keywords ride it except keyword-only text. |
| OCR (Apple Vision / Tesseract) | Read text from pixels | Image, scanned PDF | Apple Vision preferred, Tesseract fallback. Feeds text to the analyzer. Digital PDFs skip OCR. |
| `PyMuPDF` (`fitz`) | PDF read + redact | Any PDF | Digital PDF: annotations remove text. Scanned PDF: render pages → **OCR** + **Pillow**. |
| `Pillow` (PIL) | Draw black boxes | Image, scanned PDF | Opens images / renders scanned PDF pages. Boxes where **OCR** flagged. Not for digital PDF. |
| `BeautifulSoup` (bs4) | Parse HTML, redact text nodes | HTML (`.html`/`.htm`) | Parses markup so the analyzer / `keyword_redactor` see only visible text, then writes redacted text back. |

**Project links:** [spaCy](https://spacy.io) · [Presidio](https://github.com/microsoft/presidio) · [PyMuPDF](https://pymupdf.readthedocs.io) · [Pillow](https://python-pillow.org) · [BeautifulSoup](https://www.crummy.com/software/BeautifulSoup/) · [Tesseract](https://github.com/tesseract-ocr/tesseract)

**The 6 precision points:**

1. **`*` — the model loads but does zero NER work (S2).** In keyword-only mode with media, the spaCy model loads *only* so Presidio can run your **keyword** recognizers over OCR'd text. `entities: []` means NER was disabled. To skip the model entirely on a media folder, use **S3** (`regex_only: true`).
2. **`regex_only: true` gates NER off (S3/S4/S5).** `run()` takes that branch first, so spaCy never loads. It redacts **only the regex types you list in `entities`** plus keywords. NER types in `entities` are silently ignored — regex-only is *not* "all regex," you must list the types.
3. **`regex_analyzer` ❌ in NER mode does NOT mean emails are missed.** That row tracks `regex_analyzer` (only when `regex_only: true`). In NER mode (S6/S7), `EMAIL_ADDRESS`/`URL`/etc. are still matched — by Presidio's built-in recognizers inside the full engine (Presidio ✅).
4. **S3 splits work by file type:** text → `keyword_redactor`; images/PDFs → `regex_analyzer` (Presidio KW_\* recognizers). Both do keyword-only matching (`entities: []` registers no regex-entity recognizers).
5. **spaCy + NER model are one unit** — spaCy loads/runs the model; neither runs without the other, neither runs in regex-only. One row, by design.
6. **Keyword blackout vs find→replace is not a tech difference.** Same component either way; only the replacement string (`█████` vs your pseudonym) and the report subsection differ.

## Command reference — every variation

Pick the config mode first (table above), then the command. All examples assume the venv is active (`source .venv/bin/activate`).

**NER mode** (default config — `entities` populated). Detects and redacts *every* name, email, phone, org, and location the model finds — see the warning at the end of this section.

```bash
python redact.py <folder> --dry-run          # preview every detected entity, write nothing
python redact.py <folder>                     # redact for real → <folder>/redacted/
python redact.py <folder> --scan              # list candidate identities, change nothing
```

**Keyword-only mode** (`entities: []`). Redacts *only* the exact strings in `custom_keywords` — nothing else is touched. Deterministic, auditable, no model for text-only input.

```bash
python redact.py <folder> --dry-run          # preview keyword hits only
python redact.py <folder>                     # redact only your listed terms
```

**Regex-only mode** (`regex_only: true` in config). Runs Presidio's regex recognizers **for the entity types you list in `entities`** (`EMAIL_ADDRESS`, `URL`, `PHONE_NUMBER`, `CREDIT_CARD`, …) plus `custom_keywords` — but skips the spaCy model entirely. NER types (`PERSON`, `ORGANIZATION`, …) are silently skipped even if listed; `MODEL ENTITIES` shows N/A in the report. Useful when you want pattern redaction without the model overhead, or when NER is too slow on large files.

```bash
python redact.py <folder> --dry-run          # preview regex + keyword hits, no model
python redact.py <folder>                     # redact for real, no model
```

**Restrict file types for one run** (overrides `include_extensions`):

```bash
python redact.py <folder> --include .md,.txt          # only Markdown + text
python redact.py <folder> --include .json --dry-run   # only JSON, preview
```

**Two-config pattern.** `--config` swaps the *entire* config file, so keep one NER config and one keyword-only config side by side and choose at runtime:

```bash
python redact.py <folder> --config keyword-only.yaml  # explicit-terms-only run
python redact.py <folder> --config ner.yaml --dry-run # auto-detect, preview
```

> **⚠ What actually gets redacted.** In **NER mode** the tool redacts *every* span matching the entity *types* in `entities` (every PERSON, EMAIL, PHONE, ORGANIZATION, LOCATION it detects) — **not** an allow-list of specific names. `custom_keywords` are layered *on top* with your own replacements. If you want *"only the exact terms I listed get touched, nothing else,"* use **keyword-only mode** (`entities: []`). Only `--include` (file types) and `--config` (whole file) override config at runtime; `entities`, `custom_keywords`, and `replacement` are config-only.

## How it works

- **Text** (`.md .txt .html .json .csv`) — find→replace from your `custom_keywords` (case-insensitive) and/or NER. JSON redacts values only (valid JSON out); CSV redacts every cell.
- **PDFs** — digital text is truly removed from the file; scanned pages are OCR'd and blacked out. *(Processed by default; add `.pdf` to `skip_extensions` to skip them.)*
- **Images** (`.png .jpg .gif .webp`) — OCR locates PII, black boxes are drawn over it.
- **Unhandled types** (`.zip .xlsx …`) are **not** copied into `redacted/` by default (a leak guard — an unredacted file in `redacted/` looks safe and isn't). Set `copy_unhandled: true` to mirror them. Originals are never modified.

## Configuration

`demo.config.yaml` (the committed template — `cp demo.config.yaml config.yaml`) is fully commented; your real `config.yaml` is gitignored. The knobs you'll touch most:

- `entities` — entity types to detect; `[]` = keyword-only (see the mode table).
  - **Regex types** (work with `regex_only: true`, no model): `EMAIL_ADDRESS, URL, PHONE_NUMBER, CREDIT_CARD, CRYPTO, IBAN_CODE, IP_ADDRESS, US_SSN, US_BANK_NUMBER, US_DRIVER_LICENSE, US_ITIN, US_PASSPORT, MEDICAL_LICENSE`.
  - **NER types** (need the model, i.e. `regex_only: false`): `PERSON, ORGANIZATION, LOCATION, NRP`.
  - Add `URL` to redact http(s) URLs to `[URL]`.
- `custom_keywords` — exact strings to always redact; plain (`█████`) or `find:`/`replace:` for your own pseudonyms. Generate this list from a names file with `gen_keywords.py` (below).
- `decode_nested_json` — decode double-encoded JSON string values (rich-text "delta" blobs) so the analyzer reads clean text instead of NER-tagging markup (default `true`).
- `include_extensions` — allowlist of types to process; override per run with `--include .md,.txt`.
- `skip_extensions` — types ignored entirely (demo default: `.mp4 .mov .m4v` — PDFs are *not* skipped).
- `copy_unhandled` — mirror unhandled types into `redacted/` (default `false`).
- `regex_only` — skip the spaCy model entirely; redact only the **regex types you list in `entities`** + `custom_keywords` (default `false`). NER types in `entities` are silently skipped when `true`.
- `spacy_model` — which spaCy model NER loads (`en_core_web_sm` / `_md` / `_lg`); pick by the size/accuracy trade-off noted in `demo.config.yaml`.

## Generating `custom_keywords` from a names list

`gen_keywords.py` turns a plain names file into ready-to-paste `custom_keywords` YAML, so you don't hand-number pseudonyms. Input: `# PREFIX` group headers, one person per line; comma-separated names on a line are **aliases of one person** and share that person's code.

```
# ENG
Mary Bello, Mary
John Smith

# MGR
Jane Doe
```
```bash
python gen_keywords.py names.md      # prints YAML to stdout; paste under custom_keywords:
```
Numbers reset per group, zero-padded two-digit; aliases share one code:
```yaml
  - find: "Mary Bello"
    replace: "ENG01"
  - find: "Mary"
    replace: "ENG01"
  - find: "John Smith"
    replace: "ENG02"
  - find: "Jane Doe"
    replace: "MGR01"
```
Comma is the alias delimiter (so a name *containing* a comma is read as two aliases). Duplicate finds get a stderr warning. Keep your names file out of git if it holds real names.

## After a run

> **Reading the report:** every run ends with the same itemized report — `--dry-run` and a real run print identical bodies (the real run adds an `Output at:` line). Matches are grouped into **PATTERN MATCHES** (regex: emails, URLs, …), **MODEL ENTITIES** (spaCy NER: names, orgs, …), and **CUSTOM KEYWORDS** (blacked out vs. replaced), with per-group subtotals and a grand total. An empty category shows `none` (ran, matched nothing) or `N/A` (not engaged this run) with a `← reason`. The report lists matched text, so treat it as sensitive.
>
> **Presidio warning suppression:** the tool silences Presidio's per-entity `"Entity X is not mapped to a Presidio entity"` log lines (for spaCy types like `CARDINAL`, `MONEY`, `PRODUCT` that Presidio has no recognizer for). These are noise — the entities are filtered from output regardless — but the suppression uses a log-message filter, not Presidio's native `labels_to_ignore`. If you add a custom Presidio recognizer for one of those spaCy entity types and see unexpected behavior, disable the filter by commenting out the `_NoMappingFilter` block in `build_analyzer()`.

```
────────────────────────────────────────────────────
  Total redactions : 15
  Markdown files   : 4
  HTML files       : 2
  JSON files       : 4
  CSV files        : 2
  PDF files        : 0
  Image files      : 0
  Copied unchanged : 0
  Not copied (unhandled) : 3
  Skipped entirely : 5
  Errors           : 0
  Output at        : /path/to/folder/redacted

  Note: 3 unhandled file(s) were NOT copied into redacted/ (leak guard)...
    not copied: archive.zip
    not copied: scans/old.tiff
    not copied: notes.xlsx
```

...followed by the itemized report (the SAME report `--dry-run` prints, minus the `Output at:` line):

```
══════════════════════════════════════════════════════════════════
  REDACTION COMPLETE
  Output at: /path/to/folder/redacted
  Extensions scanned: .csv, .html, .json, .md        12 files scanned · 6 with matches
══════════════════════════════════════════════════════════════════

PATTERN MATCHES  (regex — deterministic)
────────────────────────────────────────────────
EMAIL_ADDRESS  (2 unique · 5 hits)               → █████
    jane.doe@example.com         ×3
    support@acme.test            ×2
URL            (1 unique · 2 hits)               → [URL]
    https://acme.test/dashboard  ×2

MODEL ENTITIES  (spaCy NER — probabilistic)
────────────────────────────────────────────────
    none   ← NER active, no matches

CUSTOM KEYWORDS — blacked out
────────────────────────────────────────────────
    N/A    ← no plain keywords configured

CUSTOM KEYWORDS — replaced
────────────────────────────────────────────────
[CLIENT-A]     (2 aliases · 8 hits)
    Acme Corp                    ×6
    Acme                         ×2

──────────────────────────────────────────────────
  GRAND TOTAL: 15 redactions across 6 files
══════════════════════════════════════════════════════════════════
```

Each subsection always prints. When it has no rows it shows one of two states, with a `← reason` note: **`none`** = the detection ran but matched nothing, or **`N/A`** = that detection wasn't engaged this run (nothing of that kind was configured — e.g. no NER types, so `MODEL ENTITIES` is `N/A`; no plain keywords, so blacked-out is `N/A`). `PATTERN MATCHES` are regex recognizers, `MODEL ENTITIES` are spaCy NER, and custom keywords split by configured intent (plain → blacked out; `find→replace` → the pseudonym, aliases grouped under it). `GRAND TOTAL` equals `Total redactions`.

## Privacy

No network requests at runtime — the model and OCR run locally. Safe on air-gapped machines or data that can't leave your environment.

## Removing the model

To reclaim the space used by the spaCy model (uninstall whichever you installed):

```bash
source .venv/bin/activate
pip uninstall en_core_web_sm    # or en_core_web_md / en_core_web_lg — whichever you installed
```

To wipe the entire virtual environment and start fresh:

```bash
rm -rf .venv
bash setup.sh    # re-run setup when you want it back
```
