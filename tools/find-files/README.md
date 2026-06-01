# find_files

> **Status:** v0.1 — early and experimental.
>
> **Caveat emptor:** verify output before relying on it.

Recursively finds all files with a given extension within the current working directory and all child directories.

## Usage

```bash
# search cwd for .py files (default)
python find_files.py

# search cwd for a specific extension
python find_files.py . .md

# search a specific directory for a specific extension
python find_files.py /path/to/search .md
```

Arguments:
- `directory` — directory to search (default: current working directory)
- `extension` — file extension to match, with or without leading dot (default: `.py`)

## Output

Prints sorted absolute paths, one per line, with a total count at the end.
