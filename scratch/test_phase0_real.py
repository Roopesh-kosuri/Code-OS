import asyncio
import json
import sys
sys.path.insert(0, r"D:\HTML\CODE OS\backend")

import httpx
from app.features.settings.service import get_api_key
from app.features.ai.chat_harness import _build_system_prompt, OPENAI_HARNESS_TOOLS

async def test_phase0():
    key = await get_api_key("groq")
    model = "openai/gpt-oss-120b"
    sys_prompt = _build_system_prompt(r"D:\HTML\CODE OS", {"workspace": r"D:\HTML\CODE OS"})
    
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": "create hello.html, 1000+ line portfolio"},
    ]
    
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "stream": True,
        "tools": OPENAI_HARNESS_TOOLS,
        "tool_choice": "auto",
    }
    
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    
    tokens = []
    finish_reason = None
    tool_call_deltas = {}
    
    async with httpx.AsyncClient(timeout=180.0) as client:
        async with client.stream("POST", "https://api.groq.com/openai/v1/chat/completions", json=payload, headers=headers) as resp:
            print(f"HTTP Status: {resp.status_code}")
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except Exception:
                    continue
                choices = chunk.get("choices", [])
                if not choices:
                    continue
                delta = choices[0].get("delta", {})
                content = delta.get("content")
                if content:
                    tokens.append(content)
                tc_chunks = delta.get("tool_calls")
                if tc_chunks:
                    for tc in tc_chunks:
                        idx = tc.get("index", 0)
                        fn = tc.get("function", {})
                        name = fn.get("name")
                        args = fn.get("arguments", "")
                        if idx not in tool_call_deltas:
                            tool_call_deltas[idx] = {"name": "", "arguments": ""}
                        if name:
                            tool_call_deltas[idx]["name"] += name
                        if args:
                            tool_call_deltas[idx]["arguments"] += args
                if choices[0].get("finish_reason"):
                    finish_reason = choices[0]["finish_reason"]

    raw_text = "".join(tokens)
    print(f"Finish Reason: {finish_reason}")
    print(f"Content tokens length (chars): {len(raw_text)}")
    print(f"Native tool calls captured: {list(tool_call_deltas.keys())}")
    for idx, tc in tool_call_deltas.items():
        print(f"Tool {idx}: name='{tc['name']}', args_len={len(tc['arguments'])}")
        print(f"Tool {idx} args ends with: {repr(tc['arguments'][-200:])}")
        try:
            parsed = json.loads(tc['arguments'])
            print(f"Tool {idx} valid JSON: True")
        except json.JSONDecodeError as jde:
            print(f"Tool {idx} valid JSON: FALSE (JSONDecodeError: {jde})")

    print("\n--- LAST 500 CHARS OF RAW TEXT ---")
    print(raw_text[-500:] if len(raw_text) >= 500 else raw_text)
    print("--- END LAST 500 CHARS ---")

if __name__ == "__main__":
    asyncio.run(test_phase0())
