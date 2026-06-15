#!/usr/bin/env python3
"""gen_keywords.py — turn a names list into redaction `custom_keywords` YAML.

Input is a markdown/text file:
  - a line starting with `#` begins a group whose text is the replace PREFIX
    (e.g. `# ENG`); any number of `#` and surrounding spaces are tolerated.
  - every other non-blank line is ONE person; a leading `- ` / `* ` bullet is
    stripped. Comma-separated names on a line are ALIASES of that one person and
    all share that person's code (e.g. `Robin Lee, Robin` -> both `ENG01`).
  - the reserved header `# BLACKOUT` (case-insensitive) marks a group whose members
    emit PLAIN blackout strings (`- "term"` -> the default █████), NO code. Inside it,
    commas separate INDEPENDENT terms (not aliases) — so one names file can drive both
    pseudonyms and the blackout list.

Output (stdout) is `custom_keywords` entries at 2-space indent, ready to paste
under `custom_keywords:` in config.yaml. Numbers are two-digit, zero-padded, and
reset per group. The config already supports many `find`s -> one `replace`
(aliasing), so no config change is needed.

  python gen_keywords.py names.md                       # print YAML to stdout
  python gen_keywords.py names.md --write config.yaml   # write in place between the
                                                        # gen_keywords:begin/end markers
                                                        # (.bak, atomic, YAML-validated)

Note: comma is the alias delimiter, so a name containing a comma ("Smith, John")
is read as two aliases. Duplicate finds (case-insensitive) are emitted anyway
with a stderr warning — the redactor rejects duplicate finds, so fix them before
pasting. Stdlib only; no dependencies.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Reserved group header (case-insensitive): its members emit PLAIN blackout strings
# (-> the default █████ replacement), not find/replace pseudonym codes. Inside it,
# commas separate INDEPENDENT terms (not aliases-of-one), since there is no code to share.
BLACKOUT_GROUP = "blackout"


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
        parts = [p.strip() for p in line.split(",") if p.strip()]
        if not parts:
            continue
        if current.strip().lower() == BLACKOUT_GROUP:
            # Blackout group: each comma-separated token is its OWN plain-string term
            # (-> default █████). No shared code — nothing to alias.
            for term in parts:
                key = term.lower()
                if key in seen:
                    warnings.append(
                        f"duplicate find {term!r} (case-insensitive) — the redactor "
                        f"rejects duplicate finds; fix before pasting")
                seen.add(key)
                out.append(f"  - {json.dumps(term, ensure_ascii=False)}")
            continue
        # Pseudonym group: comma-separated names are ALIASES of one person -> one code.
        counters[current] += 1
        code = f"{current}{counters[current]:02d}"
        for alias in parts:
            key = alias.lower()
            if key in seen:
                warnings.append(
                    f"duplicate find {alias!r} (case-insensitive) — the redactor "
                    f"rejects duplicate finds; fix before pasting")
            seen.add(key)
            out.append(f"  - find: {json.dumps(alias, ensure_ascii=False)}")
            out.append(f"    replace: {json.dumps(code, ensure_ascii=False)}")

    return "\n".join(out), warnings


def find_duplicate_finds(text: str) -> list[str]:
    """Return the find-terms that occur more than once, as a sorted list of lowercased
    keys — the same case-insensitive dup key `format_keywords` and the redactor use.
    Empty list = clean. Pure (no I/O). Mirrors `format_keywords` parsing: bullet strip,
    `#` group headers, and comma-splitting (aliases in pseudonym groups and independent
    terms in BLACKOUT both contribute one key per comma token)."""
    from collections import Counter
    counts: "Counter[str]" = Counter()
    current: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            current = line.lstrip("#").strip() or None
            continue
        if line[:2] in ("- ", "* "):
            line = line[2:].strip()
        if current is None:
            continue
        for term in (p.strip() for p in line.split(",")):
            if term:
                counts[term.lower()] += 1
    return sorted(k for k, n in counts.items() if n > 1)


# Managed-block markers for `--write` (matched as substrings — indent/surrounding text
# tolerant, so the user can phrase the marker comments however they like).
_MARKER_BEGIN = "gen_keywords:begin"
_MARKER_END = "gen_keywords:end"


def splice_into_config(config_text: str, generated: str) -> str:
    """Replace the lines between the managed markers with `generated`.

    Finds the first line containing `gen_keywords:begin` and the next containing
    `gen_keywords:end`, and replaces everything strictly between them — keeping the
    marker lines and ALL surrounding config untouched. Raises ValueError (never guesses)
    if the markers are missing or out of order, so nothing is destroyed."""
    lines = config_text.splitlines()
    begin = next((i for i, ln in enumerate(lines) if _MARKER_BEGIN in ln), None)
    end = next((i for i, ln in enumerate(lines) if _MARKER_END in ln), None)
    if begin is None or end is None or end <= begin:
        raise ValueError(
            "managed markers not found (or out of order). Add these two lines once, "
            "under `custom_keywords:` in your config, then re-run with --write:\n"
            "  # >>> gen_keywords:begin — managed by gen_keywords.py --write >>>\n"
            "  # <<< gen_keywords:end <<<")
    new_lines = lines[:begin + 1] + generated.splitlines() + lines[end:]
    text = "\n".join(new_lines)
    return text + "\n" if config_text.endswith("\n") else text


def update_config_file(path: str, generated: str) -> None:
    """Splice `generated` into the config at `path`, in place and safely: back up to
    `<name>.bak`, validate the result still parses as YAML (only if PyYAML is present,
    so stdout mode stays stdlib-only), then atomically replace. Raises ValueError
    (before any write) if the markers are missing."""
    p = Path(path)
    original = p.read_text(encoding="utf-8")
    new_text = splice_into_config(original, generated)   # raises before any write if no markers
    try:
        import yaml
        yaml.safe_load(new_text)                          # propagates YAMLError before writing
    except ImportError:
        pass
    (p.parent / (p.name + ".bak")).write_text(original, encoding="utf-8")
    tmp = p.parent / (p.name + ".tmp")
    tmp.write_text(new_text, encoding="utf-8")
    os.replace(tmp, p)                                    # atomic


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Generate redaction custom_keywords YAML from a names list.")
    ap.add_argument(
        "input",
        help="markdown/text file: '# PREFIX' group headers, one person per line, "
             "comma-separated aliases share one code")
    ap.add_argument(
        "--write", metavar="CONFIG", default=None,
        help="splice the generated keywords into CONFIG in place, between the "
             "`gen_keywords:begin/end` markers (makes a .bak, atomic, YAML-validated). "
             "Without it, prints to stdout as before.")
    args = ap.parse_args()

    text = Path(args.input).expanduser().read_text(encoding="utf-8")
    rendered, warnings = format_keywords(text)
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    if args.write:
        try:
            update_config_file(args.write, rendered)
        except ValueError as e:
            sys.exit(f"--write: {e}")
        print(f"Updated {args.write} in place (backup: {args.write}.bak).",
              file=sys.stderr)
    elif rendered:
        print(rendered)


if __name__ == "__main__":
    main()
