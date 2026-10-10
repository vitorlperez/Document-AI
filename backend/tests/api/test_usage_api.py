from datetime import UTC, date, datetime
from uuid import uuid4

from app.audit_usage.models import UsageRecord
from app.audit_usage.service import ACTIVE_DOCUMENT_LIMIT, MONTHLY_LIMITS
from app.identity.models import User
from app.organizations.models import Membership, MembershipRole
from tests.api.test_multiscope_questions_api import corpus  # noqa: F401
from tests.api.test_text_search_api import login, search_api  # noqa: F401


def test_usage_panel_reports_levels_for_admin(corpus):  # noqa: F811
    client, factory, _, org, _, _ = corpus
    now = datetime.now(UTC)
    with factory.begin() as session:
        session.add(UsageRecord(organization_id=org, period_start=date(now.year, now.month, 1),
                                metric="questions", quantity=int(MONTHLY_LIMITS["questions"] * 0.85)))
        session.add(UsageRecord(organization_id=org, period_start=date(now.year, now.month, 1),
                                metric="ocr_pages", quantity=MONTHLY_LIMITS["ocr_pages"]))
    body = client.get(f"/organizations/{org}/usage").json()
    rows = {row["metric"]: row for row in body["metrics"]}
    assert rows["questions"]["level"] == "warning"
    assert rows["ocr_pages"]["level"] == "exceeded"
    assert rows["embedding_tokens"]["level"] == "ok"
    assert rows["questions"]["limit"] == MONTHLY_LIMITS["questions"]
    assert body["active_documents"]["limit"] == ACTIVE_DOCUMENT_LIMIT
    assert body["active_documents"]["used"] == 2


def test_usage_panel_denies_plain_member_and_foreign_org(corpus):  # noqa: F811
    client, factory, gateway, org, _, _ = corpus
    assert client.get(f"/organizations/{uuid4()}/usage").status_code == 403
    login(client, gateway, code="m", email="m@example.test", subject="m")
    with factory.begin() as session:
        user = session.query(User).filter_by(email="m@example.test").one()
        session.add(Membership(organization_id=org, user_id=user.id, role=MembershipRole.MEMBER))
    assert client.get(f"/organizations/{org}/usage").status_code == 403
