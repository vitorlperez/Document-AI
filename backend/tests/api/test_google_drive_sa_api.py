"""M58 API contract: existing cookie auth, two orgs and no enumeration."""
# ruff: noqa: F811

from sqlalchemy import select

from app.integrations.google_drive_sa import FolderAccessLost
from app.integrations.google_sa_models import DriveFolderLink, GoogleSaIdentity, GoogleSaProject
from tests.api.test_google_integrations import create_organization, google_api, login  # noqa: F401


def prepare(google_api):
    client, factory, gateway, _ = google_api
    login(client, gateway, code="owner", email="owner@example.test", subject="owner")
    org = create_organization(client)
    from cryptography.fernet import Fernet

    from app.access.ratelimit import InMemoryRateLimiter

    client.app.state.rate_limiter = InMemoryRateLimiter()
    settings = client.app.state.settings
    settings.google_drive_sa_enabled = True
    from pydantic import SecretStr

    settings.google_sa_key_encryption_key = SecretStr(Fernet.generate_key().decode())
    with factory() as session:
        project = GoogleSaProject(gcp_project_id="pool")
        session.add(project)
        session.flush()
        for n in range(2):
            session.add(
                GoogleSaIdentity(
                    project_id=project.id, sa_email=f"robot{n}@example.test", encrypted_key="key"
                )
            )
        session.commit()
    return client, factory, org


def test_flag_disabled(google_api):
    client, _, gateway, _ = google_api
    login(client, gateway, code="owner", email="owner@example.test", subject="owner")
    org = create_organization(client)
    result = client.post(f"/data-sources/google-sa/enable?organization_id={org}")
    assert result.status_code == 404
    assert result.json() == {"detail": {"code": "disabled"}}


def test_enable_tenant_and_uniform_missing_errors(google_api, monkeypatch):
    client, factory, org = prepare(google_api)
    result = client.post(f"/data-sources/google-sa/enable?organization_id={org}")
    assert result.status_code == 200
    assert result.json()["share_role"] == "reader"
    source_id = result.json()["source_id"]
    assert "key" not in str(result.json())
    other = create_organization(client)
    other_result = client.post(f"/data-sources/google-sa/enable?organization_id={other}")
    assert other_result.status_code == 200
    assert other_result.json()["robot_email"] != result.json()["robot_email"]
    from app.integrations.google_drive_sa_service import DriveSaConnectionService

    monkeypatch.setattr(DriveSaConnectionService, "credentials", lambda *a: None)

    class Denied:
        def verify_folder(self, **kwargs):
            raise FolderAccessLost(kwargs["folder_id"])

    client.app.state.drive_sa_client = Denied()
    responses = [
        client.post(
            f"/data-sources/google-sa/{source_id}/folders/verify?organization_id={tenant}",
            json={"url_or_id": folder},
        )
        for tenant, folder in [
            (org, "absent_123456"),
            (org, "denied_123456"),
            (other, "denied_123456"),
        ]
    ]
    assert [(x.status_code, x.json()) for x in responses] == [
        (404, {"detail": {"code": "not_shared"}})
    ] * 3
    with factory() as session:
        assert session.scalar(select(DriveFolderLink)) is None


def test_link_catalog_scope_and_disconnect(google_api, monkeypatch):
    client, factory, org = prepare(google_api)
    from app.integrations.google_drive_sa_service import DriveSaConnectionService

    monkeypatch.setattr(DriveSaConnectionService, "credentials", lambda *a: None)

    class Client:
        def verify_folder(self, **kwargs):
            item = {
                "id": kwargs["folder_id"],
                "name": "Contracts",
                "mimeType": "application/vnd.google-apps.folder",
                "sharedWithMeTime": "2026-10-14T00:00:00Z",
            }
            return item, item

        def list_folder_files(self, **kwargs):
            return []

    client.app.state.drive_sa_client = Client()
    source_id = client.post(f"/data-sources/google-sa/enable?organization_id={org}").json()[
        "source_id"
    ]
    link = client.post(
        f"/data-sources/google-sa/{source_id}/folders?organization_id={org}",
        json={"folder_id": "folder_123456"},
    )
    assert link.status_code == 200
    assert link.json()["status"] == "verified"
    listing = client.get(f"/data-sources/google-sa/{source_id}/folders?organization_id={org}")
    assert listing.status_code == 200
    assert listing.json()["folders"][0]["link_id"] == link.json()["link_id"]
    catalog = client.get(f"/data-sources/{source_id}/scope-catalog?organization_id={org}")
    assert catalog.status_code == 200
    assert catalog.json()["root_files"]["available"] is False
    assert catalog.json()["folders"][0]["id"] == "folder_123456"
    scope = client.post(
        f"/workspace-folders/selections?organization_id={org}",
        json={"source_id": source_id, "mode": "all_accessible", "uniform_access_confirmed": True},
    )
    assert scope.status_code == 422
    deleted = client.delete(f"/data-sources/{source_id}?organization_id={org}")
    assert deleted.status_code == 204
    with factory() as session:
        assert (
            session.scalar(
                select(GoogleSaIdentity).where(GoogleSaIdentity.organization_id == org)
            ).status
            == "retired"
        )


def test_invalid_link_and_rate_limit_have_stable_codes(google_api, monkeypatch):
    client, _, org = prepare(google_api)
    source_id = client.post(f"/data-sources/google-sa/enable?organization_id={org}").json()[
        "source_id"
    ]
    invalid = client.post(
        f"/data-sources/google-sa/{source_id}/folders/verify?organization_id={org}",
        json={"url_or_id": "x' in parents"},
    )
    assert invalid.status_code == 422
    assert invalid.json() == {"detail": {"code": "invalid_folder_link"}}
    missing = client.post(
        f"/data-sources/google-sa/{source_id}/folders/verify?organization_id={org}", json={}
    )
    assert missing.json() == {"detail": {"code": "invalid_request"}}
    from app.access.ratelimit import InMemoryRateLimiter

    limiter = InMemoryRateLimiter(clock=lambda: 10)
    client.app.state.rate_limiter = limiter
    for _ in range(30):
        limiter.hit(key=f"drive-sa:{org}:verify", limit=30)
    limited = client.post(
        f"/data-sources/google-sa/{source_id}/folders/verify?organization_id={org}",
        json={"url_or_id": "folder_123456"},
    )
    assert limited.status_code == 429
    assert limited.json() == {"detail": {"code": "rate_limited"}}


def test_org_b_robot_cannot_link_org_a_folder(google_api, monkeypatch):
    client, factory, org_a = prepare(google_api)
    org_b = create_organization(client)
    source_a = client.post(f"/data-sources/google-sa/enable?organization_id={org_a}").json()
    source_b = client.post(f"/data-sources/google-sa/enable?organization_id={org_b}").json()
    from app.integrations.google_drive import GoogleCredentials
    from app.integrations.google_drive_sa_service import DriveSaConnectionService

    monkeypatch.setattr(
        DriveSaConnectionService,
        "credentials",
        lambda self, source: GoogleCredentials(source.account_email, None, None),
    )
    calls = []

    class Client:
        def verify_folder(self, credentials, folder_id):
            calls.append((credentials.access_token, folder_id))
            if (
                credentials.access_token != source_a["robot_email"]
                or folder_id != "tenant_a_123456"
            ):
                raise FolderAccessLost(folder_id)
            item = {
                "id": folder_id,
                "name": "A private folder",
                "mimeType": "application/vnd.google-apps.folder",
                "sharedWithMeTime": "2026-10-14T00:00:00Z",
            }
            return item, item

        def list_folder_files(self, **kw):
            return []

    client.app.state.drive_sa_client = Client()
    a = client.post(
        f"/data-sources/google-sa/{source_a['source_id']}/folders?organization_id={org_a}",
        json={"folder_id": "tenant_a_123456"},
    )
    assert a.status_code == 200
    denied = client.post(
        f"/data-sources/google-sa/{source_b['source_id']}/folders?organization_id={org_b}",
        json={"folder_id": "tenant_a_123456"},
    )
    missing = client.post(
        f"/data-sources/google-sa/{source_b['source_id']}/folders?organization_id={org_b}",
        json={"folder_id": "missing_123456"},
    )
    assert denied.status_code == missing.status_code == 404
    assert denied.json() == missing.json() == {"detail": {"code": "not_shared"}}
    assert "A private folder" not in denied.text
    assert calls[-2:] == [
        (source_b["robot_email"], "tenant_a_123456"),
        (source_b["robot_email"], "missing_123456"),
    ]
    with factory() as session:
        assert (
            session.scalar(select(DriveFolderLink).where(DriveFolderLink.organization_id == org_b))
            is None
        )


def test_robot_route_auth_errors_have_stable_code(google_api):
    client, _, _, _ = google_api
    result = client.post(
        "/data-sources/google-sa/enable?organization_id=00000000-0000-0000-0000-000000000001"
    )
    assert result.status_code == 401
    assert result.json() == {"detail": {"code": "unauthenticated"}}


def test_link_works_with_production_session_without_autoflush(google_api, monkeypatch):
    """Regressão E2E local: fonte nasce awaiting_share e a sessão real tem autoflush=False."""
    client, factory, org = prepare(google_api)
    from sqlalchemy.orm import sessionmaker

    from app.integrations.google_drive_sa_service import DriveSaConnectionService

    client.app.state.session_factory = sessionmaker(
        bind=factory.kw["bind"], autoflush=False, expire_on_commit=False
    )
    monkeypatch.setattr(DriveSaConnectionService, "credentials", lambda *a: None)

    class Client:
        def verify_folder(self, **kwargs):
            item = {"id": kwargs["folder_id"], "name": "Contracts",
                    "mimeType": "application/vnd.google-apps.folder", "sharedWithMeTime": "2026-10-14T00:00:00Z"}
            return item, item

        def list_folder_files(self, **kwargs):
            return []

    client.app.state.drive_sa_client = Client()
    source_id = client.post(f"/data-sources/google-sa/enable?organization_id={org}").json()["source_id"]
    link = client.post(f"/data-sources/google-sa/{source_id}/folders?organization_id={org}",
                       json={"folder_id": "folder_123456"})
    assert link.status_code == 200
    assert link.json()["status"] == "verified"


def prepare_on_demand(google_api):
    client, factory, gateway, _ = google_api
    login(client, gateway, code="owner", email="owner@example.test", subject="owner")
    org = create_organization(client)
    from cryptography.fernet import Fernet
    from pydantic import SecretStr

    from app.access.ratelimit import InMemoryRateLimiter

    client.app.state.rate_limiter = InMemoryRateLimiter()
    settings = client.app.state.settings
    settings.google_drive_sa_enabled = True
    settings.google_sa_key_encryption_key = SecretStr(Fernet.generate_key().decode())
    settings.google_sa_pool_projects = "pool-a"
    sent = []
    client.app.state.automation_send_task = lambda name, args: sent.append((name, args))
    return client, factory, org, sent


def test_enable_on_demand_returns_provisioning_then_ready(google_api):
    client, factory, org, sent = prepare_on_demand(google_api)
    first = client.post(f"/data-sources/google-sa/enable?organization_id={org}")
    again = client.post(f"/data-sources/google-sa/enable?organization_id={org}")
    assert first.status_code == 200 and first.json()["status"] == "provisioning"
    assert first.json()["robot_email"] is None and again.json()["source_id"] == first.json()["source_id"]
    assert [name for name, _ in sent] == ["document_intelligence.ingestion.provision_drive_sa_robot"]
    assert sent[0][1] == [first.json()["source_id"]]
    source_id = first.json()["source_id"]
    polled = client.get(f"/data-sources/google-sa/{source_id}/status?organization_id={org}")
    assert polled.json()["status"] == "provisioning"
    blocked = client.get(f"/data-sources/google-sa/{source_id}/inbox?organization_id={org}")
    assert (blocked.status_code, blocked.json()) == (409, {"detail": {"code": "provisioning"}})
    # Worker side (IAM mocked) finishes the job.
    from uuid import UUID

    from app.ingestion.tasks import run_provisioning
    from app.integrations.google_drive_sa import ServiceAccountKeyCipher
    from app.integrations.google_sa_provisioner import RobotProvisioner

    class Iam:
        def create_account(self, project, account_id, name):
            return f"{account_id}@{project}.iam.gserviceaccount.com"

        def create_key(self, email):
            return {"client_email": email, "private_key": "pem", "private_key_id": "k"}

    settings = client.app.state.settings
    with factory() as session:
        cipher = ServiceAccountKeyCipher(settings.google_sa_key_encryption_key.get_secret_value())
        assert run_provisioning(session, settings, UUID(source_id), provisioner=RobotProvisioner(session, settings, Iam(), cipher)) == "ready"
    ready = client.get(f"/data-sources/google-sa/{source_id}/status?organization_id={org}").json()
    assert ready["status"] == "ready" and ready["robot_email"].endswith("@pool-a.iam.gserviceaccount.com")
    final = client.post(f"/data-sources/google-sa/enable?organization_id={org}").json()
    assert final["status"] == "ready" and len(sent) == 1


def test_enable_uses_warm_robot_instantly_and_failed_can_retry(google_api):
    client, factory, org, sent = prepare_on_demand(google_api)
    with factory() as session:
        project = GoogleSaProject(gcp_project_id="pool-a")
        session.add(project)
        session.flush()
        session.add(GoogleSaIdentity(project_id=project.id, sa_email="warm@example.test", encrypted_key="key"))
        session.commit()
    ready = client.post(f"/data-sources/google-sa/enable?organization_id={org}").json()
    assert ready["status"] == "ready" and ready["robot_email"] == "warm@example.test"
    assert [name for name, _ in sent] == ["document_intelligence.ingestion.label_drive_sa_robot"]
    other = create_organization(client)
    pending = client.post(f"/data-sources/google-sa/enable?organization_id={other}").json()
    assert pending["status"] == "provisioning"
    from app.integrations.models import DataSource

    with factory() as session:
        session.get(DataSource, __import__("uuid").UUID(pending["source_id"])).status = "provisioning_failed"
        session.commit()
    assert client.get(f"/data-sources/google-sa/{pending['source_id']}/status?organization_id={other}").json()["status"] == "failed"
    retry = client.post(f"/data-sources/google-sa/enable?organization_id={other}").json()
    assert retry["status"] == "provisioning" and sent[-1][0].endswith("provision_drive_sa_robot")


class TreeClient:
    """Fake robot Drive: `tree` maps folder id -> (name, parent ids); `visible` is what this robot can open."""

    def __init__(self, tree, visible=None, blocked=None):
        self.tree, self.visible, self.blocked = tree, visible, blocked or {}

    def _meta(self, folder_id):
        name, parents = self.tree[folder_id]
        return {
            "id": folder_id,
            "name": name,
            "parents": parents,
            "mimeType": "application/vnd.google-apps.folder",
            "sharedWithMeTime": "2026-10-14T00:00:00Z",
        }

    def verify_folder(self, credentials, folder_id):
        if folder_id not in self.tree or (self.visible is not None and folder_id not in self.visible):
            raise FolderAccessLost(folder_id)
        item = self._meta(folder_id)
        return item, item

    def ancestors(self, credentials, root, max_hops=10):
        chain, current = [], root
        while current.get("parents") and len(chain) < max_hops:
            parent = current["parents"][0]
            if parent not in self.tree:
                break
            current = self._meta(parent)
            chain.append({"id": parent, "name": current["name"]})
        return chain

    def list_folder_files(self, credentials, root_folder_id, root_verified=False):
        from app.integrations.google_drive import RemoteFile

        count = self.blocked.get(root_folder_id, 0)
        return [
            RemoteFile(
                id=f"{root_folder_id}-f{n}", name=f"f{n}.pdf", mime_type="application/pdf",
                source_url="", modified_at=None, can_download=False,
            )
            for n in range(count)
        ]

    def inbox(self, credentials):
        return [
            {**self._meta(x), "sharingUser": {"emailAddress": "boss@example.test"}}
            for x in self.tree
            if self.visible is None or x in self.visible
        ]


def batch_setup(google_api, monkeypatch, tree, **kw):
    client, factory, org = prepare(google_api)
    from app.integrations.google_drive_sa_service import DriveSaConnectionService

    monkeypatch.setattr(DriveSaConnectionService, "credentials", lambda *a: None)
    client.app.state.drive_sa_client = TreeClient(tree, **kw)
    source_id = client.post(f"/data-sources/google-sa/enable?organization_id={org}").json()[
        "source_id"
    ]
    return client, factory, org, source_id


def test_batch_links_many_and_reports_per_folder(google_api, monkeypatch):
    tree = {
        "contracts_0001": ("Contratos", ["root_000000"]),
        "finance_00001": ("Financeiro", []),
        "hr_0000000001": ("RH", []),
    }
    client, factory, org, source_id = batch_setup(
        google_api, monkeypatch, tree, blocked={"hr_0000000001": 2}
    )
    result = client.post(
        f"/data-sources/google-sa/{source_id}/folders/batch?organization_id={org}",
        json={"folder_ids": ["contracts_0001", "finance_00001", "hr_0000000001", "missing_000001"]},
    )
    assert result.status_code == 200
    rows = result.json()["results"]
    assert [x["folder_id"] for x in rows] == [
        "contracts_0001", "finance_00001", "hr_0000000001", "missing_000001",
    ]
    assert [x["status"] for x in rows] == ["ok", "ok", "ok", "error"]
    assert rows[2]["code"] == "download_blocked_partial" and rows[2]["blocked_download_count"] == 2
    assert rows[3]["code"] == "not_shared"
    assert all(x["workspace_folder_id"] for x in rows[:3])
    listing = client.get(f"/data-sources/google-sa/{source_id}/folders?organization_id={org}")
    assert {x["name"] for x in listing.json()["folders"]} == {"Contratos", "Financeiro", "RH"}
    catalog = client.get(f"/data-sources/{source_id}/scope-catalog?organization_id={org}").json()
    parents = {x["id"]: x["parent_ids"] for x in catalog["folders"]}
    assert parents["contracts_0001"] == ["root_000000"] and parents["finance_00001"] == []
    # Idempotent: a second batch is all ok and creates no duplicates.
    again = client.post(
        f"/data-sources/google-sa/{source_id}/folders/batch?organization_id={org}",
        json={"folder_ids": ["finance_00001", "finance_00001"]},
    )
    assert [x["status"] for x in again.json()["results"]] == ["ok"]
    with factory() as session:
        assert len(list(session.scalars(select(DriveFolderLink)))) == 3


def test_batch_nested_folder_is_not_linked_twice(google_api, monkeypatch):
    tree = {
        "parent_000001": ("Parent", []),
        "child_0000001": ("Child", ["parent_000001"]),
        "grand_0000001": ("Grand", ["child_0000001"]),
        "other_0000001": ("Other", []),
    }
    client, factory, org, source_id = batch_setup(google_api, monkeypatch, tree)
    # Child and grandchild listed BEFORE the parent: the parent still wins.
    first = client.post(
        f"/data-sources/google-sa/{source_id}/folders/batch?organization_id={org}",
        json={"folder_ids": ["grand_0000001", "child_0000001", "parent_000001", "other_0000001"]},
    ).json()["results"]
    by_id = {x["folder_id"]: x for x in first}
    assert by_id["parent_000001"]["status"] == "ok" and by_id["other_0000001"]["status"] == "ok"
    for nested in ("grand_0000001", "child_0000001"):
        assert by_id[nested]["status"] == "nested"
        assert by_id[nested]["code"] == "nested_in_linked"
    assert by_id["child_0000001"]["parent_name"] == "Parent"
    assert by_id["grand_0000001"]["parent_name"] == "Parent"
    with factory() as session:
        names = {x.folder_name for x in session.scalars(select(DriveFolderLink))}
    assert names == {"Parent", "Other"}
    # Later single link of a nested folder: stable code + 409.
    single = client.post(
        f"/data-sources/google-sa/{source_id}/folders?organization_id={org}",
        json={"folder_id": "child_0000001"},
    )
    assert single.status_code == 409
    assert single.json()["detail"] == {
        "code": "nested_in_linked", "parent_id": "parent_000001", "parent_name": "Parent",
    }


def test_inbox_exposes_parents_and_nesting(google_api, monkeypatch):
    tree = {
        "parent_000001": ("Parent", []),
        "child_0000001": ("Child", ["parent_000001"]),
        "solo_00000001": ("Solo", ["unknown_00001"]),
    }
    client, _, org, source_id = batch_setup(google_api, monkeypatch, tree)
    rows = {
        x["id"]: x
        for x in client.get(
            f"/data-sources/google-sa/{source_id}/inbox?organization_id={org}"
        ).json()["folders"]
    }
    assert rows["child_0000001"]["parent_ids"] == ["parent_000001"]
    assert rows["child_0000001"]["nested_in"] == {
        "id": "parent_000001", "name": "Parent", "linked": False,
    }
    assert rows["parent_000001"]["nested_in"] is None and rows["solo_00000001"]["nested_in"] is None
    client.post(
        f"/data-sources/google-sa/{source_id}/folders?organization_id={org}",
        json={"folder_id": "parent_000001"},
    )
    rows = {
        x["id"]: x
        for x in client.get(
            f"/data-sources/google-sa/{source_id}/inbox?organization_id={org}"
        ).json()["folders"]
    }
    assert rows["child_0000001"]["nested_in"]["linked"] is True
    assert rows["parent_000001"]["linked"] is True


def test_batch_is_tenant_isolated_and_validated(google_api, monkeypatch):
    tree = {"secret_000001": ("Secret", [])}
    client, factory, _org_a, source_a = batch_setup(google_api, monkeypatch, tree)
    org_b = create_organization(client)
    source_b = client.post(f"/data-sources/google-sa/enable?organization_id={org_b}").json()[
        "source_id"
    ]
    # Org B cannot use org A's source, even with a valid folder id.
    cross = client.post(
        f"/data-sources/google-sa/{source_a}/folders/batch?organization_id={org_b}",
        json={"folder_ids": ["secret_000001"]},
    )
    assert (cross.status_code, cross.json()) == (404, {"detail": {"code": "not_shared"}})
    # Org B's own robot cannot see org A's folder: per-folder not_shared, nothing linked.
    client.app.state.drive_sa_client = TreeClient(tree, visible=set())
    own = client.post(
        f"/data-sources/google-sa/{source_b}/folders/batch?organization_id={org_b}",
        json={"folder_ids": ["secret_000001"]},
    )
    assert own.status_code == 200
    assert own.json()["results"][0]["code"] == "not_shared"
    for body in ({"folder_ids": []}, {"folder_ids": ["x" * 11] * 21}, {}):
        bad = client.post(
            f"/data-sources/google-sa/{source_b}/folders/batch?organization_id={org_b}", json=body
        )
        assert (bad.status_code, bad.json()) == (422, {"detail": {"code": "invalid_request"}})
    with factory() as session:
        assert session.scalar(select(DriveFolderLink)) is None
