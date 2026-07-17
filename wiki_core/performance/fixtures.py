from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterator

from .models import PerformanceContractError, canonical_bytes, sha256_value
from .profiles import FixtureProfile

FIXTURE_SCHEMA_VERSION = "wiki_performance_fixture.v1"
DEFAULT_SEED = 469


def _page_id(seed: int, ordinal: int) -> str:
    return f"synthetic-{seed:04d}-page-{ordinal:05d}"


def _event_id(seed: int, ordinal: int) -> str:
    return f"synthetic-{seed:04d}-event-{ordinal:06d}"


def logical_records(profile: FixtureProfile, seed: int) -> Iterator[dict[str, Any]]:
    for ordinal in range(profile.pages):
        yield {
            "kind": "page",
            "id": _page_id(seed, ordinal),
            "ordinal": ordinal,
            "title": f"Synthetic node {ordinal:05d}",
        }
    for ordinal in range(profile.relations):
        source = ordinal % profile.pages
        hop = 1 + (ordinal // profile.pages)
        target = (source + hop) % profile.pages
        yield {
            "kind": "relation",
            "id": f"synthetic-{seed:04d}-relation-{ordinal:07d}",
            "source": _page_id(seed, source),
            "target": _page_id(seed, target),
            "relation": "supports",
        }
    for ordinal in range(profile.events):
        yield {
            "kind": "event",
            "id": _event_id(seed, ordinal),
            "page": _page_id(seed, ordinal % profile.pages),
            "date": f"2026-{1 + (ordinal // 28) % 12:02d}-{1 + ordinal % 28:02d}",
            "iteration": ordinal % profile.soak_iterations,
        }


def fixture_identity(profile: FixtureProfile, seed: int = DEFAULT_SEED) -> dict[str, Any]:
    digest = hashlib.sha256()
    counts = {"page": 0, "relation": 0, "event": 0}
    for record in logical_records(profile, seed):
        digest.update(canonical_bytes(record))
        digest.update(b"\n")
        counts[str(record["kind"])] += 1
    payload = {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "profile": profile.name,
        "seed": seed,
        "counts": {
            "pages": counts["page"],
            "relations": counts["relation"],
            "events": counts["event"],
        },
        "soak_iterations": profile.soak_iterations,
        "records_sha256": digest.hexdigest(),
        "privacy": "public_synthetic_only",
    }
    payload["fixture_sha256"] = sha256_value(payload)
    return payload


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _copy_contract_inputs(source_root: Path, target_root: Path) -> None:
    for name in (
        "wiki.page-types.yaml",
        "wiki.relations.yaml",
        "wiki.blocks.yaml",
        "wiki.packs.lock.yaml",
    ):
        source = source_root / name
        if source.exists():
            shutil.copy2(source, target_root / name)
    for relative in ("packs", "docs/references/templates"):
        source = source_root / relative
        if source.exists():
            shutil.copytree(source, target_root / relative, dirs_exist_ok=True)


def materialize_fixture(
    source_root: Path,
    target_root: Path,
    profile: FixtureProfile,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    if target_root.exists() and any(target_root.iterdir()):
        raise PerformanceContractError(f"fixture target is not empty: {target_root}")
    target_root.mkdir(parents=True, exist_ok=True)
    _copy_contract_inputs(source_root, target_root)
    root_page = f"memories/example/{_page_id(seed, 0)}.md"
    _write(
        target_root / "wiki.config.yaml",
        "\n".join(
            [
                "repo_id: wiki-performance-synthetic",
                "owner_label: Synthetic Operator",
                "language: en",
                "default_context: example",
                "contexts: []",
                "private_sensitive_allowed: false",
                "root_entity:",
                f"  page: {root_page}",
                "  entity_type: product",
                "  input_stage_page: memories/system/input-stage.md",
                "llm:",
                "  required_context_pass: false",
                "  cache_enabled: true",
                "  default_model_profile: performance_synthetic",
                "  chunk_target_tokens: 1200",
                "  chunk_overlap_tokens: 150",
                "  prompt_versions:",
                "    context_deep_read: v3",
                "audit:",
                "  forbid_access_secrets: true",
                "  require_frontmatter: true",
                "",
            ]
        ),
    )
    _write(target_root / "AGENTS.md", "# Synthetic performance fixture\n\nPublic synthetic data only.\n")
    per_page = profile.relations // profile.pages
    remainder = profile.relations % profile.pages
    for ordinal in range(profile.pages):
        relation_count = per_page + (1 if ordinal < remainder else 0)
        related: list[str] = []
        for relation_index in range(relation_count):
            hop = 1 + relation_index
            target = (ordinal + hop) % profile.pages
            related.append(f"memories/example/{_page_id(seed, target)}.md")
        page_type = "root_entity" if ordinal == 0 else "context_note"
        parent = "" if ordinal == 0 else f"moc_parent: {root_page}\n"
        root_fields = (
            "root_entity_type: product\n"
            "primary_contexts:\n"
            "  - example\n"
            "input_stage_ref: memories/system/input-stage.md\n"
            if ordinal == 0
            else ""
        )
        relations = "\n".join(f"  - {value}" for value in related)
        body = (
            "---\n"
            f"page_id: {_page_id(seed, ordinal)}\n"
            f"page_type: {page_type}\n"
            f"title: \"Synthetic node {ordinal:05d}\"\n"
            "context: example\n"
            "visibility: public\n"
            f"updated_at: 2026-{1 + (ordinal // 28) % 12:02d}-{1 + ordinal % 28:02d}\n"
            "stale_after_days: 3650\n"
            f"{root_fields}"
            f"{parent}"
            "related_pages:\n"
            f"{relations}\n"
            "---\n\n"
            f"# Synthetic node {ordinal:05d}\n\n"
            f"Deterministic public performance content for ordinal {ordinal}.\n"
        )
        _write(target_root / f"memories/example/{_page_id(seed, ordinal)}.md", body)
    relation_file = target_root / "data/performance/relations.jsonl"
    event_file = target_root / "data/performance/events.jsonl"
    relation_file.parent.mkdir(parents=True, exist_ok=True)
    with relation_file.open("w", encoding="utf-8") as relations_handle, event_file.open(
        "w", encoding="utf-8"
    ) as events_handle:
        for record in logical_records(profile, seed):
            if record["kind"] == "relation":
                relations_handle.write(canonical_bytes(record).decode("utf-8") + "\n")
            elif record["kind"] == "event":
                events_handle.write(canonical_bytes(record).decode("utf-8") + "\n")
    fixture = fixture_identity(profile, seed)
    _write(
        target_root / "fixture.json",
        json.dumps(fixture, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    subprocess.run(["git", "init", "-b", "main"], cwd=target_root, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=target_root, check=True, capture_output=True)
    env = {
        "GIT_AUTHOR_NAME": "Synthetic Fixture",
        "GIT_AUTHOR_EMAIL": "synthetic@example.invalid",
        "GIT_COMMITTER_NAME": "Synthetic Fixture",
        "GIT_COMMITTER_EMAIL": "synthetic@example.invalid",
        "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
        "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
    }
    subprocess.run(
        ["git", "commit", "-m", "fixture: deterministic performance subject"],
        cwd=target_root,
        check=True,
        capture_output=True,
        env={**__import__("os").environ, **env},
    )
    fixture["git_sha"] = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=target_root, check=True, capture_output=True, text=True
    ).stdout.strip()
    return fixture
