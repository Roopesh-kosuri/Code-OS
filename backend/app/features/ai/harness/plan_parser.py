"""
plan_parser.py - Plan parsing, DAG step tracking, and rule-based query classification.

Provides:
- Fast rule-based tier and effort classification (<1ms)
- Extraction and serialization of [PLAN] DAG structures
- In-flight replanning upon tool failure
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Literal

_PLAN_RE = re.compile(r"\[PLAN\]([\s\S]*?)\[/PLAN\]", re.IGNORECASE)


@dataclass
class DAGPlanStep:
    id: str
    title: str
    status: Literal["pending", "running", "done", "failed", "blocked"] = "pending"
    depends_on: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "depends_on": self.depends_on,
        }


def _classify_rules(q_lower: str, attached_paths: list[str] | None = None) -> tuple[int, str, str]:
    """Pure rule-based task classifier (<1ms, no network or LLM calls)."""
    # 1. Greetings and Conversational Inquiries (Tier 0 Fast Answer)
    greetings = (
        "hi", "hello", "hey", "good morning", "good afternoon", "good evening",
        "greetings", "sup", "howdy", "yo", "hi there", "hello there", "hey there",
    )
    clean_q = re.sub(r"[^\w\s]", "", q_lower).strip()
    if clean_q in greetings:
        return 0, "Fast Answer", "Fast path: greeting"
    if any(clean_q.startswith(g + " ") for g in greetings) and len(clean_q.split()) <= 4 and not any(v in clean_q for v in ("build", "create", "fix", "add", "run", "edit", "delete", "make")):
        return 0, "Fast Answer", "Fast path: conversational greeting"

    # 2. Tier 2 Scope Checks (Deep Think)
    creation_verbs = ("build", "create", "scaffold", "implement", "setup", "make", "generate", "write")
    compound_test_markers = (
        "with test", "and test", "with tests", "and tests", "with unit test", "with readme",
        "and readme", "test suite", "tests and", "tests &", "tests +", "including test",
    )
    if any(v in q_lower for v in creation_verbs) and any(t in q_lower for t in compound_test_markers):
        return 2, "Deep think", "Deep think: project creation with tests/readme detected"

    if re.search(r"\b\d+\+?\s*lines?\b", q_lower) or "full stack" in q_lower or "fullstack" in q_lower:
        return 2, "Deep think", "Deep think: explicit size / full-stack scope detected"

    if re.search(r"\b(with|including|having)\s+[\w\s-]+,\s*[\w\s-]+(\s+(and|&)\s+[\w\s-]+)?", q_lower):
        return 2, "Deep think", "Deep think: multi-feature architecture detected"
    if re.search(r"\bwith\s+[\w\s-]+\s+(and|&)\s+[\w\s-]+", q_lower) and any(kw in q_lower for kw in ("app", "clone", "system", "dashboard", "site", "page", "bot", "service", "features", "cli", "tool", "project")):
        return 2, "Deep think", "Deep think: multi-feature scope joined by with/and detected"

    tier2_scope_words = (
        "clone", "entire", "full", "complete", "website", "dashboard",
        "portfolio", "from scratch", "architecture", "entire codebase", "all files",
        "across the project", "full system", "redesign", "port to", "migrate",
        "rewrite", "debug and fix all", "refactor", "system", "files in workspace",
        "analyze files", "scan all", "audit all",
    )
    for word in tier2_scope_words:
        if re.search(rf"\b{re.escape(word)}\b", q_lower):
            return 2, "Deep think", f"Deep think: scope keyword '{word}' detected"

    deep_generation_verbs = ("build", "create", "design", "implement", "generate", "analyze", "scaffold", "setup")
    deep_generation_nouns = (
        "app", "application", "system", "clone", "platform", "portal", "dashboard",
        "portfolio", "website", "service", "game", "extension", "project", "layout",
        "html", "site", "page", "file", "codebase", "workspace", "cli", "tool",
        "package", "module", "repo", "repository", "program", "script", "backend",
        "frontend", "fullstack", "library", "component", "widget", "suite",
    )
    for verb in deep_generation_verbs:
        if re.search(rf"\b{verb}\b", q_lower):
            for noun in deep_generation_nouns:
                if re.search(rf"\b{noun}\b", q_lower):
                    return 2, "Deep think", f"Deep think: project creation '{verb} {noun}' detected"
            if "multiple" in q_lower or "multi-file" in q_lower or "multifile" in q_lower or "huge" in q_lower:
                return 2, "Deep think", f"Deep think: multi-file generation '{verb}' detected"

    # Default Tier 1 Task Plan
    return 1, "Task Plan", "Task plan: standard workspace query"


def _classify_task_effort(user_query: str, attached_paths: list[str] | None = None) -> tuple[str, str]:
    tier, label, reason = _classify_rules(user_query.lower(), attached_paths)
    if tier == 0:
        return "quick", reason
    elif tier == 2:
        return "deep", reason
    return "standard", reason


def _is_deep_query(q_lower: str, attached_paths: list[str] | None = None) -> bool:
    tier, _, _ = _classify_rules(q_lower, attached_paths)
    return tier == 2


def _is_quick_task_query(q_lower: str, attached_paths: list[str] | None = None) -> bool:
    tier, _, _ = _classify_rules(q_lower, attached_paths)
    return tier == 0


def _parse_plan(response: str) -> list[str] | None:
    match = _PLAN_RE.search(response)
    if not match:
        return None
    raw_steps = match.group(1).strip().splitlines()
    steps: list[str] = []
    for line in raw_steps:
        line = line.strip()
        if not line:
            continue
        line = re.sub(r"^[\d]+[.)]\s*", "", line)
        line = re.sub(r"^[-*]\s*", "", line)
        line = line.strip()
        if line:
            steps.append(line)
    return steps if steps else None


def _parse_plan_dag(response: str) -> list[DAGPlanStep] | None:
    match = _PLAN_RE.search(response)
    if not match:
        return None
    raw_steps = match.group(1).strip().splitlines()
    steps: list[DAGPlanStep] = []
    for idx, line in enumerate(raw_steps):
        line = line.strip()
        if not line:
            continue
        cleaned = re.sub(r"^[\d]+[.)]\s*", "", line)
        cleaned = re.sub(r"^[-*]\s*", "", cleaned).strip()
        if not cleaned:
            continue
        step_id = f"step_{idx + 1}"
        deps: list[str] = []
        dep_match = re.search(r"\((?:depends on|after)\s*([\d,\s]+)\)", cleaned, re.IGNORECASE)
        if dep_match:
            raw_nums = re.findall(r"\d+", dep_match.group(1))
            deps = [f"step_{n}" for n in raw_nums]
            cleaned = re.sub(r"\((?:depends on|after)\s*[\d,\s]+\)", "", cleaned, flags=re.IGNORECASE).strip()
        elif idx > 0:
            deps = [f"step_{idx}"]
        steps.append(DAGPlanStep(id=step_id, title=cleaned, status="pending", depends_on=deps))
    return steps if steps else None


def _replan_on_failure(steps: list[DAGPlanStep], failed_idx: int, error_detail: str) -> list[DAGPlanStep]:
    if failed_idx < 0 or failed_idx >= len(steps):
        return steps
    failed_step = steps[failed_idx]
    failed_step.status = "failed"
    failed_id = failed_step.id

    for s in steps:
        if failed_id in s.depends_on and s.status == "pending":
            s.status = "blocked"

    fix_id = f"fix_{failed_id}_{int(time.time())}"
    fix_title = f"Repair failure in {failed_step.title}: {error_detail[:50]}"
    fix_step = DAGPlanStep(id=fix_id, title=fix_title, status="running", depends_on=[failed_id])
    return list(steps[:failed_idx + 1]) + [fix_step] + list(steps[failed_idx + 1:])


def _has_escalate_marker(response: str) -> bool:
    return "[ESCALATE]" in response


def _response_is_done(response: str) -> bool:
    return "[DONE]" in response


def _declares_tool_intent(text: str) -> bool:
    if "[DONE]" in text:
        return False
    lower = text.lower()
    if any(res in lower for res in [
        "test passed", "tests passed", "test failed", "tests failed",
        "pytest passed", "pytest failed", "output shows", "result is",
        "exited with code", "failed with exit", "passed with", "is not working",
        "is working", "it is working", "it is not working",
    ]):
        return False
    action_intents = [
        "i will run", "let me run", "i will execute", "let me execute",
        "i'll run", "i will check", "let me check", "now i will test",
        "running the test", "running test", "now running", "i will write",
        "let me write", "i will edit", "let me edit", "i will create",
        "let me create", "i will apply", "let me apply", "i will read",
        "let me read", "reading the file", "reading file", "running the command",
    ]
    return any(intent in lower for intent in action_intents)


class PlanParser:
    """Class wrapper providing plan extraction and task classification."""

    @staticmethod
    def parse_plan(response: str) -> list[str] | None:
        return _parse_plan(response)

    @staticmethod
    def parse_dag(response: str) -> list[DAGPlanStep] | None:
        return _parse_plan_dag(response)

    @staticmethod
    def replan(steps: list[DAGPlanStep], failed_idx: int, error_detail: str) -> list[DAGPlanStep]:
        return _replan_on_failure(steps, failed_idx, error_detail)

    @staticmethod
    def classify(query: str, attached: list[str] | None = None) -> tuple[int, str, str]:
        return _classify_rules(query.lower(), attached)