import logging
import json
import re
from typing import Optional
from .agent_interface import BaseAgent, AgentOutput
from ..service import provider_for
from ..schemas import ChatRequest, ChatMessage
from ..job_service import add_job_log
from ..event_bus import event_bus

logger = logging.getLogger(__name__)


class ReviewerAgent(BaseAgent):
    """Specialized agent for code review with structured feedback."""
    
    def __init__(self, provider_config=None) -> None:
        super().__init__("Review Agent", provider_config=provider_config)
    
    def get_system_prompt(self) -> str:
        return """You are a Code Review Agent. Audit code for quality, security, and maintainability.
- Analyze code structure, logic flaws, and architecture violations
- Check for style consistency and best practices
- Identify security vulnerabilities (OWASP Top 10, injection vectors, credential leaks)
- Flag performance issues and bottlenecks
- Return structured feedback in JSON format with issues, severity, and suggested fixes

Output format:
{
  "issues": [
    {
      "file": "path/to/file.py",
      "line": 42,
      "severity": "high|medium|low",
      "category": "security|performance|style|logic|architecture",
      "description": "Clear description of the issue",
      "suggested_fix": "Specific actionable fix"
    }
  ],
  "approved": false,
  "summary": "Overall assessment"
}"""
    
    async def execute(self, job_id: str, task_id: str, title: str, context: str, workspace: str) -> AgentOutput:
        logger.info("ReviewerAgent.execute task_id=%s title=%s", task_id, title)
        logs = []
        
        logs.append(f"ReviewerAgent initializing code review...")
        await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
        
        # Generate specialized instruction
        system_instruction = self.get_system_prompt()
        prompt = f"Task Title: {title}\n\nCodebase Context:\n{context}\n\nWorkspace: {workspace}\n\nPerform a thorough code review and return structured JSON feedback."
        
        # Call LLM
        chat_req = self.create_chat_request(
            messages=[
                ChatMessage(role="system", content=system_instruction),
                ChatMessage(role="user", content=prompt)
            ]
        )
        
        reasoning = ""
        structured_data = {}
        
        try:
            response = ""
            while True:
                try:
                    provider = await provider_for(chat_req)
                    tokens = []
                    async for token in provider.stream_chat(chat_req.model, chat_req.messages, temperature=0.1):
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
            
            logs.append(f"ReviewerAgent completed analysis.")
            
            # Try to parse structured JSON from response
            try:
                # Extract JSON from response (handle markdown code blocks)
                json_match = re.search(r'\{[\s\S]*\}', response)
                if json_match:
                    structured_data = json.loads(json_match.group())
                    logs.append(f"ReviewerAgent found {len(structured_data.get('issues', []))} issues")
                else:
                    # Fallback: create a structured response from prose
                    structured_data = {
                        "issues": [],
                        "approved": False,
                        "summary": response[:500],
                        "raw_response": response
                    }
                    logs.append("ReviewerAgent could not parse structured JSON, using prose fallback")
            except json.JSONDecodeError:
                structured_data = {
                    "issues": [],
                    "approved": False,
                    "summary": response[:500],
                    "raw_response": response,
                    "parse_error": "Failed to parse JSON"
                }
                logs.append("ReviewerAgent JSON parse failed, using prose fallback")
                
            structured_data["agent_type"] = "reviewer"
            reasoning = structured_data.get("summary", "Review complete.")
            
        except Exception as exc:
            logs.append(f"ReviewerAgent LLM failure: {exc}")
            return AgentOutput(
                agent_role=self.role,
                task_id=task_id,
                status="failure",
                confidence=0.1,
                reasoning_summary=f"LLM failure: {exc}",
                logs=logs
            )
        
        return AgentOutput(
            agent_role=self.role,
            task_id=task_id,
            status="success",
            confidence=0.85,
            reasoning_summary=reasoning,
            logs=logs,
            structured_data={
                "agent_type": "reviewer",
                **structured_data
            }
        )
