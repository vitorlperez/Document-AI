"""Export only /v1 without database, Redis or provider network calls."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.openapi.utils import get_openapi

from app.api.public_v1 import router

TARGET = Path(__file__).resolve().parents[2] / "docs/api/openapi-v1.json"


def schema():
    return get_openapi(title="Arquivio Public API", version="1.0.0", routes=router.routes,
                       description="Read-only organization library. Bearer API keys.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = json.dumps(schema(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.check:
        from openapi_spec_validator import validate
        validate(schema())
        if not TARGET.exists() or TARGET.read_text() != rendered:
            print("OpenAPI differs: run python scripts/export_openapi.py")
            return 1
        print("OpenAPI export matches /v1")
    else:
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        TARGET.write_text(rendered)
        print("Exported docs/api/openapi-v1.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
