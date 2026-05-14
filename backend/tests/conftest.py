import pytest
import pytest_asyncio
import asyncio
from httpx import AsyncClient
from main import app
from app.api.v1 import chat as chat_api
from app.api.v1.chat import _last_request_time
from app.core.auth import TokenData, get_current_user
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

from httpx import ASGITransport

@pytest.fixture(autouse=True)
def auth_override():
    """Bypass OAuth in API tests; auth behavior is covered separately."""
    async def _mock_current_user():
        return TokenData(username="test-user", role="admin")

    app.dependency_overrides[get_current_user] = _mock_current_user
    _last_request_time.clear()
    chat_api._rate_limit_client = None
    yield
    app.dependency_overrides.clear()
    _last_request_time.clear()
    chat_api._rate_limit_client = None


@pytest_asyncio.fixture
async def client():
    """FastAPI Test Client."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

@pytest.fixture
def mock_llm():
    """Mock for the LLM service."""
    with patch("app.services.rag.query_engine._build_chain") as mock:
        mock_chain = MagicMock()
        mock_chain.invoke.return_value = "This is a mocked LLM response."
        mock_chain.stream.return_value = ["This ", "is ", "streamed."]
        mock.return_value = mock_chain
        yield mock

@pytest.fixture
def mock_vector_store():
    """Mock for the Vector Store."""
    with patch("app.services.rag.query_engine.get_vector_store") as mock:
        mock_store = MagicMock()
        # Mock similarity_search_with_score
        mock_store.similarity_search_with_score.return_value = [
            (MagicMock(page_content="Mocked context 1", metadata={"source": "test.pdf", "page": 1}), 0.1),
            (MagicMock(page_content="Mocked context 2", metadata={"source": "test.pdf", "page": 2}), 0.2),
        ]
        # Mock collection.get
        mock_store._collection.get.return_value = {
            "documents": ["Mocked context 1", "Mocked context 2"],
            "metadatas": [{"source": "test.pdf", "page": 1}, {"source": "test.pdf", "page": 2}]
        }
        mock.return_value = mock_store
        yield mock

@pytest.fixture
def mock_db():
    """Mock for the database connection."""
    with patch("app.services.topic_guard_service.get_conn") as mock_topic_conn, \
         patch("app.services.rag.cache_service.get_conn") as mock_cache_conn:
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_topic_conn.return_value.__enter__.return_value = mock_conn
        mock_cache_conn.return_value.__enter__.return_value = mock_conn
        yield mock_cur


@pytest.fixture(autouse=True)
def mock_query_cache():
    """Keep unit tests off Redis, Postgres vector cache, and embedding APIs."""
    with patch("app.services.rag.query_engine.cache_service") as mock_cache, \
         patch("app.services.rag.query_engine.reranker") as mock_reranker:
        mock_cache.get_cached_answer.return_value = None
        mock_reranker.rerank.side_effect = (
            lambda _question, documents: [(document, 1.0) for document in documents]
        )
        yield mock_cache
