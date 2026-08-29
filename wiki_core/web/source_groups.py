"""Versioned, portable organization for the source registry.

Source groups are deliberately separate from input channels: channels describe
how evidence enters the semantic wiki, while groups describe where an operator
expects to find a source (local folder, remote folder, cloud account, web, and
so on).  The browser submits the complete ordered grouping, previews a
content-bound write, and must return the exact token before the canonical YAML
file is changed.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from wiki_core.config import WikiConfig
from wiki_core.paths import WikiPaths

SOURCE_GROUPS_SCHEMA_VERSION = "wiki_source_groups.v1"
SOURCE_GROUPS_PATH = "wiki.source-groups.yaml"
SOURCE_GROUP_ICONS = {"folder", "folder-remote", "cloud", "web", "repository", "inbox"}
_SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _group_for_source(source: dict[str, Any]) -> str:
    platform = str(source.get("platform") or "").lower()
    source_kind = str(source.get("source_kind") or "").lower()
    if platform in {"file", "manual"}:
        return "local"
    if platform == "drive" and source_kind == "collection":
        return "remote-folders"
    if platform == "repo" or source_kind == "repository":
        return "repositories"
    if platform == "web" and source_kind in {"endpoint", "item"}:
        return "web"
    if platform in {"gmail", "gchat", "chatgpt", "whatsapp"} or source_kind == "account":
        return "cloud"
    return "uncategorized"


def _default_groups(sources: list[dict[str, Any]], language: str) -> list[dict[str, Any]]:
    labels = {
        "en": ("Local folders", "Remote folders", "Cloud and accounts", "Web and feeds", "Repositories", "Uncategorized"),
        "es": ("Carpetas locales", "Carpetas remotas", "Nube y cuentas", "Web y canales", "Repositorios", "Sin categoría"),
        "pt": ("Pastas locais", "Pastas remotas", "Cloud e contas", "Web e feeds", "Repositórios", "Sem categoria"),
    }.get(language, ("Local folders", "Remote folders", "Cloud and accounts", "Web and feeds", "Repositories", "Uncategorized"))
    definitions = [
        ("local", labels[0], "folder"),
        ("remote-folders", labels[1], "folder-remote"),
        ("cloud", labels[2], "cloud"),
        ("web", labels[3], "web"),
        ("repositories", labels[4], "repository"),
        ("uncategorized", labels[5], "inbox"),
    ]
    buckets = {group_id: [] for group_id, _, _ in definitions}
    for source in sources:
        buckets[_group_for_source(source)].append(str(source.get("source_id") or ""))
    return [
        {"id": group_id, "label": label, "icon": icon, "source_ids": buckets[group_id]}
        for group_id, label, icon in definitions
        if buckets[group_id] or group_id != "uncategorized"
    ]


def _normalize_groups(groups: Any, source_ids: set[str]) -> list[dict[str, Any]]:
    if not isinstance(groups, list) or not groups or len(groups) > 64:
        raise ValueError("source_groups_invalid_groups")
    normalized: list[dict[str, Any]] = []
    seen_groups: set[str] = set()
    seen_sources: set[str] = set()
    for raw in groups:
        if not isinstance(raw, dict):
            raise ValueError("source_groups_invalid_group")
        group_id = str(raw.get("id") or "").strip().lower()
        label = str(raw.get("label") or "").strip()
        icon = str(raw.get("icon") or "folder").strip().lower()
        raw_source_ids = raw.get("source_ids")
        if (
            not _SLUG_RE.fullmatch(group_id)
            or group_id in seen_groups
            or not label
            or len(label) > 80
            or any(ord(char) < 32 for char in label)
            or icon not in SOURCE_GROUP_ICONS
            or not isinstance(raw_source_ids, list)
        ):
            raise ValueError("source_groups_invalid_group")
        members: list[str] = []
        for raw_source_id in raw_source_ids:
            source_id = str(raw_source_id).strip()
            if source_id not in source_ids:
                raise ValueError("source_groups_unknown_source")
            if source_id in seen_sources:
                raise ValueError("source_groups_duplicate_source")
            seen_sources.add(source_id)
            members.append(source_id)
        seen_groups.add(group_id)
        normalized.append({"id": group_id, "label": label, "icon": icon, "source_ids": members})
    missing = sorted(source_ids - seen_sources)
    if missing:
        raise ValueError("source_groups_unassigned_source")
    return normalized


def _read_configured_groups(path: Path) -> list[dict[str, Any]] | None:
    if not path.is_file():
        return None
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(raw, dict) or raw.get("schema_version") != SOURCE_GROUPS_SCHEMA_VERSION:
        return None
    groups = raw.get("groups")
    return groups if isinstance(groups, list) else None


def build_source_groups_payload(
    root: Path,
    config: WikiConfig,
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return a complete grouping, deterministically placing newly added sources."""
    source_ids = {str(source.get("source_id") or "") for source in sources}
    path = root / SOURCE_GROUPS_PATH
    configured = _read_configured_groups(path)
    if configured is None:
        groups = _default_groups(sources, config.language)
        return {
            "schema_version": SOURCE_GROUPS_SCHEMA_VERSION,
            "config_path": SOURCE_GROUPS_PATH,
            "configured": False,
            "groups": groups,
        }

    # Be tolerant on reads after a source was added or removed. Existing order,
    # labels and assignments survive; only live source ids are projected.
    projected: list[dict[str, Any]] = []
    assigned: set[str] = set()
    known_group_ids: set[str] = set()
    for raw in configured:
        if not isinstance(raw, dict):
            continue
        group_id = str(raw.get("id") or "").strip().lower()
        label = str(raw.get("label") or "").strip()
        icon = str(raw.get("icon") or "folder").strip().lower()
        if not _SLUG_RE.fullmatch(group_id) or not label or icon not in SOURCE_GROUP_ICONS or group_id in known_group_ids:
            continue
        members = [str(item) for item in raw.get("source_ids") or [] if str(item) in source_ids and str(item) not in assigned]
        projected.append({"id": group_id, "label": label, "icon": icon, "source_ids": members})
        known_group_ids.add(group_id)
        assigned.update(members)

    by_id = {group["id"]: group for group in projected}
    for source in sources:
        source_id = str(source.get("source_id") or "")
        if source_id in assigned:
            continue
        preferred = _group_for_source(source)
        target = by_id.get(preferred)
        if target is None:
            target = by_id.get("uncategorized")
        if target is None:
            label = {"pt": "Sem categoria", "es": "Sin categoría"}.get(config.language, "Uncategorized")
            target = {"id": "uncategorized", "label": label, "icon": "inbox", "source_ids": []}
            projected.append(target)
            by_id[target["id"]] = target
        target["source_ids"].append(source_id)
        assigned.add(source_id)
    return {
        "schema_version": SOURCE_GROUPS_SCHEMA_VERSION,
        "config_path": SOURCE_GROUPS_PATH,
        "configured": True,
        "groups": projected,
    }


def preview_source_groups_operation(
    root: Path,
    config: WikiConfig,
    groups: Any,
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    normalized = _normalize_groups(groups, {str(source.get("source_id") or "") for source in sources})
    path = root / SOURCE_GROUPS_PATH
    current = path.read_text(encoding="utf-8") if path.is_file() else ""
    rendered = yaml.safe_dump(
        {"schema_version": SOURCE_GROUPS_SCHEMA_VERSION, "groups": normalized},
        sort_keys=False,
        allow_unicode=True,
    )
    if current == rendered:
        raise ValueError("source_groups_no_changes")
    material = {
        "schema_version": SOURCE_GROUPS_SCHEMA_VERSION,
        "config_sha256": _sha(current),
        "result_sha256": _sha(rendered),
        "groups": normalized,
    }
    token = _sha(json.dumps(material, sort_keys=True, ensure_ascii=False, separators=(",", ":")))
    return {
        "ok": True,
        "schema_version": SOURCE_GROUPS_SCHEMA_VERSION,
        "preview_token": token,
        "config_path": SOURCE_GROUPS_PATH,
        "config_sha256": material["config_sha256"],
        "result_sha256": material["result_sha256"],
        "configured": bool(current),
        "groups": normalized,
    }


def apply_source_groups_operation(
    root: Path,
    config: WikiConfig,
    groups: Any,
    sources: list[dict[str, Any]],
    preview_token: str,
) -> dict[str, Any]:
    preview = preview_source_groups_operation(root, config, groups, sources)
    if not preview_token or preview_token != preview["preview_token"]:
        raise ValueError("source_groups_preview_stale")
    path = root / SOURCE_GROUPS_PATH
    current = path.read_text(encoding="utf-8") if path.is_file() else ""
    if _sha(current) != preview["config_sha256"]:
        raise ValueError("source_groups_preview_stale")
    rendered = yaml.safe_dump(
        {"schema_version": SOURCE_GROUPS_SCHEMA_VERSION, "groups": preview["groups"]},
        sort_keys=False,
        allow_unicode=True,
    )
    if _sha(rendered) != preview["result_sha256"]:
        raise ValueError("source_groups_preview_stale")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)

    operation_id = "sgp-" + uuid.uuid4().hex[:12]
    receipt = {
        "schema_version": SOURCE_GROUPS_SCHEMA_VERSION,
        "operation_id": operation_id,
        "recorded_at": _now(),
        "status": "applied",
        "preview_token": preview_token,
        "config_path": SOURCE_GROUPS_PATH,
        "result_sha256": preview["result_sha256"],
    }
    receipt_dir = WikiPaths(root, config).derived_root / "source-operations"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipt_dir / f"{operation_id}.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "ok": True,
        **receipt,
        "receipt_path": str(receipt_path.relative_to(root)),
        "changed_files": [SOURCE_GROUPS_PATH],
        "groups": preview["groups"],
    }
