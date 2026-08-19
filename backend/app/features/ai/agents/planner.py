import json
import logging
from ..service import provider_for
from ..schemas import ChatRequest, ChatMessage

logger = logging.getLogger(__name__)

PLANNER_SYSTEM_PROMPT = """You are the Lead Task Planner for CODE OS. Your role is to decompose a complex software engineering request into a Directed Acyclic Graph (DAG) of dependent subtasks.

Available Agent Roles:
- Coding Agent: Writes/modifies workspace code, logic, refactoring, security fixes, and performance optimization.
- Review Agent: Audits code quality, style, security risks, and architecture.
- Testing Agent: Writes unit tests and executes code validation tests.
- Documentation Agent: Updates module summaries, API lists, and README.md.

CRITICAL: Assign tasks ONLY to the 4 Available Agent Roles listed above. For security analysis or performance profiling, assign to 'Coding Agent' or 'Review Agent' with specialized instructions in the task title.


Format your output EXACTLY as a JSON object matching this structure:
{
  "tasks": [
    {
      "id": "db_setup",
      "title": "Setup SQLite Schema",
      "agent_role": "Coding Agent",
      "dependencies": [],
      "estimated_effort": "30 mins"
    },
    {
      "id": "backend_api",
      "title": "Implement authentication endpoints",
      "agent_role": "Coding Agent",
      "dependencies": ["db_setup"],
      "estimated_effort": "2 hours"
    },
    {
      "id": "verify_tests",
      "title": "Generate validation tests for endpoints",
      "agent_role": "Testing Agent",
      "dependencies": ["backend_api"],
      "estimated_effort": "1 hour"
    }
  ]
}
Return ONLY raw JSON, with no markdown wrapping or additional text.
"""

class PlannerAgent:
    def __init__(self, provider_config: dict | None = None) -> None:
        self.provider_config = provider_config

    async def plan_task(self, user_request: str, workspace_context: str = "") -> list[dict]:
        if "--quick" in user_request.lower() or "--quick" in workspace_context.lower():
            import re, uuid
            clean_title = re.sub(r'(?i)--quick', '', user_request).strip()
            return [
                {
                    "id": f"quick_coding_{uuid.uuid4().hex[:8]}",
                    # Preserve the execution flag: the coding task is created later
                    # from this title, so removing it here silently disabled quick mode.
                    "title": f"{clean_title if clean_title else 'Quick coding task'} --quick",
                    "agent_role": "Coding Agent",
                    "dependencies": [],
                    "estimated_effort": "5 mins"
                }
            ]

        prompt = f"User Request: {user_request}\n\nWorkspace Context:\n{workspace_context}"
        
        _PRESET_TO_PROVIDER = {
            "local_reasoning": "ollama",
            "local_fast": "ollama",
            "api_fast": "groq",
            "api_reasoning": "openai-compatible",
            "auto": "auto",
        }
        raw_provider = (self.provider_config or {}).get("provider") or (self.provider_config or {}).get("preset", "auto")
        provider_name = _PRESET_TO_PROVIDER.get(raw_provider, raw_provider)
        model_name = self.provider_config.get("model", "") if self.provider_config else ""
        base_url = self.provider_config.get("base_url") if self.provider_config else None
        api_key_provider = self.provider_config.get("api_key_provider") if self.provider_config else None

        chat_req = ChatRequest(
            provider=provider_name,
            model=model_name,
            base_url=base_url,
            api_key_provider=api_key_provider,
            messages=[
                ChatMessage(role="system", content=PLANNER_SYSTEM_PROMPT),
                ChatMessage(role="user", content=prompt)
            ]
        )
        
        for attempt in range(2):
            try:
                provider = await provider_for(chat_req)
                # Use non-streaming completion for structured plan parsing with a 25s timeout
                async def _collect_tokens():
                    tokens = []
                    async for token in provider.stream_chat(chat_req.model, chat_req.messages, temperature=0.1):
                        tokens.append(token)
                    return "".join(tokens).strip()

                import asyncio
                response = await asyncio.wait_for(_collect_tokens(), timeout=25.0)
                
                # Extract JSON from response (handles surrounding prose or markdown fences)
                import re
                json_match = re.search(r'\{[\s\S]*\}', response)
                if json_match:
                    data = json.loads(json_match.group())
                else:
                    data = json.loads(response)
                
                tasks = data.get("tasks", [])
                if tasks:
                    return tasks
                raise ValueError("No tasks found in planner output")
                
            except Exception as exc:
                is_rate_limit = "429" in str(exc) or "rate limit" in str(exc).lower() or "quota" in str(exc).lower()
                effective_prov = (chat_req.api_key_provider or chat_req.provider or "groq").lower()

                if is_rate_limit and attempt == 0 and effective_prov == "groq" and "120b" in (chat_req.model or ""):
                    chat_req.model = "llama-3.3-70b-versatile"
                    continue

                if is_rate_limit and attempt == 0:
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
                            chat_req.base_url = fb_url
                            chat_req.provider = "openai-compatible" if fb_prov in _RECOVERY_URLS else fb_prov
                            chat_req.model = fb_model
                            chat_req.api_key_provider = fb_prov
                            continue
                    except Exception:
                        pass
                logger.error("PlannerAgent failed to generate plan: %s. Using default fallback template.", exc)
                return self._fallback_plan(user_request)

    def _fallback_plan(self, user_request: str) -> list[dict]:

        """Intelligent heuristic fallback task graph when LLM planning fails.
        Decomposes complex requests into modular subtasks (CLI subcommands, bulleted features).
        """
        import re
        import uuid

        clean_req = user_request.strip()
        lines = [line.strip() for line in clean_req.splitlines() if line.strip()]
        
        # 1. Identify distinct requirements or subcommands from bullets and keywords
        bullets = []
        for line in lines:
            if re.match(r"^[-*•\d.]+\s+", line):
                item = re.sub(r"^[-*•\d.]+\s+", "", line).strip()
                if len(item) > 8:
                    bullets.append(item)

        # 2. Extract subcommands from patterns like `subcommand` or "subcommands: watch, query, stats"
        subcommands = []
        subcmd_match = re.search(r"(?:subcommands?|commands?):\s*([^\n\r]+)", clean_req, re.IGNORECASE)
        if subcmd_match:
            raw_cmds = re.findall(r"[`'\"]?([a-zA-Z0-9_\-]+)[`'\"]?", subcmd_match.group(1))
            for cmd in raw_cmds:
                if cmd.lower() not in ("and", "or", "the", "a", "an", "three", "two", "four", "start", "print"):
                    if cmd not in subcommands:
                        subcommands.append(cmd)

        coding_tasks = []
        prior_id = None

        # Build modular coding tasks based on extracted features
        if subcommands and len(subcommands) >= 2:
            sfx = uuid.uuid4().hex[:8]
            setup_id = f"task_cli_setup_{sfx}"
            first_line = lines[0] if lines else "CLI Tool"
            coding_tasks.append({
                "id": setup_id,
                "title": f"Design and setup CLI structure for {first_line[:60]}",
                "agent_role": "Coding Agent",
                "dependencies": [],
                "estimated_effort": "30 mins",
                "fallback": True
            })
            prior_id = setup_id

            for cmd in subcommands:
                cmd_sfx = uuid.uuid4().hex[:8]
                cmd_id = f"task_cmd_{cmd}_{cmd_sfx}"
                coding_tasks.append({
                    "id": cmd_id,
                    "title": f"Implement '{cmd}' subcommand and required business logic",
                    "agent_role": "Coding Agent",
                    "dependencies": [prior_id] if prior_id else [],
                    "estimated_effort": "45 mins",
                    "fallback": True
                })
                prior_id = cmd_id
        elif len(bullets) >= 2:
            sfx = uuid.uuid4().hex[:8]
            base_id = f"task_base_setup_{sfx}"
            coding_tasks.append({
                "id": base_id,
                "title": f"Setup core architecture and data structures ({lines[0][:60] if lines else 'Module'})",
                "agent_role": "Coding Agent",
                "dependencies": [],
                "estimated_effort": "30 mins",
                "fallback": True
            })
            prior_id = base_id

            for i, b in enumerate(bullets[:4]):
                b_sfx = uuid.uuid4().hex[:8]
                b_id = f"task_feature_{i+1}_{b_sfx}"
                coding_tasks.append({
                    "id": b_id,
                    "title": f"Implement {b[:80]}",
                    "agent_role": "Coding Agent",
                    "dependencies": [prior_id] if prior_id else [],
                    "estimated_effort": "40 mins",
                    "fallback": True
                })
                prior_id = b_id
        else:
            sfx = uuid.uuid4().hex[:8]
            generic_id = f"task_coding_{sfx}"
            first_line = lines[0] if lines else "requested features"
            coding_tasks.append({
                "id": generic_id,
                "title": f"Implement {first_line[:90]}",
                "agent_role": "Coding Agent",
                "dependencies": [],
                "estimated_effort": "1 hour",
                "fallback": True
            })
            prior_id = generic_id

        last_coding_ids = [coding_tasks[-1]["id"]] if coding_tasks else []

        sfx = uuid.uuid4().hex[:8]
        id_review = f"task_review_{sfx}"
        id_testing = f"task_testing_{sfx}"
        id_docs = f"task_docs_{sfx}"

        review_task = {
            "id": id_review,
            "title": "Perform static code review and quality checks",
            "agent_role": "Review Agent",
            "dependencies": last_coding_ids,
            "estimated_effort": "20 mins",
            "fallback": True
        }
        test_task = {
            "id": id_testing,
            "title": "Generate and execute validation unit tests",
            "agent_role": "Testing Agent",
            "dependencies": last_coding_ids,
            "estimated_effort": "30 mins",
            "fallback": True
        }
        docs_task = {
            "id": id_docs,
            "title": "Synchronize project README.md documentation",
            "agent_role": "Documentation Agent",
            "dependencies": [id_review, id_testing],
            "estimated_effort": "15 mins",
            "fallback": True
        }

        return [*coding_tasks, review_task, test_task, docs_task]
