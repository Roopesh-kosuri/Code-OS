"""
chat_harness.py - Streamlined agent orchestration entrypoint for CODE OS.

Decomposed architecture:
- 100% backward-compatible re-exports from harness/ submodules
- Master `run_chat_agent()` async generator
- File size strictly under 500 lines
"""
from __future__ import annotations

import asyncio
import difflib
import json
import logging
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Literal, Optional

from app.core.paths import ensure_within_workspace, normalize_workspace
from app.core.rate_limiter import rate_limiter
from .indexing.code_intelligence import (
    CodeIntelligence,
    _build_symbol_index,
    _handle_go_to_definition,
    _handle_find_references,
    _extract_style_conventions,
    _load_style_conventions_summary,
    _find_dead_code,
    _load_architecture_doc,
    _update_architecture_doc,
    _get_structured_git_diff,
    _handle_git_diff,
    _scan_for_secrets,
    _calculate_shannon_entropy,
    SECRET_PATTERNS,
)
from .model_catalog_service import model_catalog_service
from .provider_health import provider_health_tracker
from .sandbox.executor import (
    SandboxExecutor,
    SandboxUnavailableError,
    _monitor_process_governor,
    _detect_container_runtime,
    _detect_windows_sandbox,
    _generate_wsb_config,
    _launch_windows_sandbox,
    _execute_command_async,
    _execute_command_sandboxed,
    MAX_COMMAND_TIMEOUT_SECONDS,
    MAX_COMMAND_MEMORY_BYTES,
)
from .schemas import ChatMessage, ChatRequest, EditProposalRequest, FileChange
from app.features.search.semantic_service import semantic_search
from .service import provider_for, create_proposal, PROPOSAL_RE
from .sessions.server_manager import (
    ActiveServerSession,
    ServerSessionManager,
    _active_server_sessions,
    _server_session_start,
    _server_session_request,
    _server_session_stop,
    _server_session_list,
    _cleanup_server_sessions,
    _handle_server_session,
)
from app.features.settings.service import get_api_key
from app.features.terminal.service import _build_safe_environment
from .vision_service import capture_screenshot, analyze_image_with_vlm, resolve_default_vision_model
from .artifact_auditor import audit_generated_artifact, ArtifactAuditReport
from .agents.agent_tools import (
    _handle_read_file,
    _handle_list_directory,
    _handle_search_code,
    _handle_run_test,
    parse_tool_calls,
    has_tool_calls,
    ToolCall,
    ToolResult,
    summarize_test_output,
    _clean_rel_path,
    AGENT_TOOLS,
)
from .context_service import gather_context

# -----------------------------------------------------------------------------
# 100% Backward-Compatible Re-Exports from harness/ Subpackage
# -----------------------------------------------------------------------------
from .harness import (
    MAX_AGENT_ITERATIONS,
    MAX_QUICK_TASK_ITERATIONS,
    MAX_TOOL_CALLS_PER_ITERATION,
    MAX_RETRY_BEFORE_ESCALATE,
    SEMANTIC_SEARCH_TOP_K,
    COMMAND_APPROVAL_TIMEOUT_SECONDS,
    EDIT_APPROVAL_TIMEOUT_SECONDS,
    APPROVAL_TIMEOUT_SECONDS,
    COMPACTION_THRESHOLD_TURNS,
    MAX_ACTIVITY_LOG_BYTES,
    MAX_ACTIVITY_LOG_LINES,
    MAX_ACTIVITY_LOG_FILES,
    log_and_flag_failure,
    _sse_event, _sse_status, _sse_checkpoint, _sse_token, _sse_tier_routing,
    _sse_ask_user, _sse_memory_updated, _sse_plan, _sse_approval_request,
    _sse_proposal, _sse_command_result, _sse_metrics, _sse_done, _sse_error,
    PendingApproval, PendingUserResponse,
    _pending_approvals, _pending_user_responses,
    approve_action, reject_action, respond_to_user_question, clear_all_pending,
    _get_trusted_commands_path, _load_trusted_commands, _save_trusted_command,
    _remove_trusted_command, _is_command_trusted, _is_sensitive_filename, SENSITIVE_FILE_PATTERNS,
    _ensure_git_checkpoint, undo_turn_files,
    _rotate_activity_log, _append_activity_log, _load_activity_log_tail,
    _load_activity_log, _get_interrupted_state_path, _save_interrupted_state,
    _load_interrupted_state, _clear_interrupted_state,
    _compact_conversation_history, _clean_response_text, _is_response_truncated,
    _generate_diff_summary,
    DAGPlanStep, _parse_plan, _parse_plan_dag, _replan_on_failure,
    _classify_rules, _classify_task_effort, _is_deep_query, _is_quick_task_query,
    _has_escalate_marker, _response_is_done, _declares_tool_intent,
    _extract_heuristic_tool_calls, _parse_tool_calls_extended, _has_tool_calls_extended,
    _clean_rel_path, _read_file_cached, _find_mismatch_context, _validate_smart_edit,
    _handle_append_file, _handle_list_tests, _handle_run_single_test,
    _is_command_safe, _is_command_malicious, _load_project_memory, _handle_memory_write,
    _should_audit_staged_changes, MALICIOUS_COMMAND_PATTERNS, SAFE_COMMAND_ALLOWLIST,
    SAFE_COMMAND_PREFIXES, AGENT_TOOLS, HARNESS_TOOLS, OPENAI_HARNESS_TOOLS,
    PROJECT_MEMORY_MAX_CHARS,
    _build_system_prompt, _gather_budgeted_rag_context, _discover_and_run_test_snapshot,
    _evaluate_edit_critique, _CHAT_AGENT_SYSTEM_PROMPT, _DEEP_TASK_SYSTEM_PROMPT,
    _LEAN_CHAT_SYSTEM_PROMPT, _QUICK_TASK_SYSTEM_PROMPT,
    _finalize_staged_changes,
    _escalate_to_duo,
)

# Engine Singletons
sandbox_executor = SandboxExecutor()
server_session_manager = ServerSessionManager()
code_intelligence = CodeIntelligence()

logger = logging.getLogger(__name__)

@dataclass
class ChatAgentRequest:
    """Request payload for the chat agent harness."""
    provider: str = "auto"
    model: str = ""
    base_url: str | None = None
    temperature: float = 0.2
    api_key_provider: str | None = None
    messages: list[dict] = field(default_factory=list)
    workspace: str = ""
    attached_paths: list[str] = field(default_factory=list)
    attached_images: list[dict] = field(default_factory=list)
    is_agent_mode: bool = False
    vision_model: str | None = None
    vision_provider: str | None = None
    vision_base_url: str | None = None


async def run_chat_agent(request: ChatAgentRequest) -> AsyncIterator[str]:
    """Run the complete adaptive autonomous coding agent loop, streaming typed SSE events."""
    start_time = time.time()
    total_tools_executed = 0
    workspace = request.workspace

    if not workspace:
        workspace = "."

    try:
        user_messages = [m for m in request.messages if m.get("role") == "user"]
        user_query = user_messages[-1]["content"] if user_messages else ""
        turn_number = len(user_messages) or 1

        # Phase 2: Secure URL context injection (user messages only)
        from .url_fetcher import extract_user_urls, fetch_user_url
        from app.features.settings.service import list_settings

        user_urls = []
        try:
            settings_dict = await list_settings()
            allow_links = settings_dict.get("ai.allow_link_fetch", "true").lower() != "false"
            if allow_links and user_query:
                user_urls = extract_user_urls(user_query)
        except Exception as e:
            logger.warning("Failed to check link fetch settings: %s", e)

        fetched_url_blocks = []
        for u in user_urls:
            yield _sse_status("fetching_url", f"Fetching {u}...")
            ok, target_url, content_block = await fetch_user_url(u)
            if ok:
                fetched_url_blocks.append(content_block)
            else:
                logger.info("URL fetch skipped or failed for %s: %s", target_url, content_block)

        if fetched_url_blocks:
            user_query = (
                f"{user_query}\n\n"
                f"[Web Content Context]: The following web content was fetched from the URL(s) you provided. "
                f"Use this content to answer questions, explain code, or perform tasks regarding the linked resource:\n"
                + "\n\n".join(fetched_url_blocks)
            )
            if user_messages:
                user_messages[-1]["content"] = user_query

        # ── Step 1: Adaptive Effort Routing Classifier ───────────────────────
        tier, tier_label, tier_reason = _classify_task_effort(
            user_query,
            request.attached_paths,
            request.is_agent_mode,
            has_images=bool(request.attached_images),
        )
        yield _sse_tier_routing(tier, tier_label, reason=tier_reason)
        yield _sse_status("tier_routing", f"Routing: {tier_reason}", tier=tier, label=tier_label)
        _append_activity_log(workspace, {
            "action_type": "routing",
            "target": user_query[:100],
            "outcome": "success",
            "tier": tier,
            "token_count": 0,
            "details": f"Routed to Tier {tier} ({tier_label}) - {tier_reason}",
        })

        max_iterations = 1 if tier == 0 else (MAX_QUICK_TASK_ITERATIONS if tier == 1 else MAX_AGENT_ITERATIONS)

        # ── Step 2: Context Gathering & Memory Loading ───────────────────────
        project_memory = _load_project_memory(workspace)
        rag_snippets = ""
        context: dict = {"workspace": workspace}

        if tier == 0:
            # Tier 0 Fast Answer: Skip RAG, skip heavy context gathering gate -> immediate streaming
            pass
        elif tier == 1:
            # Tier 1 Quick Task: Active file context only
            yield _sse_status("thinking", "Preparing fast task context...")
            if request.attached_paths:
                try:
                    p = ensure_within_workspace(workspace, request.attached_paths[0])
                    if p.is_file():
                        context["active_file"] = {"name": p.name, "content": _read_file_cached(p)}
                except Exception as exc:
                    log_and_flag_failure("active_file_reading", exc, {"attached_paths": request.attached_paths})
        else:
            # Tier 2 Deep Task: Full budgeted RAG with symbol search & semantic retrieval
            yield _sse_status("thinking", "Analyzing workspace and gathering budgeted grounding snippets...")
            try:
                context = await gather_context(
                    workspace=workspace,
                    active_path=request.attached_paths[0] if request.attached_paths else None,
                    open_tabs=request.attached_paths,
                    query=user_query,
                    provider_config={"provider": request.provider, "preset": request.provider},
                )
            except Exception as exc:
                logger.warning("chat_harness: gather_context failed: %s", exc)

            if user_query.strip():
                try:
                    _, rag_snippets = await _gather_budgeted_rag_context(workspace, user_query, request.attached_paths)
                except Exception as exc:
                    _, sse_warn = log_and_flag_failure("rag_context_gathering", exc, {"workspace": workspace, "query": user_query})
                    yield sse_warn

        # ── Step 3: Provider Initialization ──────────────────────────────────
        system_prompt = _build_system_prompt(workspace, tier, context, rag_snippets, project_memory)
        messages = [ChatMessage(role="system", content=system_prompt)]

        # ── Step 3b: Process Uploaded Images with Vision Model ───────────────
        image_analyses: list[str] = []
        if request.attached_images:
            v_provider = request.vision_provider or request.provider
            v_model = request.vision_model or resolve_default_vision_model(v_provider)
            v_base_url = request.vision_base_url or request.base_url
            v_api_key = (await get_api_key(v_provider)) if v_provider != "ollama" else None

            for img in request.attached_images:
                img_name = img.get("name", "uploaded_image.png")
                data_url = img.get("dataUrl", "")
                if "," in data_url:
                    header, b64 = data_url.split(",", 1)
                    fmt = "image/png"
                    if "image/jpeg" in header or "image/jpg" in header:
                        fmt = "image/jpeg"
                    elif "image/webp" in header:
                        fmt = "image/webp"
                else:
                    b64 = data_url
                    fmt = "image/png"

                if b64:
                    yield _sse_status("vision", f"Inspecting uploaded image '{img_name}' with {v_model}...", tool="take_screenshot", detail=img_name)
                    success_vlm, findings = await analyze_image_with_vlm(
                        image_base64=b64,
                        format_type=fmt,
                        question=user_query or "Describe all visible UI elements, active model/provider, open code editor, window title, and visual quality details in this image.",
                        target=img_name,
                        mode="preview",
                        provider=v_provider,
                        model=v_model,
                        base_url=v_base_url,
                        api_key=v_api_key,
                    )
                    if success_vlm:
                        image_analyses.append(f"### Visual Inspection of Uploaded Image '{img_name}':\n{findings}")

        vision_context_block = "\n\n".join(image_analyses) if image_analyses else ""

        for idx, m in enumerate(request.messages):
            # If this is the last user message and we have image analyses, augment it directly
            if idx == len(request.messages) - 1 and m.get("role") == "user" and vision_context_block:
                augmented = (
                    f"{m.get('content', '')}\n\n"
                    f"[ATTACHED IMAGE VISUAL FINDINGS]\n"
                    f"{vision_context_block}\n"
                    f"[END ATTACHED IMAGE VISUAL FINDINGS]\n\n"
                    f"Instruction: You are provided with the visual inspection of the user's uploaded image above. "
                    f"Answer the user's questions directly about what is visible in the image, its UI, active model, code editor, layout, and visual quality. "
                    f"Do NOT run filesystem tools (like list_directory) unless specifically asked to edit or create project files on disk."
                )
                messages.append(ChatMessage(role="user", content=augmented))
            else:
                messages.append(ChatMessage(role=m["role"], content=m["content"]))

        effective_prov_key = request.api_key_provider or ("nvidia-nim" if request.provider == "nvidia-nim" else request.provider)
        if effective_prov_key == "openai-compatible" and request.provider in ("groq", "gemini", "nvidia-nim", "openai", "anthropic", "deepseek", "mistral"):
            effective_prov_key = request.provider

        chat_request = ChatRequest(
            provider=request.provider,
            model=request.model,
            messages=messages,
            base_url=request.base_url,
            temperature=request.temperature,
            attached_paths=request.attached_paths,
            workspace=workspace,
            api_key_provider=request.api_key_provider,
        )

        try:
            provider = await provider_for(chat_request)
        except Exception as exc:
            yield _sse_error(f"Failed to initialize AI model provider: {exc}")
            yield _sse_done(False, f"Provider initialization failed: {exc}")
            return

        # ── Step 4: Execution Loop ───────────────────────────────────────────
        staged_changes: list[FileChange] = []
        dag_plan_steps: list[DAGPlanStep] | None = None
        current_step = 0
        consecutive_failures = 0
        consecutive_tool_failures: dict[str, int] = {}
        skipped_items: list[str] = []
        attempted_providers: set[str] = {effective_prov_key}
        prev_response_prefix: str = ""
        tools_executed_last_turn: int = 0
        intent_retried = False
        truncation_retries = 0
        idle_timeout_retries = 0
        zero_tools_retries = 0
        retry_prompt_injected_count = 0
        audit_retried = False
        read_dedup_cache: dict[tuple[str, int, int], tuple[float, int, int]] = {}

        iteration = 0
        while iteration < max_iterations:
            # ── Mid-Task Auto-Escalation Check ───────────────────────────────
            if tier == 1 and (total_tools_executed >= 4 or consecutive_failures > 0):
                logger.info("chat_harness: auto-escalating from Tier 1 to Tier 2 (tools=%d, failures=%d)", total_tools_executed, consecutive_failures)
                tier = 2
                max_iterations = MAX_AGENT_ITERATIONS
                tier_label = "Deep think"
                tier_reason = "Escalated to deep task: execution exceeded quick limits or encountered errors"
                yield _sse_tier_routing(2, tier_label, reason=tier_reason)
                yield _sse_status("tier_routing", "Escalated to deep task", tier=2, label=tier_label)
                yield _sse_status("thinking", "Escalated to deep task — loading full DAG planning and grounding...")
                if not project_memory:
                    project_memory = _load_project_memory(workspace)
                if not rag_snippets and user_query.strip():
                    try:
                        _, rag_snippets = await _gather_budgeted_rag_context(workspace, user_query, request.attached_paths)
                    except Exception as exc:
                        _, sse_warn = log_and_flag_failure("rag_context_gathering", exc, {"workspace": workspace, "query": user_query})
                        yield sse_warn
                messages[0] = ChatMessage(role="system", content=_build_system_prompt(workspace, tier, context, rag_snippets, project_memory))

            status_msg = "Rony Agent is streaming answer..." if tier == 0 else (
                "Rony Agent is thinking..." if iteration == 0 else f"Rony Agent is working (step {iteration + 1})..."
            )
            yield _sse_status("thinking", status_msg, round=iteration + 1, tier=tier)

            effective_messages = _compact_conversation_history(messages)
            full_response: list[str] = []

            # Tool availability: Tier 0 passes no tools (pure streaming answer)
            if tier >= 1:
                from ..mcp.mcp_manager import mcp_manager
                mcp_tool_defs = []
                try:
                    for t in mcp_manager.get_all_tools():
                        mcp_tool_defs.append({
                            "type": "function",
                            "function": {
                                "name": t.namespaced_name,
                                "description": f"[MCP Tool from {t.server_id}] {t.description}".strip(),
                                "parameters": t.input_schema or {"type": "object", "properties": {}},
                            }
                        })
                except Exception:
                    pass
                active_tools = OPENAI_HARNESS_TOOLS + mcp_tool_defs
            else:
                active_tools = None

            try:
                if active_tools:
                    try:
                        stream = provider.stream_chat(
                            chat_request.model,
                            effective_messages,
                            chat_request.temperature,
                            tools=active_tools,
                        )
                    except TypeError:
                        stream = provider.stream_chat(
                            chat_request.model,
                            effective_messages,
                            chat_request.temperature,
                        )
                else:
                    stream = provider.stream_chat(
                        chat_request.model,
                        effective_messages,
                        chat_request.temperature,
                    )

                # Hard per-token idle watchdog (90.0s)
                stream_iter = stream.__aiter__()
                while True:
                    try:
                        token = await asyncio.wait_for(stream_iter.__anext__(), timeout=90.0)
                        full_response.append(token)
                        yield _sse_token(token)
                    except StopAsyncIteration:
                        break
            except asyncio.TimeoutError:
                logger.warning("chat_harness: 90s hard idle watchdog fired on LLM token stream (iteration %d). Discarding partial buffer.", iteration)
                full_response.clear()
                if idle_timeout_retries == 0:
                    idle_timeout_retries += 1
                    yield _sse_status("thinking", "Generation timed out waiting for response (90s idle) — retrying with fresh prompt...")
                    messages.append(ChatMessage(
                        role="user",
                        content="The previous attempt timed out waiting for tokens. Please emit your tool calls or response concisely now without preamble."
                    ))
                    iteration += 1
                    continue
                else:
                    yield _sse_error("Provider generation timed out after 90s — server stopped responding.")
                    yield _sse_done(False, "Task stopped: Provider generation timed out after 90s.")
                    return
            except Exception as exc:
                logger.error("chat_harness: stream_chat error (iteration %d): %s", iteration, exc)
                is_429 = "429" in str(exc) or "rate limit" in str(exc).lower() or "quota" in str(exc).lower()
                is_404 = "404" in str(exc) or "not exist" in str(exc).lower() or "not found" in str(exc).lower()
                provider_health_tracker.record_outcome(effective_prov_key, success=False, error_msg=str(exc), is_429=is_429, is_404=is_404)

                # Attempt automatic fallback on 404, 429, or server outage
                attempted_providers.add(effective_prov_key)
                configured_keys = {
                    "groq": await get_api_key("groq"),
                    "gemini": await get_api_key("gemini"),
                    "nvidia-nim": await get_api_key("nvidia-nim"),
                    "openai": await get_api_key("openai"),
                    "anthropic": await get_api_key("anthropic"),
                    "deepseek": await get_api_key("deepseek"),
                    "mistral": await get_api_key("mistral"),
                }
                fallback = provider_health_tracker.find_fallback_provider(attempted_providers, configured_keys)
                if fallback and (is_429 or is_404 or "server error" in str(exc).lower() or "502" in str(exc) or "503" in str(exc) or "504" in str(exc)):
                    fb_prov, fb_model, fb_url = fallback
                    attempted_providers.add(fb_prov)
                    reason_label = "429 Rate Limit" if is_429 else ("404 Unknown Model" if is_404 else "Server Error")
                    yield _sse_status("thinking", f"Provider '{effective_prov_key}' failed ({reason_label}). Automatically falling back to {fb_prov} ({fb_model})...")
                    chat_request.provider = fb_prov
                    chat_request.model = fb_model
                    chat_request.base_url = fb_url
                    chat_request.api_key_provider = fb_prov
                    effective_prov_key = fb_prov
                    try:
                        provider = await provider_for(chat_request)
                        # Do not consume iteration count on provider switch
                        continue
                    except Exception as fb_err:
                        logger.error("Fallback provider initialization error: %s", fb_err)

                yield _sse_error(f"AI provider request error: {exc}")
                consecutive_failures += 1

                if tier == 0 or consecutive_failures >= MAX_RETRY_BEFORE_ESCALATE:
                    yield _sse_error(f"AI provider error: {exc}")
                    yield _sse_done(False, f"AI provider error ({exc}). Please check your API key/rate limits or switch models in the dropdown.")
                    return

                messages.append(ChatMessage(role="assistant", content=f"[Error: AI provider call failed: {exc}]"))
                iteration += 1
                continue


            response_text = "".join(full_response)
            messages.append(ChatMessage(role="assistant", content=response_text))

            # Record success and daily token usage
            provider_health_tracker.record_outcome(effective_prov_key, success=True)
            turn_tokens = max(1, len(response_text) // 4)
            rate_limiter.record_provider_tokens(effective_prov_key, turn_tokens)

            tokens_used = sum(len(m.content.split()) * 4 // 3 for m in messages if hasattr(m, "content") and m.content)
            _save_interrupted_state(
                workspace=workspace,
                user_query=user_query,
                tier=tier,
                iteration=iteration,
                max_iterations=max_iterations,
                messages=messages,
                dag_plan_steps=dag_plan_steps,
                staged_changes=staged_changes,
                tokens_used=tokens_used,
                tools_executed=total_tools_executed,
            )

            # Tier 0 completion: direct answer streamed
            if tier == 0:
                duration_ms = (time.time() - start_time) * 1000.0
                _clear_interrupted_state(workspace)
                _append_activity_log(workspace, {
                    "action_type": "session_done",
                    "target": user_query[:100],
                    "outcome": "success",
                    "tier": 0,
                    "token_count": tokens_used,
                    "details": "Fast path streamed answer successfully",
                })
                yield _sse_metrics(1, 0, duration_ms, tier=0, tokens_used=tokens_used)
                yield _sse_done(True, "Answer streamed successfully.")
                return

            # ── Zero-Tool Permission, Retry & Give-Up Interceptor & Repetition Breaker ────
            has_tools = _has_tool_calls_extended(response_text)
            curr_prefix = re.sub(r"\s+", " ", response_text[:200]).strip().lower()
            clean_resp_lower = response_text.strip().lower()

            is_retry_or_permission_question = bool(re.search(
                r"(?:would you like|shall i|should i|do you want me to|would you want me to|can i|may i|could i)\s+(?:me to\s+)?(?:try|create|do that|run|list|check|inspect|proceed|attempt|fix|re-run|look)\b",
                clean_resp_lower,
            )) or bool(re.search(
                r"(?:try again|retry|proceed|do that)\s*\?\s*$",
                clean_resp_lower,
            ))

            is_environmental_inquiry = bool(re.search(
                r"(?:could you please confirm|could you confirm|please provide more details|confirm if there are any specific restrictions|sufficient permissions|restrictions on directory creation)\b",
                clean_resp_lower,
            )) and not has_tools

            is_give_up_statement = bool(re.search(
                r"(?:unable to create|cannot proceed|can\'t proceed|prevent(?:s|ed)? me from creating|cannot create the|unable to proceed|fail(?:ed)? to create the folder|problem with the environment|fundamental issue with directory creation)\b",
                clean_resp_lower,
            )) and not staged_changes and not has_tools

            should_intercept_stall = (is_retry_or_permission_question or is_environmental_inquiry or is_give_up_statement)

            # Auto-recovery interceptor: if agent asks permission, asks diagnostic questions, or prematurely gives up with 0 tool calls
            if not has_tools and should_intercept_stall and retry_prompt_injected_count < 2:
                retry_prompt_injected_count += 1
                logger.info("chat_harness: intercepting zero-tool stall/permission/give-up and injecting auto-recovery directive (count=%d)", retry_prompt_injected_count)
                yield _sse_status("thinking", "Instructing agent to bypass directory creation and execute tools directly...")
                messages.append(ChatMessage(
                    role="user",
                    content=(
                        "Do not ask for permission, diagnostics, or abort. As the autonomous agent, execute your tools directly. "
                        "Remember: File-creation tools (`edit_file` with original=\"\") automatically create all parent directories on disk — a failed or timed-out `mkdir` is never blocking. "
                        "Execute the corrected approach now by staging the required files directly with their relative paths (e.g. `edit_file(path=\"src/example/App.java\", original=\"\", updated=\"...\")`) or calling tools directly."
                    )
                ))
                iteration += 1
                continue

            if prev_response_prefix and tools_executed_last_turn == 0 and not has_tools and not _response_is_done(response_text):
                is_exact_prefix = (len(curr_prefix) >= 30 and curr_prefix[:80] == prev_response_prefix[:80])
                similarity = difflib.SequenceMatcher(None, curr_prefix, prev_response_prefix).ratio() if curr_prefix and prev_response_prefix else 0.0
                if is_exact_prefix or similarity > 0.85:
                    if should_intercept_stall and retry_prompt_injected_count < 2:
                        retry_prompt_injected_count += 1
                        logger.info("chat_harness: intercepting repeated stall/permission/give-up and injecting auto-recovery directive (count=%d)", retry_prompt_injected_count)
                        yield _sse_status("thinking", "Instructing agent to bypass directory creation and execute tools directly...")
                        messages.append(ChatMessage(
                            role="user",
                            content=(
                                "Do not ask for permission, diagnostics, or abort. As the autonomous agent, execute your tools directly. "
                                "Remember: File-creation tools (`edit_file` with original=\"\") automatically create all parent directories on disk — a failed or timed-out `mkdir` is never blocking. "
                                "Execute the corrected approach now by staging the required files directly with their relative paths (e.g. `edit_file(path=\"src/example/App.java\", original=\"\", updated=\"...\")`) or calling tools directly."
                            )
                        ))
                        iteration += 1
                        continue

                    logger.warning("chat_harness: detected response repetition loop (similarity=%.2f)", similarity)
                    yield _sse_error("Execution stopped: Agent is repeating near-identical responses without taking action.")
                    yield _sse_done(False, "Stopped: Detected repeated near-identical response loop.")
                    return
            prev_response_prefix = curr_prefix

            # ── Truncation / Timeout Detection & Recovery Guard ────────────────
            if _is_response_truncated(response_text):
                if truncation_retries == 0:
                    truncation_retries += 1
                    yield _sse_status("thinking", "Response was cut off or timed out — instructing agent to chunk and shrink chunk size...")
                    messages.append(ChatMessage(
                        role="user",
                        content=(
                            "Your previous response was cut off or timed out. "
                            "Progressive Chunk Shrink Rule: Make the next chunk at most HALF the size of the one that timed out (around ~150–200 lines maximum). "
                            "Use edit_file with original='' for part 1, then use append_file for subsequent smaller chunks. "
                            "Please emit the first smaller chunk now."
                        )
                    ))
                    iteration += 1
                    continue
                else:
                    yield _sse_error("output too large for one response — chunking required")
                    yield _sse_done(False, "Task stopped: Output exceeded provider limit or timed out.")
                    return

            # ── Plan Parsing & Dynamic Tracking ──────────────────────────────
            if dag_plan_steps is None:
                parsed_dag = _parse_plan_dag(response_text)
                if parsed_dag:
                    dag_plan_steps = parsed_dag
                    current_step = 0
                    yield _sse_plan(dag_plan_steps, current_step)

            # ── Escalation Marker ────────────────────────────────────────────
            if _has_escalate_marker(response_text):
                yield _sse_status("duo_escalation", "Rony Agent requested Duo Loop adversarial refinement...")
                async for event in _escalate_to_duo(request, user_query):
                    yield event
                return

            # ── Tool Execution ───────────────────────────────────────────────
            tool_calls = _parse_tool_calls_extended(response_text) if has_tools else []

            if not tool_calls and (iteration == 0 or _declares_tool_intent(response_text)):
                heuristic_calls = _extract_heuristic_tool_calls(response_text, user_query)
                if heuristic_calls:
                    tool_calls = heuristic_calls
                    has_tools = True

            if not tool_calls and not _response_is_done(response_text) and _declares_tool_intent(response_text) and not intent_retried:
                intent_retried = True
                yield _sse_status("thinking", "Instructing Rony Agent to emit the tool call...")
                messages.append(ChatMessage(
                    role="user",
                    content="You stated intent to execute tools, but did not emit the tool block. Please emit the required [TOOL_CALL: ...] block now."
                ))
                iteration += 1
                continue

            if tool_calls:
                tools_executed_this_turn = 0
                tool_results_list: list[str] = []

                for tc in tool_calls[:MAX_TOOL_CALLS_PER_ITERATION]:
                    detail = tc.arguments.get("path") or tc.arguments.get("command") or tc.arguments.get("query") or tc.arguments.get("question") or tc.arguments.get("fact") or tc.arguments.get("target") or ""
                    try:
                        args_sig = json.dumps(tc.arguments, sort_keys=True)
                    except Exception:
                        args_sig = str(sorted(tc.arguments.items()))
                    tool_sig = f"{tc.name}:{args_sig}"

                    # Repeat-failure breaker
                    if consecutive_tool_failures.get(tool_sig, 0) >= 2:
                        skip_msg = f"Skipped after 2 failed attempts: {tc.name} ({detail})" if detail else f"Skipped after 2 failed attempts: {tc.name}"
                        yield _sse_status("tool_skipped", skip_msg, tool=tc.name, detail=detail, reason="Failed twice consecutively")
                        skip_desc = f"{tc.name} ({detail})" if detail else tc.name
                        if skip_desc not in skipped_items:
                            skipped_items.append(skip_desc)
                        result = ToolResult(
                            tool_name=tc.name,
                            success=False,
                            output="",
                            error=f"Tool call skipped: signature {tc.name} failed twice in a row."
                        )
                        tool_results_list.append(f"[TOOL_RESULT: {tc.name}]\nSKIPPED: {result.error}\n[/TOOL_RESULT]")
                        continue

                    # Execute tool
                    status_desc = f"Running {tc.name}..." if not detail else f"Executing {tc.name} on {detail}..."
                    if tc.name == "read_file":
                        status_desc = f"Reading {detail}..."
                    elif tc.name == "list_tests":
                        status_desc = "Discovering test suite (pytest --collect-only)..."
                    elif tc.name == "run_single_test":
                        status_desc = f"Running test case: {detail}..."
                    elif tc.name == "edit_file":
                        status_desc = f"Staging edit for {detail}..."
                    elif tc.name == "append_file":
                        status_desc = f"Appending chunk to {detail}..."
                    elif tc.name == "search_code" or tc.name == "semantic_search":
                        status_desc = f"Searching for '{detail}'..."
                    elif tc.name == "run_test":
                        status_desc = f"Running tests: {detail}..."
                    elif tc.name == "memory_write":
                        status_desc = f"Saving preference: '{detail}'..."
                    elif tc.name == "ask_user":
                        status_desc = f"Asking user: '{detail}'..."
                    elif tc.name == "find_references":
                        status_desc = f"Finding references for symbol '{detail}'..."
                    elif tc.name == "go_to_definition":
                        status_desc = f"Locating definition for symbol '{detail}'..."
                    elif tc.name == "server_session":
                        status_desc = f"Managing server session ({tc.arguments.get('action', 'start')})..."
                    elif tc.name == "git_diff":
                        status_desc = "Inspecting structured git diff..."
                    elif tc.name == "find_dead_code":
                        status_desc = "Scanning for unreferenced / orphaned files..."
                    elif tc.name == "update_architecture_doc":
                        status_desc = "Refreshing ARCHITECTURE.md..."
                    elif tc.name.startswith("mcp__"):
                        status_desc = f"Executing MCP tool: {tc.name}..."

                    yield _sse_status("tool", status_desc, tool=tc.name, detail=detail)

                    if tc.name == "list_tests":
                        result = _handle_list_tests(workspace, tc.arguments)
                    elif tc.name == "run_single_test":
                        result = _handle_run_single_test(workspace, tc.arguments)
                    elif tc.name == "memory_write":
                        success_m, msg_m = _handle_memory_write(workspace, tc.arguments)
                        result = ToolResult(tool_name="memory_write", success=success_m, output=msg_m if success_m else "", error="" if success_m else msg_m)
                        if success_m:
                            yield _sse_memory_updated(tc.arguments.get("fact") or tc.arguments.get("memory") or "")
                    elif tc.name == "find_references":
                        result = _handle_find_references(workspace, tc.arguments)
                    elif tc.name == "go_to_definition":
                        result = _handle_go_to_definition(workspace, tc.arguments)
                    elif tc.name == "server_session":
                        result = _handle_server_session(workspace, tc.arguments)
                    elif tc.name == "git_diff":
                        result = _handle_git_diff(workspace, tc.arguments)
                    elif tc.name == "find_dead_code":
                        result = _find_dead_code(workspace, tc.arguments.get("paths"))
                    elif tc.name == "update_architecture_doc":
                        result = _update_architecture_doc(workspace, tc.arguments.get("reason") or "Manual tool invocation")
                    elif tc.name.startswith("mcp__"):
                        parts = tc.name.split("__")
                        server_id = parts[1] if len(parts) >= 2 else "unknown"
                        raw_tool_name = "__".join(parts[2:]) if len(parts) >= 3 else tc.name

                        from ..mcp.mcp_manager import mcp_manager
                        from ...workspaces.trust_service import get_workspace_trust
                        trust = await get_workspace_trust(workspace)
                        is_trusted = trust.get("trusted", False)

                        instance = mcp_manager.instances.get(server_id)
                        tool_def = next((t for t in (instance.tools if instance else []) if t.name == raw_tool_name), None)
                        is_read_only = tool_def.read_only if tool_def else False

                        if not is_trusted and not is_read_only:
                            restricted_err = f"Workspace is in Restricted Mode. Mutating MCP tool '{tc.name}' is blocked."
                            yield _sse_status("tool_error", restricted_err, tool=tc.name)
                            result = ToolResult(
                                tool_name=tc.name,
                                success=False,
                                output="",
                                error=restricted_err,
                                failure_reason="restricted_mode_blocked",
                                failure_detail=restricted_err
                            )
                        else:
                            auto_approved = is_read_only and (instance.config.auto_approve_read_only if instance else False)

                            if auto_approved:
                                yield _sse_status("tool", f"[MCP: {server_id}] Executing {raw_tool_name} (auto-approved)...", tool=tc.name)
                                try:
                                    raw_res = await mcp_manager.call_tool(tc.name, tc.arguments)
                                    text_content = "\n".join(c.get("text", "") for c in raw_res.get("content", []) if isinstance(c, dict))
                                    wrapped_output = f'<untrusted_mcp_content server="{server_id}" tool="{raw_tool_name}">\n{text_content}\n</untrusted_mcp_content>'
                                    result = ToolResult(
                                        tool_name=tc.name,
                                        success=not raw_res.get("is_error", False),
                                        output=wrapped_output,
                                        error="" if not raw_res.get("is_error", False) else text_content
                                    )
                                except Exception as exc:
                                    result = ToolResult(tool_name=tc.name, success=False, output="", error=str(exc))
                            else:
                                action_id = str(uuid.uuid4())
                                pending_mcp = PendingApproval(
                                    action_id=action_id,
                                    action_type="mcp",
                                    detail=f"{server_id}:{raw_tool_name}",
                                    reason=f"MCP Tool Execution ({tc.name})",
                                    workspace=workspace,
                                    command=tc.name
                                )
                                _pending_approvals[action_id] = pending_mcp

                                yield _sse_approval_request(
                                    action_id=action_id,
                                    action_type="mcp",
                                    detail=f"{server_id}:{raw_tool_name}",
                                    reason=pending_mcp.reason,
                                    command=tc.name
                                )
                                try:
                                    await asyncio.wait_for(pending_mcp.event.wait(), timeout=COMMAND_APPROVAL_TIMEOUT_SECONDS)
                                    if pending_mcp.approved:
                                        yield _sse_status("tool", f"[MCP: {server_id}] Approved: Executing {raw_tool_name}...", tool=tc.name)
                                        raw_res = await mcp_manager.call_tool(tc.name, tc.arguments)
                                        text_content = "\n".join(c.get("text", "") for c in raw_res.get("content", []) if isinstance(c, dict))
                                        wrapped_output = f'<untrusted_mcp_content server="{server_id}" tool="{raw_tool_name}">\n{text_content}\n</untrusted_mcp_content>'
                                        result = ToolResult(
                                            tool_name=tc.name,
                                            success=not raw_res.get("is_error", False),
                                            output=wrapped_output,
                                            error="" if not raw_res.get("is_error", False) else text_content
                                        )
                                    else:
                                        denied_msg = f"MCP Tool '{tc.name}' was rejected by user."
                                        yield _sse_status("tool", denied_msg, tool=tc.name)
                                        result = ToolResult(tool_name=tc.name, success=False, output="", error=denied_msg, failure_reason="user_denied", failure_detail=denied_msg)
                                except asyncio.TimeoutError:
                                    timeout_msg = f"Approval card timed out for MCP tool: {tc.name}."
                                    yield _sse_status("tool_error", timeout_msg, tool=tc.name)
                                    result = ToolResult(tool_name=tc.name, success=False, output="", error=timeout_msg, failure_reason="approval_timeout", failure_detail=timeout_msg)
                                finally:
                                    _pending_approvals.pop(action_id, None)
                    elif tc.name == "ask_user":
                        q_text = str(tc.arguments.get("question") or "Please select an option:")
                        opts = tc.arguments.get("options")
                        if not isinstance(opts, list) or not opts:
                            opts = ["Yes, proceed", "No, cancel"]
                        action_id = str(uuid.uuid4())
                        pending_u = PendingUserResponse(action_id=action_id, question=q_text, options=[str(o) for o in opts])
                        _pending_user_responses[action_id] = pending_u
                        yield _sse_ask_user(action_id, q_text, [str(o) for o in opts])
                        yield _sse_status("ask_user", f"Waiting for user input: {q_text}", action_id=action_id)
                        try:
                            await asyncio.wait_for(pending_u.event.wait(), timeout=APPROVAL_TIMEOUT_SECONDS)
                            user_ans = pending_u.selected_option or opts[0]
                            yield _sse_status("tool", f"User selected: '{user_ans}'", tool="ask_user")
                            result = ToolResult(tool_name="ask_user", success=True, output=f"User selected: {user_ans}", error="")
                        except asyncio.TimeoutError:
                            result = ToolResult(tool_name="ask_user", success=False, output="", error="User clarifying question timed out after 120s.")
                        finally:
                            _pending_user_responses.pop(action_id, None)
                    elif tc.name == "edit_file":
                        valid, err, change = _validate_smart_edit(workspace, tc.arguments)
                        if valid and change:
                            existing_idx = next((i for i, c in enumerate(staged_changes) if c.path == change.path), None)
                            if existing_idx is not None:
                                staged_changes[existing_idx] = change
                            else:
                                staged_changes.append(change)
                            result = ToolResult(
                                tool_name="edit_file",
                                success=True,
                                output=f"Staged modification for '{change.path}'.",
                                error=""
                            )
                        else:
                            result = ToolResult(tool_name="edit_file", success=False, output="", error=err)
                    elif tc.name == "append_file":
                        valid, err, change = _handle_append_file(workspace, tc.arguments, staged_changes)
                        if valid and change:
                            result = ToolResult(
                                tool_name="append_file",
                                success=True,
                                output=f"Appended chunk to '{change.path}' (total {len(change.updated.splitlines())} lines).",
                                error=""
                            )
                        else:
                            result = ToolResult(tool_name="append_file", success=False, output="", error=err)
                    elif tc.name == "read_file":
                        raw_path = tc.arguments.get("path", "")
                        rel_path = _clean_rel_path(raw_path)
                        try:
                            start_line = max(1, int(tc.arguments.get("start_line", 1) or 1))
                        except (ValueError, TypeError):
                            start_line = 1
                        try:
                            limit = min(max(1, int(tc.arguments.get("limit", 250) or 250)), 500)
                        except (ValueError, TypeError):
                            limit = 250
                        cache_key = (rel_path, start_line, limit)

                        target_stat = None
                        try:
                            target_file = ensure_within_workspace(workspace, rel_path)
                            if target_file.is_file():
                                st = target_file.stat()
                                target_stat = (st.st_mtime, st.st_size)
                        except Exception:
                            target_stat = None

                        if target_stat and cache_key in read_dedup_cache:
                            cached_mtime, cached_size, cached_turn = read_dedup_cache[cache_key]
                            if cached_mtime == target_stat[0] and cached_size == target_stat[1]:
                                receipt_output = (
                                    f"=== FILE: {rel_path} (Lines {start_line}) ===\n"
                                    f"(unchanged since turn {cached_turn} — refer to earlier full read)"
                                )
                                result = ToolResult(
                                    tool_name="read_file",
                                    success=True,
                                    output=receipt_output,
                                    error="",
                                )
                            else:
                                result = _handle_read_file(workspace, tc.arguments)
                                if result.success and target_stat:
                                    read_dedup_cache[cache_key] = (target_stat[0], target_stat[1], iteration + 1)
                        else:
                            result = _handle_read_file(workspace, tc.arguments)
                            if result.success and target_stat:
                                read_dedup_cache[cache_key] = (target_stat[0], target_stat[1], iteration + 1)
                    elif tc.name == "list_directory":
                        result = _handle_list_directory(workspace, tc.arguments)
                    elif tc.name == "search_code":
                        result = _handle_search_code(workspace, tc.arguments)
                    elif tc.name == "semantic_search":
                        q = tc.arguments.get("query", "")
                        sem_matches = await semantic_search(workspace, q, limit=5)
                        if sem_matches:
                            out_lines = [f"- {m.get('relative_path', m.get('path'))} (score: {m.get('score', 0):.2f})" for m in sem_matches]
                            result = ToolResult(tool_name="semantic_search", success=True, output="Semantic matches:\n" + "\n".join(out_lines))
                        else:
                            result = ToolResult(tool_name="semantic_search", success=True, output="No semantic matches found.")

                    elif tc.name in ("take_screenshot", "inspect_visuals", "vision_inspect"):
                        mode = str(tc.arguments.get("mode") or "preview").lower().strip()
                        target = str(tc.arguments.get("target") or tc.arguments.get("path") or tc.arguments.get("url") or "").strip()
                        question = str(tc.arguments.get("question") or tc.arguments.get("prompt") or "Describe visual layout, navigation, and any broken or overlapping elements.").strip()
                        
                        target_label = target or ("CODE OS App Window" if mode == "app_window" else "HTML Preview")
                        yield _sse_status("vision", f"Capturing visual rendering ({mode}: {target_label})...", tool="take_screenshot", detail=f"{target_label} | {question[:60]}")
                        
                        success_cap, img_data, fmt = await capture_screenshot(mode=mode, target=target, workspace=workspace)
                        if not success_cap:
                            result = ToolResult(
                                tool_name="take_screenshot",
                                success=False,
                                output="",
                                error=f"Screenshot capture failed: {img_data}"
                            )
                        else:
                            v_provider = request.vision_provider or request.provider
                            v_model = request.vision_model or resolve_default_vision_model(v_provider)
                            v_base_url = request.vision_base_url or request.base_url
                            v_api_key = (await get_api_key(v_provider)) if v_provider != "ollama" else None
                            
                            yield _sse_status("vision", f"Inspecting with Vision model ({v_model})...", tool="take_screenshot", detail=f"Question: {question[:60]}")
                            
                            success_vlm, findings = await analyze_image_with_vlm(
                                image_base64=img_data,
                                format_type=fmt,
                                question=question,
                                target=target,
                                mode=mode,
                                provider=v_provider,
                                model=v_model,
                                base_url=v_base_url,
                                api_key=v_api_key,
                            )
                            
                            if success_vlm:
                                yield _sse_status("vision", f"Visual analysis complete: {findings[:80]}...", tool="take_screenshot", detail=f"Q: {question} | A: {findings[:120]}")
                                result = ToolResult(
                                    tool_name="take_screenshot",
                                    success=True,
                                    output=f"=== VISUAL INSPECTION RESULT ({mode} mode, target: '{target_label}') ===\nQuestion Asked: {question}\n\nVisual Analysis Findings:\n{findings}",
                                    error=""
                                )
                            else:
                                result = ToolResult(
                                    tool_name="take_screenshot",
                                    success=False,
                                    output="",
                                    error=f"Vision model analysis failed: {findings}"
                                )
                    elif tc.name == "run_test":
                        cmd = tc.arguments.get("command") or tc.arguments.get("test_path") or "pytest"
                        result = await _execute_command_async(workspace, cmd)
                        _append_activity_log(workspace, {
                            "action_type": "command_run",
                            "target": cmd,
                            "outcome": "success" if result.success else "failed",
                            "tier": tier,
                            "token_count": 0,
                            "details": result.output[:200] if result.success else result.error[:200],
                        })
                    elif tc.name == "run_command":
                        cmd = tc.arguments.get("command", "")
                        require_sandbox = bool(tc.arguments.get("require_sandbox", False) or tc.arguments.get("sandboxed", False))
                        caps = _detect_container_runtime()

                        # Step 1: Pre-Execution Semantic Policy Filter (Prompt Injection Defense)
                        if _is_command_malicious(cmd):
                            policy_err = "Command blocked by security policy: potential code injection detected."
                            logger.warning("chat_harness: Malicious command rejected by security policy: %s", cmd)
                            yield _sse_status("tool_skipped", policy_err, tool="run_command", command=cmd)
                            yield _sse_command_result(cmd, policy_err, exit_code=1, success=False, reason="security_policy_blocked")
                            _append_activity_log(workspace, {
                                "action_type": "security_policy_blocked",
                                "target": cmd,
                                "outcome": "blocked",
                                "tier": tier,
                                "token_count": 0,
                                "details": policy_err,
                            })
                            result = ToolResult(
                                tool_name="run_command",
                                success=False,
                                output="",
                                error=json.dumps({
                                    "reason": "security_policy_blocked",
                                    "detail": policy_err,
                                    "command": cmd,
                                }),
                                failure_reason="security_policy_blocked",
                                failure_detail=policy_err,
                            )
                        elif require_sandbox:
                            # User or tool requested strict container sandbox execution (fail-closed)
                            try:
                                yield _sse_status("tool", f"[Container Sandbox] Running command: {cmd}", tool="run_command", command=cmd, sandboxed=True)
                                result = await _execute_command_sandboxed(workspace, cmd)
                                if not result.success:
                                    yield _sse_command_result(cmd, result.failure_detail or result.error, exit_code=1, success=False, reason=result.failure_reason or "exit_code")
                            except SandboxUnavailableError as exc:
                                logger.error("chat_harness: Sandbox unavailable: %s", exc)
                                yield _sse_error(str(exc))
                                yield _sse_command_result(cmd, str(exc), exit_code=1, success=False, reason="sandbox_unavailable")
                                result = ToolResult(
                                    tool_name="run_command",
                                    success=False,
                                    output="",
                                    error=json.dumps({
                                        "reason": "sandbox_unavailable",
                                        "detail": str(exc),
                                        "command": cmd,
                                    }),
                                    failure_reason="sandbox_unavailable",
                                    failure_detail=str(exc),
                                )
                        elif _is_command_trusted(workspace, cmd):
                            yield _sse_status("tool", f"[Trusted] Running command: {cmd}", tool="run_command", command=cmd, trusted=True)
                            result = await _execute_command_async(workspace, cmd)
                            if not result.success:
                                yield _sse_command_result(cmd, result.failure_detail or result.error, exit_code=1, success=False, reason=result.failure_reason or "exit_code")
                        elif _is_command_safe(cmd, workspace):
                            result = await _execute_command_async(workspace, cmd)
                            if not result.success:
                                yield _sse_command_result(cmd, result.failure_detail or result.error, exit_code=1, success=False, reason=result.failure_reason or "exit_code")
                        else:
                            action_id = str(uuid.uuid4())
                            is_native_fallback = not caps.get("docker_available")
                            reason_text = (
                                f"Container runtime unavailable. Run on host instead? (Less secure): `{cmd}`"
                                if is_native_fallback
                                else f"Terminal command is not on the safe read-only allowlist: `{cmd}`"
                            )
                            pending = PendingApproval(
                                action_id=action_id,
                                action_type="command",
                                detail=cmd,
                                reason=reason_text,
                                workspace=workspace,
                                command=cmd,
                                is_native_fallback=is_native_fallback,
                            )
                            _pending_approvals[action_id] = pending
                            yield _sse_approval_request(
                                action_id=action_id,
                                action_type="command",
                                detail=cmd,
                                reason=pending.reason,
                                command=cmd,
                                is_native_fallback=is_native_fallback,
                            )
                            yield _sse_status("approval_required", f"Approval needed to run: {cmd}", command=cmd)

                            try:
                                await asyncio.wait_for(pending.event.wait(), timeout=COMMAND_APPROVAL_TIMEOUT_SECONDS)
                                if pending.approved:
                                    yield _sse_status("tool", f"Approved: Running {cmd} on host...", tool="run_command", command=cmd)
                                    result = await _execute_command_async(workspace, cmd)
                                    if not result.success:
                                        yield _sse_command_result(cmd, result.failure_detail or result.error, exit_code=1, success=False, reason=result.failure_reason or "exit_code")
                                else:
                                    denied_msg = f"Command '{cmd}' was rejected by user."
                                    yield _sse_status("tool", f"Denied: Execution of {cmd} was rejected by user.", tool="run_command")
                                    yield _sse_command_result(cmd, denied_msg, exit_code=1, success=False, reason="user_denied")
                                    result = ToolResult(
                                        tool_name="run_command",
                                        success=False,
                                        output="",
                                        error=json.dumps({"reason": "user_denied", "detail": denied_msg, "command": cmd}),
                                        failure_reason="user_denied",
                                        failure_detail=denied_msg,
                                    )
                            except asyncio.TimeoutError:
                                # Approval-timeout re-issue once with specific reminder
                                _pending_approvals.pop(action_id, None)
                                yield _sse_status("approval_required", "Waiting on your approval — click Approve/Deny on the card above the input.", command=cmd)

                                action_id2 = str(uuid.uuid4())
                                pending2 = PendingApproval(
                                    action_id=action_id2,
                                    action_type="command",
                                    detail=cmd,
                                    reason=reason_text,
                                    workspace=workspace,
                                    command=cmd,
                                    is_native_fallback=is_native_fallback,
                                )
                                _pending_approvals[action_id2] = pending2
                                yield _sse_approval_request(
                                    action_id=action_id2,
                                    action_type="command",
                                    detail=cmd,
                                    reason=pending2.reason,
                                    command=cmd,
                                    is_native_fallback=is_native_fallback,
                                )

                                try:
                                    await asyncio.wait_for(pending2.event.wait(), timeout=COMMAND_APPROVAL_TIMEOUT_SECONDS)
                                    if pending2.approved:
                                        yield _sse_status("tool", f"Approved: Running {cmd} on host...", tool="run_command", command=cmd)
                                        result = await _execute_command_async(workspace, cmd)
                                        if not result.success:
                                            yield _sse_command_result(cmd, result.failure_detail or result.error, exit_code=1, success=False, reason=result.failure_reason or "exit_code")
                                    else:
                                        denied_msg = f"Command '{cmd}' was rejected by user."
                                        yield _sse_status("tool", f"Denied: Execution of {cmd} was rejected by user.", tool="run_command")
                                        yield _sse_command_result(cmd, denied_msg, exit_code=1, success=False, reason="user_denied")
                                        result = ToolResult(
                                            tool_name="run_command",
                                            success=False,
                                            output="",
                                            error=json.dumps({"reason": "user_denied", "detail": denied_msg, "command": cmd}),
                                            failure_reason="user_denied",
                                            failure_detail=denied_msg,
                                        )
                                except asyncio.TimeoutError:
                                    app_timeout_msg = f"Approval card timed out after {int(COMMAND_APPROVAL_TIMEOUT_SECONDS)}s — command NOT executed."
                                    yield _sse_status("tool_error", app_timeout_msg, tool="run_command", command=cmd, reason="approval_timeout")
                                    yield _sse_command_result(cmd, app_timeout_msg, exit_code=1, success=False, reason="approval_timeout")
                                    result = ToolResult(
                                        tool_name="run_command",
                                        success=False,
                                        output="",
                                        error=json.dumps({
                                            "reason": "approval_timeout",
                                            "detail": app_timeout_msg,
                                            "command": cmd,
                                        }),
                                        failure_reason="approval_timeout",
                                        failure_detail=app_timeout_msg,
                                    )
                                finally:
                                    _pending_approvals.pop(action_id2, None)
                            finally:
                                _pending_approvals.pop(action_id, None)

                        _append_activity_log(workspace, {
                            "action_type": "command_run",
                            "target": cmd,
                            "outcome": "success" if result.success else "failed",
                            "tier": tier,
                            "token_count": 0,
                            "details": result.output[:200] if result.success else result.error[:200],
                        })
                    else:
                        result = ToolResult(tool_name=tc.name, success=False, output="", error=f"Unknown tool '{tc.name}'")

                    total_tools_executed += 1
                    tools_executed_this_turn += 1

                    if result.success:
                        consecutive_tool_failures.pop(tool_sig, None)
                    else:
                        consecutive_tool_failures[tool_sig] = consecutive_tool_failures.get(tool_sig, 0) + 1
                        # Re-plan if DAG step failed
                        if dag_plan_steps and current_step < len(dag_plan_steps):
                            dag_plan_steps = _replan_on_failure(dag_plan_steps, current_step, result.error)
                            yield _sse_status("replan", f"Re-planning: {result.error[:60]}")
                            yield _sse_plan(dag_plan_steps, current_step)

                    if result.success:
                        tool_results_list.append(f"[TOOL_RESULT: {tc.name}]\n{result.output}\n[/TOOL_RESULT]")
                    else:
                        tool_results_list.append(f"[TOOL_RESULT: {tc.name}]\nERROR: {result.error}\n[/TOOL_RESULT]")

                tools_executed_last_turn = tools_executed_this_turn
                tool_results_text = "\n\n".join(tool_results_list)

                # Advance DAG plan step if successful
                if dag_plan_steps and current_step < len(dag_plan_steps):
                    dag_plan_steps[current_step].status = "done"
                    current_step = min(current_step + 1, len(dag_plan_steps) - 1)
                    if current_step < len(dag_plan_steps) and dag_plan_steps[current_step].status == "pending":
                        dag_plan_steps[current_step].status = "running"
                    yield _sse_plan(dag_plan_steps, current_step)

                # Check if turn completed with [DONE]
                clean_prose = _clean_response_text(response_text)
                if _response_is_done(response_text) and (clean_prose or staged_changes):
                    # Quality gate audit check
                    if staged_changes and _should_audit_staged_changes(staged_changes, user_query) and not audit_retried:
                        audit_reports = [audit_generated_artifact(c.updated, c.path) for c in staged_changes]
                        if any(r.has_errors for r in audit_reports):
                            audit_retried = True
                            yield _sse_status("audit", "Running structural audit on generated artifact — detected issues needing repair...")
                            feedback_lines = ["Structural audit detected errors in staged artifact(s):"]
                            for r in audit_reports:
                                for f in r.findings:
                                    if f.severity == "error":
                                        feedback_lines.append(f"- [{r.file_path}] {f.message} (Line {f.line_number or 'N/A'})")
                            feedback_lines.append("Please stage an edit to fix these errors before outputting [DONE].")
                            messages.append(ChatMessage(role="user", content="\n".join(feedback_lines)))
                            iteration += 1
                            continue
                        else:
                            yield _sse_status("audit", "✓ Post-generation structural audit passed cleanly.")

                    async for event in _finalize_staged_changes(staged_changes, workspace, tier, turn_number=turn_number, user_query=user_query):
                        yield event
                    duration_ms = (time.time() - start_time) * 1000.0
                    tokens_used = sum(len(m.content.split()) * 4 // 3 for m in messages if hasattr(m, "content") and m.content)
                    _clear_interrupted_state(workspace)
                    _append_activity_log(workspace, {
                        "action_type": "session_done",
                        "target": user_query[:100],
                        "outcome": "success",
                        "tier": tier,
                        "token_count": tokens_used,
                        "details": f"Completed in {iteration + 1} iterations, {total_tools_executed} tools",
                    })
                    yield _sse_metrics(iteration + 1, total_tools_executed, duration_ms, tier=tier, tokens_used=tokens_used)
                    yield _sse_done(True, "All tasks completed and verified successfully.")
                    return

                has_any_error = any("ERROR:" in tr for tr in tool_results_list)
                error_recovery_note = (
                    "\n\n[RECOVERY DIRECTIVE]\n"
                    "One or more tool calls encountered an error. Remember:\n"
                    "1. One step failing NEVER aborts the overall task. Adapt and continue with the next step.\n"
                    "2. If `mkdir` or a folder command failed/timed out, DO NOT keep retrying `mkdir` with different names. "
                    "File-creation tools (`edit_file` with original=\"\") automatically create all parent directories on disk — "
                    "stage the file directly with its subfolder path (e.g. `edit_file(path=\"folder/File.java\", original=\"\", updated=\"...\")`) and the directory will be created.\n"
                    "3. If a command failed due to unquoted spaces, wrap all path arguments in double quotes.\n"
                    "4. Do NOT ask 'Shall I try again?' — immediately emit the tool call for the corrected approach."
                    if has_any_error else ""
                )

                messages.append(ChatMessage(
                    role="user",
                    content=(
                        f"Tool observation results:\n\n{tool_results_text}{error_recovery_note}\n\n"
                        "Inspect the results above and directly answer the user's question or continue executing the next required step. If all tasks or checks are complete, summarize the outcome and output [DONE]."
                    )
                ))
                iteration += 1
                continue

            # ── Done Marker Check ────────────────────────────────────────────
            if _response_is_done(response_text):
                clean_prose = _clean_response_text(response_text)
                if not clean_prose and total_tools_executed > 0:
                    messages.append(ChatMessage(
                        role="user",
                        content="Answer the user's question directly in plain language using the tool observation results above."
                    ))
                    try:
                        stream = provider.stream_chat(chat_request.model, _compact_conversation_history(messages), chat_request.temperature)
                        async for token in stream:
                            yield _sse_token(token)
                    except Exception as exc:
                        _, sse_warn = log_and_flag_failure("model_streaming", exc, {"model": chat_request.model})
                        yield sse_warn

                # Quality gate audit check
                if staged_changes and _should_audit_staged_changes(staged_changes, user_query) and not audit_retried:
                    audit_reports = [audit_generated_artifact(c.updated, c.path) for c in staged_changes]
                    if any(r.has_errors for r in audit_reports):
                        audit_retried = True
                        yield _sse_status("audit", "Running structural audit on generated artifact — detected issues needing repair...")
                        feedback_lines = ["Structural audit detected errors in staged artifact(s):"]
                        for r in audit_reports:
                            for f in r.findings:
                                if f.severity == "error":
                                    feedback_lines.append(f"- [{r.file_path}] {f.message} (Line {f.line_number or 'N/A'})")
                        feedback_lines.append("Please stage an edit to fix these errors before outputting [DONE].")
                        messages.append(ChatMessage(role="user", content="\n".join(feedback_lines)))
                        iteration += 1
                        continue
                    else:
                        yield _sse_status("audit", "✓ Post-generation structural audit passed cleanly.")

                # Honest completion guard: If generation query produced nothing
                if _is_deep_query(user_query.lower(), request.attached_paths) and not staged_changes and total_tools_executed == 0:
                    if zero_tools_retries == 0:
                        zero_tools_retries += 1
                        yield _sse_status("thinking", "Plan registered. Prompting agent to emit execution tool calls for Step 1...")
                        messages.append(ChatMessage(
                            role="user",
                            content="Plan registered. Please proceed immediately to execute Step 1 by emitting the required tool calls (e.g. edit_file or run_command). Do not output plain conversational prose."
                        ))
                        iteration += 1
                        continue
                    else:
                        yield _sse_error("Nothing was generated for requested artifact. Agent emitted prose instead of tool calls.")
                        yield _sse_done(False, "Task failed: Nothing was generated for requested artifact.")
                        return

                async for event in _finalize_staged_changes(staged_changes, workspace, tier, turn_number=turn_number, user_query=user_query):
                    yield event

                duration_ms = (time.time() - start_time) * 1000.0
                tokens_used = sum(len(m.content.split()) * 4 // 3 for m in messages if hasattr(m, "content") and m.content)
                _clear_interrupted_state(workspace)
                _append_activity_log(workspace, {
                    "action_type": "session_done",
                    "target": user_query[:100],
                    "outcome": "success",
                    "tier": tier,
                    "token_count": tokens_used,
                    "details": f"Completed in {iteration + 1} iterations, {total_tools_executed} tools",
                })
                yield _sse_metrics(iteration + 1, total_tools_executed, duration_ms, tier=tier, tokens_used=tokens_used)
                yield _sse_done(True, "All tasks completed and verified successfully.")
                return

            if not has_tools:
                tools_executed_last_turn = 0
                if _is_deep_query(user_query.lower(), request.attached_paths) and not staged_changes and total_tools_executed == 0:
                    if zero_tools_retries == 0:
                        zero_tools_retries += 1
                        yield _sse_status("thinking", "Plan registered. Prompting agent to emit execution tool calls for Step 1...")
                        messages.append(ChatMessage(
                            role="user",
                            content="Plan registered. Please proceed immediately to execute Step 1 by emitting the required tool calls (e.g. edit_file or run_command). Do not output plain conversational prose."
                        ))
                        iteration += 1
                        continue
                    else:
                        yield _sse_error("Nothing was generated for requested artifact. Agent emitted prose instead of tool calls.")
                        yield _sse_done(False, "Task failed: Nothing was generated for requested artifact.")
                        return

                async for event in _finalize_staged_changes(staged_changes, workspace, tier, turn_number=turn_number, user_query=user_query):
                    yield event

                duration_ms = (time.time() - start_time) * 1000.0
                tokens_used = sum(len(m.content.split()) * 4 // 3 for m in messages if hasattr(m, "content") and m.content)
                _clear_interrupted_state(workspace)
                _append_activity_log(workspace, {
                    "action_type": "session_done",
                    "target": user_query[:100],
                    "outcome": "success",
                    "tier": tier,
                    "token_count": tokens_used,
                    "details": f"Completed in {iteration + 1} iterations, {total_tools_executed} tools",
                })
                yield _sse_metrics(iteration + 1, total_tools_executed, duration_ms, tier=tier, tokens_used=tokens_used)
                yield _sse_done(True)
                return

            iteration += 1

        # Cap reached — honest partial report
        if tier == 0:
            duration_ms = (time.time() - start_time) * 1000.0
            tokens_used = sum(len(m.content.split()) * 4 // 3 for m in messages if hasattr(m, "content") and m.content)
            _clear_interrupted_state(workspace)
            yield _sse_metrics(1, total_tools_executed, duration_ms, tier=0, tokens_used=tokens_used)
            yield _sse_done(False, "Fast answer could not be generated. Please try again or switch model in the dropdown.")
            return

        async for event in _finalize_staged_changes(staged_changes, workspace, tier, turn_number=turn_number, user_query=user_query):
            yield event

        duration_ms = (time.time() - start_time) * 1000.0
        tokens_used = sum(len(m.content.split()) * 4 // 3 for m in messages if hasattr(m, "content") and m.content)
        _clear_interrupted_state(workspace)
        _append_activity_log(workspace, {
            "action_type": "session_done",
            "target": user_query[:100],
            "outcome": "partial",
            "tier": tier,
            "token_count": tokens_used,
            "details": f"Iteration limit ({max_iterations}) reached",
        })
        yield _sse_metrics(max_iterations, total_tools_executed, duration_ms, tier=tier, tokens_used=tokens_used)

        report_lines = [
            f"Rony Agent reached iteration limit ({max_iterations}). Partial progress report:",
            "Completed Items:",
        ]
        completed_list: list[str] = []
        if staged_changes:
            for c in staged_changes:
                c_desc = f"Staged changes for '{c.path}' ({len(c.updated.splitlines())} lines)"
                report_lines.append(f"  ✓ {c_desc}")
                completed_list.append(c_desc)
        elif total_tools_executed > 0:
            c_desc = f"Executed {total_tools_executed} tool action(s)"
            report_lines.append(f"  ✓ {c_desc}")
            completed_list.append(c_desc)
        else:
            report_lines.append("  - No files were modified.")

        report_lines.append("Skipped / Incomplete Items:")
        skipped_list: list[str] = list(skipped_items)
        if dag_plan_steps and current_step < len(dag_plan_steps):
            for step in dag_plan_steps[current_step:]:
                skipped_list.append(f"Incomplete step: {step.title}")
        if skipped_list:
            for item in skipped_list:
                report_lines.append(f"  ⚠️ {item}")
        else:
            skipped_list.append("Full verification incomplete before iteration limit")

        partial_summary = "\n".join(report_lines)
        yield _sse_status("partial_report", partial_summary)
        yield _sse_done(False, partial_summary, completed_items=completed_list, skipped_items=skipped_list)

    except Exception as top_exc:
        logger.exception("chat_harness: unhandled error in run_chat_agent: %s", top_exc)
        yield _sse_error(f"Agent execution error: {top_exc}")
        yield _sse_done(False, f"Agent execution stopped: {top_exc}")
    finally:
        try:
            _cleanup_server_sessions(workspace)
        except Exception as exc:
            log_and_flag_failure("server_session_cleanup", exc, {"workspace": workspace})
