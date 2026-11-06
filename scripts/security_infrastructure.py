"""Probe live service privilege boundaries without disclosing connection secrets."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from redis import Redis
from sqlalchemy import create_engine, text

from backend.app.core.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("/tmp/security-infrastructure.json"))
    args = parser.parse_args()
    settings = get_settings()
    engine = create_engine(settings.database_url)
    checks = []
    with engine.connect() as connection:
        privileged = connection.execute(
            text(
                "SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls "
                "FROM pg_roles WHERE rolname=current_user"
            )
        ).scalar_one()
        can_create = connection.execute(
            text("SELECT has_schema_privilege(current_user, 'public', 'CREATE')")
        ).scalar_one()
        checks.append({"check": "runtime_not_admin", "passed": not privileged and not can_create})
        if settings.service_role == "worker":
            password_read = connection.execute(
                text("SELECT has_column_privilege(current_user,'users','password_hash','SELECT')")
            ).scalar_one()
            token_read = connection.execute(
                text("SELECT has_table_privilege(current_user,'refresh_tokens','SELECT')")
            ).scalar_one()
            checkpoint_read = connection.execute(
                text("SELECT has_table_privilege(current_user,'checkpoints','SELECT')")
            ).scalar_one()
            checks.append(
                {
                    "check": "worker_no_auth_or_checkpoint_access",
                    "passed": not any([password_read, token_read, checkpoint_read]),
                }
            )
    engine.dispose()
    response = httpx.get(settings.qdrant_url + "/collections", timeout=10)
    checks.append(
        {
            "check": "qdrant_requires_auth",
            "status": response.status_code,
            "passed": response.status_code in {401, 403},
        }
    )
    redis_url = urlsplit(settings.redis_url)
    anonymous = Redis(
        host=redis_url.hostname or "redis", port=redis_url.port or 6379, socket_timeout=5
    )
    try:
        anonymous.ping()
        checks.append({"check": "redis_requires_auth", "passed": False})
    except Exception as exc:
        checks.append(
            {"check": "redis_requires_auth", "passed": type(exc).__name__ == "AuthenticationError"}
        )
    finally:
        anonymous.close()
    if settings.service_role == "api":
        # Invalid nonexistent collection mutation must be denied by read-only credentials
        # before lookup/body validation. No user content is touched.
        response = httpx.delete(
            settings.qdrant_url + "/collections/security_nonexistent_probe",
            headers={"api-key": settings.qdrant_api_key.get_secret_value()},
            timeout=10,
        )
        checks.append(
            {
                "check": "api_qdrant_readonly",
                "status": response.status_code,
                "passed": response.status_code in {401, 403},
            }
        )
    if settings.service_role == "worker":
        status = Path("/proc/self/status").read_text()
        checks.append(
            {
                "check": "worker_unprivileged_process",
                "passed": "NoNewPrivs:\t1" in status and "CapEff:\t0000000000000000" in status,
            }
        )
    args.output.write_text(
        json.dumps(
            {
                "execution_date": datetime.now(UTC).isoformat(),
                "role": settings.service_role,
                "checks": checks,
            },
            indent=2,
        )
        + "\n"
    )
    print(
        json.dumps(
            {
                "role": settings.service_role,
                "passed": sum(c["passed"] for c in checks),
                "total": len(checks),
            }
        )
    )
    if not all(c["passed"] for c in checks):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
