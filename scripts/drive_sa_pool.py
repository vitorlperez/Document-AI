#!/usr/bin/env python3
"""Offline IAM pool. Run with backend/.venv/bin/python scripts/drive_sa_pool.py create.
DATABASE_URL + GOOGLE_SA_KEY_ENCRYPTION_KEY required. IAM auth comes from local gcloud
or DRIVE_SA_POOL_IAM_TOKEN (offline only). Private keys never touch stdout or disk.
"""

import argparse
import base64
import json
import logging
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import httpx
from app.core.config import Settings
from app.core.database import build_engine
from app.core.scoping import OrganizationScope
from app.identity import models as identity_models  # noqa: F401
from app.integrations.google_drive_sa_service import (
    DriveSaConnectionService,
    key_cipher,
)
from app.integrations.google_sa_models import GoogleSaIdentity, GoogleSaProject
from app.organizations import models as organization_models  # noqa: F401
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session


class PoolError(RuntimeError):
    pass


class IamApi:
    def token(self):
        token = os.environ.get("DRIVE_SA_POOL_IAM_TOKEN")
        if not token:
            result = subprocess.run(
                ["gcloud", "auth", "print-access-token"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode:
                raise PoolError("iam_auth_unavailable")
            token = result.stdout.strip()
        if not token:
            raise PoolError("iam_auth_unavailable")
        return token

    def request(self, method, path, *, body=None):
        response = httpx.request(
            method,
            "https://iam.googleapis.com/v1/" + path,
            headers={"Authorization": "Bearer " + self.token()},
            json=body,
            timeout=30,
        )
        if response.status_code not in (200, 201, 204):
            raise PoolError("iam_request_failed_" + str(response.status_code))
        return response.json() if response.content else {}

    def create_key(self, email):
        reply = self.request(
            "POST",
            f"projects/-/serviceAccounts/{email}/keys",
            body={
                "privateKeyType": "TYPE_GOOGLE_CREDENTIALS_FILE",
                "keyAlgorithm": "KEY_ALG_RSA_2048",
            },
        )
        try:
            return json.loads(base64.b64decode(reply["privateKeyData"], validate=True))
        except (KeyError, ValueError):
            raise PoolError("iam_key_response_invalid") from None

    def create_robot(self, project, account):
        reply = self.request(
            "POST",
            f"projects/{project}/serviceAccounts",
            body={
                "accountId": account,
                "serviceAccount": {"displayName": "Arquivio Drive robot"},
            },
        )
        if not reply.get("email"):
            raise PoolError("iam_robot_response_invalid")
        return self.create_key(reply["email"])

    def delete_key(self, email, key_id):
        self.request("DELETE", f"projects/-/serviceAccounts/{email}/keys/{key_id}")

    def retire_keys(self, email):
        reply = self.request(
            "GET", f"projects/-/serviceAccounts/{email}/keys?keyTypes=USER_MANAGED"
        )
        for key in reply.get("keys", []):
            self.request("DELETE", key["name"])


def fill_pool(
    *,
    session,
    project_id,
    count,
    quota,
    iam,
    cipher,
    sleep=time.sleep,
    clock=time.monotonic,
):
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,62}", project_id):
        raise PoolError("invalid_project")
    if count < 1 or count > quota:
        raise PoolError("invalid_count")
    project = session.scalar(
        select(GoogleSaProject)
        .where(GoogleSaProject.gcp_project_id == project_id)
        .with_for_update()
    )
    if not project:
        project = GoogleSaProject(gcp_project_id=project_id, sa_quota=quota)
        session.add(project)
        session.flush()
    occupied = session.scalar(
        select(func.count())
        .select_from(GoogleSaIdentity)
        .where(GoogleSaIdentity.project_id == project.id)
    )
    if occupied + count > project.sa_quota:
        raise PoolError("project_quota_exceeded")
    last = None
    for _ in range(count):
        # <=3 creates per rolling minute, also across the minute boundary.
        if last is not None:
            delay = 20.1 - (clock() - last)
            if delay > 0:
                sleep(delay)
        last = clock()
        key = iam.create_robot(project_id, "arq-" + secrets.token_hex(4))
        session.add(
            GoogleSaIdentity(
                project_id=project.id,
                sa_email=key["client_email"],
                encrypted_key=cipher.encrypt(key),
            )
        )
        try:
            session.commit()
        except Exception:  # noqa: BLE001 - sanitize errors that may carry key material
            session.rollback()
            try:
                iam.delete_key(key["client_email"], key["private_key_id"])
            except Exception:  # noqa: BLE001 - sanitize errors that may carry key material
                print("pool_cleanup_required", file=sys.stderr)
            raise PoolError("pool_store_failed") from None
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    create = commands.add_parser("create")
    create.add_argument("--project", required=True)
    create.add_argument("--count", type=int, default=50)
    create.add_argument("--quota", type=int, default=100)
    rotate = commands.add_parser("rotate")
    rotate.add_argument("--source-id", required=True)
    rotate.add_argument("--organization-id", required=True)
    rotate.add_argument("--actor-user-id", required=True)
    retire = commands.add_parser("retire-keys")
    retire.add_argument("--identity-id", required=True)
    args = parser.parse_args()
    settings = Settings()
    if not settings.google_sa_key_encryption_key:
        raise PoolError("dedicated_encryption_key_required")
    iam, engine = IamApi(), build_engine(settings)
    from uuid import UUID

    with engine.connect() as connection, Session(bind=connection) as session:
        # Session-level advisory lock survives commits and serializes offline provisioning.
        lock_name = "drive-sa-pool:" + (
            args.project if args.operation == "create" else args.operation
        )
        connection.execute(
            text("SELECT pg_advisory_lock(hashtext(:name))"), {"name": lock_name}
        )
        connection.commit()
        try:
            if args.operation == "create":
                count = fill_pool(
                    session=session,
                    project_id=args.project,
                    count=args.count,
                    quota=args.quota,
                    iam=iam,
                    cipher=key_cipher(settings),
                )
                print(f"created={count}; keys encrypted; throttle=3/min")
            elif args.operation == "rotate":
                service = DriveSaConnectionService(session, settings)
                source = service.source(
                    scope=OrganizationScope(UUID(args.organization_id)),
                    user_id=UUID(args.actor_user_id),
                    source_id=UUID(args.source_id),
                )
                identity = service.identity(source)
                old = service.cipher.decrypt(identity.encrypted_key)
                new = iam.create_key(identity.sa_email)
                try:
                    service.rotate_key(
                        source, user_id=UUID(args.actor_user_id), new_key=new
                    )
                    session.commit()
                except Exception:  # noqa: BLE001 - sanitize errors that may carry key material
                    session.rollback()
                    iam.delete_key(identity.sa_email, new["private_key_id"])
                    raise PoolError("rotation_validation_failed") from None
                iam.delete_key(identity.sa_email, old["private_key_id"])
                print("key rotated and previous IAM key deleted")
            else:
                identity = session.get(GoogleSaIdentity, UUID(args.identity_id))
                if not identity or identity.status not in ("retired", "compromised"):
                    raise PoolError("identity_not_retired")
                iam.retire_keys(identity.sa_email)
                identity.encrypted_key = None
                session.commit()
                print("retired IAM keys deleted; identity remains assigned")
        finally:
            connection.execute(
                text("SELECT pg_advisory_unlock(hashtext(:name))"), {"name": lock_name}
            )
            connection.commit()
    engine.dispose()


if __name__ == "__main__":
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        main()
    except PoolError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
    except Exception:  # noqa: BLE001 - sanitize errors that may carry key material
        print(
            "pool_operation_failed (inspect IAM/DB configuration without logging secrets)",
            file=sys.stderr,
        )
        sys.exit(1)
