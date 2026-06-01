#!/usr/bin/env python3
"""Search session-log markdown files recursively for a string.

Matches files whose name contains `scratchpad` or `session-log` (covers both the
legacy `scratchpad-YYYY-MM-DD-*.md` naming and the current `*-session-log-*.md`).
Defaults to searching `.claude/session-logs/` under the current working directory.
"""

from pathlib import Path
import sys

DEFAULT_SUBDIR = Path(".claude/session-logs")
KEYWORDS = ("scratchpad", "session-log")


def search_session_logs(root: Path, query: str) -> None:
    files = sorted(
        p for p in root.rglob("*.md")
        if any(k in p.name.lower() for k in KEYWORDS)
    )
    matches = 0

    for file in files:
        lines = file.read_text(encoding="utf-8").splitlines()
        hits = [
            (i + 1, line)
            for i, line in enumerate(lines)
            if query.lower() in line.lower()
        ]
        if hits:
            for lineno, line in hits:
                print(f"{file}:{lineno}: {line.strip()}")
            matches += len(hits)

    print(f"\n{matches} match{'es' if matches != 1 else ''} across {len(files)} session-log file{'s' if len(files) != 1 else ''}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python search_session_logs.py <query> [directory]")
        sys.exit(1)

    query = sys.argv[1]
    if len(sys.argv) > 2:
        root = Path(sys.argv[2])
    else:
        default = Path.cwd() / DEFAULT_SUBDIR
        root = default if default.is_dir() else Path.cwd()

    search_session_logs(root, query)
