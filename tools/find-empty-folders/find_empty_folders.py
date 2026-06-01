"""Find folders containing no files anywhere in their subtree.

Usage: python find_empty_folders.py [directory]
Default directory: current working directory.
"""

import sys
from pathlib import Path

SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".idea", ".vscode"}


def is_skipped(path: Path) -> bool:
    return path.name in SKIP_DIRS or path.name.startswith(".")


def subtree_has_file(folder: Path) -> bool:
    for entry in folder.rglob("*"):
        if entry.is_dir() and is_skipped(entry):
            continue
        if any(is_skipped(p) for p in entry.relative_to(folder).parents):
            continue
        if entry.is_file():
            return True
    return False


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 2

    all_folders = [root] + [p for p in root.rglob("*") if p.is_dir() and not is_skipped(p) and not any(is_skipped(parent) for parent in p.relative_to(root).parents)]

    empty = [f for f in all_folders if not subtree_has_file(f)]

    print(f"Scanned: {root}")
    print(f"Folders checked: {len(all_folders)}")
    print(f"Empty folders (no files anywhere in subtree): {len(empty)}")
    if empty:
        print()
        for f in sorted(empty):
            print(f"  {f.relative_to(root) if f != root else '.'}")
        return 1
    print("All folders contain at least one file.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
