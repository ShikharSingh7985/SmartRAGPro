import math
import os
from collections.abc import Iterator
from io import BytesIO
from typing import Any
from unittest.mock import Mock

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from langchain_core.embeddings import Embeddings
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
            float(text.casefold().count(word))
            for word in ["alpha", "beta", "revenue", "million", "policy", "leave", "days", "secret"]
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
def stack(tmp_path) -> Iterator[tuple[TestClient, sessionmaker[Session], Resources]]:
    url = os.environ.get("TEST_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    if not url.startswith("sqlite") and not url.endswith("/smartrag_test"):
        raise RuntimeError("Integration tests require a dedicated smartrag_test database")
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    settings = get_settings().model_copy(
        update={
            "embedding_dimensions": 8,
            "qdrant_collection": "smartrag_test",
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
    resources = Resources.__new__(Resources)
    resources.settings = settings
    resources.store = MemoryStore()
    resources.qdrant = (
        QdrantClient(url=os.environ["TEST_QDRANT_URL"])
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
