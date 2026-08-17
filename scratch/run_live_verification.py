"""
Live Measured Verification Suite for Adaptive Effort Routing, RAG, DAG, and Hardened Rony Agent Harness.
Runs real measured requests against the live backend (port 8000) using Groq llama-3.3-70b-versatile.
"""
import asyncio
import json
import os
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path

# UTF-8 stdout encoding on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# Add backend directory to sys.path
sys.path.insert(0, r"d:\HTML\CODE OS\backend")

WORKSPACE = r"d:\HTML\CODE OS"
SESSION_TOKEN_FILE = os.path.expanduser("~/.code-os/session_token")
BASE_URL = "http://127.0.0.1:8000"

PROVIDER = "openai-compatible"
MODEL = "llama-3.3-70b-versatile"
BASE_URL_API = "https://api.groq.com/openai/v1"
API_KEY_PROVIDER = "groq"


def get_token() -> str:
    if os.path.exists(SESSION_TOKEN_FILE):
        return open(SESSION_TOKEN_FILE).read().strip()
    return ""


async def stream_agent(request_data: dict):
    token = get_token()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    url = f"{BASE_URL}/api/ai/chat-agent/stream"
    
    full_req = {
        "provider": PROVIDER,
        "model": MODEL,
        "base_url": BASE_URL_API,
        "api_key_provider": API_KEY_PROVIDER,
        "workspace": WORKSPACE,
        **request_data,
    }
    req_json = json.dumps(full_req).encode("utf-8")
    
    start_time = time.time()
    first_token_time = None
    events = []
    
    req = urllib.request.Request(url, data=req_json, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            current_event_type = "message"
            for raw_line in resp:
                line = raw_line.decode("utf-8").strip()
                if not line:
                    continue
                if line.startswith("event: "):
                    current_event_type = line[7:].strip()
                elif line.startswith("data: "):
                    data_str = line[6:].strip()
                    try:
                        data_obj = json.loads(data_str)
                    except Exception:
                        data_obj = data_str
                    
                    if current_event_type == "token" and first_token_time is None:
                        first_token_time = time.time()
                    
                    events.append({
                        "event": current_event_type,
                        "data": data_obj,
                        "elapsed": time.time() - start_time,
                    })
    except Exception as exc:
        events.append({"event": "error", "error": str(exc), "elapsed": time.time() - start_time})
    
    total_time = time.time() - start_time
    ttft = (first_token_time - start_time) if first_token_time else None
    return events, ttft, total_time


async def run_v1():
    print("\n" + "="*70, flush=True)
    print("RUNNING V1: Tier 0 (Fast Answer) — Question / Explanation", flush=True)
    print("="*70, flush=True)
    
    req = {
        "messages": [
            {"role": "user", "content": "what does is_source_file in inventory_generator.py do?"}
        ],
        "agent_mode": False,
    }
    
    events, ttft, total_time = await stream_agent(req)
    
    tier_events = [e for e in events if e["event"] == "tier_routing"]
    plan_events = [e for e in events if e["event"] == "plan"]
    token_events = [e for e in events if e["event"] == "token"]
    done_events = [e for e in events if e["event"] == "done"]
    
    full_text = "".join([e["data"].get("content", "") if isinstance(e["data"], dict) else str(e["data"]) for e in token_events])
    
    print(f"[*] Total Events Received: {len(events)}", flush=True)
    print(f"[*] TTFT (Time-to-First-Token): {ttft:.3f}s" if ttft else "[*] TTFT: None", flush=True)
    print(f"[*] Total Duration: {total_time:.3f}s", flush=True)
    print(f"[*] Tier Routing Event: {tier_events[0]['data'] if tier_events else 'None'}", flush=True)
    print(f"[*] Plan Events Emitted: {len(plan_events)} (Expected 0 for Tier 0)", flush=True)
    print(f"[*] Response Preview ({len(full_text)} chars):\n{full_text[:300]}...", flush=True)
    print(f"[*] Done Status: {done_events[0]['data'] if done_events else 'None'}", flush=True)
    
    success = (
        tier_events and tier_events[0]["data"].get("tier") == 0 and
        len(plan_events) == 0 and
        ttft is not None and ttft < 3.0 and
        len(full_text) > 20
    )
    print(f"[+] V1 Result: {'PASSED' if success else 'FAILED'} (Measured TTFT: {ttft:.3f}s)", flush=True)
    return success, ttft


async def run_v2():
    print("\n" + "="*70, flush=True)
    print("RUNNING V2: Tier 1 (Quick Task) — Targeted Command / Surgical Action", flush=True)
    print("="*70, flush=True)
    
    req = {
        "messages": [
            {"role": "user", "content": "inspect git status and list files in backend/app"}
        ],
        "agent_mode": False,
    }
    
    events, ttft, total_time = await stream_agent(req)
    
    tier_events = [e for e in events if e["event"] == "tier_routing"]
    status_events = [e for e in events if e["event"] == "status"]
    tool_statuses = [e["data"] for e in status_events if e["data"].get("type") == "tool"]
    done_events = [e for e in events if e["event"] == "done"]
    
    print(f"[*] Total Events: {len(events)}", flush=True)
    print(f"[*] Tier Routing Event: {tier_events[0]['data'] if tier_events else 'None'}", flush=True)
    print(f"[*] Tools Executed in Tier 1: {len(tool_statuses)}", flush=True)
    for t in tool_statuses[:5]:
        print(f"    - {t.get('tool')}: {t.get('detail')}", flush=True)
    print(f"[*] Done Status: {done_events[0]['data'] if done_events else 'None'}", flush=True)
    
    success = (
        tier_events and tier_events[0]["data"].get("tier") == 1 and
        len(tool_statuses) <= 4 and
        done_events and done_events[0]["data"].get("success") is True
    )
    print(f"[+] V2 Result: {'PASSED' if success else 'FAILED'}", flush=True)
    return success


async def run_v3():
    print("\n" + "="*70, flush=True)
    print("RUNNING V3: Tier 2 (Deep Task) — Multi-Step Plan & Audit", flush=True)
    print("="*70, flush=True)
    
    req = {
        "messages": [
            {"role": "user", "content": "build a complete modern HTML portfolio in scratch_portfolio.html with responsive CSS"}
        ],
        "agent_mode": True,
    }
    
    events, ttft, total_time = await stream_agent(req)
    
    tier_events = [e for e in events if e["event"] == "tier_routing"]
    plan_events = [e for e in events if e["event"] == "plan"]
    proposal_events = [e for e in events if e["event"] == "proposal"]
    approval_events = [e for e in events if e["event"] == "approval_request"]
    
    print(f"[*] Total Events: {len(events)}", flush=True)
    print(f"[*] Tier Routing: {tier_events[0]['data'] if tier_events else 'None'}", flush=True)
    print(f"[*] Plan Events: {len(plan_events)}", flush=True)
    if plan_events:
        steps = plan_events[-1]["data"].get("steps", [])
        print(f"    Steps in Plan ({len(steps)}):", flush=True)
        for s in steps[:4]:
            print(f"      - {s.get('id')}: {s.get('title')} [{s.get('status')}]", flush=True)
    print(f"[*] Proposal Created: {len(proposal_events) > 0}", flush=True)
    print(f"[*] Approval Requested: {len(approval_events) > 0}", flush=True)
    
    success = (
        tier_events and tier_events[0]["data"].get("tier") == 2
    )
    print(f"[+] V3 Result: {'PASSED' if success else 'FAILED'}", flush=True)
    return success


async def run_v8():
    print("\n" + "="*70, flush=True)
    print("RUNNING V8: Project Memory (RONY.md) Save & Recall", flush=True)
    print("="*70, flush=True)
    
    from app.features.ai.chat_harness import _handle_memory_write, _load_project_memory
    
    test_fact = f"Rule-{int(time.time())}: Use snake_case for all Python helper functions."
    ok, msg = _handle_memory_write(WORKSPACE, {"fact": test_fact})
    print(f"[*] memory_write result: {ok}, message: {msg}", flush=True)
    
    memory = _load_project_memory(WORKSPACE)
    print(f"[*] RONY.md loaded memory content preview:\n{memory[-200:]}", flush=True)
    
    success = ok and test_fact in memory
    print(f"[+] V8 Result: {'PASSED' if success else 'FAILED'}", flush=True)
    return success


async def main():
    print("Starting Live Verification Suite against http://127.0.0.1:8000 ...", flush=True)
    
    token = get_token()
    req = urllib.request.Request(f"{BASE_URL}/api/ai/chat-agent/health", headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req) as resp:
            health = json.loads(resp.read().decode())
            print(f"[*] Backend Health: {health}", flush=True)
    except Exception as exc:
        print(f"[!] Backend Health check failed: {exc}", flush=True)
        return
    
    v1_ok, ttft = await run_v1()
    v2_ok = await run_v2()
    v3_ok = await run_v3()
    v8_ok = await run_v8()
    
    print("\n" + "="*70, flush=True)
    print("LIVE MEASURED VERIFICATION SUMMARY REPORT", flush=True)
    print("="*70, flush=True)
    print(f"V1 (Tier 0 Fast Answer TTFT): {'PASSED' if v1_ok else 'FAILED'} (TTFT = {ttft:.3f}s)" if ttft else f"V1: {v1_ok}", flush=True)
    print(f"V2 (Tier 1 Quick Task):       {'PASSED' if v2_ok else 'FAILED'}", flush=True)
    print(f"V3 (Tier 2 Deep Task):        {'PASSED' if v3_ok else 'FAILED'}", flush=True)
    print(f"V8 (Project Memory Recall):   {'PASSED' if v8_ok else 'FAILED'}", flush=True)
    print("="*70, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
