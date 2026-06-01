#!/usr/bin/env python3
"""Convert a .docx file to Markdown. Usage: python3 docx_to_md.py <file.docx>"""

import sys
from pathlib import Path
from docx import Document


def runs_to_md(para):
    parts = []
    for run in para.runs:
        text = run.text
        if not text:
            continue
        if run.bold and run.italic:
            text = f"***{text}***"
        elif run.bold:
            text = f"**{text}**"
        elif run.italic:
            text = f"*{text}*"
        parts.append(text)
    return "".join(parts)


def para_to_md(para):
    style = para.style.name
    text = runs_to_md(para) or para.text.strip()

    if not text.strip():
        return ""
    if style.startswith("Heading 1"):
        return f"# {text}"
    if style.startswith("Heading 2"):
        return f"## {text}"
    if style.startswith("Heading 3"):
        return f"### {text}"
    if style.startswith("Heading 4"):
        return f"#### {text}"
    if "Bullet" in style or "List" in style:
        return f"- {text}"
    return text


def table_to_md(table):
    rows = []
    for i, row in enumerate(table.rows):
        cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
        rows.append("| " + " | ".join(cells) + " |")
        if i == 0:
            rows.append("| " + " | ".join(["---"] * len(cells)) + " |")
    return "\n".join(rows)


def convert(docx_path: Path) -> Path:
    doc = Document(docx_path)
    lines = []

    # Interleave paragraphs and tables in document order
    body = doc.element.body
    for child in body:
        tag = child.tag.split("}")[-1]
        if tag == "p":
            from docx.oxml.ns import qn
            from docx.text.paragraph import Paragraph
            para = Paragraph(child, doc)
            lines.append(para_to_md(para))
        elif tag == "tbl":
            from docx.table import Table
            table = Table(child, doc)
            lines.append("")
            lines.append(table_to_md(table))
            lines.append("")

    # Collapse runs of multiple blank lines to one
    output, prev_blank = [], False
    for line in lines:
        is_blank = line.strip() == ""
        if is_blank and prev_blank:
            continue
        output.append(line)
        prev_blank = is_blank

    md_path = docx_path.with_suffix(".md")
    md_path.write_text("\n".join(output).strip() + "\n", encoding="utf-8")
    return md_path


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 docx_to_md.py <file.docx>")
        sys.exit(1)
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"Error: file not found: {path}")
        sys.exit(1)
    out = convert(path)
    print(f"Saved: {out}")
