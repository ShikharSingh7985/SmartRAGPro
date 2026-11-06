"""Bootstrap-only local PostgreSQL runtime grants; never interpolates identifiers."""

from psycopg import sql
from sqlalchemy import Engine

from backend.app.core.config import Settings


def provision_roles(engine: Engine, settings: Settings) -> None:
    if not settings.runtime_database_password.get_secret_value():
        return  # Hosted operators provision roles independently; this is documented.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        raw = connection.connection.driver_connection
        assert raw is not None
        with raw.cursor() as cursor:
            for role, password in [
                ("smartrag_api", settings.runtime_database_password),
                ("smartrag_worker", settings.worker_database_password),
            ]:
                if not password.get_secret_value():
                    raise RuntimeError("Runtime database credentials are incomplete")
                exists = cursor.execute(
                    "SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)
                ).fetchone()
                if not exists:
                    cursor.execute(sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(role)))
                verifier = raw.pgconn.encrypt_password(
                    password.get_secret_value().encode(), role.encode(), b"scram-sha-256"
                ).decode()
                cursor.execute(
                    sql.SQL(
                        "ALTER ROLE {} PASSWORD {} NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOREPLICATION NOBYPASSRLS"
                    ).format(sql.Identifier(role), sql.Literal(verifier))
                )
            cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            cursor.execute("GRANT USAGE ON SCHEMA public TO smartrag_api, smartrag_worker")
            cursor.execute(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES "
                "IN SCHEMA public TO smartrag_api"
            )
            cursor.execute(
                "REVOKE INSERT, UPDATE, DELETE ON alembic_version, checkpoint_migrations "
                "FROM smartrag_api"
            )
            cursor.execute(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON documents, ingestion_jobs, "
                "document_assets, page_extractions, search_chunks, search_terms, "
                "security_inspections TO smartrag_worker"
            )
            cursor.execute("GRANT SELECT (id, is_active, deleted_at) ON users TO smartrag_worker")
