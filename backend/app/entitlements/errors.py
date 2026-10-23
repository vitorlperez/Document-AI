"""Uniform plan/limit error: HTTP 402 (plan, limit, expired) or 403 (account type) with a machine-readable body."""

from __future__ import annotations


class EntitlementError(Exception):
    status_code = 402

    def __init__(
        self, code: str, message: str | None = None, *, limit: int | None = None, used: int | None = None,
        upgrade_to: str | None = None, status_code: int | None = None,
    ) -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code
        self.limit = limit
        self.used = used
        self.upgrade_to = upgrade_to
        if status_code is not None:
            self.status_code = status_code

    def body(self) -> dict[str, object]:
        return {"detail": self.message, "code": self.code, "limit": self.limit, "used": self.used,
                "upgrade_to": self.upgrade_to}


class AccountTypeError(EntitlementError):
    """The account type itself forbids the action (e.g. a personal account cannot have members)."""

    status_code = 403


class BillingNotConfigured(EntitlementError):
    status_code = 501

    def __init__(self) -> None:
        super().__init__("billing_not_configured", "billing is not configured")
