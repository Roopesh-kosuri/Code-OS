import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, r"D:\HTML\CODE OS\backend")

from app.features.ai.chat_harness import (
    run_chat_agent,
    ChatAgentRequest,
    _pending_approvals,
    approve_action,
)

async def auto_approver():
    """Simulate user clicking 'Approve' on the inline approval card."""
    while True:
        await asyncio.sleep(0.1)
        if _pending_approvals:
            for act_id in list(_pending_approvals.keys()):
                print(f"[AUTO-APPROVER] Approving action: {act_id}")
                await approve_action(act_id)

async def main():
    workspace = r"D:\HTML\CODE OS"
    target_file = Path(workspace) / "hello.html"
    
    # Remove existing hello.html if present before test
    if target_file.exists():
        target_file.unlink()
        print("Removed existing hello.html")

    req = ChatAgentRequest(
        provider="auto",
        model="",
        workspace=workspace,
        messages=[{"role": "user", "content": "create hello.html, 1000+ line portfolio"}],
    )

    print("Starting agent run on 'create hello.html, 1000+ line portfolio'...")
    approver_task = asyncio.create_task(auto_approver())

    events = []
    try:
        async for chunk in run_chat_agent(req):
            events.append(chunk)
            # Print status and tokens in real-time
            if "event: status" in chunk:
                print(chunk.strip())
            elif "event: approval_request" in chunk:
                print(">>> APPROVAL REQUEST EMITTED <<<")
                print(chunk.strip())
            elif "event: done" in chunk:
                print(">>> DONE EVENT <<<")
                print(chunk.strip())
    finally:
        approver_task.cancel()

    print("\n--- RUN FINISHED ---")
    if target_file.exists():
        content = target_file.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        print(f"SUCCESS: hello.html exists on disk!")
        print(f"Total lines in hello.html: {len(lines)}")
        print(f"Total chars: {len(content)}")
        print(f"First 10 lines:\n" + "\n".join(lines[:10]))
        print(f"...\nLast 10 lines:\n" + "\n".join(lines[-10:]))
    else:
        print("FAILURE: hello.html was not created on disk.")

if __name__ == "__main__":
    asyncio.run(main())
