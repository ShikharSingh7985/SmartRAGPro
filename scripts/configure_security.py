"""Generate private Compose runtime environments without printing credentials.

Only internal local-development endpoints are changed. Hosted deployments must
provision equivalent roles and service credentials through their secret manager.
"""

import secrets
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values


def main() -> None:
    path = Path(".env")
    values = {key: value for key, value in dotenv_values(path).items() if value is not None}
    database = values.get("MIGRATION_DATABASE_URL") or values["DATABASE_URL"]
    if (
        urlsplit(database).hostname != "postgres"
        or urlsplit(values["REDIS_URL"]).hostname != "redis"
    ):
        raise SystemExit(
            "Local helper requires internal postgres/redis hosts; "
            "configure hosted services manually."
        )
    additions = {
        "MIGRATION_DATABASE_URL": database,
        "RUNTIME_DATABASE_PASSWORD": values.get("RUNTIME_DATABASE_PASSWORD")
        or secrets.token_urlsafe(32),
        "WORKER_DATABASE_PASSWORD": values.get("WORKER_DATABASE_PASSWORD")
        or secrets.token_urlsafe(32),
        "REDIS_PASSWORD": values.get("REDIS_PASSWORD") or secrets.token_urlsafe(32),
        "QDRANT_API_KEY": values.get("QDRANT_API_KEY") or secrets.token_urlsafe(32),
        "QDRANT_READ_API_KEY": values.get("QDRANT_READ_API_KEY") or secrets.token_urlsafe(32),
    }
    additions["DATABASE_URL"] = (
        "postgresql+psycopg://smartrag_api:"
        + additions["RUNTIME_DATABASE_PASSWORD"]
        + "@postgres:5432/smartrag"
    )
    additions["REDIS_URL"] = "redis://:" + additions["REDIS_PASSWORD"] + "@redis:6379/0"
    # Preserve comments and every unrelated setting, including existing provider keys.
    lines = path.read_text(encoding="utf-8").splitlines()
    for key, value in additions.items():
        replacement = f"{key}={value}"
        matches = [i for i, line in enumerate(lines) if line.startswith(key + "=")]
        if len(matches) > 1:
            raise SystemExit("Duplicate configuration keys require manual cleanup")
        if matches:
            lines[matches[0]] = replacement
        else:
            lines.append(replacement)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    values.update(additions)
    root = Path(".docker-local")
    root.mkdir(exist_ok=True)
    if not (root / "grafana-password").exists():
        (root / "grafana-password").write_text(secrets.token_urlsafe(32), encoding="utf-8")
    privileged = {
        "MIGRATION_DATABASE_URL",
        "RUNTIME_DATABASE_PASSWORD",
        "WORKER_DATABASE_PASSWORD",
        "POSTGRES_PASSWORD",
        "REDIS_PASSWORD",
        "QDRANT_READ_API_KEY",
    }
    for role in ("api", "worker", "dispatcher", "bootstrap"):
        env = {key: value for key, value in values.items() if key not in privileged}
        env["SERVICE_ROLE"] = role
        if role not in {"api", "worker"}:
            env["LANGFUSE_ENABLED"] = "false"
            env.pop("LANGFUSE_SECRET_KEY", None)
            env.pop("LANGFUSE_PUBLIC_KEY", None)
        if role != "api":
            env.pop("JWT_SECRET", None)
        if role == "bootstrap":
            env.update({key: values[key] for key in privileged if key in values})
            env["DATABASE_URL"] = database
        elif role == "worker":
            env["DATABASE_URL"] = (
                "postgresql+psycopg://smartrag_worker:"
                + additions["WORKER_DATABASE_PASSWORD"]
                + "@postgres:5432/smartrag"
            )
        elif role == "api":
            env["QDRANT_API_KEY"] = additions["QDRANT_READ_API_KEY"]
        (root / f"{role}.env").write_text(
            "\n".join(f"{key}={value}" for key, value in env.items()) + "\n", encoding="utf-8"
        )
    (root / "redis.conf").write_text(
        "appendonly yes\nprotected-mode yes\nrequirepass " + additions["REDIS_PASSWORD"] + "\n",
        encoding="utf-8",
    )
    print("Private runtime environments generated. No credentials were printed.")


if __name__ == "__main__":
    main()
