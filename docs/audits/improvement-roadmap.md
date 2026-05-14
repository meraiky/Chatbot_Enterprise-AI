# AIAgentChatbot - Improvement Roadmap
**Created**: 2026-05-09  
**Current Score**: 9.0/10  
**Target Score**: 9.5/10  
**Timeline**: 2-3 sprints (4-6 weeks)

---

## Sprint 1: Infrastructure & Stability (Week 1-2)

### 1.1 Setup Redis Cache ⚡ [HIGH PRIORITY]
**Current**: Redis unavailable, fallback to PostgreSQL  
**Target**: Redis L1 cache operational  
**Impact**: Giảm latency cache hit từ ~0.5s → <0.01s

**Implementation**:
```bash
# Option 1: Railway Redis (Recommended)
# 1. Add Redis service in Railway dashboard
# 2. Copy REDIS_URL from Railway
# 3. Update backend/.env:
REDIS_URL=redis://default:password@redis.railway.internal:6379

# Option 2: Upstash Redis (Free tier)
# 1. Sign up at https://upstash.com
# 2. Create Redis database
# 3. Copy connection string
REDIS_URL=rediss://default:password@host.upstash.io:6379
```

**Verification**:
```python
# backend/scripts/test_redis.py
import redis
from app.core.config import settings

r = redis.from_url(settings.REDIS_URL)
r.set("test", "ok")
assert r.get("test") == b"ok"
print("✅ Redis connected")
```

**Files to modify**:
- `backend/.env` - Add REDIS_URL
- `backend/app/services/rag/cache_service.py` - Already has Redis fallback logic

**Estimated effort**: 2 hours

---

### 1.2 Verify Chroma/Neon Consistency 🔍 [HIGH PRIORITY]
**Current**: Consistency not checked in current session  
**Target**: Automated consistency check + alert

**Implementation**:
```bash
# Run consistency check
cd Projects/apps/AIAgentChatbot/backend
python scripts/consistency_check.py

# Expected output:
# ✅ Chroma: 90 chunks
# ✅ Neon: 90 chunks
# ✅ No inconsistencies found
```

**Add to CI/CD**:
```yaml
# .github/workflows/consistency-check.yml
name: Consistency Check
on:
  schedule:
    - cron: '0 0 * * *'  # Daily at midnight
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Run consistency check
        run: |
          cd backend
          python scripts/consistency_check.py
          if [ $? -ne 0 ]; then
            echo "❌ Consistency check failed"
            exit 1
          fi
```

**Files to create**:
- `.github/workflows/consistency-check.yml`
- `backend/scripts/consistency_check.py` (already exists, verify it works)

**Estimated effort**: 3 hours

---

### 1.3 Monitoring & Alerting 📊 [HIGH PRIORITY]
**Current**: Logs only, no alerting  
**Target**: Real-time error tracking + performance monitoring

**Implementation**:

**Option A: Sentry (Recommended)**
```bash
# Install
pip install sentry-sdk[fastapi]

# backend/main.py
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration

sentry_sdk.init(
    dsn=settings.SENTRY_DSN,
    integrations=[FastApiIntegration()],
    traces_sample_rate=0.1,
    profiles_sample_rate=0.1,
)
```

**Option B: Railway Metrics (Built-in)**
```bash
# Railway dashboard automatically tracks:
# - CPU usage
# - Memory usage
# - Request rate
# - Error rate
# - Response time

# Add custom metrics:
# backend/app/core/observability.py
from prometheus_client import Counter, Histogram

chat_requests = Counter('chat_requests_total', 'Total chat requests')
chat_latency = Histogram('chat_latency_seconds', 'Chat request latency')
```

**Files to modify**:
- `backend/requirements.txt` - Add `sentry-sdk[fastapi]`
- `backend/main.py` - Add Sentry init
- `backend/.env` - Add `SENTRY_DSN`
- `backend/app/core/observability.py` - Add custom metrics

**Estimated effort**: 4 hours

---

## Sprint 2: Quality & Security (Week 3-4)

### 2.1 Vietnamese BM25 Tokenizer 🇻🇳 [MEDIUM PRIORITY]
**Current**: Regex tokenization (không tốt cho từ ghép tiếng Việt)  
**Target**: Vietnamese-aware tokenization với `underthesea`

**Implementation**:
```bash
# Install
pip install underthesea

# backend/app/services/rag/bm25_search.py
from underthesea import word_tokenize

class BM25Search:
    def _tokenize(self, text: str) -> list[str]:
        """Vietnamese-aware tokenization."""
        # Old: return re.findall(r'\w+', text.lower())
        # New:
        tokens = word_tokenize(text.lower())
        return [t for t in tokens if len(t) > 1]  # Filter single chars
```

**Test cases**:
```python
# backend/tests/unit/test_bm25_vietnamese.py
def test_vietnamese_compound_words():
    tokenizer = BM25Search()
    
    # Test compound words
    text = "phần mềm quản lý nhân sự"
    tokens = tokenizer._tokenize(text)
    assert "phần_mềm" in tokens  # Should keep compound
    assert "quản_lý" in tokens
    assert "nhân_sự" in tokens
    
    # Test vs old regex
    old_tokens = re.findall(r'\w+', text.lower())
    assert len(tokens) < len(old_tokens)  # Fewer but better tokens
```

**Files to modify**:
- `backend/requirements.txt` - Add `underthesea`
- `backend/app/services/rag/bm25_search.py` - Update `_tokenize()`
- `backend/tests/unit/test_bm25_vietnamese.py` - Add tests

**Estimated effort**: 6 hours

---

### 2.2 Document ACL (Access Control List) 🔒 [HIGH PRIORITY]
**Current**: Chỉ có Internal/External mode  
**Target**: Document-level permissions per user/role

**Implementation**:

**Step 1: Database schema**
```sql
-- backend/migrations/versions/008_document_acl.py
CREATE TABLE document_acl (
    id SERIAL PRIMARY KEY,
    doc_id TEXT NOT NULL,
    min_role TEXT NOT NULL DEFAULT 'user',  -- user, admin
    allowed_user_ids TEXT[],  -- NULL = all users with min_role
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_document_acl_doc_id ON document_acl(doc_id);
```

**Step 2: Service layer**
```python
# backend/app/services/document_acl_service.py
from app.core.database import get_conn

class DocumentACLService:
    @staticmethod
    def can_access(doc_id: str, user_role: str, user_id: int) -> bool:
        """Check if user can access document."""
        sql = """
            SELECT min_role, allowed_user_ids
            FROM document_acl
            WHERE doc_id = %s
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (doc_id,))
                row = cur.fetchone()
                
                if not row:
                    # No ACL = public access
                    return True
                
                min_role, allowed_users = row
                
                # Check role
                if user_role == 'admin':
                    return True
                if min_role == 'admin' and user_role != 'admin':
                    return False
                
                # Check user whitelist
                if allowed_users and user_id not in allowed_users:
                    return False
                
                return True
```

**Step 3: Apply to retrieval**
```python
# backend/app/services/rag/query_engine.py
def answer_query_stream(self, question: str, mode: str, user_role: str, user_id: int):
    # ... existing code ...
    
    # Filter retrieved docs by ACL
    accessible_docs = []
    for doc in retrieved_docs:
        if DocumentACLService.can_access(doc.metadata['doc_id'], user_role, user_id):
            accessible_docs.append(doc)
    
    # Continue with accessible_docs only
```

**Step 4: Admin UI**
```typescript
// frontend/src/pages/AdminPage.tsx
const DocumentACLManager = () => {
  const [docId, setDocId] = useState('');
  const [minRole, setMinRole] = useState('user');
  const [allowedUsers, setAllowedUsers] = useState<number[]>([]);
  
  const saveACL = async () => {
    await apiClient.post('/api/v1/admin/document-acl', {
      doc_id: docId,
      min_role: minRole,
      allowed_user_ids: allowedUsers,
    });
  };
  
  return (
    <div>
      <h3>Document Access Control</h3>
      <select value={docId} onChange={e => setDocId(e.target.value)}>
        {documents.map(d => <option key={d.id} value={d.id}>{d.filename}</option>)}
      </select>
      <select value={minRole} onChange={e => setMinRole(e.target.value)}>
        <option value="user">User</option>
        <option value="admin">Admin Only</option>
      </select>
      <button onClick={saveACL}>Save ACL</button>
    </div>
  );
};
```

**Files to create/modify**:
- `backend/migrations/versions/008_document_acl.py`
- `backend/app/services/document_acl_service.py`
- `backend/app/api/v1/admin.py` - Add ACL endpoints
- `backend/app/services/rag/query_engine.py` - Filter by ACL
- `frontend/src/pages/AdminPage.tsx` - Add ACL UI

**Estimated effort**: 12 hours

---

### 2.3 Retrieval Evaluation Suite 📈 [MEDIUM PRIORITY]
**Current**: Không có metrics đo chất lượng retrieval  
**Target**: Golden dataset + automated eval (recall@k, MRR)

**Implementation**:

**Step 1: Create golden dataset**
```json
// backend/data/eval/golden_qa.json
[
  {
    "question": "Scrum có mấy vai trò chính?",
    "expected_doc_ids": ["internal-vi_scrumprimer20.pdf-d7c2abe383bb"],
    "expected_answer_contains": ["Product Owner", "Scrum Master", "Development Team"],
    "mode": "Internal"
  },
  {
    "question": "Sprint Planning kéo dài bao lâu?",
    "expected_doc_ids": ["internal-vi_scrumprimer20.pdf-d7c2abe383bb"],
    "expected_answer_contains": ["8 giờ", "1 tháng"],
    "mode": "Internal"
  }
]
```

**Step 2: Evaluation script**
```python
# backend/scripts/eval_retrieval.py
import json
from app.services.rag.query_engine import QueryEngine

def calculate_recall_at_k(retrieved_docs, expected_doc_ids, k=3):
    """Recall@k: % expected docs in top-k results."""
    top_k_ids = [d.metadata['doc_id'] for d in retrieved_docs[:k]]
    hits = sum(1 for exp_id in expected_doc_ids if exp_id in top_k_ids)
    return hits / len(expected_doc_ids) if expected_doc_ids else 0

def calculate_mrr(retrieved_docs, expected_doc_ids):
    """Mean Reciprocal Rank: 1/rank of first relevant doc."""
    for i, doc in enumerate(retrieved_docs, 1):
        if doc.metadata['doc_id'] in expected_doc_ids:
            return 1.0 / i
    return 0.0

def run_eval():
    with open('data/eval/golden_qa.json') as f:
        test_cases = json.load(f)
    
    engine = QueryEngine()
    results = {
        'recall@3': [],
        'recall@5': [],
        'mrr': [],
    }
    
    for case in test_cases:
        retrieved = engine._retrieve_candidates(
            case['question'],
            case['mode']
        )
        
        results['recall@3'].append(
            calculate_recall_at_k(retrieved, case['expected_doc_ids'], k=3)
        )
        results['recall@5'].append(
            calculate_recall_at_k(retrieved, case['expected_doc_ids'], k=5)
        )
        results['mrr'].append(
            calculate_mrr(retrieved, case['expected_doc_ids'])
        )
    
    print(f"Recall@3: {sum(results['recall@3']) / len(results['recall@3']):.2%}")
    print(f"Recall@5: {sum(results['recall@5']) / len(results['recall@5']):.2%}")
    print(f"MRR: {sum(results['mrr']) / len(results['mrr']):.3f}")

if __name__ == '__main__':
    run_eval()
```

**Step 3: Add to CI/CD**
```yaml
# .github/workflows/eval.yml
name: Retrieval Evaluation
on:
  pull_request:
    paths:
      - 'backend/app/services/rag/**'
jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Run evaluation
        run: |
          cd backend
          python scripts/eval_retrieval.py
          # Fail if recall@3 < 80%
```

**Files to create**:
- `backend/data/eval/golden_qa.json` - Test cases
- `backend/scripts/eval_retrieval.py` - Evaluation script
- `.github/workflows/eval.yml` - CI integration

**Estimated effort**: 10 hours (including creating 20+ test cases)

---

## Sprint 3: Scale & Polish (Week 5-6)

### 3.1 Migrate to Shared Vector Store 🗄️ [MEDIUM PRIORITY]
**Current**: Local Chroma (không scale multi-replica)  
**Target**: PostgreSQL pgvector hoặc managed vector DB

**Option A: PostgreSQL pgvector (Recommended)**
```sql
-- Already have pgvector extension in Neon
-- Just need to migrate Chroma data

CREATE TABLE document_vectors (
    id SERIAL PRIMARY KEY,
    doc_id TEXT NOT NULL,
    chunk_index INT NOT NULL,
    content TEXT NOT NULL,
    embedding vector(3072),  -- Gemini embedding dimension
    metadata JSONB,
    mode TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_document_vectors_embedding 
ON document_vectors 
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
```

**Migration script**:
```python
# backend/scripts/migrate_chroma_to_pgvector.py
from app.services.rag.vector_store import get_vector_store
from app.core.database import get_conn

def migrate():
    chroma = get_vector_store()
    all_docs = chroma.get()
    
    with get_conn() as conn:
        with conn.cursor() as cur:
            for i, doc in enumerate(all_docs['documents']):
                cur.execute("""
                    INSERT INTO document_vectors 
                    (doc_id, chunk_index, content, embedding, metadata, mode)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    all_docs['metadatas'][i]['doc_id'],
                    i,
                    doc,
                    all_docs['embeddings'][i],
                    json.dumps(all_docs['metadatas'][i]),
                    all_docs['metadatas'][i]['mode']
                ))
        conn.commit()
    
    print(f"✅ Migrated {len(all_docs['documents'])} chunks to pgvector")
```

**Update vector_store.py**:
```python
# backend/app/services/rag/vector_store.py
class PgVectorStore:
    def similarity_search(self, query_embedding, mode: str, k: int = 5):
        sql = """
            SELECT content, metadata, 
                   1 - (embedding <=> %s::vector) AS similarity
            FROM document_vectors
            WHERE mode = %s
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (query_embedding, mode, query_embedding, k))
                return cur.fetchall()
```

**Files to create/modify**:
- `backend/migrations/versions/009_pgvector_store.py`
- `backend/scripts/migrate_chroma_to_pgvector.py`
- `backend/app/services/rag/vector_store.py` - Add PgVectorStore class
- `backend/app/core/config.py` - Add `USE_PGVECTOR` flag

**Estimated effort**: 16 hours

---

### 3.2 Load Testing & Optimization 🚀 [MEDIUM PRIORITY]
**Current**: Chưa test với concurrent users  
**Target**: Handle 100 concurrent users với <5s latency

**Implementation**:
```python
# backend/tests/load/locustfile.py
from locust import HttpUser, task, between

class ChatbotUser(HttpUser):
    wait_time = between(1, 3)
    
    def on_start(self):
        # Login
        response = self.client.post("/api/v1/auth/login", data={
            "username": "testuser",
            "password": "testpass"
        })
        self.token = response.json()["access_token"]
    
    @task(3)
    def chat(self):
        self.client.post(
            "/api/v1/chat/message/stream",
            json={
                "question": "Scrum là gì?",
                "mode": "Internal",
                "conversation_id": None
            },
            headers={"Authorization": f"Bearer {self.token}"}
        )
    
    @task(1)
    def list_documents(self):
        self.client.get(
            "/api/v1/document",
            headers={"Authorization": f"Bearer {self.token}"}
        )
```

**Run load test**:
```bash
# Install
pip install locust

# Run test
cd backend/tests/load
locust -f locustfile.py --host http://localhost:8000

# Open http://localhost:8089
# Set: 100 users, spawn rate 10/s
# Run for 5 minutes
```

**Optimization targets**:
- P50 latency: <3s
- P95 latency: <5s
- P99 latency: <8s
- Error rate: <1%
- Throughput: >20 req/s

**Files to create**:
- `backend/tests/load/locustfile.py`
- `backend/tests/load/README.md` - Load test guide

**Estimated effort**: 8 hours

---

### 3.3 Frontend Polish 💅 [LOW PRIORITY]
**Current**: Basic UI, functional  
**Target**: Better UX, session management, error handling

**Improvements**:

**A. Session Summary UI**
```typescript
// frontend/src/components/SessionSummary.tsx
const SessionSummary = ({ conversationId }: { conversationId: string }) => {
  const [summary, setSummary] = useState<any>(null);
  
  useEffect(() => {
    apiClient.get(`/api/v1/usage/conversations/${conversationId}/cost`)
      .then(res => setSummary(res.data));
  }, [conversationId]);
  
  if (!summary) return null;
  
  return (
    <div className="session-summary">
      <h4>Session Summary</h4>
      <p>Messages: {summary.message_count}</p>
      <p>Tokens: {summary.total_tokens.toLocaleString()}</p>
      <p>Cost: ${summary.estimated_cost_usd.toFixed(4)}</p>
      <p>Duration: {summary.duration_minutes}m</p>
    </div>
  );
};
```

**B. Better error handling**
```typescript
// frontend/src/pages/ChatPage.tsx
const handleError = (error: any) => {
  const message = getApiErrorMessage(error, 'An error occurred');
  
  // Show user-friendly message
  if (message.includes('topic guard')) {
    toast.error('This topic is restricted. Please ask something else.');
  } else if (message.includes('rate limit')) {
    toast.error('Too many requests. Please wait a moment.');
  } else if (message.includes('401')) {
    toast.error('Session expired. Please login again.');
    // Redirect to login
  } else {
    toast.error(message);
  }
};
```

**C. Conversation history sidebar**
```typescript
// frontend/src/components/ConversationHistory.tsx
const ConversationHistory = () => {
  const [conversations, setConversations] = useState<any[]>([]);
  
  useEffect(() => {
    apiClient.get('/api/v1/usage/conversations')
      .then(res => setConversations(res.data));
  }, []);
  
  return (
    <aside className="conversation-history">
      <h3>Recent Conversations</h3>
      {conversations.map(conv => (
        <div key={conv.id} onClick={() => loadConversation(conv.id)}>
          <p>{conv.first_message}</p>
          <small>{conv.created_at}</small>
        </div>
      ))}
    </aside>
  );
};
```

**Files to create/modify**:
- `frontend/src/components/SessionSummary.tsx`
- `frontend/src/components/ConversationHistory.tsx`
- `frontend/src/pages/ChatPage.tsx` - Better error handling
- `frontend/src/index.css` - Polish styles

**Estimated effort**: 12 hours

---

## Summary: Effort Estimation

| Sprint | Tasks | Total Hours | Priority |
|--------|-------|-------------|----------|
| **Sprint 1** | Redis + Consistency + Monitoring | 9h | 🔴 HIGH |
| **Sprint 2** | Vietnamese BM25 + ACL + Eval | 28h | 🟡 MEDIUM |
| **Sprint 3** | pgvector + Load Test + Polish | 36h | 🟢 LOW |
| **Total** | 11 tasks | **73 hours** (~2 weeks full-time) |

---

## Expected Score Improvement

| Metric | Before | After Sprint 1 | After Sprint 2 | After Sprint 3 |
|--------|--------|----------------|----------------|----------------|
| **RAG Retrieval** | 8.7 | 8.7 | 9.2 ✅ | 9.2 |
| **Token Optimization** | 9.0 | 9.2 ✅ | 9.2 | 9.2 |
| **Storage/Deployment** | 8.5 | 8.5 | 8.5 | 9.0 ✅ |
| **Auditability** | 9.1 | 9.3 ✅ | 9.3 | 9.3 |
| **UX/Admin** | 8.8 | 8.8 | 9.0 ✅ | 9.3 ✅ |
| **Safety** | 8.4 | 8.4 | 9.0 ✅ | 9.0 |
| **Test Coverage** | 7.8 | 8.0 ✅ | 8.5 ✅ | 8.5 |
| **Operational** | 8.2 | 9.0 ✅ | 9.0 | 9.2 ✅ |
| **Overall** | **9.0** | **9.1** | **9.3** | **9.5** ✅ |

---

## Quick Wins (Can Do Today)

### 1. Setup Redis (2 hours)
```bash
# Railway: Add Redis service
# Update .env with REDIS_URL
# Restart backend
# Verify: curl http://localhost:8000/api/v1/admin/health/retrieval
```

### 2. Run Consistency Check (30 minutes)
```bash
cd Projects/apps/AIAgentChatbot/backend
python scripts/consistency_check.py
```

### 3. Add Sentry (1 hour)
```bash
pip install sentry-sdk[fastapi]
# Add to main.py
# Deploy
```

**Total quick wins**: 3.5 hours → Score 9.0 → 9.1 ✅

---

## Long-term Vision (Beyond 9.5)

### Phase 4: Enterprise Features (9.5 → 10.0)
- Multi-tenancy (workspace isolation)
- SSO integration (SAML, OAuth)
- Advanced analytics dashboard
- Custom model fine-tuning
- API rate limiting per user
- Webhook notifications
- Export to Word/PDF
- Mobile app (React Native)

### Phase 5: AI Platform (10.0+)
- MCP server for Claude Desktop
- Skill marketplace (reusable workflows)
- Wiki-lite knowledge layer (Arkon-style)
- Multi-agent orchestration
- Voice interface
- Real-time collaboration
- Plugin system

---

**Next Steps**: Start with Sprint 1 quick wins (Redis + Consistency + Sentry) to reach 9.1/10 trong 1 ngày.
