"""Composed FICTIONAL cycle, not autonomous-runtime acceptance.

Real: source files/manifests, canonical action/context, Git/bare transport,
contribution implementation, local HTTP producer and served body readback.
Mocked: source account probe, executor material, independent review, GitHub/CI
and merge service. Fixture gate scripts are invocation contracts, not audits.
No model, corporate account or external network is used.
"""
import datetime as dt
import hashlib
import subprocess
import contextlib
import io

import yaml

import wiki_core.action_contribution as port
from wiki_core.action_transition import _parse_document, _render_document
from wiki_core.config import load_config
from wiki_core.source_config import project_source_access
from wiki_core.web.ingestion_plan import build_ingestion_plan
from test_action_contribution import fixture, call, git, review, head_review, reconcile_pr_identity
from test_source_access import source, probe
from test_web_server import _Server


def test_composed_fictional_cycle_replay_interruption_exact_review_and_served_bytes(tmp_path, monkeypatch):
    action, request = fixture(tmp_path)
    fm, body = _parse_document(action.read_text()); fm["context"] = "system"
    canonical = _render_document(fm, body); action.write_text(canonical)
    proposed = canonical.replace("Original evidence.", "Fictional executor result, reviewed separately.")
    request["files"][0].update(base_sha256=hashlib.sha256(canonical.encode()).hexdigest(), sha256=hashlib.sha256(proposed.encode()).hexdigest(), text=proposed)
    event_path = "memories/event.md"
    event = {"page_type": "ingestion_event", "event_id": "fixture-event", "page_id": "fixture-event", "context": "system",
             "source_account": "reader@example.test", "source_refs": ["source-logical"], "config_ref": "memories/source-config.md"}
    raw = "---\n"+yaml.safe_dump(event)+"---\n# Fictional source observation\n"; (tmp_path/event_path).write_text(raw)
    binding = {"repo_id": "synthetic", "source_key": "source-logical", "account_id": "reader@example.test", "context": "system",
               "event_id": "fixture-event", "event_sha256": hashlib.sha256(raw.encode()).hexdigest(), "action_id": "example-action",
               "action_sha256": request["files"][0]["base_sha256"], "owner_ref": "synthetic-owner", "coordinator": "research", "required_sources": ["corporate", "tasks"]}
    (tmp_path/"memories/source-config.md").write_text("---\n"+yaml.safe_dump({"page_type": "source_config", "page_id": "config-one", "action_binding": binding})+"---\n")
    (tmp_path/"wiki.coordination.yaml").write_text(yaml.safe_dump({"schema_version": "wiki_coordination.v1", "profiles": {
        "research": {"label": "Research", "scope": "Fictional source review", "action_ids": ["example-action"]}}}))
    git(tmp_path,"add","."); git(tmp_path,"commit","-m","fictional explicit source binding")
    request["files"][0]["base_commit"] = git(tmp_path,"rev-parse","HEAD")
    cfg = load_config(tmp_path)
    snapshot = {"manifest.json": {"snapshot_id": "fixture"}, "pages.json": {"pages": [{"id": "example-action",
        "path": request["files"][0]["path"], "page_type": "action", "context": "system", "content_sha256": binding["action_sha256"],
        "work": {"state": "open", "owner_ref": "synthetic-owner"}}]}}
    preview = build_ingestion_plan(tmp_path,cfg,event_path,context="system",snapshot=snapshot)["action_preview"]
    assert preview["status"] == "reuse" and not preview["execution_ready"]
    assert preview == build_ingestion_plan(tmp_path,cfg,event_path,context="system",snapshot=snapshot)["action_preview"]
    # A synthetic adapter assertion is NOT a real account observation.
    s = source(); now=dt.datetime(2026,10,20,12,tzinfo=dt.timezone.utc)
    assert project_source_access(s,probe(s),now=now)["verified"]
    assert not project_source_access(s,probe(s,outcome="awaiting_auth"),now=now)["verified"]
    prepared = call(tmp_path,"prepare",request,review=review(request))
    assert prepared["status"] == "prepared",prepared
    replay = call(tmp_path,"prepare",request,review=review(request))
    assert replay["idempotent"] and replay["proposal_commit"] == prepared["proposal_commit"]
    remote = tmp_path.parent/(tmp_path.name+"-fictional-remote.git")
    subprocess.run(["git","init","--bare",str(remote)],check=True,capture_output=True)
    git(tmp_path,"remote","add","origin",str(remote));git(tmp_path,"push","origin","main")
    pr={"number":1,"state":"OPEN","headRefOid":prepared["proposal_commit"],"baseRefName":"main","statusCheckRollup":[{"conclusion":"SUCCESS"}]}
    reconcile_pr_identity(pr,prepared)
    monkeypatch.setattr(port,"_pr",lambda *_:dict(pr));monkeypatch.setattr(port,"_repository",lambda *_:"example.test/synthetic/wiki")
    original_run=port._run; merges=[]
    def mocked_github(root,*argv,**kw):
        if argv[:3]==("gh","pr","merge"):
            merges.append(argv);git(tmp_path,"push","origin",prepared["proposal_commit"]+":refs/heads/main")
            pr.update(state="MERGED",mergeCommit={"oid":prepared["proposal_commit"]})
            raise subprocess.TimeoutExpired(argv,1)  # Effect happened; ACK was lost.
        return original_run(root,*argv,**kw)
    monkeypatch.setattr(port,"_run",mocked_github)
    rejected=call(tmp_path,"integrate",request,pr=1)
    assert rejected["status"]=="refused" and rejected["error"]=="exact_generated_head_review_required" and not merges
    uncertain=call(tmp_path,"integrate",request,pr=1,head_review=head_review(request,prepared["proposal_commit"]))
    assert uncertain["status"]=="unknown" and len(merges)==1
    recovered=call(tmp_path,"reconcile",request,pr=1)
    assert recovered["remote_merged"] and recovered["status"]=="waiting_worktree_adoption" and len(merges)==1
    # A synthetic operator adopts the exact reviewed bytes, not an agent runner.
    git(tmp_path,"merge","--ff-only",prepared["proposal_commit"])
    adopted=call(tmp_path,"reconcile",request,pr=1)
    assert adopted["canonical_body_adopted"] and not adopted["served_adoption_verified"] and len(merges)==1
    with contextlib.redirect_stdout(io.StringIO()):
        server=_Server(tmp_path,load_config(tmp_path))
    try:
        status,content=server.get("/api/pages/example-action/content")
        assert status==200 and "Fictional executor result, reviewed separately." in content["body"],content
        assert content["body"] == _parse_document(action.read_text())[1]
    finally:
        server.close()
    assert not adopted["served_adoption_verified"]  # Port does not certify our separate fixture HTTP read.
