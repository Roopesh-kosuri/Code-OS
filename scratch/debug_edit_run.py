import asyncio, sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
from app.features.ai.chat_harness import run_chat_agent, ChatAgentRequest, _pending_approvals, approve_action

async def main():
    prompt = "In inventory_generator.py, add '.sql' and '.toml' to SOURCE_EXTENSIONS. Make a surgical edit, then stop and ask me before running tests."
    workspace = r"D:\HTML\CODE OS"
    
    req = ChatAgentRequest(
        provider="auto",
        model="llama-3.1-8b-instant",
        api_key_provider="groq",
        workspace=workspace,
        messages=[{"role": "user", "content": prompt}],
    )
    
    async def auto_approver():
        for _ in range(50):
            await asyncio.sleep(0.2)
            if _pending_approvals:
                for act_id in list(_pending_approvals.keys()):
                    pending = _pending_approvals[act_id]
                    print(f"\n>>> [AUTO-APPROVER] Found pending action_id={act_id}, type={pending.action_type}, path={pending.path or pending.detail}")
                    await approve_action(act_id)
                break
    
    app_task = asyncio.create_task(auto_approver())
    
    async for event in run_chat_agent(req):
        print(event.strip())
    
    await app_task

asyncio.run(main())
