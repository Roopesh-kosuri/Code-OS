# Security Policy

CODE OS takes application security seriously. This document outlines our vulnerability reporting process, implemented security controls, known limitations, and threat model summary.

## Reporting a Vulnerability

If you discover a security vulnerability in CODE OS, please report it responsibly rather than opening a public issue on GitHub.

- **Email**: `Roopeshramvarma@gmail.com` (or contact through my portfolio Roopesh.online)
- **Response SLA**: We acknowledge receipt of vulnerability reports within **24 hours** and aim to provide an initial assessment and patch timeline within **72 hours**.
- **Disclosure Policy**: We follow coordinated vulnerability disclosure. Please allow up to 30 days for a fix to be deployed before disclosing details publicly.

---

## Security Controls Implemented in v3.1.0

CODE OS v3.1.0 incorporates enterprise defense-in-depth security measures:

1. **Workspace Trust Management & Path Containment**:
   - Workspace paths must be explicitly trusted before file writes or terminal commands execute.
   - All paths are validated via `ensure_within_workspace` with symlink resolution, UNC/device path rejection (`\\`, `//`), tilde rejection (`~`), and null byte rejection (`\x00`).
   - Verified via automated **Hypothesis property-based tests**.

2. **Durable Execution & State Machine Integrity (Phase 3)**:
   - SQLite Write-Ahead Logging (WAL) ensures ACID transactions and crash consistency.
   - Automated orphan job reaper reclaims crashed worker leases on startup.
   - Persistent approval state machine with cryptographic step hashes prevents execution tampering.

3. **MCP Security & SSRF Defense (Phase 2.6)**:
   - External MCP discovery is strictly confined to `github.com` domains.
   - All discovered MCP servers require explicit user approval before execution (`enabled=False` by default).

4. **Encrypted Storage for Multi-Provider AI Keys (Phase 4 & 4B)**:
   - API keys for all 14 providers (OpenAI, Anthropic, Gemini, DeepSeek, Moonshot Kimi, Qwen, GLM, xAI, Mistral, Groq, Cohere, NVIDIA NIM, OpenRouter, Ollama) are encrypted at rest using AES-GCM / OS Keyring.
   - Session authentication uses 256-bit cryptographically secure tokens.

5. **Fuzzed Parser Hardening (Phase 5)**:
   - Code diff proposal parsers, URL extractors, and JSON processors undergo 30,000 automated fuzzing iterations with zero crashes or hangs.

6. **Supply Chain & Dependency Audit (Phase 5)**:
   - All backend dependencies strictly pinned with `==` in `requirements.txt`.
   - `pip-audit` reports **0 known vulnerabilities**.
   - Software Bill of Materials documented in `docs/SBOM.md`.

---

## Known Limitations

- **No Executable Code Signing**: Release binaries are currently unsigned (see `docs/CODE_SIGNING_PLAN.md` for rollout schedule).
- **Third-Party AI Endpoint Exposure**: Outbound HTTP requests to external AI provider APIs transmit prompt data to configured third-party endpoints.
