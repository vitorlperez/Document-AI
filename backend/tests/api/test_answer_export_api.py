import io
from uuid import uuid4

from docx import Document as DocxDocument
from pypdf import PdfReader

from app.knowledge.export import ExportSource, parse_blocks, to_markdown
from tests.api.test_answer_feedback_api import transcript
from tests.api.test_multiscope_questions_api import ask, corpus  # noqa: F401
from tests.api.test_text_search_api import login, search_api  # noqa: F401


def test_markdown_export_keeps_citations_and_lists_numbered_sources() -> None:
    text = to_markdown("Prazos", "| Arquivo | Prazo |\n| --- | --- |\n| A.pdf | 30 dias [1] |",
                       [ExportSource("A.pdf", "https://drive.example.test/a")])
    assert "30 dias [1]" in text
    assert text.rstrip().endswith("1. A.pdf — https://drive.example.test/a")


def test_parse_blocks_reads_headings_bullets_tables_and_strips_formatting() -> None:
    kinds = [b.kind for b in parse_blocks("## Título\n- **item** [1]\n\n| a | b |\n|---|---|\n| 1 | 2 |\ntexto")]
    assert kinds == ["heading", "bullet", "table", "paragraph"]
    [table] = [b for b in parse_blocks("| a | b |\n|---|---|\n| 1 | 2 |") if b.kind == "table"]
    assert table.rows == (("a", "b"), ("1", "2"))


def test_export_endpoint_returns_md_docx_pdf_with_sources_and_guards_access(corpus):  # noqa: F811 - imported pytest fixture
    client, _, _, org, _, _ = corpus
    conv = ask(client, org, scope='organization').json()['conversation_id']
    messages = transcript(client, org, conv)
    msg = messages[-1]
    base = f'/organizations/{org}/conversations/{conv}/messages/{msg["id"]}/export'

    markdown = client.get(base, params={'format': 'md'})
    assert markdown.status_code == 200 and 'attachment' in markdown.headers['content-disposition']
    assert msg['content'].strip() in markdown.text
    docx = client.get(base, params={'format': 'docx'})
    assert docx.status_code == 200
    assert msg['content'].split()[0] in "\n".join(p.text for p in DocxDocument(io.BytesIO(docx.content)).paragraphs)
    pdf = client.get(base, params={'format': 'pdf'})
    assert pdf.status_code == 200 and pdf.content.startswith(b'%PDF')
    assert len(PdfReader(io.BytesIO(pdf.content)).pages) >= 1

    assert client.get(base, params={'format': 'exe'}).status_code == 422
    other = f'/organizations/{org}/conversations/{conv}/messages/{messages[0]["id"]}/export'
    assert client.get(other).status_code == 404  # user messages are not exportable
    assert client.get(f'/organizations/{org}/conversations/{conv}/messages/{uuid4()}/export').status_code == 404
    assert client.get(f'/organizations/{uuid4()}/conversations/{conv}/messages/{msg["id"]}/export').status_code == 404
