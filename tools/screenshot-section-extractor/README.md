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

## Why I built it (and why off-the-shelf didn't fit)

The source material was a stack of **confidential HR-document
screenshots**. The task was never "OCR an image" — lots of tools do that. It was:
*pull one specific section from the right column of a particular two-column
layout, verbatim, across dozens of screenshots, into clean Markdown.* Build vs.
buy:

- **Cloud OCR** (Google Cloud Vision, AWS Textract, Azure AI Document
  Intelligence, Adobe) uploads images to remote servers, where they can be cached
  and pass through logging / CDN layers before reaching the OCR service. For
  confidential HR documents that's a non-starter, and most workplaces' **data-loss-
  prevention (DLP) policies block exactly this kind of cloud upload.** Disqualified
  on privacy. ([on-device vs cloud OCR](https://scanlens.io/blog/on-device-vs-cloud-ocr))
- **Local OCR engines** (Tesseract, IronOCR, ABBYY) keep data on the machine, but
  they hand back raw text or bounding boxes. None of them do the actual task here:
  locate a *named section between two heading anchors*, in a *chosen column*, and
  *reflow it to Markdown across a batch*. That orchestration is the bespoke part.
- **Apple Vision** was chosen for the OCR layer because it is on-device (privacy),
  ships with macOS (zero install, zero dependencies), and on ordinary documents now
  matches cloud accuracy. ([on-device vs cloud OCR](https://scanlens.io/blog/on-device-vs-cloud-ocr))

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

## Demo

A synthetic, fully **anonymized** example ships in [`demo/`](demo/) — invented
content, no real data:

| Before | After |
|--------|-------|
| [`demo/sample-assessment-2023-02.png`](demo/sample-assessment-2023-02.png) | [`demo/sample-output.md`](demo/sample-output.md) |

Reproduce it:

```bash
cp demo.env .env
python3 extract_section.py demo demo/out.md
```

Excerpt of the output:

```markdown
## February 2023

### Self assessment
Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod
tempor incididunt ut labore et dolore magna aliqua.

Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut
aliquip ex ea commodo consequat.

### Manager assessment — about Jordan Rivera
Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia
deserunt mollit anim id est laborum.
...
```

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
