# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Workspace for local AI tooling experiments. Not a single project — a collection of independent Python CLI tools and scripts. Privacy-first: tools default to local execution, no network calls at runtime.

No build system, no top-level package, no shared dependency manifest, no test runner. Each tool is self-contained in its own folder with its own README and (if needed) its own `.venv`. There is no monorepo glue — touching one tool does not affect another.

Git repository (`main` branch).

## Layout

- `tools/` — runnable Python CLI tools, each in a kebab-case subfolder with README
  - `redaction-tool/` — local PII redaction for a folder of files (spaCy + Presidio + Apple Vision OCR); has its own `.venv`, `setup.sh`, `requirements.txt`, nested `CLAUDE.md`, and `gen_keywords.py` (names-list → `custom_keywords` helper). Config: `demo.config.yaml` is the committed template; `config.yaml` (your real terms) is gitignored — `cp demo.config.yaml config.yaml` first.
  - `convert-to-md/` — `docx_to_md.py`, `html_to_md.py`
  - `find-duplicates/find_duplicates.py` — content-hash dedup; edit `TARGET_DIRECTORY` at top before running
  - `find-files/find_files.py` — `python find_files.py [directory] [extension]` (defaults: cwd, `.py`)
  - `find-empty-folders/find_empty_folders.py` — `python find_empty_folders.py [directory]`
  - `search-session-logs/search_session_logs.py` — `python search_session_logs.py <query> [directory]` (searches `.claude/session-logs/`)


### Testing

Verify by running with `--dry-run` against sample data. Run test executions in a sandbox (`/tmp/`), not the live workspace — and "done" means actually run, not just written. Create test plans for projects with non-trivial complexity (e.g. `tools/redaction-tool/`).

## Conventions

- New CLI scripts live in `tools/<kebab-case>/` with a `README.md` containing both a terse technical section and a numbered walkthrough for non-technical users.
- CLI scripts default to `Path.cwd()` when no directory argument is given.
- Versioning for sequenced filenames: zero-padded two-digit strings (`"01"`, `"02"`, …), quoted in YAML.
- When superseding a file, move the old one to `archive/<name>_v1.<ext>` — do not leave dead files in active dirs.
- Docs edits are additive — append to existing READMEs; do not rewrite or remove existing content.
- Three-audience doc separation — spec readers, runbook users, and script users get separate docs (e.g. `TESTING.md` vs operator runbook vs tool `README.md`); do not bloat one doc to serve all three.
