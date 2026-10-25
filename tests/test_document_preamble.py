"""A whole lexical introduction is an authored factual record, never ignored."""
import copy
import datetime as dt

import pytest

from test_freshness_impact import page, repo
from test_document_records import graph
from wiki_core.document_records import digest, edge_digest, node_id, project_records, sections
from wiki_core.document_view_selectors import body_span
from wiki_core.freshness_impact import evaluate_impact

POLICY = "memories/policy.md"
CONSUMER = "memories/consumer.md"
INTRO = {"kind": "markdown_preamble"}
TODAY = dt.date(2026, 10, 25)


def pair(root):
    page(root,"old-source",stale=True)
    page(root,"consumer",body="Current privacy respects [policy](policy.md). "
         "The current decision also requires [source](old-source.md).")
    page(root,"whole",body="The complete [policy](policy.md) is required.")
    target=page(root,"policy",body="# Policy\n\nApproval requires human review.\n\n"
        "## Invariants\n\nProtect secrets and preserve source evidence.\n\n"
        "## Gate\n\nApply the required approval and independent checks.\n")
    base=graph(root)
    target.write_text(target.read_text().replace("Approval requires human review.",
        "Approval follows the existing independent-review authority."))
    current=graph(root)
    records=[]
    for rid,selector in [("introduction",INTRO),("invariants",{"kind":"h2","heading":"Invariants"}),
                         ("gate",{"kind":"h2","heading":"Gate"})]:
        item=dict(id=rid,independent=True,epistemic_status="decision",recorded_on="2026-10-25",
            rationale="Reviewed synthetic rule: invariants are unconditional; Gate requires approval context.",
            context_records=["introduction"] if rid=="gate" else [],
            selectors={origin:copy.deepcopy(selector)for origin in ("base","current")})
        for origin,g in [("base",base),("current",current)]:
            text=g["documents"][POLICY];body=sections(text)[0];a,b=body_span(text,selector)
            item[origin+"_sha256"]=digest("".join(body.splitlines(keepends=True)[a:b]))
        records.append(item)
    contract=dict(schema_version="document_record.v2",document_modes={POLICY:"explicit_view_v2"},
        documents=[dict(path=POLICY,records=records)],bindings=[],
        **{origin+"_documents_sha256":{p:digest(t)for p,t in g["documents"].items()}
           for origin,g in [("base",base),("current",current)]})
    for origin,g in [("base",base),("current",current)]:
        raw=next(e for e in g["edges"]if e["source"]==CONSUMER and e["target"]==POLICY)
        contract["bindings"].append(dict(origin=origin,edge_sha256=edge_digest(raw),
            role="consumption",target_record="invariants",consumed_sha256=records[1][origin+"_sha256"],
            rationale="This reviewed occurrence consumes unconditional privacy; the source requirement stays factual."))
    return base,current,contract


def evaluate(base,current,contract):
    c,b,seeds,evidence=project_records(current,base,{POLICY},contract)
    result=evaluate_impact(c,b,seeds,today=TODAY)
    return result,evidence


def test_independent_preamble_keeps_whole_consumers_and_unchanged_rule_scope(repo):
    base,current,contract=pair(repo)
    result,evidence=evaluate(base,current,contract)
    assert evidence[0]["complete_delta_covered"]
    assert node_id(POLICY,"introduction") in result["seeds"]
    assert node_id(POLICY,"invariants") not in result["seeds"]
    included={r["path"]for r in result["included"]}
    assert "memories/whole.md" in included
    assert CONSUMER not in included
    assert "memories/old-source.md" in {r["path"]for r in result["unrelated_debt"]}
    assert result["ok"]


def test_required_preamble_context_preserves_mixed_factual_dependency(repo):
    base,current,contract=pair(repo)
    contract["documents"][0]["records"][1]["context_records"]=["introduction"]
    result,_evidence=evaluate(base,current,contract)
    assert CONSUMER in {r["path"]for r in result["included"]}
    assert "memories/old-source.md" in {r["path"]for r in result["blockers"]}
    assert not result["ok"]
    assert all(b["role"]=="consumption"for b in contract["bindings"])


@pytest.mark.parametrize("delta",["metadata","reference_definition"])
def test_preamble_does_not_hide_uncovered_common_delta(repo,delta):
    base,current,contract=pair(repo)
    target=repo/POLICY
    text=target.read_text()
    if delta=="metadata":
        text=text.replace("page_id: policy","page_id: policy\ntitle: Changed common identity")
    else:
        text+="\n[common-source]: old-source.md\n"
    target.write_text(text)
    current=graph(repo)
    contract["current_documents_sha256"]={p:digest(t)for p,t in current["documents"].items()}
    if delta=="reference_definition":
        contract["documents"][0]["records"][2]["current_sha256"]=digest(sections(text)[1]["Gate"][2])
    result,evidence=evaluate(base,current,contract)
    assert not evidence[0]["complete_delta_covered"]
    assert node_id(POLICY,"invariants") in result["seeds"]
    assert CONSUMER in {r["path"]for r in result["included"]}
    assert not result["ok"]


def test_preamble_hash_and_unproven_boundary_refuse(repo):
    base,current,contract=pair(repo)
    contract["documents"][0]["records"][0]["current_sha256"]="0"*64
    with pytest.raises(ValueError,match="selector/hash mismatch"):
        evaluate(base,current,contract)
    with pytest.raises(ValueError,match="proven top-level H2"):
        body_span("# Policy\n\nNo H2 yet.\n",INTRO)
    with pytest.raises(ValueError,match="no free boundaries"):
        body_span("# Policy\n\n## Rule\n",dict(kind="markdown_preamble",end=1))


def test_h2_added_only_in_current_cannot_hide_a_base_introduction(repo):
    base,current,contract=pair(repo)
    no_boundary=base["documents"][POLICY].split("## Invariants",1)[0]
    (repo/POLICY).write_text(no_boundary)
    base=graph(repo)
    contract["base_documents_sha256"]={p:digest(t)for p,t in base["documents"].items()}
    for record in contract["documents"][0]["records"]:
        record["selectors"]["base"]=None
        record["base_sha256"]=None
    with pytest.raises(ValueError,match="proven top-level H2 boundary"):
        evaluate(base,current,contract)


def test_preamble_cannot_be_smuggled_as_publication_envelope(repo):
    base,current,contract=pair(repo)
    introduction=contract["documents"][0]["records"].pop(0)
    introduction["claim"]="artifact_publication_date"
    contract["documents"][0]["envelope"]=[introduction]
    with pytest.raises(ValueError,match="unsupported envelope selector/claim"):
        evaluate(base,current,contract)


@pytest.mark.parametrize("newline",["\n","\r\n"])
def test_preamble_uses_parser_boundary_and_preserves_whole_prefix(newline):
    body=newline.join(["# Policy","","```md","## Fenced","```","","> ## Quoted","",
        "- ## Nested list heading","","Introduction with [a source](source.md).","","## Real rule","","Rule.",""])
    a,b=body_span(body,INTRO)
    selected="".join(body.splitlines(keepends=True)[a:b])
    assert selected==body.split("## Real rule",1)[0]
    assert "## Fenced" in selected and "> ## Quoted" in selected and "## Nested list heading" in selected


def test_preamble_inherits_its_actual_prerequisites(repo):
    base,current,contract=pair(repo)
    for origin,g in [("base",base),("current",current)]:
        # Rebuild both actual documents/edges with an introduction premise.
        text=g["documents"][POLICY].replace("\n\n## Invariants", "\n\nCommon [authority](old-source.md).\n\n## Invariants",1)
        (repo/POLICY).write_text(text)
        rebuilt=graph(repo)
        if origin=="base":base=rebuilt
        else:current=rebuilt
    # Derive declarations and occurrence hashes again from the changed inputs.
    for origin,g in [("base",base),("current",current)]:
        contract[origin+"_documents_sha256"]={p:digest(t)for p,t in g["documents"].items()}
        text=g["documents"][POLICY];body=sections(text)[0];a,b=body_span(text,INTRO)
        contract["documents"][0]["records"][0][origin+"_sha256"]=digest("".join(body.splitlines(keepends=True)[a:b]))
    result,_=evaluate(base,current,contract)
    assert "memories/old-source.md" in {r["path"]for r in result["blockers"]}
    assert not result["ok"]
