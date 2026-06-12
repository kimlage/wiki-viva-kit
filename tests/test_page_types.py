from __future__ import annotations

from pathlib import Path

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
