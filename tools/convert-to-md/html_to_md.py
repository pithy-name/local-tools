#!/usr/bin/env python3
import sys
from pathlib import Path

try:
    import markdownify
    from bs4 import BeautifulSoup
except ImportError:
    print("Required packages not found. Install with: pip install markdownify beautifulsoup4")
    sys.exit(1)


def convert(html_path: Path) -> str:
    html = html_path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    return markdownify.markdownify(str(soup), heading_style="ATX")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python html_to_md.py <file.html> [output.md]")
        sys.exit(1)

    src = Path(sys.argv[1])
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_suffix(".md")

    md = convert(src)
    dst.write_text(md, encoding="utf-8")
    print(f"Saved to {dst}")
