"""Independent HTTP regressions for authorized cross-tool retrieval."""

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from app.audit_usage.models import UsageRecord
from app.audit_usage.service import MONTHLY_LIMITS
from app.identity.models import User
from app.integrations.models import DataSource
from app.knowledge.models import Document, DocumentChunk
from app.knowledge.questions import AIProviderUnavailable, GeneratedAnswer
from app.organizations.models import Membership, PlatformStaff
from app.workspaces.models import WorkspaceFolder
from tests.api.test_text_search_api import (
    create_organization,
    login,
    search_api,  # noqa: F401 -- explicitly reuse the established isolated API fixture
    seed_indexed_document,
)


class RecordingProvider:
    def __init__(self, fail_at=None):
        self.embeds = []
        self.answers = []
        self.fail_at = fail_at

    def embed(self, *, texts):
        self.embeds.append(texts)
        if self.fail_at == "embed":
            raise AIProviderUnavailable("secret upstream error")
        return [[1.0, 0.0] for _ in texts]

    def answer(self, *, question, evidence):
        self.answers.append(evidence)
        if self.fail_at == "answer":
            raise AIProviderUnavailable("secret upstream error")
        return GeneratedAnswer(
            "The campaign launches in September.", list(range(1, len(evidence) + 1))
        )


@pytest.fixture()
def corpus(search_api):  # noqa: F811 -- pytest injects the explicitly imported fixture
    client, factory, gateway = search_api
    login(client, gateway, code="owner", email="owner@example.test", subject="owner")
    organization_id = create_organization(client)
    folders = {}
    for provider in ("google_drive", "notion"):
        folder_id = seed_indexed_document(factory, organization_id=organization_id)
        with factory.begin() as session:
            folder = session.get(WorkspaceFolder, folder_id)
            folder.name = provider
            session.get(DataSource, folder.source_id).provider = provider
            document = session.query(Document).filter_by(workspace_folder_id=folder_id).one()
            document.name = f"{provider} campaign.pdf"
            document.external_file_id = provider
            document.source_url = f"https://{provider}.example.test/campaign"
        folders[provider] = folder_id
    provider = RecordingProvider()
    client.app.state.semantic_provider = provider
    return client, factory, gateway, organization_id, folders, provider


def ask(client, organization_id, **scope):
    return client.post(
        f"/organizations/{organization_id}/questions",
        json={"question": "When does the campaign launch?", **scope},
    )


def test_organization_combines_tools_and_cites_actual_evidence(corpus):
    client, _, _, organization_id, _, provider = corpus
    response = ask(client, organization_id, scope="organization")
    assert response.status_code == 200
    payload = response.json()
    assert payload["confidence"] == "supported"
    assert payload["retrieval_status"] == "sufficient_evidence"
    assert {item["source_provider"] for item in payload["citations"]} == {"google_drive", "notion"}
    assert {item["document_id"] for item in payload["citations"]} == {
        str(item.document_id) for item in provider.answers[0]
    }
    for citation in payload["citations"]:
        assert citation["document_name"] == f"{citation['source_provider']} campaign.pdf"
        assert (
            citation["source_url"] == f"https://{citation['source_provider']}.example.test/campaign"
        )
    assert len(provider.embeds) == len(provider.answers) == 1


def test_answer_links_are_removed_but_document_references_keep_original_urls(corpus, monkeypatch):
    client, _, _, organization_id, folders, provider = corpus
    generated = (
        "O prazo está no [escopo do projeto](https://drive.google.com/file/d/(briefing_(v2))) "
        "(google_drive: https://docs.google.com/document/d/abc/edit?usp=drivesdk) [1].\n"
        "Fonte: [Escopo](https://drive.google.com/file/d/briefing)\n"
        "Fonte: https://drive.google.com/file/d/briefing_(v2)\n"
        "A decisão consta na reunião (https://example.test/reuniao) [2][3]. "
        "Veja www.notion.so/reuniao para detalhes.\n[1]."
    )
    monkeypatch.setattr(
        provider,
        "answer",
        lambda *, question, evidence: GeneratedAnswer(generated, list(range(1, len(evidence) + 1))),
    )

    responses = [
        ask(client, organization_id, scope="organization"),
        client.post(
            f"/workspace-folders/{folders['google_drive']}/questions?organization_id={organization_id}",
            json={"question": "When does the campaign launch?"},
        ),
    ]
    for response in responses:
        assert response.status_code == 200
        payload = response.json()
        assert payload["confidence"] == "supported"
        assert "escopo do projeto" in payload["answer"]
        assert "O prazo está" in payload["answer"]
        assert "Fonte:" not in payload["answer"]
        assert "http" not in payload["answer"]
        assert "www." not in payload["answer"]
        assert "[escopo" not in payload["answer"]
        assert "briefing_" not in payload["answer"]
        assert "()" not in payload["answer"]
        assert "google_drive:" not in payload["answer"]
        assert "[1]" not in payload["answer"]
        assert "[2]" not in payload["answer"]
        assert payload["citations"]
        assert all(item["source_url"].startswith("https://") for item in payload["citations"])


def test_provider_scope_excludes_other_tools_before_generation(corpus):
    client, _, _, organization_id, _, provider = corpus
    response = ask(client, organization_id, scope="provider", provider="google_drive")
    assert response.status_code == 200
    assert {item["source_provider"] for item in response.json()["citations"]} == {"google_drive"}
    assert {item.source_provider for item in provider.answers[0]} == {"google_drive"}
    assert "notion" not in response.text


def test_provider_scope_accepts_ui_canonical_google_provider(corpus):
    client, _, _, organization_id, _, provider = corpus
    response = ask(client, organization_id, scope="provider", provider="google")
    assert response.status_code == 200
    assert {item["source_provider"] for item in response.json()["citations"]} == {"google_drive"}
    assert {item.source_provider for item in provider.answers[0]} == {"google_drive"}


@pytest.mark.parametrize("access", ["foreign", "inactive", "staff"])
def test_unauthorized_broad_scope_never_calls_model(corpus, access):
    client, factory, gateway, organization_id, _, provider = corpus
    if access == "inactive":
        with factory.begin() as session:
            session.query(Membership).filter_by(organization_id=organization_id).update(
                {"is_active": False}
            )
    else:
        login(client, gateway, code="outsider", email="outsider@example.test", subject="outsider")
        if access == "staff":
            with factory.begin() as session:
                outsider = session.query(User).filter_by(email="outsider@example.test").one()
                session.add(PlatformStaff(user_id=outsider.id))
    response = ask(client, organization_id, scope="organization")
    assert response.status_code == 403
    assert "September" not in response.text
    assert provider.embeds == provider.answers == []


@pytest.mark.parametrize(
    "scope",
    [
        {},
        {"scope": "folder"},
        {"scope": "provider"},
        {"scope": "provider", "provider": "  "},
        {"scope": "organization", "provider": "google_drive"},
    ],
)
def test_invalid_scope_is_rejected_before_generation(corpus, scope):
    client, _, _, organization_id, _, provider = corpus
    response = ask(client, organization_id, **scope)
    assert response.status_code == 422
    assert provider.embeds == provider.answers == []


@pytest.mark.parametrize(
    "empty_kind", ["unknown_provider", "pending", "no_documents", "no_embeddings"]
)
def test_empty_or_pending_context_is_safe_without_model(corpus, empty_kind):
    client, factory, _, organization_id, _, provider = corpus
    with factory.begin() as session:
        if empty_kind == "pending":
            session.query(WorkspaceFolder).update({"status": "pending"})
        elif empty_kind == "no_documents":
            session.query(DocumentChunk).delete()
            session.query(Document).delete()
        elif empty_kind == "no_embeddings":
            session.query(DocumentChunk).update({"embedding": None, "embedding_model": None})
    scope = (
        {"scope": "provider", "provider": "unknown_tool"}
        if empty_kind == "unknown_provider"
        else {"scope": "organization"}
    )
    response = ask(client, organization_id, **scope)
    assert response.status_code == 200
    payload = response.json()
    assert {
        key: payload[key] for key in ("answer", "confidence", "citations", "retrieval_status")
    } == {
        "answer": None,
        "confidence": "insufficient_evidence",
        "citations": [],
        "retrieval_status": "no_compatible_embeddings"
        if empty_kind == "no_embeddings"
        else "no_indexed_content",
    }
    assert provider.embeds == provider.answers == []


def test_foreign_source_join_cannot_supply_evidence_or_provider_metadata(corpus):
    client, factory, _, organization_id, folders, provider = corpus
    with factory.begin() as session:
        folder = session.get(WorkspaceFolder, folders["notion"])
        session.get(DataSource, folder.source_id).organization_id = uuid4()
    response = ask(client, organization_id, scope="organization")
    assert response.status_code == 200
    assert {item["source_provider"] for item in response.json()["citations"]} == {"google_drive"}
    assert {item.source_provider for item in provider.answers[0]} == {"google_drive"}
    assert "notion" not in response.text


def test_broad_scope_quota_blocks_model_and_preserves_counter(corpus):
    client, factory, _, organization_id, _, provider = corpus
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
    response = ask(client, organization_id, scope="organization")
    assert response.status_code == 429
    assert provider.embeds == provider.answers == []
    with factory() as session:
        assert (
            session.query(UsageRecord).filter_by(metric="questions").one().quantity
            == MONTHLY_LIMITS["questions"]
        )


@pytest.mark.parametrize("fail_at", ["embed", "answer"])
def test_provider_failures_are_safe_and_count_one_attempt_like_folder_questions(corpus, fail_at):
    client, factory, _, organization_id, _, _ = corpus
    client.app.state.semantic_provider = RecordingProvider(fail_at=fail_at)
    response = ask(client, organization_id, scope="organization")
    assert response.status_code == 503
    assert response.json() == {"detail": "AI provider unavailable"}
    # Preserve existing question-attempt accounting when the upstream model fails.
    with factory() as session:
        assert (
            sum(row.quantity for row in session.query(UsageRecord).filter_by(metric="questions"))
            == 1
        )


def test_other_organization_content_never_reaches_generation(corpus):
    client, factory, _, organization_id, _, provider = corpus
    other_organization = create_organization(client)
    foreign_folder = seed_indexed_document(factory, organization_id=other_organization)
    with factory.begin() as session:
        document = session.query(Document).filter_by(workspace_folder_id=foreign_folder).one()
        document.name = "Private foreign campaign.pdf"
        session.query(DocumentChunk).filter_by(workspace_folder_id=foreign_folder).update(
            {
                "text": "Private foreign campaign launches in December.",
                "search_text": "Private foreign campaign launches in December.",
            }
        )
    response = ask(client, organization_id, scope="organization")
    assert response.status_code == 200
    assert "Private foreign" not in response.text
    assert all("Private foreign" not in item.excerpt for item in provider.answers[0])
    assert len(response.json()["citations"]) == 2


def test_provider_alias_includes_legacy_google_sources(corpus):
    client, factory, _, organization_id, folders, provider = corpus
    with factory.begin() as session:
        folder = session.get(WorkspaceFolder, folders["google_drive"])
        session.get(DataSource, folder.source_id).provider = "google"
    response = ask(client, organization_id, scope="provider", provider="google_drive")
    assert response.status_code == 200
    assert response.json()["confidence"] == "supported"
    assert len(response.json()["citations"]) == 1
    assert len(provider.answers[0]) == 1
    assert provider.answers[0][0].document_name == "google_drive campaign.pdf"


def test_partial_coverage_counts_pending_folders_and_only_sends_ready_evidence(corpus):
    client, factory, _, organization_id, folders, provider = corpus
    with factory.begin() as session:
        session.get(WorkspaceFolder, folders["notion"]).status = "pending"
    response = ask(client, organization_id, scope="organization")
    assert response.status_code == 200
    assert response.json()["coverage"] == {
        "total_folders": 2,
        "eligible_folders": 1,
        "pending_folders": 1,
    }
    assert {item.source_provider for item in provider.answers[0]} == {"google_drive"}
