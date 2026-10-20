"""T-D5: sync status, syncs and history endpoints respect the caller's Spaces."""

import pytest

from app.ingestion.models import ProcessingJob, ProcessingJobStatus
from app.library.models import ManualSyncRun
from tests.api.test_text_search_api import (  # noqa: F401 -- reuse the isolated API fixture
    login,
    search_api,
)
from tests.spaces_helpers import bind_login_identities, seed_world

SECRET_FILE = "reajuste-confidencial.pdf"


@pytest.fixture()
def world_api(search_api):  # noqa: F811
    client, factory, gateway = search_api
    with factory.begin() as session:
        world = seed_world(session)
        bind_login_identities(session, world)
        source_id = world.source_id
        for key, folder_id in world.folders.items():
            job = ProcessingJob(organization_id=world.organization_id, workspace_folder_id=folder_id,
                                status=ProcessingJobStatus.PARTIAL_FAILURE, idempotency_key=f"job-{key}")
            session.add(job)
            session.flush()
            session.add(ManualSyncRun(
                organization_id=world.organization_id, source_id=source_id, scope_kind="sync",
                scope_external_id=str(job.id), scope_name=key, triggered_by="x", status="partial_failure",
                progress={str(job.id): {
                    "workspace_name": key, "workspace_folder_id": str(folder_id), "status": "partial_failure",
                    "stage": "done", "total": 1, "processed": 0, "failed": 1, "skipped": 0, "docs_ready": 0,
                    "error_code": None,
                    "outcomes": [{"external_id": f"{key}-x", "name": f"{key}-{SECRET_FILE}", "processed": False,
                                  "error_code": "extract_failed", "status": "failed"}]}}))
    return client, gateway, world


def get(client, gateway, world, who, path):
    client.cookies.clear()
    login(client, gateway, code=who, email=f"{who}@acme.test", subject=who)
    response = client.get(f"{path}{'&' if '?' in path else '?'}organization_id={world.organization_id}")
    assert response.status_code == 200, response.text
    return response


def test_member_history_and_syncs_hide_other_spaces(world_api):
    client, gateway, world = world_api
    history = get(client, gateway, world, "bruno", "/library/sync-history")
    assert {item["scope_name"] for item in history.json()["items"]} == {"politicas", "rh"}
    assert "diretoria" not in history.text
    syncs = get(client, gateway, world, "bruno", "/library/syncs")
    assert {item["workspace_name"] for item in syncs.json()["items"]} == {"politicas", "rh"}


def test_admin_sees_every_scope_but_no_file_names_of_unreadable_ones(world_api):
    client, gateway, world = world_api
    history = get(client, gateway, world, "eva", "/library/sync-history")
    by_scope = {item["scope_name"]: item for item in history.json()["items"]}
    assert set(by_scope) == {"politicas", "rh", "diretoria"}
    assert by_scope["rh"]["status"] == "partial_failure" and by_scope["rh"]["failed"] == 1
    assert "rh-" + SECRET_FILE not in history.text and "diretoria-" + SECRET_FILE not in history.text
    assert "politicas-" + SECRET_FILE in history.text  # her own readable scope keeps its detail


def test_sync_status_is_limited_to_readable_scopes_for_members(world_api):
    client, gateway, world = world_api
    status = get(client, gateway, world, "bruno", "/library/sync-status").json()["items"]
    assert len(status) == 1 and status[0]["failed"] == 2  # politicas + rh, not diretoria
