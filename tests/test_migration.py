from __future__ import annotations

import datetime as dt
from pathlib import Path

from wiki_core.config import WikiConfig
from wiki_core.migration import (
    frontmatter_block_for_suggestion,
    infer_context,
    infer_page_type,
    migration_inventory,
    suggest_frontmatter_for_legacy_page,
)


def test_infer_context_uses_localized_memory_root_and_contexts() -> None:
    config = WikiConfig(
        contexts=("financeiro", "documentos"),
        default_context="sistema",
        paths={**WikiConfig().paths, "memory_root": "memorias", "system_dirname": "sistema"},
    )

    assert infer_context("memorias/financeiro/contas.md", config) == "financeiro"
    assert infer_context("memorias/sistema/log.md", config) == "sistema"
    assert infer_context("docs/referencias/x.md", config) == "sistema"


def test_suggest_frontmatter_for_legacy_page_is_deterministic(tmp_path: Path) -> None:
    (tmp_path / "memorias/financeiro").mkdir(parents=True)
    rel = "memorias/financeiro/contas-e-cartoes.md"
    (tmp_path / rel).write_text("# Contas e cartoes\n\nBody.\n", encoding="utf-8")
    config = WikiConfig(
        contexts=("financeiro",),
        default_context="sistema",
        paths={**WikiConfig().paths, "memory_root": "memorias"},
        freshness={"default": 30, "financeiro": 14},
    )

    suggestion = suggest_frontmatter_for_legacy_page(
        tmp_path,
        rel,
        config,
        today=dt.date(2026, 6, 12),
    )

    assert suggestion is not None
    assert suggestion.context == "financeiro"
    assert suggestion.page_type == "context_note"
    assert suggestion.page_id == "context-note-contas-e-cartoes"
    assert suggestion.updated_at == "2026-06-12"
    assert suggestion.stale_after_days == "14"


def test_migration_inventory_skips_pages_with_frontmatter(tmp_path: Path) -> None:
    (tmp_path / "memories/example").mkdir(parents=True)
    (tmp_path / "memories/example/legacy.md").write_text("# Legacy\n\nBody.\n", encoding="utf-8")
    (tmp_path / "memories/example/typed.md").write_text(
        "---\npage_id: typed\npage_type: context_note\n---\n\n# Typed\n",
        encoding="utf-8",
    )
    config = WikiConfig(contexts=("example",))

    rows = migration_inventory(tmp_path, config, today=dt.date(2026, 6, 12))

    assert [row.rel for row in rows] == ["memories/example/legacy.md"]


def test_infer_page_type_uses_semantic_dirs_before_fallback() -> None:
    config = WikiConfig(paths={**WikiConfig().paths, "memory_root": "memorias"})

    assert infer_page_type("memorias/financeiro/regras/regras-de-consolidacao.md", config)[0] == (
        "operational_rule"
    )
    assert infer_page_type("memorias/financeiro/contextos/emprestimo-mae.md", config)[0] == (
        "context_note"
    )
    assert infer_page_type("memorias/financeiro/analises/resumo.md", config)[0] == "insight"


def test_infer_page_type_does_not_treat_year_prefix_as_date() -> None:
    config = WikiConfig(paths={**WikiConfig().paths, "memory_root": "memorias"})

    assert infer_page_type("memorias/financeiro/provedor/conciliacao/2026-exemplo-fila.md", config)[0] == (
        "context_note"
    )
    assert infer_page_type("memorias/financeiro/provedor/conciliacao/2026-06-05-sync.md", config)[0] == (
        "monthly_closing"
    )


def test_frontmatter_block_for_suggestion_uses_suggestion_date(tmp_path: Path) -> None:
    (tmp_path / "memories/example").mkdir(parents=True)
    rel = "memories/example/legacy.md"
    (tmp_path / rel).write_text("# Legacy\n\nBody.\n", encoding="utf-8")
    suggestion = suggest_frontmatter_for_legacy_page(
        tmp_path,
        rel,
        WikiConfig(contexts=("example",)),
        today=dt.date(2026, 6, 12),
    )
    assert suggestion is not None

    block = frontmatter_block_for_suggestion(
        suggestion,
        visibility="private_self",
        gate="github_pr",
    )

    assert "updated_at: '2026-06-12'" in block
    assert "visibility: private_self" in block
    assert "gate: github_pr" in block
