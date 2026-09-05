# ADR-004: Virtual File Tree

## Status
Accepted | Date: 2026-09-01

## Context
In large enterprise workspaces (>50,000 files, deep `node_modules`, build artifacts), fetching the entire workspace file tree recursively generated multi-megabyte JSON payloads. This caused backend CPU spikes during JSON serialization and froze the frontend React UI for several seconds upon initial workspace load.

## Decision
Replace full-tree recursive generation with a depth-1 virtualized tree API:
1. `GET /api/files/tree?path={dir}&depth=1`: Returns only immediate child directories and files for the requested folder.
2. In-memory LRU cache (`_tree_cache`) holding up to 10,000 directory listings with automatic invalidation on file modification events.
3. Frontend directory expand/collapse loads child nodes on-demand with lazy caching in `useFileStore`.

## Consequences
### Positive
- Initial tree payload size reduced from >5MB to <12KB.
- Initial file tree load time dropped from ~5,000ms to 5.9ms.
- Scalable to repositories with hundreds of thousands of files without UI lag.

### Negative
- Expanding deeply nested directories requires an additional lightweight HTTP request if not already cached.

### Metrics
- Initial Tree Load Time: ~5,000ms -> 5.9ms (>99% latency reduction).
- Payload payload size: 5.2MB -> 11.4KB (99.7% payload reduction).
