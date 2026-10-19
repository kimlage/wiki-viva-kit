"""Real synthetic Git recovery, mocked GitHub reads; no live CI claim."""
from __future__ import annotations
import copy
import subprocess
import pytest
import wiki_core.action_contribution as port
from test_action_contribution import fixture, git, call, review, head_review
from wiki_core.web.git_workflows import run_git_workflow
from wiki_core.config import load_config


def recovery(root, monkeypatch, *, state="OPEN"):
    path, request = fixture(root)
    prepared = call(root, "prepare", request, review=review(request))
    assert prepared["ok"], prepared
    remote = root.parent / (root.name + "-remote.git")
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    git(root, "remote", "add", "origin", str(remote))
    git(root, "push", "origin", "main", prepared["branch"])
    pr = {"number": 7, "state": state, "headRefOid": prepared["proposal_commit"],
          "headRefName": prepared["branch"], "baseRefName": "main", "isCrossRepository": False,
          "headRepository": {"name": "wiki"}, "headRepositoryOwner": {"login": "synthetic"},
          "mergeCommit": {"oid": prepared["proposal_commit"]} if state == "MERGED" else None}
    responses = {"list": [{"number": 7, "headRefOid": prepared["proposal_commit"]}], "pr": pr}
    monkeypatch.setattr(port, "_repository", lambda *_: "example.test/synthetic/wiki")
    def gh(_root, *args):
        assert args[:2] in {("pr", "list"), ("pr", "view")}, args
        assert args[args.index("--repo")+1] == "example.test/synthetic/wiki"
        return copy.deepcopy(responses["list"] if args[1] == "list" else responses["pr"])
    monkeypatch.setattr(port, "_gh", gh)
    commands = []
    original = port._run
    def observe(_root, *args, **kwargs):
        commands.append(args)
        assert args[:2] != ("git", "push"), args
        assert args[:3] not in {("gh", "pr", "create"), ("gh", "pr", "merge")}, args
        if args[:2] == ("git", "update-ref"):
            assert args[2] == "-d" and args[3].startswith("refs/wiki/contribution-read/"), args
        assert args[:2] not in {("git", "checkout"), ("git", "switch"), ("git", "reset")}, args
        return original(_root, *args, **kwargs)
    monkeypatch.setattr(port, "_run", observe)
    return path, request, prepared, remote, responses, commands


def retained(root):
    return (git(root, "for-each-ref", "--format=%(refname) %(objectname)"),
            git(root, "status", "--porcelain"), git(root, "rev-parse", "HEAD"))


def test_discovers_lost_local_ref_and_pr_from_frozen_request(tmp_path, monkeypatch):
    path, req, out, _, _, commands = recovery(tmp_path, monkeypatch)
    git(tmp_path, "update-ref", "-d", "refs/heads/" + out["branch"])
    before, source = retained(tmp_path), path.read_bytes()
    (tmp_path/".git/FETCH_HEAD").write_text("synthetic retained fetch state\n")
    result = call(tmp_path, "reconcile", req)
    assert result["status"] == "waiting_pr" and result["proposal_commit"] == out["proposal_commit"], result
    assert result["pr"]["number"] == 7 and result["proposal_validated"]
    assert retained(tmp_path) == before and path.read_bytes() == source
    assert (tmp_path/".git/FETCH_HEAD").read_text() == "synthetic retained fetch state\n"
    assert not git(tmp_path, "for-each-ref", "refs/wiki/contribution-read/")
    assert any("--no-tags" in c and "--refmap=" in c for c in commands)


def test_deleted_branch_after_merge_uses_exact_pull_ref_and_distinguishes_adoption(tmp_path, monkeypatch):
    path, req, out, remote, _, commands = recovery(tmp_path, monkeypatch, state="MERGED")
    git(tmp_path, "push", "origin", out["proposal_commit"] + ":refs/heads/main",
        out["proposal_commit"] + ":refs/pull/7/head")
    git(remote, "update-ref", "-d", "refs/heads/"+out["branch"])
    git(tmp_path, "update-ref", "-d", "refs/heads/"+out["branch"])
    before = retained(tmp_path)
    result = call(tmp_path, "reconcile", req)
    assert result["remote_merged"] and result["source_commit"] == out["proposal_commit"], result
    assert result["status"] == "waiting_worktree_adoption" and not result["canonical_body_adopted"]
    assert not result["served_adoption_verified"] and "Original evidence." in path.read_text()
    assert retained(tmp_path) == before
    assert any(any(x.startswith("refs/pull/7/head:") for x in cmd) for cmd in commands)


@pytest.mark.parametrize("published", [False, True])
def test_no_pr_reports_retained_proposal_without_repeating_publication(tmp_path, monkeypatch, published):
    _, req, out, remote, responses, _ = recovery(tmp_path, monkeypatch)
    responses["list"] = []
    if not published:
        git(remote, "update-ref", "-d", "refs/heads/"+out["branch"])
    before = retained(tmp_path)
    result = call(tmp_path, "reconcile", req)
    assert result["status"] == ("published_ref_no_pr_observed" if published else "prepared_ref_no_pr_observed"), result
    assert result["proposal_validated"] and not result["canonical_body_adopted"]
    assert retained(tmp_path) == before


def test_missing_all_retained_refs_is_unknown_never_absence_of_effect(tmp_path, monkeypatch):
    _, req, out, remote, responses, _ = recovery(tmp_path, monkeypatch)
    responses["list"] = []
    git(remote, "update-ref", "-d", "refs/heads/"+out["branch"])
    git(tmp_path, "update-ref", "-d", "refs/heads/"+out["branch"])
    result = call(tmp_path, "reconcile", req)
    assert result["status"] == "unknown" and result["error"] == "contribution_effect_not_observed"
    assert "no absence-of-effect guarantee" in result["discovery"]["coverage"]


@pytest.mark.parametrize("count", [2, 100])
def test_ambiguous_pr_results_never_select_first_or_newest(tmp_path, monkeypatch, count):
    _, req, _, _, responses, _ = recovery(tmp_path, monkeypatch)
    responses["list"] *= count
    before = retained(tmp_path)
    result = call(tmp_path, "reconcile", req)
    assert result["error"] == "pr_discovery_ambiguous" and not result["ok"]
    assert retained(tmp_path) == before


@pytest.mark.parametrize("field,value", [("headRefName", "wiki/other"), ("baseRefName", "other"),
    ("isCrossRepository", True), ("headRepository", {"name":"different"}),
    ("headRepositoryOwner", {"login":"someone"}), ("headRepositoryOwner", []),
    ("headRefOid", "0"*40)])
@pytest.mark.parametrize("explicit", [False, True])
def test_identity_conflicts_are_refused_with_or_without_pr_number(tmp_path, monkeypatch, field, value, explicit):
    _, req, _, _, responses, _ = recovery(tmp_path, monkeypatch)
    responses["pr"][field] = value
    result = call(tmp_path, "reconcile", req, **({"pr":7} if explicit else {}))
    assert result["error"] in {"pr_identity_conflict", "proposal_ref_identity_conflict"}, result
    assert not result["ok"] and not result["canonical_body_adopted"]


def test_present_divergent_branch_is_not_ignored(tmp_path, monkeypatch):
    _, req, out, remote, _, _ = recovery(tmp_path, monkeypatch)
    git(remote, "update-ref", "refs/heads/"+out["branch"], git(tmp_path,"rev-parse","HEAD"))
    result = call(tmp_path, "reconcile", req)
    assert result["error"] == "proposal_ref_identity_conflict"


def test_recovery_anchors_candidate_to_fresh_canonical_not_stale_tracking_ref(tmp_path, monkeypatch):
    _, req, out, remote, _, _ = recovery(tmp_path, monkeypatch)
    # No local candidate and no local/tracking approved ref; the selected
    # checkout still retains the request base. Only remote source anchors it.
    git(tmp_path, "update-ref", "-d", "refs/heads/"+out["branch"])
    git(tmp_path, "update-ref", "-d", "refs/remotes/origin/main")
    git(tmp_path, "switch", "--detach")
    git(tmp_path, "update-ref", "-d", "refs/heads/main")
    result = call(tmp_path, "reconcile", req)
    assert result["status"] == "waiting_pr" and result["proposal_validated"], result
    assert not git(tmp_path, "for-each-ref", "refs/heads/")


@pytest.mark.parametrize("field", ["body", "log", "review"])
def test_recovered_candidate_revalidates_actual_bytes(tmp_path, monkeypatch, field):
    path, req, out, _, responses, _ = recovery(tmp_path, monkeypatch)
    git(tmp_path, "switch", out["branch"])
    if field == "body":
        path.write_text(path.read_text().replace("Reviewed historical evidence.", "Unreviewed new evidence."))
    elif field == "log":
        log=tmp_path/"memories/system/log.md"; log.write_text(log.read_text()+"Unexpected log write\n")
    else:
        path.write_text(path.read_text().replace("independent-session", "author-session"))
    git(tmp_path, "add", ".");git(tmp_path, "commit", "--amend", "--no-edit")
    changed=git(tmp_path,"rev-parse","HEAD")
    git(tmp_path,"push","--force","origin",out["branch"])
    git(tmp_path,"switch","main");git(tmp_path,"update-ref","-d","refs/heads/"+out["branch"])
    responses["list"][0]["headRefOid"]=changed;responses["pr"]["headRefOid"]=changed
    result=call(tmp_path,"reconcile",req)
    assert not result["ok"] and not result["canonical_body_adopted"], result
    assert not git(tmp_path,"for-each-ref","refs/wiki/contribution-read/")


def test_failed_merged_readback_keeps_observed_merge(tmp_path, monkeypatch):
    _, req, out, _, _, _ = recovery(tmp_path, monkeypatch,state="MERGED")
    def fail(*args,**kwargs):raise port.ContributionError("readback_unknown")
    monkeypatch.setattr(port,"_canonical_readback",fail)
    result=call(tmp_path,"reconcile",req)
    assert result["status"]=="unknown" and result["remote_merged"] and result["source_commit"]==out["proposal_commit"]
    assert not result["canonical_body_adopted"]


def test_closed_unmerged_pr_is_observed_without_reopening(tmp_path, monkeypatch):
    _,req,_,_,_,_=recovery(tmp_path,monkeypatch,state="CLOSED")
    result=call(tmp_path,"reconcile",req)
    assert result["status"]=="closed_unmerged_pr" and result["pr_state"]=="CLOSED"


@pytest.mark.parametrize("failure", ["changed_head", "after_fetch"])
def test_fetch_race_or_failure_never_leaves_temporary_or_permanent_refs(tmp_path, monkeypatch, failure):
    _, req, out, remote, _, _ = recovery(tmp_path, monkeypatch)
    git(tmp_path,"update-ref","-d","refs/heads/"+out["branch"])
    git(remote,"update-ref","refs/tags/remote-only",out["proposal_commit"])
    before=retained(tmp_path)
    actual=port._git
    def interrupted(root,*args):
        chosen=args[0]=="fetch" and any(x.startswith("refs/heads/"+out["branch"]+":") for x in args)
        if chosen and failure=="changed_head":
            git(remote,"update-ref","refs/heads/"+out["branch"],req["files"][0]["base_commit"])
        value=actual(root,*args)
        if chosen and failure=="after_fetch":raise port.ContributionError("command_outcome_unknown")
        return value
    monkeypatch.setattr(port,"_git",interrupted)
    result=call(tmp_path,"reconcile",req)
    assert result["error"] == ("discovered_ref_identity_changed" if failure=="changed_head" else "contribution_object_observation_unknown"),result
    assert retained(tmp_path)==before
    assert not git(tmp_path,"for-each-ref","refs/wiki/contribution-read/")
    assert not git(tmp_path,"for-each-ref","refs/tags/")


def test_pr_change_after_object_read_is_not_accepted_as_atomic_observation(tmp_path, monkeypatch):
    _,req,_,_,responses,_=recovery(tmp_path,monkeypatch)
    original=port._pr
    calls=0
    def changed(*args):
        nonlocal calls
        calls+=1
        if calls==2:responses["pr"]["headRefName"]="wiki/changed"
        return original(*args)
    monkeypatch.setattr(port,"_pr",changed)
    result=call(tmp_path,"reconcile",req)
    assert result["error"]=="pr_identity_changed_during_reconciliation"
    assert not result["canonical_body_adopted"]


@pytest.mark.parametrize("failure",["github","remote","canonical"])
def test_unavailable_evidence_is_unknown_without_replaying_effect(tmp_path, monkeypatch, failure):
    _,req,_,_,_,_=recovery(tmp_path,monkeypatch)
    if failure=="github":
        def fail(*args):raise port.ContributionError("command_failed:gh")
        monkeypatch.setattr(port,"_gh",fail)
    elif failure=="canonical":
        def fail(*args):raise port.ContributionError("command_failed:git")
        monkeypatch.setattr(port,"_fetch_canonical",fail)
    else:
        def fail(*args):raise subprocess.TimeoutExpired("git",120)
        monkeypatch.setattr(port,"_remote_branch",fail)
    before=retained(tmp_path)
    result=call(tmp_path,"reconcile",req)
    assert result["status"]=="unknown" and not result["ok"],result
    assert retained(tmp_path)==before
    assert not git(tmp_path,"for-each-ref","refs/wiki/contribution-read/")


def test_readback_after_disjoint_remote_advance_uses_real_two_parent_merge(tmp_path, monkeypatch):
    _,req,out,remote,responses,_=recovery(tmp_path,monkeypatch,state="MERGED")
    other=tmp_path.parent/(tmp_path.name+"-other")
    subprocess.run(["git","clone","-b","main",str(remote),str(other)],check=True,capture_output=True)
    git(other,"config","user.name","Synthetic peer");git(other,"config","user.email","peer@example.test")
    (other/"disjoint.md").write_text("Independent canonical advance\\n")
    git(other,"add",".");git(other,"commit","-m","Disjoint advance")
    git(other,"merge","--no-ff","origin/"+out["branch"],"-m","Merge reviewed contribution")
    merged=git(other,"rev-parse","HEAD")
    assert len(git(other,"rev-list","--parents","-1",merged).split())==3
    git(other,"push","origin","main")
    responses["pr"]["mergeCommit"]={"oid":merged}
    stale=git(tmp_path,"rev-parse","refs/remotes/origin/main")
    result=call(tmp_path,"reconcile",req)
    assert result["status"]=="waiting_worktree_adoption" and result["remote_merged"],result
    assert result["source_commit"]==merged and result["canonical_matches_material"]
    assert git(tmp_path,"rev-parse","refs/remotes/origin/main")==stale


@pytest.mark.parametrize("bad",["missing","wrong_head","self_review","blocking"])
def test_material_review_and_green_ci_cannot_replace_generated_head_review(tmp_path, monkeypatch, bad):
    _,req,out,_,responses,commands=recovery(tmp_path,monkeypatch)
    responses["pr"]["statusCheckRollup"]=[{"conclusion":"SUCCESS"}]
    report=head_review(req,out["proposal_commit"])
    if bad=="wrong_head":report["proposal_commit"]="0"*40
    if bad=="self_review":report["reviewer_session_id"]=req["session_ref"]["session_id"]
    if bad=="blocking":report["report"]["findings"]=[{"blocking":True}]
    result=call(tmp_path,"integrate",req,pr=7,**({} if bad=="missing" else {"head_review":report}))
    assert result["status"]=="refused",result
    assert result["error"] in {"exact_generated_head_review_required","independent_reviewer_required","review_not_approved"}
    assert not any(c[:3]==("gh","pr","merge") for c in commands)


def test_dry_run_prepare_checks_review_and_sources_without_gates_or_ref_installation(tmp_path,monkeypatch):
    _,req=fixture(tmp_path)
    before=retained(tmp_path)
    def fail(*args,**kwargs):pytest.fail("dry run invoked gates")
    monkeypatch.setattr(port,"_gates",fail)
    missing=run_git_workflow(tmp_path,load_config(tmp_path),"prepare_contribution",{"request":req},dry_run=True)
    assert not missing["ok"] and missing["error"]=="exact_material_review_required"
    valid=run_git_workflow(tmp_path,load_config(tmp_path),"prepare_contribution",{"request":req,"review":review(req)},dry_run=True)
    assert valid["ok"] and valid["dry_run"] and valid["gates_not_run"]
    assert valid["validation_status"]=="ready_to_prepare" and retained(tmp_path)==before


@pytest.mark.parametrize("op",["publish","integrate"])
def test_dry_run_requires_prepared_candidate(tmp_path,op):
    _,req=fixture(tmp_path)
    result=run_git_workflow(tmp_path,load_config(tmp_path),op+"_contribution",{"request":req},dry_run=True)
    assert not result["ok"] and result["error"]=="prepare_required"


def test_dry_run_integration_validates_exact_head_without_fetch_or_merge(tmp_path,monkeypatch):
    _,req,out,_,responses,commands=recovery(tmp_path,monkeypatch)
    responses["pr"]["statusCheckRollup"]=[{"conclusion":"SUCCESS"}]
    before=retained(tmp_path)
    result=run_git_workflow(tmp_path,load_config(tmp_path),"integrate_contribution",
        {"request":req,"pr":7,"head_review":head_review(req,out["proposal_commit"])},dry_run=True)
    assert result["ok"] and result["validation_status"]=="ready_to_integrate",result
    assert result["head_review"]["proposal_commit"]==out["proposal_commit"]
    assert not any(c[:2]==("git","fetch") for c in commands)
    assert retained(tmp_path)==before


def test_dry_run_recovery_observes_retained_evidence_without_fetch(tmp_path,monkeypatch):
    _,req,_,_,_,commands=recovery(tmp_path,monkeypatch)
    before=retained(tmp_path)
    result=run_git_workflow(tmp_path,load_config(tmp_path),"reconcile_contribution",{"request":req},dry_run=True)
    assert result["ok"] and result["dry_run"] and result["status"]=="waiting_pr",result
    assert not any(c[:2]==("git","fetch") for c in commands)
    assert retained(tmp_path)==before


@pytest.mark.parametrize("stage",["list","first_pr","second_pr"])
def test_malformed_github_json_is_unknown_remote_observation(tmp_path,monkeypatch,stage):
    _,req,_,_,_,_=recovery(tmp_path,monkeypatch)
    actual=port._gh
    pr_reads=0
    def malformed(root,*args):
        nonlocal pr_reads
        if args[1]=="view":pr_reads+=1
        if ((stage=="list" and args[1]=="list") or
            (stage=="first_pr" and pr_reads==1) or (stage=="second_pr" and pr_reads==2)):
            raise ValueError("synthetic truncated JSON")
        return actual(root,*args)
    monkeypatch.setattr(port,"_gh",malformed)
    result=call(tmp_path,"reconcile",req)
    assert result["status"]=="unknown" and result["error"] in {"pr_discovery_unknown","pr_observation_unknown"},result


@pytest.mark.parametrize("response",[None,[],3,"incomplete"])
@pytest.mark.parametrize("explicit",[False,True])
def test_invalid_pr_view_shape_is_unknown_not_no_pr_observed(tmp_path,monkeypatch,response,explicit):
    _,req,_,_,responses,_=recovery(tmp_path,monkeypatch)
    responses["pr"]=response
    result=call(tmp_path,"reconcile",req,**({"pr":7} if explicit else {}))
    assert result["status"]=="unknown" and result["error"]=="pr_observation_unknown",result
    assert not result["ok"]
