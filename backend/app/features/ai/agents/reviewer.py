import logging
import json
import re
import asyncio
from typing import Optional
from .agent_interface import BaseAgent, AgentOutput
from ..service import provider_for
from ..schemas import ChatRequest, ChatMessage
from ..job_service import add_job_log
from ..event_bus import event_bus
# D2: hoisted from function-level to avoid repeated inline imports (no circular import risk)
from ..providers.constants import RECOVERY_URLS as _RECOVERY_URLS, PRESET_TO_PROVIDER as _PRESET_TO_PROVIDER

logger = logging.getLogger(__name__)


class ReviewerAgent(BaseAgent):
    """Specialized agent for code review with structured feedback."""
    
    def __init__(self, provider_config=None) -> None:
        super().__init__("Review Agent", provider_config=provider_config)
    
    def get_system_prompt(self) -> str:
        from .agent_tools import get_tool_instructions
        return """You are a Code Review Agent. Audit code for quality, security, and maintainability.
- Use read_file, list_directory, and search_code to inspect the actual implementation before evaluating
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
}""" + get_tool_instructions(allow_edit=False)
    
    async def execute(self, job_id: str, task_id: str, title: str, context: str, workspace: str) -> AgentOutput:
        logger.info("ReviewerAgent.execute task_id=%s title=%s", task_id, title)
        logs = []
        
        logs.append(f"ReviewerAgent initializing code review...")
        await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
        
        # Generate specialized instruction
        system_instruction = self.get_system_prompt()
        prompt = (
            f"Task Title: {title}\n\n"
            f"Codebase Context:\n{context}\n\n"
            f"Workspace: {workspace}\n\n"
            f"Use read_file / list_directory / search_code if needed to inspect full files, then perform a thorough code review and return structured JSON feedback."
        )
        
        from .agent_tools import parse_tool_calls, has_tool_calls, execute_tool_calls, MAX_TOOL_ITERATIONS, TOOL_PHASE_TIMEOUT_SECONDS
        import time

        messages = [
            ChatMessage(role="system", content=system_instruction),
            ChatMessage(role="user", content=prompt)
        ]
        
        reasoning = ""
        structured_data = {}
        final_response = ""
        
        try:
            tool_iteration = 0
            tool_start_time = time.time()
            MAX_AUTO_RETRIES = 2

            while tool_iteration <= MAX_TOOL_ITERATIONS:
                chat_req = self.create_chat_request(messages=messages)
                response = ""
                auto_retries = 0
                while auto_retries <= MAX_AUTO_RETRIES:
                    try:
                        provider = await provider_for(chat_req)
                        tokens = []
                        async for token in provider.stream_chat(chat_req.model, chat_req.messages, temperature=0.1):
                            tokens.append(token)
                        response = "".join(tokens).strip()
                        break
                    except Exception as exc:
                        is_rate_limit = "429" in str(exc) or "rate limit" in str(exc).lower() or "quota" in str(exc).lower()
                        is_daily_limit = "tpd" in str(exc).lower() or "tokens per day" in str(exc).lower() or "daily" in str(exc).lower()
                        effective_prov = (chat_req.api_key_provider or chat_req.provider or "groq").lower()

                        if is_rate_limit and effective_prov == "groq" and "120b" in (chat_req.model or ""):
                            alt_model = "llama-3.3-70b-versatile"
                            logs.append(f"[FAILOVER] Groq model '{chat_req.model}' hit token limit. Automatically switching to '{alt_model}'...")
                            await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
                            chat_req.model = alt_model
                            if not self.provider_config:
                                self.provider_config = {}
                            self.provider_config["model"] = alt_model
                            auto_retries = 0
                            continue

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
                                    logs.append(f"[FAILOVER] Rate limit on [{effective_prov}] {chat_req.model}. Automatically falling back to [{fb_prov}] {fb_model}...")
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
                                    chat_req.base_url = new_base_url
                                    chat_req.provider = new_provider
                                    chat_req.model = fb_model
                                    chat_req.api_key_provider = new_key_provider
                                    auto_retries = 0
                                    continue
                            except Exception as fb_lookup_err:
                                logger.warning("Cross-provider fallback lookup failed: %s", fb_lookup_err)

                        logs.append(f"[ERROR] LLM call failed (auto-retry {auto_retries}/{MAX_AUTO_RETRIES}): {exc}")
                        if auto_retries >= MAX_AUTO_RETRIES:
                            decision_res = await self.handle_llm_failure(job_id, task_id, exc)
                            action = decision_res.get("action", "cancel")
                            if action == "retry":
                                auto_retries = 0
                                continue
                            elif action in ("switch_to_api", "change_model"):
                                auto_retries = 0
                                new_provider = decision_res.get("provider") or "groq"
                                new_model = decision_res.get("model") or ("llama-3.3-70b-versatile" if new_provider == "groq" else "gpt-4o")
                                new_key_provider = decision_res.get("api_key_provider") or new_provider
                                if not self.provider_config:
                                    self.provider_config = {}
                                self.provider_config["preset"] = new_provider
                                self.provider_config["provider"] = new_provider
                                self.provider_config["model"] = new_model
                                self.provider_config["api_key_provider"] = new_key_provider
                                chat_req.provider = new_provider
                                chat_req.model = new_model
                                chat_req.api_key_provider = new_key_provider
                                continue
                            else:
                                raise exc
                        else:
                            auto_retries += 1
                            await asyncio.sleep(1.5 * auto_retries)

                
                if response.startswith("[Error:") or "Error:" in response and len(response) < 150:
                    raise Exception(response)
                
                final_response = response

                if has_tool_calls(response) and tool_iteration < MAX_TOOL_ITERATIONS:
                    tool_calls = parse_tool_calls(response)
                    if tool_calls:
                        tool_names = [tc.name for tc in tool_calls]
                        logs.append(f"🔧 [TOOL] Reviewer Iteration {tool_iteration}: {len(tool_calls)} tool call(s) — {', '.join(tool_names)}")
                        await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})

                        tool_results_text = execute_tool_calls(tool_calls, workspace, [])

                        # Compact older tool messages to prevent quadratic token growth
                        if len(messages) > 4:
                            for idx in range(2, len(messages) - 2, 2):
                                if idx + 1 < len(messages):
                                    old_user_msg = messages[idx + 1]
                                    if old_user_msg.role == "user" and "Tool results:" in (old_user_msg.content or ""):
                                        if len(old_user_msg.content) > 250:
                                            old_user_msg.content = "Tool results (compacted history):\n✓ Executed previous tool calls successfully.\n"

                        messages.append(ChatMessage(role="assistant", content=response))
                        messages.append(ChatMessage(role="user", content=f"Tool results:\n\n{tool_results_text}\n\nContinue with your review. Output more tool calls if needed, or output your final JSON review."))

                        tool_iteration += 1
                        if time.time() - tool_start_time > TOOL_PHASE_TIMEOUT_SECONDS:
                            break
                        continue
                break

            logs.append("ReviewerAgent completed analysis.")
            
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
