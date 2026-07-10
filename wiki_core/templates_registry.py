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
    # --- v2: the type as a COMPLETE module contract (blocks/identity/subpages) ---
    # Optional, back-compatible: a v1 registry resolves these to empty defaults.
    can_anchor_blocks: bool = False
    blocks: tuple[dict[str, Any], ...] = ()  # default blocks the type applies
    identity: dict[str, Any] = field(default_factory=dict)  # landmark/motif/ambient/horizon_label
    subpages: tuple[dict[str, Any], ...] = ()  # {rel, page_type, slug?, required|generated}
    skills: dict[str, Any] = field(default_factory=dict)  # {human: [...], agent: [...]}
    home_quadrant: str | None = None  # per-type quadrant home override
    # Optional collection contract for real index pages. Membership is
    # orthogonal to moc_parent and compiled by wiki_core.collections.
    collection: dict[str, Any] = field(default_factory=dict)
    # Can a HUMAN create this type from the generic palette? Generated/system
    # types (ingestion events, registries, logs) and rite-owned types (the
    # root) say no — offering the uncreatable is lying to the user.
    creatable: bool = True

    def to_json(self) -> dict[str, Any]:
        payload = {
            "page_type": self.page_type,
            "extends": self.extends,
            "body_template": self.body_template,
            "pinned_fields": list(self.pinned_fields),
            "facets": {k: list(v) for k, v in self.facets.items()},
            "view": self.view,
            "controls": [dict(c) for c in self.controls],
            "scene": self.scene,
            "can_anchor_blocks": self.can_anchor_blocks,
            "blocks": [dict(b) for b in self.blocks],
            "identity": dict(self.identity),
            "subpages": [dict(s) for s in self.subpages],
            "skills": dict(self.skills),
            "home_quadrant": self.home_quadrant,
            "creatable": self.creatable,
        }
        if self.collection:
            payload["collection"] = dict(self.collection)
        return payload


@dataclass(frozen=True)
class TemplateRegistry:
    path: Path | None
    schema_version: str
    raw_types: dict[str, dict[str, Any]]
    bases: dict[str, dict[str, Any]]
    # v2 block registry (the `blocks:` section), merged with local overrides. A
    # v1 file simply has none. Kept RAW here; wiki_core.template_blocks owns the
    # block vocabulary, validation and stack resolution.
    raw_blocks: dict[str, dict[str, Any]] = field(default_factory=dict)
    # v2 packages: NAMED groups of blocks (attachment sugar — blocks stay the
    # primitive). Attaching `packages: [gamification]` on an anchor expands to
    # the package's blocks, in order, at that ring.
    raw_packages: dict[str, dict[str, Any]] = field(default_factory=dict)
    vocabulary: dict[str, Any] = field(default_factory=dict)

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


def _merge_named_section(
    base: dict[str, Any] | None,
    over: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge a registry section without erasing sibling contract keys.

    Local registries are documented as overrides layered on top of the kit.
    Replacing a whole named type/block/package when only one property was
    overridden made that contract misleading (for example,
    ``can_anchor_blocks`` silently reset ``creatable`` and ``view``).  Merge
    each named entry with the same one-level semantics used by resolved specs.
    """
    merged = {str(key): dict(value) for key, value in (base or {}).items() if isinstance(value, dict)}
    for key, value in (over or {}).items():
        name = str(key)
        if isinstance(value, dict) and isinstance(merged.get(name), dict):
            merged[name] = _merge(merged[name], value)
        elif isinstance(value, dict):
            merged[name] = dict(value)
    return merged


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
        for section in ("bases", "types", "blocks", "packages"):
            data[section] = _merge_named_section(data.get(section), local.get(section))
        if isinstance(local.get("vocabulary"), dict):
            data["vocabulary"] = {**(data.get("vocabulary") or {}), **local["vocabulary"]}
    return TemplateRegistry(
        path=registry_path if registry_path.exists() else None,
        schema_version=str(data.get("schema_version") or TEMPLATES_SCHEMA_VERSION),
        raw_types={str(k): dict(v) for k, v in (data.get("types") or {}).items() if isinstance(v, dict)},
        bases={str(k): dict(v) for k, v in (data.get("bases") or {}).items() if isinstance(v, dict)},
        raw_blocks={str(k): dict(v) for k, v in (data.get("blocks") or {}).items() if isinstance(v, dict)},
        raw_packages={str(k): dict(v) for k, v in (data.get("packages") or {}).items() if isinstance(v, dict)},
        vocabulary=dict(data.get("vocabulary") or {}),
    )


_DEFAULT_SPEC: dict[str, Any] = {
    "extends": None,
    "body_template": "",
    "pinned_fields": [],
    "facets": {},
    "view": {"center": "document", "panels": [], "badges": ["freshness"]},
    "controls": [],
    "scene": {"shape": "sphere", "emphasis": "none"},
    "can_anchor_blocks": False,
    "blocks": [],
    "identity": {},
    "subpages": [],
    "skills": {},
    "home_quadrant": None,
    "collection": {},
    "creatable": True,
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
    home_q = merged.get("home_quadrant")
    collection = merged.get("collection")
    return TemplateSpec(
        page_type=page_type,
        extends=raw.get("extends"),
        body_template=str(merged.get("body_template") or ""),
        pinned_fields=tuple(str(f) for f in (merged.get("pinned_fields") or [])),
        facets=facets,
        view=dict(merged.get("view") or {}),
        controls=tuple(dict(c) for c in (merged.get("controls") or []) if isinstance(c, dict)),
        scene=dict(merged.get("scene") or {}),
        can_anchor_blocks=bool(merged.get("can_anchor_blocks") or False),
        blocks=tuple(dict(b) for b in (merged.get("blocks") or []) if isinstance(b, dict)),
        identity=dict(merged.get("identity") or {}),
        subpages=tuple(dict(s) for s in (merged.get("subpages") or []) if isinstance(s, dict)),
        skills=dict(merged.get("skills") or {}),
        home_quadrant=str(home_q) if home_q else None,
        collection=dict(collection) if isinstance(collection, dict) else {},
        creatable=bool(merged.get("creatable", True)),
    )


def validate_template_registry(registry: TemplateRegistry) -> list[str]:
    """Flag any spec that references a primitive outside the fixed vocabulary,
    an unknown facet id, or a dangling `extends`. WARN-level: unknown kinds are
    a template-authoring mistake, not a data-corruption risk."""
    errors: list[str] = []
    for page_type in list(registry.raw_types):
        raw_collection = registry.raw_types[page_type].get("collection")
        if raw_collection is not None and not isinstance(raw_collection, dict):
            errors.append(f"{page_type}: collection must be an object")
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
        collection = spec.collection
        unknown_collection_keys = sorted(
            set(collection) - {"member_types", "members", "contexts"}
        )
        for key in unknown_collection_keys:
            errors.append(f"{page_type}: unknown collection key `{key}`")
        for key in ("member_types", "members", "contexts"):
            if key in collection and not isinstance(collection.get(key), list):
                errors.append(f"{page_type}: collection.{key} must be a list")
        for member_type in collection.get("member_types") or []:
            if str(member_type) not in registry.raw_types:
                errors.append(
                    f"{page_type}: collection references unknown member type `{member_type}`"
                )
    return errors
