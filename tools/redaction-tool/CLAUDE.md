# redaction-tool

Local PII redaction CLI for Notion exports. Air-gapped — no network calls at runtime.

## Commands

```bash
bash setup.sh                                          # one-time setup (downloads ~750 MB spaCy model)
source .venv/bin/activate
pip install -r requirements.txt                        # reinstall deps if venv rebuilt
python redact.py /path/to/notion-export --dry-run      # preview — no files written
python redact.py /path/to/notion-export                # output → input-dir/redacted/ (beside input, not here)
```

## Gotchas

- Always dry-run first — no undo; originals never modified but output is permanent
- Apple Vision OCR (macOS) >> Tesseract; check `setup.sh` output for which is active
- Changing spaCy model requires re-running `setup.sh` (or `python -m spacy download <model>`)
- No test suite — test manually with `--dry-run` on sample data

## Config

`config.yaml` controls: entity types, `custom_keywords` (exact-match overrides), `replacement` char, `spacy_model`, `output_dir`, file extensions.
