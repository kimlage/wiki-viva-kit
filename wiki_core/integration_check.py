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

SHA = re.compile(r"^[0-9a-f]{40,64}$")
FIELDS = ("number,url,state,author,headRefName,headRefOid,headRepositoryOwner,"
          "baseRefName,baseRefOid,mergeCommit,isDraft,reviewDecision,statusCheckRollup,"
          "reviews,comments,mergeStateStatus,closedAt")


def _field(body: str, key: str) -> str:
    match = re.search(r"(?im)^" + re.escape(key) + r":\s*([^\r\n]+)\s*$", body)
    return match.group(1).strip() if match else ""


def policy(root: Path, base: str) -> dict[str, Any]:
    """Use policy in the observed destination base, never in the candidate."""
    try:
        obj = yaml.safe_load(_blob(root, base, "wiki.config.yaml"))
        approval = obj.get("approval", {}) if isinstance(obj, dict) else None
        if not isinstance(approval, dict):
            return {}
        return approval
    except (ContributionError, yaml.YAMLError, UnicodeError):
        return {}


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
    review = gates = False
    thread = None
    for item in pr.get("comments") or []:
        body = item.get("body", "")
        if not isinstance(body, str):
            continue
        if _field(body, "Head") != head:
            continue
        sender = _field(body, "Executor")
        reviewer = _field(body, "Reviewer")
        decision = _field(body, "Review")
        if (sender and reviewer and sender != reviewer and decision.lower() == "approved"
                and _field(body, "Review-Evidence")):
            review = True
        if _field(body, "Local-Gates").lower() == "passed":
            gates = True
        thread = _field(body, "Responsible-Thread") or thread
    # GitHub native review has a separately authenticated principal.
    author = (pr.get("author") or {}).get("login")
    for item in _latest_reviews(pr):
        reviewer = (item.get("author") or {}).get("login")
        if (author and reviewer and reviewer != author and item.get("state") == "APPROVED"
                and (item.get("commit") or {}).get("oid") == head
                and head in str(item.get("body") or "")):
            review = True
    return review, gates, thread


def evaluate(pr: dict, approval: dict, *, ancestry: str, human_approved: bool) -> dict:
    """Evaluate supplied observations; never execute commands or mutate state."""
    head = pr.get("headRefOid") or ""
    out = {"number": pr.get("number"), "url": pr.get("url"), "head": head,
           "base": pr.get("baseRefOid"), "status": "waiting:observation"}
    review, gates, thread = _comment_evidence(pr, head)
    if thread:
        out["responsible_thread"] = thread
    state = str(pr.get("state", "")).upper()
    if state in {"MERGED", "CLOSED"}:
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
    elif pr.get("baseRefName") != str(approval.get("default_branch") or "main"):
        out["status"] = "fix:wrong_base"
    elif ancestry == "unknown":
        out["status"] = "waiting:local_git_objects"
    elif ancestry != "current":
        out["status"] = "fix:base_outdated"
    elif pr.get("mergeStateStatus") in {"DIRTY", "CONFLICTING"} or pr.get("reviewDecision") == "CHANGES_REQUESTED":
        out["status"] = "fix:conflict_or_changes_requested"
    elif pr.get("isDraft"):
        out["status"] = "waiting:ready_for_review"
    elif not review:
        out["status"] = "waiting:exact_head_review"
    elif approval.get("contribution_validation", "github_checks") == "local_gates":
        # The contribution contract reruns gates on the immutable head; a
        # comment or receipt cannot replace that execution. This reader cannot
        # run it, and explicitly does not treat a claim as a successful gate.
        out["status"] = "waiting:local_gates_at_integration"
    elif approval.get("contribution_validation", "github_checks") == "github_checks" and not pr.get("statusCheckRollup"):
        out["status"] = "waiting:github_checks"
    elif approval.get("contribution_validation", "github_checks") == "github_checks" and any((c.get("conclusion") or c.get("state")) not in {"SUCCESS"} for c in pr.get("statusCheckRollup") or []):
        out["status"] = "waiting:github_checks"
    elif approval.get("require_human_review", False) and not human_approved:
        out["status"] = "waiting:human_review"
    else:
        out["status"] = "integrable"
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
    head = pr.get("headRefOid")
    author = (pr.get("author") or {}).get("login")
    host = repo.split("/", 1)[0]
    for review in _latest_reviews(pr):
        login = (review.get("author") or {}).get("login")
        if not login or login == author or review.get("state") != "APPROVED" or (review.get("commit") or {}).get("oid") != head:
            continue
        try:
            if _gh(root, "api", "--hostname", host, "users/" + login).get("type") == "User":
                return True
        except (ContributionError, ValueError, AttributeError):
            pass
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
        p = subprocess.run(["git", "--no-optional-locks", "status", "--porcelain", "--untracked-files=normal"],
                           cwd=path, text=True, capture_output=True)
        result.append({"path": path, "branch": branch or None,
                       "dirty": bool(p.stdout) if p.returncode == 0 else None})
    return result


def inspect(root: Path, number: int | None = None) -> dict:
    """Read Git and GitHub state. No fetch, checkout, gate execution or writes."""
    root = root.resolve()
    try:
        repo = _repository(root)
        if number is None:
            prs = _gh(root, "pr", "list", "--repo", repo, "--state", "all", "--limit", "1000", "--json", FIELDS)
            if len(prs) >= 1000:
                return {"ok": False, "status": "waiting:proposal_inventory_truncated"}
        else:
            prs = [_gh(root, "pr", "view", str(number), "--repo", repo, "--json", FIELDS)]
        default_line = _git(root, "ls-remote", "--symref", "origin", "HEAD").splitlines()[0]
        if not default_line.startswith("ref: refs/heads/") or not default_line.endswith("\tHEAD"):
            return {"ok": False, "status": "waiting:default_branch"}
        default = default_line.removeprefix("ref: refs/heads/").removesuffix("\tHEAD")
        remote_lines = _git(root, "ls-remote", "--heads", "origin").splitlines()
        remote = {line.split("\t", 1)[1].removeprefix("refs/heads/"): line.split("\t", 1)[0] for line in remote_lines if "\t" in line}
        base = remote.get(default, "")
        approval = policy(root, base) if SHA.fullmatch(base) else {}
        if not approval:
            return {"ok": False, "status": "waiting:destination_policy"}
        proposals = []
        for pr in prs:
            if pr.get("baseRefName") == default and pr.get("baseRefOid") != base:
                ancestry = "unknown"
            else:
                ancestry = _ancestry(root, str(pr.get("baseRefOid") or ""), str(pr.get("headRefOid") or ""))
            proposals.append(evaluate(pr, approval, ancestry=ancestry,
                                      human_approved=_human_review(root, repo, pr) if approval.get("require_human_review") is True else False))
        local = _git(root, "for-each-ref", "--format=%(refname:short)", "refs/heads/").splitlines()
        worktrees = _worktrees(root)
        owner = repo.split("/")[1].lower()
        own = lambda p: str((p.get("headRepositoryOwner") or {}).get("login") or "").lower() == owner
        open_heads = {p.get("headRefName") for p in prs if p.get("state") == "OPEN" and own(p)}
        closed_heads = {p.get("headRefName") for p in prs if p.get("state") == "MERGED" and own(p)} - open_heads
        present = set(local) | set(remote) | {w["branch"] for w in worktrees}
        for pr, observation in zip(prs, proposals):
            if pr.get("state") == "MERGED" and own(pr) and pr.get("headRefName") in closed_heads & present:
                observation["status"] = "fix:merged_branch_or_worktree_remaining"
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
                hygiene.append({"status": "fix:merged_worktree_remaining", **wt})
            elif number is None and wt["branch"] != default and wt["branch"] not in open_heads:
                hygiene.append({"status": "fix:worktree_without_pr", **wt})
        return {"ok": True, "repository": repo, "base": base, "proposals": proposals, "hygiene": hygiene}
    except (ContributionError, OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return {"ok": False, "status": "waiting:observation_unavailable"}
