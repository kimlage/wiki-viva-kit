from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from wiki_core.web import snapshot as snapshot_module
from wiki_core.config import WikiConfig
from wiki_core.output_safety import OUTPUT_OWNER_FILENAME
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

KIT_ROOT = Path(__file__).resolve().parents[1]


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


def _make_unmarked_legacy_snapshot(out_dir: Path, *, repo_id: str) -> None:
    _materialize_snapshot_pointer(out_dir)
    (out_dir / OUTPUT_OWNER_FILENAME).unlink()
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    artifacts = {
        name: json.loads((out_dir / name).read_text(encoding="utf-8"))
        for name in manifest["files"]
    }
    manifest = artifacts["manifest.json"]
    manifest["repo"]["repo_id"] = repo_id
    for page in artifacts["pages.json"]["pages"]:
        page.pop("content_sha256", None)
    manifest["integrity"]["pages.json"] = snapshot_module._payload_integrity(
        artifacts["pages.json"]
    )
    bundle_hash = snapshot_module._bundle_hash_for_artifacts(artifacts)
    manifest["bundle_hash"] = bundle_hash
    manifest["snapshot_id"] = f"{repo_id}-{bundle_hash[:16]}"
    manifest["contract_errors"] = snapshot_contract_errors(artifacts)
    assert manifest["contract_errors"] and all(
        error.startswith("invalid page content hash: ")
        for error in manifest["contract_errors"]
    )
    for name in ("pages.json", "manifest.json"):
        (out_dir / name).write_text(
            json.dumps(artifacts[name], indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _materialize_snapshot_pointer(out_dir: Path) -> None:
    """Create an offline flat-directory fixture from the live pointer layout."""

    if not out_dir.is_symlink():
        return
    materialized = out_dir.with_name(f".{out_dir.name}.materialized")
    shutil.copytree(out_dir.resolve(strict=True), materialized)
    out_dir.unlink()
    materialized.replace(out_dir)


def _snapshot_file_map(out_dir: Path) -> dict[str, bytes]:
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    names = [*manifest["files"], OUTPUT_OWNER_FILENAME]
    return {name: (out_dir / name).read_bytes() for name in names}


def _prepared_snapshot_variant(
    root: Path,
    config: WikiConfig,
    *,
    version: int,
) -> dict[str, dict[str, object]]:
    page = root / "memories/example/index.md"
    base = page.read_text(encoding="utf-8").split("\nSynthetic revision ", 1)[0]
    page.write_text(f"{base}\nSynthetic revision {version}.\n", encoding="utf-8")
    payloads = build_snapshot(
        root,
        config,
        generated_at=f"2026-07-01T00:00:{version:02d}Z",
    )
    return prepare_snapshot_artifacts(
        root,
        config,
        payloads,
        content_sidecars=False,
    )


def _write_source_lifecycle_fixture(
    root: Path, *, attempt_state: str, pipeline_stage: str
) -> None:
    stage_line = (
        f"source_pipeline_stage: {pipeline_stage}\n" if pipeline_stage else ""
    )
    _write(
        root / "memories/sources/bank.md",
        "---\n"
        "page_id: source-bank\n"
        "page_type: source\n"
        "title: Bank statements\n"
        "context: example\n"
        "visibility: private_self\n"
        "updated_at: 2026-07-01\n"
        "stale_after_days: 30\n"
        "moc_parent: memories/index.md\n"
        f"source_last_attempt_state: {attempt_state}\n"
        f"{stage_line}"
        "---\n\n"
        "# Bank statements\n",
    )


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


def test_snapshot_action_state_is_canonical_over_editorial_status(tmp_path: Path) -> None:
    config = _sample_repo(tmp_path)
    _write(
        tmp_path / "memories/actions/closed.md",
        """---
page_id: action-closed
page_type: action
title: "Closed action"
context: example
visibility: private_self
updated_at: 2026-07-01
stale_after_days: 30
source_refs: []
moc_parent: memories/example/index.md
action_state: done
status: open
owner_kind: human
created_at: 2026-07-01
priority: normal
attention_basis: "Already closed."
completion_receipt: "commit:test-closed"
---

# Closed action

State: `cancelled`.

Editorial copy must not reopen canonical work.
""",
    )

    snapshot = build_snapshot(
        tmp_path,
        config,
        generated_at="2026-07-01T00:00:00Z",
    )

    page = next(
        row for row in snapshot["pages.json"]["pages"] if row["id"] == "action-closed"
    )
    assert page["status"] == "open"
    assert page["work"]["state"] == "done"
    assert page["work"]["state_raw"] == "done"
    assert page["work"]["state_source"] == "action_state"
    assert page["work"]["state_compatibility"] is False
    item = next(
        row
        for row in snapshot["work_items.json"]["actions"]
        if row["action_id"] == "action-closed"
    )
    assert item["state"] == "done"
    assert item["state_source"] == "action_state"
    assert item["state_compatibility"] is False
    assert snapshot_contract_errors(snapshot) == []


def test_snapshot_resolves_body_only_legacy_action_state(tmp_path: Path) -> None:
    config = _sample_repo(tmp_path)
    _write(
        tmp_path / "memories/actions/body-only.md",
        """---
page_id: action-body-only
page_type: action
title: "Body-only action"
context: example
visibility: private_self
updated_at: 2026-07-01
stale_after_days: 30
source_refs: []
moc_parent: memories/example/index.md
owner_kind: human
created_at: 2026-07-01
priority: normal
attention_basis: "Legacy action under migration."
completion_receipt: "commit:test-body-only"
---

# Body-only action

State: `completed`.
""",
    )

    snapshot = build_snapshot(
        tmp_path,
        config,
        generated_at="2026-07-01T00:00:00Z",
    )

    page = next(
        row for row in snapshot["pages.json"]["pages"] if row["id"] == "action-body-only"
    )
    assert page["status"] == ""
    assert page["work"]["state"] == "done"
    assert page["work"]["state_raw"] == "completed"
    assert page["work"]["state_source"] == "body_state"
    assert page["work"]["state_compatibility"] is True
    assert page["work"]["state_warnings"] == ["legacy_action_state"]
    item = next(
        row
        for row in snapshot["work_items.json"]["actions"]
        if row["action_id"] == "action-body-only"
    )
    assert item["state"] == "done"
    assert item["state_source"] == "body_state"
    assert item["state_compatibility"] is True
    assert item["contract_warnings"] == ["legacy_action_state"]
    assert snapshot_contract_errors(snapshot) == []


def test_collection_membership_edge_is_unique_and_keeps_declaration_provenance(
    tmp_path: Path,
) -> None:
    config = _sample_repo(tmp_path)
    _write(
        tmp_path / "memories/claims/index.md",
        """---
page_id: claims-index
page_type: ontology_index
title: "Claims"
context: example
visibility: private_self
updated_at: 2026-07-01
stale_after_days: 30
moc_parent: memories/index.md
collection:
  member_types: [claim]
---

# Claims
""",
    )
    _write(
        tmp_path / "memories/claims/a.md",
        """---
page_id: claim-a
page_type: claim
title: "Claim A"
context: example
visibility: private_self
updated_at: 2026-07-01
stale_after_days: 30
moc_parent: memories/index.md
source_refs: []
collection_refs:
  - claims-index
---

# Claim A
""",
    )

    snapshot = build_snapshot(tmp_path, config, generated_at="2026-07-01T00:00:00Z")
    edges = [
        edge
        for edge in snapshot["graph.json"]["edges"]
        if edge["type"] == "collection_member"
        and edge["source"] == "claim-a"
        and edge["target"] == "claims-index"
    ]

    assert len(edges) == 1
    assert edges[0]["basis"] == "member.collection_refs"
    assert edges[0]["provenance"] == {
        "page_id": "claim-a",
        "path": "memories/claims/a.md",
        "field": "collection_refs",
        "origin": "member",
    }
    pages = {page["id"]: page for page in snapshot["pages.json"]["pages"]}
    assert pages["claims-index"]["collection_members_count"] == 1
    assert {row["id"] for row in snapshot["graph.json"]["relation_types"]} >= {
        "collection_member"
    }


def test_snapshot_compiles_collections_once_for_pages_edges_and_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _sample_repo(tmp_path)
    original = snapshot_module.compile_collections
    calls = 0

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(snapshot_module, "compile_collections", counted)

    snapshot = build_snapshot(
        tmp_path,
        config,
        generated_at="2026-07-01T00:00:00Z",
        reference_date=dt.date(2026, 7, 1),
    )

    assert calls == 1
    assert snapshot["manifest.json"]["contract_errors"] == []


def test_unresolved_collection_reference_is_preserved_as_graph_diagnostic(
    tmp_path: Path,
) -> None:
    config = _sample_repo(tmp_path)
    _write(
        tmp_path / "memories/example/note.md",
        """---
page_id: note-a
page_type: context_note
title: "Note"
context: example
visibility: private_self
updated_at: 2026-07-01
stale_after_days: 30
collection_refs: [missing-index]
---

# Note
""",
    )

    snapshot = build_snapshot(tmp_path, config, generated_at="2026-07-01T00:00:00Z")
    diagnostic = next(
        row
        for row in snapshot["graph.json"]["relation_diagnostics"]
        if "unresolved_collection_ref" in row["reasons"]
    )
    assert diagnostic["source"] == "note-a"
    assert diagnostic["target"] == "missing-index"
    assert diagnostic["type"] == "collection_member"
    assert diagnostic["provenance"]["field"] == "collection_refs"


def test_forbidden_collection_cycle_blocks_snapshot_with_actionable_path(
    tmp_path: Path,
) -> None:
    config = _sample_repo(tmp_path)
    _write(
        tmp_path / "memories/example/loop.md",
        """---
page_id: loop-index
page_type: ontology_index
title: "Loop"
context: example
visibility: private_self
updated_at: 2026-07-01
stale_after_days: 30
moc_parent: memories/example/index.md
collection_refs: [loop-index]
---

# Loop
""",
    )

    snapshot = build_snapshot(
        tmp_path, config, generated_at="2026-07-01T00:00:00Z"
    )

    expected = (
        "forbidden relation cycle (collection_member): "
        "loop-index -> loop-index"
    )
    assert expected in snapshot["manifest.json"]["contract_errors"]
    diagnostic = next(
        row
        for row in snapshot["graph.json"]["relation_diagnostics"]
        if "forbidden_collection_cycle" in row["reasons"]
    )
    assert diagnostic["cycle_path"] == ["loop-index", "loop-index"]
    assert diagnostic["cycle_path_text"] == "loop-index -> loop-index"

    out_dir = tmp_path / "snapshot-out"
    with pytest.raises(ValueError, match="forbidden relation cycle"):
        write_snapshot(tmp_path, out_dir, config)
    assert not out_dir.exists()


def test_snapshot_contract_allows_cycle_when_relation_vocabulary_explicitly_does(
    tmp_path: Path,
) -> None:
    config = _sample_repo(tmp_path)
    example = tmp_path / "memories/example/index.md"
    example.write_text(
        example.read_text(encoding="utf-8") + "\n[Root](../index.md)\n",
        encoding="utf-8",
    )

    snapshot = build_snapshot(
        tmp_path, config, generated_at="2026-07-01T00:00:00Z"
    )
    markdown_edges = {
        (edge["source"], edge["target"])
        for edge in snapshot["graph.json"]["edges"]
        if edge["type"] == "markdown_link"
    }

    assert {("root", "example-hub"), ("example-hub", "root")} <= markdown_edges
    assert snapshot["manifest.json"]["contract_errors"] == []


def test_frontmatter_relations_keep_field_semantics_and_allow_related_reciprocity(
    tmp_path: Path,
) -> None:
    config = _sample_repo(tmp_path)
    _write(
        tmp_path / "memories/example/source.md",
        """---
page_id: source-a
page_type: source
title: "Source A"
context: example
visibility: private_self
updated_at: 2026-07-01
stale_after_days: 30
moc_parent: example-hub
---

# Source A
""",
    )
    _write(
        tmp_path / "memories/example/evidence.md",
        """---
page_id: evidence-a
page_type: evidence
title: "Evidence A"
context: example
visibility: private_self
updated_at: 2026-07-01
stale_after_days: 30
moc_parent: example-hub
---

# Evidence A
""",
    )
    _write(
        tmp_path / "memories/example/peer.md",
        """---
page_id: peer-a
page_type: context_note
title: "Peer A"
context: example
visibility: private_self
updated_at: 2026-07-01
stale_after_days: 30
moc_parent: example-hub
related_pages: [note-a]
---

# Peer A
""",
    )
    _write(
        tmp_path / "memories/example/note.md",
        """---
page_id: note-a
page_type: context_note
title: "Note A"
context: example
visibility: private_self
updated_at: 2026-07-01
stale_after_days: 30
moc_parent: example-hub
source_refs: [source-a]
related_pages: [peer-a]
evidence_refs: [evidence-a]
claims: [root]
---

# Note A
""",
    )

    snapshot = build_snapshot(
        tmp_path, config, generated_at="2026-07-01T00:00:00Z"
    )
    edges = {
        (edge["source"], edge["target"], edge["type"]): edge
        for edge in snapshot["graph.json"]["edges"]
    }

    assert edges[("note-a", "example-hub", "moc_parent")]["provenance"]["field"] == (
        "moc_parent"
    )
    assert edges[("note-a", "source-a", "source_ref")]["provenance"]["field"] == (
        "source_refs"
    )
    assert edges[("note-a", "peer-a", "related_page")]["provenance"]["field"] == (
        "related_pages"
    )
    assert ("peer-a", "note-a", "related_page") in edges
    assert not any(
        edge["source"] == "note-a"
        and edge["target"] in {"evidence-a", "root", "peer-a"}
        and edge["type"] == "source_ref"
        for edge in snapshot["graph.json"]["edges"]
    )
    related_type = next(
        row
        for row in snapshot["graph.json"]["relation_types"]
        if row["id"] == "related_page"
    )
    assert related_type["allows_cycles"] is True
    assert snapshot["manifest.json"]["contract_errors"] == []


def test_template_default_collection_membership_points_provenance_to_registry_contract(
    tmp_path: Path,
) -> None:
    config = _sample_repo(tmp_path)
    kit_root = Path(__file__).resolve().parents[1]
    shutil.copy(kit_root / "wiki.templates.yaml", tmp_path / "wiki.templates.yaml")
    _write(
        tmp_path / "memories/system/source-registry.md",
        """---
page_id: source-registry
page_type: source_registry
title: "Sources"
context: system
visibility: private_self
updated_at: 2026-07-01
stale_after_days: 30
moc_parent: memories/index.md
---

# Sources
""",
    )
    _write(
        tmp_path / "memories/sources/a.md",
        """---
page_id: source-a
page_type: source
title: "Source A"
context: example
visibility: private_self
updated_at: 2026-07-01
stale_after_days: 30
moc_parent: memories/index.md
---

# Source A
""",
    )

    snapshot = build_snapshot(tmp_path, config, generated_at="2026-07-01T00:00:00Z")
    edge = next(
        row
        for row in snapshot["graph.json"]["edges"]
        if row["source"] == "source-a"
        and row["target"] == "source-registry"
        and row["type"] == "collection_member"
    )
    assert edge["basis"] == "collection.member_types"
    assert edge["provenance"] == {
        "page_id": "",
        "path": "wiki.templates.yaml",
        "field": "templates.types.source_registry.collection",
        "origin": "template_default",
    }


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

    subprocess.run(["git", "add", "generated-output/manifest.json"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "sibling generated output"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    after_sibling_commit = build_snapshot(
        source_root, config, generated_at="2026-07-01T00:00:00Z"
    )["manifest.json"]["source_sha"]
    assert after_sibling_commit == initial

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


def test_sidecar_body_change_requires_fresh_snapshot_revision(
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
    with pytest.raises(ValueError, match="page changed since snapshot"):
        prepare_snapshot_artifacts(
            tmp_path, config, payloads, content_sidecars=True
        )
    refreshed_payloads = build_snapshot(
        tmp_path,
        config,
        generated_at="2026-07-01T00:00:00Z",
        content_sidecars=True,
    )
    second = prepare_snapshot_artifacts(
        tmp_path, config, refreshed_payloads, content_sidecars=True
    )

    assert second["pages.json"] != first["pages.json"]
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


def test_source_lifecycle_typo_is_actionable_and_publication_stays_fail_closed(
    tmp_path: Path,
) -> None:
    invalid_root = tmp_path / "invalid"
    invalid_config = _sample_repo(invalid_root)
    _write_source_lifecycle_fixture(
        invalid_root,
        attempt_state="retrying",
        pipeline_stage="em_progresso",
    )
    invalid = build_snapshot(
        invalid_root,
        invalid_config,
        generated_at="2026-07-01T00:00:00Z",
    )
    row = next(
        source
        for source in invalid["source_lifecycle.json"]["sources"]
        if source["source_id"] == "source-bank"
    )
    assert row["last_attempt_state"] == "retrying"
    assert row["pipeline_stage"] == "em_progresso"
    assert invalid["manifest.json"]["contract_errors"] == [
        "invalid source last_attempt_state: source-bank value='retrying'; "
        "allowed=failed, needs_auth, never, ok, parser_error, secret_blocked",
        "invalid source pipeline_stage: source-bank value='em_progresso'; "
        "allowed=complete, configured, deep_read, extracted, gate_pending, indexed, "
        "integrating, manifested, proposal_ready",
    ]

    invalid_out = invalid_root / "snapshot-out"
    with pytest.raises(ValueError, match="invalid source last_attempt_state"):
        write_snapshot(invalid_root, invalid_out, invalid_config)
    assert not invalid_out.exists()


def test_source_lifecycle_conflict_and_acceptance_dependencies_reach_snapshot_gate(
    tmp_path: Path,
) -> None:
    root = tmp_path / "conflict"
    config = _sample_repo(root)
    _write(
        root / "memories/sources/bank.md",
        "---\n"
        "page_id: source-bank\n"
        "page_type: source\n"
        "title: Bank statements\n"
        "context: example\n"
        "visibility: private_self\n"
        "updated_at: 2026-07-01\n"
        "stale_after_days: 30\n"
        "moc_parent: memories/index.md\n"
        "source_last_attempt_state: ok\n"
        "source_lifecycle:\n"
        "  state: ingested\n"
        "  freshness_state: fresh\n"
        "  last_attempt_state: failed\n"
        "  pipeline_stage: complete\n"
        "  adoption_state: accepted\n"
        "  emitted_page_ids: [page-one]\n"
        "---\n\n"
        "# Bank statements\n",
    )

    snapshot = build_snapshot(
        root,
        config,
        generated_at="2026-07-01T00:00:00Z",
    )
    errors = snapshot["manifest.json"]["contract_errors"]

    assert any(
        "[conflicting_source_last_attempt_state]" in error for error in errors
    )
    assert any("[accepted_source_missing_ref]" in error for error in errors)
    assert any("accepted source missing ref/emitted-page closure" in error for error in errors)


def test_snapshot_contract_never_echoes_secret_shaped_invalid_lifecycle_value(
    tmp_path: Path,
) -> None:
    secret = "sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz123456"
    root = tmp_path / "redacted"
    config = _sample_repo(root)
    _write(
        root / "memories/sources/bank.md",
        "---\n"
        "page_id: source-bank\n"
        "page_type: source\n"
        "title: Bank statements\n"
        "context: example\n"
        "visibility: private_self\n"
        "updated_at: 2026-07-01\n"
        "stale_after_days: 30\n"
        "moc_parent: memories/index.md\n"
        "source_lifecycle:\n"
        f"  state: {secret}\n"
        "  freshness_state: never_synced\n"
        "  last_attempt_state: never\n"
        "  pipeline_stage: configured\n"
        "  adoption_state: pending\n"
        "---\n\n"
        "# Bank statements\n",
    )

    snapshot = build_snapshot(
        root,
        config,
        generated_at="2026-07-01T00:00:00Z",
    )
    rendered = json.dumps(snapshot["manifest.json"]["contract_errors"])

    assert secret not in rendered
    assert "[invalid_source_lifecycle_state]" in rendered


def test_nested_blocked_reason_projects_and_conflicting_compatibility_fails_closed(
    tmp_path: Path,
) -> None:
    def write_source(root: Path, *, compatibility_reason: str = "") -> None:
        compatibility_line = (
            f"source_blocked_reason: {compatibility_reason}\n"
            if compatibility_reason
            else ""
        )
        _write(
            root / "memories/sources/bank.md",
            "---\n"
            "page_id: source-bank\n"
            "page_type: source\n"
            "title: Bank statements\n"
            "context: example\n"
            "visibility: private_self\n"
            "updated_at: 2026-07-01\n"
            "stale_after_days: 30\n"
            "moc_parent: memories/index.md\n"
            f"{compatibility_line}"
            "source_lifecycle:\n"
            "  state: blocked\n"
            "  freshness_state: stale\n"
            "  last_attempt_state: failed\n"
            "  pipeline_stage: manifested\n"
            "  adoption_state: pending\n"
            "  blocked_reason: Nested safe parser failure.\n"
            "---\n\n"
            "# Bank statements\n",
        )

    canonical_root = tmp_path / "canonical"
    canonical_config = _sample_repo(canonical_root)
    write_source(canonical_root)
    canonical = build_snapshot(
        canonical_root,
        canonical_config,
        generated_at="2026-07-01T00:00:00Z",
    )
    row = next(
        source
        for source in canonical["source_lifecycle.json"]["sources"]
        if source["source_id"] == "source-bank"
    )
    assert row["blocked_reason"] == "Nested safe parser failure."
    assert canonical["manifest.json"]["contract_errors"] == []

    conflict_root = tmp_path / "conflict"
    conflict_config = _sample_repo(conflict_root)
    write_source(conflict_root, compatibility_reason="Flat safe parser failure.")
    conflict = build_snapshot(
        conflict_root,
        conflict_config,
        generated_at="2026-07-01T00:00:00Z",
    )
    conflict_errors = conflict["manifest.json"]["contract_errors"]
    assert any(
        "[conflicting_source_blocked_reason]" in error
        for error in conflict_errors
    )


@pytest.mark.parametrize(
    ("attempt_state", "pipeline_stage", "expected_attempt", "expected_stage"),
    (("ok", "complete", "ok", "complete"), ("partial", "", "failed", "configured")),
)
def test_canonical_and_legacy_source_lifecycle_values_publish_atomically(
    tmp_path: Path,
    attempt_state: str,
    pipeline_stage: str,
    expected_attempt: str,
    expected_stage: str,
) -> None:
    root = tmp_path / attempt_state
    config = _sample_repo(root)
    _write_source_lifecycle_fixture(
        root,
        attempt_state=attempt_state,
        pipeline_stage=pipeline_stage,
    )
    snapshot = build_snapshot(
        root,
        config,
        generated_at="2026-07-01T00:00:00Z",
    )
    row = next(
        source
        for source in snapshot["source_lifecycle.json"]["sources"]
        if source["source_id"] == "source-bank"
    )
    assert row["last_attempt_state"] == expected_attempt
    assert row["pipeline_stage"] == expected_stage
    assert snapshot_contract_errors(snapshot) == []

    out = root / "snapshot-out"
    written = write_snapshot(root, out, config)
    assert set(written) == set(SNAPSHOT_FILES)
    assert (out / "manifest.json").is_file()
    assert (out / OUTPUT_OWNER_FILENAME).is_file()


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
    assert out_dir.is_symlink()
    active_relative = Path(os.readlink(out_dir))
    assert active_relative.parts == (
        snapshot_module._revision_store_path(out_dir).name,
        active_relative.name,
    )
    assert snapshot_module.SNAPSHOT_REVISION_HASH_RE.fullmatch(active_relative.name)
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"] == list(SNAPSHOT_FILES)
    assert (out_dir / OUTPUT_OWNER_FILENAME).is_file()
    assert snapshot_module.load_active_snapshot_artifacts(
        out_dir,
        expected_repo_id=config.repo_id,
    )["manifest.json"]["snapshot_id"] == manifest["snapshot_id"]


def test_snapshot_refuses_unowned_directory_and_preserves_user_files(
    tmp_path: Path,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "personal-notes"
    user_file = out_dir / "do-not-delete.txt"
    _write(user_file, "irreplaceable\n")

    with pytest.raises(ValueError, match="unowned non-empty"):
        write_snapshot(tmp_path, out_dir, config, clean=True)

    assert user_file.read_text(encoding="utf-8") == "irreplaceable\n"
    assert not (out_dir / "manifest.json").exists()

    write_snapshot(
        tmp_path,
        out_dir,
        config,
        clean=True,
        force_unowned_output=True,
    )
    assert not user_file.exists()
    assert (out_dir / OUTPUT_OWNER_FILENAME).is_file()

    # Once marked, the generator can safely replace its own output without a
    # force flag.
    write_snapshot(tmp_path, out_dir, config, clean=True)


def test_snapshot_refuses_output_outside_repository_even_with_force(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    config = _sample_repo(root)
    outside = tmp_path / "outside"
    user_file = outside / "user.txt"
    _write(user_file, "keep\n")

    with pytest.raises(ValueError, match="inside repository root"):
        write_snapshot(
            root,
            outside,
            config,
            clean=True,
            force_unowned_output=True,
        )

    assert user_file.read_text(encoding="utf-8") == "keep\n"


def test_snapshot_refuses_target_symlink_and_preserves_external_directory(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    config = _sample_repo(root)
    external = tmp_path / "external-target"
    keeper = external / "keep.txt"
    _write(keeper, "external target\n")
    out_dir = root / "snapshot-link"
    out_dir.symlink_to(external, target_is_directory=True)

    with pytest.raises(ValueError, match="cannot be a symlink"):
        write_snapshot(
            root,
            out_dir,
            config,
            clean=True,
            force_unowned_output=True,
        )

    assert out_dir.is_symlink()
    assert keeper.read_text(encoding="utf-8") == "external target\n"
    assert sorted(
        path.relative_to(external).as_posix()
        for path in external.rglob("*")
        if path.is_file()
    ) == ["keep.txt"]


def test_snapshot_refuses_ancestor_symlink_escape_and_preserves_external_directory(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    config = _sample_repo(root)
    external = tmp_path / "external-ancestor"
    keeper = external / "snapshot" / "keep.txt"
    _write(keeper, "external ancestor\n")
    linked_parent = root / "linked-parent"
    linked_parent.symlink_to(external, target_is_directory=True)

    with pytest.raises(ValueError, match="inside repository root"):
        write_snapshot(
            root,
            linked_parent / "snapshot",
            config,
            clean=True,
            force_unowned_output=True,
        )

    assert linked_parent.is_symlink()
    assert keeper.read_text(encoding="utf-8") == "external ancestor\n"
    assert sorted(
        path.relative_to(external).as_posix()
        for path in external.rglob("*")
        if path.is_file()
    ) == ["snapshot/keep.txt"]


def test_snapshot_does_not_auto_adopt_current_unmarked_directory(
    tmp_path: Path,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "current-unmarked-snapshot"
    write_snapshot(tmp_path, out_dir, config, clean=True)
    _materialize_snapshot_pointer(out_dir)
    (out_dir / OUTPUT_OWNER_FILENAME).unlink()
    before = {
        path.relative_to(out_dir).as_posix(): path.read_bytes()
        for path in sorted(item for item in out_dir.rglob("*") if item.is_file())
    }

    with pytest.raises(ValueError, match="unowned non-empty"):
        write_snapshot(tmp_path, out_dir, config, clean=True)

    after = {
        path.relative_to(out_dir).as_posix(): path.read_bytes()
        for path in sorted(item for item in out_dir.rglob("*") if item.is_file())
    }
    assert after == before


def test_snapshot_adopts_only_legacy_hash_gap_from_same_repo(tmp_path: Path) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "same-repo-legacy-snapshot"
    write_snapshot(tmp_path, out_dir, config, clean=True)
    _make_unmarked_legacy_snapshot(out_dir, repo_id=config.repo_id)

    write_snapshot(tmp_path, out_dir, config, clean=True)

    assert (out_dir / OUTPUT_OWNER_FILENAME).is_file()
    assert (
        snapshot_contract_errors(
            {
                name: json.loads((out_dir / name).read_text(encoding="utf-8"))
                for name in json.loads(
                    (out_dir / "manifest.json").read_text(encoding="utf-8")
                )["files"]
            }
        )
        == []
    )


def test_snapshot_refuses_legacy_hash_gap_from_different_repo(tmp_path: Path) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "other-repo-legacy-snapshot"
    write_snapshot(tmp_path, out_dir, config, clean=True)
    _make_unmarked_legacy_snapshot(out_dir, repo_id="different-repo")
    before = (out_dir / "manifest.json").read_bytes()

    with pytest.raises(ValueError, match="unowned non-empty"):
        write_snapshot(tmp_path, out_dir, config, clean=True)

    assert (out_dir / "manifest.json").read_bytes() == before
    assert not (out_dir / OUTPUT_OWNER_FILENAME).exists()


def test_snapshot_pointer_activation_preserves_previous_on_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    write_snapshot(tmp_path, out_dir, config, clean=True)
    before = _snapshot_file_map(out_dir)
    page = tmp_path / "memories/example/index.md"
    page.write_text(page.read_text(encoding="utf-8") + "\nChanged.\n", encoding="utf-8")

    def fail_activation(*args: object, **kwargs: object) -> bool:
        raise OSError("synthetic promotion failure")

    monkeypatch.setattr(
        snapshot_module,
        "_activate_snapshot_pointer_cas",
        fail_activation,
    )
    with pytest.raises(OSError, match="synthetic promotion failure"):
        write_snapshot(tmp_path, out_dir, config, clean=True)

    after = _snapshot_file_map(out_dir)
    assert after == before
    assert not list(out_dir.parent.glob(f".{out_dir.name}.stage-*"))


def test_absent_activation_race_preserves_external_bytes_and_blocks_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    artifacts = _prepared_snapshot_variant(tmp_path, config, version=1)
    revision = str(artifacts["manifest.json"]["bundle_hash"])
    original_install = snapshot_module._atomic_install_directory_noreplace
    external_bytes = b"external writer owns this pathname\n"
    injected = False

    def inject_absent_collision(source: Path, target: Path) -> None:
        nonlocal injected
        if not injected and Path(source).name == "active" and Path(target) == out_dir:
            injected = True
            out_dir.write_bytes(external_bytes)
        original_install(source, target)

    monkeypatch.setattr(
        snapshot_module,
        "_atomic_install_directory_noreplace",
        inject_absent_collision,
    )

    with pytest.raises(
        snapshot_module.SnapshotPublicationBlockedError,
        match="active pathname appeared after preflight",
    ) as blocked:
        snapshot_module.promote_snapshot_revisioned(tmp_path, out_dir, artifacts)

    assert blocked.value.committed is False
    assert injected is True
    assert out_dir.is_file() and not out_dir.is_symlink()
    assert out_dir.read_bytes() == external_bytes
    assert not (snapshot_module._revision_store_path(out_dir) / revision).exists()


def test_existing_activation_race_restores_external_replacement_and_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    variants = [
        _prepared_snapshot_variant(tmp_path, config, version=index)
        for index in range(2)
    ]
    snapshot_module.promote_snapshot_revisioned(tmp_path, out_dir, variants[0])
    original_exchange = snapshot_module._atomic_exchange_paths
    external_bytes = b"external replacement must survive CAS rollback\n"
    injected = False

    def inject_existing_collision(first: Path, second: Path) -> None:
        nonlocal injected
        if not injected and Path(first) == out_dir and Path(second).name == "active":
            injected = True
            out_dir.unlink()
            out_dir.write_bytes(external_bytes)
        original_exchange(first, second)

    monkeypatch.setattr(
        snapshot_module,
        "_atomic_exchange_paths",
        inject_existing_collision,
    )

    with pytest.raises(
        snapshot_module.SnapshotPublicationBlockedError,
        match="external entry restored",
    ) as blocked:
        snapshot_module.promote_snapshot_revisioned(tmp_path, out_dir, variants[1])

    assert blocked.value.committed is False
    assert injected is True
    assert out_dir.is_file() and not out_dir.is_symlink()
    assert out_dir.read_bytes() == external_bytes


def test_snapshot_flat_migration_preserves_current_on_exchange_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    write_snapshot(tmp_path, out_dir, config, clean=True)
    _materialize_snapshot_pointer(out_dir)
    before = _snapshot_file_map(out_dir)
    page = tmp_path / "memories/example/index.md"
    page.write_text(page.read_text(encoding="utf-8") + "\nChanged.\n", encoding="utf-8")

    def fail_atomic_exchange(source: Path, target: Path) -> None:
        raise OSError("synthetic atomic exchange failure")

    monkeypatch.setattr(
        snapshot_module, "_atomic_exchange_paths", fail_atomic_exchange
    )
    with pytest.raises(OSError, match="synthetic atomic exchange failure"):
        write_snapshot(tmp_path, out_dir, config, clean=True)

    after = _snapshot_file_map(out_dir)
    assert after == before
    assert not list(out_dir.parent.glob(f".{out_dir.name}.stage-*"))


def test_snapshot_migration_preserves_recovery_directory_when_archive_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    write_snapshot(tmp_path, out_dir, config, clean=True)
    _materialize_snapshot_pointer(out_dir)
    before = _snapshot_file_map(out_dir)
    page = tmp_path / "memories/example/index.md"
    page.write_text(page.read_text(encoding="utf-8") + "\nChanged.\n", encoding="utf-8")

    def fail_previous_archive(*args: object, **kwargs: object) -> None:
        raise OSError("synthetic previous archive failure")

    monkeypatch.setattr(
        snapshot_module,
        "_archive_exchanged_snapshot_directory",
        fail_previous_archive,
    )
    result = write_snapshot(tmp_path, out_dir, config, clean=True)

    assert result.committed is True
    assert any(
        warning.startswith("previous_snapshot_recovery_pending:")
        for warning in result.cleanup_warnings
    )
    assert out_dir.is_symlink()
    assert snapshot_module.load_active_snapshot_artifacts(out_dir)["manifest.json"]
    backups = list(out_dir.parent.glob(f".{out_dir.name}.activate-*/active"))
    assert len(backups) == 1
    recovered = {
        path.relative_to(backups[0]).as_posix(): path.read_bytes()
        for path in sorted(item for item in backups[0].rglob("*") if item.is_file())
    }
    assert recovered == before
    assert backups[0].is_dir() and not backups[0].is_symlink()
    assert tuple(result.recovery_paths) == (backups[0],)

    # A later successful publication reconciles the publisher-owned recovery
    # container instead of accumulating or silently deleting it.
    monkeypatch.undo()
    follow_up = write_snapshot(tmp_path, out_dir, config, clean=True)
    assert follow_up.committed is True
    assert not list(out_dir.parent.glob(f".{out_dir.name}.activate-*"))


def test_snapshot_rejects_invalid_staged_manifest_before_activation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    write_snapshot(tmp_path, out_dir, config, clean=True)
    before = _snapshot_file_map(out_dir)
    page = tmp_path / "memories/example/index.md"
    page.write_text(page.read_text(encoding="utf-8") + "\nChanged.\n", encoding="utf-8")

    original_write = snapshot_module._write_snapshot_artifacts

    def write_invalid_manifest(
        target_dir: Path, artifacts: dict[str, dict[str, object]]
    ) -> dict[str, Path]:
        written = original_write(target_dir, artifacts)
        manifest_path = target_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"] = manifest["files"][:-1]
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return written

    monkeypatch.setattr(
        snapshot_module, "_write_snapshot_artifacts", write_invalid_manifest
    )
    with pytest.raises(
        ValueError, match="snapshot staging directory differs from manifest"
    ):
        write_snapshot(tmp_path, out_dir, config, clean=True)

    after = _snapshot_file_map(out_dir)
    assert after == before
    assert not list(out_dir.parent.glob(f".{out_dir.name}.stage-*"))


def test_snapshot_refuses_parent_traversal_artifact_without_external_write(
    tmp_path: Path,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    write_snapshot(tmp_path, out_dir, config, clean=True)
    before = _snapshot_file_map(out_dir)

    payloads = build_snapshot(
        tmp_path,
        config,
        generated_at="2026-07-01T00:00:00Z",
    )
    artifacts = prepare_snapshot_artifacts(
        tmp_path, config, payloads, content_sidecars=False
    )
    unsafe_name = "../rt55-escaped.json"
    artifacts[unsafe_name] = {"unsafe": True}
    manifest = artifacts["manifest.json"]
    manifest["files"].append(unsafe_name)
    manifest["integrity"][unsafe_name] = snapshot_module._payload_integrity(
        artifacts[unsafe_name]
    )
    bundle_hash = snapshot_module._bundle_hash_for_artifacts(artifacts)
    manifest["bundle_hash"] = bundle_hash
    manifest["snapshot_id"] = f"{config.repo_id}-{bundle_hash[:16]}"
    manifest["contract_errors"] = []
    assert snapshot_contract_errors(artifacts) == []

    external_path = out_dir.parent / "rt55-escaped.json"
    with pytest.raises(ValueError, match="unsafe snapshot artifact path"):
        snapshot_module.promote_snapshot_revisioned(
            tmp_path,
            out_dir,
            artifacts,
        )

    assert not external_path.exists()
    after = _snapshot_file_map(out_dir)
    assert after == before
    assert not list(out_dir.parent.glob(f".{out_dir.name}.stage-*"))


def test_snapshot_revision_pointer_rejects_unowned_internal_target(
    tmp_path: Path,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    write_snapshot(tmp_path, out_dir, config, clean=True)
    store = snapshot_module._revision_store_path(out_dir)
    unowned_revision = store / ("a" * 64)
    unowned_revision.mkdir()
    _write(unowned_revision / "keep.txt", "not publisher-owned\n")
    out_dir.unlink()
    out_dir.symlink_to(
        Path(store.name) / unowned_revision.name,
        target_is_directory=True,
    )

    with pytest.raises(ValueError, match="snapshot revision is not owned"):
        write_snapshot(tmp_path, out_dir, config, clean=True)

    assert (unowned_revision / "keep.txt").read_text(encoding="utf-8") == (
        "not publisher-owned\n"
    )


def test_snapshot_publication_lock_refuses_symlink_without_touching_target(
    tmp_path: Path,
) -> None:
    config = _sample_repo(tmp_path)
    artifacts = _prepared_snapshot_variant(tmp_path, config, version=1)
    out_dir = tmp_path / "snapshot-output"
    external = tmp_path / "publication-lock-target.txt"
    _write(external, "preserve external bytes\n")
    lock_path = out_dir.parent / f".{out_dir.name}.publication.lock"
    lock_path.symlink_to(external)

    with pytest.raises(ValueError, match="cannot be a symlink"):
        snapshot_module.promote_snapshot_revisioned(
            tmp_path,
            out_dir,
            artifacts,
        )

    assert external.read_text(encoding="utf-8") == "preserve external bytes\n"
    assert lock_path.is_symlink()
    assert not out_dir.exists() and not snapshot_module._revision_store_path(
        out_dir
    ).exists()


def test_revision_lease_rejects_traversal_symlink_directory_and_symlink_leaf(
    tmp_path: Path,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    write_snapshot(tmp_path, out_dir, config, clean=True)
    store = snapshot_module._revision_store_path(out_dir)
    revision = Path(os.readlink(out_dir)).name
    leases = store / "leases"

    with pytest.raises(ValueError, match="must be a sha256"):
        with snapshot_module._revision_lease(
            store,
            "../../escaped",
            exclusive=False,
        ):
            pass
    assert not (store.parent / "escaped.lock").exists()

    external_dir = tmp_path / "external-leases"
    external_dir.mkdir()
    shutil.rmtree(leases)
    leases.symlink_to(external_dir, target_is_directory=True)
    with pytest.raises(ValueError, match="leases directory is unsafe"):
        snapshot_module.load_active_snapshot_artifacts(out_dir)
    assert list(external_dir.iterdir()) == []

    leases.unlink()
    leases.mkdir()
    external_lock = tmp_path / "external-lock.txt"
    _write(external_lock, "preserve lock target\n")
    (leases / f"{revision}.lock").symlink_to(external_lock)
    with pytest.raises(ValueError, match="lease lock is unsafe"):
        snapshot_module.load_active_snapshot_artifacts(out_dir)
    assert external_lock.read_text(encoding="utf-8") == "preserve lock target\n"

    (leases / f"{revision}.lock").unlink()
    real_store = store.with_name(f"{store.name}.held")
    os.replace(store, real_store)
    external_store = tmp_path / "external-store"
    (external_store / "leases").mkdir(parents=True)
    store.symlink_to(external_store, target_is_directory=True)
    with pytest.raises(ValueError, match="lease lock is unsafe"):
        with snapshot_module._revision_lease(store, revision, exclusive=False):
            pass
    assert list((external_store / "leases").iterdir()) == []


def test_existing_and_racing_revision_directory_must_match_requested_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    variants = [
        _prepared_snapshot_variant(tmp_path, config, version=index)
        for index in range(3)
    ]
    snapshot_module.promote_snapshot_revisioned(tmp_path, out_dir, variants[0])
    store = snapshot_module._revision_store_path(out_dir)
    active_dir = out_dir.resolve(strict=True)
    before = _snapshot_file_map(out_dir)

    requested_existing = str(variants[1]["manifest.json"]["bundle_hash"])
    shutil.copytree(active_dir, store / requested_existing)
    with pytest.raises(ValueError, match="revision identity mismatch"):
        snapshot_module.promote_snapshot_revisioned(
            tmp_path,
            out_dir,
            variants[1],
        )
    assert _snapshot_file_map(out_dir) == before

    requested_race = str(variants[2]["manifest.json"]["bundle_hash"])
    race_target = store / requested_race
    original_install = snapshot_module._atomic_install_directory_noreplace

    def install_wrong_racing_revision(source: Path, target: Path) -> None:
        source_path = Path(source)
        target_path = Path(target)
        if source_path.name.startswith(".stage-") and target_path == race_target:
            shutil.copytree(active_dir, race_target)
            raise FileExistsError("synthetic racing revision")
        original_install(source, target)

    monkeypatch.setattr(
        snapshot_module,
        "_atomic_install_directory_noreplace",
        install_wrong_racing_revision,
    )
    with pytest.raises(ValueError, match="revision identity mismatch"):
        snapshot_module.promote_snapshot_revisioned(
            tmp_path,
            out_dir,
            variants[2],
        )
    assert _snapshot_file_map(out_dir) == before


def test_revision_install_preserves_broken_and_external_target_symlinks(
    tmp_path: Path,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    variants = [
        _prepared_snapshot_variant(tmp_path, config, version=index)
        for index in range(3)
    ]
    snapshot_module.promote_snapshot_revisioned(tmp_path, out_dir, variants[0])
    store = snapshot_module._revision_store_path(out_dir)
    before = _snapshot_file_map(out_dir)

    broken_revision = str(variants[1]["manifest.json"]["bundle_hash"])
    broken_target = store / broken_revision
    missing = tmp_path / "missing-external-revision"
    broken_target.symlink_to(missing, target_is_directory=True)
    with pytest.raises(ValueError, match="directory does not match request"):
        snapshot_module.promote_snapshot_revisioned(
            tmp_path,
            out_dir,
            variants[1],
        )
    assert broken_target.is_symlink()
    assert os.readlink(broken_target) == str(missing)
    assert not missing.exists()

    external = tmp_path / "external-revision"
    external.mkdir()
    sentinel = external / "sentinel.txt"
    sentinel.write_text("preserve external revision\n", encoding="utf-8")
    external_revision = str(variants[2]["manifest.json"]["bundle_hash"])
    external_target = store / external_revision
    external_target.symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError, match="directory does not match request"):
        snapshot_module.promote_snapshot_revisioned(
            tmp_path,
            out_dir,
            variants[2],
        )
    assert external_target.is_symlink()
    assert os.readlink(external_target) == str(external)
    assert sentinel.read_text(encoding="utf-8") == "preserve external revision\n"
    assert _snapshot_file_map(out_dir) == before


def test_flat_archive_preserves_preexisting_revision_symlink_target(
    tmp_path: Path,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    variants = [
        _prepared_snapshot_variant(tmp_path, config, version=index)
        for index in range(2)
    ]
    snapshot_module.promote_snapshot_revisioned(tmp_path, out_dir, variants[0])
    _materialize_snapshot_pointer(out_dir)
    store = snapshot_module._revision_store_path(out_dir)
    old_revision = str(variants[0]["manifest.json"]["bundle_hash"])
    shutil.rmtree(store / old_revision)
    external = tmp_path / "external-archive-target"
    external.mkdir()
    sentinel = external / "sentinel.txt"
    sentinel.write_text("preserve archive target\n", encoding="utf-8")
    archived_target = store / old_revision
    archived_target.symlink_to(external, target_is_directory=True)

    result = snapshot_module.promote_snapshot_revisioned(
        tmp_path,
        out_dir,
        variants[1],
    )

    assert result.committed is True
    assert any(
        warning.startswith("previous_snapshot_recovery_pending:")
        for warning in result.cleanup_warnings
    )
    assert archived_target.is_symlink()
    assert os.readlink(archived_target) == str(external)
    assert sentinel.read_text(encoding="utf-8") == "preserve archive target\n"
    assert len(result.recovery_paths) == 1
    assert result.recovery_paths[0].is_dir()


def test_owned_revision_rejects_symlink_payload_before_external_read(
    tmp_path: Path,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    artifacts = _prepared_snapshot_variant(tmp_path, config, version=1)
    snapshot_module.promote_snapshot_revisioned(tmp_path, out_dir, artifacts)
    revision_dir = out_dir.resolve(strict=True)
    payload = revision_dir / "pages.json"
    external = tmp_path / "external-pages.json"
    external_bytes = payload.read_bytes()
    external.write_bytes(external_bytes)
    payload.unlink()
    payload.symlink_to(external)

    with pytest.raises(ValueError, match="contains symlink: pages.json"):
        snapshot_module.load_active_snapshot_artifacts(
            out_dir,
            expected_repo_id=config.repo_id,
        )

    status = snapshot_module.snapshot_publication_status(
        tmp_path,
        out_dir,
        repo_id=config.repo_id,
    )
    assert status["pointer_state"] == "invalid"
    assert payload.is_symlink()
    assert external.read_bytes() == external_bytes


def test_owned_revision_with_undeclared_file_is_excluded_from_prune_ranking(
    tmp_path: Path,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    variants = [
        _prepared_snapshot_variant(tmp_path, config, version=index)
        for index in range(4)
    ]
    for variant in variants:
        snapshot_module.promote_snapshot_revisioned(
            tmp_path,
            out_dir,
            variant,
            retention=10,
        )
    store = snapshot_module._revision_store_path(out_dir)
    adulterated_revision = str(variants[0]["manifest.json"]["bundle_hash"])
    adulterated = store / adulterated_revision
    extra = adulterated / "user-extra.txt"
    extra.write_text("preserve user bytes\n", encoding="utf-8")
    future = time.time_ns() + 10_000_000_000
    os.utime(adulterated, ns=(future, future))

    cleanup = snapshot_module.prune_snapshot_revisions(
        tmp_path,
        out_dir,
        repo_id=config.repo_id,
        retention=2,
    )

    assert adulterated.is_dir()
    assert extra.read_text(encoding="utf-8") == "preserve user bytes\n"
    assert (
        f"invalid_or_unowned_revision_preserved:{adulterated_revision}"
        in cleanup.cleanup_warnings
    )


def test_foreign_manifest_revision_is_rejected_by_loader_prune_and_health(
    tmp_path: Path,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    local = _prepared_snapshot_variant(tmp_path, config, version=1)
    snapshot_module.promote_snapshot_revisioned(tmp_path, out_dir, local)
    original_target = Path(os.readlink(out_dir))
    store = snapshot_module._revision_store_path(out_dir)

    foreign = json.loads(json.dumps(local))
    foreign_manifest = foreign["manifest.json"]
    foreign_manifest["repo"]["repo_id"] = "foreign-repo"
    foreign["operations.json"]["foreign_probe"] = True
    foreign_manifest["integrity"]["operations.json"] = (
        snapshot_module._payload_integrity(foreign["operations.json"])
    )
    foreign_revision = snapshot_module._bundle_hash_for_artifacts(foreign)
    foreign_manifest["bundle_hash"] = foreign_revision
    foreign_manifest["snapshot_id"] = f"foreign-repo-{foreign_revision[:16]}"
    foreign_manifest["contract_errors"] = snapshot_contract_errors(foreign)
    assert foreign_manifest["contract_errors"] == []

    foreign_dir = store / foreign_revision
    foreign_dir.mkdir()
    snapshot_module._write_snapshot_artifacts(foreign_dir, foreign)
    snapshot_module.write_output_owner(
        foreign_dir,
        kind="web_snapshot",
        repo_id=config.repo_id,
    )
    out_dir.unlink()
    out_dir.symlink_to(
        Path(store.name) / foreign_revision,
        target_is_directory=True,
    )

    with pytest.raises(ValueError, match="different repository"):
        snapshot_module.load_active_snapshot_artifacts(
            out_dir,
            expected_repo_id=config.repo_id,
        )
    assert snapshot_module.snapshot_publication_status(
        tmp_path,
        out_dir,
        repo_id=config.repo_id,
    )["pointer_state"] == "invalid"

    out_dir.unlink()
    out_dir.symlink_to(original_target, target_is_directory=True)
    cleanup = snapshot_module.prune_snapshot_revisions(
        tmp_path,
        out_dir,
        repo_id=config.repo_id,
        retention=2,
    )
    assert foreign_dir.is_dir()
    assert (
        f"invalid_or_unowned_revision_preserved:{foreign_revision}"
        in cleanup.cleanup_warnings
    )


def test_prune_preserves_invalid_or_unowned_sha_directories_under_lock(
    tmp_path: Path,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    variants = [
        _prepared_snapshot_variant(tmp_path, config, version=index)
        for index in range(5)
    ]
    for variant in variants:
        snapshot_module.promote_snapshot_revisioned(
            tmp_path,
            out_dir,
            variant,
            retention=10,
        )
    store = snapshot_module._revision_store_path(out_dir)
    unowned = store / ("e" * 64)
    unowned.mkdir()
    _write(unowned / "keep.txt", "unowned\n")
    mismatched = store / ("f" * 64)
    shutil.copytree(out_dir.resolve(strict=True), mismatched)
    future = time.time_ns() + 10_000_000_000
    os.utime(unowned, ns=(future, future))
    os.utime(mismatched, ns=(future + 1, future + 1))

    cleanup = snapshot_module.prune_snapshot_revisions(
        tmp_path,
        out_dir,
        repo_id=config.repo_id,
        retention=2,
    )

    assert (unowned / "keep.txt").read_text(encoding="utf-8") == "unowned\n"
    assert mismatched.is_dir()
    assert {
        warning.split(":", 1)[0] for warning in cleanup.cleanup_warnings
    } >= {"invalid_or_unowned_revision_preserved"}
    active_revision = Path(os.readlink(out_dir)).name
    assert (store / active_revision).is_dir()
    valid_backup = str(variants[-2]["manifest.json"]["bundle_hash"])
    assert (store / valid_backup).is_dir()


def test_prune_quarantine_preserves_replacement_installed_after_revalidation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    variants = [
        _prepared_snapshot_variant(tmp_path, config, version=index)
        for index in range(4)
    ]
    for variant in variants:
        snapshot_module.promote_snapshot_revisioned(
            tmp_path,
            out_dir,
            variant,
            retention=10,
        )
    store = snapshot_module._revision_store_path(out_dir)
    victim_revision = str(variants[0]["manifest.json"]["bundle_hash"])
    victim = store / victim_revision
    held = store / ".adversarial-held-valid-revision"
    sentinel = victim / "external-sentinel.txt"
    original_validate = snapshot_module._validate_owned_snapshot_revision
    victim_validations = 0
    replacement_installed = False

    def replace_after_leased_validation(
        revision_dir: Path,
        **kwargs: object,
    ) -> dict[str, dict[str, object]]:
        nonlocal replacement_installed, victim_validations
        payloads = original_validate(revision_dir, **kwargs)
        if Path(revision_dir) == victim and kwargs.get("require_directory_name", True):
            victim_validations += 1
            if victim_validations == 2:
                os.replace(victim, held)
                victim.mkdir()
                sentinel.write_text(
                    "arbitrary replacement must not be pruned\n",
                    encoding="utf-8",
                )
                replacement_installed = True
        return payloads

    monkeypatch.setattr(
        snapshot_module,
        "_validate_owned_snapshot_revision",
        replace_after_leased_validation,
    )
    cleanup = snapshot_module.prune_snapshot_revisions(
        tmp_path,
        out_dir,
        repo_id=config.repo_id,
        retention=2,
    )

    assert replacement_installed is True
    assert sentinel.read_text(encoding="utf-8") == (
        "arbitrary replacement must not be pruned\n"
    )
    assert held.is_dir()
    assert victim not in cleanup
    assert (
        f"invalid_or_unowned_revision_preserved:{victim_revision}"
        in cleanup.cleanup_warnings
    )


def test_prune_descriptor_delete_preserves_quarantine_root_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    variants = [
        _prepared_snapshot_variant(tmp_path, config, version=index)
        for index in range(4)
    ]
    for variant in variants:
        snapshot_module.promote_snapshot_revisioned(
            tmp_path,
            out_dir,
            variant,
            retention=10,
        )
    store = snapshot_module._revision_store_path(out_dir)
    victim_revision = str(variants[0]["manifest.json"]["bundle_hash"])
    held_original = store / ".held-valid-quarantine"
    original_delete = snapshot_module._delete_snapshot_tree_descriptor_pinned
    replaced_quarantine: Path | None = None
    sentinel: Path | None = None

    def swap_quarantine_root_before_descriptor_delete(
        store_path: Path,
        quarantine: Path,
        **kwargs: object,
    ) -> None:
        nonlocal replaced_quarantine, sentinel
        if (
            replaced_quarantine is None
            and quarantine.name.startswith(f".prune-{victim_revision}-")
        ):
            os.replace(quarantine, held_original)
            quarantine.mkdir()
            sentinel = quarantine / "external-sentinel.txt"
            sentinel.write_text(
                "replacement after second validation\n",
                encoding="utf-8",
            )
            replaced_quarantine = quarantine
        original_delete(store_path, quarantine, **kwargs)

    monkeypatch.setattr(
        snapshot_module,
        "_delete_snapshot_tree_descriptor_pinned",
        swap_quarantine_root_before_descriptor_delete,
    )
    cleanup = snapshot_module.prune_snapshot_revisions(
        tmp_path,
        out_dir,
        repo_id=config.repo_id,
        retention=2,
    )

    assert replaced_quarantine is not None and replaced_quarantine.is_dir()
    assert sentinel is not None
    assert sentinel.read_text(encoding="utf-8") == (
        "replacement after second validation\n"
    )
    assert held_original.is_dir()
    assert all(path.name != victim_revision for path in cleanup)
    assert (
        f"revision_prune_descriptor_race_preserved:{victim_revision}"
        in cleanup.cleanup_warnings
    )
    assert set(cleanup.recovery_paths) >= {replaced_quarantine, held_original}


def test_precommit_fsync_failure_preserves_previous_and_postcommit_is_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    variants = [
        _prepared_snapshot_variant(tmp_path, config, version=index)
        for index in range(3)
    ]
    snapshot_module.promote_snapshot_revisioned(tmp_path, out_dir, variants[0])
    before = _snapshot_file_map(out_dir)
    original_fsync_directory = snapshot_module._fsync_directory

    def fail_staging_fsync(directory: Path) -> None:
        if directory.name.startswith(".stage-"):
            raise OSError("synthetic precommit fsync failure")
        original_fsync_directory(directory)

    monkeypatch.setattr(snapshot_module, "_fsync_directory", fail_staging_fsync)
    with pytest.raises(OSError, match="synthetic precommit fsync failure"):
        snapshot_module.promote_snapshot_revisioned(
            tmp_path,
            out_dir,
            variants[1],
        )
    assert _snapshot_file_map(out_dir) == before

    monkeypatch.undo()
    original_fsync_directory = snapshot_module._fsync_directory
    parent_fsync_calls = 0

    def fail_second_parent_fsync(directory: Path) -> None:
        nonlocal parent_fsync_calls
        if directory == out_dir.parent:
            parent_fsync_calls += 1
            if parent_fsync_calls == 2:
                raise OSError("synthetic postcommit fsync failure")
        original_fsync_directory(directory)

    monkeypatch.setattr(snapshot_module, "_fsync_directory", fail_second_parent_fsync)
    committed = snapshot_module.promote_snapshot_revisioned(
        tmp_path,
        out_dir,
        variants[2],
    )
    assert committed.committed is True
    assert "active_pointer_parent_fsync_failed" in committed.cleanup_warnings
    assert snapshot_module.load_active_snapshot_artifacts(out_dir)["manifest.json"]


def test_postcommit_activation_container_value_error_is_warning_and_reconciles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    artifacts = _prepared_snapshot_variant(tmp_path, config, version=1)
    original_remove = snapshot_module._remove_owned_activation_container

    def fail_container_cleanup(*args: object, **kwargs: object) -> None:
        raise ValueError("synthetic postcommit container cleanup failure")

    monkeypatch.setattr(
        snapshot_module,
        "_remove_owned_activation_container",
        fail_container_cleanup,
    )
    result = snapshot_module.promote_snapshot_revisioned(
        tmp_path,
        out_dir,
        artifacts,
    )

    assert result.committed is True
    assert any(
        warning.startswith("activation_container_cleanup_failed:")
        for warning in result.cleanup_warnings
    )
    assert out_dir.is_symlink()
    assert len(result.recovery_paths) == 1

    monkeypatch.setattr(
        snapshot_module,
        "_remove_owned_activation_container",
        original_remove,
    )
    follow_up = snapshot_module.promote_snapshot_revisioned(
        tmp_path,
        out_dir,
        artifacts,
    )
    assert follow_up.committed is True
    assert not list(out_dir.parent.glob(f".{out_dir.name}.activate-*"))


def test_pointer_and_archive_commits_fsync_both_mutated_parent_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    variants = [
        _prepared_snapshot_variant(tmp_path, config, version=index)
        for index in range(3)
    ]
    snapshot_module.promote_snapshot_revisioned(tmp_path, out_dir, variants[0])
    original_exchange = snapshot_module._atomic_exchange_paths
    original_fsync_directory = snapshot_module._fsync_directory
    events: list[tuple[str, Path]] = []

    def record_exchange(first: Path, second: Path) -> None:
        first_path = Path(first)
        second_path = Path(second)
        original_exchange(first, second)
        if first_path == out_dir and second_path.name == "active":
            events.append(("pointer_commit", second_path.parent))

    def record_fsync(directory: Path) -> None:
        events.append(("fsync", Path(directory)))
        original_fsync_directory(directory)

    monkeypatch.setattr(snapshot_module, "_atomic_exchange_paths", record_exchange)
    monkeypatch.setattr(snapshot_module, "_fsync_directory", record_fsync)
    snapshot_module.promote_snapshot_revisioned(tmp_path, out_dir, variants[1])
    commit_index = next(
        index for index, event in enumerate(events) if event[0] == "pointer_commit"
    )
    activation_dir = events[commit_index][1]
    assert events[commit_index + 1 : commit_index + 3] == [
        ("fsync", activation_dir),
        ("fsync", out_dir.parent),
    ]

    monkeypatch.undo()
    _materialize_snapshot_pointer(out_dir)
    old_revision = str(variants[1]["manifest.json"]["bundle_hash"])
    store = snapshot_module._revision_store_path(out_dir)
    shutil.rmtree(store / old_revision)
    events = []
    original_install = snapshot_module._atomic_install_directory_noreplace
    original_fsync_directory = snapshot_module._fsync_directory

    def record_archive_replace(source: Path, target: Path) -> None:
        source_path = Path(source)
        target_path = Path(target)
        original_install(source, target)
        if source_path.name == "active" and target_path.parent == store:
            events.append(("archive_commit", source_path.parent))

    def record_archive_fsync(directory: Path) -> None:
        events.append(("fsync", Path(directory)))
        original_fsync_directory(directory)

    monkeypatch.setattr(
        snapshot_module,
        "_atomic_install_directory_noreplace",
        record_archive_replace,
    )
    monkeypatch.setattr(snapshot_module, "_fsync_directory", record_archive_fsync)
    snapshot_module.promote_snapshot_revisioned(tmp_path, out_dir, variants[2])
    archive_index = next(
        index for index, event in enumerate(events) if event[0] == "archive_commit"
    )
    archive_source_parent = events[archive_index][1]
    assert events[archive_index + 1 : archive_index + 3] == [
        ("fsync", archive_source_parent),
        ("fsync", store),
    ]


def test_activation_source_fsync_failure_is_committed_cleanup_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    artifacts = _prepared_snapshot_variant(tmp_path, config, version=1)
    original_install = snapshot_module._atomic_install_directory_noreplace
    original_fsync_directory = snapshot_module._fsync_directory
    committed = False
    failed = False

    def observe_commit(source: Path, target: Path) -> None:
        nonlocal committed
        original_install(source, target)
        if Path(source).name == "active" and Path(target) == out_dir:
            committed = True

    def fail_source_fsync_after_commit(directory: Path) -> None:
        nonlocal failed
        if committed and not failed and ".activate-" in Path(directory).name:
            failed = True
            raise OSError("synthetic activation source fsync failure")
        original_fsync_directory(directory)

    monkeypatch.setattr(
        snapshot_module,
        "_atomic_install_directory_noreplace",
        observe_commit,
    )
    monkeypatch.setattr(
        snapshot_module,
        "_fsync_directory",
        fail_source_fsync_after_commit,
    )
    result = snapshot_module.promote_snapshot_revisioned(
        tmp_path,
        out_dir,
        artifacts,
    )

    assert result.committed is True
    assert failed is True
    assert "activation_source_directory_fsync_failed" in result.cleanup_warnings
    assert snapshot_module.load_active_snapshot_artifacts(out_dir)["manifest.json"]


def test_cleanup_tombstone_survives_marker_to_rmdir_failure_and_reconciles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    artifacts = _prepared_snapshot_variant(tmp_path, config, version=1)
    original_rmdir = snapshot_module.os.rmdir
    failed = False

    def fail_cleanup_rmdir(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        *args: object,
        **kwargs: object,
    ) -> None:
        nonlocal failed
        if not failed and ".cleanup-" in os.fsdecode(path):
            failed = True
            raise OSError("synthetic cleanup tombstone rmdir failure")
        original_rmdir(path, *args, **kwargs)

    monkeypatch.setattr(snapshot_module.os, "rmdir", fail_cleanup_rmdir)
    result = snapshot_module.promote_snapshot_revisioned(
        tmp_path,
        out_dir,
        artifacts,
    )

    assert result.committed is True
    assert failed is True
    assert any(
        warning.startswith("activation_container_cleanup_failed:")
        for warning in result.cleanup_warnings
    )
    tombstones = list(out_dir.parent.glob(f".{out_dir.name}.cleanup-*"))
    assert len(tombstones) == 1
    assert list(tombstones[0].iterdir()) == []
    store = snapshot_module._revision_store_path(out_dir)
    receipt = snapshot_module._read_cleanup_receipt(
        store,
        tombstones[0],
        output_kind="web_snapshot",
        repo_id=config.repo_id,
    )
    assert receipt is not None
    assert receipt["binding_sha256"] == snapshot_module._cleanup_receipt_binding(
        receipt_id=receipt["receipt_id"],
        activation_name=receipt["activation_name"],
        cleanup_name=receipt["cleanup_name"],
        cleanup_dev=receipt["cleanup_dev"],
        cleanup_ino=receipt["cleanup_ino"],
        cleanup_type=receipt["cleanup_type"],
        output_kind="web_snapshot",
        repo_id=config.repo_id,
    )
    assert tuple(result.recovery_paths) == (tombstones[0],)
    health = snapshot_module.snapshot_publication_status(
        tmp_path,
        out_dir,
        repo_id=config.repo_id,
    )
    assert health["recovery"]["cleanup_empty_pending"] == 1
    assert health["recovery"]["owned_pending"] == 1

    monkeypatch.setattr(snapshot_module.os, "rmdir", original_rmdir)
    follow_up = snapshot_module.promote_snapshot_revisioned(
        tmp_path,
        out_dir,
        artifacts,
    )
    assert follow_up.committed is True
    assert not list(out_dir.parent.glob(f".{out_dir.name}.cleanup-*"))
    assert not list(out_dir.parent.glob(f".{out_dir.name}.activate-*"))


def test_unreceipted_empty_cleanup_prefix_directory_is_never_deleted(
    tmp_path: Path,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    artifacts = _prepared_snapshot_variant(tmp_path, config, version=1)
    arbitrary = out_dir.parent / f".{out_dir.name}.cleanup-user-created"
    arbitrary.mkdir()

    result = snapshot_module.promote_snapshot_revisioned(
        tmp_path,
        out_dir,
        artifacts,
    )

    assert result.committed is True
    assert arbitrary.is_dir()
    assert list(arbitrary.iterdir()) == []
    assert (
        f"unreceipted_cleanup_tombstone_preserved:{arbitrary.name}"
        in result.cleanup_warnings
    )
    health = snapshot_module.snapshot_publication_status(
        tmp_path,
        out_dir,
        repo_id=config.repo_id,
    )
    assert health["recovery"]["cleanup_ambiguous_preserved"] == 1
    assert health["recovery"]["unowned_preserved"] == 1

    follow_up = snapshot_module.promote_snapshot_revisioned(
        tmp_path,
        out_dir,
        artifacts,
    )
    assert follow_up.committed is True
    assert arbitrary.is_dir()


def test_cleanup_collision_is_never_receipted_or_deleted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    artifacts = _prepared_snapshot_variant(tmp_path, config, version=1)
    original_install = snapshot_module._atomic_install_directory_noreplace
    collision: Path | None = None

    def inject_empty_cleanup_collision(source: Path, target: Path) -> None:
        nonlocal collision
        source_path = Path(source)
        target_path = Path(target)
        if (
            collision is None
            and ".activate-" in source_path.name
            and ".cleanup-" in target_path.name
        ):
            target_path.mkdir()
            collision = target_path
        original_install(source, target)

    monkeypatch.setattr(
        snapshot_module,
        "_atomic_install_directory_noreplace",
        inject_empty_cleanup_collision,
    )
    first = snapshot_module.promote_snapshot_revisioned(tmp_path, out_dir, artifacts)

    assert first.committed is True
    assert collision is not None and collision.is_dir()
    assert list(collision.iterdir()) == []
    store = snapshot_module._revision_store_path(out_dir)
    assert snapshot_module._read_cleanup_receipt(
        store,
        collision,
        output_kind="web_snapshot",
        repo_id=config.repo_id,
    ) is None
    pending_activations = list(out_dir.parent.glob(f".{out_dir.name}.activate-*"))
    assert len(pending_activations) == 1
    assert (
        pending_activations[0] / snapshot_module.SNAPSHOT_CLEANUP_INTENT_FILENAME
    ).is_file()

    monkeypatch.setattr(
        snapshot_module,
        "_atomic_install_directory_noreplace",
        original_install,
    )
    follow_up = snapshot_module.promote_snapshot_revisioned(
        tmp_path,
        out_dir,
        artifacts,
    )
    assert follow_up.committed is True
    assert collision.is_dir() and list(collision.iterdir()) == []
    assert snapshot_module._read_cleanup_receipt(
        store,
        collision,
        output_kind="web_snapshot",
        repo_id=config.repo_id,
    ) is None


def test_cleanup_revalidates_renamed_inode_and_intent_before_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    artifacts = _prepared_snapshot_variant(tmp_path, config, version=1)
    original_install = snapshot_module._atomic_install_directory_noreplace
    held_activation = tmp_path / ".held-owned-activation"
    cleanup_dir: Path | None = None
    external_activation: Path | None = None
    sentinel: Path | None = None
    swapped = False

    def swap_after_intent_fsync(source: Path, target: Path) -> None:
        nonlocal cleanup_dir, external_activation, sentinel, swapped
        source_path = Path(source)
        target_path = Path(target)
        if (
            not swapped
            and ".activate-" in source_path.name
            and ".cleanup-" in target_path.name
        ):
            assert (
                source_path / snapshot_module.SNAPSHOT_CLEANUP_INTENT_FILENAME
            ).is_file()
            os.replace(source_path, held_activation)
            source_path.mkdir()
            external_activation = source_path
            sentinel = source_path / "external-sentinel.txt"
            sentinel.write_text("external replacement\n", encoding="utf-8")
            cleanup_dir = target_path
            swapped = True
        original_install(source, target)

    monkeypatch.setattr(
        snapshot_module,
        "_atomic_install_directory_noreplace",
        swap_after_intent_fsync,
    )
    result = snapshot_module.promote_snapshot_revisioned(
        tmp_path,
        out_dir,
        artifacts,
    )

    assert result.committed is True
    assert swapped is True
    assert cleanup_dir is not None and not cleanup_dir.exists()
    assert external_activation is not None and external_activation.is_dir()
    assert sentinel is not None
    assert sentinel.parent == external_activation
    assert sentinel.read_text(encoding="utf-8") == "external replacement\n"
    assert held_activation.is_dir()
    assert (
        held_activation / snapshot_module.SNAPSHOT_CLEANUP_INTENT_FILENAME
    ).is_file()
    store = snapshot_module._revision_store_path(out_dir)
    assert snapshot_module._read_cleanup_receipt(
        store,
        cleanup_dir,
        output_kind="web_snapshot",
        repo_id=config.repo_id,
    ) is None
    assert any(
        warning.startswith("activation_container_cleanup_failed:")
        for warning in result.cleanup_warnings
    )
    assert tuple(result.recovery_paths) == (external_activation,)


def test_cleanup_reports_preserved_quarantine_when_race_rollback_is_occupied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    artifacts = _prepared_snapshot_variant(tmp_path, config, version=1)
    original_install = snapshot_module._atomic_install_directory_noreplace
    held_activation = tmp_path / ".held-owned-activation"
    activation_path: Path | None = None
    cleanup_dir: Path | None = None
    swapped = False

    def occupy_activation_after_untrusted_rename(source: Path, target: Path) -> None:
        nonlocal activation_path, cleanup_dir, swapped
        source_path = Path(source)
        target_path = Path(target)
        if (
            not swapped
            and ".activate-" in source_path.name
            and ".cleanup-" in target_path.name
        ):
            os.replace(source_path, held_activation)
            source_path.mkdir()
            (source_path / "external-sentinel.txt").write_text(
                "displaced external replacement\n",
                encoding="utf-8",
            )
            activation_path = source_path
            cleanup_dir = target_path
            swapped = True
            original_install(source, target)
            source_path.mkdir()
            (source_path / "second-external-writer.txt").write_text(
                "occupies original pathname\n",
                encoding="utf-8",
            )
            return
        original_install(source, target)

    monkeypatch.setattr(
        snapshot_module,
        "_atomic_install_directory_noreplace",
        occupy_activation_after_untrusted_rename,
    )
    result = snapshot_module.promote_snapshot_revisioned(
        tmp_path,
        out_dir,
        artifacts,
    )

    assert result.committed is True
    assert swapped is True
    assert activation_path is not None and activation_path.is_dir()
    assert (activation_path / "second-external-writer.txt").read_text(
        encoding="utf-8"
    ) == "occupies original pathname\n"
    assert cleanup_dir is not None and cleanup_dir.is_dir()
    assert (cleanup_dir / "external-sentinel.txt").read_text(
        encoding="utf-8"
    ) == "displaced external replacement\n"
    store = snapshot_module._revision_store_path(out_dir)
    assert snapshot_module._read_cleanup_receipt(
        store,
        cleanup_dir,
        output_kind="web_snapshot",
        repo_id=config.repo_id,
    ) is None
    assert tuple(result.recovery_paths) == (cleanup_dir,)


def test_cleanup_intent_recovers_crash_after_noreplace_rename_before_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    artifacts = _prepared_snapshot_variant(tmp_path, config, version=1)
    original_ensure_receipt = snapshot_module._ensure_cleanup_receipt
    failed = False

    def fail_first_receipt(*args: object, **kwargs: object) -> Path:
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("synthetic crash before cleanup receipt")
        return original_ensure_receipt(*args, **kwargs)

    monkeypatch.setattr(
        snapshot_module,
        "_ensure_cleanup_receipt",
        fail_first_receipt,
    )
    first = snapshot_module.promote_snapshot_revisioned(tmp_path, out_dir, artifacts)

    assert first.committed is True
    assert failed is True
    tombstones = list(out_dir.parent.glob(f".{out_dir.name}.cleanup-*"))
    assert len(tombstones) == 1
    tombstone = tombstones[0]
    assert (tombstone / OUTPUT_OWNER_FILENAME).is_file()
    assert (
        tombstone / snapshot_module.SNAPSHOT_CLEANUP_INTENT_FILENAME
    ).is_file()
    store = snapshot_module._revision_store_path(out_dir)
    assert snapshot_module._read_cleanup_receipt(
        store,
        tombstone,
        output_kind="web_snapshot",
        repo_id=config.repo_id,
    ) is None
    health = snapshot_module.snapshot_publication_status(
        tmp_path,
        out_dir,
        repo_id=config.repo_id,
    )
    assert health["recovery"]["cleanup_owned_pending"] == 1
    assert health["recovery"]["cleanup_ambiguous_preserved"] == 0

    monkeypatch.setattr(
        snapshot_module,
        "_ensure_cleanup_receipt",
        original_ensure_receipt,
    )
    follow_up = snapshot_module.promote_snapshot_revisioned(
        tmp_path,
        out_dir,
        artifacts,
    )
    assert follow_up.committed is True
    assert not tombstone.exists()


def test_cleanup_receipt_is_durable_before_activation_marker_unlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    artifacts = _prepared_snapshot_variant(tmp_path, config, version=1)
    store = snapshot_module._revision_store_path(out_dir)
    original_unlink = snapshot_module._unlink_regular_entry_at
    observed = False

    def observe_marker_unlink(directory_fd: int, name: str) -> None:
        nonlocal observed
        if name == OUTPUT_OWNER_FILENAME:
            observed = True
            cleanup_dirs = list(out_dir.parent.glob(f".{out_dir.name}.cleanup-*"))
            assert len(cleanup_dirs) == 1
            receipt = snapshot_module._read_cleanup_receipt(
                store,
                cleanup_dirs[0],
                output_kind="web_snapshot",
                repo_id=config.repo_id,
            )
            assert receipt is not None
        original_unlink(directory_fd, name)

    monkeypatch.setattr(
        snapshot_module,
        "_unlink_regular_entry_at",
        observe_marker_unlink,
    )
    result = snapshot_module.promote_snapshot_revisioned(
        tmp_path,
        out_dir,
        artifacts,
    )

    assert result.committed is True
    assert observed is True
    assert not list(out_dir.parent.glob(f".{out_dir.name}.cleanup-*"))


def test_cleanup_inode_bound_receipt_preserves_post_receipt_empty_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    artifacts = _prepared_snapshot_variant(tmp_path, config, version=1)
    store = snapshot_module._revision_store_path(out_dir)
    held_owned = tmp_path / ".held-owned-cleanup-after-receipt"
    original_unlink = snapshot_module._unlink_regular_entry_at
    external_cleanup: Path | None = None
    receipt_was_valid = False

    def swap_before_marker_unlink(directory_fd: int, name: str) -> None:
        nonlocal external_cleanup, receipt_was_valid
        if external_cleanup is None and name == OUTPUT_OWNER_FILENAME:
            cleanup_dirs = list(out_dir.parent.glob(f".{out_dir.name}.cleanup-*"))
            assert len(cleanup_dirs) == 1
            cleanup_dir = cleanup_dirs[0]
            receipt_was_valid = snapshot_module._read_cleanup_receipt(
                store,
                cleanup_dir,
                output_kind="web_snapshot",
                repo_id=config.repo_id,
            ) is not None
            os.replace(cleanup_dir, held_owned)
            cleanup_dir.mkdir()
            external_cleanup = cleanup_dir
        original_unlink(directory_fd, name)

    monkeypatch.setattr(
        snapshot_module,
        "_unlink_regular_entry_at",
        swap_before_marker_unlink,
    )
    first = snapshot_module.promote_snapshot_revisioned(
        tmp_path,
        out_dir,
        artifacts,
    )

    assert first.committed is True
    assert receipt_was_valid is True
    assert external_cleanup is not None and external_cleanup.is_dir()
    assert list(external_cleanup.iterdir()) == []
    assert held_owned.is_dir() and list(held_owned.iterdir()) == []
    assert snapshot_module._read_cleanup_receipt(
        store,
        external_cleanup,
        output_kind="web_snapshot",
        repo_id=config.repo_id,
    ) is None
    assert snapshot_module._read_cleanup_receipt(
        store,
        external_cleanup,
        output_kind="web_snapshot",
        repo_id=config.repo_id,
        require_directory_match=False,
    ) is not None
    assert tuple(first.recovery_paths) == (external_cleanup,)

    monkeypatch.setattr(
        snapshot_module,
        "_unlink_regular_entry_at",
        original_unlink,
    )
    follow_up = snapshot_module.promote_snapshot_revisioned(
        tmp_path,
        out_dir,
        artifacts,
    )
    assert follow_up.committed is True
    assert external_cleanup.is_dir() and list(external_cleanup.iterdir()) == []
    assert any(
        warning.startswith("cleanup_receipt_inode_mismatch_preserved:")
        for warning in follow_up.cleanup_warnings
    )


def test_orphan_cleanup_receipt_is_reported_then_retired_on_next_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    artifacts = _prepared_snapshot_variant(tmp_path, config, version=1)
    original_remove_receipt = snapshot_module._remove_cleanup_receipt
    failed = False

    def fail_receipt_removal_once(*args: object, **kwargs: object) -> None:
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("synthetic orphan cleanup receipt")
        original_remove_receipt(*args, **kwargs)

    monkeypatch.setattr(
        snapshot_module,
        "_remove_cleanup_receipt",
        fail_receipt_removal_once,
    )
    result = snapshot_module.promote_snapshot_revisioned(
        tmp_path,
        out_dir,
        artifacts,
    )

    assert result.committed is True
    assert failed is True
    receipts = snapshot_module._cleanup_receipts_path(
        snapshot_module._revision_store_path(out_dir)
    )
    orphan_receipts = [
        path
        for path in receipts.glob("*.json")
        if path.name != OUTPUT_OWNER_FILENAME
    ]
    assert len(orphan_receipts) == 1
    assert tuple(result.recovery_paths) == (orphan_receipts[0],)
    health = snapshot_module.snapshot_publication_status(
        tmp_path,
        out_dir,
        repo_id=config.repo_id,
    )
    assert health["recovery"]["cleanup_orphan_receipts_pending"] == 1
    assert health["recovery"]["owned_pending"] == 1

    monkeypatch.setattr(
        snapshot_module,
        "_remove_cleanup_receipt",
        original_remove_receipt,
    )
    follow_up = snapshot_module.promote_snapshot_revisioned(
        tmp_path,
        out_dir,
        artifacts,
    )
    assert follow_up.committed is True
    assert [
        path
        for path in receipts.glob("*.json")
        if path.name != OUTPUT_OWNER_FILENAME
    ] == []


def test_health_pins_revision_while_concurrent_publish_and_prune_advance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    variants = [
        _prepared_snapshot_variant(tmp_path, config, version=index)
        for index in range(3)
    ]
    snapshot_module.promote_snapshot_revisioned(
        tmp_path,
        out_dir,
        variants[0],
        retention=2,
    )
    first_revision = str(variants[0]["manifest.json"]["bundle_hash"])
    original_validate = snapshot_module._validate_owned_snapshot_revision
    health_pinned = threading.Event()
    release_health = threading.Event()
    health_result: list[dict[str, object]] = []
    health_failure: list[BaseException] = []

    def pause_health_validation(*args: object, **kwargs: object):
        if (
            threading.current_thread().name == "snapshot-health-reader"
            and kwargs.get("requested_revision") == first_revision
        ):
            health_pinned.set()
            assert release_health.wait(timeout=20)
        return original_validate(*args, **kwargs)

    monkeypatch.setattr(
        snapshot_module,
        "_validate_owned_snapshot_revision",
        pause_health_validation,
    )

    def read_health() -> None:
        try:
            health_result.append(
                snapshot_module.snapshot_publication_status(
                    tmp_path,
                    out_dir,
                    repo_id=config.repo_id,
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted below.
            health_failure.append(exc)

    reader = threading.Thread(target=read_health, name="snapshot-health-reader")
    reader.start()
    assert health_pinned.wait(timeout=20)
    for variant in variants[1:]:
        snapshot_module.promote_snapshot_revisioned(
            tmp_path,
            out_dir,
            variant,
            retention=2,
        )
    store = snapshot_module._revision_store_path(out_dir)
    assert (store / first_revision).is_dir()
    release_health.set()
    reader.join(timeout=20)

    assert not reader.is_alive()
    assert not health_failure
    assert health_result[0]["pointer_state"] == (
        "full_inventory_owner_repo_and_hash_valid"
    )
    assert health_result[0]["active_revision"] == first_revision
    validation = health_result[0]["validation"]
    assert validation["mode"] == "lease_pinned_full_inventory_owner_repo_and_sha256"
    assert validation["cache_ttl_seconds"] == (
        snapshot_module.SNAPSHOT_HEALTH_VALIDATION_CACHE_TTL_S
    )
    assert validation["duration_ms"] >= 0

    snapshot_module.prune_snapshot_revisions(
        tmp_path,
        out_dir,
        repo_id=config.repo_id,
        retention=2,
    )
    assert not (store / first_revision).exists()


def test_health_validation_cache_reports_cost_and_rechecks_metadata(
    tmp_path: Path,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    artifacts = _prepared_snapshot_variant(tmp_path, config, version=1)
    snapshot_module.promote_snapshot_revisioned(tmp_path, out_dir, artifacts)

    cold = snapshot_module.snapshot_publication_status(
        tmp_path,
        out_dir,
        repo_id=config.repo_id,
    )
    warm = snapshot_module.snapshot_publication_status(
        tmp_path,
        out_dir,
        repo_id=config.repo_id,
    )

    assert cold["pointer_state"] == "full_inventory_owner_repo_and_hash_valid"
    assert cold["validation"]["cache_hit"] is False
    assert cold["validation"]["duration_ms"] >= 0
    assert cold["validation"]["budget_ms"] == (
        snapshot_module.SNAPSHOT_HEALTH_VALIDATION_BUDGET_MS
    )
    assert cold["deletion_safety"] == {
        "prune_recursive_delete": "descriptor_pinned_no_follow",
        "cleanup_receipt_binding": "directory_dev_ino_type",
        "posix_final_compare_to_rmdir_window": (
            "unavoidable_without_inode_conditional_rmdir"
        ),
    }
    assert warm["pointer_state"] == "full_inventory_owner_repo_and_hash_valid"
    assert warm["validation"]["cache_hit"] is True
    assert warm["validation"]["metadata_fingerprint_checked_on_cache_hit"] is True
    assert warm["validation"]["duration_ms"] >= 0

    # A cache hit is never revision-only: a fresh metadata inventory detects
    # an undeclared file during the TTL and forces full validation to fail.
    extra = out_dir.resolve(strict=True) / "user-extra.txt"
    extra.write_text("cache must not hide this file\n", encoding="utf-8")
    changed = snapshot_module.snapshot_publication_status(
        tmp_path,
        out_dir,
        repo_id=config.repo_id,
    )
    assert changed["pointer_state"] == "invalid"
    assert extra.read_text(encoding="utf-8") == "cache must not hide this file\n"


def test_health_cache_rejects_same_size_corruption_with_restored_mtime(
    tmp_path: Path,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    artifacts = _prepared_snapshot_variant(tmp_path, config, version=1)
    snapshot_module.promote_snapshot_revisioned(tmp_path, out_dir, artifacts)
    snapshot_module.SNAPSHOT_HEALTH_VALIDATION_CACHE.clear()
    cold = snapshot_module.snapshot_publication_status(
        tmp_path,
        out_dir,
        repo_id=config.repo_id,
    )
    assert cold["pointer_state"] == "full_inventory_owner_repo_and_hash_valid"
    assert cold["validation"]["cache_hit"] is False

    operations = out_dir.resolve(strict=True) / "operations.json"
    before = operations.stat(follow_symlinks=False)
    payload = operations.read_bytes()
    offset = payload.find(b"Operations")
    assert offset >= 0
    with operations.open("r+b") as handle:
        handle.seek(offset)
        handle.write(b"X")
        handle.flush()
        os.fsync(handle.fileno())
    os.utime(
        operations,
        ns=(before.st_atime_ns, before.st_mtime_ns),
        follow_symlinks=False,
    )
    after = operations.stat(follow_symlinks=False)
    assert (after.st_ino, after.st_size, after.st_mtime_ns) == (
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    assert after.st_ctime_ns != before.st_ctime_ns

    corrupted = snapshot_module.snapshot_publication_status(
        tmp_path,
        out_dir,
        repo_id=config.repo_id,
    )
    assert corrupted["pointer_state"] == "invalid"
    assert corrupted["validation"]["cache_hit"] is False


def test_atomic_legacy_migration_fails_closed_on_unsupported_platform(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = tmp_path / "current"
    candidate = tmp_path / "candidate"
    _write(current / "old.txt", "old\n")
    _write(candidate / "new.txt", "new\n")
    monkeypatch.setattr(snapshot_module.sys, "platform", "win32")

    with pytest.raises(OSError, match="supported only on Darwin and Linux"):
        snapshot_module._atomic_exchange_paths(current, candidate)

    assert (current / "old.txt").read_text(encoding="utf-8") == "old\n"
    assert (candidate / "new.txt").read_text(encoding="utf-8") == "new\n"


def test_live_revision_publication_fails_closed_without_posix_leases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _sample_repo(tmp_path)
    artifacts = _prepared_snapshot_variant(tmp_path, config, version=1)
    out_dir = tmp_path / "snapshot-output"
    monkeypatch.setattr(snapshot_module.sys, "platform", "win32")
    monkeypatch.setattr(snapshot_module, "fcntl", None)

    with pytest.raises(OSError, match="supported only on Darwin and Linux"):
        snapshot_module.promote_snapshot_revisioned(
            tmp_path,
            out_dir,
            artifacts,
        )

    assert not out_dir.exists() and not out_dir.is_symlink()
    assert not snapshot_module._revision_store_path(out_dir).exists()

    static_out = tmp_path / "static-flat-output"
    written = write_snapshot(
        tmp_path,
        static_out,
        config,
        mode="static",
    )
    assert set(written) == set(SNAPSHOT_FILES)
    assert static_out.is_dir() and not static_out.is_symlink()
    assert not snapshot_module._revision_store_path(static_out).exists()

    operator_out = tmp_path / "operator-output"
    with pytest.raises(OSError, match="supported only on Darwin and Linux"):
        write_snapshot(
            tmp_path,
            operator_out,
            config,
            mode="local_operator",
        )
    assert not operator_out.exists()


def test_concurrent_snapshot_readers_never_accept_absent_or_mixed_revision(
    tmp_path: Path,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    variants = [
        _prepared_snapshot_variant(tmp_path, config, version=index)
        for index in range(6)
    ]
    expected_ids = {
        str(variant["manifest.json"]["snapshot_id"]) for variant in variants
    }
    snapshot_module.promote_snapshot_revisioned(tmp_path, out_dir, variants[0])

    stop = threading.Event()
    observed: set[str] = set()
    failures: list[BaseException] = []
    observed_lock = threading.Lock()

    def read_until_stopped() -> None:
        while not stop.is_set():
            try:
                payloads = snapshot_module.load_active_snapshot_artifacts(out_dir)
                assert snapshot_contract_errors(payloads) == []
                snapshot_id = str(payloads["manifest.json"]["snapshot_id"])
                assert snapshot_id in expected_ids
                with observed_lock:
                    observed.add(snapshot_id)
            except BaseException as exc:  # pragma: no branch - captured for assertion.
                failures.append(exc)
                stop.set()

    readers = [threading.Thread(target=read_until_stopped) for _ in range(8)]
    for reader in readers:
        reader.start()
    try:
        for index in range(60):
            snapshot_module.promote_snapshot_revisioned(
                tmp_path,
                out_dir,
                variants[index % len(variants)],
            )
            time.sleep(0.001)
    finally:
        stop.set()
        for reader in readers:
            reader.join(timeout=10)

    assert not failures
    assert len(observed) >= 2
    assert out_dir.is_symlink() and (out_dir / "manifest.json").is_file()
    assert not list(out_dir.parent.glob(f".{out_dir.name}.activate-*"))
    store = snapshot_module._revision_store_path(out_dir)
    revisions = [
        path
        for path in store.iterdir()
        if path.is_dir()
        and not path.is_symlink()
        and snapshot_module.SNAPSHOT_REVISION_HASH_RE.fullmatch(path.name)
    ]
    assert len(revisions) <= snapshot_module.SNAPSHOT_REVISION_RETENTION


def test_reader_pinned_during_flat_to_pointer_migration_retries_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    old_artifacts = _prepared_snapshot_variant(tmp_path, config, version=1)
    new_artifacts = _prepared_snapshot_variant(tmp_path, config, version=2)
    snapshot_module.promote_snapshot_artifacts(
        tmp_path,
        out_dir,
        old_artifacts,
    )

    reader_entered = threading.Event()
    continue_reader = threading.Event()
    original_load = snapshot_module._load_snapshot_directory
    blocked_once = False

    def block_reader_once(
        revision_dir: Path,
    ) -> dict[str, dict[str, object]]:
        nonlocal blocked_once
        if (
            not blocked_once
            and threading.current_thread().name == "migration-reader"
            and revision_dir == out_dir
        ):
            blocked_once = True
            reader_entered.set()
            assert continue_reader.wait(timeout=10)
        return original_load(revision_dir)

    monkeypatch.setattr(snapshot_module, "_load_snapshot_directory", block_reader_once)
    result: list[dict[str, dict[str, object]]] = []
    failures: list[BaseException] = []

    def read_snapshot() -> None:
        try:
            result.append(snapshot_module.load_active_snapshot_artifacts(out_dir))
        except BaseException as exc:  # pragma: no cover - asserted below.
            failures.append(exc)

    reader = threading.Thread(target=read_snapshot, name="migration-reader")
    reader.start()
    assert reader_entered.wait(timeout=10)
    snapshot_module.promote_snapshot_revisioned(
        tmp_path,
        out_dir,
        new_artifacts,
    )
    continue_reader.set()
    reader.join(timeout=10)

    assert not reader.is_alive()
    assert not failures
    assert result[0]["manifest.json"]["snapshot_id"] == (
        new_artifacts["manifest.json"]["snapshot_id"]
    )
    assert snapshot_contract_errors(result[0]) == []


def test_flat_reader_rejects_valid_but_unowned_directory(tmp_path: Path) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "flat-output"
    artifacts = _prepared_snapshot_variant(tmp_path, config, version=1)
    snapshot_module.promote_snapshot_artifacts(tmp_path, out_dir, artifacts)
    (out_dir / OUTPUT_OWNER_FILENAME).unlink()

    with pytest.raises(ValueError, match="flat snapshot directory is unowned"):
        snapshot_module.load_active_snapshot_artifacts(
            out_dir,
            expected_repo_id=config.repo_id,
        )


def test_reader_waits_with_bounded_backoff_before_first_pointer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = tmp_path / "missing-snapshot"
    delays: list[float] = []
    monkeypatch.setattr(snapshot_module.time, "sleep", delays.append)
    with pytest.raises(RuntimeError, match="changed during 3 read attempts"):
        snapshot_module.load_active_snapshot_artifacts(missing, max_attempts=3)
    assert delays == [
        snapshot_module.SNAPSHOT_READ_RETRY_BASE_S,
        snapshot_module.SNAPSHOT_READ_RETRY_BASE_S * 2,
    ]

    monkeypatch.undo()
    config = _sample_repo(tmp_path / "repo")
    root = tmp_path / "repo"
    out_dir = root / "snapshot-output"
    artifacts = _prepared_snapshot_variant(root, config, version=1)
    loaded: list[dict[str, dict[str, object]]] = []
    failures: list[BaseException] = []

    def read_before_publish() -> None:
        try:
            loaded.append(
                snapshot_module.load_active_snapshot_artifacts(
                    out_dir,
                    max_attempts=8,
                    expected_repo_id=config.repo_id,
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted below.
            failures.append(exc)

    reader_waiting = threading.Event()
    publish_finished = threading.Event()

    def wait_for_publish(_delay: float) -> None:
        reader_waiting.set()
        assert publish_finished.wait(timeout=10)

    monkeypatch.setattr(snapshot_module.time, "sleep", wait_for_publish)
    reader = threading.Thread(target=read_before_publish)
    reader.start()
    assert reader_waiting.wait(timeout=10)
    snapshot_module.promote_snapshot_revisioned(root, out_dir, artifacts)
    publish_finished.set()
    reader.join(timeout=10)
    assert not reader.is_alive()
    assert not failures
    assert loaded[0]["manifest.json"]["snapshot_id"] == (
        artifacts["manifest.json"]["snapshot_id"]
    )


@pytest.mark.parametrize("preexisting_store", [False, True])
def test_concurrent_publishers_serialize_activation_and_never_prune_active(
    tmp_path: Path,
    preexisting_store: bool,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    variants = [
        _prepared_snapshot_variant(tmp_path, config, version=index)
        for index in range(7)
    ]
    if preexisting_store:
        snapshot_module.promote_snapshot_revisioned(
            tmp_path,
            out_dir,
            variants[0],
            retention=2,
        )
        publishing_variants = variants[1:]
    else:
        publishing_variants = variants
    barrier = threading.Barrier(len(publishing_variants))
    failures: list[BaseException] = []
    reader_failures: list[BaseException] = []
    observed: list[str] = []
    publishers_done = threading.Event()

    def publish(variant: dict[str, dict[str, object]]) -> None:
        try:
            barrier.wait(timeout=10)
            snapshot_module.promote_snapshot_revisioned(
                tmp_path,
                out_dir,
                variant,
                retention=2,
            )
        except BaseException as exc:  # pragma: no branch - asserted below.
            failures.append(exc)

    def read_complete_snapshots() -> None:
        reads = 0
        while not out_dir.is_symlink() and not publishers_done.is_set():
            time.sleep(0.0005)
        while not publishers_done.is_set() or reads == 0:
            try:
                payloads = snapshot_module.load_active_snapshot_artifacts(
                    out_dir,
                    expected_repo_id=config.repo_id,
                )
                assert snapshot_contract_errors(payloads) == []
                observed.append(str(payloads["manifest.json"]["snapshot_id"]))
                reads += 1
            except BaseException as exc:  # pragma: no branch - asserted below.
                reader_failures.append(exc)
                return

    readers = [threading.Thread(target=read_complete_snapshots) for _ in range(4)]
    publishers = [
        threading.Thread(target=publish, args=(variant,))
        for variant in publishing_variants
    ]
    for reader in readers:
        reader.start()
    for publisher in publishers:
        publisher.start()
    for publisher in publishers:
        publisher.join(timeout=20)
    publishers_done.set()
    for reader in readers:
        reader.join(timeout=20)

    assert not any(publisher.is_alive() for publisher in publishers)
    assert not any(reader.is_alive() for reader in readers)
    assert not failures
    assert not reader_failures
    assert len(observed) >= len(readers)
    payloads = snapshot_module.load_active_snapshot_artifacts(
        out_dir,
        expected_repo_id=config.repo_id,
    )
    assert snapshot_contract_errors(payloads) == []
    assert payloads["manifest.json"]["snapshot_id"] in {
        variant["manifest.json"]["snapshot_id"] for variant in variants
    }
    store = snapshot_module._revision_store_path(out_dir)
    active_revision = Path(os.readlink(out_dir)).name
    assert (store / active_revision).is_dir()
    revisions = [
        path
        for path in store.iterdir()
        if path.is_dir()
        and not path.is_symlink()
        and snapshot_module.SNAPSHOT_REVISION_HASH_RE.fullmatch(path.name)
    ]
    assert len(revisions) <= 2


def test_multiprocess_first_publish_serializes_and_reader_waits_for_commit(
    tmp_path: Path,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    variants = [
        _prepared_snapshot_variant(tmp_path, config, version=index)
        for index in range(4)
    ]
    variant_paths: list[Path] = []
    for index, variant in enumerate(variants):
        path = tmp_path / f"variant-{index}.json"
        path.write_text(json.dumps(variant), encoding="utf-8")
        variant_paths.append(path)
    start = tmp_path / "start-publishers"
    publisher_code = "\n".join(
        [
            "import json, sys, time",
            "from pathlib import Path",
            "from wiki_core.web.snapshot import promote_snapshot_revisioned",
            "root, out, payload_path, start = map(Path, sys.argv[1:5])",
            "while not start.exists(): time.sleep(0.001)",
            "payloads = json.loads(payload_path.read_text(encoding='utf-8'))",
            "result = promote_snapshot_revisioned(root, out, payloads, retention=2)",
            "print(result.snapshot_id, flush=True)",
        ]
    )
    reader_code = "\n".join(
        [
            "import sys, time",
            "from pathlib import Path",
            "from wiki_core.web.snapshot import load_active_snapshot_artifacts",
            "out = Path(sys.argv[1])",
            "deadline = time.monotonic() + 20",
            "while not out.is_symlink() and time.monotonic() < deadline: time.sleep(0.001)",
            "payloads = load_active_snapshot_artifacts(out, expected_repo_id='sample')",
            "print(payloads['manifest.json']['snapshot_id'], flush=True)",
        ]
    )
    reader = subprocess.Popen(
        [sys.executable, "-c", reader_code, str(out_dir)],
        cwd=KIT_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    publishers = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                publisher_code,
                str(tmp_path),
                str(out_dir),
                str(variant_path),
                str(start),
            ],
            cwd=KIT_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for variant_path in variant_paths
    ]
    start.write_text("go\n", encoding="utf-8")
    publisher_outputs = [process.communicate(timeout=30) for process in publishers]
    reader_stdout, reader_stderr = reader.communicate(timeout=30)

    assert all(process.returncode == 0 for process in publishers), publisher_outputs
    assert reader.returncode == 0, reader_stderr
    expected_ids = {
        str(variant["manifest.json"]["snapshot_id"]) for variant in variants
    }
    assert {stdout.strip() for stdout, _stderr in publisher_outputs} == expected_ids
    assert reader_stdout.strip() in expected_ids
    payloads = snapshot_module.load_active_snapshot_artifacts(
        out_dir,
        expected_repo_id=config.repo_id,
    )
    assert snapshot_contract_errors(payloads) == []
    active_revision = Path(os.readlink(out_dir)).name
    store = snapshot_module._revision_store_path(out_dir)
    assert (store / active_revision).is_dir()
    assert not list(out_dir.parent.glob(f".{out_dir.name}.activate-*"))
    assert not list(store.glob(".stage-*"))


def test_cross_process_reader_lease_defers_then_allows_bounded_cleanup(
    tmp_path: Path,
) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "snapshot-output"
    variants = [
        _prepared_snapshot_variant(tmp_path, config, version=index)
        for index in range(5)
    ]
    snapshot_module.promote_snapshot_revisioned(
        tmp_path,
        out_dir,
        variants[0],
        retention=2,
    )
    store = snapshot_module._revision_store_path(out_dir)
    leased_revision = str(variants[0]["manifest.json"]["bundle_hash"])
    child_code = "\n".join(
        [
            "import sys",
            "from pathlib import Path",
            "from wiki_core.web.snapshot import _revision_lease",
            "store, revision = Path(sys.argv[1]), sys.argv[2]",
            "with _revision_lease(store, revision, exclusive=False) as acquired:",
            "    print('ready' if acquired else 'unavailable', flush=True)",
            "    sys.stdin.readline()",
        ]
    )
    child = subprocess.Popen(
        [sys.executable, "-c", child_code, str(store), leased_revision],
        cwd=KIT_ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "ready"
        for variant in variants[1:]:
            snapshot_module.promote_snapshot_revisioned(
                tmp_path,
                out_dir,
                variant,
                retention=2,
            )
        assert (store / leased_revision).is_dir()
    finally:
        _child_stdout, child_stderr = child.communicate("release\n", timeout=10)
    assert child.returncode == 0
    assert child_stderr == ""

    snapshot_module.prune_snapshot_revisions(
        tmp_path,
        out_dir,
        repo_id=config.repo_id,
        retention=2,
    )
    assert not (store / leased_revision).exists()
    revisions = [
        path
        for path in store.iterdir()
        if path.is_dir()
        and not path.is_symlink()
        and snapshot_module.SNAPSHOT_REVISION_HASH_RE.fullmatch(path.name)
    ]
    assert len(revisions) <= 2


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
    assert (out_dir / OUTPUT_OWNER_FILENAME).is_file()
    assert (out_dir / "sample-review" / OUTPUT_OWNER_FILENAME).is_file()
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


def test_deploy_bundle_refuses_unowned_or_escaped_output(tmp_path: Path) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "deploy"
    user_file = out_dir / "notes.txt"
    _write(user_file, "keep\n")

    with pytest.raises(ValueError, match="unowned non-empty"):
        write_deploy_bundle(
            tmp_path,
            out_dir,
            config,
            data_boundary="private_ok",
            clean=True,
        )
    assert user_file.read_text(encoding="utf-8") == "keep\n"

    escaped = tmp_path / "escaped"
    with pytest.raises(ValueError, match="inside repository root"):
        write_deploy_bundle(
            tmp_path,
            tmp_path / "safe-deploy",
            config,
            snapshot_base="../escaped",
            data_boundary="private_ok",
            clean=True,
        )
    assert not escaped.exists()
    assert not (tmp_path / "safe-deploy").exists()


def test_deploy_bundle_refuses_target_symlink_and_preserves_external_directory(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    config = _sample_repo(root)
    external = tmp_path / "external-deploy-target"
    keeper = external / "keep.txt"
    _write(keeper, "external deploy target\n")
    out_dir = root / "deploy-link"
    out_dir.symlink_to(external, target_is_directory=True)

    with pytest.raises(ValueError, match="cannot be a symlink"):
        write_deploy_bundle(
            root,
            out_dir,
            config,
            data_boundary="private_ok",
            clean=True,
            force_unowned_output=True,
        )

    assert out_dir.is_symlink()
    assert keeper.read_text(encoding="utf-8") == "external deploy target\n"
    assert sorted(
        path.relative_to(external).as_posix()
        for path in external.rglob("*")
        if path.is_file()
    ) == ["keep.txt"]


def test_deploy_bundle_refuses_ancestor_symlink_escape_and_preserves_external_directory(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    config = _sample_repo(root)
    external = tmp_path / "external-deploy-ancestor"
    keeper = external / "deploy" / "keep.txt"
    _write(keeper, "external deploy ancestor\n")
    linked_parent = root / "linked-parent"
    linked_parent.symlink_to(external, target_is_directory=True)

    with pytest.raises(ValueError, match="inside repository root"):
        write_deploy_bundle(
            root,
            linked_parent / "deploy",
            config,
            data_boundary="private_ok",
            clean=True,
            force_unowned_output=True,
        )

    assert linked_parent.is_symlink()
    assert keeper.read_text(encoding="utf-8") == "external deploy ancestor\n"
    assert sorted(
        path.relative_to(external).as_posix()
        for path in external.rglob("*")
        if path.is_file()
    ) == ["deploy/keep.txt"]


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
    with pytest.raises(ValueError, match="deploy bundle refused") as exc_info:
        write_deploy_bundle(
            tmp_path,
            out_dir,
            config,
            snapshot_base="/sample-review",
            runtime_mode="static",
            data_boundary="synthetic_or_public",
            target="vercel_static",
        )
    message = str(exc_info.value)
    assert "private page(s)" in message
    assert "memories/" not in message
    assert "root" not in message
    # Refusal happens against in-memory artifacts: no deploy directory, owner
    # marker or private sidecar may ever reach the filesystem.
    assert not out_dir.exists()


def test_deploy_boundary_refusal_preserves_previous_public_bundle(tmp_path: Path) -> None:
    config = _sample_repo(tmp_path)
    for page_path in (tmp_path / "memories").rglob("*.md"):
        page_path.write_text(
            page_path.read_text(encoding="utf-8").replace(
                "visibility: private_self", "visibility: public_synthetic"
            ),
            encoding="utf-8",
        )
    out_dir = tmp_path / "deploy"
    write_deploy_bundle(
        tmp_path,
        out_dir,
        config,
        snapshot_base="/sample-review",
        data_boundary="synthetic_or_public",
        clean=True,
    )
    before = {
        path.relative_to(out_dir).as_posix(): path.read_bytes()
        for path in sorted(item for item in out_dir.rglob("*") if item.is_file())
    }

    root_page = tmp_path / "memories/index.md"
    root_page.write_text(
        root_page.read_text(encoding="utf-8").replace(
            "visibility: public_synthetic", "visibility: private_self"
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="deploy bundle refused"):
        write_deploy_bundle(
            tmp_path,
            out_dir,
            config,
            snapshot_base="/sample-review",
            data_boundary="synthetic_or_public",
            clean=True,
        )

    after = {
        path.relative_to(out_dir).as_posix(): path.read_bytes()
        for path in sorted(item for item in out_dir.rglob("*") if item.is_file())
    }
    assert after == before


def test_pages_payload_skips_unreadable_page(tmp_path: Path, monkeypatch) -> None:
    """One vanished/unreadable page file must not abort the whole snapshot
    build: the broken page is skipped, every readable page still lands."""
    from wiki_core.web.snapshot import _pages_payload

    config = _sample_repo(tmp_path)
    broken = tmp_path / "memories/example/broken.md"
    _write(broken, "---\npage_id: broken\n---\n\n# Broken\n")
    original_record = snapshot_module._page_record

    def fail_only_for_fixture(
        root,
        path,
        page_config,
        *,
        today=None,
        temporal_adapter_fields=None,
    ):
        if path == broken:
            raise PermissionError("synthetic unreadable page")
        return original_record(
            root,
            path,
            page_config,
            today=today,
            temporal_adapter_fields=temporal_adapter_fields,
        )

    monkeypatch.setattr(snapshot_module, "_page_record", fail_only_for_fixture)
    payload = _pages_payload(tmp_path, config)
    paths = {page["path"] for page in payload["pages"]}
    assert "memories/example/broken.md" not in paths
    assert "memories/index.md" in paths
