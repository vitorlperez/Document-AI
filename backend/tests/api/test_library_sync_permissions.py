"""Who may sync: any member runs an incremental sync; a complete resync is Owner/Admin only."""
# ruff: noqa: F811  (pytest fixture imported from the library API tests)

from uuid import UUID

import pytest

from app.ingestion.models import ProcessingJob, ProcessingJobStatus
from app.library import manual_sync
from app.organizations.models import Membership, MembershipRole
from app.workspaces.models import WorkspaceFolder
from tests.api.test_company_library_api import (  # noqa: F401
    _nest_file_under_folder,
    api,
    login,
    seed_library,
)


@pytest.fixture()
def world(api):
    client, factory = api
    login(client)  # owner
    organization = client.post("/organizations", json={"name": "Acme"}).json()["id"]
    source = seed_library(factory, organization)
    folder_node = _nest_file_under_folder(factory, organization, source)
    login(client, "plain")
    with factory() as session:
        from app.identity.models import User
        plain = session.query(User).filter_by(email="plain@example.test").one()
        session.add(Membership(organization_id=UUID(organization), user_id=plain.id,
                               role=MembershipRole.MEMBER, is_active=True))
        workspace = session.query(WorkspaceFolder).one().id
        session.commit()
    client.app.state.ingestion_dispatcher = type("D", (), {"dispatch": lambda self, job_id: None})()

    def finish_jobs():
        with factory() as session:
            session.query(ProcessingJob).update({"status": ProcessingJobStatus.READY})
            session.commit()

    return client, organization, folder_node, workspace, finish_jobs


def _incremental(client, organization, node, workspace, *, via):
    if via == "node":
        return client.post(f"/library/nodes/{node}/reprocess?organization_id={organization}")
    return client.post(f"/library/workspaces/{workspace}/reprocess?organization_id={organization}")


def _complete(client, organization, node, workspace, *, via):
    if via == "node":
        return client.post(f"/library/nodes/{node}/reprocess?organization_id={organization}&reprocess_all=true")
    return client.post(f"/library/workspaces/{workspace}/reprocess?organization_id={organization}&reprocess_all=true")


@pytest.mark.parametrize("via", ["node", "workspace"])
def test_member_can_run_an_incremental_sync(world, via) -> None:
    client, organization, node, workspace, _finish = world
    response = _incremental(client, organization, node, workspace, via=via)
    assert response.status_code == 202
    history = client.get(f"/library/manual-syncs?organization_id={organization}").json()["items"][0]
    assert history["mode"] == "incremental"


@pytest.mark.parametrize("via", ["node", "workspace"])
def test_member_cannot_run_a_complete_resync(world, via) -> None:
    client, organization, node, workspace, _finish = world
    assert _complete(client, organization, node, workspace, via=via).status_code == 403
    assert client.get(f"/library/manual-syncs?organization_id={organization}").json()["items"] == []


@pytest.mark.parametrize("via", ["node", "workspace"])
def test_admin_can_run_both(world, via) -> None:
    client, organization, node, workspace, finish = world
    login(client)  # owner
    assert _incremental(client, organization, node, workspace, via=via).status_code == 202
    finish()
    assert _complete(client, organization, node, workspace, via=via).status_code == 202
    modes = [item["mode"] for item in client.get(f"/library/manual-syncs?organization_id={organization}").json()["items"]]
    assert sorted(modes) == ["full", "incremental"]


def test_non_member_cannot_sync(world) -> None:
    client, organization, node, workspace, _finish = world
    login(client, "outsider")
    assert _incremental(client, organization, node, workspace, via="node").status_code == 403
    assert _incremental(client, organization, node, workspace, via="workspace").status_code == 403


def test_active_sync_is_reused_instead_of_conflicting(world) -> None:
    client, organization, node, workspace, _finish = world
    first = _incremental(client, organization, node, workspace, via="workspace")
    second = _incremental(client, organization, node, workspace, via="node")
    assert first.status_code == second.status_code == 202
    assert second.json()["job_ids"] == [first.json()["job_id"]]
    assert second.json()["run_id"] == first.json()["run_id"]


def test_incremental_sync_has_a_cooldown_per_space(world, monkeypatch) -> None:
    client, organization, node, workspace, finish = world
    monkeypatch.setattr(manual_sync, "SYNC_COOLDOWN_SECONDS", 60)
    assert _incremental(client, organization, node, workspace, via="workspace").status_code == 202
    finish()
    again = _incremental(client, organization, node, workspace, via="workspace")
    assert again.status_code == 429 and "Retry-After" in again.headers
