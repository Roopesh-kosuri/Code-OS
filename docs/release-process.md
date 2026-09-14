# CODE OS — Release Process & Clean Publish Procedure

## Overview

This document outlines the official release procedure for **CODE OS v5.0.0**.

> [!IMPORTANT]
> **Zero Leakage Rule**: Internal development artifacts, audit findings registers, vulnerability analyses, and session resume states exist only in local development commits. They are untracked and excluded via `.gitignore`. The local development branch containing intermediate audit commits must **NEVER** be pushed to a public remote.

---

## 1. Clean-Publish Procedure (Orphan Branch)

Because local intermediate commits contain internal audit history, releases are published to public repositories via a clean orphan branch that respects `.gitignore`:

### Step 1: Create an Orphan Release Branch

From a clean working tree on `main`:

```bash
git checkout --orphan release-v5
```

This creates an unparented branch with an empty commit history while keeping all working tree files intact.

### Step 2: Stage Tracked Production Files

Stage all files in the working directory (respecting `.gitignore`):

```bash
git add -A
```

`.gitignore` automatically excludes:
- `docs/audit/**` (findings register, expected vs actual, fix plan)
- `PHASE_STATE.md` (session resume state)
- `docs/TEAM_CONSOLE_AUDIT.md`, `docs/SYSTEM_VERIFICATION_REPORT.md`, `docs/V4_FINAL_VERIFICATION_REPORT.md`
- `docs/CODEX_CURRENT_ERRORS.md`, `docs/CODEX_HANDOFF.md`, `docs/CODE_SIGNING_PLAN.md`
- `docs/PRE_COMMIT_CHECKLIST.md`, `docs/RELEASE_CLEANUP.md`
- `*walkthrough*.md`, `*notes*.md`
- `bandit_raw.json`, `task-*.log`, `*.log`
- `scratch/`, `build/` (except icons, entitlements, and runtimes), `dist/`, `release/`

### Step 3: Verify Staged Inventory

Run verification before committing to guarantee zero internal documents are staged:

```bash
git ls-files | grep -iE "(audit|phase_state|findings|fix_plan|codex|bandit)"
```

This command must return **zero** matches.

### Step 4: Create Clean Release Commit

```bash
git commit -m "release: CODE OS v5.0.0"
```

### Step 5: Tag the Release

```bash
git tag v5.0.0
```

### Step 6: Push ONLY the Release Branch and Tag

```bash
git push origin release-v5
git push origin v5.0.0
```

> [!CAUTION]
> **NEVER push the development branch (`main` or feature branches with intermediate audit history) to any public remote.** Only push `release-v5` and annotated release tags.

---

## 2. Release Build Procedures

Release builds follow a hybrid model:
- **macOS**: Built, signed, notarized, and spctl-verified automatically via GitHub Actions CI upon tag push.
- **Windows & Linux**: Built locally by the maintainer and manually uploaded to GitHub Releases to avoid CI credential collision and environment drift.

### A. Pre-Build Artifact Cleaning

Always run the clean script before building release packages:

```bash
# Deletes old release installers from release/
node scripts/clean-release.js
```

### B. Windows Build (Assisted Installer & Portable)

Windows releases bundle Python 3.11 standalone, Node.js 20 LTS, MinGit portable, and offline tiktoken encoding caches (`cl100k_base`, `o200k_base`):

```bash
# 1. Ensure all portable runtimes and token caches are downloaded
node scripts/download-runtimes.js --win

# 2. Build the backend executable and compile Vite/Electron
npm run build

# 3. Generate NSIS installer and portable executable
npm run build:win

# 4. Prune stale build artifacts
node scripts/clean-release.js --prune-stale
```

Generated artifacts in `release/`:
- `CODE OS-5.0.0-setup.exe` (NSIS assisted installer)
- `CODE OS-5.0.0-portable.exe` (Zero-install portable executable)

### C. Linux Build (AppImage & Debian Package)

Linux releases can be built using Docker (recommended) or WSL2:

```bash
# Option 1: Docker (Single-command isolated build)
docker run --rm -ti -v "${PWD}:/project" -w /project electronuserland/builder:wine npm run build:linux

# Option 2: Native Linux / WSL2
npm run download:runtimes -- --linux
npm run build:linux
```

Generated artifacts in `release/`:
- `CODE OS-5.0.0-x64.AppImage`
- `CODE OS-5.0.0-x64.deb`

### D. macOS Build (Automated in CI)

Upon pushing a release tag (`v5.0.0`), the GitHub Actions `mac-release-build` workflow executes:
1. `npm run build:mac`
2. Apple Developer ID codesigning with hardened runtime
3. Apple notarization (`notarytool`) and stapling
4. Gatekeeper verification (`spctl --assess -vv --type install release/mac*/"CODE OS.app"`)
5. Artifact release guard (`scripts/release-guard.js`)

Generated artifacts:
- `CODE OS-5.0.0-mac-x64.dmg` / `CODE OS-5.0.0-mac-arm64.dmg`
- `CODE OS-5.0.0-mac-x64.zip` / `CODE OS-5.0.0-mac-arm64.zip`

---

## 3. GitHub Release Creation & Upload

1. Navigate to `https://github.com/Roopesh-kosuri/code-os/releases/new`.
2. Select tag: `v5.0.0`.
3. Set release title: `CODE OS v5.0.0 — Agentic AI Operating System`.
4. Copy release notes from `CHANGELOG.md`.
5. Attach the locally built Windows and Linux binaries:
   - `release/CODE OS-5.0.0-setup.exe`
   - `release/CODE OS-5.0.0-portable.exe`
   - `release/CODE OS-5.0.0-x64.AppImage` (if built)
   - `release/CODE OS-5.0.0-x64.deb` (if built)
6. Attach the macOS artifacts generated from the CI build workflow.
7. Click **Publish Release**.
