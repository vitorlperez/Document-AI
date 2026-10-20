"""T-H2: an old run result whose provenance left the viewer's access is hidden (API and PDF)."""

import pytest

from app.automations.models import Automation, AutomationRun
from tests.api.test_text_search_api import login, search_api  # noqa: F401
from tests.space_derived_helpers import remove_from_space
from tests.spaces_helpers import bind_login_identities, seed_world


@pytest.fixture()
def world_api(search_api):  # noqa: F811
    client, factory, gateway = search_api
    with factory.begin() as session:
        world = seed_world(session)
        bind_login_identities(session, world)
        automation = Automation(
            organization_id=world.organization_id, created_by_user_id=world.users["carla"], name="Diretoria semanal",
            enabled=True, trigger_kind="schedule", trigger_config={"frequency": "weekly", "weekday": 0, "hour": 8,
                                                                     "timezone": "America/Sao_Paulo"},
            scope={"workspace_folder_ids": [str(world.folders["diretoria"])]}, prompt="Resuma.", template="table",
            output_formats=[], recipients=[])
        session.add(automation)
        session.flush()
        provenance = {"document_ids": [str(world.documents["diretoria"])],
                      "workspace_folder_ids": [str(world.folders["diretoria"])]}
        runs = {}
        for label, result in {
            "new": {"answer": "Reajuste de 5%.", "citations": [{"document_id": str(world.documents["diretoria"]),
                                                                 "document_name": "diretoria.pdf"}],
                    "provenance": provenance},
            "old": {"answer": "Reajuste antigo.", "citations": [{"document_id": str(world.documents["diretoria"]),
                                                                  "document_name": "diretoria.pdf"}]},
        }.items():
            run = AutomationRun(automation_id=automation.id, organization_id=world.organization_id, status="ok",
                                trigger_ref=label, result=result)
            session.add(run)
            session.flush()
            runs[label] = run.id
        return_value = (world, automation.id, runs)
    return client, factory, gateway, return_value


def as_user(client, gateway, who):
    client.cookies.clear()
    login(client, gateway, code=who, email=f"{who}@acme.test", subject=who)


@pytest.mark.parametrize("label", ["new", "old"])
def test_run_is_readable_then_hidden_after_the_creator_loses_the_folder(world_api, label):
    client, factory, gateway, (world, automation_id, runs) = world_api
    as_user(client, gateway, "carla")
    base = f"/organizations/{world.organization_id}/automations/{automation_id}/runs/{runs[label]}"
    assert client.get(base).json()["result"]["answer"]
    assert client.get(base + "/pdf").status_code == 200
    with factory.begin() as session:
        remove_from_space(session, world, "carla", "diretoria")
    as_user(client, gateway, "carla")
    hidden = client.get(base).json()
    assert hidden["result"] == {"hidden": True, "reason": "access_changed"} and hidden["pdf_available"] is False
    assert client.get(base + "/pdf").status_code == 404
    listed = client.get(f"/organizations/{world.organization_id}/automations/{automation_id}/runs").json()["items"]
    assert all(item["result"] == {"hidden": True, "reason": "access_changed"} for item in listed)
    assert "Reajuste" not in client.get(base + "/view").text
