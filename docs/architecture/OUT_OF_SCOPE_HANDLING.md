# Out-of-Scope Question Handling

## Overview

This document explains how AIAgentChatbot handles user questions that are not covered by the indexed document collection.

The project uses multiple guardrails to avoid hallucinated answers and reduce unnecessary LLM/token usage.

---

## 1. Current Behavior

When a user asks a question outside the document knowledge base, the system can respond through three layers:

1. **Light intent guard** before retrieval.
2. **Retrieval confidence guard** after hybrid search and reranking.
3. **Prompt-level context-only instruction** before LLM generation.

Relevant implementation: `backend/app/services/rag/query_engine.py`.

---

## 2. Layer 1 - Light Intent Guard

The system first classifies the question using `_classify_light_intent()`.

It can return:

- `empty`: user submitted an empty question.
- `chit_chat`: greeting or capability question.
- `out_of_scope`: obvious unrelated topic.
- `rag`: normal document-grounded question.

Examples of currently detected out-of-scope topics:

- weather
- stock price
- football score
- recipe/cooking
- giá vàng
- chứng khoán
- thời tiết

### Example

User asks:

```text
Thời tiết hôm nay thế nào?
```

The system detects `thoi tiet` and returns an out-of-scope response without retrieval or LLM generation.

Current response shape:

```text
I can only answer questions related to the indexed knowledge base. Please ask about uploaded company documents, policies, processes, or public FAQs.
```

---

## 3. Layer 2 - Retrieval Confidence Guard

If the question is classified as `rag`, the system runs hybrid retrieval:

```text
question
  -> Chroma vector search
  -> BM25 keyword search
  -> RRF fusion
  -> cross-encoder reranking
```

After reranking, the system checks the best reranker score.

If there are no final results, or if the best score is lower than `MIN_RERANK_SCORE`, the system returns no context:

```python
if final_results and float(final_results[0][1]) < settings.MIN_RERANK_SCORE:
    return "", [], retrieval_usage
```

Then the answer becomes a no-context message.

Vietnamese no-context response:

```text
Mình chưa tìm thấy nội dung phù hợp trong kho tài liệu hiện tại. Bạn đang hỏi ở chế độ {mode}; hãy kiểm tra tài liệu đã được upload đúng chế độ chưa.
```

English no-context response:

```text
I don't have enough information to answer that based on my current knowledge base. You are asking in {mode} mode; check that the document was uploaded to the same mode.
```

---

## 4. Layer 3 - Prompt-Level Guard

Even when context exists, the prompt instructs the LLM to answer only from the provided context:

```text
Answer based ONLY on the following context. If the context does not contain the answer, say "{no_context_answer}"
```

This is the final protection layer against hallucination.

---

## 5. Example Outcomes

| User question | Expected handling | Result |
|---|---|---|
| `Xin chào` | Light intent guard | Chit-chat reply, no retrieval |
| `Bạn trả lời tiếng Việt được không?` | Light intent guard | Chit-chat/capability reply |
| `Thời tiết hôm nay thế nào?` | Light intent guard | Out-of-scope reply |
| `Giá vàng hôm nay bao nhiêu?` | Light intent guard | Out-of-scope reply |
| `Quy trình nghỉ phép là gì?` but no HR document exists | Retrieval confidence guard | No-context reply |
| `Scrum có mấy vai trò?` when Scrum PDF exists | RAG pipeline | Grounded answer with source citation |
| `Kể chuyện cười đi` | Prompt/retrieval guard | No-context or out-of-scope reply depending classifier |

---

## 6. Assessment

Current implementation is safe and suitable for enterprise RAG because it:

- avoids answering from model memory when documents do not support the answer;
- prevents obvious unrelated queries from spending retrieval/LLM tokens;
- returns user-friendly no-context messages;
- records audit and usage metadata for observability.

Score for current out-of-scope handling: **8.2/10**.

---

## 7. Recommended Improvements

### 7.1 Expand Vietnamese Out-of-Scope Keywords

Current keywords cover common topics, but should include more Vietnamese variants.

Suggested additions:

```python
_OUT_OF_SCOPE_KEYWORDS = (
    "weather",
    "stock price",
    "football score",
    "recipe",
    "cook",
    "nau",
    "thoi tiet",
    "du bao thoi tiet",
    "gia vang",
    "gia do la",
    "ty gia",
    "chung khoan",
    "co phieu",
    "bong da",
    "ket qua bong da",
    "xem phim",
    "nghe nhac",
)
```

### 7.2 Return Vietnamese Out-of-Scope Reply

Currently the generic out-of-scope reply is English. Add a Vietnamese version:

```python
OUT_OF_SCOPE_REPLY_VI = (
    "Mình chỉ có thể trả lời các câu hỏi liên quan đến kho tài liệu đã được tải lên, "
    "chính sách, quy trình, sản phẩm hoặc FAQ công khai."
)
```

Then choose response language based on `_prefers_vietnamese(question)`.

### 7.3 Add Out-of-Scope Category Metadata

Return metadata so the frontend can show why a question was rejected:

```json
{
  "answer": "...",
  "sources": [],
  "guardrail": {
    "type": "out_of_scope",
    "reason": "question does not match indexed knowledge base"
  }
}
```

### 7.4 Add UI Suggestions

When no context is found, the UI should suggest actions:

- Upload a relevant document.
- Switch Internal/External mode.
- Ask a more specific question.
- Check available documents.

### 7.5 Add Tests

Recommended test cases:

```python
def test_vietnamese_weather_is_out_of_scope():
    assert _classify_light_intent("Thời tiết hôm nay thế nào?") == "out_of_scope"


def test_unknown_document_question_returns_no_context():
    answer = answer_query("Quy định nghỉ thai sản là gì?", mode="Internal")
    assert "chưa tìm thấy" in answer["answer"].lower()
    assert answer["sources"] == []
```

---

## 8. Recommended UX Copy

### Vietnamese

```text
Mình chưa tìm thấy nội dung phù hợp trong kho tài liệu hiện tại.

Bạn có thể thử:
- kiểm tra tài liệu đã được upload đúng chế độ Internal/External chưa;
- hỏi cụ thể hơn, ví dụ kèm tên quy trình hoặc tài liệu;
- upload thêm tài liệu liên quan nếu nội dung này chưa có trong hệ thống.
```

### English

```text
I could not find enough information in the current knowledge base.

You can try:
- checking whether the document was uploaded to the correct Internal/External mode;
- asking a more specific question with the process or document name;
- uploading a relevant document if this topic is not indexed yet.
```

---

## 9. Target State

Target behavior for 9.5/10:

- More Vietnamese out-of-scope coverage.
- Localized out-of-scope response.
- Guardrail metadata in API response.
- UI suggestions for next actions.
- Unit tests for out-of-scope and no-context paths.
- Retrieval evaluation set includes negative questions.
