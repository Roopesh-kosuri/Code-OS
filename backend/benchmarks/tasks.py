"""Registry of deterministic OSS benchmark tasks for CODE OS Benchmark Gym."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional
from backend.benchmarks.schemas import BenchmarkTask


TASKS: Dict[str, BenchmarkTask] = {
    # ── 1. Simple Flask/FastAPI Apps (3 Tasks) ───────────────────────────────
    "flask_auth": BenchmarkTask(
        id="flask_auth",
        name="Flask: Add Token Authentication Endpoint",
        tier=1,
        category="flask_fastapi",
        prompt="Add a '/api/login' endpoint to app.py that verifies username and password, returns a token, and protect '/api/protected'.",
        expected_files=["app.py", "test_auth.py"],
        expected_tests_pass=["test_login_success", "test_login_invalid", "test_protected_route"],
        expected_tools_used=["edit_range", "multicut"],
        max_iterations=4,
        initial_files={
            "flask.py": (
                "class _Request:\n"
                "    headers = {}\n"
                "    _json = {}\n"
                "    def get_json(self): return self._json\n"
                "request = _Request()\n\n"
                "class _Response:\n"
                "    def __init__(self, data, status_code=200):\n"
                "        self._data = data; self.status_code = status_code\n"
                "    def get_json(self): return self._data\n\n"
                "def jsonify(data=None, **kwargs):\n"
                "    return _Response(data or kwargs)\n\n"
                "class Flask:\n"
                "    def __init__(self, name): self.routes = {}; self.testing = False\n"
                "    def route(self, path, methods=None):\n"
                "        def decorator(f):\n"
                "            self.routes[path] = f; return f\n"
                "        return decorator\n"
                "    def test_client(self):\n"
                "        return _TestClient(self)\n\n"
                "class _TestClient:\n"
                "    def __init__(self, app): self.app = app\n"
                "    def get(self, path, headers=None):\n"
                "        request.headers = headers or {}\n"
                "        handler = self.app.routes.get(path)\n"
                "        if not handler: return _Response({}, 404)\n"
                "        res = handler()\n"
                "        if isinstance(res, tuple): return _Response(res[0].get_json(), res[1])\n"
                "        return res\n"
                "    def post(self, path, json=None, headers=None):\n"
                "        request.headers = headers or {}; request._json = json or {}\n"
                "        handler = self.app.routes.get(path)\n"
                "        if not handler: return _Response({}, 404)\n"
                "        res = handler()\n"
                "        if isinstance(res, tuple): return _Response(res[0].get_json(), res[1])\n"
                "        return res\n"
            ),
            "app.py": (
                "from flask import Flask, request, jsonify\n\n"
                "app = Flask(__name__)\n"
                "TOKENS = {}\n\n"
                "@app.route('/api/health')\n"
                "def health():\n"
                "    return jsonify(status='ok')\n"
            ),
            "test_auth.py": (
                "import pytest\n"
                "from app import app\n\n"
                "@pytest.fixture\n"
                "def client():\n"
                "    app.testing = True\n"
                "    return app.test_client()\n\n"
                "def test_health(client):\n"
                "    res = client.get('/api/health')\n"
                "    assert res.status_code == 200\n\n"
                "def test_login_success(client):\n"
                "    res = client.post('/api/login', json={'username': 'alice', 'password': 'secret'})\n"
                "    assert res.status_code == 200\n"
                "    assert 'token' in res.get_json()\n\n"
                "def test_login_invalid(client):\n"
                "    res = client.post('/api/login', json={'username': 'alice', 'password': 'wrong'})\n"
                "    assert res.status_code == 401\n\n"
                "def test_protected_route(client):\n"
                "    res = client.get('/api/protected')\n"
                "    assert res.status_code == 401\n"
                "    res2 = client.get('/api/protected', headers={'Authorization': 'Bearer valid_token'})\n"
                "    assert res2.status_code == 200\n"
            ),
        },
        solution_files={
            "app.py": (
                "from flask import Flask, request, jsonify\n\n"
                "app = Flask(__name__)\n"
                "TOKENS = {'valid_token': 'alice'}\n\n"
                "@app.route('/api/health')\n"
                "def health():\n"
                "    return jsonify(status='ok')\n\n"
                "@app.route('/api/login', methods=['POST'])\n"
                "def login():\n"
                "    data = request.get_json() or {}\n"
                "    if data.get('username') == 'alice' and data.get('password') == 'secret':\n"
                "        return jsonify({'token': 'valid_token'})\n"
                "    return jsonify({'error': 'unauthorized'}), 401\n\n"
                "@app.route('/api/protected')\n"
                "def protected():\n"
                "    auth = request.headers.get('Authorization', '')\n"
                "    if auth == 'Bearer valid_token':\n"
                "        return jsonify({'data': 'secret data'})\n"
                "    return jsonify({'error': 'unauthorized'}), 401\n"
            ),
        },
    ),

    "fastapi_store": BenchmarkTask(
        id="fastapi_store",
        name="FastAPI: Add Product Model and CRUD Route",
        tier=1,
        category="flask_fastapi",
        prompt="Add an 'Item' model and CRUD routes (/items) with GET and POST to main.py.",
        expected_files=["main.py", "test_items.py"],
        expected_tests_pass=["test_create_item", "test_get_item", "test_list_items"],
        expected_tools_used=["edit_range", "multicut"],
        max_iterations=4,
        initial_files={
            "main.py": (
                "from fastapi import FastAPI\n\n"
                "app = FastAPI()\n"
                "items_db = {}\n\n"
                "@app.get('/health')\n"
                "def health():\n"
                "    return {'status': 'ok'}\n"
            ),
            "test_items.py": (
                "import pytest\n"
                "from fastapi.testclient import TestClient\n"
                "from main import app\n\n"
                "client = TestClient(app)\n\n"
                "def test_health():\n"
                "    assert client.get('/health').status_code == 200\n\n"
                "def test_create_item():\n"
                "    res = client.post('/items', json={'id': '1', 'name': 'Widget', 'price': 9.99})\n"
                "    assert res.status_code == 201\n"
                "    assert res.json()['name'] == 'Widget'\n\n"
                "def test_get_item():\n"
                "    client.post('/items', json={'id': '2', 'name': 'Gadget', 'price': 19.99})\n"
                "    res = client.get('/items/2')\n"
                "    assert res.status_code == 200\n"
                "    assert res.json()['name'] == 'Gadget'\n\n"
                "def test_list_items():\n"
                "    res = client.get('/items')\n"
                "    assert res.status_code == 200\n"
                "    assert isinstance(res.json(), list)\n"
            ),
        },
        solution_files={
            "main.py": (
                "from fastapi import FastAPI, HTTPException\n"
                "from pydantic import BaseModel\n\n"
                "app = FastAPI()\n"
                "items_db = {}\n\n"
                "class Item(BaseModel):\n"
                "    id: str\n"
                "    name: str\n"
                "    price: float\n\n"
                "@app.get('/health')\n"
                "def health():\n"
                "    return {'status': 'ok'}\n\n"
                "@app.post('/items', status_code=201)\n"
                "def create_item(item: Item):\n"
                "    items_db[item.id] = item.model_dump()\n"
                "    return items_db[item.id]\n\n"
                "@app.get('/items/{item_id}')\n"
                "def get_item(item_id: str):\n"
                "    if item_id not in items_db:\n"
                "        raise HTTPException(status_code=404, detail='Not found')\n"
                "    return items_db[item_id]\n\n"
                "@app.get('/items')\n"
                "def list_items():\n"
                "    return list(items_db.values())\n"
            ),
        },
    ),

    "flask_calc": BenchmarkTask(
        id="flask_calc",
        name="Flask: Fix Calculator Zero Division and Negative Powers",
        tier=1,
        category="flask_fastapi",
        prompt="Fix calculation bugs in calc.py: handle division by zero with a structured 400 error and support exponents.",
        expected_files=["calc.py", "test_calc.py"],
        expected_tests_pass=["test_divide_by_zero", "test_power_calculation", "test_valid_operations"],
        expected_tools_used=["edit_range"],
        max_iterations=3,
        initial_files={
            "calc.py": (
                "def evaluate_expression(op: str, a: float, b: float) -> float:\n"
                "    if op == 'add': return a + b\n"
                "    if op == 'sub': return a - b\n"
                "    if op == 'mul': return a * b\n"
                "    if op == 'div': return a / b  # Bug: raises ZeroDivisionError unhandled\n"
                "    raise ValueError(f'Unsupported op: {op}')\n"
            ),
            "test_calc.py": (
                "import pytest\n"
                "from calc import evaluate_expression\n\n"
                "def test_valid_operations():\n"
                "    assert evaluate_expression('add', 2, 3) == 5\n"
                "    assert evaluate_expression('sub', 5, 2) == 3\n"
                "    assert evaluate_expression('mul', 4, 3) == 12\n\n"
                "def test_divide_by_zero():\n"
                "    with pytest.raises(ValueError) as exc:\n"
                "        evaluate_expression('div', 10, 0)\n"
                "    assert 'Division by zero' in str(exc.value)\n\n"
                "def test_power_calculation():\n"
                "    assert evaluate_expression('pow', 2, 3) == 8\n"
            ),
        },
        solution_files={
            "calc.py": (
                "def evaluate_expression(op: str, a: float, b: float) -> float:\n"
                "    if op == 'add': return a + b\n"
                "    if op == 'sub': return a - b\n"
                "    if op == 'mul': return a * b\n"
                "    if op == 'div':\n"
                "        if b == 0:\n"
                "            raise ValueError('Division by zero is not permitted')\n"
                "        return a / b\n"
                "    if op == 'pow': return a ** b\n"
                "    raise ValueError(f'Unsupported op: {op}')\n"
            ),
        },
    ),

    # ── 2. React/TS Components (3 Tasks) ─────────────────────────────────────
    "react_counter_state": BenchmarkTask(
        id="react_counter_state",
        name="React: Add Bounded State to Counter Component",
        tier=1,
        category="react_ts",
        prompt="Add stateful count logic to Counter.tsx with bounded limits (min 0, max 100).",
        expected_files=["Counter.tsx", "test_counter.py"],
        expected_tests_pass=["test_counter_increment", "test_counter_bounds", "test_counter_reset"],
        expected_tools_used=["edit_range"],
        max_iterations=3,
        initial_files={
            "Counter.tsx": (
                "import React from 'react';\n\n"
                "export interface CounterProps { min?: number; max?: number; }\n"
                "export const Counter: React.FC<CounterProps> = () => {\n"
                "  return <div><span>0</span><button>Increment</button></div>;\n"
                "};\n"
            ),
            "test_counter.py": (
                "# Python test verifying TypeScript AST / component contract\n"
                "from pathlib import Path\n\n"
                "def test_counter_increment():\n"
                "    content = Path('Counter.tsx').read_text()\n"
                "    assert 'useState' in content\n"
                "    assert 'setCount' in content or 'count +' in content\n\n"
                "def test_counter_bounds():\n"
                "    content = Path('Counter.tsx').read_text()\n"
                "    assert 'min' in content and 'max' in content\n"
                "    assert 'Math.min' in content or '<=' in content\n\n"
                "def test_counter_reset():\n"
                "    content = Path('Counter.tsx').read_text()\n"
                "    assert 'reset' in content.lower() or '0' in content\n"
            ),
        },
        solution_files={
            "Counter.tsx": (
                "import React, { useState } from 'react';\n\n"
                "export interface CounterProps { min?: number; max?: number; }\n"
                "export const Counter: React.FC<CounterProps> = ({ min = 0, max = 100 }) => {\n"
                "  const [count, setCount] = useState(min);\n"
                "  const increment = () => setCount((c) => Math.min(max, c + 1));\n"
                "  const decrement = () => setCount((c) => Math.max(min, c - 1));\n"
                "  const reset = () => setCount(min);\n"
                "  return (\n"
                "    <div>\n"
                "      <span>{count}</span>\n"
                "      <button onClick={increment}>Increment</button>\n"
                "      <button onClick={decrement}>Decrement</button>\n"
                "      <button onClick={reset}>Reset</button>\n"
                "    </div>\n"
                "  );\n"
                "};\n"
            ),
        },
    ),

    "react_prop_drilling": BenchmarkTask(
        id="react_prop_drilling",
        name="React: Refactor Prop Drilling to Context API",
        tier=1,
        category="react_ts",
        prompt="Eliminate prop drilling in UserProfile.tsx by implementing and using UserContext from AppContext.tsx.",
        expected_files=["AppContext.tsx", "UserProfile.tsx", "test_context.py"],
        expected_tests_pass=["test_user_context_defined", "test_prop_drilling_eliminated"],
        expected_tools_used=["edit_range", "multicut"],
        max_iterations=4,
        initial_files={
            "AppContext.tsx": (
                "import React, { createContext, useContext } from 'react';\n\n"
                "export interface User { id: string; name: string; role: string; }\n"
                "// TODO: export UserContext\n"
            ),
            "UserProfile.tsx": (
                "import React from 'react';\n\n"
                "// Heavily drilled user prop through 3 levels\n"
                "export const Level3 = ({ user }: { user: any }) => <div>{user.name}</div>;\n"
                "export const Level2 = ({ user }: { user: any }) => <Level3 user={user} />;\n"
                "export const UserProfile = ({ user }: { user: any }) => <Level2 user={user} />;\n"
            ),
            "test_context.py": (
                "from pathlib import Path\n\n"
                "def test_user_context_defined():\n"
                "    ctx = Path('AppContext.tsx').read_text()\n"
                "    assert 'createContext' in ctx\n"
                "    assert 'useUser' in ctx or 'useContext' in ctx\n\n"
                "def test_prop_drilling_eliminated():\n"
                "    prof = Path('UserProfile.tsx').read_text()\n"
                "    assert '<Level2 />' in prof or 'Level2 = ()' in prof\n"
                "    assert 'useUser' in prof or 'useContext' in prof\n"
            ),
        },
        solution_files={
            "AppContext.tsx": (
                "import React, { createContext, useContext } from 'react';\n\n"
                "export interface User { id: string; name: string; role: string; }\n"
                "export const UserContext = createContext<User | null>(null);\n"
                "export const useUser = () => {\n"
                "  const user = useContext(UserContext);\n"
                "  if (!user) throw new Error('useUser must be within Provider');\n"
                "  return user;\n"
                "};\n"
            ),
            "UserProfile.tsx": (
                "import React from 'react';\n"
                "import { useUser } from './AppContext';\n\n"
                "export const Level3 = () => {\n"
                "  const user = useUser();\n"
                "  return <div>{user.name}</div>;\n"
                "};\n"
                "export const Level2 = () => <Level3 />;\n"
                "export const UserProfile = () => <Level2 />;\n"
            ),
        },
    ),

    "react_todo_test": BenchmarkTask(
        id="react_todo_test",
        name="React: Add Unit Test Suite for TodoList",
        tier=1,
        category="react_ts",
        prompt="Write unit tests in test_todo.py verifying item creation, completion toggling, and deletion.",
        expected_files=["TodoList.tsx", "test_todo.py"],
        expected_tests_pass=["test_todo_add", "test_todo_toggle", "test_todo_delete"],
        expected_tools_used=["edit_range"],
        max_iterations=3,
        initial_files={
            "TodoList.tsx": (
                "export interface Todo { id: number; title: string; done: boolean; }\n"
                "export class TodoStore {\n"
                "  todos: Todo[] = [];\n"
                "  add(title: string) { this.todos.push({ id: Date.now(), title, done: false }); }\n"
                "  toggle(id: number) { const t = this.todos.find(x => x.id === id); if (t) t.done = !t.done; }\n"
                "  remove(id: number) { this.todos = this.todos.filter(x => x.id !== id); }\n"
                "}\n"
            ),
            "test_todo.py": (
                "# Incomplete test suite\n"
                "def test_placeholder():\n"
                "    assert True\n"
            ),
        },
        solution_files={
            "test_todo.py": (
                "from pathlib import Path\n"
                "import re\n\n"
                "def test_todo_add():\n"
                "    code = Path('TodoList.tsx').read_text()\n"
                "    assert 'add(title: string)' in code\n"
                "    assert 'this.todos.push' in code\n\n"
                "def test_todo_toggle():\n"
                "    code = Path('TodoList.tsx').read_text()\n"
                "    assert 'toggle(id: number)' in code\n"
                "    assert 't.done = !t.done' in code\n\n"
                "def test_todo_delete():\n"
                "    code = Path('TodoList.tsx').read_text()\n"
                "    assert 'remove(id: number)' in code\n"
                "    assert 'filter' in code\n"
            ),
        },
    ),

    # ── 3. Multi-File Refactors (2 Tasks) ────────────────────────────────────
    "refactor_extract_util": BenchmarkTask(
        id="refactor_extract_util",
        name="Refactor: Extract Utility Across 5 Files",
        tier=2,
        category="refactor",
        prompt="Extract duplicated email validation function into shared_utils.py across 5 service files using surgical tools.",
        expected_files=[
            "shared_utils.py",
            "service_auth.py",
            "service_billing.py",
            "service_notify.py",
            "service_invite.py",
            "service_profile.py",
            "test_services.py",
        ],
        expected_tests_pass=["test_shared_util_extracted", "test_all_services_use_shared_util"],
        expected_tools_used=["edit_range", "multicut"],
        max_iterations=6,
        initial_files={
            "service_auth.py": "def is_valid_email(e: str) -> bool: return '@' in e and '.' in e\ndef login(e): return is_valid_email(e)\n",
            "service_billing.py": "def is_valid_email(e: str) -> bool: return '@' in e and '.' in e\ndef invoice(e): return is_valid_email(e)\n",
            "service_notify.py": "def is_valid_email(e: str) -> bool: return '@' in e and '.' in e\ndef notify(e): return is_valid_email(e)\n",
            "service_invite.py": "def is_valid_email(e: str) -> bool: return '@' in e and '.' in e\ndef invite(e): return is_valid_email(e)\n",
            "service_profile.py": "def is_valid_email(e: str) -> bool: return '@' in e and '.' in e\ndef update_profile(e): return is_valid_email(e)\n",
            "test_services.py": (
                "import pytest\n"
                "from pathlib import Path\n\n"
                "def test_shared_util_extracted():\n"
                "    assert Path('shared_utils.py').exists(), 'shared_utils.py must be created'\n"
                "    content = Path('shared_utils.py').read_text()\n"
                "    assert 'def is_valid_email' in content\n\n"
                "def test_all_services_use_shared_util():\n"
                "    services = ['service_auth.py', 'service_billing.py', 'service_notify.py', 'service_invite.py', 'service_profile.py']\n"
                "    for s in services:\n"
                "        txt = Path(s).read_text()\n"
                "        assert 'from shared_utils import is_valid_email' in txt, f'{s} did not import from shared_utils'\n"
                "        assert txt.count('def is_valid_email') == 0, f'{s} still contains duplicate definition'\n"
            ),
        },
        solution_files={
            "shared_utils.py": "def is_valid_email(e: str) -> bool:\n    return '@' in e and '.' in e\n",
            "service_auth.py": "from shared_utils import is_valid_email\ndef login(e): return is_valid_email(e)\n",
            "service_billing.py": "from shared_utils import is_valid_email\ndef invoice(e): return is_valid_email(e)\n",
            "service_notify.py": "from shared_utils import is_valid_email\ndef notify(e): return is_valid_email(e)\n",
            "service_invite.py": "from shared_utils import is_valid_email\ndef invite(e): return is_valid_email(e)\n",
            "service_profile.py": "from shared_utils import is_valid_email\ndef update_profile(e): return is_valid_email(e)\n",
        },
    ),

    "refactor_rename_symbol": BenchmarkTask(
        id="refactor_rename_symbol",
        name="Refactor: Rename Symbol Across 5 Files",
        tier=2,
        category="refactor",
        prompt="Rename symbol 'format_user_payload' to 'normalize_user_record' across all 5 modules and caller tests.",
        expected_files=[
            "user_formatter.py",
            "api_v1.py",
            "api_v2.py",
            "webhook_sender.py",
            "audit_logger.py",
            "test_rename.py",
        ],
        expected_tests_pass=["test_symbol_renamed_everywhere", "test_no_old_symbol_remains"],
        expected_tools_used=["edit_range", "multicut"],
        max_iterations=6,
        initial_files={
            "user_formatter.py": "def format_user_payload(u: dict) -> dict: return {'user': u}\n",
            "api_v1.py": "from user_formatter import format_user_payload\ndef handle_v1(u): return format_user_payload(u)\n",
            "api_v2.py": "from user_formatter import format_user_payload\ndef handle_v2(u): return format_user_payload(u)\n",
            "webhook_sender.py": "from user_formatter import format_user_payload\ndef send_hook(u): return format_user_payload(u)\n",
            "audit_logger.py": "from user_formatter import format_user_payload\ndef audit(u): return format_user_payload(u)\n",
            "test_rename.py": (
                "from pathlib import Path\n\n"
                "FILES = ['user_formatter.py', 'api_v1.py', 'api_v2.py', 'webhook_sender.py', 'audit_logger.py']\n\n"
                "def test_symbol_renamed_everywhere():\n"
                "    for f in FILES:\n"
                "        content = Path(f).read_text()\n"
                "        assert 'normalize_user_record' in content, f'New symbol missing in {f}'\n\n"
                "def test_no_old_symbol_remains():\n"
                "    for f in FILES:\n"
                "        content = Path(f).read_text()\n"
                "        assert 'format_user_payload' not in content, f'Old symbol still exists in {f}'\n"
            ),
        },
        solution_files={
            "user_formatter.py": "def normalize_user_record(u: dict) -> dict: return {'user': u}\n",
            "api_v1.py": "from user_formatter import normalize_user_record\ndef handle_v1(u): return normalize_user_record(u)\n",
            "api_v2.py": "from user_formatter import normalize_user_record\ndef handle_v2(u): return normalize_user_record(u)\n",
            "webhook_sender.py": "from user_formatter import normalize_user_record\ndef send_hook(u): return normalize_user_record(u)\n",
            "audit_logger.py": "from user_formatter import normalize_user_record\ndef audit(u): return normalize_user_record(u)\n",
        },
    ),

    # ── 4. RAG-Heavy Tasks (2 Tasks) ─────────────────────────────────────────
    "rag_large_docs": BenchmarkTask(
        id="rag_large_docs",
        name="RAG: Index Large Documentation and Extract Config",
        tier=2,
        category="rag",
        prompt="Query large system documentation across multiple markdown files and write correct config extract to config.json.",
        expected_files=["config.json", "test_rag_config.py"],
        expected_tests_pass=["test_config_json_matches_docs"],
        expected_tools_used=["edit_range"],
        max_iterations=4,
        initial_files={
            "docs/server.md": "# Server Specs\nHost: 0.0.0.0\nPort: 8443\nWorkers: 4\nMaxConnections: 1000\n",
            "docs/database.md": "# Database Specs\nEngine: postgresql\nPoolSize: 20\nTimeoutSeconds: 30\n",
            "test_rag_config.py": (
                "import json\nfrom pathlib import Path\n\n"
                "def test_config_json_matches_docs():\n"
                "    cfg_file = Path('config.json')\n"
                "    assert cfg_file.exists()\n"
                "    data = json.loads(cfg_file.read_text())\n"
                "    assert data['server']['port'] == 8443\n"
                "    assert data['database']['engine'] == 'postgresql'\n"
                "    assert data['database']['pool_size'] == 20\n"
            ),
        },
        solution_files={
            "config.json": json.dumps({
                "server": {"host": "0.0.0.0", "port": 8443, "workers": 4, "max_connections": 1000},
                "database": {"engine": "postgresql", "pool_size": 20, "timeout_seconds": 30},
            }, indent=2),
        },
    ),

    "rag_cross_file": BenchmarkTask(
        id="rag_cross_file",
        name="RAG: Cross-File Schema and Migration Query",
        tier=2,
        category="rag",
        prompt="Trace database migration schema to SQLAlchemy model and endpoint to generate relationship schema.py.",
        expected_files=["schema.py", "test_cross_file_rag.py"],
        expected_tests_pass=["test_schema_model_fields"],
        expected_tools_used=["edit_range"],
        max_iterations=4,
        initial_files={
            "migrations/001_create_orgs.sql": "CREATE TABLE orgs (id UUID PRIMARY KEY, name VARCHAR(100), tier VARCHAR(20));",
            "migrations/002_create_members.sql": "CREATE TABLE members (id UUID PRIMARY KEY, org_id UUID REFERENCES orgs(id), role VARCHAR(20));",
            "test_cross_file_rag.py": (
                "from pathlib import Path\n\n"
                "def test_schema_model_fields():\n"
                "    txt = Path('schema.py').read_text()\n"
                "    assert 'class Org' in txt and 'class Member' in txt\n"
                "    assert 'org_id' in txt\n"
                "    assert 'relationship' in txt or 'members' in txt\n"
            ),
        },
        solution_files={
            "schema.py": (
                "class Org:\n"
                "    id: str\n"
                "    name: str\n"
                "    tier: str\n"
                "    members: list['Member']\n\n"
                "class Member:\n"
                "    id: str\n"
                "    org_id: str\n"
                "    role: str\n"
            ),
        },
    ),

    # ── 5. Marathon Multi-Day / Multi-Step Task (1 Task) ─────────────────────
    "marathon_multi_step": BenchmarkTask(
        id="marathon_multi_step",
        name="Marathon: Plan -> Execute -> Verify Over 3 Steps",
        tier=3,
        category="marathon",
        prompt="Execute 3-phase lifecycle: Step 1 generate plan.json, Step 2 implement pipeline.py, Step 3 verify with test_marathon.py.",
        expected_files=["plan.json", "pipeline.py", "test_marathon.py"],
        expected_tests_pass=["test_step1_plan_valid", "test_step2_pipeline_executes", "test_step3_verification_passed"],
        expected_tools_used=["edit_range", "multicut"],
        max_iterations=8,
        initial_files={
            "test_marathon.py": (
                "import json\nfrom pathlib import Path\n\n"
                "def test_step1_plan_valid():\n"
                "    p = Path('plan.json')\n"
                "    assert p.exists()\n"
                "    data = json.loads(p.read_text())\n"
                "    assert len(data.get('steps', [])) == 3\n\n"
                "def test_step2_pipeline_executes():\n"
                "    from pipeline import run_pipeline\n"
                "    res = run_pipeline([1, 2, 3, 4])\n"
                "    assert res == [2, 4, 6, 8]\n\n"
                "def test_step3_verification_passed():\n"
                "    from pipeline import verify_state\n"
                "    assert verify_state() is True\n"
            ),
        },
        solution_files={
            "plan.json": json.dumps({"steps": ["plan", "execute", "verify"], "status": "completed"}, indent=2),
            "pipeline.py": (
                "def run_pipeline(data: list[int]) -> list[int]:\n"
                "    return [x * 2 for x in data]\n\n"
                "def verify_state() -> bool:\n"
                "    return True\n"
            ),
        },
    ),
}


def get_task(task_id: str) -> Optional[BenchmarkTask]:
    """Retrieve a benchmark task by ID."""
    return TASKS.get(task_id)


def list_tasks(suite: str = "all") -> List[BenchmarkTask]:
    """Filter benchmark tasks by suite name."""
    if suite == "all":
        return list(TASKS.values())
    if suite == "simple":
        return [t for t in TASKS.values() if t.category in ("flask_fastapi", "react_ts")]
    if suite == "refactor":
        return [t for t in TASKS.values() if t.category == "refactor"]
    if suite == "rag":
        return [t for t in TASKS.values() if t.category == "rag"]
    if suite == "marathon":
        return [t for t in TASKS.values() if t.category == "marathon"]
    return [t for t in TASKS.values() if t.id == suite or t.category == suite]
