"""Pinned Docling Serve v1.35.0 contract measured in F0.3."""
import base64

import httpx

from app.ingestion.extraction.ocr import OcrError
from app.integrations.http import RemoteHttp, RemoteThrottled, RetryPolicy

VERSION = "v1.35.0-pt1"


def pages_from_docling(payload: dict, page_count: int) -> list[str]:
    try:
        if payload["status"] != "success" or payload.get("errors"):
            raise ValueError()
        document = payload["document"]["json_content"]
        texts = document["texts"]
        pages = [[] for _ in range(page_count)]
        # Tables are intentionally rejected until a real table fixture validates provenance.
        if document.get("tables"):
            raise ValueError()
        for item in texts:
            text = item["text"]
            if not isinstance(text, str):
                raise TypeError()
            for page in {int(p["page_no"]) for p in item["prov"]}:
                if not 1 <= page <= page_count:
                    raise ValueError()
                pages[page - 1].append(text)
        return ["\n".join(items) for items in pages]
    except (KeyError, ValueError, TypeError, IndexError):
        raise OcrError("OCR engine failed") from None


class DoclingServeEngine:
    name = "docling-serve"

    def __init__(self, base_url, *, timeout=120.0, languages="por,eng", version=VERSION, http=None):
        self.base_url, self.timeout, self.languages, self.version = base_url.rstrip("/"), timeout, languages, version
        # 504 is docling's own timeout: resending only piles up duplicate conversions.
        policy = RetryPolicy(max_attempts=3, max_total_wait=20.0, retry_statuses=frozenset({429, 500, 502, 503}))
        self.http = http or RemoteHttp(policy=policy)

    def recognize(self, pdf, *, page_count, cache_key=None):
        try:
            response = self.http.request(
                "POST", self.base_url + "/v1/convert/source",
                json={"sources": [{"kind": "file", "filename": "document.pdf",
                                   "base64_string": base64.b64encode(pdf).decode("ascii")}],
                      "options": {"to_formats": ["json", "text"], "do_ocr": True,
                                  "force_ocr": True, "ocr_preset": "tesseract",
                                  "ocr_lang": self.languages.split(","),
                                  "do_table_structure": False,
                                  "document_timeout": self.timeout}},
                timeout=self.timeout,
            )
            response.raise_for_status()
            return pages_from_docling(response.json(), page_count)
        except (httpx.HTTPError, RemoteThrottled, ValueError, KeyError, TypeError):
            raise OcrError("OCR engine failed") from None
