# redaction-tool

Local, air-gapped PII redaction CLI. No network calls at runtime. Handles
text (`.md .txt .html .json .csv`) and binary (`.pdf` + images) formats.

Three find modes (set via `entities` + `regex_only` in config):
- **Keyword-only** (`entities: []`) — deterministic find→replace from
  `custom_keywords`, **no spaCy model loaded for text-only input** (the model
  loads only when an image/PDF is present, for OCR matching). Stdlib-fast,
  auditable. Engine: `keyword_redactor.py` (no deps).
- **Regex-only** (`regex_only: true`) — skips the spaCy model entirely; matches
  only regex-based entity types (EMAIL_ADDRESS, URL, PHONE_NUMBER, CREDIT_CARD, …)
  + custom keywords via Presidio `PatternRecognizer` subclasses directly. NER types
  (PERSON, ORGANIZATION, …) are silently skipped → MODEL ENTITIES shows N/A. Fast,
  deterministic — cuts large-JSON runs from minutes to seconds.
- **NER** (`entities` non-empty, `regex_only: false`) — spaCy/Presidio detects
  names/orgs/etc. Add `URL` to `entities` to redact http(s) URLs to `[URL]` (a
  blanket `(?i)https?://\S+` recognizer; opt-in, off unless `URL` is listed).

Plus a discovery mode: **`--scan`** lists candidate identities (NER) by entity
type, writing nothing — to seed `custom_keywords` before redacting.

Nested JSON: `decode_nested_json: true` (default) decodes string values that are
themselves JSON — double-encoded blobs like rich-text "delta" exports
(`{"richText": "[{\"text\":\"…\"}]"}`) — redacts the inner text, then re-encodes,
so NER reads clean prose instead of tagging JSON markup as bogus entities. Fully
generic (recurses any nesting depth; no field names assumed).

Modules: `redact.py` (CLI + handlers), `keyword_redactor.py` (stdlib keyword
engine), `report_format.py` (stdlib unified end-of-run report + scan report), `gen_keywords.py`
(stdlib helper: a names list → `custom_keywords` YAML).

## Config files

`config.yaml` is **gitignored** — it holds your real redaction terms (PII).
`demo.config.yaml` is the committed, clean template. First use:

```bash
cp demo.config.yaml config.yaml      # then edit config.yaml with your real terms
```

The tool defaults to `config.yaml`, so `python redact.py <dir>` uses your local
(gitignored) config automatically — no `--config` needed.

## Commands

```bash
# setup.sh auto-selects python3.11 (falls back to a newer 3.x if absent), builds
# the venv, installs deps, and downloads the model. Tested on 3.11 only.
bash setup.sh

# Manual equivalent (system python3 is 3.9 — too old; build with 3.11):
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt                  # click is pinned in requirements
python -m spacy download en_core_web_sm

cp demo.config.yaml config.yaml                   # first run: make your local config
python redact.py <dir> --dry-run                 # preview (no files written)
python redact.py <dir>                            # redact → <dir>/redacted/
python redact.py <dir> --scan                     # discover identities (no writes)
python redact.py <dir> --include .md,.txt         # process only these types this run
python gen_keywords.py names.md                   # names list → custom_keywords YAML (stdout)
python redact.py <dir> --full-throttle           # dupe-check names_file → propagate → redact (one shot)
```

## Tests

```bash
.venv/bin/python -m unittest discover -s tests    # full suite (under the venv)
```
Stdlib-only modules (`keyword_redactor`, `report_format`, `gen_keywords`,
scan/leak-guard logic) also run under system `python3`.

## Gotchas

- Always dry-run first — no undo; originals never modified but output is permanent
- `copy_unhandled: false` (default) = unhandled types (.zip/.xlsx/…) are NOT copied into `redacted/` (leak guard); set true to mirror the input
- `custom_keywords` matching is CASE-INSENSITIVE, word-boundary
- Apple Vision OCR (macOS) >> Tesseract; check setup output for which is active
- `include_extensions` is an enforced allowlist (only listed + handled types are processed); `--include .md,.txt` overrides it per run; `skip_extensions` is checked first
- Re-runs never re-redact own output: a scan skips any nested dir named `redacted`/`redacted-*` (and `redaction-report*.md`), so re-running a folder after adding keywords is safe and won't nest prior output. Exception: pointing the tool *directly at* a `redacted-*` dir (as the input) processes it. Originals are read-only — never renamed/modified (`_is_own_output_dir`, redact.py)
- `URL` entity (add to `entities`) → http(s) URLs redacted to `[URL]`
- Every run (dry-run AND real) prints the SAME unified report — PATTERN MATCHES (regex) / MODEL ENTITIES (NER) / CUSTOM KEYWORDS (blacked out vs replaced), per-group subtotals + grand total; the real run adds an `Output at:` line. Itemizes text and image/PDF matches alike

## Config

`config.yaml` controls: `entities` (incl. `URL`), `custom_keywords` (find→replace
overrides), `replacement` char, `spacy_model`, `output_dir`, `copy_unhandled`
(leak guard), `decode_nested_json` (decode double-encoded JSON values),
`regex_only` (skip spaCy; regex entities + keywords only), `tight_image_boxes`
(word-level image redaction), `report` (persist the end-of-run report to disk:
`true` → `<dir>/redaction-report.md`, or a path string; `--report` overrides it),
`timestamp_outputs` (suffix a per-run `YYYYMMDD-HHMMSS` onto the redacted dir + default
report — testing aid), `names_file` (`--full-throttle`'s names list, default `names.md`),
`skip_extensions`, OCR settings.
