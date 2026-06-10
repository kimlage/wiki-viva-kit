"""Tests for the presence AND content verifier of the living wiki methodology.

They build a minimal repo in tmp_path and exercise run_checks() to ensure that:
- an empty file fails;
- a file without frontmatter/page_id fails;
- a matrix without the 4 mentions fails;
- everything present and valid -> complete: true.
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
context: sistema
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

# Corpo

{body}
"""

EVENT_BODY = """# Evento

## Quadrantes

| Quadrante | Conteudo |
| --- | --- |
| Interior individual | algo real e suficientemente longo aqui |
"""

LONG_BODY = "Corpo de pagina com conteudo real e suficientemente longo para passar do limite minimo de bytes."

PERCEPTIVE_PAGE = """---
page_id: {page_id}
page_type: {page_type}
context: sistema
visibility: private_self
updated_at: 2026-06-09
status: active
status_epistemologico: percepcao
purpose: pagina perceptiva real de teste
perception_policy:
  layer: perceptiva
  is_canonical_truth: false
---

{body}
"""

COVERAGE_BODY = (
    "Matriz cobrindo visibilidade das paginas, papeis de agentes, leitura "
    "perceptiva integral e o sistema de karma/gamificacao."
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _scaffold_valid_repo(root: Path) -> None:
    """Creates a minimal repo where ALL content checks pass."""
    # Memory pages.
    _write(
        root / "memorias/fontes/metodologia-wiki-viva-v5.md",
        PAGE_FM.format(
            page_id="fonte-v5", page_type="source", purpose="fonte metodologica", body=LONG_BODY
        ),
    )
    _write(
        root / "memorias/sistema/cobertura-metodologia-v5.md",
        PAGE_FM.format(
            page_id="cobertura-v5",
            page_type="source_catalog",
            purpose="matriz de cobertura",
            body=COVERAGE_BODY,
        ),
    )
    _write(
        root / "memorias/operacao.md",
        PAGE_FM.format(
            page_id="operacao", page_type="dashboard", purpose="cockpit diario", body=LONG_BODY
        ),
    )

    # Templates (mix of raw frontmatter and wrapped in ```yaml).
    _write(
        root / "docs/referencias/templates/wiki/ingestao-evento.md",
        TEMPLATE_FENCED.format(page_id="tpl-evento", page_type="source_catalog", body=LONG_BODY),
    )
    _write(
        root / "docs/referencias/templates/wiki/operacao.md",
        TEMPLATE_FENCED.format(page_id="tpl-operacao", page_type="dashboard", body=LONG_BODY),
    )
    _write(
        root / "docs/referencias/templates/wiki/dashboard-vitalidade.md",
        TEMPLATE_FENCED.format(page_id="tpl-vitalidade", page_type="dashboard", body=LONG_BODY),
    )
    _write(
        root / "docs/referencias/templates/wiki/subagent-brief.md",
        TEMPLATE_RAW.format(page_id="tpl-subagent", page_type="operational_template", body=LONG_BODY),
    )
    _write(
        root / "docs/referencias/templates/wiki/gate.md",
        TEMPLATE_FENCED.format(page_id="tpl-gate", page_type="operational_rule", body=LONG_BODY),
    )

    # Support files (only need to exist).
    for rel in cov.REQUIRED_SUPPORT_FILES.values():
        _write(root / rel, "conteudo de suporte\n")
    # Real config: declares the scaffold's language (pt content -> pt mentions).
    _write(root / "wiki.config.yaml", "repo_id: scaffold\nlanguage: pt\n")

    # Perceptive layer: real USE requires >=1 real journal and >=1 real map (not template),
    # with the perception_policy marker in the frontmatter.
    _write(
        root / "memorias/sistema/percepcao/journal-exemplo.md",
        PERCEPTIVE_PAGE.format(
            page_id="journal-exemplo", page_type="journal_entry", body=LONG_BODY
        ),
    )
    _write(
        root / "memorias/sistema/percepcao/mapa-exemplo.md",
        PERCEPTIVE_PAGE.format(
            page_id="mapa-exemplo", page_type="relationship_map", body=LONG_BODY
        ),
    )

    # Ingestion event with a Quadrants section + ignored README.
    _write(root / "memorias/sistema/ingestao/eventos/2026-06-09-evento.md", EVENT_BODY)
    _write(root / "memorias/sistema/ingestao/eventos/README.md", "# README\nsem quadrantes\n")

    # Derived manifest for source_id discovery.
    _write(
        root / "data/derived/wiki/source-manifests/source-exemplo-abc123.json",
        '{"source_id": "source-exemplo-abc123"}\n',
    )


def test_valid_repo_is_complete(tmp_path: Path) -> None:
    _scaffold_valid_repo(tmp_path)
    result = cov.run_checks(tmp_path)
    failing = [e["name"] for e in result["errors"]]
    assert result["complete"] is True, f"unexpected failing checks: {failing}"
    assert result["errors"] == []


def test_perceptive_usage_required(tmp_path: Path) -> None:
    # Without real perceptive pages, the coverage fails (requires USE, not a template).
    _scaffold_valid_repo(tmp_path)
    (tmp_path / "memorias/sistema/percepcao/journal-exemplo.md").unlink()
    (tmp_path / "memorias/sistema/percepcao/mapa-exemplo.md").unlink()
    result = cov.run_checks(tmp_path)
    failing = {e["name"] for e in result["errors"]}
    assert result["complete"] is False
    assert "perceptive_journal_real" in failing
    assert "perceptive_map_real" in failing


def test_perceptive_template_does_not_count(tmp_path: Path) -> None:
    # A perceptive page with status=template does NOT count as real use.
    _scaffold_valid_repo(tmp_path)
    (tmp_path / "memorias/sistema/percepcao/journal-exemplo.md").unlink()
    _write(
        tmp_path / "memorias/sistema/percepcao/journal-template.md",
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
    (tmp_path / "memorias/fontes/metodologia-wiki-viva-v5.md").write_text(
        "---\npage_id: fonte-v5\n---\n", encoding="utf-8"
    )
    result = cov.run_checks(tmp_path)
    assert result["complete"] is False
    failing = {e["name"]: e.get("detail") for e in result["errors"]}
    assert "source_page" in failing
    assert "placeholder" in (failing["source_page"] or "")


def test_zero_byte_file_fails(tmp_path: Path) -> None:
    _scaffold_valid_repo(tmp_path)
    (tmp_path / "memorias/operacao.md").write_text("", encoding="utf-8")
    result = cov.run_checks(tmp_path)
    assert result["complete"] is False
    assert "operation_page" in {e["name"] for e in result["errors"]}


def test_missing_frontmatter_page_id_fails(tmp_path: Path) -> None:
    _scaffold_valid_repo(tmp_path)
    # Body present, but without a frontmatter block / page_id.
    (tmp_path / "memorias/fontes/metodologia-wiki-viva-v5.md").write_text(
        "# Pagina sem frontmatter\n\n" + LONG_BODY + "\n", encoding="utf-8"
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
        tmp_path / "docs/referencias/templates/wiki/gate.md",
        "---\npage_id: tpl-gate\n---\n\n# Corpo\n\n" + LONG_BODY + "\n",
    )
    result = cov.run_checks(tmp_path)
    failing = {e["name"] for e in result["errors"]}
    assert "gate_template" not in failing


def test_empty_template_fails(tmp_path: Path) -> None:
    _scaffold_valid_repo(tmp_path)
    _write(tmp_path / "docs/referencias/templates/wiki/gate.md", "# x\n")
    result = cov.run_checks(tmp_path)
    failing = {e["name"]: (e.get("detail") or "") for e in result["errors"]}
    assert "gate_template" in failing
    assert "empty" in failing["gate_template"].lower() or "placeholder" in failing["gate_template"].lower()


def test_coverage_matrix_missing_mentions_fails(tmp_path: Path) -> None:
    _scaffold_valid_repo(tmp_path)
    # Matrix with real body, valid frontmatter, but without the 4 mentions.
    _write(
        tmp_path / "memorias/sistema/cobertura-metodologia-v5.md",
        PAGE_FM.format(
            page_id="cobertura-v5",
            page_type="source_catalog",
            purpose="matriz de cobertura",
            body="Matriz sem nenhuma das mencoes obrigatorias, apenas texto generico.",
        ),
    )
    result = cov.run_checks(tmp_path)
    assert result["complete"] is False
    failing = {e["name"]: e.get("detail") for e in result["errors"]}
    assert "coverage_matrix_sections" in failing
    detail = failing["coverage_matrix_sections"] or ""
    assert "visibilidade" in detail and "perceptiva" in detail and "karma" in detail


def test_ingestion_event_missing_quadrants_fails(tmp_path: Path) -> None:
    _scaffold_valid_repo(tmp_path)
    _write(
        tmp_path / "memorias/sistema/ingestao/eventos/2026-06-09-evento.md",
        "# Evento sem quadrantes\n\nsem a secao exigida\n",
    )
    result = cov.run_checks(tmp_path)
    assert result["complete"] is False
    assert "ingestion_event_quadrants" in {e["name"] for e in result["errors"]}


def test_operation_dashboard_requires_purpose(tmp_path: Path) -> None:
    _scaffold_valid_repo(tmp_path)
    _write(
        tmp_path / "memorias/operacao.md",
        "---\npage_id: operacao\npage_type: dashboard\n---\n\n" + LONG_BODY + "\n",
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
