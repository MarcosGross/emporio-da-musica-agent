"""Convert the store policy manual (PDF) into markdown for the system prompt.

Usage:
    uv run python scripts/extract_policies.py [--force]

The output (data/processed/policies.md) is reviewed by hand after generation,
so the script refuses to overwrite it unless --force is given.

Structure comes from pypdf's layout mode: "N." / "N.N" headings at column 0,
"•" bullets, indented "N." numbered steps, and tables whose columns are
separated by 3+ spaces. Page headers and "Página N" footers are dropped.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "raw" / "políticas_da_loja.pdf"
TARGET = ROOT / "data" / "processed" / "policies.md"

SECTION = re.compile(r"^(\d+)\.\s+(\S.*)$")
SUBSECTION = re.compile(r"^(\d+\.\d+)\s+(\S.*)$")
BULLET = re.compile(r"^\s+•\s+(.*)$")
NUMBERED = re.compile(r"^\s+(\d+)\.\s+(.*)$")
LABEL = re.compile(r"^([A-ZÀ-Ý][^:]{2,30}):\s+(.*)$")
PAGE_FOOTER = re.compile(r"^Página \d+$")
COLUMN_GAP = re.compile(r"\s{3,}")


def page_lines(reader: PdfReader) -> tuple[list[str], list[str]]:
    """Cover lines, and body lines of the remaining pages without headers/footers."""
    pages = [page.extract_text(extraction_mode="layout") for page in reader.pages]
    cover = [line.strip() for line in pages[0].splitlines() if line.strip()]

    body: list[str] = []
    for text in pages[1:]:
        lines = [line.rstrip() for line in text.splitlines()]
        first = next(i for i, line in enumerate(lines) if line.strip())
        body.extend(line for line in lines[first + 1:] if not PAGE_FOOTER.match(line.strip()))
    return cover, body


def to_blocks(lines: list[str]) -> list[dict]:
    blocks: list[dict] = []
    current: dict | None = None

    def close() -> None:
        nonlocal current
        if current is not None:
            blocks.append(current)
        current = None

    for line in lines:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())

        if not stripped:
            if current is not None and current["type"] != "table":
                close()  # table rows are separated by blank lines
            continue

        cells = COLUMN_GAP.split(stripped)
        section = SECTION.match(line) if indent == 0 else None
        subsection = SUBSECTION.match(line) if indent == 0 else None

        if subsection or section:
            close()
            level = 3 if subsection else 2
            match = subsection or section
            blocks.append({"type": "heading", "level": level, "text": f"{match.group(1)}. {match.group(2)}"
                           if section else f"{match.group(1)} {match.group(2)}"})
        elif (m := BULLET.match(line)) or (m := NUMBERED.match(line)):
            kind = "bullets" if BULLET.match(line) else "numbered"
            if current is None or current["type"] != kind:
                close()
                current = {"type": kind, "items": []}
            # Keep the PDF's own numbering: a page break splits the 7.2 steps into two lists.
            current["items"].append((m.group(1), m.group(2)) if kind == "numbered" else m.group(1))
        elif current is not None and current["type"] in ("bullets", "numbered") and indent >= 4:
            last = current["items"][-1]
            current["items"][-1] = (last[0], f"{last[1]} {stripped}") if isinstance(last, tuple) else f"{last} {stripped}"
        elif len(cells) >= 2 and indent > 0:
            if current is None or current["type"] != "table":
                close()
                current = {"type": "table", "header": cells, "rows": []}
            else:
                current["rows"].append(cells)
        elif current is not None and current["type"] == "table" and indent > 20:
            current["rows"][-1][-1] += " " + stripped  # wrapped cell
        else:
            if current is not None and current["type"] == "table":
                close()
            if current is None or current["type"] != "paragraph" or LABEL.match(stripped):
                close()
                current = {"type": "paragraph", "text": stripped}
            else:
                current["text"] += " " + stripped
    close()
    return blocks


def render(cover: list[str], blocks: list[dict]) -> str:
    out = [f"# {cover[0]}", "  \n".join(cover[1:])]
    for block in blocks:
        if block["type"] == "heading":
            out.append(f"{'#' * block['level']} {block['text']}")
        elif block["type"] == "paragraph":
            label = LABEL.match(block["text"])
            out.append(f"**{label.group(1)}:** {label.group(2)}" if label else block["text"])
        elif block["type"] == "bullets":
            out.append("\n".join(f"- {item}" for item in block["items"]))
        elif block["type"] == "numbered":
            out.append("\n".join(f"{number}. {item}" for number, item in block["items"]))
        elif block["type"] == "table":
            width = len(block["header"])
            rows = [block["header"], ["---"] * width, *block["rows"]]
            out.append("\n".join("| " + " | ".join(c.replace("|", "\\|") for c in row) + " |" for row in rows))
    return "\n\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="overwrite the reviewed policies.md")
    args = parser.parse_args()

    if TARGET.exists() and not args.force:
        print(f"{TARGET.relative_to(ROOT)} already exists (it may hold manual fixes). Use --force to overwrite.")
        return 1

    cover, body = page_lines(PdfReader(SOURCE))
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(render(cover, to_blocks(body)), encoding="utf-8")
    print(f"Wrote {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
