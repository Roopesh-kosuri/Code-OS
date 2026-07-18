# CODE OS CI/CD Workflows

This directory contains the GitHub Actions configurations for Continuous Integration (CI) and Continuous Delivery/Release Packaging (CD).

---

## 1. Continuous Integration (`ci.yml`)

### Triggers
- Runs on every `push` and `pull_request` targeting the `main` branch.

### Environment & Runner
- Executes on an `ubuntu-latest` (Linux) runner for optimal build speeds.

### Automated Checks
1. **Frontend Integration**:
   - Installs node dependencies (`npm install`).
   - Runs TypeScript compilation checks (`npm run typecheck`).
   - Compiles the web application bundle (`npm run build`).
2. **Backend Verification**:
   - Sets up Python 3.11.
   - Installs pip packages (`backend/requirements.txt`).
   - Runs the backend test suite, including fast-path models and platform-agnostic workspace trust integration tests:
     ```bash
     python -m unittest discover -s backend/tests -p "test_*.py"
     ```

---

## 2. Release Packaging (`release.yml`)

### Triggers
- Triggers automatically when a new release version tag (matching `v*.*.*`) is pushed to the repository.

### Environment & Build Matrix
Executes a multi-platform compilation matrix:
- `windows-latest` (compiles Windows `.exe` installer via NSIS).
- `macos-latest` (compiles macOS `.dmg` disk image; unsigned unless certificates are configured).
- `ubuntu-latest` (compiles Linux `.AppImage` and `.deb` packages).

### Packaging Architecture & Extra Resources
To run the FastAPI server, the application's backend directory is copied into the packaged build's `extraResources` directory. This keeps the Python scripts outside the Node.js ASAR archive, ensuring they remain readable by a local python executable.

> [!NOTE]
> Currently, the production package relies on a local system Python installation on the host machine to execute. For a fully self-contained deployment, future packaging must bundle a portable Python interpreter or use a tool like PyInstaller to compile the FastAPI server code into a single binary executable.
