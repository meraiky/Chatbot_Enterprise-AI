# Web Search Setup and External Data Strategy

## What similar chatbot/RAG projects usually do

Most production-style chatbot/RAG systems that answer from external web data do not let the LLM browse randomly by itself. They usually use a controlled retrieval layer:

1. Search provider API first: Google Custom Search, Bing Search, Tavily, SerpAPI, Brave Search, or similar.
2. Fetch only search snippets or selected pages.
3. Keep external results separate from internal document indexes.
4. Synthesize the answer with citations.
5. Cache external search results with a TTL.
6. Clearly mark whether an answer came from internal documents, external web, or a hybrid combination.

This matches the current project strategy: internal RAG first, then ask the user before external search, then answer with external source attribution.

## Recommended architecture for this project

The chatbot should use this order:

1. Internal documents via RAG.
2. If internal context is missing, show a web-search offer to the user.
3. If user accepts, search external providers.
4. Use provider priority:
   - Google Custom Search if `GOOGLE_SEARCH_API_KEY` and `GOOGLE_SEARCH_CX` are configured.
   - Bing Search if `BING_SEARCH_API_KEY` is configured.
   - DuckDuckGo fallback because it is free but less reliable.
5. Save web search results only in `external_search_cache`, not in the internal vector store.
6. Return answer metadata with `source_type = external_web` and a list of external source URLs.

## Why DuckDuckGo failed

The current DuckDuckGo provider uses the free instant-answer endpoint. That endpoint is useful for facts with known instant answers, but it is not a general search engine API. Queries such as Vietnamese business questions may return no useful results even though a normal browser search works.

Google Custom Search is more reliable for general web queries because it returns standard ranked web results.

## Google Custom Search setup

### Step 1: Create an API key

1. Open Google Cloud Console.
2. Create or select a project.
3. Enable `Custom Search API`.
4. Create an API key.
5. Copy the API key into the backend `.env` file:

```env
GOOGLE_SEARCH_API_KEY=your_google_api_key_here
```

### Step 2: Create a Programmable Search Engine

1. Open Google Programmable Search Engine.
2. Create a new search engine.
3. Configure it to search the entire web, not only one site.
4. Copy the Search Engine ID, also called `cx`.
5. Add it to the backend `.env` file:

```env
GOOGLE_SEARCH_CX=your_google_cx_id_here
```

### Step 3: Restart backend

Restart the backend server so `pydantic-settings` reloads the environment variables.

Expected startup/search logs should include:

```text
Web search: Google Custom Search enabled (primary provider)
Web search: DuckDuckGo enabled (fallback provider)
```

## Current implementation files

- Backend settings: `backend/app/core/config.py`
- Search provider priority: `backend/app/services/web_search_service.py`
- Environment example: `backend/.env.example`
- Hybrid RAG flow: `backend/app/services/rag/query_engine.py`
- Web-search preferences API: `backend/app/api/v1/users.py`
- Chat streaming endpoint: `backend/app/api/v1/chat.py`

## Operational rules

1. Do not store web search data in Chroma/internal vector store.
2. Do not label external answers as internal answers.
3. Do not auto-search web unless the user has enabled the preference.
4. Always include external source URLs when the answer uses web data.
5. Treat web data as lower-trust than curated internal documents.
6. Keep cache TTL short enough for freshness, usually 1 to 7 days depending on the use case.

## Recommended next improvements

1. Add a provider health endpoint to show whether Google/Bing/DuckDuckGo are configured and working.
2. Add query rewriting before web search for Vietnamese queries, for example converting `Business analyst là sao` into `Business analyst là gì vai trò kỹ năng responsibilities`.
3. Add source-quality filtering to prefer official docs, reputable articles, and recent pages.
4. Add per-provider latency and failure logging.
5. Add a UI badge that says `Nguồn: Internet` and lists each external source.
