"""Verification Matrix for CODE OS (Phase 14).

Pure logic data model, verdict computation, and deterministic completion text.
Evidence-based gating: every 'completed' claim must carry proof.
Verification never blocks or rolls back S4 mutations; it only governs what the
system is permitted to claim.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ── Status Enums ─────────────────────────────────────────────────────────────

class VerifyStatus(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    WARN = "WARN"
    SKIPPED = "SKIPPED"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"


class VerdictState(str, Enum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    FAILED = "FAILED"


# ── Data Models ──────────────────────────────────────────────────────────────

@dataclass
class VerifyResult:
    """Individual verification hook execution outcome."""
    hook: str
    status: VerifyStatus | str
    summary: str
    details: list[str] = field(default_factory=list)
    duration_ms: int = 0
    skip_reason: str | None = None
    coverage_note: str | None = None  # e.g. "partial: 20 of 47 test files"
    caveats: list[str] = field(default_factory=list)

    def __post_init__(self):
        if isinstance(self.status, str):
            try:
                self.status = VerifyStatus(self.status.upper())
            except ValueError:
                self.status = VerifyStatus.ERROR

    def to_dict(self) -> dict[str, Any]:
        return {
            "hook": self.hook,
            "status": self.status.value if isinstance(self.status, VerifyStatus) else str(self.status),
            "summary": self.summary,
            "details": self.details,
            "duration_ms": self.duration_ms,
            "skip_reason": self.skip_reason,
            "coverage_note": self.coverage_note,
            "caveats": self.caveats,
        }


@dataclass
class Verdict:
    """Consolidated verification verdict for a turn, job, or task."""
    state: VerdictState | str
    reasons: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    summary_line: str = ""

    def __post_init__(self):
        if isinstance(self.state, str):
            try:
                self.state = VerdictState(self.state.upper())
            except ValueError:
                self.state = VerdictState.UNVERIFIED

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value if isinstance(self.state, VerdictState) else str(self.state),
            "reasons": self.reasons,
            "caveats": self.caveats,
            "summary_line": self.summary_line,
        }


# ── App-level Settings & Defaults ───────────────────────────────────────────

DEFAULT_VERIFY_SETTINGS = {
    "code_os_verify_enabled": True,
    "code_os_verify_timeout_s": 120,          # clamp 5..900
    "code_os_verify_max_test_files": 20,
    "code_os_verify_baseline_max_mb": 200,
    "code_os_verify_security_enabled": True,
}


def parse_verify_settings(raw_settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Parse and validate verification settings from app-level settings dict.
    
    Falls back to defaults with a WARNING on invalid values, never crashes.
    Strictly ignores any workspace-level files or overrides.
    """
    settings = dict(DEFAULT_VERIFY_SETTINGS)
    if not raw_settings:
        return settings

    # 1. code_os_verify_enabled
    if "code_os_verify_enabled" in raw_settings:
        val = raw_settings["code_os_verify_enabled"]
        if isinstance(val, bool):
            settings["code_os_verify_enabled"] = val
        elif isinstance(val, str):
            settings["code_os_verify_enabled"] = val.lower() in ("true", "1", "yes")
        else:
            logger.warning("Invalid code_os_verify_enabled: %r; using default %s", val, settings["code_os_verify_enabled"])

    # 2. code_os_verify_timeout_s (clamp 5..900)
    if "code_os_verify_timeout_s" in raw_settings:
        val = raw_settings["code_os_verify_timeout_s"]
        try:
            int_val = int(val)
            clamped = max(5, min(900, int_val))
            settings["code_os_verify_timeout_s"] = clamped
        except (ValueError, TypeError):
            logger.warning("Invalid code_os_verify_timeout_s: %r; using default %s", val, settings["code_os_verify_timeout_s"])

    # 3. code_os_verify_max_test_files
    if "code_os_verify_max_test_files" in raw_settings:
        val = raw_settings["code_os_verify_max_test_files"]
        try:
            int_val = int(val)
            settings["code_os_verify_max_test_files"] = max(1, int_val)
        except (ValueError, TypeError):
            logger.warning("Invalid code_os_verify_max_test_files: %r; using default %s", val, settings["code_os_verify_max_test_files"])

    # 4. code_os_verify_baseline_max_mb
    if "code_os_verify_baseline_max_mb" in raw_settings:
        val = raw_settings["code_os_verify_baseline_max_mb"]
        try:
            int_val = int(val)
            settings["code_os_verify_baseline_max_mb"] = max(1, int_val)
        except (ValueError, TypeError):
            logger.warning("Invalid code_os_verify_baseline_max_mb: %r; using default %s", val, settings["code_os_verify_baseline_max_mb"])

    # 5. code_os_verify_security_enabled
    if "code_os_verify_security_enabled" in raw_settings:
        val = raw_settings["code_os_verify_security_enabled"]
        if isinstance(val, bool):
            settings["code_os_verify_security_enabled"] = val
        elif isinstance(val, str):
            settings["code_os_verify_security_enabled"] = val.lower() in ("true", "1", "yes")
        else:
            logger.warning("Invalid code_os_verify_security_enabled: %r; using default %s", val, settings["code_os_verify_security_enabled"])

    return settings


# ── File Classification Helpers ──────────────────────────────────────────────

NON_CODE_EXTENSIONS = frozenset({
    ".md", ".txt", ".rst", ".json", ".yaml", ".yml", ".toml", ".ini",
    ".cfg", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".css",
    ".scss", ".less", ".html", ".htm", ".lock", ".env", ".gitignore",
})


def is_code_file(path_str: str) -> bool:
    """Return True if path represents executable / compilable code."""
    suffix = Path(path_str).suffix.lower()
    return bool(suffix and suffix not in NON_CODE_EXTENSIONS)


def is_test_file(path_str: str) -> bool:
    """Return True if path looks like a test suite file."""
    p = Path(path_str)
    name = p.name.lower()
    parts = [part.lower() for part in p.parts]
    if "tests" in parts or "test" in parts or "__tests__" in parts:
        return True
    return name.startswith("test_") or name.endswith(("_test.py", "_test.go", ".test.ts", ".test.tsx", ".test.js", ".spec.ts", ".spec.tsx", ".spec.js"))


# ── Pure Verdict Computation (Single Source of Truth) ───────────────────────

def compute_verdict(
    results: list[VerifyResult],
    changed_files_info: dict[str, Any] | None = None,
) -> Verdict:
    """Compute the consolidated Verdict from hook results and changed file info.
    
    Strictly encodes the Phase 14 specification table:
    1. Any FAILED from readback_hash, test_suite (turn-caused), or security_scan (HIGH) -> FAILED.
    2. Any ERROR (tool crash) or TIMEOUT and no FAILED -> UNVERIFIED.
    3. readback_hash PASSED, no FAILED, and test_suite PASSED -> VERIFIED.
    4. Only non-code files changed (docs/config/assets), readback_hash PASSED -> VERIFIED (with caveat).
    5. Code changed but test_suite SKIPPED (no runner / no tests / untrusted / declined) -> UNVERIFIED.
    6. Baseline could not attribute failing tests -> UNVERIFIED ("failures could not be attributed").
    7. Failing tests that also fail at baseline -> listed as WARN, do NOT fail verdict.
    """
    info = changed_files_info or {}
    changed_files: list[str] = info.get("changed_files", [])
    suppressions_added: int = int(info.get("suppressions_added", 0))
    is_non_code_only = bool(info.get("non_code_only", False))

    if not is_non_code_only and changed_files:
        is_non_code_only = all(not is_code_file(f) for f in changed_files)

    reasons: list[str] = []
    caveats: list[str] = []

    # Accumulate caveats from results & info
    for r in results:
        if r.caveats:
            for c in r.caveats:
                if c not in caveats:
                    caveats.append(c)
        if r.coverage_note and r.coverage_note not in caveats:
            caveats.append(f"coverage {r.coverage_note}")

    if any(is_test_file(f) for f in changed_files):
        test_caveat = "tests were edited in this turn: weaker evidence"
        if test_caveat not in caveats:
            caveats.append(test_caveat)

    if suppressions_added > 0:
        supp_caveat = f"{suppressions_added} security suppression{'s' if suppressions_added > 1 else ''} added in this turn"
        if supp_caveat not in caveats:
            caveats.append(supp_caveat)

    # Index results by hook name
    by_hook: dict[str, VerifyResult] = {r.hook: r for r in results}

    # Extract specific hook results
    rb_res = by_hook.get("readback_hash")
    test_res = by_hook.get("test_suite")
    sec_res = by_hook.get("security_scan")

    # Check for FAILED hooks
    failed_hooks: list[VerifyResult] = [r for r in results if r.status == VerifyStatus.FAILED]

    # Row 1: Any FAILED
    if failed_hooks:
        for fh in failed_hooks:
            if fh.details:
                detail_str = f"{fh.hook}: {', '.join(fh.details)}"
            else:
                detail_str = f"{fh.hook}: {fh.summary}"
            reasons.append(detail_str)
        verdict = Verdict(
            state=VerdictState.FAILED,
            reasons=reasons,
            caveats=caveats,
        )
        verdict.summary_line = completion_line(verdict)
        return verdict

    # Row 6: Baseline could not attribute failing tests -> UNVERIFIED
    if test_res and test_res.status == VerifyStatus.WARN and "baseline unavailable" in " ".join(test_res.caveats + [test_res.summary]).lower():
        if "baseline unavailable" not in caveats:
            caveats.append("baseline unavailable")
        reasons.append("failures could not be attributed; may be pre-existing")
        verdict = Verdict(
            state=VerdictState.UNVERIFIED,
            reasons=reasons,
            caveats=caveats,
        )
        verdict.summary_line = completion_line(verdict)
        return verdict

    # Row 2: Any ERROR or TIMEOUT and no FAILED -> UNVERIFIED
    error_or_timeout = [r for r in results if r.status in (VerifyStatus.ERROR, VerifyStatus.TIMEOUT)]
    if error_or_timeout:
        for eh in error_or_timeout:
            if eh.status == VerifyStatus.TIMEOUT:
                reasons.append(f"tests timed out: {eh.summary}")
            else:
                reasons.append(f"hook internal error: {eh.hook}")
            logger.warning("Verification matrix hook %s finished with %s: %s", eh.hook, eh.status, eh.summary)
        verdict = Verdict(
            state=VerdictState.UNVERIFIED,
            reasons=reasons,
            caveats=caveats,
        )
        verdict.summary_line = completion_line(verdict)
        return verdict

    # Check readback state
    rb_passed = rb_res is not None and rb_res.status == VerifyStatus.PASSED

    # Row 4: Only non-code files changed, readback_hash PASSED -> VERIFIED
    if is_non_code_only and rb_passed:
        caveat_non_code = "non-code change: readback only"
        if caveat_non_code not in caveats:
            caveats.append(caveat_non_code)
        verdict = Verdict(
            state=VerdictState.VERIFIED,
            reasons=[],
            caveats=caveats,
        )
        verdict.summary_line = completion_line(verdict)
        return verdict

    # Row 3: readback_hash PASSED, no FAILED, and test_suite PASSED -> VERIFIED
    if rb_passed and test_res is not None and test_res.status == VerifyStatus.PASSED:
        verdict = Verdict(
            state=VerdictState.VERIFIED,
            reasons=[],
            caveats=caveats,
        )
        verdict.summary_line = completion_line(verdict)
        return verdict

    # Row 5: Code changed but test_suite SKIPPED -> UNVERIFIED
    if test_res is not None and test_res.status == VerifyStatus.SKIPPED:
        skip_r = test_res.skip_reason or test_res.summary or "test execution skipped"
        reasons.append(skip_r)
        verdict = Verdict(
            state=VerdictState.UNVERIFIED,
            reasons=reasons,
            caveats=caveats,
        )
        verdict.summary_line = completion_line(verdict)
        return verdict

    # If test_suite ran and produced WARN (pre-existing failures filtered by baseline)
    if rb_passed and test_res is not None and test_res.status == VerifyStatus.WARN:
        # Pre-existing failures do NOT fail the verdict (Row 7)
        verdict = Verdict(
            state=VerdictState.VERIFIED,
            reasons=[],
            caveats=caveats,
        )
        verdict.summary_line = completion_line(verdict)
        return verdict

    # Fallback: if readback failed or missing
    if not rb_passed:
        reasons.append("readback verification failed or missing")
        verdict = Verdict(
            state=VerdictState.UNVERIFIED,
            reasons=reasons,
            caveats=caveats,
        )
        verdict.summary_line = completion_line(verdict)
        return verdict

    # If tests were not run at all for code changes
    if not is_non_code_only and (test_res is None or test_res.status == VerifyStatus.SKIPPED):
        reasons.append("no targeted tests executed")
        verdict = Verdict(
            state=VerdictState.UNVERIFIED,
            reasons=reasons,
            caveats=caveats,
        )
        verdict.summary_line = completion_line(verdict)
        return verdict

    # General verified case
    verdict = Verdict(
        state=VerdictState.VERIFIED,
        reasons=[],
        caveats=caveats,
    )
    verdict.summary_line = completion_line(verdict)
    return verdict


# ── Deterministic Completion Line ────────────────────────────────────────────

def completion_line(verdict: Verdict) -> str:
    """Generate deterministic completion string based strictly on Verdict.
    
    Enforces the invariant:
    - 'Verified' (with caveats if any)
    - 'Completed unverified: <reasons>.'
    - 'Completed with verification failures: <reasons>.'
    The bare phrase 'successfully completed' is strictly forbidden.
    """
    state_str = verdict.state.value if isinstance(verdict.state, VerdictState) else str(verdict.state).upper()
    
    if state_str == "VERIFIED":
        if verdict.caveats:
            return f"Verified ({'; '.join(verdict.caveats)})."
        return "Verified."

    if state_str == "UNVERIFIED":
        reasons_text = "; ".join(verdict.reasons) if verdict.reasons else "verification incomplete"
        if verdict.caveats:
            return f"Completed unverified: {reasons_text} ({'; '.join(verdict.caveats)})."
        return f"Completed unverified: {reasons_text}."

    if state_str == "FAILED":
        reasons_text = "; ".join(verdict.reasons) if verdict.reasons else "checks failed"
        if verdict.caveats:
            return f"Completed with verification failures: {reasons_text} ({'; '.join(verdict.caveats)})."
        return f"Completed with verification failures: {reasons_text}."

    return f"Completed unverified: unknown verdict state '{state_str}'."


# ── Turn-Level Verification Orchestrator (Part 2 & Part 6) ──────────────────

# Per-workspace lock to ensure one verification at a time per workspace
_WORKSPACE_VERIFY_LOCKS: dict[str, asyncio.Lock] = {}


async def execute_verification_matrix(
    workspace_root: str | Path,
    touched_files: list[str],
    pre_images: dict[str, bytes | None] | None = None,
    readback_statuses: dict[str, str] | None = None,
    raw_settings: dict[str, Any] | None = None,
    event_emitter: Optional[Callable[[str], Any]] = None,
    cancellation_event: Optional[asyncio.Event] = None,
) -> tuple[Verdict, list[VerifyResult]]:
    """Execute the full verification matrix for a turn, task, or job.
    
    Runs once per turn, never blocks applied mutations, emits typed SSE events,
    and returns (verdict, results).
    """
    from app.core.paths import normalize_workspace
    from app.features.ai.harness.sse_streamer import (
        _sse_verification_hook_finished,
        _sse_verification_result,
        _sse_verification_started,
    )
    from app.features.ai.harness.activity_logger import _append_activity_log

    ws_path = normalize_workspace(str(workspace_root))
    ws_key = str(ws_path)

    lock = _WORKSPACE_VERIFY_LOCKS.setdefault(ws_key, asyncio.Lock())
    async with lock:
        settings = parse_verify_settings(raw_settings)

        # 1. Master switch check: code_os_verify_enabled
        if not settings.get("code_os_verify_enabled", True):
            verdict = Verdict(
                state=VerdictState.UNVERIFIED,
                reasons=["verification disabled by setting"],
                summary_line="Completed unverified: verification disabled by setting.",
            )
            if event_emitter:
                event_emitter(_sse_verification_result(verdict.to_dict(), []))
            return verdict, []

        # 2. If no files touched
        if not touched_files:
            verdict = Verdict(
                state=VerdictState.VERIFIED,
                caveats=["no files modified"],
                summary_line="Verified (no files modified).",
            )
            if event_emitter:
                event_emitter(_sse_verification_result(verdict.to_dict(), []))
            return verdict, []

        results: list[VerifyResult] = []

        # 3. Synchronous S7 readback status check
        rb_dict = readback_statuses or {}
        rb_failed_items = [f"{k}: {v}" for k, v in rb_dict.items() if v != "passed"]
        if rb_failed_items:
            rb_res = VerifyResult(
                hook="readback_hash",
                status=VerifyStatus.FAILED,
                summary="disk state suspect: readback failed",
                details=rb_failed_items,
                duration_ms=1,
            )
            results.append(rb_res)
            # Skip heavy hooks per specification: disk state suspect
            verdict = compute_verdict(results, {"changed_files": touched_files})
            if event_emitter:
                event_emitter(_sse_verification_started(ws_key, touched_files, ["readback_hash"]))
                event_emitter(_sse_verification_hook_finished(
                    hook="readback_hash",
                    status=rb_res.status.value,
                    summary=rb_res.summary,
                    duration_ms=rb_res.duration_ms,
                    details=rb_res.details,
                ))
                event_emitter(_sse_verification_result(verdict.to_dict(), [r.to_dict() for r in results]))
            return verdict, results

        rb_res = VerifyResult(
            hook="readback_hash",
            status=VerifyStatus.PASSED,
            summary="readback verified",
            duration_ms=1,
        )
        results.append(rb_res)

        # Build active hooks list
        hooks = ["readback_hash", "security_scan", "test_suite"]
        has_lockfile = any(Path(f).name in ("package-lock.json", "yarn.lock", "pnpm-lock.yaml") for f in touched_files)
        if has_lockfile:
            hooks.append("npm_audit")

        if event_emitter:
            event_emitter(_sse_verification_started(ws_key, touched_files, hooks))
            event_emitter(_sse_verification_hook_finished(
                hook="readback_hash",
                status=rb_res.status.value,
                summary=rb_res.summary,
                duration_ms=rb_res.duration_ms,
            ))

        # Check cancellation
        if cancellation_event and cancellation_event.is_set():
            verdict = Verdict(
                state=VerdictState.UNVERIFIED,
                reasons=["verification cancelled by user"],
                summary_line="Completed unverified: verification cancelled by user.",
            )
            return verdict, results

        # 4. Security Scan Hook
        supp_count = 0
        if settings.get("code_os_verify_security_enabled", True):
            from app.features.ai.harness.verify_security import run_security_scan_hook
            sec_res, supp_count = await run_security_scan_hook(ws_path, touched_files, pre_images)
            results.append(sec_res)
            if event_emitter:
                event_emitter(_sse_verification_hook_finished(
                    hook="security_scan",
                    status=sec_res.status.value if isinstance(sec_res.status, VerifyStatus) else str(sec_res.status),
                    summary=sec_res.summary,
                    duration_ms=sec_res.duration_ms,
                    details=sec_res.details,
                    caveats=sec_res.caveats,
                ))

        # Check cancellation
        if cancellation_event and cancellation_event.is_set():
            verdict = Verdict(
                state=VerdictState.UNVERIFIED,
                reasons=["verification cancelled by user"],
                summary_line="Completed unverified: verification cancelled by user.",
            )
            return verdict, results

        # 5. Test Suite Hook
        from app.features.ai.harness.verify_runners import run_test_suite_hook
        test_coro = run_test_suite_hook(ws_path, touched_files, pre_images, raw_settings=settings)
        if cancellation_event:
            test_task = asyncio.create_task(test_coro)
            wait_cancel_task = asyncio.create_task(cancellation_event.wait())
            done, pending = await asyncio.wait([test_task, wait_cancel_task], return_when=asyncio.FIRST_COMPLETED)
            if wait_cancel_task in done:
                test_task.cancel()
                try:
                    await test_task
                except (asyncio.CancelledError, Exception):
                    pass
                verdict = Verdict(
                    state=VerdictState.UNVERIFIED,
                    reasons=["verification cancelled by user"],
                    summary_line="Completed unverified: verification cancelled by user.",
                )
                return verdict, results
            else:
                wait_cancel_task.cancel()
                test_res = test_task.result()
        else:
            test_res = await test_coro

        results.append(test_res)
        if event_emitter:
            event_emitter(_sse_verification_hook_finished(
                hook="test_suite",
                status=test_res.status.value if isinstance(test_res.status, VerifyStatus) else str(test_res.status),
                summary=test_res.summary,
                duration_ms=test_res.duration_ms,
                details=test_res.details,
                skip_reason=test_res.skip_reason,
                caveats=test_res.caveats,
            ))

        # 6. npm audit Hook (if lockfile touched)
        if has_lockfile:
            from app.features.ai.harness.verify_security import run_npm_audit_hook
            audit_res = await run_npm_audit_hook(ws_path)
            results.append(audit_res)
            if event_emitter:
                event_emitter(_sse_verification_hook_finished(
                    hook="npm_audit",
                    status=audit_res.status.value if isinstance(audit_res.status, VerifyStatus) else str(audit_res.status),
                    summary=audit_res.summary,
                    duration_ms=audit_res.duration_ms,
                    details=audit_res.details,
                    skip_reason=audit_res.skip_reason,
                ))

        # 7. Compute Consolidated Verdict
        changed_info = {
            "changed_files": touched_files,
            "suppressions_added": supp_count,
        }
        verdict = compute_verdict(results, changed_info)

        # 8. Emit Final verification_result Event
        if event_emitter:
            event_emitter(_sse_verification_result(verdict.to_dict(), [r.to_dict() for r in results]))

        # 9. Record in Activity Log (persistence without DB migration)
        try:
            _append_activity_log(
                ws_key,
                "verification_matrix",
                verdict.summary_line,
                {
                    "verdict": verdict.to_dict(),
                    "results": [r.to_dict() for r in results],
                    "touched_files": touched_files,
                },
            )
        except Exception as log_err:
            logger.debug("Activity log append skipped: %s", log_err)

        return verdict, results
