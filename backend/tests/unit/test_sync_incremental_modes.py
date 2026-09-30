"""Library resync is incremental; integration-management re-sync is deep (M25)."""
# ruff: noqa: F811  (pytest fixture imported from tests.sync_helpers)

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.scoping import OrganizationScope
from app.integrations.google_drive import RemoteFolder
from app.knowledge.models import Document
from app.library.manual_sync import request_run, serialize_run
from app.library.models import LibraryNode
from tests.sync_helpers import T0, TREE, doc, seed, session, space, sync  # noqa: F401


def _node(session: Session, external_id: str) -> LibraryNode:
    return session.scalar(select(LibraryNode).where(LibraryNode.external_id == external_id))


def _two_spaces(session: Session):
    organization, user, source = seed(session)
    tda = space(session, organization, source, "tda", created_at=T0, folder_id="tda")
    other = space(session, organization, source, "other", created_at=T0, folder_id="other")
    sync(session, organization, user, tda, [doc("a")])
    sync(session, organization, user, other, [doc("x", parent="other")],
         folders=[RemoteFolder("other", "Other")])
    return organization, user, source, tda, other


def test_library_resync_is_incremental_and_keeps_hashes(session: Session) -> None:
    organization, user, _source, tda, _other = _two_spaces(session)
    run, _jobs = request_run(session, scope=OrganizationScope(organization.id), user=user,
                             workspace_id=tda.id)
    assert serialize_run(run)["mode"] == "incremental"
    assert session.scalar(select(Document.content_hash).where(Document.external_file_id == "a")) != ""


def test_reprocess_all_is_a_complete_run_and_clears_hashes(session: Session) -> None:
    organization, user, _source, tda, _other = _two_spaces(session)
    run, _jobs = request_run(session, scope=OrganizationScope(organization.id), user=user,
                             workspace_id=tda.id, reprocess_all=True)
    assert serialize_run(run)["mode"] == "full"
    assert session.scalar(select(Document.content_hash).where(Document.external_file_id == "a")) == ""


@pytest.mark.parametrize("external_id", ["tda", "sub"])
def test_folder_resync_only_syncs_spaces_containing_the_folder(session: Session, external_id: str) -> None:
    organization, user, _source, tda, _other = _two_spaces(session)
    _run, jobs = request_run(session, scope=OrganizationScope(organization.id), user=user,
                             node_id=_node(session, external_id).id)
    assert [job.workspace_folder_id for job in jobs] == [tda.id]


def test_folder_resync_includes_all_accessible_space(session: Session) -> None:
    organization, user, source, tda, _other = _two_spaces(session)
    everything = space(session, organization, source, "all", created_at=T0)
    _run, jobs = request_run(session, scope=OrganizationScope(organization.id), user=user,
                             node_id=_node(session, "tda").id)
    assert {job.workspace_folder_id for job in jobs} == {tda.id, everything.id}


def test_source_resync_syncs_every_space_of_the_source(session: Session) -> None:
    organization, user, source, tda, other = _two_spaces(session)
    node = LibraryNode(organization_id=organization.id, source_id=source.id,
                       external_id="source", kind="source", name="Drive")
    session.add(node)
    session.flush()
    _run, jobs = request_run(session, scope=OrganizationScope(organization.id), user=user,
                             node_id=node.id)
    assert {job.workspace_folder_id for job in jobs} == {tda.id, other.id}


def test_folder_resync_with_no_containing_space_explains_itself(session: Session) -> None:
    organization, user, source, _tda, _other = _two_spaces(session)
    session.add(LibraryNode(organization_id=organization.id, source_id=source.id,
                            external_id="orphan", kind="folder", name="Orphan"))
    session.flush()
    with pytest.raises(ValueError, match="Nenhum espaço"):
        request_run(session, scope=OrganizationScope(organization.id), user=user,
                    node_id=_node(session, "orphan").id)
