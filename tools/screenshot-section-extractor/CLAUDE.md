# CLAUDE.md

Guidance for Claude Code working in this repo. Start here, then see `README.md`.

## What this is

`screenshot-section-extractor` — a single-purpose **macOS** tool. It OCRs
two-column "assessment" screenshots **on-device** (Apple Vision), pulls the
verbatim text of a **named, heading-anchored section** from each column, reflows
it to Markdown, and aggregates a folder of screenshots into one file. It is *not*
a general OCR engine. The full pitch + build-vs-buy rationale is in `README.md`.

## Files

- `ocr.swift` — Apple Vision OCR/crop helper (the only Swift). Args:
  `<png> x0 y0 x1 y1 scale [--save out.png]`; prints TSV `xGlobal\tyGlobal\ttext`,
  normalized to the full image, top-left origin.
- `extract_section.py` — the tool. **Two passes per column:** coarse *anchor* (find
  the y of the start + stop headings), then a tight *section* crop re-read at high
  scale for clean text. `reconstruct()` reflows soft-wrapped lines into Markdown.
  Every form-specific value comes from `.env`.
- `envconfig.py` — ~25-line stdlib `.env` loader. **No third-party deps anywhere** —
  keep the "just run it" property.
- `demo.env` — documented config template. `demo/` — synthetic before/after example.
- `TODO.md` — pre-publish / move checklist. `LICENSE` — MIT.

## Commands

```bash
swiftc -O ocr.swift -o ocr                 # build the OCR helper (else Python falls back to `swift ocr.swift`)
cp demo.env .env                           # then edit .env for your form
python3 extract_section.py IMAGE_DIR out.md
python3 extract_section.py --debug IMAGE_DIR/one.png      # print one screenshot's result
python3 extract_section.py --readcrops IMAGE_DIR/one.png  # save legible section crops to /tmp/ocr_verify
python3 extract_section.py demo demo/out.md              # run the bundled demo
```

(`python3` is correct — this is macOS.)

## How config works

Everything form-specific lives in `.env` (copy `demo.env`). Heading/stop values are
**regexes matched against OCR text that has been lowercased and punctuation-stripped**
— write them lowercase. The manager heading uses `(?:\w+ )+` so it matches one- *or*
multi-word subject names. `SUBJECT_NAME` is **output-only**, never used for matching.
Column x-bands are normalized 0–1.

## Adapting to a new form

1. Dump every line's left edge with the raw OCR helper:
   `./ocr your.png 0 0 1 1 2.0`  →  `x \t y \t text`.
2. Read the two columns' left-edge `x` values and set the bands in `.env` so each
   column's text falls inside its band with the split between them:
   `SELF_X0/X1` + `SELF_XMIN_LO/HI`, and `MANAGER_X0/X1/XMIN`.
   (In the demo: self text ≈ 0.33, manager ≈ 0.63.)
3. Set `SELF_HEADING`/`SELF_STOP` and `MANAGER_HEADING`/`MANAGER_STOP` to regexes
   matching your form's start/stop headings — lowercase, punctuation-stripped;
   use `(?:\w+ )+` where a name appears.
4. Confirm the crops land right: `python3 extract_section.py --readcrops your.png`
   (legible crops → `/tmp/ocr_verify`), and `--debug your.png` for the extracted Markdown.

## Verifying a change

There is no test suite — `demo/sample-output.md` is the **golden file**. After editing,
regenerate against the shipped demo config and diff:

```bash
cp demo.env .env                              # ensure the demo's config
python3 extract_section.py demo /tmp/out.md
diff demo/sample-output.md /tmp/out.md        # expect no differences
```

If a change *intentionally* alters output, review the diff, then update the golden
file: `cp /tmp/out.md demo/sample-output.md`. Don't claim a change works off one
happy-path run — also try a screenshot you didn't design for (multi-word name,
missing manager column, an absent heading).

## Gotchas

- **macOS only** — depends on the Apple Vision framework.
- **Never commit `.env` or the compiled `ocr` binary** (both gitignored). `.env` holds
  tuned values; `ocr` is a local arm64 build — rebuild it with `swiftc`.
- Text is **never editorialized** — only unambiguous OCR-artifact fixes (`|`→`I`,
  `l'm`→`I'm`). Preserve that contract when editing `extract_section.py`.
- The `demo/` image is **synthetic** (invented data). Keep it that way — never add real
  screenshots to the repo; point `IMAGE_DIR` at images that live outside it.
- **Zero runtime dependencies** (Python stdlib + Swift only). Don't add pip/SPM deps.
