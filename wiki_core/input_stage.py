"""Deterministic input-stage compiler for the integral root model.

The input stage does not fetch external systems. It reads the repo's declared
root entity, input-channel pages, source pages and source configs, then emits a
stable catalog the agent can use before ingestion.
"""

from __future__ import annotations

import yaml

import datetime as dt
import json
import posixpath
import re
from pathlib import Path
from typing import Any

from wiki_core.traversal import wiki_markdown_files
from wiki_core.config import WikiConfig
from wiki_core.frontmatter import list_values, parse_frontmatter
from wiki_core.paths import WikiPaths
from wiki_core.quadrants import (
    DEFAULT_QUADRANT_MAP,
    quadrant_boundary_rule,
    quadrant_semantics,
)
from wiki_core.source_config import find_source_config

INPUT_STAGE_SCHEMA_VERSION = "wiki_input_stage.v1"
LOCAL_FOLDER_INPUT_STATUS = 'local_folder_only_source_configuration_unresolved'
SOURCE_PAGE_TYPES = {"source", "source_catalog", "artifact"}

SOURCE_STATUS_TO_INPUT_STATUS = {
    "blocked": "blocked",
    "ingested": "integrated",
    "partial": "ingesting",
    "ready_for_ingest": "ready_for_ingest",
    "registered": "configured",
    "staged": "staged",
    "stale": "configured",
    "unread": "configured",
}

READY_INPUT_STATUSES = frozenset({"ready_for_ingest", "staged"})


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _is_portuguese(config: WikiConfig) -> bool:
    return str(getattr(config, "language", "en")).lower().startswith("pt")


def _is_spanish(config: WikiConfig) -> bool:
    return str(getattr(config, "language", "en")).lower().startswith("es")


def _quadrant_semantics(config: WikiConfig) -> dict[str, dict[str, str]]:
    return quadrant_semantics(getattr(config, "language", "en"))


def _quadrant_boundary_rule(config: WikiConfig) -> str:
    return quadrant_boundary_rule(getattr(config, "language", "en"))


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _repo_path(root: Path, value: str, reads=None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = root / value
    if reads is not None:
        try:
            relative = path.relative_to(root)
        except ValueError:
            raise RuntimeError('selected path unavailable') from None
        from wiki_core.context_policy import safe_path
        try:
            if safe_path(relative.as_posix()) != relative.as_posix():
                raise ValueError('noncanonical')
        except ValueError:
            raise RuntimeError('selected path unavailable') from None
        return path
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    return path


def _md_pages(paths: WikiPaths, reads=None) -> list[Path]:
    if reads is not None:
        return reads.markdown(paths.memory_root, paths.root) if reads.is_dir(paths.memory_root) else []
    if not paths.memory_root.exists():
        return []
    return sorted(path for path in wiki_markdown_files(paths.memory_root, wiki_root=paths.root)
                  if path.is_file() and not path.is_symlink()
                  and not any(parent.is_symlink() for parent in path.parents
                              if parent != paths.root and paths.root in parent.parents))


def _read_page(root: Path, path: Path, reads=None) -> dict[str, Any]:
    values, body = parse_frontmatter(path if reads is None else reads.read_text(path, errors='replace'))
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


def _pages_by_type(root: Path, paths: WikiPaths, page_type: str, reads=None) -> list[dict[str, Any]]:
    pages = []
    for path in _md_pages(paths, reads):
        page = _read_page(root, path, reads)
        if page["page_type"] == page_type:
            pages.append(page)
    return pages


def _source_pages(root: Path, paths: WikiPaths, reads=None) -> list[dict[str, Any]]:
    pages = []
    for path in paths.source_files(reads=reads):
        if path.name in {"index.md", "README.md"}:
            continue
        page = _read_page(root, path, reads)
        if page["page_type"] in SOURCE_PAGE_TYPES:
            pages.append(page)
    return pages


def _configured_root_page(root: Path, config: WikiConfig, reads=None) -> Path | None:
    page = str((config.root_entity or {}).get("page") or "").strip()
    return _repo_path(root, page, reads) if page else None


def find_root_entity(root: Path, config: WikiConfig, paths: WikiPaths, reads=None) -> dict[str, Any] | None:
    configured = _configured_root_page(root, config, reads)
    if configured and (configured.exists() if reads is None else reads.exists(configured)):
        page = _read_page(root, configured, reads)
        if page["page_type"] == "root_entity":
            return _root_payload(page, config)

    candidates = _pages_by_type(root, paths, "root_entity", reads)
    if candidates:
        return _root_payload(candidates[0], config)
    return None


def _bundle_from_config(config: WikiConfig) -> tuple[list[str], list[str]]:
    bundle = (config.root_entity or {}).get("perspective_bundle") or {}
    if not isinstance(bundle, dict):
        return [], []
    return list_values(bundle.get("required")), list_values(bundle.get("optional"))


def _root_payload(page: dict[str, Any], config: WikiConfig, *, include_aqal: bool = True) -> dict[str, Any]:
    values = dict(page["values"])
    cfg_required, cfg_optional = _bundle_from_config(config)
    required = _dedupe(cfg_required + list_values(values.get("perspective_bundle_required"))
                       + ([item for ids in DEFAULT_QUADRANT_MAP.values() for item in ids] if include_aqal else []))
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


def _page_keys(page: dict[str, Any]) -> set[str]:
    return {key for key in (page.get("page_id"), page.get("path")) if key}


def _config_page_for_source(
    root: Path,
    config: WikiConfig,
    source_page: dict[str, Any],
    reads=None,
) -> dict[str, Any] | None:
    found = find_source_config(root, config, str(source_page["path"]), reads=reads)
    if found is None:
        return None
    config_path = _repo_path(root, str(found.get("path") or ""), reads)
    if config_path is None or not (config_path.exists() if reads is None else reads.exists(config_path)):
        return found
    page = _read_page(root, config_path, reads)
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
    aqal = {item for ids in DEFAULT_QUADRANT_MAP.values() for item in ids}
    skipped -= aqal & set(root_required)
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


def _target_bundle(root_entity, targets, pages, anchor_types):
    """Merge anchor additions along each declared destination's parent chain."""
    root_bundle = (root_entity or {}).get("perspective_bundle") or {}
    required = list(root_bundle.get("required") or [])
    optional = list(root_bundle.get("optional") or [])
    by_key = {key: page for page in pages for key in _page_keys(page)}
    known = {page["page_id"] for page in pages if page["page_type"] == "perspective"}
    for page in pages:
        values = page["values"]
        for field in ("perspective_bundle_required", "perspective_bundle_optional"):
            raw = values.get(field)
            if raw is not None and (not isinstance(raw, list) or any(not isinstance(item, str) or not item.strip() for item in raw)):
                raise ValueError(f"{page['path']}: {field} must be a list of perspective IDs")
        declared = list_values(values.get("perspective_bundle_required")) + list_values(values.get("perspective_bundle_optional"))
        if not declared:
            continue
        if page["page_type"] not in anchor_types:
            raise ValueError(f"{page['path']}: perspective bundle requires a block anchor")
        unknown = sorted(set(declared) - known)
        if unknown:
            raise ValueError(f"{page['path']}: unknown perspective id(s): {', '.join(unknown)}")
    for target in targets:
        current = by_key.get(target)
        chain = []
        seen = set()
        while current and current["path"] not in seen:
            seen.add(current["path"])
            chain.append(current)
            current = by_key.get(str(current["values"].get("moc_parent") or ""))
        for page in reversed(chain):
            if page["page_type"] not in anchor_types or page["path"] == (root_entity or {}).get("path"):
                continue
            required.extend(list_values(page["values"].get("perspective_bundle_required")))
            optional.extend(list_values(page["values"].get("perspective_bundle_optional")))
    required = _dedupe(required)
    return {"perspective_bundle": {"required": required,
            "optional": _dedupe([item for item in optional if item not in required])}}


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
    reads=None,
) -> dict[str, Any]:
    """Compile root/channel/source configuration into a deterministic catalog."""
    if generated_at is None:
        date_text = dt.date.today().isoformat()
    elif isinstance(generated_at, dt.date):
        date_text = generated_at.isoformat()
    else:
        date_text = str(generated_at)

    from wiki_core.context_hubs import context_memory_root
    if context_memory_root(root, config) is None:
        raise ValueError("unsafe context memory root")
    paths = WikiPaths(root, config)
    root_entity = find_root_entity(root, config, paths, reads)
    channels = [_channel_payload(page) for page in _pages_by_type(root, paths, "input_channel", reads)]
    source_pages = _source_pages(root, paths, reads)
    from wiki_core.context_hubs import discover_context_hubs, is_editorial_context_hub
    contexts = _dedupe([str(p["values"].get("context") or p.get("context") or config.default_context)
                        for p in source_pages])
    hubs, hub_errors = discover_context_hubs(root, config, contexts=contexts, reads=reads)
    warnings: list[str] = list(hub_errors)
    resolved_hubs: dict[str, str | None] = {}
    for context in contexts:
        registered = context in config.contexts
        administrative = context == config.default_context and not registered
        unexpected = not registered and not administrative
        if unexpected:
            warnings.append(f"context {context}: undeclared editorial context")
        candidates = hubs.get(context, [])
        invalid = any(error.startswith(f"context {context}:") for error in hub_errors)
        resolved_hubs[context] = None
        if not invalid and not unexpected and len(candidates) == 1:
            candidate = _repo_path(root, candidates[0], reads)
            if candidate and (candidate.is_file() if reads is None else reads.is_file(candidate)):
                page = _read_page(root, candidate, reads)
                # Fallback paths are diagnostic, not qualified hub identities.
                # Check original typed metadata, not _read_page's display strings.
                configured_root = _configured_root_page(root, config, reads)
                flat_root = (page["page_type"] == "root_entity"
                             and configured_root == candidate
                             and (root_entity or {}).get("path") == page["path"])
                if is_editorial_context_hub(page["values"], context) or flat_root:
                    resolved_hubs[context] = page["path"]
        if resolved_hubs[context] is None and (registered or invalid):
            warnings.append(f"context {context}: context hub unavailable; root/channel/config targets do not substitute for it")
    # Use the same guarded reader as the rest of the input-stage compiler.
    pages = [_read_page(root, path, reads) for path in _md_pages(paths, reads)]
    has_local_bundles = any(p["page_type"] != "root_entity" and
        (p["values"].get("perspective_bundle_required") or p["values"].get("perspective_bundle_optional")) for p in pages)
    anchor_types = {"root_entity", "context_hub", "project", "holon", "source", "template_block", "ontology_index", "source_registry"}
    if has_local_bundles:
        if reads is not None:
            # Registry bytes must be in the admitted selection, never bypass the reader.
            from wiki_core.templates_registry import TemplateRegistry, _merge_named_section
            data = {}
            for name in ("wiki.templates.yaml", "wiki.templates.local.yaml"):
                path = root / name
                if reads.exists(path):
                    part = yaml.safe_load(reads.read_text(path)) or {}
                    for section in ("bases", "types"):
                        data[section] = _merge_named_section(data.get(section), part.get(section))
            registry = TemplateRegistry(None, "", data.get("types", {}), data.get("bases", {}))
        else:
            from wiki_core.templates_registry import load_template_registry
            registry = load_template_registry(root, config)
        if registry.raw_types:
            anchor_types = {name for name in registry.raw_types if registry.resolve(name).can_anchor_blocks}
    # Validate configured root declarations as well as every page declaration.
    known_perspectives = {p["page_id"] for p in pages if p["page_type"] == "perspective"}
    cfg_required, cfg_optional = _bundle_from_config(config)
    unknown = sorted(set(cfg_required + cfg_optional) - known_perspectives)
    if unknown:
        raise ValueError(f"root entity: unknown perspective id(s): {', '.join(unknown)}")
    _target_bundle(root_entity, [], pages, anchor_types)  # validate even without sources
    source_rows: list[dict[str, Any]] = []

    for source_page in source_pages:
        source_config = _config_page_for_source(root, config, source_page, reads)
        channel = _match_channel(source_page, source_config, channels)
        values = dict(source_page["values"])
        context = str(values.get("context") or source_page.get("context") or config.default_context)
        context_hub = resolved_hubs.get(context)
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
                "resolved_perspectives": _resolved_perspectives(
                    _target_bundle(root_entity, target_pages, pages, anchor_types), channel, source_config),
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
        if source.get("input_status") in READY_INPUT_STATUSES
    ]
    return {
        "schema_version": INPUT_STAGE_SCHEMA_VERSION,
        "config_ref": "wiki.config.yaml" if ((root/"wiki.config.yaml").is_file() if reads is None else reads.is_file(root/"wiki.config.yaml")) else "",
        "generated_at": date_text,
        "root_entity": root_entity,
        "quadrant_map": DEFAULT_QUADRANT_MAP,
        "quadrant_semantics": _quadrant_semantics(config),
        "quadrant_boundary_rule": _quadrant_boundary_rule(config),
        "channels": channels,
        "declared_channels_without_sources": declared_channels,
        "sources": source_rows,
        "ready_inputs": ready,
        "warnings": sorted(set(warnings)),
    }


def local_folder_input_context() -> dict[str, Any]:
    """Report missing global input metadata without discovering other pages."""
    return {'root_entity': None, 'input_channel': None, 'quadrant_map': {},
            'quadrant_semantics': {}, 'quadrant_boundary_rule': '', 'target_pages': [],
            'perspectives_required': [], 'perspectives_optional': [],
            'input_stage_status': LOCAL_FOLDER_INPUT_STATUS}


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
            "quadrant_semantics": catalog.get("quadrant_semantics"),
            "quadrant_boundary_rule": catalog.get("quadrant_boundary_rule"),
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
        "quadrant_semantics": catalog.get("quadrant_semantics"),
        "quadrant_boundary_rule": catalog.get("quadrant_boundary_rule"),
        "target_pages": matched.get("target_pages") or [],
        "perspectives_required": list(resolved.get("required") or []),
        "perspectives_optional": list(resolved.get("optional") or []),
        "input_stage_status": matched.get("input_status"),
    }


def _input_stage_dir(config: WikiConfig) -> str:
    page = str((config.root_entity or {}).get("input_stage_page") or "memories/system/input-stage.md")
    return posixpath.dirname(page) or "."


def _labels(config: WikiConfig) -> dict[str, str]:
    if _is_portuguese(config):
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
            "quadrant_semantics": "Semantica dos quadrantes",
            "semantic_key": "Chave semantica",
            "aqal_position": "Posicao AQAL",
            "operational_test": "Teste operacional",
            "boundary_rule": "Regra de fronteira",
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
    if _is_spanish(config):
        return {
            "title": "Etapa de entrada",
            "updated_on": "Actualizado el",
            "generated_note": "Esta página se genera mediante [wiki_input_stage.py](../../scripts/wiki_input_stage.py). No la edite manualmente.",
            "root_entity": "Entidad raíz",
            "field": "Campo",
            "value": "Valor",
            "entity_type": "Tipo de entidad",
            "required_perspectives": "Perspectivas obligatorias",
            "optional_perspectives": "Perspectivas opcionales",
            "input_channels": "Canales de entrada",
            "quadrant_semantics": "Semántica de los cuadrantes",
            "semantic_key": "Clave semántica",
            "aqal_position": "Posición AQAL",
            "operational_test": "Prueba operativa",
            "boundary_rule": "Regla de frontera",
            "channel": "Canal",
            "type": "Tipo",
            "status": "Estado",
            "quadrants": "Cuadrantes",
            "sources": "Fuentes",
            "source": "Fuente",
            "input_status": "Estado de entrada",
            "config": "Configuración",
            "target_pages": "Páginas objetivo",
            "ready_inputs": "Entradas listas",
            "next_action": "Próxima acción",
            "ready_action": "Ejecute o actualice la ingesta cuando el material actual esté preparado.",
            "warnings": "Advertencias",
            "none": "_(ninguno)_",
            "no_warnings": "Ninguna.",
            "validation": "Validación",
            "not_configured": "no_configurado",
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
        "quadrant_semantics": "Quadrant semantics",
        "semantic_key": "Semantic key",
        "aqal_position": "AQAL position",
        "operational_test": "Operational test",
        "boundary_rule": "Boundary rule",
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


def _link(label: str, path: str | None, config: WikiConfig, *, role: str | None = None, consumes: list[str] | None = None) -> str:
    if not path:
        return ""
    literal = f"[{label}]({_display_path(config, path)})"
    if consumes:
        from wiki_core.markdown_link_roles import declare_projection
        return declare_projection(literal,consumes=consumes)
    if role:
        from wiki_core.markdown_link_roles import declare_link_role
        return declare_link_role(literal, role)
    return literal


def _join(values: list[str] | tuple[str, ...] | None) -> str:
    return ", ".join(values or [])


def _links(values: list[str] | tuple[str, ...] | None, config: WikiConfig, *, role: str | None = None) -> str:
    return ", ".join(_link(value, value, config, role=role) for value in (values or []))


_WARNING_PATH_RE = re.compile(r"^(?P<path>.+?\.md)(?P<detail>:\s.*)$")


def _warning_label(warning: Any, config: WikiConfig, *, annotated: bool = True) -> str:
    """Render a generated diagnostic without leaking a bare repo-local path.

    The catalog keeps its stable string warning contract for JSON consumers,
    while the Markdown projection links the leading page path emitted by the
    compiler. This keeps generated pages compatible with
    ``audit.require_markdown_links``.
    """
    text = str(warning)
    match = _WARNING_PATH_RE.match(text)
    if not match:
        return text
    path = match.group("path")
    if "://" in path or path.startswith("/"):
        return text
    return f"{_link(path, path, config, role='review_record' if annotated else None)}{match.group('detail')}"


def _source_config_label(source: dict[str, Any], config: WikiConfig, *, annotated: bool = True) -> str:
    source_config = source.get("source_config")
    if not isinstance(source_config, dict):
        return ""
    path = str(source_config.get("path") or "")
    return _link(str(source_config.get("page_id") or "config"), path, config,
        consumes=['page_id','page_type','source_refs','perspectives_required','perspectives_optional',
            'perspectives_skip_with_reason','input_channel_ref','process_refs','target_pages','quadrants'] if annotated else None)


def _channel_label(channel: dict[str, Any] | None, config: WikiConfig, *, annotated: bool = True) -> str:
    if not channel:
        return ""
    return _link(
        str(channel.get("title") or channel.get("page_id") or "channel"),
        str(channel.get("path") or ""),
        config,
        consumes=_channel_fields() if annotated else None,
    )


def _channel_fields() -> list[str]:
    return ['page_id','page_type','title','channel_type','input_status','quadrants','source_refs',
        'source_config_refs','target_pages','perspectives_required','perspectives_optional']


def _source_fields() -> list[str]:
    return ['page_id','page_type','title','context','source_type','ingestion_state','config_ref']


def render_input_stage_markdown(
    catalog: dict[str, Any], config: WikiConfig, *, _annotate_targets: bool = True,
    _annotate_projections: bool = True,
) -> str:
    labels = _labels(config)
    root_entity = catalog.get("root_entity") if isinstance(catalog.get("root_entity"), dict) else None
    date_text = str(catalog.get("generated_at") or dt.date.today().isoformat())
    root_link = _link(
        str((root_entity or {}).get("title") or "Not configured"),
        str((root_entity or {}).get("path") or ""),
        config,
        consumes=['page_id','page_type','title','root_entity_type','perspective_bundle_required',
            'perspective_bundle_optional'] if _annotate_projections else None,
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
        *(yaml.safe_dump({'projection_inputs':[
            *([{'paths':['wiki.config.yaml'],'fields':['body']}] if catalog.get('config_ref') else []),
            {'page_types':sorted(SOURCE_PAGE_TYPES),**WikiPaths(Path('.'),config).collection_selector('sources_dirname'),
             'fields':_source_fields(),'title_fallback':'blank'},
            {'page_types':['input_channel'],'fields':_channel_fields(),'title_fallback':'blank'},
            {'page_types':['context_hub'],'path_prefix':config.paths['memory_root'],
             'fields':['page_id','page_type','context','moc_parent']},
            {'page_types':['root_entity'],'fields':['page_id','title','root_entity_type',
                'perspective_bundle_required','perspective_bundle_optional'],'title_fallback':'blank'},
            {'page_types':['source_config'],'fields':['page_id','source_refs','input_channel_ref','process_refs',
                'target_pages','quadrants','perspectives_required','perspectives_optional','perspectives_skip_with_reason']},
        ]},sort_keys=False).rstrip().splitlines() if _annotate_projections else []),
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
        f"## {labels['quadrant_semantics']}",
        "",
        f"| {labels['quadrants']} | {labels['semantic_key']} | {labels['aqal_position']} | {labels['operational_test']} |",
        "| --- | --- | --- | --- |",
    ]
    for qid, semantics in (catalog.get("quadrant_semantics") or {}).items():
        lines.append(
            f"| `{qid}` | `{semantics.get('semantic_key') or ''}`"
            + f" | {semantics.get('aqal_position') or ''}"
            + f" | {semantics.get('operational_test') or ''} |"
        )
    lines.extend(
        [
            "",
            f"{labels['boundary_rule']}: {catalog.get('quadrant_boundary_rule') or ''}",
            "",
        ]
    )
    lines.extend(
        [
        f"## {labels['input_channels']}",
        "",
        f"| {labels['channel']} | {labels['type']} | {labels['status']} | {labels['quadrants']} | {labels['sources']} |",
        "| --- | --- | --- | --- | --- |",
        ]
    )
    for channel in catalog.get("channels", []):
        lines.append(
            "| "
            + _link(str(channel.get("title") or channel.get("page_id")), str(channel.get("path") or ""), config,
                consumes=_channel_fields() if _annotate_projections else None)
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
            + _link(str(source.get("title") or source.get("source_page_id")), str(source.get("source_path") or ""), config,
                consumes=_source_fields() if _annotate_projections else None)
            + f" | `{source.get('input_status') or ''}`"
            + f" | {_channel_label(source.get('input_channel'), config, annotated=_annotate_projections)}"
            + f" | {_source_config_label(source, config, annotated=_annotate_projections)}"
            + f" | {_join(required)}"
            + f" | {_links(source.get('target_pages') or [], config, role='change_target' if _annotate_targets else None)} |"
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
            + _link(str(source.get("title") or source.get("source_page_id")), str(source.get("source_path") or ""), config,
                consumes=_source_fields() if _annotate_projections else None)
            + f" | `{source.get('input_status') or ''}` | {labels['ready_action']} |"
        )
    if not catalog.get("ready_inputs"):
        lines.append(f"| {labels['none']} |  |  |")

    lines.extend(["", f"## {labels['warnings']}", ""])
    warnings = catalog.get("warnings") or []
    if warnings:
        for warning in warnings:
            lines.append(f"- {_warning_label(warning, config, annotated=_annotate_projections)}")
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


def matching_input_stage_catalog(
    catalog: dict[str, Any], config: WikiConfig, markdown: bytes,
) -> dict[str, Any] | None:
    """Match complete canonical modern or pre-role output, never clean input.

    The Markdown's canonical date is authoritative, not the ignored JSON cache.
    This proves only the Markdown output for current compiler inputs, not full
    historical model equality, source freshness or narrower consumption.
    """
    try:
        values, _ = parse_frontmatter(markdown.decode("utf-8"))
        date_text = str(values.get("updated_at") or "")
        if dt.date.fromisoformat(date_text).isoformat() != date_text:
            return None
    except (UnicodeError, ValueError):
        return None
    retained = {**catalog, "generated_at": date_text}
    for annotated, projections in ((True,True),(True,False),(False,False)):
        expected = render_input_stage_markdown(retained, config, _annotate_targets=annotated,_annotate_projections=projections)
        if markdown == expected.encode("utf-8"):
            return retained
    return None


def matching_input_stage_cache(catalog: dict[str, Any], data: bytes) -> dict[str, Any] | None:
    """Verify the complete cache against current inputs at its own date.

    Cache and Markdown are separate generated outputs. Equal Markdown does not
    prove equality of model fields that the renderer does not publish.
    """
    try:
        payload = json.loads(data)
        date_text = payload.get("generated_at") if isinstance(payload, dict) else None
        if not isinstance(date_text, str) or dt.date.fromisoformat(date_text).isoformat() != date_text:
            return None
    except (UnicodeError, ValueError):
        return None
    retained = {**catalog, "generated_at": date_text}
    expected = (json.dumps(retained, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return retained if data == expected else None


def write_input_stage(
    root: Path, config: WikiConfig, *, generated_at: dt.date | str | None = None,
    if_changed: bool = False,
) -> dict[str, Any]:
    """Generate normally, or explicitly preserve a proven unchanged artifact.

    In opt-in mode generated_at dates newly generated output only. An existing
    exact supported output keeps its own date and bytes; a check is not a new
    generation or source verification. The full JSON has its own generation
    date: it is retained only if its entire current model also matches.
    """
    paths = WikiPaths(root, config)
    catalog = compile_input_stage(root, config, generated_at=generated_at)
    publication_date = catalog["generated_at"]
    retained = (matching_input_stage_catalog(catalog, config, paths.input_stage_page.read_bytes())
                if if_changed and paths.input_stage_page.exists() else None)
    retained_cache = (matching_input_stage_cache(catalog, paths.input_stage_catalog.read_bytes())
                      if if_changed and paths.input_stage_catalog.exists() else None)
    if retained_cache is not None:
        catalog = retained_cache
    expected_json = (json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    paths.input_stage.mkdir(parents=True, exist_ok=True)
    if (not if_changed or not paths.input_stage_catalog.exists()
            or paths.input_stage_catalog.read_bytes() != expected_json):
        paths.input_stage_catalog.write_bytes(expected_json)
    if retained is None:
        paths.input_stage_page.parent.mkdir(parents=True, exist_ok=True)
        # A new Markdown output uses this execution's requested date, even if
        # a complete unchanged JSON cache was retained at its earlier date.
        markdown_catalog = {**catalog, "generated_at": publication_date}
        paths.input_stage_page.write_text(render_input_stage_markdown(markdown_catalog, config), encoding="utf-8")
    return catalog


def existing_generated_at(paths: WikiPaths, reads=None) -> str | None:
    if paths.input_stage_page.exists() if reads is None else reads.exists(paths.input_stage_page):
        values, _body = parse_frontmatter(paths.input_stage_page if reads is None else reads.read_text(paths.input_stage_page, errors='replace'))
        date_text = str(values.get("updated_at") or "")
        try:
            return date_text if dt.date.fromisoformat(date_text).isoformat() == date_text else None
        except ValueError:
            return None
    if paths.input_stage_catalog.exists() if reads is None else reads.exists(paths.input_stage_catalog):
        try:
            data = json.loads(paths.input_stage_catalog.read_text(encoding="utf-8") if reads is None else reads.read_text(paths.input_stage_catalog))
        except json.JSONDecodeError:
            return None
        if isinstance(data, dict):
            date_text = data.get("generated_at")
            try:
                return date_text if isinstance(date_text, str) and dt.date.fromisoformat(date_text).isoformat() == date_text else None
            except ValueError:
                return None
    return None
