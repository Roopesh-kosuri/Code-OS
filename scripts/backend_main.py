"""
backend_main.py — Entry point for PyInstaller-bundled CODE OS backend.

This script starts the uvicorn server for the FastAPI backend.
It is ONLY used by PyInstaller — not by the normal dev-mode Python launch.
The normal dev path continues to use:
    python -m uvicorn backend.app.main:app ...
"""
import sys
import os
import uvicorn


def main():
    # When running as a PyInstaller bundle, sys._MEIPASS contains
    # the extracted temporary directory. We add it to sys.path so
    # 'from app.xxx import ...' imports work correctly.
    if getattr(sys, 'frozen', False):
        bundle_dir = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
        # The 'app' directory is bundled at the root of _MEIPASS
        sys.path.insert(0, bundle_dir)
        # Set CODE_OS_HOME so the backend knows where to store its data
        if 'CODE_OS_HOME' not in os.environ:
            home = os.path.expanduser('~')
            os.environ['CODE_OS_HOME'] = os.path.join(home, '.code-os')

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    main()
