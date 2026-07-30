import asyncio
import json
import urllib.request
import urllib.error

API = "http://127.0.0.1:8000"

def test_chat_stream():
    print("--- 1. Testing AI Chat Stream ---")
    url = f"{API}/api/ai/chat/stream"
    payload = {
        "provider": "ollama",
        "model": "llama3",
        "base_url": "http://127.0.0.1:11434",
        "messages": [{"role": "user", "content": "Say hello in one word."}],
        "attached_paths": [],
        "workspace": "D:/HTML/trusted_workspace"
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req)
        chunk = resp.read(200).decode("utf-8")
        print(f"Chat Stream SUCCESS. Response preview:\n{chunk[:150]}")
    except urllib.error.HTTPError as e:
        print(f"Chat Stream HTTP ERROR {e.code}: {e.read().decode('utf-8')}")
    except Exception as e:
        print(f"Chat Stream ERROR: {e}")

def test_duo_session():
    print("\n--- 2. Testing Duo Session Creation ---")
    url = f"{API}/api/duo/sessions"
    payload = {
        "workspace": "D:/HTML/trusted_workspace",
        "task_description": "Add a documentation comment to index.html",
        "generator": {
            "provider": "ollama",
            "model": "llama3",
            "base_url": "http://127.0.0.1:11434"
        },
        "critic": {
            "provider": "ollama",
            "model": "llama3",
            "base_url": "http://127.0.0.1:11434"
        },
        "max_rounds": 1
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req)
        body = json.loads(resp.read().decode("utf-8"))
        print(f"Duo Session SUCCESS. Created Session ID: {body.get('id')}, Status: {body.get('status')}")
    except urllib.error.HTTPError as e:
        print(f"Duo Session HTTP ERROR {e.code}: {e.read().decode('utf-8')}")
    except Exception as e:
        print(f"Duo Session ERROR: {e}")

def test_agent_plan():
    print("\n--- 3. Testing Agent Console Plan & Job ---")
    url = f"{API}/api/agents/plan"
    payload = {
        "workspace": "D:/HTML/trusted_workspace",
        "user_request": "Refactor test helper function"
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req)
        body = json.loads(resp.read().decode("utf-8"))
        tasks = body.get("tasks", [])
        print(f"Agent Plan SUCCESS. Received {len(tasks)} tasks.")
    except urllib.error.HTTPError as e:
        print(f"Agent Plan HTTP ERROR {e.code}: {e.read().decode('utf-8')}")
    except Exception as e:
        print(f"Agent Plan ERROR: {e}")

if __name__ == "__main__":
    test_chat_stream()
    test_duo_session()
    test_agent_plan()
