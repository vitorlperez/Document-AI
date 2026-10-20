"""Seed the local dev database with the Spaces demo (Acme in ``shadow``, Beta in ``enforce``).

Run from backend against the dev database (never production):
  DATABASE_URL=postgresql+psycopg://...@localhost:5432/... .venv/bin/python -m scripts.seed_espacos_demo [--out sessions.json]

Each organization gets the Acme world of tests/spaces_helpers.py (Geral, RH, Diretoria; eva owner, ana RH manager,
bruno, carla, daniel). Local dev has no password login, so the script also mints one opaque session per person and
writes the cookie values to --out; set the cookie ``document_intelligence_session`` in the browser to log in.
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import build_engine, build_session_factory
from app.core.vector import EMBEDDING_DIMENSIONS
from app.identity.auth import IdentityService
from app.knowledge.models import DocumentChunk
from app.organizations.models import Membership, Organization
from app.spaces import rollout
from tests.spaces_helpers import seed_world

DEMOS = (("Acme", "shadow"), ("Beta", "off"))


def widen_demo_embeddings(session: Session, organization_id: UUID) -> None:
    """seed_world stores 2-dim test embeddings; pgvector (VECTOR(1536)) rejects them and every question 500s.

    Zero-padding keeps the chunks scorable (valid dimension) without calling the embedding provider.
    """
    for chunk in session.scalars(select(DocumentChunk).where(DocumentChunk.organization_id == organization_id)):
        vector = list(chunk.embedding or [])
        vector += [0.0] * (EMBEDDING_DIMENSIONS - len(vector))
        chunk.embedding, chunk.embedding_vec = vector, vector


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("/private/tmp/espacos-smoke/sessions.json"))
    args = parser.parse_args()
    settings = get_settings()
    sessions: dict[str, dict] = {}
    with build_session_factory(build_engine(settings))() as session:
        for name, mode in DEMOS:
            if session.scalar(select(Organization).where(Organization.name == name)):
                raise SystemExit(f"organização {name} já existe; resete o banco antes de semear de novo")
            world = seed_world(session, mode=mode, name=name)
            widen_demo_embeddings(session, world.organization_id)
            org = session.get(Organization, world.organization_id)
            org.onboarding_step, org.onboarding_completed_at = "complete", datetime.now(UTC)
            for membership in session.scalars(select(Membership).where(Membership.organization_id == org.id)):
                membership.tour_completed_at = datetime.now(UTC)  # demo people skip the product tour
            if name == "Beta":
                session.flush()
                if rollout.run(["enforce", "--organization", str(world.organization_id)], session) != 0:
                    raise SystemExit("rollout recusou enforce em Beta")
            for who, user_id in world.users.items():
                _, raw = IdentityService(session).create_session(user_id=user_id, ttl_hours=24 * 30)
                sessions[f"{who}@{name.lower()}.test"] = {
                    "organization": name, "mode": "enforce" if name == "Beta" else mode, "cookie": raw}
        session.commit()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"cookie_name": settings.auth_session_cookie_name, "users": sessions}, indent=2))
    print(f"{len(sessions)} pessoas semeadas; sessões em {args.out}")


if __name__ == "__main__":
    main()
