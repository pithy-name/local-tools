# tools/

Tier-1 utility scripts — run with `python3`, no venv. Full usage + non-technical walkthrough in each tool's `README.md`.

## Quick invocations

```bash
python3 find-files/find_files.py [directory] [extension]      # defaults: cwd, .py
python3 find-empty-folders/find_empty_folders.py [directory]
python3 search-session-logs/search_session_logs.py "<query>" [directory]   # searches .claude/session-logs/
python3 find-duplicates/find_duplicates.py                    # edit TARGET_DIRECTORY at top first
python3 convert-to-md/docx_to_md.py <file.docx>               # also html_to_md.py
```

`redaction-tool/` has its own venv + nested `CLAUDE.md` — see there.

`migrate-cowork-sessions/` has its own nested `CLAUDE.md` — see there. Stdlib only (no venv); requires `.env` setup (see `demo.env` template).
