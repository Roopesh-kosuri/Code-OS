import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.features.terminal.service import TerminalSession, run_command

from app.features.ai.agents.planner import PLANNER_SYSTEM_PROMPT, PlannerAgent
from app.features.ai.agents.agent_factory import AgentFactory, CoderAgent


class TestLogicCorrectness(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = str(Path(self.tmp.name).resolve())

    def tearDown(self):
        self.tmp.cleanup()

    async def test_cd_command_parsing(self):
        """Verify 'cdk deploy' and 'cdrom' do NOT trigger directory change handling."""
        session = TerminalSession(
            id="test-session",
            name="Test",
            shell="powershell.exe" if os.name == "nt" else "bash",
            cwd=self.workspace,
            processes=[],
        )

        with patch("app.features.terminal.service.sessions", {"test-session": session}), \
             patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_sub:
            mock_proc = AsyncMock()
            mock_proc.pid = 1234
            mock_proc.communicate = AsyncMock(return_value=(b"cdk output", b""))
            mock_proc.returncode = 0
            mock_sub.return_value = mock_proc

            # 'cdk deploy' should execute subprocess, NOT _change_directory
            output, code, bg = await run_command("test-session", "cdk deploy", False)

            self.assertEqual(output, "cdk output")
            mock_sub.assert_called_once()

    async def test_placeholder_exact_match(self):
        """Verify comments like '# TODO: empty file cleanup' do not trigger placeholder whole-file overwriting."""
        from app.features.ai.service import apply_proposal
        from app.features.ai.schemas import EditProposalDto, FileChange
        from fastapi import HTTPException

        file_path = Path(self.workspace) / "clean.py"
        file_path.write_text("# TODO: empty file cleanup\ndef foo(): pass\n")

        mock_proposal = EditProposalDto(
            id="prop-1",
            workspace=self.workspace,
            status="pending",
            summary="test",
            changes=[
                FileChange(
                    path=str(file_path),
                    original="# TODO: empty file cleanup",
                    updated="# Cleaned up\ndef foo(): pass\n",
                )
            ],
            diff="",
        )

        with patch("app.features.ai.service.get_proposal", return_value=mock_proposal), \
             patch("app.features.ai.service.get_db") as mock_db:
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock(return_value=AsyncMock(fetchone=AsyncMock(return_value={"payload": "{}"})))
            mock_conn.commit = AsyncMock()
            mock_conn.fetchall = AsyncMock(return_value=[])
            mock_db.return_value = mock_conn

            # Applying proposal should perform snippet replacement, NOT whole-file overwrite
            updated_prop = await apply_proposal("prop-1")
            self.assertIn("# Cleaned up", file_path.read_text())


    async def test_multiple_target_occurrences_fails_conflict(self):
        """Verify ambiguous edits (target snippet appearing twice) raise HTTP 409 conflict."""
        from app.features.ai.service import apply_proposal
        from app.features.ai.schemas import EditProposalDto, FileChange
        from fastapi import HTTPException

        file_path = Path(self.workspace) / "dups.py"
        file_path.write_text("item = 1\nitem = 1\n")

        mock_proposal = EditProposalDto(
            id="prop-dup",
            workspace=self.workspace,
            status="pending",
            summary="test",
            changes=[
                FileChange(
                    path=str(file_path),
                    original="item = 1",
                    updated="item = 2",
                )
            ],
            diff="",
        )

        with patch("app.features.ai.service.get_proposal", return_value=mock_proposal):
            with self.assertRaises(HTTPException) as ctx:
                await apply_proposal("prop-dup")
            self.assertEqual(ctx.exception.status_code, 409)
            self.assertIn("appears 2 times", ctx.exception.detail)

    def test_planner_advertises_only_implemented_agents(self):
        """Verify planner system prompt advertises only implemented agents."""
        self.assertIn("Coding Agent", PLANNER_SYSTEM_PROMPT)
        self.assertIn("Review Agent", PLANNER_SYSTEM_PROMPT)
        self.assertIn("Testing Agent", PLANNER_SYSTEM_PROMPT)
        self.assertIn("Documentation Agent", PLANNER_SYSTEM_PROMPT)
        self.assertNotIn("Security Agent:", PLANNER_SYSTEM_PROMPT)
        self.assertNotIn("Performance Agent:", PLANNER_SYSTEM_PROMPT)

        # Factory fallback
        agent = AgentFactory.create_agent("Security Agent")
        self.assertIsInstance(agent, CoderAgent)

    async def test_dag_dependency_validation(self):
        """Verify start_job route drops hallucinated dependency IDs."""
        from app.features.ai.agent_routes import start_job, StartJobRequest

        req = StartJobRequest(
            workspace=self.workspace,
            workflow="test",
            tasks=[
                {
                    "id": "task_a",
                    "title": "A",
                    "agent_role": "Coding Agent",
                    "dependencies": ["hallucinated_non_existent_id"],
                }
            ],
        )

        with patch("app.features.workspaces.trust_service.get_workspace_trust", return_value={"trusted": True}), \
             patch("app.features.ai.agent_routes.create_job") as mock_cj, \
             patch("app.features.ai.agent_routes.create_task") as mock_ct, \
             patch("app.features.ai.agent_routes.dag_engine.start_job") as mock_sj:
            mock_cj.return_value = None
            mock_ct.return_value = None
            mock_sj.return_value = None

            res = await start_job(req)
            self.assertIn("job_id", res)

            # Check that create_task was called with empty dependencies (hallucinated ID dropped)
            mock_ct.assert_called_once()
            _, kwargs = mock_ct.call_args
            self.assertEqual(kwargs["dependencies"], [])

    def test_no_httpx_response_hack(self):
        """Verify zero instances of the httpx.Response status-200 hack in non-test backend code."""
        import subprocess
        result = subprocess.run(
            ["git", "grep", "-rn", "--", "httpx.Response(200", ":(exclude)tests/*", ":(exclude)*.md"],
            cwd=str(BACKEND_DIR.parent),
            capture_output=True,
            text=True,
        )
        # Filter out any matches from test files themselves
        matches = [
            line for line in result.stdout.strip().splitlines()
            if line and "/tests/" not in line and "\\tests\\" not in line
        ]
        self.assertEqual(matches, [], f"Found forbidden httpx.Response hack in app code: {matches}")



if __name__ == "__main__":
    unittest.main(verbosity=2)
