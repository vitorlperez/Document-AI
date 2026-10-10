"""Export one stored assistant answer as Markdown, DOCX or PDF, always with its numbered sources.

The answer text is rendered from a small Markdown subset (headings, bullets, tables, paragraphs);
source names are cleaned like everywhere else and links are only the ones stored with the answer.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

from app.knowledge.untrusted import sanitize_label, strip_invisible

FORMATS = {
    "md": ("text/markdown; charset=utf-8", "md"),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
    "pdf": ("application/pdf", "pdf"),
}
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_CODE = re.compile(r"`([^`]+)`")
_CELL_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


@dataclass(frozen=True)
class ExportSource:
    name: str
    url: str


@dataclass(frozen=True)
class ExportBlock:
    kind: str  # heading | bullet | paragraph | table
    text: str = ""
    level: int = 0
    rows: tuple[tuple[str, ...], ...] = ()


def plain(text: str) -> str:
    return _CODE.sub(r"\1", _BOLD.sub(r"\1", strip_invisible(text))).strip()


def _cells(line: str) -> tuple[str, ...]:
    return tuple(plain(cell) for cell in line.strip().strip("|").split("|"))


def parse_blocks(text: str) -> list[ExportBlock]:
    blocks: list[ExportBlock] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].rstrip()
        stripped = line.strip()
        index += 1
        if not stripped or stripped == ":::":
            continue
        if stripped.startswith("::: file "):
            blocks.append(ExportBlock("heading", plain(stripped[9:]), 3))
        elif match := re.match(r"^(#{1,4})\s+(.*)$", stripped):
            blocks.append(ExportBlock("heading", plain(match.group(2)), len(match.group(1))))
        elif stripped.startswith("|"):
            rows = [_cells(stripped)]
            while index < len(lines) and lines[index].strip().startswith("|"):
                if not _CELL_SEPARATOR.match(lines[index]):
                    rows.append(_cells(lines[index]))
                index += 1
            blocks.append(ExportBlock("table", rows=tuple(rows)))
        elif match := re.match(r"^(?:[-*]|\d+[.)])\s+(.*)$", stripped):
            blocks.append(ExportBlock("bullet", plain(match.group(1))))
        else:
            blocks.append(ExportBlock("paragraph", plain(stripped)))
    return blocks


def _source_line(number: int, source: ExportSource) -> str:
    return f"{number}. {source.name}" + (f" — {source.url}" if source.url else "")


def to_markdown(title: str, answer: str, sources: list[ExportSource]) -> str:
    out = [f"# {title}", "", answer.strip()]
    if sources:
        out += ["", "## Fontes", ""]
        out += [_source_line(number, source) for number, source in enumerate(sources, 1)]
    return "\n".join(out) + "\n"


def to_docx(title: str, answer: str, sources: list[ExportSource]) -> bytes:
    from docx import Document

    document = Document()
    document.add_heading(title, level=0)
    for block in parse_blocks(answer):
        if block.kind == "heading":
            document.add_heading(block.text, level=min(max(block.level, 1), 4))
        elif block.kind == "bullet":
            document.add_paragraph(block.text, style="List Bullet")
        elif block.kind == "table":
            width = max(len(row) for row in block.rows)
            table = document.add_table(rows=len(block.rows), cols=width)
            table.style = "Table Grid"
            for r, row in enumerate(block.rows):
                for c, cell in enumerate(row):
                    table.cell(r, c).text = cell
        else:
            document.add_paragraph(block.text)
    if sources:
        document.add_heading("Fontes", level=1)
        for number, source in enumerate(sources, 1):
            document.add_paragraph(_source_line(number, source))
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _latin1(text: str) -> str:
    """The built-in PDF fonts are Latin-1: keep Portuguese intact, replace what they cannot draw."""
    text = text.replace("—", "-").replace("–", "-").replace("“", '"').replace("”", '"').replace("’", "'")
    return text.encode("latin-1", "replace").decode("latin-1")


def to_pdf(title: str, answer: str, sources: list[ExportSource]) -> bytes:
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    def write(text: str, *, size: int = 11, bold: bool = False, indent: float = 0) -> None:
        pdf.set_font("Helvetica", "B" if bold else "", size)
        pdf.set_x(pdf.l_margin + indent)
        pdf.multi_cell(0, size * 0.5, _latin1(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(1.5)

    write(title, size=18, bold=True)
    for block in parse_blocks(answer):
        if block.kind == "heading":
            write(block.text, size={1: 16, 2: 14, 3: 12}.get(block.level, 11), bold=True)
        elif block.kind == "bullet":
            write(f"- {block.text}", indent=4)
        elif block.kind == "table":
            pdf.set_font("Helvetica", "", 9)
            with pdf.table(first_row_as_headings=True, text_align="LEFT") as table:
                for row in block.rows:
                    table_row = table.row()
                    for cell in row:
                        table_row.cell(_latin1(cell))
            pdf.ln(2)
        else:
            write(block.text)
    if sources:
        write("Fontes", size=14, bold=True)
        for number, source in enumerate(sources, 1):
            write(_source_line(number, source), size=9, indent=2)
    return bytes(pdf.output())


def render(fmt: str, *, title: str, answer: str, sources: list[ExportSource]) -> tuple[bytes, str]:
    title = sanitize_label(title)[:120] or "Resposta"
    if fmt == "md":
        return to_markdown(title, answer, sources).encode(), FORMATS[fmt][0]
    if fmt == "docx":
        return to_docx(title, answer, sources), FORMATS[fmt][0]
    if fmt == "pdf":
        return to_pdf(title, answer, sources), FORMATS[fmt][0]
    raise ValueError("unsupported export format")
