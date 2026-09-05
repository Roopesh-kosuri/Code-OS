# Software Bill of Materials (SBOM)

**Product**: CODE OS v3.1.0  
**Generated**: September 2026  
**License**: SEE LICENSE IN License.md  

## Critical Dependencies (Top 20)

| # | Package / Component | Ecosystem | Version | Purpose / Role | License |
|---|---------------------|-----------|---------|----------------|---------|
| 1 | `fastapi` | Python | `0.141.1` | Core REST API framework & OpenAPI specification | MIT |
| 2 | `uvicorn` | Python | `0.52.4` | ASGI web server supervisor | BSD-3-Clause |
| 3 | `aiosqlite` | Python | `0.20.0` | Async SQLite database engine & durable logging | MIT |
| 4 | `cryptography` | Python | `50.0.1` | Secure token & API key AES-GCM encryption | Apache-2.0 / BSD |
| 5 | `httpx` | Python | `0.28.1` | Async HTTP client for AI model providers | BSD-3-Clause |
| 6 | `pydantic` | Python | `2.13.5` | Strict data validation & schema enforcement | MIT |
| 7 | `pydantic-settings` | Python | `2.15.0` | Environment & runtime configuration parsing | MIT |
| 8 | `gitpython` | Python | `3.1.61` | Git repository workspace operations | BSD-3-Clause |
| 9 | `watchdog` | Python | `6.0.0` | Native filesystem event monitoring | Apache-2.0 |
| 10 | `pywinpty` | Python | `2.0.14` | Windows ConPTY terminal pseudoterminal | MIT |
| 11 | `python-multipart` | Python | `0.0.32` | Form & multipart payload parsing | Apache-2.0 |
| 12 | `hypothesis` | Python | `6.167.1` | Property-based fuzz & security validation | MPL-2.0 |
| 13 | `electron` | Node.js | `33.2.1` | Native desktop window shell & IPC bridge | MIT |
| 14 | `react` | Node.js | `18.3.1` | Frontend declarative component rendering | MIT |
| 15 | `react-dom` | Node.js | `18.3.1` | DOM renderer for React | MIT |
| 16 | `@monaco-editor/react` | Node.js | `4.7.0` | Code editor core UI component | MIT |
| 17 | `monaco-editor` | Node.js | `0.52.0` | In-browser code editing engine | MIT |
| 18 | `node-pty` | Node.js | `1.1.0` | Native backend PTY fork & process management | MIT |
| 19 | `@xterm/xterm` | Node.js | `5.5.0` | Terminal emulator frontend renderer | MIT |
| 20 | `zustand` | Node.js | `5.0.2` | Client-side centralized reactive state management | MIT |

## Lockfile Integrity
- Python dependencies are strictly pinned with `==` in `backend/requirements.txt`.
- Node.js dependencies are locked with SHA-512 subresource integrity hashes in `package-lock.json`.
