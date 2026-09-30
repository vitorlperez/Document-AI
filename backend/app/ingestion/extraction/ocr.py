"""OCR contract and per-job budget. Engines live in engines/ (Docling sidecar, cloud API)."""

import threading
import time
from collections.abc import Callable
from typing import Protocol


class OcrError(RuntimeError):
    """The engine failed or returned something unusable (never carries document text)."""


class OcrBudgetExceeded(OcrError):
    pass


class OcrEngine(Protocol):
    name: str
    version: str

    def recognize(self, pdf: bytes, *, page_count: int, cache_key: str | None = None) -> list[str]: ...


class OcrBudget:
    def __init__(self, *, pages: int, deadline_seconds: float | None = None,
                 monotonic: Callable[[], float] = time.monotonic) -> None:
        self._pages, self._monotonic = pages, monotonic
        self._deadline = None if deadline_seconds is None else monotonic() + deadline_seconds
        self._lock = threading.Lock()

    def reserve(self, pages: int) -> None:
        with self._lock:
            if self._deadline is not None and self._monotonic() > self._deadline:
                raise OcrBudgetExceeded("OCR time budget exhausted")
            if pages > self._pages:
                raise OcrBudgetExceeded("OCR page budget exhausted")
            self._pages -= pages