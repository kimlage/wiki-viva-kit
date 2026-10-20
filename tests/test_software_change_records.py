"""Public synthetic composition of the existing v1 documentary primitives.

This verifies a complete *declared fixture*, not the closure of any consumer
wiki, policy compliance, execution permissions or a deployment.
"""
import copy
import hashlib

import pytest

from test_document_records import declaration, graph
from test_freshness_impact import TODAY, page, repo
from wiki_core.document_records import digest, edge_digest, node_id, project_records
from wiki_core.freshness_impact import evaluate_impact


def software_case(root, *, stale=None, change=None, financial_claim=None):
    def add(name, body="", **fields):
        return page(root, name, stale=name == stale, body=body, **fields)

    page(root, "finance", stale=True, body="A dated unrelated business observation.")
    add("dashboard", "The old [business item](finance.md).")
    add("v5", "Historical method origin, not the current implementation. [Old dashboard](dashboard.md).")
    add("repo-origin", "Historical origin of a received direction. [Old dashboard](dashboard.md).")
    add("event", "Received permission and limits; [business](finance.md) was observed then.")
    add("project", "# Tool project\n\n## Old pilot\nAn old [business item](finance.md).")
    add("root", "Actionable [business items](finance.md).")
    add("proposals", "Past [business proposals](finance.md).")
    page(root, "ledger", stale=True, body="Historical impact decisions about [business](finance.md).")
    add("control-fact", "The operative input required by the current software rule.")
    add("authority", "# Authority\n\n## Direction\n"
        "Reviewed software changes are permitted; no payments or credentials. "
        "The [business state](finance.md) was reported on a past date.\n\n"
        "## Limits\nDo not bypass failed gates or permissions.\n",
        source_refs=["repo-origin"], evidence_refs=["event"])
    add("policy", "# Policy\n\n## Rules\nUse the current [authority](authority.md) "
        "and operative [control fact](control-fact.md).\n\n"
        "## Checklist\nKeep the [root](root.md) actionable and update the [log](log.md).\n\n"
        "## Validation\nFollow [checks](audit.md) and [contract](contract.md).\n")
    add("process", "# Process\n\n## Steps\nRegister this change in the [log](log.md).\n\n"
        "## Links\nLink-format example: [finance](finance.md). Stage in [proposals](proposals.md).\n")
    add("audit", "# Checks\n\nThe [product](project.md), [policy](policy.md) "
        "and [contract](contract.md) define the check scope.\n\n"
        "## Checks\nUpdate affected pages or record a reason in the [ledger](ledger.md).\n\n"
        "### Impact\nThe [ledger](ledger.md) is append-only with a reason.\n")
    add("contract", "# Operating contract\n\n## Rules\nKeep [root](root.md) actionable. "
        "For financial claims consult the [financial source](finance.md).\n")
    log = add("log", "# Log\n\n## Old\nAn old [business delivery](finance.md).\n\n")
    catalog = add("catalog", "# Commands\n\nCLIs of the [project](project.md); "
        "follow [process](process.md), [checks](audit.md) and [policy](policy.md).\n\n"
        "## Old commands\nEarlier implementation.\n\n", source_refs=["v5"])
    add("existing-client", "The unchanged client follows [policy](policy.md).")
    base = graph(root)
    log.write_text(log.read_text() + "## Software update\n"
                   "Copied the actual implementation; [policy](policy.md) applies. Checks pending.\n")
    catalog.write_text(catalog.read_text() + "## New CLI\n"
                       "The actual implementation supports one reviewed change. "
                       "The current [policy](policy.md) applies; no account grant.\n")
    if financial_claim == "body":
        catalog.write_text(catalog.read_text() + "A real current [financial claim](finance.md).\n")
    elif financial_claim == "metadata":
        catalog.write_text(catalog.read_text().replace("- v5", "- v5\n- finance"))
    if change:
        target = root / "memories" / f"{change}.md"
        target.write_text(target.read_text().replace(
            "Reviewed software changes", "Changed reviewed software changes")
            if change == "authority" else target.read_text() + "\nChanged operative fact.\n")
    current = graph(root)
    headings = {"log": ["Software update"], "catalog": ["New CLI"],
                "policy": ["Rules", "Checklist", "Validation"],
                "authority": ["Direction", "Limits"], "process": ["Steps", "Links"],
                "audit": ["Checks"], "contract": ["Rules"]}
    contract = declaration(base, current, "memories/log.md", headings["log"])
    contract["documents"] = [declaration(base, current, f"memories/{name}.md", titles)["documents"][0]
                             for name, titles in headings.items()]
    for doc in contract["documents"]:
        if doc["path"] in {"memories/policy.md", "memories/authority.md", "memories/process.md"}:
            doc["records"][0]["context_records"] = [r["id"] for r in doc["records"][1:]]
        for record in doc["records"]:
            record["rationale"] = ("The declared canonical rule retains all applicable contexts; "
                                   "historical subjects are qualified separately, not made current.")
    contract["artifacts"] = []
    inputs = {}
    for origin, g in (("base", base), ("current", current)):
        for name in ("v5", "repo-origin", "event", "finance"):
            data = g["documents"][f"memories/{name}.md"].encode()
            aid = "historical-" + name
            contract["artifacts"].append(dict(origin=origin, id=aid,
                path=f"proofs/{aid}.txt", sha256=hashlib.sha256(data).hexdigest()))
            inputs[(origin, aid)] = data
    implementation = b"# Synthetic current implementation\ndef prepare(): return 'review required'\n"
    contract["artifacts"].append(dict(origin="current", id="implementation",
        path="scripts/example_cli.py", sha256=hashlib.sha256(implementation).hexdigest()))
    inputs[("current", "implementation")] = implementation
    for doc in contract["documents"][:2]:
        doc["records"][0]["current_evidence"] = ["implementation"]

    obligations = []
    def bind(origin, name, target, consumer, role="consumption", target_record="entry-0", field=None):
        g = {"base": base, "current": current}[origin]
        for raw in g["edges"]:
            if (raw["source"] != f"memories/{name}.md" or raw["target"] != f"memories/{target}.md"
                    or (field and raw["field"] != field)):
                continue
            b = dict(origin=origin, edge_sha256=edge_digest(raw), consumer_record=consumer, role=role,
                     rationale="Reviewed exact synthetic occurrence and claim; not a waiver of gates or authority.")
            if role == "consumption":
                record = next(d for d in contract["documents"] if d["path"] == raw["target"])["records"]
                b.update(target_record=target_record,
                         consumed_sha256=next(r for r in record if r["id"] == target_record)[origin + "_sha256"])
            else:
                b["prerequisite_document_sha256"] = digest(g["documents"][raw["target"]])
                if role == "provenance":
                    b["evidence"] = ["historical-" + target]
            contract["bindings"].append(b)
            if role == "change_target" and ((name == "process" and target == "log")
                                             or (name == "audit" and target == "ledger")):
                obligations.append((origin, b["edge_sha256"], consumer))

    for origin in ("base", "current"):
        bind(origin, "policy", "authority", "entry-0")
        bind(origin, "policy", "root", "entry-1", "change_target")
        bind(origin, "policy", "log", "entry-1", "change_target")
        bind(origin, "policy", "audit", "entry-2")
        bind(origin, "policy", "contract", "entry-2")
        for rid in ("entry-0", "entry-1"):
            for target in ("repo-origin", "event"):
                bind(origin, "authority", target, rid, "provenance")
        bind(origin, "authority", "finance", "entry-0", "provenance")
        bind(origin, "process", "log", "entry-0", "change_target")
        bind(origin, "process", "finance", "entry-1", "navigation")
        bind(origin, "process", "proposals", "entry-1", "change_target")
        bind(origin, "audit", "ledger", "entry-0", "change_target")
        bind(origin, "audit", "project", "entry-0", "navigation")
        bind(origin, "audit", "policy", "entry-0")
        bind(origin, "audit", "contract", "entry-0")
        bind(origin, "contract", "root", "entry-0", "change_target")
        bind(origin, "contract", "finance", "entry-0", "navigation")
        bind(origin, "existing-client", "policy", "document")
    bind("current", "log", "policy", "entry-0")
    for target in ("policy", "process", "audit"):
        bind("current", "catalog", target, "entry-0")
    bind("current", "catalog", "project", "entry-0", "navigation")
    bind("current", "catalog", "v5", "entry-0", "provenance", field="source_refs")
    changed = {"memories/log.md", "memories/catalog.md"}
    if change:
        changed.add(f"memories/{change}.md")
    assert len(obligations) == 6
    return base, current, contract, inputs, changed, set(obligations)


def run_case(case, *, contract=None):
    base, current, original, inputs, changed, _ = case
    projected, historical, seeds, _ = project_records(current, base, changed,
        contract if contract is not None else original, artifact_inputs=inputs)
    return evaluate_impact(projected, historical, seeds, today=TODAY)


def test_existing_v1_covers_software_norms_history_and_technical_frontier(repo):
    case = software_case(repo)
    result = run_case(case)
    assert result["ok"]
    included = {r["path"]: r for r in result["included"]}
    for name in ("policy", "authority", "process", "audit", "contract"):
        assert included[node_id(f"memories/{name}.md", "entry-0")]["state"] == "fresh"
    assert "memories/control-fact.md" in included
    assert "memories/finance.md" not in included
    assert "memories/ledger.md" not in included
    assert "memories/existing-client.md" not in included  # No fanout from discovered policy.
    assert any(r["state"] == "historical_evidence" for r in included.values())


def test_technical_evidence_does_not_implicitly_remove_inherited_historical_source(repo):
    case = software_case(repo)
    contract = copy.deepcopy(case[2])
    contract["bindings"] = [b for b in contract["bindings"] if not (
        b["origin"] == "current" and b.get("evidence") == ["historical-v5"])]
    result = run_case(case, contract=contract)
    assert "memories/finance.md" in {r["path"] for r in result["blockers"]}


def test_six_old_obligation_occurrences_are_not_fixed_by_record_partition_alone(repo):
    case = software_case(repo)
    contract = copy.deepcopy(case[2])
    contract["bindings"] = [b for b in contract["bindings"]
        if (b["origin"], b["edge_sha256"], b["consumer_record"]) not in case[5]]
    result = run_case(case, contract=contract)
    assert {"memories/finance.md", "memories/ledger.md"} <= {r["path"] for r in result["blockers"]}


@pytest.mark.parametrize("stale", ["policy", "authority", "control-fact"])
def test_canonical_norms_and_real_factual_support_still_age(repo, stale):
    result = run_case(software_case(repo, stale=stale))
    expected = f"memories/{stale}.md" if stale == "control-fact" else node_id(f"memories/{stale}.md", "entry-0")
    assert expected in {r["path"] for r in result["blockers"]}


@pytest.mark.parametrize("location", ["body", "metadata"])
def test_an_actual_financial_claim_is_not_hidden_by_other_historical_qualifications(repo, location):
    result = run_case(software_case(repo, financial_claim=location))
    assert "memories/finance.md" in {r["path"] for r in result["blockers"]}


@pytest.mark.parametrize("change", ["authority", "control-fact"])
def test_real_normative_or_factual_change_still_reaches_unchanged_consumers(repo, change):
    result = run_case(software_case(repo, change=change))
    client = next(r for r in result["included"] if r["path"] == "memories/existing-client.md")
    assert client["reason"] == "affected_dependent"


def test_changed_canonical_authority_rejects_previous_complete_contract(repo):
    case = software_case(repo)
    authority = repo / "memories/authority.md"
    authority.write_text(authority.read_text() + "\nPermission revoked.\n")
    case = (case[0], graph(repo), *case[2:])
    with pytest.raises(ValueError, match="snapshot does not match"):
        run_case(case)
