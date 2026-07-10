from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

PAGE_TYPES_SCHEMA_VERSION = "wiki_page_types.v1"


@dataclass(frozen=True)
class PageTypeRegistry:
    path: Path
    schema_version: str
    page_types: dict[str, dict[str, Any]]


def load_page_type_registry(root: Path, path: str = "wiki.page-types.yaml") -> PageTypeRegistry | None:
    registry_path = root / path
    if not registry_path.exists():
        return None
    data = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    page_types = data.get("page_types") or {}
    if not isinstance(page_types, dict):
        page_types = {}
    return PageTypeRegistry(
        path=registry_path,
        schema_version=str(data.get("schema_version") or ""),
        page_types={str(k): v for k, v in page_types.items() if isinstance(v, dict)},
    )


def list_values(value: Any) -> list[str]:
    """Shape-validator normalization (intentionally NON-stripping).

    This is the one ``list_values`` that does NOT delegate to the canonical
    :func:`wiki_core.frontmatter.list_values`. The shape gate validates raw
    frontmatter values verbatim (``field_type_error`` checks dates/enums against
    the exact text), so stripping here could silently change a gate verdict. It
    keeps items as-is, filtering only on truthiness after ``str(item)``, and does
    not strip the single-string case. See ``wiki_core.frontmatter`` for the
    differences this helper preserves.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, tuple):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str):
        if value.strip() == "[]":
            return []
        return [value]
    return [str(value)]


def markdown_headings(text: str) -> set[str]:
    headings: set[str] = set()
    for line in text.splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
        if match:
            headings.add(match.group(1).strip())
    return headings


def field_type_error(field: str, expected: str, value: Any) -> str | None:
    values = list_values(value)
    if expected == "string":
        if not isinstance(value, str) or not value.strip():
            return f"{field} must be a non-empty string"
    elif expected == "date":
        if not values or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", values[0]):
            return f"{field} must be an ISO date"
    elif expected == "list":
        if not isinstance(value, list):
            return f"{field} must be a list"
    elif expected == "object":
        if not isinstance(value, dict):
            return f"{field} must be an object"
    elif expected == "bool":
        if str(value).lower() not in {"true", "false", "yes", "no", "on", "off", "1", "0"}:
            return f"{field} must be boolean-like"
    elif expected.startswith("enum:"):
        allowed = {item.strip() for item in expected.split(":", 1)[1].split(",") if item.strip()}
        if not values or any(item not in allowed for item in values):
            return f"{field} must be one of {', '.join(sorted(allowed))}"
    return None


def template_coverage_error(root: Path, page_type: str, shape: dict[str, Any]) -> str | None:
    template = shape.get("template")
    if template == "none":
        if not str(shape.get("template_none_reason") or "").strip():
            return f"page_type `{page_type}` has template: none without template_none_reason"
        return None
    if not template:
        return f"page_type `{page_type}` has no template"
    if not (root / str(template)).exists():
        return f"page_type `{page_type}` template does not exist: {template}"
    return None


def validate_shape(
    root: Path,
    rel: str,
    values: dict[str, Any],
    text: str,
    shape: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    for field in shape.get("required_frontmatter") or []:
        if field not in values or values[field] in ("", [], None):
            errors.append(f"{rel}: missing required shape field `{field}`")
    for field, expected in (shape.get("field_types") or {}).items():
        if field in values:
            error = field_type_error(str(field), str(expected), values[field])
            if error:
                errors.append(f"{rel}: {error}")
    if str(values.get("page_type") or "") == "action":
        action_state = str(values.get("action_state") or "").strip()
        if action_state == "blocked" and not str(
            values.get("blocker_reason") or ""
        ).strip():
            errors.append(f"{rel}: blocked action requires `blocker_reason`")
        if action_state == "done" and not str(
            values.get("completion_receipt") or ""
        ).strip():
            errors.append(f"{rel}: done action requires `completion_receipt`")
        if action_state == "cancelled" and not str(
            values.get("cancellation_receipt") or ""
        ).strip():
            errors.append(f"{rel}: cancelled action requires `cancellation_receipt`")
    allowed_dirs = [str(item).rstrip("/") for item in (shape.get("allowed_dirs") or [])]
    if allowed_dirs and not any(rel.startswith(prefix + "/") or rel == prefix for prefix in allowed_dirs):
        errors.append(f"{rel}: page_type `{values.get('page_type')}` not allowed in this directory")
    headings = markdown_headings(text)
    for section in shape.get("required_sections") or []:
        if str(section) not in headings:
            errors.append(f"{rel}: missing required section `{section}`")
    return errors
