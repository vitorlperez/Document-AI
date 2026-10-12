"""Branded PDF for one automation run, rendered on demand from the stored result JSON (no file is persisted).

The chat export keeps using ``knowledge.export.to_pdf``; this report adds the ArquivIO header (logo, automation,
folder, run time, trigger), styled Markdown, a numbered sources section and a page footer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.knowledge.export import _CELL_SEPARATOR, plain
from app.knowledge.untrusted import sanitize_label, strip_invisible

LOGO = Path(__file__).parent / "assets" / "arquivio-logo.png"  # copy of frontend/public/arquivio-logo-120.png
DEFAULT_TIMEZONE = "America/Sao_Paulo"
# Frontend tokens (frontend/app/globals.css, light theme)
BRAND = (0x24, 0x5B, 0x45)  # wordmark colour, same as the e-mail header
PRIMARY, PRIMARY_DARK = (0x1C, 0x60, 0x52), (0x12, 0x4B, 0x3F)
INK, MUTED_INK = (0x24, 0x3B, 0x35), (0x65, 0x70, 0x69)
BORDER, SURFACE, PAPER = (0xDE, 0xDF, 0xD5), (0xF5, 0xF5, 0xF5), (0xFA, 0xF9, 0xF5)
WHITE = (255, 255, 255)
_INLINE_BOLD = re.compile(r"\*\*(.+?)\*\*")
_INLINE_ITALIC = re.compile(r"(?<![*\w])\*(?!\s)([^*]+?)\*(?![*\w])")
_INLINE_CODE = re.compile(r"`([^`]+)`")
_ORDERED = re.compile(r"^(\d+)[.)]\s+(.*)$")
_BULLET = re.compile(r"^[-*+]\s+(.*)$")
_WEEKDAYS = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")


@dataclass(frozen=True)
class ReportSource:
    name: str
    url: str = ""
    excerpt: str = ""
    page: int | None = None


@dataclass(frozen=True)
class ReportMeta:
    automation_name: str
    folders: tuple[str, ...]
    executed_at: datetime | None
    trigger: str
    timezone: str = DEFAULT_TIMEZONE
    documents_considered: int | None = None


def trigger_label(trigger_kind: str, trigger_config: dict[str, object] | None, trigger_ref: str) -> str:
    if trigger_ref.startswith("manual:"):
        return "Execução manual"
    if trigger_kind == "folder_changed" or trigger_ref.startswith("folder:"):
        return "Mudança na pasta"
    config = trigger_config or {}
    frequency = {"daily": "diário", "weekly": "semanal", "monthly": "mensal"}.get(str(config.get("frequency")), "")
    hour = config.get("hour")
    parts = ["Agendada"] + ([frequency] if frequency else [])
    weekday = config.get("weekday")
    if config.get("frequency") == "weekly" and isinstance(weekday, int) and 0 <= weekday <= 6:
        parts.append(f"({_WEEKDAYS[weekday]})")
    if isinstance(hour, int) and not isinstance(hour, bool):
        parts.append(f"às {hour:02d}h")
    return " ".join(parts)


def _text(value: str) -> str:
    """Core PDF fonts are Latin-1: keep Portuguese intact, map the common typographic marks, replace the rest."""
    value = strip_invisible(value)
    for source, target in {"—": "-", "–": "-", "“": '"', "”": '"', "‘": "'", "’": "'", "…": "...", "•": "-",
                           "→": "->", " ": " "}.items():
        value = value.replace(source, target)
    return value.encode("latin-1", "replace").decode("latin-1")


def _inline(value: str) -> str:
    """Markdown inline subset -> fpdf markdown (**bold**, __italic__); code loses its backticks."""
    value = _INLINE_CODE.sub(r"\1", strip_invisible(value))
    value = _INLINE_ITALIC.sub(r"__\1__", value)
    return _text(value.replace("--", "- -"))  # fpdf reads -- as underline


def _blocks(answer: str) -> list[tuple[str, object]]:
    out: list[tuple[str, object]] = []
    lines = answer.splitlines()
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        i += 1
        if not stripped or stripped == ":::" or re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            continue
        if stripped.startswith("::: file "):
            out.append(("heading", (3, plain(stripped[9:]))))
        elif match := re.match(r"^(#{1,4})\s+(.*)$", stripped):
            out.append(("heading", (len(match.group(1)), plain(match.group(2)))))
        elif stripped.startswith("|"):
            rows = [stripped]
            while i < len(lines) and lines[i].strip().startswith("|"):
                if not _CELL_SEPARATOR.match(lines[i]):
                    rows.append(lines[i].strip())
                i += 1
            out.append(("table", [[cell.strip() for cell in row.strip("|").split("|")] for row in rows]))
        elif stripped.startswith(">"):
            out.append(("quote", stripped.lstrip("> ").strip()))
        elif match := _ORDERED.match(stripped):
            out.append(("ordered", (match.group(1), match.group(2))))
        elif match := _BULLET.match(stripped):
            out.append(("bullet", match.group(1)))
        else:
            out.append(("paragraph", stripped))
    return out


def _format_when(moment: datetime | None, zone: str) -> str:
    if moment is None:
        return "-"
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    try:
        local = moment.astimezone(ZoneInfo(zone))
    except Exception:  # noqa: BLE001 - unknown zone falls back to UTC
        local = moment.astimezone(UTC)
    return local.strftime("%d/%m/%Y às %H:%M") + f" ({local.tzname()})"


def to_report_pdf(meta: ReportMeta, answer: str, sources: list[ReportSource]) -> bytes:
    from fpdf import FPDF, FontFace
    from fpdf.enums import TableCellFillMode, XPos, YPos

    title = sanitize_label(meta.automation_name)[:120] or "Automação"

    class Report(FPDF):
        def header(self) -> None:
            if self.page_no() == 1:
                return
            self.image(str(LOGO), x=self.l_margin, y=8.5, w=7)
            self.set_xy(self.l_margin + 9, 9)
            self.set_font("Helvetica", "B", 12)
            self.set_text_color(*BRAND)
            self.cell(30, 6, "arquivio.")
            self.set_font("Helvetica", "", 9)
            self.set_text_color(*MUTED_INK)
            self.cell(0, 6, _text(title), align="R")
            self.set_draw_color(*BORDER)
            self.line(self.l_margin, 17, self.w - self.r_margin, 17)
            self.set_y(22)

        def footer(self) -> None:
            self.set_y(-14)
            self.set_draw_color(*BORDER)
            self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
            self.set_y(-12)
            self.set_font("Helvetica", "", 8)
            self.set_text_color(*MUTED_INK)
            self.cell(0, 5, "Gerado por ArquivIO", align="L")
            self.set_x(self.l_margin)
            self.cell(0, 5, f"Página {self.page_no()} de {{nb}}", align="R")

    pdf = Report(format="A4")
    pdf.set_margins(20, 18, 20)
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.alias_nb_pages("{nb}")
    pdf.set_title(_text(title))
    pdf.set_creator("ArquivIO")
    pdf.add_page()
    width = pdf.w - pdf.l_margin - pdf.r_margin

    def para(text: str, *, size: float = 10.5, style: str = "", color=INK, indent: float = 0, line: float = 5.6,
             after: float = 2.2, width_: float | None = None) -> None:
        pdf.set_font("Helvetica", style, size)
        pdf.set_text_color(*color)
        pdf.set_x(pdf.l_margin + indent)
        pdf.multi_cell((width_ if width_ is not None else width) - indent, line, _inline(text), markdown=True,
                       new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(after)

    # --- cover header ---
    top = pdf.get_y()
    pdf.image(str(LOGO), x=pdf.l_margin, y=top, w=13)
    pdf.set_xy(pdf.l_margin + 16, top + 1.5)
    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(*BRAND)
    pdf.cell(60, 7, "arquivio.", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_x(pdf.l_margin + 16)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*MUTED_INK)
    pdf.cell(0, 4.5, "Relatório de automação")
    pdf.set_y(top + 18)
    pdf.set_draw_color(*PRIMARY)
    pdf.set_line_width(0.6)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.set_line_width(0.2)
    pdf.ln(6)
    pdf.set_font("Helvetica", "B", 21)
    pdf.set_text_color(*INK)
    pdf.multi_cell(0, 9, _text(title), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)

    folders = [sanitize_label(item) for item in meta.folders] or ["-"]
    rows = [("Pasta", "\n".join(folders)), ("Executado em", _format_when(meta.executed_at, meta.timezone)),
            ("Gatilho", meta.trigger)]
    if meta.documents_considered:
        rows.append(("Documentos", f"{meta.documents_considered} analisados"))
    label_w = 40
    pdf.set_font("Helvetica", "", 9.5)
    heights = [max(len(value.split("\n")), 1) * 5.2 + 3 for _, value in rows]
    pdf.set_fill_color(*PAPER)
    pdf.set_draw_color(*BORDER)
    box_top = pdf.get_y()
    pdf.rect(pdf.l_margin, box_top, width, sum(heights), style="DF")
    pdf.set_fill_color(*PRIMARY)
    pdf.rect(pdf.l_margin, box_top, 1.4, sum(heights), style="F")
    y = box_top
    for (label, value), height in zip(rows, heights, strict=True):
        pdf.set_xy(pdf.l_margin + 5, y + 1.5)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*MUTED_INK)
        pdf.cell(label_w, 5.2, _text(label.upper()))
        pdf.set_font("Helvetica", "", 9.5)
        pdf.set_text_color(*INK)
        pdf.set_xy(pdf.l_margin + 5 + label_w, y + 1.5)
        pdf.multi_cell(width - label_w - 8, 5.2, _text(value), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        y += height
    pdf.set_y(box_top + sum(heights) + 8)

    # --- body ---
    sizes = {1: 15, 2: 13, 3: 11.5, 4: 10.5}
    for kind, value in _blocks(answer):
        if kind == "heading":
            level, text = value  # type: ignore[misc]
            if pdf.get_y() > pdf.h - 45:
                pdf.add_page()
            pdf.ln(3 if level > 1 else 4)
            para(text, size=sizes.get(level, 10.5), style="B", color=PRIMARY_DARK if level <= 2 else INK, after=1.5,
                 line=sizes.get(level, 10.5) * 0.5)
            if level <= 2:
                pdf.set_draw_color(*BORDER)
                pdf.line(pdf.l_margin, pdf.get_y() - 1, pdf.w - pdf.r_margin, pdf.get_y() - 1)
                pdf.ln(1.5)
        elif kind in ("bullet", "ordered"):
            number, text = value if kind == "ordered" else (None, value)  # type: ignore[misc]
            y0 = pdf.get_y()
            if y0 > pdf.h - 30:
                pdf.add_page()
                y0 = pdf.get_y()
            if number is None:
                pdf.set_fill_color(*PRIMARY)
                pdf.ellipse(pdf.l_margin + 2, y0 + 2.1, 1.6, 1.6, style="F")
            else:
                pdf.set_xy(pdf.l_margin, y0)
                pdf.set_font("Helvetica", "B", 10.5)
                pdf.set_text_color(*PRIMARY)
                pdf.cell(7, 5.6, f"{number}.", align="R")
            para(text, indent=8, after=1.2)
        elif kind == "quote":
            pdf.ln(2)
            y0 = pdf.get_y()
            para(value, indent=6, style="", color=MUTED_INK, after=2.5)  # type: ignore[arg-type]
            pdf.set_draw_color(*PRIMARY)
            pdf.set_line_width(0.7)
            pdf.line(pdf.l_margin + 1.5, y0, pdf.l_margin + 1.5, pdf.get_y() - 2.5)
            pdf.set_line_width(0.2)
        elif kind == "table":
            table_rows: list[list[str]] = value  # type: ignore[assignment]
            columns = max(len(row) for row in table_rows)
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*INK)
            pdf.set_draw_color(*BORDER)
            pdf.set_fill_color(*SURFACE)
            with pdf.table(first_row_as_headings=True, text_align="LEFT", borders_layout="HORIZONTAL_LINES",
                           cell_fill_color=SURFACE, cell_fill_mode=TableCellFillMode.ROWS, line_height=5.4,
                           headings_style=FontFace(emphasis="BOLD", color=WHITE, fill_color=PRIMARY),
                           padding=1.8) as table:
                for row in table_rows:
                    cells = table.row()
                    for index in range(columns):
                        cells.cell(_inline(row[index]) if index < len(row) else "")
            pdf.ln(4)
        else:
            para(value)  # type: ignore[arg-type]

    # --- sources ---
    if sources:
        if pdf.get_y() > pdf.h - 60:
            pdf.add_page()
        pdf.ln(5)
        para("Fontes", size=15, style="B", color=PRIMARY_DARK, after=1.5, line=7.5)
        pdf.set_draw_color(*PRIMARY)
        pdf.line(pdf.l_margin, pdf.get_y() - 1, pdf.w - pdf.r_margin, pdf.get_y() - 1)
        pdf.ln(3)
        for number, source in enumerate(sources, 1):
            excerpt = " ".join(source.excerpt.split())
            est = 8 + (len(excerpt) // 85 + 1) * 4.4 + (4.4 if source.url else 0)
            if pdf.get_y() + est > pdf.h - 22:
                pdf.add_page()
            y0 = pdf.get_y()
            pdf.set_fill_color(*PRIMARY)
            pdf.rect(pdf.l_margin, y0, 6.5, 6.5, style="F", round_corners=True, corner_radius=1.2)
            pdf.set_xy(pdf.l_margin, y0 + 0.9)
            pdf.set_font("Helvetica", "B", 8.5)
            pdf.set_text_color(*WHITE)
            pdf.cell(6.5, 4.7, str(number), align="C")
            pdf.set_xy(pdf.l_margin + 9, y0)
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(*INK)
            pdf.multi_cell(width - 9, 5, _text(sanitize_label(source.name) + (f"  (p. {source.page})" if source.page else "")),
                           new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            if excerpt:
                para(f"“{excerpt}”", size=9, style="I", color=MUTED_INK, indent=9, line=4.4, after=0.5)
            if source.url:
                pdf.set_x(pdf.l_margin + 9)
                pdf.set_font("Helvetica", "", 8)
                pdf.set_text_color(*PRIMARY)
                pdf.cell(width - 9, 4.2, _text(source.url[:110]), link=source.url, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(3.5)
    return bytes(pdf.output())
