"""
escalation_tracker.py - Feedback Loop and Outcome Tracking for Adaptive Orchestration.

Tracks escalation decisions (accepted vs declined), job outcomes (success/failure, duration),
and dynamically adapts escalation confidence scoring based on historical performance.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()

_DATA: dict[str, Any] = {
    "total_escalations": 0,
    "accepted": 0,
    "declined": 0,
    "completed_success": 0,
    "completed_failed": 0,
    "total_duration": 0.0,
    "confidence_modifier": 0.0,
    "jobs": {},
    "events": [],
}


def _calculate_stats() -> dict[str, Any]:
    with _LOCK:
        total = _DATA["total_escalations"]
        accepted = _DATA["accepted"]
        declined = _DATA["declined"]
        comp_success = _DATA["completed_success"]
        comp_failed = _DATA["completed_failed"]
        total_completed = comp_success + comp_failed
        total_dur = _DATA["total_duration"]

        success_rate = (comp_success / total_completed) if total_completed > 0 else (1.0 if accepted > 0 else 0.0)
        avg_dur = (total_dur / total_completed) if total_completed > 0 else 0.0

        return {
            "total_escalations": total,
            "accepted": accepted,
            "declined": declined,
            "success_rate": round(success_rate, 2),
            "avg_duration": round(avg_dur, 2),
        }


def record_escalation_initiated(job_id: str, task: str, reasoning: str = "") -> None:
    """Record that an escalation was accepted by the user and a team job started."""
    with _LOCK:
        _DATA["total_escalations"] += 1
        _DATA["accepted"] += 1
        _DATA["jobs"][job_id] = {
            "job_id": job_id,
            "task": task,
            "reasoning": reasoning,
            "initiated_at": time.time(),
            "status": "running",
        }
        _DATA["events"].append({
            "event": "escalation_initiated",
            "job_id": job_id,
            "task": task,
            "reasoning": reasoning,
            "timestamp": time.time(),
        })
        logger.info("Escalation initiated for job %s: %s", job_id, reasoning)


def record_escalation_completed(job_id: str, duration: float, success: bool = True) -> None:
    """Record that an escalated team job finished, updating success rates and learning."""
    with _LOCK:
        job_info = _DATA["jobs"].get(job_id, {})
        job_info["status"] = "completed" if success else "failed"
        job_info["duration"] = duration
        job_info["success"] = success

        if success:
            _DATA["completed_success"] += 1
            # Raise confidence slightly if accepted jobs succeed
            _DATA["confidence_modifier"] = min(0.15, _DATA["confidence_modifier"] + 0.02)
        else:
            _DATA["completed_failed"] += 1
            # If job failed, investigate and slightly temper confidence
            _DATA["confidence_modifier"] = max(-0.15, _DATA["confidence_modifier"] - 0.03)

        _DATA["total_duration"] += max(0.0, float(duration))
        _DATA["events"].append({
            "event": "escalation_completed",
            "job_id": job_id,
            "duration": duration,
            "success": success,
            "timestamp": time.time(),
        })
        logger.info("Escalation completed for job %s: success=%s, duration=%.1fs", job_id, success, duration)


def record_escalation_declined(task: str = "", rony_succeeded: bool = True) -> None:
    """
    Record that the user declined escalation and continued with Rony.
    If user declined escalation and Rony succeeded, lower future confidence to avoid over-escalation.
    """
    with _LOCK:
        _DATA["total_escalations"] += 1
        _DATA["declined"] += 1
        if rony_succeeded:
            # Lower confidence since Rony handled the task without needing the team
            _DATA["confidence_modifier"] = max(-0.15, _DATA["confidence_modifier"] - 0.02)

        _DATA["events"].append({
            "event": "escalation_declined",
            "task": task,
            "rony_succeeded": rony_succeeded,
            "timestamp": time.time(),
        })
        logger.info("Escalation declined by user (total declined: %d)", _DATA["declined"])


def get_escalation_stats() -> dict[str, Any]:
    """Return aggregated escalation statistics."""
    return _calculate_stats()


def get_confidence_modifier() -> float:
    """Return adaptive confidence adjustment learned from outcomes."""
    with _LOCK:
        return round(_DATA["confidence_modifier"], 3)


def reset_escalation_tracker() -> None:
    """Reset all escalation tracker state for clean testing."""
    with _LOCK:
        _DATA["total_escalations"] = 0
        _DATA["accepted"] = 0
        _DATA["declined"] = 0
        _DATA["completed_success"] = 0
        _DATA["completed_failed"] = 0
        _DATA["total_duration"] = 0.0
        _DATA["confidence_modifier"] = 0.0
        _DATA["jobs"].clear()
        _DATA["events"].clear()
