#!/usr/bin/env python3
"""redact.py — Fully-local PII redaction for Notion exports
──────────────────────────────────────────────────────────────
Handles: Markdown, HTML, PDF (digital + scanned), Images
No network calls. All NLP and OCR runs on-device.

Usage:
    python redact.py /path/to/notion/export
    python redact.py /path/to/notion/export --config config.yaml
    python redact.py /path/to/notion/export --dry-run
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Optional

import yaml

log = logging.getLogger("redact")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)


# ── Config ────────────────────────────────────────────────────────────────────

DEFAULT_CONFIG: dict = {
    # Presidio/spaCy named entity types to detect
    "entities": [
        "PERSON",
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "ORGANIZATION",
        "LOCATION",
    ],
    "custom_keywords": [],       # exact strings to always redact (word-boundary match)
    "replacement": "█████",      # what replaced text looks like
    "spacy_model": "en_core_web_lg",  # change to en_core_web_sm for a ~12MB model
    "output_dir": "redacted",    # created inside input_dir
    "copy_unhandled": False,     # leak guard: don't copy unhandled file types into redacted/
    "include_extensions": [
        ".md", ".html", ".htm",
        ".pdf",
        ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ],
    "ocr": {
        "use_apple_vision": True,   # on-device Apple OCR (M-series Mac)
        "fallback_tesseract": True, # fall back to Tesseract if Vision unavailable
        "dpi": 200,                 # resolution for rendering scanned PDF pages
    },
}


def load_config(path: Optional[str]) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    cfg["ocr"] = dict(DEFAULT_CONFIG["ocr"])  # deep copy nested dict
    if path and Path(path).exists():
        with open(path) as f:
            overrides = yaml.safe_load(f) or {}
        for k, v in overrides.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k] = {**cfg[k], **v}
            else:
                cfg[k] = v
    return cfg


# ── Import checks ─────────────────────────────────────────────────────────────

def check_imports() -> None:
    """Fail fast with a helpful message if required packages are missing."""
    missing = []
    checks = [
        ("presidio_analyzer", "presidio-analyzer"),
        ("presidio_anonymizer", "presidio-anonymizer"),
        ("spacy", "spacy"),
        ("fitz", "pymupdf"),
        ("PIL", "Pillow"),
        ("bs4", "beautifulsoup4"),
        ("yaml", "PyYAML"),
    ]
    for module, package in checks:
        try:
            __import__(module)
        except ImportError:
            missing.append(package)
    if missing:
        sys.exit(
            f"Missing packages: {', '.join(missing)}\n"
            f"Fix: pip install {' '.join(missing)}"
        )


# ── NLP / Presidio ────────────────────────────────────────────────────────────

def normalize_keywords(cfg: dict) -> list[dict]:
    """
    Normalize custom_keywords into a list of {find, replace} dicts.
    Supports two formats in config.yaml:
      - Plain string:             "Acme Corp"          → replace with default █████
      - Find/replace mapping:     {find: "John Smith", replace: "J.S."}
    """
    normalized = []
    for item in cfg.get("custom_keywords", []):
        if isinstance(item, str):
            normalized.append({"find": item, "replace": None})   # None → use default
        elif isinstance(item, dict) and "find" in item:
            normalized.append({"find": item["find"], "replace": item.get("replace")})
        else:
            log.warning(f"Skipping unrecognized custom_keyword entry: {item!r}")
    return normalized


def make_keyword_redactor_from_config(cfg: dict):
    """Keyword-only text redactor backed by keyword_redactor — NO spaCy load.

    Used when entities is empty (keyword-only mode). Converts redact.py's
    custom_keywords into keyword_redactor mappings: a plain-string keyword
    (replace=None) takes the default replacement (cfg['replacement']).
    """
    from keyword_redactor import KeywordRedactor

    default = cfg.get("replacement", "█████")
    mappings = [
        {"find": k["find"],
         "replace": k["replace"] if k["replace"] is not None else default}
        for k in normalize_keywords(cfg)
    ]
    return KeywordRedactor(mappings)


def build_analyzer(cfg: dict) -> tuple:
    """
    Return (AnalyzerEngine, kw_replacements).
    kw_replacements maps entity_type → replacement string (or None for default).
    Each keyword gets its own entity type KW_0, KW_1, … so per-entry replacements work.
    """
    from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
    from presidio_analyzer.nlp_engine import NlpEngineProvider

    model_name = cfg.get("spacy_model", "en_core_web_lg")
    nlp_cfg = {
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "en", "model_name": model_name}],
    }
    try:
        provider = NlpEngineProvider(nlp_configuration=nlp_cfg)
        nlp_engine = provider.create_engine()
    except Exception as e:
        log.error(f"Failed to load spaCy model '{model_name}': {e}")
        log.error(f"Fix: python -m spacy download {model_name}")
        sys.exit(1)

    analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["en"])

    keywords = normalize_keywords(cfg)
    kw_replacements: dict[str, Optional[str]] = {}

    for i, kw in enumerate(keywords):
        entity_type = f"KW_{i}"
        pattern = Pattern(
            name=f"kw_{i}",
            regex=r"(?i)\b" + re.escape(kw["find"]) + r"\b",  # case-insensitive
            score=0.95,
        )
        recognizer = PatternRecognizer(supported_entity=entity_type, patterns=[pattern])
        analyzer.registry.add_recognizer(recognizer)
        kw_replacements[entity_type] = kw["replace"]  # None = fall back to default

    if keywords:
        n_mapped = sum(1 for k in keywords if k["replace"] is not None)
        log.info(
            f"Loaded {len(keywords)} custom keyword(s) "
            f"({n_mapped} with custom replacement, {len(keywords) - n_mapped} using default)"
        )

    return analyzer, kw_replacements


def get_entities(cfg: dict, kw_replacements: dict) -> list:
    ents = list(cfg.get("entities", DEFAULT_CONFIG["entities"]))
    ents.extend(kw_replacements.keys())   # KW_0, KW_1, …
    return ents


def analyze(text: str, analyzer, cfg: dict, kw_replacements: dict) -> list:
    if not text.strip():
        return []
    return analyzer.analyze(
        text=text, entities=get_entities(cfg, kw_replacements), language="en"
    )


def anonymize(
    text: str,
    results: list,
    default_replacement: str,
    kw_replacements: Optional[dict] = None,
) -> str:
    """
    Replace detected spans with their appropriate replacement.
    Custom keywords (KW_N) use their configured string if set; everything else
    uses default_replacement. Processes spans high→low to keep offsets valid.
    """
    if not results:
        return text
    kw_replacements = kw_replacements or {}
    buf = list(text)
    for r in sorted(results, key=lambda r: r.start, reverse=True):
        per_entity = kw_replacements.get(r.entity_type)  # None if not a KW entity
        replacement = per_entity if per_entity is not None else default_replacement
        buf[r.start:r.end] = list(replacement)
    return "".join(buf)


# ── Text file handlers ────────────────────────────────────────────────────────

def _redact_text(text, analyzer, cfg: dict, kw_replacements: dict, kr) -> tuple:
    """Redact one string → (redacted, n_swaps).

    kr (a keyword_redactor.KeywordRedactor, keyword-only mode) wins when set —
    no spaCy. Otherwise the NER+keyword analyzer path. n_swaps is per-call.
    """
    if kr is not None:
        before = sum(kr.counts.values())
        out = kr.redact(text)
        return out, sum(kr.counts.values()) - before
    results = analyze(text, analyzer, cfg, kw_replacements)
    return anonymize(text, results, cfg["replacement"], kw_replacements), len(results)


def process_markdown(
    src: Path, dst: Path, analyzer, cfg: dict, kw_replacements: dict, dry_run: bool, kr=None
) -> int:
    text = src.read_text(encoding="utf-8", errors="replace")
    redacted, n = _redact_text(text, analyzer, cfg, kw_replacements, kr)
    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(redacted, encoding="utf-8")
    return n


def process_html(
    src: Path, dst: Path, analyzer, cfg: dict, kw_replacements: dict, dry_run: bool, kr=None
) -> int:
    from bs4 import BeautifulSoup

    html = src.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    total = 0
    SKIP_TAGS = {"script", "style", "code", "pre"}

    # Redact visible text nodes
    for node in soup.find_all(string=True):
        if node.parent and node.parent.name in SKIP_TAGS:
            continue
        text = str(node)
        redacted, n = _redact_text(text, analyzer, cfg, kw_replacements, kr)
        total += n
        if n and not dry_run:
            node.replace_with(redacted)

    # Also scrub mailto: href attributes (emails in links)
    for tag in soup.find_all("a", href=re.compile(r"^mailto:", re.I)):
        href = tag.get("href", "")
        redacted, n = _redact_text(href, analyzer, cfg, kw_replacements, kr)
        total += n
        if n and not dry_run:
            tag["href"] = redacted

    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(str(soup), encoding="utf-8")

    return total


def _walk_json(obj, redact_one):
    """Recursively redact string VALUES via redact_one(s)->(s', n). Keys and
    non-strings pass through. Returns (new_obj, total_swaps)."""
    if isinstance(obj, str):
        return redact_one(obj)
    if isinstance(obj, list):
        out, total = [], 0
        for v in obj:
            nv, n = _walk_json(v, redact_one)
            out.append(nv)
            total += n
        return out, total
    if isinstance(obj, dict):
        out, total = {}, 0
        for k, v in obj.items():
            nv, n = _walk_json(v, redact_one)
            out[k] = nv
            total += n
        return out, total
    return obj, 0


def process_json(
    src: Path, dst: Path, analyzer, cfg: dict, kw_replacements: dict, dry_run: bool, kr=None
) -> int:
    """Parse-aware JSON redaction: redact string VALUES only, re-serialize valid
    JSON. Keys, numbers, bools, nulls pass through; originals never modified."""
    data = json.loads(src.read_text(encoding="utf-8-sig", errors="replace"))
    redacted, total = _walk_json(
        data, lambda s: _redact_text(s, analyzer, cfg, kw_replacements, kr))
    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(json.dumps(redacted, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
    return total


def process_csv(
    src: Path, dst: Path, analyzer, cfg: dict, kw_replacements: dict, dry_run: bool, kr=None
) -> int:
    """Redact every cell of a CSV, preserving structure (csv.reader/writer)."""
    rows_out, total = [], 0
    with src.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f):
            new_row = []
            for cell in row:
                red, n = _redact_text(cell, analyzer, cfg, kw_replacements, kr)
                new_row.append(red)
                total += n
            rows_out.append(new_row)
    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        with dst.open("w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerows(rows_out)
    return total


# ── OCR (Apple Vision + Tesseract fallback) ───────────────────────────────────

# Each observation: {"text": str, "bbox_pixels": (x0, y0, x1, y1)}
Observation = dict

_apple_vision_checked: Optional[bool] = None


def apple_vision_available() -> bool:
    global _apple_vision_checked
    if _apple_vision_checked is not None:
        return _apple_vision_checked
    try:
        import objc  # noqa: F401
        import Vision  # noqa: F401
        _apple_vision_checked = True
        log.info("Apple Vision OCR: available (on-device M-series)")
    except ImportError:
        _apple_vision_checked = False
        log.info("Apple Vision OCR: unavailable (pyobjc not installed)")
    return _apple_vision_checked


def ocr_apple_vision(img) -> list[Observation]:
    """
    Apple Vision on-device OCR.
    Vision uses normalized coords with origin at bottom-left (Core Graphics).
    We flip the Y axis to convert to PIL's top-left origin.
    """
    import Vision
    from Foundation import NSURL

    width, height = img.size
    observations = []

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        img.save(tmp_path, format="PNG")
        url = NSURL.fileURLWithPath_(tmp_path)
        handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, None)
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)

        success, error = handler.performRequests_error_([request], None)
        if not success:
            log.warning(f"Apple Vision error: {error}")
            return []

        for obs in (request.results() or []):
            candidates = obs.topCandidates_(1)
            if not candidates:
                continue
            cand = candidates[0]
            text = str(cand.string()).strip()
            confidence = float(cand.confidence())
            if not text or confidence < 0.3:
                continue

            # Normalized CGRect (origin bottom-left) → PIL pixel coords (origin top-left)
            bb = obs.boundingBox()
            x = bb.origin.x
            y = bb.origin.y
            w = bb.size.width
            h = bb.size.height

            x0 = max(0, int(x * width) - 2)
            y0 = max(0, int((1.0 - y - h) * height) - 2)
            x1 = min(width, int((x + w) * width) + 2)
            y1 = min(height, int((1.0 - y) * height) + 2)

            observations.append({
                "text": text,
                "confidence": confidence,
                "bbox_pixels": (x0, y0, x1, y1),
            })
    finally:
        os.unlink(tmp_path)

    return observations


def ocr_tesseract(img) -> list[Observation]:
    """Tesseract fallback — requires: brew install tesseract && pip install pytesseract"""
    try:
        import pytesseract
    except ImportError:
        log.warning("pytesseract not installed; skipping OCR on this image")
        return []

    data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
    observations = []
    for i, text in enumerate(data["text"]):
        text = str(text).strip()
        conf = int(data["conf"][i])
        if not text or conf < 50:
            continue
        x = data["left"][i]
        y = data["top"][i]
        w = data["width"][i]
        h = data["height"][i]
        observations.append({
            "text": text,
            "confidence": conf / 100.0,
            "bbox_pixels": (x, y, x + w, y + h),
        })
    return observations


def ocr_image(img, cfg: dict) -> list[Observation]:
    if cfg["ocr"].get("use_apple_vision", True) and apple_vision_available():
        return ocr_apple_vision(img)
    elif cfg["ocr"].get("fallback_tesseract", True):
        return ocr_tesseract(img)
    log.warning("No OCR backend available — scanned content will not be redacted")
    return []


# ── Image redaction ───────────────────────────────────────────────────────────

def redact_image_pixels(img, analyzer, cfg: dict):
    """
    OCR the image, run Presidio on each text observation, black out sensitive regions.
    Returns (modified PIL.Image, num_redactions).
    Conservative: if any PII found in a line's observation, the whole bounding box
    is blacked out — no partial-line sub-pixel surgery needed.
    """
    from PIL import ImageDraw

    observations = ocr_image(img, cfg)
    draw = ImageDraw.Draw(img)
    count = 0

    for obs in observations:
        # kw_replacements not needed here — visual redaction always uses black box
        results = analyze(obs["text"], analyzer, cfg, kw_replacements={})
        if results:
            # Black out the entire observation region
            draw.rectangle(obs["bbox_pixels"], fill=(0, 0, 0))
            count += len(results)

    return img, count


def process_image(src: Path, dst: Path, analyzer, cfg: dict, dry_run: bool) -> int:
    from PIL import Image

    img = Image.open(str(src)).convert("RGB")
    img, count = redact_image_pixels(img, analyzer, cfg)

    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if count:
            img.save(str(dst))
        else:
            shutil.copy2(src, dst)  # no changes needed — copy original

    return count


# ── PDF redaction ─────────────────────────────────────────────────────────────

def process_pdf(src: Path, dst: Path, analyzer, cfg: dict, dry_run: bool) -> int:
    """
    Digital pages  → PyMuPDF native redaction annotations (preserves PDF structure).
    Scanned pages  → Render to image → Apple Vision OCR → black boxes → reinsert.
    Output is a new PDF saved to dst.
    """
    import fitz
    from PIL import Image

    dpi = cfg["ocr"].get("dpi", 200)
    scale = dpi / 72.0
    total = 0

    src_doc = fitz.open(str(src))
    out_doc = fitz.open()

    for page_num in range(len(src_doc)):
        page = src_doc[page_num]
        page_text = page.get_text().strip()

        if page_text:
            # ── Digital text page: use PyMuPDF redaction annotations ──────
            out_doc.insert_pdf(src_doc, from_page=page_num, to_page=page_num)
            out_page = out_doc[-1]

            # kw_replacements not needed for PDFs — visual redaction only
            results = analyze(page_text, analyzer, cfg, kw_replacements={})
            total += len(results)

            for r in results:
                # Get the exact phrase from the extracted text
                phrase = page_text[r.start:r.end].strip()
                if not phrase:
                    continue
                # search_for returns a list of Rects/Quads covering the phrase
                for quad in out_page.search_for(phrase):
                    out_page.add_redact_annot(quad, fill=(0, 0, 0))

            # Apply: permanently removes text and renders black boxes
            out_page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

        else:
            # ── Scanned page: render → OCR → image redact → reinsert ─────
            mat = fitz.Matrix(scale, scale)
            pix = page.get_pixmap(matrix=mat)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

            img, count = redact_image_pixels(img, analyzer, cfg)
            total += count

            # New page at original PDF dimensions (points), filled with redacted image
            new_page = out_doc.new_page(
                width=page.rect.width,
                height=page.rect.height,
            )
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                img.save(tmp_path, format="PNG")
                new_page.insert_image(new_page.rect, filename=tmp_path)
            finally:
                os.unlink(tmp_path)

    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        out_doc.save(str(dst), deflate=True, garbage=3)

    src_doc.close()
    out_doc.close()
    return total


# ── Orchestration ─────────────────────────────────────────────────────────────

def run(input_dir: Path, cfg: dict, dry_run: bool) -> None:
    output_dir = input_dir / cfg["output_dir"]
    if not dry_run:
        output_dir.mkdir(exist_ok=True)

    skip_exts = set(cfg.get("skip_extensions", []))
    stats: dict = {"md": 0, "html": 0, "json": 0, "csv": 0, "pdf": 0, "img": 0,
                   "copy": 0, "uncopied": 0, "skip": 0, "errors": 0}
    total_redactions = 0

    # Collect all files first (excluding the output dir) so we can decide what to load.
    all_files = sorted(f for f in input_dir.rglob("*") if f.is_file())
    files = [f for f in all_files if output_dir not in f.parents]

    # Keyword-only mode (entities empty) redacts text via the stdlib keyword_redactor
    # and loads the spaCy model ONLY when a config-enabled image/PDF is present —
    # images/PDF still need the analyzer for matching on OCR'd text. A text-only
    # keyword run loads no model at all; a text-only config never loads one either.
    BINARY_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp"}
    keyword_only = not cfg.get("entities")
    has_binary = any(f.suffix.lower() in BINARY_EXTS and f.suffix.lower() not in skip_exts
                     for f in files)
    kr = make_keyword_redactor_from_config(cfg) if keyword_only else None
    if (not keyword_only) or has_binary:
        log.info(f"Loading NLP model '{cfg.get('spacy_model', 'en_core_web_lg')}' "
                 f"(first run may take ~30s)…")
        analyzer, kw_replacements = build_analyzer(cfg)
        log.info("NLP model ready.")
    else:
        analyzer, kw_replacements = None, {}
        log.info("Keyword-only, text-only input — skipping spaCy model load.")

    for src in files:
        rel = src.relative_to(input_dir)
        dst = output_dir / rel
        ext = src.suffix.lower()

        try:
            if ext in skip_exts:
                log.debug(f"  SKIP {rel}")
                stats["skip"] += 1
                continue
            if ext == ".md":
                n = process_markdown(src, dst, analyzer, cfg, kw_replacements, dry_run, kr=kr)
                log.info(f"  MD   {rel}  → {n} redaction(s)")
                stats["md"] += 1
                total_redactions += n

            elif ext in (".html", ".htm"):
                n = process_html(src, dst, analyzer, cfg, kw_replacements, dry_run, kr=kr)
                log.info(f"  HTML {rel}  → {n} redaction(s)")
                stats["html"] += 1
                total_redactions += n

            elif ext == ".json":
                n = process_json(src, dst, analyzer, cfg, kw_replacements, dry_run, kr=kr)
                log.info(f"  JSON {rel}  → {n} redaction(s)")
                stats["json"] += 1
                total_redactions += n

            elif ext == ".csv":
                n = process_csv(src, dst, analyzer, cfg, kw_replacements, dry_run, kr=kr)
                log.info(f"  CSV  {rel}  → {n} redaction(s)")
                stats["csv"] += 1
                total_redactions += n

            elif ext == ".pdf":
                n = process_pdf(src, dst, analyzer, cfg, dry_run)
                log.info(f"  PDF  {rel}  → {n} redaction(s)")
                stats["pdf"] += 1
                total_redactions += n

            elif ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
                n = process_image(src, dst, analyzer, cfg, dry_run)
                log.info(f"  IMG  {rel}  → {n} redaction(s)")
                stats["img"] += 1
                total_redactions += n

            else:
                # Unhandled type. Leak guard (default): do NOT copy into redacted/
                # — an unredacted file there looks safe but isn't. Opt in with
                # copy_unhandled: true to mirror the input instead.
                if cfg.get("copy_unhandled", False):
                    if not dry_run:
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dst)
                    stats["copy"] += 1
                else:
                    stats["uncopied"] += 1

        except Exception as exc:
            log.error(f"  ERR  {rel}: {exc}")
            stats["errors"] += 1

    mode = "[DRY RUN] " if dry_run else ""
    log.info(
        f"\n{mode}{'─' * 52}\n"
        f"  Total redactions : {total_redactions}\n"
        f"  Markdown files   : {stats['md']}\n"
        f"  HTML files       : {stats['html']}\n"
        f"  JSON files       : {stats['json']}\n"
        f"  CSV files        : {stats['csv']}\n"
        f"  PDF files        : {stats['pdf']}\n"
        f"  Image files      : {stats['img']}\n"
        f"  Copied unchanged : {stats['copy']}\n"
        f"  Not copied (unhandled) : {stats['uncopied']}\n"
        f"  Skipped entirely : {stats['skip']}\n"
        f"  Errors           : {stats['errors']}\n"
        + (f"  Output at        : {output_dir}\n" if not dry_run else "")
    )

    if stats["uncopied"]:
        log.info(f"  Note: {stats['uncopied']} unhandled file(s) were NOT copied into "
                 f"redacted/ (leak guard). They remain in the source; set "
                 f"copy_unhandled: true in config to mirror them instead.")

    # Keyword-only mode: per-pseudonym count report. text-sub counts come from the
    # keyword_redactor; blackout is N/A until the image/PDF path reports per-keyword
    # counts (binary count parity, a later milestone).
    if kr is not None and kr.mappings:
        from report_format import build_count_report, render_count_report
        report = build_count_report(kr.mappings, kr.counts)
        log.info("\n  Per-pseudonym counts (text-sub | blackout):\n"
                 + render_count_report(report))


# ── Scan (discovery) ──────────────────────────────────────────────────────────

def _iter_json_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_json_strings(v)
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_json_strings(v)


def _texts_for_scan(src: Path, ext: str, cfg: dict):
    """Yield the text chunks to NER-scan for one file (images via OCR)."""
    if ext in (".md", ".txt"):
        yield src.read_text(encoding="utf-8", errors="replace")
    elif ext == ".json":
        yield from _iter_json_strings(
            json.loads(src.read_text(encoding="utf-8-sig", errors="replace")))
    elif ext == ".csv":
        with src.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.reader(f):
                yield from row
    elif ext in (".html", ".htm"):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(src.read_text(encoding="utf-8", errors="replace"),
                             "html.parser")
        yield soup.get_text(" ")
    elif ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        from PIL import Image
        img = Image.open(str(src)).convert("RGB")
        for obs in ocr_image(img, cfg):
            yield obs["text"]
    elif ext == ".pdf":
        import fitz
        doc = fitz.open(str(src))
        try:
            for page in doc:
                text = page.get_text().strip()  # digital pages; scanned-page OCR TODO
                if text:
                    yield text
        finally:
            doc.close()


def scan(input_dir: Path, cfg: dict) -> None:
    """Discovery scan: run NER over text files and LIST candidate identities by
    entity type. Writes nothing. Images/PDF/HTML are not yet scanned."""
    from report_format import collect_entities, render_scan_report

    log.info(f"Loading NLP model '{cfg.get('spacy_model', 'en_core_web_lg')}' for scan…")
    analyzer, _ = build_analyzer(cfg)
    entities = cfg.get("entities") or DEFAULT_CONFIG["entities"]

    output_dir = input_dir / cfg["output_dir"]
    files = [f for f in sorted(input_dir.rglob("*"))
             if f.is_file() and output_dir not in f.parents]
    SCAN_EXTS = {".md", ".txt", ".json", ".csv", ".html", ".htm",
                 ".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf"}

    texts, scanned, skipped = [], 0, 0
    for src in files:
        ext = src.suffix.lower()
        if ext not in SCAN_EXTS:
            skipped += 1
            continue
        try:
            texts.extend(_texts_for_scan(src, ext, cfg))  # images via OCR
            scanned += 1
        except Exception as e:
            log.error(f"  scan skip {src.relative_to(input_dir)}: {e}")

    found = collect_entities(
        texts, lambda t: analyzer.analyze(text=t, entities=entities, language="en"))
    log.info(f"\n[SCAN] {scanned} file(s) scanned, {skipped} unsupported skipped "
             f"(scanned-PDF-page OCR is still TODO).\n"
             + render_scan_report(found))


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    check_imports()

    parser = argparse.ArgumentParser(
        description="Local PII redaction for Notion exports — no cloud, no network."
    )
    parser.add_argument("input_dir", help="Path to your Notion export folder")
    parser.add_argument(
        "--config", default="config.yaml",
        help="Path to YAML config file (default: config.yaml in current dir)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what would be redacted without writing any files"
    )
    parser.add_argument(
        "--scan", action="store_true",
        help="Discovery mode: NER-scan text files and LIST candidate identities "
             "(no redaction, no files written) to seed custom_keywords"
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    input_dir = Path(args.input_dir).expanduser().resolve()

    if not input_dir.is_dir():
        sys.exit(f"Error: not a directory: {input_dir}")

    if args.scan:
        scan(input_dir, cfg)
        return

    if args.dry_run:
        log.info("DRY RUN mode — no files will be written")

    run(input_dir, cfg, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
