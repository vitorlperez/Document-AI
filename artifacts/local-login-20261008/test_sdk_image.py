# Operational evidence copy: SDK 10.5 public http_client injection, original assertions unchanged.
"""Use the installed SDK with intercepted HTTP; never call a real provider."""

import json

import httpx
import pytest
from workos import WorkOSClient

from app.identity.auth import (
    AuthenticationRateLimited,
    AuthenticationRejected,
    AuthenticationUnavailable,
    HostedAuthenticationRequired,
    WorkOSAuthKitGateway,
)

USER = {
    "object": "user", "id": "user_test", "email": "person@example.test",
    "first_name": None, "last_name": None, "profile_picture_url": None,
    "external_id": None, "last_sign_in_at": None,
    "email_verified": False, "created_at": "2026-10-08T00:00:00Z",
    "updated_at": "2026-10-08T00:00:00Z",
}
RESET = {
    "object": "password_reset", "id": "password_reset_test", "user_id": "user_test",
    "email": "person@example.test", "expires_at": "2026-10-08T01:00:00Z",
    "created_at": "2026-10-08T00:00:00Z", "password_reset_token": "test-token",
    "password_reset_url": "https://app.example.test/login?token=test-token",
}


@pytest.fixture
def sdk_gateway(monkeypatch):
    clients = []
    def make(handler):
        transport_client = httpx.Client(transport=httpx.MockTransport(handler))
        client = WorkOSClient(api_key="test-key", client_id="client_test", max_retries=0, http_client=transport_client)
        clients.append(transport_client)
        gateway = WorkOSAuthKitGateway(api_key="test-key", client_id="client_test", redirect_uri="https://app.example.test/callback")
        monkeypatch.setattr(gateway, "_client", lambda: client)
        return gateway
    yield make
    for client in clients:
        client.close()


@pytest.mark.parametrize("existing", [False, True])
def test_signup_sdk_http_never_transmits_a_password_before_inbox_ownership(sdk_gateway, existing):
    calls = []
    def handler(request):
        calls.append((request.method, request.url.path, json.loads(request.content) if request.content else None))
        if request.method == "GET":
            return httpx.Response(200, json={"data": [USER] if existing else [], "list_metadata": {"before": None, "after": None}})
        if request.url.path == "/user_management/users":
            return httpx.Response(200, json=USER)
        assert request.url.path == "/user_management/password_reset"
        return httpx.Response(200, json=RESET)
    gateway = sdk_gateway(handler)
    assert gateway.register_account(email="person@example.test", ip_address="198.51.100.10", user_agent="test-browser") is None
    assert calls[-1] == ("POST", "/user_management/password_reset", {"email": "person@example.test"})
    assert len(calls) == (2 if existing else 3)
    assert all(body is None or "password" not in body for _, _, body in calls)


def test_pending_authentication_and_resend_use_documented_sdk_resources(sdk_gateway):
    calls = []
    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/user_management/authenticate":
            return httpx.Response(403, json={"code": "email_verification_required", "pending_authentication_token": "test-pending", "email_verification_id": "email_verification_test", "email": USER["email"]})
        if request.url.path == "/user_management/email_verification/email_verification_test":
            return httpx.Response(200, json={"object": "email_verification", "id": "email_verification_test", "user_id": USER["id"], "email": USER["email"], "code": "123456", "expires_at": RESET["expires_at"], "created_at": RESET["created_at"], "updated_at": RESET["created_at"]})
        assert request.url.path == "/user_management/users/user_test/email_verification/send"
        return httpx.Response(200, json={"user": USER})
    gateway = sdk_gateway(handler)
    result = gateway.authenticate_password(email=USER["email"], password="test-password", ip_address=None, user_agent=None)
    assert result.token == "test-pending"
    assert result.verification_id == "email_verification_test"
    gateway.resend_verification(verification_id=result.verification_id)
    assert len(calls) == 3


def test_sdk_429_preserves_actual_retry_after_without_returning_raw_error(sdk_gateway):
    gateway = sdk_gateway(lambda request: httpx.Response(429, headers={"Retry-After": "120"}, json={"message": "private error"}))
    with pytest.raises(AuthenticationRateLimited) as error:
        gateway.request_password_reset(email=USER["email"])
    assert error.value.retry_after == 120
    assert "private" not in str(error.value)


@pytest.mark.parametrize("code,pending", [
    ("radar_email_challenge", True), ("radar_sms_challenge", True),
    ("radar_challenge", False), ("radar_sign_up_challenge", False),
    ("future_challenge", True),
])
@pytest.mark.parametrize("operation", ["password", "verify"])
def test_radar_and_pending_challenges_use_hosted_fallback(sdk_gateway, code, pending, operation):
    body = {"code": code}
    if pending:
        body["pending_authentication_token"] = "private-pending-token"
    gateway = sdk_gateway(lambda request: httpx.Response(403, json=body))
    if operation == "password":
        result = gateway.authenticate_password(email=USER["email"], password="test-password", ip_address=None, user_agent=None)
    else:
        result = gateway.verify_email(token="private-pending-token", code="123456", ip_address=None, user_agent=None)
    assert isinstance(result, HostedAuthenticationRequired)


@pytest.mark.parametrize("status,body,expected", [
    (400, {"code": "invalid_credentials"}, AuthenticationRejected),
    (400, {"error": "invalid_grant", "pending_authentication_token": "private-token"}, AuthenticationRejected),
    (400, {"code": "email_verification_code_invalid", "pending_authentication_token": "private-token"}, AuthenticationRejected),
    (400, {"code": "invalid_credentials", "pending_authentication_token": "private-token"}, AuthenticationRejected),
    (403, {"code": "unknown_error"}, AuthenticationRejected),
    (429, {"code": "radar_email_challenge", "pending_authentication_token": "private-token"}, AuthenticationRateLimited),
    (503, {"code": "radar_email_challenge", "pending_authentication_token": "private-token"}, AuthenticationUnavailable),
])
def test_credentials_and_outages_remain_errors_even_with_pending_context(sdk_gateway, status, body, expected):
    gateway = sdk_gateway(lambda request: httpx.Response(status, json=body))
    with pytest.raises(expected) as error:
        gateway.authenticate_password(email=USER["email"], password="test-password", ip_address=None, user_agent=None)
    assert "private" not in str(error.value)
