from types import SimpleNamespace
from uuid import uuid4

from app.ingestion import tasks


def test_beat_schedule_has_the_weekly_digest() -> None:
    entry = tasks.celery_app.conf.beat_schedule["weekly-what-changed-digest"]
    assert entry["task"] == "document_intelligence.ingestion.weekly_digest"
    assert tasks.weekly_digest_task.name == entry["task"]


def test_followed_refresh_never_fails_a_sync(monkeypatch) -> None:
    class Session:
        rolled_back = False

        def rollback(self):
            self.rolled_back = True

    settings = SimpleNamespace(openai_api_key=SimpleNamespace(get_secret_value=lambda: "k"),
                               resend_api_key=None, invitation_from_email=None, public_app_url="http://x")
    from app.notifications import followed

    def boom(*_a, **_k):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(followed, "refresh_followed_queries", boom)
    session = Session()
    tasks.refresh_followed_after_sync(session, settings, uuid4())  # must not raise
    assert session.rolled_back


def test_followed_refresh_is_skipped_without_an_openai_key() -> None:
    settings = SimpleNamespace(openai_api_key=None)
    tasks.refresh_followed_after_sync(object(), settings, uuid4())
