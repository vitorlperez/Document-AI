"""Invariant (g): the scheduler is explicit and has a visible beat_schedule."""

# (g): the beat schedule is visible wherever the tasks module is imported.
def test_beat_schedule_is_defined_on_the_worker_module() -> None:
    from app.ingestion.tasks import celery_app

    schedule = celery_app.conf.beat_schedule
    assert schedule["schedule-connected-source-reconciliation"]["task"] == "document_intelligence.ingestion.schedule"
    assert "purge-extraction-cache" in schedule


def test_compose_runs_a_celery_beat_service() -> None:
    import re
    from pathlib import Path

    compose = (Path(__file__).resolve().parents[3] / "docker-compose.yml").read_text()
    service = re.search(r"^  beat:\n((?:    .*\n|\n)+)", compose, re.MULTILINE)
    assert service is not None
    assert '["celery", "-A", "app.ingestion.tasks", "beat"' in service.group(1)
