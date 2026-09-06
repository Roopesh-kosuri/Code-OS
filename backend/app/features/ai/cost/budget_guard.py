from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any, Optional, Tuple

from app.features.settings.service import get_setting, set_setting
from .cost_aggregator import get_spend_summary

logger = logging.getLogger(__name__)

# Context variable to track active workspace across async boundaries
active_workspace_ctx: ContextVar[str] = ContextVar("active_workspace_ctx", default="")

DEFAULT_DOWNGRADE_MODEL = "groq/llama-3.3-70b"


class BudgetExceeded(Exception):
    """Raised when spend exceeds the hard stop budget limit."""

    def __init__(
        self,
        message: str = "Budget limit exceeded. AI operations blocked.",
        usage_percent: float = 100.0,
        spend: float = 0.0,
        limit: float = 0.0,
        downgrade_model: str = DEFAULT_DOWNGRADE_MODEL,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.usage_percent = usage_percent
        self.spend = spend
        self.limit = limit
        self.downgrade_model = downgrade_model

    def to_recovery_payload(self) -> dict[str, Any]:
        """Format for existing recovery panel UI."""
        return {
            "error_type": "budget_exceeded",
            "message": self.message,
            "usage_percent": self.usage_percent,
            "spend": self.spend,
            "limit": self.limit,
            "suggested_actions": [
                {
                    "action": "increase_budget",
                    "label": "Increase Daily Budget Limit in Settings",
                },
                {
                    "action": "downgrade_model",
                    "label": f"Switch to Free / Low-cost Model ({self.downgrade_model})",
                    "target_model": self.downgrade_model,
                },
                {
                    "action": "reset_today_spend",
                    "label": "Reset Today's Spend (Admin)",
                },
            ],
        }


async def get_budget_settings() -> dict[str, Any]:
    """Retrieve budget guard configuration from settings."""
    daily_raw = await get_setting("budget.daily_limit_usd")
    session_raw = await get_setting("budget.session_limit_usd")
    auto_dg_raw = await get_setting("budget.auto_downgrade_at_percent")
    hard_stop_raw = await get_setting("budget.hard_stop_at_percent")
    dg_model_raw = await get_setting("budget.downgrade_model")
    show_pill_raw = await get_setting("budget.show_topbar_pill")

    daily_limit = float(daily_raw) if daily_raw not in (None, "", "null") else None
    session_limit = float(session_raw) if session_raw not in (None, "", "null") else None
    auto_downgrade_at = float(auto_dg_raw) if auto_dg_raw not in (None, "", "null") else 90.0
    hard_stop_at = float(hard_stop_raw) if hard_stop_raw not in (None, "", "null") else 100.0
    downgrade_model = dg_model_raw if dg_model_raw else DEFAULT_DOWNGRADE_MODEL
    show_topbar_pill = show_pill_raw != "false" if show_pill_raw is not None else True

    return {
        "daily_limit_usd": daily_limit,
        "session_limit_usd": session_limit,
        "auto_downgrade_at_percent": auto_downgrade_at,
        "hard_stop_at_percent": hard_stop_at,
        "downgrade_model": downgrade_model,
        "show_topbar_pill": show_topbar_pill,
    }


async def check_budget(workspace: str = "") -> dict[str, Any]:
    """
    Check if current spend exceeds limits.
    Returns: {ok: bool, usage_percent: float, action: 'none' | 'downgrade' | 'block', spend: float, limit: float | None}
    """
    ws = workspace or active_workspace_ctx.get()
    cfg = await get_budget_settings()
    daily_limit = cfg["daily_limit_usd"]

    spend_summary = await get_spend_summary(ws, period="today")
    today_spend = float(spend_summary.get("total_usd", 0.0))

    if daily_limit is None or daily_limit <= 0.0:
        return {
            "ok": True,
            "usage_percent": 0.0,
            "action": "none",
            "spend": round(today_spend, 4),
            "limit": None,
            "downgrade_model": cfg["downgrade_model"],
        }

    usage_percent = (today_spend / daily_limit) * 100.0

    if usage_percent >= cfg["hard_stop_at_percent"]:
        return {
            "ok": False,
            "usage_percent": round(usage_percent, 1),
            "action": "block",
            "spend": round(today_spend, 4),
            "limit": daily_limit,
            "downgrade_model": cfg["downgrade_model"],
        }

    if usage_percent >= cfg["auto_downgrade_at_percent"]:
        return {
            "ok": True,
            "usage_percent": round(usage_percent, 1),
            "action": "downgrade",
            "spend": round(today_spend, 4),
            "limit": daily_limit,
            "downgrade_model": cfg["downgrade_model"],
        }

    return {
        "ok": True,
        "usage_percent": round(usage_percent, 1),
        "action": "none",
        "spend": round(today_spend, 4),
        "limit": daily_limit,
        "downgrade_model": cfg["downgrade_model"],
    }


async def apply_budget_guard(workspace: str, provider: str, model: str) -> tuple[str, str, str]:
    """
    Called before LLM dispatch.
    If action='downgrade', returns (downgrade_provider, downgrade_model, 'downgrade').
    If action='block', raises BudgetExceeded.
    Otherwise returns (provider, model, 'none').
    """
    res = await check_budget(workspace)
    action = res["action"]

    if action == "block":
        raise BudgetExceeded(
            f"Daily budget limit of ${res['limit']:.2f} reached ({res['usage_percent']:.1f}% used, spend: ${res['spend']:.2f}). Hard stop enforced.",
            usage_percent=res["usage_percent"],
            spend=res["spend"],
            limit=res["limit"] or 0.0,
            downgrade_model=res["downgrade_model"],
        )

    if action == "downgrade":
        dg = res["downgrade_model"]
        if "/" in dg:
            new_prov, new_mod = dg.split("/", 1)
        else:
            new_prov, new_mod = "groq", dg
        logger.warning(
            "Budget guard auto-downgrade active (%s%% used). Swapping %s/%s -> %s/%s",
            res["usage_percent"], provider, model, new_prov, new_mod
        )
        return (new_prov, new_mod, "downgrade")

    return (provider, model, "none")


_hook_installed = False


def install_budget_guard_hook() -> None:
    """
    Dynamically install pre-request interceptor on provider adapters without modifying providers/* files on disk.
    Wraps stream_chat and stream_agent on provider classes at runtime.
    """
    global _hook_installed
    if _hook_installed:
        return

    try:
        from app.features.ai.providers.base import AIProvider
        from app.features.ai.providers.openai_compatible import OpenAICompatibleProvider
        from app.features.ai.providers.anthropic import AnthropicProvider
        from app.features.ai.providers.ollama import OllamaProvider

        def make_guarded_stream_chat(original_method):
            async def guarded_stream_chat(self, model: str, messages: Any, *args, **kwargs):
                ws = active_workspace_ctx.get()
                provider_id = getattr(self, "id", "openai")
                _, effective_model, _ = await apply_budget_guard(ws, provider_id, model)
                async for chunk in original_method(self, effective_model, messages, *args, **kwargs):
                    yield chunk
            return guarded_stream_chat

        def make_guarded_stream_agent(original_method):
            async def guarded_stream_agent(self, model: str, messages: Any, *args, **kwargs):
                ws = active_workspace_ctx.get()
                provider_id = getattr(self, "id", "openai")
                _, effective_model, _ = await apply_budget_guard(ws, provider_id, model)
                async for event in original_method(self, effective_model, messages, *args, **kwargs):
                    yield event
            return guarded_stream_agent

        for cls in (OpenAICompatibleProvider, AnthropicProvider, OllamaProvider):
            if hasattr(cls, "stream_chat"):
                setattr(cls, "_orig_stream_chat", cls.stream_chat)
                setattr(cls, "stream_chat", make_guarded_stream_chat(cls.stream_chat))
            if hasattr(cls, "stream_agent"):
                setattr(cls, "_orig_stream_agent", cls.stream_agent)
                setattr(cls, "stream_agent", make_guarded_stream_agent(cls.stream_agent))

        _hook_installed = True
        logger.info("Budget Guard dynamic provider hook installed successfully.")
    except Exception as exc:
        logger.warning("Failed installing dynamic budget guard hook: %s", exc)
