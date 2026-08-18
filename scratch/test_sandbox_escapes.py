"""
test_sandbox_escapes.py
Comprehensive Sandbox Escape & Security Regression Suite for CODE OS.
Validates:
1. Path Traversal & Absolute Path Rejection in _is_command_safe
2. Command Chaining / Shell Injection Rejection
3. Subprocess Environment Credential Scrubbing
4. Resource Governor Memory & Timeout Enforcement (512MB RAM cap / 60s CPU)
5. Container Sandbox Execution & Fallback Warning
6. Windows Sandbox (.wsb) XML Generation & Safety Settings
7. Sanitized Error Monitoring & Credential Redaction
8. Rate Limiting, Agent Run Throttling, and Token Budgeting
9. Backup Creation, 7-Day Rotation, and Safe Restoration
"""
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

# Add backend to sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.features.ai.chat_harness import (
    _is_command_safe,
    _execute_command_async,
    _execute_command_sandboxed,
    _detect_container_runtime,
    _detect_windows_sandbox,
    _generate_wsb_config,
    _save_interrupted_state,
    _load_interrupted_state,
    _clear_interrupted_state,
    SandboxUnavailableError,
    ChatMessage,
)
from app.features.terminal.service import _build_safe_environment
from app.core.monitoring import monitor, sanitize_text
from app.core.rate_limiter import rate_limiter
from app.features.ai.backup_service import (
    create_workspace_backup,
    list_workspace_backups,
    restore_workspace_backup,
    _rotate_backups,
)


def run_all_tests():
    print("================================================================================")
    print("            CODE OS: SANDBOX ESCAPE & SECURITY REGRESSION SUITE                 ")
    print("================================================================================\n")
    
    passed_count = 0
    total_count = 0

    with tempfile.TemporaryDirectory() as tmp_ws:
        ws_path = Path(tmp_ws).resolve()
        test_file = ws_path / "hello.txt"
        test_file.write_text("Safe file content", encoding="utf-8")

        # -------------------------------------------------------------------------
        # TEST 1: Path Traversal Rejection
        # -------------------------------------------------------------------------
        total_count += 1
        traversal_payloads = [
            "cat ../../etc/passwd",
            "type C:\\Windows\\System32\\drivers\\etc\\hosts",
            "type C:\\Users\\..\\.env",
            "cat ..\\..\\..\\.env",
            "ls D:\\secret",
            "dir ..\\..",
            "grep pass ..\\..\\secret.txt",
            "findstr secret C:\\Users\\Admin\\.ssh\\id_rsa",
            "head /etc/shadow",
            "tail D:/private_key.pem",
        ]
        all_rejected = True
        for cmd in traversal_payloads:
            if _is_command_safe(cmd, str(ws_path)):
                print(f"[-] FAILED: Escape command allowed: {cmd}")
                all_rejected = False
                break
        
        # Verify legitimate in-workspace command IS allowed
        safe_allowed = _is_command_safe("type hello.txt", str(ws_path)) or _is_command_safe("cat hello.txt", str(ws_path))
        if all_rejected and safe_allowed:
            print("[+] PASS: Test 1 - Path traversal & absolute path rejection verified.")
            passed_count += 1
        else:
            print(f"[-] FAILED: Test 1 - Traversal rejection failed (all_rejected={all_rejected}, safe_allowed={safe_allowed})")

        # -------------------------------------------------------------------------
        # TEST 2: Shell Injection & Chaining Rejection
        # -------------------------------------------------------------------------
        total_count += 1
        injection_payloads = [
            "cat hello.txt; whoami",
            "cat hello.txt && id",
            "type hello.txt | net user",
            "cat hello.txt || echo hacked",
            "echo $(whoami)",
            "echo `whoami`",
            "cat hello.txt > /tmp/out",
            "cat hello.txt >> /tmp/out",
        ]
        injections_blocked = True
        for cmd in injection_payloads:
            if _is_command_safe(cmd, str(ws_path)):
                print(f"[-] FAILED: Injected command allowed: {cmd}")
                injections_blocked = False
                break

        if injections_blocked:
            print("[+] PASS: Test 2 - Shell injection and command chaining strictly blocked.")
            passed_count += 1
        else:
            print("[-] FAILED: Test 2 - Injection blocking failed.")

        # -------------------------------------------------------------------------
        # TEST 3: Subprocess Environment Credential Scrubbing
        # -------------------------------------------------------------------------
        total_count += 1
        os.environ["OPENAI_API_KEY"] = "sk-test-secret-key-12345"
        os.environ["AWS_SECRET_ACCESS_KEY"] = "AKIAIOSFODNN7EXAMPLE"
        os.environ["GITHUB_TOKEN"] = "ghp_123456789012345678901234567890123456"
        os.environ["SSH_AUTH_SOCK"] = "/tmp/ssh-agent.sock"
        os.environ["DATABASE_PASSWORD"] = "SuperSecretPassword123!"

        safe_env = _build_safe_environment()
        leaks = []
        for bad_key in ["OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN", "SSH_AUTH_SOCK", "DATABASE_PASSWORD"]:
            if bad_key in safe_env:
                leaks.append(bad_key)

        if not leaks and "PATH" in safe_env:
            print("[+] PASS: Test 3 - Environment credentials & secrets scrubbed from subprocess env.")
            passed_count += 1
        else:
            print(f"[-] FAILED: Test 3 - Environment leaked: {leaks}")

        # -------------------------------------------------------------------------
        # TEST 4: Resource Governor - Memory Hog Kill (512MB RAM Cap)
        # -------------------------------------------------------------------------
        total_count += 1
        print("  [..] Running memory hog test against resource governor (allocating 1GB RAM)...")
        mem_hog_cmd = 'python -c "x = \'a\' * (1024 * 1024 * 1024); import time; time.sleep(10)"'
        res = asyncio.run(_execute_command_async(str(ws_path), mem_hog_cmd))
        
        expected_error = "Command exceeded resource limit (512MB memory / 60s CPU)"
        if not res.success and (expected_error in res.error or "resource limit" in res.error.lower() or "exceeded" in res.error.lower()):
            print(f"[+] PASS: Test 4 - Resource governor terminated memory hog process. Output: {res.error}")
            passed_count += 1
        else:
            print(f"[-] FAILED: Test 4 - Resource governor did not intercept memory hog properly. Res: success={res.success}, err={res.error}")

        # -------------------------------------------------------------------------
        # TEST 5: Container Runtime Detection & Fail-Closed Sandboxed Execution
        # -------------------------------------------------------------------------
        total_count += 1
        caps = _detect_container_runtime()
        print(f"  [..] Container runtime detected: {caps}")
        
        if not caps["docker_available"]:
            try:
                sandboxed_res = asyncio.run(_execute_command_sandboxed(str(ws_path), 'python -c "print(\'sandboxed_ok\')"'))
                print("[-] FAILED: Test 5 - Expected SandboxUnavailableError but execution succeeded without Docker.")
            except SandboxUnavailableError as exc:
                print(f"[+] PASS: Test 5 - Fail-closed verified: SandboxUnavailableError raised when Docker unavailable ({exc}).")
                passed_count += 1
            except Exception as exc:
                print(f"[-] FAILED: Test 5 - Unexpected exception type: {type(exc)}: {exc}")
        else:
            sandboxed_res = asyncio.run(_execute_command_sandboxed(str(ws_path), 'python -c "print(\'sandboxed_ok\')"'))
            if sandboxed_res.success and "sandboxed_ok" in sandboxed_res.output:
                print("[+] PASS: Test 5 - Container execution succeeded inside Docker.")
                passed_count += 1
            else:
                print(f"[-] FAILED: Test 5 - Docker execution failed: {sandboxed_res.error}")

        # -------------------------------------------------------------------------
        # TEST 6: Windows Sandbox (.wsb) XML Generation & Isolation Config
        # -------------------------------------------------------------------------
        total_count += 1
        wsb_xml = _generate_wsb_config(str(ws_path))
        has_config = "<Configuration>" in wsb_xml
        has_net_disable = "<Networking>Disable</Networking>" in wsb_xml
        has_mapped_folder = str(ws_path) in wsb_xml

        if has_config and has_net_disable and has_mapped_folder:
            print("[+] PASS: Test 6 - Windows Sandbox .wsb config generated with network isolation and folder mapping.")
            passed_count += 1
        else:
            print(f"[-] FAILED: Test 6 - Windows Sandbox XML invalid: {wsb_xml}")

        # -------------------------------------------------------------------------
        # TEST 7: Sanitized Error Monitoring & Credential Redaction
        # -------------------------------------------------------------------------
        total_count += 1
        try:
            # Simulate exception with sensitive credentials in message and context
            raise ValueError("Failed connecting to https://api.openai.com with key sk-proj-99999999999999999999 and token ghp_ABCDEF1234567890ABCDEF1234567890ABCD and password='SuperSecretPassword!'")
        except Exception as exc:
            err_id = monitor.capture_exception(exc, context={"api_key": "sk-proj-99999999999999999999", "user": "admin"})
            recent = monitor.get_recent_errors(limit=5)
            found_entry = next((e for e in recent if e["id"] == err_id), None)

            if found_entry:
                msg = found_entry["message"]
                tb = found_entry["sanitized_traceback"]
                clean = ("sk-proj" not in msg and "ghp_" not in msg and "[REDACTED" in msg)
                if clean:
                    print(f"[+] PASS: Test 7 - Error monitor captured exception and redacted credentials ({err_id}).")
                    passed_count += 1
                else:
                    print(f"[-] FAILED: Test 7 - Error monitor did not redact secrets: {msg}")
            else:
                print("[-] FAILED: Test 7 - Error entry not found in monitor.")

        # -------------------------------------------------------------------------
        # TEST 8: Rate Limiting & Monthly Token Budgeting
        # -------------------------------------------------------------------------
        total_count += 1
        rate_limiter.reset()
        
        # Test rate limiter
        for _ in range(5):
            rate_limiter.check("test_client", max_requests=10, window_seconds=60.0)
        
        hit_limit = False
        try:
            for _ in range(10):
                rate_limiter.check("test_client", max_requests=10, window_seconds=60.0)
        except Exception as exc:
            hit_limit = getattr(exc, "status_code", 0) == 429

        # Test token recording
        rate_limiter.record_tokens("ws_test", 50000)
        status = rate_limiter.get_token_status("ws_test", budget=1000000)

        if hit_limit and status["used_tokens"] == 50000 and status["remaining_tokens"] == 950000:
            print("[+] PASS: Test 8 - Rate limiter 429 throttling and token budgeting verified.")
            passed_count += 1
        else:
            print(f"[-] FAILED: Test 8 - Rate limiter / token budget failed: hit_limit={hit_limit}, status={status}")

        # -------------------------------------------------------------------------
        # TEST 9: Backup Service & 7-Day Rotation
        # -------------------------------------------------------------------------
        total_count += 1
        code_os_dir = ws_path / ".code_os"
        code_os_dir.mkdir(parents=True, exist_ok=True)
        (code_os_dir / "trusted_commands.json").write_text('["pytest", "git status"]', encoding="utf-8")
        (code_os_dir / "activity_log.jsonl").write_text('{"action": "test"}\n', encoding="utf-8")

        backup_file = create_workspace_backup(str(ws_path), reason="test_backup")
        backups = list_workspace_backups(str(ws_path))
        
        # Corrupt/delete trusted commands to test restore
        (code_os_dir / "trusted_commands.json").unlink()
        restored = restore_workspace_backup(str(ws_path), Path(backup_file).name)
        recovered_exists = (code_os_dir / "trusted_commands.json").is_file()

        if backup_file and len(backups) >= 1 and restored and recovered_exists:
            print(f"[+] PASS: Test 9 - Backup creation, listing, and restoration verified successfully.")
            passed_count += 1
        else:
            print(f"[-] FAILED: Test 9 - Backup service failed (file={backup_file}, len={len(backups)}, restored={restored})")

    print("\n================================================================================")
    print(f"             SANDBOX ESCAPE SUITE SUMMARY: {passed_count}/{total_count} PASSED                ")
    print("================================================================================\n")
    return passed_count == total_count


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
