#!/usr/bin/env python3
"""json_scan.py — advisory local NER scan over JSON string values.

Prints unique candidate entities (names/orgs/emails) found by spaCy+Presidio,
so you can curate them into mappings.json. NO files are written. Runs locally,
no network. Run it with the redaction-tool venv's interpreter so the spaCy
model is available, e.g.:

    ../redaction-tool/.venv/bin/python json_scan.py /path/to/notes

WARNING: the candidate list this prints contains REAL PII. Keep it out of git
and off any synced location — treat it like the raw notes.

See plans/json-redact/2026-06-04-json-redact-design.md (§5a) for the design.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ENTITIES = ["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "ORGANIZATION", "LOCATION"]


def iter_strings(obj):
    """Yield every string VALUE in a JSON structure (depth-first)."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, list):
        for v in obj:
            yield from iter_strings(v)
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from iter_strings(v)


def collect(input_dir: Path, analyze_fn) -> dict:
    """Walk every .json file, run analyze_fn on each string value, return
    {entity_type: Counter(matched_text)}. analyze_fn(text) -> list of objects
    with .entity_type/.start/.end (injectable for testing)."""
    found: dict = defaultdict(Counter)
    for src in sorted(input_dir.rglob("*.json")):
        try:
            data = json.loads(src.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        for s in iter_strings(data):
            if not s.strip():
                continue
            for r in analyze_fn(s):
                found[r.entity_type][s[r.start:r.end]] += 1
    return found


def build_analyze_fn(model: str = "en_core_web_lg"):
    """Construct the real Presidio analyzer. Imported lazily so the NER-free
    logic (and its tests) never require spaCy/Presidio to be installed."""
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider
    except ImportError:
        sys.exit(
            "spaCy/Presidio not available. Run json_scan.py with the "
            "redaction-tool venv:\n"
            "  ../redaction-tool/.venv/bin/python json_scan.py <dir>\n"
            "If that venv does not exist, run: bash ../redaction-tool/setup.sh")
    provider = NlpEngineProvider(nlp_configuration={
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "en", "model_name": model}],
    })
    analyzer = AnalyzerEngine(nlp_engine=provider.create_engine(),
                              supported_languages=["en"])

    def analyze(text: str):
        return analyzer.analyze(text=text, entities=ENTITIES, language="en")
    return analyze


def report(found: dict) -> None:
    if not found:
        print("No candidate entities found.")
        return
    print("\nCandidate entities (REAL PII — do not commit this output):\n")
    for etype in sorted(found):
        items = found[etype].most_common()
        print(f"{etype}  ({len(items)} unique)")
        width = max((len(t) for t, _ in items), default=0)
        for text, n in items:
            print(f"    {text.ljust(width)} ... {n}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Advisory local NER scan over JSON notes — seeds mappings.json.")
    parser.add_argument("input_dir", help="Directory of .json notes (recursed)")
    parser.add_argument("--model", default="en_core_web_lg",
                        help="spaCy model (default: en_core_web_lg)")
    args = parser.parse_args()

    input_dir = Path(args.input_dir).expanduser().resolve()
    if not input_dir.is_dir():
        sys.exit(f"Error: not a directory: {input_dir}")
    found = collect(input_dir, build_analyze_fn(args.model))
    report(found)


if __name__ == "__main__":
    main()
