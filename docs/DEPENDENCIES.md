# Dependency Audit & Supply Chain Security

**CODE OS v3.1.0 Security Compliance Report**

## 1. Python Backend Audit (`pip-audit`)
- **Scanner**: `pip-audit` v2.10.1 (PyPA / PyPI Advisory Database)
- **Target**: `backend/requirements.txt`
- **Result**: **0 known vulnerabilities** found.
- **Hardened Version Pins**:
  - `cryptography`: Upgraded to `50.0.1` (resolves all known CVEs).
  - `gitpython`: Upgraded to `3.1.61` (resolves all command injection / path escape advisories).
  - `python-multipart`: Upgraded to `0.0.32` (resolves parsing overflow CVEs).
  - `fastapi`: Upgraded to `0.141.1` and `starlette` to `1.6.0`.
  - `aiohttp`: Upgraded to `3.14.3`.
  - `uvicorn`: Upgraded to `0.52.4`.

## 2. Frontend Node.js Audit (`npm audit`)
- **Scanner**: `npm audit` (GitHub Advisory Database)
- **Target**: `package.json` production runtime dependencies
- **Production Audit Findings**:
  - `dompurify` (bundled transitively via `@monaco-editor/react` / `monaco-editor`):
    - Severity: Low / Moderate (Custom element attribute handling).
    - Mitigation: CODE OS sanitizes all AI markdown and code diffs before passing to Monaco and DOMPurify with strict HTML escape policies. Monaco editor operates inside an isolated sandbox with `contextIsolation: true` and no direct Node.js execution.

## 3. Dependency Pinning & Supply Chain Rules
1. All Python dependencies must be pinned with exact `==` versions.
2. Direct dependencies must not use wildcards (`*`) or unbounded ranges.
3. Supply chain audits run automatically in CI pipeline before every release.
