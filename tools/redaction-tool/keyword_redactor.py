"""keyword_redactor.py — deterministic, no-spaCy keyword find->replace engine.

Stdlib only. The NER-free redaction backend shared by redact.py's keyword-only
mode (and the JSON/CSV handlers). Built test-first; see tests/test_keyword_redactor.py.
"""
from __future__ import annotations

import json
import re
import warnings
from collections import Counter
from pathlib import Path


def load_mappings(path) -> list[dict]:
    """Load + validate a mappings.json (list of {find, replace})."""
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        raise ValueError(f"mappings must be a JSON array, got {type(data).__name__}")
    seen_finds: set[str] = set()
    replace_origin: dict[str, str] = {}  # replace -> first find that used it
    for i, item in enumerate(data):
        if not isinstance(item, dict) or "find" not in item or "replace" not in item:
            raise ValueError(f"mapping #{i} must be an object with 'find' and 'replace'")
        f, r = item["find"], item["replace"]
        if not isinstance(f, str) or not isinstance(r, str) or not f or not r:
            raise ValueError(f"mapping #{i}: 'find' and 'replace' must be non-empty strings")
        if f.lower() in seen_finds:
            raise ValueError(f"mapping #{i}: duplicate find {f!r} (case-insensitive)")
        seen_finds.add(f.lower())
        # Shared replace is ALLOWED: aliasing many mentions of one identity to one
        # pseudonym (e.g. "Mary" + "Mary Bello" -> "[PERSON_A]"). Warn, don't reject.
        if r in replace_origin:
            warnings.warn(
                f"mapping #{i}: replace {r!r} also used by {replace_origin[r]!r} "
                f"— aliasing {f!r} to the same pseudonym",
                UserWarning, stacklevel=2)
        else:
            replace_origin[r] = f
    return data


class KeywordRedactor:
    def __init__(self, mappings: list[dict]):
        self.mappings = mappings  # public: [{find, replace}], for count reporting
        # Longest find first → the combined alternation prefers longer matches.
        ordered = sorted(mappings, key=lambda m: len(m["find"]), reverse=True)
        alts = "|".join(re.escape(m["find"]) for m in ordered)
        self._pattern = re.compile(r"(?i)\b(?:" + alts + r")\b") if alts else None
        self._lookup = {m["find"].lower(): m for m in mappings}
        self.counts: Counter = Counter()  # per-find text-sub counts, accumulated

    def redact(self, text: str) -> str:
        # Single pass: every char considered once, so no replacement is re-matched.
        if self._pattern is None:
            return text

        def repl(mo: re.Match) -> str:
            m = self._lookup[mo.group(0).lower()]
            self.counts[m["find"]] += 1
            return m["replace"]

        return self._pattern.sub(repl, text)
