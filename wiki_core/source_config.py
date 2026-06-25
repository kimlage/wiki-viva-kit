from __future__ import annotations

from pathlib import Path
from typing import Any

from wiki_core.config import WikiConfig
from wiki_core.frontmatter import list_values as _list_values
from wiki_core.frontmatter import parse_frontmatter_flat as parse_frontmatter
from wiki_core.paths import WikiPaths


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _repo_path(root: Path, source: str) -> Path | None:
    path = Path(source)
    if not path.is_absolute():
        path = root / source
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    return path


def _read_config_page(path: Path, paths: WikiPaths) -> dict[str, Any] | None:
    if not path.exists():
        return None
    values = parse_frontmatter(path)
    if values.get("page_type") != "source_config":
        return None
    return {
        "path": paths.rel(path),
        "page_id": str(values.get("page_id") or ""),
        "perspectives_required": _list_values(values.get("perspectives_required")),
        "perspectives_optional": _list_values(values.get("perspectives_optional")),
        "perspectives_skip_with_reason": _list_values(values.get("perspectives_skip_with_reason")),
        "input_channel_ref": str(values.get("input_channel_ref") or "").strip(),
        "process_refs": _list_values(values.get("process_refs")),
        "target_pages": _list_values(values.get("target_pages")),
        "quadrants": _list_values(values.get("quadrants")),
    }


def find_source_config(root: Path, config: WikiConfig, source: str) -> dict[str, Any] | None:
    """Return the source_config page that governs a repo-local source page.

    The preferred link is `config_ref` on the source page. The fallback scans
    `sources/config/*.md` for a matching `source_refs` entry. Raw files and URLs
    have no source page identity, so they return None.
    """

    paths = WikiPaths(root, config)
    source_path = _repo_path(root, source)
    if source_path is None or not source_path.exists() or source_path.suffix.lower() != ".md":
        return None

    values = parse_frontmatter(source_path)
    source_keys = {key for key in (str(values.get("page_id") or ""), paths.rel(source_path)) if key}

    config_ref = str(values.get("config_ref") or "").strip()
    if config_ref:
        config_path = _repo_path(root, config_ref)
        if config_path is not None:
            direct = _read_config_page(config_path, paths)
            if direct is not None:
                return direct

    config_dir = paths.sources_dir / "config"
    if not config_dir.exists():
        return None
    for path in sorted(config_dir.rglob("*.md")):
        values = parse_frontmatter(path)
        if values.get("page_type") != "source_config":
            continue
        if source_keys & set(_list_values(values.get("source_refs"))):
            return _read_config_page(path, paths)
    return None


def merge_perspectives(
    source_config: dict[str, Any] | None,
    *,
    required: list[str],
    optional: list[str],
    root_required: list[str] | None = None,
    root_optional: list[str] | None = None,
    channel_required: list[str] | None = None,
    channel_optional: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    root_required = root_required or []
    root_optional = root_optional or []
    channel_required = channel_required or []
    channel_optional = channel_optional or []
    skipped = set(source_config.get("perspectives_skip_with_reason") or []) if source_config else set()
    merged_required = _dedupe(
        [
            item
            for item in (
                list(root_required)
                + list(channel_required)
                + list(source_config.get("perspectives_required") or [] if source_config else [])
                + list(required)
            )
            if item not in skipped
        ]
    )
    merged_optional = _dedupe(
        [
            value
            for value in (
                list(root_optional)
                + list(channel_optional)
                + list(source_config.get("perspectives_optional") or [] if source_config else [])
                + list(optional)
            )
            if value not in set(merged_required) and value not in skipped
        ]
    )
    return merged_required, merged_optional
