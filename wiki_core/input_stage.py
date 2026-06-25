"""Deterministic input-stage compiler for the integral root model.

The input stage does not fetch external systems. It reads the repo's declared
root entity, input-channel pages, source pages and source configs, then emits a
stable catalog the agent can use before ingestion.
"""

from __future__ import annotations

import datetime as dt
import json
import posixpath
from pathlib import Path
from typing import Any

from wiki_core.config import WikiConfig
from wiki_core.frontmatter import list_values, parse_frontmatter
from wiki_core.paths import WikiPaths
from wiki_core.source_config import find_source_config

INPUT_STAGE_SCHEMA_VERSION = "wiki_input_stage.v1"
SOURCE_PAGE_TYPES = {"source", "source_catalog", "artifact"}

DEFAULT_QUADRANT_MAP = {
    "q1": ["perspective-identity-intent"],
    "q2": ["perspective-artifacts-evidence"],
    "q3": ["perspective-roles-relationships"],
    "q4": ["perspective-systems-processes"],
}

SOURCE_STATUS_TO_INPUT_STATUS = {
    "ingested": "integrated",
    "partial": "ingesting",
    "stale": "configured",
    "unread": "configured",
}


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _repo_path(root: Path, value: str) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = root / value
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    return path


def _md_pages(paths: WikiPaths) -> list[Path]:
    if not paths.memory_root.exists():
        return []
    return sorted(paths.memory_root.rglob("*.md"))


def _read_page(root: Path, path: Path) -> dict[str, Any]:
    values, body = parse_frontmatter(path)
    title = str(values.get("title") or "").strip()
    if not title:
        for line in body.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
    return {
        "path": _rel(root, path),
        "page_id": str(values.get("page_id") or ""),
        "page_type": str(values.get("page_type") or ""),
        "title": title or path.stem,
        "context": str(values.get("context") or ""),
        "values": values,
    }


def _pages_by_type(root: Path, paths: WikiPaths, page_type: str) -> list[dict[str, Any]]:
    pages = []
    for path in _md_pages(paths):
        page = _read_page(root, path)
        if page["page_type"] == page_type:
            pages.append(page)
    return pages


def _source_pages(root: Path, paths: WikiPaths) -> list[dict[str, Any]]:
    if not paths.sources_dir.exists():
        return []
    pages = []
    for path in sorted(paths.sources_dir.rglob("*.md")):
        if path.name in {"index.md", "README.md"}:
            continue
        page = _read_page(root, path)
        if page["page_type"] in SOURCE_PAGE_TYPES:
            pages.append(page)
    return pages


def _configured_root_page(root: Path, config: WikiConfig) -> Path | None:
    page = str((config.root_entity or {}).get("page") or "").strip()
    return _repo_path(root, page) if page else None


def find_root_entity(root: Path, config: WikiConfig, paths: WikiPaths) -> dict[str, Any] | None:
    configured = _configured_root_page(root, config)
    if configured and configured.exists():
        page = _read_page(root, configured)
        if page["page_type"] == "root_entity":
            return _root_payload(page, config)

    candidates = _pages_by_type(root, paths, "root_entity")
    if candidates:
        return _root_payload(candidates[0], config)
    return None


def _bundle_from_config(config: WikiConfig) -> tuple[list[str], list[str]]:
    bundle = (config.root_entity or {}).get("perspective_bundle") or {}
    if not isinstance(bundle, dict):
        return [], []
    return list_values(bundle.get("required")), list_values(bundle.get("optional"))


def _root_payload(page: dict[str, Any], config: WikiConfig) -> dict[str, Any]:
    values = dict(page["values"])
    cfg_required, cfg_optional = _bundle_from_config(config)
    required = _dedupe(cfg_required + list_values(values.get("perspective_bundle_required")))
    optional = _dedupe(
        [
            item
            for item in cfg_optional + list_values(values.get("perspective_bundle_optional"))
            if item not in set(required)
        ]
    )
    return {
        "page_id": page["page_id"],
        "path": page["path"],
        "title": page["title"],
        "entity_type": str(
            (config.root_entity or {}).get("entity_type")
            or values.get("root_entity_type")
            or ""
        ),
        "primary_contexts": _dedupe(list_values(values.get("primary_contexts"))),
        "input_stage_ref": str(
            (config.root_entity or {}).get("input_stage_page")
            or values.get("input_stage_ref")
            or ""
        ),
        "perspective_bundle": {"required": required, "optional": optional},
    }


def _context_hub(root: Path, config: WikiConfig, context: str) -> str | None:
    if not context:
        return None
    path = root / config.paths["memory_root"] / context / "index.md"
    return _rel(root, path) if path.exists() else None


def _page_keys(page: dict[str, Any]) -> set[str]:
    return {key for key in (page.get("page_id"), page.get("path")) if key}


def _config_page_for_source(
    root: Path,
    config: WikiConfig,
    source_page: dict[str, Any],
) -> dict[str, Any] | None:
    found = find_source_config(root, config, str(source_page["path"]))
    if found is None:
        return None
    config_path = _repo_path(root, str(found.get("path") or ""))
    if config_path is None or not config_path.exists():
        return found
    page = _read_page(root, config_path)
    values = dict(page["values"])
    return {
        **found,
        "title": page["title"],
        "input_channel_ref": str(values.get("input_channel_ref") or ""),
        "process_refs": list_values(values.get("process_refs")),
        "target_pages": list_values(values.get("target_pages")),
        "quadrants": list_values(values.get("quadrants")),
        "perspectives_skip_with_reason": list_values(values.get("perspectives_skip_with_reason")),
    }


def _channel_payload(page: dict[str, Any]) -> dict[str, Any]:
    values = dict(page["values"])
    return {
        "page_id": page["page_id"],
        "path": page["path"],
        "title": page["title"],
        "context": page["context"],
        "channel_type": str(values.get("channel_type") or ""),
        "input_status": str(values.get("input_status") or "declared"),
        "quadrants": list_values(values.get("quadrants")),
        "perspectives_required": list_values(values.get("perspectives_required")),
        "perspectives_optional": list_values(values.get("perspectives_optional")),
        "source_refs": list_values(values.get("source_refs")),
        "source_config_refs": list_values(values.get("source_config_refs")),
        "process_refs": list_values(values.get("process_refs")),
        "target_pages": list_values(values.get("target_pages")),
        "privacy_boundary": str(values.get("privacy_boundary") or values.get("visibility") or ""),
        "refresh_policy": str(values.get("refresh_policy") or ""),
        "refresh_cadence_days": str(values.get("refresh_cadence_days") or ""),
    }


def _match_channel(
    source_page: dict[str, Any],
    source_config: dict[str, Any] | None,
    channels: list[dict[str, Any]],
) -> dict[str, Any] | None:
    source_keys = _page_keys(source_page)
    config_keys = {
        key
        for key in (
            (source_config or {}).get("page_id"),
            (source_config or {}).get("path"),
        )
        if key
    }
    explicit = str((source_config or {}).get("input_channel_ref") or "")
    for channel in channels:
        channel_keys = _page_keys(channel)
        if explicit and explicit in channel_keys:
            return channel
        if source_keys & set(channel.get("source_refs") or []):
            return channel
        if config_keys & set(channel.get("source_config_refs") or []):
            return channel
    return None


def _resolved_perspectives(
    root_entity: dict[str, Any] | None,
    channel: dict[str, Any] | None,
    source_config: dict[str, Any] | None,
) -> dict[str, list[str]]:
    root_required = list((root_entity or {}).get("perspective_bundle", {}).get("required") or [])
    root_optional = list((root_entity or {}).get("perspective_bundle", {}).get("optional") or [])
    channel_required = list((channel or {}).get("perspectives_required") or [])
    channel_optional = list((channel or {}).get("perspectives_optional") or [])
    config_required = list((source_config or {}).get("perspectives_required") or [])
    config_optional = list((source_config or {}).get("perspectives_optional") or [])
    skipped = set((source_config or {}).get("perspectives_skip_with_reason") or [])
    required = _dedupe(
        [item for item in root_required + channel_required + config_required if item not in skipped]
    )
    required_set = set(required)
    optional = _dedupe(
        [
            item
            for item in root_optional + channel_optional + config_optional
            if item not in required_set and item not in skipped
        ]
    )
    return {"required": required, "optional": optional, "skipped": sorted(skipped)}


def _source_input_status(source_page: dict[str, Any], source_config: dict[str, Any] | None) -> str:
    values = dict(source_page["values"])
    if str(values.get("source_type") or "") == "no_ingest":
        return "no_ingest"
    ingestion_state = str(values.get("ingestion_state") or "unread")
    mapped = SOURCE_STATUS_TO_INPUT_STATUS.get(ingestion_state, "configured")
    if mapped == "configured" and not source_config:
        return "declared"
    return mapped


def compile_input_stage(
    root: Path,
    config: WikiConfig,
    *,
    generated_at: dt.date | str | None = None,
) -> dict[str, Any]:
    """Compile root/channel/source configuration into a deterministic catalog."""
    if generated_at is None:
        date_text = dt.date.today().isoformat()
    elif isinstance(generated_at, dt.date):
        date_text = generated_at.isoformat()
    else:
        date_text = str(generated_at)

    paths = WikiPaths(root, config)
    root_entity = find_root_entity(root, config, paths)
    channels = [_channel_payload(page) for page in _pages_by_type(root, paths, "input_channel")]
    source_pages = _source_pages(root, paths)
    warnings: list[str] = []
    source_rows: list[dict[str, Any]] = []

    for source_page in source_pages:
        source_config = _config_page_for_source(root, config, source_page)
        channel = _match_channel(source_page, source_config, channels)
        values = dict(source_page["values"])
        context = str(values.get("context") or source_page.get("context") or config.default_context)
        context_hub = _context_hub(root, config, context)
        target_pages = _dedupe(
            [
                item
                for item in [
                    (root_entity or {}).get("path"),
                    context_hub,
                    *list((channel or {}).get("target_pages") or []),
                    *list((source_config or {}).get("target_pages") or []),
                ]
                if item
            ]
        )
        quadrants = _dedupe(
            list((channel or {}).get("quadrants") or [])
            + list((source_config or {}).get("quadrants") or [])
        )
        if not source_config:
            warnings.append(f"{source_page['path']}: no source_config linked")
        if not channel:
            warnings.append(f"{source_page['path']}: no input_channel linked")
        source_rows.append(
            {
                "source_page_id": source_page["page_id"],
                "source_path": source_page["path"],
                "title": source_page["title"],
                "context": context,
                "source_type": str(values.get("source_type") or ""),
                "ingestion_state": str(values.get("ingestion_state") or "unread"),
                "input_status": _source_input_status(source_page, source_config),
                "source_config": source_config,
                "input_channel": channel,
                "quadrants": quadrants,
                "resolved_perspectives": _resolved_perspectives(root_entity, channel, source_config),
                "target_pages": target_pages,
                "privacy_boundary": str(values.get("visibility") or config.default_visibility),
                "refresh_policy": str(values.get("refresh_policy") or ""),
                "refresh_cadence_days": str(values.get("refresh_cadence_days") or ""),
            }
        )

    channel_source_keys: set[str] = set()
    for source in source_rows:
        channel = source.get("input_channel") or {}
        channel_source_keys.update(channel.get("source_refs") or [])

    declared_channels = []
    source_keys = set()
    for source_page in source_pages:
        source_keys.update(_page_keys(source_page))
    for channel in channels:
        refs = set(channel.get("source_refs") or [])
        if refs and refs <= source_keys:
            continue
        if not refs:
            declared_channels.append(channel)
        elif refs - source_keys:
            warnings.append(
                f"{channel['path']}: source_refs not found: {', '.join(sorted(refs - source_keys))}"
            )
            declared_channels.append(channel)

    ready = [
        source
        for source in source_rows
        if source.get("input_status") in {"ready_for_ingest", "configured", "staged"}
    ]
    return {
        "schema_version": INPUT_STAGE_SCHEMA_VERSION,
        "generated_at": date_text,
        "root_entity": root_entity,
        "quadrant_map": DEFAULT_QUADRANT_MAP,
        "channels": channels,
        "declared_channels_without_sources": declared_channels,
        "sources": source_rows,
        "ready_inputs": ready,
        "warnings": sorted(set(warnings)),
    }


def input_context_for_source(
    root: Path,
    config: WikiConfig,
    source: str,
    *,
    generated_at: dt.date | str | None = None,
) -> dict[str, Any]:
    """Return root/input metadata for a repo-local source page.

    Raw files and URLs usually have no source page yet; they still receive root
    defaults when a root entity is configured.
    """
    catalog = compile_input_stage(root, config, generated_at=generated_at)
    source_path = _repo_path(root, source)
    source_rel = _rel(root, source_path) if source_path is not None else source
    matched = None
    for row in catalog.get("sources", []):
        if row.get("source_path") == source_rel or row.get("source_page_id") == source:
            matched = row
            break
    root_entity = catalog.get("root_entity") if isinstance(catalog.get("root_entity"), dict) else None
    if matched is None:
        root_bundle = (root_entity or {}).get("perspective_bundle", {})
        return {
            "root_entity": root_entity,
            "input_channel": None,
            "quadrant_map": catalog.get("quadrant_map"),
            "target_pages": [root_entity.get("path")] if root_entity and root_entity.get("path") else [],
            "perspectives_required": list(root_bundle.get("required") or []),
            "perspectives_optional": list(root_bundle.get("optional") or []),
            "input_stage_status": "unmatched_source",
        }
    resolved = matched.get("resolved_perspectives") or {}
    return {
        "root_entity": root_entity,
        "input_channel": matched.get("input_channel"),
        "quadrant_map": catalog.get("quadrant_map"),
        "target_pages": matched.get("target_pages") or [],
        "perspectives_required": list(resolved.get("required") or []),
        "perspectives_optional": list(resolved.get("optional") or []),
        "input_stage_status": matched.get("input_status"),
    }


def _input_stage_dir(config: WikiConfig) -> str:
    page = str((config.root_entity or {}).get("input_stage_page") or "memories/system/input-stage.md")
    return posixpath.dirname(page) or "."


def _labels(config: WikiConfig) -> dict[str, str]:
    if str(getattr(config, "language", "en")).lower().startswith("pt"):
        return {
            "title": "Estagio de entrada",
            "updated_on": "Atualizado em",
            "generated_note": "Esta pagina e gerada por [wiki_input_stage.py](../../scripts/wiki_input_stage.py). Nao edite manualmente.",
            "root_entity": "Entidade raiz",
            "field": "Campo",
            "value": "Valor",
            "entity_type": "Tipo da entidade",
            "required_perspectives": "Perspectivas obrigatorias",
            "optional_perspectives": "Perspectivas opcionais",
            "input_channels": "Canais de entrada",
            "channel": "Canal",
            "type": "Tipo",
            "status": "Estado",
            "quadrants": "Quadrantes",
            "sources": "Fontes",
            "source": "Fonte",
            "input_status": "Estado de entrada",
            "config": "Config",
            "target_pages": "Paginas-alvo",
            "ready_inputs": "Entradas prontas",
            "next_action": "Proxima acao",
            "ready_action": "Rodar ou atualizar a ingestao quando o material atual estiver preparado.",
            "warnings": "Avisos",
            "none": "_(nenhum)_",
            "no_warnings": "Nenhum.",
            "validation": "Validacao",
            "not_configured": "nao_configurado",
        }
    return {
        "title": "Input stage",
        "updated_on": "Updated on",
        "generated_note": "This page is generated by [wiki_input_stage.py](../../scripts/wiki_input_stage.py). Do not hand-edit.",
        "root_entity": "Root entity",
        "field": "Field",
        "value": "Value",
        "entity_type": "Entity type",
        "required_perspectives": "Required perspectives",
        "optional_perspectives": "Optional perspectives",
        "input_channels": "Input channels",
        "channel": "Channel",
        "type": "Type",
        "status": "Status",
        "quadrants": "Quadrants",
        "sources": "Sources",
        "source": "Source",
        "input_status": "Input status",
        "config": "Config",
        "target_pages": "Target pages",
        "ready_inputs": "Ready inputs",
        "next_action": "Next action",
        "ready_action": "Run or refresh ingestion when current material is staged.",
        "warnings": "Warnings",
        "none": "_(none)_",
        "no_warnings": "None.",
        "validation": "Validation",
        "not_configured": "not_configured",
    }


def _display_path(config: WikiConfig, path: str | None) -> str:
    if not path:
        return ""
    if "://" in path or path.startswith("#"):
        return path
    return posixpath.relpath(path, _input_stage_dir(config))


def _link(label: str, path: str | None, config: WikiConfig) -> str:
    if not path:
        return ""
    return f"[{label}]({_display_path(config, path)})"


def _join(values: list[str] | tuple[str, ...] | None) -> str:
    return ", ".join(values or [])


def _links(values: list[str] | tuple[str, ...] | None, config: WikiConfig) -> str:
    return ", ".join(_link(value, value, config) for value in (values or []))


def _source_config_label(source: dict[str, Any], config: WikiConfig) -> str:
    source_config = source.get("source_config")
    if not isinstance(source_config, dict):
        return ""
    path = str(source_config.get("path") or "")
    return _link(str(source_config.get("page_id") or "config"), path, config)


def _channel_label(channel: dict[str, Any] | None, config: WikiConfig) -> str:
    if not channel:
        return ""
    return _link(
        str(channel.get("title") or channel.get("page_id") or "channel"),
        str(channel.get("path") or ""),
        config,
    )


def render_input_stage_markdown(catalog: dict[str, Any], config: WikiConfig) -> str:
    labels = _labels(config)
    root_entity = catalog.get("root_entity") if isinstance(catalog.get("root_entity"), dict) else None
    date_text = str(catalog.get("generated_at") or dt.date.today().isoformat())
    root_link = _link(
        str((root_entity or {}).get("title") or "Not configured"),
        str((root_entity or {}).get("path") or ""),
        config,
    )
    lines = [
        "---",
        "page_id: system-input-stage",
        "page_type: input_stage",
        f"title: \"{labels['title']}\"",
        f"context: {config.default_context}",
        "visibility: private_self",
        f"updated_at: {date_text}",
        "stale_after_days: 1",
        "sources_policy: generated_from_root_entity_sources_and_configs",
        "gate: github_pr",
        "sensitive_data_policy: private_sensitive_allowed",
        f"moc_parent: {config.paths['memory_root']}/index.md",
        "---",
        "",
        f"# {labels['title']}",
        "",
        f"{labels['updated_on']}: {date_text}.",
        "",
        labels["generated_note"],
        "",
        f"## {labels['root_entity']}",
        "",
        f"| {labels['field']} | {labels['value']} |",
        "| --- | --- |",
        f"| {labels['root_entity']} | {root_link} |",
        f"| {labels['entity_type']} | `{(root_entity or {}).get('entity_type') or labels['not_configured']}` |",
        f"| {labels['required_perspectives']} | {_join((root_entity or {}).get('perspective_bundle', {}).get('required') or [])} |",
        f"| {labels['optional_perspectives']} | {_join((root_entity or {}).get('perspective_bundle', {}).get('optional') or [])} |",
        "",
        f"## {labels['input_channels']}",
        "",
        f"| {labels['channel']} | {labels['type']} | {labels['status']} | {labels['quadrants']} | {labels['sources']} |",
        "| --- | --- | --- | --- | --- |",
    ]
    for channel in catalog.get("channels", []):
        lines.append(
            "| "
            + _link(str(channel.get("title") or channel.get("page_id")), str(channel.get("path") or ""), config)
            + f" | `{channel.get('channel_type') or ''}`"
            + f" | `{channel.get('input_status') or ''}`"
            + f" | {_join(channel.get('quadrants') or [])}"
            + f" | {_join(channel.get('source_refs') or [])} |"
        )
    if not catalog.get("channels"):
        lines.append(f"| {labels['none']} |  |  |  |  |")

    lines.extend(
        [
            "",
            f"## {labels['sources']}",
            "",
            f"| {labels['source']} | {labels['input_status']} | {labels['channel']} | {labels['config']} | {labels['required_perspectives']} | {labels['target_pages']} |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for source in catalog.get("sources", []):
        required = source.get("resolved_perspectives", {}).get("required") or []
        lines.append(
            "| "
            + _link(str(source.get("title") or source.get("source_page_id")), str(source.get("source_path") or ""), config)
            + f" | `{source.get('input_status') or ''}`"
            + f" | {_channel_label(source.get('input_channel'), config)}"
            + f" | {_source_config_label(source, config)}"
            + f" | {_join(required)}"
            + f" | {_links(source.get('target_pages') or [], config)} |"
        )
    if not catalog.get("sources"):
        lines.append(f"| {labels['none']} |  |  |  |  |  |")

    lines.extend(
        [
            "",
            f"## {labels['ready_inputs']}",
            "",
            f"| {labels['source']} | {labels['status']} | {labels['next_action']} |",
            "| --- | --- | --- |",
        ]
    )
    for source in catalog.get("ready_inputs", []):
        lines.append(
            "| "
            + _link(str(source.get("title") or source.get("source_page_id")), str(source.get("source_path") or ""), config)
            + f" | `{source.get('input_status') or ''}` | {labels['ready_action']} |"
        )
    if not catalog.get("ready_inputs"):
        lines.append(f"| {labels['none']} |  |  |")

    lines.extend(["", f"## {labels['warnings']}", ""])
    warnings = catalog.get("warnings") or []
    if warnings:
        for warning in warnings:
            lines.append(f"- {warning}")
    else:
        lines.append(f"- {labels['no_warnings']}")

    lines.extend(
        [
            "",
            f"## {labels['validation']}",
            "",
            "```sh",
            "python3 scripts/wiki_input_stage.py --check",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def write_input_stage(root: Path, config: WikiConfig, *, generated_at: dt.date | str | None = None) -> dict[str, Any]:
    paths = WikiPaths(root, config)
    catalog = compile_input_stage(root, config, generated_at=generated_at)
    paths.input_stage.mkdir(parents=True, exist_ok=True)
    paths.input_stage_catalog.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    paths.input_stage_page.parent.mkdir(parents=True, exist_ok=True)
    paths.input_stage_page.write_text(render_input_stage_markdown(catalog, config), encoding="utf-8")
    return catalog


def existing_generated_at(paths: WikiPaths) -> str | None:
    if paths.input_stage_catalog.exists():
        try:
            data = json.loads(paths.input_stage_catalog.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        return str(data.get("generated_at") or "") or None
    if paths.input_stage_page.exists():
        values, _body = parse_frontmatter(paths.input_stage_page)
        return str(values.get("updated_at") or "") or None
    return None
