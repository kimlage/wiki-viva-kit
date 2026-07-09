from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from wiki_core.web import snapshot as snapshot_module
from wiki_core.config import WikiConfig
from wiki_core.web.deploy_bundle import write_deploy_bundle
from wiki_core.web.schemas import SNAPSHOT_FILES, WEB_SNAPSHOT_SCHEMA_VERSION
from wiki_core.web.snapshot import (
    _graph_overlay_metrics,
    _snapshot_warnings_payload,
    _source_lifecycle_payload,
    build_snapshot,
    prepare_snapshot_artifacts,
    snapshot_contract_errors,
    write_snapshot,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _init_git(root: Path) -> None:
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "wiki@example.test"], cwd=root, check=True
    )
    subprocess.run(["git", "config", "user.name", "Wiki Test"], cwd=root, check=True)


def _sample_repo(root: Path) -> WikiConfig:
    _write(
        root / "memories/index.md",
        """---
page_id: root
page_type: root_index
title: "Root"
context: system
visibility: private_self
updated_at: 2026-07-01
stale_after_days: 30
---

# Root

The root links to [Example](example/index.md).
""",
    )
    _write(
        root / "memories/example/index.md",
        """---
page_id: example-hub
page_type: context_hub
title: "Example"
context: example
visibility: private_self
updated_at: 2026-07-01
stale_after_days: 30
moc_parent: memories/index.md
---

# Example

Operational sample context.
""",
    )
    _write(
        root / "memories/operations.md",
        """---
page_id: operations
page_type: dashboard
title: "Operations"
context: system
visibility: private_self
updated_at: 2026-07-01
stale_after_days: 1
---

# Operations

## Current state

- Git state is checked live.

## Alerts

- No open alerts.
""",
    )
    _init_git(root)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        ["git", "commit", "-m", "sample"], cwd=root, check=True, capture_output=True
    )
    return WikiConfig(repo_id="sample", contexts=("example",))


def test_build_snapshot_contains_plan_files_and_local_data(tmp_path: Path) -> None:
    config = _sample_repo(tmp_path)

    snapshot = build_snapshot(
        tmp_path,
        config,
        generated_at="2026-07-01T00:00:00Z",
    )

    assert tuple(snapshot) == SNAPSHOT_FILES
    assert snapshot["manifest.json"]["schema_version"] == WEB_SNAPSHOT_SCHEMA_VERSION
    assert snapshot["manifest.json"]["snapshot_id"].startswith("sample-")
    assert snapshot["manifest.json"]["root_page_id"] == "root"
    assert (
        snapshot["manifest.json"]["versions"]["runtime_contract"]
        == "wiki_world_runtime.v8"
    )
    expected_versions = {
        "semantic_visual_tokens": "wiki_semantic_visual_tokens.v1",
        "source_freshness": "wiki_source_freshness.v1",
        "source_last_attempt": "wiki_source_last_attempt.v1",
        "registry_module_api": "wiki_registry_module_api.v1",
        "canonical_route": "wiki_world_route.v8",
        "relation_vocabulary": "wiki_relation_types.v1",
    }
    assert {
        key: snapshot["manifest.json"]["versions"][key] for key in expected_versions
    } == expected_versions
    assert set(snapshot["manifest.json"]["integrity"]) == set(SNAPSHOT_FILES) - {
        "manifest.json"
    }
    assert snapshot["manifest.json"]["repo"]["repo_id"] == "sample"
    assert snapshot["manifest.json"]["repo"]["branch_prefix"] == "wiki/"
    assert snapshot["manifest.json"]["repo"]["default_context"] == "system"
    assert snapshot["manifest.json"]["repo"]["karma_enabled"] is True
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    assert snapshot["manifest.json"]["source_sha"] == head
    assert snapshot["manifest.json"]["source_commit"] == head
    assert snapshot["git.json"]["current_branch"] == "main"
    assert snapshot["timeline.json"]["summary"]["event_count"] >= 1
    assert snapshot["diff.json"]["summary"]["file_count"] == 0
    assert snapshot["operations.json"]["title"] == "Operations"
    assert snapshot["freshness.json"]["summary"]["fresh"] >= 1
    assert any(node["id"] == "example-hub" for node in snapshot["graph.json"]["nodes"])
    assert any(
        action["id"] == "run-honesty-gates"
        for action in snapshot["actions.json"]["actions"]
    )
    assert snapshot["manifest.json"]["contract_errors"] == []
    assert snapshot["operator_commands.json"]["operator_commands"]
    assert (
        snapshot["graph.json"]["relation_vocabulary_version"]
        == "wiki_relation_types.v1"
    )
    assert (
        snapshot["graph.json"]["overlay_metrics_version"]
        == "wiki_semantic_visual_tokens.v1"
    )
    for node in snapshot["graph.json"]["nodes"]:
        assert set(node["overlay_metrics"]) == {
            "attention",
            "freshness",
            "actions",
            "ownership",
            "evidence",
            "quality",
        }
        for metric in node["overlay_metrics"].values():
            assert set(metric) == {"state", "value", "count", "reasons", "refs"}


def test_dirty_snapshot_source_identity_is_honest_deterministic_and_content_bound(
    tmp_path: Path,
) -> None:
    config = _sample_repo(tmp_path)
    page = tmp_path / "memories/example/index.md"
    page.write_text(page.read_text(encoding="utf-8") + "\nDirty one.\n", encoding="utf-8")

    first = build_snapshot(
        tmp_path, config, generated_at="2026-07-01T00:00:00Z"
    )["manifest.json"]
    second = build_snapshot(
        tmp_path, config, generated_at="2026-07-01T00:00:00Z"
    )["manifest.json"]
    assert first["source_sha"].startswith("uncommitted:")
    assert len(first["source_sha"].removeprefix("uncommitted:")) == 64
    assert first["source_commit"] is None
    assert second["source_sha"] == first["source_sha"]

    page.write_text(page.read_text(encoding="utf-8") + "Dirty two.\n", encoding="utf-8")
    changed = build_snapshot(
        tmp_path, config, generated_at="2026-07-01T00:00:00Z"
    )["manifest.json"]
    assert changed["source_sha"] != first["source_sha"]


def test_nested_snapshot_source_identity_ignores_sibling_generated_output(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "nested-source"
    config = _sample_repo(source_root)
    shutil.rmtree(source_root / ".git")
    _init_git(tmp_path)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "nested source"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    initial = build_snapshot(
        source_root, config, generated_at="2026-07-01T00:00:00Z"
    )["manifest.json"]["source_sha"]
    sibling = tmp_path / "generated-output/manifest.json"
    sibling.parent.mkdir(parents=True)
    sibling.write_text('{"generation": 1}\n', encoding="utf-8")
    after_sibling = build_snapshot(
        source_root, config, generated_at="2026-07-01T00:00:00Z"
    )["manifest.json"]["source_sha"]
    assert after_sibling == initial

    nested_page = source_root / "memories/example/index.md"
    nested_page.write_text(
        nested_page.read_text(encoding="utf-8") + "\nNested source edit.\n",
        encoding="utf-8",
    )
    after_source = build_snapshot(
        source_root, config, generated_at="2026-07-01T00:00:00Z"
    )["manifest.json"]["source_sha"]
    assert after_source.startswith("uncommitted:")
    assert after_source != initial

    sibling.write_text('{"generation": 2}\n', encoding="utf-8")
    after_second_sibling = build_snapshot(
        source_root, config, generated_at="2026-07-01T00:00:00Z"
    )["manifest.json"]["source_sha"]
    assert after_second_sibling == after_source


def test_sidecar_only_body_change_updates_bundle_and_snapshot_identity(
    tmp_path: Path,
) -> None:
    config = _sample_repo(tmp_path)
    payloads = build_snapshot(
        tmp_path,
        config,
        generated_at="2026-07-01T00:00:00Z",
        content_sidecars=True,
    )
    first = prepare_snapshot_artifacts(
        tmp_path, config, payloads, content_sidecars=True
    )
    page = tmp_path / "memories/example/index.md"
    page.write_text(
        page.read_text(encoding="utf-8")
        + "\nA sidecar-only paragraph beyond the frozen page index.\n",
        encoding="utf-8",
    )
    second = prepare_snapshot_artifacts(
        tmp_path, config, payloads, content_sidecars=True
    )

    assert second["pages.json"] == first["pages.json"]
    assert second["manifest.json"]["bundle_hash"] != first["manifest.json"]["bundle_hash"]
    assert second["manifest.json"]["snapshot_id"] != first["manifest.json"]["snapshot_id"]
    assert snapshot_contract_errors(first) == []
    assert snapshot_contract_errors(second) == []


def test_graph_overlay_metrics_are_data_backed_and_keep_cancelled_distinct() -> None:
    pages = {
        "pages": [
            {
                "id": "source-one",
                "path": "memories/sources/one.md",
                "page_type": "source",
                "freshness_state": "stale",
                "status": "",
                "risk_flags": [],
                "source_refs": [],
            },
            {
                "id": "person-one",
                "path": "memories/people/one.md",
                "page_type": "person",
                "freshness_state": "fresh",
                "status": "",
                "risk_flags": [],
                "source_refs": [],
            },
            {
                "id": "action-cancelled",
                "path": "memories/actions/cancelled.md",
                "page_type": "action",
                "freshness_state": "fresh",
                "status": "",
                "risk_flags": [],
                "source_refs": ["source-one"],
                "work": {
                    "state": "cancelled",
                    "owner_kind": "human",
                    "owner_ref": "person-one",
                    "evidence_refs": ["source-one"],
                    "parent_ref": "source-one",
                    "cancellation_receipt": "receipt:test-cancelled",
                },
            },
        ]
    }
    quality = {
        "quality_flags": {
            "low_information_density_pages": ["memories/actions/cancelled.md"],
            "orphan_actions": ["memories/actions/cancelled.md"],
            "quality_exempt_pages": ["memories/actions/cancelled.md"],
        }
    }
    metrics = _graph_overlay_metrics(
        pages,
        {
            "memories/sources/one.md": "source-one",
            "memories/people/one.md": "person-one",
            "memories/actions/cancelled.md": "action-cancelled",
        },
        quality,
        snapshot_warnings_payload={
            "warnings": [
                {
                    "code": "source_blocked",
                    "source_id": "source-one",
                    "severity": "warning",
                }
            ]
        },
        gates_payload={"gates": [{"id": "wiki_audit", "status": "fail"}]},
        source_lifecycle_payload={
            "sources": [{"source_id": "source-one", "freshness_state": "never_synced"}]
        },
        root_page_id="person-one",
    )

    action = metrics["action-cancelled"]
    assert action["actions"]["state"] == "cancelled"
    assert action["ownership"] == {
        "state": "assigned",
        "value": 1,
        "count": 1,
        "reasons": ["owner:recorded"],
        "refs": ["person-one"],
    }
    assert action["evidence"]["state"] == "linked"
    assert action["quality"]["state"] == "flagged"
    assert action["quality"]["reasons"] == [
        "quality:low_information_density_pages",
        "quality:orphan_actions",
    ]
    assert metrics["source-one"]["freshness"]["state"] == "never_synced"
    assert metrics["source-one"]["attention"]["state"] == "urgent"
    assert (
        "snapshot_warning:source_blocked"
        in metrics["source-one"]["attention"]["reasons"]
    )
    assert metrics["person-one"]["attention"]["state"] == "urgent"
    assert metrics["person-one"]["attention"]["refs"] == ["gate:wiki_audit"]


def test_snapshot_contract_detects_duplicate_ids_dangling_relations_and_corruption(
    tmp_path: Path,
) -> None:
    config = _sample_repo(tmp_path)
    snapshot = build_snapshot(tmp_path, config, generated_at="2026-07-01T00:00:00Z")
    snapshot["pages.json"]["pages"].append(dict(snapshot["pages.json"]["pages"][0]))
    snapshot["graph.json"]["edges"].append(
        {
            "id": "dangling",
            "source": "root",
            "target": "missing",
            "type": "evidence",
            "direction": "directed",
            "basis": "fixture",
            "provenance": {"page_id": "root"},
            "status": "valid",
        }
    )
    errors = snapshot_contract_errors(snapshot)
    assert any("duplicate page ids" in error for error in errors)
    assert any("dangling relation" in error for error in errors)
    assert any("integrity mismatch: pages.json" in error for error in errors)

    snapshot = build_snapshot(tmp_path, config, generated_at="2026-07-01T00:00:00Z")
    snapshot["graph.json"]["edges"][0]["type"] = "unknown-relation"
    assert any(
        "unknown relation type" in error for error in snapshot_contract_errors(snapshot)
    )

    snapshot = build_snapshot(tmp_path, config, generated_at="2026-07-01T00:00:00Z")
    snapshot["manifest.json"]["versions"].pop("canonical_route")
    assert any(
        "missing contract versions" in error
        for error in snapshot_contract_errors(snapshot)
    )

    snapshot = build_snapshot(tmp_path, config, generated_at="2026-07-01T00:00:00Z")
    snapshot["graph.json"]["nodes"][0]["overlay_metrics"]["actions"]["state"] = (
        "fictional"
    )
    assert any(
        "invalid overlay state" in error for error in snapshot_contract_errors(snapshot)
    )


def test_source_lifecycle_never_calls_raw_pipeline_progress_ingested() -> None:
    pages = {
        "pages": [
            {
                "id": "source-raw",
                "source_lifecycle_state": "ingested",
                "source_blocked_reason": "",
            },
            {
                "id": "source-accepted",
                "source_lifecycle_state": "ingested",
                "source_blocked_reason": "",
            },
        ]
    }
    sources = {
        "sources": [
            {
                "source_id": "source-raw",
                "recipe_ok": True,
                "streams": [],
                "sync": {
                    "last_status": "ok",
                    "last_run_at": "2026-07-01",
                    "last_event_ref": "event-raw",
                },
                "lifecycle": {
                    "state": "ingested",
                    "pipeline_stage": "indexed",
                    "adoption_state": "pending",
                },
            },
            {
                "source_id": "source-accepted",
                "recipe_ok": True,
                "streams": [],
                "sync": {
                    "last_status": "ok",
                    "last_run_at": "2026-07-01",
                    "last_event_ref": "event-closed",
                },
                "lifecycle": {
                    "state": "ingested",
                    "pipeline_stage": "complete",
                    "adoption_state": "accepted",
                    "accepted_ref": "sha256:accepted-fixture",
                    "emitted_page_ids": ["page-a"],
                    "last_ingested_at": "2026-07-02",
                },
            },
        ]
    }

    payload = _source_lifecycle_payload(pages, sources)
    by_id = {row["source_id"]: row for row in payload["sources"]}
    assert by_id["source-raw"]["lifecycle_state"] == "proposed"
    assert by_id["source-raw"]["pipeline_stage"] == "indexed"
    assert by_id["source-raw"]["contract_warnings"] == [
        "ingested_requires_closure_and_accepted_ref"
    ]
    assert by_id["source-accepted"]["lifecycle_state"] == "ingested"
    assert by_id["source-accepted"]["accepted_ref"] == "sha256:accepted-fixture"


def test_snapshot_warnings_detect_core_overload_and_wrong_semantic_buckets() -> None:
    pages = {
        "pages": [
            *[{"id": f"core-{index}", "page_type": "content"} for index in range(30)],
            {"id": "source-wrong", "page_type": "source"},
            {"id": "rule-wrong", "page_type": "operational_rule"},
        ]
    }
    stacks = {
        "anchors": {
            "root": {
                "derived": {
                    "quadrant_assignments": {
                        "q0_core": [f"core-{index}" for index in range(30)],
                        "q1": ["source-wrong", "rule-wrong"],
                        "q2": [],
                        "q3": [],
                        "q4": [],
                    },
                    "region_groups": {"groups": []},
                }
            }
        }
    }
    payload = _snapshot_warnings_payload(pages, stacks, {"sources": []})
    codes = {warning["code"] for warning in payload["warnings"]}
    assert {
        "q0_overload",
        "oversized_core",
        "source_wrong_bucket",
        "governance_wrong_bucket",
    } <= codes


def test_write_snapshot_creates_all_json_files(tmp_path: Path) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "data/derived/wiki/web-snapshot"

    written = write_snapshot(tmp_path, out_dir, config, clean=True)

    assert set(written) == set(SNAPSHOT_FILES)
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"] == list(SNAPSHOT_FILES)


def test_snapshot_promotion_restores_previous_directory_on_rename_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    write_snapshot(tmp_path, out_dir, config, clean=True)
    before = {
        path.relative_to(out_dir).as_posix(): path.read_bytes()
        for path in sorted(item for item in out_dir.rglob("*") if item.is_file())
    }
    page = tmp_path / "memories/example/index.md"
    page.write_text(page.read_text(encoding="utf-8") + "\nChanged.\n", encoding="utf-8")

    original_replace = snapshot_module.os.replace
    failed = False

    def fail_new_directory_once(source: Path, target: Path) -> None:
        nonlocal failed
        if (
            not failed
            and Path(target) == out_dir
            and ".stage-" in Path(source).name
            and not Path(source).name.endswith(".previous")
        ):
            failed = True
            raise OSError("synthetic promotion failure")
        original_replace(source, target)

    monkeypatch.setattr(snapshot_module.os, "replace", fail_new_directory_once)
    with pytest.raises(OSError, match="synthetic promotion failure"):
        write_snapshot(tmp_path, out_dir, config, clean=True)

    after = {
        path.relative_to(out_dir).as_posix(): path.read_bytes()
        for path in sorted(item for item in out_dir.rglob("*") if item.is_file())
    }
    assert after == before
    assert not list(out_dir.parent.glob(f".{out_dir.name}.stage-*"))


def test_write_deploy_bundle_creates_runtime_config_snapshot_and_proof(
    tmp_path: Path,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "deploy"

    written = write_deploy_bundle(
        tmp_path,
        out_dir,
        config,
        snapshot_base="/sample-review",
        repo_label="Sample Review",
        runtime_mode="static",
        # The fixture wiki carries private pages: the boundary gate must be
        # explicitly waived for the bundle to build at all (see the refusal test).
        data_boundary="private_ok",
        target="vercel_static",
        clean=True,
    )

    assert "config" in written
    assert "proof" in written
    assert (out_dir / "sample-review" / "manifest.json").exists()
    runtime_config = json.loads(
        (out_dir / "wiki-cockpit.config.json").read_text(encoding="utf-8")
    )
    assert runtime_config == {
        "api_base": "",
        "mode": "static",
        "repo_label": "Sample Review",
        "snapshot_base": "/sample-review",
        "codex": {"enabled": True},
    }
    proof = (out_dir / "DEPLOYMENT.md").read_text(encoding="utf-8")
    assert "vercel_static" in proof
    assert "private_ok" in proof
    assert "Pull Requests" in proof

    url_out = tmp_path / "deploy-url"
    write_deploy_bundle(
        tmp_path,
        url_out,
        config,
        snapshot_base="https://cdn.example.test/wiki/snapshot",
        data_boundary="private_ok",  # same fixture, same waiver
        target="vercel_static",
        clean=True,
    )
    url_config = json.loads(
        (url_out / "wiki-cockpit.config.json").read_text(encoding="utf-8")
    )
    assert url_config["snapshot_base"] == "https://cdn.example.test/wiki/snapshot"
    assert (url_out / "snapshot" / "manifest.json").exists()


def test_snapshot_diff_tracks_branch_and_worktree_changes(tmp_path: Path) -> None:
    config = _sample_repo(tmp_path)
    subprocess.run(
        ["git", "checkout", "-b", "wiki/review-fixture"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    _write(
        tmp_path / "memories/example/index.md",
        """---
page_id: example-hub
page_type: context_hub
title: "Example"
context: example
visibility: private_self
updated_at: 2026-07-01
stale_after_days: 30
moc_parent: memories/index.md
---

# Example

Operational sample context with a branch proposal update.
""",
    )
    subprocess.run(
        ["git", "add", "memories/example/index.md"], cwd=tmp_path, check=True
    )
    subprocess.run(
        ["git", "commit", "-m", "update example hub"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    _write(
        tmp_path / "memories/operations.md",
        """---
page_id: operations
page_type: dashboard
title: "Operations"
context: system
visibility: private_self
updated_at: 2026-07-01
stale_after_days: 1
---

# Operations

## Current state

- Git state is checked live.
- Worktree has a local operator note.
""",
    )

    snapshot = build_snapshot(tmp_path, config, generated_at="2026-07-01T00:00:00Z")
    diff = snapshot["diff.json"]

    assert diff["compare"]["current_branch"] == "wiki/review-fixture"
    assert diff["summary"]["branch_file_count"] == 1
    assert diff["summary"]["working_tree_file_count"] == 1
    assert diff["summary"]["privacy_review_required"] is True
    by_path = {file["path"]: file for file in diff["files"]}
    assert by_path["memories/example/index.md"]["change_sources"] == ["branch"]
    assert "memory_review" in by_path["memories/example/index.md"]["risk_hints"]
    assert by_path["memories/operations.md"]["change_sources"] == ["working_tree"]
    assert any(
        "branch proposal update" in line
        for line in by_path["memories/example/index.md"]["preview"]
    )


def test_snapshot_timeline_includes_pages_operations_and_commits(
    tmp_path: Path,
) -> None:
    config = _sample_repo(tmp_path)

    snapshot = build_snapshot(tmp_path, config, generated_at="2026-07-01T12:00:00Z")
    timeline = snapshot["timeline.json"]

    kinds = {event["kind"] for event in timeline["events"]}
    assert {"snapshot", "operations_updated", "page_updated", "git_commit"}.issubset(
        kinds
    )
    assert timeline["summary"]["by_context"]["example"] == 1
    assert timeline["bands"]["last_7_days"] >= 1


def test_snapshot_respects_localized_memory_root(tmp_path: Path) -> None:
    _write(
        tmp_path / "memorias/index.md",
        """---
page_id: raiz
page_type: root_index
title: "Raiz"
context: sistema
visibility: private_self
updated_at: 2026-07-01
stale_after_days: 30
---

# Raiz

Conteudo sintetico.
""",
    )
    config = WikiConfig(
        repo_id="pt",
        language="pt",
        default_context="sistema",
        contexts=("financeiro",),
        paths={
            **WikiConfig().paths,
            "memory_root": "memorias",
            "operation_page": "memorias/operacao.md",
        },
        karma={"enabled": False},
    )

    snapshot = build_snapshot(tmp_path, config, generated_at="2026-07-01T00:00:00Z")

    assert snapshot["manifest.json"]["repo"]["memory_root"] == "memorias"
    assert snapshot["manifest.json"]["repo"]["default_context"] == "sistema"
    assert snapshot["manifest.json"]["repo"]["karma_enabled"] is False
    assert snapshot["pages.json"]["pages"][0]["path"] == "memorias/index.md"
    assert snapshot["pages.json"]["pages"][0]["context"] == "sistema"


def test_snapshot_handles_dense_localized_contexts_without_english_paths(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "memorias/index.md",
        """---
page_id: raiz
page_type: root_index
title: "Raiz"
context: sistema
visibility: private_self
updated_at: 2026-07-01
stale_after_days: 30
---

# Raiz
""",
    )
    for index in range(18):
        _write(
            tmp_path / "memorias/financeiro" / f"nota-{index:02d}.md",
            f"""---
page_id: nota-{index:02d}
page_type: source_note
title: "Nota {index:02d}"
context: financeiro
visibility: private_self
updated_at: 2026-07-01
stale_after_days: 30
---

# Nota {index:02d}

Conteudo sintetico para volume local.
""",
        )
    config = WikiConfig(
        repo_id="pt-denso",
        language="pt",
        default_context="sistema",
        contexts=("financeiro", "projetos"),
        paths={
            **WikiConfig().paths,
            "memory_root": "memorias",
            "operation_page": "memorias/operacao.md",
        },
        karma={"enabled": False},
    )

    snapshot = build_snapshot(tmp_path, config, generated_at="2026-07-01T00:00:00Z")

    assert snapshot["manifest.json"]["repo"]["memory_root"] == "memorias"
    assert snapshot["manifest.json"]["repo"]["default_context"] == "sistema"
    assert snapshot["freshness.json"]["by_context"]["financeiro"]["fresh"] == 18
    assert len(snapshot["sources.json"]["sources"]) == 18
    assert all(
        str(page["path"]).startswith("memorias/")
        for page in snapshot["pages.json"]["pages"]
    )


def test_freshness_state_honors_stale_exempt() -> None:
    from wiki_core.web.snapshot import _freshness_state
    import datetime as dt

    today = dt.date(2026, 7, 1)
    old_record = {"updated_at": "2025-03-01", "stale_after_days": "30"}
    assert _freshness_state(old_record, today=today) == "stale"
    # Evergreen records opt out of the freshness window entirely.
    exempt_record = {**old_record, "stale_exempt": "true"}
    assert _freshness_state(exempt_record, today=today) == "fresh"
    exempt_bool = {**old_record, "stale_exempt": True}
    assert _freshness_state(exempt_bool, today=today) == "fresh"
    not_exempt = {**old_record, "stale_exempt": "false"}
    assert _freshness_state(not_exempt, today=today) == "stale"


def test_write_deploy_bundle_refuses_private_pages_by_default(tmp_path: Path) -> None:
    """The data boundary is ENFORCED: a snapshot with `visibility: private_*`
    pages must never reach a public bundle unless explicitly waived."""
    import pytest

    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "deploy"
    with pytest.raises(ValueError, match="deploy bundle refused"):
        write_deploy_bundle(
            tmp_path,
            out_dir,
            config,
            snapshot_base="/sample-review",
            runtime_mode="static",
            data_boundary="synthetic_or_public",
            target="vercel_static",
        )
    # The refused snapshot must not linger on disk.
    assert not (out_dir / "sample-review").exists()


def test_pages_payload_skips_unreadable_page(tmp_path: Path) -> None:
    """One vanished/unreadable page file must not abort the whole snapshot
    build: the broken page is skipped, every readable page still lands."""
    import os

    import pytest

    from wiki_core.web.snapshot import _pages_payload

    if os.geteuid() == 0:  # pragma: no cover - root ignores file modes
        pytest.skip("permission bits are not enforced for root")
    config = _sample_repo(tmp_path)
    broken = tmp_path / "memories/example/broken.md"
    _write(broken, "---\npage_id: broken\n---\n\n# Broken\n")
    broken.chmod(0)
    try:
        payload = _pages_payload(tmp_path, config)
    finally:
        broken.chmod(0o644)
    paths = {page["path"] for page in payload["pages"]}
    assert "memories/example/broken.md" not in paths
    assert "memories/index.md" in paths
