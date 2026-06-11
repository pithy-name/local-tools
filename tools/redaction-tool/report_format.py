"""report_format.py — the unified redaction count report (stdlib only).

Shared output model for the redactor summary (and, later, the --scan listing):
per-find rows grouped by pseudonym, per-pseudonym subtotals (incl. singletons),
two mechanism counts (text-sub / blackout), with blackout == None rendered N/A
(mechanism not engaged) vs 0 (engaged, none found).
"""
from __future__ import annotations

from collections import Counter, OrderedDict, defaultdict


def build_count_report(mappings, text_counts, blackout_counts=None) -> dict:
    """mappings: [{find, replace}]. text_counts/blackout_counts: find -> count.
    blackout_counts None → blackout is N/A everywhere. Returns a structured report."""
    have_black = blackout_counts is not None
    groups_map: "OrderedDict[str, list]" = OrderedDict()
    for m in mappings:
        groups_map.setdefault(m["replace"], []).append(m["find"])

    groups = []
    total_text = 0
    total_black = 0
    for pseudo, finds in groups_map.items():
        rows = []
        sub_t = 0
        sub_b = 0
        for find in finds:
            t = text_counts.get(find, 0)
            b = blackout_counts.get(find, 0) if have_black else None
            rows.append({"find": find, "text": t, "blackout": b})
            total_text += t
            sub_t += t
            if have_black:
                total_black += b
                sub_b += b
        groups.append({
            "pseudonym": pseudo,
            "rows": rows,
            "subtotal": {"text": sub_t, "blackout": sub_b if have_black else None},
        })
    return {
        "groups": groups,
        "total_text": total_text,
        "total_blackout": total_black if have_black else None,
    }


def _b(value) -> str:
    return "N/A" if value is None else str(value)


def render_count_report(report) -> str:
    """Render build_count_report() output as text (N/A = mechanism not engaged)."""
    lines = []
    for g in report["groups"]:
        for row in g["rows"]:
            lines.append(
                f"    {g['pseudonym']}  ({row['find']})  "
                f"text-sub: {row['text']}  blackout: {_b(row['blackout'])}")
        st = g["subtotal"]
        lines.append(
            f"      └─ {g['pseudonym']} subtotal  "
            f"text-sub: {st['text']}  blackout: {_b(st['blackout'])}")
    lines.append(f"  Total text-subs : {report['total_text']}")
    lines.append(f"  Total blackouts : {_b(report['total_blackout'])}")
    return "\n".join(lines)


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
                           entity_replacements=None) -> dict:
    """Build the structured end-of-run report from a tally (no model needed).

    entity_tally:  {entity_type: {matched_text: count}} — non-keyword entities.
    keyword_tally: [{find, replace, count}] — replace=None → blacked out,
                   replace=<str> → that pseudonym.
    replacement_char: default blackout display token (e.g. "█████").
    entity_replacements: per-type token overrides, e.g. {"URL": "[URL]"};
                   any type not present falls back to replacement_char.
    """
    entity_replacements = entity_replacements or {}

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


def _render_entity_blocks(lines, blocks) -> None:
    if not blocks:
        lines.append("    none")
        return
    for b in blocks:
        head = f"{b['entity_type'].ljust(14)} ({b['unique']} unique · {b['hits']} hits)"
        lines.append(f"{head.ljust(48)} → {b['replacement']}")
        for row in b["rows"]:
            lines.append(f"    {row['text'].ljust(28)} ×{row['count']}")


def _render_blackout(lines, block) -> None:
    if not block["rows"]:
        lines.append("    none")
        return
    head = f"{''.ljust(14)} ({block['unique']} unique · {block['hits']} hits)"
    lines.append(f"{head.ljust(48)} → {block['replacement']}")
    for row in block["rows"]:
        lines.append(f"    {row['text'].ljust(28)} ×{row['count']}")


def _render_replaced(lines, groups) -> None:
    if not groups:
        lines.append("    none")
        return
    for g in groups:
        word = "alias" if g["aliases"] == 1 else "aliases"
        lines.append(
            f"{g['pseudonym'].ljust(14)} ({g['aliases']} {word} · {g['hits']} hits)")
        for row in g["rows"]:
            lines.append(f"    {row['text'].ljust(28)} ×{row['count']}")


def render_redaction_report(report, *, title, files_scanned, files_matched,
                            extensions=None, output_dir=None) -> str:
    """Render build_redaction_report() output as text.

    title: "REDACTION PREVIEW (--dry-run)" or "REDACTION COMPLETE".
    output_dir: when set (a real run), adds an "Output at:" line — the ONLY body
    difference from a dry-run; everything from PATTERN MATCHES down is identical.
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

    lines.append("PATTERN MATCHES  (regex — deterministic)")
    lines.append(_THIN)
    _render_entity_blocks(lines, report["pattern_matches"])
    lines.append("")

    lines.append("MODEL ENTITIES  (spaCy NER — probabilistic)")
    lines.append(_THIN)
    _render_entity_blocks(lines, report["model_entities"])
    lines.append("")

    lines.append("CUSTOM KEYWORDS — blacked out")
    lines.append(_THIN)
    _render_blackout(lines, report["keywords_blackout"])
    lines.append("")

    lines.append("CUSTOM KEYWORDS — replaced")
    lines.append(_THIN)
    _render_replaced(lines, report["keywords_replaced"])
    lines.append("")

    lines.append(_TOTAL_RULE)
    lines.append(
        f"  GRAND TOTAL: {report['grand_total']} redactions "
        f"across {files_matched} files")
    lines.append(_RULE)
    return "\n".join(lines)
