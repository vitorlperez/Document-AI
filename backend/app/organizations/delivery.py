"""Outbound invitation delivery boundary."""

from typing import Protocol

import resend


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
        resend.Emails.send(
            {
                "from": self.from_email,
                "to": [recipient],
                "subject": "Você foi convidado para o Document Intelligence",
                "html": f'<p>Você recebeu um convite.</p><p><a href="{invitation_url}">Aceitar convite</a></p>',
            }
        )
