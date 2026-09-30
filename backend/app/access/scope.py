"""Confine every programmatic query to the credential's organization (and optional folders)."""

from uuid import UUID

from sqlalchemy.orm import Session

from app.access.principal import Principal
from app.library.service import LibraryService, QuestionSelection


class ScopedAccess:
    def __init__(self, session: Session, principal: Principal):
        self.session, self.principal = session, principal
        self._library = LibraryService(session)

    def providers(self) -> list[str]:
        found = self._library.source_providers(scope=self.principal.scope, user_id=self.principal.user_id)
        return sorted({"google_drive" if item == "google" else item for item in found.values()})

    def mentions(self, requested_ids: list[UUID] | None) -> list[tuple[str, UUID]]:
        root_ids = list(self.principal.node_ids) if self.principal.node_ids else None
        if root_ids is None and not requested_ids:
            return []
        return self._library.authorize_mentions(
            scope=self.principal.scope, user_id=self.principal.user_id,
            root_ids=root_ids, requested_ids=list(requested_ids or []),
        )

    def selection(self, requested_ids: list[UUID] | None) -> QuestionSelection | None:
        """None when nothing is eligible (no ready folder, or the selection has no indexed content)."""
        # Authorize all nodes first: unavailable content must never hide a foreign node.
        mentions, providers = self.mentions(requested_ids), self.providers()
        selections = []
        for group in ([[mention] for mention in mentions] if mentions else [[]]):
            try:
                selection = self._library.resolve_question_selection(
                    scope=self.principal.scope, user_id=self.principal.user_id,
                    providers=providers, mentions=group,
                )
            except ValueError:  # An authorized root has no indexed content yet.
                continue
            if selection.folder_ids:
                selections.append(selection)
        if not selections:
            return None
        return QuestionSelection(
            list(dict.fromkeys(folder for item in selections for folder in item.folder_ids)),
            None if not mentions else set().union(*(item.document_ids or set() for item in selections)),
            selections[0].coverage,
            [node for item in selections for node in item.accepted_node_ids],
        )
