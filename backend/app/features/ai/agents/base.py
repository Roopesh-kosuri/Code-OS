import asyncio
import logging
from typing import Optional, Dict
from pydantic import BaseModel
from ..service import provider_for
from ..schemas import ChatRequest, ChatMessage, FileChange
from ..job_service import update_task_status, update_task_pending_action, add_job_log
from ..event_bus import event_bus
from .agent_interface import BaseAgent as NewBaseAgent, AgentOutput as NewAgentOutput

logger = logging.getLogger(__name__)

# Legacy compatibility class for roles not yet migrated to new system
class BaseAgent(NewBaseAgent):
    """Legacy BaseAgent for backward compatibility with unimplemented roles."""
    
    def __init__(self, role: str, provider_config: Optional[Dict] = None) -> None:
        self.role = role
        super().__init__(role, provider_config=provider_config)

    async def execute(self, job_id: str, task_id: str, title: str, context: str, workspace: str) -> NewAgentOutput:
        """Legacy execute method for backward compatibility."""
        logger.info("Legacy BaseAgent.execute role=%s task_id=%s title=%s", self.role, task_id, title)
        logs = []
        
        # 1. Generate specialized instruction based on role
        system_instruction = self._get_system_prompt()
        prompt = f"Task Title: {title}\n\nCodebase Context:\n{context}\n\nWorkspace: {workspace}"
        
        logs.append(f"Legacy Agent [{self.role}] initializing task...")
        await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
        
        # 2. Call LLM
        # Resolve provider: 'provider' key takes priority, then fall back to 'preset'
        # with a mapping table so legacy 'local_reasoning'/'api_fast' presets still work.
        _PRESET_TO_PROVIDER = {
            "local_reasoning": "ollama",
            "local_fast": "ollama",
            "api_fast": "groq",
            "api_reasoning": "openai-compatible",
            "auto": "auto",
        }
        raw_provider = (self.provider_config or {}).get("provider") or (self.provider_config or {}).get("preset", "auto")
        provider_name = _PRESET_TO_PROVIDER.get(raw_provider, raw_provider)  # pass-through if already a real name
        model_name = self.provider_config.get("model", "") if self.provider_config else ""
        base_url = self.provider_config.get("base_url") if self.provider_config else None
        api_key_provider = self.provider_config.get("api_key_provider") if self.provider_config else None

        chat_req = ChatRequest(
            provider=provider_name,
            model=model_name,
            base_url=base_url,
            api_key_provider=api_key_provider,
            messages=[
                ChatMessage(role="system", content=system_instruction),
                ChatMessage(role="user", content=prompt)
            ]
        )
        
        proposals = []
        reasoning = f"Executed {self.role} task successfully."
        
        try:
            response = ""
            while True:
                try:
                    provider = await provider_for(chat_req)
                    tokens = []
                    async for token in provider.stream_chat(chat_req.model, chat_req.messages, temperature=0.2):
                        tokens.append(token)
                        
                    response = "".join(tokens).strip()
                    break
                except Exception as exc:
                    logs.append(f"[ERROR] Legacy Agent [{self.role}] LLM call failed: {exc}")
                    decision_res = await self.handle_llm_failure(job_id, task_id, exc)
                    action = decision_res.get("action", "cancel")
                    if action == "retry":
                        continue
                    elif action == "switch_to_api":
                        chat_req.provider = "groq"
                        chat_req.model = "llama-3.3-70b-versatile"
                        continue
                    else:
                        raise exc
                        
            logs.append(f"Legacy Agent [{self.role}] completed reasoning.")
            
            # Parse edit proposals from response text
            from ..service import PROPOSAL_RE
            for match in PROPOSAL_RE.finditer(response):
                filepath = match.group("path").strip()
                original = match.group("original")
                updated = match.group("updated")
                proposals.append(FileChange(path=filepath, original=original, updated=updated))
                logs.append(f"Legacy Agent [{self.role}] proposed changes to file: {filepath}")
                await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
            
            reasoning = response[:500] + "..." if len(response) > 500 else response
            
        except Exception as exc:
            logs.append(f"Legacy Agent [{self.role}] LLM failure: {exc}")
            return NewAgentOutput(
                agent_role=self.role,
                task_id=task_id,
                status="failure",
                confidence=0.1,
                reasoning_summary=f"LLM failure: {exc}",
                logs=logs
            )
        
        # Convert FileChange objects to dicts for NewAgentOutput
        proposal_dicts = [p.model_dump() for p in proposals]
            
        return NewAgentOutput(
            agent_role=self.role,
            task_id=task_id,
            status="success",
            confidence=0.85,
            reasoning_summary=reasoning,
            proposals=proposal_dicts,
            logs=logs,
            structured_data={
                "agent_type": "legacy",
                "role": self.role
            }
        )

    def get_system_prompt(self) -> str:
        """Override abstract method with legacy implementation."""
        return self._get_system_prompt()

    def _get_system_prompt(self) -> str:
        prompts = {
            "Research Agent": "You are a Research Agent. Summarize project APIs, read configuration files, list imports, and cite references carefully.",
            "Git Agent": "You are a Git Agent. Analyze file modifications and construct meaningful Conventional Commit messages.",
            "Security Agent": "You are a Security Agent. Review imports and logic blocks for OWASP vulnerabilities, injection vectors, and credentials leaks.",
            "Performance Agent": "You are a Performance Agent. Identify runtime bottlenecks, memory leaks, and redundant calculations. Suggest clean optimization rewrites."
        }
        return prompts.get(self.role, "You are a specialized Software Agent.")
