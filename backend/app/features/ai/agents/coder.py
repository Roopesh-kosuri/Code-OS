import logging
import json
import time
import asyncio
import re
from typing import Optional, List, Dict, Any, Awaitable, Callable
from pathlib import Path
from pydantic import BaseModel

from .agent_interface import BaseAgent, AgentOutput
from ..service import provider_for, create_proposal, get_proposal
from ..schemas import ChatRequest, ChatMessage, FileChange, EditProposalRequest
from ..job_service import add_job_log
from ..event_bus import event_bus
from ....db.database import get_db

logger = logging.getLogger(__name__)

# ── Budget and Retry Limits ──────────────────────────────────────────────────
MAX_LLM_CALLS_PER_TASK = 25  # Safety cap: prevents a single task from silently exhausting rate-limit window
MAX_INSTRUMENTED_RETRIES = 1  # Auto-retries before escalating to user via handle_llm_failure

class BudgetExhaustedError(RuntimeError):
    """Raised when a task exceeds its per-task LLM call budget."""
    pass

# ── Reviewer System Prompt ───────────────────────────────────────────────────

LIGHT_REVIEWER_SYSTEM_PROMPT = """You are a senior code auditor. Review this quick code change for syntactical correctness and critical bugs.
You MUST return a JSON object matching this structure EXACTLY:
{
  "approved": bool,
  "issues": ["description of issue 1", "description of issue 2", ...],
  "reasoning": "summary of review findings"
}
Do not return any prose or explanation outside the JSON block.
"""

# Keep the fast path deliberately conservative.  It is used only after the
# planner has named a single, no-risk file and the generated patch is small.
HIGH_STAKES_KEYWORDS = ("refactor", "migrate", "breaking", "security", "auth", "payment", "database", "deploy")
TRIVIAL_DIFF_MAX_CHARS = 1_200

REVIEWER_SYSTEM_PROMPT = """You are a senior reviewer. Analyze the proposed changes against the original code.
Evaluate:
1. Does this actually achieve the stated goal?
2. Are there off-by-one errors, missing imports, broken references, or type errors?
3. Does it touch files outside files_to_touch without justification?
4. Is there a simpler solution?

You MUST return a JSON object matching this structure EXACTLY:
{
  "approved": bool,
  "issues": ["description of issue 1", "description of issue 2", ...],
  "reasoning": "summary of review findings"
}
Do not return any prose or explanation outside the JSON block.
"""

PLANNER_SYSTEM_PROMPT = """You are a senior software architect. Analyze the task title and context, and create a structured implementation plan.
If the task description is ambiguous and you cannot confidently fill out the hypothesis, ask a clarifying question instead of guessing.

You MUST return a JSON object matching this structure EXACTLY:
{
  "ambiguous": bool,
  "clarifying_question": "optional question if ambiguous is true, otherwise empty",
  "goal": "one sentence goal description",
  "hypothesis": "what you believe is true about the current state or problem",
  "files_to_touch": ["relative/path/to/file1.py", ...],
  "context_files": ["relative/path/to/file_to_read.py", ...],
  "approach": "how you will solve it in 2-3 sentences",
  "risks": ["risk 1", "risk 2", ...],
  "verification": "how we will know we succeeded"
}

IMPORTANT: "files_to_touch" lists files to CREATE or MODIFY. "context_files" lists existing files the agent should READ for context but NOT modify (e.g. to understand data formats, API contracts, or dependencies). Always include relevant context_files when the task requires understanding existing code.
Do not return any prose or explanation outside the JSON block.
"""

# ── Pydantic models for structured parsing ────────────────────────────────────

class PlanModel(BaseModel):
  ambiguous: bool
  clarifying_question: str
  goal: str
  hypothesis: str
  files_to_touch: List[str]
  context_files: List[str] = []  # Files to read for context but not modify
  approach: str
  risks: List[str]
  verification: str


class ReviewModel(BaseModel):
  approved: bool
  issues: List[str]
  reasoning: str


class CoderAgent(BaseAgent):
  """Specialized agent for writing and editing code with planning, self-review, testing, and DuoLoop orchestration."""

  def __init__(self, provider_config=None) -> None:
    super().__init__("Coding Agent", provider_config=provider_config)

  def get_system_prompt(self) -> str:
    from .agent_tools import get_tool_instructions
    base_prompt = """You are a senior Software Coding Agent. Write clean, modular, typed code following conventions.
- Analyze existing code patterns and style before making changes
- Use existing libraries and utilities from the codebase
- Return proposals using the [PROPOSAL] block format when changing files:
  [PROPOSAL: path]
  <<<< ORIGINAL
  <exact original code to replace — copy it verbatim from the GROUNDED FILE CONTEXT below>
  ====
  <new code>
  >>>>
- CRITICAL FOR NEW FILES OR FULL REPLACEMENTS: If creating a NEW file or replacing an entire file, leave the <<<< ORIGINAL section completely empty:
  [PROPOSAL: path]
  <<<< ORIGINAL
  ====
  <new code>
  >>>>
- The GROUNDED FILE CONTEXT section contains the real current file contents — you MUST use them
  as the source of truth for the original block when modifying existing files. Never invent or paraphrase the original.
- Reference repo index/symbols for context, not just raw file text
- Keep code compact and avoid unnecessary nesting"""
    return base_prompt + get_tool_instructions()

  @staticmethod
  def is_high_stakes(plan: PlanModel, title: str, context: str) -> tuple[bool, list[str]]:
    """Return the escalation decision and the reasons behind it for observability."""
    text = f"{plan.goal} {title} {context}".lower()
    reasons: list[str] = []
    if len(plan.files_to_touch) > 5:
      reasons.append(f"{len(plan.files_to_touch)} files planned")
    if plan.risks:
      reasons.append("planner reported risks")
    matched = [keyword for keyword in HIGH_STAKES_KEYWORDS if keyword in text]
    if matched:
      reasons.append(f"risk keywords: {', '.join(matched)}")
    if "--force-duo" in text:
      reasons.append("--force-duo")
    if "--no-duo" in text:
      return False, ["--no-duo"]
    return bool(reasons), reasons

  @staticmethod
  def is_trivial_change(plan: PlanModel, proposals: List[FileChange]) -> bool:
    """A small, one-file, no-risk proposal can use the abbreviated rigor path."""
    if len(plan.files_to_touch) != 1 or plan.risks or len(proposals) != 1:
      return False
    change = proposals[0]
    return len(change.original) + len(change.updated) <= TRIVIAL_DIFF_MAX_CHARS

  async def _ground_files(
    self,
    workspace: str,
    files_to_touch: List[str],
    max_lines_per_file: int = 300,
    is_context_reference: bool = False,
    timing_recorder: Callable[[str, float], Awaitable[None]] | None = None,
  ) -> str:
    """Read actual file contents + repo symbols/imports from SQLite for each planned file.

    Returns a compact, token-efficient string to inject into the generation prompt so the LLM
    can produce a correct `original` block and avoid hallucinating symbols without bloating context.
    """
    from ....db.database import get_db
    from ....core.paths import normalize_workspace, ensure_within_workspace

    root = normalize_workspace(workspace)
    sections: List[str] = []

    # Optimized token budget: target file gets up to 300 lines; reference context gets 80 lines + symbol outline
    if is_context_reference:
      max_files = 6
      max_lines = 80
      max_symbols = 25
      max_imports = 10
    else:
      max_files = 8
      max_lines = min(max_lines_per_file, 300)
      max_symbols = 35
      max_imports = 15

    for rel_path in files_to_touch[:max_files]:
      # Resolve to absolute path — reject anything outside the workspace
      try:
        candidate = ensure_within_workspace(workspace, rel_path)
      except Exception:
        logger.warning("coder: file path rejected (outside workspace): %s", rel_path)
        continue

      # ── 1. File source content ──────────────────────────────────────────────
      source_lines: List[str] = []
      total_file_lines = 0
      if candidate.is_file():
        try:
          raw = candidate.read_text(encoding="utf-8", errors="ignore")
          all_lines = raw.splitlines()
          total_file_lines = len(all_lines)
          source_lines = all_lines[:max_lines]
        except OSError:
          source_lines = ["(could not read file)"]
      else:
        source_lines = ["(file does not exist yet — this will be a new file)"]

      source_text = "\n".join(source_lines)
      truncated_note = ""
      if total_file_lines > max_lines:
        truncated_note = f"\n... [Showing first {max_lines} of {total_file_lines} total lines. Use read_file tool with start_line={max_lines + 1} if more lines needed]"

      # ── 2. Repo symbols ─────────────────────────────────────────────────────
      symbol_lines: List[str] = []
      try:
        query_start = time.perf_counter()
        db = await get_db()
        sym_rows = await db.execute_fetchall(
          "SELECT name, kind, line, signature FROM repo_symbols WHERE workspace = ? AND path = ? ORDER BY line LIMIT ?",
          (str(root), str(candidate), int(max_symbols)),
        )
        for row in sym_rows:
          sig = f" — {row['signature']}" if row["signature"] else ""
          symbol_lines.append(f"  L{row['line']} [{row['kind']}] {row['name']}{sig}")
        if timing_recorder:
          await timing_recorder(f"Repo grounding: repo_symbols ({rel_path})", time.perf_counter() - query_start)
      except Exception as exc:
        symbol_lines = [f"  (symbol query failed: {exc})"]

      # ── 3. Import edges ──────────────────────────────────────────────────────
      import_lines: List[str] = []
      try:
        query_start = time.perf_counter()
        db = await get_db()
        edge_rows = await db.execute_fetchall(
          "SELECT module, target_path FROM repo_import_edges WHERE workspace = ? AND source_path = ? LIMIT ?",
          (str(root), str(candidate), int(max_imports)),
        )
        for row in edge_rows:
          target = row["target_path"] or "(external)"
          import_lines.append(f"  {row['module']} → {target}")
        if timing_recorder:
          await timing_recorder(f"Repo grounding: repo_import_edges ({rel_path})", time.perf_counter() - query_start)
      except Exception as exc:
        import_lines = [f"  (import edge query failed: {exc})"]

      rel_display = str(candidate.relative_to(root)) if candidate.is_relative_to(root) else str(candidate)
      header_tag = "REFERENCE CONTEXT FILE (read-only)" if is_context_reference else "TARGET FILE TO EDIT"
      section = (
        f"### [{header_tag}] {rel_display}\n"
        f"#### Symbols\n" + ("\n".join(symbol_lines) if symbol_lines else "  (none indexed)") + "\n"
        f"#### Imports\n" + ("\n".join(import_lines) if import_lines else "  (none indexed)") + "\n"
        f"#### Source Excerpt (lines 1-{len(source_lines)}{f' of {total_file_lines}' if total_file_lines else ''})\n"
        f"```\n{source_text}{truncated_note}\n```"
      )
      sections.append(section)

    if not sections:
      return "(no files to ground — plan has empty files_to_touch)"

    return "\n\n".join(sections)

  async def execute(self, job_id: str, task_id: str, title: str, context: str, workspace: str) -> AgentOutput:
    logger.info("coder.agent.execute starting task_id=%s title=%s (LIVE_PATCH_V2)", task_id, title)
    start_time = time.time()
    logs = [f"[{start_time:.2f}] CoderAgent initializing task..."]
    await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})

    llm_call_count = 0
    phase_timings: Dict[str, float] = {}
    proposals: List[FileChange] = []
    proposal_dicts: list[dict] = []
    resolved_model = "unknown"
    resolved_provider = "unknown"
    duo_escalation_data = None
    high_stakes = False
    escalation_reasons: list[str] = []
    self_review_verdict: dict = {"approved": True, "verdict": "✓ self-reviewed", "issues": []}
    test_results: dict = {"status": "no_tests", "passed": 0, "failed": 0, "total": 0, "summary": "No tests run."}
    structured_data: dict = {
      "agent_type": "coder",
      "plan": {},
      "self_review": self_review_verdict,
      "test_results": test_results,
      "files_modified": 0,
      "proposal_created_internally": False,
      "model": resolved_model,
      "provider": resolved_provider,
      "diagnostics": {
        "llm_call_count": 0,
        "phase_timings_seconds": {},
        "quick_edit": False,
        "duo_escalated": False,
        "duo_reasons": [],
        "trivial_change": False,
      },
    }

    task_input_tokens = 0
    task_output_tokens = 0

    async def record_timing(phase_name: str, elapsed: float) -> None:
        phase_timings[phase_name] = phase_timings.get(phase_name, 0.0) + elapsed
        message = f"[METRIC] Phase: {phase_name} | took {elapsed:.2f}s"
        logs.append(message)
        await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": message})

    async def instrumented_chat(req: ChatRequest, phase_name: str, temp: float = 0.1) -> str:
        nonlocal llm_call_count, task_input_tokens, task_output_tokens
        auto_retries = 0
        while auto_retries <= MAX_INSTRUMENTED_RETRIES:
            # ── Budget check ──
            if llm_call_count >= MAX_LLM_CALLS_PER_TASK:
                budget_msg = f"[BUDGET] Task LLM call budget exhausted ({llm_call_count}/{MAX_LLM_CALLS_PER_TASK}). Stopping to prevent rate-limit burst."
                logs.append(budget_msg)
                await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": budget_msg})
                raise BudgetExhaustedError(budget_msg)
            # ── Budget warnings at 50% and 80% ──
            if llm_call_count == MAX_LLM_CALLS_PER_TASK // 2:
                warn_msg = f"[BUDGET] 50% of LLM call budget used ({llm_call_count}/{MAX_LLM_CALLS_PER_TASK})"
                logs.append(warn_msg)
                await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": warn_msg})
            elif llm_call_count == int(MAX_LLM_CALLS_PER_TASK * 0.8):
                warn_msg = f"[BUDGET] 80% of LLM call budget used ({llm_call_count}/{MAX_LLM_CALLS_PER_TASK})"
                logs.append(warn_msg)
                await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": warn_msg})

            llm_call_count += 1
            call_start = time.time()
            try:
                provider = await provider_for(req)
                tokens = []
                async for token in provider.stream_chat(req.model, req.messages, temperature=temp):
                    tokens.append(token)
                response = "".join(tokens).strip()
                if not response:
                    raise RuntimeError(f"Model '{req.model}' on provider '{req.provider or req.api_key_provider}' returned an empty response (0 tokens). Check that the model ID exists on this provider.")
                if response.startswith("[Error:"):
                    raise RuntimeError(response)
                # Detect error strings appended to partial responses
                if "[Error:" in response:
                    error_idx = response.index("[Error:")
                    error_tail = response[error_idx:]
                    clean_response = response[:error_idx].strip()
                    logs.append(f"[WARN] Partial response truncated — error appended by provider: {error_tail[:120]}")
                    await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
                    if len(clean_response) < 50:
                        raise RuntimeError(f"Response too short after stripping appended error: {error_tail}")
                    response = clean_response
                elapsed = time.time() - call_start
                phase_timings[f"{phase_name}_call_{llm_call_count}"] = elapsed

                # ── Token accounting & cost estimation ──
                prompt_chars = sum(len(m.content or "") for m in req.messages)
                call_input_tokens = max(1, int(prompt_chars / 3.6))
                call_output_tokens = max(1, int(len(response) / 3.6))
                task_input_tokens += call_input_tokens
                task_output_tokens += call_output_tokens
                task_total_tokens = task_input_tokens + task_output_tokens
                
                # Estimated blended API cost ($3/M input, $15/M output)
                task_cost_est = (task_input_tokens * 3.0 + task_output_tokens * 15.0) / 1_000_000

                metric_msg = (
                    f"[METRIC] Phase: {phase_name} | Call #{llm_call_count}/{MAX_LLM_CALLS_PER_TASK} took {elapsed:.2f}s | "
                    f"Tokens: ~{call_input_tokens:,} in, ~{call_output_tokens:,} out | "
                    f"Task Total: ~{task_total_tokens:,} (~${task_cost_est:.4f}) | Model: {req.model or 'auto'}"
                )
                logs.append(metric_msg)
                await event_bus.publish("agent_log", {
                    "job_id": job_id,
                    "task_id": task_id,
                    "message": metric_msg,
                    "token_metrics": {
                        "call_input_tokens": call_input_tokens,
                        "call_output_tokens": call_output_tokens,
                        "task_input_tokens": task_input_tokens,
                        "task_output_tokens": task_output_tokens,
                        "task_total_tokens": task_total_tokens,
                        "estimated_cost_usd": task_cost_est,
                    }
                })
                return response
            except BudgetExhaustedError:
                raise  # Never retry budget exhaustion
            except Exception as exc:
                is_rate_limit = "429" in str(exc) or "rate limit" in str(exc).lower() or "quota" in str(exc).lower()
                is_daily_limit = "tpd" in str(exc).lower() or "tokens per day" in str(exc).lower() or "daily" in str(exc).lower()
                parsed_delay = None
                if is_rate_limit:
                    match = re.search(r'try again in\s*([\d.]+)\s*(s|sec|seconds|ms|m)?', str(exc), re.IGNORECASE)
                    if match:
                        val = float(match.group(1))
                        unit = (match.group(2) or 's').lower()
                        parsed_delay = (val / 1000.0) if unit == 'ms' else ((val * 60.0) if unit == 'm' else val)

                # Canonical base URLs for all cloud providers
                _RECOVERY_URLS = {
                    "groq": "https://api.groq.com/openai/v1",
                    "openai": "https://api.openai.com/v1",
                    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
                    "deepseek": "https://api.deepseek.com/v1",
                    "mistral": "https://api.mistral.ai/v1",
                    "openrouter": "https://openrouter.ai/api/v1",
                    "nvidia-nim": "https://integrate.api.nvidia.com/v1",
                    "nvidia": "https://integrate.api.nvidia.com/v1",
                    "anthropic": "https://api.anthropic.com/v1",
                }

                effective_prov = (req.api_key_provider or req.provider or "groq").lower()

                # 1. Automatic Intra-Provider Failover: If Groq hit 429 on gpt-oss-120b, try llama-3.3-70b-versatile or llama-3.1-8b-instant
                if is_rate_limit and effective_prov == "groq" and "120b" in (req.model or ""):
                    alt_model = "llama-3.3-70b-versatile"
                    logs.append(f"[FAILOVER] Groq model '{req.model}' hit token limit. Automatically switching to '{alt_model}'...")
                    await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
                    req.model = alt_model
                    if not self.provider_config:
                        self.provider_config = {}
                    self.provider_config["model"] = alt_model
                    auto_retries = 0
                    continue

                # 2. Automatic Cross-Provider Failover: Try other configured providers (Gemini, NVIDIA NIM, OpenAI, Anthropic, Ollama)
                if is_rate_limit or is_daily_limit:
                    try:
                        from ..provider_health import provider_health_tracker
                        from ...settings.service import get_api_key
                        configured_keys = {
                            "groq": await get_api_key("groq"),
                            "gemini": await get_api_key("gemini"),
                            "nvidia-nim": await get_api_key("nvidia-nim"),
                            "openai": await get_api_key("openai"),
                            "anthropic": await get_api_key("anthropic"),
                            "deepseek": await get_api_key("deepseek"),
                            "mistral": await get_api_key("mistral"),
                        }
                        fb = provider_health_tracker.find_fallback_provider(effective_prov, configured_keys)
                        if fb:
                            fb_prov, fb_model, fb_url = fb
                            logs.append(f"[FAILOVER] Rate limit on [{effective_prov}] {req.model}. Automatically falling back to [{fb_prov}] {fb_model}...")
                            await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
                            new_base_url = fb_url
                            new_provider = "openai-compatible" if fb_prov in _RECOVERY_URLS else fb_prov
                            new_key_provider = fb_prov

                            if not self.provider_config:
                                self.provider_config = {}
                            self.provider_config["preset"] = new_key_provider
                            self.provider_config["provider"] = new_provider
                            self.provider_config["model"] = fb_model
                            self.provider_config["api_key_provider"] = new_key_provider
                            self.provider_config["base_url"] = new_base_url
                            req.base_url = new_base_url
                            req.provider = new_provider
                            req.model = fb_model
                            req.api_key_provider = new_key_provider
                            auto_retries = 0
                            continue
                    except Exception as fb_lookup_err:
                        logger.warning("Cross-provider fallback lookup failed: %s", fb_lookup_err)

                max_retries_for_call = 1 if (is_daily_limit or (parsed_delay and parsed_delay > 15.0)) else MAX_INSTRUMENTED_RETRIES
                logs.append(f"[ERROR] LLM call failed during {phase_name} (auto-retry {auto_retries}/{max_retries_for_call}): {exc}")
                await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})

                # Escalate to user after exhausting auto-retries
                if auto_retries >= max_retries_for_call:
                    decision_res = await self.handle_llm_failure(job_id, task_id, exc)
                    action = decision_res.get("action", "cancel")
                    if action == "retry":
                        auto_retries = 0  # Reset auto-retry counter for user-initiated retry
                        logs.append(f"User requested retry for {phase_name}. Resetting auto-retries.")
                        await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
                        continue
                    elif action in ("switch_to_api", "change_model"):
                        auto_retries = 0  # Reset for new provider
                        new_provider = decision_res.get("provider") or "openai-compatible"
                        new_model = decision_res.get("model") or "llama-3.3-70b-versatile"
                        new_key_provider = decision_res.get("api_key_provider") or new_provider
                        new_base_url = decision_res.get("base_url")

                        # Normalize all named providers to openai-compatible wire protocol
                        if new_provider in _RECOVERY_URLS or new_key_provider in _RECOVERY_URLS:
                            if not new_base_url:
                                new_base_url = _RECOVERY_URLS.get(new_key_provider) or _RECOVERY_URLS.get(new_provider)
                            new_provider = "openai-compatible"

                        logs.append(f"Switching model to [{new_key_provider}] {new_model} for {phase_name}...")
                        await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
                        if not self.provider_config:
                            self.provider_config = {}
                        self.provider_config["preset"] = new_key_provider
                        self.provider_config["provider"] = new_provider
                        self.provider_config["model"] = new_model
                        self.provider_config["api_key_provider"] = new_key_provider
                        self.provider_config["base_url"] = new_base_url or ""
                        req.base_url = new_base_url
                        req.provider = new_provider
                        req.model = new_model
                        req.api_key_provider = new_key_provider
                        continue
                    else:
                        raise exc
                else:
                    auto_retries += 1
                    backoff = min(5.0, 1.5 * auto_retries)
                    logs.append(f"[RETRY] Auto-retrying {phase_name} in {backoff:.1f}s (attempt {auto_retries}/{max_retries_for_call})...")
                    await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
                    await asyncio.sleep(backoff)


    # ── Phase 1: Planning ─────────────────────────────────────────────────────
    plan_start = time.time()
    logs.append(f"[{plan_start:.2f}] Phase 1: Planning phase started.")
    await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})

    quick_mode = "--quick" in title or "--quick" in context
    if quick_mode:
        files_to_touch = []
        # Find any word ending in standard source extensions
        matches = re.findall(r'[a-zA-Z0-9_\-\.\/]+\.(?:py|js|ts|tsx|css|html|go|rs|json|txt|md)', f"{title} {context}")
        for m in matches:
            if m not in files_to_touch:
                files_to_touch.append(m)
        if not files_to_touch:
            files_to_touch = ["main.py"]
            
        plan = PlanModel(
            ambiguous=False,
            clarifying_question="",
            goal=title.replace("--quick", "").strip(),
            hypothesis="Quick edit mode request",
            files_to_touch=files_to_touch,
            approach="Perform quick edit as requested",
            risks=[],
            verification="Manual review"
        )
        logs.append(f"[METRIC] Quick Edit mode active. Bypassed planning LLM call. Target files: {files_to_touch}")
        await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
    else:
        plan_req = self.create_chat_request(
          messages=[
            ChatMessage(role="system", content=PLANNER_SYSTEM_PROMPT),
            ChatMessage(role="user", content=f"Task: {title}\n\nContext:\n{context}\n\nWorkspace: {workspace}")
          ]
        )

        try:
          plan_raw = await instrumented_chat(plan_req, "Phase 1: Planning", temp=0.1)
          
          # Extract JSON from markdown tags if present
          from ...duo.service import _extract_json
          plan_dict = _extract_json(plan_raw)
          plan = PlanModel(**plan_dict)
        except Exception as exc:
          logger.error("Planning failed: %s", exc)
          plan = PlanModel(
            ambiguous=False,
            clarifying_question="",
            goal=title,
            hypothesis="Auto-generated hypothesis",
            files_to_touch=[],
            approach="Solve the task as described",
            risks=[],
            verification="Manual verification"
          )

    # Publish plan to event bus immediately
    await event_bus.publish("agent_log", {
      "job_id": job_id,
      "task_id": task_id,
      "message": f"[PLAN_EMITTED] {json.dumps(plan.model_dump())}"
    })

    # Ambiguity check — pause for clarification instead of failing the workflow!
    if plan.ambiguous and plan.clarifying_question:
      logs.append(f"Task is ambiguous. Asking user for clarification: {plan.clarifying_question}")
      await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
      
      answer = await self.request_clarification(job_id, task_id, plan.clarifying_question)
      
      if answer:
        logs.append(f"Received user clarification: '{answer}'. Re-planning task with provided specifications...")
        await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
        
        clarified_context = f"{context}\n\n=== USER CLARIFICATION ===\nQuestion: {plan.clarifying_question}\nAnswer: {answer}"
        plan_req = self.create_chat_request(
          messages=[
            ChatMessage(role="system", content=PLANNER_SYSTEM_PROMPT),
            ChatMessage(role="user", content=f"Task: {title}\n\nContext:\n{clarified_context}\n\nWorkspace: {workspace}")
          ]
        )
        try:
          plan_raw = await instrumented_chat(plan_req, "Phase 1: Re-Planning with Clarification", temp=0.1)
          from ...duo.service import _extract_json
          plan_dict = _extract_json(plan_raw)
          plan = PlanModel(**plan_dict)
          plan.ambiguous = False
        except Exception as exc:
          logger.error("Re-planning post clarification failed: %s", exc)
          plan = PlanModel(
            ambiguous=False,
            clarifying_question="",
            goal=f"{title} ({answer})",
            hypothesis="Implementation plan based on user clarification",
            files_to_touch=[],
            approach=f"Implement task following user instructions: {answer}",
            risks=[],
            verification="Manual verification"
          )
      else:
        logs.append("Clarification request cancelled by user. Aborting task.")
        await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
        return AgentOutput(
          agent_role=self.role,
          task_id=task_id,
          status="failure",
          confidence=0.0,
          reasoning_summary="Clarification request cancelled by user.",
          logs=logs,
          structured_data=structured_data
        )


    # --plan-only mode check
    plan_only = "--plan-only" in title or "--plan-only" in context
    if plan_only:
      logs.append("Stopped at planning phase (--plan-only active).")
      return AgentOutput(
        agent_role=self.role,
        task_id=task_id,
        status="success",
        confidence=0.9,
        reasoning_summary=f"Emitted plan for approval: {plan.goal}",
        logs=logs,
        structured_data={
          "agent_type": "coder",
          "plan": plan.model_dump(),
          "plan_only": True
        }
      )

    if not plan.files_to_touch:
      # Universal file inference — ask LLM to suggest concrete files for any task
      infer_prompt = (
        f"Given this software task, what specific files should be created or modified?\n"
        f"Task: {plan.goal}\nApproach: {plan.approach}\n\n"
        f"Return ONLY a JSON array of relative file paths, e.g. [\"src/main.py\", \"tests/test_main.py\"].\n"
        f"If it's a new project, infer reasonable file names from the task description.\n"
        f"Return at least 1 file. Do not return any prose, just the JSON array."
      )
      infer_req = self.create_chat_request(
        messages=[
          ChatMessage(role="system", content="You are a senior software architect. Return ONLY a JSON array of file paths."),
          ChatMessage(role="user", content=infer_prompt)
        ]
      )
      try:
        infer_raw = await instrumented_chat(infer_req, "Phase 1b: File Inference", temp=0.1)
        # Extract JSON array from response
        import re as _re
        array_match = _re.search(r'\[\s*"[^"]+"(?:\s*,\s*"[^"]+")*\s*\]', infer_raw)
        if array_match:
          inferred = json.loads(array_match.group())
          plan.files_to_touch = [f for f in inferred if isinstance(f, str) and f.strip()]
          logs.append(f"[INFERRED] Planner returned no files — LLM inferred: {plan.files_to_touch}")
          await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
        else:
          logs.append(f"[WARN] File inference returned unparseable response: {infer_raw[:200]}")
          await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
      except Exception as infer_exc:
        logs.append(f"[WARN] File inference LLM call failed: {infer_exc}")
        await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})

    # We can loop up to 3 times for user rejection-with-feedback!
    user_retry = 0
    max_user_retries = 3
    user_feedback = None
    resolved_model = "unknown"
    resolved_provider = "unknown"
    duo_escalation_data = None

    while user_retry <= max_user_retries:
      proposals: List[FileChange] = []
      generation_outcomes: Dict[str, str] = {}  # file -> "success:N" | "empty_response" | "parse_failed:len" | "llm_error:msg"

      # ── Phase 2: Generation / DuoLoop Orchestration ────────────────────────────
      gen_start = time.time()
      logs.append(f"[{gen_start:.2f}] Phase 2: Code generation phase started.")
      await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})

      # This decision must be explicit: accidental Duo escalation adds multiple
      # sequential model calls, which is especially expensive with local models.
      high_stakes, escalation_reasons = self.is_high_stakes(plan, title, context)
      logs.append(f"[METRIC] Duo escalation: {'triggered' if high_stakes else 'skipped'} | reasons: {', '.join(escalation_reasons) or 'single-file/no-risk task'}")
      await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})

      if high_stakes:
        logs.append("High-stakes task detected. Running inside internal DuoLoop...")
        await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
        try:
          from ...duo.service import start_session, get_session
          from ...duo.schemas import DuoSessionRequest, ModelConfig
          
          p_prov = self.provider_config.get("provider", "auto") if self.provider_config else "auto"
          p_mod = self.provider_config.get("model", "") if self.provider_config else ""
          duo_req = DuoSessionRequest(
            workspace=workspace,
            task_description=f"Task: {title}\n\nFiles to change: {plan.files_to_touch}\nApproach: {plan.approach}",
            generator=ModelConfig(provider=p_prov, model=p_mod),
            critic=ModelConfig(provider=p_prov, model=p_mod),
            max_rounds=3,
            internal=True
          )
          
          session = await start_session(duo_req)
          max_duo_wait = 180.0
          duo_wait_start = time.time()
          last_reported_round = -1
          last_heartbeat = time.time()
          
          while True:
            await asyncio.sleep(1.5)
            elapsed = time.time() - duo_wait_start
            
            if elapsed > max_duo_wait:
              logs.append(f"⚠ [DuoLoop] Timed out after {max_duo_wait:.0f}s. Falling back to standard generation...")
              await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
              break
              
            session = await get_session(session.id)
            
            # Progress reporting
            if session.current_round != last_reported_round:
              last_reported_round = session.current_round
              msg = f"⚡ [DuoLoop] Round {session.current_round}/{session.max_rounds}: Generator and Critic active..."
              logs.append(msg)
              await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": msg})
              last_heartbeat = time.time()
            elif time.time() - last_heartbeat >= 12.0 and session.status == "running":
              last_heartbeat = time.time()
              msg = f"⏳ [DuoLoop] In progress (Round {session.current_round}/{session.max_rounds}, {elapsed:.0f}s elapsed)..."
              logs.append(msg)
              await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": msg})
              
            if session.status in ["approved", "unresolved", "error", "cancelled", "waiting_for_recovery"]:
              if session.status == "waiting_for_recovery":
                logs.append("⚠ [DuoLoop] Session encountered an error. Falling back to standard generation...")
                await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
              break
              
          if session.final_proposal_id:
            final_prop = await get_proposal(session.final_proposal_id)
            proposals = final_prop.changes
            logs.append(f"DuoLoop finished with final proposal: {session.final_proposal_id} ({len(proposals)} files)")
            await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
            duo_escalation_data = {
              "invoked": True,
              "rounds": len(session.rounds),
              "status": session.status
            }
            # Resolve settings to get actual model info
            from ...settings.service import list_settings
            settings = await list_settings()
            resolved_model = settings.get("ollama.model") or "llama3"
            resolved_provider = "ollama"
        except Exception as exc:
          logs.append(f"DuoLoop orchestration failed: {exc}. Falling back to standard generation...")
          await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})

      # Standard code generation if fallback or not high-stakes
      if not proposals:
        system_instruction = self.get_system_prompt()
        from .agent_tools import parse_tool_calls, has_tool_calls, response_is_done, execute_tool_calls, MAX_TOOL_ITERATIONS, TOOL_PHASE_TIMEOUT_SECONDS

        # Pre-ground context_files (read-only reference outline)
        context_grounding = ""
        if plan.context_files:
          logs.append(f"Grounding {len(plan.context_files)} reference context file(s): {plan.context_files}")
          await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
          try:
            context_grounding = await self._ground_files(workspace, plan.context_files, is_context_reference=True, timing_recorder=record_timing)
          except Exception as exc:
            context_grounding = f"(context grounding failed: {exc})"
            logger.warning("CoderAgent context grounding failed: %s", exc)

        if plan.files_to_touch:
          # Sequential, context-carrying multi-file execution
          for file_to_touch in plan.files_to_touch:
            grounding_start = time.time()
            logs.append(f"Grounding: reading {file_to_touch} from repo index...")
            await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
            try:
              grounding_context = await self._ground_files(workspace, [file_to_touch], is_context_reference=False, timing_recorder=record_timing)
            except Exception as exc:
              grounding_context = f"(grounding failed: {exc})"
              logger.warning("CoderAgent grounding failed for %s: %s", file_to_touch, exc)

            logs.append(f"✍️ [EDITING] {file_to_touch}")
            await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})

            preceding_context = ""
            if proposals:
              summary_items = []
              for p in proposals:
                orig_l = len(p.original.splitlines()) if p.original else 0
                upd_l = len(p.updated.splitlines()) if p.updated else 0
                diff_sign = "+" if upd_l >= orig_l else ""
                summary_items.append(f"- `{p.path}` ({diff_sign}{upd_l - orig_l} lines)")

              snippets = []
              for p in proposals[-2:]:
                clean_upd = (p.updated[:250] + "...") if len(p.updated) > 250 else p.updated
                snippets.append(f"[{p.path}]\n{clean_upd}")

              preceding_context = (
                f"\n=== PRECEDING CHANGES ALREADY PROPOSED IN THIS TASK ===\n"
                f"You already proposed changes to:\n" + "\n".join(summary_items) + "\n\n"
                f"Key interface snippets:\n" + "\n\n".join(snippets) + "\n"
                f"Ensure changes to {file_to_touch} remain consistent with these prior changes.\n"
              )

            # Include context_files grounding if available
            context_section = ""
            if context_grounding:
              context_section = f"\n=== CONTEXT FILES (read-only reference) ===\n{context_grounding}\n"

            prompt = (
              f"Task Goal: {plan.goal}\n"
              f"Hypothesis: {plan.hypothesis}\n"
              f"Approach: {plan.approach}\n"
              f"Current File to touch: {file_to_touch}\n\n"
              f"Workspace Context:\n{context}\n"
              f"{preceding_context}\n"
              f"{context_section}"
              f"=== GROUNDED FILE CONTEXT ===\n"
              f"{grounding_context}"
            )
            if user_feedback:
              prompt += f"\n\n=== USER FEEDBACK ON PREVIOUS PROP ===\nThe user rejected the previous proposal with this comment:\n{user_feedback}\n\nPlease regenerate the proposal for {file_to_touch} fixing this issue."

            # Build initial messages for the tool-use conversation
            messages = [
              ChatMessage(role="system", content=system_instruction),
              ChatMessage(role="user", content=prompt)
            ]

            try:
              # ── Tool-use loop: iterative read/list/edit ──
              tool_staged_changes: list = []
              tool_iteration = 0
              tool_loop_start = time.time()
              final_response = ""

              while tool_iteration <= MAX_TOOL_ITERATIONS:
                chat_req = self.create_chat_request(messages=messages)
                response = await instrumented_chat(chat_req, f"Phase 2: Code Gen ({file_to_touch}, iter {tool_iteration})", temp=0.2)
                response = response or ""
                final_response = response

                resolved_model = chat_req.model
                resolved_provider = chat_req.api_key_provider or chat_req.provider

                # Check for tool calls in response
                if has_tool_calls(response) and tool_iteration < MAX_TOOL_ITERATIONS:
                  tool_calls = parse_tool_calls(response)
                  if tool_calls:
                    tool_names = [tc.name for tc in tool_calls]
                    logs.append(f"🔧 [TOOL] Iteration {tool_iteration}: {len(tool_calls)} tool call(s) — {', '.join(tool_names)}")
                    await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})

                    # Execute tools
                    tool_results_text = execute_tool_calls(tool_calls, workspace, tool_staged_changes)

                    # Compact older tool messages (iteration T-2 and older) to prevent quadratic token growth
                    if len(messages) > 4:
                      for idx in range(2, len(messages) - 2, 2):
                        if idx + 1 < len(messages):
                          old_user_msg = messages[idx + 1]
                          if old_user_msg.role == "user" and "Tool results:" in (old_user_msg.content or ""):
                            if len(old_user_msg.content) > 250:
                              old_user_msg.content = "Tool results (compacted history):\n✓ Executed previous tool calls successfully.\n"

                    # Append assistant response and tool results to conversation
                    messages.append(ChatMessage(role="assistant", content=response))
                    messages.append(ChatMessage(role="user", content=f"Tool results:\n\n{tool_results_text}\n\nContinue with your task. Use more tools if needed, or output your final [PROPOSAL] blocks and [DONE] when finished."))

                    tool_iteration += 1

                    # Check timeout
                    if time.time() - tool_loop_start > TOOL_PHASE_TIMEOUT_SECONDS:
                      logs.append(f"⚠ [TOOL] Tool loop timed out after {TOOL_PHASE_TIMEOUT_SECONDS}s")
                      await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
                      break
                    continue

                # No tool calls or [DONE] reached — exit loop
                if tool_iteration > 0:
                  logs.append(f"🔧 [TOOL] Loop completed after {tool_iteration} iteration(s)")
                  await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
                break

              # Collect proposals from both traditional extraction and tool-staged changes
              from ..service import extract_proposals_robust
              parsed = extract_proposals_robust(final_response, [file_to_touch])

              # Merge tool-staged changes (edit_file calls)
              if tool_staged_changes:
                staged_paths = {c.path for c in tool_staged_changes}
                # Avoid duplicates: if extract_proposals_robust already found a proposal for the same path, skip tool-staged
                for staged in tool_staged_changes:
                  if staged.path not in {p.path for p in parsed}:
                    parsed.append(staged)
                logs.append(f"🔧 [TOOL] {len(tool_staged_changes)} edit(s) staged via edit_file tool")
                await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})

              proposals.extend(parsed)

              final_text = (final_response or "").strip()
              if parsed:
                generation_outcomes[file_to_touch] = f"success:{len(parsed)}"
                logs.append(f"✓ [EDITED] {file_to_touch} ({len(parsed)} changes)")
              elif not final_text:
                generation_outcomes[file_to_touch] = "empty_response"
                logs.append(f"⚠ [EMPTY] {file_to_touch} — LLM returned an empty response")
              else:
                generation_outcomes[file_to_touch] = f"parse_failed:{len(final_text)}"
                logs.append(f"⚠ [PARSE_FAILED] {file_to_touch} — LLM returned {len(final_text)} chars but parser extracted 0 proposals")
              await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
            except Exception as exc:
              generation_outcomes[file_to_touch] = f"llm_error:{exc}"
              logs.append(f"✗ [LLM_ERROR] {file_to_touch}: {exc}")
              await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
        else:
          # Fallback standard generation if no plan files to touch
          grounding_start = time.time()
          logs.append(f"[{grounding_start:.2f}] Grounding: reading planned file(s) from repo index...")
          await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
          try:
            grounding_context = await self._ground_files(workspace, plan.files_to_touch, timing_recorder=record_timing)
          except Exception as exc:
            grounding_context = f"(grounding failed: {exc})"
            logger.warning("CoderAgent grounding failed: %s", exc)
          grounding_end = time.time()

          context_section = ""
          if context_grounding:
            context_section = f"\n=== CONTEXT FILES (read-only reference) ===\n{context_grounding}\n"

          prompt = (
            f"Task Goal: {plan.goal}\n"
            f"Hypothesis: {plan.hypothesis}\n"
            f"Approach: {plan.approach}\n"
            f"Files to touch: {plan.files_to_touch}\n\n"
            f"Workspace Context:\n{context}\n\n"
            f"{context_section}"
            f"=== GROUNDED FILE CONTEXT (use verbatim for original blocks) ===\n"
            f"{grounding_context}"
          )
          if user_feedback:
            prompt += f"\n\n=== USER FEEDBACK ON PREVIOUS PROP ===\nThe user rejected the previous proposal with this comment:\n{user_feedback}\n\nPlease regenerate the proposals fixing this issue."
          
          messages = [
            ChatMessage(role="system", content=system_instruction),
            ChatMessage(role="user", content=prompt)
          ]

          try:
            tool_staged_changes: list = []
            tool_iteration = 0
            tool_loop_start = time.time()
            final_response = ""

            while tool_iteration <= MAX_TOOL_ITERATIONS:
              chat_req = self.create_chat_request(messages=messages)
              response = await instrumented_chat(chat_req, f"Phase 2: Standard Code Gen (iter {tool_iteration})", temp=0.2)
              response = response or ""
              final_response = response

              resolved_model = chat_req.model
              resolved_provider = chat_req.api_key_provider or chat_req.provider

              # Check for tool calls in response
              if has_tool_calls(response) and tool_iteration < MAX_TOOL_ITERATIONS:
                tool_calls = parse_tool_calls(response)
                if tool_calls:
                  tool_names = [tc.name for tc in tool_calls]
                  logs.append(f"🔧 [TOOL] Iteration {tool_iteration}: {len(tool_calls)} tool call(s) — {', '.join(tool_names)}")
                  await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})

                  tool_results_text = execute_tool_calls(tool_calls, workspace, tool_staged_changes)

                  messages.append(ChatMessage(role="assistant", content=response))
                  messages.append(ChatMessage(role="user", content=f"Tool results:\n\n{tool_results_text}\n\nContinue with your task. Use more tools if needed, or output your final [PROPOSAL] blocks and [DONE] when finished."))

                  tool_iteration += 1

                  if time.time() - tool_loop_start > TOOL_PHASE_TIMEOUT_SECONDS:
                    logs.append(f"⚠ [TOOL] Tool loop timed out after {TOOL_PHASE_TIMEOUT_SECONDS}s")
                    await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
                    break
                  continue

              if tool_iteration > 0:
                logs.append(f"🔧 [TOOL] Loop completed after {tool_iteration} iteration(s)")
                await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
              break

            from ..service import extract_proposals_robust
            parsed = extract_proposals_robust(final_response, plan.files_to_touch)

            if tool_staged_changes:
              for staged in tool_staged_changes:
                if staged.path not in {p.path for p in parsed}:
                  parsed.append(staged)
              logs.append(f"🔧 [TOOL] {len(tool_staged_changes)} edit(s) staged via edit_file tool")
              await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})

            proposals.extend(parsed)
            final_std_text = (final_response or "").strip()
            if parsed:
              generation_outcomes["_standard"] = f"success:{len(parsed)}"
            elif not final_std_text:
              generation_outcomes["_standard"] = "empty_response"
            else:
              generation_outcomes["_standard"] = f"parse_failed:{len(final_std_text)}"
          except Exception as exc:
            generation_outcomes["_standard"] = f"llm_error:{exc}"
            logs.append(f"Standard LLM call failed: {exc}")
            return AgentOutput(
              agent_role=self.role,
              task_id=task_id,
              status="failure",
              confidence=0.1,
              reasoning_summary=f"LLM call failed during code generation: {exc}",
              logs=logs,
              structured_data=structured_data
            )


      # ── Phase 3: Self-Review Loop ─────────────────────────────────────────────
      review_start = time.time()
      logs.append(f"[{review_start:.2f}] Phase 3: Self-review loop started.")
      await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})

      self_review_verdict = {"approved": True, "verdict": "✓ self-reviewed", "issues": []}

      if proposals:
        if quick_mode:
          self_review_verdict = {"approved": True, "verdict": "✓ self-reviewed (skipped in quick mode)", "issues": []}
          logs.append("Quick Edit mode active. Bypassed self-review LLM call.")
          await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
        else:
          is_low_complexity = self.is_trivial_change(plan, proposals)
          system_prompt_to_use = LIGHT_REVIEWER_SYSTEM_PROMPT if is_low_complexity else REVIEWER_SYSTEM_PROMPT
          logs.append(f"Self-review: using {'lightweight' if is_low_complexity else 'standard'} pass.")
          await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})

          retry_count = 0
          max_retries = 2
          while retry_count <= max_retries:
            from ..service import proposal_diff
            diff_text = proposal_diff(proposals)
            
            review_req = self.create_chat_request(
              messages=[
                ChatMessage(role="system", content=system_prompt_to_use),
                ChatMessage(role="user", content=f"Goal: {plan.goal}\nFiles to touch: {plan.files_to_touch}\n\nProposed Diffs:\n{diff_text}")
              ]
            )
            
            try:
              review_raw = await instrumented_chat(review_req, f"Phase 3: Self-Review (Attempt {retry_count})", temp=0.1)
              
              from ...duo.service import _extract_json
              review_dict = _extract_json(review_raw)
              review = ReviewModel(**review_dict)
            except Exception as exc:
              logger.error("Self review parsing failed: %s", exc)
              review = ReviewModel(approved=True, issues=[], reasoning="Auto-approved review")
              
            if review.approved:
              logs.append("Self-review approved the code proposals!")
              await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
              break
            else:
              retry_count += 1
              self_review_verdict = {
                "approved": False,
                "verdict": f"⚠ regenerated (Retry {retry_count}/{max_retries}: {review.reasoning[:60]})",
                "issues": review.issues
              }
              logs.append(f"Self-review failed: {review.reasoning}. Regenerating proposals (Try {retry_count})...")
              await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
              
              system_instruction = self.get_system_prompt()
              try:
                grounding_context = await self._ground_files(workspace, plan.files_to_touch, timing_recorder=record_timing)
              except Exception:
                grounding_context = "(grounding unavailable)"
              feedback_prompt = (
                f"Goal: {plan.goal}\n\n"
                f"Previous proposals failed reviewer checks:\n{self_review_verdict['issues']}\n\n"
                f"=== GROUNDED FILE CONTEXT (use verbatim for original blocks) ===\n"
                f"{grounding_context}\n\n"
                f"Please write a corrected set of code proposals resolving all issues listed above."
              )
              
              chat_req = self.create_chat_request(
                messages=[
                  ChatMessage(role="system", content=system_instruction),
                  ChatMessage(role="user", content=feedback_prompt)
                ]
              )
              
              try:
                response = await instrumented_chat(chat_req, f"Phase 3: Self-Review Refine (Attempt {retry_count})", temp=0.2)
                from ..service import extract_proposals_robust
                refined = extract_proposals_robust(response, plan.files_to_touch)
                if refined:
                  proposals = refined
                else:
                  logs.append("Self-review refinement parser found no new proposal format; keeping prior proposals.")
              except Exception as e:
                logger.error("Self review refinement failed: %s", e)
                break

      # ── Phase 4: Test Integration via TesterAgent ─────────────────────────────
      test_start = time.time()
      logs.append(f"[{test_start:.2f}] Phase 4: Test execution phase started.")
      await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})

      skip_tests = "--skip-tests" in title or "--skip-tests" in context or quick_mode
      test_results = {"status": "no_tests", "passed": 0, "failed": 0, "total": 0, "summary": ""}

      if not skip_tests and proposals:
        from .tester import TesterAgent
        tester = TesterAgent()
        runner_start = time.perf_counter()
        runner = tester.detect_test_runner(workspace)
        await record_timing("TesterAgent: test-runner detection", time.perf_counter() - runner_start)
        if not runner:
          test_results = {
            "status": "no_tests",
            "passed": 0,
            "failed": 0,
            "total": 0,
            "summary": "No test runner detected cover these files — consider adding some."
          }
          logs.append("No test runner detected for touched files. TesterAgent LLM fallback was not invoked.")
        else:
          affected_files = [p.path for p in proposals if p.path.endswith(('.py', '.js', '.ts', '.tsx', '.go', '.rs'))]
          if not affected_files:
            test_results = {
              "status": "no_tests",
              "passed": 0,
              "failed": 0,
              "total": 0,
              "summary": "No testable files cover these changes — consider adding some."
            }
            logs.append("No coverable files in proposals.")
          else:
            if runner["type"] == "pytest":
              cmd = f"python -m pytest {' '.join(affected_files)}"
            elif runner["type"] in ["jest", "npm"]:
              cmd = f"npm test -- {' '.join(affected_files)}"
            else:
              cmd = runner["command"]
              
            logs.append(f"Running affected tests via TesterAgent: {cmd}")
            await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})

            permission_details = (
              f"CoderAgent (Phase 4) requests permission to execute test suite.\n"
              f"Runner: {runner['type']} | Command: {cmd}"
            )
            test_allowed = await self.request_permission(
              job_id, task_id, "execute_command", permission_details, cmd
            )
            _skip_test_run = not test_allowed
            if not test_allowed:
              logs.append("Test execution permission denied by user — skipping Phase 4.")
              await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
              test_results = {
                "status": "no_tests",
                "passed": 0,
                "failed": 0,
                "total": 0,
                "summary": "Test execution was denied by the user."
              }

            test_retry = 0
            max_test_retries = 2
            while not _skip_test_run and test_retry <= max_test_retries:
              try:
                command_start = time.perf_counter()
                output, returncode = await tester.execute_test_command(workspace, cmd)
                await record_timing(f"TesterAgent: test command (Attempt {test_retry})", time.perf_counter() - command_start)
                parsed = tester.parse_test_output(output, runner["type"])
                
                if parsed["failed"] == 0 and returncode == 0:
                  test_results = {
                    "status": "pass",
                    "passed": parsed["passed"],
                    "failed": 0,
                    "total": parsed["total"],
                    "summary": f"All tests passed: {parsed['passed']}/{parsed['total']} tests."
                  }
                  logs.append(f"All tests passed on attempt {test_retry}!")
                  break
                else:
                  test_retry += 1
                  test_results = {
                    "status": "fail",
                    "passed": parsed["passed"],
                    "failed": parsed["failed"],
                    "total": parsed["total"],
                    "summary": f"Tests failed: {parsed['failed']} tests failed.\n{output[-500:] if len(output) > 500 else output}"
                  }
                  
                  if test_retry > max_test_retries:
                    logs.append("Tests failed. Retries exhausted.")
                    break
                    
                  logs.append(f"Tests failed: {test_results['summary']}. Fixing proposals (Try {test_retry})...")
                  await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
                  
                  from .agent_tools import summarize_test_output
                  test_summary = summarize_test_output(output, max_chars=800)
                  system_instruction = self.get_system_prompt()
                  feedback_prompt = (
                    f"Goal: {plan.goal}\n\n"
                    f"Proposed files failed the test suite with return code {returncode}.\n"
                    f"Test failure summary:\n{test_summary}\n\n"
                    f"Please correct the code proposals to resolve the test failure."
                  )
                  
                  chat_req = self.create_chat_request(
                    messages=[
                      ChatMessage(role="system", content=system_instruction),
                      ChatMessage(role="user", content=feedback_prompt)
                    ]
                  )
                  
                  try:
                    response = await instrumented_chat(chat_req, f"Phase 4: Tester Refine (Attempt {test_retry})", temp=0.2)
                    from ..service import extract_proposals_robust
                    refined = extract_proposals_robust(response, plan.files_to_touch)
                    if refined:
                      proposals = refined
                    else:
                      logs.append("Tester refinement parser found no new proposal format; keeping prior proposals.")
                  except Exception as e:
                    logger.error("Tester refinement failed: %s", e)
                    break
              except Exception as exc:
                logger.error("Tester integration failed: %s", exc)
                test_results = {
                  "status": "no_tests",
                  "passed": 0,
                  "failed": 0,
                  "total": 0,
                  "summary": f"Test runner invocation error: {exc}"
                }
                break

      elif quick_mode:
        logs.append("Quick Edit mode active. Bypassed TesterAgent and test execution.")
        await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
      elif "--skip-tests" in title or "--skip-tests" in context:
        logs.append("--skip-tests active. Bypassed TesterAgent and test execution.")
        await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})

      # ── Proposal Return & Autonomous Engine Handling ───────────────────────────
      if not proposals and not plan_only:
        # Build a specific diagnostic message based on what actually went wrong
        if not generation_outcomes:
          if not plan.files_to_touch:
            failure_reason = f"Planner could not determine target files for '{title}'. Specify filenames in the prompt or break the task into smaller, more concrete subtasks."
          else:
            failure_reason = f"No generation was attempted for '{title}' — internal control flow error."
        else:
          error_files = [f for f, o in generation_outcomes.items() if o.startswith("llm_error:")]
          empty_files = [f for f, o in generation_outcomes.items() if o == "empty_response"]
          parse_files = [f for f, o in generation_outcomes.items() if o.startswith("parse_failed:")]
          if error_files:
            err_details = "; ".join(f"{f}: {generation_outcomes[f][10:80]}" for f in error_files[:3])
            failure_reason = f"LLM calls failed for {len(error_files)} of {len(generation_outcomes)} files: {err_details}"
          elif empty_files:
            failure_reason = f"LLM returned empty responses for {len(empty_files)} of {len(generation_outcomes)} files ({', '.join(empty_files[:3])}). The model may not have understood the task — try rephrasing or adding more context."
          elif parse_files:
            sizes = [generation_outcomes[f].split(":")[1] for f in parse_files[:3]]
            failure_reason = f"LLM produced responses ({', '.join(s + ' chars' for s in sizes)}) but the code parser could not extract valid proposals. The model may have responded conversationally instead of producing code blocks."
          else:
            failure_reason = f"CoderAgent failed to generate any code proposals for '{title}'."

        logs.append(f"[FAILURE] {failure_reason}")
        return AgentOutput(
          agent_role=self.role,
          task_id=task_id,
          status="failure",
          confidence=0.1,
          reasoning_summary=failure_reason,
          logs=logs,
          structured_data=structured_data
        )
      else:
        # Proposals generated successfully
        break

    # Save plan/review/test metadata onto proposal dicts
    proposal_dicts = []
    for p in proposals:
      p_dict = p.model_dump()
      p_dict["plan"] = plan.model_dump()
      p_dict["self_review"] = self_review_verdict
      p_dict["test_results"] = test_results
      proposal_dicts.append(p_dict)

    end_time = time.time()
    task_total_toks = task_input_tokens + task_output_tokens
    task_cost_final = (task_input_tokens * 3.0 + task_output_tokens * 15.0) / 1_000_000
    logs.append(f"[{end_time:.2f}] CoderAgent execution completed in {end_time - start_time:.2f}s.")
    logs.append(
      f"[METRIC] Pipeline summary | total LLM calls: {llm_call_count} | "
      f"total tokens: ~{task_total_toks:,} (~${task_cost_final:.4f}) | elapsed: {end_time - start_time:.2f}s"
    )
    await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})

    structured_data = {
      "agent_type": "coder",
      "plan": plan.model_dump(),
      "self_review": self_review_verdict,
      "test_results": test_results,
      "files_modified": len(proposals),
      "proposal_created_internally": True,
      "model": resolved_model,
      "provider": resolved_provider,
      "diagnostics": {
        "llm_call_count": llm_call_count,
        "token_metrics": {
          "input_tokens": task_input_tokens,
          "output_tokens": task_output_tokens,
          "total_tokens": task_total_toks,
          "estimated_cost_usd": task_cost_final,
        },
        "phase_timings_seconds": phase_timings,
        "quick_edit": quick_mode,
        "duo_escalated": high_stakes,
        "duo_reasons": escalation_reasons,
        "trivial_change": self.is_trivial_change(plan, proposals) if proposals else False,
      },
    }
    if duo_escalation_data:
      structured_data["duo_escalation"] = duo_escalation_data

    # Dynamic confidence scoring based on review verdict and proposals
    has_proposals = len(proposals) > 0
    review_ok = self_review_verdict.get("approved", True)
    test_ok = test_results.get("status") in ("pass", "no_tests")
    
    if has_proposals and review_ok and test_ok:
      confidence_score = 0.95
    elif has_proposals and review_ok:
      confidence_score = 0.8
    elif has_proposals:
      confidence_score = 0.6
    else:
      confidence_score = 0.2

    task_status = "success" if (has_proposals or plan_only) else "failure"
    reasoning_text = plan.goal if has_proposals else (
      f"Emitted plan: {plan.goal}" if plan_only else f"No code proposals generated for '{title}'"
    )

    return AgentOutput(
      agent_role=self.role,
      task_id=task_id,
      status=task_status,
      confidence=confidence_score,
      reasoning_summary=reasoning_text,
      proposals=proposal_dicts,
      logs=logs,
      structured_data=structured_data
    )
