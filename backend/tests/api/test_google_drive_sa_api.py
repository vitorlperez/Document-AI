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
