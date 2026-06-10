"""Tests for the presence AND content verifier of the living wiki methodology.

They build a minimal repo in tmp_path and exercise run_checks() to ensure that:
- an empty file fails;
- a file without frontmatter/page_id fails;
- a matrix without the required mentions fails;
- everything present and valid -> complete: true.

Fixture repos use the ENGLISH default layout (no `paths`/`coverage` section in
the fixture config). One dedicated test pins the pt layout in the fixture's
wiki.config.yaml to prove localized-layout compatibility.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COVERAGE_PATH = ROOT / "scripts" / "wiki_check_methodology_coverage.py"


def _load_coverage_module():
    # scripts/ is not a package; load directly from the file. The module inserts
    # ROOT on sys.path at import to resolve its `wiki_core` imports.
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location("wiki_coverage_under_test", COVERAGE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


cov = _load_coverage_module()


PAGE_FM = """---
page_id: {page_id}
page_type: {page_type}
context: system
visibility: private_self
updated_at: 2026-06-09
purpose: {purpose}
---

{body}
"""

TEMPLATE_RAW = """---
page_id: {page_id}
page_type: {page_type}
---

# Template

{body}
"""

TEMPLATE_FENCED = """# Template - {page_id}

```yaml
---
page_id: {page_id}
page_type: {page_type}
---
```

# Body

{body}
"""

EVENT_BODY = """# Event

## Quadrants

| Quadrant | Content |
| --- | --- |
| Interior individual | something real and long enough here |
"""

LONG_BODY = "Page body with real content that is long enough to pass the minimum byte threshold."

PERCEPTIVE_PAGE = """---
page_id: {page_id}
page_type: {page_type}
context: system
visibility: private_self
updated_at: 2026-06-09
status: active
status_epistemologico: percepcao
purpose: real perceptive test page
perception_policy:
  layer: perceptiva
  is_canonical_truth: false
---

{body}
"""

# Required mentions per language (see COVERAGE_REQUIRED_MENTIONS_BY_LANG).
COVERAGE_BODY_EN = (
    "Matrix covering page visibility, the roles of agents, full perceptive "
    "reading and the karma/gamification system."
)
COVERAGE_BODY_PT = (
    "Matriz cobrindo visibilidade das paginas, papeis de agentes, leitura "
    "perceptiva integral e o sistema de karma/gamificacao."
)

# English default layout (no `paths` section in the fixture config).
EN_LAYOUT = {
    "config": "repo_id: scaffold\nlanguage: en\n",
    "source_page": "memories/sources/wiki-viva-methodology-v5.md",
    "coverage_matrix": "memories/system/methodology-coverage-v5.md",
    "operation_page": "memories/operations.md",
    "templates_root": "docs/references/templates/wiki",
    "template_names": (
        "ingestion-event.md",
        "operation.md",
        "vitality-dashboard.md",
        "subagent-brief.md",
        "gate.md",
    ),
    "events_dir": "memories/system/ingestion/events",
    "perception_dir": "memories/system/perception",
    "coverage_body": COVERAGE_BODY_EN,
}

# Localized (pt) layout, pinned explicitly in the fixture's wiki.config.yaml —
# proves one shared codebase serves a translated repo layout.
PT_CONFIG = """\
repo_id: scaffold-pt
language: pt
default_context: sistema
paths:
  memory_root: memorias
  references_root: docs/referencias
  system_dirname: sistema
  ingest_dirname: ingestao
  events_dirname: eventos
  sources_dirname: fontes
  operation_page: memorias/operacao.md
coverage:
  methodology_source_page: memorias/fontes/metodologia-wiki-viva-v5.md
  coverage_matrix_page: memorias/sistema/cobertura-metodologia-v5.md
  required_templates:
    - ingestao-evento.md
    - operacao.md
    - dashboard-vitalidade.md
    - subagent-brief.md
    - gate.md
"""

PT_LAYOUT = {
    "config": PT_CONFIG,
    "source_page": "memorias/fontes/metodologia-wiki-viva-v5.md",
    "coverage_matrix": "memorias/sistema/cobertura-metodologia-v5.md",
    "operation_page": "memorias/operacao.md",
    "templates_root": "docs/referencias/templates/wiki",
    "template_names": (
        "ingestao-evento.md",
        "operacao.md",
        "dashboard-vitalidade.md",
        "subagent-brief.md",
        "gate.md",
    ),
    "events_dir": "memorias/sistema/ingestao/eventos",
    "perception_dir": "memorias/sistema/percepcao",
    "coverage_body": COVERAGE_BODY_PT,
}


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _scaffold_valid_repo(root: Path, layout: dict = EN_LAYOUT) -> None:
    """Creates a minimal repo where ALL content checks pass."""
    # Memory pages.
    _write(
        root / layout["source_page"],
        PAGE_FM.format(
            page_id="source-v5", page_type="source", purpose="methodology source", body=LONG_BODY
        ),
    )
    _write(
        root / layout["coverage_matrix"],
        PAGE_FM.format(
            page_id="coverage-v5",
            page_type="source_catalog",
            purpose="coverage matrix",
            body=layout["coverage_body"],
        ),
    )
    _write(
        root / layout["operation_page"],
        PAGE_FM.format(
            page_id="operations", page_type="dashboard", purpose="daily cockpit", body=LONG_BODY
        ),
    )

    # Templates (mix of raw frontmatter and wrapped in ```yaml).
    tpl_root = root / layout["templates_root"]
    for name in layout["template_names"]:
        template = TEMPLATE_RAW if name == "subagent-brief.md" else TEMPLATE_FENCED
        _write(
            tpl_root / name,
            template.format(page_id=f"tpl-{name.removesuffix('.md')}", page_type="dashboard", body=LONG_BODY),
        )

    # Support files (only need to exist).
    for rel in cov.REQUIRED_SUPPORT_FILES.values():
        _write(root / rel, "support content\n")
    # Real config: declares the scaffold's language and (for localized repos)
    # the pinned layout. Overwrites the support-file placeholder.
    _write(root / "wiki.config.yaml", layout["config"])

    # Perceptive layer: real USE requires >=1 real journal and >=1 real map (not template),
    # with the perception_policy marker in the frontmatter.
    _write(
        root / layout["perception_dir"] / "journal-example.md",
        PERCEPTIVE_PAGE.format(
            page_id="journal-example", page_type="journal_entry", body=LONG_BODY
        ),
    )
    _write(
        root / layout["perception_dir"] / "map-example.md",
        PERCEPTIVE_PAGE.format(
            page_id="map-example", page_type="relationship_map", body=LONG_BODY
        ),
    )

    # Ingestion event with a Quadrants section + ignored README.
    _write(root / layout["events_dir"] / "2026-06-09-event.md", EVENT_BODY)
    _write(root / layout["events_dir"] / "README.md", "# README\nno quadrants here\n")

    # Derived manifest for source_id discovery.
    _write(
        root / "data/derived/wiki/source-manifests/source-example-abc123.json",
        '{"source_id": "source-example-abc123"}\n',
    )


def test_valid_repo_is_complete(tmp_path: Path) -> None:
    _scaffold_valid_repo(tmp_path)
    result = cov.run_checks(tmp_path)
    failing = [e["name"] for e in result["errors"]]
    assert result["complete"] is True, f"unexpected failing checks: {failing}"
    assert result["errors"] == []


def test_valid_repo_with_pinned_pt_layout_is_complete(tmp_path: Path) -> None:
    """Localized-layout compatibility: a repo that pins the pt layout in its
    wiki.config.yaml passes the same gate with zero code changes."""
    _scaffold_valid_repo(tmp_path, layout=PT_LAYOUT)
    result = cov.run_checks(tmp_path)
    failing = [e["name"] for e in result["errors"]]
    assert result["complete"] is True, f"unexpected failing checks: {failing}"
    # The configured pt paths are the ones actually checked.
    checked_paths = {c["path"] for c in result["checks"]}
    assert "memorias/operacao.md" in checked_paths
    assert "docs/referencias/templates/wiki/gate.md" in checked_paths


def test_perceptive_usage_required(tmp_path: Path) -> None:
    # Without real perceptive pages, the coverage fails (requires USE, not a template).
    _scaffold_valid_repo(tmp_path)
    (tmp_path / "memories/system/perception/journal-example.md").unlink()
    (tmp_path / "memories/system/perception/map-example.md").unlink()
    result = cov.run_checks(tmp_path)
    failing = {e["name"] for e in result["errors"]}
    assert result["complete"] is False
    assert "perceptive_journal_real" in failing
    assert "perceptive_map_real" in failing


def test_perceptive_template_does_not_count(tmp_path: Path) -> None:
    # A perceptive page with status=template does NOT count as real use.
    _scaffold_valid_repo(tmp_path)
    (tmp_path / "memories/system/perception/journal-example.md").unlink()
    _write(
        tmp_path / "memories/system/perception/journal-template.md",
        PERCEPTIVE_PAGE.replace("status: active", "status: template").format(
            page_id="journal-template", page_type="journal_entry", body=LONG_BODY
        ),
    )
    result = cov.run_checks(tmp_path)
    failing = {e["name"] for e in result["errors"]}
    assert "perceptive_journal_real" in failing


def test_empty_file_fails(tmp_path: Path) -> None:
    _scaffold_valid_repo(tmp_path)
    # Zero out the source page body (valid frontmatter, empty body).
    (tmp_path / "memories/sources/wiki-viva-methodology-v5.md").write_text(
        "---\npage_id: source-v5\n---\n", encoding="utf-8"
    )
    result = cov.run_checks(tmp_path)
    assert result["complete"] is False
    failing = {e["name"]: e.get("detail") for e in result["errors"]}
    assert "source_page" in failing
    assert "placeholder" in (failing["source_page"] or "")


def test_zero_byte_file_fails(tmp_path: Path) -> None:
    _scaffold_valid_repo(tmp_path)
    (tmp_path / "memories/operations.md").write_text("", encoding="utf-8")
    result = cov.run_checks(tmp_path)
    assert result["complete"] is False
    assert "operation_page" in {e["name"] for e in result["errors"]}


def test_missing_frontmatter_page_id_fails(tmp_path: Path) -> None:
    _scaffold_valid_repo(tmp_path)
    # Body present, but without a frontmatter block / page_id.
    (tmp_path / "memories/sources/wiki-viva-methodology-v5.md").write_text(
        "# Page without frontmatter\n\n" + LONG_BODY + "\n", encoding="utf-8"
    )
    result = cov.run_checks(tmp_path)
    assert result["complete"] is False
    failing = {e["name"]: e.get("detail") for e in result["errors"]}
    assert "source_page" in failing
    assert "page_id" in (failing["source_page"] or "")


def test_template_without_page_type_passes(tmp_path: Path) -> None:
    # Templates vary in schema (the event one uses event_id; the brief has no
    # page frontmatter): we require real content, not a fixed page_type.
    _scaffold_valid_repo(tmp_path)
    _write(
        tmp_path / "docs/references/templates/wiki/gate.md",
        "---\npage_id: tpl-gate\n---\n\n# Body\n\n" + LONG_BODY + "\n",
    )
    result = cov.run_checks(tmp_path)
    failing = {e["name"] for e in result["errors"]}
    assert "template:gate.md" not in failing


def test_empty_template_fails(tmp_path: Path) -> None:
    _scaffold_valid_repo(tmp_path)
    _write(tmp_path / "docs/references/templates/wiki/gate.md", "# x\n")
    result = cov.run_checks(tmp_path)
    failing = {e["name"]: (e.get("detail") or "") for e in result["errors"]}
    assert "template:gate.md" in failing
    assert "empty" in failing["template:gate.md"].lower() or "placeholder" in failing["template:gate.md"].lower()


def test_missing_template_fails_loud(tmp_path: Path) -> None:
    # A configured template that does not exist is reported (never a silent no-op).
    _scaffold_valid_repo(tmp_path)
    (tmp_path / "docs/references/templates/wiki/gate.md").unlink()
    result = cov.run_checks(tmp_path)
    failing = {e["name"]: (e.get("detail") or "") for e in result["errors"]}
    assert "template:gate.md" in failing
    assert "missing" in failing["template:gate.md"].lower()


def test_coverage_matrix_missing_mentions_fails(tmp_path: Path) -> None:
    _scaffold_valid_repo(tmp_path)
    # Matrix with real body, valid frontmatter, but without the required mentions.
    _write(
        tmp_path / "memories/system/methodology-coverage-v5.md",
        PAGE_FM.format(
            page_id="coverage-v5",
            page_type="source_catalog",
            purpose="coverage matrix",
            body="Matrix without any of the required sections, just generic filler text.",
        ),
    )
    result = cov.run_checks(tmp_path)
    assert result["complete"] is False
    failing = {e["name"]: e.get("detail") for e in result["errors"]}
    assert "coverage_matrix_sections" in failing
    detail = failing["coverage_matrix_sections"] or ""
    # "visibility" is satisfied by the frontmatter key itself; the body must
    # still cover agents, the perceptive layer and karma.
    assert "agents" in detail and "perceptive" in detail and "karma" in detail


def test_ingestion_event_missing_quadrants_fails(tmp_path: Path) -> None:
    _scaffold_valid_repo(tmp_path)
    _write(
        tmp_path / "memories/system/ingestion/events/2026-06-09-event.md",
        "# Event without quadrants\n\nmissing the required section\n",
    )
    result = cov.run_checks(tmp_path)
    assert result["complete"] is False
    assert "ingestion_event_quadrants" in {e["name"] for e in result["errors"]}


def test_missing_events_dir_fails_loud(tmp_path: Path) -> None:
    # The configured events directory missing entirely is an error, not a skip.
    import shutil

    _scaffold_valid_repo(tmp_path)
    shutil.rmtree(tmp_path / "memories/system/ingestion/events")
    result = cov.run_checks(tmp_path)
    assert result["complete"] is False
    failing = {e["name"]: (e.get("detail") or "") for e in result["errors"]}
    assert "ingestion_events_dir" in failing
    assert "missing" in failing["ingestion_events_dir"].lower()


def test_operation_dashboard_requires_purpose(tmp_path: Path) -> None:
    _scaffold_valid_repo(tmp_path)
    _write(
        tmp_path / "memories/operations.md",
        "---\npage_id: operations\npage_type: dashboard\n---\n\n" + LONG_BODY + "\n",
    )
    result = cov.run_checks(tmp_path)
    assert result["complete"] is False
    failing = {e["name"]: e.get("detail") for e in result["errors"]}
    assert "operation_dashboard" in failing
    assert "purpose" in (failing["operation_dashboard"] or "")


def test_llm_plan_alone_is_not_proof(tmp_path: Path) -> None:
    """The existence of a -llm-context-plan.json neither creates nor passes any check."""
    _scaffold_valid_repo(tmp_path)
    _write(
        tmp_path / "data/derived/wiki/extraction-events/source-x-llm-context-plan.json",
        '{"chunks": [{"cache_key": "k1"}]}\n',
    )
    result = cov.run_checks(tmp_path)
    # Without a request file, no llm_context_pending check should exist.
    assert not any(c["name"] == "llm_context_pending" for c in result["checks"])
    assert result["complete"] is True


def test_llm_request_without_cache_pending(tmp_path: Path) -> None:
    _scaffold_valid_repo(tmp_path)
    _write(
        tmp_path / "data/derived/wiki/extraction-events/source-x-llm-context-request.json",
        '{"chunks": [{"cache_key": "missing-key"}]}\n',
    )
    result = cov.run_checks(tmp_path)
    assert result["complete"] is False
    pending = [e for e in result["errors"] if e["name"] == "llm_context_pending"]
    assert pending and "llm-cache" in (pending[0].get("detail") or "")


def test_llm_request_with_cache_passes(tmp_path: Path) -> None:
    _scaffold_valid_repo(tmp_path)
    _write(
        tmp_path / "data/derived/wiki/extraction-events/source-x-llm-context-request.json",
        '{"chunks": [{"cache_key": "present-key"}]}\n',
    )
    _write(tmp_path / "data/derived/wiki/llm-cache/present-key.json", '{"ok": true}\n')
    result = cov.run_checks(tmp_path)
    assert result["complete"] is True
    assert any(
        c["name"] == "llm_context_pending" and c["ok"] for c in result["checks"]
    )


def test_no_absolute_paths_in_module() -> None:
    """Ensures portability: no /Users/ path hardcoded in the script."""
    source = Path(cov.__file__).read_text(encoding="utf-8")
    assert "/Users/" not in source
