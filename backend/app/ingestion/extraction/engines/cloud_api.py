"""No vendor is configured: external processing requires flag, DPA and tenant consent."""
import logging

from app.ingestion.extraction.ocr import OcrBudgetExceeded, OcrError

logger = logging.getLogger("document_intelligence.ocr")


class FallbackOcr:
    def __init__(self, primary, secondary, *, allow_secondary, enabled=False, dpa_approved=False):
        self.primary, self.secondary = primary, secondary
        self.allow_secondary, self.enabled, self.dpa_approved = allow_secondary, enabled, dpa_approved
        self.name = primary.name + "+fallback"
        self.version = primary.version + ":" + secondary.version

    def recognize(self, pdf, *, page_count, cache_key=None):
        try:
            return self.primary.recognize(pdf, page_count=page_count, cache_key=cache_key)
        except OcrBudgetExceeded:
            raise
        except OcrError:
            if not (self.enabled and self.dpa_approved and self.allow_secondary()):
                raise
            logger.warning("OCR fallback", extra={"event": "ocr_fallback"})
            return self.secondary.recognize(pdf, page_count=page_count, cache_key=cache_key)
