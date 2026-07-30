import difflib
import json
import logging
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

logger = logging.getLogger(__name__)


from fastapi import HTTPException

from .providers.ollama import OllamaProvider
from .providers.openai_compatible import OpenAICompatibleProvider
from .schemas import ChatMessage, ChatRequest, EditProposalDto, EditProposalRequest, FileChange, ProviderHealth
from ..files.service import write_file
from ..settings.service import get_api_key
from ...db.database import get_db

MAX_ATTACHMENT_CHARS = 20_000

KNOWN_PLACEHOLDERS = {
    "no original", "empty file", "new file", "there is no original",
    "create a new file", "n/a", "none", "file does not exist", "new file creation",
    "# empty file", "// empty file", "<!-- empty file -->",
}



import re
from ..settings.service import list_settings

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
        "ollama": "llama3",
    }

    if request.provider == "ollama":
        if not request.model:
            request.model = settings.get("ollama.model") or "llama3"
        timeout, retries = _provider_resilience(settings, "ollama")
        return OllamaProvider(request.base_url, timeout, retries)

    if request.provider == "openai-compatible":
        base_url = request.base_url or "https://api.openai.com/v1"
        key_id = request.api_key_provider or "openai-compatible"
        if not request.model:
            request.model = settings.get(f"{key_id}.model") or settings.get("openai-compatible.model") or _DEFAULT_MODELS.get(key_id, "gpt-4o")
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
    if request.provider == "anthropic":
        from .providers.anthropic import AnthropicProvider
        key_id = request.api_key_provider or "anthropic"
        base_url = request.base_url or "https://api.anthropic.com/v1"
        if not request.model:
            request.model = settings.get("anthropic.model") or _DEFAULT_MODELS.get("anthropic", "claude-3-5-sonnet-latest")
        timeout, retries = _provider_resilience(settings, "anthropic")
        return AnthropicProvider(base_url, await get_api_key(key_id), timeout, retries)

    if request.provider in _NAMED_PROVIDERS:
        base_url, key_id = _NAMED_PROVIDERS[request.provider]
        base_url = request.base_url or base_url
        key_id = request.api_key_provider or key_id
        if not request.model:
            request.model = settings.get(f"{key_id}.model") or _DEFAULT_MODELS.get(key_id, "gpt-4o")
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
                from ...git.service import diff as git_diff
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

    full_response = []
    try:
        provider = await provider_for(request)
        async for token in provider.stream_chat(request.model, messages, request.temperature):
            full_response.append(token)
            yield token
    except Exception as exc:
        logger.error("stream_chat error: %s", exc)
        if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
            err_msg = "\n\n[Error: AI provider request timed out. Please check your connection and try again.]"
        elif isinstance(exc, httpx.HTTPStatusError):
            code = exc.response.status_code
            if code in (401, 403):
                err_msg = "\n\n[Error: Authentication failed with AI provider. Please verify your API key in Settings.]"
            elif code == 429:
                err_msg = "\n\n[Error: Rate limit reached for AI provider. Please wait 60 seconds before retrying.]"
            else:
                err_msg = f"\n\n[Error: AI provider returned status HTTP {code}.]"
        else:
            err_msg = "\n\n[Error: An unexpected error occurred while communicating with the AI provider.]"
        full_response.append(err_msg)
        yield err_msg


    # 2. Parse accumulated stream response for edit proposals
    response_text = "".join(full_response)
    if request.workspace:
        from ...core.paths import ensure_within_workspace, normalize_workspace
        workspace_root = normalize_workspace(request.workspace)
        for match in PROPOSAL_RE.finditer(response_text):
            filepath = match.group("path").strip()
            original = match.group("original")
            updated = match.group("updated")

            # Resolve path, reject anything that escapes the workspace
            try:
                resolved_path = ensure_within_workspace(request.workspace, filepath)
            except Exception:
                logger.warning("stream_chat: proposal path escaped workspace, skipping: %s", filepath)
                continue

            # If the file does not exist, force original to empty (pure CREATE)
            if not resolved_path.exists():
                original = ""

            # Create edit proposal
            try:
                proposal_payload = EditProposalRequest(
                    workspace=request.workspace,
                    summary=f"AI Chat proposal for {resolved_path.name}",
                    changes=[FileChange(path=str(resolved_path), original=original, updated=updated)]
                )
                proposal = await create_proposal(proposal_payload)
                yield f"\n\n[EDIT_PROPOSAL_CREATED: {proposal.id}]"
            except Exception as exc:
                logger.error("Failed to automatically create edit proposal: %s", exc)


def _get_attachment_context_text(request: ChatRequest) -> str:
    """
    Build a file-context block for the LLM from attached paths.

    SECURITY: every supplied path is validated to be inside the workspace root
    before any filesystem access.  Paths outside the workspace are silently
    skipped so the rest of the chat still works.
    """
    if not request.attached_paths:
        return ""

    if not request.workspace:
        # Without a workspace anchor we cannot safely bound-check paths.
        return ""

    from ...core.paths import ensure_within_workspace, normalize_workspace, is_within_workspace
    workspace_root = normalize_workspace(request.workspace)

    chunks: list[str] = []
    remaining = MAX_ATTACHMENT_CHARS
    for raw_path in request.attached_paths:
        # Boundary-check the supplied path
        try:
            path = ensure_within_workspace(request.workspace, raw_path)
        except Exception:
            logger.warning("_get_attachment_context_text: path rejected (outside workspace): %s", raw_path)
            continue

        if path.is_file():
            candidates = [path]
        elif path.is_dir():
            # Only recurse into files that are still within the workspace
            candidates = [
                item for item in path.rglob("*")
                if item.is_file() and is_within_workspace(workspace_root, item.resolve())
            ][:20]
        else:
            candidates = []

        for candidate in candidates:
            if remaining <= 0:
                break
            # Double-check the resolved candidate path (handles symlinks in dir rglob)
            if not is_within_workspace(workspace_root, candidate.resolve()):
                logger.warning("_get_attachment_context_text: symlink escape blocked: %s", candidate)
                continue
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
    from ...core.paths import normalize_workspace, ensure_within_workspace
    normalized_workspace = str(normalize_workspace(payload.workspace))

    # Validate and normalise each change path against the workspace boundary
    for change in payload.changes:
        try:
            change_path = ensure_within_workspace(normalized_workspace, change.path)
            # Store the canonical absolute path to avoid ambiguity
            change.path = str(change_path)
        except Exception:
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail=f"Proposal change path escapes workspace: {change.path}")
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
    db = await get_db()
    await db.execute(
        "INSERT INTO edit_proposals(id, workspace, status, payload) VALUES (?, ?, ?, ?)",
        (proposal_id, normalized_workspace, "pending", json.dumps(body)),
    )
    await db.commit()
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
    db = await get_db()
    cursor = await db.execute("SELECT * FROM edit_proposals WHERE id = ?", (proposal_id,))
    row = await cursor.fetchone()
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
        
    from ...core.paths import normalize_workspace, ensure_within_workspace
    root = normalize_workspace(proposal.workspace)
    
    # 1. Normalize line endings and merge changes
    merged_contents = {}
    for change in proposal.changes:
        # SECURITY: validate that each change path is within the workspace root,
        # even if the path stored in the DB was absolute (from an LLM-generated proposal).
        try:
            file_path = ensure_within_workspace(proposal.workspace, change.path)
        except Exception as exc:
            raise HTTPException(
                status_code=403,
                detail=f"Proposal change path escapes workspace: {change.path}"
            )

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

            if original_normalized in current_normalized:
                target_snippet = original_normalized
            elif original_stripped in current_normalized:
                target_snippet = original_stripped
            else:
                # Fuzzy fallback: match contiguous lines ignoring leading/trailing whitespace
                orig_lines = [l.strip() for l in original_stripped.splitlines() if l.strip()]
                curr_lines = current_normalized.splitlines()
                target_snippet = None
                if orig_lines:
                    for i in range(len(curr_lines) - len(orig_lines) + 1):
                        window = [curr_lines[i + j].strip() for j in range(len(orig_lines))]
                        if window == orig_lines:
                            target_snippet = "\n".join(curr_lines[i : i + len(orig_lines)])
                            break

            if target_snippet is None:
                # Require an EXACT match of the entire original block against known placeholder strings
                is_placeholder = original_stripped.lower() in KNOWN_PLACEHOLDERS
                if is_placeholder or not current_normalized.strip() or not original_stripped:
                    merged = updated_clean
                else:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Merge conflict in {change.path}: proposed original block not found in current file."
                    )
            else:
                # If target snippet appears multiple times in the file, skip to avoid ambiguous replacement
                count = current_normalized.count(target_snippet)
                if count > 1:
                    logger.warning("apply_proposal: snippet appears %d times in %s, skipping ambiguous edit", count, change.path)
                    raise HTTPException(
                        status_code=409,
                        detail=f"Merge conflict in {change.path}: proposed original block appears {count} times in file; ambiguous replacement target."
                    )
                merged = current_normalized.replace(target_snippet, updated_clean.replace("\r\n", "\n"), 1)

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
            
    db = await get_db()
    await db.execute("UPDATE edit_proposals SET status = ? WHERE id = ?", ("applied", proposal_id))
    await db.commit()
        
    # 3. Check if this proposal belongs to a pending task permission event and resume it
    cursor = await db.execute("SELECT payload FROM edit_proposals WHERE id = ?", (proposal_id,))
    row = await cursor.fetchone()
    if row and row["payload"]:
        payload = json.loads(row["payload"])
        task_id = payload.get("task_id")
        if task_id:
            from .agents import permission_state as perm_state
            if task_id in perm_state.pending_permission_events:
                perm_state.pending_permission_decisions[task_id] = "approve"
                perm_state.pending_permission_events[task_id].set()

    return await get_proposal(proposal_id)


async def reject_proposal(proposal_id: str, feedback: str | None = None) -> EditProposalDto:
    db = await get_db()
    await db.execute("UPDATE edit_proposals SET status = ? WHERE id = ?", ("rejected", proposal_id))
    await db.commit()
        
    # Check if this proposal belongs to a pending task permission event and resume it
    cursor = await db.execute("SELECT payload FROM edit_proposals WHERE id = ?", (proposal_id,))
    row = await cursor.fetchone()
    if row and row["payload"]:
        payload = json.loads(row["payload"])
        task_id = payload.get("task_id")
        if task_id:
            from .agents import permission_state as perm_state
            if task_id in perm_state.pending_permission_events:
                perm_state.pending_permission_decisions[task_id] = "reject"
                if feedback:
                    perm_state.pending_permission_feedback[task_id] = feedback
                perm_state.pending_permission_events[task_id].set()
        
    return await get_proposal(proposal_id)


async def list_proposals(workspace: str) -> list[EditProposalDto]:
    from ...core.paths import normalize_path
    normalized_workspace = str(normalize_path(workspace)).lower().replace("\\", "/").rstrip("/")
    
    db = await get_db()
    all_rows = await db.execute_fetchall("SELECT * FROM edit_proposals ORDER BY created_at DESC")
    rows = [
        r for r in all_rows 
        if str(r["workspace"]).lower().replace("\\", "/").rstrip("/") == normalized_workspace
    ]
    
    results = []
    for row in rows:
        payload = json.loads(row["payload"])
        status = row["status"]
        
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
        
    return results

