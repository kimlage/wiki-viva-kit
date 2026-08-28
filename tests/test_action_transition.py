from __future__ import annotations

import hashlib
import multiprocessing
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import yaml

from wiki_core.action_transition import (
    ACTION_TRANSITION_RECEIPT_VERSION,
    ActionTransitionError,
    action_transition_diagnostics,
    transition_action_page,
)
from wiki_core.frontmatter import parse_frontmatter, parse_frontmatter_flat_with_errors
import wiki_core.action_transition as transition_module


FIXED_AT = "2026-07-11T14:30:00Z"


def _multiprocess_transition_attempt(
    root: str,
    page: str,
    target: str,
    expected_sha256: str,
    barrier,
    queue,
) -> None:
    barrier.wait()
    try:
        receipt = transition_action_page(
            Path(root),
            Path(page),
            target,
            blocker_reason=(
                "Synthetic dependency is unavailable." if target == "blocked" else None
            ),
            expected_sha256=expected_sha256,
            recorded_at=FIXED_AT,
        )
        queue.put(("ok", receipt.next_state))
    except ActionTransitionError as exc:
        queue.put(("error", exc.code))


def _write_action(
    root: Path,
    *,
    action_state: str | None = "open",
    status: str | None = "pending",
    body_state: str = "",
    extra: dict[str, object] | None = None,
) -> Path:
    values: dict[str, object] = {
        "page_id": "action-synthetic-review",
        "page_type": "action",
        "title": "Action - synthetic review",
        "context": "example",
        "visibility": "private_self",
        "updated_at": "2026-07-10",
        "stale_after_days": 30,
        "next_action": "Review the synthetic evidence.",
        "owner_kind": "unassigned",
        "created_at": "2026-07-10",
        "priority": "normal",
        "attention_basis": "Synthetic transition coverage.",
        "source_refs": [],
        "moc_parent": "memories/index.md",
    }
    if action_state is not None:
        values["action_state"] = action_state
    if status is not None:
        values["status"] = status
    values.update(extra or {})
    path = root / "memories/actions/action-synthetic-review.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    body_line = f"\n{body_state}\n" if body_state else "\n"
    path.write_text(
        "---\n"
        + yaml.safe_dump(values, sort_keys=False, allow_unicode=True)
        + "---\n\n# Synthetic action\n"
        + body_line
        + "Body is preserved verbatim.\n",
        encoding="utf-8",
    )
    return path


def _values(path: Path) -> dict[str, object]:
    return parse_frontmatter(path)[0]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_writer_output_is_compatible_with_structured_and_flat_frontmatter_parsers(
    tmp_path: Path,
) -> None:
    long_attention = " ".join(["Synthetic downstream pressure"] * 20) + "."
    path = _write_action(
        tmp_path,
        extra={
            "attention_basis": long_attention,
            "related_holons": ["holon-synthetic-one", "holon-synthetic-two"],
        },
    )

    transition_action_page(
        tmp_path,
        path,
        "in_progress",
        reason="Exercise the canonical writer under long localized content.",
        recorded_at=FIXED_AT,
    )

    rendered = path.read_text(encoding="utf-8")
    structured, _body = parse_frontmatter(rendered)
    flat, errors = parse_frontmatter_flat_with_errors(rendered)

    assert errors == []
    assert structured["attention_basis"] == long_attention
    assert structured["related_holons"] == [
        "holon-synthetic-one",
        "holon-synthetic-two",
    ]
    assert flat["related_holons"] == [
        "holon-synthetic-one",
        "holon-synthetic-two",
    ]
    assert "\n  Synthetic downstream pressure" not in rendered


def test_valid_transition_is_atomic_receipted_and_auditable(tmp_path: Path) -> None:
    path = _write_action(tmp_path)
    before = path.read_text(encoding="utf-8")

    receipt = transition_action_page(
        tmp_path,
        path.relative_to(tmp_path),
        "in_progress",
        reason="Synthetic review started.",
        expected_sha256=_sha(path),
        recorded_at=FIXED_AT,
    )

    values = _values(path)
    assert receipt.changed is True
    assert receipt.idempotent is False
    assert receipt.previous_state == "open"
    assert receipt.next_state == "in_progress"
    assert receipt.page_ref == "memories/actions/action-synthetic-review.md"
    assert receipt.page_id == "action-synthetic-review"
    assert receipt.receipt_id.startswith("sha256:")
    assert receipt.before_sha256 != receipt.after_sha256
    assert "Synthetic review started" not in str(receipt.to_dict())
    assert values["action_state"] == "in_progress"
    assert values["status"] == "pending"
    assert values["updated_at"] == "2026-07-11"
    assert values["action_state_history"] == [
        {
            "schema_version": ACTION_TRANSITION_RECEIPT_VERSION,
            "kind": "transition",
            "page_id": "action-synthetic-review",
            "from": "open",
            "to": "in_progress",
            "at": FIXED_AT,
            "state_source": "action_state",
            "before_sha256": receipt.before_sha256,
            "before_revision": hashlib.sha256(
                before.rstrip("\r\n").encode("utf-8")
            ).hexdigest(),
            "payload_sha256": values["action_state_history"][0]["payload_sha256"],
            "support_fields": [],
            "governed_support_sha256": values["action_state_history"][0][
                "governed_support_sha256"
            ],
            "prior_receipt_id": "",
            "reason_recorded": True,
            "receipt_id": receipt.receipt_id,
            "reason": "Synthetic review started.",
        }
    ]
    assert "Body is preserved verbatim." in path.read_text(encoding="utf-8")
    assert action_transition_diagnostics(before, path.read_text(encoding="utf-8")) == ()


def test_atomic_persistence_fsyncs_file_before_rename_and_parent_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_action(tmp_path)
    synced: list[str] = []
    original_fsync = transition_module.os.fsync

    def recording_fsync(descriptor: int) -> None:
        mode = os.fstat(descriptor).st_mode
        synced.append("directory" if stat.S_ISDIR(mode) else "file")
        original_fsync(descriptor)

    monkeypatch.setattr(transition_module.os, "fsync", recording_fsync)

    transition_action_page(
        tmp_path,
        path,
        "in_progress",
        recorded_at=FIXED_AT,
    )

    assert synced == ["file", "directory"]


def test_directory_fsync_failure_returns_success_warning_after_committed_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_action(tmp_path)
    before = path.read_bytes()
    original_fsync = transition_module.os.fsync

    def fail_only_directory_sync(descriptor: int) -> None:
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("synthetic directory fsync failure")
        original_fsync(descriptor)

    monkeypatch.setattr(transition_module.os, "fsync", fail_only_directory_sync)

    receipt = transition_action_page(
        tmp_path,
        path,
        "in_progress",
        expected_sha256=hashlib.sha256(before).hexdigest(),
        recorded_at=FIXED_AT,
    )

    assert receipt.changed is True
    assert "directory_fsync_unavailable" in receipt.warnings
    assert path.read_bytes() != before
    assert _values(path)["action_state"] == "in_progress"
    assert len(_values(path)["action_state_history"]) == 1


def test_invalid_transition_fails_closed_without_touching_file(tmp_path: Path) -> None:
    path = _write_action(tmp_path, action_state="in_progress")
    before = path.read_bytes()

    with pytest.raises(ActionTransitionError) as raised:
        transition_action_page(tmp_path, path, "open", recorded_at=FIXED_AT)

    assert raised.value.code == "invalid_transition"
    assert raised.value.current_state == "in_progress"
    assert raised.value.next_state == "open"
    assert raised.value.allowed_next_states == (
        "blocked",
        "cancelled",
        "done",
        "waiting_human",
    )
    assert path.read_bytes() == before


@pytest.mark.parametrize("terminal", ["done", "cancelled"])
def test_terminal_state_cannot_reopen(tmp_path: Path, terminal: str) -> None:
    extra = (
        {"completion_receipt": "commit:synthetic"}
        if terminal == "done"
        else {"cancellation_receipt": "decision:synthetic"}
    )
    path = _write_action(tmp_path, action_state=terminal, extra=extra)
    before = path.read_bytes()

    with pytest.raises(ActionTransitionError, match="invalid_transition"):
        transition_action_page(tmp_path, path, "open", recorded_at=FIXED_AT)

    assert path.read_bytes() == before


def test_repeated_transition_is_a_true_noop_with_same_receipt(tmp_path: Path) -> None:
    path = _write_action(tmp_path)
    first = transition_action_page(
        tmp_path,
        path,
        "in_progress",
        reason="Start.",
        recorded_at=FIXED_AT,
    )
    after_first = path.read_bytes()

    second = transition_action_page(tmp_path, path, "in_progress")

    assert second.changed is False
    assert second.idempotent is True
    assert second.receipt_id == first.receipt_id
    assert second.before_sha256 == second.after_sha256
    assert path.read_bytes() == after_first
    assert len(_values(path)["action_state_history"]) == 1


def test_concurrent_same_revision_attempts_serialize_and_one_fails_stale(
    tmp_path: Path,
) -> None:
    path = _write_action(tmp_path)
    expected = _sha(path)

    def attempt(target: str):
        try:
            return transition_action_page(
                tmp_path,
                path,
                target,
                blocker_reason=(
                    "Synthetic dependency is unavailable."
                    if target == "blocked"
                    else None
                ),
                expected_sha256=expected,
                recorded_at=FIXED_AT,
            )
        except ActionTransitionError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, ("in_progress", "blocked")))

    successes = [result for result in results if not isinstance(result, Exception)]
    failures = [
        result for result in results if isinstance(result, ActionTransitionError)
    ]
    assert len(successes) == 1
    assert [failure.code for failure in failures] == ["stale_action_revision"]
    assert _values(path)["action_state"] in {"in_progress", "blocked"}
    assert len(_values(path)["action_state_history"]) == 1


def test_multiprocess_same_revision_attempts_are_serialized_by_file_lock(
    tmp_path: Path,
) -> None:
    path = _write_action(tmp_path)
    expected = _sha(path)
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    queue = context.Queue()
    processes = [
        context.Process(
            target=_multiprocess_transition_attempt,
            args=(str(tmp_path), str(path), target, expected, barrier, queue),
        )
        for target in ("in_progress", "blocked")
    ]
    for process in processes:
        process.start()
    outcomes = [queue.get(timeout=15) for _process in processes]
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0

    assert sorted(kind for kind, _value in outcomes) == ["error", "ok"]
    assert ("error", "stale_action_revision") in outcomes
    assert _values(path)["action_state"] in {"in_progress", "blocked"}
    assert len(_values(path)["action_state_history"]) == 1


@pytest.mark.parametrize(
    ("status", "body_state", "target", "extra", "expected_previous"),
    [
        ("completed", "", "done", {"completion_receipt": "commit:legacy"}, "done"),
        (
            None,
            "Estado: em andamento",
            "blocked",
            {"blocker_reason": "Synthetic dependency is unavailable."},
            "in_progress",
        ),
        ("pending", "", "in_progress", {}, "open"),
    ],
)
def test_legacy_aliases_remain_readable_and_are_canonicalized_once(
    tmp_path: Path,
    status: str | None,
    body_state: str,
    target: str,
    extra: dict[str, object],
    expected_previous: str,
) -> None:
    path = _write_action(
        tmp_path,
        action_state=None,
        status=status,
        body_state=body_state,
        extra=extra,
    )
    before = path.read_text(encoding="utf-8")

    receipt = transition_action_page(
        tmp_path,
        path,
        target,
        recorded_at=FIXED_AT,
    )

    values = _values(path)
    assert receipt.previous_state == expected_previous
    assert receipt.canonicalized_legacy is True
    assert "legacy_action_state" in receipt.warnings
    assert "legacy_action_state_canonicalized" in receipt.warnings
    assert values["action_state"] == target
    if status is not None:
        assert values["status"] == status
    assert action_transition_diagnostics(before, path.read_text(encoding="utf-8")) == ()


def test_legacy_alias_is_not_accepted_as_a_new_authored_target(tmp_path: Path) -> None:
    path = _write_action(tmp_path)
    before = path.read_bytes()

    with pytest.raises(ActionTransitionError) as raised:
        transition_action_page(tmp_path, path, "completed")

    assert raised.value.code == "invalid_target_state"
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    ("target", "expected_code"),
    [
        ("done", "missing_completion_receipt"),
        ("cancelled", "missing_cancellation_receipt"),
        ("blocked", "missing_blocker_reason"),
    ],
)
def test_transition_contract_fields_are_enforced_before_write(
    tmp_path: Path,
    target: str,
    expected_code: str,
) -> None:
    path = _write_action(tmp_path)
    before = path.read_bytes()

    with pytest.raises(ActionTransitionError) as raised:
        transition_action_page(tmp_path, path, target, recorded_at=FIXED_AT)

    assert raised.value.code == expected_code
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    [
        (
            "completion_receipt",
            "commit:premature",
            "completion_receipt_not_allowed",
        ),
        (
            "cancellation_receipt",
            "decision:premature",
            "cancellation_receipt_not_allowed",
        ),
        (
            "blocker_reason",
            "Premature blocker.",
            "blocker_reason_not_allowed",
        ),
        (
            "blocked_by",
            ["source:premature"],
            "blocked_by_not_allowed",
        ),
    ],
)
def test_state_specific_evidence_cannot_be_pre_recorded(
    tmp_path: Path,
    field: str,
    value: str,
    expected_code: str,
) -> None:
    path = _write_action(tmp_path)
    before = path.read_bytes()

    with pytest.raises(ActionTransitionError) as raised:
        transition_action_page(
            tmp_path,
            path,
            "in_progress",
            recorded_at=FIXED_AT,
            **{field: value},
        )

    assert raised.value.code == expected_code
    assert path.read_bytes() == before


def test_terminal_receipts_are_write_once(tmp_path: Path) -> None:
    path = _write_action(
        tmp_path,
        action_state="done",
        extra={"completion_receipt": "commit:first"},
    )
    before = path.read_bytes()

    with pytest.raises(ActionTransitionError) as raised:
        transition_action_page(
            tmp_path,
            path,
            "done",
            completion_receipt="commit:replacement",
            recorded_at=FIXED_AT,
        )

    assert raised.value.code == "immutable_receipt_conflict"
    assert path.read_bytes() == before


def test_same_state_governed_support_update_is_receipted_and_auditable(
    tmp_path: Path,
) -> None:
    path = _write_action(tmp_path)
    before = path.read_text(encoding="utf-8")

    receipt = transition_action_page(
        tmp_path,
        path,
        "open",
        next_action="Review the second synthetic evidence packet.",
        recorded_at=FIXED_AT,
    )

    values = _values(path)
    entry = values["action_state_history"][-1]
    assert receipt.changed is True
    assert receipt.previous_state == receipt.next_state == "open"
    assert entry["kind"] == "contract_update"
    assert entry["support_fields"] == ["next_action"]
    assert len(entry["governed_support_sha256"]) == 64
    assert action_transition_diagnostics(before, path.read_text(encoding="utf-8")) == ()


def test_leaving_blocked_clears_stale_blocker_and_receipts_the_support_delta(
    tmp_path: Path,
) -> None:
    path = _write_action(
        tmp_path,
        action_state="blocked",
        extra={
            "blocked_by": ["source-synthetic-dependency"],
            "blocker_reason": "Synthetic dependency unavailable.",
        },
    )
    before = path.read_text(encoding="utf-8")

    transition_action_page(
        tmp_path,
        path,
        "in_progress",
        recorded_at=FIXED_AT,
    )

    values = _values(path)
    assert "blocker_reason" not in values
    assert "blocked_by" not in values
    assert values["action_state_history"][-1]["support_fields"] == [
        "blocked_by",
        "blocker_reason",
    ]
    assert action_transition_diagnostics(before, path.read_text(encoding="utf-8")) == ()


@pytest.mark.parametrize(
    ("current", "target", "receipt_field", "receipt_value"),
    [
        ("in_progress", "done", "completion_receipt", "commit:synthetic-done"),
        ("blocked", "cancelled", "cancellation_receipt", "decision:synthetic-cancel"),
    ],
)
def test_terminal_transition_clears_actionable_fields_and_records_exact_instant(
    tmp_path: Path,
    current: str,
    target: str,
    receipt_field: str,
    receipt_value: str,
) -> None:
    path = _write_action(
        tmp_path,
        action_state=current,
        extra={
            "blocked_by": ["source-synthetic-dependency"],
            "blocker_reason": "Synthetic dependency unavailable.",
            # A malformed legacy page can carry the opposite receipt. The
            # canonical writer repairs it rather than publishing contradiction.
            "cancellation_receipt" if target == "done" else "completion_receipt": "receipt:premature",
        },
    )
    before = path.read_text(encoding="utf-8")

    transition_action_page(
        tmp_path,
        path,
        target,
        recorded_at=FIXED_AT,
        **{receipt_field: receipt_value},
    )

    values = _values(path)
    assert values["action_state"] == target
    assert values["completed_at"] == FIXED_AT
    assert values[receipt_field] == receipt_value
    for stale in (
        "next_action",
        "blocked_by",
        "blocker_reason",
        "cancellation_receipt" if target == "done" else "completion_receipt",
    ):
        assert stale not in values
    assert values["action_state_history"][-1]["at"] == FIXED_AT
    assert "completed_at" in values["action_state_history"][-1]["support_fields"]
    assert action_transition_diagnostics(before, path.read_text(encoding="utf-8")) == ()


@pytest.mark.parametrize(
    "recorded_at",
    ["2026-07-11", "2026-07-11T14:30Z", "2026-07-11T14:30:00"],
)
def test_terminal_transition_refuses_imprecise_or_timezone_free_clock(
    tmp_path: Path,
    recorded_at: str,
) -> None:
    path = _write_action(tmp_path, action_state="in_progress")
    before = path.read_bytes()

    with pytest.raises(ActionTransitionError) as raised:
        transition_action_page(
            tmp_path,
            path,
            "done",
            completion_receipt="commit:synthetic",
            recorded_at=recorded_at,
        )

    assert raised.value.code == "invalid_recorded_at"
    assert path.read_bytes() == before


def test_writer_rejects_causal_clock_regression_and_preserves_latest_revision(
    tmp_path: Path,
) -> None:
    path = _write_action(tmp_path)
    transition_action_page(
        tmp_path,
        path,
        "in_progress",
        recorded_at="2026-07-11T14:30:00.000001Z",
    )
    before = path.read_bytes()

    with pytest.raises(ActionTransitionError) as raised:
        transition_action_page(
            tmp_path,
            path,
            "waiting_human",
            recorded_at="2026-07-11T14:30:00Z",
        )

    assert raised.value.code == "non_monotonic_recorded_at"
    assert path.read_bytes() == before


def test_writer_rejects_first_receipt_before_existing_updated_at(
    tmp_path: Path,
) -> None:
    path = _write_action(tmp_path)
    before = path.read_bytes()

    with pytest.raises(ActionTransitionError) as raised:
        transition_action_page(
            tmp_path,
            path,
            "in_progress",
            recorded_at="1900-01-01T00:00:00Z",
        )

    assert raised.value.code == "recorded_at_before_updated_at"
    assert path.read_bytes() == before


def test_invalid_canonical_source_never_falls_back_to_legacy_done(
    tmp_path: Path,
) -> None:
    path = _write_action(
        tmp_path,
        action_state="finished",
        status="completed",
        extra={"completion_receipt": "commit:legacy"},
    )

    with pytest.raises(ActionTransitionError) as raised:
        transition_action_page(tmp_path, path, "done")

    assert raised.value.code == "invalid_current_state"
    assert raised.value.warnings == ("invalid_action_state",)


def test_stale_revision_secret_and_path_escapes_have_safe_diagnostics(
    tmp_path: Path,
) -> None:
    path = _write_action(tmp_path)
    before = path.read_bytes()

    with pytest.raises(ActionTransitionError) as stale:
        transition_action_page(
            tmp_path,
            path,
            "in_progress",
            expected_sha256="0" * 64,
        )
    assert stale.value.to_dict() == {
        "ok": False,
        "error": "action transition refused",
        "error_code": "stale_action_revision",
    }

    secret = "AKIAIOSFODNN7EXAMPLE"
    with pytest.raises(ActionTransitionError) as blocked:
        transition_action_page(
            tmp_path,
            path,
            "in_progress",
            reason=secret,
        )
    assert blocked.value.code == "secret_blocked"
    assert secret not in str(blocked.value.to_dict())

    external = tmp_path.parent / "external-action.md"
    external.write_text("external\n", encoding="utf-8")
    with pytest.raises(ActionTransitionError) as escaped:
        transition_action_page(tmp_path, external, "in_progress")
    assert escaped.value.code == "path_outside_repo"
    assert str(external) not in str(escaped.value.to_dict())
    assert path.read_bytes() == before


def test_action_symlink_is_refused_and_external_target_is_preserved(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    external = tmp_path / "external.md"
    external.write_text("external bytes\n", encoding="utf-8")
    link = root / "memories/actions/link.md"
    link.parent.mkdir(parents=True)
    link.symlink_to(external)

    with pytest.raises(ActionTransitionError) as raised:
        transition_action_page(root, link, "in_progress")

    assert raised.value.code == "symlink_action_path"
    assert external.read_text(encoding="utf-8") == "external bytes\n"


def test_lock_directory_symlink_escape_is_refused_without_external_write(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    path = _write_action(root)
    before = path.read_bytes()
    external = tmp_path / "external-lock-root"
    external.mkdir()
    keeper = external / "keep.txt"
    keeper.write_text("preserve me\n", encoding="utf-8")
    (root / "data").symlink_to(external, target_is_directory=True)

    with pytest.raises(ActionTransitionError) as raised:
        transition_action_page(root, path, "in_progress")

    assert raised.value.code == "action_lock_symlink"
    assert path.read_bytes() == before
    assert keeper.read_text(encoding="utf-8") == "preserve me\n"
    assert sorted(item.name for item in external.iterdir()) == ["keep.txt"]


def test_hardlinked_lock_is_refused_before_any_lock_file_write(
    tmp_path: Path,
) -> None:
    path = _write_action(tmp_path)
    before = path.read_bytes()
    lock_directory = tmp_path / "data/derived/action-transition-locks"
    lock_directory.mkdir(parents=True)
    external = tmp_path / "external-lock-bytes"
    sentinel = b"preserve hardlink referent\n"
    external.write_bytes(sentinel)
    page_ref = path.relative_to(tmp_path).as_posix()
    lock_path = lock_directory / f"{hashlib.sha256(page_ref.encode()).hexdigest()}.lock"
    os.link(external, lock_path)

    with pytest.raises(ActionTransitionError) as raised:
        transition_action_page(tmp_path, path, "in_progress")

    assert raised.value.code == "action_lock_hardlink"
    assert external.read_bytes() == sentinel
    assert lock_path.read_bytes() == sentinel
    assert path.read_bytes() == before


def test_missing_platform_lock_backend_refuses_instead_of_racing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_action(tmp_path)
    before = path.read_bytes()
    monkeypatch.setattr(transition_module, "_fcntl", None)
    monkeypatch.setattr(transition_module, "_msvcrt", None)

    with pytest.raises(ActionTransitionError) as raised:
        transition_action_page(tmp_path, path, "in_progress")

    assert raised.value.code == "action_lock_backend_unavailable"
    assert path.read_bytes() == before
    assert not (tmp_path / "data").exists()


def test_audit_rejects_manual_valid_or_invalid_state_edits_without_receipt(
    tmp_path: Path,
) -> None:
    path = _write_action(tmp_path)
    previous = path.read_text(encoding="utf-8")
    manual_valid = previous.replace("action_state: open", "action_state: in_progress")
    valid_diagnostics = action_transition_diagnostics(previous, manual_valid)
    assert [item.code for item in valid_diagnostics] == [
        "missing_action_transition_receipt"
    ]

    manual_invalid = previous.replace("action_state: open", "action_state: cancelled")
    manual_invalid = manual_invalid.replace(
        "next_action: Review the synthetic evidence.\n",
        "next_action: Review the synthetic evidence.\n"
        "cancellation_receipt: decision:synthetic\n",
    )
    invalid_diagnostics = action_transition_diagnostics(previous, manual_invalid)
    assert [item.code for item in invalid_diagnostics] == [
        "invalid_action_lifecycle_contract"
    ]
    assert "next_action_not_allowed" in invalid_diagnostics[0].message


def test_audit_rejects_existing_action_page_id_rewrite(tmp_path: Path) -> None:
    path = _write_action(tmp_path)
    previous = path.read_text(encoding="utf-8")
    rewritten = previous.replace(
        "page_id: action-synthetic-review",
        "page_id: action-foreign-identity",
    )

    diagnostics = action_transition_diagnostics(previous, rewritten)

    assert [item.code for item in diagnostics] == ["action_page_id_changed"]


def test_audit_rejects_appended_receipt_bound_to_foreign_page_id(
    tmp_path: Path,
) -> None:
    path = _write_action(tmp_path)
    previous = path.read_text(encoding="utf-8")
    transition_action_page(
        tmp_path,
        path,
        "in_progress",
        recorded_at=FIXED_AT,
    )
    current = path.read_text(encoding="utf-8")
    values, body = transition_module._parse_document(current)
    entry = values["action_state_history"][-1]
    entry["page_id"] = "action-foreign-identity"
    entry["receipt_id"] = transition_module._receipt_id(entry)
    tampered = transition_module._render_document(values, body)

    diagnostics = action_transition_diagnostics(previous, tampered)

    assert [item.code for item in diagnostics] == [
        "invalid_action_transition_receipt"
    ]
    assert "page_id" in diagnostics[0].message


def test_action_writes_fail_closed_on_windows_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_action(tmp_path)
    before = path.read_bytes()
    monkeypatch.setattr(transition_module.os, "name", "nt")

    with pytest.raises(ActionTransitionError) as raised:
        transition_action_page(tmp_path, path, "in_progress")

    assert raised.value.code == "action_writes_unsupported_on_windows"
    assert path.read_bytes() == before


def test_audit_rejects_manual_support_edit_and_terminal_receipt_rewrite(
    tmp_path: Path,
) -> None:
    path = _write_action(tmp_path)
    previous = path.read_text(encoding="utf-8")
    support_edit = previous.replace(
        "next_action: Review the synthetic evidence.",
        "next_action: Bypass the governed writer.",
    )
    diagnostics = action_transition_diagnostics(previous, support_edit)
    assert [item.code for item in diagnostics] == ["missing_action_transition_receipt"]

    terminal = _write_action(
        tmp_path,
        action_state="done",
        extra={
            "next_action": "",
            "completed_at": FIXED_AT,
            "completion_receipt": "commit:original",
        },
    ).read_text(encoding="utf-8")
    rewritten = terminal.replace("commit:original", "commit:replacement")
    diagnostics = action_transition_diagnostics(terminal, rewritten)
    assert [item.code for item in diagnostics] == ["terminal_action_receipt_rewritten"]


def test_audit_allows_semantically_equal_legacy_schema_migration(
    tmp_path: Path,
) -> None:
    path = _write_action(tmp_path, action_state=None, status="pending")
    previous = path.read_text(encoding="utf-8")
    values, body = parse_frontmatter(path)
    values["action_state"] = "open"
    migrated = (
        "---\n"
        + yaml.safe_dump(values, sort_keys=False, allow_unicode=True)
        + "---\n"
        + body
    )

    assert action_transition_diagnostics(previous, migrated) == ()


def test_writer_receipts_legacy_canonicalization_with_governed_support_migration(
    tmp_path: Path,
) -> None:
    path = _write_action(tmp_path, action_state=None, status="pending")
    previous = path.read_text(encoding="utf-8")

    transition_action_page(
        tmp_path,
        path,
        "open",
        next_action="Use the migrated canonical action contract.",
        recorded_at=FIXED_AT,
    )

    values = _values(path)
    entry = values["action_state_history"][-1]
    assert values["action_state"] == "open"
    assert entry["kind"] == "legacy_canonicalization"
    assert entry["state_source"] == "status"
    assert entry["support_fields"] == ["next_action"]
    assert (
        entry["before_revision"]
        == hashlib.sha256(previous.rstrip("\r\n").encode("utf-8")).hexdigest()
    )
    assert (
        action_transition_diagnostics(previous, path.read_text(encoding="utf-8")) == ()
    )


def test_legacy_v1_receipt_remains_readable_but_cannot_bind_v2_only_fields(
    tmp_path: Path,
) -> None:
    path = _write_action(tmp_path)
    previous = path.read_text(encoding="utf-8")
    transition_action_page(
        tmp_path,
        path,
        "in_progress",
        recorded_at=FIXED_AT,
    )
    values, body = transition_module._parse_document(
        path.read_text(encoding="utf-8")
    )
    entry = values["action_state_history"][-1]
    entry["schema_version"] = "wiki_action_transition_receipt.v1"
    entry["governed_support_sha256"] = transition_module._governed_support_sha256(
        values,
        schema_version="wiki_action_transition_receipt.v1",
    )
    entry["receipt_id"] = transition_module._receipt_id(entry)
    legacy_current = transition_module._render_document(values, body)

    assert action_transition_diagnostics(previous, legacy_current) == ()

    values["action_state"] = "blocked"
    values["blocker_reason"] = "Synthetic blocker."
    values["blocked_by"] = ["source-new-v2-field"]
    entry["to"] = "blocked"
    entry["support_fields"] = ["blocker_reason"]
    entry["governed_support_sha256"] = transition_module._governed_support_sha256(
        values,
        schema_version="wiki_action_transition_receipt.v1",
    )
    entry["receipt_id"] = transition_module._receipt_id(entry)
    weakened = transition_module._render_document(values, body)
    diagnostics = action_transition_diagnostics(previous, weakened)
    assert [item.code for item in diagnostics] == [
        "action_transition_receipt_support_mismatch"
    ]


def test_audit_accepts_multi_step_receipt_chain_from_one_pr(tmp_path: Path) -> None:
    path = _write_action(tmp_path)
    previous = path.read_text(encoding="utf-8")
    first = transition_action_page(
        tmp_path,
        path,
        "in_progress",
        recorded_at="2026-07-11T14:30:00Z",
    )
    second = transition_action_page(
        tmp_path,
        path,
        "done",
        completion_receipt="commit:synthetic-finish",
        recorded_at="2026-07-11T14:31:00Z",
    )

    assert first.receipt_id != second.receipt_id
    assert (
        action_transition_diagnostics(previous, path.read_text(encoding="utf-8")) == ()
    )
    history = _values(path)["action_state_history"]
    assert history[1]["prior_receipt_id"] == history[0]["receipt_id"]


def test_tampered_receipt_and_rewritten_history_are_rejected(tmp_path: Path) -> None:
    path = _write_action(tmp_path)
    previous = path.read_text(encoding="utf-8")
    transition_action_page(
        tmp_path,
        path,
        "in_progress",
        recorded_at=FIXED_AT,
    )
    values, body = parse_frontmatter(path)
    values["action_state_history"][0]["payload_sha256"] = "f" * 64
    tampered = (
        "---\n"
        + yaml.safe_dump(values, sort_keys=False, allow_unicode=True)
        + "---\n"
        + body
    )

    diagnostics = action_transition_diagnostics(previous, tampered)
    assert [item.code for item in diagnostics] == ["invalid_action_transition_receipt"]
    assert "does not match" in diagnostics[0].message


def test_audit_rejects_receipt_time_inversion_and_updated_at_regression(
    tmp_path: Path,
) -> None:
    path = _write_action(tmp_path)
    previous = path.read_text(encoding="utf-8")
    transition_action_page(
        tmp_path,
        path,
        "in_progress",
        recorded_at="2026-07-11T14:30:00Z",
    )
    transition_action_page(
        tmp_path,
        path,
        "in_progress",
        next_action="Review the second packet.",
        recorded_at="2026-07-11T14:31:00Z",
    )
    values, body = transition_module._parse_document(
        path.read_text(encoding="utf-8")
    )
    second = values["action_state_history"][-1]
    second["at"] = "2026-07-11T14:29:00Z"
    second["receipt_id"] = transition_module._receipt_id(second)
    inverted = transition_module._render_document(values, body)

    diagnostics = action_transition_diagnostics(previous, inverted)
    assert [item.code for item in diagnostics] == [
        "invalid_action_transition_receipt"
    ]
    assert "causally monotonic" in diagnostics[0].message

    values, body = transition_module._parse_document(
        path.read_text(encoding="utf-8")
    )
    values["updated_at"] = "2026-07-09"
    regressed = transition_module._render_document(values, body)
    diagnostics = action_transition_diagnostics(previous, regressed)
    assert [item.code for item in diagnostics] == ["action_updated_at_regressed"]


def test_terminal_legacy_canonicalization_binds_completed_at_to_receipt_clock(
    tmp_path: Path,
) -> None:
    path = _write_action(
        tmp_path,
        action_state=None,
        status="completed",
        extra={"completion_receipt": "commit:legacy-terminal"},
    )
    previous = path.read_text(encoding="utf-8")
    transition_action_page(
        tmp_path,
        path,
        "done",
        recorded_at=FIXED_AT,
    )
    values, body = transition_module._parse_document(
        path.read_text(encoding="utf-8")
    )
    entry = values["action_state_history"][-1]
    assert entry["from"] == entry["to"] == "done"
    assert "completed_at" in entry["support_fields"]
    values["completed_at"] = "1900-01-01"
    entry["governed_support_sha256"] = transition_module._governed_support_sha256(
        values
    )
    entry["receipt_id"] = transition_module._receipt_id(entry)
    forged = transition_module._render_document(values, body)

    diagnostics = action_transition_diagnostics(previous, forged)
    assert [item.code for item in diagnostics] == [
        "action_terminal_timestamp_mismatch"
    ]
