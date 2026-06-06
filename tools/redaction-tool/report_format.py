"""report_format.py — the unified redaction count report (stdlib only).

Shared output model for the redactor summary (and, later, the --scan listing):
per-find rows grouped by pseudonym, per-pseudonym subtotals (incl. singletons),
two mechanism counts (text-sub / blackout), with blackout == None rendered N/A
(mechanism not engaged) vs 0 (engaged, none found).
"""
from __future__ import annotations

from collections import OrderedDict


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
