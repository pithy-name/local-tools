# redaction-tool

> **Status:** v0.2 — early and experimental.
>
> **Caveat emptor:** text redaction is deterministic — it replaces exactly the terms you
> configure — but it only catches what you list (and NER auto-detection, if enabled, still
> misses some names/orgs). **Image and PDF redaction rely on OCR, which can miss text or
> misplace the black boxes.** Always review the output — especially redacted images and
> PDFs — before trusting it on sensitive data.
>
> **Presidio warning suppression:** the tool silences Presidio's per-entity `"Entity X is not
> mapped to a Presidio entity"` log lines (for spaCy types like `CARDINAL`, `MONEY`, `PRODUCT`
> that Presidio has no recognizer for). These are noise — the entities are filtered from output
> regardless — but the suppression uses a log-message filter, not Presidio's native
> `labels_to_ignore`. If you add a custom Presidio recognizer for one of those spaCy entity types
> and see unexpected behavior, disable the filter by commenting out the `_NoMappingFilter` block
> in `build_analyzer()`.
>
> **Reading the report:** the per-keyword `blackout` column (image/PDF redaction counts) is one of:

| `blackout` shows | meaning |
|---|---|
| `N/A` | no images/PDFs were processed — not applicable to this run |
| `0` | images/PDFs were processed, but this keyword wasn't matched in them |
| `N` (a count) | the keyword was blacked out N times in images/PDFs |

A fully local, air-gapped PII redaction tool. Point it at a folder of files; it writes a
redacted copy with names, emails, phone numbers, and other sensitive data removed. No
network calls, no cloud — nothing leaves your machine.

## Prerequisites

- **macOS** (Apple Silicon recommended — OCR runs on the Neural Engine; Intel/Linux fall
  back to Tesseract).
- **Python 3.11** — install with `brew install python@3.11`. Tested on 3.11 only;
  `setup.sh` accepts a newer 3.x but it's untested.

## Setup

```bash
bash setup.sh    # picks python3.11, builds .venv, installs deps, downloads the model (~750 MB, once)
```

<details><summary>Manual setup / non-macOS OCR</summary>

```bash
python3.11 -m venv .venv                   # create the virtual environment
source .venv/bin/activate                  # activate it
pip install -r requirements.txt            # install dependencies
python -m spacy download en_core_web_lg    # download the NER model (~750 MB)
```
Non-macOS OCR: `brew install tesseract`, then uncomment `pytesseract` in `requirements.txt`.
</details>

## Removing the model

To reclaim the ~750 MB used by `en_core_web_lg`:

```bash
source .venv/bin/activate
pip uninstall en_core_web_lg
```

To wipe the entire virtual environment and start fresh:

```bash
rm -rf .venv
bash setup.sh    # re-run setup when you want it back
```

## Redact a folder

The tool runs on a **folder** (not a single file — that's a known TODO). Finish Setup, then:

```bash
source .venv/bin/activate            # 0. activate the venv (once per terminal)

python redact.py <folder> --dry-run  # 1. preview: reports what WOULD change, writes nothing
python redact.py <folder>            # 2. redact for real: writes to <folder>/redacted/
```

The dry-run report shows totals, per-file-type counts, and per-keyword hit counts. After a
real run, **open `<folder>/redacted/` and review it yourself** before sharing — recall isn't
guaranteed (see the caveat).

**Optional — discover terms first.** `--scan` lists candidate names/orgs it detects, but
**writes nothing and changes no config**:

```bash
python redact.py <folder> --scan     # lists candidate identities to the screen
```
You then copy the ones you want into `custom_keywords` in `config.yaml` yourself, and redact.

## Which mode do I want?

`entities` in `config.yaml` (plus whether the folder has images/PDFs) decides whether the
750 MB model loads:

| Goal | `entities` | Input | 750 MB model? |
|---|---|---|---|
| Fast, deterministic redaction from your own keyword list | `[]` | text only (`.md .txt .html .json .csv`) | **No** — stdlib only |
| Same, but the folder has images/PDFs | `[]` | with images/PDFs | **Yes** (for OCR matching) |
| Auto-detect names/orgs/etc. *(default config)* | populated | any | **Yes** |
| Discover candidate identities, write nothing | — | `--scan` | **Yes** |

A **text-only, keyword-only** run loads no model: fast and fully auditable. The default
config ships in NER mode, so the model loads.

## How it works

- **Text** (`.md .txt .html .json .csv`) — find→replace from your `custom_keywords`
  (case-insensitive) and/or NER. JSON redacts values only (valid JSON out); CSV redacts every cell.
- **PDFs** — digital text is truly removed from the file; scanned pages are OCR'd and blacked
  out. *(`.pdf` is in `skip_extensions` by default — remove it there to process PDFs.)*
- **Images** (`.png .jpg .gif .webp`) — OCR locates PII, black boxes are drawn over it.
- **Unhandled types** (`.zip .xlsx …`) are **not** copied into `redacted/` by default (a leak
  guard — an unredacted file in `redacted/` looks safe and isn't). Set `copy_unhandled: true`
  to mirror them. Originals are never modified.

## The tech (what's under the hood)

| Job | Tool | What it does |
|---|---|---|
| Deterministic keyword redaction | `keyword_redactor.py` (Python stdlib, no deps) | case-insensitive, word-boundary find→replace — the reliable path; catches exactly the terms you list |
| **The NER model** | **`en_core_web_lg`** — a spaCy pipeline (~750 MB) | "the model" referred to throughout: the ~750 MB artifact `setup.sh` downloads — a pre-trained statistical pipeline that performs NER. Swappable for the smaller `en_core_web_md` / `_sm`. |
| Entity detection — **NER** | [spaCy](https://spacy.io) (loads + runs the model) | **NER = Named Entity Recognition** — the *task* of reading text and labeling spans as PERSON / ORGANIZATION / LOCATION etc. by *inferring* what's a name, not matching a list. spaCy is the library that runs the model. Probabilistic → imperfect recall. |
| Structured-PII detection | [Microsoft Presidio](https://github.com/microsoft/presidio) | recognizers (regex + context) for emails, phones, SSNs, credit cards, IPs, layered on spaCy; orchestrates detect → anonymize |
| OCR — preferred | Apple Vision | on-device text recognition on the M-series Neural Engine; reads text out of images / scanned pages locally, no network |
| OCR — fallback | [Tesseract](https://github.com/tesseract-ocr/tesseract) | open-source OCR engine; the cross-platform fallback used only when Apple Vision isn't available |
| PDF redaction | [PyMuPDF](https://pymupdf.readthedocs.io) (`fitz`) | digital pages: redaction annotations remove the underlying text from the file; scanned pages: render → OCR → black box → reinsert |
| Image redaction | [Pillow](https://python-pillow.org) | draws the black rectangles over located PII regions |
| HTML parsing | [BeautifulSoup](https://www.crummy.com/software/BeautifulSoup/) | redacts the text nodes in `.html` |

So a keyword-only text run touches **none** of the model/OCR stack — just the stdlib engine.

## Configuration

`config.yaml` is fully commented — open it for every option. The knobs you'll touch most:

- `entities` — NER types to detect; `[]` = keyword-only (see the mode table). Available:
  `PERSON, EMAIL_ADDRESS, PHONE_NUMBER, ORGANIZATION, LOCATION, US_SSN, CREDIT_CARD,
  IBAN_CODE, IP_ADDRESS, NRP`.
- `custom_keywords` — exact strings to always redact; plain (`█████`) or `find:`/`replace:`
  for your own pseudonyms.
- `include_extensions` — allowlist of types to process; override per run with `--include .md,.txt`.
- `skip_extensions` — types ignored entirely (default: `.pdf .mp4 .mov .m4v`).
- `copy_unhandled` — mirror unhandled types into `redacted/` (default `false`).

## After a run

```
────────────────────────────────────────────────────
  Total redactions : 142
  Markdown files   : 38
  HTML files       : 12
  JSON files       : 4
  CSV files        : 2
  PDF files        : 0
  Image files      : 0
  Copied unchanged : 201
  Not copied (unhandled) : 3
  Skipped entirely : 5
  Errors           : 0
  Output at        : /path/to/folder/redacted

  Note: 3 unhandled file(s) were NOT copied into redacted/ (leak guard)...
    not copied: archive.zip
    not copied: scans/old.tiff
    not copied: notes.xlsx

  Per-pseudonym counts (text-sub | blackout):
    [CLIENT-A]  (Acme Corp)  text-sub: 12  blackout: N/A
      └─ [CLIENT-A] subtotal  text-sub: 12  blackout: N/A
    J.S.  (John Smith)  text-sub: 7  blackout: N/A
      └─ J.S. subtotal  text-sub: 7  blackout: N/A
  Total text-subs : 19
  Total blackouts : N/A
```

## Privacy

No network requests at runtime — the model and OCR run locally. Safe on air-gapped machines
or data that can't leave your environment.
