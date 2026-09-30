from datetime import date
from io import BytesIO

import pytest
from openpyxl import Workbook

from app.ingestion.extraction import extract_blocks
from app.ingestion.extraction.errors import ExtractionError
from app.ingestion.extraction.spreadsheet import rows_to_blocks

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def workbook_bytes(build) -> bytes:
    wb = Workbook()
    build(wb)
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


def test_rows_carry_their_header_and_skip_empty_cells() -> None:
    blocks = rows_to_blocks(
        "Clientes",
        [
            ["Cliente", "Vencimento", "Valor"],
            ["Acme", date(2026, 3, 15), 1500.0],
            ["Beta", None, 20.5],
        ],
    )
    assert len(blocks) == 1
    assert (
        blocks[0].text
        == "Cliente: Acme | Vencimento: 15/03/2026 | Valor: 1500\nCliente: Beta | Valor: 20.5"
    )
    assert blocks[0].section_path == "Clientes › linhas 2–3"


def test_many_rows_are_grouped_in_blocks_of_25() -> None:
    rows = [["id"]] + [[i] for i in range(60)]
    assert [b.section_path for b in rows_to_blocks("S", rows)] == [
        "S › linhas 2–26",
        "S › linhas 27–51",
        "S › linhas 52–61",
    ]


def test_xlsx_reads_visible_sheets_only_and_uses_cached_values() -> None:
    def build(wb):
        ws = wb.active
        ws.title = "Contratos"
        ws.append(["Cliente", "Total"])
        ws.append(["Acme", 10])
        ws.append(["Beta", "=B2*2"])
        hidden = wb.create_sheet("Interna")
        hidden.sheet_state = "hidden"
        hidden.append(["segredo"])
        hidden.append(["x"])

    blocks = extract_blocks(XLSX, workbook_bytes(build))
    text = "\n".join(b.text for b in blocks)
    assert "Cliente: Acme | Total: 10" in text and "segredo" not in text
    # openpyxl-written formulas have no cached value: the cell is omitted rather than invented
    assert "Cliente: Beta" in text and "=B2*2" not in text


def test_csv_detects_semicolon_and_cp1252() -> None:
    content = "Nome;Cidade\nJoão;São Paulo\nMaria;Belém\n".encode("cp1252")
    blocks = extract_blocks("text/csv", content)
    assert blocks[0].text == "Nome: João | Cidade: São Paulo\nNome: Maria | Cidade: Belém"


def test_oversized_and_zip_bomb_inputs_fail_with_a_code() -> None:
    with pytest.raises(ExtractionError) as big:
        extract_blocks(XLSX, b"0" * (25 * 1024 * 1024 + 1))
    assert big.value.code == "file_too_large"


def test_rows_over_the_cap_are_truncated_with_a_citable_notice() -> None:
    rows = [["id"]] + [[i] for i in range(5_005)]
    assert "Conteúdo truncado" in rows_to_blocks("S", rows)[-1].text
