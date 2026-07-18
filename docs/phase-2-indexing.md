# Phase 2 Repository Indexing

## Architecture

The repository indexer is a backend subsystem under `backend/app/features/indexing`.

- `service.py` schedules and runs background indexing jobs.
- `language.py` maps supported file extensions to languages.
- `parsers.py` extracts symbols, imports, and dependencies with lightweight language-aware parsers.
- `routes.py` exposes status, manual run, and summary APIs.
- SQLite stores index status, indexed files, symbols, import edges, dependencies, and folder hierarchy.

Workspace open triggers indexing automatically through `workspaces/service.py`. The filesystem watcher schedules follow-up indexing when source files change.

## Supported Languages

- Python
- C
- C++
- Java
- JavaScript
- TypeScript

## Stored Data

- Project type and frameworks
- Language file counts
- Entry points
- File metadata and content hashes
- Symbol database
- Import graph
- Dependency graph
- Folder hierarchy

## Incremental Strategy

The scanner walks workspace metadata in the background. Files whose `mtime_ns` and size are unchanged are not hashed or parsed. Changed files are parsed and upserted; removed files are deleted from the index.

## Verification

The subsystem was tested with a temporary mixed-language workspace containing TypeScript, Python, C++, and Java files plus `package.json` and `requirements.txt`.

Verified:

- Automatic indexing on workspace open
- Language detection
- Framework detection
- Dependency extraction
- Symbol extraction
- Entry point detection
- Index summary API
- Incremental re-index after one changed file
