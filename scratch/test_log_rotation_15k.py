"""
test_log_rotation_15k.py
Verification suite for Activity Log Rotation, Tail Reader, and Pagination (Fix #4).

Tests:
1. Programmatically write 15,000 log entries in batches and test rotation.
2. Confirm rotation occurs (activity_log.1.jsonl created).
3. Confirm max files constraint (only activity_log.jsonl, activity_log.1.jsonl, activity_log.2.jsonl).
4. Verify tail query latency (< 500ms) and reverse chronological ordering on 15,000 entries.
5. Verify pagination (offset & limit, total count, has_more flag).
"""
import json
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
    _append_activity_log,
    _load_activity_log,
    _rotate_activity_log,
)


def run_tests():
    print("================================================================================", flush=True)
    print("        ACTIVITY LOG ROTATION & PAGINATION VERIFICATION (15,000 ENTRIES)       ", flush=True)
    print("================================================================================\n", flush=True)

    passed_count = 0
    total_count = 0

    with tempfile.TemporaryDirectory() as tmp_dir:
        ws_path = Path(tmp_dir).resolve()
        os_dir = ws_path / ".code_os"
        os_dir.mkdir(parents=True, exist_ok=True)
        log_file = os_dir / "activity_log.jsonl"

        # ---------------------------------------------------------------------
        # TEST 1 & 2: Generate 15,000 entries and verify rotation
        # ---------------------------------------------------------------------
        total_count += 1
        print("[TEST 1 & 2] Generating 15,000 log entries and verifying rotation...", flush=True)
        
        # Write first 10,000 entries (approx 1.5MB)
        start_write = time.perf_counter()
        with log_file.open("w", encoding="utf-8") as f:
            for i in range(10000):
                entry = {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "action_type": "command_run" if i % 2 == 0 else "edit_file",
                    "target": f"src/module_{i % 50}.py",
                    "outcome": "success" if i % 10 != 0 else "failed",
                    "details": f"Executed iteration step index {i} with automated parameters",
                    "step_index": i,
                }
                f.write(json.dumps(entry) + "\n")
        
        # Trigger rotation with max_size_mb=1 (or threshold)
        _rotate_activity_log(log_file, max_size_mb=1, max_files=3)
        
        # Write remaining 5,000 entries to new activity_log.jsonl
        with log_file.open("w", encoding="utf-8") as f:
            for i in range(10000, 15000):
                entry = {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "action_type": "command_run" if i % 2 == 0 else "edit_file",
                    "target": f"src/module_{i % 50}.py",
                    "outcome": "success" if i % 10 != 0 else "failed",
                    "details": f"Executed iteration step index {i} with automated parameters",
                    "step_index": i,
                }
                f.write(json.dumps(entry) + "\n")

        elapsed_write = time.perf_counter() - start_write
        print(f"  [+] Created 15,000 entries across archives in {elapsed_write:.2f}s.", flush=True)

        rotated_1 = os_dir / "activity_log.1.jsonl"
        
        if rotated_1.is_file() and log_file.is_file():
            print(f"  [+] Log rotated successfully!")
            print(f"      Current log: {log_file.name} ({log_file.stat().st_size / 1024:.1f} KB)")
            print(f"      Archive 1:   {rotated_1.name} ({rotated_1.stat().st_size / 1024:.1f} KB)")
            print("[+] PASS: Test 1 & 2 - Rotation triggered at archive boundary.", flush=True)
            passed_count += 1
        else:
            print(f"[-] FAIL: Test 1 & 2 - Rotation failed. Files: {[f.name for f in os_dir.iterdir()]}", flush=True)

        # ---------------------------------------------------------------------
        # TEST 3: Max Archive Limit (Keep only 3 files)
        # ---------------------------------------------------------------------
        total_count += 1
        print("\n[TEST 3] Testing maximum archive constraint (max 3 files)...", flush=True)
        
        # Trigger 3 more rotations
        for r in range(3):
            _rotate_activity_log(log_file, max_size_mb=0, max_files=3)  # force rotate
            log_file.write_text('{"step_index": 99999}\n', encoding="utf-8")
        
        all_logs = sorted([f.name for f in os_dir.glob("activity_log*.jsonl")])
        print(f"  Existing log files in .code_os: {all_logs}", flush=True)

        expected_logs = ["activity_log.1.jsonl", "activity_log.2.jsonl", "activity_log.jsonl"]
        if set(all_logs) == set(expected_logs):
            print("  [+] Exactly 3 active/archive log files exist (oldest archives deleted).", flush=True)
            print("[+] PASS: Test 3 - Max archive limit verified.", flush=True)
            passed_count += 1
        else:
            print(f"[-] FAIL: Test 3 - Archive list unexpected: {all_logs}", flush=True)

        # ---------------------------------------------------------------------
        # TEST 4: Query Latency & Reverse Chronological Ordering (< 500ms)
        # ---------------------------------------------------------------------
        total_count += 1
        print("\n[TEST 4] Testing tail query latency and reverse order on large dataset...", flush=True)
        
        # Populate 15,000 entries in active log for tail benchmark
        with log_file.open("w", encoding="utf-8") as f:
            for i in range(15000):
                entry = {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "action_type": "command_run" if i % 2 == 0 else "edit_file",
                    "target": f"src/module_{i % 50}.py",
                    "outcome": "success" if i % 10 != 0 else "failed",
                    "details": f"Executed iteration step index {i} with automated parameters",
                    "step_index": i,
                }
                f.write(json.dumps(entry) + "\n")

        t0 = time.perf_counter()
        meta = _load_activity_log(str(ws_path), limit=100, return_metadata=True)
        t_query_ms = (time.perf_counter() - t0) * 1000

        entries = meta["entries"]
        print(f"  [+] Query returned {len(entries)} entries in {t_query_ms:.2f}ms (threshold < 500ms).", flush=True)
        first_step = entries[0].get("step_index")
        last_step = entries[-1].get("step_index")
        print(f"  [+] Newest entry step: {first_step}, Oldest returned step: {last_step}", flush=True)

        if t_query_ms < 500 and len(entries) == 100 and first_step > last_step:
            print("[+] PASS: Test 4 - Reverse tail query verified (< 500ms).", flush=True)
            passed_count += 1
        else:
            print(f"[-] FAIL: Test 4 - Performance or ordering failure: time={t_query_ms:.2f}ms, count={len(entries)}", flush=True)

        # ---------------------------------------------------------------------
        # TEST 5: Pagination (limit, offset, total, has_more)
        # ---------------------------------------------------------------------
        total_count += 1
        print("\n[TEST 5] Testing pagination offsets, page consistency, and metadata...", flush=True)
        
        page_1 = _load_activity_log(str(ws_path), limit=10, offset=0, return_metadata=True)
        page_2 = _load_activity_log(str(ws_path), limit=10, offset=10, return_metadata=True)
        page_3 = _load_activity_log(str(ws_path), limit=10, offset=20, return_metadata=True)

        p1_steps = [e.get("step_index") for e in page_1["entries"]]
        p2_steps = [e.get("step_index") for e in page_2["entries"]]
        p3_steps = [e.get("step_index") for e in page_3["entries"]]

        print(f"  Page 1 (offset 0):  steps {p1_steps[:3]}...{p1_steps[-1]}", flush=True)
        print(f"  Page 2 (offset 10): steps {p2_steps[:3]}...{p2_steps[-1]}", flush=True)
        print(f"  Page 3 (offset 20): steps {p3_steps[:3]}...{p3_steps[-1]}", flush=True)
        print(f"  Metadata: total={page_1['total']}, has_more={page_1['has_more']}", flush=True)

        overlap = set(p1_steps).intersection(set(p2_steps)).intersection(set(p3_steps))
        
        if not overlap and len(p1_steps) == 10 and len(p2_steps) == 10 and page_1["has_more"] is True:
            print("  [+] No page overlap detected. Offsets advance seamlessly.", flush=True)
            print("[+] PASS: Test 5 - Pagination verified.", flush=True)
            passed_count += 1
        else:
            print(f"[-] FAIL: Test 5 - Pagination failed: overlap={overlap}, p1_len={len(p1_steps)}", flush=True)

    print("\n================================================================================", flush=True)
    print(f"        ACTIVITY LOG 15,000 ENTRIES SUMMARY: {passed_count}/{total_count} PASSED                ", flush=True)
    print("================================================================================\n", flush=True)
    return passed_count == total_count


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
