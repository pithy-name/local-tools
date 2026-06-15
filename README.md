# local-tools

A small collection of local-first command-line tools for working with files and documents on your own machine. No cloud services, no network calls at runtime — everything runs locally.

## Tools

| Tool | What it does |
|---|---|
| [`redaction-tool`](tools/redaction-tool/) | Air-gapped PII redaction for a folder of files (names, emails, phones, etc.) across Markdown, HTML, JSON, CSV, PDF, and images. Uses spaCy + Presidio + on-device OCR. |
| [`convert-to-md`](tools/convert-to-md/) | Convert `.docx` and `.html` files to Markdown. |
| [`find-duplicates`](tools/find-duplicates/) | Find duplicate files by content hash (not filename) and report them oldest → newest. |
| [`find-files`](tools/find-files/) | Find files by extension, recursively. |
| [`find-empty-folders`](tools/find-empty-folders/) | Report folders whose subtree contains zero files. |
| [`search-session-logs`](tools/search-session-logs/) | Full-text search across session-log Markdown files. |

Each tool lives in its own folder under `tools/` with a README containing both a terse technical reference and a step-by-step walkthrough for non-technical users.

## Requirements

- Python 3.11+
- macOS recommended (the redaction tool uses Apple Vision OCR with a Tesseract fallback); the plain file utilities are cross-platform.

Most utilities run with no setup:

```bash
python3 tools/<tool>/<script>.py
```

The redaction tool has its own virtualenv — see [`tools/redaction-tool/README.md`](tools/redaction-tool/README.md).

## For AI agents

See [`CLAUDE.md`](CLAUDE.md) for repository structure, commands, and working conventions.
