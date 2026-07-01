from __future__ import annotations

import json
import subprocess
from pathlib import Path

from wiki_core.config import WikiConfig
from wiki_core.web.deploy_bundle import write_deploy_bundle
from wiki_core.web.schemas import SNAPSHOT_FILES, WEB_SNAPSHOT_SCHEMA_VERSION
from wiki_core.web.snapshot import build_snapshot, write_snapshot


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _init_git(root: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "wiki@example.test"], cwd=root, check=True)
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
    subprocess.run(["git", "commit", "-m", "sample"], cwd=root, check=True, capture_output=True)
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
    assert snapshot["manifest.json"]["repo"]["repo_id"] == "sample"
    assert snapshot["manifest.json"]["repo"]["branch_prefix"] == "wiki/"
    assert snapshot["manifest.json"]["repo"]["default_context"] == "system"
    assert snapshot["manifest.json"]["repo"]["karma_enabled"] is True
    assert snapshot["git.json"]["current_branch"] == "main"
    assert snapshot["timeline.json"]["summary"]["event_count"] >= 1
    assert snapshot["diff.json"]["summary"]["file_count"] == 0
    assert snapshot["operations.json"]["title"] == "Operations"
    assert snapshot["freshness.json"]["summary"]["fresh"] >= 1
    assert any(node["id"] == "example-hub" for node in snapshot["graph.json"]["nodes"])
    assert any(action["id"] == "run-honesty-gates" for action in snapshot["actions.json"]["actions"])


def test_write_snapshot_creates_all_json_files(tmp_path: Path) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "data/derived/wiki/web-snapshot"

    written = write_snapshot(tmp_path, out_dir, config, clean=True)

    assert set(written) == set(SNAPSHOT_FILES)
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"] == list(SNAPSHOT_FILES)


def test_write_deploy_bundle_creates_runtime_config_snapshot_and_proof(tmp_path: Path) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "deploy"

    written = write_deploy_bundle(
        tmp_path,
        out_dir,
        config,
        snapshot_base="/sample-review",
        repo_label="Sample Review",
        runtime_mode="static",
        data_boundary="synthetic_open",
        target="vercel_static",
        clean=True,
    )

    assert "config" in written
    assert "proof" in written
    assert (out_dir / "sample-review" / "manifest.json").exists()
    runtime_config = json.loads((out_dir / "wiki-cockpit.config.json").read_text(encoding="utf-8"))
    assert runtime_config == {
        "api_base": "",
        "mode": "static",
        "repo_label": "Sample Review",
        "snapshot_base": "/sample-review",
    }
    proof = (out_dir / "DEPLOYMENT.md").read_text(encoding="utf-8")
    assert "vercel_static" in proof
    assert "synthetic_open" in proof
    assert "Pull Requests" in proof

    url_out = tmp_path / "deploy-url"
    write_deploy_bundle(
        tmp_path,
        url_out,
        config,
        snapshot_base="https://cdn.example.test/wiki/snapshot",
        target="vercel_static",
        clean=True,
    )
    url_config = json.loads((url_out / "wiki-cockpit.config.json").read_text(encoding="utf-8"))
    assert url_config["snapshot_base"] == "https://cdn.example.test/wiki/snapshot"
    assert (url_out / "snapshot" / "manifest.json").exists()


def test_snapshot_diff_tracks_branch_and_worktree_changes(tmp_path: Path) -> None:
    config = _sample_repo(tmp_path)
    subprocess.run(["git", "checkout", "-b", "wiki/review-fixture"], cwd=tmp_path, check=True, capture_output=True)
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
    subprocess.run(["git", "add", "memories/example/index.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "update example hub"], cwd=tmp_path, check=True, capture_output=True)
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
    assert any("branch proposal update" in line for line in by_path["memories/example/index.md"]["preview"])


def test_snapshot_timeline_includes_pages_operations_and_commits(tmp_path: Path) -> None:
    config = _sample_repo(tmp_path)

    snapshot = build_snapshot(tmp_path, config, generated_at="2026-07-01T12:00:00Z")
    timeline = snapshot["timeline.json"]

    kinds = {event["kind"] for event in timeline["events"]}
    assert {"snapshot", "operations_updated", "page_updated", "git_commit"}.issubset(kinds)
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
        paths={**WikiConfig().paths, "memory_root": "memorias", "operation_page": "memorias/operacao.md"},
        karma={"enabled": False},
    )

    snapshot = build_snapshot(tmp_path, config, generated_at="2026-07-01T00:00:00Z")

    assert snapshot["manifest.json"]["repo"]["memory_root"] == "memorias"
    assert snapshot["manifest.json"]["repo"]["default_context"] == "sistema"
    assert snapshot["manifest.json"]["repo"]["karma_enabled"] is False
    assert snapshot["pages.json"]["pages"][0]["path"] == "memorias/index.md"
    assert snapshot["pages.json"]["pages"][0]["context"] == "sistema"


def test_snapshot_handles_dense_localized_contexts_without_english_paths(tmp_path: Path) -> None:
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
        paths={**WikiConfig().paths, "memory_root": "memorias", "operation_page": "memorias/operacao.md"},
        karma={"enabled": False},
    )

    snapshot = build_snapshot(tmp_path, config, generated_at="2026-07-01T00:00:00Z")

    assert snapshot["manifest.json"]["repo"]["memory_root"] == "memorias"
    assert snapshot["manifest.json"]["repo"]["default_context"] == "sistema"
    assert snapshot["freshness.json"]["by_context"]["financeiro"]["fresh"] == 18
    assert len(snapshot["sources.json"]["sources"]) == 18
    assert all(str(page["path"]).startswith("memorias/") for page in snapshot["pages.json"]["pages"])


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
