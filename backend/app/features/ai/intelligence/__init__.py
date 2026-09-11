"""
intelligence - AI intelligence layer for CODE OS: unified task difficulty classification,
context-window aware model routing, and explainable decision making.
"""
from .task_classifier import classify_task, set_llm_classifier_fn, reset_llm_classifier_fn
from .prompt_enhancer import (
    classify_prompt_quality,
    enhance_prompt,
    get_enhancement_stats,
    record_enhancement_action,
    set_enhancer_llm_fn,
    reset_enhancer_llm_fn,
    clear_enhancer_session_cache,
)
from .intelligence_routes import router as intelligence_router

__all__ = [
    "classify_task",
    "set_llm_classifier_fn",
    "reset_llm_classifier_fn",
    "classify_prompt_quality",
    "enhance_prompt",
    "get_enhancement_stats",
    "record_enhancement_action",
    "set_enhancer_llm_fn",
    "reset_enhancer_llm_fn",
    "clear_enhancer_session_cache",
    "intelligence_router",
]
