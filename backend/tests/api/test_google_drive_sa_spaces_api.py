"""F-GAP-2: robot Drive folders are granted to the chosen Spaces (default Space when none)."""
# ruff: noqa: F811

import pytest
from sqlalchemy import select

from app.spaces.models import Space, SpaceFolderGrant
from tests.api.test_google_drive_sa_api import batch_setup, google_api  # noqa: F401

pytestmark = pytest.mark.no_auto_spaces

TREE = {"contracts_0001": ("Contratos", []), "finance_00001": ("Financeiro", [])}
ZERO = "00000000-0000-0000-0000-000000000000"


def mk_space(client, org, name):
    response = client.post(f"/organizations/{org}/spaces", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def grants(factory):
    with factory() as session:
        rows = session.execute(
            select(Space.name, SpaceFolderGrant.workspace_folder_id)
            .join(Space, Space.id == SpaceFolderGrant.space_id)
            .where(SpaceFolderGrant.revoked_at.is_(None))).all()
    return sorted((name, str(folder)) for name, folder in rows)


def test_link_without_space_ids_goes_to_default_space(google_api, monkeypatch):
    client, factory, org, source_id = batch_setup(google_api, monkeypatch, TREE)
    response = client.post(
        f"/data-sources/google-sa/{source_id}/folders?organization_id={org}", json={"folder_id": "contracts_0001"})
    assert response.status_code == 200
    assert grants(factory) == [("Geral", response.json()["workspace_folder_id"])]


def test_link_with_space_ids_grants_only_those_spaces(google_api, monkeypatch):
    client, factory, org, source_id = batch_setup(google_api, monkeypatch, TREE)
    rh, fin = mk_space(client, org, "RH"), mk_space(client, org, "Financeiro")
    response = client.post(
        f"/data-sources/google-sa/{source_id}/folders?organization_id={org}",
        json={"folder_id": "contracts_0001", "space_ids": [rh, fin, rh]})
    assert response.status_code == 200
    folder = response.json()["workspace_folder_id"]
    assert grants(factory) == [("Financeiro", folder), ("RH", folder)]  # no default grant, no duplicates
    again = client.post(
        f"/data-sources/google-sa/{source_id}/folders?organization_id={org}",
        json={"folder_id": "contracts_0001", "space_ids": [rh]})
    assert again.status_code == 200 and len(grants(factory)) == 2


def test_link_refuses_foreign_archived_unknown_space_and_links_nothing(google_api, monkeypatch):
    client, factory, org, source_id = batch_setup(google_api, monkeypatch, TREE)
    other = client.post("/organizations", json={"name": "Other"}).json()["id"]
    foreign = mk_space(client, other, "Foreign")
    archived = mk_space(client, org, "Velho")
    assert client.delete(f"/organizations/{org}/spaces/{archived}").status_code == 204
    for bad in (foreign, archived, ZERO):
        response = client.post(
            f"/data-sources/google-sa/{source_id}/folders?organization_id={org}",
            json={"folder_id": "contracts_0001", "space_ids": [bad]})
        assert response.status_code == 404 and response.json() == {"detail": {"code": "space_not_found"}}
    listing = client.get(f"/data-sources/google-sa/{source_id}/folders?organization_id={org}").json()
    assert listing["folders"] == [] and grants(factory) == []


def test_batch_with_space_ids_grants_every_linked_folder(google_api, monkeypatch):
    client, factory, org, source_id = batch_setup(google_api, monkeypatch, TREE)
    rh = mk_space(client, org, "RH")
    response = client.post(
        f"/data-sources/google-sa/{source_id}/folders/batch?organization_id={org}",
        json={"folder_ids": ["contracts_0001", "finance_00001", "missing_000001"], "space_ids": [rh]})
    assert response.status_code == 200
    rows = response.json()["results"]
    ok = sorted(row["workspace_folder_id"] for row in rows if row["status"] == "ok")
    assert len(ok) == 2
    assert grants(factory) == sorted(("RH", folder) for folder in ok)


def test_batch_without_space_ids_goes_to_default_space(google_api, monkeypatch):
    client, factory, org, source_id = batch_setup(google_api, monkeypatch, TREE)
    response = client.post(
        f"/data-sources/google-sa/{source_id}/folders/batch?organization_id={org}",
        json={"folder_ids": ["contracts_0001", "finance_00001"]})
    ids = sorted(row["workspace_folder_id"] for row in response.json()["results"])
    assert grants(factory) == [("Geral", folder) for folder in ids]


def test_batch_refuses_bad_space_before_touching_drive(google_api, monkeypatch):
    client, factory, org, source_id = batch_setup(google_api, monkeypatch, TREE)
    response = client.post(
        f"/data-sources/google-sa/{source_id}/folders/batch?organization_id={org}",
        json={"folder_ids": ["contracts_0001"], "space_ids": [ZERO]})
    assert response.status_code == 404 and response.json() == {"detail": {"code": "space_not_found"}}
    assert grants(factory) == []
