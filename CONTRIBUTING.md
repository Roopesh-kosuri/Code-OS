# Contributing to CODE OS

Thank you for your interest in contributing to CODE OS! As a local-first AI development workspace, we aim to maintain a robust, reliable, and secure development environment.

---

## 1. Local Development Setup

To set up the project locally, run:

```bash
# Clone the repository and navigate to root
git clone https://github.com/roopesh-kosuri/code-os.git
cd code-os

# Install frontend dependencies (including electron-builder)
npm install

# Install backend dependencies
pip install -r backend/requirements.txt
```

Start the local server suite (Vite + FastAPI + Electron) with:

```bash
npm run dev
```

---

## 2. Testing Your Changes Locally

Before opening a pull request, you **must** verify that your changes compile and pass tests locally:

1. **Frontend TypeScript & Build Checks**:
   - Run typecheck compiler: `npm run typecheck`
   - Run bundler compiler: `npm run build`
2. **Backend Unit & Integration Tests**:
   - Run tests: `python -m pytest backend/tests -v`

---

## 3. Pull Request Requirements

We enforce strict validation checks on all pull requests targeting the `main` branch:

- **Continuous Integration (CI)**: All pushed commits and pull requests trigger `.github/workflows/ci.yml`.
- **Pass Verification**: Any failures in frontend compilation, TypeScript typechecking, or backend tests will cause the CI workflow to fail.
- **Merge Gate**: Pull requests cannot be merged unless all CI checks are passing successfully.

Please check the **Actions** tab on your fork or repository page to track status!

---

## 4. Release Architecture & Procedure

> **CI builds and uploads macOS and Linux automatically** (via `.github/workflows/release.yml` on `macos-latest` and `ubuntu-latest` runners).
> Windows installers are built **locally** by the maintainer and uploaded to the GitHub Release by hand.

### Building Windows installers (on a Windows machine)

```powershell
# 1. Install dependencies
npm install
pip install -r backend/requirements.txt pyinstaller

# 2. Compile the PyInstaller backend binary
npm run build:backend-exe

# 3. Download bundled Python + Node runtimes for Windows
npm run fetch-runtimes   # auto-detects platform (win32)

# 4. Run preflight check + package
npm run package          # runs build -> preflight -> electron-builder
# Output: release/CODE-OS-Setup-<version>.exe  (NSIS installer)
#         release/CODE-OS-<version>-portable.exe (portable)
```

### Uploading Windows assets to GitHub Release

1. Push your release tag:
   ```bash
   git tag v3.0.1
   git push origin v3.0.1
   ```
2. GitHub Actions will automatically compile and attach:
   - `CODE-OS-3.0.1.dmg` (macOS DMG)
   - `CODE-OS-3.0.1-mac.zip` (macOS ZIP)
   - `CODE-OS-3.0.1.AppImage` (Linux AppImage)
   - `code-os_3.0.1_amd64.deb` (Linux deb package)
3. Go to the GitHub repository → **Releases** → `v3.0.1`.
4. Click **Edit release**, drag-and-drop the local Windows files (`CODE-OS-Setup-3.0.1.exe` and `CODE-OS-3.0.1-portable.exe`), and click **Update release**.

---

## 5. Security

Please see [SECURITY.md](SECURITY.md) for our vulnerability disclosure policy.