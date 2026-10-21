"""Impact preview and purge of derived content after access is withdrawn (ADR-0021 §8.3-§8.4).

Reads hide immediately (``derived_visibility``); this module computes what a removal would hide *before* it
happens and, ≥ 24 h after the loss, physically replaces the hidden content with tombstones. Everything is
idempotent: a second pass over the same data changes nothing.
"""
from collections.abc import Collection, Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_usage.models import SavedQuery
from app.automations.models import Automation, AutomationRun
from app.automations.scope import legacy_folder_ids, scope_node_ids
from app.automations.space_access import (
    hidden_result,
    pause_automations_for_lost_access,
    run_provenance,
    runs_visibility,
)
from app.core.scoping import OrganizationScope
from app.ingestion.service import SyncAccessDenied
from app.knowledge.derived_visibility import (
    HIDDEN_NOTICE,
    Provenance,
    answer_provenance,
    build_index,
    hidden_response,
)
from app.knowledge.models import Conversation, ConversationMessage
from app.library.service import LibraryService
from app.notifications.followed import clear_followed_state_for_lost_access
from app.notifications.models import Notification
from app.notifications.visibility import CONTENT_KINDS, hidden_data, notifications_visibility
from app.spaces.access import SpaceAccess, SpaceAccessResolver
from app.spaces.models import Space, SpaceFolderGrant, SpaceMember

PURGE_GRACE = timedelta(hours=24)
PURGE_LOOKBACK = timedelta(days=30)  # losses older than this were purged by an earlier daily pass
MESSAGE_SCAN_LIMIT = 5000
_BATCH = 500
ZERO_PURGE = {"followed": 0, "automations_paused": 0, "notifications": 0, "messages": 0, "runs": 0}


def lost_node_ids(access: SpaceAccess, space_id: UUID | None) -> set[UUID]:
    """Granted library folders the person reads ONLY through ``space_id`` (their other Spaces do not grant them)."""
    if space_id is None:
        return set()
    return {node for node, spaces in access.node_grants.items() if spaces <= {space_id}}


def _after(access: SpaceAccess, lost: set[UUID], lost_nodes: Collection[UUID] = ()) -> SpaceAccess:
    """What the person still reads once ``lost`` scopes and ``lost_nodes`` granted folders are gone."""
    return SpaceAccess(access.organization_id, access.user_id, {},
                       {folder: frozenset() for folder in access.folder_ids - lost},
                       node_grants={node: spaces for node, spaces in access.node_grants.items()
                                    if node not in set(lost_nodes)})


def _messages(session: Session, organization_id: UUID, user_id: UUID, limit: int | None = None) -> Iterator[list[ConversationMessage]]:
    query = (select(ConversationMessage).join(Conversation, Conversation.id == ConversationMessage.conversation_id)
             .where(Conversation.organization_id == organization_id, Conversation.user_id == user_id,
                    ConversationMessage.role == "assistant").order_by(ConversationMessage.created_at.desc(), ConversationMessage.id))
    if limit:
        query = query.limit(limit)
    rows = list(session.scalars(query))
    for start in range(0, len(rows), _BATCH):
        yield rows[start:start + _BATCH]


def _automation_folders(session: Session, scope: OrganizationScope, user_id: UUID, automation: Automation) -> set[UUID]:
    folders = set(legacy_folder_ids(automation.scope))
    library = LibraryService(session)
    for node_id in scope_node_ids(automation.scope):
        try:
            folders |= {item.workspace_folder_id for item in library.indexed_documents_under(
                scope=scope, user_id=user_id, node_id=node_id, system_view=True)}
        except SyncAccessDenied:
            continue
    return folders


def _automation_loses_nodes(
    session: Session, scope: OrganizationScope, user_id: UUID, automation: Automation, after: SpaceAccess
) -> bool:
    """A node-scoped automation stops when some document it reads is no longer readable once the grants are gone."""
    wanted = scope_node_ids(automation.scope)
    if not wanted:
        return False
    library = LibraryService(session)
    documents: set[UUID] = set()
    for node_id in wanted:
        try:
            documents |= {item.document_id for item in library.indexed_documents_under(
                scope=scope, user_id=user_id, node_id=node_id, system_view=True)}
        except SyncAccessDenied:
            continue
    if not documents:
        return False
    probe = Provenance(document_ids=frozenset(documents))
    return not build_index(session, after, [probe]).visible(probe)


def derived_impact(
    session: Session, organization_id: UUID, user_id: UUID, *, lost_folder_ids: set[UUID],
    lost_space_id: UUID | None = None,
) -> dict[str, int]:
    """What losing ``lost_folder_ids`` and the library folders granted only by ``lost_space_id`` (net of the person's
    other Spaces) would hide or stop. Read-only."""
    result = {"conversations_hidden": 0, "automations_paused": 0, "followed_queries_cleared": 0}
    lost = set(lost_folder_ids)
    scope = OrganizationScope(organization_id)
    access = SpaceAccessResolver(session).resolve(scope=scope, user_id=user_id)
    nodes = lost_node_ids(access, lost_space_id)
    if not lost and not nodes:
        return result
    after = _after(access, lost, nodes)
    hidden_conversations: set[UUID] = set()
    for batch in _messages(session, organization_id, user_id, MESSAGE_SCAN_LIMIT):
        provenance = {m.id: answer_provenance(m.response, m.context) for m in batch}
        now_index = build_index(session, access, provenance.values())
        later_index = build_index(session, after, provenance.values())
        hidden_conversations |= {m.conversation_id for m in batch
                                 if now_index.visible(provenance[m.id]) and not later_index.visible(provenance[m.id])}
    result["conversations_hidden"] = len(hidden_conversations)
    for automation in session.scalars(select(Automation).where(
            Automation.organization_id == organization_id, Automation.created_by_user_id == user_id,
            Automation.enabled.is_(True))):
        if (lost and _automation_folders(session, scope, user_id, automation) & lost) or (
                nodes and _automation_loses_nodes(session, scope, user_id, automation, after)):
            result["automations_paused"] += 1
    result["followed_queries_cleared"] = len(list(session.scalars(select(SavedQuery.id).where(
        SavedQuery.organization_id == organization_id, SavedQuery.user_id == user_id, SavedQuery.followed.is_(True),
        SavedQuery.workspace_folder_id.in_(list(lost)))))) if lost else 0
    return result


def purge_derived_for_user(session: Session, organization_id: UUID, user_id: UUID) -> dict[str, int]:
    """Tombstone everything of this person's that cites content they can no longer read. No grace is applied here."""
    counts = dict(ZERO_PURGE)
    scope = OrganizationScope(organization_id)
    try:
        access = SpaceAccessResolver(session).resolve(scope=scope, user_id=user_id)
    except SyncAccessDenied:
        return counts  # left the organization: the membership check already cuts everything
    counts["followed"] = clear_followed_state_for_lost_access(session, organization_id, user_id)
    counts["automations_paused"] = len(pause_automations_for_lost_access(session, organization_id, user_id))
    for batch in _messages(session, organization_id, user_id):
        provenance = {m.id: answer_provenance(m.response, m.context) for m in batch}
        index = build_index(session, access, provenance.values())
        for message in batch:
            if provenance[message.id] and not index.visible(provenance[message.id]):
                message.content, message.context, message.response = HIDDEN_NOTICE, None, hidden_response()
                counts["messages"] += 1
    notes = [item for item in session.scalars(select(Notification).where(
        Notification.organization_id == organization_id, Notification.user_id == user_id))
        if not (isinstance(item.data, dict) and item.data.get("hidden"))]
    if notes:
        seen = notifications_visibility(session, organization_id, user_id, notes)
        for item in notes:
            if not seen[item.id] and (item.kind in CONTENT_KINDS or (isinstance(item.data, dict) and item.data.get("provenance"))):
                item.body, item.data = HIDDEN_NOTICE, hidden_data(item.data)
                counts["notifications"] += 1
    runs = [run for run in session.scalars(
        select(AutomationRun).join(Automation, Automation.id == AutomationRun.automation_id)
        .where(Automation.organization_id == organization_id, Automation.created_by_user_id == user_id))
        if run.result and not run.result.get("hidden") and run_provenance(run)]
    if runs:
        seen_runs = runs_visibility(session, organization_id, user_id, runs)
        for run in runs:
            if not seen_runs[run.id]:
                run.result = hidden_result()
                counts["runs"] += 1
    session.flush()
    return counts


def _add(total: dict[str, int], part: dict[str, int]) -> None:
    for key, value in part.items():
        total[key] = total.get(key, 0) + value


def purge_derived_for_folder(
    session: Session, organization_id: UUID, workspace_folder_id: UUID, *, now: datetime | None = None,
    grace: timedelta = PURGE_GRACE,
) -> dict[str, int]:
    """Purge for every member of a Space whose grant on this folder was revoked at least ``grace`` ago."""
    cutoff = (now or datetime.now(UTC)) - grace
    spaces = select(SpaceFolderGrant.space_id).where(
        SpaceFolderGrant.organization_id == organization_id, SpaceFolderGrant.workspace_folder_id == workspace_folder_id,
        SpaceFolderGrant.revoked_at.is_not(None), SpaceFolderGrant.revoked_at <= cutoff)
    users = set(session.scalars(select(SpaceMember.user_id).where(
        SpaceMember.organization_id == organization_id, SpaceMember.space_id.in_(spaces))))
    total = dict(ZERO_PURGE)
    for user_id in sorted(users, key=str):
        _add(total, purge_derived_for_user(session, organization_id, user_id))
    return total


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def purge_hidden_derived(
    session: Session, *, now: datetime | None = None, grace: timedelta = PURGE_GRACE,
    lookback: timedelta = PURGE_LOOKBACK,
) -> dict[str, int]:
    """The daily job: purge people who lost a membership, a granted folder or a whole Space ≥ ``grace`` ago."""
    now = now or datetime.now(UTC)
    cutoff, floor = now - grace, now - lookback
    pairs: set[tuple[UUID, UUID]] = set()
    for org, user in session.execute(select(SpaceMember.organization_id, SpaceMember.user_id).where(
            SpaceMember.removed_at.is_not(None), SpaceMember.removed_at <= cutoff, SpaceMember.removed_at >= floor)):
        pairs.add((org, user))
    closed = select(SpaceFolderGrant.space_id).where(
        SpaceFolderGrant.revoked_at.is_not(None), SpaceFolderGrant.revoked_at <= cutoff, SpaceFolderGrant.revoked_at >= floor
    ).union(select(Space.id).where(Space.archived_at.is_not(None), Space.archived_at <= cutoff, Space.archived_at >= floor))
    for org, user in session.execute(select(SpaceMember.organization_id, SpaceMember.user_id).where(
            SpaceMember.space_id.in_(closed))):
        pairs.add((org, user))
    total = dict(ZERO_PURGE)
    for org, user in sorted(pairs, key=lambda pair: (str(pair[0]), str(pair[1]))):
        _add(total, purge_derived_for_user(session, org, user))
    return total
