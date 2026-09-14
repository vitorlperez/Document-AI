import logging

import pytest

from app.core.logging import JsonFormatter


def test_json_logging_does_not_emit_auth_or_invitation_secrets() -> None:
    raw_session = "session-raw-secret"
    invitation_token = "invitation-raw-secret"
    authorization_code = "authorization-code-secret"
    record = logging.makeLogRecord(
        {
            "name": "document_intelligence.auth",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "msg": "authentication completed",
            "args": (),
            "event": "authentication_completed",
            "token": invitation_token,
            "cookie": raw_session,
            "code": authorization_code,
            "email": "person@example.test",
        }
    )

    rendered = JsonFormatter().format(record)

    assert '"event":"authentication_completed"' in rendered
    for sensitive_value in (raw_session, invitation_token, authorization_code, "person@example.test"):
        assert sensitive_value not in rendered


@pytest.mark.parametrize(
    ("action", "result"),
    [
        ("start", "redirected"),
        ("complete", "failed"),
        ("complete", "connected"),
        ("list_folders", "reauth_required"),
    ],
)
def test_google_connection_logs_render_operational_fields_without_oauth_secrets(
    action: str, result: str
) -> None:
    authorization_code = "authorization-code-secret"
    oauth_state = "oauth-state-secret"
    access_token = "google-access-token"
    remote_url = "https://drive.google.com/secret-folder"
    record = logging.makeLogRecord(
        {
            "name": "document_intelligence.integration",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "msg": "google connection operational event",
            "args": (),
            "event": "google_connection",
            "provider": "google_drive",
            "action": action,
            "result": result,
            "elapsed_ms": 12.5,
            "code": authorization_code,
            "state": oauth_state,
            "token": access_token,
            "remote_url": remote_url,
        }
    )

    rendered = JsonFormatter().format(record)

    assert '"event":"google_connection"' in rendered
    assert '"provider":"google_drive"' in rendered
    assert f'"action":"{action}"' in rendered
    assert f'"result":"{result}"' in rendered
    assert '"elapsed_ms":12.5' in rendered
    for sensitive_value in (authorization_code, oauth_state, access_token, remote_url):
        assert sensitive_value not in rendered
