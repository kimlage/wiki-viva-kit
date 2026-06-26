"""Offline tests for scripts/wiki_operation_compile.py.

scripts/ is not a package, so the module is loaded from its file path via
importlib (same pattern as tests/test_wiki_audit.py). wiki_operation_compile.py
inserts the repo ROOT on sys.path at import time so its `wiki_core` imports
resolve.

The tests build a minimal repo in tmp_path (config + decisions + actions +
context hubs) and exercise build_page(root, config) with an injectable root.
The fixture tree uses the ENGLISH default layout (memories/decisions, ...);
one dedicated test pins the Portuguese layout via wiki.config.yaml to prove
localized-layout compatibility. No network, no writes outside tmp_path.
Production code is not modified.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPILE_PATH = ROOT / "scripts" / "wiki_operation_compile.py"


def _load_module():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location("wiki_operation_compile_under_test", COMPILE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def compile_mod():
    return _load_module()


@pytest.fixture
def config(compile_mod):
    # language=pt: the assertions in this file check the Portuguese rendering.
    # The English rendering has its own test (test_build_page_language_en).
    # The layout stays at the ENGLISH defaults (no paths override): language
    # (strings) and layout (paths) are independent dimensions.
    return compile_mod.WikiConfig(
        repo_id="acme-wiki",
        owner_label="Alex Doe",
        language="pt",
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _decision(page_id: str, context: str, title: str, status: str | None = "pendente") -> str:
    status_line = f"status: {status}\n" if status is not None else ""
    return (
        "---\n"
        f"page_id: {page_id}\n"
        "page_type: decision\n"
        f"context: {context}\n"
        f"{status_line}"
        "visibility: private_self\n"
        "updated_at: 2026-06-08\n"
        "stale_after_days: 180\n"
        "sources_policy: contrato\n"
        "gate: github_pr\n"
        "sensitive_data_policy: private_sensitive_allowed\n"
        "---\n\n"
        f"# Decisao - {title}\n\n"
        "Data: 2026-06-08.\n\nCorpo.\n"
    )


def _action(page_id: str, context: str, title: str, state: str) -> str:
    return (
        "---\n"
        f"page_id: {page_id}\n"
        "page_type: action\n"
        f"context: {context}\n"
        "visibility: private_self\n"
        "updated_at: 2026-06-08\n"
        "stale_after_days: 30\n"
        "sources_policy: contrato\n"
        "gate: github_pr\n"
        "sensitive_data_policy: private_sensitive_allowed\n"
        "---\n\n"
        f"# Acao - {title}\n\n"
        f"Estado: `{state}`.\n\nCorpo.\n"
    )


def _hub(context: str, updated_at: str, stale_after_days: int) -> str:
    return (
        "---\n"
        f"page_id: {context}-index\n"
        "page_type: context_hub\n"
        f"context: {context}\n"
        "visibility: private_self\n"
        f"updated_at: {updated_at}\n"
        f"stale_after_days: {stale_after_days}\n"
        "sources_policy: fontes_vivas_primeiro\n"
        "gate: github_pr\n"
        "sensitive_data_policy: private_sensitive_allowed\n"
        "---\n\n"
        f"# Hub {context}\n"
    )


@pytest.fixture
def minimal_repo(tmp_path: Path) -> Path:
    # English DEFAULT layout (memories/decisions, memories/actions, pending.md):
    # no paths override in the config. The pt layout has its own pinned test
    # (test_build_page_with_pt_pinned_layout).
    mem = tmp_path / "memories"

    # Decisions (one per file) + an index that must be ignored.
    _write(mem / "decisions" / "alfa.md", _decision("decisao-alfa", "sistema", "Aprovar o plano alfa"))
    _write(mem / "decisions" / "beta.md", _decision("decisao-beta", "financeiro", "Escolher piloto beta"))
    _write(
        mem / "decisions" / "index.md",
        "---\npage_id: decisions-index\npage_type: ontology_index\ncontext: sistema\n"
        "visibility: private_self\nupdated_at: 2026-06-08\nstale_after_days: 45\n"
        "sources_policy: x\ngate: github_pr\nsensitive_data_policy: private_sensitive_allowed\n---\n\n# Decisoes\n",
    )

    # Actions + pending queue + index (index/pending must be skipped as actions).
    _write(mem / "actions" / "primeira.md", _action("acao-primeira", "sistema", "Revisar cobertura", "recorrente"))
    _write(mem / "actions" / "segunda.md", _action("acao-segunda", "financeiro", "Conciliar fila", "pendente"))
    _write(
        mem / "actions" / "pending.md",
        "---\npage_id: acoes-pendentes\npage_type: ontology_index\ncontext: sistema\n"
        "visibility: private_self\nupdated_at: 2026-06-08\nstale_after_days: 14\n"
        "sources_policy: x\ngate: github_pr\nsensitive_data_policy: private_sensitive_allowed\n---\n\n"
        "# Acoes pendentes\n\n"
        "- `acao-primeira`\n"
        "- `acao-segunda` (deadline 2026-06-12)\n"
        "- [action-terceira](terceira.md) - linked queue row\n",
    )

    # Context hubs: one fresh, one deliberately stale.
    _write(mem / "sistema-hub" / "index.md", _hub("sistema", dt.date.today().isoformat(), 30))
    _write(mem / "financeiro" / "index.md", _hub("financeiro", "2000-01-01", 1))
    # A non-hub index that must NOT appear in the vitality table.
    _write(
        mem / "ontology" / "index.md",
        "---\npage_id: ontologia-index\npage_type: ontology_index\ncontext: sistema\n"
        "visibility: private_self\nupdated_at: 2026-06-08\nstale_after_days: 45\n"
        "sources_policy: x\ngate: github_pr\nsensitive_data_policy: private_sensitive_allowed\n---\n\n# Ontologia\n",
    )

    return tmp_path


def test_build_page_uses_owner_label_and_repo_id(compile_mod, config, minimal_repo):
    page = compile_mod.build_page(minimal_repo, config)
    assert "# Operacao - acme-wiki" in page
    assert "Alex Doe" in page  # owner_label surfaced (title/labels)
    # The page_id prefix is the stem of the configured operation page
    # (en default: memories/operations.md -> "operations").
    assert "page_id: operations-acme-wiki" in page


def test_build_page_has_no_personal_literals(compile_mod, config, minimal_repo):
    page = compile_mod.build_page(minimal_repo, config)
    for forbidden in ("Kim", "Sargam", "Downloads", "../../../../"):
        assert forbidden not in page, f"unexpected personal literal: {forbidden!r}"


def test_build_page_reflects_decisions_from_sources(compile_mod, config, minimal_repo):
    page = compile_mod.build_page(minimal_repo, config)
    assert "Aprovar o plano alfa" in page
    assert "Escolher piloto beta" in page
    assert "decisions/alfa.md" in page
    # The decisions/index.md is not a decision and must not be listed.
    assert "decisions-index" not in page


def test_build_page_excludes_explicitly_closed_decisions(compile_mod, config, minimal_repo):
    _write(
        minimal_repo / "memories" / "decisions" / "gamma.md",
        (
            "---\n"
            "page_id: decisao-gamma\n"
            "page_type: decision\n"
            "context: sistema\n"
            "status: concluida\n"
            "visibility: private_self\n"
            "updated_at: 2026-06-08\n"
            "stale_after_days: 180\n"
            "sources_policy: contrato\n"
            "gate: github_pr\n"
            "sensitive_data_policy: private_sensitive_allowed\n"
            "---\n\n"
            "# Decisao - Fechar gamma\n\n"
            "Historico: havia pendencia operacional, mas a decisao foi fechada.\n"
        ),
    )

    page = compile_mod.build_page(minimal_repo, config)

    assert "Aprovar o plano alfa" in page
    assert "Escolher piloto beta" in page
    assert "Fechar gamma" not in page


def test_build_page_excludes_statusless_structural_decisions(compile_mod, config, minimal_repo):
    _write(
        minimal_repo / "memories" / "decisions" / "structural.md",
        _decision("decisao-structural", "sistema", "Convencao estrutural", status=None),
    )

    page = compile_mod.build_page(minimal_repo, config)

    assert "Aprovar o plano alfa" in page
    assert "Escolher piloto beta" in page
    assert "Convencao estrutural" not in page


def test_build_page_reflects_actions_from_sources(compile_mod, config, minimal_repo):
    page = compile_mod.build_page(minimal_repo, config)
    assert "Revisar cobertura" in page
    assert "Conciliar fila" in page
    assert "[Revisar cobertura](actions/primeira.md)" in page
    assert "[Conciliar fila](actions/segunda.md)" in page
    assert "recorrente" in page
    assert "pendente" in page
    assert "actions/primeira.md" in page
    # The owner actions header is parameterized on owner_label.
    assert "## Acoes do dono (Alex Doe)" in page


def test_build_page_extracts_state_before_inline_detail(compile_mod, config, minimal_repo):
    _write(
        minimal_repo / "memories" / "actions" / "terceira.md",
        (
            "---\n"
            "page_id: acao-terceira\n"
            "page_type: action\n"
            "context: sistema\n"
            "visibility: private_self\n"
            "updated_at: 2026-06-08\n"
            "stale_after_days: 30\n"
            "sources_policy: contrato\n"
            "gate: github_pr\n"
            "sensitive_data_policy: private_sensitive_allowed\n"
            "---\n\n"
            "# Acao - Acompanhar bloqueio\n\n"
            "Estado: `pendente` — detalhe operacional que nao deve virar estado.\n"
        ),
    )
    page = compile_mod.build_page(minimal_repo, config)
    assert "| [Acompanhar bloqueio](actions/terceira.md) | sistema | pendente |" in page
    assert "detalhe operacional que nao deve virar estado" not in page


def test_build_page_lists_pending_action_ids(compile_mod, config, minimal_repo):
    page = compile_mod.build_page(minimal_repo, config)
    assert "`acao-primeira`" in page
    assert "`acao-segunda`" in page
    assert "`action-terceira`" in page
    # The queue intro links the CONFIGURED pending file (placeholder filled
    # relative to the cockpit page's directory), not a hardcoded pt path.
    assert "[actions/pending.md](actions/pending.md)" in page
    assert "acoes/pendentes.md" not in page


def test_build_page_derives_context_vitality(compile_mod, config, minimal_repo):
    page = compile_mod.build_page(minimal_repo, config)
    # Fresh hub (updated today) -> fresca; stale hub (updated_at 2000) -> stale.
    assert "fresca" in page
    assert "stale" in page
    # Only context_hub indexes appear; the ontology index is excluded.
    assert "ontology/index.md" not in page
    # The stale context is surfaced in the alerts section.
    assert "Contextos stale para revisar: financeiro." in page  # generated pt output, kept verbatim


def _source_page(page_id: str, *, ingested: bool = True) -> str:
    state = "ingested" if ingested else "pending"
    return (
        "---\n"
        f"page_id: {page_id}\n"
        "page_type: source\n"
        "context: sistema\n"
        "visibility: private_self\n"
        "updated_at: 2026-06-08\n"
        "stale_after_days: 180\n"
        "sources_policy: contrato\n"
        "gate: github_pr\n"
        "sensitive_data_policy: private_sensitive_allowed\n"
        f"ingestion_state: {state}\n"
        "last_ingested_at: 2026-06-08\n"
        "---\n\n"
        f"# Source {page_id}\n"
    )


def _event_page(event_id: str, source_ref: str, *, closed: bool) -> str:
    # Block-list frontmatter (the "- item" shape parse_frontmatter_flat turns into
    # a list[str]); inline "[a]" would flatten to the literal string "[a]".
    consolidated = (
        "consolidated_into:\n  - memories/sistema/index.md\n" if closed else ""
    )
    return (
        "---\n"
        f"page_id: {event_id}\n"
        "page_type: ingestion_event\n"
        f"event_id: {event_id}\n"
        "context: sistema\n"
        "visibility: private_self\n"
        "updated_at: 2026-06-08\n"
        "stale_after_days: 180\n"
        "sources_policy: contrato\n"
        "gate: github_pr\n"
        "sensitive_data_policy: private_sensitive_allowed\n"
        "source_refs:\n"
        f"  - {source_ref}\n"
        f"{consolidated}"
        "---\n\n"
        f"# Ingestion event {event_id}\n\n"
        "## Claims candidates\n\n- claim one\n- claim two\n"
    )


def test_build_page_closure_section_empty_without_events(compile_mod, config, minimal_repo):
    # minimal_repo has no ingestion events: the closure section shows an honest
    # empty placeholder (not a crash), and is a DETERMINISTIC section in --check.
    page = compile_mod.build_page(minimal_repo, config)
    assert "## Fechamento da ingestao" in page
    assert "Sem eventos de ingestao registrados ainda." in page
    view = compile_mod.stable_cockpit_view(page)
    assert "## Fechamento da ingestao" in view  # deterministic -> stays in --check


def test_build_page_closure_section_reflects_closed_ingestion(compile_mod, config, minimal_repo):
    sources = minimal_repo / "memories" / "sources"
    events = minimal_repo / "memories" / "system" / "ingestion" / "events"
    _write(sources / "fonte-a.md", _source_page("fonte-a"))
    _write(sources / "fonte-b.md", _source_page("fonte-b"))
    _write(events / "ev-a.md", _event_page("ev-a", "fonte-a", closed=True))
    _write(events / "ev-b.md", _event_page("ev-b", "fonte-b", closed=False))
    page = compile_mod.build_page(minimal_repo, config)
    # 2 events, 1 closed; 2 ingested sources, 1 with a closed event, 1 gap.
    assert "| Eventos de ingestao fechados | 1/2 |" in page
    assert "| Fontes ingeridas com evento fechado | 1/2 |" in page
    assert "| Fontes ingeridas SEM evento fechado (0 = saudavel) | 1 |" in page
    # The closure section is deterministic content -> drift is caught by --check.
    view = compile_mod.stable_cockpit_view(page)
    assert "Fontes ingeridas SEM evento fechado" in view
    # Recompiling without changing the tree yields an identical stable view.
    assert compile_mod.stable_cockpit_view(
        compile_mod.build_page(minimal_repo, config)
    ) == view


def test_build_page_empty_repo_writes_honest_placeholders(compile_mod, config, tmp_path):
    (tmp_path / "memories").mkdir()
    page = compile_mod.build_page(tmp_path, config)
    assert "Sem decisoes pendentes registradas." in page
    assert "Sem acoes registradas." in page
    assert "Sem acoes pendentes registradas." in page
    assert "Sem hubs de contexto registrados." in page
    # Still portable / parameterized even when empty.
    assert "# Operacao - acme-wiki" in page
    assert "Kim" not in page and "Sargam" not in page


def test_build_page_frontmatter_satisfies_auditor_contract(compile_mod, config, minimal_repo):
    page = compile_mod.build_page(minimal_repo, config)
    head = page.split("---", 2)[1]
    assert "page_type: dashboard" in head
    assert "stale_after_days: 1" in head
    assert f"updated_at: {dt.date.today().isoformat()}" in head
    assert "visibility: private_self" in head
    assert "gate: github_pr" in head
    assert "sensitive_data_policy: private_sensitive_allowed" in head
    assert "purpose: cockpit de retomada operacional diaria da wiki" in head
    assert "moc_parent: memories/index.md" in head
    # context comes from config.default_context (en default: "system").
    assert "context: system" in head


def test_frontmatter_has_provenance(compile_mod, config, minimal_repo):
    head = compile_mod.build_page(minimal_repo, config).split("---", 2)[1]
    assert "generated_from_commit:" in head
    assert "generated_from_branch:" in head


def test_branch_state_line_is_not_always_open_pr(compile_mod):
    pt = compile_mod._cs("pt")
    en = compile_mod._cs("en")
    assert "Estado no momento da compilacao: `main` aprovado" in compile_mod._branch_state_line("main", pt)
    proposal_pt = compile_mod._branch_state_line("wiki/topic", pt)
    assert "branch de proposta `wiki/*`" in proposal_pt
    assert "proveniencia historica" in proposal_pt
    assert "abrir ou verificar o PR antes de publicar ou concluir" not in proposal_pt
    assert "branch `feature/topic`" in compile_mod._branch_state_line("feature/topic", pt)
    assert "Compile-time state: approved `main`" in compile_mod._branch_state_line("main", en)
    proposal_en = compile_mod._branch_state_line("wiki/topic", en)
    assert "proposal branch `wiki/*`" in proposal_en
    assert "historical provenance" in proposal_en


def test_checked_sections_detect_decision_drift(compile_mod, config, minimal_repo):
    page = compile_mod.build_page(minimal_repo, config)
    sections = compile_mod.checked_sections(page, config.language)
    # Only the deterministic sections (decisions/actions) enter --check; nothing from git/date.
    assert any(h.startswith("Decisoes pendentes") for h in sections)
    assert any(h.startswith("Acoes do dono") for h in sections)
    # Recompiling without changing the memory tree produces identical sections
    # (-> --check passes).
    assert compile_mod.checked_sections(
        compile_mod.build_page(minimal_repo, config), config.language
    ) == sections
    # Removing a decision changes the checked sections (-> --check fails).
    (minimal_repo / "memories" / "decisions" / "alfa.md").unlink()
    drifted = compile_mod.checked_sections(
        compile_mod.build_page(minimal_repo, config), config.language
    )
    assert drifted != sections


def test_checked_sections_work_in_english(compile_mod, minimal_repo):
    # Regression: the prefixes used to be a fixed pt tuple, so the per-section
    # drift check silently matched NOTHING when language=en. They now come from
    # the active language's string table.
    en = compile_mod.WikiConfig(repo_id="acme-wiki", owner_label="Owner", language="en")
    page = compile_mod.build_page(minimal_repo, en)
    sections = compile_mod.checked_sections(page, en.language)
    assert any(h.startswith("Pending decisions") for h in sections)
    assert any(h.startswith("Owner actions") for h in sections)
    assert any(h.startswith("Pending action queue") for h in sections)
    assert compile_mod.checked_section_prefixes("en") == (
        "Pending decisions", "Owner actions", "Pending action queue",
    )
    assert compile_mod.checked_section_prefixes("pt") == (
        "Decisoes pendentes", "Acoes do dono", "Fila de acoes pendentes",
    )


def test_stable_view_covers_whole_body_excludes_volatile(compile_mod, config, minimal_repo):
    page = compile_mod.build_page(minimal_repo, config)
    view = compile_mod.stable_cockpit_view(page)
    # Covers the whole deterministic body, not just decisions/actions.
    assert "## Decisoes pendentes" in view
    assert "## Acoes do dono" in view or "Acoes do dono" in view
    assert "## Links de retomada" in view
    assert "## Alertas" in view
    # Excludes what is volatile (date, git state, karma, commit provenance).
    view_lines = view.splitlines()
    assert not any(l.startswith("generated_from_commit:") for l in view_lines)
    assert not any(l.startswith("generated_from_branch:") for l in view_lines)
    assert not any(l.startswith("updated_at:") for l in view_lines)
    assert "## Karma e vitalidade" not in view
    assert "## Vitalidade dos contextos" not in view
    assert "Compilado de:" not in view
    # Recompiling without changing memorias -> identical stable view (--check passes).
    assert compile_mod.stable_cockpit_view(compile_mod.build_page(minimal_repo, config)) == view


def test_stable_view_detects_drift_outside_decisoes(compile_mod, config, minimal_repo):
    # A change in a deterministic part outside decisions/actions changes the stable
    # view (the 3-section check missed it; the widened one catches it).
    page = compile_mod.build_page(minimal_repo, config)
    view = compile_mod.stable_cockpit_view(page)
    tampered = page.replace("## Links de retomada", "## Links de retomada (editado)")
    assert compile_mod.stable_cockpit_view(tampered) != view


def test_stable_view_ignores_commit_and_date_churn(compile_mod, config, minimal_repo):
    # Swapping generated_from_commit / updated_at / "Compilado de" must NOT change the
    # stable view (they are volatile) -> avoids a false positive in --check.
    page = compile_mod.build_page(minimal_repo, config)
    view = compile_mod.stable_cockpit_view(page)
    churned = (
        page.replace("generated_from_commit: ", "generated_from_commit: deadbeef")
        if "generated_from_commit: " in page else page
    )
    import re as _re
    churned = _re.sub(r"generated_from_commit: \S+", "generated_from_commit: deadbeefcafe", churned)
    churned = _re.sub(r"generated_from_branch: \S+", "generated_from_branch: outra-branch", churned)
    assert compile_mod.stable_cockpit_view(churned) == view


def test_build_page_renders_karma_when_events_exist(compile_mod, config, minimal_repo):
    from wiki_core.score import record_event

    derived = minimal_repo / "data/derived/wiki"
    derived.mkdir(parents=True, exist_ok=True)
    record_event(derived / "score-events.jsonl", event_type="ingestar_fonte_valida",
                 actor="owner", context="sistema", ts="2026-06-09")
    page = compile_mod.build_page(minimal_repo, config)
    assert "## Karma e vitalidade (gamificacao)" in page
    assert "Eventos de score: 1" in page
    assert "confiabilidade" in page  # dimension of the ingestar_fonte_valida event


def test_build_page_karma_empty_when_no_events(compile_mod, config, minimal_repo):
    page = compile_mod.build_page(minimal_repo, config)
    assert "Sem eventos de score registrados" in page
    # the karma section does NOT enter --check (depends on date/score, not on content)
    assert "Karma e vitalidade" not in "".join(compile_mod.checked_sections(page, config.language))


def test_build_page_language_en(compile_mod, minimal_repo):
    # language=en generates the cockpit in English from the same memory tree.
    en = compile_mod.WikiConfig(repo_id="acme-wiki", owner_label="Owner", language="en")
    page = compile_mod.build_page(minimal_repo, en)
    assert "# Operations - acme-wiki" in page
    assert "## Pending decisions" in page
    assert "## Owner actions (Owner)" in page
    assert "## Resume links" in page
    assert "| Decision | Context | Source |" in page
    # Footer links derive from the configured layout (en defaults here).
    assert "- Wiki: [memories/index.md](index.md)" in page
    assert "- Log: [memories/system/log.md](system/log.md)" in page
    assert "- Operational pass: [memories/system/operational-pass.md](system/operational-pass.md)" in page
    assert "- Coverage: [memories/system/wiki-coverage.md](system/wiki-coverage.md)" in page
    assert (
        "- Methodology coverage: "
        "[memories/system/methodology-coverage-v5.md](system/methodology-coverage-v5.md)"
    ) in page
    # no Portuguese (strings or layout paths) in the generated body
    assert "## Decisoes pendentes" not in page
    assert "Atualizado em:" not in page
    assert "memorias/" not in page


def test_stable_view_language_robust(compile_mod, minimal_repo):
    # The stable view excludes the volatile sections in both pt and en, so that
    # --check works regardless of the language.
    en = compile_mod.WikiConfig(repo_id="acme-wiki", owner_label="Owner", language="en")
    view = compile_mod.stable_cockpit_view(compile_mod.build_page(minimal_repo, en))
    assert "## Context vitality" not in view
    assert "## Karma and vitality" not in view
    assert "## Pending decisions" in view  # deterministic content stays


def test_action_without_state_uses_language_fallback(compile_mod, config, minimal_repo):
    # An action page with no "Estado:"/"State:" line renders the language-table
    # fallback (COCKPIT_STRINGS["no_state"]), not a hardcoded pt literal.
    _write(
        minimal_repo / "memories" / "actions" / "terceira.md",
        "---\npage_id: acao-terceira\npage_type: action\ncontext: sistema\n"
        "visibility: private_self\nupdated_at: 2026-06-08\nstale_after_days: 30\n"
        "sources_policy: contrato\ngate: github_pr\nsensitive_data_policy: private_sensitive_allowed\n---\n\n"
        "# Acao - Sem linha de estado\n\nCorpo.\n",
    )
    page_pt = compile_mod.build_page(minimal_repo, config)
    assert "| [Sem linha de estado](actions/terceira.md) | sistema | sem estado |" in page_pt
    en = compile_mod.WikiConfig(repo_id="acme-wiki", owner_label="Owner", language="en")
    page_en = compile_mod.build_page(minimal_repo, en)
    assert "| [Sem linha de estado](actions/terceira.md) | sistema | no state |" in page_en
    assert "sem estado" not in page_en


def test_state_parser_accepts_estado_and_state(compile_mod, config, minimal_repo):
    # English-authored action pages ("State: `...`") are parsed like Portuguese
    # ones ("Estado: `...`"); the bilingual STATE_RE covers both.
    _write(
        minimal_repo / "memories" / "actions" / "english.md",
        "---\npage_id: acao-english\npage_type: action\ncontext: sistema\n"
        "visibility: private_self\nupdated_at: 2026-06-08\nstale_after_days: 30\n"
        "sources_policy: contrato\ngate: github_pr\nsensitive_data_policy: private_sensitive_allowed\n---\n\n"
        "# Action - Review backlog\n\nState: `recurring`.\n\nBody.\n",
    )
    assert compile_mod.first_state("Estado: `pendente`.") == "pendente"
    assert compile_mod.first_state("State: `recurring`.") == "recurring"
    page = compile_mod.build_page(minimal_repo, config)
    assert "| [Review backlog](actions/english.md) | sistema | recurring |" in page
    # The pt pages of the fixture keep working side by side.
    assert "| [Revisar cobertura](actions/primeira.md) | sistema | recorrente |" in page


def test_clean_title_strips_bilingual_prefixes(compile_mod, config, minimal_repo):
    for raw, expected in (
        ("Decisao - Aprovar plano", "Aprovar plano"),
        ("Decision - Approve plan", "Approve plan"),
        ("Acao - Revisar fila", "Revisar fila"),
        ("Action - Review queue", "Review queue"),
        ("Titulo sem prefixo", "Titulo sem prefixo"),
    ):
        assert compile_mod._clean_title(raw) == expected
    # End to end: an en-prefixed decision title is listed without the prefix.
    _write(
        minimal_repo / "memories" / "decisions" / "gamma.md",
        "---\npage_id: decisao-gamma\npage_type: decision\ncontext: sistema\n"
        "status: pendente\nvisibility: private_self\nupdated_at: 2026-06-08\nstale_after_days: 180\n"
        "sources_policy: contrato\ngate: github_pr\nsensitive_data_policy: private_sensitive_allowed\n---\n\n"
        "# Decision - Adopt the kit\n\nBody.\n",
    )
    page = compile_mod.build_page(minimal_repo, config)
    assert "| [Adopt the kit](decisions/gamma.md) | sistema |" in page
    assert "Decision - Adopt the kit" not in page


def test_build_page_with_pt_pinned_layout(compile_mod, tmp_path):
    # Localized-layout compatibility: a repo that pins the Portuguese layout in
    # wiki.config.yaml keeps generating its localized cockpit (page_id prefix,
    # default context, queue/footer links) exactly as before the en defaults.
    (tmp_path / "wiki.config.yaml").write_text(
        "repo_id: acme-wiki\n"
        "owner_label: Alex Doe\n"
        "language: pt\n"
        "default_context: sistema\n"
        "paths:\n"
        "  memory_root: memorias\n"
        "  system_dirname: sistema\n"
        "  decisions_dirname: decisoes\n"
        "  actions_dirname: acoes\n"
        "  pending_actions_filename: pendentes.md\n"
        "  operation_page: memorias/operacao.md\n"
        "  operational_pass_page: memorias/sistema/passagem-fontes-acoes-contextos.md\n"
        "  wiki_coverage_page: memorias/sistema/cobertura-wiki.md\n"
        "coverage:\n"
        "  coverage_matrix_page: memorias/sistema/cobertura-metodologia-v5.md\n",
        encoding="utf-8",
    )
    config = compile_mod.load_config(tmp_path)
    mem = tmp_path / "memorias"
    _write(mem / "decisoes" / "alfa.md", _decision("decisao-alfa", "sistema", "Aprovar o plano alfa"))
    _write(mem / "acoes" / "primeira.md", _action("acao-primeira", "sistema", "Revisar cobertura", "recorrente"))
    _write(
        mem / "acoes" / "pendentes.md",
        "---\npage_id: acoes-pendentes\npage_type: ontology_index\ncontext: sistema\n"
        "visibility: private_self\nupdated_at: 2026-06-08\nstale_after_days: 14\n"
        "sources_policy: x\ngate: github_pr\nsensitive_data_policy: private_sensitive_allowed\n---\n\n"
        "# Acoes pendentes\n\n- `acao-primeira`\n",
    )
    page = compile_mod.build_page(tmp_path, config)
    head = page.split("---", 2)[1]
    assert "page_id: operacao-acme-wiki" in head
    assert "context: sistema" in head
    assert "decisoes/alfa.md" in page
    assert "acoes/primeira.md" in page
    assert "[acoes/pendentes.md](acoes/pendentes.md):" in page
    assert "- Wiki: [memorias/index.md](index.md)" in page
    assert "- Log: [memorias/sistema/log.md](sistema/log.md)" in page
    assert (
        "- Passagem operacional: "
        "[memorias/sistema/passagem-fontes-acoes-contextos.md](sistema/passagem-fontes-acoes-contextos.md)"
    ) in page
    assert "- Cobertura: [memorias/sistema/cobertura-wiki.md](sistema/cobertura-wiki.md)" in page
    assert (
        "- Cobertura metodologia: "
        "[memorias/sistema/cobertura-metodologia-v5.md](sistema/cobertura-metodologia-v5.md)"
    ) in page
    # No English layout names leak into the pt-pinned cockpit body.
    assert "memories/" not in page
