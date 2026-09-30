import json
from pathlib import Path

import httpx
import pytest

from app.ingestion.extraction.engines.docling_serve import DoclingServeEngine, pages_from_docling
from app.ingestion.extraction.ocr import OcrError
from app.integrations.http import RemoteHttp, RetryPolicy


def payload():
    return json.loads((Path(__file__).parents[1] / "fixtures/ocr_pt/docling_serve_response.json").read_text())


def test_real_response_preserves_pages_and_accents():
    pages = pages_from_docling(payload(), 3)
    assert len(pages) == 3 and all("ção" in p for p in pages)


def test_missing_page_is_empty():
    value = payload()
    value["document"]["json_content"]["texts"] = []
    assert pages_from_docling(value, 3) == ["", "", ""]


@pytest.mark.parametrize("value", [{}, {"status": "failure"}, {"status": "success", "document": {}}])
def test_invalid_payload_is_not_success(value):
    with pytest.raises(OcrError):
        pages_from_docling(value, 1)


def test_retry_and_measured_json_contract(monkeypatch):
    calls = []
    now = [0.0]
    def send(url, **kwargs):
        calls.append(kwargs)
        return httpx.Response(503 if len(calls) < 3 else 200, json=payload(), request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", send)
    http = RemoteHttp(policy=RetryPolicy(max_attempts=3), sleep=lambda s: now.__setitem__(0, now[0]+s), monotonic=lambda: now[0])
    pages = DoclingServeEngine("http://sidecar", http=http).recognize(b"pdf", page_count=3)
    assert len(pages) == 3 and len(calls) == 3
    assert calls[0]["json"]["sources"][0]["base64_string"] == "cGRm"
    assert calls[0]["json"]["options"]["ocr_lang"] == ["por", "eng"]


def test_timeout_is_opaque(monkeypatch):
    def send(*args, **kwargs):
        raise httpx.ReadTimeout("private document text")
    monkeypatch.setattr(httpx, "post", send)
    with pytest.raises(OcrError, match="^OCR engine failed$"):
        DoclingServeEngine("http://sidecar").recognize(b"secret", page_count=1)


def test_gateway_timeout_is_not_resent(monkeypatch):
    calls = []
    def send(url, **kwargs):
        calls.append(url)
        return httpx.Response(504, text="timeout", request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", send)
    with pytest.raises(OcrError):
        DoclingServeEngine("http://sidecar").recognize(b"pdf", page_count=1)
    assert len(calls) == 1
