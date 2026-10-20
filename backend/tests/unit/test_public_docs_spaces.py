"""T-I3: the public reference states the Space rules; the contract carries the new fields."""

import json
from pathlib import Path

DOCS = Path(__file__).resolve().parents[3] / "docs"


def test_reference_documents_space_ids_spaces_and_the_intersection_rule():
    text = (DOCS / "api" / "referencia-v1.md").read_text()
    assert "space_ids" in text and "spaces" in text and "interseção" in text
    assert "1.1.0" in (DOCS / "api" / "CHANGELOG.md").read_text()


def test_threat_model_has_the_space_threats():
    text = (DOCS / "seguranca" / "threat-model-api-mcp-canais.md").read_text()
    assert all(f"T-ESP-{n}" in text for n in (1, 2, 3))


def test_openapi_contract_accepts_space_ids():
    spec = json.loads((DOCS / "api" / "openapi-v1.json").read_text())
    for schema in ("SearchInput", "AskInput"):
        assert "space_ids" in spec["components"]["schemas"][schema]["properties"]
    assert spec["info"]["version"] == "1.1.0"
