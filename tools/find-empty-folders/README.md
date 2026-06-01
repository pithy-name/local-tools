# find_empty_folders

> **Status:** v0.1 — early and experimental.
>
> **Caveat emptor:** verify output before relying on it.

Recursively scans a directory and reports any folders whose subtree contains zero files. A folder is considered empty if neither it nor any of its descendants (excluding skipped dirs) contains a file.

## Usage

```bash
# scan cwd (default)
python3 find_empty_folders.py

# scan a specific directory
python3 find_empty_folders.py /path/to/search
```

Arguments:
- `directory` — directory to scan (default: current working directory)

## Skipped directories

Hidden dirs (names starting with `.`) and common junk dirs are ignored during the scan:

`.git`, `.venv`, `venv`, `__pycache__`, `node_modules`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `.tox`, `.idea`, `.vscode`

## Output

Prints:
- the root path scanned
- total folder count checked
- count of empty folders, followed by relative paths (one per line)

## Exit codes

- `0` — every folder contains at least one file
- `1` — one or more empty folders found
- `2` — argument is not a directory

---

## Step-by-step (for first-timers)

If you've never run a Python script from the terminal before, follow these. At the end you'll have a list of any empty folders printed in the terminal.

1. Open the Terminal app (press `Cmd+Space`, type "Terminal", hit Enter).
2. No installation needed — this script uses only Python's built-in libraries.
3. Change into this folder:
   ```bash
   cd path/to/local-tools/tools/find-empty-folders
   ```
4. Run the script. To scan your current directory, just run:
   ```bash
   python3 find_empty_folders.py
   ```
   To scan a specific folder instead, pass its path. Tip: drag the folder from Finder onto the terminal window to paste its full path.
   ```bash
   python3 find_empty_folders.py /full/path/to/folder
   ```
5. The terminal prints a summary: how many folders were checked and how many were empty. If any empty folders exist, their paths are listed below.
6. If you see `All folders contain at least one file.`, you're done — nothing is empty.
