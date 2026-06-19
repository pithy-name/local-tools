"""filename_redactor.py — deterministic, no-spaCy SUBSTRING engine for redacting
keyword matches inside output FILENAMES and directory names.

Stdlib only. Sibling to keyword_redactor.py, with two deliberate differences:

  1. SUBSTRING match (no `\\b`): names embed terms without boundaries
     (`asmith_1on1.png`), which the word-boundary content engine leaves alone. To
     stop short keywords (`ed`, `mark`) mangling innocent names, terms shorter than
     `min_len` are skipped (surfaced via `skipped_short`).

  2. Only ALIASED keywords are RENAMED. A keyword with a `replace` pseudonym is
     substituted (filesystem-sanitized) into the name. A PLAIN (blackout, replace=None)
     keyword is NOT renamed — a `█████`-style token is useless in a filename and the user
     tracks identities by pseudonym. Instead, plain keywords found in an output name are
     FLAGGED (`flagged_terms_in`) so they can be aliased or renamed by hand — never
     silently left in place.

Consumes the same `[{find, replace}]` mappings redact.py's normalize_keywords produces.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath

# Filesystem-safe charset for redacted name fragments. Everything else (brackets,
# spaces, …) is collapsed to "_" so a pseudonym like "[PERSON_A]" → "PERSON_A".
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_FALLBACK = "REDACTED"   # used only if a pseudonym sanitizes to empty (degenerate)


def sanitize_pseudonym(s: str) -> str:
    """Make a pseudonym safe to embed in a filename: keep [A-Za-z0-9._-], map any
    other run to "_", collapse repeats, strip edge underscores. `[PERSON_A]` →
    `PERSON_A`, `[CLIENT-A]` → `CLIENT-A`, `J.S.` → `J.S.`, `Client A` → `Client_A`."""
    out = _UNSAFE.sub("_", s)
    out = re.sub(r"_+", "_", out)
    return out.strip("_")


class FilenameRedactor:
    """Substring keyword redactor for a single path component or relative path.
    Renames ALIASED keywords; FLAGS plain ones."""

    def __init__(self, mappings, min_len: int = 4):
        self.min_len = min_len
        aliased, plain, skipped = [], [], []
        for m in mappings:
            if len(m["find"]) < min_len:
                skipped.append(m["find"])
            elif m.get("replace") is not None:
                aliased.append(m)
            else:
                plain.append(m["find"])
        # Surface short terms we deliberately did NOT match (no silent gap).
        self.skipped_short = sorted(set(skipped))
        # Plain (no-alias) terms: flagged, never renamed.
        self._plain_terms = sorted(set(plain))
        # Longest find first so the alternation prefers longer matches; NO \b → substring.
        ordered = sorted(aliased, key=lambda m: len(m["find"]), reverse=True)
        self._lookup = {m["find"].lower(): m for m in aliased}
        alts = "|".join(re.escape(m["find"]) for m in ordered)
        self._pattern = re.compile("(?i)(?:" + alts + ")") if alts else None

    def _redact_string(self, s: str):
        """Substitute every ALIASED-keyword substring → (new_string, n_hits)."""
        if self._pattern is None:
            return s, 0
        count = 0

        def repl(mo: re.Match) -> str:
            nonlocal count
            count += 1
            m = self._lookup[mo.group(0).lower()]
            return sanitize_pseudonym(m["replace"]) or _FALLBACK

        return self._pattern.sub(repl, s), count

    def redact_dirname(self, name: str):
        """Redact a directory component (no extension handling)."""
        return self._redact_string(name)

    def redact_filename(self, name: str):
        """Redact a file basename, preserving its final extension."""
        suffix = PurePosixPath(name).suffix
        stem = name[: -len(suffix)] if suffix else name
        new_stem, hits = self._redact_string(stem)
        return new_stem + suffix, hits

    def redact_relpath(self, relpath):
        """Redact every dir component + the basename of a relative path.
        Returns (PurePosixPath, total_hits)."""
        parts = PurePosixPath(relpath).parts
        if not parts:
            return PurePosixPath(relpath), 0
        new_parts, total = [], 0
        for part in parts[:-1]:
            np, h = self.redact_dirname(part)
            new_parts.append(np)
            total += h
        np, h = self.redact_filename(parts[-1])
        new_parts.append(np)
        total += h
        return PurePosixPath(*new_parts), total

    def flagged_terms_in(self, name: str) -> list:
        """Plain (no-alias) keywords present as substrings in `name` — the leaks that were
        NOT auto-renamed. Case-insensitive; min_len already applied. Sorted, distinct."""
        low = name.lower()
        return [t for t in self._plain_terms if t.lower() in low]


def _with_suffix_tag(path: str, n: int) -> str:
    """Insert `__n` before the final extension: out/A.md, 2 → out/A__2.md."""
    p = PurePosixPath(path)
    tagged = f"{p.stem}__{n}{p.suffix}"
    return tagged if str(p.parent) == "." else str(p.parent / tagged)


def resolve_collisions(items):
    """Resolve cases where distinct originals redact to the SAME output path.

    `items`: list of (orig_relpath, redacted_relpath). Returns list of
    (orig_relpath, final_relpath) in input order. The first colliding name (by
    sorted original path → deterministic) keeps the clean redacted name; later
    ones get `__2`, `__3`, … inserted before the extension.
    """
    final = [None] * len(items)
    used = set()
    counts = {}
    for i in sorted(range(len(items)), key=lambda j: items[j][0]):
        _orig, red = items[i]
        if red not in counts:
            counts[red] = 1
            final[i] = red
        else:
            counts[red] += 1
            cand = _with_suffix_tag(red, counts[red])
            while cand in used:
                counts[red] += 1
                cand = _with_suffix_tag(red, counts[red])
            final[i] = cand
        used.add(final[i])
    return [(items[i][0], final[i]) for i in range(len(items))]


def plan_tree(rels, redactor: FilenameRedactor):
    """Plan the renames for a whole output tree, in ONE place so redact.py stays a
    thin caller (and this logic is testable under stdlib python).

    `rels`: relative path strings (the files about to be written under redacted/).
    Returns (plan, stats):
      plan  = {orig_rel_str: final_rel_str}   (collisions already resolved)
      stats = {files_renamed, dirs_renamed, collisions, flagged_files, skipped_short}
    """
    rels = [str(PurePosixPath(r)) for r in rels]
    raw = [(r, str(redactor.redact_relpath(r)[0])) for r in rels]
    plan = {orig: final for orig, final in resolve_collisions(raw)}
    return plan, summarize(rels, plan, redactor)


def summarize(rels, plan, redactor: FilenameRedactor) -> dict:
    """Count rename outcomes for a chosen SUBSET of a plan. redact.py plans over all
    candidate files (so collisions resolve globally) but summarizes over only the files
    it actually wrote — so the report's counts and the maps reflect the real output.

      files_renamed : basename changed
      dirs_renamed  : distinct original dir subpaths that changed
      collisions    : finals that got a `__n` suffix (final != naive redaction)
      flagged_files : output names still containing a plain (no-alias) keyword
    """
    files_renamed, collisions, flagged_files = 0, 0, 0
    changed_dirs = set()
    for r in rels:
        r = str(PurePosixPath(r))
        final = plan.get(r, r)
        op, fp = PurePosixPath(r).parts, PurePosixPath(final).parts
        for idx in range(len(op) - 1):
            if op[idx] != fp[idx]:
                changed_dirs.add("/".join(op[: idx + 1]))
        if op and op[-1] != fp[-1]:
            files_renamed += 1
        if final != str(redactor.redact_relpath(r)[0]):
            collisions += 1
        if redactor.flagged_terms_in(final):
            flagged_files += 1
    return {
        "files_renamed": files_renamed,
        "dirs_renamed": len(changed_dirs),
        "collisions": collisions,
        "flagged_files": flagged_files,
        "skipped_short": list(redactor.skipped_short),
    }


def collect_filename_flags(rels, plan, redactor: FilenameRedactor):
    """For the LOCAL flags file: [(output_relpath, [plain_terms])] for every written file
    whose OUTPUT name still contains a plain (no-alias) keyword. Sorted by output path."""
    flags = []
    for r in rels:
        final = plan.get(str(PurePosixPath(r)), str(PurePosixPath(r)))
        terms = redactor.flagged_terms_in(final)
        if terms:
            flags.append((final, terms))
    return sorted(flags)


def render_rename_map(pairs) -> str:
    """Render the LOCAL old→new rename log. Contains original (PII) names, so the
    caller must keep it out of any shareable report."""
    lines = [
        "# Filename redaction map — LOCAL ONLY (contains original names; do not share)",
        "# old\t->\tnew",
    ]
    lines.extend(f"{old}\t->\t{new}" for old, new in pairs)
    return "\n".join(lines) + "\n"


def render_flags_file(pairs) -> str:
    """Render the LOCAL plain-keyword leak list. Lists OUTPUT names still containing a
    plain keyword (not auto-renamed — they have no alias). Holds names → keep local."""
    lines = [
        "# Filename plain-keyword leaks — LOCAL ONLY (output names still holding a plain keyword)",
        "# NOT auto-renamed (no alias). Add an alias in custom_keywords, or rename by hand.",
        "# output_name\tmatched_terms",
    ]
    lines.extend(f"{name}\t{', '.join(terms)}" for name, terms in pairs)
    return "\n".join(lines) + "\n"
