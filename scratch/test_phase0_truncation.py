import asyncio
import json
import logging
import sys
import os
sys.path.insert(0, r"D:\HTML\CODE OS\backend")

from app.features.ai.service import provider_for, ChatRequest
from app.features.ai.schemas import ChatMessage
from app.features.ai.chat_harness import OPENAI_HARNESS_TOOLS, _build_system_prompt

async def run_phase0_test():
    req = ChatRequest(
        provider="auto",
        model="",
        messages=[
            ChatMessage(role="user", content="create hello.html, 1000+ line portfolio")
        ],
        workspace=r"D:\HTML\CODE OS",
    )
    prov = await provider_for(req)
    print(f"Provider ID: {prov.id}, Resolved Model: {req.model}")

    # Build system prompt
    sys_prompt = _build_system_prompt(req.workspace, {"workspace": req.workspace})
    messages = [
        ChatMessage(role="system", content=sys_prompt),
        ChatMessage(role="user", content="create hello.html, 1000+ line portfolio"),
    ]

    tokens = []
    try:
        async for tok in prov.stream_chat(req.model, messages, 0.2, tools=OPENAI_HARNESS_TOOLS):
            tokens.append(tok)
    except Exception as e:
        print(f"Stream error: {e}")

    full_resp = "".join(tokens)
    print(f"Response total length (chars): {len(full_resp)}")
    print("--- LAST 500 CHARS OF RESPONSE ---")
    print(full_resp[-500:] if len(full_resp) >= 500 else full_resp)
    print("--- END LAST 500 CHARS ---")

    has_open_tag = "[TOOL_CALL:" in full_resp
    has_close_tag = "[/TOOL_CALL]" in full_resp
    print(f"Contains '[TOOL_CALL:': {has_open_tag}")
    print(f"Contains '[/TOOL_CALL]': {has_close_tag}")
    if has_open_tag and not has_close_tag:
        print("CONFIRMED: Tool call was truncated mid-stream without closing tag!")

if __name__ == "__main__":
    asyncio.run(run_phase0_test())
