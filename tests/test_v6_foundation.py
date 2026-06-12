"""Tests for the v6 foundation: freshness-by-context, de-genericized proposals,
entity mention->link warn, the source registry, and the gate pending guard."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wiki_core.config import WikiConfig, freshness_for, load_config
from wiki_core.paths import WikiPaths


def _load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
# freshness_for: context drives the update cadence
# --------------------------------------------------------------------------- #


def test_freshness_for_context_default_and_type_override():
    cfg = WikiConfig(freshness={"default": 30, "finance": 14, "type:source": 7})
    assert freshness_for("finance", "decision", cfg) == 14   # context wins
    assert freshness_for("unknown", "decision", cfg) == 30   # falls back to default
    assert freshness_for("finance", "source", cfg) == 7      # type override beats context
    # No usable value anywhere -> hard fallback 30.
    assert freshness_for("x", "y", WikiConfig(freshness={})) == 30


# --------------------------------------------------------------------------- #
# A. De-genericized proposal: a pending marker, never filler prose
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("language, filler", [
    ("en", ("To fill in", "depends on extraction", "Proposal generated from metadata")),
    ("pt", ("A preencher", "depende de extracao", "Proposta gerada por metadados")),
])
def test_proposal_has_pending_marker_not_filler(language, filler):
    ingest = _load_script("wiki_new_ingest")
    import datetime as dt

    out = ingest.build_proposal("https://example.com/x.html", "system", dt.date(2026, 6, 10), "draft", language)
    assert "<!-- pending" in out or "<!-- pendente" in out
    for phrase in filler:
        assert phrase not in out, f"filler leaked: {phrase!r}"
    # Quadrant rows are present but EMPTY (structure, no fake content).
    assert "| Interior individual |  |  |" in out


# --------------------------------------------------------------------------- #
# C. Entity mention -> link (warn)
# --------------------------------------------------------------------------- #


def _load_audit():
    return _load_script("wiki_audit")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_entity_mention_without_link_warns(tmp_path, monkeypatch):
    audit = _load_audit()
    cfg = WikiConfig()  # English defaults: memory_root = memories
    _write(
        tmp_path / "memories/people/ana.md",
        '---\npage_id: person-ana\npage_type: person\ntitle: "Ana Souza"\n---\n# Ana Souza\n',
    )
    _write(
        tmp_path / "memories/system/note.md",
        "---\npage_id: note\npage_type: source_catalog\n---\n# Note\nAna Souza reviewed the plan.\n",
    )
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(
        audit, "markdown_files",
        lambda: ["memories/people/ana.md", "memories/system/note.md"],
    )
    audit.parse_frontmatter.cache_clear()
    errors: list[str] = []
    warnings: list[str] = []
    audit.audit_entity_mention_links(warnings, cfg, errors)
    assert not errors  # nothing changed in the diff: warn-only
    assert any("Ana Souza" in w and "note.md" in w for w in warnings)


def test_entity_mention_when_linked_does_not_warn(tmp_path, monkeypatch):
    audit = _load_audit()
    cfg = WikiConfig()
    _write(
        tmp_path / "memories/people/ana.md",
        '---\npage_id: person-ana\npage_type: person\ntitle: "Ana Souza"\n---\n# Ana Souza\n',
    )
    _write(
        tmp_path / "memories/system/note.md",
        "---\npage_id: note\npage_type: source_catalog\n---\n# Note\n"
        "[Ana Souza](../people/ana.md) reviewed the plan.\n",
    )
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(
        audit, "markdown_files",
        lambda: ["memories/people/ana.md", "memories/system/note.md"],
    )
    audit.parse_frontmatter.cache_clear()
    errors: list[str] = []
    warnings: list[str] = []
    audit.audit_entity_mention_links(warnings, cfg, errors)
    assert not errors and not warnings


def test_entity_alias_map_drops_short_and_common_names():
    audit = _load_audit()
    cfg = WikiConfig()
    catalog = {
        "person-ana": ("memories/people/ana.md", {"page_type": "person", "title": "Ana Souza"}),
        "person-bo": ("memories/people/bo.md", {"page_type": "person", "title": "Bo"}),  # too short
        "src-index": ("memories/sources/index.md", {"page_type": "ontology_index", "title": "Index"}),  # common word
    }
    aliases = audit._entity_alias_map(catalog, cfg)
    assert "ana souza" in aliases
    assert "bo" not in aliases
    assert "index" not in aliases


def test_duplicate_entity_canonical_name_errors(tmp_path, monkeypatch):
    audit = _load_audit()
    cfg = WikiConfig()
    _write(
        tmp_path / "memories/people/ana.md",
        '---\npage_id: person-ana\npage_type: person\ntitle: "Person - Ana Souza"\n---\n# Ana Souza\n',
    )
    _write(
        tmp_path / "memories/people/ana-souza.md",
        "---\npage_id: person-ana-souza\npage_type: person\n---\n# Ana Souza\n",
    )
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(
        audit,
        "markdown_files",
        lambda: ["memories/people/ana.md", "memories/people/ana-souza.md"],
    )
    audit.parse_frontmatter.cache_clear()
    errors: list[str] = []
    audit.audit_duplicate_entity_names(errors, cfg)
    assert any("duplicate entity canonical name `ana souza`" in e for e in errors)


def test_operational_concept_links_error_when_hub_uses_plain_term(tmp_path, monkeypatch):
    audit = _load_audit()
    cfg = WikiConfig(
        audit={
            "operational_concept_links": {
                "memories/companies/index.md": {
                    "memories/sources/index.md": ["source"],
                    "memories/claims/index.md": ["claim"],
                }
            }
        }
    )
    _write(tmp_path / "memories/sources/index.md", "# Sources\n")
    _write(tmp_path / "memories/claims/index.md", "# Claims\n")
    _write(tmp_path / "memories/companies/index.md", "# Hub\nUse source and claim here.\n")
    monkeypatch.setattr(audit, "ROOT", tmp_path)

    errors: list[str] = []
    audit.audit_operational_concept_links(errors, cfg)

    assert any("operational concepts without links" in e and "`source`" in e for e in errors)
    assert any("operational concepts without links" in e and "`claim`" in e for e in errors)


def test_operational_concept_links_accepts_markdown_links(tmp_path, monkeypatch):
    audit = _load_audit()
    cfg = WikiConfig(
        audit={
            "operational_concept_links": {
                "memories/companies/index.md": {
                    "memories/sources/index.md": ["source"],
                }
            }
        }
    )
    _write(tmp_path / "memories/sources/index.md", "# Sources\n")
    _write(
        tmp_path / "memories/companies/index.md",
        "# Hub\nUse [canonical sources](../sources/index.md) when a source appears here.\n",
    )
    monkeypatch.setattr(audit, "ROOT", tmp_path)

    errors: list[str] = []
    audit.audit_operational_concept_links(errors, cfg)

    assert errors == []


def test_tracked_files_skip_deleted_paths(tmp_path, monkeypatch):
    audit = _load_audit()
    _write(tmp_path / "memories/people/ana.md", "# Ana\n")
    monkeypatch.setattr(audit, "ROOT", tmp_path)

    def fake_git(args):
        if args == ["ls-files"]:
            return "memories/people/ana.md\nmemories/people/deleted.md"
        if args == ["ls-files", "--others", "--exclude-standard"]:
            return ""
        return ""

    monkeypatch.setattr(audit, "run_git", fake_git)
    audit.tracked_files.cache_clear()
    assert audit.tracked_files() == ["memories/people/ana.md"]


# --------------------------------------------------------------------------- #
# D. Source registry: deterministic + language-aware
# --------------------------------------------------------------------------- #


def test_source_registry_is_deterministic_and_titled():
    reg = _load_script("wiki_source_registry")
    config = load_config(ROOT)
    paths = WikiPaths(ROOT, config)
    a = reg.build_registry(paths, config, "2026-06-10")
    b = reg.build_registry(paths, config, "2026-06-10")
    assert a == b  # deterministic
    assert reg.STRINGS[config.language]["title"] in a
    assert "page_type: source_registry" in a


# --------------------------------------------------------------------------- #
# A. Gate refuses to advance a proposal while the pending marker survives
# --------------------------------------------------------------------------- #


def test_gate_refuses_advance_while_pending(tmp_path, capsys):
    gate = _load_script("wiki_gate")
    proposal = tmp_path / "p.md"
    proposal.write_text(
        "---\npage_id: p\ngate_state: created\ncreated_at: 2026-06-10\n---\n"
        "body\n<!-- pending: filled by the contextual deep-read -->\n",
        encoding="utf-8",
    )
    rc = gate.cmd_transition(proposal, "approved", None)
    assert rc == 1
    err = capsys.readouterr().err
    assert "pending deep-read marker" in err


# --------------------------------------------------------------------------- #
# Phase 2: external-tool entity types + per-source config column
# --------------------------------------------------------------------------- #


def test_phase2_ontology_types_registered():
    audit = _load_audit()
    types = audit.ONTOLOGY_DIRNAME_TYPES
    assert "meeting" in types["meetings"] and "meeting" in types["reunioes"]
    assert "external_card" in types["cards"] and "external_card" in types["cartoes"]
    assert "calendar_event" in types["calendar"] and "calendar_event" in types["calendario"]
    # Per-source config pages live under the sources dir.
    assert "source_config" in types["sources"] and "source_config" in types["fontes"]


def test_registry_config_column_only_links_existing_config(tmp_path, monkeypatch):
    reg = _load_script("wiki_source_registry")
    cfg = WikiConfig()  # English defaults: sources under memories/sources
    paths = WikiPaths(tmp_path, cfg)
    (tmp_path / "memories/sources/config").mkdir(parents=True)
    (tmp_path / "memories/sources/config/s.md").write_text(
        "---\npage_id: cfg-s\npage_type: source_config\n---\n", encoding="utf-8"
    )
    (tmp_path / "memories/sources/s.md").write_text(
        '---\npage_id: source-s\npage_type: source\ntitle: "S"\n'
        "config_ref: memories/sources/config/s.md\n---\n",
        encoding="utf-8",
    )
    (tmp_path / "memories/sources/t.md").write_text(
        '---\npage_id: source-t\npage_type: source\ntitle: "T"\n'
        "config_ref: memories/sources/config/missing.md\n---\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(reg, "ROOT", tmp_path)
    rows = {r["title"]: r["config"] for r in reg.collect_sources(paths)}
    assert rows["S"] == "memories/sources/config/s.md"  # exists -> linkable
    assert rows["T"] == ""                              # missing -> not linked


def test_source_registry_marks_next_refresh_status(tmp_path, monkeypatch):
    reg = _load_script("wiki_source_registry")
    cfg = WikiConfig()
    paths = WikiPaths(tmp_path, cfg)
    _write(
        tmp_path / "memories/sources/s.md",
        '---\npage_id: source-s\npage_type: source\ntitle: "S"\n'
        "source_type: live\ningestion_state: ingested\nlast_ingested_at: 2026-06-01\n"
        "refresh_policy: recurring\nrefresh_cadence_days: 7\n---\n",
    )
    monkeypatch.setattr(reg, "ROOT", tmp_path)
    rendered = reg.build_registry(paths, cfg, "2026-06-10")
    assert "| S |" not in rendered  # linked title, not bare filler
    assert "2026-06-08" in rendered
    assert "| due | recurring (7d) |" in rendered


def test_obsidian_directory_links_warn(tmp_path, monkeypatch):
    audit = _load_audit()
    cfg = WikiConfig()
    _write(tmp_path / "docs/README.md", "# Docs\n")
    _write(
        tmp_path / "memories/system/note.md",
        "# Note\n[Docs folder](../../docs/) and [Docs index](../../docs/README.md).\n",
    )
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(audit, "link_audit_files", lambda _cfg: ["memories/system/note.md"])
    warnings: list[str] = []
    audit.audit_obsidian_directory_links(warnings, cfg)
    assert any("directories" in warning and "Obsidian" in warning for warning in warnings)
