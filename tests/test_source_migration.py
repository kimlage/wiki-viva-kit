from __future__ import annotations

import datetime as dt
from pathlib import Path

from wiki_core.config import WikiConfig
from wiki_core.frontmatter import parse_frontmatter_flat
from wiki_core.source_migration import (
    apply_change,
    infer_locator,
    infer_platform,
    initial_sync,
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


def test_infer_platform_prefers_specific_identity_over_coarse_legacy_type() -> None:
    assert infer_platform(
        {"source_type": "chat", "page_id": "source-whatsapp-a"}
    ) == ("whatsapp", False)
    assert infer_platform(
        {"source_type": "reference", "title": "Google Photos archive"}
    ) == ("google_photos", False)


def test_infer_locator_uses_page_path_for_repo_and_todo_for_chat() -> None:
    assert infer_locator("memories/sources/x.md", {}, "repo") == ("memories/sources/x.md", False)
    assert infer_locator("memories/sources/x.md", {"source_locator": "kept"}, "repo") == ("kept", False)
    loc, todo = infer_locator("memories/sources/x.md", {}, "slack")
    assert todo is True and loc.startswith("TODO-slack")


def test_initial_sync_preserves_versioned_ingestion_evidence() -> None:
    assert initial_sync({})["last_status"] == "never"
    assert initial_sync({"last_ingested_at": "2026-06-09"}) == {
        "last_run_at": "2026-06-09",
        "last_status": "ok",
        "last_event_ref": "",
    }
    assert initial_sync({"last_ingested_at": "2026-07-06", "ingestion_state": "partial"})[
        "last_status"
    ] == "partial"


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
    assert cfg.add_frontmatter["platform"] == "repo"
    assert cfg.append_recipe
    # The config inherits the entity's platform/locator, not a bare "manual" guess.
    mapping = extract_recipe_mapping(cfg.append_recipe)
    assert parse_recipe(mapping).platform == "repo"


def test_operational_plan_activates_linked_source_stream(tmp_path: Path) -> None:
    _seed_source_wiki(tmp_path)
    changes = plan_source_migration(
        tmp_path,
        _config(),
        today=dt.date(2026, 8, 26),
        operational_recipes=True,
    )
    config_change = next(
        change for change in changes if change.page_type == "source_config"
    )
    recipe = parse_recipe(extract_recipe_mapping(config_change.append_recipe))
    assert recipe.streams[0].id == "methodology"
    assert recipe.streams[0].selected is True
    assert recipe.streams[0].filters == {"source_ref": "sources-methodology"}
    assert validate_recipe(recipe) == []


def test_operational_plan_preserves_versioned_lifecycle_evidence(tmp_path: Path) -> None:
    _seed_source_wiki(tmp_path)
    source = tmp_path / "memories/sources/methodology.md"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "config_ref: memories/sources/config/methodology.md\n",
            "config_ref: memories/sources/config/methodology.md\n"
            "source_lifecycle:\n"
            "  last_sync_success_at: 2026-08-21\n"
            "  secret_safe_log_refs:\n"
            "    - memories/system/events/2026-08-21-methodology.md\n",
        ),
        encoding="utf-8",
    )
    changes = plan_source_migration(
        tmp_path,
        _config(),
        today=dt.date(2026, 8, 26),
        operational_recipes=True,
    )
    source_change = next(change for change in changes if change.page_type == "source")
    assert source_change.add_frontmatter["sync"] == {
        "last_run_at": "2026-08-21",
        "last_status": "ok",
        "last_event_ref": "memories/system/events/2026-08-21-methodology.md",
    }


def test_existing_recipe_keeps_body_and_pins_config_platform(tmp_path: Path) -> None:
    _seed_source_wiki(tmp_path)
    config_path = tmp_path / "memories/sources/config/methodology.md"
    original = config_path.read_text(encoding="utf-8") + "\n" + scaffold_recipe_block(
        "repo", "memories/sources/methodology.md"
    )
    config_path.write_text(original, encoding="utf-8")

    changes = plan_source_migration(tmp_path, _config(), today=dt.date(2026, 7, 3))
    cfg = next(change for change in changes if change.page_type == "source_config")

    assert cfg.add_frontmatter == {"platform": "repo"}
    assert cfg.append_recipe == ""
    apply_change(tmp_path, cfg)
    migrated = config_path.read_text(encoding="utf-8")
    assert migrated.count("```yaml") == original.count("```yaml")
    assert extract_recipe_mapping(migrated) == extract_recipe_mapping(original)


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


def test_scalar_sync_is_not_re_added_as_a_duplicate_key(tmp_path: Path) -> None:
    # A `sync` that exists but is a scalar (not a mapping) must be left alone —
    # re-adding a `sync:` mapping would produce a duplicate YAML key.
    (tmp_path / "memories/sources").mkdir(parents=True)
    (tmp_path / "memories/sources/x.md").write_text(
        "---\npage_id: sources-x\npage_type: source\nplatform: slack\n"
        "source_locator: C1\nowner: me\nsync: pending\n---\n\n# X\n",
        encoding="utf-8",
    )
    changes = plan_source_migration(tmp_path, _config(), today=dt.date(2026, 7, 3))
    # Nothing to add: every contract field is present (sync is present-but-scalar).
    assert [c for c in changes if c.add_frontmatter] == []


def test_insert_frontmatter_keys_drops_keys_already_present(tmp_path: Path) -> None:
    text = "---\npage_id: a\nplatform: slack\n---\n\n# Body\n"
    # platform already present → never appended (no duplicate); owner is added.
    out = insert_frontmatter_keys(text, {"platform": "repo", "owner": "me"})
    assert out.count("platform:") == 1
    assert "owner: me" in out
    assert parse_frontmatter_flat(out)["platform"] == "slack"  # original value kept


def test_config_ref_traversal_is_refused(tmp_path: Path) -> None:
    # A source whose config_ref escapes the repo must not read the outside file.
    (tmp_path / "memories/sources").mkdir(parents=True)
    (tmp_path / "secret.md").write_text("owner: leaked\n", encoding="utf-8")
    (tmp_path / "memories/sources/x.md").write_text(
        "---\npage_id: sources-x\npage_type: source\nsource_type: reference\n"
        "config_ref: ../../secret.md\n---\n\n# X\n",
        encoding="utf-8",
    )
    change = next(
        c for c in plan_source_migration(tmp_path, _config(), today=dt.date(2026, 7, 3))
        if c.rel.endswith("x.md")
    )
    # owner could not be inferred from the (refused) outside file → noted, not leaked.
    assert change.add_frontmatter.get("owner") != "leaked"


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
