import asyncio
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
import httpx

from app.db.database import get_db, init_db, close_db
from app.features.workspaces import service as workspace_service
from app.features.workspaces import trust_service
from app.features.files import service as file_service
from app.features.settings import service as settings_service
from app.features.settings import memory_service
from app.features.search import service as search_service
from app.features.terminal import language_detector
from app.features.indexing import parsers
from app.features.indexing import repo_service
from app.features.indexing import service as indexing_service
from app.features.git import service as git_service
from app.features.git import github_auth
from app.features.debug import python_debugger


class TestCoverageRoutesAndServices(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await close_db()
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_db.sqlite3"
        await init_db(self.db_path)

        self.ws_tmp = tempfile.TemporaryDirectory()
        self.ws_path = Path(self.ws_tmp.name).resolve()
        (self.ws_path / "src").mkdir(parents=True, exist_ok=True)
        (self.ws_path / "src" / "main.py").write_text("def hello():\n    return 'world'\n", encoding="utf-8")
        (self.ws_path / "README.md").write_text("# Test Project\n", encoding="utf-8")
        (self.ws_path / "app.js").write_text("function add(a, b) { return a + b; }\n", encoding="utf-8")

        # Ensure workspace exists in workspaces table for FK constraints
        db = await get_db()
        await db.execute(
            "INSERT INTO workspaces(path, name, last_opened_at) VALUES (?, ?, '2026-01-01T00:00:00')",
            (str(self.ws_path), self.ws_path.name)
        )
        await db.commit()

    async def asyncTearDown(self):
        await close_db()
        self.tmp_dir.cleanup()
        self.ws_tmp.cleanup()

    # ============================================================================
    # 1. WORKSPACE SERVICE & TRUST
    # ============================================================================

    async def test_workspace_service_lifecycle_and_cleanup(self):
        with patch("app.features.workspaces.service.index_manager.schedule", new_callable=AsyncMock),              patch("app.features.workspaces.service.watcher.watch"):
            dto = await workspace_service.open_workspace(str(self.ws_path))
            self.assertEqual(dto.path, str(self.ws_path))
            self.assertEqual(dto.name, self.ws_path.name)

            recent = await workspace_service.list_recent_workspaces()
            self.assertTrue(any(w.path == str(self.ws_path) for w in recent))

            last = await workspace_service.get_last_workspace()
            self.assertIsNotNone(last)
            self.assertEqual(last.path, str(self.ws_path))

            # Cleanup missing workspaces
            deleted_ws = self.ws_path.parent / "non_existent_deleted_ws"
            db = await get_db()
            await db.execute(
                "INSERT INTO workspaces(path, name, last_opened_at) VALUES (?, ?, '2026-01-01T00:00:00')",
                (str(deleted_ws), "deleted_ws")
            )
            await db.commit()

            await workspace_service.cleanup_missing_workspaces()
            recent_after = await workspace_service.list_recent_workspaces()
            self.assertFalse(any(w.path == str(deleted_ws) for w in recent_after))

            # Explicit removal
            await workspace_service.remove_workspaces([str(self.ws_path)])
            recent_final = await workspace_service.list_recent_workspaces()
            self.assertFalse(any(w.path == str(self.ws_path) for w in recent_final))

    async def test_workspace_trust_service(self):
        # Set trust to restricted / untrusted
        res = await trust_service.set_workspace_trust(str(self.ws_path), trusted=False, trust_level="restricted")
        self.assertFalse(res["trusted"])

        status = await trust_service.get_workspace_trust(str(self.ws_path))
        self.assertFalse(status["trusted"])

        # Set trust to trusted full
        res_full = await trust_service.set_workspace_trust(str(self.ws_path), trusted=True, trust_level="full")
        self.assertTrue(res_full["trusted"])
        self.assertEqual(res_full["trust_level"], "full")

        status_full = await trust_service.get_workspace_trust(str(self.ws_path))
        self.assertTrue(status_full["trusted"])

        # List trusted
        trusted_list = await trust_service.list_trusted_workspaces()
        self.assertTrue(any(w["path"] == str(self.ws_path) for w in trusted_list))

        # Subdirectory trust inheritance
        subdir = str(self.ws_path / "src")
        sub_trust = await trust_service.get_workspace_trust(subdir)
        self.assertTrue(sub_trust["trusted"])

        # Remove trust
        await trust_service.remove_workspace_trust(str(self.ws_path))
        status_removed = await trust_service.get_workspace_trust(str(self.ws_path))
        self.assertFalse(status_removed["trusted"])

    # ============================================================================
    # 2. FILE SERVICE & TREE
    # ============================================================================

    def test_file_service_crud_and_tree(self):
        ws_str = str(self.ws_path)

        # 1. Write file
        file_service.write_file(ws_str, "src/utils.py", "import math\n\ndef calc():\n    return 42\n")
        self.assertTrue((self.ws_path / "src" / "utils.py").exists())

        # 2. Read file (returns tuple (content, language))
        content, lang = file_service.read_file(ws_str, "src/utils.py")
        self.assertIn("def calc():", content)
        self.assertEqual(lang, "python")

        # 3. Create entry (folder and file)
        file_service.create_entry(ws_str, "docs/notes", "directory")
        self.assertTrue((self.ws_path / "docs" / "notes").is_dir())
        file_service.create_entry(ws_str, "docs/notes/todo.txt", "file")
        self.assertTrue((self.ws_path / "docs" / "notes" / "todo.txt").exists())

        # 4. Duplicate entry
        copy_path = file_service.duplicate_entry(ws_str, "src/utils.py")
        self.assertTrue(copy_path.exists())

        # 5. Move entry
        moved_path = file_service.move_entry(ws_str, "docs/notes/todo.txt", "src/todo.txt")
        self.assertTrue((self.ws_path / "src" / "todo.txt").exists())
        self.assertFalse((self.ws_path / "docs" / "notes" / "todo.txt").exists())

        # 6. Rename entry
        renamed_path = file_service.rename_entry(ws_str, "src/utils.py", "helpers.py")
        self.assertTrue(renamed_path.exists())
        self.assertEqual(renamed_path.name, "helpers.py")

        # 7. Tree generation
        tree = file_service.build_tree(ws_str)
        self.assertEqual(tree.type, "directory")
        self.assertEqual(tree.name, self.ws_path.name)
        child_names = [c.name for c in (tree.children or [])]
        self.assertIn("src", child_names)
        self.assertIn("README.md", child_names)

        # 8. Path traversal attempt should fail
        with self.assertRaises(HTTPException):
            file_service.read_file(ws_str, "../../../windows/system32/cmd.exe")

        # 9. Delete entries
        file_service.delete_entry(ws_str, "src/helpers.py")
        self.assertFalse((self.ws_path / "src" / "helpers.py").exists())
        file_service.delete_entry(ws_str, "docs")
        self.assertFalse((self.ws_path / "docs").exists())

    # ============================================================================
    # 3. SETTINGS & REPO MEMORY
    # ============================================================================

    async def test_settings_and_api_keys(self):
        # Key-value settings
        await settings_service.set_setting("theme", "synthwave")
        await settings_service.set_setting("fontSize", "15")
        settings = await settings_service.list_settings()
        self.assertEqual(settings.get("theme"), "synthwave")
        self.assertEqual(settings.get("fontSize"), "15")

        # API Keys with encryption
        await settings_service.store_api_key("anthropic", "sk-ant-test-key-12345")
        status = await settings_service.list_api_key_status()
        self.assertTrue(any(s["provider_id"] == "anthropic" and s["configured"] is True for s in status))

        key = await settings_service.get_api_key("anthropic")
        self.assertEqual(key, "sk-ant-test-key-12345")

        # Clear keys
        await settings_service.clear_api_keys()
        key_after = await settings_service.get_api_key("anthropic")
        self.assertIsNone(key_after)

    async def test_clear_all_history(self):
        db = await get_db()
        ws_str = str(self.ws_path)
        # Seed chat_threads, duo_sessions, agent_jobs with valid schema fields
        await db.execute("INSERT INTO chat_threads(id, workspace, title) VALUES ('t-1', ?, 'Test Thread')", (ws_str,))
        await db.execute("INSERT INTO duo_sessions(id, workspace, task_description, status) VALUES ('d-1', ?, 'Duo Test', 'running')", (ws_str,))
        await db.execute("INSERT INTO agent_jobs(id, workspace, workflow, status) VALUES ('j-1', ?, 'Goal Test', 'completed')", (ws_str,))
        await db.commit()

        await settings_service.clear_all_history()

        cursor1 = await db.execute("SELECT COUNT(*) FROM chat_threads")
        self.assertEqual((await cursor1.fetchone())[0], 0)
        cursor2 = await db.execute("SELECT COUNT(*) FROM duo_sessions")
        self.assertEqual((await cursor2.fetchone())[0], 0)
        cursor3 = await db.execute("SELECT COUNT(*) FROM agent_jobs")
        self.assertEqual((await cursor3.fetchone())[0], 0)

    async def test_repo_memory_service(self):
        ws_str = str(self.ws_path)

        # Save keys
        await memory_service.save_memory_key(ws_str, "style_guide", "PEP8 with 4 spaces")
        await memory_service.save_memory_key(ws_str, "arch_pattern", "FastAPI + Clean Architecture")

        # Get single key
        val = await memory_service.get_memory_key(ws_str, "style_guide")
        self.assertEqual(val, "PEP8 with 4 spaces")

        # Get all memory
        all_mem = await memory_service.get_all_memory(ws_str)
        self.assertEqual(all_mem.get("style_guide"), "PEP8 with 4 spaces")
        self.assertEqual(all_mem.get("arch_pattern"), "FastAPI + Clean Architecture")

        # Clear memory
        await memory_service.clear_memory(ws_str)
        all_mem_after = await memory_service.get_all_memory(ws_str)
        self.assertEqual(len(all_mem_after), 0)

    # ============================================================================
    # 4. SEARCH SERVICE
    # ============================================================================

    def test_search_service_filenames_and_text(self):
        ws_str = str(self.ws_path)

        # Search files
        matches = search_service.search_files(ws_str, "main")
        self.assertGreaterEqual(len(matches), 1)
        self.assertEqual(matches[0].name, "main.py")

        # Search text literal (returns list of tuples: (path, line_no, col, preview))
        results = search_service.search_text(ws_str, "return 'world'", regex=False, case_sensitive=True)
        self.assertGreaterEqual(len(results), 1)
        path, line_no, col, preview = results[0]
        self.assertEqual(line_no, 2)
        self.assertIn("world", preview)

        # Search text regex
        regex_results = search_service.search_text(ws_str, r"function\s+add", regex=True)
        self.assertGreaterEqual(len(regex_results), 1)
        self.assertIn("app.js", str(regex_results[0][0]))

        # Search whole word
        word_results = search_service.search_text(ws_str, "hello", whole_word=True)
        self.assertGreaterEqual(len(word_results), 1)

    # ============================================================================
    # 5. LANGUAGE DETECTOR & TOOLCHAINS
    # ============================================================================

    def test_language_detector_and_specs(self):
        spec_py = language_detector.detect_language(Path("test.py"))
        self.assertIsNotNone(spec_py)
        self.assertEqual(spec_py.id, "python")
        self.assertFalse(spec_py.is_compiled)

        spec_cpp = language_detector.detect_language(Path("main.cpp"))
        self.assertIsNotNone(spec_cpp)
        self.assertEqual(spec_cpp.id, "cpp")
        self.assertTrue(spec_cpp.is_compiled)

        spec_ts = language_detector.detect_language(Path("index.ts"))
        self.assertIsNotNone(spec_ts)
        self.assertEqual(spec_ts.id, "typescript")

        # Detect toolchains
        toolchains = language_detector.get_all_toolchains()
        self.assertGreater(len(toolchains), 0)
        py_status = next((t for t in toolchains if t.id == "python"), None)
        self.assertIsNotNone(py_status)
        self.assertTrue(py_status.installed)

    # ============================================================================
    # 6. INDEXING PARSERS, DEPENDENCIES & PROJECT DETECTION
    # ============================================================================

    def test_source_code_parsers(self):
        # Python Parser
        py_code = """
import os
from math import sqrt

class Calculator:
    def add(self, a, b):
        return a + b

async def fetch_data():
    return 1
"""
        py_parsed = parsers.parse_source(self.ws_path / "calc.py", "python", py_code)
        self.assertIn("os", py_parsed.imports)
        self.assertIn("math", py_parsed.imports)
        symbol_names = [s.name for s in py_parsed.symbols]
        self.assertIn("Calculator", symbol_names)
        self.assertIn("add", symbol_names)
        self.assertIn("fetch_data", symbol_names)

        # C / C++ Parser
        c_code = """
#include <stdio.h>
#include "my_header.h"

struct Point {
    int x;
    int y;
};

int compute_distance(int x1, int y1) {
    return 0;
}
"""
        c_parsed = parsers.parse_source(self.ws_path / "main.c", "c", c_code)
        self.assertIn("stdio.h", c_parsed.imports)
        self.assertIn("my_header.h", c_parsed.imports)
        c_symbols = [s.name for s in c_parsed.symbols]
        self.assertIn("Point", c_symbols)
        self.assertIn("compute_distance", c_symbols)

        # Java Parser
        java_code = """
import java.util.List;
import java.io.*;

public class UserService {
    public void findUser(int id) {
    }
}
"""
        java_parsed = parsers.parse_source(self.ws_path / "UserService.java", "java", java_code)
        self.assertIn("java.util.List", java_parsed.imports)
        java_symbols = [s.name for s in java_parsed.symbols]
        self.assertIn("UserService", java_symbols)

        # JS/TS Parser
        js_code = """
import React from 'react';
const lodash = require('lodash');

export class AppContainer {
}

export function renderApp() {
}

const calculateTotal = (items) => {
    return 0;
};
"""
        js_parsed = parsers.parse_source(self.ws_path / "app.tsx", "typescript", js_code)
        self.assertIn("react", js_parsed.imports)
        self.assertIn("lodash", js_parsed.imports)
        js_symbols = [s.name for s in js_parsed.symbols]
        self.assertIn("AppContainer", js_symbols)
        self.assertIn("renderApp", js_symbols)

    def test_indexing_dependencies_and_project_detection(self):
        # Create requirements.txt and package.json
        (self.ws_path / "requirements.txt").write_text("fastapi==0.110.0\nuvicorn>=0.28.0\npytest\n", encoding="utf-8")
        (self.ws_path / "package.json").write_text(json.dumps({
            "name": "my-app",
            "dependencies": {"react": "^18.2.0", "lucide-react": "^0.300.0"}
        }), encoding="utf-8")
        (self.ws_path / "main.py").write_text("print('start')", encoding="utf-8")

        deps = indexing_service._detect_dependencies(self.ws_path)
        dep_names = [d[0] for d in deps]
        self.assertIn("fastapi", dep_names)
        self.assertIn("uvicorn", dep_names)
        self.assertIn("react", dep_names)

        project_type, frameworks = indexing_service._detect_project(self.ws_path, deps)
        self.assertEqual(project_type, "node+python")
        self.assertIn("fastapi", frameworks)
        self.assertIn("react", frameworks)

        entry_points = indexing_service._detect_entry_points(self.ws_path)
        self.assertIn("main.py", entry_points)

    async def test_repo_architecture_service(self):
        ws_str = str(self.ws_path)
        db = await get_db()

        # Insert mock index data
        await db.execute(
            """
            INSERT INTO repo_index_status (
                workspace, status, message, started_at, completed_at,
                total_files, indexed_files, changed_files, project_type,
                language_summary, frameworks, entry_points
            ) VALUES (?, 'completed', '', '2026-01-01', '2026-01-01', 10, 10, 0, 'fullstack', '{"python": 8, "javascript": 2}', '["FastAPI", "React"]', '["main.py"]')
            """,
            (ws_str,)
        )
        await db.execute(
            """
            INSERT INTO repo_dependencies (workspace, name, version, source)
            VALUES (?, 'fastapi', '0.110.0', 'requirements.txt')
            """,
            (ws_str,)
        )
        await db.execute(
            """
            INSERT INTO repo_import_edges (workspace, source_path, target_path, module)
            VALUES (?, ?, ?, 'src.main')
            """,
            (ws_str, str(self.ws_path / "app.py"), str(self.ws_path / "src" / "main.py"))
        )
        await db.commit()

        summary = await repo_service.get_repo_summary(ws_str)
        self.assertEqual(summary["project_type"], "fullstack")
        self.assertIn("FastAPI", summary["frameworks"])
        self.assertEqual(len(summary["dependencies"]), 1)
        self.assertIn("fullstack", summary["architecture_summary"].lower())

        graph = await repo_service.get_repo_graph(ws_str)
        self.assertEqual(len(graph["nodes"]), 2)
        self.assertEqual(len(graph["edges"]), 1)
        self.assertEqual(graph["edges"][0]["module"], "src.main")

    # ============================================================================
    # 7. GIT DANGEROUS FILES & GITHUB AUTH
    # ============================================================================

    def test_git_dangerous_files_filter(self):
        self.assertTrue(git_service.is_dangerous_file(".env"))
        self.assertTrue(git_service.is_dangerous_file(".env.production"))
        self.assertTrue(git_service.is_dangerous_file("certs/server.key"))
        self.assertTrue(git_service.is_dangerous_file("secrets/credentials.json"))
        self.assertTrue(git_service.is_dangerous_file(".ssh/id_rsa"))
        self.assertTrue(git_service.is_dangerous_file("id_ed25519"))

        self.assertFalse(git_service.is_dangerous_file("src/main.py"))
        self.assertFalse(git_service.is_dangerous_file("README.md"))
        self.assertFalse(git_service.is_dangerous_file("package.json"))

    async def test_github_auth_validation_and_storage(self):
        # 1. Empty token raises 400
        with self.assertRaises(HTTPException) as cm:
            await github_auth.validate_and_store_token("   ")
        self.assertEqual(cm.exception.status_code, 400)

        # 2. Mock GitHub API 200 response
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"login": "octocat"}

        with patch("httpx.AsyncClient.get", return_value=mock_response),              patch("app.features.git.github_auth._token_path") as mock_tpath:
            token_file = self.ws_path / "github_pat.enc"
            mock_tpath.return_value = token_file

            res = await github_auth.validate_and_store_token("ghp_test_valid_token_12345")
            self.assertEqual(res["login"], "octocat")
            self.assertTrue(token_file.exists())

            # Read back stored token
            stored = github_auth.get_stored_token()
            self.assertEqual(stored, "ghp_test_valid_token_12345")

    # ============================================================================
    # 8. DEBUGGER UTILITIES
    # ============================================================================

    def test_python_debugger_port(self):
        port = python_debugger._free_local_port()
        self.assertIsInstance(port, int)
        self.assertGreater(port, 1024)
