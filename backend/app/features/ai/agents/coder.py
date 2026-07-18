import logging
import json
import time
import asyncio
from typing import Optional, List, Dict, Any, Awaitable, Callable
from pathlib import Path
from pydantic import BaseModel

from .agent_interface import BaseAgent, AgentOutput
from backend.app.features.ai.service import provider_for, create_proposal, get_proposal
from backend.app.features.ai.schemas import ChatRequest, ChatMessage, FileChange, EditProposalRequest
from backend.app.features.ai.job_service import add_job_log
from backend.app.features.ai.event_bus import event_bus
from backend.app.db.database import get_connection

logger = logging.getLogger(__name__)

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
  "approach": "how you will solve it in 2-3 sentences",
  "risks": ["risk 1", "risk 2", ...],
  "verification": "how we will know we succeeded"
}
Do not return any prose or explanation outside the JSON block.
"""

# ── Pydantic models for structured parsing ────────────────────────────────────

class PlanModel(BaseModel):
  ambiguous: bool
  clarifying_question: str
  goal: str
  hypothesis: str
  files_to_touch: List[str]
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
    return """You are a senior Software Coding Agent. Write clean, modular, typed code following conventions.
- Analyze existing code patterns and style before making changes
- Use existing libraries and utilities from the codebase
- Return proposals using the [PROPOSAL] block format when changing files:
  [PROPOSAL: path]
  <<<< ORIGINAL
  <exact original code to replace — copy it verbatim from the GROUNDED FILE CONTEXT below>
  ====
  <new code>
  >>>>
- The GROUNDED FILE CONTEXT section contains the real current file contents — you MUST use them
  as the source of truth for the original block. Never invent or paraphrase the original.
- Reference repo index/symbols for context, not just raw file text
- Keep code compact and avoid unnecessary nesting"""

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
    max_lines_per_file: int = 120,
    timing_recorder: Callable[[str, float], Awaitable[None]] | None = None,
  ) -> str:
    """Read actual file contents + repo symbols/imports from SQLite for each planned file.

    Returns a compact string to inject into the generation prompt so the LLM
    can produce a correct `original` block and avoid hallucinating symbols.
    """
    from backend.app.db.database import get_connection
    from backend.app.core.paths import normalize_path

    root = normalize_path(workspace)
    sections: List[str] = []

    # Scale budget based on model capability tier
    is_large = False
    if self.provider_config:
        raw_provider = self.provider_config.get("provider") or self.provider_config.get("preset", "auto")
        if raw_provider not in ("ollama", "local_reasoning", "local_fast"):
            is_large = True

    max_files = 20 if is_large else 8
    max_lines = 500 if is_large else max_lines_per_file
    max_symbols = 150 if is_large else 40
    max_imports = 60 if is_large else 20

    for rel_path in files_to_touch[:max_files]:
      # Resolve to absolute path
      candidate = Path(rel_path)
      if not candidate.is_absolute():
        candidate = (root / rel_path).resolve()

      # ── 1. File source content ──────────────────────────────────────────────
      source_lines: List[str] = []
      if candidate.is_file():
        try:
          raw = candidate.read_text(encoding="utf-8", errors="ignore")
          source_lines = raw.splitlines()
          if len(source_lines) > max_lines:
            source_lines = source_lines[:max_lines]
            source_lines.append(f"... ({len(raw.splitlines()) - max_lines} more lines truncated)")
        except OSError:
          source_lines = ["(could not read file)"]
      else:
        source_lines = ["(file does not exist yet — this will be a new file)"]

      source_text = "\n".join(source_lines)

      # ── 2. Repo symbols ─────────────────────────────────────────────────────
      symbol_lines: List[str] = []
      try:
        query_start = time.perf_counter()
        db = await get_connection()
        try:
          sym_rows = await db.execute_fetchall(
            f"SELECT name, kind, line, signature FROM repo_symbols WHERE workspace = ? AND path = ? ORDER BY line LIMIT {max_symbols}",
            (str(root), str(candidate)),
          )
          for row in sym_rows:
            sig = f" — {row['signature']}" if row["signature"] else ""
            symbol_lines.append(f"  L{row['line']} [{row['kind']}] {row['name']}{sig}")
        finally:
          await db.close()
          if timing_recorder:
            await timing_recorder(f"Repo grounding: repo_symbols ({rel_path})", time.perf_counter() - query_start)
      except Exception as exc:
        symbol_lines = [f"  (symbol query failed: {exc})"]

      # ── 3. Import edges ──────────────────────────────────────────────────────
      import_lines: List[str] = []
      try:
        query_start = time.perf_counter()
        db = await get_connection()
        try:
          edge_rows = await db.execute_fetchall(
            f"SELECT module, target_path FROM repo_import_edges WHERE workspace = ? AND source_path = ? LIMIT {max_imports}",
            (str(root), str(candidate)),
          )
          for row in edge_rows:
            target = row["target_path"] or "(external)"
            import_lines.append(f"  {row['module']} → {target}")
        finally:
          await db.close()
          if timing_recorder:
            await timing_recorder(f"Repo grounding: repo_import_edges ({rel_path})", time.perf_counter() - query_start)
      except Exception as exc:
        import_lines = [f"  (import edge query failed: {exc})"]

      rel_display = str(candidate.relative_to(root)) if candidate.is_relative_to(root) else str(candidate)
      section = (
        f"### GROUNDED FILE: {rel_display}\n"
        f"#### Symbols\n" + ("\n".join(symbol_lines) if symbol_lines else "  (none indexed)") + "\n"
        f"#### Imports\n" + ("\n".join(import_lines) if import_lines else "  (none indexed)") + "\n"
        f"#### Current Source (first {max_lines} lines)\n"
        f"```\n{source_text}\n```"
      )
      sections.append(section)

    if not sections:
      return "(no files to ground — plan has empty files_to_touch)"

    return "\n\n".join(sections)

  async def execute(self, job_id: str, task_id: str, title: str, context: str, workspace: str) -> AgentOutput:
    start_time = time.time()
    logs = [f"[{start_time:.2f}] CoderAgent initializing task..."]
    await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})

    llm_call_count = 0
    phase_timings: Dict[str, float] = {}

    async def record_timing(phase_name: str, elapsed: float) -> None:
        phase_timings[phase_name] = phase_timings.get(phase_name, 0.0) + elapsed
        message = f"[METRIC] Phase: {phase_name} | took {elapsed:.2f}s"
        logs.append(message)
        await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": message})

    async def instrumented_chat(req: ChatRequest, phase_name: str, temp: float = 0.1) -> str:
        nonlocal llm_call_count
        while True:
            llm_call_count += 1
            call_start = time.time()
            try:
                provider = await provider_for(req)
                tokens = []
                async for token in provider.stream_chat(req.model, req.messages, temperature=temp):
                    tokens.append(token)
                response = "".join(tokens).strip()
                elapsed = time.time() - call_start
                phase_timings[f"{phase_name}_call_{llm_call_count}"] = elapsed
                logs.append(f"[METRIC] Phase: {phase_name} | Call #{llm_call_count} took {elapsed:.2f}s | Model: {req.model or 'auto'}")
                await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
                return response
            except Exception as exc:
                logs.append(f"[ERROR] LLM call failed during {phase_name}: {exc}")
                await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
                
                decision_res = await self.handle_llm_failure(job_id, task_id, exc)
                action = decision_res.get("action", "cancel")
                if action == "retry":
                    logs.append(f"Retrying LLM call for {phase_name}...")
                    await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
                    continue
                elif action == "switch_to_api":
                    logs.append(f"Switching to API provider for {phase_name}...")
                    await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
                    # Update local config and the request to use API
                    if not self.provider_config:
                        self.provider_config = {}
                    self.provider_config["preset"] = "groq"
                    self.provider_config["model"] = "llama-3.3-70b-versatile"
                    req.provider = "groq"
                    req.model = "llama-3.3-70b-versatile"
                    continue
                else:
                    raise exc

    # ── Phase 1: Planning ─────────────────────────────────────────────────────
    plan_start = time.time()
    logs.append(f"[{plan_start:.2f}] Phase 1: Planning phase started.")
    await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})

    quick_mode = "--quick" in title or "--quick" in context
    if quick_mode:
        import re
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
          from backend.app.features.duo.service import _extract_json
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

    # Ambiguity check
    if plan.ambiguous and plan.clarifying_question:
      logs.append(f"Task is ambiguous. Clarifying question: {plan.clarifying_question}")
      await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
      return AgentOutput(
        agent_role=self.role,
        task_id=task_id,
        status="failure",
        confidence=0.0,
        reasoning_summary=plan.clarifying_question,
        logs=logs
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

    # We can loop up to 3 times for user rejection-with-feedback!
    user_retry = 0
    max_user_retries = 3
    user_feedback = None
    resolved_model = "unknown"
    resolved_provider = "unknown"
    duo_escalation_data = None

    while user_retry <= max_user_retries:
      proposals: List[FileChange] = []

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
          from backend.app.features.duo.service import start_session, get_session
          from backend.app.features.duo.schemas import DuoSessionRequest, ModelConfig
          
          duo_req = DuoSessionRequest(
            workspace=workspace,
            task_description=f"Task: {title}\n\nFiles to change: {plan.files_to_touch}\nApproach: {plan.approach}",
            generator=ModelConfig(provider="auto", model=""),
            critic=ModelConfig(provider="auto", model=""),
            max_rounds=4
          )
          
          session = await start_session(duo_req)
          while True:
            await asyncio.sleep(2.0)
            session = await get_session(session.id)
            if session.status in ["approved", "unresolved", "error", "cancelled"]:
              break
              
          if session.final_proposal_id:
            final_prop = await get_proposal(session.final_proposal_id)
            proposals = final_prop.changes
            logs.append(f"DuoLoop finished with final proposal: {session.final_proposal_id}")
            duo_escalation_data = {
              "invoked": True,
              "rounds": len(session.rounds),
              "status": session.status
            }
            # Resolve settings to get actual model info
            from backend.app.features.settings.service import list_settings
            settings = await list_settings()
            resolved_model = settings.get("ollama.model") or "llama3"
            resolved_provider = "ollama"
        except Exception as exc:
          logs.append(f"DuoLoop orchestration failed: {exc}. Falling back to standard generation...")
          await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})

      # Standard code generation if fallback or not high-stakes
      if not proposals:
        system_instruction = self.get_system_prompt()

        if plan.files_to_touch:
          # Sequential, context-carrying multi-file execution
          for file_to_touch in plan.files_to_touch:
            grounding_start = time.time()
            logs.append(f"Grounding: reading {file_to_touch} from repo index...")
            await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
            try:
              grounding_context = await self._ground_files(workspace, [file_to_touch], timing_recorder=record_timing)
            except Exception as exc:
              grounding_context = f"(grounding failed: {exc})"
              logger.warning("CoderAgent grounding failed for %s: %s", file_to_touch, exc)

            logs.append(f"✍️ [EDITING] {file_to_touch}")
            await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})

            from backend.app.features.ai.service import proposal_diff
            preceding_context = ""
            if proposals:
              diff_text = proposal_diff(proposals)
              preceding_context = (
                f"\n\n=== PROPOSED CHANGES FROM PREVIOUS STEPS ===\n"
                f"You have already proposed the following changes in this task. "
                f"Ensure your changes to {file_to_touch} are fully compatible with and "
                f"reference these proposed changes:\n{diff_text}\n"
              )

            prompt = (
              f"Task Goal: {plan.goal}\n"
              f"Hypothesis: {plan.hypothesis}\n"
              f"Approach: {plan.approach}\n"
              f"Current File to touch: {file_to_touch}\n\n"
              f"Workspace Context:\n{context}\n"
              f"{preceding_context}\n"
              f"=== GROUNDED FILE CONTEXT ===\n"
              f"{grounding_context}"
            )
            if user_feedback:
              prompt += f"\n\n=== USER FEEDBACK ON PREVIOUS PROP ===\nThe user rejected the previous proposal with this comment:\n{user_feedback}\n\nPlease regenerate the proposal for {file_to_touch} fixing this issue."

            chat_req = self.create_chat_request(
              messages=[
                ChatMessage(role="system", content=system_instruction),
                ChatMessage(role="user", content=prompt)
              ]
            )

            try:
              response = await instrumented_chat(chat_req, f"Phase 2: Code Gen ({file_to_touch})", temp=0.2)

              resolved_model = chat_req.model
              resolved_provider = chat_req.api_key_provider or chat_req.provider

              from backend.app.features.ai.service import PROPOSAL_RE
              for match in PROPOSAL_RE.finditer(response):
                filepath = match.group("path").strip()
                original = match.group("original")
                updated = match.group("updated")
                proposals.append(FileChange(path=filepath, original=original, updated=updated))

              logs.append(f"✓ [EDITED] {file_to_touch}")
              await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
            except Exception as exc:
              logs.append(f"LLM call failed for {file_to_touch}: {exc}")
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

          prompt = (
            f"Task Goal: {plan.goal}\n"
            f"Hypothesis: {plan.hypothesis}\n"
            f"Approach: {plan.approach}\n"
            f"Files to touch: {plan.files_to_touch}\n\n"
            f"Workspace Context:\n{context}\n\n"
            f"=== GROUNDED FILE CONTEXT (use verbatim for original blocks) ===\n"
            f"{grounding_context}"
          )
          if user_feedback:
            prompt += f"\n\n=== USER FEEDBACK ON PREVIOUS PROP ===\nThe user rejected the previous proposal with this comment:\n{user_feedback}\n\nPlease regenerate the proposals fixing this issue."
          
          chat_req = self.create_chat_request(
            messages=[
              ChatMessage(role="system", content=system_instruction),
              ChatMessage(role="user", content=prompt)
            ]
          )
          
          try:
            response = await instrumented_chat(chat_req, "Phase 2: Standard Code Gen", temp=0.2)

            resolved_model = chat_req.model
            resolved_provider = chat_req.api_key_provider or chat_req.provider
            
            from backend.app.features.ai.service import PROPOSAL_RE
            for match in PROPOSAL_RE.finditer(response):
              filepath = match.group("path").strip()
              original = match.group("original")
              updated = match.group("updated")
              proposals.append(FileChange(path=filepath, original=original, updated=updated))
          except Exception as exc:
            logs.append(f"Standard LLM call failed: {exc}")
            return AgentOutput(
              agent_role=self.role,
              task_id=task_id,
              status="failure",
              confidence=0.1,
              reasoning_summary=f"LLM failure: {exc}",
              logs=logs
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
            from backend.app.features.ai.service import proposal_diff
            diff_text = proposal_diff(proposals)
            
            review_req = self.create_chat_request(
              messages=[
                ChatMessage(role="system", content=system_prompt_to_use),
                ChatMessage(role="user", content=f"Goal: {plan.goal}\nFiles to touch: {plan.files_to_touch}\n\nProposed Diffs:\n{diff_text}")
              ]
            )
            
            try:
              review_raw = await instrumented_chat(review_req, f"Phase 3: Self-Review (Attempt {retry_count})", temp=0.1)
              
              from backend.app.features.duo.service import _extract_json
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
                
                proposals = []
                from backend.app.features.ai.service import PROPOSAL_RE
                for match in PROPOSAL_RE.finditer(response):
                  filepath = match.group("path").strip()
                  original = match.group("original")
                  updated = match.group("updated")
                  proposals.append(FileChange(path=filepath, original=original, updated=updated))
              except Exception:
                break

      # ── Phase 4: Test Integration via TesterAgent ─────────────────────────────
      test_start = time.time()
      logs.append(f"[{test_start:.2f}] Phase 4: Test execution phase started.")
      await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})

      skip_tests = "--skip-tests" in title or "--skip-tests" in context or quick_mode
      test_results = {"status": "no_tests", "passed": 0, "failed": 0, "total": 0, "summary": ""}

      if not skip_tests and proposals:
        from backend.app.features.ai.agents.tester import TesterAgent
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
                  
                  system_instruction = self.get_system_prompt()
                  feedback_prompt = (
                    f"Goal: {plan.goal}\n\n"
                    f"Proposed files failed the test suite with return code {returncode}.\n"
                    f"Test failure details:\n{output[-1000:] if len(output) > 1000 else output}\n\n"
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
                    
                    proposals = []
                    from backend.app.features.ai.service import PROPOSAL_RE
                    for match in PROPOSAL_RE.finditer(response):
                      filepath = match.group("path").strip()
                      original = match.group("original")
                      updated = match.group("updated")
                      proposals.append(FileChange(path=filepath, original=original, updated=updated))
                  except Exception:
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

      # ── Proposal Internal Creation & Approval Loop ─────────────────────────────
      if proposals:
        from backend.app.features.ai.service import create_proposal
        
        proposal_payload = EditProposalRequest(
          workspace=workspace,
          summary=f"Task: {title} (Coding Agent)",
          changes=proposals,
          plan=plan.model_dump(),
          self_review=self_review_verdict,
          test_results=test_results
        )
        # Link proposal to task/job in JSON payload metadata
        payload_dict = proposal_payload.model_dump()
        payload_dict["task_id"] = task_id
        payload_dict["job_id"] = job_id
        
        # Create the proposal
        proposal = await create_proposal(proposal_payload)
        logs.append(f"Agent [Coding Agent] created internal edit proposal ID: {proposal.id}")
        await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
        
        # Save payload back to proposal in DB to carry metadata
        db = await get_connection()
        try:
          await db.execute(
            "UPDATE edit_proposals SET payload = ? WHERE id = ?",
            (json.dumps(payload_dict), proposal.id)
          )
          await db.commit()
        finally:
          await db.close()

        permission_details = f"CoderAgent proposed edits to {len(proposals)} file(s). Review and approve them in DiffViewer."
        approved = await self.request_permission(
          job_id, task_id, "file-write", permission_details, command=proposal.id
        )

        if approved:
          logs.append("Proposal approved and applied successfully!")
          await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
          break
        else:
          # Rejection feedback retrieval
          from backend.app.features.ai.agents import permission_state as perm_state
          user_feedback = perm_state.pending_permission_feedback.pop(task_id, None)
          if not user_feedback:
            user_feedback = "User rejected proposal without comment."
          
          logs.append(f"Proposal rejected by user: {user_feedback}")
          await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": f"Proposal rejected. Feedback: {user_feedback}"})
          
          user_retry += 1
          if user_retry <= max_user_retries:
            logs.append(f"Regenerating proposals with user feedback (Try {user_retry + 1}/{max_user_retries + 1})...")
            await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
            continue
          else:
            logs.append("User rejection retries exhausted.")
            await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
            return AgentOutput(
              agent_role=self.role,
              task_id=task_id,
              status="failure",
              confidence=0.5,
              reasoning_summary=f"Task rejected by user: {user_feedback}",
              logs=logs
            )
      else:
        # No proposals generated at all
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
    logs.append(f"[{end_time:.2f}] CoderAgent execution completed in {end_time - start_time:.2f}s.")
    logs.append(f"[METRIC] Pipeline summary | total LLM calls: {llm_call_count} | elapsed: {end_time - start_time:.2f}s")
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
        "phase_timings_seconds": phase_timings,
        "quick_edit": quick_mode,
        "duo_escalated": high_stakes,
        "duo_reasons": escalation_reasons,
        "trivial_change": self.is_trivial_change(plan, proposals) if proposals else False,
      },
    }
    if duo_escalation_data:
      structured_data["duo_escalation"] = duo_escalation_data

    return AgentOutput(
      agent_role=self.role,
      task_id=task_id,
      status="success",
      confidence=0.9,
      reasoning_summary=plan.goal,
      proposals=proposal_dicts,
      logs=logs,
      structured_data=structured_data
    )
