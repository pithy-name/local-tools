#!/usr/bin/env python3
"""redact.py — Fully-local PII redaction for a folder of files
──────────────────────────────────────────────────────────────
Handles: Markdown, HTML, PDF (digital + scanned), Images
No network calls. All NLP and OCR runs on-device.

Usage:
    python redact.py /path/to/folder
    python redact.py /path/to/folder --config config.yaml
    python redact.py /path/to/folder --dry-run
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
from collections import Counter
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
    "decode_nested_json": True,  # JSON string values that are themselves JSON (double-encoded
                                 # blobs, e.g. rich-text deltas) → decode, redact inner text, re-encode
    "include_extensions": [          # allowlist of types to process (handled set)
        ".md", ".txt", ".html", ".htm", ".json", ".csv",
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
            if v is None:
                continue  # present-but-empty YAML key (e.g. all examples commented out) → keep default
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k] = {**cfg[k], **v}
            else:
                cfg[k] = v
    return cfg


def _normalize_extensions(items) -> list:
    """Lowercase each extension and ensure a leading dot. 'MD' / '.Json' → '.md' / '.json'."""
    out = []
    for it in items:
        e = str(it).strip().lower()
        if e and not e.startswith("."):
            e = "." + e
        if e:
            out.append(e)
    return out


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
    for item in (cfg.get("custom_keywords") or []):
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


# Presidio emits benign WARNING noise we suppress at the source logger:
#   • "<TYPE> is not mapped to a Presidio entity" — spaCy entity types (CARDINAL,
#     MONEY, …) Presidio has no recognizer for; emitted per-token during analyze().
#   • "Recognizer not added to registry because language is not supported …" —
#     locale-specific predefined recognizers (e.g. the Spanish CreditCardRecognizer,
#     passport recognizers) skipped because this registry is English-only; emitted
#     while the AnalyzerEngine is being constructed.
# Both are expected for an en-only setup. The substring match catches every such
# recognizer regardless of name/language. The filter must be installed BEFORE the
# AnalyzerEngine is built, since the language warning fires during construction.
_BENIGN_PRESIDIO_LOG_SUBSTRINGS = (
    "is not mapped to a Presidio entity",
    "Recognizer not added to registry because language is not supported",
)


class _BenignPresidioFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        return not any(s in msg for s in _BENIGN_PRESIDIO_LOG_SUBSTRINGS)


def _silence_benign_presidio_warnings() -> None:
    """Attach the benign-noise filter to Presidio's loggers (hyphen + underscore
    spellings). Idempotent — safe to call on every build_analyzer()."""
    for name in ("presidio-analyzer", "presidio_analyzer"):
        lg = logging.getLogger(name)
        if not any(isinstance(f, _BenignPresidioFilter) for f in lg.filters):
            lg.addFilter(_BenignPresidioFilter())


# Blanket http(s) URL pattern (case-insensitive scheme; \S+ grabs the whole URL
# token up to whitespace — trailing punctuation is intentionally included).
URL_REGEX = r"(?i)https?://\S+"


def _register_url_recognizer(analyzer, cfg: dict, kw_replacements: dict) -> bool:
    """Opt-in blanket URL redaction. When 'URL' is listed in `entities`, register a
    recognizer for the URL pattern and map the URL entity to the literal '[URL]'
    replacement (via kw_replacements, which anonymize() honors). Returns True if
    registered. URLs are untouched unless 'URL' is enabled."""
    if "URL" not in cfg.get("entities", DEFAULT_CONFIG["entities"]):
        return False
    from presidio_analyzer import PatternRecognizer, Pattern
    pattern = Pattern(name="url", regex=URL_REGEX, score=0.9)
    analyzer.registry.add_recognizer(
        PatternRecognizer(supported_entity="URL", patterns=[pattern]))
    kw_replacements["URL"] = "[URL]"
    return True


def build_analyzer(cfg: dict) -> tuple:
    """
    Return (AnalyzerEngine, kw_replacements).
    kw_replacements maps entity_type → replacement string (or None for default).
    Each keyword gets its own entity type KW_0, KW_1, … so per-entry replacements work.
    """
    from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
    from presidio_analyzer.nlp_engine import NlpEngineProvider

    # Install before the engine/registry is built — the unsupported-language
    # warnings fire during AnalyzerEngine construction below.
    _silence_benign_presidio_warnings()

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

    if _register_url_recognizer(analyzer, cfg, kw_replacements):
        log.info("URL redaction enabled — http(s) URLs will be replaced with [URL].")

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


def _deoverlap(results: list) -> list:
    """Drop spans fully contained within a longer/higher-priority span."""
    by_length = sorted(results, key=lambda r: r.end - r.start, reverse=True)
    kept = []
    for r in by_length:
        if not any(k.start <= r.start and r.end <= k.end for k in kept):
            kept.append(r)
    return kept


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
    Overlapping/contained spans: the longer (outer) span wins; the shorter is dropped.
    """
    if not results:
        return text
    kw_replacements = kw_replacements or {}
    kept = _deoverlap(results)
    buf = list(text)
    for r in sorted(kept, key=lambda r: r.start, reverse=True):
        per_entity = kw_replacements.get(r.entity_type)  # None if not a KW entity
        replacement = per_entity if per_entity is not None else default_replacement
        buf[r.start:r.end] = list(replacement)
    return "".join(buf)


# ── Text file handlers ────────────────────────────────────────────────────────

def _redact_text(text, analyzer, cfg: dict, kw_replacements: dict, kr, collector=None) -> tuple:
    """Redact one string → (redacted, n_swaps).

    kr (a keyword_redactor.KeywordRedactor, keyword-only mode) wins when set —
    no spaCy. Otherwise the NER+keyword analyzer path. n_swaps is per-call.
    collector, when set, accumulates {entity_type: {text: count}} for dry-run reporting.
    """
    if kr is not None:
        before = sum(kr.counts.values())
        out = kr.redact(text)
        return out, sum(kr.counts.values()) - before
    results = analyze(text, analyzer, cfg, kw_replacements)
    kept = _deoverlap(results)
    if collector is not None:
        # Collect from kept (post-deoverlap) — the spans actually redacted — so the
        # report's counts equal the real redaction count, not the raw pre-overlap hits.
        for r in kept:
            entity_text = text[r.start:r.end]
            bucket = collector.setdefault(r.entity_type, {})
            bucket[entity_text] = bucket.get(entity_text, 0) + 1
    return anonymize(text, kept, cfg["replacement"], kw_replacements), len(kept)


def process_markdown(
    src: Path, dst: Path, analyzer, cfg: dict, kw_replacements: dict, dry_run: bool,
    kr=None, collector=None
) -> int:
    text = src.read_text(encoding="utf-8", errors="replace")
    redacted, n = _redact_text(text, analyzer, cfg, kw_replacements, kr, collector)
    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(redacted, encoding="utf-8")
    return n


def process_html(
    src: Path, dst: Path, analyzer, cfg: dict, kw_replacements: dict, dry_run: bool,
    kr=None, collector=None
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
        redacted, n = _redact_text(text, analyzer, cfg, kw_replacements, kr, collector)
        total += n
        if n and not dry_run:
            node.replace_with(redacted)

    # Also scrub mailto: href attributes (emails in links)
    for tag in soup.find_all("a", href=re.compile(r"^mailto:", re.I)):
        href = tag.get("href", "")
        redacted, n = _redact_text(href, analyzer, cfg, kw_replacements, kr, collector)
        total += n
        if n and not dry_run:
            tag["href"] = redacted

    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(str(soup), encoding="utf-8")

    return total


def _looks_like_json(s: str) -> bool:
    """Cheap pre-check before a json.loads probe: only strings that begin with
    `{` or `[` could be a nested JSON object/array, so skip the parse on everything
    else (the overwhelmingly common case is plain prose)."""
    t = s.lstrip()
    return bool(t) and t[0] in "[{"


def _walk_json(obj, redact_one, decode_nested=True):
    """Recursively redact string VALUES via redact_one(s)->(s', n). Keys and
    non-strings pass through. Returns (new_obj, total_swaps).

    When decode_nested is set (config: decode_nested_json), a string value that is
    ITSELF serialized JSON — a double-encoded blob, e.g. a rich-text delta stored as
    a string — is decoded, its inner string values redacted the same way, then
    re-encoded. This lets the analyzer read clean text runs instead of raw markup
    (otherwise NER tags JSON syntax as bogus entities), and the file round-trips.
    Fully generic: no field names are assumed."""
    if isinstance(obj, str):
        if decode_nested and _looks_like_json(obj):
            try:
                inner = json.loads(obj)
            except ValueError:
                inner = None
            if isinstance(inner, (dict, list)):
                new_inner, n = _walk_json(inner, redact_one, decode_nested)
                return json.dumps(new_inner, ensure_ascii=False), n
        return redact_one(obj)
    if isinstance(obj, list):
        out, total = [], 0
        for v in obj:
            nv, n = _walk_json(v, redact_one, decode_nested)
            out.append(nv)
            total += n
        return out, total
    if isinstance(obj, dict):
        out, total = {}, 0
        for k, v in obj.items():
            nv, n = _walk_json(v, redact_one, decode_nested)
            out[k] = nv
            total += n
        return out, total
    return obj, 0


def process_json(
    src: Path, dst: Path, analyzer, cfg: dict, kw_replacements: dict, dry_run: bool,
    kr=None, collector=None
) -> int:
    """Parse-aware JSON redaction: redact string VALUES only, re-serialize valid
    JSON. Keys, numbers, bools, nulls pass through; originals never modified."""
    data = json.loads(src.read_text(encoding="utf-8-sig", errors="replace"))
    redacted, total = _walk_json(
        data, lambda s: _redact_text(s, analyzer, cfg, kw_replacements, kr, collector),
        decode_nested=cfg.get("decode_nested_json", True))
    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(json.dumps(redacted, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
    return total


def process_csv(
    src: Path, dst: Path, analyzer, cfg: dict, kw_replacements: dict, dry_run: bool,
    kr=None, collector=None
) -> int:
    """Redact every cell of a CSV, preserving structure (csv.reader/writer)."""
    rows_out, total = [], 0
    with src.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f):
            new_row = []
            for cell in row:
                red, n = _redact_text(cell, analyzer, cfg, kw_replacements, kr, collector)
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
    raise RuntimeError(
        "No OCR backend available (Apple Vision and Tesseract both disabled or missing). "
        "Cannot safely process images — original would be copied unredacted."
    )


def _ocr_backend_available(cfg: dict) -> bool:
    """Return True if at least one OCR backend will work for this config."""
    if cfg["ocr"].get("use_apple_vision", True) and apple_vision_available():
        return True
    if cfg["ocr"].get("fallback_tesseract", True):
        try:
            import pytesseract  # noqa: F401
            if shutil.which("tesseract"):
                return True
        except ImportError:
            pass
    return False


# ── Image redaction ───────────────────────────────────────────────────────────

def redact_image_pixels(img, analyzer, cfg: dict, collector=None):
    """
    OCR the image, run Presidio on each text observation, black out sensitive regions.
    Returns (modified PIL.Image, num_redactions, blackout_counts) — blackout_counts is a
    Counter keyed by the matched keyword's `find` (for the per-keyword report).
    collector, when set, accumulates {entity_type: {matched_text: count}} so image/PDF
    matches are itemized in the unified report alongside text matches.
    Conservative: if any PII found in a line's observation, the whole bounding box
    is blacked out — no partial-line sub-pixel surgery needed.
    """
    from PIL import ImageDraw

    # KW_{i} entity types map back to the i-th configured keyword (see build_analyzer).
    kw_finds = {f"KW_{i}": kw["find"] for i, kw in enumerate(normalize_keywords(cfg))}
    keyword_only = not cfg.get("entities")
    # Always detect the keyword (KW_*) types — custom keywords apply on images/PDFs too;
    # in NER mode get_entities() adds the configured entities. Keyword-only mode → KW only
    # (no NER). With NO keywords in keyword-only mode there's nothing to detect — return
    # early rather than let an empty filter fall through to "detect everything".
    if keyword_only and not kw_finds:
        return img, 0, Counter()
    ent_filter = kw_finds
    observations = ocr_image(img, cfg)
    draw = ImageDraw.Draw(img)
    count = 0
    blackout = Counter()

    for obs in observations:
        # visual redaction always uses a black box (no text replacement needed)
        results = analyze(obs["text"], analyzer, cfg, ent_filter)
        if results:
            # Black out the entire observation region
            draw.rectangle(obs["bbox_pixels"], fill=(0, 0, 0))
            count += len(results)
            for r in results:
                find = kw_finds.get(r.entity_type)
                if find is not None:
                    blackout[find] += 1
                if collector is not None:
                    entity_text = obs["text"][r.start:r.end]
                    bucket = collector.setdefault(r.entity_type, {})
                    bucket[entity_text] = bucket.get(entity_text, 0) + 1

    return img, count, blackout


def process_image(src: Path, dst: Path, analyzer, cfg: dict, dry_run: bool, collector=None):
    """Returns (num_redactions, blackout_counts)."""
    from PIL import Image

    img = Image.open(str(src)).convert("RGB")
    img, count, blackout = redact_image_pixels(img, analyzer, cfg, collector=collector)

    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if count:
            img.save(str(dst))
        else:
            shutil.copy2(src, dst)  # no changes needed — copy original

    return count, blackout


# ── PDF redaction ─────────────────────────────────────────────────────────────

def process_pdf(src: Path, dst: Path, analyzer, cfg: dict, dry_run: bool, collector=None):
    """
    Digital pages  → PyMuPDF native redaction annotations (preserves PDF structure).
    Scanned pages  → Render to image → Apple Vision OCR → black boxes → reinsert.
    Output is a new PDF saved to dst. Returns (num_redactions, blackout_counts).
    collector, when set, accumulates {entity_type: {matched_text: count}} so PDF
    matches are itemized in the unified report alongside text matches.
    """
    import fitz
    from PIL import Image

    kw_finds = {f"KW_{i}": kw["find"] for i, kw in enumerate(normalize_keywords(cfg))}
    keyword_only = not cfg.get("entities")
    no_detect = keyword_only and not kw_finds   # keyword-only + no keywords → detect nothing
    ent_filter = kw_finds   # KW types always; NER mode adds configured entities (get_entities)
    dpi = cfg["ocr"].get("dpi", 200)
    scale = dpi / 72.0
    total = 0
    blackout = Counter()

    src_doc = fitz.open(str(src))
    out_doc = fitz.open()

    for page_num in range(len(src_doc)):
        page = src_doc[page_num]
        page_text = page.get_text().strip()

        if page_text:
            # ── Digital text page: use PyMuPDF redaction annotations ──────
            out_doc.insert_pdf(src_doc, from_page=page_num, to_page=page_num)
            out_page = out_doc[-1]

            # visual redaction only (no text replacement); keyword-only → no NER
            results = [] if no_detect else analyze(page_text, analyzer, cfg, ent_filter)

            for r in results:
                find = kw_finds.get(r.entity_type)
                phrase = page_text[r.start:r.end].strip()
                if not phrase:
                    continue
                # Count and annotate only when search_for confirms placement.
                # search_for returns [] on line-wrapped/ligature/whitespace mismatch —
                # incrementing before the call would silently report a phantom redaction.
                quads = out_page.search_for(phrase)
                if not quads:
                    log.warning(
                        f"  PDF p{page_num+1}: phrase not found in rendered layout "
                        f"(possible line-wrap/ligature): {phrase!r}"
                    )
                    continue
                total += 1
                if find is not None:
                    blackout[find] += 1
                if collector is not None:
                    bucket = collector.setdefault(r.entity_type, {})
                    bucket[phrase] = bucket.get(phrase, 0) + 1
                for quad in quads:
                    out_page.add_redact_annot(quad, fill=(0, 0, 0))

            # Apply: permanently removes text and renders black boxes
            out_page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

        else:
            # ── Scanned page: render → OCR → image redact → reinsert ─────
            mat = fitz.Matrix(scale, scale)
            pix = page.get_pixmap(matrix=mat)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

            img, count, page_blackout = redact_image_pixels(img, analyzer, cfg, collector=collector)
            total += count
            blackout.update(page_blackout)

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
    return total, blackout


# ── Orchestration ─────────────────────────────────────────────────────────────

def _copy_or_skip_unhandled(src: Path, dst: Path, cfg: dict, dry_run: bool, stats: dict) -> bool:
    """Leak guard: copy an unhandled/not-allowlisted file into redacted/ only if
    copy_unhandled is set; otherwise leave it in the source and tally it. Returns True
    when the file was left uncopied (so the caller can record its path)."""
    if cfg.get("copy_unhandled", False):
        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        stats["copy"] += 1
        return False
    stats["uncopied"] += 1
    return True


def _merge_collector(dst: dict, src: dict) -> None:
    """Fold a per-file {entity_type: {text: count}} tally into the run-level collector."""
    for etype, texts in src.items():
        bucket = dst.setdefault(etype, {})
        for text, count in texts.items():
            bucket[text] = bucket.get(text, 0) + count


def run(input_dir: Path, cfg: dict, dry_run: bool) -> int:
    """Process all files in input_dir. Returns the number of per-file errors."""
    output_dir = input_dir / cfg["output_dir"]
    if not dry_run:
        output_dir.mkdir(exist_ok=True)

    skip_exts = set(cfg.get("skip_extensions", []))
    stats: dict = {"md": 0, "txt": 0, "html": 0, "json": 0, "csv": 0, "pdf": 0, "img": 0,
                   "copy": 0, "uncopied": 0, "skip": 0, "errors": 0}
    total_redactions = 0
    files_with_matches = 0   # files with >=1 redaction (for the report header)

    # Collect all files first (excluding the output dir) so we can decide what to load.
    all_files = sorted(f for f in input_dir.rglob("*") if f.is_file())
    files = [f for f in all_files if output_dir not in f.parents]

    # Keyword-only mode (entities empty) redacts text via the stdlib keyword_redactor
    # and loads the spaCy model ONLY when a config-enabled image/PDF is present —
    # images/PDF still need the analyzer for matching on OCR'd text. A text-only
    # keyword run loads no model at all; a text-only config never loads one either.
    BINARY_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp"}
    keyword_only = not cfg.get("entities")
    # One tally feeds the unified end-of-run report for EVERY mode, dry-run AND real run
    # (real==dry). Populated by the NER text path (_redact_text) and the image/PDF path;
    # keyword-only text counts come from kr.counts and are merged in at report time.
    collector: dict = {}
    include_set = set(_normalize_extensions(cfg.get("include_extensions", [])))
    # Only count a binary as "will be processed" if it passes the include_extensions allowlist.
    has_binary = any(
        f.suffix.lower() in BINARY_EXTS
        and f.suffix.lower() not in skip_exts
        and (not include_set or f.suffix.lower() in include_set)
        for f in files
    )
    if has_binary and not _ocr_backend_available(cfg):
        log.error(
            "No OCR backend (Apple Vision or Tesseract) is available, but images/PDFs "
            "are present. Cannot safely process — original files would be copied unredacted. "
            "Install Tesseract (brew install tesseract) or run on macOS with Apple Vision."
        )
        sys.exit(1)
    kr = make_keyword_redactor_from_config(cfg) if keyword_only else None
    if (not keyword_only) or has_binary:
        log.info(f"Loading NLP model '{cfg.get('spacy_model', 'en_core_web_lg')}' "
                 f"(first run may take ~30s)…")
        analyzer, kw_replacements = build_analyzer(cfg)
        log.info("NLP model ready.")
    else:
        analyzer, kw_replacements = None, {}
        log.info("Keyword-only, text-only input — skipping spaCy model load.")

    uncopied_paths = []           # leak guard: files left in the source (not copied)
    error_files = []              # files that raised during processing
    for src in files:
        rel = src.relative_to(input_dir)
        dst = output_dir / rel
        ext = src.suffix.lower()

        try:
            n = 0
            # Per-file tally: merged into the run-level collector ONLY on success
            # (below). A handler that raises mid-file leaves its partial matches here,
            # discarded — so the report's grand_total never counts a failed file that
            # total_redactions excluded (keeps grand_total == total_redactions).
            file_collector: dict = {}
            if ext in skip_exts:
                log.debug(f"  SKIP {rel}")
                stats["skip"] += 1
                continue
            if include_set and ext not in include_set:
                # not in the allowlist → unhandled (leak guard / copy_unhandled)
                if _copy_or_skip_unhandled(src, dst, cfg, dry_run, stats):
                    uncopied_paths.append(str(rel))
                continue
            if ext == ".md":
                n = process_markdown(src, dst, analyzer, cfg, kw_replacements, dry_run, kr=kr, collector=file_collector)
                log.info(f"  MD   {rel}  → {n} redaction(s)")
                stats["md"] += 1
                total_redactions += n

            elif ext == ".txt":
                n = process_markdown(src, dst, analyzer, cfg, kw_replacements, dry_run, kr=kr, collector=file_collector)
                log.info(f"  TXT  {rel}  → {n} redaction(s)")
                stats["txt"] += 1
                total_redactions += n

            elif ext in (".html", ".htm"):
                n = process_html(src, dst, analyzer, cfg, kw_replacements, dry_run, kr=kr, collector=file_collector)
                log.info(f"  HTML {rel}  → {n} redaction(s)")
                stats["html"] += 1
                total_redactions += n

            elif ext == ".json":
                n = process_json(src, dst, analyzer, cfg, kw_replacements, dry_run, kr=kr, collector=file_collector)
                log.info(f"  JSON {rel}  → {n} redaction(s)")
                stats["json"] += 1
                total_redactions += n

            elif ext == ".csv":
                n = process_csv(src, dst, analyzer, cfg, kw_replacements, dry_run, kr=kr, collector=file_collector)
                log.info(f"  CSV  {rel}  → {n} redaction(s)")
                stats["csv"] += 1
                total_redactions += n

            elif ext == ".pdf":
                n, _ = process_pdf(src, dst, analyzer, cfg, dry_run, collector=file_collector)
                log.info(f"  PDF  {rel}  → {n} redaction(s)")
                stats["pdf"] += 1
                total_redactions += n

            elif ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
                n, _ = process_image(src, dst, analyzer, cfg, dry_run, collector=file_collector)
                log.info(f"  IMG  {rel}  → {n} redaction(s)")
                stats["img"] += 1
                total_redactions += n

            else:
                # Allowlisted but no handler for this type → leak guard.
                if _copy_or_skip_unhandled(src, dst, cfg, dry_run, stats):
                    uncopied_paths.append(str(rel))

            # Reached only if no handler raised → commit this file's matches + tally.
            _merge_collector(collector, file_collector)
            if n:
                files_with_matches += 1

        except Exception as exc:
            log.error(f"  ERR  {rel}: {exc}")
            stats["errors"] += 1
            error_files.append(str(rel))

    mode = "[DRY RUN] " if dry_run else ""
    log.info(
        f"\n{mode}{'─' * 52}\n"
        f"  Total redactions : {total_redactions}\n"
        f"  Markdown files   : {stats['md']}\n"
        f"  Plain text files : {stats['txt']}\n"
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
        for p in uncopied_paths:
            log.info(f"    not copied: {p}")

    if error_files:
        log.warning(
            f"\n  FAILED — {len(error_files)} file(s) could not be processed:\n"
            + "\n".join(f"    {p}" for p in error_files)
        )

    # Unified end-of-run report — the SAME report for --dry-run and a real write run
    # (real==dry), in EVERY mode. Sourced from one tally: the collector (NER text +
    # image/PDF matches) merged with keyword_redactor's per-find counts (keyword-only
    # text). Matched text is printed (audit visibility) — same exposure as --scan.
    from report_format import (
        assemble_report_inputs, build_redaction_report, render_redaction_report)
    keywords = normalize_keywords(cfg)
    kr_counts = kr.counts if kr is not None else None
    entity_tally, keyword_tally = assemble_report_inputs(
        collector, keywords, kr_counts=kr_counts)
    # Per-entity replacement tokens (e.g. URL → [URL]); KW_* are reported separately.
    entity_repls = {k: v for k, v in (kw_replacements or {}).items()
                    if not k.startswith("KW_") and v is not None}
    rep = build_redaction_report(
        entity_tally, keyword_tally,
        replacement_char=cfg["replacement"], entity_replacements=entity_repls)
    files_scanned = (stats["md"] + stats["txt"] + stats["html"] + stats["json"]
                     + stats["csv"] + stats["pdf"] + stats["img"])
    report_text = render_redaction_report(
        rep,
        title="REDACTION PREVIEW (--dry-run)" if dry_run else "REDACTION COMPLETE",
        files_scanned=files_scanned,
        files_matched=files_with_matches,
        extensions=sorted(include_set) if include_set else None,
        output_dir=None if dry_run else output_dir,
    )
    log.info("\n" + report_text)

    return stats["errors"]


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
        from PIL import Image
        scale = cfg.get("ocr", {}).get("dpi", 200) / 72.0
        doc = fitz.open(str(src))
        try:
            for page in doc:
                text = page.get_text().strip()
                if text:
                    yield text                       # digital page
                else:
                    # scanned page: render → OCR (mirrors the redact path)
                    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    for obs in ocr_image(img, cfg):
                        yield obs["text"]
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

    OCR_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf"}
    has_ocr_files = any(f.suffix.lower() in OCR_EXTS for f in files
                        if f.suffix.lower() in SCAN_EXTS)
    if has_ocr_files and not _ocr_backend_available(cfg):
        log.warning(
            "OCR backend unavailable (Apple Vision and Tesseract both disabled or missing). "
            "Image and PDF files will be skipped during scan."
        )

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
    log.info(f"\n[SCAN] {scanned} file(s) scanned, {skipped} unsupported skipped.\n"
             + render_scan_report(found))


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    check_imports()

    parser = argparse.ArgumentParser(
        description="Local PII redaction for a folder of files — no cloud, no network."
    )
    parser.add_argument("input_dir", help="Path to the folder to redact")
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
    parser.add_argument(
        "--include", default=None,
        help="Comma-separated extensions to process this run (e.g. '.md,.txt'), "
             "overriding include_extensions in the config"
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.include:
        cfg["include_extensions"] = _normalize_extensions(args.include.split(","))
    input_dir = Path(args.input_dir).expanduser().resolve()

    if not input_dir.is_dir():
        sys.exit(f"Error: not a directory: {input_dir}")

    if args.scan:
        scan(input_dir, cfg)
        return

    if args.dry_run:
        log.info("DRY RUN mode — no files will be written")

    errors = run(input_dir, cfg, dry_run=args.dry_run)
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
