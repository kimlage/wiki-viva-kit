from __future__ import annotations

import datetime as dt
from pathlib import Path

from wiki_core.config import WikiConfig
from wiki_core.frontmatter import parse_frontmatter_flat
from wiki_core.source_migration import (
    apply_change,
    infer_locator,
    infer_platform,
    insert_frontmatter_keys,
    plan_source_migration,
    scaffold_recipe_block,
)
from wiki_core.source_recipe import extract_recipe_mapping, parse_recipe, validate_recipe


def _config() -> WikiConfig:
    return WikiConfig(paths={**WikiConfig().paths, "memory_root": "memories"})


def test_infer_platform_keeps_existing_and_maps_source_type() -> None:
    assert infer_platform({"platform": "slack"}) == ("slack", False)
    assert infer_platform({"source_type": "reference"}) == ("repo", False)
    assert infer_platform({"source_type": "chat"}) == ("slack", True)  # coarse → guessed
    assert infer_platform({}) == ("manual", True)  # unknown → conservative fallback


def test_infer_locator_uses_page_path_for_repo_and_todo_for_chat() -> None:
    assert infer_locator("memories/sources/x.md", {}, "repo") == ("memories/sources/x.md", False)
    assert infer_locator("memories/sources/x.md", {"source_locator": "kept"}, "repo") == ("kept", False)
    loc, todo = infer_locator("memories/sources/x.md", {}, "slack")
    assert todo is True and loc.startswith("TODO-slack")


def test_insert_frontmatter_keys_is_additive_and_preserves_order() -> None:
    text = "---\npage_id: a\npage_type: source\n---\n\n# Body\n"
    out = insert_frontmatter_keys(text, {"platform": "repo"})
    assert out == "---\npage_id: a\npage_type: source\nplatform: repo\n---\n\n# Body\n"
    # Body verbatim, existing keys untouched.
    values = parse_frontmatter_flat(out)
    assert values["page_id"] == "a" and values["platform"] == "repo"


def test_scaffold_recipe_is_valid_but_placeholder() -> None:
    block = scaffold_recipe_block("repo", "memories/sources/x.md")
    mapping = extract_recipe_mapping(block)
    assert mapping is not None
    recipe = parse_recipe(mapping)
    assert recipe.platform == "repo"
    assert recipe.locator == "memories/sources/x.md"
    # The scaffold is structurally valid (unselected stream carries a skip_reason).
    assert validate_recipe(recipe) == []
    assert recipe.streams[0].selected is False


def _seed_source_wiki(root: Path) -> None:
    (root / "memories/sources/config").mkdir(parents=True)
    (root / "memories/sources/methodology.md").write_text(
        "---\n"
        "page_id: sources-methodology\n"
        "page_type: source\n"
        "source_type: reference\n"
        "config_ref: memories/sources/config/methodology.md\n"
        "---\n\n# Methodology source\n",
        encoding="utf-8",
    )
    (root / "memories/sources/config/methodology.md").write_text(
        "---\n"
        "page_id: source-config-methodology\n"
        "page_type: source_config\n"
        "owner: root-entity\n"
        "source_refs:\n  - sources-methodology\n"
        "---\n\n# Methodology config\n\nNo recipe here yet.\n",
        encoding="utf-8",
    )


def test_plan_adds_contract_fields_and_scaffolds_recipe(tmp_path: Path) -> None:
    _seed_source_wiki(tmp_path)
    changes = plan_source_migration(tmp_path, _config(), today=dt.date(2026, 7, 3))
    by_rel = {c.rel: c for c in changes}

    src = by_rel["memories/sources/methodology.md"]
    assert src.add_frontmatter["platform"] == "repo"
    assert src.add_frontmatter["source_locator"] == "memories/sources/methodology.md"
    # Owner inherited from the governing config page (never fabricated).
    assert src.add_frontmatter["owner"] == "root-entity"
    assert src.add_frontmatter["sync"]["last_status"] == "never"

    cfg = by_rel["memories/sources/config/methodology.md"]
    assert cfg.append_recipe
    # The config inherits the entity's platform/locator, not a bare "manual" guess.
    mapping = extract_recipe_mapping(cfg.append_recipe)
    assert parse_recipe(mapping).platform == "repo"


def test_apply_is_idempotent(tmp_path: Path) -> None:
    _seed_source_wiki(tmp_path)
    config = _config()
    for change in plan_source_migration(tmp_path, config, today=dt.date(2026, 7, 3)):
        apply_change(tmp_path, change)
    # Second plan on the migrated wiki is empty — nothing left to add.
    assert plan_source_migration(tmp_path, config, today=dt.date(2026, 7, 3)) == []
    # The applied recipe round-trips through the validator.
    text = (tmp_path / "memories/sources/config/methodology.md").read_text(encoding="utf-8")
    recipe = parse_recipe(extract_recipe_mapping(text))
    assert validate_recipe(recipe) == []


def test_plan_never_overwrites_existing_values(tmp_path: Path) -> None:
    (tmp_path / "memories/sources").mkdir(parents=True)
    (tmp_path / "memories/sources/x.md").write_text(
        "---\n"
        "page_id: sources-x\n"
        "page_type: source\n"
        "platform: slack\n"
        "source_locator: C0123\n"
        "owner: someone\n"
        "sync:\n  last_status: ok\n"
        "---\n\n# X\n",
        encoding="utf-8",
    )
    changes = plan_source_migration(tmp_path, _config(), today=dt.date(2026, 7, 3))
    # Fully-specified source needs no changes.
    assert changes == []
