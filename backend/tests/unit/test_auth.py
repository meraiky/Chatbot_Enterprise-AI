from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.core import auth
from main import app


@pytest.mark.asyncio
async def test_get_current_user_requires_token_without_dev_bypass(monkeypatch):
    monkeypatch.setattr(auth.settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(auth.settings, "ALLOW_DEV_AUTH_BYPASS", False)
    monkeypatch.setattr(auth.settings, "JWT_SECRET_KEY", "test-secret")

    with pytest.raises(auth.HTTPException) as exc:
        await auth.get_current_user(None)

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_access_token_round_trip(monkeypatch):
    monkeypatch.setattr(auth.settings, "JWT_SECRET_KEY", "test-secret")

    token = auth.create_access_token({"sub": "alice", "role": "admin"}, expires_delta=timedelta(minutes=5))
    user = auth.decode_access_token(token)

    assert user is not None
    assert user.username == "alice"
    assert user.role == "admin"


@pytest.mark.asyncio
async def test_get_current_admin_rejects_non_admin_role():
    with pytest.raises(auth.HTTPException) as exc:
        await auth.get_current_admin(auth.TokenData(username="bob", role="user"))

    assert exc.value.status_code == 403


def test_create_admin_requires_admin_token(monkeypatch):
    monkeypatch.setattr(auth.settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(auth.settings, "ALLOW_DEV_AUTH_BYPASS", False)
    monkeypatch.setattr(auth.settings, "JWT_SECRET_KEY", "test-secret")
    app.dependency_overrides.clear()

    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/create-admin",
        json={"username": "newadmin", "password": "securepass123"},
    )

    assert response.status_code == 401
