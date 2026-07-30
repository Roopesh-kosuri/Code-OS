import logging
import time
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional
from pydantic import BaseModel

from .agents.tester import TesterAgent
from .service import provider_for, create_proposal, parse_proposals_from_llm
from .schemas import ChatRequest, ChatMessage, EditProposalRequest
from app.core.paths import normalize_workspace

logger = logging.getLogger(__name__)


class CoderModeRequest(BaseModel):
    workspace: str
    user_request: str
    target_file: Optional[str] = None
    provider_config: Optional[Dict[str, Any]] = None


async def execute_coder_mode(req: CoderModeRequest) -> Dict[str, Any]:
    """
    Phase 3 — Coder Agent Pipeline:
    Single-model fast path using only CoderAgent (code generation) + TesterAgent (test verification).
    Skips Planner/Reviewer/Documenter and multi-step Duo loops.
    """
    start_t = time.time()
    ws_path = normalize_workspace(req.workspace)

    try:
        # 1. Gather context snippets
        grounded_snippets = []
        if req.target_file:
            tf_path = ws_path / req.target_file
            if tf_path.exists() and tf_path.is_file():
                content = tf_path.read_text(encoding="utf-8", errors="ignore")[:4000]
                grounded_snippets.append(f"Target File: {req.target_file}\n```\n{content}\n```")

        if not grounded_snippets:
            count = 0
            for path in ws_path.rglob("*"):
                if count >= 4:
                    break
                if path.is_file() and not any(p in path.parts for p in [".git", "node_modules", "dist", "build", ".venv"]):
                    try:
                        rel = str(path.relative_to(ws_path))
                        content = path.read_text(encoding="utf-8", errors="ignore")[:3000]
                        grounded_snippets.append(f"File: {rel}\n```\n{content}\n```")
                        count += 1
                    except OSError:
                        continue

        context_str = "\n\n".join(grounded_snippets) if grounded_snippets else "(Empty workspace)"

        # 2. Construct Coder prompt & invoke LLM
        system_prompt = (
            "You are a Senior Coder Agent executing a software development task.\n"
            "Generate clean, correct, working code using the EXACT edit proposal format:\n"
            "[PROPOSAL: relative/file/path.ext]\n"
            "<<<< ORIGINAL\n"
            "<exact original code to replace or empty if creating a new file>\n"
            "====\n"
            "<new updated code>\n"
            ">>>>\n\n"
            "Be thorough, handle edge cases, and keep edits precise."
        )

        user_prompt = (
            f"USER REQUEST: {req.user_request}\n\n"
            f"=== WORKSPACE CONTEXT ===\n{context_str}"
        )

        p_cfg = req.provider_config or {}
        model_name = p_cfg.get("model") or "default"
        chat_req = ChatRequest(
            provider=p_cfg.get("provider", "auto"),
            model=model_name,
            base_url=p_cfg.get("base_url"),
            api_key_provider=p_cfg.get("api_key_provider"),
            messages=[
                ChatMessage(role="system", content=system_prompt),
                ChatMessage(role="user", content=user_prompt)
            ],
            provider_config=p_cfg
        )

        provider = await provider_for(chat_req)
        tokens = []
        async for token in provider.stream_chat(chat_req.model or "default", chat_req.messages, temperature=0.2):
            tokens.append(token)
        raw_output = "".join(tokens).strip()

        parsed_changes, summary = parse_proposals_from_llm(raw_output)

        proposal_dto = None
        if parsed_changes:
            req_payload = EditProposalRequest(
                workspace=req.workspace,
                summary=f"Coder Agent: {req.user_request[:50]}",
                changes=parsed_changes,
                plan={"task": req.user_request, "agent": "CoderAgent"},
                self_review={"approved": True, "verdict": "Coder Agent fast-path proposal generated"}
            )
            proposal_dto = await create_proposal(req_payload)

        # 3. Tester Agent Verification
        tester = TesterAgent(provider_config=req.provider_config)
        runner_info = tester.detect_test_runner(req.workspace)

        test_result = {
            "tested": False,
            "runner": runner_info["type"] if runner_info else None,
            "summary": "No test runner detected in workspace",
            "passed": False
        }

        if runner_info and proposal_dto:
            try:
                cmd = runner_info["command"]
                proc = await asyncio.create_subprocess_shell(
                    cmd,
                    cwd=str(ws_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=20.0)
                output_str = stdout.decode("utf-8", errors="ignore")
                
                parsed = tester.parse_test_output(output_str, runner_info["type"])
                passed = parsed.get("failed", 0) == 0 and parsed.get("passed", 0) > 0
                summary_txt = f"{parsed.get('passed', 0)} passed, {parsed.get('failed', 0)} failed via {runner_info['type']}"

                test_result = {
                    "tested": True,
                    "runner": runner_info["type"],
                    "command": cmd,
                    "passed": passed,
                    "summary": summary_txt,
                    "raw_output": output_str[:1000]
                }
            except asyncio.TimeoutError:
                test_result = {
                    "tested": True,
                    "runner": runner_info["type"],
                    "passed": False,
                    "summary": "Test run timed out after 20s"
                }
            except Exception as exc:
                logger.warning("TesterAgent execution failed: %s", exc)
                test_result = {
                    "tested": False,
                    "runner": runner_info["type"],
                    "summary": f"Test runner execution error: {exc}"
                }

        duration = round(time.time() - start_t, 2)

        return {
            "status": "completed",
            "duration": duration,
            "proposal": {
                "id": proposal_dto.id if proposal_dto else None,
                "summary": summary or "Coder Agent completed",
                "diff": proposal_dto.diff if proposal_dto else "(No proposal block generated)",
                "changes": [c.model_dump() for c in proposal_dto.changes] if proposal_dto else [],
                "raw_output": raw_output
            },
            "test_result": test_result
        }
    except Exception as exc:
        logger.error("execute_coder_mode encountered an unhandled exception: %s", exc, exc_info=True)
        return {
            "status": "failed",
            "duration": round(time.time() - start_t, 2),
            "proposal": {
                "id": None,
                "summary": f"Execution error: {exc}",
                "diff": f"[Error: {exc}]",
                "changes": [],
                "raw_output": str(exc)
            },
            "test_result": {
                "tested": False,
                "runner": None,
                "passed": False,
                "summary": f"Execution error: {exc}"
            }
        }
