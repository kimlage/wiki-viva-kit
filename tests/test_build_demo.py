from __future__ import annotations

import importlib.util
import json
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE = KIT_ROOT / "apps/wiki-cockpit/public/sample-snapshot"
DENSE_SAMPLE = SAMPLE / "scenarios/dense_stress"


def _demo_module():
    spec = importlib.util.spec_from_file_location(
        "wiki_build_demo", KIT_ROOT / "scripts/wiki_build_demo.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_stage_fixtures_are_monotonic_subsets(tmp_path: Path) -> None:
    demo = _demo_module()
    previous: set[str] = set()
    for stage in range(demo.FINAL_STAGE + 1):
        target = tmp_path / str(stage)
        target.mkdir()
        ids = set(demo.write_fixture(target, stage))
        assert previous <= ids, f"stage {stage} lost pages from stage {stage - 1}"
        previous = ids
    # The final stage is the full cast.
    full = tmp_path / "full"
    full.mkdir()
    assert set(demo.write_fixture(full, demo.FINAL_STAGE)) == previous


def test_root_attachments_grow_with_the_arc() -> None:
    demo = _demo_module()
    assert demo.root_attachments(1) == {}
    stage2 = demo.root_attachments(2)
    assert [b["id"] for b in stage2["blocks"]] == ["wiki.block.quadrants.v1"]
    stage4 = demo.root_attachments(4)
    assert "wiki.block.relations.v1" in [b["id"] for b in stage4["blocks"]]
    assert "packages" not in stage4  # stage 4 is QUIET on purpose
    stage5 = demo.root_attachments(5)
    assert stage5["packages"] == ["gamification"]


def test_v8_scenario_registry_is_executable_and_complete() -> None:
    demo = _demo_module()
    manifests = demo.load_scenario_manifests()
    assert tuple(manifests) == demo.REQUIRED_SCENARIOS

    for scenario_id, manifest in manifests.items():
        page_ids = demo.scenario_page_ids(scenario_id, manifests=manifests)
        assert page_ids
        assert len(page_ids) == manifest["expected"]["page_count"]
        assert demo.page_id_hash(page_ids) == manifest["expected"]["page_id_sha256"]
        assert manifest["builder"]["module"] == "scripts/wiki_build_demo.py"
        assert manifest["builder"]["callable"] == "build_scenario_pages"
        assert manifest["canonical_routes"]
        assert manifest["interactions"]
        assert manifest["automated_assertions"]
        assert manifest["visual"]["viewports"]
        assert manifest["visual"]["browser_projects"]
        assert manifest["generated_files"]
        assert manifest["regeneration_command"].endswith("scripts/wiki_build_demo.py")
        assert {
            front["page_id"] for _, front, _ in demo.build_scenario_pages(scenario_id)
        } == set(page_ids)

    dense_ids = demo.scenario_page_ids("dense_stress", manifests=manifests)
    normal_ids = demo.scenario_page_ids("normal_operations", manifests=manifests)
    assert len(dense_ids) > 350  # forces the explicit mobile compact threshold
    assert any(page_id.startswith("artifact-region-pressure-") for page_id in dense_ids)
    assert not any("-region-pressure-" in page_id for page_id in normal_ids)


def test_snapshot_generation_is_byte_deterministic(tmp_path: Path) -> None:
    demo = _demo_module()
    first_fixture = tmp_path / "first-fixture"
    second_fixture = tmp_path / "second-fixture"
    first_out = tmp_path / "first-out"
    second_out = tmp_path / "second-out"

    demo.write_fixture(first_fixture, stage=1)
    demo.write_fixture(second_fixture, stage=1)
    demo._write_snapshot_deterministic(first_fixture, first_out, stage=1)
    demo._write_snapshot_deterministic(second_fixture, second_out, stage=1)

    assert demo._fixture_file_map(first_fixture) == demo._fixture_file_map(
        second_fixture
    )
    assert demo._tree_file_map(first_out) == demo._tree_file_map(second_out)
    manifest = json.loads((first_out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["generated_at"] == demo.DEMO_GENERATED_AT
    assert manifest["source_commit"] is None
    assert manifest["fixture"] == {
        "fixture_id": demo.DEMO_FIXTURE_ID,
        "scenario_id": "walking_skeleton",
        "scenario_ids": list(demo.REQUIRED_SCENARIOS),
        "seed": 8001,
        "source_input_sha256": demo.source_input_hash(first_fixture),
        "reference_date": demo.DEMO_REFERENCE_DATE.isoformat(),
        "genesis_stage": 1,
    }


def test_check_mode_regenerates_in_temp_and_never_mutates_targets(
    tmp_path: Path, monkeypatch
) -> None:
    demo = _demo_module()
    committed_fixture = tmp_path / "fixture"
    committed_out = tmp_path / "snapshot"
    state = {"drift": False}

    def fake_build_demo(fixture_dir: Path, out_dir: Path) -> dict:
        memories = fixture_dir / "memories"
        memories.mkdir(parents=True)
        (memories / "index.md").write_text("stable fixture\n", encoding="utf-8")
        for name in demo.GENERATED_FIXTURE_CONFIGS:
            (fixture_dir / name).write_text(f"{name}\n", encoding="utf-8")
        out_dir.mkdir(parents=True)
        value = "drift\n" if state["drift"] else "stable snapshot\n"
        (out_dir / "manifest.json").write_text(value, encoding="utf-8")
        return {}

    fake_build_demo(committed_fixture, committed_out)
    before_fixture = demo._fixture_file_map(committed_fixture)
    before_out = demo._tree_file_map(committed_out)
    monkeypatch.setattr(demo, "FIXTURE", committed_fixture)
    monkeypatch.setattr(demo, "OUT", committed_out)
    monkeypatch.setattr(demo, "build_demo", fake_build_demo)

    assert demo.main(["--check"]) == 0
    assert demo._fixture_file_map(committed_fixture) == before_fixture
    assert demo._tree_file_map(committed_out) == before_out

    state["drift"] = True
    assert demo.main(["--check"]) == 1
    assert demo._fixture_file_map(committed_fixture) == before_fixture
    assert demo._tree_file_map(committed_out) == before_out


def test_committed_stage_snapshots_are_consistent() -> None:
    """The committed artifacts (what the tutorial actually loads) must hold the
    contract: monotonic page subsets, stage arc materializing the interface,
    final stage identical to the default instructional demo."""
    stages_dir = SAMPLE / "stages"
    manifest = json.loads((stages_dir / "stages.json").read_text(encoding="utf-8"))
    final = manifest["final_stage"]
    previous: set[str] = set()
    for entry in manifest["stages"]:
        stage_dir = SAMPLE / entry["dir"]
        pages = json.loads((stage_dir / "pages.json").read_text(encoding="utf-8"))
        ids = {page["id"] for page in pages["pages"]}
        assert previous <= ids
        previous = ids
        assert (stage_dir / "block_stacks.json").exists()
    # Final stage == default normal_operations demo (same page set).
    full_pages = json.loads((SAMPLE / "pages.json").read_text(encoding="utf-8"))
    assert previous == {page["id"] for page in full_pages["pages"]}

    # The tutorial's dramatic beats, straight from the artifacts:
    def root_ui(stage: int) -> dict:
        payload = json.loads(
            (SAMPLE / f"stages/{stage}/block_stacks.json").read_text(encoding="utf-8")
        )
        return payload["anchors"]["root-alex-rivera"]

    assert (
        root_ui(1)["interface"]["views"]["default"] == "radar"
    )  # bare root: no quadrant map
    assert root_ui(2)["interface"]["has_quadrants"] is True  # lenses attach
    assert root_ui(4)["interface"]["missions"]["active"] is False  # world knows...
    assert root_ui(4)["derived"]["relations"]["due"]  # ...Marina is overdue
    assert root_ui(5)["interface"]["missions"]["active"] is True  # ...and now it asks
    assert final == 8

    final_blocks = json.loads(
        (SAMPLE / "block_stacks.json").read_text(encoding="utf-8")
    )
    anchors = final_blocks["anchors"]
    assert "block-library-lens" in anchors
    template_q = anchors["block-library-lens"]["derived"]["quadrant_assignments"]
    assert "claim-template-library-purpose" in template_q["q1"]
    assert "artifact-template-library-example" in template_q["q2"]
    assert "meeting-template-library-review" in template_q["q3"]
    assert "process-template-library-governance" in template_q["q4"]
    system_q = anchors["hub-sistema"]["derived"]["quadrant_assignments"]
    assert "block-library-lens" in system_q["q4"]
    root_q = anchors["root-alex-rivera"]["derived"]["quadrant_assignments"]
    assert "block-library-lens" not in root_q["q4"]
    assert "claim-template-library-purpose" not in root_q["q1"]
    company_q = anchors["company-clearpath-labs"]["derived"]["quadrant_assignments"]
    assert "claim-clearpath-market-signal" in company_q["q1"]
    assert "source-clearpath-customer-interviews" in company_q["q2"]
    assert "dashboard-clearpath-activation" in company_q["q2"]
    assert "role-clearpath-customer-success-lead" in company_q["q3"]
    assert "rule-clearpath-release-gate" in company_q["q4"]

    # The instructional fixture must exercise the collection contract itself,
    # not only ship compiler unit tests for downstream consumers.
    decision_ids = {
        page["id"]
        for page in full_pages["pages"]
        if page["page_type"] == "decision"
    }
    decision_q = anchors["idx-decisoes"]["derived"]["quadrant_assignments"]
    assert set(decision_q["q1"]) == decision_ids
    assert decision_q["q0_core"] == []
    graph = json.loads((SAMPLE / "graph.json").read_text(encoding="utf-8"))
    collection_sources = {
        edge["source"]
        for edge in graph["edges"]
        if edge["type"] == "collection_member"
        and edge["target"] == "idx-decisoes"
    }
    assert collection_sources == decision_ids


def test_committed_default_and_dense_snapshots_match_scenario_manifests() -> None:
    demo = _demo_module()
    manifests = demo.load_scenario_manifests()

    normal_pages = json.loads((SAMPLE / "pages.json").read_text(encoding="utf-8"))
    normal_ids = {row["id"] for row in normal_pages["pages"]}
    normal_manifest = json.loads((SAMPLE / "manifest.json").read_text(encoding="utf-8"))
    assert normal_ids == set(demo.scenario_page_ids("normal_operations", manifests=manifests))
    assert len(normal_ids) == manifests["normal_operations"]["expected"]["page_count"]
    assert not any("-region-pressure-" in page_id for page_id in normal_ids)
    assert normal_manifest["fixture"]["scenario_id"] == "normal_operations"
    assert normal_manifest["fixture"]["seed"] == manifests["normal_operations"]["seed"]

    dense_pages = json.loads((DENSE_SAMPLE / "pages.json").read_text(encoding="utf-8"))
    dense_ids = {row["id"] for row in dense_pages["pages"]}
    dense_manifest = json.loads((DENSE_SAMPLE / "manifest.json").read_text(encoding="utf-8"))
    assert dense_ids == set(demo.scenario_page_ids("dense_stress", manifests=manifests))
    assert len(dense_ids) == manifests["dense_stress"]["expected"]["page_count"]
    assert any(page_id.startswith("artifact-region-pressure-") for page_id in dense_ids)
    assert dense_manifest["fixture"]["scenario_id"] == "dense_stress"
    assert dense_manifest["fixture"]["seed"] == manifests["dense_stress"]["seed"]


def test_committed_source_lifecycle_fixture_covers_every_contract_axis() -> None:
    payload = json.loads((SAMPLE / "source_lifecycle.json").read_text(encoding="utf-8"))
    sources = payload["sources"]
    assert {row["lifecycle_state"] for row in sources} >= {
        "configured",
        "ready",
        "syncing",
        "proposed",
        "consolidated",
        "ingested",
        "blocked",
    }
    assert {row["freshness_state"] for row in sources} >= {
        "fresh",
        "stale",
        "never_synced",
    }
    assert {row["last_attempt_state"] for row in sources} >= {
        "ok",
        "failed",
        "needs_auth",
        "parser_error",
        "secret_blocked",
    }
    for row in sources:
        assert set(row) >= {
            "source_id",
            "lifecycle_state",
            "freshness_state",
            "last_attempt_state",
            "last_sync_success_at",
            "last_ingested_at",
            "last_attempt_at",
            "pipeline_stage",
            "pipeline_stage_timestamps",
            "blocked_reason",
            "emitted_page_ids",
            "emitted_action_ids",
            "proposal_ids",
            "raw_artifact_count",
            "secret_safe_log_refs",
        }
        if row["lifecycle_state"] == "ingested":
            assert row["accepted_ref"]
            assert row["emitted_page_ids"] or row["reviewed_no_change_receipt"]


def test_committed_dense_actions_cover_canonical_work_contract() -> None:
    payload = json.loads((DENSE_SAMPLE / "work_items.json").read_text(encoding="utf-8"))
    actions = [
        row
        for row in payload["actions"]
        if row["action_id"].startswith("action-region-pressure-")
    ]
    assert len(actions) == 60
    assert {row["state"] for row in actions} == {
        "open",
        "in_progress",
        "blocked",
        "waiting_human",
        "done",
        "cancelled",
    }
    assert {row["owner"]["kind"] for row in actions} == {
        "human",
        "agent",
        "system",
        "other",
        "unassigned",
    }
    assert any(
        row["overdue"] for row in actions if row["state"] not in {"done", "cancelled"}
    )
    assert all(row["completion_receipt"] for row in actions if row["state"] == "done")
    assert all(
        row["cancellation_receipt"] for row in actions if row["state"] == "cancelled"
    )
    assert all(
        row["blocked_by"] and row["blocker_reason"]
        for row in actions
        if row["state"] == "blocked"
    )
    assert all(not row["contract_warnings"] for row in actions)


def test_committed_empty_regions_distinguish_identical_zero_counts() -> None:
    payload = json.loads((SAMPLE / "region_groups.json").read_text(encoding="utf-8"))
    by_key = {(row["anchor_id"], row["label_key"]): row for row in payload["groups"]}
    cases = {
        "source-action-ledger": ("required", "concerning"),
        "source-reference-folder": ("optional", "healthy"),
        "source-crm-accounts": ("not_applicable", "healthy"),
        "source-error-traces": ("unknown", "unmodeled"),
    }
    for anchor, (expectation, absence) in cases.items():
        row = by_key[(anchor, "intencao")]
        assert (
            row["summary"]["total"]
            == row["summary"]["shown"]
            == row["summary"]["hidden"]
            == 0
        )
        assert row["expectation_state"] == expectation
        assert row["absence_state"] == absence
        assert row["expectation_basis"]
        assert row["next_safe_interaction"]


def test_committed_relation_vocabulary_covers_families_diagnostics_and_provenance_trail() -> (
    None
):
    graph = json.loads((SAMPLE / "graph.json").read_text(encoding="utf-8"))
    assert graph["relation_vocabulary_version"] == "wiki_relation_types.v1"
    relation_types = {row["id"]: row for row in graph["relation_types"]}
    assert {row["family"] for row in relation_types.values()} >= {
        "hierarchy",
        "evidence",
        "source_emission",
        "dependency",
        "ownership",
        "participation",
        "citation",
        "impact",
        "temporal",
    }
    assert all(
        row["visual_line_intent"] and row["fallback"] for row in relation_types.values()
    )
    diagnostics = graph["relation_diagnostics"]
    reasons = {reason for row in diagnostics for reason in row["reasons"]}
    assert reasons >= {
        "unknown_type",
        "invalid_endpoint",
        "invalid_direction",
        "missing_provenance",
    }

    edges = {(row["source"], row["target"], row["type"]) for row in graph["edges"]}
    assert ("source-health-checks", "source-error-traces", "markdown_link") in edges
    assert ("source-error-traces", "source-health-checks", "markdown_link") in edges
    assert relation_types["markdown_link"]["allows_cycles"] is True
    assert (
        "source-product-analytics",
        "event-ingest-product-analytics-2026-07",
        "source_emission",
    ) in edges
    assert (
        "event-ingest-product-analytics-2026-07",
        "proposal-ingest-product-analytics-2026-07",
        "proposal_transition",
    ) in edges
    assert (
        "proposal-ingest-product-analytics-2026-07",
        "dashboard-clearpath-activation",
        "impact",
    ) in edges
    dense_work = json.loads(
        (DENSE_SAMPLE / "work_items.json").read_text(encoding="utf-8")
    )
    pressure = next(
        row
        for row in dense_work["actions"]
        if row["action_id"] == "action-region-pressure-001"
    )
    assert pressure["evidence_refs"] == ["dashboard-clearpath-activation"]
    assert pressure["source_refs"] == ["source-support-tickets"]


def test_committed_snapshot_warnings_cover_structural_and_source_governance_risks() -> (
    None
):
    normal_payload = json.loads(
        (SAMPLE / "snapshot_warnings.json").read_text(encoding="utf-8")
    )
    dense_payload = json.loads(
        (DENSE_SAMPLE / "snapshot_warnings.json").read_text(encoding="utf-8")
    )
    assert {row["code"] for row in normal_payload["warnings"]} >= {
        "region_expected_missing",
        "source_blocked",
    }
    assert {row["code"] for row in dense_payload["warnings"]} >= {
        "region_hidden_density",
    }
    # Bucket warnings are data-dependent: when present they must identify both
    # the canonical page and the actual derived bucket, never a CSS guess.
    for row in [*normal_payload["warnings"], *dense_payload["warnings"]]:
        if row["code"] in {"source_wrong_bucket", "governance_wrong_bucket"}:
            assert row["page_id"] and row["bucket"]


def test_committed_graph_exercises_semantic_visual_tokens_from_real_metrics() -> None:
    graphs = [
        json.loads((SAMPLE / "graph.json").read_text(encoding="utf-8")),
        json.loads((DENSE_SAMPLE / "graph.json").read_text(encoding="utf-8")),
    ]
    assert all(
        graph["overlay_metrics_version"] == "wiki_semantic_visual_tokens.v1"
        for graph in graphs
    )
    nodes = [node for graph in graphs for node in graph["nodes"]]
    overlays = {
        overlay: {node["overlay_metrics"][overlay]["state"] for node in nodes}
        for overlay in (
            "attention",
            "freshness",
            "actions",
            "ownership",
            "evidence",
            "quality",
        )
    }
    assert overlays["attention"] >= {"quiet", "watch", "urgent"}
    assert overlays["freshness"] >= {"fresh", "stale", "never_synced"}
    assert overlays["actions"] >= {
        "none",
        "open",
        "blocked",
        "overdue",
        "done",
        "cancelled",
    }
    assert overlays["ownership"] >= {"assigned", "shared", "unassigned", "unknown"}
    assert overlays["evidence"] >= {"linked", "unrecorded"}
    assert overlays["quality"] >= {"clear", "warning", "flagged"}
    for node in nodes:
        for metric in node["overlay_metrics"].values():
            assert set(metric) == {"state", "value", "count", "reasons", "refs"}
            assert metric["count"] >= 0
            assert all(isinstance(reason, str) for reason in metric["reasons"])
            assert all(isinstance(ref, str) for ref in metric["refs"])
