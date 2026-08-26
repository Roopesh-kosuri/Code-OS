from abc import ABC, abstractmethod
from typing import Optional
from pydantic import BaseModel
# D2: hoisted from function-level to avoid repeated inline import (no circular import risk)
from ..providers.constants import PRESET_TO_PROVIDER as _PRESET_TO_PROVIDER


class AgentOutput(BaseModel):
    agent_role: str
    task_id: str
    status: str
    confidence: float
    reasoning_summary: str
    files_analyzed: list[str] = []
    proposals: list[dict] = []
    logs: list[str] = []
    # Structured output for specific agent types
    structured_data: dict = {}


class BaseAgent(ABC):
    """Abstract base class for all specialized agents."""
    
    def __init__(self, role: str, provider_config: Optional[dict] = None) -> None:
        self.role = role
        self.provider_config = provider_config
    
    @abstractmethod
    async def execute(self, job_id: str, task_id: str, title: str, context: str, workspace: str) -> AgentOutput:
        """Execute the agent's specific task."""
        pass
    
    @abstractmethod
    def get_system_prompt(self) -> str:
        """Get the system prompt for this agent type."""
        pass
        
    def create_chat_request(self, messages: list) -> "ChatRequest":
        """Build a ChatRequest based on the agent's provider config."""
        from ..schemas import ChatRequest
        
        # Canonical base URLs for each provider — used to resolve base_url
        # when the caller specifies api_key_provider but not an explicit URL.
        _PROVIDER_BASE_URLS = {
            "openai": "https://api.openai.com/v1",
            "groq": "https://api.groq.com/openai/v1",
            "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
            "deepseek": "https://api.deepseek.com/v1",
            "mistral": "https://api.mistral.ai/v1",
            "openrouter": "https://openrouter.ai/api/v1",
            "nvidia-nim": "https://integrate.api.nvidia.com/v1",
            "anthropic": "https://api.anthropic.com/v1",
        }

        
        cfg = self.provider_config or {}
        raw_provider = cfg.get("provider") or cfg.get("preset", "auto")
        provider_name = _PRESET_TO_PROVIDER.get(raw_provider, raw_provider)
        model_name = cfg.get("model", "")
        base_url = cfg.get("base_url")
        api_key_provider = cfg.get("api_key_provider")

        # If provider is a named cloud provider, set api_key_provider automatically
        if not api_key_provider and raw_provider in _PROVIDER_BASE_URLS:
            api_key_provider = raw_provider

        # Always resolve base_url from the canonical map when api_key_provider
        # is a known cloud provider and no explicit URL was given.
        if not base_url and api_key_provider and api_key_provider in _PROVIDER_BASE_URLS:
            base_url = _PROVIDER_BASE_URLS[api_key_provider]
        
        return ChatRequest(
            provider=provider_name,
            model=model_name,
            base_url=base_url,
            api_key_provider=api_key_provider,
            messages=messages
        )
    
    async def request_permission(self, job_id: str, task_id: str, action_type: str, details: str, command: Optional[str] = None) -> bool:
        """
        Pauses agent execution and prompts the user for action approval.
        Returns True if approved, False if rejected.
        """
        import asyncio
        from ..job_service import update_task_status, update_task_pending_action, add_job_log
        
        # Import permission state at runtime to avoid circular dependency
        from . import permission_state as perm_state
        
        # Create event
        event = asyncio.Event()
        perm_state.pending_permission_events[task_id] = event
        
        # Save pending action metadata in SQLite
        action_payload = {
            "type": action_type,
            "details": details,
            "command": command
        }
        await update_task_pending_action(task_id, action_payload)
        await update_task_status(task_id, "waiting")
        await add_job_log(job_id, f"Agent [{self.role}] is waiting for permission to: {details}")
        
        # Block until event is set
        await event.wait()
        
        # Cleanup
        perm_state.pending_permission_events.pop(task_id, None)
        decision = perm_state.pending_permission_decisions.pop(task_id, "reject")
        
        await update_task_pending_action(task_id, None)
        await update_task_status(task_id, "running")
        
        if decision == "approve":
            await add_job_log(job_id, f"Permission GRANTED for task ID: {task_id}")
            return True
        else:
            await add_job_log(job_id, f"Permission DENIED for task ID: {task_id}")
            return False

    async def handle_llm_failure(self, job_id: str, task_id: str, exc: Exception) -> dict:
        """
        Pauses agent execution on LLM failure and prompts user for recovery.
        Returns a dict: {"action": "retry" | "switch_to_api" | "cancel"}
        """
        import asyncio
        from ..job_service import update_task_status, update_task_pending_action, add_job_log
        from . import permission_state as perm_state
        
        event = asyncio.Event()
        perm_state.pending_permission_events[task_id] = event
        
        action_payload = {
            "type": "llm_failure",
            "details": str(exc),
        }
        await update_task_pending_action(task_id, action_payload)
        await update_task_status(task_id, "waiting")
        await add_job_log(job_id, f"Agent [{self.role}] paused due to LLM failure: {exc}")
        
        await event.wait()
        
        perm_state.pending_permission_events.pop(task_id, None)
        decision = perm_state.pending_permission_decisions.pop(task_id, "cancel")
        recovery_data = perm_state.pending_permission_data.pop(task_id, {})
        
        await update_task_pending_action(task_id, None)
        await update_task_status(task_id, "running")
        
        await add_job_log(job_id, f"LLM failure recovery decision: {decision}")
        return {
            "action": decision,
            "provider": recovery_data.get("provider"),
            "model": recovery_data.get("model"),
            "api_key_provider": recovery_data.get("api_key_provider"),
            "base_url": recovery_data.get("base_url"),
        }

    async def request_clarification(self, job_id: str, task_id: str, question: str) -> str:
        """
        Pauses agent execution and prompts the user for task clarification.
        Returns the user's answer string, or empty string if cancelled/rejected.
        """
        import asyncio
        from ..job_service import update_task_status, update_task_pending_action, add_job_log
        from . import permission_state as perm_state
        
        event = asyncio.Event()
        perm_state.pending_permission_events[task_id] = event
        
        action_payload = {
            "type": "clarification",
            "details": question,
            "question": question
        }
        await update_task_pending_action(task_id, action_payload)
        await update_task_status(task_id, "waiting")
        await add_job_log(job_id, f"Agent [{self.role}] is waiting for user clarification: {question}")
        
        # Block until user answers or cancels via API
        await event.wait()
        
        perm_state.pending_permission_events.pop(task_id, None)
        decision = perm_state.pending_permission_decisions.pop(task_id, "reject")
        user_answer = perm_state.pending_permission_feedback.pop(task_id, "")
        
        await update_task_pending_action(task_id, None)
        await update_task_status(task_id, "running")
        
        if decision in ("answer", "approve") and user_answer.strip():
            await add_job_log(job_id, f"User provided clarification: '{user_answer.strip()}'")
            return user_answer.strip()
        else:
            await add_job_log(job_id, f"Clarification request cancelled for task ID: {task_id}")
            return ""

