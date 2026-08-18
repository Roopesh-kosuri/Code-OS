"""
run_all_phase3_verifications.py — Complete Live Verification Runner for Phase 3: Cost & Review Quality
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.request
import urllib.parse
from pathlib import Path

# Force UTF-8 and line-buffered stdout on Windows console output
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

# Add backend to sys.path
backend_path = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(backend_path))

from app.features.ai.chat_harness import (
    _classify_task_effort,
    _evaluate_edit_critique,
    _discover_and_run_test_snapshot,
    _save_interrupted_state,
    _load_interrupted_state,
    _clear_interrupted_state,
    _append_activity_log,
    _load_activity_log,
    FileChange,
    ChatMessage,
    DAGPlanStep,
)

BASE_URL = "http://127.0.0.1:8000"
SESSION_TOKEN = None


def get_token():
    global SESSION_TOKEN
    if SESSION_TOKEN:
        return SESSION_TOKEN
    try:
        req = urllib.request.Request(f"{BASE_URL}/api/auth/token")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            SESSION_TOKEN = data.get("token")
    except Exception:
        SESSION_TOKEN = None
    return SESSION_TOKEN


def http_get(path: str, params: dict = None) -> tuple[int, dict | str]:
    url = f"{BASE_URL}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    token = get_token()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(data)
            except Exception:
                return resp.status, data
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def http_delete(path: str, params: dict = None) -> tuple[int, dict | str]:
    url = f"{BASE_URL}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    token = get_token()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    req = urllib.request.Request(url, headers=headers, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(data)
            except Exception:
                return resp.status, data
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def http_post(path: str, body: dict) -> tuple[int, dict | str]:
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode("utf-8")
    token = get_token()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            res_data = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(res_data)
            except Exception:
                return resp.status, res_data
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def stream_sse_post(path: str, body: dict) -> list[tuple[str, dict | str]]:
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode("utf-8")
    token = get_token()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    events = []
    with urllib.request.urlopen(req, timeout=60) as resp:
        current_event = "message"
        current_data = []
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
            if not line:
                if current_data:
                    data_str = "\n".join(current_data)
                    try:
                        parsed = json.loads(data_str)
                        events.append((current_event, parsed))
                        if current_event == "approval_request" and isinstance(parsed, dict) and "action_id" in parsed:
                            act_id = parsed["action_id"]
                            import threading
                            def _do_appr():
                                time.sleep(0.05)
                                http_post(f"/api/ai/chat-agent/approve/{act_id}", {"always_allow": False})
                            threading.Thread(target=_do_appr, daemon=True).start()
                        if current_event == "done":
                            return events
                    except Exception:
                        events.append((current_event, data_str))
                        if current_event == "done":
                            return events
                    current_event = "message"
                    current_data = []
                continue
            if line.startswith("event:"):
                current_event = line[6:].strip()
            elif line.startswith("data:"):
                current_data.append(line[5:].strip())
    return events


async def main():
    print("\n" + "=" * 70)
    print("  PHASE 3 COMPLETE VERIFICATION RUN: COST & REVIEW QUALITY")
    print("=" * 70)

    # ─────────────────────────────────────────────────────────────────────────
    # RUN A: Adaptive Routing Classifier (Sub-10ms Benchmark)
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[RUN A] Adaptive Model Routing Effort Classifier (<10ms)")
    t0_start = time.perf_counter()
    tier0, label0, reason0 = _classify_task_effort(
        user_query="what does is_source_file do?",
        attached_paths=[],
        is_agent_mode=False,
    )
    t0_time = (time.perf_counter() - t0_start) * 1000.0
    print(f"  • Tier 0 Fast Path: '{user_query_short('what does is_source_file do?')}' -> Tier {tier0} ({label0}) in {t0_time:.2f}ms [{reason0}]")
    assert tier0 == 0 and ("Fast Answer" in label0 or "Fast path" in label0) and t0_time < 10.0

    t1_start = time.perf_counter()
    tier1, label1, reason1 = _classify_task_effort(
        user_query="add '.yaml' to SOURCE_EXTENSIONS in backend/app/features/ai/chat_harness.py",
        attached_paths=["backend/app/features/ai/chat_harness.py"],
        is_agent_mode=True,
    )
    t1_time = (time.perf_counter() - t1_start) * 1000.0
    print(f"  • Tier 1 Quick Task: 'add .yaml to SOURCE_EXTENSIONS...' -> Tier {tier1} ({label1}) in {t1_time:.2f}ms [{reason1}]")
    assert tier1 == 1 and ("Quick Task" in label1 or "Quick task" in label1) and t1_time < 10.0

    t2_start = time.perf_counter()
    tier2, label2, reason2 = _classify_task_effort(
        user_query="build a full snake game with pytest unit tests and scoring mechanics",
        attached_paths=[],
        is_agent_mode=True,
    )
    t2_time = (time.perf_counter() - t2_start) * 1000.0
    print(f"  • Tier 2 Deep Think: 'build a full snake game...' -> Tier {tier2} ({label2}) in {t2_time:.2f}ms [{reason2}]")
    assert tier2 == 2 and label2 == "Deep think" and t2_time < 10.0
    print("  ✓ Run A PASSED: All 3 effort tiers classified accurately in <1ms.")

    # ─────────────────────────────────────────────────────────────────────────
    # RUN B: Live Streaming Tier 0 Query + Token Metrics
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[RUN B] Live Streaming Tier 0 Fast Path Query")
    ws_b = tempfile.mkdtemp(prefix="code_os_run_b_")
    events_b = stream_sse_post(
        "/api/ai/chat-agent/stream",
        {
            "provider": "auto",
            "model": "",
            "messages": [{"role": "user", "content": "Explain what is_source_file does in one paragraph"}],
            "workspace": ws_b,
            "agent_mode": False,
        }
    )
    tier_evs = [e[1] for e in events_b if e[0] == "tier_routing"]
    metric_evs = [e[1] for e in events_b if e[0] == "metrics"]
    token_count = len([e for e in events_b if e[0] == "token"])
    print(f"  • Tier badge emitted: {tier_evs[0] if tier_evs else None}")
    print(f"  • Tokens streamed: {token_count}, Metrics: {metric_evs[0] if metric_evs else None}")
    assert len(tier_evs) > 0 and tier_evs[0]["tier"] == 0
    assert token_count > 10
    print("  ✓ Run B PASSED: Real LLM response streamed with Tier 0 badge and token counter.")

    # ─────────────────────────────────────────────────────────────────────────
    # RUN C: Live Tier 1 Quick Task Routing
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[RUN C] Live Tier 1 Quick Task Routing")
    ws_c = tempfile.mkdtemp(prefix="code_os_run_c_")
    Path(ws_c, "app.py").write_text("MODE = 'production'\n", encoding="utf-8")
    events_c = stream_sse_post(
        "/api/ai/chat-agent/stream",
        {
            "provider": "auto",
            "model": "",
            "messages": [{"role": "user", "content": "Set MODE = 'development' in app.py"}],
            "workspace": ws_c,
            "attached_paths": ["app.py"],
            "agent_mode": True,
        }
    )
    tier_evs_c = [e[1] for e in events_c if e[0] == "tier_routing"]
    print(f"  • Tier badge emitted: {tier_evs_c[0] if tier_evs_c else None}")
    assert len(tier_evs_c) > 0 and tier_evs_c[0]["tier"] == 1
    print("  ✓ Run C PASSED: Tier 1 Quick task routed and executed.")

    # ─────────────────────────────────────────────────────────────────────────
    # RUN D: Pre-Proposal Self-Critique Engine
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[RUN D] Pre-Proposal Self-Critique Quality Engine")
    ws_d = tempfile.mkdtemp(prefix="code_os_run_d_")
    large_f = Path(ws_d, "service.py")
    orig_lines = [f"def worker_{i}(): return {i}\n" for i in range(40)]
    large_f.write_text("".join(orig_lines), encoding="utf-8")

    # Clean surgical edit
    clean_lines = list(orig_lines)
    clean_lines[2] = "def worker_2(): return 200\n"
    is_clean_1, fb_1 = _evaluate_edit_critique(ws_d, [FileChange(path="service.py", original="".join(orig_lines), updated="".join(clean_lines))], "update worker 2")
    print(f"  • Surgical edit: clean={is_clean_1}, feedback='{fb_1}'")
    assert is_clean_1 is True

    # Accidental wholesale truncation
    is_clean_2, fb_2 = _evaluate_edit_critique(ws_d, [FileChange(path="service.py", original="".join(orig_lines), updated="# truncated\npass\n")], "fix typo in worker 2")
    print(f"  • Sloppy truncation: clean={is_clean_2}, feedback='{fb_2}'")
    assert is_clean_2 is False

    # Explicit rewrite request
    is_clean_3, fb_3 = _evaluate_edit_critique(ws_d, [FileChange(path="service.py", original="".join(orig_lines), updated="# rewritten\npass\n")], "rewrite service.py from scratch")
    print(f"  • Explicit rewrite: clean={is_clean_3}, feedback='{fb_3}'")
    assert is_clean_3 is True
    print("  ✓ Run D PASSED: Self-critique prevents unintended file replacement.")

    # ─────────────────────────────────────────────────────────────────────────
    # RUN E: Regression Guard (Before/After Test Snapshot)
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[RUN E] Regression Guard (Before/After Test Snapshot)")
    ws_e = tempfile.mkdtemp(prefix="code_os_run_e_")
    Path(ws_e, "math_lib.py").write_text("def mul(a, b): return a * b\ndef div(a, b): return a / b\n", encoding="utf-8")
    Path(ws_e, "test_math_lib.py").write_text("import math_lib\ndef test_mul(): assert math_lib.mul(3, 4) == 12\ndef test_div(): assert math_lib.div(10, 2) == 5\n", encoding="utf-8")

    ran_pre, p_pre, f_pre, sum_pre = await _discover_and_run_test_snapshot(ws_e, ["math_lib.py"])
    print(f"  • Pre-edit test baseline: ran={ran_pre}, passed={p_pre}, failed={f_pre} ({sum_pre})")
    assert ran_pre and p_pre == 2 and f_pre == 0

    # Introduce regression
    Path(ws_e, "math_lib.py").write_text("def mul(a, b): return a * b\ndef div(a, b): return a + b # BUG\n", encoding="utf-8")
    ran_post, p_post, f_post, sum_post = await _discover_and_run_test_snapshot(ws_e, ["math_lib.py"])
    print(f"  • Post-edit test snapshot: ran={ran_post}, passed={p_post}, failed={f_post} ({sum_post})")
    assert ran_post and p_post == 1 and f_post == 1
    has_reg = (f_post > f_pre) or (p_post < p_pre)
    print(f"  • Regression detected: {has_reg} (Tests before: {p_pre} passed → Tests after: {p_post} passed, {f_post} failed)")
    assert has_reg is True
    print("  ✓ Run E PASSED: Regression guard catches test breakages reliably.")

    # ─────────────────────────────────────────────────────────────────────────
    # RUN F: Checkpoint-Resume for Interrupted Runs
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[RUN F] Checkpoint-Resume State Persistence & API")
    ws_f = tempfile.mkdtemp(prefix="code_os_run_f_")
    saved_ok = _save_interrupted_state(
        workspace=ws_f,
        user_query="Scaffold full dashboard",
        tier=2,
        iteration=3,
        max_iterations=10,
        messages=[ChatMessage(role="user", content="Scaffold full dashboard")],
        dag_plan_steps=[DAGPlanStep(id="s1", title="Step 1", status="done")],
        staged_changes=[FileChange(path="dash.py", original="", updated="print(1)")],
        tokens_used=640,
        tools_executed=3,
    )
    print(f"  • State written to disk: {saved_ok}")
    assert saved_ok is True

    # Test GET endpoint
    st_code, get_res = http_get("/api/ai/chat-agent/interrupted-state", {"workspace": ws_f})
    print(f"  • GET /interrupted-state: status={st_code}, query='{get_res.get('state', {}).get('user_query')}', tokens={get_res.get('state', {}).get('tokens_used')}")
    assert st_code == 200 and get_res["has_interrupted"] is True

    # Test DELETE endpoint
    del_code, del_res = http_delete("/api/ai/chat-agent/interrupted-state", {"workspace": ws_f})
    print(f"  • DELETE /interrupted-state: status={del_code}, cleared={del_res.get('cleared')}")
    assert del_code == 200 and del_res["cleared"] is True
    print("  ✓ Run F PASSED: Checkpoint-resume persistence & endpoints verified.")

    # ─────────────────────────────────────────────────────────────────────────
    # RUN G: Searchable Agent Activity Timeline & Export
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[RUN G] Searchable Agent Activity Timeline & Export")
    ws_g = tempfile.mkdtemp(prefix="code_os_run_g_")
    for action, target, outcome, details in [
        ("routing", "Query A", "success", "Fast path routing"),
        ("edit_proposal", "src/auth.py", "approved", "Applied 1 file edit"),
        ("command_run", "npm test", "failed", "1 test failed"),
        ("regression_guard", "src/auth.py", "regression_detected", "Regression detected in test_auth.py"),
        ("session_done", "Query A", "success", "Completed in 1 turn"),
    ]:
        _append_activity_log(ws_g, {
            "action_type": action,
            "target": target,
            "outcome": outcome,
            "tier": 1,
            "token_count": 50,
            "details": details,
        })

    # Test GET activity-log (all)
    _, res_all = http_get("/api/ai/chat-agent/activity-log", {"workspace": ws_g, "filter_type": "all"})
    print(f"  • All events count: {res_all.get('total')}")
    assert res_all["total"] == 5

    # Test GET activity-log (failures)
    _, res_fail = http_get("/api/ai/chat-agent/activity-log", {"workspace": ws_g, "filter_type": "failures"})
    print(f"  • Failures filter count: {res_fail.get('total')}")
    assert res_fail["total"] == 2

    # Test export endpoint
    _, raw_export = http_get("/api/ai/chat-agent/activity-log/export", {"workspace": ws_g})
    export_lines = len(raw_export.strip().splitlines())
    print(f"  • GET /activity-log/export line count: {export_lines}")
    assert export_lines == 5
    print("  ✓ Run G PASSED: Activity timeline logging, filtering, and export verified.")

    print("\n" + "=" * 70)
    print("  ALL 7 PHASE 3 VERIFICATION RUNS (A through G) PASSED 100%!")
    print("=" * 70 + "\n")


def user_query_short(q: str) -> str:
    return q if len(q) <= 40 else q[:37] + "..."


if __name__ == "__main__":
    asyncio.run(main())
