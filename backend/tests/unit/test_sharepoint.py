from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet

from app.integrations.google_drive import RemoteFolder
from app.integrations.onedrive import (
    GRAPH_ROOT,
    DeltaPage,
    OneDriveCipher,
    OneDriveCredentials,
    OneDriveDeltaExpired,
)
from app.integrations.sharepoint import (
    ITEM_SELECT,
    SHAREPOINT_SCOPES,
    SharePointDocumentProvider,
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


# --- A4: provider -------------------------------------------------------------

CIPHER = OneDriveCipher(Fernet.generate_key().decode())
LATEST = f"{GRAPH_ROOT}/drives/b%21d1/root/delta?token=T1"
NEXT = f"{GRAPH_ROOT}/drives/b%21d1/root/delta?token=T2"


def _file(item_id: str, parent: str, *, drive: str = DRIVE, size: int = 10) -> dict:
    return {
        "id": item_id,
        "name": f"{item_id}.pdf",
        "file": {"mimeType": "application/pdf"},
        "size": size,
        "webUrl": f"https://c.sharepoint.com/{item_id}.pdf",
        "lastModifiedDateTime": "2026-09-01T10:00:00+00:00",
        "parentReference": {"driveId": drive, "id": parent},
    }


class InMemoryGraph(SharePointGraphClient):
    """High-level Graph fake: records the order of remote operations."""

    def __init__(
        self,
        *,
        files=(),
        delta=(),
        parents=None,
        items=None,
        expired=False,
        catalog_nodes=(),
        folders=(),
    ) -> None:
        super().__init__(client_id="c", client_secret="s", redirect_uri="https://x.test/cb")
        self.files, self.delta, self.expired = list(files), list(delta), expired
        self.parents, self.items = parents or {}, items or {}
        self.catalog_nodes, self.folder_items = list(catalog_nodes), list(folders)
        self.latest, self.order, self.reads = LATEST, [], []

    def latest_delta_link(self, *, credentials, drive_id):
        self.order.append("latest")
        return self.latest

    def list_files(self, *, credentials, scope_id):
        self.order.append("children")
        return list(self.files)

    def delta_root(self, *, credentials, drive_id, cursor):
        self.order.append("delta")
        if self.expired:
            raise OneDriveDeltaExpired()
        return DeltaPage(list(self.delta), NEXT)

    def drive_root_id(self, *, credentials, drive_id):
        return "01ROOT"

    def _get_or_none(self, url, credentials):
        self.order.append("parent")
        item_id = url.split("/items/", 1)[1].split("?", 1)[0]
        parent = self.parents.get(item_id)
        return None if parent is None else {"id": item_id, "parentReference": {"id": parent}}

    def get_item(self, *, credentials, item_id):
        self.order.append("get_item")
        return self.items.get(item_id)

    def read_file(self, *, credentials, item_id):
        self.reads.append(item_id)
        return b"body"

    def catalog(self, *, credentials, max_sites=200):
        return list(self.catalog_nodes)

    def list_folders(self, *, credentials, drive_id):
        return [f for f in self.folder_items if f["parentReference"]["driveId"] == drive_id]


def make_provider(graph: InMemoryGraph) -> SharePointDocumentProvider:
    return SharePointDocumentProvider(graph, CIPHER)


def fake_selection(*, external_folder_id: str, encrypted_delta_link: str | None):
    return SimpleNamespace(
        id=uuid4(),
        kind="folder",
        external_folder_id=external_folder_id,
        encrypted_delta_link=encrypted_delta_link,
    )


def _discover(graph, selection, **kwargs):
    return make_provider(graph).discover(
        encrypted_credentials=CIPHER.encrypt_credentials(CREDS), selections=[selection], **kwargs
    )


def _incremental(scope: str = "b!d1|01S"):
    return fake_selection(
        external_folder_id=scope, encrypted_delta_link=CIPHER.encrypt_cursor(LATEST)
    )


def test_first_sync_takes_latest_token_before_traversal_and_returns_full_snapshot() -> None:
    graph = InMemoryGraph(files=[_file("01A", "01ROOT")])
    selection = fake_selection(external_folder_id="b!d1|01ROOT", encrypted_delta_link=None)
    result = _discover(graph, selection)
    assert graph.order == ["latest", "children"]
    assert result.full_snapshot is True
    assert [d.external_file_id for d in result.documents] == ["b!d1|01A"]
    assert result.documents[0].parent_ids == ("b!d1|01ROOT",)
    assert result.delta_links == {selection.id: graph.latest}


def test_incremental_delta_reads_only_changed_file_inside_scope() -> None:
    graph = InMemoryGraph(
        delta=[_file("01A", "01S"), _file("01Z", "01X")], parents={"01X": "01ROOT"}
    )
    selection = _incremental()
    result = _discover(graph, selection)
    assert [d.external_file_id for d in result.documents] == ["b!d1|01A"]
    assert result.removed_file_ids == ("b!d1|01Z",)
    assert result.full_snapshot is False
    assert result.delta_links == {selection.id: NEXT}
    assert graph.reads == ["b!d1|01A"]


def test_moved_out_of_scope_file_is_reported_as_removed() -> None:
    graph = InMemoryGraph(delta=[_file("01M", "01OTHER")], parents={"01OTHER": "01ROOT"})
    result = _discover(graph, _incremental())
    assert result.documents == []
    assert result.removed_file_ids == ("b!d1|01M",)


def test_deleted_item_is_removed_without_membership_calls() -> None:
    deleted = {"id": "01D", "deleted": {}, "parentReference": {"driveId": DRIVE, "id": "01S"}}
    graph = InMemoryGraph(delta=[deleted])
    result = _discover(graph, _incremental())
    assert result.removed_file_ids == ("b!d1|01D",)
    assert "parent" not in graph.order and "get_item" not in graph.order


def test_folder_event_inside_scope_forces_snapshot() -> None:
    folder = {"id": "01G", "folder": {}, "parentReference": {"driveId": DRIVE, "id": "01S"}}
    graph = InMemoryGraph(delta=[folder], files=[_file("01N", "01G")])
    selection = _incremental()
    result = _discover(graph, selection)
    assert result.full_snapshot is True
    assert graph.order == ["delta", "latest", "children"]
    assert [d.external_file_id for d in result.documents] == ["b!d1|01N"]
    assert result.delta_links == {selection.id: LATEST}


def test_expired_cursor_falls_back_to_snapshot_with_new_token() -> None:
    graph = InMemoryGraph(expired=True, files=[_file("01A", "01S")])
    selection = _incremental()
    result = _discover(graph, selection)
    assert result.full_snapshot is True
    assert graph.order == ["delta", "latest", "children"]
    assert result.delta_links == {selection.id: LATEST}


def test_library_root_scope_skips_membership_calls() -> None:
    graph = InMemoryGraph(delta=[_file("01A", "01DEEP")])
    result = _discover(graph, _incremental("b!d1|01ROOT"))
    assert [d.external_file_id for d in result.documents] == ["b!d1|01A"]
    assert "parent" not in graph.order and "get_item" not in graph.order


def test_force_file_ids_reads_unchanged_file_when_in_scope_and_removes_when_gone() -> None:
    graph = InMemoryGraph(
        items={"b!d1|01A": _file("01A", "01S"), "b!d1|01OUT": _file("01OUT", "01X")},
        parents={"01X": "01ROOT"},
    )
    result = _discover(
        graph, _incremental(), force_file_ids={"b!d1|01A", "b!d1|01GONE", "b!d1|01OUT"}
    )
    assert graph.reads == ["b!d1|01A"]
    assert [d.external_file_id for d in result.documents] == ["b!d1|01A"]
    assert result.removed_file_ids == ("b!d1|01GONE", "b!d1|01OUT")


def test_oversized_file_becomes_file_too_large_without_download() -> None:
    too_big = SharePointDocumentProvider.max_file_bytes + 1
    graph = InMemoryGraph(delta=[_file("01A", "01S", size=too_big)])
    result = _discover(graph, _incremental())
    assert [d.error_code for d in result.documents] == ["file_too_large"]
    assert graph.reads == []


def test_folders_for_selections_returns_site_library_and_folder_nodes_only_for_selected_drives() -> (
    None
):
    s1, s2 = site_node_id("h,s1,1"), site_node_id("h,s2,2")
    graph = InMemoryGraph(
        catalog_nodes=[
            RemoteFolder(s1, "Jurídico", ()),
            RemoteFolder("b!d1|01ROOT", "Documentos", (s1,)),
            RemoteFolder(s2, "RH", ()),
            RemoteFolder("b!d2|02ROOT", "Pessoas", (s2,)),
        ],
        folders=[
            {
                "id": "01F",
                "name": "Contratos",
                "parentReference": {"driveId": DRIVE, "id": "01ROOT"},
            },
            {"id": "02F", "name": "Folha", "parentReference": {"driveId": "b!d2", "id": "02ROOT"}},
        ],
    )
    nodes = make_provider(graph).folders_for_selections(
        encrypted_credentials=CIPHER.encrypt_credentials(CREDS),
        selections=[fake_selection(external_folder_id="b!d1|01F", encrypted_delta_link=None)],
    )
    assert nodes == [
        RemoteFolder(s1, "Jurídico", ()),
        RemoteFolder("b!d1|01ROOT", "Documentos", (s1,)),
        RemoteFolder("b!d1|01F", "Contratos", ("b!d1|01ROOT",)),
    ]
