from __future__ import annotations

import datetime as dt
from pathlib import Path

from wiki_core.config import WikiConfig
from wiki_core.input_stage import compile_input_stage, input_context_for_source, render_input_stage_markdown


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fixture_repo(tmp_path: Path) -> WikiConfig:
    cfg = WikiConfig(
        contexts=("example",),
        default_context="example",
        root_entity={
            **WikiConfig().root_entity,
            "page": "memories/example/index.md",
            "entity_type": "team",
            "perspective_bundle": {
                "required": ["perspective-identity-intent"],
                "optional": ["perspective-privacy-publication"],
            },
        },
    )
    _write(
        tmp_path / "memories/example/index.md",
        """---
page_id: root-example-team
page_type: root_entity
title: "Example team"
context: example
visibility: private_self
updated_at: 2026-06-25
stale_after_days: 30
root_entity_type: team
moc_parent: memories/index.md
primary_contexts:
  - example
input_stage_ref: memories/system/input-stage.md
perspective_bundle_required:
  - perspective-artifacts-evidence
perspective_bundle_optional: []
---

# Example team

## Identity and Scope

## Integral Quadrant Map

## Channels and Input Sources

## Perspective Bundle

## Source Ingestion Map
""",
    )
    _write(
        tmp_path / "memories/input-channels/team-docs.md",
        """---
page_id: input-channel-team-docs
page_type: input_channel
title: "Team docs"
context: example
visibility: private_self
updated_at: 2026-06-25
stale_after_days: 30
channel_type: document
input_status: configured
moc_parent: memories/example/index.md
quadrants:
  - q2
  - q4
perspectives_required:
  - perspective-systems-processes
source_refs:
  - source-team-handbook
source_config_refs:
  - source-config-team-handbook
process_refs:
  - process-delivery
target_pages:
  - memories/example/index.md
---

# Team docs
""",
    )
    _write(
        tmp_path / "memories/sources/team-handbook.md",
        """---
page_id: source-team-handbook
page_type: source
title: "Team handbook"
context: example
visibility: private_self
updated_at: 2026-06-25
stale_after_days: 45
source_type: reference
ingestion_state: unread
moc_parent: memories/example/index.md
config_ref: memories/sources/config/team-handbook.md
source_refs: []
---

# Team handbook
""",
    )
    _write(
        tmp_path / "memories/sources/config/team-handbook.md",
        """---
page_id: source-config-team-handbook
page_type: source_config
title: "Team handbook config"
context: example
visibility: private_self
updated_at: 2026-06-25
stale_after_days: 90
moc_parent: memories/example/index.md
source_refs:
  - source-team-handbook
input_channel_ref: input-channel-team-docs
quadrants:
  - q4
perspectives_required:
  - perspective-roles-relationships
perspectives_optional:
  - perspective-project
target_pages:
  - memories/example/index.md
---

# Team handbook config
""",
    )
    return cfg


def test_compile_input_stage_inherits_root_channel_and_source_config(tmp_path: Path) -> None:
    cfg = _fixture_repo(tmp_path)

    catalog = compile_input_stage(tmp_path, cfg, generated_at=dt.date(2026, 6, 25))

    assert catalog["schema_version"] == "wiki_input_stage.v1"
    assert catalog["root_entity"]["page_id"] == "root-example-team"
    assert catalog["root_entity"]["entity_type"] == "team"
    assert len(catalog["sources"]) == 1
    source = catalog["sources"][0]
    assert source["input_status"] == "configured"
    assert source["input_channel"]["page_id"] == "input-channel-team-docs"
    assert source["source_config"]["page_id"] == "source-config-team-handbook"
    assert source["quadrants"] == ["q2", "q4"]
    assert source["resolved_perspectives"]["required"] == [
        "perspective-identity-intent",
        "perspective-artifacts-evidence",
        "perspective-systems-processes",
        "perspective-roles-relationships",
    ]
    assert source["resolved_perspectives"]["optional"] == [
        "perspective-privacy-publication",
        "perspective-project",
    ]
    assert source["target_pages"] == ["memories/example/index.md"]


def test_input_context_for_source_returns_request_metadata(tmp_path: Path) -> None:
    cfg = _fixture_repo(tmp_path)

    context = input_context_for_source(tmp_path, cfg, "memories/sources/team-handbook.md")

    assert context["root_entity"]["page_id"] == "root-example-team"
    assert context["input_channel"]["page_id"] == "input-channel-team-docs"
    assert context["input_stage_status"] == "configured"
    assert "perspective-systems-processes" in context["perspectives_required"]
    assert context["target_pages"] == ["memories/example/index.md"]


def test_compile_input_stage_treats_source_artifacts_as_canonical_sources(tmp_path: Path) -> None:
    cfg = _fixture_repo(tmp_path)
    _write(
        tmp_path / "memories/input-channels/team-artifacts.md",
        """---
page_id: input-channel-team-artifacts
page_type: input_channel
title: "Team artifacts"
context: example
visibility: private_self
updated_at: 2026-06-25
stale_after_days: 30
channel_type: artifact
input_status: configured
moc_parent: memories/example/index.md
quadrants:
  - q2
source_refs:
  - source-team-proposal
source_config_refs:
  - source-config-team-proposal
target_pages:
  - memories/example/index.md
---

# Team artifacts
""",
    )
    _write(
        tmp_path / "memories/sources/team-proposal.md",
        """---
page_id: source-team-proposal
page_type: artifact
title: "Team proposal"
context: example
visibility: private_self
updated_at: 2026-06-25
stale_after_days: 45
source_type: artifact
ingestion_state: ingested
moc_parent: memories/example/index.md
config_ref: memories/sources/config/team-proposal.md
source_refs: []
---

# Team proposal
""",
    )
    _write(
        tmp_path / "memories/sources/config/team-proposal.md",
        """---
page_id: source-config-team-proposal
page_type: source_config
title: "Team proposal config"
context: example
visibility: private_self
updated_at: 2026-06-25
stale_after_days: 90
moc_parent: memories/example/index.md
source_refs:
  - source-team-proposal
input_channel_ref: input-channel-team-artifacts
quadrants:
  - q2
perspectives_required:
  - perspective-artifacts-evidence
target_pages:
  - memories/example/index.md
---

# Team proposal config
""",
    )

    catalog = compile_input_stage(tmp_path, cfg, generated_at="2026-06-25")

    artifact = next(
        source
        for source in catalog["sources"]
        if source["source_page_id"] == "source-team-proposal"
    )
    assert artifact["source_type"] == "artifact"
    assert artifact["input_status"] == "integrated"
    assert artifact["input_channel"]["page_id"] == "input-channel-team-artifacts"
    assert not catalog["warnings"]


def test_render_input_stage_markdown_is_stable_and_links(tmp_path: Path) -> None:
    cfg = _fixture_repo(tmp_path)
    catalog = compile_input_stage(tmp_path, cfg, generated_at="2026-06-25")

    md = render_input_stage_markdown(catalog, cfg)

    assert "page_type: input_stage" in md
    assert "context: example" in md
    assert "moc_parent: memories/index.md" in md
    assert "[Example team](../example/index.md)" in md
    assert "[Team docs](../input-channels/team-docs.md)" in md
    assert "[Team handbook](../sources/team-handbook.md)" in md
    assert "perspective-identity-intent" in md


def test_render_input_stage_markdown_uses_localized_layout_and_language(tmp_path: Path) -> None:
    cfg = _fixture_repo(tmp_path)
    cfg = WikiConfig(
        language="pt",
        contexts=cfg.contexts,
        default_context="sistema",
        paths={**cfg.paths, "memory_root": "memorias"},
        root_entity={**cfg.root_entity, "input_stage_page": "memorias/sistema/estagio-entrada.md"},
    )
    catalog = compile_input_stage(tmp_path, cfg, generated_at="2026-06-25")

    md = render_input_stage_markdown(catalog, cfg)

    assert 'title: "Estagio de entrada"' in md
    assert "context: sistema" in md
    assert "moc_parent: memorias/index.md" in md
    assert "## Entidade raiz" in md
    assert "## Canais de entrada" in md
    assert "Atualizado em: 2026-06-25." in md
