"""Bind resend capability to an unexpired pending authentication, not an email."""

import hmac
import time

from fastapi import HTTPException, Request

CONTEXT_COOKIE = "document_intelligence_verification_context"


def _signature(request: Request, token: str, timestamp: str, verification_id: str) -> str:
    configured = request.app.state.settings.auth_proxy_secret
    secret = configured.get_secret_value() if configured else request.app.state.auth_verification_secret
    message = f"verification-context\n{token}\n{timestamp}\n{verification_id}"
    return hmac.new(secret.encode(), message.encode(), "sha256").hexdigest()


def make_verification_context(request: Request, token: str, verification_id: str) -> str:
    timestamp = str(int(time.time()))
    return f"{timestamp}:{verification_id}:{_signature(request, token, timestamp, verification_id)}"


def read_verification_context(request: Request, token: str) -> str:
    try:
        timestamp, verification_id, signature = request.cookies.get(CONTEXT_COOKIE, "").split(":")
        if not timestamp.isdecimal() or len(timestamp) > 12 or not 0 <= time.time() - int(timestamp) <= 600:
            raise ValueError("expired")
        if not verification_id.startswith("email_verification_") or len(verification_id) > 128:
            raise ValueError("invalid")
        if not hmac.compare_digest(_signature(request, token, timestamp, verification_id), signature):
            raise ValueError("invalid")
        return verification_id
    except (ValueError, TypeError):
        raise HTTPException(400, "A confirmação expirou. Entre novamente para receber um novo código.") from None
