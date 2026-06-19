"""report_format.py — the unified end-of-run redaction report (stdlib only).

Four fixed subsections (PATTERN MATCHES / MODEL ENTITIES /
CUSTOM KEYWORDS blacked out / CUSTOM KEYWORDS replaced), always rendered,
empty = none (engaged, no matches) or N/A (mechanism not engaged).
Identical output for --dry-run and real runs (real==dry requirement).
"""
from __future__ import annotations

from collections import Counter, OrderedDict, defaultdict


# ── Scan (discovery) report — lists candidate identities, no pseudonyms yet ──

def collect_entities(texts, analyze_fn) -> dict:
    """texts: iterable of strings. analyze_fn(text) -> results with
    .entity_type/.start/.end. Returns {entity_type: Counter(matched_string)}."""
    found: "defaultdict[str, Counter]" = defaultdict(Counter)
    for text in texts:
        if not text or not text.strip():
            continue
        for r in analyze_fn(text):
            found[r.entity_type][text[r.start:r.end]] += 1
    return found


def render_scan_report(found) -> str:
    if not found:
        return "  No candidate entities found."
    lines = ["  Candidate entities (real PII — do not commit this output):"]
    for etype in sorted(found):
        items = found[etype].most_common()
        lines.append(f"  {etype}  ({len(items)} unique)")
        width = max((len(t) for t, _ in items), default=0)
        for text, n in items:
            lines.append(f"    {text.ljust(width)}  ... {n}")
    return "\n".join(lines)


# ── Unified end-of-run report (dry-run preview AND real write run) ──────────────
#
# The SAME report prints for `--dry-run` and a real write run — byte-identical
# bodies, only the title / "Output at:" lines differ (the real==dry requirement;
# see plans/decisions.md). Four fixed subsections, always rendered, empty = "none":
#   PATTERN MATCHES (regex)  ·  MODEL ENTITIES (NER)
#   CUSTOM KEYWORDS — blacked out  ·  CUSTOM KEYWORDS — replaced

# Presidio entity types detected by a regex PatternRecognizer (deterministic),
# NOT the spaCy NER model. Anything else is treated as model NER (probabilistic).
REGEX_ENTITIES = {
    "EMAIL_ADDRESS", "URL", "PHONE_NUMBER", "CREDIT_CARD", "CRYPTO",
    "IBAN_CODE", "IP_ADDRESS", "US_SSN", "US_BANK_NUMBER", "US_DRIVER_LICENSE",
    "US_ITIN", "US_PASSPORT", "MEDICAL_LICENSE",
}


def entity_engine(entity_type: str) -> str:
    """Classify a Presidio entity type by detection mechanism.

    'regex' = deterministic PatternRecognizer (EMAIL_ADDRESS, URL, PHONE_NUMBER, …);
    'NER'   = probabilistic spaCy model (PERSON, ORGANIZATION, LOCATION, …).
    Drives the PATTERN MATCHES vs MODEL ENTITIES split. Pure + model-free so the
    report builder is unit-testable. (Custom keywords KW_* are reported separately,
    not classified here.)
    """
    return "regex" if entity_type in REGEX_ENTITIES else "NER"


def _rows_by_count_desc(counts) -> list:
    """{text: count} → [{text, count}] sorted by count desc, then text A-Z.

    Matched text is whitespace-collapsed for display (a span crossing a line break —
    e.g. a name wrapped across two lines, or a JSON/CSV value with embedded newlines —
    would otherwise inject literal newlines and break the report layout). Length is NOT
    truncated: this is an audit report, so the full matched text stays visible.
    """
    return [{"text": " ".join(t.split()) or repr(t), "count": c}
            for t, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def build_redaction_report(entity_tally, keyword_tally, *,
                           replacement_char="█████",
                           entity_replacements=None, engaged=None) -> dict:
    """Build the structured end-of-run report from a tally (no model needed).

    entity_tally:  {entity_type: {matched_text: count}} — non-keyword entities.
    keyword_tally: [{find, replace, count}] — replace=None → blacked out,
                   replace=<str> → that pseudonym.
    replacement_char: default blackout display token (e.g. "█████").
    entity_replacements: per-type token overrides, e.g. {"URL": "[URL]"};
                   any type not present falls back to replacement_char.
    engaged: {"pattern"/"model"/"blackout"/"replaced": bool} — whether each
                   subsection's detection mechanism ran this configuration. An EMPTY
                   subsection renders `none` when engaged (ran, matched nothing) vs
                   `N/A` when not engaged (nothing of that kind configured). Defaults
                   to all True (so empty → none) when not supplied.
    """
    entity_replacements = entity_replacements or {}
    engaged = engaged or {}
    engaged = {k: engaged.get(k, True)
               for k in ("pattern", "model", "blackout", "replaced")}

    pattern_matches, model_entities = [], []
    for etype in sorted(entity_tally):
        counts = entity_tally[etype]
        block = {
            "entity_type": etype,
            "unique": len(counts),
            "hits": sum(counts.values()),
            "replacement": entity_replacements.get(etype, replacement_char),
            "rows": _rows_by_count_desc(counts),
        }
        (pattern_matches if entity_engine(etype) == "regex"
         else model_entities).append(block)

    blackout_counts: "OrderedDict[str, int]" = OrderedDict()
    replaced_groups: "OrderedDict[str, OrderedDict]" = OrderedDict()
    for k in keyword_tally:
        find, replace, count = k["find"], k.get("replace"), k["count"]
        if replace is None:
            blackout_counts[find] = blackout_counts.get(find, 0) + count
        else:
            grp = replaced_groups.setdefault(replace, OrderedDict())
            grp[find] = grp.get(find, 0) + count

    keywords_blackout = {
        "unique": len(blackout_counts),
        "hits": sum(blackout_counts.values()),
        "replacement": replacement_char,
        "rows": _rows_by_count_desc(blackout_counts),
    }

    keywords_replaced = []
    for pseudo in sorted(replaced_groups):
        finds = replaced_groups[pseudo]
        keywords_replaced.append({
            "pseudonym": pseudo,
            "aliases": len(finds),
            "hits": sum(finds.values()),
            "rows": _rows_by_count_desc(finds),
        })

    grand_total = (
        sum(b["hits"] for b in pattern_matches)
        + sum(b["hits"] for b in model_entities)
        + keywords_blackout["hits"]
        + sum(g["hits"] for g in keywords_replaced)
    )

    return {
        "pattern_matches": pattern_matches,
        "model_entities": model_entities,
        "keywords_blackout": keywords_blackout,
        "keywords_replaced": keywords_replaced,
        "grand_total": grand_total,
        "engaged": engaged,
    }


def assemble_report_inputs(collector, keywords, kr_counts=None):
    """Bridge redact.py's runtime tallies → build_redaction_report() inputs.

    collector:  {entity_type: {matched_text: count}} accumulated during the run.
                Non-keyword types (EMAIL_ADDRESS, URL, PERSON, …) become entity_tally;
                KW_<i> types map back to the i-th configured keyword.
    keywords:   normalize_keywords(cfg) output — [{find, replace}] in KW index order
                (replace=None → blacked out, str → pseudonym).
    kr_counts:  keyword_redactor's per-find Counter (keyword-only text mode), merged in
                so a keyword matched in BOTH a text file (kr) and an image (collector)
                is summed. None in NER mode.

    Returns (entity_tally, keyword_tally). Keywords with zero total hits are omitted.
    Single source for the unified report across every mode — text and image/PDF, NER
    and keyword-only — so grand_total == the run's total redactions.
    """
    collector = collector or {}
    kr_counts = kr_counts or {}

    entity_tally = {}
    kw_by_index = {}  # KW index -> count from collector
    for etype, texts in collector.items():
        if etype.startswith("KW_"):
            idx = int(etype.split("_", 1)[1])
            kw_by_index[idx] = kw_by_index.get(idx, 0) + sum(texts.values())
        else:
            entity_tally[etype] = dict(texts)

    keyword_tally = []
    for idx, kw in enumerate(keywords):
        count = kw_by_index.get(idx, 0) + kr_counts.get(kw["find"], 0)
        if count:
            keyword_tally.append(
                {"find": kw["find"], "replace": kw["replace"], "count": count})

    return entity_tally, keyword_tally


_RULE = "═" * 68
_THIN = "─" * 48
_TOTAL_RULE = "─" * 50


# Per-subsection reason text for the two empty states: (N/A reason, none reason).
# N/A = mechanism not engaged this run; none = engaged but matched nothing.
_REASONS = {
    "pattern":  ("no regex entity types configured", "regex active, no matches"),
    "model":    ("no NER types configured",          "NER active, no matches"),
    "blackout": ("no plain keywords configured",     "plain keywords active, no matches"),
    "replaced": ("no pseudonym keywords configured", "pseudonym keywords active, no matches"),
}


def _render_empty(lines, engaged_map, key) -> None:
    """Render an empty subsection as `none` (engaged, no matches) or `N/A` (not
    engaged), each with a `← <reason>` annotation."""
    na_reason, none_reason = _REASONS[key]
    if engaged_map.get(key, True):
        lines.append(f"    none   ← {none_reason}")
    else:
        lines.append(f"    N/A    ← {na_reason}")


def _render_entity_blocks(lines, blocks) -> None:
    for b in blocks:
        head = f"{b['entity_type'].ljust(14)} ({b['unique']} unique · {b['hits']} hits)"
        lines.append(f"{head.ljust(48)} → {b['replacement']}")
        for row in b["rows"]:
            lines.append(f"    {row['text'].ljust(28)} ×{row['count']}")


def _render_blackout(lines, block) -> None:
    head = f"{''.ljust(14)} ({block['unique']} unique · {block['hits']} hits)"
    lines.append(f"{head.ljust(48)} → {block['replacement']}")
    for row in block["rows"]:
        lines.append(f"    {row['text'].ljust(28)} ×{row['count']}")


def _render_replaced(lines, groups) -> None:
    for g in groups:
        word = "alias" if g["aliases"] == 1 else "aliases"
        lines.append(
            f"{g['pseudonym'].ljust(14)} ({g['aliases']} {word} · {g['hits']} hits)")
        for row in g["rows"]:
            lines.append(f"    {row['text'].ljust(28)} ×{row['count']}")


def _render_filename_section(lines, stats) -> None:
    """Filename-redaction summary. The end-of-run report is already a keep-local PII doc
    (it lists matched text in full), so old→new names and plain-keyword leaks are itemized
    here too — and ALSO written to redacted/_filename-renames.txt + _filename-flags.txt."""
    lines.append("FILENAME REDACTIONS")
    lines.append(_THIN)
    lines.append(f"    Files renamed      : {stats.get('files_renamed', 0)}")
    lines.append(f"    Dir parts renamed  : {stats.get('dirs_renamed', 0)}")
    lines.append(f"    Collisions resolved: {stats.get('collisions', 0)}")
    lines.append(f"    Plain-keyword leaks: {stats.get('flagged_files', 0)}")
    skipped = stats.get("skipped_short") or []
    note = f"  ← below filename_min_match_len: {', '.join(skipped)}" if skipped else ""
    lines.append(f"    Short terms skipped: {len(skipped)}{note}")

    renames = stats.get("renames") or []
    if renames:
        lines.append("")
        lines.append("    Renamed (old → new):")
        w = max(len(o) for o, _ in renames)
        for old, new in renames:
            lines.append(f"      {old.ljust(w)}  → {new}")

    flags = stats.get("flags") or []
    if flags:
        lines.append("")
        lines.append("    Plain-keyword leaks (no alias — add one or rename by hand):")
        w = max(len(n) for n, _ in flags)
        for name, terms in flags:
            lines.append(f"      {name.ljust(w)}  ← {', '.join(terms)}")
    lines.append("")


def render_redaction_report(report, *, title, files_scanned, files_matched,
                            extensions=None, output_dir=None,
                            filename_stats=None) -> str:
    """Render build_redaction_report() output as text.

    title: "REDACTION PREVIEW (--dry-run)" or "REDACTION COMPLETE".
    output_dir: when set (a real run), adds an "Output at:" line — the ONLY body
    difference from a dry-run; everything from PATTERN MATCHES down is identical.
    filename_stats: when set (redact_filenames engaged), adds a counts-only
    FILENAME REDACTIONS section — identical in dry-run and real runs (the caller
    passes the same stats to both, preserving the real==dry requirement). None when
    the feature is off → section omitted.
    """
    ext_str = ", ".join(extensions) if extensions else "(all configured)"
    lines = [_RULE, f"  {title}"]
    if output_dir is not None:
        lines.append(f"  Output at: {output_dir}")
    lines.append(
        f"  Extensions scanned: {ext_str}        "
        f"{files_scanned} files scanned · {files_matched} with matches")
    lines.append(_RULE)
    lines.append("")

    eng = report.get("engaged", {})

    lines.append("PATTERN MATCHES  (regex — deterministic)")
    lines.append(_THIN)
    if report["pattern_matches"]:
        _render_entity_blocks(lines, report["pattern_matches"])
    else:
        _render_empty(lines, eng, "pattern")
    lines.append("")

    lines.append("MODEL ENTITIES  (spaCy NER — probabilistic)")
    lines.append(_THIN)
    if report["model_entities"]:
        _render_entity_blocks(lines, report["model_entities"])
    else:
        _render_empty(lines, eng, "model")
    lines.append("")

    lines.append("CUSTOM KEYWORDS — blacked out")
    lines.append(_THIN)
    if report["keywords_blackout"]["rows"]:
        _render_blackout(lines, report["keywords_blackout"])
    else:
        _render_empty(lines, eng, "blackout")
    lines.append("")

    lines.append("CUSTOM KEYWORDS — replaced")
    lines.append(_THIN)
    if report["keywords_replaced"]:
        _render_replaced(lines, report["keywords_replaced"])
    else:
        _render_empty(lines, eng, "replaced")
    lines.append("")

    if filename_stats is not None:
        _render_filename_section(lines, filename_stats)

    lines.append(_TOTAL_RULE)
    lines.append(
        f"  GRAND TOTAL: {report['grand_total']} redactions "
        f"across {files_matched} files")
    lines.append(_RULE)
    return "\n".join(lines)


def render_markdown_report(report, *, title, files_scanned, files_matched,
                           extensions=None, output_dir=None, meta=None,
                           heading=None, file_stats=None, filename_stats=None) -> str:
    """Render the report as a self-contained markdown doc (for `redact.py --report`):
    a folder-named H1, a two-line SENSITIVE keep-local banner, optional caller-supplied
    `meta` bullets (mode/entities/timestamp/…), a Summary table (file-type counts from
    `file_stats` plus per-entity/keyword subtotals from the report dict), and the full
    itemized text report (render_redaction_report) inside a fenced block.

    heading: the markdown H1 (e.g. "Redaction Report — <folder>"); defaults to `title`
        for back-compat. Kept IDENTICAL across dry-run and real runs, so the only
        dry/real differences live in `meta` (Run type), the `Generated` timestamp, and
        the itemized banner / `Output at:` line (the real==dry requirement).
    meta: bullet items — plain strings (`- {s}`) OR (label, value) tuples rendered as
        bold-key bullets (`- **{label}:** {value}`).
    file_stats: optional list of (label, value) rows inserted into the Summary table
        (file-type counts, not-copied, errors, …), before the per-entity/keyword rows.

    Pure — the markdown lives here (the rendering concern) so redact.py only calls
    and writes it. Matched PII appears in the itemized block; callers keep it local.
    """
    itemized = render_redaction_report(
        report, title=title, files_scanned=files_scanned,
        files_matched=files_matched, extensions=extensions, output_dir=output_dir,
        filename_stats=filename_stats)

    rows = ["| Metric | Value |", "|---|---|",
            f"| Files scanned · with matches | {files_scanned} · {files_matched} |"]
    for label, value in (file_stats or []):
        rows.append(f"| {label} | {value} |")
    for b in report.get("pattern_matches", []):
        rows.append(f"| PATTERN — {b['entity_type']} | {b['unique']} unique · {b['hits']} hits |")
    for b in report.get("model_entities", []):
        rows.append(f"| MODEL — {b['entity_type']} | {b['unique']} unique · {b['hits']} hits |")
    kb = report.get("keywords_blackout") or {"unique": 0, "hits": 0}
    rows.append(f"| Keywords — blacked out | {kb['unique']} unique · {kb['hits']} hits |")
    krep = report.get("keywords_replaced", [])
    rows.append(f"| Keywords — replaced | {len(krep)} pseudonyms · "
                f"{sum(g['hits'] for g in krep)} hits |")
    rows.append(f"| GRAND TOTAL | {report.get('grand_total', 0)} |")

    meta_lines = []
    for m in (meta or []):
        if isinstance(m, (tuple, list)) and len(m) == 2:
            meta_lines.append(f"- **{m[0]}:** {m[1]}")
        else:
            meta_lines.append(f"- {m}")
    meta_block = ("\n".join(meta_lines) + "\n\n") if meta_lines else ""

    return (
        f"# {heading or title}\n\n"
        "> ⚠️ **SENSITIVE — contains real PII.** Lists matched emails, names, URLs, and original filenames in full.\n"
        "> Keep it local: do NOT commit it, and do NOT place it inside `redacted/`.\n\n"
        f"{meta_block}"
        "## Summary\n\n"
        + "\n".join(rows) + "\n\n"
        "## Itemized (full report)\n\n"
        "```\n"
        f"{itemized}\n"
        "```\n"
    )
