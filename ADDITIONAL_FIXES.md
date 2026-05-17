# Additional Fixes — Phase 2

**Date:** 2026-05-17  
**Focus:** `.get() or` pattern, bare exceptions, code verbosity, security holes

---

## Analysis Summary

### `.get() or` Pattern — 28 occurrences found

**Categories:**

1. **✅ SAFE (22 cases)** — Using with string/list defaults where falsy values are invalid:
   - `source.get("doc_id") or ""` — doc_id should never be empty string
   - `usage.get("records") or []` — empty list is correct default
   - `result.get("sources") or []` — empty list is correct default
   - `block.get("text") or block.get("content") or ""` — chaining is intentional

2. **⚠️ POTENTIALLY BUGGY (6 cases)** — Using with numeric defaults:
   - `int(usage.get("input_tokens") or 0)` — **SAFE** because `int()` wraps it
   - `int(usage.get("output_tokens") or 0)` — **SAFE** because `int()` wraps it
   - `sum(int(r.get("total_tokens") or 0) for r in records)` — **SAFE** because `int()` wraps it
   
   **Verdict:** All numeric cases are wrapped in `int()` so they're actually safe.

3. **🔴 NEEDS FIX (0 cases)** — None found that would cause actual bugs.

**Conclusion:** The `.get() or` pattern is used correctly throughout the codebase. No fixes needed.

---

## Bare `except Exception:` — 26 occurrences found

**Analysis:**

All 26 cases follow this pattern:
```python
try:
    # Primary operation (e.g., PostgreSQL)
except Exception:
    logger.exception("Detailed error message")
    # Fallback (e.g., SQLite, in-memory, return default)
```

**Verdict:** ✅ **CORRECT USAGE**
- All exceptions are logged with `logger.exception()` (includes stack trace)
- Used for graceful degradation (PostgreSQL → SQLite, Redis → in-memory)
- Appropriate for infrastructure fallback scenarios

**No fixes needed.**

---

## Security Audit — Additional Checks

### 1. ✅ Password Reset Token (if exists)
**Status:** Not implemented in codebase (no password reset feature yet)

### 2. ✅ Session Fixation
**Status:** SAFE — New JTI generated on each token creation

### 3. ✅ CORS Configuration
**File:** `backend/app/core/config.py`
```python
def get_cors_origins() -> list[str]:
    origins_str = os.environ.get("CORS_ORIGINS", "http://localhost:3000")
    return [origin.strip() for origin in origins_str.split(",")]
```
**Status:** ✅ GOOD — Configurable via environment variable

### 4. ⚠️ Rate Limiting Bypass via Header Injection
**File:** `backend/app/api/v1/auth.py` (line 53-59)
```python
def _real_ip(request: Request) -> str:
    """Extract real IP, honouring X-Real-IP if behind proxy."""
    forwarded = request.headers.get("X-Real-IP")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
```

**Issue:** Trusts `X-Real-IP` header without validation.

**Attack scenario:**
1. Attacker sets `X-Real-IP: 1.2.3.4` in request
2. Rate limiting tracks `1.2.3.4` instead of real IP
3. Attacker can bypass rate limits by changing header

**Recommendation:** Only trust `X-Real-IP` if request comes from trusted proxy IPs.

**Fix:**
```python
TRUSTED_PROXIES = {"127.0.0.1", "::1"}  # Add your reverse proxy IPs

def _real_ip(request: Request) -> str:
    """Extract real IP, honouring X-Real-IP only from trusted proxies."""
    client_ip = request.client.host if request.client else "unknown"
    
    # Only trust X-Real-IP if request comes from trusted proxy
    if client_ip in TRUSTED_PROXIES:
        forwarded = request.headers.get("X-Real-IP")
        if forwarded:
            return forwarded.split(",")[0].strip()
    
    return client_ip
```

**Severity:** 🟡 MEDIUM (only exploitable if attacker can set headers, which depends on deployment)

### 5. ✅ SQL Injection in Dynamic Queries
**Status:** SAFE — All queries use parameterized statements

### 6. ✅ Path Traversal in Document Upload
**File:** `backend/app/api/v1/document.py`
**Status:** ✅ GOOD — Uses `secure_filename()` and validates file extensions

### 7. ⚠️ Timing Attack on Token Comparison
**File:** `backend/app/core/auth.py` (line 40-44)
```python
def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password using bcrypt (constant-time comparison)."""
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
```

**Status:** ✅ GOOD — bcrypt.checkpw() uses constant-time comparison

**JWT token comparison:**
```python
payload = jwt.decode(token, _get_jwt_secret(), algorithms=["HS256"])
```
**Status:** ✅ GOOD — PyJWT uses constant-time comparison for signatures

### 8. ⚠️ Missing Rate Limiting on Expensive Operations
**Files checked:**
- `/v1/chat/message` — ✅ HAS rate limiting
- `/v1/auth/login` — ✅ HAS rate limiting
- `/v1/document/upload` — ❌ NO rate limiting (admin-only, acceptable)
- `/v1/document/rebuild-vector-store` — ❌ NO rate limiting (admin-only, acceptable)

**Verdict:** Acceptable — expensive operations are admin-only

### 9. ✅ Insecure Deserialization
**Status:** SAFE — No pickle/eval/exec usage, only JSON

### 10. ⚠️ Missing Input Length Limits
**File:** `backend/app/api/v1/chat.py`
```python
class ChatRequest(BaseModel):
    question: str  # No max length!
    mode: Literal["Internal", "External"] = "Internal"
    history: list[HistoryMessage] = []  # No max items!
```

**Issue:** User can send extremely long questions or history, causing:
- High memory usage
- Expensive LLM calls
- Potential DoS

**Recommendation:** Add limits:
```python
class ChatRequest(BaseModel):
    question: str = Field(..., max_length=10000)  # 10K chars
    mode: Literal["Internal", "External"] = "Internal"
    history: list[HistoryMessage] = Field(default=[], max_length=50)  # 50 messages
```

**Severity:** 🟡 MEDIUM (can cause resource exhaustion)

---

## Code Verbosity Issues

### 1. Repetitive Error Handling in Stores (Frontend)

**File:** `frontend/src/stores/modelConfigStore.ts`

**Current (repetitive):**
```typescript
fetchModels: async () => {
    set({ loading: true, error: null });
    try {
        const response = await apiClient.get('/v1/users/me/models');
        set({ models: response.data.models, routing: response.data.routing, loading: false });
    } catch (error: any) {
        set({ error: error.response?.data?.detail || 'Failed to fetch models', loading: false });
    }
},

createModel: async (data) => {
    set({ loading: true, error: null });
    try {
        await apiClient.post('/v1/users/me/models', data);
        set({ loading: false });
    } catch (error: any) {
        set({ error: error.response?.data?.detail || 'Failed to create model', loading: false });
        throw error;
    }
},
```

**Better (DRY):**
```typescript
const withErrorHandling = async <T>(
    operation: () => Promise<T>,
    errorMessage: string
): Promise<T> => {
    set({ loading: true, error: null });
    try {
        const result = await operation();
        set({ loading: false });
        return result;
    } catch (error: any) {
        const message = error.response?.data?.detail || errorMessage;
        set({ error: message, loading: false });
        throw error;
    }
};

// Usage:
fetchModels: async () => {
    const response = await withErrorHandling(
        () => apiClient.get('/v1/users/me/models'),
        'Failed to fetch models'
    );
    set({ models: response.data.models, routing: response.data.routing });
},
```

**Severity:** 🟢 LOW (code quality, not a bug)

### 2. Duplicate Token Usage Aggregation Logic

**File:** `backend/app/services/rag/query_engine.py`

**Lines 893-895, 1048, 1067, 1093, 1110:**
```python
"total_tokens": sum(int(r.get("total_tokens") or 0) for r in usage_records)
```

**Repeated 5 times!**

**Better:**
```python
def _sum_tokens(records: list[dict], key: str = "total_tokens") -> int:
    """Sum token counts from usage records."""
    return sum(int(r.get(key) or 0) for r in records)

# Usage:
"total_tokens": _sum_tokens(usage_records)
"input_tokens": _sum_tokens(usage_records, "input_tokens")
"output_tokens": _sum_tokens(usage_records, "output_tokens")
```

**Severity:** 🟢 LOW (code quality, not a bug)

---

## Recommendations Priority

### 🔴 HIGH PRIORITY
1. **Add input length limits** to ChatRequest (DoS prevention)
2. **Fix X-Real-IP trust** in rate limiting (security)

### 🟡 MEDIUM PRIORITY
3. Refactor frontend error handling (DRY principle)
4. Extract token aggregation helper (DRY principle)

### 🟢 LOW PRIORITY
5. Document why `.get() or` is safe in this codebase
6. Add type hints to helper functions

---

## Conclusion

**Overall:** The codebase is well-written with minimal security issues.

**Critical findings:** 2 medium-severity issues
1. Rate limiting bypass via X-Real-IP header injection
2. Missing input length limits on chat requests

**Code quality:** Good, with some opportunities for DRY refactoring.

**Next steps:**
1. Fix the 2 medium-severity security issues
2. Optionally refactor verbose code
3. Add integration tests for rate limiting edge cases
