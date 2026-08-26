import subprocess
import time
import urllib.request
import urllib.error
import json
import sqlite3
import os
import sys
import tempfile
import shutil
from pathlib import Path

def run_all_security_tests():
    # Paths
    temp_dir = Path(tempfile.gettempdir())
    WORKSPACE_TRUSTED = str((temp_dir / "trusted_workspace").resolve()).replace("\\", "/")
    WORKSPACE_RESTRICTED = str((temp_dir / "restricted_workspace").resolve()).replace("\\", "/")
    DB_PATH = os.path.expanduser("~/.code-os/code-os.sqlite3")

    # Create workspaces (clean first if they exist)
    if os.path.exists(WORKSPACE_TRUSTED):
        shutil.rmtree(WORKSPACE_TRUSTED, ignore_errors=True)
    if os.path.exists(WORKSPACE_RESTRICTED):
        shutil.rmtree(WORKSPACE_RESTRICTED, ignore_errors=True)

    os.makedirs(WORKSPACE_TRUSTED, exist_ok=True)
    os.makedirs(WORKSPACE_RESTRICTED, exist_ok=True)

    # Setup DB trust states
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS workspace_trust (path TEXT PRIMARY KEY, trusted INTEGER NOT NULL DEFAULT 0, trust_level TEXT, trusted_at TEXT)")
    c.execute("INSERT OR REPLACE INTO workspace_trust (path, trusted, trust_level) VALUES (?, ?, ?)", (str(Path(WORKSPACE_TRUSTED).resolve()), 1, "trusted"))
    c.execute("INSERT OR REPLACE INTO workspace_trust (path, trusted, trust_level) VALUES (?, ?, ?)", (str(Path(WORKSPACE_RESTRICTED).resolve()), 0, "restricted"))
    conn.commit()
    conn.close()

    print("Starting backend server...")
    project_root = Path(__file__).resolve().parent.parent.parent
    backend_dir = project_root / "backend"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(backend_dir)
    server_process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8000"],
        cwd=str(backend_dir),
        env=env
    )
    time.sleep(3) # Wait for server to start

    def _run_endpoint_test(endpoint: str, payload: dict, expected_status: int, name: str, method: str = "POST"):
        url = f"http://127.0.0.1:8000{endpoint}"
        token_path = Path.home() / ".code-os" / "session_token"
        token = token_path.read_text(encoding="utf-8").strip() if token_path.exists() else ""
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {token}',
        }
        if method == "POST":
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        else:
            req = urllib.request.Request(url, headers=headers, method="GET")

        try:
            response = urllib.request.urlopen(req)
            status = response.getcode()
            body = response.read().decode('utf-8')
        except urllib.error.HTTPError as e:
            status = e.code
            body = e.read().decode('utf-8')
        except Exception as e:
            raise AssertionError(f"[{name}] Connection error: {e}")

        if status == expected_status:
            print(f"[{status}] {name} - PASSED (Expected {expected_status}, Response: {body})")
        else:
            raise AssertionError(f"[{status}] {name} - FAILED (Expected {expected_status}, got {status}, Response: {body})")

    try:
        print("\n--- Testing RESTRICTED Workspace ---")
        _run_endpoint_test("/api/workspaces/open", {"path": WORKSPACE_RESTRICTED}, 200, "Open RESTRICTED Workspace")
        _run_endpoint_test("/api/files/write", {"workspace": WORKSPACE_RESTRICTED, "path": f"{WORKSPACE_RESTRICTED}/test.txt", "content": "hello"}, 403, "RESTRICTED /api/files/write")
        _run_endpoint_test("/api/files/create", {"workspace": WORKSPACE_RESTRICTED, "path": f"{WORKSPACE_RESTRICTED}/test2.txt", "type": "file"}, 403, "RESTRICTED /api/files/create")
        _run_endpoint_test("/api/files/rename", {"workspace": WORKSPACE_RESTRICTED, "path": f"{WORKSPACE_RESTRICTED}/test2.txt", "new_name": "test3.txt"}, 403, "RESTRICTED /api/files/rename")
        _run_endpoint_test("/api/files/delete", {"workspace": WORKSPACE_RESTRICTED, "path": f"{WORKSPACE_RESTRICTED}/test2.txt"}, 403, "RESTRICTED /api/files/delete")
        _run_endpoint_test("/api/files/move", {"workspace": WORKSPACE_RESTRICTED, "source": f"{WORKSPACE_RESTRICTED}/test.txt", "destination": f"{WORKSPACE_RESTRICTED}/test_moved.txt"}, 403, "RESTRICTED /api/files/move")
        _run_endpoint_test("/api/files/duplicate", {"workspace": WORKSPACE_RESTRICTED, "path": f"{WORKSPACE_RESTRICTED}/test.txt", "destination": f"{WORKSPACE_RESTRICTED}/test_dup.txt"}, 403, "RESTRICTED /api/files/duplicate")
        _run_endpoint_test("/api/ai/edit-proposals", {"workspace": WORKSPACE_RESTRICTED, "summary": "test", "files": []}, 403, "RESTRICTED /api/ai/edit-proposals")
        _run_endpoint_test(f"/api/files/tree?workspace={WORKSPACE_RESTRICTED}", {}, 403, "RESTRICTED /api/files/tree", method="GET")
        _run_endpoint_test(f"/api/files/read?workspace={WORKSPACE_RESTRICTED}&path={WORKSPACE_RESTRICTED}/test.txt", {}, 403, "RESTRICTED /api/files/read", method="GET")
        _run_endpoint_test(f"/api/git/status?workspace={WORKSPACE_RESTRICTED}", {}, 403, "RESTRICTED /api/git/status", method="GET")
        _run_endpoint_test(f"/api/search/text?workspace={WORKSPACE_RESTRICTED}&query=test", {}, 403, "RESTRICTED /api/search/text", method="GET")
        _run_endpoint_test("/api/search/replace", {"workspace": WORKSPACE_RESTRICTED, "query": "a", "replacement": "b", "apply": True}, 403, "RESTRICTED /api/search/replace (apply=True)")
        _run_endpoint_test("/api/search/replace", {"workspace": WORKSPACE_RESTRICTED, "query": "a", "replacement": "b", "apply": False}, 200, "RESTRICTED /api/search/replace (apply=False)")
        _run_endpoint_test("/api/terminal/sessions", {"cwd": WORKSPACE_RESTRICTED, "shell": "powershell"}, 403, "RESTRICTED /api/terminal/sessions (create)")
        _run_endpoint_test("/api/git/commit", {"workspace": WORKSPACE_RESTRICTED, "message": "commit message"}, 403, "RESTRICTED /api/git/commit")

        time.sleep(1.2)

        print("\n--- Testing TRUSTED Workspace ---")
        _run_endpoint_test("/api/workspaces/open", {"path": WORKSPACE_TRUSTED}, 200, "Open TRUSTED Workspace")
        _run_endpoint_test("/api/files/write", {"workspace": WORKSPACE_TRUSTED, "path": f"{WORKSPACE_TRUSTED}/test.txt", "content": "hello"}, 200, "TRUSTED /api/files/write")
        _run_endpoint_test("/api/files/create", {"workspace": WORKSPACE_TRUSTED, "path": f"{WORKSPACE_TRUSTED}/test2.txt", "type": "file"}, 200, "TRUSTED /api/files/create")
        _run_endpoint_test("/api/files/rename", {"workspace": WORKSPACE_TRUSTED, "path": f"{WORKSPACE_TRUSTED}/test2.txt", "new_name": "test3.txt"}, 200, "TRUSTED /api/files/rename")
    finally:
        print("Shutting down server...")
        server_process.terminate()
        server_process.wait()

if __name__ == '__main__':
    run_all_security_tests()
