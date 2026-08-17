import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
from app.features.ai.chat_harness import run_chat_agent, ChatAgentRequest, approve_action, _pending_approvals

async def test_edit_approval():
    prompt = "In inventory_generator.py, add '.yaml' and '.json' to SOURCE_EXTENSIONS. Make a surgical edit, then stop and ask me before running tests."
    workspace = r"D:\HTML\CODE OS"
    
    print("================================================================")
    print("TEST: DOCKED EDIT APPROVAL FLOW")
    print("Prompt:", prompt)
    print("================================================================")
    
    req = ChatAgentRequest(
        provider="auto",
        model="",
        api_key_provider="groq",
        workspace=workspace,
        messages=[{"role": "user", "content": prompt}],
    )
    
    stop_approver = False
    approved_actions = []
    
    async def inline_approver():
        while not stop_approver:
            await asyncio.sleep(0.3)
            if _pending_approvals:
                for act_id in list(_pending_approvals.keys()):
                    pending = _pending_approvals[act_id]
                    if act_id not in approved_actions:
                        approved_actions.append(act_id)
                        print(f"\n>>> [DOCKED UI APPROVAL CARD DETECTED ABOVE INPUT BOX]")
                        print(f"    Action ID: {act_id}")
                        print(f"    Action Type: {pending.action_type}")
                        print(f"    Path: {pending.path or pending.detail}")
                        print(f"    Proposal ID: {pending.proposal_id}")
                        print(f"    Reason: {pending.reason}")
                        print(f"    Diff Summary:\n{pending.diff_summary}")
                        print(f">>> [USER ACTION] Clicking 'Approve & Apply' from docked card...\n")
                        await approve_action(act_id)
    
    approver_task = asyncio.create_task(inline_approver())
    
    tokens = []
    async for event in run_chat_agent(req):
        if event.startswith("event: token"):
            data_line = [l for l in event.split("\n") if l.startswith("data: ")]
            if data_line:
                tok = json.loads(data_line[0][6:])
                tokens.append(tok.get("content", ""))
                print(tok.get("content", ""), end="", flush=True)
        else:
            print(event.strip())
    
    stop_approver = True
    await approver_task
    
    print("\n================================================================")
    print("POST-RUN VERIFICATION: Checking inventory_generator.py on disk")
    target_file = Path(workspace) / "inventory_generator.py"
    assert target_file.exists(), "inventory_generator.py should exist on disk"
    content = target_file.read_text(encoding="utf-8")
    print("--- INVENTORY_GENERATOR.PY ON DISK ---")
    print(content)
    print("--------------------------------------")
    assert ".yaml" in content or ".json" in content, "Expected .yaml or .json in inventory_generator.py"
    print("✓ SUCCESS: Proposal was approved & applied from docked card directly into disk file!")
    print("================================================================")

if __name__ == "__main__":
    asyncio.run(test_edit_approval())
