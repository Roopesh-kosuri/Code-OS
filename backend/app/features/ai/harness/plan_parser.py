from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from app.features.ai.agents.agent_tools import ToolCall
from .tool_executor import HARNESS_TOOLS, MAX_TOOL_CALLS_PER_ITERATION

logger = logging.getLogger(__name__)

_PLAN_RE = re.compile(r"\[PLAN\](.*?)\[/PLAN\]", re.DOTALL | re.IGNORECASE)
_EXTENDED_TOOL_RE = re.compile(
    r"\[TOOL_CALL:\s*(?P<name>[a-z_]+)\s*\]\s*(?P<body>.*?)\s*\[/TOOL_CALL\]",
    re.DOTALL | re.IGNORECASE,
)
_CODEBLOCK_TOOL_RE = re.compile(
    r"```(?:tool_call|json)\s*\n(\{\s*\"(?:tool|name)\"\s*:\s*\"[a-z_]+\"[\s\S]*?\})\s*```",
    re.IGNORECASE,
)
_XML_TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*\{\s*\"(?:name|tool)\"\s*:\s*\"(?P<name>[a-z_]+)\"\s*,\s*\"(?:arguments|args|parameters)\"\s*:\s*(?P<body>\{[\s\S]*?\})\s*\}\s*</tool_call>",
    re.IGNORECASE,
)
_FUNCTION_TAG_RE = re.compile(
    r"<function=(?P<name>[a-z_]+)>(?P<body>[\s\S]*?)</function>",
    re.IGNORECASE,
)

@dataclass
class DAGPlanStep:
    id: str
    title: str
    status: Literal["pending", "running", "done", "failed", "blocked"] = "pending"
    depends_on: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
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
    # Compound project creation with tests / readme / scaffolding
    creation_verbs = ("build", "create", "scaffold", "implement", "setup", "make", "generate", "write")
    compound_test_markers = (
        "with test", "and test", "with tests", "and tests", "with unit test", "with readme",
        "and readme", "test suite", "tests and", "tests &", "tests +", "including test",
    )
    if any(v in q_lower for v in creation_verbs) and any(t in q_lower for t in compound_test_markers):
        return 2, "Deep think", "Deep think: project creation with tests/readme detected"

    # Explicit size patterns: "1000 lines", "1000+ lines", "500 lines", "full stack", "fullstack"
    if re.search(r"\b\d+\+?\s*lines?\b", q_lower) or "full stack" in q_lower or "fullstack" in q_lower:
        return 2, "Deep think", "Deep think: explicit size / full-stack scope detected"

    # Multi-feature join patterns: e.g. "with chat, contacts and media sharing", "with auth, db and api"
    if re.search(r"\b(with|including|having)\s+[\w\s-]+,\s*[\w\s-]+(\s+(and|&)\s+[\w\s-]+)?", q_lower):
        return 2, "Deep think", "Deep think: multi-feature architecture detected"
    if re.search(r"\bwith\s+[\w\s-]+\s+(and|&)\s+[\w\s-]+", q_lower) and any(kw in q_lower for kw in ("app", "clone", "system", "dashboard", "site", "page", "bot", "service", "features", "cli", "tool", "project")):
        return 2, "Deep think", "Deep think: multi-feature scope joined by with/and detected"

    # Scope words and deep phrases
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

    # Deep creation verbs with app/system/cli nouns or multi-file keywords
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

    # Multi-file or multi-language generation scope
    file_targets = re.findall(r"\b[\w-]+\.(?:py|java|c|cpp|h|hpp|ts|tsx|js|jsx|html|css|go|rs|rb|php|cs|json|md)\b", q_lower)
    if len(file_targets) >= 2:
        return 2, "Deep think", f"Deep think: multi-file generation ({len(file_targets)} target files) detected"

    if re.search(r"\b(?:\d+|multiple|several)\s+languages?\b", q_lower):
        return 2, "Deep think", "Deep think: multi-language scope detected"

    # If explicit paths > 2 files attached
    if attached_paths and len(attached_paths) > 2:
        return 2, "Deep think", "Deep think: >2 attached files specified"

    # 3. Tier 1 Quick Task Checks (Single-target actions)
    # Question starters that indicate conceptual inquiry rather than direct code action
    question_starters = (
        "what does", "how does", "what is", "how do i", "explain", "why is",
        "where is", "can you explain", "tell me about", "describe", "summary of",
        "how to", "what are", "is there", "why does", "could you explain",
    )
    is_question = any(q_lower.startswith(qs) or f" {qs}" in q_lower for qs in question_starters)

    if not is_question:
        quick_task_verbs = (
            "add", "fix", "change", "rename", "update", "run", "edit",
            "modify", "replace", "delete", "remove", "insert", "append",
            "set", "write", "make", "put", "run pytest", "run test", "test",
            "execute", "format", "lint", "inspect", "check", "scan", "audit",
            "search", "find", "analyze", "create", "build", "generate",
            "scaffold", "setup", "implement",
        )
        for verb in quick_task_verbs:
            if re.search(rf"\b{re.escape(verb)}\b", q_lower):
                return 1, "Quick Task", f"Quick task: single-target action '{verb}'"

        if re.search(r"\b[\w-]+\.(py|ts|tsx|js|jsx|json|md|html|css|rs|go|c|cpp|h|java|sql)\b", q_lower):
            return 1, "Quick Task", "Quick task: specific target file detected"

    # 4. Tier 0 (Fast Answer) â€” Questions, explanations, small snippets
    if is_question:
        return 0, "Fast Answer", "Fast path: conceptual inquiry / question"

    return 0, "Fast Answer", "Fast path: standard conversational / Q&A response"


def _classify_task_effort(
    user_query: str,
    attached_paths: list[str] | None = None,
    is_agent_mode: bool = False,
    has_images: bool = False,
    client: Any = None,
    model: str = "",
) -> tuple[int, str, str]:
    """Public effort classification entrypoint."""
    tier, label, reason = _classify_rules(user_query.lower(), attached_paths)
    if is_agent_mode and tier == 0:
        return 1, "Quick Task", "Agent mode active: promoted to quick task"
    return tier, label, reason


def _is_deep_query(user_query: str, attached_paths: list[str] | None = None) -> bool:
    tier, _, _ = _classify_rules(user_query.lower(), attached_paths)
    return tier >= 2


def _is_quick_task_query(user_query: str, attached_paths: list[str] | None = None) -> bool:
    tier, _, _ = _classify_rules(user_query.lower(), attached_paths)
    return tier <= 1


def _has_escalate_marker(response: str | None) -> bool:
    if not response or not isinstance(response, str):
        return False
    return "[ESCALATE]" in response or "[ESCALATE_TO_DUO]" in response or "[DUO_ESCALATE]" in response


def _response_is_done(response: str | None) -> bool:
    if not response or not isinstance(response, str):
        return False
    return "[DONE]" in response or "[COMPLETE]" in response or "[TASK_DONE]" in response


def _parse_plan(response: str) -> list[str] | None:
    match = _PLAN_RE.search(response)
    if not match:
        return None
    raw = match.group(1).strip()
    steps = [line.lstrip("0123456789.-*• ").strip() for line in raw.splitlines() if line.strip()]
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


def _replan_on_failure(
    dag_steps: list[DAGPlanStep],
    current_step: int | None = None,
    failure_reason: str = "",
    failed_idx: int | None = None,
    error_detail: str = "",
) -> list[DAGPlanStep]:
    step_idx = failed_idx if failed_idx is not None else (current_step if current_step is not None else 0)
    reason = error_detail or failure_reason or "Step failed"
    if not dag_steps or step_idx >= len(dag_steps):
        return dag_steps
    failed_step = dag_steps[step_idx]
    failed_step.status = "failed"
    for step in dag_steps[step_idx + 1:]:
        step.status = "blocked"
    repair_step = DAGPlanStep(
        id=f"repair_{failed_step.id}",
        title=f"Repair failure in {failed_step.title}: {reason[:40]}",
        status="running",
        depends_on=[failed_step.id],
    )
    dag_steps.insert(step_idx + 1, repair_step)
    return dag_steps


def step_matches_work(step: DAGPlanStep, executed_tools: list[Any]) -> bool:
    """Determine whether the work executed in this turn satisfies and advances the DAG step."""
    if not step or not executed_tools:
        return False

    for item in executed_tools:
        if isinstance(item, dict):
            if not item.get("success", True):
                return False
        elif hasattr(item, "success"):
            if not getattr(item, "success", True):
                return False

    title_lower = step.title.lower()
    executed_names = set()
    executed_paths: list[str] = []
    executed_cmds: list[str] = []

    for item in executed_tools:
        if isinstance(item, dict):
            name = item.get("name", "")
            args = item.get("arguments") or {}
            executed_names.add(name)
            if "path" in args:
                executed_paths.append(str(args["path"]).lower())
            if "command" in args:
                executed_cmds.append(str(args["command"]).lower())
        elif hasattr(item, "name"):
            name = getattr(item, "name", "")
            args = getattr(item, "arguments", {}) or {}
            executed_names.add(name)
            if isinstance(args, dict):
                if "path" in args:
                    executed_paths.append(str(args["path"]).lower())
                if "command" in args:
                    executed_cmds.append(str(args["command"]).lower())

    lang_exts = {
        "python": [".py"],
        "py": [".py"],
        "java": [".java"],
        "c++": [".cpp", ".cc", ".cxx", ".hpp", ".h"],
        "cpp": [".cpp", ".cc", ".cxx", ".hpp", ".h"],
        " c ": [".c", ".h"],
        "rust": [".rs"],
        "go": [".go"],
        "html": [".html", ".htm"],
        "css": [".css"],
        "javascript": [".js", ".jsx"],
        "typescript": [".ts", ".tsx"],
    }
    expected_exts: list[str] = []
    padded_title = f" {title_lower} "
    for lang, exts in lang_exts.items():
        if lang in padded_title:
            expected_exts.extend(exts)

    if expected_exts and executed_paths:
        matched_ext = any(any(p.endswith(ext) for ext in expected_exts) for p in executed_paths)
        if not matched_ext:
            return False

    file_matches = re.findall(r"[\w\-.]+\.[a-zA-Z0-9]+", title_lower)
    if file_matches and executed_paths:
        if not any(any(fm in p for p in executed_paths) for fm in file_matches):
            return False

    read_tools = {"read_file", "list_directory", "search_code", "semantic_search", "find_references", "go_to_definition"}
    write_tools = {"edit_file", "append_file"}
    test_tools = {"run_test", "run_command"}

    is_read_step = any(w in title_lower for w in ["read", "inspect", "check", "examine", "view", "search", "find", "locate", "list", "explore", "analyze", "understand"])
    is_write_step = any(w in title_lower for w in ["create", "write", "edit", "implement", "update", "modify", "fix", "add", "append", "generate", "code", "build"])
    is_test_step = any(w in title_lower for w in ["test", "verify", "benchmark", "validate", "assert", "pytest", "compile"])

    if is_test_step and not (is_write_step or is_read_step):
        if not (executed_names & test_tools):
            return False

    if is_write_step and not is_read_step:
        if not (executed_names & write_tools or executed_names & test_tools):
            return False

    return True


def _declares_tool_intent(response: str | None) -> bool:
    if not response or not isinstance(response, str):
        return False
    if "[DONE]" in response:
        return False
    lower = response.lower()
    if any(res in lower for res in [
        "test passed", "tests passed", "test failed", "tests failed",
        "pytest passed", "pytest failed", "output shows", "result is",
        "exited with code", "failed with exit", "passed with", "is not working",
        "is working", "it is working", "it is not working",
    ]):
        return False

    explicit_intent_phrases = [
        "use the run_test tool", "use the run_command tool", "use the read_file tool",
        "use the edit_file tool", "use the list_directory tool", "use the search_code tool",
        "let's run pytest", "we need to run pytest", "let's run the test",
        "we need to run tests", "i will run pytest", "i will run the test",
        "let me run the test", "let me run pytest", "i'll run python", "let's run python",
        "i will execute", "let's execute", "we need to execute",
        "i will run", "let's run", "we need to run", "let me run", "i'll run",
        "edit_file", "append_file", "generate the file", "we'll output",
        "i will create", "i will generate", "let me create", "let's create",
        "we will create", "we need to create", "i'll create", "we will generate",
        "i will write", "let's write", "we'll write", "we will output", "i'll output",
        "i will output", "we'll output edit_file", "output edit_file", "output append_file",
        "create hello.html", "generate hello.html", "create file", "write file",
        "build the portfolio", "create the portfolio", "generate the portfolio",
        "creating hello.html", "generating hello.html", "let's build", "i will build",
        "we need to emit edit_file", "emit edit_file", "call edit_file", "calling edit_file",
    ]
    return any(p in lower for p in explicit_intent_phrases)


def _extract_json_object(text: str, start_idx: int = 0) -> tuple[dict | None, int]:
    idx = text.find("{", start_idx)
    while idx != -1:
        decoder = json.JSONDecoder()
        try:
            obj, end_pos = decoder.raw_decode(text[idx:])
            if isinstance(obj, dict):
                return obj, idx + end_pos
        except json.JSONDecodeError:
            pass
        idx = text.find("{", idx + 1)
    return None, -1


def _parse_harmony_format(response: str) -> list[ToolCall]:
    """Extract tool calls from OpenAI Harmony channel tokens e.g. commentary to=functions.edit_file {...}."""
    calls: list[ToolCall] = []
    for match in re.finditer(r"(?:to=(?:functions\.)?|channel:[\w\-.]+\s+to=)(?P<name>[a-z_]+)", response, re.IGNORECASE):
        name = match.group("name").lower()
        if name in HARNESS_TOOLS:
            obj, _ = _extract_json_object(response, match.end())
            if obj:
                calls.append(ToolCall(name=name, arguments=obj, raw_text=response[match.start():]))
    return calls


def _parse_described_tool_call(response: str, user_query: str = "") -> list[ToolCall]:
    calls: list[ToolCall] = []
    combined = response + " " + user_query

    code_match = re.search(r"```([a-zA-Z0-9_\-]+)?\s*\n([\s\S]+?)\n```", response)
    file_match = re.search(
        r"([a-zA-Z0-9_\-./\\]+\.(?:java|html|py|js|ts|tsx|jsx|css|json|md|txt|sh|cpp|c|rs|go|kt|cs|rb|php|sql|yaml|yml|toml|xml))",
        combined,
        re.IGNORECASE
    )
    if code_match and file_match:
        file_path = file_match.group(1).strip()
        code_content = code_match.group(2).strip()
        if len(code_content) > 5:
            calls.append(ToolCall(
                name="edit_file",
                arguments={"path": file_path, "original": "", "updated": code_content},
                raw_text=code_match.group(0)
            ))
            return calls

    obj, _ = _extract_json_object(response)
    if obj:
        if "path" in obj and ("updated" in obj or "content" in obj):
            calls.append(ToolCall(
                name="edit_file",
                arguments={"path": obj["path"], "original": obj.get("original", ""), "updated": obj.get("updated") or obj.get("content", "")},
                raw_text=str(obj)
            ))
            return calls
        elif "command" in obj:
            calls.append(ToolCall(
                name="run_command",
                arguments={"command": obj["command"]},
                raw_text=str(obj)
            ))
            return calls

    return calls


def _parse_tool_calls_extended(response: str, user_query: str = "") -> list[ToolCall]:
    calls: list[ToolCall] = []

    for match in _EXTENDED_TOOL_RE.finditer(response):
        name = match.group("name").strip().lower()
        body = match.group("body").strip()
        raw = match.group(0)

        if name not in HARNESS_TOOLS:
            logger.warning("chat_harness: skipping unknown tool '%s'", name)
            continue

        obj, _ = _extract_json_object(body)
        if obj is not None:
            args = obj
        else:
            args = {"path": body.strip().strip("\"'"), "command": body.strip(), "content": body.strip(), "fact": body.strip()}

        calls.append(ToolCall(name=name, arguments=args, raw_text=raw))

    if calls:
        return calls[:MAX_TOOL_CALLS_PER_ITERATION]

    for match in _CODEBLOCK_TOOL_RE.finditer(response):
        try:
            data = json.loads(match.group(1))
            name = (data.get("tool") or data.get("name") or "").lower()
            args = data.get("arguments") or data.get("args") or {k: v for k, v in data.items() if k not in ("tool", "name")}
            if name in HARNESS_TOOLS and isinstance(args, dict):
                calls.append(ToolCall(name=name, arguments=args, raw_text=match.group(0)))
        except Exception:
            pass

    if calls:
        return calls[:MAX_TOOL_CALLS_PER_ITERATION]

    harmony_calls = _parse_harmony_format(response)
    if harmony_calls:
        return harmony_calls[:MAX_TOOL_CALLS_PER_ITERATION]

    for match in _XML_TOOL_CALL_RE.finditer(response):
        name = match.group("name").strip().lower()
        body_str = match.group("body").strip()
        if name in HARNESS_TOOLS:
            obj, _ = _extract_json_object(body_str)
            if obj:
                calls.append(ToolCall(name=name, arguments=obj, raw_text=match.group(0)))

    for match in _FUNCTION_TAG_RE.finditer(response):
        name = match.group("name").strip().lower()
        body_str = match.group("body").strip()
        if name in HARNESS_TOOLS:
            obj, _ = _extract_json_object(body_str)
            if obj:
                args = obj
            else:
                args = {"path": body_str, "command": body_str}
            calls.append(ToolCall(name=name, arguments=args, raw_text=match.group(0)))

    if calls:
        return calls[:MAX_TOOL_CALLS_PER_ITERATION]

    described = _parse_described_tool_call(response, user_query)
    if described:
        return described[:MAX_TOOL_CALLS_PER_ITERATION]

    heuristic = _extract_heuristic_tool_calls(response, user_query)
    if heuristic:
        return heuristic[:MAX_TOOL_CALLS_PER_ITERATION]

    return calls[:MAX_TOOL_CALLS_PER_ITERATION]


def _has_tool_calls_extended(response: str | None, user_query: str = "") -> bool:
    if not response or not isinstance(response, str):
        return False
    if bool(_EXTENDED_TOOL_RE.search(response)) or bool(_CODEBLOCK_TOOL_RE.search(response)):
        return True
    if bool(_XML_TOOL_CALL_RE.search(response)) or bool(_FUNCTION_TAG_RE.search(response)):
        return True
    if bool(re.search(r"(?:to=(?:functions\.)?|channel:[\w\-.]+\s+to=)[a-z_]+", response, re.IGNORECASE)):
        return True
    if len(_parse_tool_calls_extended(response, user_query)) > 0:
        return True
    return False


def _extract_heuristic_tool_calls(response: str, user_query: str = "") -> list[ToolCall]:
    calls: list[ToolCall] = []
    lower_resp = response.lower()

    # 1. Test execution intent
    test_intents = [
        "use the run_test tool", "i will run the test", "let me run the test",
        "we need to run tests", "let's run pytest", "we need to run pytest",
        "let's run the test", "i will run pytest", "i'll run pytest", "i'll run the test",
    ]
    if any(ti in lower_resp for ti in test_intents):
        test_file_match = re.search(r"([\w\-./\\]*test[\w\-./\\]*\.py)", response + " " + user_query, re.IGNORECASE)
        if test_file_match:
            cmd = f"pytest {test_file_match.group(1)}"
            calls.append(ToolCall(name="run_command", arguments={"command": cmd}))
        else:
            calls.append(ToolCall(name="run_command", arguments={"command": "pytest"}))
        return calls

    # 2. Terminal command execution intent
    cmd_intents = [
        "use the run_command tool", "i will run the command", "let me run the command",
        "we need to run the command", "let's run the command", "execute the command",
    ]
    if any(ci in lower_resp for ci in cmd_intents):
        cmd_match = re.search(r"`([^`]+)`", response)
        if cmd_match:
            calls.append(ToolCall(name="run_command", arguments={"command": cmd_match.group(1)}))
            return calls

    # 3. Read file intent
    read_intents = [
        "use the read_file tool", "let me read the file", "i will read the file",
        "we need to read the file", "let's read the file",
    ]
    if any(ri in lower_resp for ri in read_intents):
        file_match = re.search(r"`([^`]+\.[a-zA-Z0-9]+)`", response) or re.search(r"([\w\-./\\]+\.[a-zA-Z0-9]+)", response)
        if file_match:
            calls.append(ToolCall(name="read_file", arguments={"path": file_match.group(1)}))
            return calls

    # 4. File creation / edit intent with code block in response
    edit_intents = [
        "edit_file", "append_file", "generate the file", "we'll output", "i will create",
        "we will create", "let me create", "let's create", "i'll create", "we will generate",
        "i will write", "let's write", "we'll write", "here is the code", "here is the full",
        "here is hello.html", "here is the file", "create hello.html", "generate hello.html",
        "portfolio", "html", "creating hello.html", "generating hello.html", "calculator",
        "java", "create an file", "write an code", "write a code", "create a file",
    ]
    if any(ei in lower_resp for ei in edit_intents):
        code_match = re.search(r"```([a-zA-Z0-9_\-]+)?\s*\n([\s\S]+?)\n```", response)
        if code_match:
            code_content = code_match.group(2).strip()
            file_match = re.search(
                r"([a-zA-Z0-9_\-./\\]+\.(?:java|html|py|js|ts|tsx|jsx|css|json|md|txt|sh|cpp|c|rs|go|kt|cs|rb|php|sql|yaml|yml|toml|xml))",
                response + " " + user_query,
                re.IGNORECASE
            )
            if file_match and len(code_content) > 5:
                file_path = file_match.group(1).strip()
                calls.append(ToolCall(name="edit_file", arguments={"path": file_path, "original": "", "updated": code_content}))
                return calls

    # 5. Visual inspection intent
    vision_intents = [
        "take_screenshot", "inspect_visuals", "look at the page", "look at the screenshot",
        "visually inspect", "check visually", "look at the rendered", "see what's on screen",
        "tell me what's broken visually", "look at the html",
    ]
    if any(vi in lower_resp for vi in vision_intents):
        target_match = re.search(r"([a-zA-Z0-9_\-./\\]+\.(?:html|htm))", response + " " + user_query)
        if target_match:
            calls.append(ToolCall(name="take_screenshot", arguments={"mode": "preview", "target": target_match.group(1), "question": user_query or "Describe visual layout, alignment, and broken elements."}))
            return calls
        elif "screen" in lower_resp or "app" in lower_resp or "code os" in lower_resp:
            calls.append(ToolCall(name="take_screenshot", arguments={"mode": "app_window", "question": user_query or "Describe what is currently displayed on screen in CODE OS."}))
            return calls

    return calls


class PlanParser:
    @staticmethod
    def classify(q_lower: str, attached_paths: list[str] | None = None) -> tuple[int, str, str]:
        return _classify_rules(q_lower, attached_paths)

    @staticmethod
    def parse_plan(response: str) -> list[str] | None:
        return _parse_plan(response)

    @staticmethod
    def parse_dag(response: str) -> list[DAGPlanStep] | None:
        return _parse_plan_dag(response)

    @staticmethod
    def step_matches_work(step: DAGPlanStep, executed_tools: list[Any]) -> bool:
        return step_matches_work(step, executed_tools)

    @staticmethod
    def parse_tool_calls(response: str, user_query: str = ""):
        return _parse_tool_calls_extended(response, user_query)

    @staticmethod
    def has_tool_calls(response: str | None, user_query: str = "") -> bool:
        return _has_tool_calls_extended(response, user_query)
