import re
from io import BytesIO

from docx import Document as DocxDocument
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.ingestion.blocks import ExtractedBlock


def docx_blocks(content: bytes) -> list[ExtractedBlock]:
    docx = DocxDocument(BytesIO(content))
    blocks: list[ExtractedBlock] = []
    headings: list[tuple[int, str]] = []
    for element in docx.element.body.iterchildren():
        if isinstance(element, CT_P):
            paragraph = Paragraph(element, docx)
            if (
                paragraph.style
                and paragraph.style.name.lower().startswith("heading")
                and paragraph.text.strip()
            ):
                level_match = re.search(r"(\d+)$", paragraph.style.name)
                level = int(level_match.group(1)) if level_match else 1
                headings = [(prior, title) for prior, title in headings if prior < level]
                headings.append((level, paragraph.text.strip()))
            elif paragraph.text.strip():
                blocks.append(
                    ExtractedBlock(
                        paragraph.text,
                        section_path=" › ".join(title for _, title in headings) or None,
                    )
                )
        elif isinstance(element, CT_Tbl):
            table = Table(element, docx)
            headers = (
                [" ".join(cell.text.split()) for cell in table.rows[0].cells] if table.rows else []
            )
            for row in table.rows[1:] if len(table.rows) > 1 else table.rows:
                cells = [" ".join(cell.text.split()) for cell in row.cells]
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
