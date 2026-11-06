"""Idempotent infrastructure initialization, run once before API and workers."""

import time

from alembic import command
from alembic.config import Config

from backend.app.conversations.checkpoints import setup_checkpoints
from backend.app.db.session import session_factory
from backend.app.rag.vectors import ensure_collection
from backend.app.services.resources import S3Store, get_resources
from scripts.database_roles import provision_roles


def main() -> None:
    resources = get_resources()
    command.upgrade(Config("alembic.ini"), "head")
    setup_checkpoints(session_factory().kw["bind"])
    provision_roles(session_factory().kw["bind"], resources.settings)
    for attempt in range(30):
        try:
            assert isinstance(resources.store, S3Store)
            client = resources.store.client
            buckets = [item["Name"] for item in client.list_buckets().get("Buckets", [])]
            if resources.settings.s3_bucket not in buckets:
                client.create_bucket(Bucket=resources.settings.s3_bucket)
            ensure_collection(resources)
            resources.redis.ping()
            resources.close()
            return
        except Exception:
            if attempt == 29:
                raise RuntimeError("Infrastructure bootstrap failed") from None
            time.sleep(2)


if __name__ == "__main__":
    main()
