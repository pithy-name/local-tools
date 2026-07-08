#!/usr/bin/env python3
"""Extract a named, heading-anchored section from each column of two-column
"assessment" screenshots, reflow it to clean Markdown, and aggregate every
screenshot in a folder into one Markdown file (newest first).

Built for forms laid out as two side-by-side columns (e.g. a "self" column and a
"manager"/reviewer column), where the text you want sits between a start heading
and a stop heading. Every form-specific value — heading patterns, column x-bands,
subject name, input glob — lives in a local `.env` (copy `demo.env` to `.env`).

OCR is Apple Vision, on-device, macOS-only. Vision degrades on crops that are too
small OR too large, so each column is read in two passes:
  1. ANCHOR  — read the whole column coarsely to locate the y of the start
               heading and the stop heading.
  2. SECTION — crop ONLY heading..stop (always small) and read it once at high
               scale for clean, verbatim text.
Columns are separated by each line's left edge (xmin). Nothing is editorialized;
the only transformation is reflowing soft-wrapped lines back into paragraphs /
bullet / numbered lists.

Local-only, read-only on the images. Writes one Markdown file.

Usage:
    python3 extract_section.py [IMAGE_DIR] [out.md]   # IMAGE_DIR defaults to "."
    python3 extract_section.py --debug IMAGE_DIR/one.png
    python3 extract_section.py --readcrops IMAGE_DIR/one.png
Config: ./.env (falls back to .env beside this script). See demo.env for keys.
"""

import glob
import os
import re
import shutil
import subprocess
import sys
import statistics
from collections import Counter

from envconfig import load_env

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(HERE, "ocr")
SRC = os.path.join(HERE, "ocr.swift")

# ---- config (.env in CWD, else beside this script) --------------------------
CFG = load_env(os.path.join(os.getcwd(), ".env"))
if not CFG:
    CFG = load_env(os.path.join(HERE, ".env"))


def _cfg(key, default):
    v = CFG.get(key)
    return v if v not in (None, "") else default


SUBJECT_NAME = _cfg("SUBJECT_NAME", "the subject")
OCR_SCALE = float(_cfg("OCR_SCALE", "3.0"))
INPUT_GLOB = _cfg("INPUT_GLOB", "*.png")

# Column crops (normalized x, top-left origin). The xmin filter removes bleed
# from the other column. Heading/stop are regexes matched against normalized
# (lowercased, punctuation-stripped) line text.
SELF = dict(
    x0=float(_cfg("SELF_X0", "0.28")), x1=float(_cfg("SELF_X1", "0.64")),
    xmin_keep=(lambda lo, hi: (lambda x: lo < x < hi))(
        float(_cfg("SELF_XMIN_LO", "0.315")), float(_cfg("SELF_XMIN_HI", "0.60"))),
    hdr=re.compile(_cfg("SELF_HEADING", r"things .{0,4}do well")),
    stop=re.compile(_cfg("SELF_STOP", r"how could .{0,4}improve")),
)
MANAGER = dict(
    x0=float(_cfg("MANAGER_X0", "0.595")), x1=float(_cfg("MANAGER_X1", "0.99")),
    xmin_keep=(lambda m: (lambda x: x > m))(float(_cfg("MANAGER_XMIN", "0.605"))),
    hdr=re.compile(_cfg("MANAGER_HEADING", r"things (?:\w+ )+does well")),
    stop=re.compile(_cfg("MANAGER_STOP", r"how could (?:\w+ )+improve")),
)
# -----------------------------------------------------------------------------

_OCR_CMD = None


def ocr_cmd():
    """Resolve the OCR helper once. Prefer the compiled binary, but only if it
    actually runs here — a committed binary may be the wrong arch, so fall back
    to the `swift` interpreter rather than silently produce empty output.
    Returns a command prefix list, e.g. ['…/ocr'] or ['swift', SRC]."""
    global _OCR_CMD
    if _OCR_CMD is not None:
        return _OCR_CMD
    if os.path.exists(BIN):
        try:
            subprocess.run([BIN], capture_output=True, timeout=15)   # no-arg => usage/exit 2
            _OCR_CMD = [BIN]
            return _OCR_CMD
        except OSError:
            pass                                                    # wrong arch / not executable
    _OCR_CMD = ["swift", SRC]
    return _OCR_CMD


INDENT = 0.012                      # x beyond the body margin => new list item
PERIOD_RE = re.compile(r"([A-Z][a-z]{2,8}\.?\s+\d{1,2},\s*\d{4})\s*[-–—]\s*"
                       r"([A-Z][a-z]{2,8}\.?\s+\d{1,2},\s*\d{4})")
BULLET_RE = re.compile(r"^\s*[-•‣⁃▪*·]\s+")
NUM_RE = re.compile(r"^\s*\d{1,2}[.)]\s+")
JUNK_RE = re.compile(r"^[\s•·▪‣⁃\-*–—|]+$")
FRAG_RE = re.compile(r"^([A-Za-z]|[A-Za-z]{1,5}\.{2,})$")   # stray crop-edge bits: "t", "SS.."

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def is_junk(s):
    return bool(JUNK_RE.match(s) or FRAG_RE.match(s))


def fix_ocr(s):
    """Restore unambiguous OCR artifacts (not editorialization):
      - a lone '|' is the letter I;
      - a word starting "l'" (lowercase L + apostrophe) is a misread "I'"
        contraction (l've/l'm/l'll/l'd) — never real words."""
    s = re.sub(r"(?<!\S)\|(?!\S)", "I", s)
    s = re.sub(r"\bl(['’](?:ve|m|ll|d)\b)", r"I\1", s)
    return s


def ocr(png, x0, y0, x1, y1, scale=OCR_SCALE):
    """Single crop OCR. Returns [(y, x, text), ...] sorted top->bottom (x = left edge)."""
    cmd = ocr_cmd() + [png, f"{x0}", f"{y0}", f"{x1}", f"{y1}", f"{scale}"]
    out = subprocess.run(cmd, capture_output=True, text=True)
    rows = []
    for line in out.stdout.splitlines():
        p = line.split("\t")
        if len(p) == 3 and p[2].strip():
            rows.append((float(p[1]), float(p[0]), p[2].strip()))
    rows.sort(key=lambda r: r[0])
    return rows


def ocr_save(png, x0, y0, x1, y1, out, scale=OCR_SCALE):
    cmd = ocr_cmd() + [png, f"{x0}", f"{y0}", f"{x1}", f"{y1}", f"{scale}", "--save", out]
    subprocess.run(cmd, capture_output=True, text=True)


def save_read_crops(png):
    """Save legible PNG bands of each section (heading..stop) for visual verification.
    Returns {'self': [paths], 'manager': [paths]|None}."""
    stem = os.path.splitext(os.path.basename(png))[0].replace(" ", "_")
    base = os.path.join("/tmp/ocr_verify", stem)
    os.makedirs(base, exist_ok=True)
    result = {}
    for name, col, xr in (("self", SELF, (SELF["x0"] + 0.02, SELF["x1"] - 0.015)),
                          ("manager", MANAGER, (MANAGER["x0"] + 0.005, MANAGER["x1"] - 0.015))):
        hy, sy = anchor(png, col)
        if hy is None:
            result[name] = None
            continue
        y0 = hy - 0.012
        y1 = (sy + 0.012) if sy is not None else 0.985
        paths, y, i = [], y0, 0
        while y < y1:
            out = os.path.join(base, f"{name}_{i:02d}.png")
            ocr_save(png, xr[0], y, xr[1], min(y + 0.07, y1), out)
            paths.append(out)
            y += 0.064          # slight overlap so no line is split between bands
            i += 1
        result[name] = paths
    return result


def _norm(s):
    return re.sub(r"[^a-z ]", " ", s.lower())


def anchor(png, col):
    """Coarsely read the whole column; return (heading_y, stop_y). Either may be None."""
    lines = [r for r in ocr(png, col["x0"], 0.05, col["x1"], 0.985, scale=2.0)
             if col["xmin_keep"](r[1])]
    hy = sy = None
    for y, _x, t in lines:
        n = _norm(t)
        if hy is None and col["hdr"].search(n):
            hy = y
        elif hy is not None and col["stop"].search(n):
            sy = y
            break
    return hy, sy


def extract(png, col):
    """Two-pass extract of one column's section. Returns Markdown or None."""
    hy, sy = anchor(png, col)
    if hy is None:
        return None
    # Bound the crop by the anchor's stop-y (exclude the stop line) so a misspelled
    # stop heading in the tight pass can't leak in.
    y_bot = (sy - 0.004) if sy is not None else 0.985
    lines = [r for r in ocr(png, col["x0"], hy - 0.004, col["x1"], y_bot, scale=OCR_SCALE)
             if col["xmin_keep"](r[1]) and not is_junk(r[2])]
    # slice strictly after the heading; stop line already excluded by the crop bound
    start = end = None
    for i, (_y, _x, t) in enumerate(lines):
        n = _norm(t)
        if start is None and col["hdr"].search(n):
            start = i
        elif start is not None and col["stop"].search(n):
            end = i
            break
    if start is None:
        return None
    section = lines[start + 1:end] if end is not None else lines[start + 1:]
    return reconstruct(section)


def reconstruct(section):
    """Reflow (y, x, text) into Markdown paragraphs / bullet / numbered lists.

    New block when a line is a bullet, a number, indented past the body margin, or
    follows a blank-line-sized vertical gap. Otherwise it is a soft-wrap
    continuation and is joined with a space. Verbatim: text is never altered."""
    if not section:
        return ""
    xs = [round(x, 3) for _y, x, _t in section]
    base_x = Counter(xs).most_common(1)[0][0]
    gaps = [section[i][0] - section[i - 1][0] for i in range(1, len(section))]
    med = statistics.median(gaps) if gaps else 1.0
    y_thresh = med * 1.6

    blocks = []  # [kind, text]  kind in {p, ul, ol}
    prev_y = None
    for y, x, text in section:
        text = fix_ocr(text)
        is_b = bool(BULLET_RE.match(text))
        is_n = bool(NUM_RE.match(text))
        indented = x > base_x + INDENT
        big_gap = prev_y is not None and (y - prev_y) > y_thresh
        if is_b:
            blocks.append(["ul", BULLET_RE.sub("", text).strip()])
        elif is_n:
            blocks.append(["ol", text.strip()])
        elif (not blocks) or big_gap or indented:
            blocks.append(["ul" if (indented and blocks) else "p", text.strip()])
        else:
            blocks[-1][1] += " " + text.strip()
        prev_y = y

    out, prev_kind = [], None
    for kind, text in blocks:
        if kind == "p":
            if out:
                out.append("")
            out.append(text)
        else:
            if out and not (kind in ("ul", "ol") and prev_kind in ("ul", "ol")):
                out.append("")
            out.append(text if kind == "ol" else f"- {text}")
        prev_kind = kind
    return "\n".join(out)


def review_period(png, self_hy):
    """Read the strip just above the self heading for a 'Mon D, YYYY - Mon D, YYYY' window."""
    if self_hy is None:
        return None
    for _y, _x, t in ocr(png, SELF["x0"] + 0.02, self_hy - 0.055,
                         SELF["x1"] - 0.02, self_hy - 0.004, scale=OCR_SCALE):
        m = PERIOD_RE.search(t)
        if m:
            return f"{m.group(1)} – {m.group(2)}"
    return None


def date_from_name(stem):
    m = re.search(r"(20\d{2})[-_](\d{1,2})", stem)
    if not m:
        return (0, 0, stem)
    y, mo = int(m.group(1)), int(m.group(2))
    return (y, mo, f"{MONTHS[mo - 1]} {y}" if 1 <= mo <= 12 else stem)


def process_one(png):
    stem = os.path.splitext(os.path.basename(png))[0]
    year, month, label = date_from_name(stem)
    self_hy, _ = anchor(png, SELF)

    self_md = extract(png, SELF)
    mgr_md = extract(png, MANAGER)
    period = review_period(png, self_hy)

    parts = [f"## {label}"]
    if period:
        parts.append(f"*Review period: {period}*")
    parts += ["", "### Self assessment",
              self_md.strip() if self_md else "_Self section not captured._",
              "", f"### Manager assessment — about {SUBJECT_NAME}",
              mgr_md.strip() if mgr_md else "_Manager did not submit this cycle._"]
    return (year, month), "\n".join(parts), os.path.basename(png)


def preflight():
    """Fail fast with an actionable message if OCR can't run at all."""
    cmd = ocr_cmd()
    if cmd[0] != BIN and shutil.which("swift") is None:
        sys.stderr.write(
            "ERROR: no OCR backend available.\n"
            "  This tool needs macOS with Apple Vision. Either:\n"
            "   - install the Swift toolchain:  xcode-select --install\n"
            "   - or build the helper binary:   swiftc -O ocr.swift -o ocr\n")
        sys.exit(2)


def main(argv):
    preflight()
    if len(argv) > 2 and argv[1] == "--debug":
        png = argv[2] if os.path.isabs(argv[2]) else os.path.join(os.getcwd(), argv[2])
        _key, md, name = process_one(png)
        print(f"===== {name} =====\n{md}")
        return 0

    if len(argv) > 2 and argv[1] == "--readcrops":
        png = argv[2] if os.path.isabs(argv[2]) else os.path.join(os.getcwd(), argv[2])
        _key, md, name = process_one(png)
        crops = save_read_crops(png)
        print(f"===== EXTRACTED MARKDOWN for {name} =====\n{md}\n")
        print("===== LEGIBLE CROP IMAGES (read in order, top->bottom) =====")
        for col in ("self", "manager"):
            print(f"[{col}]")
            for p in (crops.get(col) or ["(none — section absent)"]):
                print(f"  {p}")
        return 0

    image_dir = argv[1] if len(argv) > 1 else "."
    out_path = argv[2] if len(argv) > 2 else os.path.join(image_dir, "extracted.md")
    pngs = sorted(glob.glob(os.path.join(image_dir, INPUT_GLOB)))
    if not pngs:
        sys.stderr.write(
            f"ERROR: no images matching {INPUT_GLOB!r} found in {image_dir!r}\n"
            "  Point IMAGE_DIR at your screenshots, or set INPUT_GLOB in .env.\n")
        return 1
    entries = []
    for png in pngs:
        key, md, name = process_one(png)
        entries.append((key, md))
        print(f"  extracted {name}  ({key[0]}-{key[1]:02d})")
    entries.sort(key=lambda e: e[0], reverse=True)

    doc = (
        f"# {SUBJECT_NAME} — Extracted Sections\n\n"
        "_Verbatim extracts of the configured self + manager sections from each "
        "screenshot, most recent first._\n\n"
        + "\n\n".join(md for _k, md in entries)
        + "\n\n---\n*Generated via extract_section.py (on-device Apple Vision OCR).*\n"
    )
    with open(out_path, "w") as f:
        f.write(doc)
    print(f"wrote {out_path}  ({len(entries)} screenshots)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
