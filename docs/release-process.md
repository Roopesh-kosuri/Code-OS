# CODE OS — Release Process & Clean Publish Procedure

## Overview

This document outlines the official release procedure for **CODE OS v5.0.0**.

> [!IMPORTANT]
> **Zero Leakage Rule**: Internal development artifacts, audit findings registers, vulnerability analyses, and session resume states exist only in local development commits. They are untracked and excluded via `.gitignore`. The local development branch containing intermediate audit commits must **NEVER** be pushed to a public remote.

---

## Clean-Publish Procedure (Orphan Branch)

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
- `scratch/`, `build/` (except icons and entitlements), `dist/`, `release/`

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

## Post-Release Verification

1. Verify on GitHub that the commit tree contains only the single clean `release: CODE OS v5.0.0` commit.
2. Confirm that `.security-exceptions.json`, `docs/macos-install.md`, `docs/release-process.md`, and `CHANGELOG.md` are present and valid.
3. Confirm that `docs/audit/` does not exist on the remote.
