import math
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from typing import Any
from unittest.mock import Mock
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from langchain_core.embeddings import Embeddings
from langgraph.checkpoint.sqlite import SqliteSaver
from qdrant_client import QdrantClient
from redis import Redis
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

os.environ["JWT_SECRET"] = "isolated-test-only-secret-never-use-in-production"
os.environ["S3_SECRET_KEY"] = "isolated-test-only"
os.environ["GEMINI_API_KEY"] = ""
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_TRACING"] = "false"
if "TIKTOKEN_CACHE_DIR" not in os.environ:
    os.environ["TIKTOKEN_CACHE_DIR"] = str(Path(".uv-cache/tiktoken").resolve())

from backend.app.core.config import get_settings  # noqa: E402
from backend.app.db.session import get_db  # noqa: E402
from backend.app.main import app  # noqa: E402
from backend.app.rag.vectors import ensure_collection  # noqa: E402
from backend.app.services.resources import Resources, S3Store, get_resources  # noqa: E402


class TestEmbeddings(Embeddings):
    """Deterministic vocabulary features, confined to tests."""

    __test__ = False

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        vector = [
            float(sum(text.casefold().count(word) for word in group))
            for group in [
                ("alpha", "accuracy", "model a", "overfitting", "overfit"),
                ("beta", "model b", "regularization", "penalty", "weights"),
                ("revenue", "validation"),
                ("million", "early stopping"),
                ("policy", "random forests"),
                ("leave",),
                ("days",),
                ("secret",),
            ]
        ]
        length = math.sqrt(sum(value * value for value in vector)) or 1
        return [value / length for value in vector]


class MemoryStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> None:
        self.objects[key] = data

    def get(self, key: str) -> bytes:
        return self.objects[key]

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    def ping(self) -> None:
        pass


@pytest.fixture
def pdf() -> bytes:
    output = BytesIO()
    canvas = Canvas(output)
    canvas.drawString(72, 740, "Alpha revenue is 42 million dollars.")
    canvas.showPage()
    canvas.drawString(72, 740, "Alpha leave policy provides 25 days.")
    canvas.save()
    return output.getvalue()


@pytest.fixture
def stack(tmp_path, monkeypatch) -> Iterator[tuple[TestClient, sessionmaker[Session], Resources]]:
    url = os.environ.get("TEST_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    if not url.startswith("sqlite") and not url.endswith("/smartrag_test"):
        raise RuntimeError("Integration tests require a dedicated smartrag_test database")
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    settings = get_settings().model_copy(
        update={
            "embedding_dimensions": 8,
            "qdrant_collection": "smartrag_test_" + uuid4().hex[:12],
            "parser_engine": "pymupdf",
        }
    )
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    engine = create_engine(
        url, connect_args={"check_same_thread": False} if "sqlite" in url else {}
    )
    if "sqlite" in url:

        @event.listens_for(engine, "connect")
        def foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

    factory = sessionmaker(engine, expire_on_commit=False)
    from backend.app.conversations import checkpoints

    if "sqlite" in url:

        class TestSaver(SqliteSaver):
            def prune(self, thread_ids, *, strategy):
                for thread in thread_ids:
                    self.conn.execute(
                        "DELETE FROM checkpoints WHERE thread_id = ? AND checkpoint_id != "
                        "(SELECT MAX(checkpoint_id) FROM checkpoints WHERE thread_id = ?)",
                        (thread, thread),
                    )
                    self.conn.execute("DELETE FROM writes WHERE thread_id = ?", (thread,))
                self.conn.commit()

        @contextmanager
        def isolated_checkpoint(_db):
            with sqlite3.connect(tmp_path / "checkpoints.db", check_same_thread=False) as conn:
                yield TestSaver(conn)

        monkeypatch.setattr(checkpoints, "checkpoint_store", isolated_checkpoint)
    else:
        checkpoints.setup_checkpoints(engine)
    resources = Resources.__new__(Resources)
    resources.settings = settings
    resources.store = MemoryStore()
    resources.qdrant = (
        QdrantClient(url=os.environ["TEST_QDRANT_URL"], timeout=60)
        if "TEST_QDRANT_URL" in os.environ
        else QdrantClient(":memory:")
    )
    resources.redis = (
        Redis.from_url(os.environ["TEST_REDIS_URL"]) if "TEST_REDIS_URL" in os.environ else Mock()
    )
    if "TEST_REDIS_URL" not in os.environ:
        resources.redis.eval.return_value = 1
    else:
        resources.redis.flushdb()
    if "TEST_S3_ENDPOINT" in os.environ:
        resources.store = S3Store(
            settings.model_copy(
                update={
                    "s3_endpoint": os.environ["TEST_S3_ENDPOINT"],
                    "s3_access_key": "smartrag-test",
                    "s3_bucket": "smartrag-test",
                }
            )
        )
        client = resources.store.client
        if "smartrag-test" not in [item["Name"] for item in client.list_buckets()["Buckets"]]:
            client.create_bucket(Bucket="smartrag-test")
    resources._embedding = TestEmbeddings()
    resources._generator = Mock()
    resources._generator.answer.return_value = "Alpha revenue is 42 million dollars. [1]"
    ensure_collection(resources)

    def database() -> Iterator[Session]:
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_resources] = lambda: resources
    try:
        with TestClient(app) as client:
            yield client, factory, resources
    finally:
        app.dependency_overrides.clear()
        resources.qdrant.delete_collection(settings.qdrant_collection)
        resources.close()
        if "sqlite" not in url:
            from sqlalchemy import text

            with engine.begin() as conn:
                for table in (
                    "checkpoint_writes",
                    "checkpoint_blobs",
                    "checkpoints",
                    "checkpoint_migrations",
                ):
                    conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
        engine.dispose()
        command.downgrade(config, "base")
        get_settings.cache_clear()


def authenticate(client: TestClient, email: str = "alice@example.com") -> dict[str, str]:
    body = {"email": email, "password": "strong-test-password"}
    assert client.post("/api/v1/auth/register", json=body).status_code == 201
    response = client.post("/api/v1/auth/login", json=body)
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def ingest(stack: Any, pdf: bytes, headers: dict[str, str]) -> str:
    from backend.app.workers.ingestion import process_one

    client, factory, resources = stack
    response = client.post(
        "/api/v1/documents", headers=headers, files={"file": ("report.pdf", pdf, "application/pdf")}
    )
    assert response.status_code == 202, response.text
    document_id = response.json()["id"]
    with factory() as db:
        assert process_one(db, resources)
    assert (
        client.get(f"/api/v1/documents/{document_id}", headers=headers).json()["status"] == "ready"
    )
    return document_id
