import unittest

from backend.app.features.ai.agents.coder import CoderAgent, PlanModel
from backend.app.features.ai.schemas import FileChange
from backend.app.features.ai.service import _provider_resilience


def plan(*, files=None, risks=None, goal="Add a print statement"):
    return PlanModel(
        ambiguous=False,
        clarifying_question="",
        goal=goal,
        hypothesis="A small edit is needed.",
        files_to_touch=files or ["main.py"],
        approach="Make the requested edit.",
        risks=risks or [],
        verification="Run the relevant check.",
    )


class CoderFastPathTests(unittest.TestCase):
    def test_simple_single_file_task_does_not_escalate_to_duo(self):
        escalates, reasons = CoderAgent.is_high_stakes(plan(), "Add a print statement", "")
        self.assertFalse(escalates)
        self.assertEqual(reasons, [])

    def test_risky_and_multi_file_tasks_keep_full_rigor(self):
        risky, reasons = CoderAgent.is_high_stakes(plan(risks=["May affect authentication"]), "Update login", "")
        multi_file, _ = CoderAgent.is_high_stakes(plan(files=[f"file{i}.py" for i in range(6)]), "Update modules", "")
        self.assertTrue(risky)
        self.assertIn("planner reported risks", reasons)
        self.assertTrue(multi_file)

    def test_small_one_file_patch_is_trivial_but_risky_or_large_patch_is_not(self):
        small = [FileChange(path="main.py", original="", updated="print('hello')\n")]
        large = [FileChange(path="main.py", original="x" * 700, updated="y" * 700)]
        self.assertTrue(CoderAgent.is_trivial_change(plan(), small))
        self.assertFalse(CoderAgent.is_trivial_change(plan(risks=["production impact"]), small))
        self.assertFalse(CoderAgent.is_trivial_change(plan(), large))

    def test_provider_resilience_uses_safe_per_provider_limits(self):
        settings = {
            "ai.provider.ollama.timeout_seconds": "420",
            "ai.provider.groq.timeout_seconds": "25",
            "ai.provider.groq.retries": "2",
        }
        self.assertEqual(_provider_resilience(settings, "ollama"), (420.0, 1))
        self.assertEqual(_provider_resilience(settings, "groq"), (25.0, 2))
        self.assertEqual(_provider_resilience({}, "openai"), (60.0, 1))

    # --- New Boundary and Edge Case Tests ---

    def test_files_to_touch_exactly_five_does_not_escalate(self):
        # 5 files is the boundary - should NOT trigger escalation by itself
        five_files = [f"file{i}.py" for i in range(5)]
        escalates, reasons = CoderAgent.is_high_stakes(plan(files=five_files), "Clean up comments", "context")
        self.assertFalse(escalates)
        self.assertEqual(reasons, [])

    def test_files_to_touch_exactly_six_escalates(self):
        # 6 files is above the boundary - should trigger escalation
        six_files = [f"file{i}.py" for i in range(6)]
        escalates, reasons = CoderAgent.is_high_stakes(plan(files=six_files), "Clean up comments", "context")
        self.assertTrue(escalates)
        self.assertIn("6 files planned", reasons)

    def test_many_files_no_risk_keywords_escalates(self):
        # 10 files with a harmless title and goal should still trigger escalation based on file count
        ten_files = [f"file{i}.py" for i in range(10)]
        escalates, reasons = CoderAgent.is_high_stakes(plan(files=ten_files), "Harmless task", "Harmless context")
        self.assertTrue(escalates)
        self.assertIn("10 files planned", reasons)

    def test_trivial_boundary_exactly_limit_chars(self):
        # Trivial diff max chars is 1200. Combined original and updated length = 1200
        original = "a" * 600
        updated = "b" * 600
        proposals = [FileChange(path="main.py", original=original, updated=updated)]
        self.assertTrue(CoderAgent.is_trivial_change(plan(), proposals))

    def test_trivial_boundary_one_over_limit_chars(self):
        # Combined original and updated length = 1201 (over the 1200 limit)
        original = "a" * 600
        updated = "b" * 601
        proposals = [FileChange(path="main.py", original=original, updated=updated)]
        self.assertFalse(CoderAgent.is_trivial_change(plan(), proposals))


if __name__ == "__main__":
    unittest.main()
