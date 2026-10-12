from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from app.audit_usage.models import UsageRecord
from app.audit_usage.service import MONTHLY_LIMITS
from app.automations import executor
from app.automations.executor import execute_run
from app.automations.models import Automation, AutomationRun
from app.automations.schedule import compute_next_run, normalize_trigger_config
from app.automations.triggers import enqueue_due_schedules, enqueue_folder_changed, queue_run
from app.identity.models import User
from app.notifications.models import Notification
from app.organizations.models import Membership, MembershipRole
from tests.api.test_multiscope_questions_api import corpus  # noqa: F401
from tests.api.test_notifications_api import FakeEmail, ScriptedProvider, touch_documents
from tests.api.test_text_search_api import login, search_api  # noqa: F401

WEEKLY = {"frequency": "weekly", "weekday": 0, "hour": 8, "timezone": "America/Sao_Paulo"}


class Sent:
    def __init__(self):
        self.calls = []

    def __call__(self, name, args=None, **_):
        self.calls.append((name, args))


def body(folder_id, **extra):
    return {"name": "Relatório semanal", "trigger_kind": "schedule", "trigger_config": WEEKLY,
            "scope": {"workspace_folder_ids": [str(folder_id)]}, "prompt": "Resuma as campanhas.", **extra}


def create(client, org, folder_id, **extra):
    response = client.post(f"/organizations/{org}/automations", json=body(folder_id, **extra))
    assert response.status_code == 201, response.text
    return response.json()


def add_member(client, factory, gateway, org, email, role=MembershipRole.MEMBER):
    login(client, gateway, code=email, email=email, subject=email)
    with factory.begin() as session:
        user = session.query(User).filter_by(email=email).one()
        session.add(Membership(organization_id=org, user_id=user.id, role=role))
        return str(user.id)


def relogin_owner(client, gateway):
    login(client, gateway, code="owner", email="owner@example.test", subject="owner")


def run_pending(factory, provider, mail=None, status=None):
    with factory.begin() as session:
        ids = [row.id for row in session.query(AutomationRun).filter_by(status="queued")]
    results = []
    for run_id in ids:
        with factory() as session:
            results.append(execute_run(session, run_id, provider=provider, email=mail, app_url="http://app"))
    return results


# --- schedule -----------------------------------------------------------------------------------

def test_next_run_is_computed_in_the_automation_timezone():
    daily = normalize_trigger_config("schedule", {"frequency": "daily", "hour": 9, "timezone": "America/Sao_Paulo"})
    after = datetime(2026, 10, 12, 11, 59, tzinfo=UTC)  # 08:59 in São Paulo (UTC-3)
    assert compute_next_run(daily, after) == datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
    assert compute_next_run(daily, datetime(2026, 10, 12, 12, 0, tzinfo=UTC)) == datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
    weekly = normalize_trigger_config("schedule", WEEKLY)
    assert compute_next_run(weekly, datetime(2026, 10, 12, 12, 0, tzinfo=UTC)) == datetime(2026, 10, 19, 11, 0, tzinfo=UTC)
    monthly = normalize_trigger_config("schedule", {"frequency": "monthly", "day": 5, "hour": 0, "timezone": "UTC"})
    assert compute_next_run(monthly, datetime(2026, 10, 12, 0, 0, tzinfo=UTC)) == datetime(2026, 11, 5, 0, 0, tzinfo=UTC)


def test_trigger_config_validation():
    import pytest

    from app.automations.schedule import InvalidTriggerConfig
    for kind, config in [("schedule", {"frequency": "weekly", "hour": 8}), ("schedule", {"frequency": "daily", "hour": 24}),
                         ("schedule", {"frequency": "daily", "hour": 8, "timezone": "Mars/Base"}),
                         ("schedule", {"frequency": "monthly", "hour": 8, "day": 31}), ("folder_changed", {"hour": 1})]:
        with pytest.raises(InvalidTriggerConfig):
            normalize_trigger_config(kind, config)


def test_tick_queues_due_schedule_once_and_advances(corpus):  # noqa: F811
    client, factory, _, org, folders, _ = corpus
    created = create(client, org, folders["google_drive"])
    assert created["next_run_at"] and created["recipients"][0]["email"] == "owner@example.test"
    now = datetime.now(UTC) + timedelta(days=8)
    sent = Sent()
    with factory() as session:
        assert enqueue_due_schedules(session, send_task=sent, now=now) == {"due": 1, "queued": 1}
    with factory() as session:
        assert enqueue_due_schedules(session, send_task=sent, now=now) == {"due": 0, "queued": 0}  # advanced past now
        automation = session.get(Automation, UUID(created["id"]))
        assert automation.next_run_at.replace(tzinfo=UTC) > now
        # a re-delivered tick for the same planned instant cannot create a second run
        assert queue_run(session, automation, session.query(AutomationRun).one().trigger_ref) is None
    assert len(sent.calls) == 1
    disabled = client.put(f"/organizations/{org}/automations/{created['id']}/enabled", json={"enabled": False}).json()
    assert disabled["next_run_at"] is None


# --- API ----------------------------------------------------------------------------------------

def test_crud_validation_and_limit(corpus):  # noqa: F811
    client, _factory, _gateway, org, folders, _ = corpus
    folder = folders["google_drive"]
    created = create(client, org, folder, output_formats=["email", "pdf"])
    base = f"/organizations/{org}/automations"
    assert client.get(base).json()["limit"] == 20
    patched = client.patch(f"{base}/{created['id']}", json={"name": "Novo nome", "trigger_kind": "folder_changed"}).json()
    assert patched["name"] == "Novo nome" and patched["trigger_config"] == {} and patched["next_run_at"] is None
    assert client.post(base, json=body(folder, output_formats=["sms"])).json()["detail"] == "invalid_output_formats"
    assert client.post(base, json={**body(folder), "trigger_config": {"frequency": "weekly", "hour": 8}}).json()["detail"] == "invalid_trigger_config"
    assert client.post(base, json={**body(folder), "scope": {"workspace_folder_ids": [str(org)]}}).json()["detail"] == "scope_not_allowed"
    assert client.get(f"{base}/{org}").status_code == 404
    assert client.delete(f"{base}/{created['id']}").status_code == 204
    assert client.get(f"{base}/{created['id']}").status_code == 404
    for _ in range(20):
        create(client, org, folder)
    assert client.post(base, json=body(folder)).json()["detail"] == "automation_limit_reached"


def test_only_owner_or_admin_notifies_others_and_sees_all(corpus):  # noqa: F811
    client, factory, gateway, org, folders, _ = corpus
    folder = folders["google_drive"]
    member_id = add_member(client, factory, gateway, org, "member@example.test")
    base = f"/organizations/{org}/automations"
    forbidden = client.post(base, json=body(folder, recipient_user_ids=[str(org)]))
    assert forbidden.status_code == 403 and forbidden.json()["detail"] == "owner or admin required"
    mine = create(client, org, folder)
    relogin_owner(client, gateway)
    assert client.get(base).json()["items"][0]["id"] == mine["id"]  # admin sees the member's automation
    other = create(client, org, folder, recipient_user_ids=[member_id])
    assert {item["user_id"] for item in other["recipients"]} >= {member_id}
    assert client.post(base, json=body(folder, recipient_user_ids=["00000000-0000-0000-0000-000000000001"])).json()["detail"] == "recipient_not_member"
    login(client, gateway, code="member@example.test", email="member@example.test", subject="member@example.test")
    assert [item["id"] for item in client.get(base).json()["items"]] == [mine["id"]]  # member sees only their own
    assert client.get(f"{base}/{other['id']}").status_code == 404
    assert client.delete(f"{base}/{other['id']}").status_code == 404


# --- executor -----------------------------------------------------------------------------------

def test_run_now_delivers_cited_result_pdf_and_email(corpus):  # noqa: F811
    client, factory, gateway, org, folders, base = corpus
    folder = folders["google_drive"]
    member_id = add_member(client, factory, gateway, org, "member@example.test")
    relogin_owner(client, gateway)
    sent = Sent()
    client.app.state.automation_send_task = sent
    created = create(client, org, folder, output_formats=["email", "pdf"], recipient_user_ids=[member_id])
    response = client.post(f"/organizations/{org}/automations/{created['id']}/run")
    assert response.status_code == 202 and response.json()["status"] == "queued" and len(sent.calls) == 1
    mail, provider = FakeEmail(), ScriptedProvider(base)
    assert run_pending(factory, provider, mail) == ["ok"]
    run = client.get(f"/organizations/{org}/automations/{created['id']}/runs/{response.json()['id']}").json()
    assert run["status"] == "ok" and run["questions_used"] == 1 and run["documents_considered"] == 1
    assert run["result"]["citations"][0]["document_name"] == "google_drive campaign.pdf" and run["result"]["notified"] == 2
    assert len(mail.sent) == 2
    notifications = client.get(f"/organizations/{org}/notifications").json()["items"]
    assert notifications[0]["kind"] == "automation_result" and notifications[0]["data"]["pdf_path"].endswith("/pdf")
    pdf = client.get(f"/organizations/{org}/automations/{created['id']}/runs/{run['id']}/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and pdf.headers["content-type"] == "application/pdf"
    assert client.get(f"/organizations/{org}/automations/{created['id']}").json()["last_run"]["status"] == "ok"
    assert len(client.get(f"/organizations/{org}/automations/{created['id']}/runs").json()["items"]) == 1
    with factory() as session:  # a re-delivered task does nothing
        assert execute_run(session, UUID(run["id"]), provider=provider) is None
    assert provider.calls == 1


def test_recipient_without_access_is_skipped_and_recorded(corpus, monkeypatch):  # noqa: F811
    client, factory, gateway, org, folders, base = corpus
    folder = folders["google_drive"]
    member_id = add_member(client, factory, gateway, org, "member@example.test")
    left_id = add_member(client, factory, gateway, org, "left@example.test")
    relogin_owner(client, gateway)
    created = create(client, org, folder, recipient_user_ids=[member_id, left_id])
    with factory.begin() as session:  # one recipient left the organization, another lost folder access
        session.query(Membership).filter_by(user_id=UUID(left_id)).update({"is_active": False})
    real = executor.accessible_folders
    monkeypatch.setattr(executor, "accessible_folders",
                        lambda session, scope, user_id: set() if str(user_id) == member_id else real(session, scope, user_id))
    client.post(f"/organizations/{org}/automations/{created['id']}/run")
    mail = FakeEmail()
    assert run_pending(factory, ScriptedProvider(base), mail) == ["ok"]
    with factory() as session:
        result = session.query(AutomationRun).one().result
        assert result["notified"] == 1
        assert {(item["user_id"], item["reason"]) for item in result["skipped_recipients"]} == {
            (member_id, "no_folder_access"), (left_id, "not_member")}
        assert session.query(Notification).filter_by(kind="automation_result").count() == 1
    assert [item[0] for item in mail.sent] == ["owner@example.test"]


def test_runs_with_creator_permission_not_admin(corpus):  # noqa: F811
    client, factory, gateway, org, folders, base = corpus
    folder = folders["google_drive"]
    creator_id = add_member(client, factory, gateway, org, "member@example.test")
    mine = create(client, org, folder)
    relogin_owner(client, gateway)
    client.post(f"/organizations/{org}/automations/{mine['id']}/run")  # an admin triggers it...
    with factory.begin() as session:  # ...but the creator has since lost access
        session.query(Membership).filter_by(user_id=UUID(creator_id)).update({"is_active": False})
    provider = ScriptedProvider(base)
    assert run_pending(factory, provider) == ["error"]
    with factory() as session:
        run = session.query(AutomationRun).one()
        assert run.error_code == "creator_access_lost" and run.result is None and provider.calls == 0
        assert session.query(Notification).filter_by(kind="automation_failed", user_id=UUID(creator_id)).count() == 1


def test_quota_exhausted_marks_run_and_warns_creator(corpus):  # noqa: F811
    client, factory, _, org, folders, base = corpus
    created = create(client, org, folders["google_drive"])
    now = datetime.now(UTC)
    with factory.begin() as session:
        session.add(UsageRecord(organization_id=org, period_start=date(now.year, now.month, 1), metric="questions",
                                quantity=MONTHLY_LIMITS["questions"]))
    client.post(f"/organizations/{org}/automations/{created['id']}/run")
    provider = ScriptedProvider(base)
    assert run_pending(factory, provider) == ["quota"]
    with factory() as session:
        run = session.query(AutomationRun).one()
        assert run.questions_used == 0 and provider.calls == 0 and session.get(Automation, UUID(created["id"])).last_run_at is None
        assert session.query(Notification).filter_by(kind="automation_quota").count() == 1


# --- folder_changed -----------------------------------------------------------------------------

def test_folder_changed_triggers_once_per_change_and_only_for_scope(corpus):  # noqa: F811
    client, factory, _, org, folders, base = corpus
    drive, notion = folders["google_drive"], folders["notion"]
    created = create(client, org, drive, trigger_kind="folder_changed", trigger_config={})
    sent = Sent()

    def hook(folder):
        with factory() as session:
            return enqueue_folder_changed(session, workspace_folder_id=folder, send_task=sent)

    assert hook(drive)["queued"] == 0  # nothing changed since the automation was created
    touch_documents(factory, drive)
    assert hook(notion)["queued"] == 0  # a sync of a folder outside the scope never triggers it
    assert hook(drive) == {"considered": 1, "queued": 1}
    assert hook(drive)["queued"] == 0  # same change set re-delivered: idempotent by trigger_ref
    assert run_pending(factory, ScriptedProvider(base)) == ["ok"]
    assert hook(drive)["queued"] == 0  # already reported
    touch_documents(factory, drive)
    assert hook(drive)["queued"] == 1  # new change, new run
    with factory() as session:
        refs = [run.trigger_ref for run in session.query(AutomationRun).order_by(AutomationRun.created_at)]
        assert len(set(refs)) == 2 and all(ref.startswith("folder:") for ref in refs)
    assert len(sent.calls) == 2
    client.put(f"/organizations/{org}/automations/{created['id']}/enabled", json={"enabled": False})
    touch_documents(factory, drive)
    assert hook(drive)["queued"] == 0  # disabled automations are ignored


def test_beat_and_hook_wiring():
    from app.ingestion import tasks

    entry = tasks.celery_app.conf.beat_schedule["automations-tick"]
    assert entry["task"] == tasks.automations_tick_task.name and entry["schedule"] == timedelta(minutes=5)
    assert tasks.run_automation_task.name == "document_intelligence.ingestion.run_automation"
    import inspect
    assert "trigger_automations_after_sync(session, settings, job.workspace_folder_id)" in inspect.getsource(tasks.reconcile_workspace_folder)
