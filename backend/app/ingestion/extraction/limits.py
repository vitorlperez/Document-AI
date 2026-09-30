import io
import os
from zipfile import ZipFile

from app.ingestion.extraction.errors import ExtractionError

def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


ROWS_PER_BLOCK = 25
MAX_SHEETS = 20
MAX_ROWS_PER_SHEET = 5_000
MAX_COLUMNS = 60
MAX_CELL_CHARS = 2_000
MAX_FILE_BYTES = env_int("MAX_FILE_BYTES", 50 * 1024 * 1024)
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
MAX_ZIP_RATIO = 200
MAX_DOCUMENT_CHARS = 600_000
MAX_CHUNKS_PER_DOCUMENT = 2_000


def guard_size(content: bytes) -> None:
    if len(content) > MAX_FILE_BYTES:
        raise ExtractionError("file_too_large")


def guard_zip(content: bytes) -> None:
    with ZipFile(io.BytesIO(content)) as archive:
        total = sum(item.file_size for item in archive.infolist())
    if total > MAX_UNCOMPRESSED_BYTES or (content and total / len(content) > MAX_ZIP_RATIO):
        raise ExtractionError("file_too_large")

MIN_CHARS_PER_PAGE = 25
OCR_MIN_LOW_PAGE_RATIO = 0.3
OCR_MAX_PAGES_PER_DOCUMENT = env_int("OCR_MAX_PAGES_PER_DOCUMENT", 120)
OCR_PAGES_PER_BATCH = 8
