from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from wiki_core.action_transition import transition_action_page
from wiki_core.frontmatter import parse_frontmatter
from wiki_core.page_types import (
    PAGE_TYPES_SCHEMA_VERSION,
    load_page_type_registry,
    template_coverage_error,
    validate_shape,
)


def test_load_page_type_registry(tmp_path: Path) -> None:
    (tmp_path / "wiki.page-types.yaml").write_text(
        "schema_version: wiki_page_types.v1\n"
        "page_types:\n"
        "  claim:\n"
        "    template: none\n"
        "    template_none_reason: test\n",
        encoding="utf-8",
    )
    registry = load_page_type_registry(tmp_path)
    assert registry is not None
    assert registry.schema_version == PAGE_TYPES_SCHEMA_VERSION
    assert "claim" in registry.page_types


def test_repo_registry_has_critical_content_shapes() -> None:
    registry = load_page_type_registry(Path(__file__).resolve().parents[1])
    assert registry is not None
    for page_type in (
        "action",
        "artifact",
        "claim",
        "context_note",
        "decision",
        "holon",
        "input_channel",
        "meeting",
        "person",
        "process",
        "project",
        "responsibility",
        "role",
        "root_entity",
        "source",
        "source_config",
    ):
        shape = registry.page_types[page_type]
        assert shape.get("required_frontmatter")
        assert shape.get("field_types")
        assert shape.get("template")


def test_repo_registry_declares_action_exactly_once() -> None:
    document = yaml.compose(
        (Path(__file__).resolve().parents[1] / "wiki.page-types.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert isinstance(document, yaml.MappingNode)
    page_types = next(
        value
        for key, value in document.value
        if isinstance(key, yaml.ScalarNode) and key.value == "page_types"
    )
    assert isinstance(page_types, yaml.MappingNode)
    assert [
        key.value
        for key, _value in page_types.value
        if isinstance(key, yaml.ScalarNode) and key.value == "action"
    ] == ["action"]


def test_relation_page_types_require_hierarchy_parent() -> None:
    registry = load_page_type_registry(Path(__file__).resolve().parents[1])
    assert registry is not None
    for page_type in (
        "action",
        "artifact",
        "claim",
        "decision",
        "holon",
        "input_channel",
        "meeting",
        "person",
        "process",
        "project",
        "responsibility",
        "role",
        "source",
        "source_config",
    ):
        shape = registry.page_types[page_type]
        assert "moc_parent" in shape.get("required_frontmatter", [])
        assert shape.get("field_types", {}).get("moc_parent") == "string"
    # The ROOT is the top of the world: everything descends from it (anchor
    # scopes), it descends from nothing — moc_parent is optional there.
    root_shape = registry.page_types["root_entity"]
    assert "moc_parent" not in root_shape.get("required_frontmatter", [])
    assert root_shape.get("field_types", {}).get("moc_parent") == "string"


def test_action_shape_exposes_the_runtime_work_contract() -> None:
    registry = load_page_type_registry(Path(__file__).resolve().parents[1])
    assert registry is not None
    action = registry.page_types["action"]
    fields = action["field_types"]
    assert {
        "action_state": "enum:open,in_progress,blocked,waiting_human,done,cancelled",
        "owner_kind": "enum:human,agent,system,other,unassigned",
        "owner_ref": "string",
        "created_at": "date",
        "due_at": "date",
        "completed_at": "date_or_instant",
        "blocked_by": "list",
        "blocker_reason": "string",
        "next_action": "string",
        "priority": "string",
        "attention_basis": "string",
        "completion_receipt": "string",
        "cancellation_receipt": "string",
    }.items() <= fields.items()
    assert {
        "action_state",
        "owner_kind",
        "created_at",
        "priority",
        "attention_basis",
    } <= set(action["required_frontmatter"])
    assert "next_action" not in action["required_frontmatter"]


def test_action_template_uses_a_runtime_valid_owner_kind() -> None:
    template = (
        Path(__file__).resolve().parents[1]
        / "docs/references/templates/wiki/action.md"
    ).read_text(encoding="utf-8")
    assert "owner_kind: unassigned" in template
    assert "owner_kind: page" not in template


def test_source_shape_and_template_expose_optional_lifecycle_authoring_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    registry = load_page_type_registry(root)
    assert registry is not None
    fields = registry.page_types["source"]["field_types"]
    assert fields["source_lifecycle"] == "object"
    assert fields["source_last_attempt_state"] == "string"
    assert fields["source_pipeline_stage"] == "string"
    required = set(registry.page_types["source"]["required_frontmatter"])
    assert "source_lifecycle" not in required
    assert "source_last_attempt_state" not in required
    assert "source_pipeline_stage" not in required

    template = (root / "docs/references/templates/wiki/source.md").read_text(
        encoding="utf-8"
    )
    assert "source_lifecycle:" in template
    assert "last_attempt_state: never" in template
    assert "pipeline_stage: configured" in template


def test_action_shape_enforces_blocker_and_terminal_receipts() -> None:
    registry = load_page_type_registry(Path(__file__).resolve().parents[1])
    assert registry is not None
    shape = registry.page_types["action"]
    base = {
        "page_id": "action-x",
        "page_type": "action",
        "context": "system",
        "visibility": "private_self",
        "updated_at": "2026-07-10",
        "stale_after_days": "30",
        "source_refs": ["source-x"],
        "moc_parent": "memories/index.md",
        "owner_kind": "human",
        "created_at": "2026-07-10",
        "next_action": "Review the evidence.",
        "priority": "normal",
        "attention_basis": "A review is due.",
    }

    blocked = validate_shape(
        Path.cwd(),
        "memories/actions/action-x.md",
        {**base, "action_state": "blocked"},
        "# Action\n",
        shape,
    )
    assert any("blocked action requires `blocker_reason`" in error for error in blocked)

    done = validate_shape(
        Path.cwd(),
        "memories/actions/action-x.md",
        {**base, "action_state": "done"},
        "# Action\n",
        shape,
    )
    assert any("done action requires `completion_receipt`" in error for error in done)

    cancelled = validate_shape(
        Path.cwd(),
        "memories/actions/action-x.md",
        {**base, "action_state": "cancelled"},
        "# Action\n",
        shape,
    )
    assert any(
        "cancelled action requires `cancellation_receipt`" in error
        for error in cancelled
    )


def test_action_shape_requires_next_action_only_while_non_terminal() -> None:
    registry = load_page_type_registry(Path(__file__).resolve().parents[1])
    assert registry is not None
    shape = registry.page_types["action"]
    base = {
        "page_id": "action-x",
        "page_type": "action",
        "context": "system",
        "visibility": "private_self",
        "updated_at": "2026-07-10",
        "stale_after_days": "30",
        "source_refs": ["source-x"],
        "moc_parent": "memories/index.md",
        "owner_kind": "human",
        "created_at": "2026-07-10",
        "priority": "normal",
        "attention_basis": "A review is due.",
    }

    open_errors = validate_shape(
        Path.cwd(),
        "memories/actions/action-x.md",
        {**base, "action_state": "open"},
        "# Action\n",
        shape,
    )
    assert any(
        "non-terminal action requires `next_action`" in error
        for error in open_errors
    )

    done_errors = validate_shape(
        Path.cwd(),
        "memories/actions/action-x.md",
        {
            **base,
            "action_state": "done",
            "completed_at": "2026-07-11T14:30:00Z",
            "completion_receipt": "commit:abc123",
        },
        "# Action\n",
        shape,
    )
    assert not any("next_action" in error for error in done_errors)

    cancelled_errors = validate_shape(
        Path.cwd(),
        "memories/actions/action-x.md",
        {
            **base,
            "action_state": "cancelled",
            "completed_at": "2026-07-11T14:30:00-03:00",
            "cancellation_receipt": "decision:obsolete",
        },
        "# Action\n",
        shape,
    )
    assert not any("next_action" in error for error in cancelled_errors)


@pytest.mark.parametrize("terminal", ["done", "cancelled"])
def test_action_shape_rejects_stale_actionable_fields_on_terminal_state(
    terminal: str,
) -> None:
    registry = load_page_type_registry(Path(__file__).resolve().parents[1])
    assert registry is not None
    shape = registry.page_types["action"]
    values = {
        "page_id": "action-terminal",
        "page_type": "action",
        "context": "system",
        "visibility": "private_self",
        "updated_at": "2026-07-10",
        "stale_after_days": "30",
        "source_refs": ["source-synthetic"],
        "moc_parent": "memories/index.md",
        "owner_kind": "human",
        "created_at": "2026-07-10",
        "action_state": terminal,
        "completed_at": "2026-07-11T14:30:00Z",
        "next_action": "This must not remain actionable.",
        "blocked_by": ["source-stale"],
        "blocker_reason": "This blocker is stale.",
        "completion_receipt": "commit:done",
        "cancellation_receipt": "decision:cancelled",
        "priority": "normal",
        "attention_basis": "Synthetic contract test.",
    }

    errors = validate_shape(
        Path.cwd(),
        "memories/actions/action-terminal.md",
        values,
        "# Action\n",
        shape,
    )

    assert any("terminal action forbids `next_action`" in error for error in errors)
    assert any("only blocked action may carry `blocked_by`" in error for error in errors)
    assert any(
        "only blocked action may carry `blocker_reason`" in error for error in errors
    )
    opposite = (
        "cancellation_receipt" if terminal == "done" else "completion_receipt"
    )
    opposite_state = "cancelled" if terminal == "done" else "done"
    assert any(
        f"only {opposite_state} action may carry `{opposite}`" in error
        for error in errors
    )


@pytest.mark.parametrize("state", ["open", "in_progress", "blocked", "waiting_human"])
def test_action_shape_rejects_terminal_facts_before_terminal_state(state: str) -> None:
    registry = load_page_type_registry(Path(__file__).resolve().parents[1])
    assert registry is not None
    shape = registry.page_types["action"]
    values = {
        "page_id": "action-active",
        "page_type": "action",
        "context": "system",
        "visibility": "private_self",
        "updated_at": "2026-07-10",
        "stale_after_days": "30",
        "source_refs": [],
        "moc_parent": "memories/index.md",
        "owner_kind": "human",
        "created_at": "2026-07-10",
        "action_state": state,
        "next_action": "Continue safely.",
        "completed_at": "2026-07-11T14:30:00Z",
        "completion_receipt": "commit:premature",
        "cancellation_receipt": "decision:premature",
        "priority": "normal",
        "attention_basis": "Synthetic contract test.",
    }
    if state == "blocked":
        values["blocker_reason"] = "Synthetic blocker."

    errors = validate_shape(
        Path.cwd(),
        "memories/actions/action-active.md",
        values,
        "# Action\n",
        shape,
    )

    assert any("non-terminal action forbids `completed_at`" in error for error in errors)
    assert any("only done action may carry `completion_receipt`" in error for error in errors)
    assert any(
        "only cancelled action may carry `cancellation_receipt`" in error
        for error in errors
    )


def test_action_shape_rejects_fabricated_or_impossible_transition_history() -> None:
    registry = load_page_type_registry(Path(__file__).resolve().parents[1])
    assert registry is not None
    shape = registry.page_types["action"]
    values = {
        "page_id": "action-fabricated-history",
        "page_type": "action",
        "context": "system",
        "visibility": "private_self",
        "updated_at": "2026-07-11",
        "stale_after_days": "30",
        "source_refs": [],
        "moc_parent": "memories/index.md",
        "owner_kind": "human",
        "created_at": "2026-07-10",
        "action_state": "open",
        "action_state_history": [
            {
                "schema_version": "wiki_action_transition_receipt.v2",
                "kind": "transition",
                "page_id": "action-fabricated-history",
                "from": "done",
                "to": "open",
                "at": "2026-07-11T14:30:00Z",
                "receipt_id": "sha256:" + "a" * 64,
                "prior_receipt_id": "",
                "support_fields": [],
            }
        ],
        "next_action": "Continue safely.",
        "priority": "normal",
        "attention_basis": "Synthetic contract test.",
    }

    errors = validate_shape(
        Path.cwd(),
        "memories/actions/action-fabricated-history.md",
        values,
        "# Action\n",
        shape,
    )

    assert any("contains an invalid canonical transition" in error for error in errors)
    assert any("receipt_id does not bind its payload" in error for error in errors)


def test_action_shape_accepts_full_v2_history_emitted_by_canonical_writer(
    tmp_path: Path,
) -> None:
    registry = load_page_type_registry(Path(__file__).resolve().parents[1])
    assert registry is not None
    shape = registry.page_types["action"]
    rel = "memories/actions/action-writer-v2.md"
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    values = {
        "page_id": "action-writer-v2",
        "page_type": "action",
        "context": "system",
        "visibility": "private_self",
        "updated_at": "2026-07-10",
        "stale_after_days": "30",
        "source_refs": ["source-synthetic"],
        "moc_parent": "memories/index.md",
        "owner_kind": "human",
        "created_at": "2026-07-10",
        "action_state": "open",
        "action_state_history": [],
        "next_action": "Continue safely.",
        "priority": "normal",
        "attention_basis": "Synthetic contract test.",
    }
    path.write_text(
        "---\n"
        + yaml.safe_dump(values, sort_keys=False, allow_unicode=True)
        + "---\n\n# Action\n",
        encoding="utf-8",
    )
    transition_action_page(
        tmp_path,
        rel,
        "in_progress",
        recorded_at="2026-07-11T14:30:00.000001Z",
    )
    written, _body = parse_frontmatter(path)

    errors = validate_shape(tmp_path, rel, written, path.read_text(), shape)

    assert not any("action_state_history" in error for error in errors)
    assert errors == []


def test_every_collection_capable_anchor_accepts_the_collection_contract() -> None:
    registry = load_page_type_registry(Path(__file__).resolve().parents[1])
    assert registry is not None
    for page_type in (
        "context_hub",
        "holon",
        "ontology_index",
        "project",
        "root_entity",
        "source",
        "source_registry",
        "template_block",
    ):
        assert registry.page_types[page_type]["field_types"]["collection"] == "object"


def test_template_coverage_requires_reason_for_none(tmp_path: Path) -> None:
    assert template_coverage_error(tmp_path, "x", {"template": "none"}) is not None
    assert template_coverage_error(
        tmp_path,
        "x",
        {"template": "none", "template_none_reason": "generated"},
    ) is None


def test_validate_shape_checks_fields_types_dirs_and_sections(tmp_path: Path) -> None:
    shape = {
        "allowed_dirs": ["memories/claims"],
        "required_frontmatter": ["page_id", "updated_at", "source_refs"],
        "field_types": {"updated_at": "date", "source_refs": "list"},
        "required_sections": ["Statement"],
    }
    values = {
        "page_id": "claim-x",
        "page_type": "claim",
        "updated_at": "2026-06-11",
        "source_refs": ["source-x"],
    }
    errors = validate_shape(
        tmp_path,
        "memories/claims/x.md",
        values,
        "# Claim\n\n## Statement\n\nBody.\n",
        shape,
    )
    assert errors == []

    bad = validate_shape(
        tmp_path,
        "memories/projects/x.md",
        {"page_id": "x", "updated_at": "June 11", "source_refs": "source-x"},
        "# Claim\n\nNo section.\n",
        shape,
    )
    assert any("not allowed" in error for error in bad)
    assert any("updated_at must be an ISO date" in error for error in bad)
    assert any("source_refs must be a list" in error for error in bad)
    assert any("missing required section" in error for error in bad)
