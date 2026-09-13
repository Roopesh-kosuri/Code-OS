from __future__ import annotations
import pytest
from pathlib import Path


# ---------------------------------------------------------------------------
# AUD-001: Pre-Approval Filesystem Mutation
# ---------------------------------------------------------------------------

class TestAud001PreApprovalDir:
    def test_nested_new_file_reject_leaves_no_directories(self, tmp_path):
        dirs_before = {p.relative_to(tmp_path) for p in tmp_path.rglob('*') if p.is_dir()}
        from app.features.ai.schemas import FileChange
        _change = FileChange(path='new/a/file.ts', original='', updated='console.log(hi);')
        dirs_after = {p.relative_to(tmp_path) for p in tmp_path.rglob('*') if p.is_dir()}
        new_dirs = dirs_after - dirs_before
        assert not new_dirs, f'AUD-001: staging created unexpected directories: {new_dirs}'
        assert not (tmp_path / 'new').exists(), 'AUD-001: pre-approval mkdir still present'

    def test_nested_new_file_timeout_leaves_no_directories(self, tmp_path):
        from app.features.ai.schemas import FileChange
        _change = FileChange(path='new/a/file.ts', original='', updated='hello')
        assert not (tmp_path / 'new' / 'a').exists(), \
            'AUD-001: parent dir was created during staging (pre-approval mkdir not removed)'

    def test_apply_creates_dirs_after_approval(self, tmp_path):
        from app.features.files.service import write_file
        write_file(str(tmp_path), 'sub/dir/new_file.txt', 'approved content')
        assert (tmp_path / 'sub' / 'dir' / 'new_file.txt').exists()


# ---------------------------------------------------------------------------
# AUD-006: Escalation Resolver Exact Action ID
# ---------------------------------------------------------------------------

class TestAud006EscalationExactId:
    def setup_method(self):
        from app.features.ai.harness.approval_coordinator import _pending_escalations
        _pending_escalations.clear()

    def teardown_method(self):
        from app.features.ai.harness.approval_coordinator import _pending_escalations
        _pending_escalations.clear()

    def _register(self, action_id: str, workspace: str = '/ws/a', task: str = 'test task'):
        from app.features.ai.harness.approval_coordinator import PendingEscalation, _pending_escalations
        esc = PendingEscalation(
            action_id=action_id, task=task, reasoning='r', confidence=0.9, workspace=workspace
        )
        _pending_escalations[action_id] = esc
        return esc

    def test_exact_action_id_resolves(self):
        from app.features.ai.harness.approval_coordinator import resolve_escalation
        esc = self._register('esc-abc-123')
        assert resolve_escalation(action_id='esc-abc-123', decision='escalate') is True
        assert esc.decision == 'escalate' and esc.event.is_set()

    def test_escalation_resolution_requires_exact_action_id(self):
        from app.features.ai.harness.approval_coordinator import resolve_escalation
        esc = self._register('esc-correct-id', workspace='/ws/myproject', task='build the app')
        result = resolve_escalation(action_id='esc-wrong-id', decision='escalate')
        assert result is False, 'AUD-006: wrong action_id must not resolve any escalation'
        assert not esc.event.is_set()

    def test_empty_action_id_rejected(self):
        from app.features.ai.harness.approval_coordinator import resolve_escalation
        esc = self._register('esc-exists')
        assert resolve_escalation(action_id='', decision='continue') is False
        assert not esc.event.is_set()

    def test_concurrent_escalations_resolve_independently(self):
        from app.features.ai.harness.approval_coordinator import resolve_escalation
        esc_a = self._register('esc-A', workspace='/ws/same', task='task A')
        esc_b = self._register('esc-B', workspace='/ws/same', task='task B')
        assert resolve_escalation(action_id='esc-B', decision='continue') is True
        assert esc_b.event.is_set()
        assert not esc_a.event.is_set(), 'AUD-006: esc-A must remain pending'
        assert resolve_escalation(action_id='esc-A', decision='escalate') is True
        assert esc_a.event.is_set()

    def test_workspace_substring_fallback_removed(self):
        from app.features.ai.harness.approval_coordinator import resolve_escalation
        esc = self._register('esc-xyz', workspace='/ws/myproject')
        assert resolve_escalation(action_id='', workspace='/ws/myproject', decision='escalate') is False
        assert not esc.event.is_set()

    def test_task_substring_fallback_removed(self):
        from app.features.ai.harness.approval_coordinator import resolve_escalation
        esc = self._register('esc-task', task='Implement authentication system')
        assert resolve_escalation(action_id='', task='authentication', decision='escalate') is False
        assert not esc.event.is_set()

    def test_most_recent_pending_fallback_removed(self):
        from app.features.ai.harness.approval_coordinator import resolve_escalation
        esc1 = self._register('esc-1')
        esc2 = self._register('esc-2')
        assert resolve_escalation(action_id='', decision='continue') is False
        assert not esc1.event.is_set() and not esc2.event.is_set()

    def test_stale_handoff_id_rejected(self):
        from app.features.ai.harness.approval_coordinator import resolve_escalation
        esc = self._register('esc-fresh')
        result = resolve_escalation(action_id='esc-stale-from-prev-session', decision='escalate')
        assert result is False, 'AUD-006: stale action_id must be rejected'
        assert not esc.event.is_set()

    def test_already_resolved_not_double_resolved(self):
        from app.features.ai.harness.approval_coordinator import resolve_escalation
        esc = self._register('esc-once')
        resolve_escalation(action_id='esc-once', decision='escalate')
        result2 = resolve_escalation(action_id='esc-once', decision='continue')
        assert result2 is False, 'AUD-006: already-resolved escalation must not flip decision'
        assert esc.decision == 'escalate'
