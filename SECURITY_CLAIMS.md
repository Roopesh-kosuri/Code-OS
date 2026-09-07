# CODE OS Security Claims & Hardening Verification Matrix

## Security Claims Matrix (v4.5 Hardening Release)

| Claim | Status | Evidence |
|---|---|---|
| Commands require approval | ✅ Server enforced | `backend/app/features/ai/sandbox/policy.py` validates test commands; `run_test` in `chat_harness.py` gates unapproved/dangerous test runners behind approval cards or blocks them. |
| AI commands cannot access backend secrets | ✅ Env sanitization enforced | `backend/app/features/ai/terminal/agentic_terminal_service.py` sanitizes environment variables via `_build_safe_environment()`, stripping API keys, tokens, and credentials. |
| Sandbox cannot be disabled by model | ✅ Server-side policy | `backend/app/features/ai/sandbox/policy.py:should_require_sandbox` enforces server-side policy; model tool arguments cannot override sandbox enforcement. Fail-closed if Docker is missing for dangerous commands. |
| Capture service authenticated | ✅ Session token required | `electron/services/captureService.ts` uses constant-time token comparison (`timingSafeEqual`) on `Authorization: Bearer <token>`, rejecting unauthenticated callers with HTTP 401. |
| Local/private capture targets blocked | ✅ IP validation | `electron/services/captureService.ts` rejects loopback, private RFC-1918, link-local, and cloud metadata IPs (169.254.169.254) as well as non-HTTP schemes (`file://`, `data://`). |
| CORS Restricted on Local Service | ✅ Renderer origin only | `electron/services/captureService.ts` removed wildcard `Access-Control-Allow-Origin: *` and now restricts headers to local renderer origin (`http://127.0.0.1:5176` or `file://`). |
| Trusted-Command Patterns Hardened | ✅ Strict validation | `backend/app/features/ai/harness/approval_coordinator.py` rejects bare `*`, command chaining (`&&`, `\|\|`, `;`, `\|`), and matches by parsed executable. |
| Rate Limiter Enforcement | ✅ Active enforcement | `backend/app/core/rate_limiter.py` provides enforcement mode (`enforce=True`) with configurable budgets per session and day, calculating `retry_after` and throwing `RateLimitExceeded`. |
| Content Security Policy Hardened | ✅ No unsafe-eval | Removed `'unsafe-eval'` from `index.html` and injected strict CSP headers via Electron `session.defaultSession.webRequest.onHeadersReceived` in `electron/main.ts`. |
| SSRF DNS Rebinding Defense | ✅ IP Pinning | `backend/app/features/ai/url_fetcher.py` uses `PinnedTransport` with `httpx` to resolve DNS once, validate against private/link-local ranges, and bind the connection directly to the verified IP. |
| External URL Validation | ✅ Scheme whitelist | `electron/utils/urlValidator.ts` and `electron/main.ts` validate `shell:openExternal` against an explicit whitelist of safe HTTP/HTTPS and mailto schemes, blocking dangerous protocols (`file:`, `javascript:`, etc.). |
| Workspace Path Containment | ✅ `relative_to` containment | `backend/app/features/ai/harness/tool_executor.py` uses `Path.resolve().relative_to(norm_ws.resolve())` to prevent prefix-matching path traversal (`/proj` matching `/proj-evil`). |
| TOCTOU Symlink Mitigation | ✅ Atomic replace & verification | `backend/app/core/paths.py` provides `verify_path_unchanged`, `safe_read_file`, and atomic temp-file replacement in `safe_write_file`. |
| Semantic RAG | ✅ Embedding similarity | `backend/app/features/ai/rag/vector_index_service.py` uses `all-MiniLM-L6-v2` dense vector embeddings and cosine similarity scoring. |
| Smart Router Transparency & Safety | ✅ Catalog validation | `backend/app/features/ai/smart_router/difficulty_classifier.py` documented as experimental heuristic; `model_router.py` validates model tiers against real provider catalog at startup. |
| Continuous Learning / Memory Feedback | ✅ Auto-population & deduplication | `backend/app/features/ai/memory/memory_service.py` automatically synthesizes Always/Never guidelines on failed tests, rejected proposals, and repair blockers with SQLite deduplication. |
| CI Security Scanning | ✅ Automated in CI | `.github/workflows/ci.yml` runs Bandit, pip-audit, and npm audit on every pull request and push to main, saving reports as CI artifacts. |
