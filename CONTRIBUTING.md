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
   - Run tests: `python -m unittest discover -s backend/tests -p "test_*.py"`

---

## 3. Pull Request Requirements

We enforce strict validation checks on all pull requests targeting the `main` branch:

- **Continuous Integration (CI)**: All pushed commits and pull requests trigger `.github/workflows/ci.yml`.
- **Pass Verification**: Any failures in frontend compilation, TypeScript typechecking, or backend tests will cause the CI workflow to fail.
- **Merge Gate**: Pull requests cannot be merged unless all CI checks are passing successfully.

Please check the **Actions** tab on your fork or repository page to track status!
