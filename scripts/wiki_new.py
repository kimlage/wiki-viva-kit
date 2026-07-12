#!/usr/bin/env python3
"""Create a new typed wiki page from the page-type registry template."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

try:  # importing _common bootstraps sys.path so wiki_core resolves
    from scripts._common import ROOT  # package/spec-loader import
except ModuleNotFoundError:
    from _common import ROOT  # direct run: scripts/ on sys.path

from wiki_core.config import load_config
from wiki_core.experience_packs import PackError
from wiki_core.frontmatter import parse_frontmatter, parse_frontmatter_flat_with_errors
from wiki_core.page_types import load_page_type_registry, validate_shape
from wiki_core.templates import (
    default_output_path,
    instantiate_template,
    resolve_template,
)


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
    for field in object_fields:
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--type", required=True, dest="page_type")
    parser.add_argument("--title", required=True)
    parser.add_argument("--context")
    parser.add_argument(
        "--output",
        help="repo-relative destination; defaults to first allowed_dir/<slug>.md",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print the page without writing"
    )
    args = parser.parse_args()

    try:
        config = load_config(ROOT)
        registry = load_page_type_registry(ROOT)
        if registry is None:
            raise ValueError("wiki.page-types.yaml not found")
        resolved = resolve_template(ROOT, config, registry, args.page_type)
        context = args.context or config.default_context
        text = instantiate_template(
            resolved,
            title=args.title,
            context=context,
            config=config,
        )
        requested_output = args.output or default_output_path(
            registry, args.page_type, args.title
        )
        output, out = _safe_output_path(
            ROOT,
            str(config.paths["memory_root"]),
            requested_output,
        )
        shape = registry.page_types[args.page_type]
        errors = _render_errors(
            ROOT,
            output,
            text,
            shape,
            page_type=args.page_type,
            title=args.title,
            context=context,
        )
        if errors:
            raise ValueError("; ".join(errors))
    except (FileNotFoundError, OSError, PackError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(text)
        return 0

    try:
        # Parent creation is followed by a second containment/symlink check so a
        # pre-existing alias cannot become the publication directory.
        out.parent.mkdir(parents=True, exist_ok=True)
        output, out = _safe_output_path(
            ROOT,
            str(config.paths["memory_root"]),
            output,
        )
        _atomic_create(out, text)
    except FileExistsError:
        print(f"ERROR: destination exists: {output}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"ERROR: could not safely create destination: {exc}", file=sys.stderr)
        return 2
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
