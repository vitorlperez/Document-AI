from datetime import UTC, datetime
from uuid import UUID

from app.notifications.automation_email import render_automation_email
from app.organizations.delivery import ResendEmailDelivery

ORG = UUID("00000000-0000-0000-0000-000000000001")
AUTOMATION = UUID("00000000-0000-0000-0000-000000000002")
RUN = UUID("00000000-0000-0000-0000-000000000003")


def render(**overrides):
    args = {
        "name": "Resumo <financeiro>",
        "answer": "**Receita** cresceu.\n\nSegundo parágrafo.\n\nTerceiro parágrafo.\n\nNão deve aparecer.",
        "folders": ["Financeiro & Operações"],
        "completed_at": datetime(2026, 10, 12, 12, 30, tzinfo=UTC),
        "timezone": "America/Sao_Paulo",
        "citations": [
            {"document_name": "<img src=x onerror=alert(1)>", "source_url": "javascript:alert(1)"}
        ],
        "organization_id": ORG,
        "automation_id": AUTOMATION,
        "run_id": RUN,
        "app_url": "https://www.arquivio.com.br",
        "pdf_available": True,
    }
    return render_automation_email(**(args | overrides))


def test_email_has_brand_metadata_safe_summary_and_matching_plain_text():
    message = render()
    assert "https://www.arquivio.com.br/arquivio-logo-120.png" in message.html
    assert "Resumo &lt;financeiro&gt;" in message.html
    assert "Financeiro &amp; Operações" in message.html
    assert "12/10/2026 às 09:30" in message.html
    assert "<strong>Receita</strong>" in message.html
    assert "Segundo parágrafo." in message.html and "Terceiro parágrafo…" in message.html
    assert "Não deve aparecer." not in message.html
    assert "<img src=x" not in message.html and "javascript:" not in message.html
    assert "Ver relatório completo" in message.html and "Baixar PDF" in message.html
    assert f"automation={AUTOMATION}&amp;run={RUN}" in message.html
    assert f"/api/organizations/{ORG}/automations/{AUTOMATION}/runs/{RUN}/pdf" in message.html
    assert "Receber também por e-mail" in message.text and "Editar automação" in message.text
    assert "Resumo <financeiro>" in message.text and "Segundo parágrafo." in message.text
    assert f"automation={AUTOMATION}&run={RUN}" in message.text


def test_email_bounds_long_answer_and_deduplicates_sources():
    sources = [
        {
            "document_name": f"Fonte {i}",
            "document_id": str(i),
            "source_url": "https://example.com/doc",
        }
        for i in range(8)
    ]
    message = render(answer="a" * 10000, citations=[sources[0], *sources])
    assert len(message.html) < 14000
    assert message.html.count("Fonte 0") == 1
    assert "Fonte 3" in message.html and "Fonte 4" not in message.html
    assert "Mais 4 fontes no relatório completo." in message.html
    assert "…" in message.text


def test_email_without_pdf_and_invalid_url_or_timezone():
    message = render(pdf_available=False, app_url="javascript:alert(1)", timezone="Invalid/Zone")
    assert "Baixar PDF" not in message.html and "Baixar PDF" not in message.text
    assert "https://www.arquivio.com.br/companies/" in message.html
    assert "America/Sao_Paulo" in message.text
    assert "javascript:" not in message.html


def test_resend_sends_both_mime_alternatives(monkeypatch):
    sent = []
    monkeypatch.setattr(
        "app.organizations.delivery.resend.Emails.send", lambda payload: sent.append(payload)
    )
    assert ResendEmailDelivery(api_key="test", from_email="test@example.test").send_email(
        recipient="user@example.test", subject="Resumo", html="<p>Resumo</p>", text="Resumo"
    )
    assert sent[0]["html"] == "<p>Resumo</p>" and sent[0]["text"] == "Resumo"
