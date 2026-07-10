from __future__ import annotations

from pathlib import Path

import yaml

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
    fields = registry.page_types["action"]["field_types"]
    assert {
        "action_state": "string",
        "owner_kind": "string",
        "owner_ref": "string",
        "created_at": "date",
        "due_at": "date",
        "completed_at": "date",
        "blocked_by": "list",
        "blocker_reason": "string",
        "next_action": "string",
        "priority": "string",
        "attention_basis": "string",
        "completion_receipt": "string",
        "cancellation_receipt": "string",
    }.items() <= fields.items()


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
