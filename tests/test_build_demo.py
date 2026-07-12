from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

from wiki_core.web.content import sidecar_name

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
        assert all(
            set(row) == {"claim_id", "statement", "test_ids", "covers"}
            and set(row["covers"])
            == {
                "interactions",
                "visual_steps",
                "visual_viewports",
                "browser_projects",
                "expected_warnings",
                "expected_failures",
            }
            for row in manifest["automated_assertions"]
        )
        assert manifest["test_capabilities"]
        assert all(
            set(row) == {"capability", "test_id"}
            for row in manifest["test_capabilities"]
        )
        assert isinstance(manifest["artifact_warning_codes"], list)
        assert manifest["visual"]["viewports"]
        assert manifest["visual"]["browser_projects"]
        assert manifest["generated_files"]
        assert manifest["generated_files"] == demo._expected_scenario_generated_files(
            scenario_id
        )
        assert manifest["regeneration_command"].endswith("scripts/wiki_build_demo.py")
        assert {
            front["page_id"] for _, front, _ in demo.build_scenario_pages(scenario_id)
        } == set(page_ids)

    dense_ids = demo.scenario_page_ids("dense_stress", manifests=manifests)
    normal_ids = demo.scenario_page_ids("normal_operations", manifests=manifests)
    assert len(dense_ids) > 350  # forces the explicit mobile compact threshold
    assert any(page_id.startswith("artifact-region-pressure-") for page_id in dense_ids)
    assert not any("-region-pressure-" in page_id for page_id in normal_ids)


def test_browser_execution_contract_is_generated_from_the_validated_manifests(
    tmp_path: Path,
) -> None:
    demo = _demo_module()
    manifests = demo.validate_scenario_manifests()

    target = demo._write_demo_execution_contract(tmp_path, manifests)
    contract = json.loads(target.read_text(encoding="utf-8"))

    assert contract["schema_version"] == "wiki_demo_scenario_execution.v1"
    assert contract["fixture_id"] == demo.DEMO_FIXTURE_ID
    assert [row["id"] for row in contract["scenarios"]] == list(
        demo.REQUIRED_SCENARIOS
    )
    for row in contract["scenarios"]:
        manifest = manifests[row["id"]]
        assert row["canonical_routes"] == manifest["canonical_routes"]
        assert row["claims"] == manifest["automated_assertions"]
        assert row["page_count"] == manifest["expected"]["page_count"]
        assert row["artifact_warning_codes"] == manifest["artifact_warning_codes"]


def test_manifest_proof_rejects_a_test_name_that_exists_only_in_a_comment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    demo = _demo_module()
    monkeypatch.setattr(demo, "KIT_ROOT", tmp_path)
    authored = tmp_path / "proof.test.ts"
    authored.write_text(
        "// test(\"comment-only proof\", () => {});\n"
        "/* test(\"block-comment proof\", () => {}); */\n"
        "test(\"live proof\", () => {});\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not an exact authored test declaration"):
        demo._validate_authored_test_id(
            "synthetic", "proof.test.ts::comment-only proof"
        )
    with pytest.raises(ValueError, match="not an exact authored test declaration"):
        demo._validate_authored_test_id(
            "synthetic", "proof.test.ts::block-comment proof"
        )
    assert (
        demo._validate_authored_test_id("synthetic", "proof.test.ts::live proof")
        == "proof.test.ts::live proof"
    )


def test_source_fixture_copy_describes_its_own_lifecycle_without_bank_copy_leakage() -> None:
    demo = _demo_module()
    source_pages = {
        str(front["page_id"]): body
        for _relative, front, body in demo.build_pages()
        if front.get("page_type") == "source"
    }

    assert "bank export is intentionally overdue" in source_pages["source-banco-export"]
    assert all(
        "bank export is intentionally overdue" not in body
        for page_id, body in source_pages.items()
        if page_id != "source-banco-export"
    )
    assert all(
        "demonstrates lifecycle" in body
        and "freshness" in body
        and "last attempt" in body
        for body in source_pages.values()
    )


def test_core_scenario_routes_fail_closed_on_unbound_universe_center_or_view() -> None:
    demo = _demo_module()
    manifests = demo.load_scenario_manifests()
    scenario_id = "walking_skeleton"
    page_ids = set(demo.scenario_page_ids(scenario_id, manifests=manifests))
    original = manifests[scenario_id]

    cases = [
        (
            "/demo/w?center=root-alex-rivera&view=quadrants",
            "canonical route scenario mismatch",
        ),
        (
            f"/demo/w?demo_scenario={scenario_id}&center=ghost-page&view=quadrants",
            "canonical route center is not a page",
        ),
        (
            f"/demo/w?demo_scenario={scenario_id}&center=root-alex-rivera&view=atlas",
            "canonical route view is invalid",
        ),
    ]
    for route, message in cases:
        manifest = json.loads(json.dumps(original))
        manifest["canonical_routes"] = [route]
        with pytest.raises(ValueError, match=message):
            demo._validate_scenario_routes(scenario_id, manifest, page_ids)


def test_pack_showcase_registry_is_closed_public_and_executable() -> None:
    demo = _demo_module()
    manifests = demo.validate_pack_showcase_manifests()

    assert tuple(manifests) == demo.REQUIRED_PACK_SHOWCASES
    for scenario_id, manifest in manifests.items():
        pages = demo.build_pack_showcase_pages(scenario_id, manifests=manifests)
        page_ids = [str(front["page_id"]) for _rel, front, _body in pages]
        assert len(page_ids) == manifest["expected"]["page_count"]
        assert demo.page_id_hash(page_ids) == manifest["expected"]["page_id_sha256"]
        assert all(front["visibility"] == "public" for _rel, front, _body in pages)
        assert all(front["context"] == "showcase" for _rel, front, _body in pages)
        assert pages[0][0] == "memories/index.md"
        assert pages[0][1]["page_id"] == f"root-{scenario_id.replace('_', '-')}"
        assert manifest["canonical_routes"]
        assert manifest["limitations"]


def test_pack_showcase_canonical_route_rejects_unknown_center() -> None:
    demo = _demo_module()
    manifests = demo.load_pack_showcase_manifests()
    scenario_id = "study_research_showcase"
    manifest = json.loads(json.dumps(manifests[scenario_id]))
    pages = demo.build_pack_showcase_pages(scenario_id, manifests=manifests)
    page_ids = {str(front["page_id"]) for _rel, front, _body in pages}
    manifest["canonical_routes"] = [
        f"/demo/w?demo_scenario={scenario_id}&center=ghost-page&view=timeline"
    ]

    with pytest.raises(ValueError, match="canonical route center is not a page"):
        demo._validate_pack_showcase_routes(scenario_id, manifest, page_ids)


@pytest.mark.parametrize(
    ("scenario_id", "pack_id"),
    [
        ("study_research_showcase", "study-research"),
        ("personal_finance_showcase", "personal-finance"),
    ],
)
def test_pack_showcase_snapshot_is_active_navigable_and_deterministic_without_root_lock_mutation(
    tmp_path: Path,
    scenario_id: str,
    pack_id: str,
) -> None:
    demo = _demo_module()
    first = tmp_path / "first" / scenario_id
    second = tmp_path / "second" / scenario_id
    kit_lock = KIT_ROOT / "wiki.packs.lock.yaml"
    before_lock = kit_lock.read_bytes()

    first_report = demo._build_pack_showcase_snapshot(scenario_id, first)
    second_report = demo._build_pack_showcase_snapshot(scenario_id, second)

    assert kit_lock.read_bytes() == before_lock
    assert demo._tree_file_map(first) == demo._tree_file_map(second)
    assert first_report == second_report
    manifest = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
    composition = json.loads(
        (first / "experience_packs.json").read_text(encoding="utf-8")
    )
    pages_payload = json.loads((first / "pages.json").read_text(encoding="utf-8"))
    temporal = json.loads(
        (first / "temporal_graph.json").read_text(encoding="utf-8")
    )
    manifests = demo.load_pack_showcase_manifests()
    expected_ids = {
        str(front["page_id"])
        for _rel, front, _body in demo.build_pack_showcase_pages(
            scenario_id, manifests=manifests
        )
    }

    assert manifest["contract_errors"] == []
    assert "experience_packs" in manifest["capabilities"]
    assert manifest["fixture"]["scenario_id"] == scenario_id
    assert manifest["fixture"]["active_pack_ids"] == [pack_id]
    assert manifest["fixture"]["public_synthetic"] is True
    assert composition["packs"] == [{"id": pack_id, "version": "0.1.0"}]
    assert composition["slots"]["views"]
    assert composition["slots"]["operations"]
    assert composition["slots"]["timelines"]
    assert {row["id"] for row in pages_payload["pages"]} == expected_ids
    assert temporal["event_count"] >= manifests[scenario_id]["expected"][
        "minimum_temporal_events"
    ]
    namespaced_kinds = sorted(
        {
            event["kind"]
            for event in temporal["events"]
            if event["kind"].startswith(f"{pack_id}.")
        }
    )
    assert namespaced_kinds == manifests[scenario_id]["expected"][
        "required_temporal_event_kinds"
    ]
    assert temporal["diagnostics"] == []
    assert first_report["temporal_event_count"] == temporal["event_count"]
    assert first_report["temporal_event_kinds"] == namespaced_kinds
    assert first_report["temporal_diagnostic_codes"] == []
    assert all(
        (first / "content" / sidecar_name(page_id)).is_file()
        for page_id in expected_ids
    )


def test_pack_showcase_compiler_enforces_temporal_minimum(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    demo = _demo_module()
    manifests = demo.load_pack_showcase_manifests()
    scenario_id = "study_research_showcase"
    altered = json.loads(json.dumps(manifests))
    altered[scenario_id]["expected"]["minimum_temporal_events"] = 1_000_000
    monkeypatch.setattr(
        demo,
        "load_pack_showcase_manifests",
        lambda *args, **kwargs: altered,
    )

    with pytest.raises(ValueError, match="temporal event minimum not met"):
        demo._build_pack_showcase_snapshot(scenario_id, tmp_path / scenario_id)


def test_pack_showcase_fixture_uses_only_its_disposable_lock(tmp_path: Path) -> None:
    demo = _demo_module()
    kit_lock = KIT_ROOT / "wiki.packs.lock.yaml"
    before = kit_lock.read_bytes()
    fixture = tmp_path / "fixture"

    demo.write_pack_showcase_fixture(fixture, "study_research_showcase")

    assert kit_lock.read_bytes() == before
    disposable = yaml.safe_load(
        (fixture / "wiki.packs.lock.yaml").read_text(encoding="utf-8")
    )
    assert list(disposable["packs"]) == ["study-research"]
    assert disposable["packs"]["study-research"]["status"] == "active"


def test_targeted_pack_showcase_cli_does_not_rebuild_base_dense_or_genesis(
    tmp_path: Path,
    monkeypatch,
) -> None:
    demo = _demo_module()
    out = tmp_path / "sample-snapshot"
    monkeypatch.setattr(demo, "OUT", out)
    lock_before = (KIT_ROOT / "wiki.packs.lock.yaml").read_bytes()

    assert demo.main(["--pack-showcase", "personal_finance_showcase"]) == 0

    target = out / "scenarios/personal_finance_showcase"
    assert (target / "manifest.json").is_file()
    assert (target / "experience_packs.json").is_file()
    assert not (out / "manifest.json").exists()
    assert not (out / "scenarios/dense_stress").exists()
    assert not (out / "stages").exists()
    assert (KIT_ROOT / "wiki.packs.lock.yaml").read_bytes() == lock_before


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


def test_genesis_stage_zero_emits_a_declared_null_root_empty_world(tmp_path: Path) -> None:
    demo = _demo_module()
    fixture = tmp_path / "stage-zero-fixture"
    out = tmp_path / "stage-zero-out"

    assert demo.write_fixture(fixture, stage=0) == []
    demo._write_snapshot_deterministic(fixture, out, stage=0)

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    pages = json.loads((out / "pages.json").read_text(encoding="utf-8"))
    assert pages["pages"] == []
    assert manifest["root_page_id"] is None
    assert manifest["fixture"]["genesis_stage"] == 0
    assert "empty_world_compat" in manifest["capabilities"]
    assert manifest["contract_errors"] == []


def test_demo_contracts_ignore_downstream_root_registry_overrides(
    tmp_path: Path, monkeypatch
) -> None:
    demo = _demo_module()
    consumer_root = tmp_path / "consumer"
    consumer_root.mkdir()
    for name in ("wiki.page-types.yaml", "wiki.templates.yaml"):
        (consumer_root / name).write_text(
            f"consumer-only: {name}\n", encoding="utf-8"
        )

    monkeypatch.setattr(demo, "KIT_ROOT", consumer_root)
    fixture = tmp_path / "fixture"
    demo.write_fixture(fixture, stage=0)

    for name in ("wiki.page-types.yaml", "wiki.templates.yaml"):
        assert (fixture / name).read_bytes() == (
            demo.DEMO_CONTRACTS_ROOT / name
        ).read_bytes()
        assert (fixture / name).read_bytes() != (consumer_root / name).read_bytes()


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
    # Sources are recursive centers. The root's default ``summarize`` mode
    # exposes each source anchor, while normalized ingestion events remain in
    # that source's own compiled world. This guards the fixture against
    # flattening provenance back into the root map.
    pages_by_path = {page["path"]: page for page in full_pages["pages"]}
    root_members = {page_id for members in root_q.values() for page_id in members}
    ingestion_events = [
        page
        for page in full_pages["pages"]
        if page["page_type"] == "ingestion_event"
    ]
    assert len(ingestion_events) == 5
    for event in ingestion_events:
        source = pages_by_path[event["moc_parent"]]
        assert source["page_type"] == "source"
        assert source["id"] in anchors
        assert event["id"] not in root_members
        source_q = anchors[source["id"]]["derived"]["quadrant_assignments"]
        assert event["id"] in source_q["q2"]
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


def test_committed_core_scenario_snapshots_match_every_executable_manifest() -> None:
    demo = _demo_module()
    manifests = demo.load_scenario_manifests()

    for scenario_id, scenario in manifests.items():
        scenario_dir = (
            SAMPLE
            if scenario_id == demo.DEFAULT_DEMO_SCENARIO
            else SAMPLE / "scenarios" / scenario_id
        )
        pages_payload = json.loads(
            (scenario_dir / "pages.json").read_text(encoding="utf-8")
        )
        manifest_payload = json.loads(
            (scenario_dir / "manifest.json").read_text(encoding="utf-8")
        )
        page_ids = {row["id"] for row in pages_payload["pages"]}
        expected_ids = set(
            demo.scenario_page_ids(scenario_id, manifests=manifests)
        )

        assert page_ids == expected_ids
        assert len(page_ids) == scenario["expected"]["page_count"]
        assert manifest_payload["contract_errors"] == []
        assert manifest_payload["fixture"]["scenario_id"] == scenario_id
        assert manifest_payload["fixture"]["seed"] == scenario["seed"]
        assert set(scenario["expected"]["required_artifact_capabilities"]) <= set(
            manifest_payload["capabilities"]
        )
        warning_payload = json.loads(
            (scenario_dir / "snapshot_warnings.json").read_text(encoding="utf-8")
        )
        warning_codes = sorted(
            {row["code"] for row in warning_payload["warnings"]}
        )
        assert warning_codes == scenario["artifact_warning_codes"]

    normal_ids = set(demo.scenario_page_ids("normal_operations", manifests=manifests))
    dense_ids = set(demo.scenario_page_ids("dense_stress", manifests=manifests))
    assert not any("-region-pressure-" in page_id for page_id in normal_ids)
    assert any(page_id.startswith("artifact-region-pressure-") for page_id in dense_ids)


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
        "never",
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
    terminal = [row for row in actions if row["state"] in {"done", "cancelled"}]
    assert all(row["completed_at"].endswith("T12:00:00Z") for row in terminal)
    assert all(not row["next_action"] for row in terminal)
    assert all(not row["blocked_by"] and not row["blocker_reason"] for row in terminal)
    assert all(
        row["next_action"]
        and not row["completed_at"]
        and not row["completion_receipt"]
        and not row["cancellation_receipt"]
        for row in actions
        if row["state"] not in {"done", "cancelled"}
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
