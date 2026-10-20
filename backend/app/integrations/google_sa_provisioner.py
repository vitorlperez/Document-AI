"""On-demand Drive robots: one dedicated service account per organization, never recycled.

Runs in the Celery worker/beat only. The provisioner credential never reaches the API process.
"""

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import jwt
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.audit_usage.models import AuditLog
from app.integrations.google_drive_sa import ServiceAccountKeyCipher
from app.integrations.google_sa_models import GoogleSaIdentity, GoogleSaProject
from app.integrations.models import DataSource
from app.organizations.models import Organization

logger = logging.getLogger("document_intelligence.integration")

IAM_BASE = "https://iam.googleapis.com/v1/"
CLOUD_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
# IAM allows 3 service-account creations per minute per project.
MIN_CREATE_INTERVAL = timedelta(seconds=20.1)
PROVISIONING = "provisioning"
PROVISIONING_FAILED = "provisioning_failed"


class ProvisionerRetry(RuntimeError):
    """Transient condition (throttle, IAM/org-policy propagation): retry with backoff."""

    def __init__(self, reason, countdown=15):
        super().__init__(reason)
        self.reason, self.countdown = reason, countdown


class ProvisionerFatal(RuntimeError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def robot_account_id(secret: str, organization_id: UUID) -> str:
    """Deterministic (retries find the same account) but not guessable without the secret."""
    digest = hmac.new(secret.encode(), f"drive-sa:{organization_id}".encode(), hashlib.sha256)
    return "arq-" + digest.hexdigest()[:12]


def display_name(organization_id: UUID | None) -> str:
    return f"ArquivIO org {organization_id}" if organization_id else "ArquivIO warm pool robot"


class IamProvisionerClient:
    """Minimal IAM REST client authenticated as the least-privilege provisioner account."""

    def __init__(self, key_b64: str, *, http=None, clock=time.time):
        try:
            self.key = json.loads(base64.b64decode(key_b64, validate=True))
            self.key["client_email"], self.key["private_key"]
        except (ValueError, KeyError, TypeError):
            raise ProvisionerFatal("provisioner_credential_invalid") from None
        self.http, self.clock = http or httpx.Client(timeout=30), clock
        self._token = None

    def token(self) -> str:
        now = self.clock()
        if self._token and self._token[1] > now + 120:
            return self._token[0]
        assertion = jwt.encode(
            {
                "iss": self.key["client_email"],
                "scope": CLOUD_SCOPE,
                "aud": "https://oauth2.googleapis.com/token",
                "iat": int(now) - 30,
                "exp": int(now) + 3500,
            },
            self.key["private_key"],
            algorithm="RS256",
            headers={"kid": self.key.get("private_key_id")},
        )
        reply = self.http.post(
            "https://oauth2.googleapis.com/token",
            data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
        )
        if reply.status_code >= 500 or reply.status_code == 429:
            raise ProvisionerRetry("token_unavailable", 30)
        token = reply.json().get("access_token") if reply.status_code == 200 else None
        if not token:
            raise ProvisionerFatal("provisioner_auth_failed")
        self._token = (token, now + int(reply.json().get("expires_in", 3000)))
        return token

    def request(self, method, path, *, body=None):
        try:
            response = self.http.request(
                method,
                IAM_BASE + path,
                headers={"Authorization": "Bearer " + self.token()},
                json=body,
            )
        except httpx.HTTPError:
            raise ProvisionerRetry("iam_network", 20) from None
        return response

    @staticmethod
    def classify(response, *, key_step=False):
        status = response.status_code
        if status in (200, 201, 204):
            return
        if status == 429 or status >= 500:
            raise ProvisionerRetry("iam_throttled_or_unavailable", 30)
        text = response.text if status == 400 else ""
        if status == 400 and "FAILED_PRECONDITION" in text:
            # iam.disableServiceAccountKeyCreation exception still propagating (60-90 s).
            raise ProvisionerRetry("org_policy_propagating", 45)
        if status == 404 and key_step:
            raise ProvisionerRetry("service_account_propagating", 10)
        if status in (401, 403):
            raise ProvisionerFatal("provisioner_forbidden")
        raise ProvisionerFatal(f"iam_request_failed_{status}")

    def create_account(self, project, account_id, name):
        response = self.request(
            "POST",
            f"projects/{project}/serviceAccounts",
            body={"accountId": account_id, "serviceAccount": {"displayName": name}},
        )
        if response.status_code == 409:  # retry after a partial attempt: reuse the same account
            existing = self.request(
                "GET", f"projects/{project}/serviceAccounts/{account_id}@{project}.iam.gserviceaccount.com"
            )
            self.classify(existing)
            return existing.json()["email"]
        self.classify(response)
        email = response.json().get("email")
        if not email:
            raise ProvisionerFatal("iam_robot_response_invalid")
        return email

    def create_key(self, email):
        response = self.request(
            "POST",
            f"projects/-/serviceAccounts/{email}/keys",
            body={"privateKeyType": "TYPE_GOOGLE_CREDENTIALS_FILE", "keyAlgorithm": "KEY_ALG_RSA_2048"},
        )
        self.classify(response, key_step=True)
        try:
            return json.loads(base64.b64decode(response.json()["privateKeyData"], validate=True))
        except (KeyError, ValueError):
            raise ProvisionerFatal("iam_key_response_invalid") from None

    def delete_key(self, email, key_id):
        self.classify(self.request("DELETE", f"projects/-/serviceAccounts/{email}/keys/{key_id}"))

    def set_display_name(self, email, name):
        response = self.request(
            "PATCH",
            f"projects/-/serviceAccounts/{email}",
            body={"serviceAccount": {"displayName": name}, "updateMask": "displayName"},
        )
        self.classify(response)


def utc(value):
    return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


class RobotProvisioner:
    def __init__(self, session, settings, iam, cipher: ServiceAccountKeyCipher, *, now=None):
        self.session, self.settings, self.iam, self.cipher = session, settings, iam, cipher
        self.now = now or (lambda: datetime.now(UTC))

    def _audit(self, source, action, target_id):
        self.session.add(
            AuditLog(
                organization_id=source.organization_id,
                actor_user_id=source.connected_by_user_id,
                action=action,
                target_type="google_sa_identity",
                target_id=target_id,
            )
        )

    def _project_usage(self, project):
        return self.session.scalar(
            select(func.count()).select_from(GoogleSaIdentity).where(GoogleSaIdentity.project_id == project.id)
        )

    def remaining_capacity(self) -> int:
        quota = self.settings.google_sa_project_quota
        total = 0
        for name in self.settings.google_sa_pool_project_list:
            project = self.session.scalar(select(GoogleSaProject).where(GoogleSaProject.gcp_project_id == name))
            total += (project.sa_quota if project else quota) - (self._project_usage(project) if project else 0)
        return max(total, 0)

    def check_capacity(self) -> int:
        remaining = self.remaining_capacity()
        if remaining == 0:
            logger.error("robot capacity exhausted", extra={"event": "drive_sa.capacity_exhausted"})
        elif remaining < self.settings.google_sa_capacity_alert_below:
            logger.warning(
                "robot capacity low", extra={"event": "drive_sa.capacity_low", "remaining": remaining}
            )
        return remaining

    def _lock_project_for_create(self):
        """Pick a pool project with free quota, row-locked so IAM creations stay <= 3/min."""
        names = self.settings.google_sa_pool_project_list
        if not names:
            raise ProvisionerFatal("pool_projects_unconfigured")
        busy = False
        for name in names:
            if not self.session.scalar(select(GoogleSaProject.id).where(GoogleSaProject.gcp_project_id == name)):
                try:  # two workers may race to register the same pool project
                    with self.session.begin_nested():
                        self.session.add(
                            GoogleSaProject(gcp_project_id=name, sa_quota=self.settings.google_sa_project_quota)
                        )
                except IntegrityError:
                    pass
            project = self.session.scalar(
                select(GoogleSaProject).where(GoogleSaProject.gcp_project_id == name).with_for_update(skip_locked=True)
            )
            if project is None:
                busy = True  # another worker holds this project's lock
                continue
            if self._project_usage(project) >= project.sa_quota:
                continue
            wait = project.last_iam_create_at and (
                utc(project.last_iam_create_at) + MIN_CREATE_INTERVAL - self.now()
            )
            if wait and wait.total_seconds() > 0:
                busy = True
                continue
            return project
        if busy:
            raise ProvisionerRetry("project_busy_or_throttled", 25)
        logger.error("robot capacity exhausted", extra={"event": "drive_sa.capacity_exhausted"})
        raise ProvisionerFatal("pool_capacity")

    def _create_robot(self, account_id, name):
        """Create account + key under the project lock; returns (project, identity). Caller commits."""
        project = self._lock_project_for_create()
        email = self.iam.create_account(project.gcp_project_id, account_id, name)
        project.last_iam_create_at = self.now()
        key = self.iam.create_key(email)
        identity = GoogleSaIdentity(
            project_id=project.id, sa_email=key["client_email"], encrypted_key=self.cipher.encrypt(key)
        )
        return project, identity, key

    def _commit_or_revoke(self, key):
        try:
            self.session.commit()
        except Exception:  # noqa: BLE001
            self.session.rollback()
            try:
                self.iam.delete_key(key["client_email"], key["private_key_id"])
            except Exception:  # noqa: BLE001 - never leak key material in logs
                logger.error("robot key cleanup required", extra={"event": "drive_sa.pool_cleanup_required"})
            raise ProvisionerFatal("robot_store_failed") from None

    def provision_source(self, source_id: UUID) -> str:
        """Give the org's pending source a dedicated robot. Idempotent; returns the outcome."""
        source = self.session.get(DataSource, source_id)
        if source is None or source.provider != "google_drive_sa":
            return "gone"
        # Same lock order as enable(): organization, then the rest.
        self.session.scalar(
            select(Organization).where(Organization.id == source.organization_id).with_for_update()
        )
        self.session.refresh(source)
        if source.status == "disconnected":
            return "gone"
        if source.sa_identity_id:
            return "ready"
        existing = self.session.scalar(
            select(GoogleSaIdentity).where(
                GoogleSaIdentity.organization_id == source.organization_id,
                GoogleSaIdentity.status == "assigned",
            )
        )
        if existing is None:
            existing = self._claim_free(source.organization_id)
        if existing is not None:
            self._attach(source, existing, "drive_sa.robot_assigned")
            self.session.commit()
            return "ready"
        account_id = robot_account_id(
            self.settings.google_sa_key_encryption_key.get_secret_value(), source.organization_id
        )
        _project, identity, key = self._create_robot(account_id, display_name(source.organization_id))
        identity.status = "assigned"
        identity.organization_id = source.organization_id
        identity.assigned_at = self.now()
        self.session.add(identity)
        self.session.flush()
        self._attach(source, identity, "drive_sa.robot_provisioned")
        self._commit_or_revoke(key)
        return "ready"

    def _claim_free(self, organization_id):
        identity = self.session.scalar(
            select(GoogleSaIdentity)
            .where(
                GoogleSaIdentity.status == "free",
                GoogleSaIdentity.organization_id.is_(None),
                GoogleSaIdentity.encrypted_key.is_not(None),
            )
            .order_by(GoogleSaIdentity.created_at, GoogleSaIdentity.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if identity:
            identity.status, identity.organization_id, identity.assigned_at = (
                "assigned",
                organization_id,
                self.now(),
            )
        return identity

    def _attach(self, source, identity, action):
        source.sa_identity_id = identity.id
        source.account_email = identity.sa_email
        source.status = "awaiting_share"
        self._audit(source, action, identity.id)

    def top_up_warm(self) -> int:
        """Keep GOOGLE_SA_WARM_POOL_SIZE free robots; stops when IAM throttling asks to wait."""
        size = self.settings.google_sa_warm_pool_size
        if size <= 0 or not self.settings.google_sa_pool_project_list:
            return 0
        free = self.session.scalar(
            select(func.count()).select_from(GoogleSaIdentity).where(
                GoogleSaIdentity.status == "free", GoogleSaIdentity.encrypted_key.is_not(None)
            )
        )
        created = 0
        for _ in range(max(size - free, 0)):
            try:
                _project, identity, key = self._create_robot("arq-" + secrets.token_hex(6), display_name(None))
            except ProvisionerRetry:
                self.session.rollback()
                break
            self.session.add(identity)
            self._commit_or_revoke(key)
            created += 1
        return created

    def label_robot(self, identity_id: UUID):
        identity = self.session.get(GoogleSaIdentity, identity_id)
        if identity and identity.organization_id:
            self.iam.set_display_name(identity.sa_email, display_name(identity.organization_id))
