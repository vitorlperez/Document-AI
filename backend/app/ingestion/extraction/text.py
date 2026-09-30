import re

from app.ingestion.blocks import ExtractedBlock


def markdown_blocks(text: str) -> list[ExtractedBlock]:
    blocks: list[ExtractedBlock] = []
    headings: list[tuple[int, str]] = []
    current: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^(#{1,6})\s+(.+)$", line.strip())
        if match:
            if current:
                blocks.append(
                    ExtractedBlock(
                        "\n".join(current), section_path=" › ".join(name for _, name in headings)
                    )
                )
                current = []
            level, title = len(match.group(1)), match.group(2).strip()
            headings = [
                (prior_level, name) for prior_level, name in headings if prior_level < level
            ]
            headings.append((level, title))
        elif line.strip():
            current.append(line)
        elif current:
            blocks.append(
                ExtractedBlock(
                    "\n".join(current),
                    section_path=" › ".join(name for _, name in headings) or None,
                )
            )
            current = []
    if current:
        blocks.append(
            ExtractedBlock(
                "\n".join(current), section_path=" › ".join(name for _, name in headings) or None
            )
        )
    return blocks


def decode_text(content: bytes) -> str:
    if content.startswith((b"\xff\xfe", b"\xfe\xff")):
        return content.decode("utf-16", errors="replace")
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("cp1252", errors="replace")


def markdown_blocks_from_bytes(content: bytes) -> list[ExtractedBlock]:
    return markdown_blocks(decode_text(content))


def google_doc_blocks(content: bytes) -> list[ExtractedBlock]:
    return [ExtractedBlock(paragraph) for paragraph in decode_text(content).splitlines()]


def text_plain_blocks(content: bytes) -> list[ExtractedBlock]:
    return [
        ExtractedBlock(p.strip()) for p in re.split(r"\n\s*\n", decode_text(content)) if p.strip()
    ]
