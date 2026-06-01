# search_session_logs

> **Status:** v0.1 — early and experimental.
>
> **Caveat emptor:** verify output before relying on it.

Recursively searches session-log markdown files for a given string. Case-insensitive. Prints matching file paths, line numbers, and matched lines.

Matches any `.md` file whose name contains `scratchpad` or `session-log` — covering both the legacy `scratchpad-YYYY-MM-DD-*.md` files and the current `*-session-log-*.md` naming. Session logs now live in `.claude/session-logs/`.

## Usage

```bash
# search .claude/session-logs/ under cwd (default)
python search_session_logs.py "my query"

# search a specific directory
python search_session_logs.py "my query" /path/to/search
```

Arguments:
- `query` — string to search for (required)
- `directory` — directory to search (default: `.claude/session-logs/` under cwd if it exists, else cwd)

## Output

Each match prints as `path:line: content` (grep-style, one per line), with a total match count at the end.

## Bash equivalent

This script is a thin wrapper around `grep`. The same search, no script needed:

```bash
grep -rin --include='*scratchpad*.md' --include='*session-log*.md' "my query" .claude/session-logs/
```

`-r` recursive, `-i` case-insensitive, `-n` line numbers; the two `--include` globs scope it to the same files the script matches. Output is `path:line:content`.

For the trailing total-match count the script prints, pipe to `wc -l`:

```bash
grep -rin --include='*scratchpad*.md' --include='*session-log*.md' "my query" .claude/session-logs/ | wc -l
```

Two cosmetic differences from the script: `grep` prints each matched line verbatim (the script strips leading/trailing whitespace), and `grep` has no `N matches across M files` summary.

## Walkthrough (non-technical)

1. Open Terminal.
2. Go to your project: `cd /path/to/your/project`
3. Run a search, replacing the words in quotes with what you're looking for:
   `python tools/search-session-logs/search_session_logs.py "redaction tool"`
4. It looks inside `.claude/session-logs/` automatically. Each result shows the file, the line number, and the line that matched. The last line is the total count.
