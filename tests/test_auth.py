from datetime import timedelta

import jwt
import pytest
from sqlalchemy import select

from backend.app.core.config import get_settings
from backend.app.models.entities import User, now
from tests.conftest import authenticate


def test_registration_login_logout(stack):
    client, factory, _ = stack
    headers = authenticate(client, "Alice@example.com")
    response = client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["email"] == "alice@example.com"
    with factory() as db:
        user = db.scalar(select(User))
        assert user.password_hash.startswith("$argon2id$")
        assert "strong-test-password" not in user.password_hash
    assert (
        client.post(
            "/api/v1/auth/register",
            json={"email": "alice@example.com", "password": "strong-test-password"},
        ).status_code
        == 409
    )
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_wrong_credentials_and_validation(stack):
    client, _, _ = stack
    authenticate(client)
    for email in ["alice@example.com", "unknown@example.com"]:
        assert (
            client.post(
                "/api/v1/auth/login", json={"email": email, "password": "wrong-password-value"}
            ).status_code
            == 401
        )
    assert (
        client.post("/api/v1/auth/register", json={"email": "bad", "password": "short"}).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/auth/register",
            json={
                "email": "bob@example.com",
                "password": "strong-test-password",
                "user_id": "injected",
            },
        ).status_code
        == 422
    )


@pytest.mark.parametrize("path", ["/auth/me", "/documents", "/conversations"])
def test_unauthorized(stack, path):
    client, _, _ = stack
    assert client.get("/api/v1" + path).status_code == 401
    assert (
        client.get("/api/v1" + path, headers={"Authorization": "Bearer invalid"}).status_code == 401
    )


@pytest.mark.parametrize(
    "change", ["expired", "issuer", "audience", "algorithm", "signature", "missing"]
)
def test_jwt_validation(stack, change):
    client, _, _ = stack
    headers = authenticate(client)
    settings = get_settings()
    secret = settings.jwt_secret.get_secret_value()
    token = headers["Authorization"].split()[1]
    claims = jwt.decode(token, secret, algorithms=["HS256"], audience=settings.jwt_audience)
    if change == "expired":
        claims["exp"] = now() - timedelta(seconds=1)
    elif change == "issuer":
        claims["iss"] = "attacker"
    elif change == "audience":
        claims["aud"] = "attacker"
    elif change == "missing":
        del claims["exp"]
    token = jwt.encode(
        claims,
        "wrong-secret-at-least-32-characters" if change == "signature" else secret,
        algorithm="HS384" if change == "algorithm" else "HS256",
    )
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code
        == 401
    )
