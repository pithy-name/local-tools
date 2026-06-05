#!/usr/bin/env python3
"""json_redact.py — deterministic curated PII find→replace for JSON notes.

Stdlib only. Reads a mappings list, walks each JSON file's string VALUES,
replaces curated names with stable pseudonyms, writes valid JSON to
<input>/redacted/. Originals are never modified; non-JSON is never copied.

See plans/json-redact/2026-06-04-json-redact-design.md for the full design.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path


def load_mappings(path: Path) -> list[dict]:
    """Load + validate mappings.json. Exits with a clear message on any problem."""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        sys.exit(f"mappings file not found: {path}")
    except json.JSONDecodeError as e:
        sys.exit(f"mappings file is not valid JSON: {e}")

    if not isinstance(data, list):
        sys.exit(f"mappings must be a JSON array, got {type(data).__name__}")

    seen_finds: set[str] = set()
    seen_replaces: set[str] = set()
    out: list[dict] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict) or "find" not in item or "replace" not in item:
            sys.exit(f"mapping #{i} must be an object with 'find' and 'replace'")
        f, r = item["find"], item["replace"]
        if not isinstance(f, str) or not isinstance(r, str) or not f or not r:
            sys.exit(f"mapping #{i}: 'find' and 'replace' must be non-empty strings")
        if f.lower() in seen_finds:
            sys.exit(f"mapping #{i}: duplicate find {f!r} (case-insensitive)")
        if r in seen_replaces:
            sys.exit(f"mapping #{i}: replace {r!r} already used — would conflate identities")
        seen_finds.add(f.lower())
        seen_replaces.add(r)
        out.append({"find": f, "replace": r})
    return out


def build_pattern(mappings: list[dict]):
    """Return (compiled combined regex | None, lookup lower(find)->mapping)."""
    if not mappings:
        return None, {}
    ordered = sorted(mappings, key=lambda m: len(m["find"]), reverse=True)
    alts = "|".join(re.escape(m["find"]) for m in ordered)
    pattern = re.compile(r"(?i)\b(?:" + alts + r")\b")
    lookup = {m["find"].lower(): m for m in mappings}
    return pattern, lookup


def make_redactor(pattern, lookup, counts: Counter):
    """Return redact(s)->str. Single-pass: every char considered once, so a
    replacement is never re-matched by another mapping. Mutates `counts`."""
    def redact(s: str) -> str:
        if pattern is None:
            return s

        def repl(m: re.Match) -> str:
            mp = lookup[m.group(0).lower()]
            counts[mp["find"]] += 1
            return mp["replace"]

        return pattern.sub(repl, s)
    return redact


def walk(obj, redact):
    """Recursively redact string VALUES. Keys and non-strings pass through."""
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, list):
        return [walk(v, redact) for v in obj]
    if isinstance(obj, dict):
        return {k: walk(v, redact) for k, v in obj.items()}  # keys untouched
    return obj  # int / float / bool / None


def run(input_dir: Path, mappings_path: Path, dry_run: bool) -> dict:
    mappings = load_mappings(mappings_path)
    pattern, lookup = build_pattern(mappings)
    counts: Counter = Counter()
    redact = make_redactor(pattern, lookup, counts)

    output_dir = input_dir / "redacted"
    mappings_file = mappings_path.resolve()
    all_files = [f for f in sorted(input_dir.rglob("*"))
                 if f.is_file()
                 and output_dir not in f.parents
                 and f.resolve() != mappings_file]  # never redact the mappings file itself
    json_files = [f for f in all_files if f.suffix.lower() == ".json"]
    non_json = [f for f in all_files if f.suffix.lower() != ".json"]

    stats = {"processed": 0, "non_json": len(non_json), "errors": 0}

    for src in json_files:
        rel = src.relative_to(input_dir)
        try:
            data = json.loads(src.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"  ERROR  {rel}: not parseable JSON ({e}) — skipped, not copied",
                  file=sys.stderr)
            stats["errors"] += 1
            continue
        redacted = walk(data, redact)
        stats["processed"] += 1
        if not dry_run:
            dst = output_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(json.dumps(redacted, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")

    mode = "[DRY RUN] " if dry_run else ""
    print(f"\n{mode}{'-' * 48}")
    print(f"  Total swaps          : {sum(counts.values())}")
    for m in mappings:
        print(f"    {m['find']!r} -> {m['replace']!r} : {counts[m['find']]}")
    print(f"  JSON files processed : {stats['processed']}")
    print(f"  Non-JSON skipped     : {stats['non_json']}  (left in source, NOT copied)")
    print(f"  Parse errors         : {stats['errors']}")
    if not dry_run:
        print(f"  Output at            : {output_dir}")
    if non_json:
        print("\n  Note: non-JSON files were NOT redacted and NOT copied to output.")
        print("  Handle attachments separately before sharing.")
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deterministic curated PII find->replace for JSON notes (stdlib).")
    parser.add_argument("input_dir", help="Directory of .json notes (recursed)")
    parser.add_argument("--mappings", default="mappings.json",
                        help="Path to mappings.json (default: ./mappings.json)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report swaps without writing any files")
    args = parser.parse_args()

    input_dir = Path(args.input_dir).expanduser().resolve()
    if not input_dir.is_dir():
        sys.exit(f"Error: not a directory: {input_dir}")
    run(input_dir, Path(args.mappings).expanduser(), dry_run=args.dry_run)


if __name__ == "__main__":
    main()
