# CODE OS Pre-Release Security Checklist

Every release of CODE OS must satisfy the following security checklist before distribution:

## 1. Supply Chain & Dependencies
- [ ] Run `python -m pip_audit -r backend/requirements.txt` — must report **0 vulnerabilities**.
- [ ] Verify all dependencies in `backend/requirements.txt` use exact `==` version pins.
- [ ] Run `npm audit --omit=dev` — verify only documented low/moderate vendor dependencies exist.
- [ ] Update `docs/SBOM.md` with current dependency version table.

## 2. Automated Security & Property Tests
- [ ] Run property-based path containment test: `python -m pytest tests/test_path_containment_property.py -v` (300+ hypothesis iterations, 0 escapes).
- [ ] Run parser fuzz suite: `python -m pytest tests/fuzz/ -v` (30,000 fuzz iterations across diffs, URLs, JSON).
- [ ] Run security regression suite: `python -m pytest tests/test_phase5_security.py tests/test_path_traversal_security.py -v`.

## 3. High-Concurrency & Chaos Validation
- [ ] Run load test: `python scripts/loadtest.py --duration 30` (P95 < 100ms, error rate < 1%).
- [ ] Run chaos test suite: `python -m pytest tests/chaos/ -v` (concurrent approvals, process crashes, db corruption recovery).

## 4. Manual Penetration & Verification Items
- [ ] Verify restricted mode blocks file creation/modification in untrusted workspaces.
- [ ] Verify session token header `Authorization: Bearer <token>` is strictly enforced on all mutating `/api/*` endpoints.
- [ ] Verify API keys are stored encrypted and never logged in plaintext.
- [ ] Verify CSP headers in `index.html` block unauthorized third-party script and connect origins.
