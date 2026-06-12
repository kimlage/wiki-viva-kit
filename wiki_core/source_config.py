from __future__ import annotations

from pathlib import Path
from typing import Any

from wiki_core.config import WikiConfig
from wiki_core.graph.page_graph import parse_frontmatter
from wiki_core.paths import WikiPaths


def _list_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        if not value.strip() or value.strip() == "[]":
            return []
        return [value.strip()]
    return [str(value).strip()]


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
) -> tuple[list[str], list[str]]:
    if not source_config:
        return _dedupe(required), _dedupe(optional)
    merged_required = _dedupe(
        list(source_config.get("perspectives_required") or []) + list(required)
    )
    merged_optional = _dedupe(
        [
            value
            for value in list(source_config.get("perspectives_optional") or []) + list(optional)
            if value not in set(merged_required)
        ]
    )
    return merged_required, merged_optional
