import json
import logging
from backend.app.features.ai.service import provider_for
from backend.app.features.ai.schemas import ChatRequest, ChatMessage

logger = logging.getLogger(__name__)

PLANNER_SYSTEM_PROMPT = """You are the Lead Task Planner for CODE OS. Your role is to decompose a complex software engineering request into a Directed Acyclic Graph (DAG) of dependent subtasks.

Available Agent Roles:
- Coding Agent: Writes/modifies workspace code and logic.
- Review Agent: Audits code quality, style, and structure.
- Testing Agent: Writes unit tests and executes code validation tests.
- Documentation Agent: Updates module summaries, API lists, and README.md.
- Research Agent: Inspects directories, summaries APIs, and references references.
- Security Agent: Performs vulnerability scans and secures implementations.
- Performance Agent: Profiles execution bottlenecks and refactors code.
- Git Agent: Summarizes differences, generates release notes, and stages commits.

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
        
        try:
            provider = await provider_for(chat_req)
            # Use non-streaming completion for structured plan parsing
            tokens = []
            async for token in provider.stream_chat(chat_req.model, chat_req.messages, temperature=0.1):
                tokens.append(token)
            
            response = "".join(tokens).strip()
            # Clean up markdown code blocks if the model ignored instructions
            if response.startswith("```"):
                lines = response.splitlines()
                if lines[0].startswith("```json"):
                    response = "\n".join(lines[1:-1])
                elif lines[0].startswith("```"):
                    response = "\n".join(lines[1:-1])
            
            data = json.loads(response)
            return data.get("tasks", [])
            
        except Exception as exc:
            logger.error("PlannerAgent failed to generate plan: %s. Using default fallback template.", exc)
            return self._fallback_plan(user_request)

    def _fallback_plan(self, user_request: str) -> list[dict]:
        # Simple generic fallback task graph if the LLM fails.
        # Each call generates fresh UUIDs so concurrent jobs never collide on
        # the UNIQUE constraint in the agent_tasks table.
        import uuid
        sfx = uuid.uuid4().hex[:8]
        id_research = f"task_research_{sfx}"
        id_coding   = f"task_coding_{sfx}"
        id_review   = f"task_review_{sfx}"
        id_testing  = f"task_testing_{sfx}"
        id_docs     = f"task_docs_{sfx}"
        return [
            {
                "id": id_research,
                "title": f"Research implementation details for '{user_request}'",
                "agent_role": "Research Agent",
                "dependencies": [],
                "estimated_effort": "15 mins"
            },
            {
                "id": id_coding,
                "title": f"Implement core changes for '{user_request}'",
                "agent_role": "Coding Agent",
                "dependencies": [id_research],
                "estimated_effort": "1 hour"
            },
            {
                "id": id_review,
                "title": "Perform static code review and quality checks",
                "agent_role": "Review Agent",
                "dependencies": [id_coding],
                "estimated_effort": "20 mins"
            },
            {
                "id": id_testing,
                "title": "Generate validation unit tests",
                "agent_role": "Testing Agent",
                "dependencies": [id_coding],
                "estimated_effort": "30 mins"
            },
            {
                "id": id_docs,
                "title": "Synchronize project README.md documentation",
                "agent_role": "Documentation Agent",
                "dependencies": [id_testing, id_review],
                "estimated_effort": "15 mins"
            }
        ]
