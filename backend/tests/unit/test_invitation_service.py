from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import pytest

from app.core.scoping import OrganizationScope
from app.organizations.models import Membership, MembershipInvitation, MembershipRole
from app.organizations.service import InvitationInvalid, OrganizationService


class FakeInvitationSession:
    def __init__(self, scalar_results: list[object | None]) -> None:
        self.scalar_results = scalar_results
        self.added: list[object] = []
        self.flush_count = 0

    def scalar(self, statement: object) -> object | None:
        return self.scalar_results.pop(0)

    def add(self, instance: object) -> None:
        self.added.append(instance)

    def flush(self) -> None:
        self.flush_count += 1


def active_owner(organization_id, user_id) -> Membership:
    return Membership(
        organization_id=organization_id,
        user_id=user_id,
        role=MembershipRole.OWNER,
        is_active=True,
    )


def test_reinviting_revokes_prior_pending_invitation_and_hashes_replacement_token() -> None:
    organization_id, owner_id = uuid4(), uuid4()
    prior = MembershipInvitation(
        organization_id=organization_id,
        email="invitee@acme.co",
        role=MembershipRole.MEMBER,
        token_hash=sha256(b"old-token").hexdigest(),
        invited_by_user_id=owner_id,
        expires_at=datetime.now(UTC),
    )
    session = FakeInvitationSession([active_owner(organization_id, owner_id), prior])

    replacement, raw_token = OrganizationService(session).create_invitation(
        scope=OrganizationScope(organization_id),
        actor_user_id=owner_id,
        email=" Invitee@Acme.Co ",
        role=MembershipRole.ADMIN,
    )

    assert prior.revoked_at is not None
    assert replacement.email == "invitee@acme.co"
    assert replacement.role is MembershipRole.ADMIN
    assert replacement.token_hash == sha256(raw_token.encode()).hexdigest()
    assert raw_token != replacement.token_hash
    assert session.added[0] is replacement


def test_owner_role_cannot_be_invited() -> None:
    session = FakeInvitationSession([])

    with pytest.raises(InvitationInvalid, match="only admin or member"):
        OrganizationService(session).create_invitation(
            scope=OrganizationScope(uuid4()),
            actor_user_id=uuid4(),
            email="invitee@acme.co",
            role=MembershipRole.OWNER,
        )
