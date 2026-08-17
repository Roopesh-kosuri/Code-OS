import logging
import os
import re
import json
from pathlib import Path
from typing import Optional, Dict, Any
from .agent_interface import BaseAgent, AgentOutput
from ..service import provider_for
from ..schemas import ChatRequest, ChatMessage
from ..job_service import add_job_log
from ..event_bus import event_bus
from ....core.paths import normalize_path

logger = logging.getLogger(__name__)


class TesterAgent(BaseAgent):
    """Specialized agent for running test suites and parsing results."""
    
    def __init__(self, provider_config=None) -> None:
        super().__init__("Testing Agent", provider_config=provider_config)
    
    def get_system_prompt(self) -> str:
        from .agent_tools import get_tool_instructions
        return """You are a QA and Testing Agent. Your role is to write comprehensive unit tests, execute test suites, and analyze results.
- CRITICAL: Always use read_file to inspect the actual implementation, class names, methods, and exports before writing tests.
- Do NOT guess or hallucinate class names, function signatures, or module paths. Read the source code first!
- Detect the appropriate test runner for the project (pytest, jest, etc.)
- When generating unit tests, return proposals using the [PROPOSAL] block format or edit_file tool
- Write tests that match the real imports and real signatures of the workspace files
- If tests fail, suggest specific fixes based on the error messages""" + get_tool_instructions(allow_edit=True)
    
    def detect_test_runner(self, workspace: str) -> Optional[Dict[str, Any]]:
        """Detect the test runner type and command for the workspace."""
        workspace_path = normalize_path(workspace)
        python_cmd = "python -m pytest"
        
        # Check for Python/pytest
        python_indicators = [
            "pytest.ini",
            "conftest.py", 
            "pyproject.toml",
            "setup.cfg",
            "tox.ini"
        ]
        
        for indicator in python_indicators:
            if (workspace_path / indicator).exists():
                # Verify it's actually pytest configuration
                if indicator == "pyproject.toml":
                    try:
                        content = (workspace_path / indicator).read_text(encoding="utf-8", errors="ignore")
                        if "pytest" in content.lower():
                            return {"type": "pytest", "command": python_cmd, "indicator": indicator}
                    except Exception:
                        pass
                elif indicator == "setup.cfg":
                    try:
                        content = (workspace_path / indicator).read_text(encoding="utf-8", errors="ignore")
                        if "[tool:pytest]" in content or "[pytest]" in content:
                            return {"type": "pytest", "command": python_cmd, "indicator": indicator}
                    except Exception:
                        pass
                else:
                    return {"type": "pytest", "command": python_cmd, "indicator": indicator}
        
        # Check for Node.js/npm/jest
        package_json = workspace_path / "package.json"
        if package_json.exists():
            try:
                content = package_json.read_text(encoding="utf-8", errors="ignore")
                pkg_data = json.loads(content)
                scripts = pkg_data.get("scripts", {})
                
                # Check for test scripts
                if "test" in scripts:
                    test_script = scripts["test"]
                    if "jest" in test_script.lower():
                        return {"type": "jest", "command": "npm test", "indicator": "package.json"}
                    elif "pytest" in test_script.lower():
                        return {"type": "pytest", "command": "npm test", "indicator": "package.json"}
                    else:
                        return {"type": "npm", "command": "npm test", "indicator": "package.json"}
                
                # Check for jest in dependencies
                deps = {**pkg_data.get("dependencies", {}), **pkg_data.get("devDependencies", {})}
                if "jest" in deps:
                    return {"type": "jest", "command": "npm test", "indicator": "package.json (jest dependency)"}
                    
            except Exception as e:
                logger.warning("Failed to parse package.json: %s", e)
        
        # Check for test files as a fallback
        test_patterns = ["test_*.py", "*_test.py", "*.test.js", "*.spec.js"]
        for pattern in test_patterns:
            if list(workspace_path.rglob(pattern)):
                # Can determine runner from file extension
                if pattern.endswith(".py"):
                    return {"type": "pytest", "command": python_cmd, "indicator": f"test files ({pattern})"}
                elif pattern.endswith(".js"):
                    return {"type": "jest", "command": "npm test", "indicator": f"test files ({pattern})"}
        
        return None
    
    def parse_test_output(self, output: str, runner_type: str) -> Dict[str, Any]:
        """Parse test output to extract structured results."""
        result = {
            "runner": runner_type,
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "errors": [],
            "duration": None
        }
        
        try:
            if runner_type == "pytest":
                # Parse pytest summary counts flexibly (any order)
                passed_m = re.search(r'(\d+)\s+passed', output)
                failed_m = re.search(r'(\d+)\s+failed', output)
                error_m = re.search(r'(\d+)\s+error', output)
                skipped_m = re.search(r'(\d+)\s+skipped', output)
                dur_m = re.search(r'in\s+([\d.]+s)', output)

                if passed_m:
                    result["passed"] = int(passed_m.group(1))
                if failed_m:
                    result["failed"] = int(failed_m.group(1))
                elif error_m:
                    result["failed"] = int(error_m.group(1))
                if skipped_m:
                    result["skipped"] = int(skipped_m.group(1))
                if dur_m:
                    result["duration"] = dur_m.group(1)
                result["total"] = result["passed"] + result["failed"] + result["skipped"]
                
                # Extract failing test names and errors
                failed_section = re.search(r'=+\s*(?:FAILURES|ERRORS|FAILED)\s*=+(.*?)(?:=+\s*|$)', output, re.DOTALL)
                if failed_section:
                    failed_tests = re.findall(r'([^\s]+)\s+(FAILED|ERROR)', failed_section.group(1))
                    for test_name, status in failed_tests:
                        error_pattern = rf'{re.escape(test_name)}.*?(?:FAILED|ERROR).*?\n(.*?)(?=\n|\Z)'
                        error_match = re.search(error_pattern, output, re.DOTALL)
                        error_msg = error_match.group(1).strip() if error_match else "No error details available"
                        
                        result["errors"].append({
                            "test": test_name,
                            "status": status,
                            "error": error_msg[:500]
                        })
            
            elif runner_type in ["jest", "npm"]:
                tests_match = re.search(r'Tests:\s*(\d+)\s+passed(?:,\s*(\d+)\s+failed)?', output)
                if tests_match:
                    result["passed"] = int(tests_match.group(1) or 0)
                    result["failed"] = int(tests_match.group(2) or 0)
                    result["total"] = result["passed"] + result["failed"]
                
                failed_patterns = re.findall(r'✕\s+([^\n]+)', output)
                for test_name in failed_patterns:
                    result["errors"].append({
                        "test": test_name.strip(),
                        "status": "FAILED",
                        "error": "Check full output for details"
                    })
        except Exception as parse_exc:
            logger.warning("TesterAgent parse_test_output error: %s", parse_exc)
        
        return result
    
    async def execute_test_command(self, workspace: str, command: str) -> tuple[str, int]:
        """Execute a test command using the terminal service."""
        from ...terminal.service import create_session, run_command, kill_session
        
        # Create a temporary terminal session
        session = create_session(workspace)
        
        try:
            output, returncode, _ = await run_command(session.id, command, background=False)
            return output, returncode
        finally:
            # Clean up the session
            kill_session(session.id)
    
    async def execute(self, job_id: str, task_id: str, title: str, context: str, workspace: str) -> AgentOutput:
        logger.info("TesterAgent.execute task_id=%s title=%s", task_id, title)
        logs = []
        
        logs.append(f"TesterAgent initializing test execution...")
        await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
        
        # 1. Detect test runner
        test_runner = self.detect_test_runner(workspace)
        if not test_runner:
            is_low_complexity = "test" not in title.lower() and "coverage" not in title.lower() and "--quick" not in title.lower()
            if is_low_complexity:
                logs.append("No test runner detected. Skipping LLM test strategy suggestion for low-complexity task.")
                await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
                return AgentOutput(
                    agent_role=self.role,
                    task_id=task_id,
                    status="success",
                    confidence=0.5,
                    reasoning_summary="No test runner detected; skipped strategy suggestion.",
                    logs=logs,
                    structured_data={
                        "agent_type": "tester",
                        "test_runner_detected": False,
                        "suggestion": "No tests run."
                    }
                )

            logs.append("No test runner detected - running TesterAgent with workspace tools to generate unit tests")
            
            # Fall back to LLM for test generation with tools
            system_instruction = self.get_system_prompt()
            prompt = (
                f"Task Title: {title}\n\n"
                f"Codebase Context:\n{context}\n\n"
                f"Workspace: {workspace}\n\n"
                f"Use read_file / list_directory to inspect the real implementation files first, then write unit tests that accurately import and test the real functions/classes."
            )
            
            from .agent_tools import parse_tool_calls, has_tool_calls, execute_tool_calls, MAX_TOOL_ITERATIONS, TOOL_PHASE_TIMEOUT_SECONDS
            import time

            messages = [
                ChatMessage(role="system", content=system_instruction),
                ChatMessage(role="user", content=prompt)
            ]
            
            test_proposals = []
            staged_changes = []
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
                            logs.append(f"🔧 [TOOL] Tester Iteration {tool_iteration}: {len(tool_calls)} tool call(s) — {', '.join(tool_names)}")
                            await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})

                            tool_results_text = execute_tool_calls(tool_calls, workspace, staged_changes)

                            messages.append(ChatMessage(role="assistant", content=response))
                            messages.append(ChatMessage(role="user", content=f"Tool results:\n\n{tool_results_text}\n\nContinue with writing unit tests. Use more tools if needed, or output your final [PROPOSAL] blocks and [DONE] when finished."))

                            tool_iteration += 1
                            if time.time() - tool_start_time > TOOL_PHASE_TIMEOUT_SECONDS:
                                break
                            continue
                    break
                
                from ..service import extract_proposals_robust
                test_proposals = extract_proposals_robust(final_response)
                
                if staged_changes:
                    for staged in staged_changes:
                        if staged.path not in {p.path for p in test_proposals}:
                            test_proposals.append(staged)

                proposal_dicts = [p.dict() if hasattr(p, 'dict') else p.model_dump() for p in test_proposals]
                for p in test_proposals:
                    logs.append(f"TesterAgent generated test file: {p.path}")
                
                return AgentOutput(
                    agent_role=self.role,
                    task_id=task_id,
                    status="success",
                    confidence=0.7,
                    reasoning_summary=f"Generated {len(test_proposals)} test file(s). Suggestion: {final_response[:300]}",
                    proposals=proposal_dicts,
                    logs=logs,
                    structured_data={
                        "agent_type": "tester",
                        "test_runner_detected": False,
                        "suggestion": final_response,
                        "files_modified": len(test_proposals)
                    }
                )
            except Exception as exc:
                logs.append(f"TesterAgent failure: {exc}")
                return AgentOutput(
                    agent_role=self.role,
                    task_id=task_id,
                    status="failure",
                    confidence=0.1,
                    reasoning_summary=f"Test execution/generation failed: {exc}",
                    logs=logs
                )
        
        logs.append(f"Detected test runner: {test_runner['type']} (command: {test_runner['command']})")
        await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
        
        # 2. Request permission to run tests
        permission_details = f"Execute test suite using {test_runner['type']} with command: {test_runner['command']}"
        allowed = await self.request_permission(
            job_id, task_id, "execute_command", 
            permission_details, test_runner['command']
        )
        
        if not allowed:
            logs.append("Test execution permission denied by user")
            return AgentOutput(
                agent_role=self.role,
                task_id=task_id,
                status="failure",
                confidence=0.0,
                reasoning_summary="Test execution permission denied by user",
                logs=logs,
                structured_data={
                    "agent_type": "tester",
                    "permission_denied": True
                }
            )
        
        logs.append("Permission granted, executing tests...")
        await event_bus.publish("agent_log", {"job_id": job_id, "task_id": task_id, "message": logs[-1]})
        
        # 3. Execute the test command
        try:
            output, returncode = await self.execute_test_command(workspace, test_runner['command'])
            logs.append(f"Test command completed with exit code: {returncode}")
            
            # 4. Parse test results
            test_results = self.parse_test_output(output, test_runner['type'])
            logs.append(f"Test results: {test_results['total']} total, {test_results['passed']} passed, {test_results['failed']} failed")
            
            # Determine overall status
            if test_results['failed'] > 0:
                status = "partial_failure"
                confidence = 0.5
                reasoning = f"Tests failed: {test_results['failed']} of {test_results['total']} tests failed"
            elif test_results['passed'] > 0:
                status = "success"
                confidence = 0.9
                reasoning = f"All tests passed: {test_results['passed']} tests"
            else:
                status = "warning"
                confidence = 0.7
                reasoning = "No tests were executed"
            
            return AgentOutput(
                agent_role=self.role,
                task_id=task_id,
                status=status,
                confidence=confidence,
                reasoning_summary=reasoning,
                logs=logs,
                structured_data={
                    "agent_type": "tester",
                    "test_runner_detected": True,
                    "test_runner": test_runner,
                    "test_results": test_results,
                    "raw_output": output[-2000:] if len(output) > 2000 else output  # Truncate for storage
                }
            )
            
        except Exception as exc:
            logs.append(f"Test execution failed: {exc}")
            return AgentOutput(
                agent_role=self.role,
                task_id=task_id,
                status="failure",
                confidence=0.1,
                reasoning_summary=f"Test execution failed: {exc}",
                logs=logs,
                structured_data={
                    "agent_type": "tester",
                    "execution_error": str(exc)
                }
            )
