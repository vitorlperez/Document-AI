from datetime import UTC, date, datetime, timedelta

from app.audit_usage.models import SavedQuery, UsageRecord
from app.audit_usage.service import monthly_limits
from app.identity.models import User
from app.knowledge.models import Document
from app.notifications.digest import send_weekly_digests
from app.notifications.followed import refresh_followed_queries
from app.notifications.models import Notification
from app.organizations.delivery import ResendEmailDelivery
from app.organizations.models import Membership, MembershipRole
from tests.api.test_multiscope_questions_api import ask, corpus  # noqa: F401
from tests.api.test_text_search_api import login, search_api  # noqa: F401


class FakeEmail:
    def __init__(self):
        self.sent = []
        self.texts = []

    def send_email(self, *, recipient, subject, html, text=None):
        self.sent.append((recipient, subject, html))
        self.texts.append(text)
        return True


class ScriptedProvider:
    """Wraps the fixture provider so tests can change the answer text between runs."""

    def __init__(self, inner):
        self.inner = inner
        self.text = "The campaign launches in September."
        self.calls = 0

    def embed(self, *, texts):
        return self.inner.embed(texts=texts)

    def answer(self, *, question, evidence):
        from app.knowledge.questions import GeneratedAnswer
        self.calls += 1
        return GeneratedAnswer(self.text, list(range(1, len(evidence) + 1)))

    def summarize_documents(self, *, question, evidence):
        self.calls += 1
        return []

    def assess_summary(self, *, claims, evidence):
        return []


def make_followed(client, org, folder_id):
    created = client.post(f"/workspace-folders/{folder_id}/saved-queries?organization_id={org}",
                          json={"name": "Lançamento", "query": "When does the campaign launch?"})
    assert created.status_code == 201 and created.json()["followed"] is False
    saved_id = created.json()["id"]
    followed = client.put(f"/saved-queries/{saved_id}/follow?organization_id={org}", json={"followed": True})
    assert followed.status_code == 200 and followed.json()["followed"] is True
    return saved_id


def touch_documents(factory, folder_id):
    with factory.begin() as session:
        session.query(Document).filter_by(workspace_folder_id=folder_id).update(
            {"indexed_at": datetime.now(UTC) + timedelta(hours=1)})


def test_followed_query_notifies_only_when_answer_changes(corpus):  # noqa: F811
    client, factory, _, org, folders, base = corpus
    folder = folders["google_drive"]
    provider = ScriptedProvider(base)
    make_followed(client, org, folder)
    mail = FakeEmail()

    def run():
        with factory.begin() as session:
            return refresh_followed_queries(session, workspace_folder_id=folder, provider=provider, email=mail)

    assert run()["rerun"] == 0 and provider.calls == 0  # nothing changed in the scope: no model call
    touch_documents(factory, folder)
    assert run() == {"considered": 1, "rerun": 1, "notified": 0}  # baseline only
    touch_documents(factory, folder)
    assert run()["notified"] == 0  # same answer stays silent
    provider.text = "The launch was moved to November; see the updated plan."
    touch_documents(factory, folder)
    assert run()["notified"] == 1
    body = client.get(f"/organizations/{org}/notifications").json()
    assert body["unread"] == 1
    item = body["items"][0]
    assert item["kind"] == "followed_query_changed" and "November" in item["body"]
    assert item["data"]["citations"][0]["document_name"] == "google_drive campaign.pdf"
    assert len(mail.sent) == 1 and "November" in mail.sent[0][2]


def test_followed_query_respects_question_quota(corpus):  # noqa: F811
    client, factory, _, org, folders, base = corpus
    folder = folders["google_drive"]
    provider = ScriptedProvider(base)
    make_followed(client, org, folder)
    now = datetime.now(UTC)
    with factory.begin() as session:
        session.add(UsageRecord(organization_id=org, period_start=date(now.year, now.month, 1),
                                metric="questions", quantity=monthly_limits()["questions"]))
    touch_documents(factory, folder)
    with factory.begin() as session:
        counts = refresh_followed_queries(session, workspace_folder_id=folder, provider=provider)
    assert counts["notified"] == 0 and provider.calls == 0
    with factory() as session:
        assert session.query(Notification).count() == 0
        assert session.query(SavedQuery).one().last_answer is None


def test_notification_endpoints_read_state_and_email_preference(corpus):  # noqa: F811
    client, factory, _gateway, org, _, _ = corpus
    assert client.get(f"/organizations/{org}/notification-preferences").json() == {"email_enabled": True}
    assert client.put(f"/organizations/{org}/notification-preferences", json={"email_enabled": False}).json() == {"email_enabled": False}
    with factory.begin() as session:
        user = session.query(User).one()
        from app.core.scoping import OrganizationScope
        from app.notifications.service import NotificationService
        mail = FakeEmail()
        service = NotificationService(session)
        service.notify(scope=OrganizationScope(org), user_id=user.id, kind="x", title="A", body="b", data={}, email=mail)
        service.notify(scope=OrganizationScope(org), user_id=user.id, kind="x", title="B", body="b", data={})
        assert mail.sent == []  # opted out of e-mail, still gets the in-app copy
    body = client.get(f"/organizations/{org}/notifications").json()
    assert body["unread"] == 2
    first = body["items"][0]["id"]
    assert client.post(f"/organizations/{org}/notifications/read", json={"ids": [first]}).json() == {"unread": 1}
    assert client.post(f"/organizations/{org}/notifications/read", json={}).json() == {"unread": 0}


def test_notifications_are_private_to_their_member(corpus):  # noqa: F811
    client, factory, gateway, org, _, _ = corpus
    with factory.begin() as session:
        from app.core.scoping import OrganizationScope
        from app.notifications.service import NotificationService
        user = session.query(User).one()
        NotificationService(session).notify(scope=OrganizationScope(org), user_id=user.id, kind="x", title="Mine", body="", data={})
    login(client, gateway, code="other", email="other@example.test", subject="other")
    with factory.begin() as session:
        other = session.query(User).filter_by(email="other@example.test").one()
        session.add(Membership(organization_id=org, user_id=other.id, role=MembershipRole.MEMBER))
    assert client.get(f"/organizations/{org}/notifications").json() == {"unread": 0, "items": []}


def test_weekly_digest_on_demand_and_scheduled_send_once(corpus):  # noqa: F811
    client, factory, _, org, folders, base = corpus
    client.app.state.semantic_provider = ScriptedProvider(base)
    touch_documents(factory, folders["google_drive"])
    with factory.begin() as session:  # only one folder changed in the week
        session.query(Document).filter_by(workspace_folder_id=folders["notion"]).update(
            {"indexed_at": datetime.now(UTC) - timedelta(days=30), "modified_at": datetime.now(UTC) - timedelta(days=30)})
    digest = client.post(f"/organizations/{org}/digest/weekly").json()
    assert [s["workspace_folder_id"] for s in digest["sections"]] == [str(folders["google_drive"])]
    assert digest["sections"][0]["citations"]
    mail = FakeEmail()
    provider = ScriptedProvider(base)
    with factory.begin() as session:
        counts = send_weekly_digests(session, provider=provider, email=mail, now=datetime.now(UTC))
    assert counts["notified"] == 1 and len(mail.sent) == 1
    with factory.begin() as session:
        assert send_weekly_digests(session, provider=provider, email=mail, now=datetime.now(UTC))["notified"] == 0
    assert client.get(f"/organizations/{org}/notifications").json()["items"][0]["kind"] == "weekly_digest"


def test_weekly_digest_sends_nothing_when_nothing_changed(corpus):  # noqa: F811
    client, factory, _, org, _, base = corpus
    old = datetime.now(UTC) - timedelta(days=30)
    with factory.begin() as session:
        session.query(Document).update({"indexed_at": old, "modified_at": old})
    mail = FakeEmail()
    with factory.begin() as session:
        assert send_weekly_digests(session, provider=ScriptedProvider(base), email=mail)["notified"] == 0
    assert mail.sent == []
    assert client.post(f"/organizations/{org}/digest/weekly").json()["sections"] == []


def test_email_delivery_without_resend_key_is_a_noop():
    assert ResendEmailDelivery(api_key=None, from_email=None).send_email(recipient="a@b.test", subject="s", html="h") is False
