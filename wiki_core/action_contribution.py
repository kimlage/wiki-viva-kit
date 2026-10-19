"""Provider-neutral action-body proposals over Git and the canonical writer.

No worker, task database, authority grant or transcript store. Callers are
trusted local operators. GitHub is used only when the consumer selects its PR
policy; material/review input is never interpreted as human or CI approval.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from wiki_core.action_transition import (
    ActionTransitionError, _action_file_lock, _assert_no_secrets,
    _contained_action_path, _parse_document, integrate_action_body,
    action_transition_diagnostics, _SUPPORT_FIELDS,
)
from wiki_core.config import WikiConfig, load_config

SCHEMA = "wiki_action_contribution.v1"
OPERATIONS = frozenset({"prepare_contribution", "publish_contribution", "integrate_contribution", "reconcile_contribution"})


class ContributionError(ValueError):
    """Safe refusal; never expose raw subprocess output or source material."""


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _run(root: Path, *argv: str, timeout: int = 120) -> str:
    try:
        p = subprocess.run(argv, cwd=root, text=True, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ContributionError("command_outcome_unknown: reconcile before retry") from exc
    if p.returncode:
        raise ContributionError("command_failed:" + argv[0])
    return p.stdout.strip()


def _git(root: Path, *argv: str) -> str:
    return _run(root, "git", *argv)


def _blob(root: Path, revision: str, path: str) -> str:
    # Do not strip terminal newlines: these hashes bind the actual bytes.
    p = subprocess.run(["git", "show", f"{revision}:{path}"], cwd=root, capture_output=True)
    if p.returncode:
        raise ContributionError("source_blob_unavailable")
    return p.stdout.decode("utf-8")


def _string(value: Any, label: str, limit: int = 1000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\x00" in value:
        raise ContributionError("invalid_" + label)
    return value


def _request(config: WikiConfig, request: dict[str, Any]) -> tuple[str, str, str]:
    if not isinstance(request, dict) or request.get("schema_version") != SCHEMA:
        raise ContributionError("unsupported_contribution")
    task = request.get("task_ref")
    if not isinstance(task, dict) or task.get("repo_id") != config.repo_id:
        raise ContributionError("task_repo_mismatch")
    _string(task.get("action_id"), "action_id")
    run, session = request.get("run_ref"), request.get("session_ref")
    if not isinstance(run, dict) or not isinstance(session, dict):
        raise ContributionError("missing_run_or_session_ref")
    for field in ("runtime", "task_id", "run_id"):
        _string(run.get(field), field)
    _string(session.get("session_id"), "session_id")
    _string(session.get("coverage"), "history_coverage", 2000)
    files = request.get("files")
    if not isinstance(files, list) or len(files) != 1 or not isinstance(files[0], dict):
        raise ContributionError("one_existing_action_only")
    item = files[0]
    path = _string(item.get("path"), "path")
    text = _string(item.get("text"), "text", 500_000)
    if item.get("sha256") != _sha(text):
        raise ContributionError("material_file_hash_mismatch")
    key = _string(request.get("effect_key"), "effect_key", 200)
    material = digest({k: v for k, v in request.items() if k != "material_sha256"})
    if request.get("material_sha256", material) != material:
        raise ContributionError("material_hash_mismatch")
    _assert_no_secrets(json.dumps(request, ensure_ascii=False))
    branch = "wiki/contribution-" + digest({"task": task, "effect_key": key})[:32]
    return path, material, branch


def _review(request: dict[str, Any], material: str, review: Any) -> dict[str, Any]:
    if not isinstance(review, dict) or review.get("material_sha256") != material:
        raise ContributionError("exact_material_review_required")
    reviewer = _string(review.get("reviewer_session_id"), "reviewer_session_id")
    if reviewer == request["session_ref"]["session_id"]:
        raise ContributionError("independent_reviewer_required")
    _string(review.get("evidence_ref"), "review_evidence_ref")
    report = review.get("report")
    if (review.get("decision") != "approved" or not isinstance(report, dict)
        or not isinstance(report.get("criteria"), list) or not report["criteria"]
        or any(not isinstance(c, str) or not c.strip() for c in report["criteria"])
        or report.get("findings") != []):
        raise ContributionError("review_not_approved")
    _assert_no_secrets(json.dumps(review, ensure_ascii=False))
    return review


def _entry(root: Path, commit: str, path: str, request: dict, material: str) -> tuple[dict, str]:
    parent = _git(root, "rev-parse", commit + "^")
    branch = str(load_config(root).approval.get("default_branch") or "main")
    approved = _candidate_ref(root, f"refs/remotes/origin/{branch}") or _candidate_ref(root, f"refs/heads/{branch}")
    if not approved:
        raise ContributionError("approved_base_unavailable")
    _git(root, "merge-base", "--is-ancestor", parent, approved)
    if _git(root, "diff", "--name-only", parent, commit).splitlines() != [path]:
        raise ContributionError("proposal_exceeds_one_action_body")
    text = _blob(root, commit, path)
    fm, _ = _parse_document(text)
    history = fm.get("action_state_history") or []
    if not isinstance(history, list) or any(not isinstance(e, dict) for e in history):
        raise ContributionError("invalid_action_history")
    found = [e for e in history if e.get("kind") == "body_integration"
             and isinstance(e.get("contribution"), dict)
             and e["contribution"].get("effect_key") == request["effect_key"]]
    if len(found) != 1 or fm.get("page_id") != request["task_ref"]["action_id"]:
        raise ContributionError("contribution_receipt_missing")
    entry = found[0]
    if entry["contribution"]["material_sha256"] != material:
        raise ContributionError("effect_key_conflict")
    return entry, text


def _gates(root: Path, config: WikiConfig) -> list[dict]:
    commands = [
        [sys.executable, "scripts/wiki_audit.py", "--check"],
        [sys.executable, "scripts/wiki_input_stage.py", "--check"],
        [sys.executable, "scripts/wiki_pr_summary.py"],
        ["git", "diff", "--check"],
    ]
    extra = config.approval.get("contribution_gates", [])
    if not isinstance(extra, list) or any(not isinstance(c, list) or not c or
            any(not isinstance(x, str) or not x for x in c) for c in extra):
        raise ContributionError("invalid_policy_gates")
    results = []
    for command in [*commands, *extra]:
        try:
            p = subprocess.run(command, cwd=root, capture_output=True, timeout=600)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ContributionError("gate_unavailable") from exc
        results.append({"argv": command, "exit_code": p.returncode,
                        "output_sha256": hashlib.sha256(p.stdout + p.stderr).hexdigest()})
        if p.returncode:
            raise ContributionError("proposal_gate_failed:" + Path(command[0]).name)
    return results


def _candidate(root: Path, branch: str) -> str | None:
    return _candidate_ref(root, f"refs/heads/{branch}")


def _candidate_ref(root: Path, ref: str) -> str | None:
    p = subprocess.run(["git", "rev-parse", "--verify", ref],
                       cwd=root, text=True, capture_output=True)
    return p.stdout.strip() if p.returncode == 0 else None


def _known_base(root: Path, path: str, item: dict) -> str:
    revision = item.get("base_commit")
    if revision:
        import re
        if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ContributionError("invalid_base_commit")
        _git(root, "merge-base", "--is-ancestor", revision, "HEAD")
        text = _blob(root, revision, path)
        if _sha(text) != item.get("base_sha256"):
            raise ContributionError("base_revision_hash_mismatch")
        return text
    # Compatibility for adapters that pin only the exact file hash. Search a
    # bounded ancestry, never accept a caller-authored base document as truth.
    for revision in _git(root, "log", "-200", "--format=%H", "--", path).splitlines():
        text = _blob(root, revision, path)
        if _sha(text) == item.get("base_sha256"):
            return text
    raise ContributionError("known_base_required: supply base_commit")


def _reconcile_source(known: str, current: str, proposed: str) -> str:
    old_fm, old_body = _parse_document(known)
    fm, body = _parse_document(current)
    proposed_fm, new_body = _parse_document(proposed)
    if old_fm != proposed_fm:
        raise ContributionError("frontmatter_changes_not_supported")
    if old_body != body:
        raise ContributionError("source_body_conflict")
    if current != known:
        # Permit only legitimate canonical transition suffixes, not arbitrary
        # history exclusions or owner/tool/authority changes.
        allowed = {*_SUPPORT_FIELDS, "action_state", "action_state_history", "updated_at", "completed_at"}
        if ({k: v for k, v in fm.items() if k not in allowed} !=
            {k: v for k, v in old_fm.items() if k not in allowed}):
            raise ContributionError("source_authority_or_frontmatter_conflict")
        history = fm.get("action_state_history") or []
        prior = old_fm.get("action_state_history") or []
        if len(history) <= len(prior) or action_transition_diagnostics(known, current):
            raise ContributionError("unproved_source_history_suffix")
    return new_body


def _prepare(root: Path, config: WikiConfig, request: dict, review: dict | None) -> dict:
    path, material, branch = _request(config, request)
    review = _review(request, material, review)
    existing = _candidate(root, branch)
    if existing:
        entry, text = _entry(root, existing, path, request, material)
        if entry["contribution"]["review"] != review:
            raise ContributionError("effect_review_conflict")
        return {"status": "prepared", "proposal_commit": existing, "branch": branch,
                "material_sha256": material, "receipt_id": entry["receipt_id"],
                "after_sha256": _sha(text), "idempotent": True, "coverage": "one_action_body"}
    target, path = _contained_action_path(root, path)
    base = _git(root, "rev-parse", "HEAD")
    approved_branch = str(config.approval.get("default_branch") or "main")
    refs = [f"refs/remotes/origin/{approved_branch}", f"refs/heads/{approved_branch}"]
    approved = None
    for ref in refs:
        try:
            approved = _git(root, "rev-parse", "--verify", ref)
            break
        except ContributionError:
            continue
    if approved != base:
        raise ContributionError("checkout_not_at_approved_base")
    before = target.read_text()
    item = request["files"][0]
    known = _known_base(root, path, item)
    committed = _blob(root, base, path)
    # Validate both committed evolution and any local canonical dialogue
    # suffix. Both chains must be real; current WIP is never silently dropped.
    _reconcile_source(known, committed, item["text"])
    body = _reconcile_source(known, before, item["text"])
    fm, _ = _parse_document(before)
    if fm.get("page_id") != request["task_ref"]["action_id"]:
        raise ContributionError("task_action_mismatch")
    policy = _blob(root, base, "wiki.config.yaml")
    if (root / "wiki.config.yaml").read_text() != policy:
        raise ContributionError("uncommitted_policy")
    # The proposal contains committed source plus this body only. Disjoint
    # staged/unstaged/untracked files in the application's checkout stay there.
    with tempfile.TemporaryDirectory(prefix="wiki-contribution-") as temporary:
        scratch = Path(temporary) / "proposal"
        _run(root, "git", "clone", "--shared", "--no-checkout", str(root), str(scratch))
        _git(scratch, "checkout", "--detach", base)
        for field in ("user.name", "user.email"):
            _git(scratch, "config", field, _git(root, "config", field))
        # Carry only the proven current action suffix into the isolated
        # checkout, through the same canonical file boundary.
        from wiki_core.action_transition import seed_action_proposal
        seed_action_proposal(scratch, path, committed, before)
        receipt = integrate_action_body(scratch, path, body, expected_sha256=_sha(before),
            contribution={"material_sha256": material, "effect_key": request["effect_key"],
                          "task_ref": request["task_ref"], "run_ref": request["run_ref"],
                          "session_ref": request["session_ref"], "review": review})
        gates = _gates(scratch, load_config(scratch))
        # Check commands may not silently modify the reviewed proposal.
        after = (scratch / path).read_text()
        if _sha(after) != receipt["after_sha256"]:
            raise ContributionError("gate_modified_proposal")
        changed = _git(scratch, "diff", "--name-only", base).splitlines()
        if changed != [path] or _git(scratch, "ls-files", "--others", "--exclude-standard"):
            raise ContributionError("gate_modified_other_paths")
        _git(scratch, "add", "--", path)
        _git(scratch, "commit", "-m", "wiki: integrate reviewed action body " + material[:12])
        commit = _git(scratch, "rev-parse", "HEAD")
        # No model/audit work under these process-shared guards. Revalidate
        # HEAD, bytes and policy immediately before installing the proposal ref.
        with _action_file_lock(root, "contribution-ref:" + branch), _action_file_lock(root, path):
            if (_git(root, "rev-parse", "HEAD") != base or target.read_text() != before
                or (root / "wiki.config.yaml").read_text() != policy):
                raise ContributionError("source_changed_during_prepare")
            if _candidate(root, branch):
                raise ContributionError("contribution_prepared_concurrently: reconcile")
            _git(root, "fetch", str(scratch), commit)
            _git(root, "update-ref", f"refs/heads/{branch}", commit, "0" * 40)
    return {"status": "prepared", "proposal_commit": commit, "branch": branch,
            "material_sha256": material, "after_sha256": receipt["after_sha256"],
            "receipt_id": receipt["receipt_id"], "gate_receipts": gates,
            "idempotent": False, "coverage": "one_action_body"}


def _repository(root: Path) -> str:
    import re
    from urllib.parse import urlparse
    remote = _git(root, "remote", "get-url", "origin")
    if remote.startswith("git@"):
        host, separator, path = remote[4:].partition(":")
        if not separator:
            raise ContributionError("unsupported_github_remote")
    else:
        parsed = urlparse(remote)
        if parsed.scheme not in {"https", "ssh"} or parsed.password or parsed.query or parsed.fragment:
            raise ContributionError("unsupported_github_remote")
        host, path = parsed.hostname or "", parsed.path.lstrip("/")
    path = path.removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9.-]+", host) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", path):
        raise ContributionError("unsupported_github_remote")
    return host + "/" + path


def _gh(root: Path, *args: str) -> Any:
    return json.loads(_run(root, "gh", *args))


def _pr(root: Path, number: Any) -> dict:
    if not str(number).isdigit():
        raise ContributionError("invalid_pr")
    return _gh(root, "pr", "view", str(number), "--repo", _repository(root), "--json",
               "number,url,state,headRefOid,baseRefName,mergeCommit,statusCheckRollup,reviews,reviewDecision,isDraft")


def _canonical_readback(root: Path, config: WikiConfig, pr: dict, path: str,
                        candidate: str, request: dict, material: str) -> dict:
    merge = pr.get("mergeCommit", {}).get("oid")
    if not merge:
        raise ContributionError("merge_readback_unavailable")
    # A fetch reads canonical Git source; it does not switch or update the
    # application's worktree or imply that a reader/service adopted it.
    branch = str(config.approval.get("default_branch") or "main")
    _git(root, "fetch", "origin", branch)
    remote_head = _git(root, "rev-parse", "FETCH_HEAD")
    _git(root, "merge-base", "--is-ancestor", merge, remote_head)
    expected = _blob(root, candidate, path)
    _, merged_text = _entry(root, merge, path, request, material)
    if merged_text != expected:
        raise ContributionError("merged_body_readback_mismatch")
    current_text = _blob(root, remote_head, path)
    p = subprocess.run(["git", "merge-base", "--is-ancestor", merge, "HEAD"], cwd=root,
                       capture_output=True)
    target, _ = _contained_action_path(root, path)
    local = p.returncode == 0 and target.read_text() == current_text and current_text == expected
    return {"status": "adopted_in_checkout" if local else "waiting_worktree_adoption",
            "remote_merged": True, "source_commit": merge, "canonical_head": remote_head,
            "canonical_body_adopted": local, "readback_sha256": _sha(current_text),
            "merged_sha256": _sha(merged_text), "canonical_matches_material": current_text == expected,
            "worktree_adopted": local, "served_adoption_verified": False,
            "coverage": "one_action_body; Git source and selected checkout only"}


def run_contribution(root: Path, config: WikiConfig, operation: str, payload: dict,
                     *, dry_run: bool = True) -> dict:
    """Trusted local CLI/API; adapters never supply executable gate commands."""
    result: dict[str, Any] = {"ok": False, "operation": operation,
                              "canonical_body_adopted": False, "coverage": "one_action_body"}
    try:
        # The application's config object can be cached. Always reload the
        # actual policy rather than promoting with stale permissions.
        config = load_config(root)
        request = payload.get("request")
        path, material, branch = _request(config, request)
        result.update(effect_key=request["effect_key"], task_ref=request["task_ref"],
                      material_sha256=material, branch=branch)
        if dry_run:
            return {**result, "ok": True, "status": "dry_run", "dry_run": True}
        if operation == "prepare_contribution":
            return {**result, **_prepare(root, config, request, payload.get("review")), "ok": True}
        commit = _candidate(root, branch)
        if not commit:
            raise ContributionError("prepare_required")
        entry, _ = _entry(root, commit, path, request, material)
        if operation == "publish_contribution":
            if str(config.approval.get("gate") or "") != "github_pr":
                return {**result, "ok": True, "status": "waiting_policy_adapter"}
            _git(root, "push", "origin", f"refs/heads/{branch}:refs/heads/{branch}")
            prs = _gh(root, "pr", "list", "--repo", _repository(root), "--head", branch, "--state", "all", "--json", "number,headRefOid,url")
            if prs:
                if len(prs) != 1 or prs[0]["headRefOid"] != commit:
                    raise ContributionError("pr_identity_conflict")
                return {**result, "ok": True, "status": "awaiting_review", "pr": prs[0]}
            base_branch = str(config.approval.get("default_branch") or "main")
            url = _run(root, "gh", "pr", "create", "--repo", _repository(root), "--draft", "--base", base_branch,
                       "--head", branch, "--title", "wiki: reviewed action contribution",
                       "--body", "One reviewed action body; material " + material)
            return {**result, "ok": True, "status": "awaiting_review", "pr_url": url}
        if str(config.approval.get("gate") or "") != "github_pr":
            return {**result, "ok": True, "status": "waiting_policy_adapter"}
        pr = _pr(root, payload.get("pr"))
        if pr.get("headRefOid") != commit or pr.get("baseRefName") != str(config.approval.get("default_branch") or "main"):
            raise ContributionError("pr_identity_conflict")
        if pr.get("state") == "MERGED":
            return {**result, **_canonical_readback(root, config, pr, path, commit, request, material), "ok": True}
        if operation == "reconcile_contribution":
            return {**result, "ok": True, "status": "waiting_pr", "pr_state": pr.get("state")}
        if operation != "integrate_contribution":
            raise ContributionError("unknown_contribution_operation")
        if str(config.approval.get("gate") or "") != "github_pr":
            return {**result, "ok": True, "status": "waiting_policy_adapter"}
        if pr.get("isDraft") or pr.get("reviewDecision") == "CHANGES_REQUESTED":
            return {**result, "ok": True, "status": "waiting_pr_review"}
        if not isinstance(config.approval.get("require_human_review", False), bool):
            raise ContributionError("invalid_human_review_policy")
        checks = pr.get("statusCheckRollup") or []
        if pr.get("state") != "OPEN" or not checks or any(
            (c.get("conclusion") or c.get("state")) != "SUCCESS" for c in checks):
            return {**result, "ok": True, "status": "waiting_ci_or_pr", "gate_receipts": checks}
        # Human review is required only when the actual consumer says so.
        # A trusted adapter's independent report is never counted as human.
        if config.approval.get("require_human_review") is True:
            approved = [r for r in pr.get("reviews", []) if r.get("state") == "APPROVED"
                        and r.get("commit", {}).get("oid") == commit]
            if not approved:
                return {**result, "ok": True, "status": "waiting_human_review"}
            # GitHub enforces reviewer permissions and dismissal policy. Query
            # account type explicitly rather than treating bots as humans.
            if not any(_gh(root, "api", "--hostname", _repository(root).split("/")[0], "users/" + r["author"]["login"]).get("type") == "User" for r in approved):
                return {**result, "ok": True, "status": "waiting_human_review"}
        target, _ = _contained_action_path(root, path)
        if _sha(target.read_text()) != entry["before_sha256"]:
            raise ContributionError("source_changed_since_prepare: reconcile required")
        # Re-read canonical policy before the effect, not only after merge.
        # Disjoint canonical commits are fine; changes to this action or to
        # policy require reconciliation rather than a stale promotion.
        base_branch = str(config.approval.get("default_branch") or "main")
        _git(root, "fetch", "origin", base_branch)
        canonical = _git(root, "rev-parse", "FETCH_HEAD")
        parent = _git(root, "rev-parse", commit + "^")
        if _blob(root, canonical, "wiki.config.yaml") != _blob(root, commit, "wiki.config.yaml"):
            raise ContributionError("canonical_policy_changed: reconcile required")
        if _blob(root, canonical, path) != _blob(root, parent, path):
            raise ContributionError("canonical_action_changed: reconcile required")
        # Gate policy must be committed, not an unreviewed local weakening.
        if (root / "wiki.config.yaml").read_text() != _blob(root, commit, "wiki.config.yaml"):
            raise ContributionError("policy_changed_since_prepare")
        if entry["contribution"]["review"]["material_sha256"] != material:
            raise ContributionError("exact_material_review_required")
        # GitHub's match-head CAS guards the only canonical write. Reconcile
        # first on the next invocation after any transport failure/UNKNOWN.
        _run(root, "gh", "pr", "merge", str(pr["number"]), "--repo", _repository(root), "--merge", "--match-head-commit", commit)
        confirmed = _pr(root, pr["number"])
        if confirmed.get("state") != "MERGED" or confirmed.get("headRefOid") != commit:
            raise ContributionError("merge_outcome_unknown: reconcile")
        return {**result, **_canonical_readback(root, config, confirmed, path, commit, request, material),
                "ok": True, "gate_receipts": checks}
    except (ContributionError, ActionTransitionError, ValueError, KeyError, TypeError) as exc:
        message = exc.code if isinstance(exc, ActionTransitionError) else str(exc) if isinstance(exc, ContributionError) else "invalid_contribution_input"
        return {**result, "error": message, "status": "unknown" if "unknown" in message else "refused"}
