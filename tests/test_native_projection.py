from dataclasses import replace
import pytest
from wiki_core.native_projection import Correlation, ProjectionHold, project_native_task

C = Correlation("action-a", "task-a", "run-a", "claim-a", "intent-a")


def row(**changes):
    return dict(wiki_action_id=C.action_id, task_id=C.task_id, run_id=C.run_id,
                claim_id=C.claim_id, intent_id=C.intent_id, revision="r1",
                status="running", delivery="acknowledged", claim_live=True,
                **changes)


def test_shared_projection_contains_only_authorized_metadata_and_never_a_body():
    seen = []
    result = project_native_task(C, row(title="private title", body="private body", result="private result"),
                                 native_columns=("running", "blocked", "review", "done"), authorize=lambda c, p: seen.append(p))
    assert result == seen[0]
    assert not {"title", "body", "result", "effect_id"} & result.keys()
    assert result["native_status"] == "running" and not result["retry_authorized"]


@pytest.mark.parametrize("field", ["action_id", "task_id", "run_id", "claim_id", "intent_id"])
def test_a_new_title_or_claim_never_creates_or_rebinds_a_task(field):
    with pytest.raises(ProjectionHold, match="correlation_changed"):
        project_native_task(replace(C, **{field: "another"}), row(), native_columns=("running", "blocked", "review", "done"), authorize=lambda *a: None)


def test_timeout_and_lost_lease_require_reconciliation_on_the_same_task():
    native = row(); native.update(delivery="unknown", claim_live=False)
    result = project_native_task(C, native, native_columns=("running", "blocked", "review", "done"), authorize=lambda *a: None)
    assert result["reconcile_required"] and not result["retry_authorized"]
    assert result["task_id"] == C.task_id and result["native_status"] == "running"
    native.update(status="done")
    with pytest.raises(ProjectionHold, match="completion_unproven"):
        project_native_task(C, native, native_columns=("running", "blocked", "review", "done"), authorize=lambda *a: None)


def test_disclosure_denial_preserves_the_native_task():
    native = row(); before = dict(native)
    def deny(*args):
        raise PermissionError("audience denied")
    with pytest.raises(PermissionError):
        project_native_task(C, native, native_columns=("running", "blocked", "review", "done"), authorize=deny)
    assert native == before
