from app.core.redaction import redact_sensitive


def test_redact_sensitive_masks_secrets_and_connection_passwords():
    message = (
        "DATABASE_URL=postgresql://postgres:supersecret@localhost:5432/app "
        "postgresql://postgres:anothersecret@db:5432/app "
        "Authorization: Bearer eyJabc.def.ghi "
        "OPENAI_API_KEY=sk-testsecretvaluewithmorethan20chars "
        "email admin@example.com"
    )

    redacted = redact_sensitive(message)

    assert "supersecret" not in redacted
    assert "anothersecret" not in redacted
    assert "eyJabc.def.ghi" not in redacted
    assert "sk-testsecretvaluewithmorethan20chars" not in redacted
    assert "admin@example.com" not in redacted
    assert "[PASSWORD_REDACTED]" in redacted
    assert "[JWT_TOKEN_REDACTED]" in redacted
    assert "[SECRET_REDACTED]" in redacted
    assert "[EMAIL_REDACTED]" in redacted
