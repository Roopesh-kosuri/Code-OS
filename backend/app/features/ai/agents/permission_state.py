"""Shared permission state for agent execution approval flow."""
import asyncio
from typing import Dict

# Shared dictionary to store execution resume events for pending permissions
pending_permission_events: Dict[str, asyncio.Event] = {}
# Stores user decisions: "approve" or "reject"
pending_permission_decisions: Dict[str, str] = {}
# Stores optional rejection feedback: text description
pending_permission_feedback: Dict[str, str] = {}
