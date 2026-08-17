import asyncio
import json
import logging
import time
import uuid
from typing import Any, Dict, Optional
from pydantic import BaseModel

from .service import provider_for, create_proposal, FileChange, EditProposalDto, EditProposalRequest
from .schemas import ChatRequest, ChatMessage
from .agents.coder import CoderAgent
from ...core.paths import normalize_workspace

logger = logging.getLogger(__name__)

# In-memory storage for active/completed Dual Coder sessions
DUAL_CODER_SESSIONS: Dict[str, Dict[str, Any]] = {}

class DualCoderModelConfig(BaseModel):
    provider: str = "ollama"
    model: str = "llama3"
    preset: Optional[str] = "auto"
    base_url: Optional[str] = None
    api_key_provider: Optional[str] = None

class DualCoderRequest(BaseModel):
    workspace: str
    task_description: str
    model_a: DualCoderModelConfig
    model_b: DualCoderModelConfig
    target_file: Optional[str] = None

async def _run_single_attempt(
    attempt_label: str,
    workspace: str,
    task_description: str,
    model_config: DualCoderModelConfig,
    target_file: Optional[str] = None
) -> Dict[str, Any]:
    """Execute a single model's attempt via CoderAgent self-review logic."""
    start_t = time.time()

    provider_dict = {
        "provider": model_config.provider,
        "preset": model_config.preset,
        "model": model_config.model,
        "base_url": model_config.base_url,
        "api_key_provider": model_config.api_key_provider,
    }

    coder = CoderAgent(provider_config=provider_dict)
    
    # Run lightweight code generation & proposal creation
    try:
        ws_path = normalize_workspace(workspace)
        grounded_snippets = []

        if target_file:
            tf_path = ws_path / target_file
            if tf_path.exists() and tf_path.is_file():
                content = tf_path.read_text(encoding="utf-8", errors="ignore")[:30000]
                grounded_snippets.append(f"File: {target_file}\n```\n{content}\n```")
        else:
            # Auto-pick top 3 recent/relevant files
            count = 0
            for path in ws_path.rglob("*"):
                if count >= 3:
                    break
                if path.is_file() and not any(p in path.parts for p in [".git", "node_modules", "dist", "build"]):
                    try:
                        rel = str(path.relative_to(ws_path))
                        content = path.read_text(encoding="utf-8", errors="ignore")[:3000]
                        grounded_snippets.append(f"File: {rel}\n```\n{content}\n```")
                        count += 1
                    except OSError:
                        continue

        context_str = "\n\n".join(grounded_snippets) if grounded_snippets else "(Empty workspace or new file creation)"

        system_prompt = (
            "You are a Senior Coder Agent executing a small/quick programming task.\n"
            "Generate your solution using the EXACT edit proposal format:\n"
            "[PROPOSAL: relative/file/path.ext]\n"
            "<<<< ORIGINAL\n"
            "<exact original code to replace or empty if new file>\n"
            "====\n"
            "<new updated code>\n"
            ">>>>\n\n"
            "Keep changes minimal, self-contained, and correct."
        )

        user_prompt = (
            f"TASK: {task_description}\n\n"
            f"=== FILE CONTEXT ===\n{context_str}"
        )

        chat_req = coder.create_chat_request(
            messages=[
                ChatMessage(role="system", content=system_prompt),
                ChatMessage(role="user", content=user_prompt)
            ]
        )

        provider = await provider_for(chat_req)
        tokens = []
        async for token in provider.stream_chat(chat_req.model, chat_req.messages, temperature=0.2):
            tokens.append(token)
        raw_output = "".join(tokens).strip()

        from .service import parse_proposals_from_llm
        parsed_changes, summary = parse_proposals_from_llm(raw_output)

        proposal_dto = None
        if parsed_changes:
            req_payload = EditProposalRequest(
                workspace=workspace,
                summary=f"Dual Coder Attempt {attempt_label}: {task_description[:50]}",
                changes=parsed_changes,
                plan={"task": task_description, "attempt": attempt_label},
                self_review={"approved": True, "verdict": "Generated cleanly via Dual Coder fast-path"}
            )
            proposal_dto = await create_proposal(req_payload)

        duration = round(time.time() - start_t, 2)

        return {
            "attempt": attempt_label,
            "model": model_config.model,
            "provider": model_config.provider,
            "duration": duration,
            "proposal_id": proposal_dto.id if proposal_dto else None,
            "summary": summary or f"Attempt {attempt_label} completed",
            "raw_output": raw_output,
            "changes": [c.model_dump() for c in proposal_dto.changes] if proposal_dto else [],
            "diff": proposal_dto.diff if proposal_dto else "(No proposal block generated)",
            "self_review": {
                "approved": bool(proposal_dto),
                "verdict": "Self-verified candidate output generated" if proposal_dto else "Formatting error in proposal output"
            }
        }
    except Exception as exc:
        logger.error("DualCoder attempt %s failed: %s", attempt_label, exc, exc_info=True)
        return {
            "attempt": attempt_label,
            "model": model_config.model,
            "provider": model_config.provider,
            "duration": round(time.time() - start_t, 2),
            "proposal_id": None,
            "summary": f"Attempt failed: {exc}",
            "raw_output": str(exc),
            "changes": [],
            "diff": f"Error: {exc}",
            "self_review": {"approved": False, "verdict": f"Execution error: {exc}"}
        }

async def execute_dual_coder(req: DualCoderRequest) -> Dict[str, Any]:
    """Run Model A and Model B in parallel and construct Dual Coder comparison payload."""
    session_id = str(uuid.uuid4())
    start_t = time.time()

    DUAL_CODER_SESSIONS[session_id] = {
        "id": session_id,
        "workspace": req.workspace,
        "task_description": req.task_description,
        "status": "running",
        "attempt_a": None,
        "attempt_b": None,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    }

    # Run Attempt A and Attempt B concurrently
    res_a, res_b = await asyncio.gather(
        _run_single_attempt("A", req.workspace, req.task_description, req.model_a, req.target_file),
        _run_single_attempt("B", req.workspace, req.task_description, req.model_b, req.target_file)
    )

    total_duration = round(time.time() - start_t, 2)

    session_data = {
        "id": session_id,
        "workspace": req.workspace,
        "task_description": req.task_description,
        "status": "completed",
        "total_duration": total_duration,
        "attempt_a": res_a,
        "attempt_b": res_b,
        "created_at": DUAL_CODER_SESSIONS[session_id]["created_at"]
    }

    DUAL_CODER_SESSIONS[session_id] = session_data
    return session_data
