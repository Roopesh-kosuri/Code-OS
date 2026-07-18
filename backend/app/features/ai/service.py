import difflib
import json
import logging
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

logger = logging.getLogger(__name__)


from fastapi import HTTPException

from backend.app.features.ai.providers.ollama import OllamaProvider
from backend.app.features.ai.providers.openai_compatible import OpenAICompatibleProvider
from backend.app.features.ai.schemas import ChatMessage, ChatRequest, EditProposalDto, EditProposalRequest, FileChange, ProviderHealth
from backend.app.features.files.service import write_file
from backend.app.features.settings.service import get_api_key
from backend.app.db.database import get_connection

MAX_ATTACHMENT_CHARS = 20_000


import re
from backend.app.features.settings.service import list_settings

SLASH_COMMAND_PROMPTS = {
    "/explain": "Explain the following code snippet in detail, analyzing its logic, inputs, outputs, and any potential issues or code style anomalies.",
    "/fix": "Identify bugs, logic errors, syntax mistakes, or unhandled edge cases in the following code. Explain them, then propose a fix. You MUST present the fix EXACTLY as a proposal code block:\n[PROPOSAL: <filepath>]\n<<<< ORIGINAL\n<exact old code to replace>\n====\n<new code>\n>>>>",
    "/refactor": "Review the following code and propose refactoring changes to improve code quality, readability, or performance. You MUST present the changes EXACTLY as a proposal code block:\n[PROPOSAL: <filepath>]\n<<<< ORIGINAL\n<exact old code to replace>\n====\n<new code>\n>>>>",
    "/document": "Analyze the following code and propose comments, docstrings, and doc updates. You MUST present the code changes EXACTLY as a proposal code block:\n[PROPOSAL: <filepath>]\n<<<< ORIGINAL\n<exact old code to replace>\n====\n<new code>\n>>>>",
    "/test": "Generate high-quality unit tests for the following code. Use pytest for Python, jest/vitest for JS/TS, JUnit for Java, or Google Test for C++. Write the test in a new file or add it. You MUST present the new test file or modifications EXACTLY as a proposal code block:\n[PROPOSAL: <filepath>]\n<<<< ORIGINAL\n<old code if editing existing, or empty if new file>\n====\n<test code>\n>>>>",
    "/review": "Perform a structured code review of the following code. Identify bug risks, style problems, security vulnerabilities, or performance issues. Categorize each finding with its severity (HIGH, MEDIUM, LOW) and description.",
    "/optimize": "Analyze the following code and suggest performance enhancements (time or space complexity). You MUST present the code modifications EXACTLY as a proposal code block:\n[PROPOSAL: <filepath>]\n<<<< ORIGINAL\n<exact old code to replace>\n====\n<new code>\n>>>>",
    "/rename": "Propose renaming symbols (functions, variables, classes) in the following code to make it more self-explanatory. You MUST present the modifications EXACTLY as a proposal code block:\n[PROPOSAL: <filepath>]\n<<<< ORIGINAL\n<exact old code to replace>\n====\n<new code>\n>>>>",
}

_DEFAULT_SYSTEM_PROMPT = """You are CODE OS, a powerful agentic AI coding assistant.
- You have access to local file context (open tabs and attached files) appended to the end of the messages.
- When the user asks you to modify, edit, create, or refactor files, you MUST propose changes using the EXACT edit proposal format:
[PROPOSAL: path/to/file.ext]
<<<< ORIGINAL
<exact original code to replace verbatim from the file context>
====
<new updated code>
>>>>
- CRITICAL: If you are creating a brand new file (file does not exist on disk), you MUST leave the ORIGINAL section completely empty (i.e. nothing between '<<<< ORIGINAL' and '===='). Do not invent placeholder content.
- Always be precise and follow the style and guidelines of the existing codebase.
"""

PROPOSAL_RE = re.compile(
    r"\[PROPOSAL:\s*(?P<path>[^\]]+)\]\s*<<<<(?: ORIGINAL)?\r?\n?(?P<original>.*?)====\r?\n?(?P<updated>.*?)\r?\n?>{3,}",
    re.DOTALL
)


def _provider_resilience(settings: dict[str, str], provider_id: str) -> tuple[float, int]:
    """Read provider-specific request limits with safe local/API defaults."""
    is_local = provider_id == "ollama"
    default_timeout = 300.0 if is_local else 60.0
    default_retries = 1
    prefix = f"ai.provider.{provider_id}"
    fallback_prefix = "ai.provider.ollama" if is_local else "ai.provider.api"
    try:
        timeout = float(settings.get(f"{prefix}.timeout_seconds", settings.get(f"{fallback_prefix}.timeout_seconds", default_timeout)))
    except (TypeError, ValueError):
        timeout = default_timeout
    try:
        retries = int(settings.get(f"{prefix}.retries", settings.get(f"{fallback_prefix}.retries", default_retries)))
    except (TypeError, ValueError):
        retries = default_retries
    return max(5.0, min(timeout, 900.0)), max(0, min(retries, 3))

async def provider_for(request: ChatRequest):
    settings = await list_settings()
    if request.provider == "auto":
        last_msg = request.messages[-1].content.strip() if request.messages else ""
        is_reasoning_task = any(last_msg.startswith(cmd) for cmd in ["/fix", "/refactor", "/review", "/optimize"])

        # Check API keys in priority order for auto-routing
        _KEY_PRIORITY = ["openai-compatible", "openai", "groq", "anthropic", "gemini",
                         "deepseek", "mistral", "openrouter", "nvidia-nim"]
        api_key_id: str | None = None
        for kid in _KEY_PRIORITY:
            if await get_api_key(kid):
                api_key_id = kid
                break

        if api_key_id and is_reasoning_task:
            request.provider = "openai-compatible"
            request.api_key_provider = api_key_id
            # Use the stored base URL for the matched provider, or sensible default
            _DEFAULT_URLS = {
                "openai-compatible": "https://api.openai.com/v1",
                "openai": "https://api.openai.com/v1",
                "groq": "https://api.groq.com/openai/v1",
                "anthropic": "https://api.anthropic.com/v1",
                "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
                "deepseek": "https://api.deepseek.com/v1",
                "mistral": "https://api.mistral.ai/v1",
                "openrouter": "https://openrouter.ai/api/v1",
                "nvidia-nim": "https://integrate.api.nvidia.com/v1",
            }
            request.base_url = settings.get(f"{api_key_id}.baseUrl") or _DEFAULT_URLS.get(api_key_id, "https://api.openai.com/v1")
            
            _DEFAULT_MODELS = {
                "openai-compatible": "gpt-4o",
                "openai": "gpt-4o",
                "anthropic": "claude-3-5-sonnet-latest",
                "gemini": "gemini-2.5-flash",
                "groq": "llama-3.3-70b-versatile",
                "deepseek": "deepseek-chat",
                "mistral": "mistral-large-latest",
                "openrouter": "openai/gpt-4o",
                "nvidia-nim": "meta/llama-3.3-70b-instruct",
            }
            request.model = settings.get(f"{api_key_id}.model") or request.model or _DEFAULT_MODELS.get(api_key_id, "gpt-4o")
        else:
            request.provider = "ollama"
            request.base_url = settings.get("ollama.baseUrl") or "http://127.0.0.1:11434"
            request.model = settings.get("ollama.model") or request.model or "llama3"

    if request.provider == "ollama":
        timeout, retries = _provider_resilience(settings, "ollama")
        return OllamaProvider(request.base_url, timeout, retries)
    if request.provider == "openai-compatible":
        base_url = request.base_url or "https://api.openai.com/v1"
        # Use api_key_provider if set; fall back to "openai-compatible" for
        # backwards compat with existing stored keys
        key_id = request.api_key_provider or "openai-compatible"
        timeout, retries = _provider_resilience(settings, key_id)
        return OpenAICompatibleProvider(base_url, await get_api_key(key_id), timeout, retries)

    # Named provider shortcuts — agents can use these directly without going
    # through the full auto-detection path.
    _NAMED_PROVIDERS: dict[str, tuple[str, str]] = {
        "groq":              ("https://api.groq.com/openai/v1",                           "groq"),
        "openai":            ("https://api.openai.com/v1",                                "openai"),
        "anthropic":         ("https://api.anthropic.com/v1",                             "anthropic"),
        "gemini":            ("https://generativelanguage.googleapis.com/v1beta/openai",   "gemini"),
        "deepseek":          ("https://api.deepseek.com/v1",                              "deepseek"),
        "mistral":           ("https://api.mistral.ai/v1",                                "mistral"),
        "openrouter":        ("https://openrouter.ai/api/v1",                             "openrouter"),
        "nvidia-nim":        ("https://integrate.api.nvidia.com/v1",                      "nvidia-nim"),
        "openai-compatible": ("https://api.openai.com/v1",                                "openai-compatible"),
    }
    if request.provider in _NAMED_PROVIDERS:
        base_url, key_id = _NAMED_PROVIDERS[request.provider]
        # Allow override base_url (e.g. self-hosted Groq proxy)
        base_url = request.base_url or base_url
        key_id = request.api_key_provider or key_id
        timeout, retries = _provider_resilience(settings, key_id)
        return OpenAICompatibleProvider(base_url, await get_api_key(key_id), timeout, retries)

    raise HTTPException(status_code=400, detail="Unknown provider")



async def stream_chat(request: ChatRequest) -> AsyncIterator[str]:
    # 1. Parse slash command
    last_msg = request.messages[-1].content.strip() if request.messages else ""
    cmd = ""
    if last_msg.startswith("/"):
        parts = last_msg.split(maxsplit=1)
        cmd = parts[0].lower()
        
        # Git intelligence: /commit diff aggregation
        if cmd == "/commit":
            try:
                from backend.app.features.git.service import diff as git_diff
                workspace_dir = request.workspace or (request.attached_paths[0] if request.attached_paths else "")
                if workspace_dir:
                    diff_text = git_diff(workspace_dir)
                    request.messages[-1].content = f"Generate a commit message for the following git diff:\n\n{diff_text}"
            except Exception:
                pass

    # Build single system prompt at index 0 containing context and instructions
    sys_instruction = SLASH_COMMAND_PROMPTS.get(cmd, _DEFAULT_SYSTEM_PROMPT)
    context_text = _get_attachment_context_text(request)
    combined_sys_prompt = f"{sys_instruction}\n{context_text}"
    
    messages = [ChatMessage(role="system", content=combined_sys_prompt)] + request.messages

    provider = await provider_for(request)
    
    full_response = []
    async for token in provider.stream_chat(request.model, messages, request.temperature):
        full_response.append(token)
        yield token

    # 2. Parse accumulated stream response for edit proposals
    response_text = "".join(full_response)
    match = PROPOSAL_RE.search(response_text)
    if match and request.workspace:
        filepath = match.group("path").strip()
        original = match.group("original")
        updated = match.group("updated")
        
        # Ensure path is absolute and within workspace
        workspace_path = Path(request.workspace)
        resolved_path = Path(filepath)
        if not resolved_path.is_absolute():
            resolved_path = (workspace_path / filepath).resolve()
        
        # If the file does not exist, force original to empty (pure CREATE)
        if not resolved_path.exists():
            original = ""

        # Create edit proposal
        try:
            proposal_payload = EditProposalRequest(
                workspace=request.workspace,
                summary=f"Automated edit from command {cmd}",
                changes=[FileChange(path=str(resolved_path), original=original, updated=updated)]
            )
            proposal = await create_proposal(proposal_payload)
            yield f"\n\n[EDIT_PROPOSAL_CREATED: {proposal.id}]"
        except Exception as exc:
            logger.error("Failed to automatically create edit proposal: %s", exc)
            yield f"\n\n[ERROR: Failed to create edit proposal - {exc}]"


def _get_attachment_context_text(request: ChatRequest) -> str:
    if not request.attached_paths:
        return ""
    chunks: list[str] = []
    remaining = MAX_ATTACHMENT_CHARS
    for raw_path in request.attached_paths:
        path = Path(raw_path)
        if not path.is_absolute() and request.workspace:
            path = (Path(request.workspace) / path).resolve()
        
        candidates = [path] if path.is_file() else [item for item in path.rglob("*") if item.is_file()][:20] if path.is_dir() else []
        for candidate in candidates:
            if remaining <= 0:
                break
            try:
                content = candidate.read_text(encoding="utf-8", errors="ignore")[:remaining]
            except OSError:
                continue
            chunks.append(f"File: {candidate}\n```\n{content}\n```")
            remaining -= len(content)
    if not chunks:
        return ""
    return "\n\n=== GROUNDED FILE CONTEXT ===\n" + "\n\n".join(chunks)


async def ollama_health(base_url: str | None = None) -> ProviderHealth:
    return await OllamaProvider(base_url).health()


async def ollama_models(base_url: str | None = None):
    return await OllamaProvider(base_url).models()


def proposal_diff(changes: list[FileChange]) -> str:
    chunks: list[str] = []
    for change in changes:
        chunks.extend(
            difflib.unified_diff(
                change.original.splitlines(keepends=True),
                change.updated.splitlines(keepends=True),
                fromfile=f"a/{change.path}",
                tofile=f"b/{change.path}",
            )
        )
    return "".join(chunks)


async def create_proposal(payload: EditProposalRequest) -> EditProposalDto:
    from backend.app.core.paths import normalize_path
    normalized_workspace = str(normalize_path(payload.workspace))
    
    from backend.app.features.workspaces.trust_service import get_workspace_trust
    trust = await get_workspace_trust(normalized_workspace)
    if not trust.get("trusted", False):
        raise HTTPException(status_code=403, detail="Workspace is in Restricted Mode. File modifications are disabled.")

    # Force original block to be empty for nonexistent files
    for change in payload.changes:
        change_path = Path(change.path)
        if not change_path.is_absolute():
            change_path = Path(normalized_workspace) / change_path
        if not change_path.exists():
            change.original = ""

    proposal_id = str(uuid.uuid4())
    body = {
        "summary": payload.summary,
        "changes": [change.model_dump() for change in payload.changes],
        "plan": payload.plan,
        "self_review": payload.self_review,
        "test_results": payload.test_results,
    }
    db = await get_connection()
    try:
        await db.execute(
            "INSERT INTO edit_proposals(id, workspace, status, payload) VALUES (?, ?, ?, ?)",
            (proposal_id, normalized_workspace, "pending", json.dumps(body)),
        )
        await db.commit()
    finally:
        await db.close()
    return EditProposalDto(
        id=proposal_id,
        workspace=normalized_workspace,
        status="pending",
        summary=payload.summary,
        changes=payload.changes,
        diff=proposal_diff(payload.changes),
        plan=payload.plan,
        self_review=payload.self_review,
        test_results=payload.test_results,
    )


async def get_proposal(proposal_id: str) -> EditProposalDto:
    db = await get_connection()
    try:
        cursor = await db.execute("SELECT * FROM edit_proposals WHERE id = ?", (proposal_id,))
        row = await cursor.fetchone()
    finally:
        await db.close()
    if not row:
        raise HTTPException(status_code=404, detail="Proposal not found")
    payload = json.loads(row["payload"])
    changes = [FileChange(**change) for change in payload["changes"]]
    return EditProposalDto(
        id=row["id"],
        workspace=row["workspace"],
        status=row["status"],
        summary=payload["summary"],
        changes=changes,
        diff=proposal_diff(changes),
        plan=payload.get("plan"),
        self_review=payload.get("self_review"),
        test_results=payload.get("test_results"),
    )


def _strip_code_fences(text: str) -> str:
    text_stripped = text.strip()
    if text_stripped.startswith("```") and text_stripped.endswith("```"):
        first_newline = text_stripped.find("\n")
        if first_newline != -1:
            return text_stripped[first_newline+1:-3].strip()
        else:
            return text_stripped[3:-3].strip()
    return text

async def apply_proposal(proposal_id: str) -> EditProposalDto:
    proposal = await get_proposal(proposal_id)
    if proposal.status != "pending":
        raise HTTPException(status_code=409, detail="Proposal is not pending")
        
    from backend.app.core.paths import normalize_path
    root = normalize_path(proposal.workspace)
    
    # 1. Normalize line endings and merge changes
    merged_contents = {}
    for change in proposal.changes:
        file_path = root / change.path
        raw_original = change.original
        # Self-healing for legacy proposals created with dynamic ORIGINAL headers
        if raw_original.startswith(" ORIGINAL\n"):
            raw_original = raw_original[len(" ORIGINAL\n"):]
        elif raw_original.startswith(" ORIGINAL"):
            raw_original = raw_original[len(" ORIGINAL"):].lstrip("\r\n")

        original_stripped = raw_original.replace("\r\n", "\n").strip()
        updated_clean = _strip_code_fences(change.updated)
        
        if not file_path.exists():
            # If creating a new file, ignore what the original section said (it's often descriptive prose)
            merged_contents[change.path] = updated_clean
        else:
            try:
                current_text = file_path.read_text(encoding="utf-8", errors="ignore")
            except OSError as exc:
                raise HTTPException(
                    status_code=500,
                    detail=f"Could not read {change.path}: {exc}"
                )
                
            current_normalized = current_text.replace("\r\n", "\n")
            original_normalized = raw_original.replace("\r\n", "\n")
            
            # Find the original snippet
            idx = current_normalized.find(original_normalized)
            if idx == -1:
                # Be more forgiving of leading/trailing whitespace around original
                idx = current_normalized.find(original_stripped)
                if idx == -1:
                    # If original is just placeholder explanation (e.g. "empty file") or file is empty, overwrite everything
                    is_placeholder = any(p in original_stripped.lower() for p in [
                        "no original", "empty file", "new file", "there is no original", "create a new file"
                    ])
                    if is_placeholder or not current_normalized.strip():
                        merged = updated_clean
                    else:
                        raise HTTPException(
                            status_code=409,
                            detail=f"Merge conflict in {change.path}: proposed original block not found in current file."
                        )
                else:
                    merged = current_normalized.replace(original_stripped, updated_clean.replace("\r\n", "\n"), 1)
            else:
                merged = current_normalized.replace(original_normalized, updated_clean.replace("\r\n", "\n"), 1)
                
            merged_contents[change.path] = merged

    # 2. Write merged contents
    for rel_path, content in merged_contents.items():
        try:
            write_file(proposal.workspace, rel_path, content)
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to write merged changes to {rel_path}: {exc}"
            )
            
    db = await get_connection()
    try:
        await db.execute("UPDATE edit_proposals SET status = ? WHERE id = ?", ("applied", proposal_id))
        await db.commit()
    finally:
        await db.close()
        
    # 3. Check if this proposal belongs to a pending task permission event and resume it
    db = await get_connection()
    try:
        cursor = await db.execute("SELECT payload FROM edit_proposals WHERE id = ?", (proposal_id,))
        row = await cursor.fetchone()
        if row and row["payload"]:
            payload = json.loads(row["payload"])
            task_id = payload.get("task_id")
            if task_id:
                from backend.app.features.ai.agents import permission_state as perm_state
                if task_id in perm_state.pending_permission_events:
                    perm_state.pending_permission_decisions[task_id] = "approve"
                    perm_state.pending_permission_events[task_id].set()
    finally:
        await db.close()

    return await get_proposal(proposal_id)


async def reject_proposal(proposal_id: str, feedback: str | None = None) -> EditProposalDto:
    db = await get_connection()
    try:
        await db.execute("UPDATE edit_proposals SET status = ? WHERE id = ?", ("rejected", proposal_id))
        await db.commit()
    finally:
        await db.close()
        
    # Check if this proposal belongs to a pending task permission event and resume it
    db = await get_connection()
    try:
        cursor = await db.execute("SELECT payload FROM edit_proposals WHERE id = ?", (proposal_id,))
        row = await cursor.fetchone()
        if row and row["payload"]:
            payload = json.loads(row["payload"])
            task_id = payload.get("task_id")
            if task_id:
                from backend.app.features.ai.agents import permission_state as perm_state
                if task_id in perm_state.pending_permission_events:
                    perm_state.pending_permission_decisions[task_id] = "reject"
                    if feedback:
                        perm_state.pending_permission_feedback[task_id] = feedback
                    perm_state.pending_permission_events[task_id].set()
    finally:
        await db.close()
        
    return await get_proposal(proposal_id)


async def list_proposals(workspace: str) -> list[EditProposalDto]:
    from backend.app.core.paths import normalize_path
    normalized_workspace = str(normalize_path(workspace))
    
    db = await get_connection()
    try:
        cursor = await db.execute("SELECT * FROM edit_proposals WHERE workspace = ? ORDER BY created_at DESC", (normalized_workspace,))
        rows = await cursor.fetchall()
        
        # Load statuses of all jobs in the workspace to evaluate active proposals
        job_cursor = await db.execute("SELECT id, status FROM agent_jobs WHERE workspace = ?", (normalized_workspace,))
        job_rows = await job_cursor.fetchall()
        job_statuses = {j["id"]: j["status"] for j in job_rows}
    finally:
        await db.close()
    
    results = []
    db = await get_connection()
    try:
        for row in rows:
            payload = json.loads(row["payload"])
            status = row["status"]
            
            # Auto-reject pending proposals that belong to finished/cancelled jobs
            job_id = payload.get("job_id")
            if status == "pending" and job_id and job_id in job_statuses:
                if job_statuses[job_id] in ("completed", "failed", "cancelled"):
                    status = "rejected"
                    await db.execute("UPDATE edit_proposals SET status = 'rejected' WHERE id = ?", (row["id"],))
                    await db.commit()
            
            changes = [FileChange(**change) for change in payload["changes"]]
            results.append(
                EditProposalDto(
                    id=row["id"],
                    workspace=row["workspace"],
                    status=status,
                    summary=payload["summary"],
                    changes=changes,
                    diff=proposal_diff(changes),
                    plan=payload.get("plan"),
                    self_review=payload.get("self_review"),
                    test_results=payload.get("test_results"),
                )
            )
    finally:
        await db.close()
        
    return results
