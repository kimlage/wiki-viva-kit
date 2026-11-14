"""Read-only observations for proposal integration and Git lifecycle hygiene.

A result is advisory. It is not an authorization, a gate run or proof of a
runtime identity. Only an explicit, exact-head handoff can supply local evidence.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

from wiki_core.action_contribution import ContributionError, _blob, _gh, _git, _repository
from wiki_core.action_transition import ActionTransitionError, _assert_no_secrets

SHA = re.compile(r"^[0-9a-f]{40,64}$")
FIELDS = ("number,url,state,author,headRefName,headRefOid,headRepositoryOwner,"
          "baseRefName,baseRefOid,mergeCommit,isDraft,reviewDecision,statusCheckRollup,"
          "reviews,comments,mergeStateStatus,closedAt")


def _field(body: str, key: str) -> str:
    match = re.search(r"(?im)^" + re.escape(key) + r":\s*([^\r\n]+)\s*$", body)
    return match.group(1).strip() if match else ""


def policy(root: Path, base: str) -> dict[str, Any] | None:
    """Use policy in the observed destination base, never in the candidate."""
    try:
        obj = yaml.safe_load(_blob(root, base, "wiki.config.yaml"))
        approval = obj.get("approval", {}) if isinstance(obj, dict) else None
        if not isinstance(approval, dict):
            return None
        return approval
    except (ContributionError, yaml.YAMLError, UnicodeError):
        return None


def _thread_ref(value: str) -> str | None:
    # Provider data is untrusted. Only bounded thread identifiers, never free
    # text, terminal control sequences, credentials or arbitrary URLs.
    if not re.fullmatch(r"(?:thread:[A-Za-z0-9:%_-]{1,220}|mcp:launch:[0-9a-f]{64}|[0-9a-f]{8}-[0-9a-f-]{27,36})", value):
        return None
    try:
        _assert_no_secrets(value)
    except ActionTransitionError:
        return None
    return value


def _latest_reviews(pr: dict) -> list[dict]:
    # GitHub returns review history, not just current decisions. A later
    # dismissal or change request from the same principal supersedes approval.
    latest: dict[str, dict] = {}
    for review in pr.get("reviews") or []:
        login = (review.get("author") or {}).get("login")
        if login:
            latest[login] = review
    return list(latest.values())


def _comment_evidence(pr: dict, head: str) -> tuple[bool, bool, str | None]:
    decisions: dict[str, str] = {}
    thread = None
    author = (pr.get("author") or {}).get("login")
    for item in pr.get("comments") or []:
        body = item.get("body", "")
        if not isinstance(body, str) or _field(body, "Head") != head:
            continue
        commenter = (item.get("author") or {}).get("login")
        decision = _field(body, "Review").lower().replace(" ", "_")
        if author and commenter and commenter != author and decision in {"approved", "rejected", "changes_requested", "blocked"}:
            decisions[commenter] = decision
        thread = _thread_ref(_field(body, "Responsible-Thread")) or thread
    native_decisions: dict[str, str] = {}
    for item in _latest_reviews(pr):
        reviewer = (item.get("author") or {}).get("login")
        if (author and reviewer and reviewer != author
                and (item.get("commit") or {}).get("oid") == head
                and head in str(item.get("body") or "")):
            decision = str(item.get("state") or "").lower()
            if decision in {"approved", "changes_requested"}:
                native_decisions[reviewer] = decision
    all_decisions = list(decisions.values()) + list(native_decisions.values())
    blocked = any(x in {"rejected", "changes_requested", "blocked"} for x in all_decisions)
    return "approved" in all_decisions, blocked, thread


def evaluate(pr: dict, approval: dict, *, ancestry: str, human_approved: bool) -> dict:
    """Evaluate supplied observations; never execute commands or mutate state."""
    head = pr.get("headRefOid") or ""
    out = {"number": pr.get("number"), "url": pr.get("url"), "head": head,
           "base": pr.get("baseRefOid"), "status": "waiting:observation"}
    review, review_blocked, thread = _comment_evidence(pr, head)
    if thread:
        out["responsible_thread"] = thread
    state = str(pr.get("state", "")).upper()
    if state in {"MERGED", "CLOSED"}:
        out["action_reconciliation"] = "unverified"
        out["status"] = "done" if state == "MERGED" else "waiting:closure_reason"
        if state == "CLOSED":
            reasons = [str(c.get("body") or "") for c in pr.get("comments") or []]
            out["status"] = ("done" if any(re.search(r"(?im)^(?:Disposition-Reason|Motivo(?: do descarte)?|Reason for (?:closure|discard))\s*:\s*\S", b) for b in reasons)
                             else "waiting:verify_closure_reason" if reasons else "fix:closure_reason_missing")
        return out
    if state != "OPEN" or not SHA.fullmatch(head) or not SHA.fullmatch(str(pr.get("baseRefOid") or "")):
        return out
    if approval.get("gate", "github_pr") != "github_pr":
        out["status"] = "waiting:policy_adapter"
    elif approval.get("contribution_validation", "github_checks") not in {"github_checks", "local_gates"} or not isinstance(approval.get("require_human_review", False), bool):
        out["status"] = "waiting:policy_adapter"
    elif (approval.get("contribution_validation", "github_checks") == "local_gates"
          and (not isinstance(approval.get("contribution_gates", []), list)
               or any(not isinstance(gate, list) or not gate
                      or any(not isinstance(arg, str) or not arg for arg in gate)
                      for gate in approval.get("contribution_gates", [])))):
        out["status"] = "fix:invalid_policy_gates"
    elif pr.get("baseRefName") != str(approval.get("default_branch") or "main"):
        out["status"] = "fix:wrong_base"
    elif ancestry == "unknown":
        out["status"] = "waiting:local_git_objects"
    elif ancestry != "current":
        out["status"] = "fix:base_outdated"
    elif pr.get("mergeStateStatus") in {"DIRTY", "CONFLICTING"} or pr.get("reviewDecision") == "CHANGES_REQUESTED" or review_blocked:
        out["status"] = "fix:conflict_or_changes_requested"
    else:
        pending = []
        if pr.get("isDraft"):
            pending.append("ready_for_review")
        if not review:
            pending.append("exact_head_review")
        if pr.get("mergeStateStatus") in {"BLOCKED", "UNKNOWN", None} or pr.get("reviewDecision") == "REVIEW_REQUIRED":
            pending.append("github_mergeability")
        checks = pr.get("statusCheckRollup") or []
        if (approval.get("contribution_validation", "github_checks") == "github_checks" and not checks) or any((c.get("conclusion") or c.get("state")) != "SUCCESS" for c in checks):
            pending.append("github_checks")
        if approval.get("require_human_review", False) and not human_approved:
            pending.append("human_review_identity")
        if approval.get("contribution_validation", "github_checks") == "local_gates":
            # Integration must run these; they have not been observed passing.
            out["required_at_integration"] = ["run_local_gates_on_exact_head"]
        out["status"] = "waiting:" + pending[0] if pending else "integrable"
        if pending:
            out["pending"] = pending

    return out


def _ancestry(root: Path, base: str, head: str) -> str:
    if not SHA.fullmatch(base) or not SHA.fullmatch(head):
        return "unknown"
    for sha in (base, head):
        if subprocess.run(["git", "cat-file", "-e", sha + "^{commit}"], cwd=root,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
            return "unknown"
    p = subprocess.run(["git", "merge-base", "--is-ancestor", base, head], cwd=root,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return "current" if p.returncode == 0 else "outdated" if p.returncode == 1 else "unknown"


def _human_review(root: Path, repo: str, pr: dict) -> bool:
    # A GitHub account of type User may be shared with an automated agent. The
    # provider does not attest who operated it, so this adapter cannot prove a
    # human approval. A future adapter may supply a stronger observation.
    return False


def _worktrees(root: Path) -> list[dict]:
    records = _git(root, "worktree", "list", "--porcelain").split("\n\n")
    result = []
    for record in records:
        fields = dict(line.split(" ", 1) for line in record.splitlines() if " " in line)
        path = fields.get("worktree")
        if not path:
            continue
        branch = fields.get("branch", "").removeprefix("refs/heads/")
        try:
            p = subprocess.run(["git", "--no-optional-locks", "status", "--porcelain", "--untracked-files=normal"],
                               cwd=path, text=True, capture_output=True)
            dirty = bool(p.stdout) if p.returncode == 0 else None
        except OSError:
            dirty = None
        result.append({"path": path, "branch": branch or None, "head": fields.get("HEAD"), "dirty": dirty})
    return result


def inspect(root: Path, number: int | None = None) -> dict:
    """Read Git and GitHub state. No fetch, checkout, gate execution or writes."""
    root = root.resolve()
    try:
        repo = _repository(root)
        default_lines = _git(root, "ls-remote", "--symref", "origin", "HEAD").splitlines()
        if not default_lines:
            return {"ok": False, "status": "waiting:default_branch"}
        default_line = default_lines[0]
        if not default_line.startswith("ref: refs/heads/") or not default_line.endswith("\tHEAD"):
            return {"ok": False, "status": "waiting:default_branch"}
        default = default_line.removeprefix("ref: refs/heads/").removesuffix("\tHEAD")
        remote_lines = _git(root, "ls-remote", "--heads", "origin").splitlines()
        remote = {line.split("\t", 1)[1].removeprefix("refs/heads/"): line.split("\t", 1)[0] for line in remote_lines if "\t" in line}
        base = remote.get(default, "")
        default_policy = policy(root, base) if SHA.fullmatch(base) else None
        if default_policy is not None and default_policy.get("gate", "github_pr") != "github_pr":
            return {"ok": False, "status": "waiting:policy_adapter"}
        if number is None:
            prs = _gh(root, "pr", "list", "--repo", repo, "--state", "all", "--limit", "1000", "--json", FIELDS)
            if len(prs) >= 1000:
                return {"ok": False, "status": "waiting:proposal_inventory_truncated"}
        else:
            prs = [_gh(root, "pr", "view", str(number), "--repo", repo, "--json", FIELDS)]
        owner = repo.split("/")[1].lower()
        own = lambda p: str((p.get("headRepositoryOwner") or {}).get("login") or "").lower() == owner
        proposals = []
        for pr in prs:
            target_base = remote.get(str(pr.get("baseRefName") or ""), "")
            approval = policy(root, target_base) if SHA.fullmatch(target_base) else None
            if pr.get("state") in {"MERGED", "CLOSED"}:
                proposals.append(evaluate(pr, {}, ancestry="unknown", human_approved=False))
                continue
            if approval is None:
                proposals.append({"number": pr.get("number"), "url": pr.get("url"),
                                  "head": pr.get("headRefOid"), "base": pr.get("baseRefOid"),
                                  "status": "waiting:destination_policy"})
                continue
            if not own(pr) or remote.get(str(pr.get("headRefName") or "")) != pr.get("headRefOid"):
                proposals.append({"number": pr.get("number"), "url": pr.get("url"),
                                  "head": pr.get("headRefOid"), "base": pr.get("baseRefOid"),
                                  "status": "waiting:head_observation"})
                continue
            if pr.get("baseRefOid") != target_base:
                ancestry = "unknown"
            else:
                ancestry = _ancestry(root, target_base, str(pr.get("headRefOid") or ""))
            proposals.append(evaluate(pr, approval, ancestry=ancestry,
                                      human_approved=_human_review(root, repo, pr) if approval.get("require_human_review") is True else False))
        local = _git(root, "for-each-ref", "--format=%(refname:short)", "refs/heads/").splitlines()
        worktrees = _worktrees(root)
        open_heads = {p.get("headRefName") for p in prs if p.get("state") == "OPEN" and own(p)}
        closed_heads = {p.get("headRefName") for p in prs if p.get("state") == "MERGED" and own(p)} - open_heads
        present = set(local) | set(remote) | {w["branch"] for w in worktrees}
        for pr, observation in zip(prs, proposals):
            if pr.get("state") == "MERGED" and own(pr) and pr.get("headRefName") in closed_heads & present:
                observation["status"] = ("waiting:verify_branch_reuse" if number is not None
                                         else "fix:merged_branch_or_worktree_remaining")
            if pr.get("state") == "MERGED" and any(w.get("branch") is None and w.get("head") == pr.get("headRefOid") for w in worktrees):
                observation["status"] = "waiting:verify_detached_worktree"
        # A filtered PR view cannot establish global inventory safely.
        hygiene = []
        if number is None:
            for branch in local:
                if branch != default and branch not in open_heads:
                    hygiene.append({"status": "fix:merged_branch_remaining" if branch in closed_heads else "fix:local_branch_without_pr", "branch": branch})
            for branch in remote:
                if branch != default and branch not in open_heads:
                    hygiene.append({"status": "fix:merged_branch_remaining" if branch in closed_heads else "fix:remote_branch_without_pr", "branch": branch})
        for wt in worktrees:
            if wt["dirty"] is None:
                hygiene.append({"status": "waiting:worktree_status", **wt})
            elif wt["dirty"]:
                hygiene.append({"status": "fix:dirty_worktree", **wt})
            elif wt["branch"] in closed_heads:
                hygiene.append({"status": "waiting:verify_branch_reuse" if number is not None
                                else "fix:merged_worktree_remaining", **wt})
            elif number is None and wt["branch"] != default and wt["branch"] not in open_heads:
                hygiene.append({"status": "fix:worktree_without_pr", **wt})
        return {"ok": True, "repository": repo, "base": base, "proposals": proposals, "hygiene": hygiene}
    except (ContributionError, OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return {"ok": False, "status": "waiting:observation_unavailable"}
