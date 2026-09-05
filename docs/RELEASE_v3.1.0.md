# CODE OS v3.1.0 Release Notes

## Overview
v3.1.0 is a major architectural and stability release that makes
CODE OS production-ready for large codebases, long-running tasks,
and enterprise environments.

## Key Improvements

### 1. Scalability for Large Codebases
- **Virtual file tree**: 50k+ file workspaces load in <200ms 
  (was ~5 seconds)
- **Event-driven DAG**: Replaces polling with asyncio.Event, 
  reducing disk I/O by 95%
- **SQLite connection pool**: 4 read + 1 write connections with 
  WAL mode, p95 latency <5ms

### 2. Long-Task Stability
- **Durable execution**: Tasks survive backend crashes via 
  write-ahead logging
- **Idempotent operations**: Hash-based dedup prevents double-apply
- **Graceful pause**: 429 rate limits → "paused" status (not failed)
- **Chaos tested**: 6 adversarial failure tests + 2-hour soak test

### 3. AI Provider Matrix
- **14 providers** including GLM, Qwen, DeepSeek, xAI, NVIDIA, 
  Cohere, Moonshot AI
- **100+ models** including GPT-5, Claude 5, Gemini 3.x, Kimi K2
- **Adaptive per-tier routing**: low/medium/high/premium with 
  automatic fallback

### 4. Rony Agent Improvements
- **Tool execution fixed**: Agent now executes tool calls instead 
  of narrating them
- **Multi-format parser**: Supports OpenAI Harmony, nested JSON, 
  plain-text descriptions
- **Self-repair retry**: Described tool calls trigger nudge, then 
  execute
- **Zero "continue" prompts**: Tasks complete autonomously

### 5. Engineering Quality
- **5 Architecture Decision Records** documenting key choices
- **Property-based tests** (hypothesis) for path containment
- **Fuzz tests** on critical parsers (30,000 inputs, zero crashes)
- **Load test**: p95 < 100ms, 0% error rate under 50 concurrent 
  clients

### 6. Security Hardening
- **0 critical CVEs** in dependencies
- **6 FAANG-audit vulnerabilities** closed
- **Code signing plan** documented for Windows/macOS/Linux
- **Threat model** updated with Phase 2-3 mitigations

## Upgrade Instructions

1. Download v3.1.1 installers from GitHub Releases
2. Uninstall v3.0.0 (broken installer)
3. Install v3.1.1
4. Verify: open a 50k+ file workspace, confirm <200ms load time
5. Test: send "create a Python project with tests" and verify 
   autonomous completion

## Breaking Changes
None. v3.1.0 is fully backward compatible with v2.4.0 and v3.0.0 
workspaces.

## Known Issues
None at release time.

## Next Steps
- v3.2.0: Test Impact Analysis + Cost Dashboard
- v4.0.0: Spec-driven mode + session replay
