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
        from .agent_tools import get_tool_instructions
        return """You are a Documentation Agent. Keep project documentation synchronized with code changes.
- Use read_file and list_directory to inspect actual code and exports before writing docs
- Update README.md files with current project information and accurate CLI/API usage
- Generate/update API documentation and schemas matching real signatures
- Write clear docstrings for functions and classes
- Maintain architecture plans and design documents
- Return proposals using the [PROPOSAL] block format or edit_file tool when changing files
- Focus on accuracy and clarity over verbosity""" + get_tool_instructions(allow_edit=True)
    
    async def execute(self, job_id: str, task_id: str, title: str, context: str, workspace: str) -> AgentOutput:
        logger.info("DocumenterAgent.execute task_id=%s title=%s", task_id, title)
        logs = []
        
        logs.append(f"DocumenterAgent initializing documentation task...")
        await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
        
        # Generate specialized instruction
        system_instruction = self.get_system_prompt()
        prompt = (
            f"Task Title: {title}\n\n"
            f"Codebase Context:\n{context}\n\n"
            f"Workspace: {workspace}\n\n"
            f"Explore workspace files using read_file/list_directory if needed, then generate or update appropriate documentation files."
        )
        
        from .agent_tools import parse_tool_calls, has_tool_calls, execute_tool_calls, MAX_TOOL_ITERATIONS, TOOL_PHASE_TIMEOUT_SECONDS
        import time

        messages = [
            ChatMessage(role="system", content=system_instruction),
            ChatMessage(role="user", content=prompt)
        ]
        
        proposals = []
        staged_changes = []
        reasoning = ""
        final_response = ""
        
        try:
            tool_iteration = 0
            tool_start_time = time.time()

            while tool_iteration <= MAX_TOOL_ITERATIONS:
                chat_req = self.create_chat_request(messages=messages)
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
                
                if response.startswith("[Error:") or "Error:" in response and len(response) < 150:
                    raise Exception(response)
                
                final_response = response

                if has_tool_calls(response) and tool_iteration < MAX_TOOL_ITERATIONS:
                    tool_calls = parse_tool_calls(response)
                    if tool_calls:
                        tool_names = [tc.name for tc in tool_calls]
                        logs.append(f"🔧 [TOOL] Documenter Iteration {tool_iteration}: {len(tool_calls)} tool call(s) — {', '.join(tool_names)}")
                        await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})

                        tool_results_text = execute_tool_calls(tool_calls, workspace, staged_changes)

                        messages.append(ChatMessage(role="assistant", content=response))
                        messages.append(ChatMessage(role="user", content=f"Tool results:\n\n{tool_results_text}\n\nContinue with your documentation. Use more tools if needed, or output your final [PROPOSAL] blocks and [DONE] when finished."))

                        tool_iteration += 1
                        if time.time() - tool_start_time > TOOL_PHASE_TIMEOUT_SECONDS:
                            break
                        continue
                break

            logs.append("DocumenterAgent completed documentation generation.")
            
            # Parse edit proposals from response text
            from ..service import extract_proposals_robust
            proposals = extract_proposals_robust(final_response, ["README.md"])
            
            # Merge tool-staged edits
            if staged_changes:
                for staged in staged_changes:
                    if staged.path not in {p.path for p in proposals}:
                        proposals.append(staged)

            # Fallback: if response is markdown documentation but no code block was matched
            if not proposals and final_response.strip() and not final_response.startswith("[Error:"):
                # If the title mentions README or docs, create README.md
                proposals.append(FileChange(path="README.md", original="", updated=final_response.strip()))

            for p in proposals:
                logs.append(f"DocumenterAgent proposed changes to file: {p.path}")
                await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
            
            reasoning = final_response[:500] + "..." if len(final_response) > 500 else final_response
            
        except Exception as exc:
            logs.append(f"DocumenterAgent failure: {exc}")
            return AgentOutput(
                agent_role=self.role,
                task_id=task_id,
                status="failure",
                confidence=0.1,
                reasoning_summary=f"Documentation generation failed: {exc}",
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
