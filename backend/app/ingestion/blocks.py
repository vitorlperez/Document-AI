from dataclasses import dataclass


@dataclass(frozen=True)
class ExtractedBlock:
    """A structurally bounded piece of extracted text and its known location."""

    text: str
    page_number: int | None = None
    section_path: str | None = None
    ocr: bool = False
