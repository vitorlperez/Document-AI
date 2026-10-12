"""Outbound webhooks: SSRF-safe URL checks, HMAC-signed delivery of ``automation.completed`` (specs/automations-api.md)."""
import hashlib
import hmac
import ipaddress
import json
import logging
import socket
from collections.abc import Callable
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.automations.models import Automation, AutomationRun, WebhookDelivery, WebhookEndpoint

logger = logging.getLogger(__name__)
EVENT_COMPLETED = "automation.completed"
EVENTS = (EVENT_COMPLETED,)
DELIVER_TASK = "document_intelligence.ingestion.deliver_webhook"
MAX_ATTEMPTS = 5
BACKOFF_SECONDS = 30
TIMEOUT_SECONDS = 5.0
ANSWER_CHARS = 4000
MAX_URL_CHARS = 2048
RETRYABLE_CODES = {408, 425, 429}


class BlockedDestination(ValueError):
    pass


def new_secret() -> str:
    import secrets
    return f"whsec_{secrets.token_urlsafe(32)}"


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def resolve_host(host: str) -> list[str]:
    return sorted({info[4][0] for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})


def _check_ip(raw: str) -> str:
    ip = ipaddress.ip_address(raw.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if not ip.is_global or ip.is_multicast:  # private, loopback, link-local, reserved, shared, unspecified
        raise BlockedDestination(raw)
    return raw


def validate_destination(url: str, resolver: Callable[[str], list[str]] | None = None) -> tuple[str, list[str]]:
    """Return ``(host, vetted_ips)`` for an https URL or raise ``BlockedDestination``; every resolved address must be public."""
    if len(url) > MAX_URL_CHARS:
        raise BlockedDestination("url too long")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as error:
        raise BlockedDestination("malformed") from error
    host = parts.hostname
    if parts.scheme != "https" or not host or parts.username or parts.password or port not in (None, 443) or parts.fragment:
        raise BlockedDestination("scheme, credentials or port")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        return host, [_check_ip(str(literal))]
    try:
        addresses = (resolver or resolve_host)(host)
    except OSError as error:
        raise BlockedDestination("unresolvable") from error
    if not addresses:
        raise BlockedDestination("unresolvable")
    return host, [_check_ip(item) for item in addresses]


def sign(secret_hash: str, timestamp: str, body: bytes) -> str:
    digest = hmac.new(secret_hash.encode("utf-8"), timestamp.encode("utf-8") + b"." + body, hashlib.sha256).hexdigest()
    return f"v1={digest}"


def send_request(url: str, ip: str, body: bytes, headers: dict[str, str]) -> int:
    """POST to the vetted ``ip`` (so DNS cannot change after validation) keeping Host/SNI/cert checks on the real hostname."""
    parts = urlsplit(url)
    target = f"[{ip}]" if ":" in ip else ip
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    with httpx.Client(timeout=httpx.Timeout(TIMEOUT_SECONDS), follow_redirects=False, trust_env=False) as client:
        response = client.post(f"https://{target}{path}", content=body, headers={**headers, "Host": parts.hostname or ""},
                               extensions={"sni_hostname": parts.hostname})
    return response.status_code


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).astimezone(UTC).isoformat().replace("+00:00", "Z")


def build_payload(delivery: WebhookDelivery, automation: Automation, run: AutomationRun) -> dict[str, object]:
    result = run.result if run.status == "ok" and isinstance(run.result, dict) else {}
    answer = result.get("answer")
    citations = []
    for item in result.get("citations") or []:
        if isinstance(item, dict):
            citations.append({"document_name": item.get("document_name"), "source_url": item.get("source_url"),
                              "page_number": item.get("page_number")})
    return {"id": str(delivery.id), "event": delivery.event, "created_at": _iso(delivery.created_at),
            "organization_id": str(delivery.organization_id),
            "data": {"automation_id": str(automation.id), "automation_name": automation.name, "run_id": str(run.id),
                     "status": run.status, "error_code": run.error_code, "documents_considered": run.documents_considered,
                     "finished_at": _iso(run.finished_at),
                     "answer": answer[:ANSWER_CHARS] if isinstance(answer, str) else None, "citations": citations}}


def enqueue_completed(session: Session, automation: Automation, run: AutomationRun,
                      send_task: Callable[..., object] | None) -> int:
    """Create one pending delivery per active subscribed endpoint (idempotent per run) and dispatch them; never raises."""
    try:
        endpoints = session.scalars(select(WebhookEndpoint).where(
            WebhookEndpoint.organization_id == automation.organization_id, WebhookEndpoint.enabled.is_(True),
            WebhookEndpoint.revoked_at.is_(None))).all()
        created: list[UUID] = []
        for endpoint in endpoints:
            if EVENT_COMPLETED not in (endpoint.events or []):
                continue
            delivery = WebhookDelivery(endpoint_id=endpoint.id, organization_id=endpoint.organization_id, run_id=run.id,
                                       event=EVENT_COMPLETED, status="pending")
            try:
                with session.begin_nested():
                    session.add(delivery)
                    session.flush()
            except IntegrityError:
                continue
            created.append(delivery.id)
        session.commit()
        for delivery_id in created:
            if send_task is not None:
                try:
                    send_task(DELIVER_TASK, args=[str(delivery_id)])
                except Exception:
                    logger.exception("webhook dispatch failed")
        return len(created)
    except Exception:
        logger.exception("webhook enqueue failed")
        session.rollback()
        return 0


def attempt_delivery(session: Session, delivery_id: UUID, *, sender: Callable[..., int] | None = None,
                     resolver: Callable[[str], list[str]] | None = None) -> str:
    """One delivery attempt. Returns ``delivered`` | ``retry`` | ``failed`` | ``skipped`` (nothing to do)."""
    delivery = session.scalar(select(WebhookDelivery).where(WebhookDelivery.id == delivery_id).with_for_update())
    if delivery is None or delivery.status != "pending":
        return "skipped"
    endpoint = session.get(WebhookEndpoint, delivery.endpoint_id)
    run = session.get(AutomationRun, delivery.run_id)
    automation = session.get(Automation, run.automation_id) if run is not None else None
    if endpoint is None or endpoint.revoked_at is not None or not endpoint.enabled or run is None or automation is None:
        delivery.status, delivery.last_error = "failed", "endpoint_inactive"
        session.commit()
        return "failed"
    delivery.attempts += 1
    outcome, error, code = "retry", None, None
    try:
        _host, ips = validate_destination(endpoint.url, resolver)
        body = json.dumps(build_payload(delivery, automation, run), separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        timestamp = str(int(datetime.now(UTC).timestamp()))
        headers = {"Content-Type": "application/json", "User-Agent": "Arquivio-Webhook/1", "X-Arquivio-Event": delivery.event,
                   "X-Arquivio-Delivery": str(delivery.id), "X-Arquivio-Timestamp": timestamp,
                   "X-Arquivio-Signature": sign(endpoint.secret_hash, timestamp, body)}
        code = (sender or send_request)(endpoint.url, ips[0], body, headers)
        if 200 <= code < 300:
            outcome = "delivered"
        else:
            error = f"http_{code}"
            if code < 500 and code not in RETRYABLE_CODES:
                outcome = "failed"
    except BlockedDestination:
        outcome, error = "failed", "blocked_destination"
    except httpx.TimeoutException:
        error = "timeout"
    except Exception:  # noqa: BLE001 - any transport failure is a retryable connection_error; details are never stored
        error = "connection_error"
    if outcome == "retry" and delivery.attempts >= MAX_ATTEMPTS:
        outcome = "failed"
    delivery.last_status_code, delivery.last_error = code, error
    if outcome == "delivered":
        delivery.status, delivery.delivered_at, delivery.last_error = "delivered", datetime.now(UTC), None
    elif outcome == "failed":
        delivery.status = "failed"
    session.commit()
    return outcome


def retry_delay(attempts_done: int) -> int:
    return BACKOFF_SECONDS * 2 ** max(attempts_done - 1, 0)
