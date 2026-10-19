"""Typed page creation shared by the CLI and local operator.

There is only one creation writer: a contained, validated, no-clobber link.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from wiki_core.config import load_config
from wiki_core.frontmatter import parse_frontmatter, parse_frontmatter_flat_with_errors
from wiki_core.page_types import load_page_type_registry, validate_shape
from wiki_core.templates import default_output_path, instantiate_template, resolve_template


def _safe_output_path(root: Path, memory_root: str, output: str) -> tuple[str, Path]:
    text = str(output or "")
    pure = PurePosixPath(text)
    if (
        not text
        or "\\" in text
        or "\x00" in text
        or any(ord(character) < 32 for character in text)
        or pure.is_absolute()
        or pure.suffix != ".md"
        or any(part in {"", ".", ".."} for part in pure.parts)
        or pure.as_posix() != text
    ):
        raise ValueError("output must be one canonical repo-relative Markdown path")
    memory = PurePosixPath(str(memory_root or ""))
    if (
        not memory.parts
        or memory.is_absolute()
        or any(part in {"", ".", ".."} for part in memory.parts)
    ):
        raise ValueError("configured memory_root is unsafe")
    root_resolved = root.resolve()
    memory_path = root_resolved / memory
    candidate = root_resolved / pure
    current = root_resolved
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("output path contains a symlink")
    try:
        candidate.resolve(strict=False).relative_to(memory_path.resolve(strict=False))
    except ValueError as exc:
        raise ValueError("output must stay inside the configured memory_root") from exc
    return pure.as_posix(), candidate


def _render_errors(
    root: Path,
    output: str,
    text: str,
    shape: dict[str, Any],
    *,
    page_type: str,
    title: str,
    context: str,
) -> list[str]:
    flat, structural = parse_frontmatter_flat_with_errors(
        text,
        required_keys=tuple(shape.get("required_frontmatter") or ()),
    )
    structured, _body = parse_frontmatter(text)
    errors = [f"{output}: {error}" for error in structural]
    shape_values = dict(flat)
    object_fields = [
        str(field)
        for field, expected in (shape.get("field_types") or {}).items()
        if str(expected) == "object"
    ]
    structured_fields = [*object_fields, "action_state_history", "action_dialogue"] if page_type == "action" else object_fields
    for field in structured_fields:
        if field in structured:
            shape_values[field] = structured[field]
    for error in validate_shape(root, output, shape_values, text, shape):
        missing_present_field = next(
            (
                field
                for field in shape.get("required_frontmatter") or []
                if f"missing required shape field `{field}`" in error and field in flat
            ),
            None,
        )
        if missing_present_field is None:
            errors.append(error)
    for field, expected in (
        ("page_type", page_type),
        ("title", title),
        ("context", context),
    ):
        actual = flat.get(field)
        if (str(actual) if actual is not None else "") != expected:
            errors.append(f"{output}: rendered `{field}` does not match the request")
    return errors


def _atomic_create(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=".wiki-new-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            os.fchmod(handle.fileno(), 0o644)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path, follow_symlinks=False)
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_fd = os.open(path.parent, directory_flags)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)



def prepare_page(root: Path, page_type: str, title: str, context: str | None = None,
                 output: str | None = None) -> tuple[str, str]:
    config = load_config(root)
    registry = load_page_type_registry(root)
    if registry is None:
        raise ValueError("wiki.page-types.yaml not found")
    resolved = resolve_template(root, config, registry, page_type)
    context = context or config.default_context
    text = instantiate_template(resolved, title=title, context=context, config=config)
    if page_type == "action":
        from datetime import date
        from wiki_core.action_transition import _parse_document, _render_document
        fm, body = _parse_document(text)
        if fm.get("created_at") == "YYYY-MM-DD":
            fm["created_at"] = date.today().isoformat()
        if fm.get("due_at") == "YYYY-MM-DD":
            fm.pop("due_at")
        if fm.get("owner_kind") == "unassigned" and not fm.get("owner_ref"):
            fm.pop("owner_ref", None)
        text = _render_document(fm, body)
    output, _ = _safe_output_path(root, str(config.paths["memory_root"]),
                                output or default_output_path(registry, page_type, title))
    errors = _render_errors(root, output, text, registry.page_types[page_type],
                           page_type=page_type, title=title, context=context)
    if errors:
        raise ValueError("; ".join(errors))
    return output, text


def create_page(root: Path, output: str, text: str) -> None:
    config = load_config(root)
    _, path = _safe_output_path(root, str(config.paths["memory_root"]), output)
    path.parent.mkdir(parents=True, exist_ok=True)
    _, path = _safe_output_path(root, str(config.paths["memory_root"]), output)
    _atomic_create(path, text)


def create_action_page(root: Path, *, title: str, context: str,
                       next_action: str, body: str = "", owner_kind: str = "unassigned",
                       owner_ref: str = "") -> dict[str, Any]:
    """Create exactly one action, without a second task store or execution."""
    from wiki_core.action_transition import (
        ActionTransitionError, _assert_no_secrets, _parse_document, _render_document,
        _sha256_text, validate_page_edit,
    )
    config = load_config(root)
    edit = validate_page_edit(dict(title=title, body=body,
                                  owner_kind=owner_kind, owner_ref=owner_ref))
    if not isinstance(context, str) or context not in {config.default_context, *config.contexts}:
        raise ActionTransitionError("invalid_context")
    if not isinstance(next_action, str) or not next_action.strip() or len(next_action) > 2000:
        raise ActionTransitionError("invalid_next_action")
    output, text = prepare_page(root, "action", edit["title"], context)
    fm, _ = _parse_document(text)
    if fm.get("action_state") != "open" or fm.get("action_state_history") not in (None, []) or fm.get("action_dialogue") not in (None, []):
        raise ActionTransitionError("invalid_action_template")
    fm.update({key: value for key, value in edit.items() if key != "body"})
    if fm.get("owner_kind") == "unassigned":
        fm.pop("owner_ref", None)
    fm["next_action"] = next_action.strip()
    fm["attention_basis"] = "Created in the wiki board."
    # A new task starts open and unexecuted. Template provenance/relations stay.
    text = _render_document(fm, edit["body"])
    registry = load_page_type_registry(root)
    errors = _render_errors(root, output, text, registry.page_types["action"],
                           page_type="action", title=edit["title"], context=context)
    if errors:
        raise ActionTransitionError("invalid_action_template")
    _assert_no_secrets(text)
    try:
        create_page(root, output, text)
    except FileExistsError as exc:
        raise ActionTransitionError("action_already_exists") from exc
    return {"ok": True, "page_id": fm["page_id"], "page_ref": output,
            "after_sha256": _sha256_text(text), "created": True}
