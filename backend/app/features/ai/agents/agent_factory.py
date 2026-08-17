"""Factory for creating specialized agent instances based on role."""
from typing import Optional
from .agent_interface import BaseAgent
from .coder import CoderAgent
from .reviewer import ReviewerAgent
from .tester import TesterAgent
from .documenter import DocumenterAgent
from .auditor import AuditorAgent


class AgentFactory:
    """Factory for creating specialized agent instances."""
    
    @staticmethod
    def create_agent(role: str, provider_config: Optional[dict] = None) -> BaseAgent:
        """Create an agent instance based on the role string."""
        role_lower = role.lower()
        
        if "coding" in role_lower or "coder" in role_lower:
            return CoderAgent(provider_config=provider_config)
        elif "audit" in role_lower or "verifier" in role_lower:
            return AuditorAgent(provider_config=provider_config)
        elif "review" in role_lower:
            return ReviewerAgent(provider_config=provider_config)
        elif "testing" in role_lower or "tester" in role_lower or "qa" in role_lower:
            return TesterAgent(provider_config=provider_config)
        elif "documentation" in role_lower or "documenter" in role_lower:
            return DocumenterAgent(provider_config=provider_config)
        else:
            # Fall back to CoderAgent for unrecognized roles
            import logging
            logging.getLogger(__name__).warning("Unrecognized agent role '%s', defaulting to CoderAgent", role)
            return CoderAgent(provider_config=provider_config)

