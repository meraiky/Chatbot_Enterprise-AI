import pytest
from pydantic import ValidationError

from app.api.v1 import users


def test_custom_endpoint_rejects_private_network_host(monkeypatch):
    monkeypatch.setattr(users.settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(users.settings, "CUSTOM_ENDPOINT_ALLOWLIST", "")

    with pytest.raises(ValidationError):
        users.ModelConfigCreate(
            name="Bad endpoint",
            provider="custom",
            custom_endpoint="https://169.254.169.254/latest/meta-data",
        )


def test_custom_endpoint_requires_allowlist_in_production(monkeypatch):
    monkeypatch.setattr(users.settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(users.settings, "CUSTOM_ENDPOINT_ALLOWLIST", "")

    with pytest.raises(ValidationError):
        users.ModelConfigCreate(
            name="Needs allowlist",
            provider="custom",
            custom_endpoint="https://llm.example.com/v1",
        )


def test_custom_endpoint_accepts_allowlisted_https_host(monkeypatch):
    monkeypatch.setattr(users.settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(users.settings, "CUSTOM_ENDPOINT_ALLOWLIST", "llm.example.com")

    config = users.ModelConfigCreate(
        name="Allowed endpoint",
        provider="custom",
        custom_endpoint="https://llm.example.com/v1",
    )

    assert config.custom_endpoint == "https://llm.example.com/v1"
