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

## 4. Manual Release Procedure

> **CI builds and uploads macOS only** (via `.github/workflows/release.yml` on a `macos-latest` runner).
> Windows and Linux installers must be built **locally** by the maintainer and uploaded to the GitHub Release by hand.

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

### Building Linux installers (on Ubuntu 22.04 / WSL2)

```bash
# 1. Install system deps for electron-builder fpm targets
sudo apt-get update && sudo apt-get install -y ruby ruby-dev build-essential rpm
sudo gem install --no-document fpm

# 2. Install project dependencies
npm install
pip install -r backend/requirements.txt pyinstaller

# 3. Compile backend binary
npm run build:backend-exe

# 4. Download runtimes for Linux
node scripts/download-runtimes.js --linux

# 5. Run preflight + package
npm run package
# Output: release/CODE-OS-<version>.AppImage
#         release/code-os_<version>_amd64.deb
```

### Uploading assets to the GitHub Release

After local builds succeed:

1. Go to the GitHub repository → **Releases** → the tag you just pushed.
2. Click **Edit release**.
3. Drag-and-drop the Windows and Linux files from your local `release/` folder.
4. Click **Update release**.

The macOS `.dmg` and `.zip` are uploaded automatically by CI.

### Consistent asset naming convention

| Platform | Asset filename |
|----------|---------------|
| Windows installer | `CODE-OS-Setup-<version>.exe` |
| Windows portable  | `CODE-OS-<version>-portable.exe` |
| macOS DMG         | `CODE-OS-<version>.dmg` |
| macOS ZIP         | `CODE-OS-<version>-mac.zip` |
| Linux AppImage    | `CODE-OS-<version>.AppImage` |
| Linux deb         | `code-os_<version>_amd64.deb` |

---

## 5. Security

Please see [SECURITY.md](SECURITY.md) for our vulnerability disclosure policy.