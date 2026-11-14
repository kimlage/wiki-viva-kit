"""Read-only observations for proposal integration and Git lifecycle hygiene.

A result is advisory. It is not an authorization, a gate run or proof of a
runtime identity. Only an explicit, exact-head handoff can supply local evidence.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

from wiki_core.action_contribution import ContributionError, _blob, _gh, _git, _repository
from wiki_core.action_transition import ActionTransitionError, _assert_no_secrets
from wiki_core.action_state import NON_TERMINAL_ACTION_STATES, TERMINAL_ACTION_STATES
from wiki_core.config import config_from_mapping
from wiki_core.frontmatter import parse_frontmatter
from wiki_core.paths import WikiPaths

SHA = re.compile(r"^[0-9a-f]{40,64}$")
FIELDS = ("number,url,state,author,headRefName,headRefOid,headRepositoryOwner,isCrossRepository,"
          "baseRefName,baseRefOid,mergeCommit,isDraft,reviewDecision,statusCheckRollup,"
          "reviews,comments,mergeStateStatus,closedAt,mergedAt")


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


def _event_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else None
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return stamp if stamp.tzinfo is not None else None
    except ValueError:
        return None


def _comment_evidence(pr: dict, head: str) -> tuple[bool, bool, bool, str | None]:
    decisions: dict[str, list[tuple[datetime | None, str]]] = {}
    thread = None
    raw_author = (pr.get("author") or {}).get("login")
    author = raw_author.casefold() if isinstance(raw_author, str) else None
    for item in pr.get("comments") or []:
        body = item.get("body", "")
        if not isinstance(body, str) or _field(body, "Head") != head:
            continue
        raw_commenter = (item.get("author") or {}).get("login")
        commenter = raw_commenter.casefold() if isinstance(raw_commenter, str) else None
        decision = _field(body, "Review").lower().replace(" ", "_")
        if author and commenter and commenter != author and decision in {"approved", "rejected", "changes_requested", "blocked"}:
            decisions.setdefault(commenter, []).append((_event_time(item.get("createdAt")), decision))
        thread = _thread_ref(_field(body, "Responsible-Thread")) or thread
    for item in pr.get("reviews") or []:
        raw_reviewer = (item.get("author") or {}).get("login")
        reviewer = raw_reviewer.casefold() if isinstance(raw_reviewer, str) else None
        if author and reviewer and reviewer != author and (item.get("commit") or {}).get("oid") == head:
            decision = str(item.get("state") or "").lower()
            if (decision in {"changes_requested", "dismissed"}
                    or (decision == "approved" and head in str(item.get("body") or ""))):
                decisions.setdefault(reviewer, []).append((_event_time(item.get("submittedAt")), decision))
    latest = []
    uncertain = False
    for events in decisions.values():
        if len({decision for _, decision in events}) == 1:
            latest.append(events[0][1])
        elif any(stamp is None for stamp, _ in events) or len({stamp for stamp, _ in events}) != len(events):
            uncertain = True
        else:
            latest.append(max(events, key=lambda event: event[0])[1])
    blocked = any(x in {"rejected", "changes_requested", "blocked"} for x in latest)
    return "approved" in latest, blocked, uncertain, thread


def _failed_ci_checks(pr: dict) -> list[str]:
    """Completed failures from the provider rollup associated with this PR head."""
    failures = []
    for item in pr.get("statusCheckRollup") or []:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").upper()
        conclusion = str(item.get("conclusion") or "").upper()
        state = str(item.get("state") or "").upper()
        is_failure = (status == "COMPLETED" and conclusion in {"FAILURE", "TIMED_OUT", "STARTUP_FAILURE"})
        is_failure |= (item.get("__typename") == "StatusContext" and state in {"FAILURE", "ERROR"})
        if not is_failure:
            continue
        name = item.get("name") or item.get("context")
        if (not isinstance(name, str) or not name.strip() or len(name) > 160
                or any(ord(char) < 32 or ord(char) == 127 for char in name)):
            name = "check_name_unavailable"
        else:
            name = name.strip()
            try:
                _assert_no_secrets(name)
            except ActionTransitionError:
                name = "check_name_unavailable"
        if name not in failures:
            failures.append(name)
    return failures


def evaluate(pr: dict, approval: dict, *, ancestry: str, human_approved: bool,
             closure_reason_required: bool = False) -> dict:
    """Evaluate supplied observations; never execute commands or mutate state."""
    head = pr.get("headRefOid") or ""
    out = {"number": pr.get("number"), "url": pr.get("url"), "head": head,
           "base": pr.get("baseRefOid"), "status": "waiting:observation"}
    review, review_blocked, review_uncertain, thread = _comment_evidence(pr, head)
    if thread:
        out["responsible_thread"] = thread
    state = str(pr.get("state", "")).upper()
    if state in {"MERGED", "CLOSED"}:
        out["action_reconciliation"] = "unverified"
        out["status"] = "done"
        if state == "CLOSED" and closure_reason_required:
            reasons = [str(c.get("body") or "") for c in pr.get("comments") or []]
            out["status"] = ("done" if any(re.search(r"(?im)^(?:Disposition-Reason|Motivo(?: do descarte)?|Reason for (?:closure|discard))\s*:\s*\S", b) for b in reasons)
                             else "waiting:verify_closure_reason" if reasons else "fix:closure_reason_missing")
        return out
    if state != "OPEN" or not SHA.fullmatch(head):
        return out
    failed_checks = _failed_ci_checks(pr)
    if failed_checks:
        out["status"] = "fix:ci_failed"
        out["ci_failed_checks"] = failed_checks
        return out
    if not SHA.fullmatch(str(pr.get("baseRefOid") or "")):
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
        if review_uncertain:
            pending.append("review_event_order")
        elif not review:
            pending.append("exact_head_review")
        if pr.get("mergeStateStatus") != "CLEAN" or pr.get("reviewDecision") == "REVIEW_REQUIRED":
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


def _action_reference(text: str, number: int, repository: str, *, numeric: bool = False) -> bool | None:
    """Prefer repository-qualified evidence; do not resolve a collision locally."""
    host, owner, repo = repository.lower().split("/", 2)
    def repo_id(link_host: str, link_owner: str, link_repo: str) -> tuple[str, str, str]:
        return link_host.lower(), link_owner.lower(), link_repo.lower().removesuffix('.git')
    target = repo_id(host, owner, repo)
    explicit: set[tuple[str, str, str]] = set()
    file_suffixes = ('.md', '.py', '.yaml', '.yml', '.json', '.toml', '.txt', '.sh', '.ts', '.tsx')
    path_roots = {'docs', 'memories', 'memorias', 'scripts', 'tests', 'src', 'data', 'apps', 'packs',
                  'tools', 'bin', 'examples', 'assets', 'lib', 'include', 'config', 'resources',
                  'build', 'templates', 'frontend', 'backend', 'server', 'client', 'acoes', 'decisoes'}
    ambiguous_path = False
    urls = re.compile(r"(?<![\w/@.-])(?:https?://)?([^/\s]+)/([^/\s]+)/([^/\s]+)/(pull|pull-requests|issues)/([0-9]+)(?![A-Za-z0-9_])", re.I)
    for match in urls.finditer(text):
        if ('.' in match.group(1) or match.group(1).lower() == host) and match.group(5) == str(number):
            linked_repo = repo_id(*match.group(1, 2, 3))
            if match.group(4).lower() in {'pull', 'pull-requests'} or linked_repo != target:
                explicit.add(linked_repo)
    merge_requests = re.compile(r"https?://([^/\s]+)/([^\s?#]+?)/-/merge_requests/([0-9]+)(?![A-Za-z0-9_])", re.I)
    for match in merge_requests.finditer(text):
        if match.group(3) == str(number):
            parts = match.group(2).split('/')
            explicit.add(repo_id(match.group(1), '/'.join(parts[:-1]), parts[-1]))
    hosted = re.compile(r"(?<![\w/@.-])(?:https?://)?([^/\s]+)/([^/\s]+)/([^/\s#]+)#([0-9]+)(?![A-Za-z0-9_])", re.I)
    for match in hosted.finditer(text):
        if match.group(4) == str(number):
            if match.group(1).lower() in {host, 'github.com', 'gitlab.com', 'bitbucket.org'}:
                explicit.add(repo_id(*match.group(1, 2, 3)))
            elif '.' in match.group(1):
                # A fragment on an unknown host could be a Git reference or
                # a document anchor; do not infer its repository.
                ambiguous_path = True
    qualified = re.compile(r"(?<![\w/.:@-])([\w.-]+)/([\w.-]+)#([0-9]+)(?![A-Za-z0-9_])", re.I)
    for match in qualified.finditer(text):
        if match.group(3) == str(number):
            if match.group(1).lower() in path_roots:
                if not match.group(2).lower().endswith(file_suffixes):
                    ambiguous_path = True
                continue
            explicit.add(repo_id(host, match.group(1), match.group(2)))
    # Also bind forms such as "repo=owner/repo PR #502" and the reverse.
    repo_name = (r"(?<![\w/.:@-])(?:(?:repo(?:sitory)?|reposit[oó]rio)[ \t]*[:=]?[ \t]*)?"
                 r"(?:([\w.-]+\.[A-Za-z]{2,})/)?([\w.-]+)/([\w.-]+)")
    pr_number = rf"(?:(?:PR|pull[ \t]+request|proposta)[ \t]*[:=]?[ \t]*#?[ \t]*|#){number}(?![A-Za-z0-9_])"
    def add_separate(match: re.Match, destination: set[tuple[str, str, str]]) -> None:
        nonlocal ambiguous_path
        named_host, named_owner, named_repo = match.group(1, 2, 3)
        labeled = bool(re.search(r"\b(?:repo(?:sitory)?|reposit[oó]rio)[ \t]*[:=]", match.group(0), re.I))
        if not named_host and not labeled and named_repo.lower().endswith(file_suffixes):
            return
        if not named_host and not labeled and named_owner.lower() in path_roots:
            ambiguous_path = True
            return
        destination.add(repo_id(named_host or host, named_owner, named_repo))
    for pattern in (repo_name + r"[ \t]*[,;:]?[ \t]*\(?[ \t]*" + pr_number,
                    pr_number + r"[ \t]*\(?[ \t]*(?:(?:do|da|de|of|in|no|na)[ \t]+)?" + repo_name):
        for match in re.finditer(pattern, text, re.I):
            add_separate(match, explicit)
    if target in explicit:
        return True
    if explicit:
        return False
    # A bare repository and number on one line, or an explicit Repo: label
    # elsewhere in the action, make the short number repository-qualified.
    contextual: set[tuple[str, str, str]] = set()
    root_urls = re.compile(r"(?<![\w/@.-])(?:https?://)?([^/\s]+)/([^/\s]+)/([\w.-]+)/?(?=$|[?#\s)>\]},;])", re.I)
    ssh_urls = re.compile(r"(?<![\w/@.-])git@([\w.-]+):([\w.-]+)/([\w.-]+)(?=$|[?#\s)\]},;])", re.I)
    def repository_url(match: re.Match, source: str) -> bool:
        link_host = match.group(1).lower()
        known = link_host in {host, 'github.com', 'gitlab.com', 'bitbucket.org'}
        # An unknown host with a fragment may be an ordinary documentation link.
        return known or ('.' in link_host and source[match.end():match.end() + 1] != '#')
    number_pattern = re.compile(r"(?i)(?:\b(?:PR|pull[ \t]+request|proposta)[ \t]*[:=]?[ \t]*#?[ \t]*|(?<![\w/])#)([0-9]+)(?![A-Za-z0-9_])")
    for line in text.splitlines():
        for segment in line.split(';'):
            numbers = {item.group(1) for item in number_pattern.finditer(segment)}
            if str(number) not in numbers:
                continue
            names = list(re.finditer(repo_name, segment, re.I))
            links = [match for match in root_urls.finditer(segment)
                     if repository_url(match, segment)]
            ssh_links = list(ssh_urls.finditer(segment))
            if len(numbers) > 1 and (names or links or ssh_links):
                ambiguous_path = True
                continue
            for match in names:
                add_separate(match, contextual)
            for match in links:
                contextual.add(repo_id(*match.group(1, 2, 3)))
            for match in ssh_links:
                contextual.add(repo_id(*match.group(1, 2, 3)))
    label = (r"(?i)\b(?:repo(?:sitory)?|reposit[oó]rio)[ \t]*[:=][ \t]*"
             r"(?:(?:https?://|git@)?([\w.-]+\.[A-Za-z]{2,})(?::|/))?([\w.-]+)/([\w.-]+)")
    all_labels = list(re.finditer(label, text))
    all_numbers = {item.group(1) for item in number_pattern.finditer(text)}
    if numeric:
        all_numbers.add(str(number))
    if all_numbers == {str(number)}:
        hints: set[tuple[str, str, str]] = set()
        for match in re.finditer(repo_name, text, re.I):
            add_separate(match, hints)
        for match in root_urls.finditer(text):
            if repository_url(match, text):
                hints.add(repo_id(*match.group(1, 2, 3)))
        for match in ssh_urls.finditer(text):
            hints.add(repo_id(*match.group(1, 2, 3)))
        contextual.update(hints)
    if len(all_labels) == 1 and all_numbers == {str(number)}:
        add_separate(all_labels[0], contextual)
    for block in re.split(r"\n[ \t]*\n", text):
        labels = list(re.finditer(label, block))
        for index, match in enumerate(labels):
            end = labels[index + 1].start() if index + 1 < len(labels) else len(block)
            following = {item.group(1) for item in number_pattern.finditer(block[match.end():end])}
            if str(number) in following:
                add_separate(match, contextual)
                continue
            if following:
                continue
            start = labels[index - 1].end() if index else 0
            previous = {item.group(1) for item in number_pattern.finditer(block[start:match.start()])}
            if previous == {str(number)}:
                add_separate(match, contextual)
            elif str(number) in previous:
                ambiguous_path = True
    if contextual:
        return True if contextual == {target} else None if target in contextual else False
    if ambiguous_path:
        return None
    local = rf"(?i)(?:\b(?:PR|pull\s+request|proposta)\s*[:=]?\s*#?\s*|(?<![\w/])#){number}(?![A-Za-z0-9_])"
    return numeric or bool(re.search(local, text))


def _action_observation(frontmatter: dict, body: str, pr: dict, repository: str) -> dict | None:
    if frontmatter.get("page_type") != "action":
        return None
    action_id = str(frontmatter.get("page_id") or "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", action_id):
        return None
    try:
        _assert_no_secrets(action_id)
    except ActionTransitionError:
        return None
    number = pr.get("number")
    if not isinstance(number, int):
        return None
    references = frontmatter.get("evidence_refs") or []
    if not isinstance(references, list):
        references = [references]
    cited = "\n".join((str(frontmatter.get("next_action") or ""),
                        *(str(ref) for ref in references), body))
    numeric_reference = any(str(ref).strip() == str(number) for ref in references)
    numeric_next = str(frontmatter.get("next_action") or "").strip() == str(number)
    numeric_body = body.strip() == str(number)
    association = _action_reference(cited, number, repository, numeric=numeric_reference or numeric_next or numeric_body)
    if association is False:
        return None
    state = frontmatter.get("action_state")
    responsible = str(frontmatter.get("owner_ref") or frontmatter.get("owner") or "action_owner")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", responsible):
        responsible = "action_owner"
    try:
        _assert_no_secrets(responsible)
    except ActionTransitionError:
        responsible = "action_owner"
    result = {"action_id": action_id, "pr": number, "responsible": responsible}
    if state in TERMINAL_ACTION_STATES:
        return {**result, "status": "terminal", "event": "action_already_terminal"}
    if association is None:
        return {**result, "status": "waiting:action_reconciliation", "event": "repository_reference_ambiguous"}
    event = _event_time(pr.get("mergedAt") if pr.get("state") == "MERGED" else pr.get("closedAt"))
    if state not in NON_TERMINAL_ACTION_STATES or event is None:
        return {**result, "status": "waiting:action_reconciliation", "event": "action_state_or_closure_time_unavailable"}
    updated = frontmatter.get("updated_at")
    updated_str = str(updated or "")
    updated_time = _event_time(updated_str)
    try:
        updated_date = date.fromisoformat(updated_str) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", updated_str) else None
    except ValueError:
        updated_date = None
    if updated_date and updated_date >= event.date():
        return {**result, "status": "current", "event": "action_updated_after_proposal"}
    history = frontmatter.get("action_state_history") or []
    if not isinstance(history, list) or (history and not isinstance(history[-1], dict)):
        return {**result, "status": "waiting:action_reconciliation", "event": "receipt_time_unavailable"}
    last_receipt = (_event_time(history[-1].get("at") or history[-1].get("recorded_at")) if history else None)
    intervals: list[tuple[datetime, datetime]] = []
    if updated_time:
        intervals.append((updated_time, updated_time))
    elif updated_date:
        # A date without a timezone may refer to any local time at a UTC
        # offset from -12 to +14 hours. Only compare non-overlapping ranges.
        midnight = datetime.combine(updated_date, time.min, tzinfo=timezone.utc)
        intervals.append((midnight - timedelta(hours=14), midnight + timedelta(days=1, hours=12)))
    if last_receipt:
        intervals.append((last_receipt, last_receipt))
    if any(start >= event for start, _ in intervals):
        return {**result, "status": "current", "event": "action_updated_after_proposal"}
    if history and last_receipt is None:
        return {**result, "status": "waiting:action_reconciliation", "event": "receipt_time_unavailable"}
    if intervals and all(end <= event for _, end in intervals):
        return {**result, "status": "fix:action_stale", "event": "proposal_closed_after_action"}
    return {**result, "status": "waiting:action_reconciliation", "event": "action_update_time_ambiguous"}


def _action_findings(root: Path, base: str, prs: list[dict], repository: str) -> tuple[list[dict], bool]:
    """Read canonical action blobs from the observed target commit; never checkout."""
    try:
        config = config_from_mapping(yaml.safe_load(_blob(root, base, "wiki.config.yaml")))
        paths = WikiPaths(root, config)
        names = _git(root, "ls-tree", "-r", "--name-only", "-z", base).split("\0")
        terminal = [p for p in prs if p.get("state") in {"MERGED", "CLOSED"}]
        findings = []
        for name in names:
            if not name.endswith(".md") or paths.collection_root(root / name, "actions_dirname") is None:
                continue
            fm, body = parse_frontmatter(_blob(root, base, name))
            for pr in terminal:
                observation = _action_observation(fm, body, pr, repository)
                if observation is not None:
                    findings.append(observation)
        return findings, True
    except (OSError, ValueError, TypeError, ContributionError, yaml.YAMLError):
        return [], False


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


def _closure_reason_scope(pr: dict, approval: dict, *, residue: bool) -> str:
    """Check only recent closed PRs or ones with observable Git residue."""
    if residue:
        return "required"
    raw = approval.get("closure_reason_after")
    if raw is None or raw == "":
        return "out_of_scope"
    try:
        if isinstance(raw, datetime):
            raise ValueError
        cutoff = raw if isinstance(raw, date) else date.fromisoformat(str(raw))
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(raw)):
            raise ValueError
    except ValueError:
        return "waiting:closure_reason_policy"
    closed = _event_time(pr.get("closedAt"))
    if closed is None:
        return "waiting:closure_time"
    return "required" if closed.date() > cutoff else "out_of_scope"


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
        own = lambda p: (p.get("isCrossRepository") is False
                         and str((p.get("headRepositoryOwner") or {}).get("login") or "").lower() == owner)
        proposals = []
        closure_policies = []
        for pr in prs:
            target_base = remote.get(str(pr.get("baseRefName") or ""), "")
            approval = policy(root, target_base) if SHA.fullmatch(target_base) else None
            # A deleted historical target falls back to the current default
            # branch; an existing but unreadable target remains unknown.
            closure_policies.append(approval if SHA.fullmatch(target_base) else default_policy)
            if pr.get("state") in {"MERGED", "CLOSED"}:
                proposals.append(evaluate(pr, {}, ancestry="unknown", human_approved=False))
                continue
            # A completed CI failure must be visible for every open proposal,
            # including drafts or those waiting on base, policy or review.
            if pr.get("state") == "OPEN" and _failed_ci_checks(pr):
                if own(pr) and remote.get(str(pr.get("headRefName") or "")) != pr.get("headRefOid"):
                    proposals.append({"number": pr.get("number"), "url": pr.get("url"),
                                      "head": pr.get("headRefOid"), "base": pr.get("baseRefOid"),
                                      "status": "waiting:head_observation"})
                else:
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
        local_lines = _git(root, "for-each-ref", "--format=%(refname:short)%09%(objectname)", "refs/heads/").splitlines()
        local_heads = {line.split("\t", 1)[0]: line.split("\t", 1)[1]
                       for line in local_lines if "\t" in line}
        local = [line.split("\t", 1)[0] for line in local_lines]
        worktrees = _worktrees(root)
        open_heads = {p.get("headRefName") for p in prs if p.get("state") == "OPEN" and own(p)}
        open_refs = {(p.get("headRefName"), p.get("headRefOid")) for p in prs if p.get("state") == "OPEN" and own(p)}
        closed_heads = {p.get("headRefName") for p in prs if p.get("state") == "MERGED" and own(p)} - open_heads
        present = set(local) | set(remote) | {w["branch"] for w in worktrees}
        for pr, observation, destination_policy in zip(prs, proposals, closure_policies):
            if pr.get("state") == "CLOSED" and not pr.get("mergedAt"):
                branch = pr.get("headRefName")
                head = pr.get("headRefOid")
                possible_branch = bool(branch and branch != default and branch in present)
                unknown_owner = bool(possible_branch and not own(pr) and pr.get("isCrossRepository") is not True)
                branch_present = bool(own(pr) and branch and branch != default and branch in present)
                residue = bool(own(pr) and branch and branch != default and head and
                               (branch, head) not in open_refs and
                               (remote.get(branch) == head or local_heads.get(branch) == head))
                detached = bool(head and any(w.get("head") == head and w.get("branch") is None
                                             for w in worktrees))
                residue |= bool(own(pr) and head and any(w.get("head") == head and
                                w.get("branch") == branch and branch != default and
                                (branch, head) not in open_refs for w in worktrees))
                uncertain_reuse = bool(number is not None and (branch_present or residue))
                if number is not None:
                    # A filtered view cannot tell whether another open PR uses
                    # the same branch and SHA, even when they still exist.
                    residue = False
                if number is None and branch_present and branch not in open_heads:
                    residue = True
                scope = (_closure_reason_scope(pr, destination_policy, residue=residue)
                         if destination_policy is not None else
                         "required" if residue else "waiting:destination_policy")
                if scope == "required":
                    observation["status"] = evaluate(pr, {}, ancestry="unknown", human_approved=False,
                                                     closure_reason_required=True)["status"]
                elif scope.startswith("waiting:"):
                    observation["status"] = scope
                elif unknown_owner:
                    observation["status"] = "waiting:head_repository"
                elif uncertain_reuse:
                    observation["status"] = "waiting:verify_branch_reuse"
                elif detached:
                    observation["status"] = "waiting:verify_detached_worktree"
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
        action_findings, action_available = _action_findings(root, base, prs, repo)
        for observation in proposals:
            if observation.get("action_reconciliation") == "unverified":
                related = [f for f in action_findings if f["pr"] == observation["number"]]
                observation["action_reconciliation"] = (related if related else [{
                    "status": "waiting:action_reconciliation", "event": "action_association_unavailable" if action_available else "action_source_unavailable",
                    "responsible": "integrator"}])
        hygiene.extend(f for f in action_findings if f["status"] == "fix:action_stale")
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
