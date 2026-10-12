from datetime import UTC, datetime
from io import BytesIO

from pypdf import PdfReader

from app.automations.report_pdf import LOGO, ReportMeta, ReportSource, to_report_pdf, trigger_label

ANSWER = """## Resumo
A receita cresceu **12%** [1].

- Item um
1. Passo

| Área | Valor |
|---|---|
| A | 1 |

> Atenção
"""


def test_trigger_labels():
    assert trigger_label("schedule", {}, "manual:abc") == "Execução manual"
    assert trigger_label("folder_changed", {}, "folder:x") == "Mudança na pasta"
    assert trigger_label("schedule", {"frequency": "weekly", "weekday": 0, "hour": 8}, "schedule:x") == \
        "Agendada semanal (segunda) às 08h"


def test_report_pdf_has_header_sources_and_footer():
    assert LOGO.is_file()
    meta = ReportMeta("Relatório semanal", ("Drive/Financeiro",), datetime(2026, 10, 12, 11, 30, tzinfo=UTC),
                      "Execução manual", documents_considered=3)
    sources = [ReportSource("Contrato.pdf", "https://x.test/a", "Trecho citado do contrato", 4), ReportSource("Planilha.xlsx")]
    reader = PdfReader(BytesIO(to_report_pdf(meta, ANSWER, sources)))
    text = "\n".join(page.extract_text() for page in reader.pages)
    for expected in ("arquivio.", "ArquivIO", "Relatório semanal", "Drive/Financeiro", "12/10/2026 às 08:30", "Execução manual",
                     "Resumo", "Fontes", "Contrato.pdf", "Trecho citado", "Planilha.xlsx", "Gerado por ArquivIO", "Página 1 de 1"):
        assert expected in text
    assert len(reader.pages[0].images) >= 1


def test_report_pdf_paginates_long_answers():
    meta = ReportMeta("Longo", (), None, "Execução manual")
    answer = "\n\n".join(f"Parágrafo {n} " + "texto " * 60 for n in range(40))
    reader = PdfReader(BytesIO(to_report_pdf(meta, answer, [])))
    assert len(reader.pages) > 1 and f"Página 2 de {len(reader.pages)}" in reader.pages[1].extract_text()
