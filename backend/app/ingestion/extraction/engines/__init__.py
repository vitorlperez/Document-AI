from app.ingestion.extraction.engines.docling_serve import DoclingServeEngine
from app.ingestion.extraction.ocr import OcrBudget


def build_ocr(settings):
    def budget():
        return OcrBudget(pages=settings.ocr_max_pages_per_job,
                         deadline_seconds=settings.ocr_job_deadline_seconds)
    if settings.ocr_engine == "none":
        return None, budget
    if settings.ocr_engine != "docling_serve":
        raise ValueError("External OCR has no approved vendor")
    return DoclingServeEngine(settings.docling_serve_url,
                              timeout=settings.docling_serve_timeout_seconds,
                              languages=settings.ocr_languages,
                              version=settings.docling_serve_version), budget
