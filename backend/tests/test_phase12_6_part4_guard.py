import ast
from dataclasses import dataclass
from pathlib import Path
import pytest
from app.features.ai.harness.content_integrity import validate_language_syntax


# ============================================================================
# Z0 — COMMENT-ONLY .ts FALSE-POSITIVE CHECK
# ============================================================================

def test_comment_only_ts_file_not_flagged_as_prose():
    """A .ts file consisting only of line comments must be ALLOWED, both with empty original and matching original."""
    content = "// this is the file for the config\n// the settings will be added here\n"
    
    # original = ""
    ok_empty, err_empty = validate_language_syntax("config.ts", content, original_content="")
    assert ok_empty is True, f"Failed with empty original: {err_empty}"
    assert err_empty == ""

    # original = same content
    ok_same, err_same = validate_language_syntax("config.ts", content, original_content=content)
    assert ok_same is True, f"Failed with matching original: {err_same}"
    assert err_same == ""


def test_block_comment_only_js_file_not_flagged_as_prose():
    """A .js file consisting only of a block comment must be ALLOWED."""
    content = "/* This file is the entry point.\n   It will export the app. */\n"
    ok, err = validate_language_syntax("index.js", content, original_content="")
    assert ok is True, f"Failed on block comment: {err}"
    assert err == ""


def test_json_like_ts_with_only_brackets_not_flagged():
    """A .ts file consisting of a bracketed array/list structure must be ALLOWED."""
    content = '[\n  "a",\n  "b"\n]\n'
    ok, err = validate_language_syntax("list.ts", content, original_content="")
    assert ok is True, f"Failed on bracketed array: {err}"
    assert err == ""


def test_conversational_prose_still_rejected_after_fix():
    """Raw conversational prose without code syntax or comments into a .ts file must be REJECTED."""
    content = "Here is the code you requested to handle authentication.\n"
    ok, err = validate_language_syntax("auth.ts", content, original_content="")
    assert ok is False
    assert "conversational prose" in err


def test_prose_with_comment_marker_prefix_still_rejected():
    """A comment on line 1 must not launder conversational prose on line 2."""
    content = "// Here is the code you requested\nSure, I can help with that.\n"
    ok, err = validate_language_syntax("auth.ts", content, original_content="")
    assert ok is False
    assert "conversational prose" in err


# ============================================================================
# M3 — PERMANENT WRITE-DRIFT GUARD
# ============================================================================

@dataclass(frozen=True)
class Hit:
    rel_path: str
    lineno: int
    enclosing_func: str
    primitive: str


class _WriteDriftVisitor(ast.NodeVisitor):
    def __init__(self, rel_path: str):
        self.rel_path = rel_path
        self.fn_stack = ["<module>"]
        self.imported: dict[str, str] = {}
        self.hits: list[Hit] = []

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self.fn_stack.append(node.name)
        self.generic_visit(node)
        self.fn_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self.fn_stack.append(node.name)
        self.generic_visit(node)
        self.fn_stack.pop()

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.module == "os":
            for a in node.names:
                if a.name in ("replace", "rename", "remove", "unlink", "rmdir", "mkdir", "makedirs"):
                    self.imported[a.asname or a.name] = f"os.{a.name}"
        elif node.module == "shutil":
            for a in node.names:
                if a.name in ("move", "copy", "copy2", "copyfile", "copytree", "rmtree"):
                    self.imported[a.asname or a.name] = f"shutil.{a.name}"
        elif node.module == "tempfile":
            for a in node.names:
                if a.name in ("NamedTemporaryFile", "mkstemp", "mkdtemp"):
                    self.imported[a.asname or a.name] = f"tempfile.{a.name}"
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        fn = self.fn_stack[-1]
        # 1. Direct Name calls (open or from X import Y)
        if isinstance(node.func, ast.Name):
            if node.func.id == "open":
                mode = None
                if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                    mode = node.args[1].value
                for kw in node.keywords:
                    if kw.arg == "mode" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        mode = kw.value.value
                if mode and any(m in mode for m in ("w", "a", "x", "r+")):
                    self.hits.append(Hit(self.rel_path, node.lineno, fn, f"open(..., mode={mode!r})"))
            elif node.func.id in ("NamedTemporaryFile", "mkstemp", "mkdtemp"):
                self.hits.append(Hit(self.rel_path, node.lineno, fn, f"tempfile.{node.func.id}"))
            elif node.func.id in self.imported:
                self.hits.append(Hit(self.rel_path, node.lineno, fn, self.imported[node.func.id]))
        # 2. Attribute calls
        elif isinstance(node.func, ast.Attribute):
            val = node.func.value
            attr = node.func.attr
            if isinstance(val, ast.Name):
                if val.id == "os" and attr in ("replace", "rename", "remove", "unlink", "rmdir", "mkdir", "makedirs"):
                    self.hits.append(Hit(self.rel_path, node.lineno, fn, f"os.{attr}"))
                elif val.id == "shutil" and attr in ("move", "copy", "copy2", "copyfile", "copytree", "rmtree"):
                    self.hits.append(Hit(self.rel_path, node.lineno, fn, f"shutil.{attr}"))
                elif val.id == "tempfile" and attr in ("NamedTemporaryFile", "mkstemp", "mkdtemp"):
                    self.hits.append(Hit(self.rel_path, node.lineno, fn, f"tempfile.{attr}"))
            if attr in ("write_text", "write_bytes", "mkdir", "rmdir", "unlink", "touch"):
                self.hits.append(Hit(self.rel_path, node.lineno, fn, f"Path.{attr}"))
            elif attr == "rename":
                self.hits.append(Hit(self.rel_path, node.lineno, fn, "Path.rename"))
            elif attr == "replace" and len(node.args) == 1 and not node.keywords:
                self.hits.append(Hit(self.rel_path, node.lineno, fn, "Path.replace"))
        self.generic_visit(node)


def scan_source(text: str, rel_path: str = "<synthetic>") -> list[Hit]:
    """Scan python source text for workspace write primitives using AST."""
    tree = ast.parse(text)
    visitor = _WriteDriftVisitor(rel_path)
    visitor.visit(tree)
    return visitor.hits


PERMANENT_ALLOWLIST = {
    ("core/auth.py", "load_token"): "non-workspace (app session token cleanup)",
    ("core/auth.py", "generate_and_store_token"): "non-workspace (app session token creation)",
    ("core/config.py", "get_settings"): "non-workspace (app storage directory setup)",
    ("core/logging.py", "configure_logging"): "non-workspace (app logs directory setup)",
    ("core/security.py", "_load_or_create_key"): "non-workspace (app secret key store)",
    ("db/database.py", "init_db"): "non-workspace (app sqlite db setup)",
    ("core/paths.py", "safe_write_file"): "unused-helper (safe_write_file in core/paths.py)",
    ("core/plugins/plugin_manager.py", "__init__"): "non-workspace (plugin cache)",
    ("core/plugins/routes.py", "install_plugin"): "non-workspace (plugin cache / install)",
    ("features/ai/file_ingestion/service.py", "get_uploads_dir"): "non-workspace (unpacked upload cache)",
    ("features/ai/file_ingestion/service.py", "save_uploaded_file"): "non-workspace (unpacked upload cache)",
    ("features/ai/file_ingestion/service.py", "delete_uploaded_file"): "non-workspace (unpacked upload cache)",
    ("features/ai/backup_service.py", "_get_backup_dir"): "non-workspace (app backups)",
    ("features/ai/backup_service.py", "_rotate_backups"): "non-workspace (app backups)",
    ("features/ai/harness/activity_logger.py", "_rotate_activity_log"): "non-workspace (.code_os activity log)",
    ("features/ai/harness/activity_logger.py", "_append_activity_log"): "non-workspace (.code_os activity log)",
    ("features/ai/harness/activity_logger.py", "_get_interrupted_state_path"): "non-workspace (.code_os activity log)",
    ("features/ai/harness/activity_logger.py", "_save_interrupted_state"): "non-workspace (.code_os activity log)",
    ("features/ai/harness/activity_logger.py", "_clear_interrupted_state"): "non-workspace (.code_os activity log)",
    ("features/ai/harness/approval_coordinator.py", "_get_trusted_commands_path"): "non-workspace (.code_os trusted commands)",
    ("features/ai/harness/approval_coordinator.py", "_save_trusted_command"): "non-workspace (.code_os trusted commands)",
    ("features/ai/harness/approval_coordinator.py", "_remove_trusted_command"): "non-workspace (.code_os trusted commands)",
    ("features/ai/harness/checkpoint_manager.py", "_ensure_git_checkpoint"): "non-workspace (.gitignore creation in checkpoint repo)",
    ("features/ai/harness/checkpoint_manager.py", "undo_turn_files"): "pipeline-adapter (cleanup empty parent directories on undo)",
    ("features/ai/harness/mutation_pipeline.py", "stage_apply"): "pipeline-internal (S4 atomic disk execution engine)",
    ("features/ai/harness/mutation_pipeline.py", "stage_rollback"): "pipeline-internal (S6 exact byte restoration engine)",
    ("features/ai/harness/mutation_pipeline.py", "apply_mutations"): "pipeline-internal (commit trash cleanup)",
    ("features/ai/harness/mutation_pipeline.py", "_cleanup_stale_trash"): "pipeline-internal (stale crash trash cleanup)",
    ("features/ai/indexing/code_intelligence.py", "_extract_style_conventions"): "non-workspace (.code_os style cache)",
    ("features/ai/marathon/marathon_service.py", "_state_file_path"): "non-workspace (.code_os marathon state)",
    ("features/ai/marathon/marathon_service.py", "save_state"): "non-workspace (.code_os marathon state)",
    ("features/ai/marathon/marathon_service.py", "delete_state_file"): "non-workspace (.code_os marathon state)",
    ("features/ai/marathon/marathon_service.py", "abort_marathon"): "non-workspace (.code_os marathon state marker cleanup)",
    ("features/ai/marathon/marathon_service.py", "pause_marathon"): "non-workspace (.code_os marathon state marker)",
    ("features/ai/marathon/marathon_service.py", "resume_marathon"): "non-workspace (.code_os marathon state marker)",
    ("features/ai/marathon/marathon_executor.py", "run"): "non-workspace (.code_os marathon checkpoint marker)",
    ("features/ai/marathon/marathon_planner.py", "decompose_goal"): "non-workspace (.code_os marathon checkpoint marker)",
    ("features/ai/memory/memory_service.py", "_get_memory_collection"): "non-workspace (.code_os memory dir)",
    ("features/ai/providers/catalog.py", "_get_sqlite_connection"): "non-workspace (.code_os provider catalog db)",
    ("features/ai/rag/vector_index_service.py", "init_vector_store"): "non-workspace (chroma vector store)",
    ("features/ai/refactoring/verify_service.py", "verify_refactor_safety"): "non-workspace (isolated temp sandbox dir)",
    ("features/ai/sandbox/executor.py", "_launch_windows_sandbox"): "non-workspace (isolated temp sandbox config)",
    ("features/ai/voice/tts_service.py", "speak"): "non-workspace (tts audio cache)",
    ("features/ai/voice/whisper_stt_service.py", "init_whisper"): "non-workspace (whisper models cache)",
    ("features/automation/browser_controller.py", "profile_path"): "non-workspace (browser profile dir)",
    ("features/automation/browser_controller.py", "screenshots_dir"): "non-workspace (browser screenshots dir)",
    ("features/automation/browser_controller.py", "trust_browser"): "non-workspace (browser trace logs)",
    ("features/automation/computer_controller.py", "audit_dir"): "non-workspace (automation audit dir)",
    ("features/git/github_auth.py", "validate_and_store_token"): "non-workspace (github auth token store)",
    ("features/git/github_service.py", "push_current_branch"): "non-workspace (git credential helper store)",
    ("features/terminal/run_service.py", "kill_run_process"): "non-workspace (terminal pty temp buffers)",
    ("features/terminal/run_service.py", "run_file_stream"): "non-workspace (terminal pty temp buffers)",
}


# ============================================================================
# M3.2 — NON-VACUITY PROOFS
# ============================================================================

def test_guard_flags_synthetic_write_text():
    """Prove that scan_source flags Path.write_text."""
    code = "def do_write():\n    Path('out.txt').write_text('content')\n"
    hits = scan_source(code, "test_file.py")
    assert len(hits) == 1
    assert hits[0].primitive == "Path.write_text"
    assert hits[0].enclosing_func == "do_write"


def test_guard_flags_synthetic_open_write_mode():
    """Prove that scan_source flags open with 'w', 'a', 'x', and 'r+' modes."""
    code = (
        "def write_open():\n"
        "    f1 = open('a.txt', 'w')\n"
        "    f2 = open('b.txt', mode='ab')\n"
        "    f3 = open('c.txt', 'x')\n"
        "    f4 = open('d.txt', mode='r+')\n"
    )
    hits = scan_source(code, "test_file.py")
    assert len(hits) == 4
    prims = [h.primitive for h in hits]
    assert any("mode='w'" in p for p in prims)
    assert any("mode='ab'" in p for p in prims)
    assert any("mode='x'" in p for p in prims)
    assert any("mode='r+'" in p for p in prims)


def test_guard_flags_synthetic_shutil_rmtree_via_from_import():
    """Prove that scan_source flags aliased from-import calls like 'from shutil import rmtree'."""
    code = (
        "from shutil import rmtree as delete_tree\n\n"
        "def clean_cache():\n"
        "    delete_tree('/tmp/cache')\n"
    )
    hits = scan_source(code, "cleaner.py")
    assert len(hits) == 1
    assert hits[0].primitive == "shutil.rmtree"
    assert hits[0].enclosing_func == "clean_cache"


def test_guard_flags_synthetic_path_touch_and_mkdir():
    """Prove that scan_source flags newly added primitives Path.touch and Path.mkdir."""
    code = (
        "def make_marker():\n"
        "    p = Path('/tmp/dir')\n"
        "    p.mkdir(parents=True)\n"
        "    (p / 'lock').touch()\n"
    )
    hits = scan_source(code, "marker.py")
    assert len(hits) == 2
    prims = {h.primitive for h in hits}
    assert prims == {"Path.mkdir", "Path.touch"}


def test_guard_flags_synthetic_new_write_inside_allowlisted_file_but_wrong_function():
    """Prove that a write in an unapproved function inside an allowlisted file is caught."""
    code = (
        "def load_token():\n"
        "    p = Path('token.txt')\n"
        "    p.unlink()\n\n"
        "def unapproved_writer():\n"
        "    Path('rogue.txt').write_text('bad')\n"
    )
    hits = scan_source(code, "core/auth.py")
    unrouted = [
        f"{h.rel_path}:{h.lineno} in {h.enclosing_func}(): {h.primitive}"
        for h in hits
        if (h.rel_path, h.enclosing_func) not in PERMANENT_ALLOWLIST
    ]
    assert len(unrouted) == 1
    assert "core/auth.py:6 in unapproved_writer(): Path.write_text" in unrouted[0]


def test_guard_reports_stale_allowlist_entry():
    """Prove that an allowlist entry that has no corresponding hits is detected as stale."""
    synthetic_allowlist = {
        ("core/auth.py", "load_token"): "active",
        ("core/auth.py", "stale_function_that_no_longer_writes"): "should fail",
    }
    code = "def load_token():\n    Path('token.txt').unlink()\n"
    hits = scan_source(code, "core/auth.py")
    active_keys = {(h.rel_path, h.enclosing_func) for h in hits}
    stale_keys = [k for k in synthetic_allowlist if k not in active_keys]
    assert stale_keys == [("core/auth.py", "stale_function_that_no_longer_writes")]


def test_guard_passes_on_current_tree():
    """Real scan over backend/app asserting ZERO unrouted writes and ZERO stale allowlist entries."""
    backend_app_dir = Path(__file__).resolve().parent.parent / "app"
    all_hits: list[Hit] = []
    
    for py_file in sorted(backend_app_dir.rglob("*.py")):
        rel = py_file.relative_to(backend_app_dir).as_posix()
        hits = scan_source(py_file.read_text(encoding="utf-8"), rel)
        all_hits.extend(hits)

    # 1. Assert zero unrouted calls
    unrouted = []
    for h in all_hits:
        key = (h.rel_path, h.enclosing_func)
        if key not in PERMANENT_ALLOWLIST:
            unrouted.append(f"{h.rel_path}:{h.lineno} in {h.enclosing_func}(): {h.primitive}")

    assert unrouted == [], f"Found unrouted workspace write primitives:\n" + "\n".join(unrouted)

    # 2. Assert zero stale allowlist entries
    active_keys = {(h.rel_path, h.enclosing_func) for h in all_hits}
    stale_entries = [k for k in PERMANENT_ALLOWLIST if k not in active_keys]
    assert stale_entries == [], f"Found stale allowlist entries with zero write hits:\n" + "\n".join(str(k) for k in stale_entries)


# ============================================================================
# M3.3 — ZERO-CALLER AND PIPELINE-ONLY GUARDS
# ============================================================================

def test_safe_write_file_has_zero_production_callers():
    """Prove that safe_write_file in app.core.paths has zero production callers anywhere in backend/app."""
    backend_app_dir = Path(__file__).resolve().parent.parent / "app"
    matches = []
    for py_file in backend_app_dir.rglob("*.py"):
        if py_file.name == "paths.py":
            continue
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "safe_write_file":
                matches.append(f"{py_file.relative_to(backend_app_dir)}:{node.lineno}")
            elif isinstance(node, ast.Attribute) and node.attr == "safe_write_file":
                matches.append(f"{py_file.relative_to(backend_app_dir)}:{node.lineno}")

    assert matches == [], f"Found unexpected callers of safe_write_file in production code:\n" + "\n".join(matches)


def test_mutation_pipeline_is_only_workspace_writer_for_workspace_mutations():
    """Prove that apply_mutations is only imported by explicit, approved workspace adapters."""
    backend_app_dir = Path(__file__).resolve().parent.parent / "app"
    
    APPROVED_PIPELINE_ADAPTERS = {
        "features/ai/agent_routes.py",
        "features/files/service.py",
        "features/ai/cicd/cicd_routes.py",
        "features/search/service.py",
        "features/ai/ghost_text/ghost_text_service.py",
        "features/ai/indexing/code_intelligence.py",
        "features/ai/harness/checkpoint_manager.py",
        "features/ai/refactoring/refactor_routes.py",
        "features/ai/service.py",
        "features/ai/security/fix_service.py",
        "features/ai/staging/staging_review_service.py",
        "features/ai/harness/patch_applicator.py",
        "features/ai/harness/stage_finalizer.py",
        "features/ai/harness/tool_executor.py",
        "features/ai/harness/mutation_pipeline.py",  # definition module itself
    }

    importing_modules = set()
    for py_file in backend_app_dir.rglob("*.py"):
        rel = py_file.relative_to(backend_app_dir).as_posix()
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and "mutation_pipeline" in node.module:
                for alias in node.names:
                    if alias.name == "apply_mutations":
                        importing_modules.add(rel)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if "mutation_pipeline" in alias.name:
                        importing_modules.add(rel)

    unexpected = importing_modules - APPROVED_PIPELINE_ADAPTERS
    assert unexpected == set(), f"Found unapproved modules importing apply_mutations: {unexpected}"
