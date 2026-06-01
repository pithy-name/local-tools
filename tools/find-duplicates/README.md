# find_duplicates

> **Status:** v0.1 — early and experimental.
>
> **Caveat emptor:** verify output before relying on it.

Recursively scans a directory and finds duplicate files by content hash (not by filename). Works on any file type — `.md`, `.html`, `.csv`, images, `.mp4`, `.pdf`, etc.

For each duplicate group, prints all matching paths sorted oldest → newest and flags the newest copy. Optionally writes a JSON report.

## Configuration

This script is configured by editing constants at the top of the file (not by CLI args):

- `TARGET_DIRECTORY` — absolute path to the folder you want scanned. **Must be set before running.**
- `HASH_ALGO` — `"md5"` (fast, default) or `"sha256"`.
- `FILE_EXTENSIONS` — list of extensions to include (e.g. `["md", "html", "csv", "pdf"]`). Empty list `[]` means all files.
- `USE_BIRTHTIME` — `True` uses file creation time (better for exported files); `False` uses modification time.

## Usage

```bash
python3 find_duplicates.py
```

## Output

- Console: each duplicate group with hash, file size, and every path (oldest → newest, newest tagged `📌 NEWEST`).
- JSON: `duplicates_report.json` written inside `TARGET_DIRECTORY` for further processing.

---

## Step-by-step (for first-timers)

If you've never run a Python script from the terminal before, follow these. At the end you'll have a list of duplicate files printed in the terminal plus a JSON report saved into the folder you scanned.

1. Open the Terminal app (press `Cmd+Space`, type "Terminal", hit Enter).
2. Open the script in a text editor so you can configure it. From Terminal:
   ```bash
   open -e path/to/local-tools/tools/find-duplicates/find_duplicates.py
   ```
3. Edit the `TARGET_DIRECTORY` line near the top so it points to the folder you want scanned. Use the full path, in quotes. Example:
   ```python
   TARGET_DIRECTORY = "/Users/yourname/Documents/folder-to-check"
   ```
   Tip: in Finder, right-click the folder while holding `Option` and choose "Copy as Pathname" to get the full path.
4. (Optional) Tweak the other settings in the same block:
   - `FILE_EXTENSIONS = []` to scan all file types, or list extensions like `["md", "pdf"]` to limit the scan.
   - `USE_BIRTHTIME = True` to sort by creation date; `False` for last-modified date.
5. Save the file and close the editor.
6. Back in Terminal, change into this folder:
   ```bash
   cd path/to/local-tools/tools/find-duplicates
   ```
7. Run the script:
   ```bash
   python3 find_duplicates.py
   ```
8. Watch the terminal. While it runs, you'll see progress lines like `Processing... (50 files scanned)`. When it finishes, each duplicate group is printed with all of its file paths. The newest copy in each group is marked `📌 NEWEST`.
9. If duplicates were found, a file called `duplicates_report.json` is saved inside the folder you scanned. Open it in any text editor to review the full report.
10. If you see `✨ No duplicates found!`, you're done — nothing was duplicated.
