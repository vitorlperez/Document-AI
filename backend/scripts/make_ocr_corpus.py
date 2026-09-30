"""Generate the synthetic PT-BR OCR corpus (no customer data). Needs Pillow (dev extra).

Usage: python -m scripts.make_ocr_corpus [--out tests/fixtures/ocr_pt]
Writes pdf/NN.pdf (image-only unless noted), truth/NN.txt (pages joined by form feed), questions.json.
"""

import argparse
import json
import random
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
]
SERIF = ["/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", "/System/Library/Fonts/Supplemental/Times New Roman.ttf"]
LOREM = [
    "O contrato de prestação de serviços foi assinado em 12/03/2025.",
    "A rescisão exige aviso prévio de trinta dias e notificação por escrito.",
    "O pagamento mensal será de R$ 1.234,56 até o quinto dia útil.",
    "A coordenação do órgão aprovou a inspeção do pêssego importado.",
]
ACCENTS = ["ação, coração, órgão, pêssego, ü", "nutrição, opinião, avô, língua, ônibus", "informação, café, você, saída, cônjuge"]
CONTRACT = [
    "CONTRATO Nº 042/2025",
    "Contratante: ACME Ltda, CNPJ 12.345.678/0001-90.",
    "Contratada: Maria Souza, CPF 123.456.789-09.",
    "Valor total: R$ 1.234,56 (mil duzentos e trinta e quatro reais).",
    "Vigência: 01/02/2025 a 31/01/2026. Foro: Comarca de São Paulo.",
]
TABLE = [["Item", "Qtd", "Preço", "Prazo", "Status", "Nota"]] + [
    [f"Peça {i}", str(i * 3), f"R$ {i * 10},50", f"{i + 5} dias", "ok", f"n{i}"] for i in range(1, 6)
]


def font(size, serif=False):
    for path in (SERIF if serif else FONTS) + FONTS:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    raise SystemExit("no TrueType font with pt-BR accents found")


def render(lines, *, dpi=300, size=26, serif=False, rotate=0.0, noise=0.0, columns=1):
    scale = dpi / 100
    width, height = int(600 * scale), int(400 * scale)
    image = Image.new("L", (width, height), 255)
    draw, f = ImageDraw.Draw(image), font(int(size * scale / 2 * 1.3), serif)
    step = int(f.size * 1.5)
    per_column = max(1, (height - 2 * step) // step)
    for index, line in enumerate(lines):
        column, row = divmod(index, per_column) if columns > 1 else (0, index)
        draw.text((step + column * width // columns, step + row * step), line, fill=0, font=f)
    if rotate:
        image = image.rotate(rotate, expand=False, fillcolor=255)
    if noise:
        rng = random.Random(7)
        pixels = image.load()
        for _ in range(int(width * height * noise)):
            x, y = rng.randrange(width), rng.randrange(height)
            pixels[x, y] = rng.choice((0, 255))
        image = image.filter(ImageFilter.GaussianBlur(0.6))
    return image


def image_pdf(images, dpi):
    out = BytesIO()
    images[0].save(out, "PDF", resolution=dpi, save_all=True, append_images=images[1:])
    return out.getvalue()


def text_layer_page(writer, text):
    page = writer.add_blank_page(width=300, height=200)
    fnt = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                            NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(fnt)})})
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode())
    page[NameObject("/Contents")] = writer._add_object(stream)


def build(out: Path):
    (out / "pdf").mkdir(parents=True, exist_ok=True)
    (out / "truth").mkdir(exist_ok=True)
    table_lines = [" | ".join(row) for row in TABLE]
    plain = [[*LOREM]]
    specs = {
        "01": (plain, dict(dpi=200)),
        "02": (plain, dict(dpi=100)),
        "03": (plain, dict(dpi=200, rotate=2.0)),
        "04": (plain, dict(dpi=200, noise=0.02)),
        "05": ([ACCENTS], dict(dpi=200)),
        "06": ([table_lines], dict(dpi=200)),
        "07": ([[*LOREM, *ACCENTS[:2]]], dict(dpi=200, columns=2)),
        "08": (plain, dict(dpi=200, size=18, serif=True)),
        "10": ([CONTRACT], dict(dpi=200)),
        "11": ([[f"Relatório interno - página {p}", *LOREM[:2], "Confidencial - uso interno"] for p in (1, 2)], dict(dpi=200)),
        "12": ([[]], dict(dpi=100)),
    }
    truths = {}
    for name, (pages, options) in specs.items():
        dpi = options.get("dpi", 200)
        images = [render(page, **options) for page in pages]
        (out / "pdf" / f"{name}.pdf").write_bytes(image_pdf(images, dpi))
        truths[name] = "\f".join("\n".join(page) for page in pages)
    # 09: mixed - pages 1 and 3 carry a real text layer (ASCII), page 2 is a scan.
    scanned = render(["Página escaneada da avaliação técnica de órgãos."], dpi=200)
    scan_reader_pdf = image_pdf([scanned], 200)
    from pypdf import PdfReader
    writer = PdfWriter()
    text_layer_page(writer, "Primeira pagina com texto digital")
    writer.add_page(PdfReader(BytesIO(scan_reader_pdf)).pages[0])
    text_layer_page(writer, "Terceira pagina com texto digital")
    buffer = BytesIO(); writer.write(buffer)
    (out / "pdf" / "09.pdf").write_bytes(buffer.getvalue())
    truths["09"] = "\f".join(["Primeira pagina com texto digital", "Página escaneada da avaliação técnica de órgãos.", "Terceira pagina com texto digital"])
    for name, text in truths.items():
        (out / "truth" / f"{name}.txt").write_text(text, encoding="utf-8")
    questions = []
    picks = {"01": LOREM, "05": ACCENTS, "10": CONTRACT, "03": LOREM[:2], "04": LOREM[:2], "11": LOREM[:2]}
    for doc, lines in picks.items():
        for line in lines:
            page = 1
            questions.append({"question": f"O que diz o documento {doc}: {line[:30]}?", "expected_doc": doc,
                              "expected_page": page, "expected_substring": line.split(",")[0].split(".")[0]})
    questions = questions[:30]
    questions.append({"question": "Qual a página escaneada da avaliação?", "expected_doc": "09",
                      "expected_page": 2, "expected_substring": "avaliação técnica"})
    (out / "questions.json").write_text(json.dumps(questions, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("tests/fixtures/ocr_pt"))
    build(parser.parse_args().out)
