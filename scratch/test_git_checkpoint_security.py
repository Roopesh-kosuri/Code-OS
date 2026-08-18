"""
test_git_checkpoint_security.py
Verification suite for Git checkpoint data leak fix.

Validates:
1. .gitignore template contains .env, *.pem, id_rsa, .aws/, .ssh/, *.key, credentials.json, serviceAccountKey.json, *.sqlite, *.db
2. Workspace with .env and sensitive files does NOT stage/commit .env when a regular file is modified (git show HEAD --stat)
3. Validation check: If touched_files contains .env or any sensitive pattern, checkpoint is aborted with exact error message:
   "Agent touched sensitive file: {filename}. Add it to .gitignore or exclude it from the workspace."
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Add backend to sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.features.ai.chat_harness import (
    _ensure_git_checkpoint,
    _is_sensitive_filename,
    SENSITIVE_FILE_PATTERNS,
)


def run_verification():
    print("================================================================================")
    print("           GIT CHECKPOINT DATA LEAK FIX VERIFICATION SUITE                      ")
    print("================================================================================\n")

    passed_count = 0
    total_count = 0

    with tempfile.TemporaryDirectory() as tmp_dir:
        ws_path = Path(tmp_dir).resolve()
        
        # 1. Create a workspace with a .env file containing fake API keys and other secrets
        env_file = ws_path / ".env"
        env_file.write_text("OPENAI_API_KEY=sk-fake-secret-key-1234567890\nDB_PASS=SuperSecret123\n", encoding="utf-8")
        
        ssh_key = ws_path / "id_rsa"
        ssh_key.write_text("-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----\n", encoding="utf-8")
        
        pem_file = ws_path / "cert.pem"
        pem_file.write_text("-----BEGIN CERTIFICATE-----\nMIIDXTCCAkWgAwIBAgIJAK...\n-----END CERTIFICATE-----\n", encoding="utf-8")

        regular_file = ws_path / "src" / "app.py"
        regular_file.parent.mkdir(parents=True, exist_ok=True)
        regular_file.write_text("def main():\n    print('Hello CODE OS')\n", encoding="utf-8")

        # ---------------------------------------------------------------------
        # TEST 1: Check .gitignore template generation
        # ---------------------------------------------------------------------
        total_count += 1
        print("[TEST 1] Verifying .gitignore template creation...")
        new_init, commit_h, err = _ensure_git_checkpoint(str(ws_path), turn_num=1, touched_files=["src/app.py"])
        
        gitignore_path = ws_path / ".gitignore"
        assert gitignore_path.is_file(), ".gitignore was not created!"
        gitignore_content = gitignore_path.read_text(encoding="utf-8")
        
        required_patterns = [
            ".env", "*.pem", "id_rsa", ".aws/", ".ssh/", "*.key",
            "credentials.json", "serviceAccountKey.json", "*.sqlite", "*.db"
        ]
        
        missing = [pat for pat in required_patterns if pat not in gitignore_content]
        if not missing:
            print(f"  [+] .gitignore created with all required sensitive patterns:\n{gitignore_content.strip()}")
            print("[+] PASS: Test 1 - .gitignore contains all sensitive patterns.")
            passed_count += 1
        else:
            print(f"  [-] Missing patterns in .gitignore: {missing}")
            print("[-] FAIL: Test 1 - .gitignore template incomplete.")

        # ---------------------------------------------------------------------
        # TEST 2: Confirm .env is NOT in the git commit (git show HEAD --stat)
        # ---------------------------------------------------------------------
        total_count += 1
        print("\n[TEST 2] Verifying .env, id_rsa, and cert.pem are NOT staged or committed...")
        
        # Check files in HEAD commit
        show_proc = subprocess.run(
            ["git", "show", "HEAD", "--stat", "--name-only"],
            cwd=str(ws_path),
            capture_output=True,
            text=True,
        )
        commit_output = show_proc.stdout
        print(f"  Git commit stat output:\n{commit_output.strip()}")

        has_env = ".env" in commit_output
        has_ssh = "id_rsa" in commit_output
        has_pem = "cert.pem" in commit_output
        has_app = "src/app.py" in commit_output

        if not has_env and not has_ssh and not has_pem and has_app:
            print("[+] PASS: Test 2 - .env, id_rsa, and cert.pem are NOT in the git commit. Only touched files staged.")
            passed_count += 1
        else:
            print(f"[-] FAIL: Test 2 - Leak detected! has_env={has_env}, has_ssh={has_ssh}, has_pem={has_pem}, has_app={has_app}")

        # ---------------------------------------------------------------------
        # TEST 3: Validation: If agent touches .env, raise error and abort checkpoint
        # ---------------------------------------------------------------------
        total_count += 1
        print("\n[TEST 3] Testing validation check when agent touches sensitive files...")
        
        sensitive_test_cases = [
            (".env", "Agent touched sensitive file: .env. Add it to .gitignore or exclude it from the workspace."),
            (".env.local", "Agent touched sensitive file: .env.local. Add it to .gitignore or exclude it from the workspace."),
            ("secrets/id_rsa", "Agent touched sensitive file: id_rsa. Add it to .gitignore or exclude it from the workspace."),
            ("private.pem", "Agent touched sensitive file: private.pem. Add it to .gitignore or exclude it from the workspace."),
            ("server.key", "Agent touched sensitive file: server.key. Add it to .gitignore or exclude it from the workspace."),
            ("credentials.json", "Agent touched sensitive file: credentials.json. Add it to .gitignore or exclude it from the workspace."),
            ("config/serviceAccountKey.json", "Agent touched sensitive file: serviceAccountKey.json. Add it to .gitignore or exclude it from the workspace."),
            (".aws/credentials", "Agent touched sensitive file: credentials. Add it to .gitignore or exclude it from the workspace."),
            ("database.sqlite", "Agent touched sensitive file: database.sqlite. Add it to .gitignore or exclude it from the workspace."),
            ("app.db", "Agent touched sensitive file: app.db. Add it to .gitignore or exclude it from the workspace."),
        ]

        all_sens_passed = True
        for filepath, expected_err in sensitive_test_cases:
            ok, h, err_msg = _ensure_git_checkpoint(str(ws_path), turn_num=2, touched_files=[filepath])
            if ok or err_msg != expected_err:
                print(f"  [-] Validation failed for '{filepath}': got ok={ok}, err='{err_msg}' (expected: '{expected_err}')")
                all_sens_passed = False
            else:
                print(f"  [+] Correctly blocked sensitive file '{filepath}':\n      -> \"{err_msg}\"")

        if all_sens_passed:
            print("[+] PASS: Test 3 - All sensitive file patterns blocked before checkpoint with exact error message.")
            passed_count += 1
        else:
            print("[-] FAIL: Test 3 - Sensitive file validation failed.")

        # ---------------------------------------------------------------------
        # TEST 4: Modifying regular file in subsequent turn stages only that file
        # ---------------------------------------------------------------------
        total_count += 1
        print("\n[TEST 4] Modifying regular file in subsequent turn...")
        utils_file = ws_path / "src" / "utils.py"
        utils_file.write_text("def helper(): return 42\n", encoding="utf-8")
        
        new_init2, commit_h2, err2 = _ensure_git_checkpoint(str(ws_path), turn_num=2, touched_files=["src/utils.py"])
        show_proc2 = subprocess.run(
            ["git", "show", "HEAD", "--stat", "--name-only"],
            cwd=str(ws_path),
            capture_output=True,
            text=True,
        )
        commit2_output = show_proc2.stdout
        print(f"  Git commit 2 stat output:\n{commit2_output.strip()}")

        if commit_h2 and not err2 and "src/utils.py" in commit2_output and ".env" not in commit2_output:
            print("[+] PASS: Test 4 - Subsequent checkpoint commit successfully staged ONLY src/utils.py.")
            passed_count += 1
        else:
            print(f"[-] FAIL: Test 4 - Subsequent turn failed: commit_h2={commit_h2}, err2={err2}")

    print("\n================================================================================")
    print(f"        GIT CHECKPOINT VERIFICATION SUMMARY: {passed_count}/{total_count} PASSED             ")
    print("================================================================================\n")
    return passed_count == total_count


if __name__ == "__main__":
    success = run_verification()
    sys.exit(0 if success else 1)
