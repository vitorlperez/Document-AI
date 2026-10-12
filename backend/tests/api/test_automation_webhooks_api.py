import hashlib
import hmac
import json
from uuid import UUID

import httpx
import pytest

from app.automations import webhooks
from app.automations.executor import execute_run
from app.automations.models import AutomationRun, WebhookDelivery, WebhookEndpoint
from app.automations.webhooks import BlockedDestination, attempt_delivery, validate_destination
from app.organizations.models import MembershipRole
from tests.api.test_automations_api import (  # noqa: F401
    Sent,
    add_member,
    create,
    relogin_owner,
    run_pending,
)
from tests.api.test_multiscope_questions_api import corpus  # noqa: F401
from tests.api.test_notifications_api import ScriptedProvider
from tests.api.test_text_search_api import login, search_api  # noqa: F401

PUBLIC_IP = "93.184.216.34"
URL = "https://hooks.example.test/arquivio"


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr(webhooks, "resolve_host", lambda host: [PUBLIC_IP])


def endpoints_url(org):
    return f"/organizations/{org}/webhook-endpoints"


def make_endpoint(client, org, **extra):
    response = client.post(endpoints_url(org), json={"url": URL, **extra})
    assert response.status_code == 201, response.text
    return response.json()


class FakeSender:
    def __init__(self, *codes):
        self.codes = list(codes)
        self.calls = []

    def __call__(self, url, ip, body, headers):
        self.calls.append((url, ip, body, headers))
        code = self.codes.pop(0) if self.codes else 200
        if isinstance(code, Exception):
            raise code
        return code


def finished_run(client, factory, org, folder, base, send):
    created = create(client, org, folder)
    client.app.state.automation_send_task = Sent()
    client.post(f"/organizations/{org}/automations/{created['id']}/run")
    with factory.begin() as session:
        run_id = session.query(AutomationRun).one().id
    with factory() as session:
        assert execute_run(session, run_id, provider=ScriptedProvider(base), send_task=send) == "ok"
    return run_id


# --- recipient catalog ---------------------------------------------------------------------------

def test_recipient_catalog_lists_members_with_folder_access(corpus, monkeypatch):  # noqa: F811
    client, factory, gateway, org, folders, _ = corpus
    folder = folders["google_drive"]
    member_id = add_member(client, factory, gateway, org, "member@example.test")
    blocked_id = add_member(client, factory, gateway, org, "blocked@example.test")
    gone_id = add_member(client, factory, gateway, org, "gone@example.test")
    from app.organizations.models import Membership
    with factory.begin() as session:
        session.query(Membership).filter_by(user_id=UUID(gone_id)).update({"is_active": False})
    from app.api import automations as api
    real = api.accessible_folders
    monkeypatch.setattr(api, "accessible_folders",
                        lambda session, scope, user_id: set() if str(user_id) == blocked_id else real(session, scope, user_id))
    login(client, gateway, code="member@example.test", email="member@example.test", subject="member@example.test")
    denied = client.get(f"/organizations/{org}/automation-recipients")
    assert denied.status_code == 403 and denied.json()["detail"] == "owner or admin required"
    relogin_owner(client, gateway)
    url = f"/organizations/{org}/automation-recipients"
    items = {item["email"]: item for item in client.get(url, params={"workspace_folder_ids": [str(folder)]}).json()["items"]}
    assert set(items) == {"owner@example.test", "member@example.test", "blocked@example.test"}  # inactive member hidden
    assert items["owner@example.test"]["is_you"] is True and items["owner@example.test"]["role"] == "owner"
    assert items["member@example.test"] == {"user_id": member_id, "name": "member", "email": "member@example.test",
                                            "role": "member", "has_access": True, "is_you": False}
    assert items["blocked@example.test"]["has_access"] is False
    assert all(item["has_access"] is None for item in client.get(url).json()["items"])
    assert client.get(url, params={"workspace_folder_ids": [str(org)]}).json()["detail"] == "scope_not_allowed"


def test_recipient_catalog_hides_other_organizations_members(corpus):  # noqa: F811
    client, factory, gateway, org, _folders, _ = corpus
    from app.organizations.models import Organization
    add_member(client, factory, gateway, org, "admin2@example.test", role=MembershipRole.ADMIN)
    with factory.begin() as session:
        other = Organization(name="Outra")
        session.add(other)
    relogin_owner(client, gateway)
    emails = {item["email"] for item in client.get(f"/organizations/{org}/automation-recipients").json()["items"]}
    assert emails == {"owner@example.test", "admin2@example.test"}


# --- SSRF ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "http://hooks.example.test/x", "ftp://hooks.example.test/x", "https://user:pw@hooks.example.test/x",
    "https://hooks.example.test:8443/x", "https://127.0.0.1/x", "https://[::1]/x", "https://10.0.0.5/x",
    "https://192.168.1.1/x", "https://172.16.0.1/x", "https://169.254.169.254/latest/meta-data", "https://[fe80::1]/x",
    "https://[fd00::1]/x", "https://0.0.0.0/x", "https://[::ffff:127.0.0.1]/x", "https://100.64.0.1/x", "https:///x", "not a url",
    "https://hooks.example.test/x#frag",
])
def test_validate_destination_blocks_unsafe_urls(url):
    with pytest.raises(BlockedDestination):
        validate_destination(url, resolver=lambda host: [PUBLIC_IP])


def test_validate_destination_checks_every_resolved_address():
    assert validate_destination(URL, resolver=lambda host: [PUBLIC_IP]) == ("hooks.example.test", [PUBLIC_IP])
    assert validate_destination("https://[2606:4700::1111]/x")[1] == ["2606:4700::1111"]
    for answer in (["127.0.0.1"], [PUBLIC_IP, "10.1.2.3"], ["::1"], ["169.254.0.1"], []):
        with pytest.raises(BlockedDestination):
            validate_destination(URL, resolver=lambda host, answer=answer: answer)

    def boom(host):
        raise OSError("nxdomain")
    with pytest.raises(BlockedDestination):
        validate_destination(URL, resolver=boom)


# --- endpoint CRUD -----------------------------------------------------------------------------------

def test_endpoint_crud_is_admin_only_and_secret_shown_once(corpus):  # noqa: F811
    client, factory, gateway, org, _folders, _ = corpus
    base = endpoints_url(org)
    created = make_endpoint(client, org)
    assert created["secret"].startswith("whsec_") and created["events"] == ["automation.completed"] and created["enabled"]
    assert "secret" not in client.get(base).json()["items"][0] and client.get(base).json()["limit"] == 5
    with factory() as session:
        row = session.get(WebhookEndpoint, UUID(created["id"]))
        assert row.secret_hash == hashlib.sha256(created["secret"].encode()).hexdigest() and created["secret"] not in row.secret_hash
    for url in ("http://hooks.example.test/x", "https://127.0.0.1/x", "https://hooks.example.test:444/x"):
        assert client.post(base, json={"url": url}).json()["detail"] == "invalid_webhook_url"
    assert client.post(base, json={"url": URL, "events": ["automation.deleted"]}).json()["detail"] == "invalid_webhook_events"
    assert client.patch(f"{base}/{created['id']}", json={"url": "https://10.0.0.1/x"}).json()["detail"] == "invalid_webhook_url"
    patched = client.patch(f"{base}/{created['id']}", json={"enabled": False, "url": "https://other.example.test/h"}).json()
    assert patched["enabled"] is False and patched["url"] == "https://other.example.test/h" and "secret" not in patched
    rotated = client.post(f"{base}/{created['id']}/rotate-secret").json()
    assert rotated["secret"] != created["secret"]
    with factory() as session:
        assert session.get(WebhookEndpoint, UUID(created["id"])).secret_hash == hashlib.sha256(rotated["secret"].encode()).hexdigest()

    add_member(client, factory, gateway, org, "member@example.test")
    for method, path, kwargs in [("get", base, {}), ("post", base, {"json": {"url": URL}}),
                                 ("patch", f"{base}/{created['id']}", {"json": {"enabled": True}}),
                                 ("post", f"{base}/{created['id']}/rotate-secret", {}), ("delete", f"{base}/{created['id']}", {}),
                                 ("get", f"{base}/{created['id']}/deliveries", {})]:
        denied = getattr(client, method)(path, **kwargs)
        assert denied.status_code == 403 and denied.json()["detail"] == "owner or admin required", (method, path)
    relogin_owner(client, gateway)

    assert client.delete(f"{base}/{created['id']}").status_code == 204
    assert client.delete(f"{base}/{created['id']}").status_code == 204  # idempotent
    listed = client.get(base).json()["items"][0]
    assert listed["revoked_at"] and listed["enabled"] is False
    assert client.patch(f"{base}/{created['id']}", json={"enabled": True}).json()["detail"] == "webhook_revoked"
    assert client.post(f"{base}/{created['id']}/rotate-secret").status_code == 409
    assert client.get(f"{base}/{org}/deliveries").status_code == 404


def test_active_endpoint_limit_ignores_revoked(corpus):  # noqa: F811
    client, _factory, _gateway, org, _folders, _ = corpus
    first = [make_endpoint(client, org) for _ in range(5)]
    assert client.post(endpoints_url(org), json={"url": URL}).json()["detail"] == "webhook_limit_reached"
    client.delete(f"{endpoints_url(org)}/{first[0]['id']}")
    make_endpoint(client, org)


# --- delivery ------------------------------------------------------------------------------------------

def test_completed_run_enqueues_one_signed_delivery_per_subscribed_endpoint(corpus):  # noqa: F811
    client, factory, _gateway, org, folders, base = corpus
    endpoint = make_endpoint(client, org)
    make_endpoint(client, org, enabled=False)
    revoked = make_endpoint(client, org)
    client.delete(f"{endpoints_url(org)}/{revoked['id']}")
    send = Sent()
    run_id = finished_run(client, factory, org, folders["google_drive"], base, send)
    assert [call[0] for call in send.calls] == ["document_intelligence.ingestion.deliver_webhook"]
    with factory() as session:
        delivery = session.query(WebhookDelivery).one()
        assert (delivery.endpoint_id, delivery.run_id, delivery.status) == (UUID(endpoint["id"]), run_id, "pending")
        assert send.calls[0][1] == [str(delivery.id)]
        sender = FakeSender(204)
        assert attempt_delivery(session, delivery.id, sender=sender) == "delivered"
        url, ip, raw, headers = sender.calls[0]
        assert (url, ip) == (URL, PUBLIC_IP)
        key = hashlib.sha256(endpoint["secret"].encode()).hexdigest().encode()
        expected = hmac.new(key, headers["X-Arquivio-Timestamp"].encode() + b"." + raw, hashlib.sha256).hexdigest()
        assert headers["X-Arquivio-Signature"] == f"v1={expected}"
        assert headers["X-Arquivio-Event"] == "automation.completed" and headers["X-Arquivio-Delivery"] == str(delivery.id)
        payload = json.loads(raw)
        assert payload["id"] == str(delivery.id) and payload["event"] == "automation.completed" and payload["organization_id"] == str(org)
        data = payload["data"]
        assert data["run_id"] == str(run_id) and data["status"] == "ok" and data["answer"] and data["error_code"] is None
        assert data["citations"][0]["document_name"] == "google_drive campaign.pdf" and "excerpt" not in data["citations"][0]
        session.refresh(delivery)
        assert (delivery.status, delivery.attempts, delivery.last_error) == ("delivered", 1, None) and delivery.delivered_at
        assert attempt_delivery(session, delivery.id, sender=sender) == "skipped" and len(sender.calls) == 1
    listed = client.get(f"{endpoints_url(org)}/{endpoint['id']}/deliveries").json()["items"]
    assert [(item["status"], item["attempts"], item["last_error"]) for item in listed] == [("delivered", 1, None)]
    by_id = {item["id"]: item for item in client.get(endpoints_url(org)).json()["items"]}
    assert by_id[endpoint["id"]]["last_delivery"]["status"] == "delivered"


def test_endpoint_not_subscribed_gets_nothing_and_enqueue_is_idempotent(corpus):  # noqa: F811
    client, factory, _gateway, org, folders, base = corpus
    endpoint = make_endpoint(client, org)
    with factory.begin() as session:
        session.get(WebhookEndpoint, UUID(endpoint["id"])).events = []
    send = Sent()
    run_id = finished_run(client, factory, org, folders["google_drive"], base, send)
    assert send.calls == []
    with factory.begin() as session:
        session.get(WebhookEndpoint, UUID(endpoint["id"])).events = ["automation.completed"]
        from app.automations.models import Automation
        run = session.get(AutomationRun, run_id)
        automation = session.get(Automation, run.automation_id)
        assert webhooks.enqueue_completed(session, automation, run, send) == 1
        assert webhooks.enqueue_completed(session, automation, run, send) == 0
    assert len(send.calls) == 1


def test_retry_backoff_and_final_failure(corpus):  # noqa: F811
    client, factory, _gateway, org, folders, base = corpus
    make_endpoint(client, org)
    run_id = finished_run(client, factory, org, folders["google_drive"], base, None)
    with factory() as session:
        delivery_id = session.query(WebhookDelivery).one().id
        sender = FakeSender(500, httpx.ReadTimeout("slow"), 429, OSError("reset"), 503)
        outcomes = [attempt_delivery(session, delivery_id, sender=sender) for _ in range(5)]
        assert outcomes == ["retry", "retry", "retry", "retry", "failed"]
        delivery = session.get(WebhookDelivery, delivery_id)
        assert (delivery.status, delivery.attempts, delivery.last_error, delivery.last_status_code) == ("failed", 5, "http_503", 503)
        assert attempt_delivery(session, delivery_id, sender=sender) == "skipped"
    assert [webhooks.retry_delay(n) for n in range(1, 5)] == [30, 60, 120, 240]
    assert run_id


def test_timeout_and_connection_errors_are_recorded_as_codes(corpus):  # noqa: F811
    client, factory, _gateway, org, folders, base = corpus
    make_endpoint(client, org)
    finished_run(client, factory, org, folders["google_drive"], base, None)
    with factory() as session:
        delivery_id = session.query(WebhookDelivery).one().id
        assert attempt_delivery(session, delivery_id, sender=FakeSender(httpx.ConnectTimeout("t"))) == "retry"
        assert session.get(WebhookDelivery, delivery_id).last_error == "timeout"
        assert attempt_delivery(session, delivery_id, sender=FakeSender(RuntimeError("secret detail"))) == "retry"
        assert session.get(WebhookDelivery, delivery_id).last_error == "connection_error"
        assert attempt_delivery(session, delivery_id, sender=FakeSender(200)) == "delivered"
        assert session.get(WebhookDelivery, delivery_id).last_error is None


def test_client_errors_do_not_retry(corpus):  # noqa: F811
    client, factory, _gateway, org, folders, base = corpus
    make_endpoint(client, org)
    finished_run(client, factory, org, folders["google_drive"], base, None)
    with factory() as session:
        delivery_id = session.query(WebhookDelivery).one().id
        assert attempt_delivery(session, delivery_id, sender=FakeSender(404)) == "failed"
        delivery = session.get(WebhookDelivery, delivery_id)
        assert (delivery.status, delivery.attempts, delivery.last_error) == ("failed", 1, "http_404")


def test_dns_rebinding_to_private_address_is_blocked_at_delivery(corpus, monkeypatch):  # noqa: F811
    client, factory, _gateway, org, folders, base = corpus
    make_endpoint(client, org)
    finished_run(client, factory, org, folders["google_drive"], base, None)
    monkeypatch.setattr(webhooks, "resolve_host", lambda host: ["169.254.169.254"])
    sender = FakeSender(200)
    with factory() as session:
        delivery_id = session.query(WebhookDelivery).one().id
        assert attempt_delivery(session, delivery_id, sender=sender) == "failed"
        delivery = session.get(WebhookDelivery, delivery_id)
        assert (delivery.status, delivery.last_error, delivery.attempts) == ("failed", "blocked_destination", 1)
    assert sender.calls == []


def test_revoked_endpoint_cancels_pending_deliveries(corpus):  # noqa: F811
    client, factory, _gateway, org, folders, base = corpus
    endpoint = make_endpoint(client, org)
    finished_run(client, factory, org, folders["google_drive"], base, None)
    client.delete(f"{endpoints_url(org)}/{endpoint['id']}")
    with factory() as session:
        delivery = session.query(WebhookDelivery).one()
        assert (delivery.status, delivery.last_error) == ("failed", "endpoint_inactive")
        sender = FakeSender(200)
        assert attempt_delivery(session, delivery.id, sender=sender) == "skipped" and sender.calls == []


def test_webhook_failure_never_fails_the_run(corpus, monkeypatch):  # noqa: F811
    client, factory, _gateway, org, folders, base = corpus
    make_endpoint(client, org)

    def broken(*_args, **_kwargs):
        raise RuntimeError("queue down")
    send = broken
    run_id = finished_run(client, factory, org, folders["google_drive"], base, send)
    with factory() as session:
        assert session.get(AutomationRun, run_id).status == "ok"
        assert session.query(WebhookDelivery).one().status == "pending"


def test_task_and_retry_wiring_registered():
    from app.ingestion.tasks import celery_app
    task = celery_app.tasks["document_intelligence.ingestion.deliver_webhook"]
    assert task.max_retries == 4 and webhooks.MAX_ATTEMPTS == task.max_retries + 1
    assert webhooks.DELIVER_TASK in celery_app.tasks
