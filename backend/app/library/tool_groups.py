"""Provider → "ferramenta" (tool group) que o usuário enxerga.

``google_drive`` (OAuth) e ``google_drive_sa`` (pasta compartilhada) continuam sendo providers distintos no
backend, mas para escopo de perguntas, filtros, menções e rótulos são a mesma ferramenta: "Google Drive".
"""
from collections.abc import Iterable

GOOGLE_DRIVE_TOOL = "google_drive"
GOOGLE_DRIVE_ALIASES = frozenset({"google", "google_drive", "google_drive_sa"})

_LABELS = {
    "google_drive": "Google Drive", "onedrive": "OneDrive", "sharepoint": "SharePoint",
    "notion": "Notion", "clickup": "ClickUp",
}


def tool_group(provider: str | None) -> str | None:
    return GOOGLE_DRIVE_TOOL if provider in GOOGLE_DRIVE_ALIASES else provider


def tool_groups(providers: Iterable[str | None]) -> set[str]:
    return {group for group in (tool_group(item) for item in providers) if group is not None}


def provider_label(provider: str | None) -> str:
    group = tool_group(provider) or ""
    return _LABELS.get(group, group.replace("_", " ").title())


LEGACY_SHARED_ROOT_NAME = "Google Drive (pasta compartilhada)"


def display_node_name(kind: str, name: str) -> str:
    """Raízes antigas da conexão por pasta compartilhada ainda gravadas com o nome antigo aparecem como 'Google Drive'."""
    return provider_label("google_drive") if kind == "source" and name == LEGACY_SHARED_ROOT_NAME else name
