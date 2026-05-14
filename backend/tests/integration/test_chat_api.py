import pytest
from unittest.mock import patch

@pytest.mark.asyncio
async def test_chat_message_success(client, mock_llm, mock_vector_store, mock_db):
    """Test the chat message endpoint returns a successful response."""
    payload = {
        "question": "Hello, how are you?",
        "mode": "Internal",
        "history": []
    }
    
    # Mock answer_query to return a fixed response
    with patch("app.api.v1.chat.answer_query") as mock_answer:
        mock_answer.return_value = {
            "reply": "I am doing well, thank you!",
            "sources": [],
            "cache_hit": False,
            "blocked": False,
            "usage": {
                "request_id": "req-test",
                "records": [],
                "total_tokens": 10,
            },
        }
        
        response = await client.post("/api/v1/chat/message", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        assert data["reply"] == "I am doing well, thank you!"

@pytest.mark.asyncio
async def test_chat_message_rate_limit(client):
    """Test that repeating the same question too quickly triggers rate limiting."""
    payload = {
        "question": "Rate limit test",
        "mode": "Internal"
    }
    
    # First request should succeed
    with patch("app.api.v1.chat._get_rate_limit_client", return_value=None), \
         patch("app.api.v1.chat.answer_query") as mock_answer:
        mock_answer.return_value = {
            "reply": "OK",
            "sources": [],
            "cache_hit": False,
            "blocked": False,
            "usage": {
                "request_id": "req-test",
                "records": [],
                "total_tokens": 0,
            },
        }

        resp1 = await client.post("/api/v1/chat/message", json=payload)
        assert resp1.status_code == 200

        # Second identical request immediately after should be rate limited
        resp2 = await client.post("/api/v1/chat/message", json=payload)
        assert resp2.status_code == 429
        assert "Please wait" in resp2.json()["detail"]

@pytest.mark.asyncio
async def test_chat_message_validation_error(client):
    """Test that invalid payloads return 422 Unprocessable Entity."""
    # Missing 'question' field
    payload = {
        "mode": "Internal"
    }
    
    response = await client.post("/api/v1/chat/message", json=payload)
    assert response.status_code == 422

@pytest.mark.asyncio
async def test_chat_message_stream_basic(client, mock_llm, mock_vector_store, mock_db):
    """Test that the streaming endpoint returns a 200 response."""
    payload = {
        "question": "Stream test",
        "mode": "Internal"
    }

    with patch("app.api.v1.chat.answer_query_stream_events") as mock_stream:
        mock_stream.return_value = [
            {"event": "token", "data": {"text": "Chunk 1"}},
            {"event": "token", "data": {"text": "Chunk 2"}},
            {"event": "metadata", "data": {"sources": [], "usage": {"total_tokens": 0}}},
            {"event": "done", "data": {}},
        ]

        response = await client.post("/api/v1/chat/message/stream", json=payload)
        assert response.status_code == 200

        content = await response.aread()
        assert b"event: token" in content
        assert b"Chunk 1" in content
        assert b"event: metadata" in content


@pytest.mark.asyncio
async def test_chat_message_rate_limit_with_redis(client):
    payload = {
        "question": "Redis rate limit test",
        "mode": "Internal"
    }

    class FakeRedis:
        def __init__(self):
            self.calls = 0

        def set(self, _key, _value, nx=True, ex=None):
            assert nx is True
            assert ex == 2
            self.calls += 1
            return self.calls == 1

    with patch("app.api.v1.chat._get_rate_limit_client", return_value=FakeRedis()), \
         patch("app.api.v1.chat.answer_query") as mock_answer:
        mock_answer.return_value = {
            "reply": "OK",
            "sources": [],
            "cache_hit": False,
            "blocked": False,
            "usage": {
                "request_id": "req-test",
                "records": [],
                "total_tokens": 0,
            },
        }

        resp1 = await client.post("/api/v1/chat/message", json=payload)
        assert resp1.status_code == 200

        resp2 = await client.post("/api/v1/chat/message", json=payload)
        assert resp2.status_code == 429


@pytest.mark.asyncio
async def test_chat_message_sanitizes_internal_error(client):
    payload = {
        "question": "Failure test",
        "mode": "Internal",
    }

    with patch("app.api.v1.chat.answer_query", side_effect=Exception("database password leaked")):
        response = await client.post("/api/v1/chat/message", json=payload)

    assert response.status_code == 500
    assert response.json()["detail"] == "Internal server error. Please try again later."


@pytest.mark.asyncio
async def test_chat_message_stream_sanitizes_internal_error(client):
    payload = {
        "question": "Stream failure test",
        "mode": "Internal",
    }

    with patch("app.api.v1.chat.answer_query_stream_events", side_effect=Exception("database password leaked")):
        response = await client.post("/api/v1/chat/message/stream", json=payload)

    assert response.status_code == 200
    content = await response.aread()
    assert b"Internal server error. Please try again later." in content
    assert b"database password leaked" not in content
