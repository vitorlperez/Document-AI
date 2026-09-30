from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.integrations.google_drive import RemoteFolder
from app.integrations.onedrive import GRAPH_ROOT, OneDriveCredentials, OneDriveDeltaExpired
from app.integrations.sharepoint import (
    ITEM_SELECT,
    SHAREPOINT_SCOPES,
    SharePointGraphClient,
    SharePointIdInvalid,
    composite_id,
    is_site_node,
    site_node_id,
    split_composite,
)

CREDS = OneDriveCredentials("token", "refresh", datetime.now(UTC) + timedelta(hours=1))


class FakeGraph(SharePointGraphClient):
    """Routes Graph GETs by URL suffix; records every call."""

    def __init__(self, routes: dict[str, dict]) -> None:
        super().__init__(client_id="c", client_secret="s", redirect_uri="https://x.test/cb")
        self.routes, self.calls = routes, []

    def _get_json(self, url, *, credentials, allow_expired_delta=False):
        path = url.removeprefix(GRAPH_ROOT)
        self.calls.append(path)
        if path not in self.routes:
            raise AssertionError(f"unexpected Graph call: {path}")
        return self.routes[path]


def test_composite_id_roundtrips_drive_ids_that_contain_a_bang() -> None:
    value = composite_id("b!AbC-dEf_123", "01ITEM")
    assert value == "b!AbC-dEf_123|01ITEM"
    assert split_composite(value) == ("b!AbC-dEf_123", "01ITEM")


@pytest.mark.parametrize("bad", ["", "01ITEM", "|01ITEM", "b!x|", "site|abc,1,2"])
def test_split_composite_rejects_plain_empty_or_site_node_values(bad: str) -> None:
    with pytest.raises(SharePointIdInvalid):
        split_composite(bad)


def test_authorization_url_uses_organizations_authority_and_read_only_scopes() -> None:
    client = SharePointGraphClient(
        client_id="c", client_secret="s", redirect_uri="https://x.test/cb"
    )
    url = httpx.URL(client.authorization_url(state="st"))
    assert url.path == "/organizations/oauth2/v2.0/authorize"
    scopes = set(url.params["scope"].split())
    assert scopes == set(SHAREPOINT_SCOPES.split())
    assert "Sites.Read.All" in scopes
    assert not [
        s for s in scopes if "ReadWrite" in s or "FullControl" in s or s == "Files.Read.All"
    ]


def test_catalog_lists_sites_and_document_libraries_with_composite_ids() -> None:
    site = "contoso.sharepoint.com,g1,g2"
    client = FakeGraph(
        {
            "/sites?search=*&$select=id,displayName,webUrl": {
                "value": [
                    {
                        "id": site,
                        "displayName": "Jurídico",
                        "webUrl": "https://contoso.sharepoint.com/sites/j",
                    }
                ]
            },
            f"/sites/{site}/drives?$select=id,name,driveType": {
                "value": [
                    {"id": "b!d1", "name": "Documentos", "driveType": "documentLibrary"},
                    {"id": "b!d2", "name": "Ativos", "driveType": "other"},
                ]
            },
            "/drives/b%21d1/root?$select=id": {"id": "01ROOT"},
        }
    )
    assert client.catalog(credentials=CREDS) == [
        RemoteFolder(site_node_id(site), "Jurídico", ()),
        RemoteFolder("b!d1|01ROOT", "Documentos", (site_node_id(site),)),
    ]
    assert is_site_node(site_node_id(site))


def test_catalog_skips_sites_without_document_libraries_and_deduplicates() -> None:
    site = "contoso.sharepoint.com,g1,g2"
    client = FakeGraph(
        {
            "/sites?search=*&$select=id,displayName,webUrl": {
                "value": [{"id": site, "displayName": "A"}, {"id": site, "displayName": "A"}]
            },
            f"/sites/{site}/drives?$select=id,name,driveType": {"value": []},
        }
    )
    assert client.catalog(credentials=CREDS) == []
    assert client.calls.count(f"/sites/{site}/drives?$select=id,name,driveType") == 1


DRIVE = "b!d1"


def test_list_files_walks_children_and_returns_only_files_with_composite_parents() -> None:
    client = FakeGraph(
        {
            f"/drives/b%21d1/items/01ROOT/children?$select={ITEM_SELECT}&$top=200": {
                "value": [
                    {
                        "id": "01F",
                        "name": "Contratos",
                        "folder": {},
                        "parentReference": {"driveId": DRIVE, "id": "01ROOT"},
                    },
                    {
                        "id": "01A",
                        "name": "a.pdf",
                        "file": {"mimeType": "application/pdf"},
                        "parentReference": {"driveId": DRIVE, "id": "01ROOT"},
                    },
                ]
            },
            f"/drives/b%21d1/items/01F/children?$select={ITEM_SELECT}&$top=200": {
                "value": [
                    {
                        "id": "01B",
                        "name": "b.docx",
                        "file": {"mimeType": "x"},
                        "parentReference": {"driveId": DRIVE, "id": "01F"},
                    }
                ]
            },
        }
    )
    items = client.list_files(credentials=CREDS, scope_id="b!d1|01ROOT")
    assert sorted(client._external_id(i) for i in items) == ["b!d1|01A", "b!d1|01B"]
    assert client._parent_ids(items[0]["parentReference"])[0].startswith("b!d1|")


def test_latest_delta_link_uses_token_latest_and_validates_graph_host() -> None:
    link = f"{GRAPH_ROOT}/drives/b%21d1/root/delta?token=abc"
    client = FakeGraph(
        {"/drives/b%21d1/root/delta?token=latest": {"value": [], "@odata.deltaLink": link}}
    )
    assert client.latest_delta_link(credentials=CREDS, drive_id=DRIVE) == link


def test_within_scope_walks_parents_once_and_memoizes() -> None:
    client = FakeGraph(
        {
            "/drives/b%21d1/items/01C?$select=id,parentReference": {
                "id": "01C",
                "parentReference": {"id": "01B"},
            },
            "/drives/b%21d1/items/01B?$select=id,parentReference": {
                "id": "01B",
                "parentReference": {"id": "01S"},
            },
        }
    )
    cache: dict[str, bool] = {}
    kwargs = {"credentials": CREDS, "drive_id": DRIVE, "scope_item_id": "01S", "cache": cache}
    assert client.within_scope(parent_id="01C", **kwargs) is True
    assert client.within_scope(parent_id="01B", **kwargs) is True  # served from cache
    assert len(client.calls) == 2


def test_within_scope_is_false_when_reaching_the_drive_root_or_a_missing_parent() -> None:
    client = FakeGraph(
        {
            "/drives/b%21d1/items/01X?$select=id,parentReference": {
                "id": "01X",
                "parentReference": {"id": "01ROOT"},
            },
        }
    )
    assert (
        client.within_scope(
            credentials=CREDS,
            drive_id=DRIVE,
            parent_id="01X",
            scope_item_id="01S",
            drive_root_id="01ROOT",
            cache={},
        )
        is False
    )


def test_delta_root_raises_expired_on_410() -> None:
    class Gone(FakeGraph):
        def _get_json(self, url, *, credentials, allow_expired_delta=False):
            assert allow_expired_delta is True
            raise OneDriveDeltaExpired()

    with pytest.raises(OneDriveDeltaExpired):
        Gone({}).delta_root(
            credentials=CREDS,
            drive_id=DRIVE,
            cursor=f"{GRAPH_ROOT}/drives/b%21d1/root/delta?token=old",
        )
