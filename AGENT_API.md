# CODE OS Agent API and Execution Guide

CODE OS features a multi-agent orchestration architecture. Agents communicate and execute subtasks using structured `AgentJob` queues stored in SQLite.

## Base Agent Abstract Class

All specialized engineering agents inherit from `BaseAgent` and override the execution handlers:

```python
from abc import ABC, abstractmethod
from typing import Dict, Any, List

class BaseAgent(ABC):
    def __init__(self, role: str):
        self.role = role

    @abstractmethod
    async def execute_task(self, task_payload: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Receives a structured task and returns execution results or code diffs.
        """
        pass
```

## Creating a Specialized Agent Subclass

To add a new agent role (e.g. security scanner):

```python
from backend.app.features.ai.agents.base import BaseAgent

class SecurityScannerAgent(BaseAgent):
    def __init__(self):
        super().__init__(role="security-scanner")

    async def execute_task(self, task_payload: dict, context: dict) -> dict:
        code_content = task_payload.get("code")
        # Run scanning logic ...
        issues = ["hardcoded-secret-detected"]
        return {
            "status": "completed",
            "findings": issues,
            "requires_action": len(issues) > 0
        }
```

## Task Lifecycle and Orchestration
1. **Planner Agent**: Generates the list of `agent_tasks` matching the user prompt.
2. **Specialized Worker Agents**: (Coding, Testing, Documentation) execute sub-tasks and return results.
3. **Review Agent**: Validates diffs and outputs approvals or requests fixes.
4. **Task Executor**: Commits verified modifications to the workspace database and disk.
