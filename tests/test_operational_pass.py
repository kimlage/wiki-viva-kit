from __future__ import annotations

import datetime as dt
from pathlib import Path

from wiki_core.config import WikiConfig, load_config
from wiki_core.operational_pass import (
    build_operational_pass_page,
    build_operational_pass_report,
    first_state,
    parse_next_steps,
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


def _factual_claim_with_historical_attention_words() -> str:
    return (
        "---\n"
        "page_id: claim-rating-closed\n"
        "page_type: claim\n"
        "title: \"Claim - Rating formerly pending\"\n"
        "context: example\n"
        "status: fato\n"
        "visibility: private_self\n"
        "updated_at: 2026-06-11\n"
        "stale_after_days: 30\n"
        "sources_policy: source\n"
        "gate: github_pr\n"
        "sensitive_data_policy: private_sensitive_allowed\n"
        "source_refs:\n"
        "  - source-crm\n"
        "---\n\n"
        "# Claim - Rating formerly pending\n\n"
        "Status: `fato`. This was pending in the source title, but the claim is now confirmed.\n"
    )


def _insight_claim_with_risk_words() -> str:
    return (
        "---\n"
        "page_id: claim-pr-gate-risk\n"
        "page_type: claim\n"
        "title: \"Claim - PR gate reduces risk\"\n"
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
        "# Claim - PR gate reduces risk\n\n"
        "Status: `insight`.\n\n"
        "A review gate reduces risk, but this is an accepted process insight, "
        "not an operational blocker.\n"
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
    page = build_operational_pass_page(tmp_path, config, updated_at="2026-06-12")

    assert report.context_rows[0].sources == 1
    assert report.context_rows[0].source_attention == 1  # next refresh was 2026-06-08
    assert report.context_rows[0].actions == 1
    assert report.context_rows[0].action_attention == 1
    assert report.context_rows[0].claims == 1
    assert report.context_rows[0].decisions == 1
    assert "Contact owner" in report.context_rows[0].next_steps[0]
    assert "stale_after_days: 1" in page
    assert "## Short-term memory" in page
    assert "### Review now" in page
    assert "### Primary actions" in page
    assert "### Latest updates" in page
    assert "[Contact owner](../actions/contact-owner.md)" in page
    assert "refresh source: [CRM export](../sources/crm.md)" in page
    assert any(row.page.page_id == "claim-missing-rating" for row in report.attention)


def test_operational_pass_does_not_surface_factual_claims_as_attention(
    tmp_path: Path,
):
    mem = tmp_path / "memories"
    _write(mem / "example" / "index.md", _hub("example"))
    _write(mem / "claims" / "rating-closed.md", _factual_claim_with_historical_attention_words())

    config = WikiConfig(repo_id="acme", owner_label="Owner", contexts=("example",))
    report = build_operational_pass_report(tmp_path, config, as_of=dt.date(2026, 6, 12))
    page = build_operational_pass_page(tmp_path, config, updated_at="2026-06-12")

    assert report.context_rows[0].claims == 1
    assert report.attention == ()
    assert report.consolidation_outputs[0].problems == 0
    assert report.consolidation_outputs[0].signal == "ok"
    assert "Claim - Rating formerly pending" not in page


def test_operational_pass_does_not_surface_insight_claims_as_attention(
    tmp_path: Path,
):
    mem = tmp_path / "memories"
    _write(mem / "example" / "index.md", _hub("example"))
    _write(mem / "claims" / "pr-gate-risk.md", _insight_claim_with_risk_words())

    config = WikiConfig(repo_id="acme", owner_label="Owner", contexts=("example",))
    report = build_operational_pass_report(tmp_path, config, as_of=dt.date(2026, 6, 12))
    page = build_operational_pass_page(tmp_path, config, updated_at="2026-06-12")

    assert report.context_rows[0].claims == 1
    assert report.attention == ()
    assert report.consolidation_outputs[0].problems == 0
    assert report.consolidation_outputs[0].signal == "ok"
    assert "Attention keyword detected" not in page


def test_short_memory_balances_attention_and_actions_across_contexts(tmp_path: Path):
    def action_page(page_id: str, title: str, context: str) -> str:
        return (
            "---\n"
            f"page_id: {page_id}\n"
            "page_type: action\n"
            f"title: \"Action - {title}\"\n"
            f"context: {context}\n"
            "status: pending\n"
            "visibility: private_self\n"
            "updated_at: 2026-06-11\n"
            "stale_after_days: 14\n"
            "sources_policy: source\n"
            "gate: github_pr\n"
            "sensitive_data_policy: private_sensitive_allowed\n"
            "---\n\n"
            f"# Action - {title}\n"
        )

    mem = tmp_path / "memories"
    for context in ("finance", "documents", "professional"):
        _write(mem / context / "index.md", _hub(context))
    for idx in range(1, 6):
        _write(
            mem / "actions" / f"docs-{idx}.md",
            action_page(f"action-docs-{idx}", f"Docs {idx}", "documents"),
        )
    _write(
        mem / "actions" / "finance.md",
        action_page("action-finance-review", "Finance review", "finance"),
    )
    _write(
        mem / "actions" / "professional.md",
        action_page("action-professional-review", "Professional review", "professional"),
    )

    config = WikiConfig(
        repo_id="acme",
        owner_label="Owner",
        contexts=("finance", "documents", "professional"),
    )
    page = build_operational_pass_page(tmp_path, config, updated_at="2026-06-12")
    review_block = page.split("### Review now", 1)[1].split("### Primary actions", 1)[0]
    actions_block = page.split("### Primary actions", 1)[1].split(
        "### Pending decisions", 1
    )[0]

    assert "Finance review" in review_block
    assert "Professional review" in review_block
    assert "Docs 1" in review_block
    assert "Docs 5" not in review_block
    assert "Finance review" in actions_block
    assert "Professional review" in actions_block
    assert "Docs 1" in actions_block
    assert "Docs 5" not in actions_block


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


def test_operational_pass_treats_closed_decision_as_not_pending(tmp_path: Path):
    mem = tmp_path / "memories"
    _write(mem / "example" / "index.md", _hub("example"))
    _write(mem / "actions" / "contact-owner.md", _action())
    _write(
        mem / "decisions" / "authorize-source.md",
        "---\npage_id: decision-authorize-source\npage_type: decision\ncontext: example\n"
        "status: concluida\nvisibility: private_self\nupdated_at: 2026-06-11\n"
        "stale_after_days: 30\nsources_policy: x\ngate: github_pr\n"
        "sensitive_data_policy: private_sensitive_allowed\nactions:\n"
        "  - action-contact-owner\n---\n\n# Decision - Authorize live source\n\n"
        "Pending source work remains, but this decision is already closed.\n",
    )

    config = WikiConfig(repo_id="acme", owner_label="Owner", contexts=("example",))
    report = build_operational_pass_report(tmp_path, config, as_of=dt.date(2026, 6, 12))
    page = build_operational_pass_page(tmp_path, config, updated_at="2026-06-12")

    assert report.pending_decisions == ()
    assert report.decision_action_blockers == ()
    assert "No pending decisions." in page


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
    assert first_state("Status: `insight`.") == "insight"
    assert (
        first_state("Estado: pendente (registrada em 2026-06-11 a partir da fonte).")
        == "pendente (registrada em 2026-06-11 a partir da fonte)"
    )


def test_parse_next_steps_extracts_trigger_and_done_flag():
    body = (
        "# Action\n\nState: `pending`.\n\n"
        "## Proximos passos\n\n"
        "- [ ] renew browser session — gatilho: before any write — resultado: fresh session\n"
        "- [x] confirm readback — trigger: after import\n"
        "- [ ] preserve final fiscal PDFs before memory update\n"
        "  trigger: when the files are available\n"
        "- [ ] plain step with no trigger\n\n"
        "## Other\n\n- [ ] not a next step\n"
    )
    steps = parse_next_steps(body)
    assert [s.text for s in steps] == [
        "renew browser session",
        "confirm readback",
        "preserve final fiscal PDFs before memory update",
        "plain step with no trigger",
    ]
    # The trailing "resultado:" clause is dropped from the trigger.
    assert steps[0].trigger == "before any write"
    assert steps[0].done is False
    assert steps[1].trigger == "after import"
    assert steps[1].done is True
    assert steps[2].trigger == "when the files are available"
    assert steps[3].trigger == ""


def _role(page_id: str, context: str, responsibilities: list[str], *, assignment: bool = True) -> str:
    resp_lines = "\n".join(f"  - {r}" for r in responsibilities) or "[]"
    resp_block = f"responsibilities:\n{resp_lines}" if responsibilities else "responsibilities: []"
    assign_block = f"assignments:\n  - assignment-{page_id}\n" if assignment else ""
    return (
        "---\n"
        f"page_id: {page_id}\n"
        "page_type: role\n"
        f'title: "Role - {page_id}"\n'
        f"context: {context}\n"
        "visibility: private_self\n"
        "updated_at: 2026-06-12\n"
        "stale_after_days: 45\n"
        "sources_policy: x\ngate: github_pr\n"
        "sensitive_data_policy: private_sensitive_allowed\n"
        f"{resp_block}\n"
        f"{assign_block}"
        "---\n\n"
        f"# Role - {page_id}\n"
    )


def _responsibility(page_id: str, context: str, roles: list[str], actions: list[str]) -> str:
    role_lines = "\n".join(f"  - {r}" for r in roles)
    action_lines = "\n".join(f"  - {a}" for a in actions)
    role_block = f"roles:\n{role_lines}" if roles else "roles: []"
    action_block = f"actions:\n{action_lines}" if actions else "actions: []"
    return (
        "---\n"
        f"page_id: {page_id}\n"
        "page_type: responsibility\n"
        f'title: "Responsibility - {page_id}"\n'
        f"context: {context}\n"
        "visibility: private_self\n"
        "updated_at: 2026-06-12\n"
        "stale_after_days: 30\n"
        "sources_policy: x\ngate: github_pr\n"
        "sensitive_data_policy: private_sensitive_allowed\n"
        f"{role_block}\n"
        f"{action_block}\n"
        "---\n\n"
        f"# Responsibility - {page_id}\n"
    )


def _model_action(page_id: str, context: str, responsibilities: list[str], state: str, steps: str = "") -> str:
    resp_lines = "\n".join(f"  - {r}" for r in responsibilities)
    resp_block = f"responsibilities:\n{resp_lines}" if responsibilities else "responsibilities: []"
    return (
        "---\n"
        f"page_id: {page_id}\n"
        "page_type: action\n"
        f'title: "Action - {page_id}"\n'
        f"context: {context}\n"
        "visibility: private_self\n"
        "updated_at: 2026-06-12\n"
        "stale_after_days: 15\n"
        "sources_policy: x\ngate: github_pr\n"
        "sensitive_data_policy: private_sensitive_allowed\n"
        f"{resp_block}\n"
        "---\n\n"
        f"# Action - {page_id}\n\n"
        f"State: `{state}`.\n"
        f"{steps}"
    )


def test_operational_model_renders_role_responsibility_action_tree(tmp_path: Path):
    mem = tmp_path / "memories"
    _write(mem / "fin" / "index.md", _hub("fin"))
    _write(mem / "papeis" / "steward.md", _role("role-steward", "fin", ["resp-validate"]))
    _write(
        mem / "atribuicoes" / "kim-steward.md",
        "---\npage_id: assignment-role-steward\npage_type: assignment\n"
        'title: "Assignment - Kim steward"\ncontext: fin\nvisibility: private_self\n'
        "updated_at: 2026-06-12\nstale_after_days: 30\nsources_policy: x\ngate: github_pr\n"
        "sensitive_data_policy: private_sensitive_allowed\nroles:\n  - role-steward\n---\n\n# Assignment\n",
    )
    _write(
        mem / "responsabilidades" / "validate.md",
        _responsibility("resp-validate", "fin", ["role-steward"], ["action-revisar"]),
    )
    _write(
        mem / "acoes" / "revisar.md",
        _model_action(
            "action-revisar",
            "fin",
            ["resp-validate"],
            "pendente",
            "\n## Proximos passos\n\n- [ ] renovar sessao Browser — gatilho: antes de escrever\n",
        ),
    )

    config = WikiConfig(repo_id="acme", owner_label="Owner", contexts=("fin",), language="pt")
    report = build_operational_pass_report(tmp_path, config, as_of=dt.date(2026, 6, 12))
    page = build_operational_pass_page(tmp_path, config, updated_at="2026-06-12")
    payload = report_to_dict(report)

    model = report.operational_model
    assert [r.context for r in model] == ["fin"]
    assert model[0].roles[0].page.page_id == "role-steward"
    assert model[0].roles[0].assignment is not None
    resp_node = model[0].roles[0].responsibilities[0]
    assert resp_node.page.page_id == "resp-validate"
    assert resp_node.health == "atencao"  # action body says pendente
    assert resp_node.open_actions[0].page_id == "action-revisar"
    assert resp_node.next_steps[0].trigger == "antes de escrever"

    assert "## Modelo operacional por contexto" in page
    assert "### fin" in page
    assert "[Role - role-steward](../papeis/steward.md)" in page
    assert "renovar sessao Browser" in page
    assert payload["operational_model"][0]["roles"][0]["health"] == "ok"
    assert (
        payload["operational_model"][0]["roles"][0]["responsibilities"][0]["next_steps"][0][
            "trigger"
        ]
        == "antes de escrever"
    )


def test_operational_pass_treats_dated_closed_action_as_closed(tmp_path: Path):
    mem = tmp_path / "memories"
    _write(mem / "fin" / "index.md", _hub("fin"))
    _write(mem / "papeis" / "steward.md", _role("role-steward", "fin", ["resp-validate"]))
    _write(
        mem / "responsabilidades" / "validate.md",
        _responsibility("resp-validate", "fin", ["role-steward"], ["action-done"]),
    )
    _write(
        mem / "acoes" / "done.md",
        _model_action(
            "action-done",
            "fin",
            ["resp-validate"],
            "concluida_em_2026-06-12",
            "\n## Next steps\n\n- [ ] pending readback would be stale if this were open\n",
        ),
    )
    _write(
        mem / "actions" / "pending.md",
        "---\npage_id: pending\npage_type: ontology_index\ncontext: system\nvisibility: private_self\n"
        "updated_at: 2026-06-12\nstale_after_days: 30\nsources_policy: x\ngate: github_pr\n"
        "sensitive_data_policy: private_sensitive_allowed\n---\n\n# Pending\n\n- `action-done`\n",
    )

    config = WikiConfig(repo_id="acme", owner_label="Owner", contexts=("fin",))
    report = build_operational_pass_report(tmp_path, config, as_of=dt.date(2026, 6, 12))
    page = build_operational_pass_page(tmp_path, config, updated_at="2026-06-12")

    assert report.context_rows[0].actions == 1
    assert report.context_rows[0].action_attention == 0
    assert report.context_rows[0].next_steps == ()
    assert not any(row.page.page_id == "action-done" for row in report.attention)

    resp_node = report.operational_model[0].roles[0].responsibilities[0]
    assert resp_node.health == "ok"
    assert resp_node.open_actions == ()
    assert "No prioritized pending actions." in page


def test_operational_model_marks_preventive_and_roleless(tmp_path: Path):
    mem = tmp_path / "memories"
    _write(mem / "fin" / "index.md", _hub("fin"))
    _write(mem / "doc" / "index.md", _hub("doc"))
    # role in fin with a responsibility that has no action (preventive)
    _write(mem / "papeis" / "steward.md", _role("role-steward", "fin", ["resp-prevent"], assignment=False))
    _write(
        mem / "responsabilidades" / "prevent.md",
        _responsibility("resp-prevent", "fin", ["role-steward"], []),
    )

    config = WikiConfig(repo_id="acme", owner_label="Owner", contexts=("fin", "doc"), language="pt")
    report = build_operational_pass_report(tmp_path, config, as_of=dt.date(2026, 6, 12))
    page = build_operational_pass_page(tmp_path, config, updated_at="2026-06-12")

    model = {r.context: r for r in report.operational_model}
    assert model["fin"].roles[0].responsibilities[0].health == "sem_acao"
    assert model["doc"].roleless_context is True
    assert "sem acao aberta (preventiva)" in page
    assert "_(contextos sem papel preenchido: 1)_" in page


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
    assert "moc_parent: memorias/index.md" in page
    assert "# Passagem operacional - fontes, acoes e contextos" in page
    assert "[memorias/operacao.md](../operacao.md)" in page
    assert "[memorias/sistema/registro-fontes.md](registro-fontes.md)" in page
