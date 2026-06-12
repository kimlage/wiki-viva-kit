from __future__ import annotations

import datetime as dt
from pathlib import Path

from wiki_core.config import WikiConfig, load_config
from wiki_core.operational_pass import (
    build_operational_pass_page,
    build_operational_pass_report,
    first_state,
    report_to_dict,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _hub(context: str) -> str:
    return (
        "---\n"
        f"page_id: {context}-index\n"
        "page_type: context_hub\n"
        f"context: {context}\n"
        "visibility: private_self\n"
        "updated_at: 2026-06-10\n"
        "stale_after_days: 30\n"
        "sources_policy: memory\n"
        "gate: github_pr\n"
        "sensitive_data_policy: private_sensitive_allowed\n"
        "---\n\n"
        f"# {context.title()} hub\n"
    )


def _source() -> str:
    return (
        "---\n"
        "page_id: source-crm\n"
        "page_type: source\n"
        "title: \"Source - CRM export\"\n"
        "source_type: csv\n"
        "ingestion_state: ingested\n"
        "last_ingested_at: 2026-06-01\n"
        "refresh_policy: recurring\n"
        "refresh_cadence_days: 7\n"
        "context: example\n"
        "visibility: private_self\n"
        "updated_at: 2026-06-01\n"
        "stale_after_days: 30\n"
        "sources_policy: source\n"
        "gate: github_pr\n"
        "sensitive_data_policy: private_sensitive_allowed\n"
        "actions:\n"
        "  - action-contact-owner\n"
        "---\n\n"
        "# Source - CRM export\n"
    )


def _action() -> str:
    return (
        "---\n"
        "page_id: action-contact-owner\n"
        "page_type: action\n"
        "context: example\n"
        "visibility: private_self\n"
        "updated_at: 2026-06-11\n"
        "stale_after_days: 14\n"
        "sources_policy: source\n"
        "gate: github_pr\n"
        "sensitive_data_policy: private_sensitive_allowed\n"
        "source_refs:\n"
        "  - source-crm\n"
        "---\n\n"
        "# Action - Contact owner\n\n"
        "State: `pending`.\n"
    )


def _claim() -> str:
    return (
        "---\n"
        "page_id: claim-missing-rating\n"
        "page_type: claim\n"
        "context: example\n"
        "visibility: private_self\n"
        "updated_at: 2026-06-11\n"
        "stale_after_days: 30\n"
        "sources_policy: source\n"
        "gate: github_pr\n"
        "sensitive_data_policy: private_sensitive_allowed\n"
        "source_refs:\n"
        "  - source-crm\n"
        "---\n\n"
        "# Claim - Missing rating\n\n"
        "Status: `pending` because the source is incomplete.\n"
    )


def _context_note() -> str:
    return (
        "---\n"
        "page_id: context-note-example\n"
        "page_type: context_note\n"
        "context: example\n"
        "visibility: private_self\n"
        "updated_at: 2026-06-11\n"
        "stale_after_days: 30\n"
        "sources_policy: source\n"
        "gate: github_pr\n"
        "sensitive_data_policy: private_sensitive_allowed\n"
        "---\n\n"
        "# Context note - Example\n"
    )


def _non_ingested_source() -> str:
    return (
        "---\n"
        "page_id: source-skipped\n"
        "page_type: source\n"
        "title: \"Source - Skipped export\"\n"
        "source_type: csv\n"
        "ingestion_state: skipped\n"
        "last_ingested_at: 2026-06-11\n"
        "refresh_policy: on_demand\n"
        "context: example\n"
        "visibility: private_self\n"
        "updated_at: 2026-06-11\n"
        "stale_after_days: 30\n"
        "sources_policy: source\n"
        "gate: github_pr\n"
        "sensitive_data_policy: private_sensitive_allowed\n"
        "---\n\n"
        "# Source - Skipped export\n"
    )


def test_operational_pass_crosses_sources_actions_and_uncertainty(tmp_path: Path):
    mem = tmp_path / "memories"
    _write(mem / "example" / "index.md", _hub("example"))
    _write(mem / "sources" / "crm.md", _source())
    _write(mem / "actions" / "contact-owner.md", _action())
    _write(
        mem / "actions" / "pending.md",
        "---\npage_id: pending\npage_type: ontology_index\ncontext: system\nvisibility: private_self\n"
        "updated_at: 2026-06-11\nstale_after_days: 30\nsources_policy: x\ngate: github_pr\n"
        "sensitive_data_policy: private_sensitive_allowed\n---\n\n# Pending\n\n- `action-contact-owner`\n",
    )
    _write(mem / "claims" / "rating.md", _claim())
    _write(
        mem / "decisions" / "ship.md",
        "---\npage_id: decision-ship\npage_type: decision\ncontext: example\nvisibility: private_self\n"
        "updated_at: 2026-06-11\nstale_after_days: 30\nsources_policy: x\ngate: github_pr\n"
        "sensitive_data_policy: private_sensitive_allowed\nsource_refs: []\n---\n\n# Decision - Ship\n",
    )

    config = WikiConfig(repo_id="acme", owner_label="Owner", contexts=("example",))
    report = build_operational_pass_report(tmp_path, config, as_of=dt.date(2026, 6, 12))

    assert report.context_rows[0].sources == 1
    assert report.context_rows[0].source_attention == 1  # next refresh was 2026-06-08
    assert report.context_rows[0].actions == 1
    assert report.context_rows[0].action_attention == 1
    assert report.context_rows[0].claims == 1
    assert report.context_rows[0].decisions == 1
    assert "Contact owner" in report.context_rows[0].next_steps[0]
    assert any(row.page.page_id == "claim-missing-rating" for row in report.attention)


def test_operational_pass_surfaces_pending_decisions(tmp_path: Path):
    mem = tmp_path / "memories"
    _write(mem / "example" / "index.md", _hub("example"))
    _write(mem / "actions" / "contact-owner.md", _action())
    _write(
        mem / "decisions" / "authorize-source.md",
        "---\npage_id: decision-authorize-source\npage_type: decision\ncontext: example\n"
        "status: pending\nvisibility: private_self\nupdated_at: 2026-06-11\n"
        "stale_after_days: 30\nsources_policy: x\ngate: github_pr\n"
        "sensitive_data_policy: private_sensitive_allowed\nactions:\n"
        "  - action-contact-owner\n---\n\n# Decision - Authorize live source\n",
    )

    config = WikiConfig(repo_id="acme", owner_label="Owner", contexts=("example",))
    report = build_operational_pass_report(tmp_path, config, as_of=dt.date(2026, 6, 12))
    page = build_operational_pass_page(tmp_path, config, updated_at="2026-06-12")

    assert [d.page_id for d in report.pending_decisions] == ["decision-authorize-source"]
    assert "## Pending decisions" in page
    assert "[Authorize live source](../decisions/authorize-source.md)" in page
    assert "`action-contact-owner`" in page


def test_operational_pass_compiles_outputs_and_decision_blockers(tmp_path: Path):
    mem = tmp_path / "memories"
    _write(mem / "example" / "index.md", _hub("example"))
    _write(mem / "sources" / "skipped.md", _non_ingested_source())
    _write(mem / "actions" / "contact-owner.md", _action())
    _write(mem / "contexts" / "example.md", _context_note())
    _write(
        mem / "decisions" / "authorize-source.md",
        "---\npage_id: decision-authorize-source\npage_type: decision\ncontext: example\n"
        "status: pending\nvisibility: private_self\nupdated_at: 2026-06-11\n"
        "stale_after_days: 30\nsources_policy: x\ngate: github_pr\n"
        "sensitive_data_policy: private_sensitive_allowed\nactions:\n"
        "  - action-contact-owner\n---\n\n# Decision - Authorize live source\n",
    )

    config = WikiConfig(repo_id="acme", owner_label="Owner", contexts=("example",))
    report = build_operational_pass_report(tmp_path, config, as_of=dt.date(2026, 6, 12))
    page = build_operational_pass_page(tmp_path, config, updated_at="2026-06-12")
    payload = report_to_dict(report)

    assert report.consolidation_outputs[0].context_notes == 1
    assert report.consolidation_outputs[0].non_ingested_sources == 1
    assert report.consolidation_outputs[0].signal == "blocked_by_decision"
    assert len(report.decision_action_blockers) == 1
    assert report.decision_action_blockers[0].action is not None
    assert report.decision_action_blockers[0].action_id == "action-contact-owner"
    assert "## Consolidation output matrix" in page
    assert "## Actions gated by pending decisions" in page
    assert "[Authorize live source](../decisions/authorize-source.md)" in page
    assert "[Contact owner](../actions/contact-owner.md)" in page
    assert payload["consolidation_outputs"][0]["signal"] == "blocked_by_decision"
    assert payload["decision_action_blockers"][0]["action_page_id"] == "action-contact-owner"


def test_context_root_index_wins_over_nested_context_hubs(tmp_path: Path):
    mem = tmp_path / "memories"
    _write(mem / "example" / "index.md", _hub("example"))
    _write(
        mem / "example" / "projects" / "README.md",
        _hub("example").replace("page_id: example-index", "page_id: nested-hub"),
    )

    config = WikiConfig(repo_id="acme", owner_label="Owner", contexts=("example",))
    report = build_operational_pass_report(tmp_path, config, as_of=dt.date(2026, 6, 12))

    assert report.context_rows[0].hub is not None
    assert report.context_rows[0].hub.rel == "memories/example/index.md"


def test_artifacts_only_count_as_sources_with_source_metadata(tmp_path: Path):
    mem = tmp_path / "memories"
    _write(mem / "example" / "index.md", _hub("example"))
    _write(
        mem / "example" / "run-log.md",
        "---\npage_id: run-log\npage_type: artifact\ncontext: example\nvisibility: private_self\n"
        "updated_at: 2026-06-11\nstale_after_days: 30\nsources_policy: x\ngate: github_pr\n"
        "sensitive_data_policy: private_sensitive_allowed\n---\n\n# Run log\n",
    )
    _write(
        mem / "sources" / "chat.md",
        "---\npage_id: source-chat\npage_type: source\ncontext: example\nvisibility: private_self\n"
        "updated_at: 2026-06-11\nstale_after_days: 30\nsource_type: chat\n"
        "structured_ingestion_state: ingested\nsources_policy: x\ngate: github_pr\n"
        "sensitive_data_policy: private_sensitive_allowed\n---\n\n# Source - chat\n",
    )
    _write(
        mem / "sources" / "public-artifact.md",
        "---\npage_id: artifact-source\npage_type: artifact\ncontext: example\nvisibility: private_self\n"
        "updated_at: 2026-06-11\nstale_after_days: 30\nsource_type: artifact\n"
        "ingestion_state: ingested\nsources_policy: x\ngate: github_pr\n"
        "sensitive_data_policy: private_sensitive_allowed\n---\n\n# Artifact source\n",
    )

    report = build_operational_pass_report(
        tmp_path,
        WikiConfig(repo_id="acme", owner_label="Owner", contexts=("example",)),
        as_of=dt.date(2026, 6, 12),
    )

    assert {s.page.page_id for s in report.sources} == {"source-chat", "artifact-source"}
    assert {s.ingestion_state for s in report.sources} == {"ingested"}


def test_root_moc_can_be_default_context_hub(tmp_path: Path):
    _write(
        tmp_path / "memories" / "index.md",
        "---\npage_id: root\npage_type: root_index\ncontext: system\nvisibility: private_self\n"
        "updated_at: 2026-06-11\nstale_after_days: 30\nsources_policy: x\ngate: github_pr\n"
        "sensitive_data_policy: private_sensitive_allowed\n---\n\n# Root\n",
    )

    report = build_operational_pass_report(
        tmp_path,
        WikiConfig(repo_id="acme", owner_label="Owner", contexts=("system",)),
        as_of=dt.date(2026, 6, 12),
    )

    assert report.context_rows[0].hub is not None
    assert report.context_rows[0].hub.rel == "memories/index.md"


def test_first_state_keeps_unquoted_iso_dates():
    assert first_state("State: `pending` -- blocked by review.") == "pending"
    assert (
        first_state("Estado: pendente (registrada em 2026-06-11 a partir da fonte).")
        == "pendente (registrada em 2026-06-11 a partir da fonte)"
    )


def test_operational_pass_page_uses_configured_localized_path(tmp_path: Path):
    _write(
        tmp_path / "wiki.config.yaml",
        "repo_id: acme\n"
        "owner_label: Owner\n"
        "language: pt\n"
        "default_context: sistema\n"
        "contexts: exemplo\n"
        "paths:\n"
        "  memory_root: memorias\n"
        "  system_dirname: sistema\n"
        "  actions_dirname: acoes\n"
        "  pending_actions_filename: pendentes.md\n"
        "  sources_dirname: fontes\n"
        "  operation_page: memorias/operacao.md\n"
        "  operational_pass_page: memorias/sistema/passagem-operacional.md\n"
        "  source_registry_page: memorias/sistema/registro-fontes.md\n",
    )
    config = load_config(tmp_path)
    _write(tmp_path / "memorias" / "exemplo" / "index.md", _hub("exemplo").replace("context_hub", "context_hub"))
    _write(tmp_path / "memorias" / "operacao.md", "---\npage_id: op\n---\n\n# Op\n")
    _write(tmp_path / "memorias" / "sistema" / "registro-fontes.md", "---\npage_id: reg\n---\n\n# Reg\n")

    page = build_operational_pass_page(tmp_path, config, updated_at="2026-06-12")

    assert "page_id: passagem-operacional-acme" in page
    assert "# Passagem operacional - fontes, acoes e contextos" in page
    assert "[memorias/operacao.md](../operacao.md)" in page
    assert "[memorias/sistema/registro-fontes.md](registro-fontes.md)" in page
