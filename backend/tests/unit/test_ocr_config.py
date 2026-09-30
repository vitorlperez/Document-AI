import pytest
from pydantic import ValidationError

from app.audit_usage.service import MONTHLY_LIMITS
from app.core.config import Settings
from app.ingestion.extraction.engines import build_ocr

DB = "postgresql+psycopg://u:p@localhost/db"

def test_disabled_defaults():
    s = Settings(database_url=DB, _env_file=None)
    assert s.ocr_engine == "none"
    assert s.ocr_cloud_fallback_enabled is False
    assert build_ocr(s)[0] is None
    assert MONTHLY_LIMITS["ocr_pages"] == 2000

def test_docling_needs_endpoint():
    with pytest.raises(ValidationError):
        Settings(database_url=DB, ocr_engine="docling_serve", _env_file=None)

def test_no_active_cloud_vendor():
    with pytest.raises(ValidationError):
        Settings(database_url=DB, ocr_engine="cloud_api", _env_file=None)
