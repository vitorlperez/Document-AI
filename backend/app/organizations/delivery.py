"""Outbound invitation delivery boundary."""

import logging
from typing import Protocol

import requests
import resend
from resend.exceptions import ResendError

logger = logging.getLogger(__name__)


class InvitationDeliveryUnavailable(RuntimeError):
    """The invitation e-mail could not be handed to the provider."""


class InvitationDeliveryPort(Protocol):
    def send(self, *, recipient: str, invitation_url: str) -> None: ...


class ResendInvitationDelivery:
    def __init__(self, *, api_key: str | None, from_email: str | None):
        self.api_key = api_key
        self.from_email = from_email

    def send(self, *, recipient: str, invitation_url: str) -> None:
        if not self.api_key or not self.from_email:
            raise RuntimeError("invitation delivery is not configured")
        resend.api_key = self.api_key
        try:
            resend.Emails.send(
                {
                    "from": self.from_email,
                    "to": [recipient],
                    "subject": "Você foi convidado para o Document Intelligence",
                    "html": f'<p>Você recebeu um convite.</p><p><a href="{invitation_url}">Aceitar convite</a></p>',
                }
            )
        except requests.RequestException as error:
            logger.error("invitation delivery transport failure: %s", type(error).__name__)
            raise InvitationDeliveryUnavailable("invitation delivery transport failure") from error
        except ResendError as error:
            # Provider rejections (unverified sender domain, sandbox sender, bad key, quota)
            # are operational failures, not server bugs: surface them as 503 without the token.
            logger.error("invitation delivery rejected by provider: code=%s type=%s", error.code, error.error_type)
            raise InvitationDeliveryUnavailable("invitation delivery rejected by provider") from error


class EmailDeliveryPort(Protocol):
    def send_email(self, *, recipient: str, subject: str, html: str, text: str | None = None) -> bool: ...


class ResendEmailDelivery:
    """Generic transactional e-mail on the same Resend boundary as invitations.

    Without a key or sender (local development) it logs and returns False; a provider
    failure is logged and returned as False so notifications never break a sync or job.
    """

    def __init__(self, *, api_key: str | None, from_email: str | None):
        self.api_key = api_key
        self.from_email = from_email

    def send_email(self, *, recipient: str, subject: str, html: str, text: str | None = None) -> bool:
        if not self.api_key or not self.from_email:
            logger.info("e-mail delivery not configured; skipping notification e-mail")
            return False
        resend.api_key = self.api_key
        try:
            payload = {"from": self.from_email, "to": [recipient], "subject": subject, "html": html}
            if text is not None:
                payload["text"] = text
            resend.Emails.send(payload)
        except requests.RequestException as error:
            logger.error("notification e-mail transport failure: %s", type(error).__name__)
            return False
        except ResendError as error:
            logger.error("notification e-mail rejected by provider: code=%s type=%s", error.code, error.error_type)
            return False
        return True


def email_delivery_from_settings(settings) -> ResendEmailDelivery:
    key = settings.resend_api_key.get_secret_value() if settings.resend_api_key else None
    return ResendEmailDelivery(api_key=key, from_email=settings.invitation_from_email)
