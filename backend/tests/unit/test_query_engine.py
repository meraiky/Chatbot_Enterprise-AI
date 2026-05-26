from unittest.mock import patch

from langchain_core.documents import Document

from app.services.rag.query_engine import (
    CHIT_CHAT_REPLY,
    OUT_OF_SCOPE_REPLY,
    OUT_OF_SCOPE_REPLY_VI,
    _classify_light_intent,
    _out_of_scope_reply,
    _rrf_fuse_results,
    answer_query,
    answer_query_stream,
    retrieve_context,
)

# ---------------------------------------------------------------------------
# Light intent classification
# ---------------------------------------------------------------------------

def test_light_intent_classification():
    assert _classify_light_intent("xin chào") == "chit_chat"
    assert _classify_light_intent("ban viet tieng viet duoc khong") == "chit_chat"
    assert _classify_light_intent("What is the weather today?") == "out_of_scope"
    assert _classify_light_intent("How do I request annual leave?") == "rag"


def test_light_intent_new_vi_keywords():
    """New Vietnamese keywords added in improvement round should be detected."""
    assert _classify_light_intent("Tỷ giá hôm nay bao nhiêu?") == "out_of_scope"
    assert _classify_light_intent("Giá đô la hôm nay là bao nhiêu?") == "out_of_scope"
    assert _classify_light_intent("Kết quả bóng đá tối qua thế nào?") == "out_of_scope"
    assert _classify_light_intent("Cho tôi xem phim hoạt hình") == "out_of_scope"
    assert _classify_light_intent("Nghe nhạc đi bạn") == "out_of_scope"
    assert _classify_light_intent("Dự báo thời tiết ngày mai") == "out_of_scope"
    assert _classify_light_intent("Giá cổ phiếu VNM hôm nay?") == "out_of_scope"


# ---------------------------------------------------------------------------
# out_of_scope reply language routing
# ---------------------------------------------------------------------------

def test_out_of_scope_reply_english_for_english_question():
    reply = _out_of_scope_reply("What is the stock price today?")
    assert reply == OUT_OF_SCOPE_REPLY


def test_out_of_scope_reply_vietnamese_for_vi_question():
    reply = _out_of_scope_reply("Thời tiết hôm nay thế nào?")
    assert reply == OUT_OF_SCOPE_REPLY_VI


# ---------------------------------------------------------------------------
# answer_query guardrail integration
# ---------------------------------------------------------------------------

def test_answer_query_chit_chat_skips_retrieval(mock_query_cache):
    result = answer_query("hello", "External")

    assert result["reply"] == CHIT_CHAT_REPLY
    assert result["sources"] == []
    assert result["usage"]["total_tokens"] == 0
    mock_query_cache.get_cached_answer.assert_not_called()


def test_answer_query_out_of_scope_skips_retrieval(mock_query_cache):
    result = answer_query("What is the weather today?", "External")

    assert result["reply"] == OUT_OF_SCOPE_REPLY
    assert result["blocked"] is True
    assert result["guardrail"]["type"] == "out_of_scope"
    mock_query_cache.get_cached_answer.assert_not_called()


def test_answer_query_out_of_scope_vi_returns_vi_reply(mock_query_cache):
    """Vietnamese out-of-scope question should get a Vietnamese rejection."""
    result = answer_query("Tỷ giá hôm nay là bao nhiêu?", "External")

    assert result["reply"] == OUT_OF_SCOPE_REPLY_VI
    assert result["blocked"] is True
    assert result["guardrail"]["type"] == "out_of_scope"
    mock_query_cache.get_cached_answer.assert_not_called()


def test_answer_query_stream_chit_chat_skips_retrieval(mock_query_cache):
    chunks = list(answer_query_stream("hello", "External"))

    assert chunks == [CHIT_CHAT_REPLY]
    mock_query_cache.get_cached_answer.assert_not_called()


def test_answer_query_stream_out_of_scope_vi_returns_vi_reply(mock_query_cache):
    """answer_query_stream should yield Vietnamese out-of-scope reply for VI questions."""
    chunks = list(answer_query_stream("Giá cổ phiếu VNM hôm nay là bao nhiêu?", "External"))

    assert chunks == [OUT_OF_SCOPE_REPLY_VI]
    mock_query_cache.get_cached_answer.assert_not_called()


def test_rrf_fusion_prioritizes_cross_retriever_hits():
    doc_a = Document(page_content="A", metadata={"source": "a.pdf"})
    doc_b = Document(page_content="B", metadata={"source": "b.pdf"})
    doc_c = Document(page_content="C", metadata={"source": "c.pdf"})

    fused = _rrf_fuse_results(
        vector_results=[(doc_a, 0.2), (doc_b, 0.3)],
        bm25_docs=[(doc_b, 8.0), (doc_c, 7.0)],
        limit=3,
        rrf_k=60,
    )

    assert [doc.page_content for doc, _score in fused] == ["B", "A", "C"]


def test_retrieve_context_empty_corpus_returns_no_context(mock_vector_store, mock_db):
    store = mock_vector_store.return_value
    store.similarity_search_with_score.return_value = []
    store._collection.get.return_value = {"documents": [], "metadatas": []}

    context, sources, usage = retrieve_context("How do I create AR?", "External", "test-req-empty")

    assert context == ""
    assert sources == []
    assert usage is not None


def test_retrieve_context_success(mock_vector_store, mock_db):
    """Test that context is correctly retrieved and formatted."""
    question = "What is the company policy on remote work?"
    mode = "Internal"
    request_id = "test-req-123"
    
    context, sources, usage = retrieve_context(question, mode, request_id)
    
    assert "Mocked context 1" in context
    assert "Mocked context 2" in context
    assert len(sources) == 2
    assert sources[0]["source"] == "test.pdf"
    assert usage is not None

def test_answer_query_blocked_by_guard(mock_llm, mock_vector_store, mock_db):
    """Test that answer_query returns a blocked response if topic guard triggers."""
    # Mock topic guard to block the request
    with patch("app.services.rag.query_engine.check_topic_guard") as mock_guard:
        mock_guard.return_value = (True, "This topic is restricted.")
        
        question = "What is the CEO's salary?"
        mode = "Internal"
        
        # We need to mock answer_query's internal call to check_topic_guard
        # Since answer_query is the function under test, we patch the service it calls
        result = answer_query(question, mode)
        
        assert "restricted" in result["reply"].lower()
        assert result["sources"] == []
        assert result["blocked"] is True

def test_answer_query_success(mock_llm, mock_vector_store, mock_db):
    """Test the full answer_query flow."""
    # Mock topic guard to allow
    with patch("app.services.rag.query_engine.check_topic_guard") as mock_guard:
        mock_guard.return_value = (False, None)
        
        question = "How do I request a vacation?"
        mode = "Internal"
        
        result = answer_query(question, mode)
        
        assert "reply" in result
        assert "sources" in result
        assert len(result["sources"]) > 0
        assert result["reply"] == "This is a mocked LLM response."
        assert result["cache_hit"] is False
