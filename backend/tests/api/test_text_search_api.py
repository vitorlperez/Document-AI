import importlib
from collections.abc import Generator
from datetime import UTC, date, datetime
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.audit_usage.models import UsageRecord
from app.audit_usage.service import MONTHLY_LIMITS
from app.core.config import Settings
from app.core.models import Base
from app.identity.auth import AuthenticationUnavailable, VerifiedIdentity
from app.identity.models import User
from app.integrations.models import DataSource
from app.knowledge.models import Document, DocumentChunk
from app.knowledge.questions import EMBEDDING_MODEL, GeneratedAnswer
from app.organizations.models import Membership, MembershipRole
from app.workspaces.models import WorkspaceFolder


class FakeAuthGateway:
    def __init__(self) -> None:
        self.identities: dict[str, VerifiedIdentity] = {}

    def authorization_url(self, *, state: str) -> str:
        return f"https://auth.example.test/login?state={state}"

    def exchange_code(self, *, code: str) -> VerifiedIdentity:
        try:
            return self.identities[code]
        except KeyError as error:
            raise AuthenticationUnavailable("invalid code") from error


class FakeSemanticProvider:
    def embed(self, *, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]

    def answer(self, *, question: str, evidence) -> GeneratedAnswer:
        return GeneratedAnswer("The campaign launches in September.", [1])


@pytest.fixture()
def search_api(monkeypatch: pytest.MonkeyPatch) -> Generator[tuple[TestClient, sessionmaker[Session], FakeAuthGateway]]:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test_user:not-a-secret@localhost:5432/test_db")
    main = importlib.import_module("app.main")
    settings = Settings(
        database_url="postgresql+psycopg://test_user:not-a-secret@localhost:5432/test_db",
        public_app_url="http://app.example.test",
        environment="development",
    )
    app = main.create_app(settings)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    gateway = FakeAuthGateway()
    app.state.session_factory = factory
    app.state.auth_gateway = gateway
    with TestClient(app) as client:
        yield client, factory, gateway
    Base.metadata.drop_all(engine)
    engine.dispose()


def login(client: TestClient, gateway: FakeAuthGateway, *, code: str, email: str, subject: str) -> None:
    gateway.identities[code] = VerifiedIdentity(provider="workos", subject=subject, email=email)
    started = client.get("/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    response = client.get(f"/auth/callback?code={code}&state={state}", follow_redirects=False)
    assert response.status_code == 302


def create_organization(client: TestClient) -> UUID:
    response = client.post("/organizations", json={"name": "Acme"})
    assert response.status_code == 201
    return UUID(response.json()["id"])


def seed_indexed_document(factory: sessionmaker[Session], *, organization_id: UUID) -> UUID:
    with factory.begin() as session:
        user = session.query(User).one()
        source = DataSource(
            organization_id=organization_id,
            provider="google_drive",
            encrypted_credentials="ciphertext",
            status="connected",
            connected_by_user_id=user.id,
        )
        session.add(source)
        session.flush()
        folder = WorkspaceFolder(
            organization_id=organization_id,
            source_id=source.id,
            external_folder_id="folder-1",
            name="Client A",
            uniform_access_confirmed=True,
            status="ready",
        )
        session.add(folder)
        session.flush()
        document = Document(
            organization_id=organization_id,
            workspace_folder_id=folder.id,
            external_file_id="briefing",
            name="Campaign Briefing.pdf",
            mime_type="application/pdf",
            source_url="https://drive.example.test/briefing",
            content_hash="a" * 64,
            processing_version="v1",
            index_status="indexed",
        )
        session.add(document)
        session.flush()
        session.add(
            DocumentChunk(
                organization_id=organization_id,
                workspace_folder_id=folder.id,
                document_id=document.id,
                position=0,
                text="The campaign launches in September.",
                search_text="Campaign Briefing.pdf\nThe campaign launches in September.",
                embedding=[1.0, 0.0],
                embedding_model=EMBEDDING_MODEL,
            )
        )
        return folder.id


def test_search_api_returns_scoped_title_and_chunk_hits_and_rejects_invalid_input(search_api) -> None:
    client, factory, gateway = search_api
    login(client, gateway, code="owner", email="owner@example.test", subject="owner")
    organization_id = create_organization(client)
    folder_id = seed_indexed_document(factory, organization_id=organization_id)

    title = client.post(
        f"/workspace-folders/{folder_id}/search?organization_id={organization_id}",
        json={"query": "briefing"},
    )
    chunk = client.post(
        f"/workspace-folders/{folder_id}/search?organization_id={organization_id}",
        json={"query": "September"},
    )
    blank = client.post(
        f"/workspace-folders/{folder_id}/search?organization_id={organization_id}",
        json={"query": "  "},
    )
    oversized = client.post(
        f"/workspace-folders/{folder_id}/search?organization_id={organization_id}",
        json={"query": "x" * 501},
    )
    oversized_page = client.post(
        f"/workspace-folders/{folder_id}/search?organization_id={organization_id}",
        json={"query": "briefing", "page_size": 51},
    )

    assert title.status_code == 200
    assert chunk.status_code == 200
    assert title.json()["items"][0]["document_name"] == "Campaign Briefing.pdf"
    assert "September" in chunk.json()["items"][0]["excerpt"]
    assert all(response.status_code == 422 for response in (blank, oversized, oversized_page))


def test_search_api_denies_a_user_from_another_organization(search_api) -> None:
    client, factory, gateway = search_api
    login(client, gateway, code="owner-a", email="owner-a@example.test", subject="owner-a")
    organization_a = create_organization(client)
    folder_id = seed_indexed_document(factory, organization_id=organization_a)
    login(client, gateway, code="owner-b", email="owner-b@example.test", subject="owner-b")
    organization_b = create_organization(client)

    response = client.post(
        f"/workspace-folders/{folder_id}/search?organization_id={organization_b}",
        json={"query": "briefing"},
    )

    assert response.status_code == 403
    assert "Campaign Briefing" not in response.text


def test_questions_api_returns_cited_answer_and_denies_cross_tenant(search_api) -> None:
    client, factory, gateway = search_api
    client.app.state.semantic_provider = FakeSemanticProvider()
    login(client, gateway, code="owner-a", email="owner-a@example.test", subject="owner-a")
    organization_a = create_organization(client)
    folder_id = seed_indexed_document(factory, organization_id=organization_a)

    supported = client.post(
        f"/workspace-folders/{folder_id}/questions?organization_id={organization_a}",
        json={"question": "When does the campaign launch?"},
    )

    assert supported.status_code == 200
    assert supported.json()["confidence"] == "supported"
    assert supported.json()["citations"] == [
        {
            "document_id": supported.json()["citations"][0]["document_id"],
            "document_name": "Campaign Briefing.pdf",
            "excerpt": "The campaign launches in September.",
            "page_number": None,
            "source_url": "https://drive.example.test/briefing",
        }
    ]

    login(client, gateway, code="owner-b", email="owner-b@example.test", subject="owner-b")
    organization_b = create_organization(client)
    denied = client.post(
        f"/workspace-folders/{folder_id}/questions?organization_id={organization_b}",
        json={"question": "When does the campaign launch?"},
    )
    assert denied.status_code == 403
    assert "September" not in denied.text


def test_saved_queries_api_persists_only_query_metadata_and_supports_owner_crud(search_api) -> None:
    client, factory, gateway = search_api
    login(client, gateway, code="owner", email="owner@example.test", subject="owner")
    organization_id = create_organization(client)
    folder_id = seed_indexed_document(factory, organization_id=organization_id)
    created = client.post(
        f"/workspace-folders/{folder_id}/saved-queries?organization_id={organization_id}",
        json={"name": "Launch", "query": "When is launch?", "filters": {"type": "briefing"}},
    )
    saved_id = created.json()["id"]
    listed = client.get(f"/workspace-folders/{folder_id}/saved-queries?organization_id={organization_id}")
    renamed = client.patch(f"/saved-queries/{saved_id}?organization_id={organization_id}", json={"name": "Launch date"})
    deleted = client.delete(f"/saved-queries/{saved_id}?organization_id={organization_id}")
    assert created.status_code == 201 and "answer" not in created.json()
    assert listed.json()[0]["query"] == "When is launch?"
    assert renamed.json()["name"] == "Launch date"
    assert deleted.status_code == 204


def test_saved_query_rejects_response_or_retrieved_content_payloads(search_api) -> None:
    client, factory, gateway = search_api
    login(client, gateway, code="owner", email="owner@example.test", subject="owner")
    organization_id = create_organization(client)
    folder_id = seed_indexed_document(factory, organization_id=organization_id)

    response = client.post(
        f"/workspace-folders/{folder_id}/saved-queries?organization_id={organization_id}",
        json={"name": "Unsafe", "query": "launch", "filters": {"answer": "September"}},
    )

    assert response.status_code == 422


def test_other_member_cannot_modify_owner_saved_query_or_access_forged_folder(search_api) -> None:
    client, factory, gateway = search_api
    login(client, gateway, code="owner", email="owner@example.test", subject="owner")
    organization_id = create_organization(client)
    folder_id = seed_indexed_document(factory, organization_id=organization_id)
    saved_id = client.post(
        f"/workspace-folders/{folder_id}/saved-queries?organization_id={organization_id}",
        json={"name": "Owner", "query": "Owner query", "filters": {}},
    ).json()["id"]
    login(client, gateway, code="member", email="member@example.test", subject="member")
    with factory.begin() as session:
        member = session.query(User).filter_by(email="member@example.test").one()
        session.add(Membership(organization_id=organization_id, user_id=member.id, role=MembershipRole.MEMBER, is_active=True))
    listed = client.get(f"/workspace-folders/{folder_id}/saved-queries?organization_id={organization_id}")
    renamed = client.patch(f"/saved-queries/{saved_id}?organization_id={organization_id}", json={"name": "Forged"})
    deleted = client.delete(f"/saved-queries/{saved_id}?organization_id={organization_id}")
    forged = client.get(f"/workspace-folders/{UUID(int=0)}/saved-queries?organization_id={organization_id}")
    assert listed.status_code == 200 and listed.json() == []
    assert renamed.status_code == deleted.status_code == forged.status_code == 403


def test_question_limit_blocks_only_the_new_question_and_leaves_search_readable(search_api) -> None:
    client, factory, gateway = search_api
    client.app.state.semantic_provider = FakeSemanticProvider()
    login(client, gateway, code="owner", email="owner@example.test", subject="owner")
    organization_id = create_organization(client)
    folder_id = seed_indexed_document(factory, organization_id=organization_id)
    now = datetime.now(UTC)
    with factory.begin() as session:
        session.add(
            UsageRecord(
                organization_id=organization_id,
                period_start=date(now.year, now.month, 1),
                metric="questions",
                quantity=MONTHLY_LIMITS["questions"],
            )
        )

    question = client.post(
        f"/workspace-folders/{folder_id}/questions?organization_id={organization_id}",
        json={"question": "When does the campaign launch?"},
    )
    search = client.post(
        f"/workspace-folders/{folder_id}/search?organization_id={organization_id}",
        json={"query": "September"},
    )
    with factory() as session:
        recorded = session.query(UsageRecord).one()

    assert question.status_code == 429
    assert search.status_code == 200
    assert recorded.quantity == MONTHLY_LIMITS["questions"]
