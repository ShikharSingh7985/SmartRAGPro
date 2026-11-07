"""Real Redis pause in the explicitly disposable integration fixture only."""

import os
import time

import pytest
from redis import Redis

from tests.conftest import authenticate


def test_real_redis_timeout_fails_closed_and_recovers(stack):
    if "TEST_REDIS_URL" not in os.environ:
        pytest.skip("Requires disposable Redis service")
    client, _, resources = stack
    headers = authenticate(client)
    original = resources.redis
    short = Redis.from_url(
        os.environ["TEST_REDIS_URL"], socket_timeout=0.15, retry_on_timeout=False
    )
    resources.redis = short
    try:
        original.execute_command("CLIENT", "PAUSE", 1500, "ALL")
        response = client.get("/api/v1/documents", headers=headers)
        assert response.status_code == 503
        assert response.json()["error"]["retryable"] is True
    finally:
        time.sleep(1.6)
        resources.redis = original
        short.close()
    assert client.get("/api/v1/documents", headers=headers).status_code == 200
