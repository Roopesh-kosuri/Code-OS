"""
backend_main.py - Entry point for PyInstaller-bundled CODE OS backend.

This script starts the uvicorn server for the FastAPI backend.
It is ONLY used by PyInstaller - not by the normal dev-mode Python launch.
"""
import sys
import os

# Configure immediate line buffering for stdout/stderr
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(line_buffering=True, encoding="utf-8")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(line_buffering=True, encoding="utf-8")
    except Exception:
        pass

import uvicorn


def main():
    if getattr(sys, 'frozen', False):
        bundle_dir = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
        sys.path.insert(0, bundle_dir)
        if 'CODE_OS_HOME' not in os.environ:
            home = os.path.expanduser('~')
            os.environ['CODE_OS_HOME'] = os.path.join(home, '.code-os')

    from app.main import app as fastapi_app

    uvicorn.run(
        fastapi_app,
        host="127.0.0.1",
        port=8000,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    main()
