import re

from docx import Document as DocxDocument
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.text.run import Run

from app.ingestion.blocks import ExtractedBlock
from app.ingestion.extraction import limits


def _visible(paragraph: Paragraph) -> str:
    """Text of the runs that are not hidden (w:vanish), hyperlinks included."""
    return "".join(
        Run(run, paragraph).text
        for run in paragraph._p.xpath(".//w:r")
        if not Run(run, paragraph).font.hidden
    )


def _cell(cell) -> str:
    return " ".join(" ".join(_visible(p) for p in cell.paragraphs).split())


def docx_blocks(content) -> list[ExtractedBlock]:
    docx = DocxDocument(limits.as_stream(content))
    blocks: list[ExtractedBlock] = []
    headings: list[tuple[int, str]] = []
    for element in docx.element.body.iterchildren():
        if isinstance(element, CT_P):
            paragraph = Paragraph(element, docx)
            if (
                paragraph.style
                and paragraph.style.name.lower().startswith("heading")
                and _visible(paragraph).strip()
            ):
                level_match = re.search(r"(\d+)$", paragraph.style.name)
                level = int(level_match.group(1)) if level_match else 1
                headings = [(prior, title) for prior, title in headings if prior < level]
                headings.append((level, _visible(paragraph).strip()))
            elif _visible(paragraph).strip():
                blocks.append(
                    ExtractedBlock(
                        _visible(paragraph),
                        section_path=" › ".join(title for _, title in headings) or None,
                    )
                )
        elif isinstance(element, CT_Tbl):
            table = Table(element, docx)
            headers = (
                [_cell(cell) for cell in table.rows[0].cells] if table.rows else []
            )
            for row in table.rows[1:] if len(table.rows) > 1 else table.rows:
                cells = [_cell(cell) for cell in row.cells]
                if any(cells):
                    row_text = " | ".join(
                        f"{headers[index]}: {value}"
                        if index < len(headers) and headers[index]
                        else value
                        for index, value in enumerate(cells)
                    )
                    blocks.append(
                        ExtractedBlock(
                            row_text,
                            section_path=" › ".join(title for _, title in headings) or None,
                        )
                    )
    return blocks
