PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
GOOGLE_DOC = "application/vnd.google-apps.document"
SHEETS = "application/vnd.google-apps.spreadsheet"
SLIDES = "application/vnd.google-apps.presentation"
GOOGLE_EXPORT_MIME = {GOOGLE_DOC: "text/plain", SHEETS: XLSX, SLIDES: PPTX}
EXTENSIONS = {
    "md": "text/markdown",
    "csv": "text/csv",
    "txt": "text/plain",
    "xlsx": XLSX,
    "pptx": PPTX,
    "pdf": PDF,
    "docx": DOCX,
}


def normalize_mime_type(name: str, mime_type: str) -> str:
    if mime_type in {"application/octet-stream", "text/plain", ""}:
        return EXTENSIONS.get(name.rsplit(".", 1)[-1].lower(), mime_type)
    return mime_type
