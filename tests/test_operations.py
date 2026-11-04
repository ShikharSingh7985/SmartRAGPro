from unittest.mock import Mock

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from pydantic import ValidationError

from backend.app.core.config import get_settings
from backend.app.models.entities import Base


def test_migrations_round_trip_and_no_drift(stack):
    _, factory, _ = stack
    with factory() as db:
        assert compare_metadata(MigrationContext.configure(db.connection()), Base.metadata) == []
    config = Config("alembic.ini")
    command.downgrade(config, "base")
    command.upgrade(config, "head")


def test_configuration_rejects_placeholder(stack):
    with pytest.raises(ValidationError):
        type(get_settings())(jwt_secret="CHANGE_ME_placeholder_longer_than_32_characters")


def test_health_and_openapi(stack):
    client, _, _ = stack
    assert client.get("/health/live").status_code == 200
    # No live key in isolated tests; readiness reports unavailable, never a fictitious success.
    assert client.get("/health/ready").status_code == 503
    assert "/api/v1/documents" in client.get("/openapi.json").json()["paths"]


def test_rate_limiting_and_fail_closed(stack):
    client, _, resources = stack
    resources.redis = Mock()
    resources.redis.eval.return_value = 21
    assert client.post("/api/v1/auth/login", json={}).status_code == 429
    resources.redis.eval.side_effect = RuntimeError("private")
    response = client.get("/api/v1/documents")
    assert response.status_code == 503
    assert "private" not in response.text
