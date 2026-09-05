"""CODE OS Multi-Agent Team Mode package."""
from .team_schemas import (
    TeamRole,
    HandoffType,
    HandoffArtifact,
    TeamConfig,
    TeamMessage,
    TeamSSEEvent,
    TeamTask,
)
from .handoff import (
    create_handoff,
    format_handoff_for_prompt,
    serialize_handoff,
    deserialize_handoff,
)
from .roles import (
    BaseTeamRole,
    ArchitectRole,
    CoderRole,
    ReviewerRole,
    TesterRole,
    DevOpsRole,
)
from .orchestrator import TeamOrchestrator

__all__ = [
    "TeamRole",
    "HandoffType",
    "HandoffArtifact",
    "TeamConfig",
    "TeamMessage",
    "TeamSSEEvent",
    "TeamTask",
    "create_handoff",
    "format_handoff_for_prompt",
    "serialize_handoff",
    "deserialize_handoff",
    "BaseTeamRole",
    "ArchitectRole",
    "CoderRole",
    "ReviewerRole",
    "TesterRole",
    "DevOpsRole",
    "TeamOrchestrator",
]
