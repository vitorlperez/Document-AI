"""Safe, bounded HTML and text alternatives for automation result e-mails."""

import html
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlencode, urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

PRODUCTION_URL = "https://www.arquivio.com.br"
LOGO_URL = f"{PRODUCTION_URL}/arquivio-logo-120.png"
SUMMARY_CHARS = 1600
SUMMARY_PARAGRAPHS = 3
SOURCE_LIMIT = 4


@dataclass(frozen=True)
class EmailContent:
    html: str
    text: str


def safe_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme in {"http", "https"}
            and parsed.hostname
            and not parsed.username
            and not parsed.password
        ):
            return value if not any(ord(char) < 32 for char in value) else ""
    except ValueError:
        pass
    return ""


def summary_paragraphs(answer: str) -> list[str]:
    # Bound before splitting; documents never get to supply HTML or remote images.
    bounded = answer[:SUMMARY_CHARS]
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", bounded) if part.strip()][
        :SUMMARY_PARAGRAPHS
    ]
    if paragraphs and (
        len(answer) > SUMMARY_CHARS or len(re.split(r"\n\s*\n", bounded)) > SUMMARY_PARAGRAPHS
    ):
        paragraphs[-1] = paragraphs[-1].rstrip(".!?… ") + "…"
    return paragraphs or ["O relatório completo está disponível no app."]


def paragraph_html(value: str) -> str:
    escaped = html.escape(value)
    # Only these formatting tokens become markup, after escaping all input.
    escaped = re.sub(r"\*\*([^*\n]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"^#{1,6}\s+", "", escaped, flags=re.MULTILINE)
    return escaped.replace("\n", "<br>")


def render_automation_email(
    *,
    name: str,
    answer: str,
    folders: list[str],
    completed_at: datetime,
    timezone: str,
    citations: list[dict[str, object]],
    organization_id: UUID,
    automation_id: UUID,
    run_id: UUID,
    app_url: str,
    pdf_available: bool,
) -> EmailContent:
    base = (safe_url(app_url) or PRODUCTION_URL).rstrip("/")
    page = f"{base}/companies/{organization_id}/automations"
    report_url = page + "?" + urlencode({"automation": str(automation_id), "run": str(run_id)})
    edit_url = page + "?" + urlencode({"automation": str(automation_id), "edit": "1"})
    pdf_url = (
        f"{base}/api/organizations/{organization_id}/automations/{automation_id}/runs/{run_id}/pdf"
    )
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        timezone = "America/Sao_Paulo"
        zone = ZoneInfo(timezone)
    completed = (
        completed_at if completed_at.tzinfo else completed_at.replace(tzinfo=UTC)
    ).astimezone(zone)
    date = completed.strftime("%d/%m/%Y às %H:%M") + f" ({timezone})"
    folder_label = " · ".join(folders) if folders else "Pastas selecionadas na automação"
    paragraphs = summary_paragraphs(answer)
    sources = []
    seen = set()
    for citation in citations:
        key = str(citation.get("document_id") or citation.get("document_name") or "Documento")
        if key not in seen:
            seen.add(key)
            sources.append(citation)
    source_items, source_text = [], []
    for citation in sources[:SOURCE_LIMIT]:
        label = str(citation.get("document_name") or "Documento")[:200]
        url = safe_url(str(citation.get("source_url") or ""))
        source_items.append(
            '<li style="margin:0 0 8px;">'
            + (
                f'<a href="{html.escape(url)}" style="color:#245b45;text-decoration:underline;">{html.escape(label)}</a>'
                if url
                else html.escape(label)
            )
            + "</li>"
        )
        source_text.append(f"- {label}" + (f": {url}" if url else ""))
    more = (
        f"Mais {len(sources) - SOURCE_LIMIT} fonte{'s' if len(sources) - SOURCE_LIMIT > 1 else ''} no relatório completo."
        if len(sources) > SOURCE_LIMIT
        else ""
    )
    sources_html = (
        (
            '<h2 style="font-size:14px;margin:24px 0 12px;">Fontes consultadas</h2>'
            '<ul style="margin:0;padding-left:20px;font-size:14px;line-height:22px;">'
            + "".join(source_items)
            + "</ul>"
            + (f'<p style="font-size:13px;">{more}</p>' if more else "")
        )
        if sources
        else ""
    )
    summary_html = "".join(
        f'<p style="margin:0 0 16px;font-size:16px;line-height:26px;">{paragraph_html(p)}</p>'
        for p in paragraphs
    )
    pdf_html = (
        f'<p style="margin:18px 0 0;"><a href="{html.escape(pdf_url)}" style="color:#245b45;font-size:14px;text-decoration:underline;">Baixar PDF</a></p>'
        if pdf_available
        else ""
    )
    footer = (
        "Você recebeu este e-mail porque é o criador ou um destinatário desta automação. "
        "Para deixar de receber, abra o sino de Notificações no app e desmarque “Receber também por e-mail”. "
        "O criador ou um administrador também pode editar os destinatários e a entrega da automação."
    )
    markup = f'''<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark"><meta name="supported-color-schemes" content="light dark">
<title>Relatório da automação</title><style>
@media (prefers-color-scheme:dark) {{ .email-bg {{background:#18231f!important;}} .email-card {{background:#24342c!important;color:#f1f5f2!important;}} .email-muted {{color:#c5d4cb!important;}} .email-card a:not(.email-button), .email-wordmark {{color:#b9dcc7!important;}} }}
@media only screen and (max-width:620px) {{ .email-padding {{padding:24px 20px!important;}} }}
</style></head><body class="email-bg" style="margin:0;padding:0;background:#edf2ee;font-family:Arial,Helvetica,sans-serif;color:#203c2e;">
<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;">Sua automação foi concluída. Confira o resumo e as fontes do relatório.</div>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" class="email-bg" style="background:#edf2ee;"><tr><td align="center" style="padding:28px 12px;">
<!--[if mso]><table role="presentation" width="600"><tr><td><![endif]-->
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" class="email-card" style="max-width:600px;background:#ffffff;border:1px solid #dce6df;border-radius:12px;color:#203c2e;table-layout:fixed;">
<tr><td class="email-padding" style="padding:30px 36px 24px;border-bottom:1px solid #dce6df;">
<a href="{html.escape(base)}" style="text-decoration:none;"><img src="{LOGO_URL}" width="48" height="48" alt="ArquivIO" style="display:inline-block;vertical-align:middle;border:0;width:48px;height:48px;background:#ffffff;border-radius:8px;"><span class="email-wordmark" style="display:inline-block;vertical-align:middle;margin-left:12px;color:#245b45;font-size:28px;font-weight:bold;letter-spacing:-1px;">arquivio.</span></a>
<p class="email-muted" style="margin:22px 0 8px;color:#52695c;font-size:12px;letter-spacing:1px;font-weight:bold;">AUTOMAÇÃO CONCLUÍDA</p>
<h1 style="margin:0;font-size:25px;line-height:33px;overflow-wrap:anywhere;word-wrap:break-word;">{html.escape(name)}</h1>
<p class="email-muted" style="margin:16px 0 8px;color:#52695c;font-size:14px;line-height:22px;overflow-wrap:anywhere;"><strong>Pasta{"s" if len(folders) > 1 else ""}:</strong> {html.escape(folder_label)}</p>
<p class="email-muted" style="margin:0;color:#52695c;font-size:13px;line-height:21px;">Concluída em {html.escape(date)}</p></td></tr>
<tr><td class="email-padding" style="padding:28px 36px;overflow-wrap:anywhere;word-wrap:break-word;">
<h2 style="margin:0 0 18px;font-size:18px;line-height:26px;">Resumo do relatório</h2>{summary_html}{sources_html}
<table role="presentation" cellspacing="0" cellpadding="0" border="0" style="margin-top:28px;"><tr><td bgcolor="#245b45" style="background:#245b45;border-radius:6px;mso-padding-alt:14px 20px;">
<a class="email-button" href="{html.escape(report_url)}" style="display:inline-block;padding:14px 20px;color:#ffffff;background:#245b45;border:1px solid #245b45;border-radius:6px;font-size:15px;font-weight:bold;text-decoration:none;line-height:22px;">Ver relatório completo</a>
</td></tr></table>{pdf_html}<p class="email-muted" style="margin:18px 0 0;color:#52695c;font-size:12px;line-height:19px;">Os links exigem acesso à sua conta e às pastas desta automação.</p></td></tr>
<tr><td class="email-padding email-muted" style="padding:24px 36px;border-top:1px solid #dce6df;color:#52695c;font-size:12px;line-height:20px;">
<p style="margin:0 0 12px;">{html.escape(footer)}</p><a href="{html.escape(edit_url)}" style="color:#245b45;text-decoration:underline;">Editar automação</a> · <a href="{html.escape(page)}" style="color:#245b45;text-decoration:underline;">Abrir app e gerenciar e-mails</a>
<p style="margin:16px 0 0;">ArquivIO · Seus documentos, mais claros.</p></td></tr></table>
<!--[if mso]></td></tr></table><![endif]-->
</td></tr></table></body></html>'''
    text = "\n\n".join(
        [
            "ArquivIO · Automação concluída",
            name,
            f"Pastas: {folder_label}",
            f"Concluída em {date}",
            "Resumo do relatório",
            *paragraphs,
            "Fontes consultadas:\n" + "\n".join(source_text) + ("\n" + more if more else "")
            if sources
            else "",
            f"Ver relatório completo: {report_url}",
            f"Baixar PDF: {pdf_url}" if pdf_available else "",
            "Os links exigem acesso à sua conta e às pastas desta automação.",
            footer,
            f"Editar automação: {edit_url}",
            f"Abrir app e gerenciar e-mails: {page}",
        ]
    )
    return EmailContent(html=markup, text=text)
