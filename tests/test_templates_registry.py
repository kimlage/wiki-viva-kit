from __future__ import annotations

from pathlib import Path

from wiki_core.templates_registry import (
    load_template_registry,
    validate_template_registry,
)

KIT_ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_kit_registry_loads_and_validates_clean() -> None:
    registry = load_template_registry(KIT_ROOT)
    assert registry.schema_version.startswith("wiki_templates")
    assert "meeting" in registry.raw_types
    assert validate_template_registry(registry) == []


def test_extends_resolves_the_base_chain() -> None:
    registry = load_template_registry(KIT_ROOT)
    meeting = registry.resolve("meeting")
    # meeting extends relation_base -> inherits the focus/nav controls...
    kinds = {c["kind"] for c in meeting.controls}
    assert "focus" in kinds
    # ...but its own facets override the base's.
    assert meeting.facets["relacoes"] == ("participants", "roles")
    assert meeting.view["center"] == "timeline"
    assert meeting.scene["shape"] == "slab"


def test_unknown_type_resolves_to_safe_default() -> None:
    registry = load_template_registry(KIT_ROOT)
    spec = registry.resolve("some_custom_type_a_wiki_invented")
    assert spec.view["center"] == "document"
    assert spec.scene["shape"] == "sphere"
    assert spec.facets == {}


def test_local_override_merges_on_top(tmp_path: Path) -> None:
    _write(tmp_path / "wiki.templates.yaml", (KIT_ROOT / "wiki.templates.yaml").read_text())
    _write(
        tmp_path / "wiki.templates.local.yaml",
        "types:\n  meeting:\n    scene: { shape: hub }\n",
    )
    registry = load_template_registry(tmp_path)
    # Local override wins on the merged nested scene key...
    assert registry.resolve("meeting").scene["shape"] == "hub"


def test_validator_flags_unknown_primitives(tmp_path: Path) -> None:
    _write(
        tmp_path / "wiki.templates.yaml",
        "schema_version: wiki_templates.v1\n"
        "types:\n"
        "  gizmo:\n"
        "    view: { center: hologram, panels: [{ kind: teleport }] }\n"
        "    scene: { shape: dodecahedron }\n"
        "    facets: { vibes: [x] }\n",
    )
    registry = load_template_registry(tmp_path)
    errors = validate_template_registry(registry)
    joined = " | ".join(errors)
    assert "hologram" in joined
    assert "teleport" in joined
    assert "dodecahedron" in joined
    assert "vibes" in joined


def test_to_json_is_serializable_per_type() -> None:
    registry = load_template_registry(KIT_ROOT)
    payload = registry.to_json(["meeting", "source"])
    assert payload["facets_order"][0] == "intencao"
    assert set(payload["types"]) == {"meeting", "source"}
    assert payload["types"]["source"]["view"]["center"] == "entity"
