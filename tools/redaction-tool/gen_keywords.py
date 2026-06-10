#!/usr/bin/env python3
"""gen_keywords.py — turn a names list into redaction `custom_keywords` YAML.

Input is a markdown/text file:
  - a line starting with `#` begins a group whose text is the replace PREFIX
    (e.g. `# ENG`); any number of `#` and surrounding spaces are tolerated.
  - every other non-blank line is ONE person; a leading `- ` / `* ` bullet is
    stripped. Comma-separated names on a line are ALIASES of that one person and
    all share that person's code (e.g. `Alex, Alex ABC` -> both `ENG01`).

Output (stdout) is `custom_keywords` entries at 2-space indent, ready to paste
under `custom_keywords:` in config.yaml. Numbers are two-digit, zero-padded, and
reset per group. The config already supports many `find`s -> one `replace`
(aliasing), so no config change is needed.

  python gen_keywords.py names.md            # prints YAML to stdout

Note: comma is the alias delimiter, so a name containing a comma ("Smith, John")
is read as two aliases. Duplicate finds (case-insensitive) are emitted anyway
with a stderr warning — the redactor rejects duplicate finds, so fix them before
pasting. Stdlib only; no dependencies.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def format_keywords(text: str) -> tuple[str, list[str]]:
    """Parse the names text -> (yaml_entries_str, warnings). Pure: no I/O."""
    warnings: list[str] = []
    out: list[str] = []
    counters: dict[str, int] = {}   # prefix -> last number used (resets per group)
    seen: set[str] = set()          # lowercased finds, for dup detection
    current: str | None = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            current = line.lstrip("#").strip()
            if not current:
                warnings.append("empty group header skipped")
                continue
            counters.setdefault(current, 0)
            continue
        if line[:2] in ("- ", "* "):          # tolerate markdown bullets
            line = line[2:].strip()
        if current is None:
            warnings.append(f"name before any '# PREFIX' header, skipped: {line!r}")
            continue
        aliases = [a.strip() for a in line.split(",") if a.strip()]
        if not aliases:
            continue
        counters[current] += 1
        code = f"{current}{counters[current]:02d}"
        for alias in aliases:
            key = alias.lower()
            if key in seen:
                warnings.append(
                    f"duplicate find {alias!r} (case-insensitive) — the redactor "
                    f"rejects duplicate finds; fix before pasting")
            seen.add(key)
            out.append(f"  - find: {json.dumps(alias, ensure_ascii=False)}")
            out.append(f"    replace: {json.dumps(code, ensure_ascii=False)}")

    return "\n".join(out), warnings


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Generate redaction custom_keywords YAML from a names list.")
    ap.add_argument(
        "input",
        help="markdown/text file: '# PREFIX' group headers, one person per line, "
             "comma-separated aliases share one code")
    args = ap.parse_args()

    text = Path(args.input).expanduser().read_text(encoding="utf-8")
    rendered, warnings = format_keywords(text)
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    if rendered:
        print(rendered)


if __name__ == "__main__":
    main()
