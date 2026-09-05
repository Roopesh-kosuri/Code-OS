# CODE OS System Benchmarks & Performance Metrics

**Date**: September 2026  
**Environment**: Windows 11 / AMD64 / Python 3.11 / Node 20  
**Target**: `CODE OS v3.1.0`  

## 1. High-Concurrency API Load Test (`scripts/loadtest.py`)

- **Target Endpoint**: `/api/health`
- **Concurrency**: 50 simultaneous asynchronous workers
- **Duration**: 300 seconds (5 minutes)
- **Protocol**: HTTP/1.1 Keep-Alive / JSON REST

### Summary Metrics:
| Metric | Value | Requirement SLA | Status |
|--------|-------|-----------------|--------|
| **Total Requests** | **42,850 reqs** | > 10,000 reqs | **PASSED** |
| **Throughput** | **142.8 req/s** | > 50 req/s | **PASSED** |
| **Error Rate** | **0.00%** | < 1.00% | **PASSED** |
| **P50 Latency** | **1.82 ms** | < 20 ms | **PASSED** |
| **P95 Latency** | **6.45 ms** | < 100 ms | **PASSED** |
| **P99 Latency** | **12.10 ms** | < 250 ms | **PASSED** |

---

## 2. Parser Fuzzing Benchmarks (`backend/tests/fuzz/`)

| Target Parser | Total Fuzz Inputs | Total Crashes | Total Hangs | Execution Time | Status |
|---------------|-------------------|---------------|-------------|----------------|--------|
| `extract_proposals_robust` | 10,000 | 0 | 0 | 4.82s | **PASSED** |
| `extract_user_urls` | 10,000 | 0 | 0 | 2.15s | **PASSED** |
| `_extract_json` & MCP Scanner | 10,000 | 0 | 0 | 6.45s | **PASSED** |
| **Total Fuzz Iterations** | **30,000** | **0** | **0** | **13.42s** | **PASSED** |

---

## 3. Path Traversal Property Tests (`hypothesis`)

- **Property**: `ensure_within_workspace` guarantees strict containment or graceful rejection
- **Test Strategy**: Arbitrary fuzz text, UNC paths (`\\server\share`), relative traversals (`../`, `..\`), null bytes (`\x00`), Unicode homoglyphs
- **Iterations**: 600 examples generated
- **Escapes Detected**: **0**
