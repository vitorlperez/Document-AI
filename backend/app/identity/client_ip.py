"""Authenticated frontend context; forwarded headers alone are never trusted."""

import hmac
import time
from ipaddress import ip_address, ip_network

from fastapi import HTTPException, Request


def auth_client_ip(request: Request) -> str:
    settings = request.app.state.settings
    peer = request.client.host if request.client else "unknown"
    secret = settings.auth_proxy_secret
    if not secret:
        # Production custom login must not silently share a proxy's IP bucket.
        if settings.environment != "development":
            raise HTTPException(503, "trusted authentication proxy is not configured")
        return peer
    try:
        peer_ip = ip_address(peer)
        peer_ip = getattr(peer_ip, "ipv4_mapped", None) or peer_ip
        networks = [ip_network(item.strip()) for item in settings.auth_trusted_proxy_cidrs.split(",") if item.strip()]
        if not any(peer_ip in network for network in networks):
            raise ValueError("untrusted peer")
        raw_ip = request.headers["x-auth-client-ip"]
        parsed_ip = ip_address(raw_ip)
        timestamp = request.headers["x-auth-ip-timestamp"]
        if not timestamp.isdecimal() or len(timestamp) > 12 or abs(time.time() - int(timestamp)) > 60:
            raise ValueError("stale context")
        message = f"{timestamp}\n{request.method}\n{request.url.path}\n{raw_ip}"
        expected = hmac.new(secret.get_secret_value().encode(), message.encode(), "sha256").hexdigest()
        if not hmac.compare_digest(expected, request.headers["x-auth-ip-signature"]):
            raise ValueError("invalid context")
        return str(getattr(parsed_ip, "ipv4_mapped", None) or parsed_ip)
    except (KeyError, ValueError, TypeError):
        raise HTTPException(403, "untrusted authentication proxy context") from None
