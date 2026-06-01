# convert-to-md

> **Status:** v0.1 — early and experimental.
>
> **Caveat emptor:** verify output before relying on it.

Two small CLI converters that turn source documents into Markdown.

## Scripts

### `docx_to_md.py`

Converts a `.docx` file to Markdown. Preserves headings (H1–H4), bold/italic runs, bullet/list paragraphs, and tables.

Usage:

```bash
python3 docx_to_md.py <file.docx>
```

Output is written next to the source file with a `.md` extension.

Dependencies: `python-docx`

```bash
pip install python-docx
```

### `html_to_md.py`

Converts an HTML file to Markdown. Strips `<script>`, `<style>`, and `<head>` before conversion.

Usage:

```bash
python3 html_to_md.py <file.html> [output.md]
```

If no output path is given, writes alongside the source with a `.md` extension.

Dependencies: `markdownify`, `beautifulsoup4`

```bash
pip install markdownify beautifulsoup4
```

---

## Step-by-step (for first-timers)

If you've never run a Python script from the terminal before, follow these. Both walkthroughs end with a `.md` file you can open.

### `docx_to_md.py` — turn a `.docx` into a `.md`

1. Open the Terminal app (press `Cmd+Space`, type "Terminal", hit Enter).
2. One-time setup: install the library this script needs.
   ```bash
   pip install python-docx
   ```
3. Change into this folder:
   ```bash
   cd path/to/local-tools/tools/convert-to-md
   ```
4. Run the script. Replace the example path with your file — tip: you can drag the file from Finder onto the terminal window to paste its full path.
   ```bash
   python3 docx_to_md.py /full/path/to/yourfile.docx
   ```
5. Terminal prints `Saved: /full/path/to/yourfile.md` when it finishes.
6. Open Finder, navigate to the folder that held your `.docx`. A new file `yourfile.md` is sitting right next to it.

### `html_to_md.py` — turn an `.html` into a `.md`

1. Open the Terminal app (`Cmd+Space`, type "Terminal", Enter).
2. One-time setup: install the libraries this script needs.
   ```bash
   pip install markdownify beautifulsoup4
   ```
3. Change into this folder:
   ```bash
   cd path/to/local-tools/tools/convert-to-md
   ```
4. Run the script. Drag the `.html` file from Finder onto the terminal to paste its full path:
   ```bash
   python3 html_to_md.py /full/path/to/yourfile.html
   ```
   Optional: pick where to save the result by adding a second path:
   ```bash
   python3 html_to_md.py /full/path/to/yourfile.html /where/to/save/out.md
   ```
5. Terminal prints `Saved to /full/path/to/yourfile.md` when it finishes.
6. Open Finder, navigate to the folder that held your `.html`. The new `yourfile.md` is right next to it (or at the path you specified in step 4).
