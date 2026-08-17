"""
Part 2 of Live Measured Verification Suite:
- V4: Ambiguity Guard (ask_user interactive question card)
- V5: Honest Failure on Edit Mismatch (first differing line diagnostic)
- V6: RAG Symbol Search (budgeted identifier search + definition snippet window)
- V7: Dynamic DAG Re-planning on tool failure
"""
import asyncio
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, r"d:\HTML\CODE OS\backend")

WORKSPACE = r"d:\HTML\CODE OS"
SESSION_TOKEN_FILE = os.path.expanduser("~/.code-os/session_token")
BASE_URL = "http://127.0.0.1:8000"


def get_token() -> str:
    if os.path.exists(SESSION_TOKEN_FILE):
        return open(SESSION_TOKEN_FILE).read().strip()
    return ""


async def test_v4_ambiguity_card():
    print("\n" + "="*70, flush=True)
    print("RUNNING V4: Ambiguity Guard (ask_user interactive clarification)", flush=True)
    print("="*70, flush=True)
    
    from app.features.ai.chat_harness import (
        PendingUserResponse,
        _pending_user_responses,
        respond_to_user_question,
        _sse_ask_user,
    )
    
    action_id = f"test-ask-{int(time.time())}"
    question = "Which color theme do you want for the portfolio?"
    options = ["Dark Minimalist", "Vibrant Cyberpunk", "Clean Light"]
    
    pending = PendingUserResponse(
        action_id=action_id,
        question=question,
        options=options,
    )
    _pending_user_responses[action_id] = pending
    
    # 1. Verify SSE event payload
    sse_event = _sse_ask_user(action_id, question, options)
    print(f"[*] SSE ask_user event:\n{sse_event}", flush=True)
    
    # 2. Simulate user selection response via endpoint / function
    ok = respond_to_user_question(action_id, "Dark Minimalist")
    print(f"[*] Response submission result: {ok}, chosen option: '{pending.selected_option}'", flush=True)
    
    success = ok and pending.selected_option == "Dark Minimalist" and pending.event.is_set()
    print(f"[+] V4 Result: {'PASSED' if success else 'FAILED'}", flush=True)
    return success


async def test_v5_mismatch_diagnostic(tmp_path):
    print("\n" + "="*70, flush=True)
    print("RUNNING V5: Honest Failure on Edit Mismatch (First Differing Line)", flush=True)
    print("="*70, flush=True)
    
    from app.features.ai.chat_harness import _validate_smart_edit
    
    test_file = tmp_path / "sample_service.py"
    test_file.write_text(
        "class ConfigService:\n"
        "    def __init__(self):\n"
        "        self.port = 8000\n"
        "        self.debug = True\n"
        "        self.environment = 'development'\n",
        encoding="utf-8",
    )
    
    # Intentionally hallucinated original line
    hallucinated_args = {
        "path": "sample_service.py",
        "original": "        self.port = 9000\n        self.debug = True",
        "updated": "        self.port = 3000\n        self.debug = False",
    }
    
    valid, err, change = _validate_smart_edit(str(tmp_path), hallucinated_args)
    print(f"[*] Validation valid: {valid}", flush=True)
    print(f"[*] Error diagnostic:\n{err}", flush=True)
    
    success = (
        valid is False and
        change is None and
        "First differing line at line 3:" in err and
        "self.port = 8000" in err
    )
    print(f"[+] V5 Result: {'PASSED' if success else 'FAILED'}", flush=True)
    return success


async def test_v6_rag_symbol_search():
    print("\n" + "="*70, flush=True)
    print("RUNNING V6: Budgeted RAG Symbol Search & Snippet Windowing", flush=True)
    print("="*70, flush=True)
    
    from app.features.ai.chat_harness import _gather_budgeted_rag_context
    
    matches, rag_summary = await _gather_budgeted_rag_context(
        workspace=WORKSPACE,
        query="explain how _is_command_safe and SAFE_COMMAND_ALLOWLIST works in chat_harness",
        token_budget=1200,
    )
    
    print(f"[*] Semantic Matches Found: {len(matches)}", flush=True)
    for m in matches[:3]:
        print(f"    - {m.get('relative_path', m.get('path'))} (score: {m.get('score', 0):.2f})", flush=True)
    
    print(f"[*] Budgeted Grounding Snippet Preview ({len(rag_summary)} chars):\n{rag_summary[:400]}...", flush=True)
    
    success = len(rag_summary) > 50 and ("_is_command_safe" in rag_summary or "chat_harness" in rag_summary or len(matches) > 0)
    print(f"[+] V6 Result: {'PASSED' if success else 'FAILED'}", flush=True)
    return success


async def test_v7_dag_replan():
    print("\n" + "="*70, flush=True)
    print("RUNNING V7: Dynamic DAG Re-planning on Step Failure", flush=True)
    print("="*70, flush=True)
    
    from app.features.ai.chat_harness import _parse_plan_dag, _replan_on_failure, DAGPlanStep
    
    dag_text = """
[PLAN]
1. Read database configuration in backend/app/core/database.py
2. Run database migration tests (depends on 1)
3. Update connection pool size (depends on 2)
4. Verify migration results (depends on 3)
[/PLAN]
"""
    steps = _parse_plan_dag(dag_text)
    print(f"[*] Initial DAG Steps ({len(steps)}):", flush=True)
    for s in steps:
        print(f"    - {s.id}: {s.title} (depends on: {s.depends_on})", flush=True)
    
    # Simulate step 2 failure
    steps[0].status = "done"
    steps[1].status = "running"
    replanned = _replan_on_failure(steps, 1, "Connection refused: database server not responding on port 5432")
    
    print(f"[*] Replanned Steps ({len(replanned)}):", flush=True)
    for s in replanned:
        print(f"    - {s.id}: {s.title} [{s.status}]", flush=True)
    
    step_2 = next(s for s in replanned if s.id == "step_2")
    step_3 = next(s for s in replanned if s.id == "step_3")
    fix_step = next(s for s in replanned if s.id.startswith("fix_step_2"))
    
    success = (
        step_2.status == "failed" and
        step_3.status == "blocked" and
        fix_step.status == "running" and
        "Repair failure in Run database migration tests" in fix_step.title
    )
    print(f"[+] V7 Result: {'PASSED' if success else 'FAILED'}", flush=True)
    return success


async def main():
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        v4_ok = await test_v4_ambiguity_card()
        v5_ok = await test_v5_mismatch_diagnostic(Path(tmp_dir))
        v6_ok = await test_v6_rag_symbol_search()
        v7_ok = await test_v7_dag_replan()
        
        print("\n" + "="*70, flush=True)
        print("PART 2 VERIFICATION SUMMARY REPORT", flush=True)
        print("="*70, flush=True)
        print(f"V4 (Ambiguity ask_user Card):  {'PASSED' if v4_ok else 'FAILED'}", flush=True)
        print(f"V5 (Edit Mismatch Diagnostic): {'PASSED' if v5_ok else 'FAILED'}", flush=True)
        print(f"V6 (RAG Symbol Search):        {'PASSED' if v6_ok else 'FAILED'}", flush=True)
        print(f"V7 (DAG Re-plan on Failure):   {'PASSED' if v7_ok else 'FAILED'}", flush=True)
        print("="*70, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
