"""Offline tests for scripts/wiki_operation_compile.py.

scripts/ is not a package, so the module is loaded from its file path via
importlib (same pattern as tests/test_wiki_audit.py). wiki_operation_compile.py
inserts the repo ROOT on sys.path at import time so its `wiki_core` imports
resolve.

The tests build a minimal repo in tmp_path (config + decisions + actions +
context hubs) and exercise build_page(root, config) with an injectable root.
No network, no writes outside tmp_path. Production code is not modified.
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
    return compile_mod.WikiConfig(
        repo_id="acme-wiki",
        owner_label="Alex Doe",
        language="pt",
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _decision(page_id: str, context: str, title: str) -> str:
    return (
        "---\n"
        f"page_id: {page_id}\n"
        "page_type: decision\n"
        f"context: {context}\n"
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
    mem = tmp_path / "memorias"

    # Decisions (one per file) + an index that must be ignored.
    _write(mem / "decisoes" / "alfa.md", _decision("decisao-alfa", "sistema", "Aprovar o plano alfa"))
    _write(mem / "decisoes" / "beta.md", _decision("decisao-beta", "financeiro", "Escolher piloto beta"))
    _write(
        mem / "decisoes" / "index.md",
        "---\npage_id: decisoes-index\npage_type: ontology_index\ncontext: sistema\n"
        "visibility: private_self\nupdated_at: 2026-06-08\nstale_after_days: 45\n"
        "sources_policy: x\ngate: github_pr\nsensitive_data_policy: private_sensitive_allowed\n---\n\n# Decisoes\n",
    )

    # Actions + pendentes list + index (index/pendentes must be skipped as actions).
    _write(mem / "acoes" / "primeira.md", _action("acao-primeira", "sistema", "Revisar cobertura", "recorrente"))
    _write(mem / "acoes" / "segunda.md", _action("acao-segunda", "financeiro", "Conciliar fila", "pendente"))
    _write(
        mem / "acoes" / "pendentes.md",
        "---\npage_id: acoes-pendentes\npage_type: ontology_index\ncontext: sistema\n"
        "visibility: private_self\nupdated_at: 2026-06-08\nstale_after_days: 14\n"
        "sources_policy: x\ngate: github_pr\nsensitive_data_policy: private_sensitive_allowed\n---\n\n"
        "# Acoes pendentes\n\n- `acao-primeira`\n- `acao-segunda`\n",
    )

    # Context hubs: one fresh, one deliberately stale.
    _write(mem / "sistema-hub" / "index.md", _hub("sistema", dt.date.today().isoformat(), 30))
    _write(mem / "financeiro" / "index.md", _hub("financeiro", "2000-01-01", 1))
    # A non-hub index that must NOT appear in the vitality table.
    _write(
        mem / "ontologia" / "index.md",
        "---\npage_id: ontologia-index\npage_type: ontology_index\ncontext: sistema\n"
        "visibility: private_self\nupdated_at: 2026-06-08\nstale_after_days: 45\n"
        "sources_policy: x\ngate: github_pr\nsensitive_data_policy: private_sensitive_allowed\n---\n\n# Ontologia\n",
    )

    return tmp_path


def test_build_page_uses_owner_label_and_repo_id(compile_mod, config, minimal_repo):
    page = compile_mod.build_page(minimal_repo, config)
    assert "# Operacao - acme-wiki" in page
    assert "Alex Doe" in page  # owner_label surfaced (title/labels)
    assert "page_id: operacao-acme-wiki" in page


def test_build_page_has_no_personal_literals(compile_mod, config, minimal_repo):
    page = compile_mod.build_page(minimal_repo, config)
    for forbidden in ("Kim", "Sargam", "Downloads", "../../../../"):
        assert forbidden not in page, f"unexpected personal literal: {forbidden!r}"


def test_build_page_reflects_decisions_from_sources(compile_mod, config, minimal_repo):
    page = compile_mod.build_page(minimal_repo, config)
    assert "Aprovar o plano alfa" in page
    assert "Escolher piloto beta" in page
    assert "decisoes/alfa.md" in page
    # The decisoes/index.md is not a decision and must not be listed.
    assert "decisoes-index" not in page


def test_build_page_reflects_actions_from_sources(compile_mod, config, minimal_repo):
    page = compile_mod.build_page(minimal_repo, config)
    assert "Revisar cobertura" in page
    assert "Conciliar fila" in page
    assert "recorrente" in page
    assert "pendente" in page
    assert "acoes/primeira.md" in page
    # The owner actions header is parameterized on owner_label.
    assert "## Acoes do dono (Alex Doe)" in page


def test_build_page_lists_pending_action_ids(compile_mod, config, minimal_repo):
    page = compile_mod.build_page(minimal_repo, config)
    assert "`acao-primeira`" in page
    assert "`acao-segunda`" in page


def test_build_page_derives_context_vitality(compile_mod, config, minimal_repo):
    page = compile_mod.build_page(minimal_repo, config)
    # Fresh hub (updated today) -> fresca; stale hub (updated_at 2000) -> stale.
    assert "fresca" in page
    assert "stale" in page
    # Only context_hub indexes appear; the ontology index is excluded.
    assert "ontologia/index.md" not in page
    # The stale context is surfaced in the alerts section.
    assert "Contextos stale para revisar: financeiro." in page  # generated pt output, kept verbatim


def test_build_page_empty_repo_writes_honest_placeholders(compile_mod, config, tmp_path):
    (tmp_path / "memorias").mkdir()
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
    assert "context: sistema" in head


def test_frontmatter_has_provenance(compile_mod, config, minimal_repo):
    head = compile_mod.build_page(minimal_repo, config).split("---", 2)[1]
    assert "generated_from_commit:" in head
    assert "generated_from_branch:" in head


def test_checked_sections_detect_decision_drift(compile_mod, config, minimal_repo):
    page = compile_mod.build_page(minimal_repo, config)
    sections = compile_mod.checked_sections(page)
    # Only the deterministic sections (decisions/actions) enter --check; nothing from git/date.
    assert any(h.startswith("Decisoes pendentes") for h in sections)
    assert any(h.startswith("Acoes do dono") for h in sections)
    # Recompiling without changing memorias produces identical sections (-> --check passes).
    assert compile_mod.checked_sections(compile_mod.build_page(minimal_repo, config)) == sections
    # Removing a decision changes the checked sections (-> --check fails).
    (minimal_repo / "memorias" / "decisoes" / "alfa.md").unlink()
    drifted = compile_mod.checked_sections(compile_mod.build_page(minimal_repo, config))
    assert drifted != sections


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
    assert "Karma e vitalidade" not in "".join(compile_mod.checked_sections(page))


def test_build_page_language_en(compile_mod, minimal_repo):
    # language=en generates the cockpit in English from the same memorias.
    en = compile_mod.WikiConfig(repo_id="acme-wiki", owner_label="Owner", language="en")
    page = compile_mod.build_page(minimal_repo, en)
    assert "# Operations - acme-wiki" in page
    assert "## Pending decisions" in page
    assert "## Owner actions (Owner)" in page
    assert "## Resume links" in page
    assert "| Decision | Context | Source |" in page
    # no Portuguese in the generated body
    assert "## Decisoes pendentes" not in page
    assert "Atualizado em:" not in page


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
        minimal_repo / "memorias" / "acoes" / "terceira.md",
        "---\npage_id: acao-terceira\npage_type: action\ncontext: sistema\n"
        "visibility: private_self\nupdated_at: 2026-06-08\nstale_after_days: 30\n"
        "sources_policy: contrato\ngate: github_pr\nsensitive_data_policy: private_sensitive_allowed\n---\n\n"
        "# Acao - Sem linha de estado\n\nCorpo.\n",
    )
    page_pt = compile_mod.build_page(minimal_repo, config)
    assert "| Sem linha de estado | sistema | sem estado |" in page_pt
    en = compile_mod.WikiConfig(repo_id="acme-wiki", owner_label="Owner", language="en")
    page_en = compile_mod.build_page(minimal_repo, en)
    assert "| Sem linha de estado | sistema | no state |" in page_en
    assert "sem estado" not in page_en


def test_state_parser_accepts_estado_and_state(compile_mod, config, minimal_repo):
    # English-authored action pages ("State: `...`") are parsed like Portuguese
    # ones ("Estado: `...`"); the bilingual STATE_RE covers both.
    _write(
        minimal_repo / "memorias" / "acoes" / "english.md",
        "---\npage_id: acao-english\npage_type: action\ncontext: sistema\n"
        "visibility: private_self\nupdated_at: 2026-06-08\nstale_after_days: 30\n"
        "sources_policy: contrato\ngate: github_pr\nsensitive_data_policy: private_sensitive_allowed\n---\n\n"
        "# Action - Review backlog\n\nState: `recurring`.\n\nBody.\n",
    )
    assert compile_mod.first_state("Estado: `pendente`.") == "pendente"
    assert compile_mod.first_state("State: `recurring`.") == "recurring"
    page = compile_mod.build_page(minimal_repo, config)
    assert "| Review backlog | sistema | recurring |" in page
    # The pt pages of the fixture keep working side by side.
    assert "| Revisar cobertura | sistema | recorrente |" in page


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
        minimal_repo / "memorias" / "decisoes" / "gamma.md",
        "---\npage_id: decisao-gamma\npage_type: decision\ncontext: sistema\n"
        "visibility: private_self\nupdated_at: 2026-06-08\nstale_after_days: 180\n"
        "sources_policy: contrato\ngate: github_pr\nsensitive_data_policy: private_sensitive_allowed\n---\n\n"
        "# Decision - Adopt the kit\n\nBody.\n",
    )
    page = compile_mod.build_page(minimal_repo, config)
    assert "| Adopt the kit | sistema |" in page
    assert "Decision - Adopt the kit" not in page
