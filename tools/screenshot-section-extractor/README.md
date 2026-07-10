# screenshot-section-extractor

Extract a named, heading-anchored **section** from each column of **two-column
assessment screenshots**, fully **on-device**, and aggregate a folder of them
into one clean Markdown file — newest first.

It is not a general OCR engine. It does one job well: given screenshots laid out
as two side-by-side columns (e.g. a *self* column and a *manager/reviewer*
column), pull the verbatim text **between a start heading and a stop heading** in
each column, reflow the soft-wrapped lines back into paragraphs / bullet /
numbered lists, and stitch every screenshot into a single Markdown document.

Everything form-specific — heading patterns, column x-bands, subject name, input
glob — lives in a local `.env`. Copy `demo.env`, edit, run.

---

## Why I built it

The source material was a stack of **confidential HR-document
screenshots**. The task was never "OCR an image" — lots of tools do that. It was:
*pull one specific section from the right column of a particular two-column
layout, verbatim, across dozens of screenshots, into clean Markdown.*

**Apple Vision** does the OCR layer: it's on-device, so confidential documents
never leave the machine; it ships with macOS (zero install, zero dependencies);
and on ordinary documents it now matches cloud accuracy. ([on-device vs cloud
OCR](https://scanlens.io/blog/on-device-vs-cloud-ocr))

In short: **buy the wheel** (the OCR engine), **build the cart** (the targeted
extraction + reflow).

## How it works

Each column is read in **two passes**, to beat Apple Vision's degradation on
crops that are too small (tiny text) or too large (it downsamples and drops text):

1. **Anchor** — read the whole column coarsely to find the *y* of the start
   heading and the stop heading.
2. **Section** — crop only `heading → stop` (always small) and re-read it at high
   scale for clean, verbatim text.

Columns are separated by each line's normalized **left edge (xmin)**. Soft-wrapped
lines are reflowed into Markdown; text is **never editorialized** — the only
changes are unambiguous OCR-artifact fixes (a lone `|` → `I`, a misread `l'm` → `I'm`).

## Requirements

- **macOS** (uses the on-device Vision framework).
- **Swift** toolchain — `xcode-select --install`. (Optional: the Python falls back
  to running `ocr.swift` through the `swift` interpreter if you don't build a binary.)
- **Python 3** — standard library only. No `pip install`, no dependencies.

## Build

```bash
swiftc -O ocr.swift -o ocr
```

## Configure

```bash
cp demo.env .env      # then edit .env for your form
```

Every key is documented in `demo.env`. Heading/stop values are **regexes** matched
against OCR text that has been lowercased and stripped of punctuation, so write
them lowercase. `.env` is gitignored — it holds your real values.

**Note on defaults:** Config keys have hardcoded defaults (e.g., `SELF_X0` defaults to `"0.28"`,
`OCR_SCALE` to `"3.0"`). If `.env` is missing or misnamed, the tool silently falls back to
these demo geometry values when running against real data. Always verify your loaded config
matches the form you're processing (check that column x-bands match your layout).

To verify: run `python3 extract_section.py --debug IMAGE_DIR/one.png` on a real
screenshot and confirm both sections come back non-empty and read as
expected — an empty or truncated section usually means a heading regex or
x-band doesn't match your form. For a visual check, `--readcrops` (see
[Usage](#usage) below) saves the exact crop images the OCR pass reads, so you
can eyeball whether each crop is cleanly bounded to the right column and the
right heading-to-stop span.

### Calibration profiles

`demo.env`/`.env` ship two column-geometry profiles:

| Profile | Keys | Layout |
|---|---|---|
| Default (active) | `SELF_X0/X1`, `SELF_XMIN_LO/HI`, `MANAGER_X0/X1`, `MANAGER_XMIN` | The narrower two-column layout `extract_section.py` reads out of the box. |
| `profile_2col_v2` (reference) | `PROFILE_2COL_V2_*` | A second, wider two-column layout seen on a differently-styled assessment form (self 0.30–0.595, manager 0.60–0.995). Not read automatically — copy the `PROFILE_2COL_V2_*` values over the default keys above to activate it. |

The `profile_2col_v2` block also carries an `INDENT` value and a rating-crop
y-band (`RATING_CROP_Y_TOP/BOTTOM`) ported for reference; `extract_section.py`
has no per-profile INDENT setting or rating-crop feature today, so those two
values aren't wired into the script yet — they're documented in `.env`/`demo.env`
for whoever picks up that layout or the rating-field feature next.

## Usage

```bash
python3 extract_section.py IMAGE_DIR [out.md]      # batch a folder -> Markdown
python3 extract_section.py --debug IMAGE_DIR/one.png   # print one screenshot's result
python3 extract_section.py --readcrops IMAGE_DIR/one.png   # save legible section crops to verify
```

**`--readcrops` output:** Saves crop images to `/tmp/ocr_verify/<image_stem>/` (where `<image_stem>` is the PNG filename without extension, spaces replaced with underscores). Images are written in reading order: `self_00.png`, `self_01.png`, … (top to bottom), and same for `manager_*.png`.

## Demo

A synthetic, fully **anonymized** example ships in [`demo/`](demo/) — invented
content, no real data:

| Before | After |
|--------|-------|
| [`demo/sample-assessment-2023-02.png`](demo/sample-assessment-2023-02.png) | [`demo/sample-output.md`](demo/sample-output.md) |

Reproduce it:

```bash
cp demo.env .env
python3 extract_section.py demo /tmp/out.md
```

See [`demo/sample-output.md`](demo/sample-output.md) for the full output.

## Limitations

- **macOS only** (Apple Vision framework).
- **Two columns**, separated by a vertical gap — not arbitrary or 3+ column layouts.
- The target section must be bounded by **detectable start + stop headings**.
- **Screenshots / images** (PNG), not born-digital PDFs — extract text from those directly.
- Tuned via regexes + x-bands; a new layout needs a few `.env` tweaks.

## Privacy

On-device only — no network calls. Reads images read-only and writes a single
Markdown file. Your real `.env` and your source screenshots are gitignored by
default; keep real images outside the repo and point `IMAGE_DIR` at them.

## License

[MIT](LICENSE).
