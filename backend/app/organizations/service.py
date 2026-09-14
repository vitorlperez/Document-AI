import secrets
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit_usage.models import AuditLog
from app.core.scoping import OrganizationScope
from app.identity.models import User
from app.organizations.models import Membership, MembershipInvitation, MembershipRole, Organization


class MembershipAlreadyExists(ValueError):
    pass


class InvitationNotAllowed(PermissionError):
    pass


class InvitationInvalid(ValueError):
    pass


def _canonical_email(email: str) -> str:
    return email.strip().lower()


def _hash_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


class OrganizationService:
    def __init__(self, session: Session):
        self.session = session

    def create_organization(
        self, *, name: str, owner_email: str, owner_user_id: UUID | None = None
    ) -> tuple[Organization, User, Membership]:
        user = self.session.get(User, owner_user_id) if owner_user_id else self.session.scalar(
            select(User).where(User.email == owner_email)
        )
        if user is None:
            user = User(email=owner_email)
            self.session.add(user)
            self.session.flush()

        organization = Organization(name=name)
        self.session.add(organization)
        self.session.flush()
        membership = Membership(
            organization_id=organization.id, user_id=user.id, role=MembershipRole.OWNER, is_active=True
        )
        self.session.add(membership)
        self.session.flush()
        self._record_membership_audit(
            organization_id=organization.id,
            actor_user_id=user.id,
            membership=membership,
            action="membership.created",
        )
        return organization, user, membership

    def add_membership(
        self, *, scope: OrganizationScope, user_id: UUID, role: MembershipRole, actor_user_id: UUID | None = None
    ) -> Membership:
        membership = Membership(organization_id=scope.organization_id, user_id=user_id, role=role, is_active=True)
        self.session.add(membership)
        try:
            self.session.flush()
        except IntegrityError as error:
            self.session.rollback()
            raise MembershipAlreadyExists("active membership already exists for this organization") from error
        self._record_membership_audit(
            organization_id=scope.organization_id,
            actor_user_id=actor_user_id or user_id,
            membership=membership,
            action="membership.created",
        )
        return membership

    def get_membership(self, *, scope: OrganizationScope, membership_id: UUID) -> Membership | None:
        return self.session.scalar(
            select(Membership).where(
                Membership.id == membership_id,
                Membership.organization_id == scope.organization_id,
            )
        )

    def organizations_for_user(self, *, user_id: UUID) -> list[tuple[Organization, Membership]]:
        return list(
            self.session.execute(
                select(Organization, Membership)
                .join(Membership, Membership.organization_id == Organization.id)
                .where(Membership.user_id == user_id, Membership.is_active.is_(True))
                .order_by(Organization.name)
            )
        )

    def members(self, *, scope: OrganizationScope, actor_user_id: UUID) -> list[tuple[Membership, User]]:
        self._require_owner(scope=scope, actor_user_id=actor_user_id)
        return list(
            self.session.execute(
                select(Membership, User)
                .join(User, User.id == Membership.user_id)
                .where(Membership.organization_id == scope.organization_id, Membership.is_active.is_(True))
                .order_by(User.email)
            )
        )

    def change_membership_role(
        self, *, scope: OrganizationScope, actor_user_id: UUID, membership_id: UUID, role: MembershipRole
    ) -> Membership:
        self._require_owner(scope=scope, actor_user_id=actor_user_id)
        membership = self.get_membership(scope=scope, membership_id=membership_id)
        if membership is None or not membership.is_active or membership.role == MembershipRole.OWNER or role == MembershipRole.OWNER:
            raise InvitationInvalid("membership is invalid")
        membership.role = role
        self._record_membership_audit(
            organization_id=scope.organization_id,
            actor_user_id=actor_user_id,
            membership=membership,
            action="membership.role_changed",
        )
        return membership

    def create_invitation(
        self, *, scope: OrganizationScope, actor_user_id: UUID, email: str, role: MembershipRole
    ) -> tuple[MembershipInvitation, str]:
        if role not in {MembershipRole.ADMIN, MembershipRole.MEMBER}:
            raise InvitationInvalid("only admin or member invitations are allowed")
        owner = self.session.scalar(
            select(Membership).where(
                Membership.organization_id == scope.organization_id,
                Membership.user_id == actor_user_id,
                Membership.is_active.is_(True),
                Membership.role == MembershipRole.OWNER,
            )
        )
        if owner is None:
            raise InvitationNotAllowed("only an owner can manage invitations")
        normalized_email = _canonical_email(email)
        pending = self.session.scalar(
            select(MembershipInvitation).where(
                MembershipInvitation.organization_id == scope.organization_id,
                MembershipInvitation.email == normalized_email,
                MembershipInvitation.accepted_at.is_(None),
                MembershipInvitation.revoked_at.is_(None),
            )
        )
        if pending is not None:
            pending.revoked_at = datetime.now(UTC)
            # Flush the replacement state before inserting. This keeps the
            # pending-invitation uniqueness invariant valid on PostgreSQL and
            # on dialects used by isolated service tests.
            self.session.flush()
        raw_token = secrets.token_urlsafe(32)
        invitation = MembershipInvitation(
            organization_id=scope.organization_id,
            email=normalized_email,
            role=role,
            token_hash=_hash_token(raw_token),
            invited_by_user_id=actor_user_id,
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        self.session.add(invitation)
        self.session.flush()
        self._record_invitation_audit(
            organization_id=scope.organization_id,
            actor_user_id=actor_user_id,
            invitation=invitation,
            action="invitation.created",
        )
        return invitation, raw_token

    def accept_invitation(self, *, raw_token: str, user: User) -> Membership:
        invitation = self.session.scalar(
            select(MembershipInvitation).where(
                MembershipInvitation.token_hash == _hash_token(raw_token),
                MembershipInvitation.accepted_at.is_(None),
                MembershipInvitation.revoked_at.is_(None),
                MembershipInvitation.expires_at > datetime.now(UTC),
            )
        )
        if invitation is None or invitation.email != _canonical_email(user.email):
            raise InvitationInvalid("invitation is invalid")
        membership = Membership(
            organization_id=invitation.organization_id,
            user_id=user.id,
            role=invitation.role,
            is_active=True,
        )
        self.session.add(membership)
        try:
            self.session.flush()
        except IntegrityError as error:
            self.session.rollback()
            raise InvitationInvalid("invitation is invalid") from error
        invitation.accepted_at = datetime.now(UTC)
        self._record_invitation_audit(
            organization_id=invitation.organization_id,
            actor_user_id=user.id,
            invitation=invitation,
            action="invitation.accepted",
        )
        return membership

    def revoke_invitation(
        self, *, scope: OrganizationScope, actor_user_id: UUID, invitation_id: UUID
    ) -> None:
        self._require_owner(scope=scope, actor_user_id=actor_user_id)
        invitation = self.session.scalar(
            select(MembershipInvitation).where(
                MembershipInvitation.id == invitation_id,
                MembershipInvitation.organization_id == scope.organization_id,
                MembershipInvitation.accepted_at.is_(None),
                MembershipInvitation.revoked_at.is_(None),
            )
        )
        if invitation is None:
            raise InvitationInvalid("invitation is invalid")
        invitation.revoked_at = datetime.now(UTC)
        self._record_invitation_audit(
            organization_id=scope.organization_id,
            actor_user_id=actor_user_id,
            invitation=invitation,
            action="invitation.revoked",
        )

    def deactivate_membership(
        self, *, scope: OrganizationScope, actor_user_id: UUID, membership_id: UUID
    ) -> Membership:
        self._require_owner(scope=scope, actor_user_id=actor_user_id)
        membership = self.session.scalar(
            select(Membership).where(
                Membership.id == membership_id,
                Membership.organization_id == scope.organization_id,
                Membership.is_active.is_(True),
            )
        )
        if membership is None or membership.role == MembershipRole.OWNER:
            raise InvitationInvalid("membership is invalid")
        membership.is_active = False
        membership.deactivated_at = datetime.now(UTC)
        self._record_membership_audit(
            organization_id=scope.organization_id,
            actor_user_id=actor_user_id,
            membership=membership,
            action="membership.deactivated",
        )
        return membership

    def _require_owner(self, *, scope: OrganizationScope, actor_user_id: UUID) -> None:
        owner = self.session.scalar(
            select(Membership).where(
                Membership.organization_id == scope.organization_id,
                Membership.user_id == actor_user_id,
                Membership.is_active.is_(True),
                Membership.role == MembershipRole.OWNER,
            )
        )
        if owner is None:
            raise InvitationNotAllowed("only an owner can manage invitations")

    def _record_membership_audit(
        self, *, organization_id: UUID, actor_user_id: UUID, membership: Membership, action: str
    ) -> AuditLog:
        audit_log = AuditLog(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            action=action,
            target_type="membership",
            target_id=membership.id,
        )
        self.session.add(audit_log)
        self.session.flush()
        return audit_log

    def _record_invitation_audit(
        self, *, organization_id: UUID, actor_user_id: UUID, invitation: MembershipInvitation, action: str
    ) -> AuditLog:
        audit_log = AuditLog(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            action=action,
            target_type="membership_invitation",
            target_id=invitation.id,
        )
        self.session.add(audit_log)
        self.session.flush()
        return audit_log
