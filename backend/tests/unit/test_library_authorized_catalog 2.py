"""LibraryService.authorized_catalog: one resolution, same ACL as the catalog tools."""

# Pytest intentionally injects the imported fixture under the same parameter name.
# ruff: noqa: F811

import pytest
from sqlalchemy import event, select

from app.library.service import LibraryService, SyncAccessDenied
from app.organizations.models import Membership
from tests.unit.test_agent_revocation_review import (
    make_case,
    no_external_ai,  # noqa: F401
    semantic_session,  # noqa: F401
)


def resolve(case, service, mentions, **extra):
    return service.authorized_catalog(
        scope=case.scope, user_id=case.user.id, providers=case.providers, mentions=mentions, **extra,
    )


def test_matches_private_nodes_and_selection_folders_without_mentions(semantic_session):
    case = make_case(semantic_session)
    service = LibraryService(semantic_session)
    catalog = resolve(case, service, [])
    private = service._authorized_catalog_nodes(
        scope=case.scope, user_id=case.user.id, providers=case.providers, mentions=[],
    )
    selection = service.resolve_question_selection(
        scope=case.scope, user_id=case.user.id, providers=case.providers, mentions=[],
    )
    assert set(catalog.nodes) == set(private) and {n.id for n in case.nodes} <= set(catalog.nodes)
    assert catalog.folder_ids == frozenset(selection.folder_ids) == {case.workspace.id}
    assert set(catalog.nodes) <= set(catalog.all_nodes)


def test_mention_narrows_nodes_but_keeps_admitted_folders(semantic_session):
    case = make_case(semantic_session)
    service = LibraryService(semantic_session)
    catalog = resolve(case, service, [("file", case.nodes[0].id)])
    assert set(catalog.nodes) == {case.nodes[0].id}
    assert catalog.folder_ids == {case.workspace.id}
    assert case.nodes[1].id in catalog.all_nodes


def test_reusing_all_nodes_gives_the_same_result_with_fewer_statements(semantic_session):
    case = make_case(semantic_session)
    service = LibraryService(semantic_session)
    mentions = [("file", case.nodes[0].id)]
    first = resolve(case, service, [])
    engine, statements = semantic_session.get_bind(), []

    def record(conn, cursor, statement, *_):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    fresh = resolve(case, service, mentions)
    fresh_count, statements[:] = len(statements), []
    reused = resolve(case, service, mentions, all_nodes=first.all_nodes)
    reused_count = len(statements)
    event.remove(engine, "before_cursor_execute", record)
    assert set(reused.nodes) == set(fresh.nodes) and reused.folder_ids == fresh.folder_ids
    assert reused_count < fresh_count


def test_acl_denials_are_unchanged(semantic_session):
    case = make_case(semantic_session)
    service = LibraryService(semantic_session)
    with pytest.raises(ValueError, match="mention is unavailable"):
        resolve(case, service, [("file", case.folder.id)])
    member = semantic_session.scalar(select(Membership).where(
        Membership.organization_id == case.org.id, Membership.user_id == case.user.id,
    ))
    member.is_active = False
    semantic_session.commit()
    with pytest.raises(SyncAccessDenied):
        resolve(case, service, [])
