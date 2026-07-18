"""Multi-agent system with specialized agent implementations."""

from .agent_interface import BaseAgent, AgentOutput
from .agent_factory import AgentFactory
from .coder import CoderAgent
from .reviewer import ReviewerAgent
from .tester import TesterAgent
from .documenter import DocumenterAgent

__all__ = [
    "BaseAgent",
    "AgentOutput", 
    "AgentFactory",
    "CoderAgent",
    "ReviewerAgent",
    "TesterAgent",
    "DocumenterAgent"
]
