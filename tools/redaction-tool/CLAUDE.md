# redaction-tool

Local, air-gapped PII redaction CLI. No network calls at runtime. Handles
text (`.md .txt .html .json .csv`) and binary (`.pdf` + images) formats.

Two find modes (set via `entities` in config):
- **Keyword-only** (`entities: []`) — deterministic find→replace from
  `custom_keywords`, **no spaCy model loaded for text-only input** (the model
  loads only when an image/PDF is present, for OCR matching). Stdlib-fast,
  auditable. Engine: `keyword_redactor.py` (no deps).
- **NER** (`entities` non-empty) — spaCy/Presidio detects names/orgs/etc.

Plus a discovery mode: **`--scan`** lists candidate identities (NER) by entity
type, writing nothing — to seed `custom_keywords` before redacting.

Modules: `redact.py` (CLI + handlers), `keyword_redactor.py` (stdlib keyword
engine), `report_format.py` (stdlib count + scan reports).

## Commands

```bash
# setup.sh auto-selects python3.11 (falls back to a newer 3.x if absent), builds
# the venv, installs deps, and downloads the model. Tested on 3.11 only.
bash setup.sh

# Manual equivalent (system python3 is 3.9 — too old; build with 3.11):
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt                  # click is pinned in requirements
python -m spacy download en_core_web_lg

python redact.py <dir> --dry-run                 # preview (no files written)
python redact.py <dir>                            # redact → <dir>/redacted/
python redact.py <dir> --scan                     # discover identities (no writes)
python redact.py <dir> --include .md,.txt         # process only these types this run
```

## Tests

```bash
.venv/bin/python -m unittest discover -s tests    # 54 tests (under the venv)
```
Stdlib-only modules (`keyword_redactor`, `report_format`, scan/leak-guard logic)
also run under system `python3`.

## Gotchas

- Always dry-run first — no undo; originals never modified but output is permanent
- `copy_unhandled: false` (default) = unhandled types (.zip/.xlsx/…) are NOT copied into `redacted/` (leak guard); set true to mirror the input
- `custom_keywords` matching is CASE-INSENSITIVE, word-boundary
- Apple Vision OCR (macOS) >> Tesseract; check setup output for which is active
- `include_extensions` is an enforced allowlist (only listed + handled types are processed); `--include .md,.txt` overrides it per run; `skip_extensions` is checked first

## Config

`config.yaml` controls: `entities`, `custom_keywords` (find→replace overrides),
`replacement` char, `spacy_model`, `output_dir`, `copy_unhandled` (leak guard),
`skip_extensions`, OCR settings.
