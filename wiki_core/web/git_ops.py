from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path
from typing import Any

from wiki_core.config import WikiConfig
from wiki_core.web.schemas import WEB_GIT_SCHEMA_VERSION


def _run_git(root: Path, args: list[str]) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)
    return proc.returncode, proc.stdout, proc.stderr


def _git_output(root: Path, args: list[str]) -> str:
    code, stdout, _stderr = _run_git(root, args)
    return stdout.strip() if code == 0 else ""


def _is_git_repo(root: Path) -> bool:
    return bool(_git_output(root, ["rev-parse", "--show-toplevel"]))


def _status_rows(root: Path) -> list[dict[str, Any]]:
    code, output, _stderr = _run_git(root, ["status", "--porcelain=v1"])
    if code != 0:
        return []
    rows: list[dict[str, Any]] = []
    for line in output.splitlines():
        if not line:
            continue
        status = line[:2]
        path = line[3:] if len(line) > 2 and line[2] == " " else line[2:].lstrip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        rows.append(
            {
                "path": path,
                "status": status.strip() or status,
                "staged": status[0] not in {" ", "?"},
                "unstaged": status[1] != " " or status == "??",
            }
        )
    return rows


def _known_generated(path: str, config: WikiConfig) -> bool:
    generated_paths = {
        config.paths["operation_page"],
        config.paths["operational_pass_page"],
        config.paths["source_registry_page"],
        str((config.root_entity or {}).get("input_stage_page") or ""),
        "data/derived/wiki/score-events-mirror.jsonl",
    }
    return path in generated_paths or path.startswith(config.paths["derived_root"].rstrip("/") + "/")


def _remote_name(root: Path, current_branch: str) -> str:
    configured = _git_output(root, ["config", "--get", f"branch.{current_branch}.remote"])
    return configured or "origin"


def _default_branch(root: Path) -> str:
    symbolic = _git_output(root, ["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"])
    if symbolic.startswith("origin/"):
        return symbolic.split("/", 1)[1]
    for candidate in ("main", "master"):
        if _git_output(root, ["show-ref", "--verify", f"refs/heads/{candidate}"]):
            return candidate
    return "main"


def _ahead_behind(root: Path, current_branch: str) -> tuple[int, int, str]:
    upstream = _git_output(root, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"])
    if not upstream:
        remote = _remote_name(root, current_branch)
        candidate = f"{remote}/{current_branch}"
        if _git_output(root, ["show-ref", "--verify", f"refs/remotes/{candidate}"]):
            upstream = candidate
    if not upstream:
        return 0, 0, ""
    output = _git_output(root, ["rev-list", "--left-right", "--count", f"HEAD...{upstream}"])
    parts = output.split()
    if len(parts) != 2:
        return 0, 0, upstream
    try:
        return int(parts[0]), int(parts[1]), upstream
    except ValueError:
        return 0, 0, upstream


def _fetch_head_time(root: Path) -> str | None:
    fetch_head = root / ".git" / "FETCH_HEAD"
    if not fetch_head.exists():
        return None
    stamp = dt.datetime.fromtimestamp(fetch_head.stat().st_mtime, tz=dt.timezone.utc)
    return stamp.isoformat().replace("+00:00", "Z")


def _gh_pr_metadata(root: Path, current_branch: str) -> dict[str, Any] | None:
    if not current_branch:
        return None
    try:
        proc = subprocess.run(
            ["gh", "pr", "view", current_branch, "--json", "url,isDraft,state,mergeStateStatus"],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=6,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _human_gate_state(
    *, current_branch: str, default_branch: str, branch_prefix: str, clean: bool, pr_metadata: dict[str, Any] | None = None
) -> str:
    if current_branch == default_branch:
        return "approved" if clean else "blocked"
    if current_branch.startswith(branch_prefix):
        if pr_metadata:
            state = str(pr_metadata.get("state") or "").upper()
            if state == "MERGED":
                return "merged"
            if state == "CLOSED":
                return "blocked"
            if pr_metadata.get("isDraft"):
                return "draft"
            return "ready_for_review"
        return "not_opened"
    return "blocked"


def build_git_state(root: Path, config: WikiConfig) -> dict[str, Any]:
    branch_prefix = str(config.approval.get("branch_prefix") or "wiki/")
    if not _is_git_repo(root):
        return {
            "schema_version": WEB_GIT_SCHEMA_VERSION,
            "available": False,
            "default_branch": "main",
            "current_branch": "",
            "branch_prefix": branch_prefix,
            "worktree": {"clean": True, "changed_files": []},
            "upstream": {"remote": "", "ahead": 0, "behind": 0, "name": "", "last_fetch_at": None},
            "proposal": {
                "is_proposal_branch": False,
                "theme": "",
                "draft_pr_url": None,
                "human_gate_state": "blocked",
            },
        }

    current_branch = _git_output(root, ["branch", "--show-current"])
    if not current_branch:
        current_branch = _git_output(root, ["rev-parse", "--short", "HEAD"])
    default_branch = _default_branch(root)
    remote = _remote_name(root, current_branch)
    ahead, behind, upstream_name = _ahead_behind(root, current_branch)
    changed = _status_rows(root)
    for row in changed:
        row["known_generated"] = _known_generated(str(row["path"]), config)
        row["suggested_stage"] = bool(row["known_generated"] or current_branch.startswith(branch_prefix))
    clean = not changed
    is_proposal = current_branch.startswith(branch_prefix)
    pr_metadata = _gh_pr_metadata(root, current_branch) if is_proposal else None
    return {
        "schema_version": WEB_GIT_SCHEMA_VERSION,
        "available": True,
        "default_branch": default_branch,
        "current_branch": current_branch,
        "branch_prefix": branch_prefix,
        "worktree": {"clean": clean, "changed_files": changed},
        "upstream": {
            "remote": remote,
            "ahead": ahead,
            "behind": behind,
            "name": upstream_name,
            "last_fetch_at": _fetch_head_time(root),
        },
        "proposal": {
            "is_proposal_branch": is_proposal,
            "theme": current_branch[len(branch_prefix):] if is_proposal else "",
            "draft_pr_url": str((pr_metadata or {}).get("url") or "") or None,
            "human_gate_state": _human_gate_state(
                current_branch=current_branch,
                default_branch=default_branch,
                branch_prefix=branch_prefix,
                clean=clean,
                pr_metadata=pr_metadata,
            ),
        },
    }
