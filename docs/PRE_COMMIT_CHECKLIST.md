# Pre-Commit Checklist for v3.1.0

Before committing, verify:

- [ ] All tests passing (547+ backend, 171+ frontend, 0 TS errors)
- [ ] README.md updated with v3.1.0 features
- [ ] CHANGELOG.md updated with v3.1.0 section
- [ ] docs/RELEASE_v3.1.0.md written
- [ ] docs/INSTALLER_BUILD_INSTRUCTIONS.md written
- [ ] No temporary debug logs in production code
- [ ] No uncommitted test files or scratch scripts
- [ ] git status shows only intended changes

Commit message:
```
feat: v3.1.0 — scalability, stability, and engineering quality

Architecture:
- Decompose chat_harness.py into 9 submodules (4,250 → <500 lines)
- Virtual file tree for 50k+ files (<200ms load)
- Event-driven DAG engine with SQLite connection pooling
- Smart context assembly with relevance ranking
- Incremental indexing (mtime-based)

Stability:
- Durable execution with write-ahead logging
- Crash recovery and idempotent operations
- Graceful pause on 429 rate limits
- Orphan process reaping on startup
- 6 chaos tests + 2-hour soak test

AI Providers:
- 14 providers (GLM, Qwen, DeepSeek, xAI, NVIDIA, Cohere, Moonshot)
- 100+ models (GPT-5, Claude 5, Gemini 3.x, Kimi K2)
- Adaptive per-tier routing with fallback

Engineering:
- 5 Architecture Decision Records
- Structured logging with request tracing
- Property-based path containment tests
- Fuzz tests on critical parsers
- Load test: p95 < 100ms, 0% error rate

Security:
- 6 FAANG-audit vulnerabilities closed
- 0 critical CVEs in dependencies
- Code signing plan documented

Fixes:
- Rony Agent tool-execution loop (executes instead of narrates)
- DNS rebinding, duplicate routes, brittle CORS, token expiry

All tests passing. Ready for v3.1.1 installer builds.
```
