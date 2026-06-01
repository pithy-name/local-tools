#!/usr/bin/env python3
"""Find all files with a given extension recursively within a directory."""

from pathlib import Path
import sys


def find_files(root: str, ext: str) -> list[Path]:
    pattern = f"*{ext}" if ext.startswith(".") else f"*.{ext}"
    return sorted(Path(root).rglob(pattern))


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else Path.cwd()
    ext = sys.argv[2] if len(sys.argv) > 2 else ".py"
    files = find_files(root, ext)
    for f in files:
        print(f)
    print(f"\n{len(files)} {ext} files found")
