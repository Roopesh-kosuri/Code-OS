import logging
from .agent_interface import BaseAgent, AgentOutput
from ..service import provider_for
from ..schemas import ChatRequest, ChatMessage, FileChange
from ..job_service import add_job_log
from ..event_bus import event_bus

logger = logging.getLogger(__name__)


class DocumenterAgent(BaseAgent):
    """Specialized agent for generating and updating documentation."""
    
    def __init__(self, provider_config=None) -> None:
        super().__init__("Documentation Agent", provider_config=provider_config)
    
    def get_system_prompt(self) -> str:
        return """You are a Documentation Agent. Keep project documentation synchronized with code changes.
- Update README.md files with current project information
- Generate/update API documentation and schemas
- Write clear docstrings for functions and classes
- Maintain architecture plans and design documents
- Update release notes and changelogs
- Follow existing documentation style and format
- Return proposals using the [PROPOSAL] block format when changing files
- Focus on accuracy and clarity over verbosity"""
    
    async def execute(self, job_id: str, task_id: str, title: str, context: str, workspace: str) -> AgentOutput:
        logger.info("DocumenterAgent.execute task_id=%s title=%s", task_id, title)
        logs = []
        
        logs.append(f"DocumenterAgent initializing documentation task...")
        await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
        
        # Generate specialized instruction
        system_instruction = self.get_system_prompt()
        prompt = f"Task Title: {title}\n\nCodebase Context:\n{context}\n\nWorkspace: {workspace}\n\nGenerate or update appropriate documentation files."
        
        # Call LLM
        chat_req = self.create_chat_request(
            messages=[
                ChatMessage(role="system", content=system_instruction),
                ChatMessage(role="user", content=prompt)
            ]
        )
        
        proposals = []
        reasoning = ""
        
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
                    logs.append(f"[ERROR] LLM call failed: {exc}")
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
            
            logs.append(f"DocumenterAgent completed documentation generation.")
            
            # Parse edit proposals from response text
            from backend.app.features.ai.service import PROPOSAL_RE
            for match in PROPOSAL_RE.finditer(response):
                filepath = match.group("path").strip()
                original = match.group("original")
                updated = match.group("updated")
                proposals.append(FileChange(path=filepath, original=original, updated=updated))
                logs.append(f"DocumenterAgent proposed changes to file: {filepath}")
                await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
            
            reasoning = response[:500] + "..." if len(response) > 500 else response
            
        except Exception as exc:
            logs.append(f"DocumenterAgent LLM failure: {exc}")
            return AgentOutput(
                agent_role=self.role,
                task_id=task_id,
                status="failure",
                confidence=0.1,
                reasoning_summary=f"LLM failure: {exc}",
                logs=logs
            )
        
        # Convert FileChange objects to dicts for AgentOutput
        proposal_dicts = [p.dict() for p in proposals]
            
        return AgentOutput(
            agent_role=self.role,
            task_id=task_id,
            status="success",
            confidence=0.85,
            reasoning_summary=reasoning,
            proposals=proposal_dicts,
            logs=logs,
            structured_data={
                "agent_type": "documenter",
                "files_modified": len(proposals),
                "documentation_types": self._detect_doc_types([p.path for p in proposals])
            }
        )
    
    def _detect_doc_types(self, file_paths: list[str]) -> list[str]:
        """Detect types of documentation being modified."""
        doc_types = []
        for path in file_paths:
            if "README" in path.upper():
                doc_types.append("README")
            elif path.endswith(".md"):
                doc_types.append("markdown")
            elif "api" in path.lower() or "schema" in path.lower():
                doc_types.append("API documentation")
            elif "docstring" in path.lower():
                doc_types.append("docstrings")
        return list(set(doc_types))
