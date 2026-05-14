import os
import time

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "60"))
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "10"))

st.set_page_config(
    page_title="Enterprise AI Chatbot",
    page_icon=":material/smart_toy:",
    layout="wide",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def api_error_message(response: requests.Response) -> str:
    try:
        detail = response.json().get("detail")
        if detail:
            return detail
    except ValueError:
        pass
    return response.text or f"HTTP {response.status_code}"


def api_get(path: str) -> requests.Response:
    return requests.get(f"{API_URL}{path}", timeout=REQUEST_TIMEOUT)


def api_post(path: str, **kwargs) -> requests.Response:
    return requests.post(f"{API_URL}{path}", timeout=REQUEST_TIMEOUT, **kwargs)


def api_patch(path: str, **kwargs) -> requests.Response:
    return requests.patch(f"{API_URL}{path}", timeout=REQUEST_TIMEOUT, **kwargs)


def api_delete(path: str) -> requests.Response:
    return requests.delete(f"{API_URL}{path}", timeout=REQUEST_TIMEOUT)


def _build_history_payload(messages: list[dict]) -> list[dict]:
    """
    Return the last MAX_HISTORY_MESSAGES turns (user + assistant pairs)
    in the format the API expects: [{role, content}, ...].
    Strips out sidebar-only keys like 'sources' and 'usage'.
    """
    clean = [{"role": m["role"], "content": m["content"]} for m in messages]
    return clean[-MAX_HISTORY_MESSAGES:]


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def render_sidebar() -> str:
    st.sidebar.title("Enterprise AI")
    st.sidebar.caption(f"API: {API_URL}")

    try:
        health = requests.get(f"{API_URL}/", timeout=5)
        if health.ok:
            st.sidebar.success("Backend online")
        else:
            st.sidebar.warning("Backend responded with an error")
    except requests.RequestException:
        st.sidebar.error("Backend offline")

    render_usage_snapshot()
    return st.sidebar.radio("Go to", ["Chat", "Admin Dashboard"])


def render_usage_snapshot():
    try:
        response = api_get("/api/v1/usage/summary")
    except requests.RequestException:
        return

    if not response.ok:
        return

    summary = response.json()
    st.sidebar.divider()
    st.sidebar.caption("Token usage")
    col1, col2 = st.sidebar.columns(2)
    col1.metric("Total", f"{summary.get('total_tokens', 0):,}")
    col2.metric("Actual", f"{summary.get('actual_tokens', 0):,}")
    st.sidebar.caption(f"Estimated: {summary.get('estimated_tokens', 0):,}")

    # Cache-hit stat from session
    total_questions = st.session_state.get("total_questions", 0)
    cache_hits = st.session_state.get("cache_hits", 0)
    if total_questions > 0:
        st.sidebar.divider()
        st.sidebar.caption("Cache performance (this session)")
        ratio = cache_hits / total_questions * 100
        st.sidebar.metric("Cache hits", f"{cache_hits}/{total_questions}", f"{ratio:.0f}%")


# ---------------------------------------------------------------------------
# Chat page
# ---------------------------------------------------------------------------

def main():
    page = render_sidebar()
    if page == "Chat":
        chat_page()
    elif page == "Admin Dashboard":
        admin_page()


def chat_page():
    st.title("Enterprise AI Chatbot")
    st.markdown("Welcome! Ask questions based on the uploaded documents.")

    mode = st.radio("Select Mode", ["Internal", "External"], horizontal=True)

    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "total_questions" not in st.session_state:
        st.session_state.total_questions = 0
    if "cache_hits" not in st.session_state:
        st.session_state.cache_hits = 0

    col_clear, col_info = st.columns([1, 5])
    with col_clear:
        if st.button("Clear chat", type="secondary"):
            st.session_state.messages = []
            st.session_state.total_questions = 0
            st.session_state.cache_hits = 0
            st.rerun()

    # Render existing messages
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message.get("cache_hit"):
                st.caption("⚡ Answered from cache (0 tokens used)")
            if message.get("sources"):
                render_sources(message["sources"])
            if message.get("usage"):
                render_message_usage(message["usage"])

    # New message
    if prompt := st.chat_input("Ask about your uploaded documents"):
        st.chat_message("user").markdown(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.session_state.total_questions += 1

        # Build history to send (exclude the message we just appended)
        history_payload = _build_history_payload(st.session_state.messages[:-1])

        with st.chat_message("assistant"):
            try:
                with st.spinner("Thinking..."):
                    response = api_post(
                        "/api/v1/chat/message",
                        json={
                            "question": prompt,
                            "mode": mode,
                            "stream": False,
                            "history": history_payload,
                        },
                    )
                if response.ok:
                    payload = response.json()
                    answer = payload.get("reply", "No response.")
                    sources = payload.get("sources", [])
                    usage = payload.get("usage")
                    cache_hit = payload.get("cache_hit", False)

                    if cache_hit:
                        st.session_state.cache_hits += 1

                    st.markdown(answer)
                    if cache_hit:
                        st.caption("⚡ Answered from cache (0 tokens used)")
                    render_sources(sources)
                    render_message_usage(usage)

                    st.session_state.messages.append(
                        {
                            "role": "assistant",
                            "content": answer,
                            "sources": sources,
                            "usage": usage,
                            "cache_hit": cache_hit,
                        }
                    )
                elif response.status_code == 429:
                    st.warning(f"⏳ Rate limit: {api_error_message(response)}")
                else:
                    st.error(f"Error: {api_error_message(response)}")
            except requests.RequestException as e:
                st.error(f"Backend connection failed: {e}")


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def render_message_usage(usage: dict | None):
    if not usage:
        return

    total_tokens = usage.get("total_tokens", 0)
    records = usage.get("records", [])
    with st.expander(f"Token usage: {total_tokens:,}", expanded=False):
        for record in records:
            label = "estimated" if record.get("estimated") else "actual"
            st.caption(
                f"{record.get('operation')} — {record.get('model')} — "
                f"{record.get('total_tokens', 0):,} tokens ({label})"
            )


def render_sources(sources: list[dict]):
    if not sources:
        return

    with st.expander("Sources", expanded=False):
        for source in sources:
            page = source.get("page") or "unknown"
            st.markdown(
                f"**{source.get('rank')}. {source.get('source', 'Unknown')}** "
                f"— page {page} — distance {source.get('distance')}"
            )
            st.caption(source.get("preview", ""))


# ---------------------------------------------------------------------------
# Admin page
# ---------------------------------------------------------------------------

def admin_page():
    st.title("Admin Dashboard")
    st.markdown("Manage Documents and Vector Database.")

    st.subheader("Upload Document (PDF)")
    doc_type = st.selectbox("Document Type", ["Internal", "External"])
    uploaded_file = st.file_uploader("Choose a PDF file", type="pdf")

    if st.button("Upload and Process", type="primary"):
        if uploaded_file is None:
            st.warning("Please select a file first.")
            return

        st.info("Processing document...")
        try:
            files = {"file": (uploaded_file.name, uploaded_file, "application/pdf")}
            data = {"doc_type": doc_type}
            response = api_post(
                "/api/v1/document/upload",
                files=files,
                data=data,
            )
            if response.ok:
                payload = response.json()
                chunks = payload.get("chunks_indexed", 0)
                replaced = payload.get("replaced_chunks", 0)
                st.success(
                    "Document uploaded and indexed successfully! "
                    f"({chunks} chunks created, {replaced} old chunks replaced)"
                )
                st.rerun()
            else:
                st.error(f"Error indexing document: {api_error_message(response)}")
        except requests.RequestException as e:
            st.error(f"Backend connection failed: {e}")

    st.divider()
    render_document_library()
    st.divider()
    render_usage_dashboard()


def render_document_library():
    st.subheader("Indexed Documents")

    try:
        response = api_get("/api/v1/document")
    except requests.RequestException as e:
        st.error(f"Backend connection failed: {e}")
        return

    if not response.ok:
        st.error(f"Error loading documents: {api_error_message(response)}")
        return

    documents = response.json().get("documents", [])
    if not documents:
        st.info("No indexed documents yet.")
        return

    for document in documents:
        label = f"{document['source']} ({document['type']})"
        with st.container(border=True):
            left, middle, right = st.columns([4, 2, 1])
            left.markdown(f"**{label}**")
            left.caption(f"Document ID: {document['doc_id']}")
            middle.metric("Chunks", document.get("chunks", 0))
            middle.caption(f"Pages: {document.get('pages', 0)}")
            uploaded_at = document.get("uploaded_at") or "legacy import"
            right.caption(uploaded_at)
            if right.button("Delete", key=f"delete-{document['doc_id']}", type="secondary"):
                delete_response = api_delete(f"/api/v1/document/{document['doc_id']}")
                if delete_response.ok:
                    st.success("Document deleted.")
                    st.rerun()
                else:
                    st.error(f"Delete failed: {api_error_message(delete_response)}")


def render_usage_dashboard():
    st.subheader("Token Usage")

    try:
        summary_response = api_get("/api/v1/usage/summary")
        records_response = api_get("/api/v1/usage/records?limit=25")
    except requests.RequestException as e:
        st.error(f"Backend connection failed: {e}")
        return

    if not summary_response.ok:
        st.error(f"Error loading usage summary: {api_error_message(summary_response)}")
        return

    summary = summary_response.json()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total tokens", f"{summary.get('total_tokens', 0):,}")
    col2.metric("Actual tokens", f"{summary.get('actual_tokens', 0):,}")
    col3.metric("Estimated tokens", f"{summary.get('estimated_tokens', 0):,}")
    col4.metric("Records", f"{summary.get('records', 0):,}")

    by_operation = summary.get("by_operation", [])
    if by_operation:
        st.caption("By operation")
        st.dataframe(by_operation, hide_index=True, use_container_width=True)

    if records_response.ok:
        records = records_response.json().get("records", [])
        if records:
            st.caption("Recent records")
            st.dataframe(records, hide_index=True, use_container_width=True)

    if st.button("Reset token usage", type="secondary"):
        delete_response = api_delete("/api/v1/usage")
        if delete_response.ok:
            st.success("Token usage cleared.")
            st.rerun()
        else:
            st.error(f"Reset failed: {api_error_message(delete_response)}")


if __name__ == "__main__":
    main()
