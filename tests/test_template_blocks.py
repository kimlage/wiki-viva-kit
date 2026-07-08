from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path

from wiki_core.config import load_config
from wiki_core.template_blocks import (
    build_block_stacks_payload,
    build_blocks_payload,
    interview_spec,
    load_block_world,
    resolve_stack,
    validate_blocks,
)

KIT_ROOT = Path(__file__).resolve().parents[1]
TODAY = dt.date(2026, 7, 6)


def _wiki(tmp_path: Path, pages: dict[str, str]) -> Path:
    """A minimal wiki using the KIT's v2 contracts + the given pages."""
    for name in ("wiki.templates.yaml", "wiki.page-types.yaml"):
        shutil.copy(KIT_ROOT / name, tmp_path / name)
    (tmp_path / "wiki.config.yaml").write_text("repo_id: demo\nlanguage: en\n", encoding="utf-8")
    for rel, text in pages.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def _world(tmp_path: Path):
    return load_block_world(tmp_path, load_config(tmp_path), today=TODAY)


def test_kit_blocks_load_and_validate_clean() -> None:
    world = load_block_world(KIT_ROOT, today=TODAY)
    assert world.blocks  # the v2 registry has blocks
    assert validate_blocks(world) == []


def test_stack_origin_and_nearest_ring_wins(tmp_path: Path) -> None:
    root = _wiki(
        tmp_path,
        {
            "memories/index.md": (
                "---\npage_id: root-demo\npage_type: root_entity\ntitle: Root\n"
                "context: demo\nvisibility: private_self\nupdated_at: 2026-06-01\n"
                "stale_after_days: 30\n---\n# Root\n"
            ),
            "memories/team/index.md": (
                "---\npage_id: holon-team\npage_type: holon\ntitle: Team\n"
                "context: demo\nvisibility: private_self\nupdated_at: 2026-06-01\n"
                "stale_after_days: 30\nmoc_parent: memories/index.md\n"
                "blocks:\n  - id: wiki.block.quadrants.v1\n    config:\n      labels: { q3: Rituals }\n---\n# Team\n"
            ),
        },
    )
    world = _world(root)
    stack = resolve_stack(world, world.by_id["holon-team"])
    quad = next(entry for entry in stack if entry["id"] == "wiki.block.quadrants.v1")
    # The nearest ring (the team's own frontmatter) wins config + origin.
    assert quad["origin"] == "page"
    assert quad["config"]["labels"]["q3"] == "Rituals"
    # Privacy inherited from the root reaches the team (a descendant).
    assert any(entry["id"] == "wiki.block.privacy_boundary.v1" for entry in stack)


def test_quadrant_assignments_cover_all_lenses_and_core(tmp_path: Path) -> None:
    pages = {
        "memories/index.md": (
            "---\npage_id: root-demo\npage_type: root_entity\ntitle: Root\ncontext: demo\n"
            "visibility: private_self\nupdated_at: 2026-06-01\nstale_after_days: 30\n"
            "blocks:\n  - id: wiki.block.quadrants.v1\n"
            "    config: { nested_mode: project_all }\n---\n# Root\n"
        ),
        # q1 (decision), q2 (artifact/source/index), q3 (person), q4 (template/system)
        "memories/decisions/d.md": _leaf("dec-1", "decision"),
        "memories/artifacts/a.md": _leaf("art-1", "artifact"),
        "memories/people/p.md": _leaf("per-1", "person"),
        "memories/sources/s.md": _leaf("src-1", "source"),
        "memories/idx.md": _leaf("idx-1", "ontology_index"),
        "memories/system/blocks/b.md": _leaf("block-1", "template_block"),
        # multi-quadrant via observed_quadrants
        "memories/multi.md": _leaf("multi-1", "claim", extra="observed_quadrants: [q1, q4]\n"),
    }
    world = _world(_wiki(tmp_path, pages))
    rec = build_block_stacks_payload(world)["anchors"]["root-demo"]
    q = rec["derived"]["quadrant_assignments"]
    assert "dec-1" in q["q1"]
    assert "art-1" in q["q2"]
    assert "per-1" in q["q3"]
    assert "src-1" in q["q2"]
    assert "idx-1" in q["q2"]
    assert "block-1" in q["q4"]
    assert q["q0_core"] == []
    # multi-quadrant page appears in both declared lenses.
    assert "multi-1" in q["q1"] and "multi-1" in q["q4"]
    # sub-lens interior is populated (person -> pessoas).
    assert "per-1" in rec["derived"]["quadrant_sub_lens"]["q3"]["pessoas"]


def test_region_groups_and_visual_grammar_are_resolved_from_templates(tmp_path: Path) -> None:
    pages = {
        "memories/index.md": (
            "---\npage_id: root-demo\npage_type: root_entity\ntitle: Root\ncontext: demo\n"
            "visibility: private_self\nupdated_at: 2026-06-01\nstale_after_days: 30\n"
            "blocks:\n  - id: wiki.block.quadrants.v1\n  - id: wiki.block.ui_regions.v1\n"
            "    config: { visual_pack: region_operations }\n---\n# Root\n"
        ),
        "memories/actions/a.md": _leaf("act-1", "action", extra="status: open\n"),
        "memories/claims/c.md": _leaf("claim-1", "claim", extra="updated_at: 2026-03-01\n"),
        "memories/sources/s.md": _leaf("src-1", "source"),
    }
    world = _world(_wiki(tmp_path, pages))
    record = build_block_stacks_payload(world)["anchors"]["root-demo"]

    assert record["visual_grammar"]["default_pack"] == "region_operations"
    region_groups = record["derived"]["region_groups"]["groups"]
    pratica = next(group for group in region_groups if group["label_key"] == "pratica")
    intencao = next(group for group in region_groups if group["label_key"] == "intencao")

    assert pratica["summary"]["raw"] == 1
    assert pratica["summary"]["open_actions"] == 1
    assert pratica["visual"]["pack_id"] == "evidence_first"
    assert intencao["summary"]["stale"] == 1
    assert any(hint["kind"] == "refresh" for hint in intencao["action_hints"])
    assert "region.card" in pratica["visual"]["slots"]

    blocks = build_blocks_payload(world)
    vocab = blocks["vocabulary"]
    assert "region_card" in vocab["visual_primitives"]
    assert "region_operations" in vocab["visual_primitive_packs"]


def test_explicit_quadrant_frontmatter_wins_over_page_type_default(tmp_path: Path) -> None:
    pages = {
        "memories/index.md": (
            "---\npage_id: root-demo\npage_type: root_entity\ntitle: Root\ncontext: demo\n"
            "visibility: private_self\nupdated_at: 2026-06-01\nstale_after_days: 30\n"
            "blocks:\n  - id: wiki.block.quadrants.v1\n---\n# Root\n"
        ),
        "memories/perspectives/artifacts.md": _leaf("perspective-artifacts", "perspective", extra="quadrant: q2\n"),
        "memories/perspectives/roles.md": _leaf("perspective-roles", "perspective", extra="quadrant: q3\n"),
        "memories/perspectives/systems.md": _leaf("perspective-systems", "perspective", extra="quadrant: q4\n"),
        "memories/perspectives/boundary.md": _leaf("perspective-boundary", "perspective", extra="quadrant: boundary\n"),
    }
    rec = build_block_stacks_payload(_world(_wiki(tmp_path, pages)))["anchors"]["root-demo"]
    q = rec["derived"]["quadrant_assignments"]
    assert "perspective-artifacts" in q["q2"]
    assert "perspective-roles" in q["q3"]
    assert "perspective-systems" in q["q4"]
    # Non-AQAL boundary lenses remain topical perspective pages and use the type default.
    assert "perspective-boundary" in q["q1"]


def test_nested_person_root_is_own_anchor_but_parent_q3_relation(tmp_path: Path) -> None:
    pages = {
        "memories/index.md": (
            "---\npage_id: root-demo\npage_type: root_entity\ntitle: Root\ncontext: demo\n"
            "visibility: private_self\nupdated_at: 2026-06-01\nstale_after_days: 30\n"
            "blocks:\n  - id: wiki.block.quadrants.v1\n  - id: wiki.block.relations.v1\n---\n# Root\n"
        ),
        "memories/people/bea.md": (
            "---\npage_id: person-bea\npage_type: root_entity\ntitle: Bea\ncontext: demo\n"
            "visibility: private_self\nupdated_at: 2026-06-01\nstale_after_days: 30\n"
            "moc_parent: memories/index.md\nroot_entity_type: person\n"
            "relationship:\n  kind: partner\n  contact_cadence_days: 10\n---\n# Bea\n"
        ),
    }
    rec = build_block_stacks_payload(_world(_wiki(tmp_path, pages)))["anchors"]["root-demo"]
    q = rec["derived"]["quadrant_assignments"]
    assert "person-bea" in q["q3"]
    assert "person-bea" not in q["q0_core"]
    assert "person-bea" in rec["derived"]["quadrant_sub_lens"]["q3"]["pessoas"]
    assert rec["derived"]["relations"]["due"][0]["person"] == "person-bea"


def test_nested_company_projects_as_q4_for_parent_but_q1_inside_company(tmp_path: Path) -> None:
    pages = {
        "memories/index.md": (
            "---\npage_id: root-demo\npage_type: root_entity\ntitle: Root\ncontext: demo\n"
            "visibility: private_self\nupdated_at: 2026-06-01\nstale_after_days: 30\n"
            "blocks:\n  - id: wiki.block.quadrants.v1\n"
            "    config: { nested_mode: project_all }\n---\n# Root\n"
        ),
        "memories/companies/acme.md": (
            "---\npage_id: company-acme\npage_type: root_entity\ntitle: ACME\ncontext: demo\n"
            "visibility: private_self\nupdated_at: 2026-06-01\nstale_after_days: 30\n"
            "moc_parent: memories/index.md\nroot_entity_type: company\n"
            "blocks:\n  - id: wiki.block.quadrants.v1\n"
            "    config: { nested_mode: project_all }\n---\n# ACME\n"
        ),
        "memories/companies/acme/intent.md": (
            "---\npage_id: company-acme-intent\npage_type: claim\ntitle: ACME intent\ncontext: demo\n"
            "visibility: private_self\nupdated_at: 2026-06-01\nstale_after_days: 30\n"
            "moc_parent: memories/companies/acme.md\nsubject_ref: company-acme\n"
            "subject_role: perception\n---\n# ACME intent\n"
        ),
        "memories/companies/acme/process.md": (
            "---\npage_id: company-acme-process\npage_type: process\ntitle: ACME process\ncontext: demo\n"
            "visibility: private_self\nupdated_at: 2026-06-01\nstale_after_days: 30\n"
            "moc_parent: memories/companies/acme.md\n---\n# ACME process\n"
        ),
        "memories/companies/acme/product.md": (
            "---\npage_id: product-nebula\npage_type: root_entity\ntitle: Nebula Product\ncontext: demo\n"
            "visibility: private_self\nupdated_at: 2026-06-01\nstale_after_days: 30\n"
            "moc_parent: memories/companies/acme.md\nroot_entity_type: product\n"
            "blocks:\n  - id: wiki.block.quadrants.v1\n---\n# Nebula Product\n"
        ),
        "memories/companies/acme/product/intent.md": (
            "---\npage_id: product-nebula-intent\npage_type: claim\ntitle: Nebula intent\ncontext: demo\n"
            "visibility: private_self\nupdated_at: 2026-06-01\nstale_after_days: 30\n"
            "moc_parent: memories/companies/acme/product.md\nsubject_ref: product-nebula\n"
            "subject_role: perception\n---\n# Nebula intent\n"
        ),
    }
    payload = build_block_stacks_payload(_world(_wiki(tmp_path, pages)))

    root_record = payload["anchors"]["root-demo"]
    root_q = root_record["derived"]["quadrant_assignments"]
    assert "company-acme" in root_q["q4"]
    assert "company-acme-intent" in root_q["q4"]
    assert "product-nebula-intent" in root_q["q4"]
    projection = root_record["derived"]["quadrant_projections"]["company-acme-intent"][0]
    assert projection["basis"] == "subject_nested_center_projection"
    assert projection["subject_center"] == "company-acme"
    assert projection["quadrant"] == "q4"
    assert projection["local_quadrant_under_subject"] == "q1"
    product_projection_from_root = root_record["derived"]["quadrant_projections"]["product-nebula-intent"][0]
    assert product_projection_from_root["subject_center"] == "company-acme"
    assert product_projection_from_root["quadrant"] == "q4"
    assert product_projection_from_root["local_quadrant_under_subject"] == "q1"

    company_record = payload["anchors"]["company-acme"]
    company_q = company_record["derived"]["quadrant_assignments"]
    assert "company-acme-intent" in company_q["q1"]
    assert "company-acme-process" in company_q["q4"]
    assert "product-nebula-intent" in company_q["q2"]
    product_projection_from_company = company_record["derived"]["quadrant_projections"]["product-nebula-intent"][0]
    assert product_projection_from_company["subject_center"] == "product-nebula"
    assert product_projection_from_company["local_quadrant_under_subject"] == "q1"
    assert "product-nebula-intent" in payload["anchors"]["product-nebula"]["derived"]["quadrant_assignments"]["q1"]
    assert payload["anchor_tree"]["nodes"]["company-acme"]["parent"] == "root-demo"
    assert payload["anchor_tree"]["nodes"]["product-nebula"]["parent"] == "company-acme"


def test_nested_mode_summarize_keeps_parent_map_to_enterable_centers(tmp_path: Path) -> None:
    pages = {
        "memories/index.md": (
            "---\npage_id: root-demo\npage_type: root_entity\ntitle: Root\ncontext: demo\n"
            "visibility: private_self\nupdated_at: 2026-06-01\nstale_after_days: 30\n"
            "blocks:\n  - id: wiki.block.quadrants.v1\n---\n# Root\n"
        ),
        "memories/companies/acme.md": (
            "---\npage_id: company-acme\npage_type: root_entity\ntitle: ACME\ncontext: demo\n"
            "visibility: private_self\nupdated_at: 2026-06-01\nstale_after_days: 30\n"
            "moc_parent: memories/index.md\nroot_entity_type: company\n"
            "blocks:\n  - id: wiki.block.quadrants.v1\n---\n# ACME\n"
        ),
        "memories/companies/acme/intent.md": (
            "---\npage_id: company-acme-intent\npage_type: claim\ntitle: ACME intent\ncontext: demo\n"
            "visibility: private_self\nupdated_at: 2026-06-01\nstale_after_days: 30\n"
            "moc_parent: memories/companies/acme.md\nsubject_ref: company-acme\n"
            "subject_role: perception\n---\n# ACME intent\n"
        ),
    }
    payload = build_block_stacks_payload(_world(_wiki(tmp_path, pages)))

    root_record = payload["anchors"]["root-demo"]
    assert root_record["derived"]["quadrant_nested_mode"] == "summarize"
    assert "company-acme" in root_record["derived"]["quadrant_assignments"]["q4"]
    assert "company-acme-intent" not in root_record["derived"]["quadrant_assignments"]["q4"]
    assert "company-acme-intent" in payload["anchors"]["company-acme"]["derived"]["quadrant_assignments"]["q1"]


def test_subject_ref_projects_cross_folder_claim_through_nested_center(tmp_path: Path) -> None:
    pages = {
        "memories/index.md": (
            "---\npage_id: root-demo\npage_type: root_entity\ntitle: Root\ncontext: demo\n"
            "visibility: private_self\nupdated_at: 2026-06-01\nstale_after_days: 30\n"
            "blocks:\n  - id: wiki.block.quadrants.v1\n"
            "    config: { nested_mode: project_all }\n---\n# Root\n"
        ),
        "memories/companies/acme.md": (
            "---\npage_id: company-acme\npage_type: root_entity\ntitle: ACME\ncontext: demo\n"
            "visibility: private_self\nupdated_at: 2026-06-01\nstale_after_days: 30\n"
            "moc_parent: memories/index.md\nroot_entity_type: company\n"
            "blocks:\n  - id: wiki.block.quadrants.v1\n---\n# ACME\n"
        ),
        "memories/claims/acme-market.md": (
            "---\npage_id: claim-acme-market\npage_type: claim\ntitle: ACME market signal\ncontext: demo\n"
            "visibility: private_self\nupdated_at: 2026-06-01\nstale_after_days: 30\n"
            "moc_parent: memories/index.md\nsource_refs: []\nsubject_ref: company-acme\n"
            "subject_role: goal\n---\n# ACME market signal\n"
        ),
    }
    payload = build_block_stacks_payload(_world(_wiki(tmp_path, pages)))

    root_projection = payload["anchors"]["root-demo"]["derived"]["quadrant_projections"]["claim-acme-market"][0]
    assert root_projection["quadrant"] == "q4"
    assert root_projection["basis"] == "subject_nested_center_projection"
    assert root_projection["subject_center"] == "company-acme"
    assert root_projection["local_quadrant_under_subject"] == "q1"
    company_projection = payload["anchors"]["company-acme"]["derived"]["quadrant_projections"]["claim-acme-market"][0]
    assert company_projection["quadrant"] == "q1"
    assert company_projection["basis"] == "subject_role"


def test_projection_override_wins_for_specific_parent_center(tmp_path: Path) -> None:
    pages = {
        "memories/index.md": (
            "---\npage_id: root-demo\npage_type: root_entity\ntitle: Root\ncontext: demo\n"
            "visibility: private_self\nupdated_at: 2026-06-01\nstale_after_days: 30\n"
            "blocks:\n  - id: wiki.block.quadrants.v1\n"
            "    config: { nested_mode: project_all }\n---\n# Root\n"
        ),
        "memories/companies/acme.md": (
            "---\npage_id: company-acme\npage_type: root_entity\ntitle: ACME\ncontext: demo\n"
            "visibility: private_self\nupdated_at: 2026-06-01\nstale_after_days: 30\n"
            "moc_parent: memories/index.md\nroot_entity_type: company\n"
            "blocks:\n  - id: wiki.block.quadrants.v1\n---\n# ACME\n"
        ),
        "memories/companies/acme/action.md": (
            "---\npage_id: company-acme-action\npage_type: action\ntitle: ACME action\ncontext: demo\n"
            "visibility: private_self\nupdated_at: 2026-06-01\nstale_after_days: 30\n"
            "moc_parent: memories/companies/acme.md\n"
            "projection_overrides:\n  root-demo:\n    quadrant: q3\n    sub_lens: rede\n"
            "    reason: Relationship-facing parent concern\n---\n# ACME action\n"
        ),
    }
    payload = build_block_stacks_payload(_world(_wiki(tmp_path, pages)))

    root_projection = payload["anchors"]["root-demo"]["derived"]["quadrant_projections"]["company-acme-action"][0]
    assert root_projection["quadrant"] == "q3"
    assert root_projection["sub_lens"] == "rede"
    assert root_projection["basis"] == "projection_override"

    company_record = payload["anchors"]["company-acme"]
    assert "company-acme-action" in company_record["derived"]["quadrant_assignments"]["q2"]


def test_relations_flags_overdue_contact(tmp_path: Path) -> None:
    pages = {
        "memories/index.md": (
            "---\npage_id: root-demo\npage_type: root_entity\ntitle: Root\ncontext: demo\n"
            "visibility: private_self\nupdated_at: 2026-06-01\nstale_after_days: 30\n"
            "blocks:\n  - id: wiki.block.relations.v1\n---\n# Root\n"
        ),
        "memories/people/marina.md": (
            "---\npage_id: person-marina\npage_type: person\ntitle: Marina\ncontext: demo\n"
            "visibility: private_self\nupdated_at: 2026-06-01\nstale_after_days: 45\n"
            "moc_parent: memories/index.md\n"
            "relationship:\n  kind: friend\n  contact_cadence_days: 10\n---\n# Marina\n"
        ),
    }
    world = _world(_wiki(tmp_path, pages))
    rec = build_block_stacks_payload(world)["anchors"]["root-demo"]
    due = rec["derived"]["relations"]["due"]
    assert due and due[0]["person"] == "person-marina"
    assert any(m["provider"] == "relation_cadence_overdue" for m in rec["derived"]["missions"])


def test_validation_flags_unknown_block_and_non_anchor(tmp_path: Path) -> None:
    pages = {
        "memories/index.md": (
            "---\npage_id: root-demo\npage_type: root_entity\ntitle: Root\ncontext: demo\n"
            "visibility: private_self\nupdated_at: 2026-06-01\nstale_after_days: 30\n"
            "blocks:\n  - id: wiki.block.does_not_exist.v1\n---\n# Root\n"
        ),
        # person is NOT an anchor type — attaching blocks must be flagged.
        "memories/people/p.md": (
            "---\npage_id: person-x\npage_type: person\ntitle: X\ncontext: demo\n"
            "visibility: private_self\nupdated_at: 2026-06-01\nstale_after_days: 45\n"
            "moc_parent: memories/index.md\n"
            "blocks:\n  - id: wiki.block.quadrants.v1\n---\n# X\n"
        ),
    }
    world = _world(_wiki(tmp_path, pages))
    warnings = " | ".join(validate_blocks(world))
    assert "does_not_exist" in warnings
    assert "cannot anchor blocks" in warnings


def test_validation_flags_unknown_visual_primitive(tmp_path: Path) -> None:
    pages = {
        "memories/index.md": (
            "---\npage_id: root-demo\npage_type: root_entity\ntitle: Root\ncontext: demo\n"
            "visibility: private_self\nupdated_at: 2026-06-01\nstale_after_days: 30\n"
            "blocks:\n"
            "  - id: wiki.block.ui_regions.v1\n"
            "    config:\n"
            "      visual_pack: region_operations\n"
            "      packs:\n"
            "        region_operations:\n"
            "          slots:\n"
            "            region.card: made_up_card\n"
            "---\n# Root\n"
        ),
    }
    warnings = " | ".join(validate_blocks(_world(_wiki(tmp_path, pages))))
    assert "made_up_card" in warnings
    assert "unknown visual primitive" in warnings


def test_snapshot_payload_is_deterministic(tmp_path: Path) -> None:
    pages = {
        "memories/index.md": (
            "---\npage_id: root-demo\npage_type: root_entity\ntitle: Root\ncontext: demo\n"
            "visibility: private_self\nupdated_at: 2026-06-01\nstale_after_days: 30\n---\n# Root\n"
        ),
        "memories/decisions/d.md": _leaf("dec-1", "decision"),
    }
    root = _wiki(tmp_path, pages)
    first = json.dumps(build_block_stacks_payload(_world(root)), sort_keys=True)
    second = json.dumps(build_block_stacks_payload(_world(root)), sort_keys=True)
    assert first == second
    payload = build_blocks_payload(_world(root))
    assert payload["schema_version"] == "wiki_web_blocks.v1"
    assert "wiki.block.quadrants.v1" in payload["blocks"]


def test_gamification_is_a_detachable_package(tmp_path: Path) -> None:
    """The stage-4→5 payoff as a unit test: without the package the world is
    quiet (no missions surface, no weather contribution); attaching the package
    on the root turns providers on — including the ones interpretation blocks
    contribute."""
    quiet_root = (
        "---\npage_id: root-demo\npage_type: root_entity\ntitle: Root\ncontext: demo\n"
        "visibility: private_self\nupdated_at: 2026-06-01\nstale_after_days: 30\n"
        "blocks:\n  - id: wiki.block.relations.v1\n---\n# Root\n"
    )
    marina = (
        "---\npage_id: person-marina\npage_type: person\ntitle: Marina\ncontext: demo\n"
        "visibility: private_self\nupdated_at: 2026-06-01\nstale_after_days: 45\n"
        "moc_parent: memories/index.md\n"
        "relationship:\n  kind: friend\n  contact_cadence_days: 10\n---\n# Marina\n"
    )
    root = _wiki(tmp_path, {"memories/index.md": quiet_root, "memories/people/m.md": marina})
    record = build_block_stacks_payload(_world(root))["anchors"]["root-demo"]
    assert record["interface"]["missions"]["active"] is False
    assert record["interface"]["missions"]["providers"] == []
    assert record["interface"]["missions"]["weather_contrib"] is False
    # The data still KNOWS (relations derive) — but nothing asks for attention.
    assert record["derived"]["relations"]["due"]

    loud_root = quiet_root.replace("---\n# Root\n", "packages:\n  - gamification\n---\n# Root\n")
    (root / "memories/index.md").write_text(loud_root, encoding="utf-8")
    record = build_block_stacks_payload(_world(root))["anchors"]["root-demo"]
    assert record["interface"]["missions"]["active"] is True
    providers = record["interface"]["missions"]["providers"]
    assert "stale" in providers  # the block's declared defaults
    assert "relation_cadence_overdue" in providers  # contributed by relations
    ids = [entry["id"] for entry in record["stack"]]
    assert "wiki.block.ui_missions.v1" in ids and "wiki.block.gamification.v1" in ids


def test_bare_root_defaults_to_radar_not_quadrants(tmp_path: Path) -> None:
    """A freshly founded root (no lenses attached) must NOT pretend to have a
    quadrant map: home view falls back to radar and quadrants is unavailable."""
    pages = {
        "memories/index.md": (
            "---\npage_id: root-demo\npage_type: root_entity\ntitle: Root\ncontext: demo\n"
            "visibility: private_self\nupdated_at: 2026-06-01\nstale_after_days: 30\n---\n# Root\n"
        ),
    }
    record = build_block_stacks_payload(_world(_wiki(tmp_path, pages)))["anchors"]["root-demo"]
    assert record["interface"]["views"]["default"] == "radar"
    assert "quadrants" not in record["interface"]["views"]["available"]
    assert record["interface"]["has_quadrants"] is False


def test_interview_spec_has_questions() -> None:
    world = load_block_world(KIT_ROOT, today=TODAY)
    spec = interview_spec(world, "person")
    assert spec["page_type"] == "person"
    assert spec["questions"]


def test_block_context_package_carries_combined_lenses(tmp_path: Path) -> None:
    from wiki_core.template_blocks import block_context_package

    pages = {
        "memories/index.md": (
            "---\npage_id: root-demo\npage_type: root_entity\ntitle: Root\ncontext: demo\n"
            "visibility: private_self\nupdated_at: 2026-06-01\nstale_after_days: 30\n"
            "blocks:\n  - id: wiki.block.quadrants.v1\n"
            "  - id: wiki.block.perspective_bundle.v1\n    config:\n      required: [perspective-privacy-publication]\n---\n# Root\n"
        ),
    }
    world = _world(_wiki(tmp_path, pages))
    package = block_context_package(world, world.by_id["root-demo"])
    assert package["center"] == "root-demo"
    lenses = package["lenses"][0]["lenses"]
    # Each canonical quadrant carries a label, an operational test and a perspective.
    assert set(lenses) == {"q1", "q2", "q3", "q4"}
    assert lenses["q1"]["perspective"] == "perspective-identity-intent"
    assert lenses["q1"]["operational_test"]
    assert lenses["q1"]["sub_lenses"][0] == "percepcao"  # perception first
    assert package["write_policy"] == "proposal_branch_only"


def test_context_request_carries_block_package() -> None:
    from wiki_core.llm.context_pass import build_context_request

    request = build_context_request(
        manifest={"source_id": "src-1"},
        chunks=[],
        cache_dir=KIT_ROOT / "data" / "derived" / "wiki" / "llm-cache",
        prompt_version="v3",
        schema_version="wiki_llm_result.v3",
        model_profile="deep_context",
        block_context_package={"center": "root-demo", "stack": []},
    )
    assert request["block_context_package"]["center"] == "root-demo"


def _leaf(page_id: str, page_type: str, *, extra: str = "") -> str:
    return (
        f"---\npage_id: {page_id}\npage_type: {page_type}\ntitle: {page_id}\ncontext: demo\n"
        f"visibility: private_self\nupdated_at: 2026-06-01\nstale_after_days: 30\n"
        f"moc_parent: memories/index.md\n{extra}---\n# {page_id}\n"
    )
