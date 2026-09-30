import pytest
from app.ingestion.extraction.engines.cloud_api import FallbackOcr
from app.ingestion.extraction.ocr import OcrError, OcrBudgetExceeded

class Engine:
    name, version = "fake", "1"
    def __init__(self, error=None): self.error, self.calls = error, 0
    def recognize(self, pdf, **kwargs):
        self.calls += 1
        if self.error: raise self.error
        return ["ação"]

@pytest.mark.parametrize("enabled,consent,dpa", [(False,True,True),(True,False,True),(True,True,False)])
def test_all_three_gates_required(enabled, consent, dpa):
    primary, secondary = Engine(OcrError()), Engine()
    engine = FallbackOcr(primary, secondary, enabled=enabled, dpa_approved=dpa, allow_secondary=lambda: consent)
    with pytest.raises(OcrError): engine.recognize(b"x",page_count=1)
    assert secondary.calls == 0

def test_allowed_fallback(caplog):
    secondary = Engine()
    engine = FallbackOcr(Engine(OcrError()), secondary, enabled=True, dpa_approved=True, allow_secondary=lambda:True)
    assert engine.recognize(b"private",page_count=1) == ["ação"]
    assert secondary.calls == 1
    assert "private" not in caplog.text

def test_budget_never_falls_back():
    secondary = Engine()
    engine = FallbackOcr(Engine(OcrBudgetExceeded()), secondary, enabled=True, dpa_approved=True, allow_secondary=lambda:True)
    with pytest.raises(OcrBudgetExceeded): engine.recognize(b"x",page_count=1)
    assert secondary.calls == 0
