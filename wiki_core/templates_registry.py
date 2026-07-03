"""Declarative template registry — the page TYPE as schema + body skeleton +
VIEW/INTERACTION spec, interpreted by the cockpit (not hardcoded per type).

`wiki.page-types.yaml` stays the VALIDATION contract (required frontmatter,
field types, allowed dirs). This registry (`wiki.templates.yaml`, merged over a
per-wiki `wiki.templates.local.yaml`) adds the PRESENTATION contract: which
fields are pinned, how each facet is filled, what panels/controls/scene the
type renders. A custom wiki adds a type by writing YAML — but only by COMPOSING
a fixed vocabulary of primitives implemented once in the cockpit; a brand-new
primitive still needs code (verified limit, DataHub entity-registry precedent),
so the vocabulary is versioned and validated here.

Deterministic, pure-ish (only reads files), exported into the snapshot as
`templates.json` and consumed by the frontend presentation layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from wiki_core.config import WikiConfig
from wiki_core.facets import FACETS

TEMPLATES_SCHEMA_VERSION = "wiki_templates.v1"

# The FIXED vocabulary. Composing these in YAML is free; anything outside needs
# code. Kept small and honest — the registry validator flags unknown kinds.
PANEL_KINDS = frozenset({"list", "table", "timeline", "badges", "text", "diff"})
CONTROL_KINDS = frozenset({"brief", "nav", "filter", "run", "focus"})
CENTER_KINDS = frozenset({"document", "timeline", "dashboard", "entity"})
SCENE_SHAPES = frozenset({"sphere", "crystal", "hub", "slab", "spark", "comet", "diamond"})
BADGE_KINDS = frozenset({"freshness", "evidence", "approval", "privacy", "sync"})


@dataclass(frozen=True)
class TemplateSpec:
    page_type: str
    extends: str | None
    body_template: str
    pinned_fields: tuple[str, ...]
    facets: dict[str, tuple[str, ...]]  # facet id -> frontmatter field names
    view: dict[str, Any]  # {center, panels: [...], badges: [...]}
    controls: tuple[dict[str, Any], ...]
    scene: dict[str, Any]  # {shape, emphasis}

    def to_json(self) -> dict[str, Any]:
        return {
            "page_type": self.page_type,
            "extends": self.extends,
            "body_template": self.body_template,
            "pinned_fields": list(self.pinned_fields),
            "facets": {k: list(v) for k, v in self.facets.items()},
            "view": self.view,
            "controls": [dict(c) for c in self.controls],
            "scene": self.scene,
        }


@dataclass(frozen=True)
class TemplateRegistry:
    path: Path | None
    schema_version: str
    raw_types: dict[str, dict[str, Any]]
    bases: dict[str, dict[str, Any]]

    def resolve(self, page_type: str) -> TemplateSpec:
        return resolve_template_spec(self, page_type)

    def to_json(self, page_types: list[str] | None = None) -> dict[str, Any]:
        keys = page_types if page_types is not None else list(self.raw_types)
        return {
            "schema_version": self.schema_version,
            "facets_order": list(FACETS),
            "types": {pt: self.resolve(pt).to_json() for pt in keys},
        }


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """Shallow-merge with list replacement (over wins). Nested view/scene dicts
    merge one level so an override can tweak `scene.shape` without redeclaring
    the whole block."""
    out = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = {**out[key], **value}
        else:
            out[key] = value
    return out


def load_template_registry(
    root: Path,
    config: WikiConfig | None = None,
    path: str = "wiki.templates.yaml",
    local_path: str = "wiki.templates.local.yaml",
) -> TemplateRegistry:
    """Load the kit registry, then merge a per-wiki local override on top
    (same override philosophy as the presentation/context config)."""
    data: dict[str, Any] = {}
    registry_path = root / path
    if registry_path.exists():
        data = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    local_file = root / local_path
    if local_file.exists():
        local = yaml.safe_load(local_file.read_text(encoding="utf-8")) or {}
        for section in ("bases", "types"):
            merged = {**(data.get(section) or {}), **(local.get(section) or {})}
            data[section] = merged
    return TemplateRegistry(
        path=registry_path if registry_path.exists() else None,
        schema_version=str(data.get("schema_version") or TEMPLATES_SCHEMA_VERSION),
        raw_types={str(k): dict(v) for k, v in (data.get("types") or {}).items() if isinstance(v, dict)},
        bases={str(k): dict(v) for k, v in (data.get("bases") or {}).items() if isinstance(v, dict)},
    )


_DEFAULT_SPEC: dict[str, Any] = {
    "extends": None,
    "body_template": "",
    "pinned_fields": [],
    "facets": {},
    "view": {"center": "document", "panels": [], "badges": ["freshness"]},
    "controls": [],
    "scene": {"shape": "sphere", "emphasis": "none"},
}


def resolve_template_spec(registry: TemplateRegistry, page_type: str) -> TemplateSpec:
    """Resolve a type's full spec: default → its `extends` base chain → its own
    keys. Unknown types resolve to the safe default (today's reader)."""
    raw = registry.raw_types.get(page_type, {})
    chain: list[dict[str, Any]] = []
    seen: set[str] = set()
    base_name = raw.get("extends")
    while base_name and base_name not in seen and base_name in registry.bases:
        seen.add(base_name)
        base = registry.bases[base_name]
        chain.append(base)
        base_name = base.get("extends")
    merged = dict(_DEFAULT_SPEC)
    for layer in reversed(chain):  # apply outermost base first
        merged = _merge(merged, layer)
    merged = _merge(merged, raw)
    facets = {
        str(k): tuple(str(x) for x in (v or []))
        for k, v in (merged.get("facets") or {}).items()
        if k in FACETS
    }
    return TemplateSpec(
        page_type=page_type,
        extends=raw.get("extends"),
        body_template=str(merged.get("body_template") or ""),
        pinned_fields=tuple(str(f) for f in (merged.get("pinned_fields") or [])),
        facets=facets,
        view=dict(merged.get("view") or {}),
        controls=tuple(dict(c) for c in (merged.get("controls") or []) if isinstance(c, dict)),
        scene=dict(merged.get("scene") or {}),
    )


def validate_template_registry(registry: TemplateRegistry) -> list[str]:
    """Flag any spec that references a primitive outside the fixed vocabulary,
    an unknown facet id, or a dangling `extends`. WARN-level: unknown kinds are
    a template-authoring mistake, not a data-corruption risk."""
    errors: list[str] = []
    for page_type in list(registry.raw_types):
        spec = registry.resolve(page_type)
        # Facets are checked from the RAW map (resolve() drops unknown ids, so
        # a typo would silently vanish rather than surface here).
        for facet in (registry.raw_types[page_type].get("facets") or {}):
            if facet not in FACETS:
                errors.append(f"{page_type}: unknown facet id `{facet}`")
        for panel in spec.view.get("panels") or []:
            kind = str(panel.get("kind") or "")
            if kind not in PANEL_KINDS:
                errors.append(f"{page_type}: unknown panel kind `{kind}` (add code or use {sorted(PANEL_KINDS)})")
        for badge in spec.view.get("badges") or []:
            if str(badge) not in BADGE_KINDS:
                errors.append(f"{page_type}: unknown badge `{badge}`")
        for control in spec.controls:
            kind = str(control.get("kind") or "")
            if kind not in CONTROL_KINDS:
                errors.append(f"{page_type}: unknown control kind `{kind}`")
        center = str(spec.view.get("center") or "document")
        if center not in CENTER_KINDS:
            errors.append(f"{page_type}: unknown center kind `{center}`")
        shape = str(spec.scene.get("shape") or "sphere")
        if shape not in SCENE_SHAPES:
            errors.append(f"{page_type}: unknown scene shape `{shape}`")
        base_name = registry.raw_types[page_type].get("extends")
        if base_name and base_name not in registry.bases:
            errors.append(f"{page_type}: extends unknown base `{base_name}`")
    return errors
