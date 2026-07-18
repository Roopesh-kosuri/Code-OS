import logging
import os
import re
import json
from pathlib import Path
from typing import Optional, Dict, Any
from backend.app.features.ai.agents.agent_interface import BaseAgent, AgentOutput
from backend.app.features.ai.service import provider_for
from backend.app.features.ai.schemas import ChatRequest, ChatMessage
from backend.app.features.ai.job_service import add_job_log
from backend.app.features.ai.event_bus import event_bus
from backend.app.core.paths import normalize_path

logger = logging.getLogger(__name__)


class TesterAgent(BaseAgent):
    """Specialized agent for running test suites and parsing results."""
    
    def __init__(self, provider_config=None) -> None:
        super().__init__("Testing Agent", provider_config=provider_config)
    
    def get_system_prompt(self) -> str:
        return """You are a QA and Testing Agent. Your role is to execute test suites and analyze results.
- Detect the appropriate test runner for the project (pytest, jest, etc.)
- Execute tests via the standard command for that runner
- Parse test output to extract pass/fail counts, failing test names, and error details
- Provide structured test results for further analysis
- If tests fail, suggest specific fixes based on the error messages"""
    
    def detect_test_runner(self, workspace: str) -> Optional[Dict[str, Any]]:
        """Detect the test runner type and command for the workspace."""
        workspace_path = normalize_path(workspace)
        
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
                        content = (workspace_path / indicator).read_text()
                        if "pytest" in content.lower():
                            return {"type": "pytest", "command": "python -m pytest", "indicator": indicator}
                    except Exception:
                        pass
                elif indicator == "setup.cfg":
                    try:
                        content = (workspace_path / indicator).read_text()
                        if "[tool:pytest]" in content or "[pytest]" in content:
                            return {"type": "pytest", "command": "python -m pytest", "indicator": indicator}
                    except Exception:
                        pass
                else:
                    return {"type": "pytest", "command": "python -m pytest", "indicator": indicator}
        
        # Check for Node.js/npm/jest
        package_json = workspace_path / "package.json"
        if package_json.exists():
            try:
                content = package_json.read_text()
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
                    return {"type": "pytest", "command": "python -m pytest", "indicator": f"test files ({pattern})"}
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
        
        if runner_type == "pytest":
            # Parse pytest output
            # Example: "5 passed, 2 failed in 1.23s"
            summary_match = re.search(r'(\d+)\s+passed(?:,\s+(\d+)\s+failed)?(?:,\s+(\d+)\s+skipped)?(?:\s+in\s+([\d.]+s))?', output)
            if summary_match:
                result["passed"] = int(summary_match.group(1) or 0)
                result["failed"] = int(summary_match.group(2) or 0)
                result["skipped"] = int(summary_match.group(3) or 0)
                result["duration"] = summary_match.group(4)
                result["total"] = result["passed"] + result["failed"] + result["skipped"]
            
            # Extract failing test names and errors
            failed_section = re.search(r'=+\s*FAILED\s*=+(.*?)(?:=+\s*|$', output, re.DOTALL)
            if failed_section:
                failed_tests = re.findall(r'([^\s]+)\s+(FAILED|ERROR)', failed_section.group(1))
                for test_name, status in failed_tests:
                    # Try to extract error context for this test
                    error_pattern = rf'{re.escape(test_name)}.*?(?:FAILED|ERROR).*?\n(.*?)(?=\n|\Z)'
                    error_match = re.search(error_pattern, output, re.DOTALL)
                    error_msg = error_match.group(1).strip() if error_match else "No error details available"
                    
                    result["errors"].append({
                        "test": test_name,
                        "status": status,
                        "error": error_msg[:500]  # Truncate long errors
                    })
        
        elif runner_type in ["jest", "npm"]:
            # Parse jest/npm output
            # Example: "Tests:  5 passed, 2 failed"
            tests_match = re.search(r'Tests:\s*(\d+)\s+passed(?:,\s*(\d+)\s+failed)?', output)
            if tests_match:
                result["passed"] = int(tests_match.group(1) or 0)
                result["failed"] = int(tests_match.group(2) or 0)
                result["total"] = result["passed"] + result["failed"]
            
            # Extract failing test details
            failed_patterns = re.findall(r'✕\s+([^\n]+)', output)
            for test_name in failed_patterns:
                result["errors"].append({
                    "test": test_name.strip(),
                    "status": "FAILED",
                    "error": "Check full output for details"
                })
        
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

            logs.append("No test runner detected - checking if LLM can generate test strategy")
            
            # Fall back to LLM for test strategy
            system_instruction = self.get_system_prompt()
            prompt = f"Task Title: {title}\n\nCodebase Context:\n{context}\n\nWorkspace: {workspace}\n\nNo standard test runner detected. Analyze the project and suggest a testing approach."
            
            chat_req = self.create_chat_request(
                messages=[
                    ChatMessage(role="system", content=system_instruction),
                    ChatMessage(role="user", content=prompt)
                ]
            )
            
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
                
                return AgentOutput(
                    agent_role=self.role,
                    task_id=task_id,
                    status="success",
                    confidence=0.6,
                    reasoning_summary=f"No test runner detected. Suggestion: {response[:500]}",
                    logs=logs,
                    structured_data={
                        "agent_type": "tester",
                        "test_runner_detected": False,
                        "suggestion": response
                    }
                )
            except Exception as exc:
                logs.append(f"LLM failure: {exc}")
                return AgentOutput(
                    agent_role=self.role,
                    task_id=task_id,
                    status="failure",
                    confidence=0.1,
                    reasoning_summary=f"LLM failure: {exc}",
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
