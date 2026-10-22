"""Pure projection of an existing native task; never creates or schedules work."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


class ProjectionHold(ValueError):
    pass


@dataclass(frozen=True)
class Correlation:
    action_id: str
    task_id: str
    run_id: str
    claim_id: str
    intent_id: str


def project_native_task(correlation: Correlation, native: dict, *,
                        authorize: Callable[[Correlation, dict], None],
                        native_columns: tuple[str, ...]) -> dict:
    """Host supplies a fresh Kanban read and independently checks disclosure.

    The caller must reuse the exact task ID. No title matching, fallback executor,
    synthetic completion, body/title copying or independent status machine.
    Unknown delivery never authorizes retry; a new claim needs reconciliation.
    """
    if any(not isinstance(v, str) or not v for v in vars(correlation).values()):
        raise ProjectionHold("native_correlation_required")
    expected = {"wiki_action_id": correlation.action_id, "task_id": correlation.task_id,
                "run_id": correlation.run_id, "claim_id": correlation.claim_id,
                "intent_id": correlation.intent_id}
    if any(native.get(k) != v for k, v in expected.items()):
        raise ProjectionHold("native_correlation_changed")
    # IDs and a native revision are references, never access grants. Validation
    # of their format and ownership belongs to the trusted native adapter.
    if not isinstance(native.get("revision"), str) or not native["revision"]:
        raise ProjectionHold("native_revision_required")
    # Consume the native /workflow columns, including consumer-defined columns.
    # The wiki never invents a second lifecycle or maps a title to a task.
    if not native_columns or native.get("status") not in native_columns:
        raise ProjectionHold("native_state_unknown")
    delivery = native.get("delivery")
    if delivery not in {"queued", "acknowledged", "unknown", "not_submitted"}:
        raise ProjectionHold("native_delivery_unknown")
    if native["status"] == "done" and (delivery != "acknowledged" or not native.get("effect_id")):
        raise ProjectionHold("native_completion_unproven")
    projection = {**expected, "native_revision": native["revision"],
                  "native_status": native["status"], "delivery": delivery,
                  "reconcile_required": delivery == "unknown" or native.get("claim_live") is not True,
                  "retry_authorized": False}
    # Shared projection is an allowlist. Private results/titles/questions remain
    # at their protected native reference, not passed to the disclosure callback.
    authorize(correlation, projection)
    return projection
