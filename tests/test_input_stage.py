from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from wiki_core.config import WikiConfig
from wiki_core.input_stage import compile_input_stage, input_context_for_source, render_input_stage_markdown


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _source_page(
    page_id: str,
    title: str,
    ingestion_state: str,
    config_ref: str,
) -> str:
    return (
        "---\n"
        f"page_id: {page_id}\n"
        "page_type: source\n"
        f"title: \"{title}\"\n"
        "context: example\n"
        "visibility: private_self\n"
        "updated_at: 2026-06-25\n"
        "stale_after_days: 45\n"
        "source_type: reference\n"
        f"ingestion_state: {ingestion_state}\n"
        "moc_parent: memories/example/index.md\n"
        f"config_ref: {config_ref}\n"
        "source_refs: []\n"
        "---\n\n"
        f"# {title}\n"
    )


def _source_config_page(page_id: str, source_ref: str) -> str:
    return (
        "---\n"
        f"page_id: {page_id}\n"
        "page_type: source_config\n"
        f"title: \"{page_id}\"\n"
        "context: example\n"
        "visibility: private_self\n"
        "updated_at: 2026-06-25\n"
        "stale_after_days: 90\n"
        "moc_parent: memories/example/index.md\n"
        "source_refs:\n"
        f"  - {source_ref}\n"
        "input_channel_ref: input-channel-team-docs\n"
        "quadrants:\n"
        "  - q4\n"
        "perspectives_required:\n"
        "  - perspective-roles-relationships\n"
        "target_pages:\n"
        "  - memories/example/index.md\n"
        "---\n\n"
        f"# {page_id}\n"
    )


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
    assert catalog["quadrant_semantics"]["q1"]["semantic_key"] == "interior_individual"
    assert catalog["quadrant_semantics"]["q2"]["aqal_position"] == "It / exterior individual / upper-right"
    assert catalog["quadrant_semantics"]["q3"]["semantic_key"] == "interior_collective"
    assert catalog["quadrant_semantics"]["q4"]["aqal_position"] == "Its / exterior collective / lower-right"
    assert "do not invent consciousness" in catalog["quadrant_semantics"]["q1"]["operational_test"]
    assert "not enough" in catalog["quadrant_semantics"]["q2"]["operational_test"]
    assert "plain people roster" in catalog["quadrant_semantics"]["q3"]["operational_test"]
    assert "artifact/output/evidence" in catalog["quadrant_boundary_rule"]
    assert "as externally administered structure they belong to q4" in catalog["quadrant_boundary_rule"]
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
    assert catalog["ready_inputs"] == []


def test_ready_inputs_exclude_configured_sources_until_staged(
    tmp_path: Path,
) -> None:
    cfg = _fixture_repo(tmp_path)
    _write(
        tmp_path / "memories/sources/staged-handbook.md",
        _source_page(
            "source-staged-handbook",
            "Staged handbook",
            "staged",
            "memories/sources/config/staged-handbook.md",
        ),
    )
    _write(
        tmp_path / "memories/sources/config/staged-handbook.md",
        _source_config_page("source-config-staged-handbook", "source-staged-handbook"),
    )
    _write(
        tmp_path / "memories/sources/ready-handbook.md",
        _source_page(
            "source-ready-handbook",
            "Ready handbook",
            "ready_for_ingest",
            "memories/sources/config/ready-handbook.md",
        ),
    )
    _write(
        tmp_path / "memories/sources/config/ready-handbook.md",
        _source_config_page("source-config-ready-handbook", "source-ready-handbook"),
    )

    catalog = compile_input_stage(tmp_path, cfg, generated_at=dt.date(2026, 6, 25))
    ready = {source["source_page_id"]: source["input_status"] for source in catalog["ready_inputs"]}

    assert ready == {
        "source-ready-handbook": "ready_for_ingest",
        "source-staged-handbook": "staged",
    }
    assert next(
        source
        for source in catalog["sources"]
        if source["source_page_id"] == "source-team-handbook"
    )["input_status"] == "configured"

    ready_section = render_input_stage_markdown(catalog, cfg).split("## Ready inputs", 1)[1]
    assert "Team handbook" not in ready_section
    assert "Staged handbook" in ready_section
    assert "Ready handbook" in ready_section


def test_input_context_for_source_returns_request_metadata(tmp_path: Path) -> None:
    cfg = _fixture_repo(tmp_path)

    context = input_context_for_source(tmp_path, cfg, "memories/sources/team-handbook.md")

    assert context["root_entity"]["page_id"] == "root-example-team"
    assert context["input_channel"]["page_id"] == "input-channel-team-docs"
    assert context["input_stage_status"] == "configured"
    assert context["quadrant_semantics"]["q2"]["semantic_key"] == "exterior_individual"
    assert "coordinates people" in context["quadrant_boundary_rule"]
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
    assert "## Quadrant semantics" in md
    assert "`q2` | `exterior_individual` | It / exterior individual / upper-right" in md
    assert "Boundary rule: Apply the quadrant to the root holon" in md
    assert "as externally administered structure they belong to q4" in md
    assert "perspective-identity-intent" in md


def test_render_input_stage_links_repo_paths_in_generated_warnings(tmp_path: Path) -> None:
    cfg = _fixture_repo(tmp_path)
    (tmp_path / "memories/sources/config/team-handbook.md").unlink()
    (tmp_path / "memories/input-channels/team-docs.md").unlink()
    _write(
        tmp_path / "memories/input-channels/orphan-channel.md",
        """---
page_id: input-channel-orphan
page_type: input_channel
title: "Orphan channel"
context: example
visibility: private_self
updated_at: 2026-06-25
stale_after_days: 30
channel_type: document
input_status: configured
moc_parent: memories/example/index.md
source_refs:
  - source-not-found
---

# Orphan channel
""",
    )

    catalog = compile_input_stage(tmp_path, cfg, generated_at="2026-06-25")
    md = render_input_stage_markdown(catalog, cfg)

    assert (
        "- [memories/sources/team-handbook.md](../sources/team-handbook.md): "
        "no source_config linked" in md
    )
    assert (
        "- [memories/sources/team-handbook.md](../sources/team-handbook.md): "
        "no input_channel linked" in md
    )
    assert (
        "- [memories/input-channels/orphan-channel.md]"
        "(../input-channels/orphan-channel.md): source_refs not found: source-not-found"
        in md
    )
    assert "- memories/sources/team-handbook.md:" not in md
    assert "- memories/input-channels/orphan-channel.md:" not in md


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
    assert "## Semantica dos quadrantes" in md
    assert "## Canais de entrada" in md
    assert "Vista interior do holon raiz" in md
    assert "O fato de algo ser documento ou repositorio nao basta" in md
    assert "cadastro simples de pessoas" in md
    assert "Regra de fronteira: Aplicar o quadrante ao holon raiz" in md
    assert "Apply the quadrant to the root holon" not in md
    assert "Atualizado em: 2026-06-25." in md


def test_render_input_stage_markdown_supports_spanish(tmp_path: Path) -> None:
    cfg = _fixture_repo(tmp_path)
    cfg = WikiConfig(
        language="es",
        contexts=cfg.contexts,
        default_context=cfg.default_context,
        paths=cfg.paths,
        root_entity=cfg.root_entity,
    )
    catalog = compile_input_stage(tmp_path, cfg, generated_at="2026-06-25")

    md = render_input_stage_markdown(catalog, cfg)

    assert 'title: "Etapa de entrada"' in md
    assert "## Entidad raíz" in md
    assert "## Semántica de los cuadrantes" in md
    assert "## Canales de entrada" in md
    assert "Regla de frontera:" in md
    assert "holón raíz" in md
    assert "Actualizado el: 2026-06-25." in md


def _published_stage(tmp_path, cfg, *, legacy=False):
    from wiki_core.input_stage import write_input_stage
    from wiki_core.paths import WikiPaths

    catalog = write_input_stage(tmp_path, cfg, generated_at="2026-06-25")
    paths = WikiPaths(tmp_path, cfg)
    if legacy:
        paths.input_stage_page.write_text(
            render_input_stage_markdown(catalog, cfg, _annotate_targets=False), encoding="utf-8")
    return paths


@pytest.mark.parametrize("legacy", [False, True])
def test_incremental_write_preserves_publication_identity_and_repairs_cache(tmp_path, legacy):
    from wiki_core.input_stage import write_input_stage

    cfg = _fixture_repo(tmp_path)
    paths = _published_stage(tmp_path, cfg, legacy=legacy)
    before = paths.input_stage_page.read_bytes()
    stat = paths.input_stage_page.stat()
    paths.input_stage_catalog.unlink()
    # A missing cache is newly generated today; it cannot date the older MD.
    catalog = write_input_stage(tmp_path, cfg, generated_at="2026-06-26", if_changed=True)
    assert catalog["generated_at"] == "2026-06-26"
    assert paths.input_stage_page.read_bytes() == before
    assert (paths.input_stage_page.stat().st_ino, paths.input_stage_page.stat().st_mtime_ns) == (stat.st_ino, stat.st_mtime_ns)
    cache = paths.input_stage_catalog.read_bytes()
    cache_stat = paths.input_stage_catalog.stat()
    # Both artifacts now remain literally unchanged, at their separate dates.
    write_input_stage(tmp_path, cfg, generated_at="2026-06-27", if_changed=True)
    assert paths.input_stage_page.read_bytes() == before
    assert paths.input_stage_catalog.read_bytes() == cache
    assert (paths.input_stage_catalog.stat().st_ino, paths.input_stage_catalog.stat().st_mtime_ns) == (cache_stat.st_ino, cache_stat.st_mtime_ns)
    assert paths.input_stage_page.stat().st_mtime_ns == stat.st_mtime_ns
    # Default behavior still deliberately regenerates both outputs.
    catalog = write_input_stage(tmp_path, cfg, generated_at="2026-06-28")
    assert catalog["generated_at"] == "2026-06-28"
    assert paths.input_stage_page.read_bytes() != before
    assert b"updated_at: 2026-06-28" in paths.input_stage_page.read_bytes()


@pytest.mark.parametrize("change", ["date", "policy", "prose", "retarget", "source_marker", "mixed", "crlf", "missing"])
def test_incremental_write_never_normalizes_unsupported_publication(tmp_path, change):
    from wiki_core.input_stage import matching_input_stage_catalog, write_input_stage

    cfg = _fixture_repo(tmp_path)
    config_path = tmp_path / "memories/sources/config/team-handbook.md"
    config_path.write_text(config_path.read_text().replace(
        "target_pages:\n  - memories/example/index.md",
        "target_pages:\n  - memories/example/index.md\n  - memories/example/second.md"))
    paths = _published_stage(tmp_path, cfg)
    text = paths.input_stage_page.read_text()
    if change == "date":
        text = text.replace("updated_at: 2026-06-25", "updated_at: 20260625")
    elif change == "policy":
        text = text.replace("stale_after_days: 1", "stale_after_days: 90")
    elif change == "prose":
        text += "\nAdditional processing instruction.\n"
    elif change == "retarget":
        text = text.replace("[Team docs](../input-channels/team-docs.md)", "[Team docs](../different.md)")
    elif change == "source_marker":
        text = text.replace("[Team handbook](../sources/team-handbook.md)",
                            "[Team handbook](../sources/team-handbook.md)<!-- wiki-link-role.v9 navigation -->")
    elif change == "mixed":
        start = text.index("<!-- wiki-link-role.v1")
        end = text.index(" -->", start) + len(" -->")
        text = text[:start] + text[end:]
    elif change == "crlf":
        text = text.replace("\n", "\r\n")
    if change == "missing":
        paths.input_stage_page.unlink()
    else:
        paths.input_stage_page.write_bytes(text.encode())
    current = compile_input_stage(tmp_path, cfg, generated_at="2026-06-26")
    assert matching_input_stage_catalog(current, cfg, paths.input_stage_page.read_bytes()
                                        if paths.input_stage_page.exists() else b"") is None
    write_input_stage(tmp_path, cfg, generated_at="2026-06-26", if_changed=True)
    assert paths.input_stage_page.read_bytes() == render_input_stage_markdown(current, cfg).encode()


@pytest.mark.parametrize("change", ["status", "target", "language"])
def test_incremental_write_generates_new_publication_for_visible_input_change(tmp_path, change):
    from dataclasses import replace
    from wiki_core.input_stage import write_input_stage

    cfg = _fixture_repo(tmp_path)
    paths = _published_stage(tmp_path, cfg, legacy=True)
    if change == "status":
        source = tmp_path / "memories/sources/team-handbook.md"
        source.write_text(source.read_text().replace("ingestion_state: unread", "ingestion_state: staged"))
    elif change == "target":
        config_path = tmp_path / "memories/sources/config/team-handbook.md"
        config_path.write_text(config_path.read_text().replace(
            "target_pages:\n  - memories/example/index.md",
            "target_pages:\n  - memories/example/index.md\n  - memories/example/new.md"))
    else:
        cfg = replace(cfg, language="es")
    write_input_stage(tmp_path, cfg, generated_at="2026-06-26", if_changed=True)
    assert b"updated_at: 2026-06-26" in paths.input_stage_page.read_bytes()
    assert "wiki-link-role.v1 change_target" in paths.input_stage_page.read_text()


def test_hidden_model_change_updates_json_at_its_real_date_not_markdown_date(tmp_path):
    from wiki_core.input_stage import matching_input_stage_cache, write_input_stage

    cfg = _fixture_repo(tmp_path)
    paths = _published_stage(tmp_path, cfg)
    before = paths.input_stage_page.read_bytes()
    source = tmp_path / "memories/sources/team-handbook.md"
    source.write_text(source.read_text().replace("visibility: private_self", "visibility: public")
                      .replace("source_type: reference", "source_type: reference\nrefresh_cadence_days: 7"))
    current = compile_input_stage(tmp_path, cfg, generated_at="2026-06-26")
    assert matching_input_stage_cache(current, paths.input_stage_catalog.read_bytes()) is None
    catalog = write_input_stage(tmp_path, cfg, generated_at="2026-06-26", if_changed=True)
    assert paths.input_stage_page.read_bytes() == before
    assert catalog["generated_at"] == "2026-06-26"
    assert catalog["sources"][0]["privacy_boundary"] == "public"
    assert catalog["sources"][0]["refresh_cadence_days"] == "7"


def test_cli_checks_independent_output_dates_and_reports_actual_execution(tmp_path, monkeypatch, capsys):
    from scripts import wiki_input_stage as cli

    cfg = _fixture_repo(tmp_path)
    paths = _published_stage(tmp_path, cfg, legacy=True)
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "load_config", lambda root: cfg)
    def run(*args):
        monkeypatch.setattr(sys, "argv", ["wiki_input_stage.py", *args])
        return cli.main()
    with pytest.raises(SystemExit) as invalid:
        run("--if-changed")
    assert invalid.value.code == 2
    capsys.readouterr()
    paths.input_stage_catalog.write_text('{"generated_at":"2099-01-01","sources":[]}')
    assert run("--check") == 1  # Contradictory model cannot date or validate MD.
    capsys.readouterr()
    assert run("--write", "--if-changed") == 0
    status = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert status["md_changed"] is False and status["catalog_changed"] is True
    assert status["md_publication_date"] == "2026-06-25"
    assert status["catalog_generation_date"] == dt.date.today().isoformat()
    assert dt.datetime.fromisoformat(status["executed_at"]).tzinfo is not None
    assert run("--check") == 0  # Different valid generation dates are supported.
    paths.input_stage_catalog.unlink()
    assert run("--check") == 0  # Existing policy: ignored cache is optional.


def test_incremental_publication_keeps_whole_time_hash_consumers_and_real_source_seeds(tmp_path):
    from wiki_core.config import load_config
    from wiki_core.freshness_impact import repository_report
    from wiki_core.input_stage import write_input_stage

    cfg = _fixture_repo(tmp_path)
    (tmp_path / "wiki.config.yaml").write_text(yaml.safe_dump(dict(
        contexts=["example"], default_context="example", root_entity=cfg.root_entity)))
    (tmp_path / ".gitignore").write_text("data/derived/\n")
    _write(tmp_path / "memories/index.md", "---\npage_id: synthetic-index\npage_type: moc\n"
           "updated_at: 2026-10-19\nstale_after_days: 30\n---\n# Synthetic index\n")
    paths = _published_stage(tmp_path, cfg, legacy=True)
    before = paths.input_stage_page.read_bytes()
    for name, claim in (("whole", "Uses this whole artifact"),
                        ("time", "Compilation published on2026-06-25"),
                        ("identity", "Expected SHA256=" + hashlib.sha256(before).hexdigest())):
        _write(tmp_path / f"memories/{name}.md", "---\npage_id: " + name +
               "\npage_type: project\nupdated_at: 2026-01-01\nstale_after_days: 1\n---\n" +
               claim + ": [input stage](system/input-stage.md).\n")
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True).strip()
    git("init", "-q")
    git("config", "user.name", "Synthetic Fixture")
    git("config", "user.email", "fixture@example.invalid")
    git("add", ".")
    git("commit", "-qm", "synthetic original publication")
    base = git("rev-parse", "HEAD")
    def report():
        return repository_report(tmp_path, load_config(tmp_path), base, today=dt.date(2026, 10, 19))
    write_input_stage(tmp_path, cfg, generated_at="2026-10-19", if_changed=True)
    assert paths.input_stage_page.read_bytes() == before
    assert report()["ok"]  # Nothing was published; stale debt is still debt.
    consumers = {f"memories/{name}.md" for name in ("whole", "time", "identity")}
    write_input_stage(tmp_path, cfg, generated_at="2026-10-19")
    assert consumers <= {r["path"] for r in report()["blockers"]}
    paths.input_stage_page.write_bytes(before)
    source = tmp_path / "memories/sources/team-handbook.md"
    source.write_text(source.read_text().replace("visibility: private_self", "visibility: public")
                      .replace("source_type: reference", "source_type: reference\nrefresh_cadence_days: 7"))
    catalog = write_input_stage(tmp_path, cfg, generated_at="2026-10-19", if_changed=True)
    result = report()
    assert paths.input_stage_page.read_bytes() == before
    assert "memories/sources/team-handbook.md" in result["seeds"]
    assert catalog["sources"][0]["privacy_boundary"] == "public"
    assert catalog["sources"][0]["refresh_cadence_days"] == "7"
    assert consumers <= {r["path"] for r in result["blockers"]}
