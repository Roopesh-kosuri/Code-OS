# Security Policy

CODE OS takes application security seriously. This document outlines our vulnerability reporting process, implemented security controls, known limitations, and threat model summary.

## Reporting a Vulnerability

If you discover a security vulnerability in CODE OS, please report it responsibly rather than opening a public issue on GitHub.

- **Email**: `Roopeshramvarma@gmail.com` (or contact through my portfolio Roopesh.online)
- **Response SLA**: We acknowledge receipt of vulnerability reports within **24 hours** and aim to provide an initial assessment and patch timeline within **72 hours**.
- **Disclosure Policy**: We follow coordinated vulnerability disclosure. Please allow up to 30 days for a fix to be deployed before disclosing details publicly.

---

## Summary of Security Controls

CODE OS implements defense-in-depth security measures across all layers:

1. **Workspace Trust Management**:
   - Workspace paths must be explicitly trusted by the user before write operations or terminal executions are allowed.
   - Restricted Mode blocks file modifications, command executions, and destructive git mutations.

2. **Strict Path Sandboxing**:
   - Every file system request resolves real paths to prevent symlink bypasses and `..` path traversal.
   - Tilde (`~`) path expansion is strictly forbidden on client-supplied API parameters.

3. **Session Token Authentication**:
   - High-privilege API routes require a 256-bit ephemeral session token (`Authorization: Bearer <session-token>`).
   - Constant-time comparison (`secrets.compare_digest`) prevents timing side-channel attacks.

4. **Terminal Environment Sanitization**:
   - Terminal subprocesses are executed with a strictly scoped environment allowlist.
   - Sensitive credentials (`AWS_SECRET_ACCESS_KEY`, `GITHUB_TOKEN`, `DATABASE_PASSWORD`) are filtered out.

5. **Encrypted Rest Storage for API Keys**:
   - Master Fernet keys are stored in OS-native secure storage (macOS Keychain, Windows Credential Manager, Linux Secret Service via `keyring`).
   - Fallback file key storage enforces POSIX `0600` permissions (`chmod 600`).

6. **Content Security Policy (CSP)**:
   - Renderer window enforces restrictive CSP headers limiting frame ancestry, script origins, and network connections.

---

## Known Limitations

- **No Executable Code Signing**: Release binaries are not currently signed with Apple or Microsoft digital certificates.
- **Third-Party AI Endpoint Exposure**: Outbound HTTP requests to external AI provider APIs (e.g. Anthropic, OpenAI) transmit prompt data to third-party endpoints as configured by the user.

---

## Threat Model Summary

- **In-Scope**:
  - Path traversal & arbitrary file read/write escaping workspace boundary.
  - Remote code execution (RCE) via untrusted backend API requests.
  - Unauthorized access to stored AI provider API keys.
  - Exfiltration of environment credentials via terminal subshells.

- **Out-of-Scope**:
  - Physical access or root-level privilege escalation on the host OS.
  - Vulnerabilities in user-installed third-party OS packages or local LLM runtimes (Ollama).
