from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from wiki_core.config import WikiConfig
from wiki_core.web.commands import SECRET_VALUE_RE
from wiki_core.web.git_ops import build_git_state

BRANCH_THEME_RE = re.compile(r"[a-z0-9][a-z0-9._-]{1,96}")


def _redact(text: str) -> str:
    return SECRET_VALUE_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)


def _result(argv: list[str], *, ok: bool, returncode: int | None, stdout: str = "", stderr: str = "", dry_run: bool = False) -> dict[str, Any]:
    return {
        "argv": argv,
        "ok": ok,
        "returncode": returncode,
        "stdout": _redact(stdout),
        "stderr": _redact(stderr),
        "dry_run": dry_run,
    }


def _run(root: Path, argv: list[str], *, dry_run: bool = False, timeout_seconds: int = 120) -> dict[str, Any]:
    if dry_run:
        return _result(argv, ok=True, returncode=None, stdout="dry run: command not executed", dry_run=True)
    try:
        proc = subprocess.run(
            argv,
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _result(argv, ok=False, returncode=None, stderr=str(exc), dry_run=False)
    return _result(argv, ok=proc.returncode == 0, returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


def _branch_prefix(config: WikiConfig) -> str:
    return str(config.approval.get("branch_prefix") or "wiki/")


def _safe_theme(value: str) -> str | None:
    theme = value.strip().strip("/")
    if not BRANCH_THEME_RE.fullmatch(theme):
        return None
    if ".." in theme or theme.endswith(".lock") or theme.startswith("-"):
        return None
    return theme


def _proposal_branch(config: WikiConfig, value: str) -> str | None:
    prefix = _branch_prefix(config)
    raw = value.strip()
    if raw.startswith(prefix):
        raw = raw[len(prefix):]
    theme = _safe_theme(raw)
    return f"{prefix}{theme}" if theme else None


def _git_lines(root: Path, args: list[str]) -> list[str]:
    proc = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _local_branches(root: Path) -> list[str]:
    return _git_lines(root, ["branch", "--format", "%(refname:short)"])


def _changed_paths(root: Path, config: WikiConfig) -> set[str]:
    state = build_git_state(root, config)
    return {str(row.get("path")) for row in state["worktree"]["changed_files"]}


def _safe_path(path: str) -> str | None:
    value = path.strip()
    if not value or value.startswith("/") or "\x00" in value:
        return None
    parts = Path(value).parts
    if any(part == ".." for part in parts):
        return None
    return value


def _ok_response(operation: str, *, dry_run: bool, summary: str, results: list[dict[str, Any]], data: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "ok": all(result["ok"] for result in results),
        "operation": operation,
        "dry_run": dry_run,
        "summary": summary,
        "results": results,
        "data": data or {},
    }


def _error(operation: str, message: str, *, dry_run: bool = False, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "operation": operation,
        "dry_run": dry_run,
        "summary": message,
        "results": [],
        "data": data or {},
        "error": message,
    }


def run_git_workflow(
    root: Path,
    config: WikiConfig,
    operation: str,
    payload: dict[str, Any] | None = None,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    payload = payload or {}
    prefix = _branch_prefix(config)
    state = build_git_state(root, config)
    current_branch = str(state.get("current_branch") or "")
    default_branch = str(state.get("default_branch") or "main")
    remote = str(state.get("upstream", {}).get("remote") or "origin")

    if operation == "list_proposals":
        branches = [branch for branch in _local_branches(root) if branch.startswith(prefix)]
        return _ok_response(
            operation,
            dry_run=False,
            summary=f"{len(branches)} proposal branch(es)",
            results=[],
            data={"branches": branches, "current_branch": current_branch},
        )

    if operation == "start_proposal":
        branch = _proposal_branch(config, str(payload.get("theme") or payload.get("branch") or ""))
        if branch is None:
            return _error(operation, "invalid proposal theme", dry_run=dry_run)
        if not state["worktree"]["clean"] and not dry_run:
            return _error(operation, "worktree must be clean before creating a proposal branch")
        if branch in _local_branches(root) and not dry_run:
            return _error(operation, f"branch already exists: {branch}")
        result = _run(root, ["git", "switch", "-c", branch], dry_run=dry_run)
        return _ok_response(operation, dry_run=dry_run, summary=f"Create proposal branch {branch}", results=[result], data={"branch": branch})

    if operation == "switch_proposal":
        branch = _proposal_branch(config, str(payload.get("branch") or payload.get("theme") or ""))
        if branch is None:
            return _error(operation, "invalid proposal branch", dry_run=dry_run)
        if branch not in _local_branches(root) and not dry_run:
            return _error(operation, f"unknown local proposal branch: {branch}")
        if not state["worktree"]["clean"] and not dry_run:
            return _error(operation, "worktree must be clean before switching branches")
        result = _run(root, ["git", "switch", branch], dry_run=dry_run)
        return _ok_response(operation, dry_run=dry_run, summary=f"Switch to {branch}", results=[result], data={"branch": branch})

    if operation == "stage_paths":
        requested = payload.get("paths") or []
        if not isinstance(requested, list):
            return _error(operation, "paths must be a list", dry_run=dry_run)
        changed = _changed_paths(root, config)
        paths: list[str] = []
        for raw in requested:
            safe = _safe_path(str(raw))
            if safe is None or safe not in changed:
                return _error(operation, f"path is not a known changed file: {raw}", dry_run=dry_run)
            paths.append(safe)
        if not paths:
            return _error(operation, "no paths selected", dry_run=dry_run)
        result = _run(root, ["git", "add", "--", *paths], dry_run=dry_run)
        return _ok_response(operation, dry_run=dry_run, summary=f"Stage {len(paths)} path(s)", results=[result], data={"paths": paths})

    if operation == "commit_proposal":
        if not current_branch.startswith(prefix):
            return _error(operation, "current branch is not a proposal branch", dry_run=dry_run)
        message = str(payload.get("message") or "").strip()
        if len(message) < 8 or "\n" in message:
            return _error(operation, "commit message must be a single line with at least 8 characters", dry_run=dry_run)
        result = _run(root, ["git", "commit", "-m", message], dry_run=dry_run)
        return _ok_response(operation, dry_run=dry_run, summary=f"Commit proposal on {current_branch}", results=[result], data={"branch": current_branch})

    if operation == "publish_proposal":
        if not current_branch.startswith(prefix):
            return _error(operation, "current branch is not a proposal branch", dry_run=dry_run)
        result = _run(root, ["git", "push", "-u", remote, current_branch], dry_run=dry_run, timeout_seconds=180)
        return _ok_response(operation, dry_run=dry_run, summary=f"Publish {current_branch}", results=[result], data={"branch": current_branch, "remote": remote})

    if operation == "open_draft_pr":
        if not current_branch.startswith(prefix):
            return _error(operation, "current branch is not a proposal branch", dry_run=dry_run)
        title = str(payload.get("title") or current_branch).strip()
        body = str(payload.get("body") or "Created by Wiki Viva cockpit.").strip()
        if len(title) < 4:
            return _error(operation, "PR title is too short", dry_run=dry_run)
        result = _run(
            root,
            ["gh", "pr", "create", "--draft", "--base", default_branch, "--head", current_branch, "--title", title, "--body", body],
            dry_run=dry_run,
            timeout_seconds=180,
        )
        return _ok_response(operation, dry_run=dry_run, summary=f"Open draft PR for {current_branch}", results=[result], data={"branch": current_branch, "base": default_branch})

    if operation == "update_draft_pr":
        if not current_branch.startswith(prefix):
            return _error(operation, "current branch is not a proposal branch", dry_run=dry_run)
        title = str(payload.get("title") or current_branch).strip()
        body = str(payload.get("body") or "Updated by Wiki Viva cockpit.").strip()
        if len(title) < 4:
            return _error(operation, "PR title is too short", dry_run=dry_run)
        result = _run(
            root,
            ["gh", "pr", "edit", current_branch, "--title", title, "--body", body],
            dry_run=dry_run,
            timeout_seconds=180,
        )
        return _ok_response(operation, dry_run=dry_run, summary=f"Update draft PR for {current_branch}", results=[result], data={"branch": current_branch})

    if operation == "sync_main":
        if current_branch != default_branch:
            return _error(operation, "checkout must be on the approved branch before syncing main", dry_run=dry_run)
        if not state["worktree"]["clean"] and not dry_run:
            return _error(operation, "worktree must be clean before syncing main", dry_run=dry_run)
        results = [
            _run(root, ["git", "fetch", "--prune", remote], dry_run=dry_run, timeout_seconds=180),
            _run(root, ["git", "pull", "--ff-only", remote, default_branch], dry_run=dry_run, timeout_seconds=180),
        ]
        return _ok_response(operation, dry_run=dry_run, summary=f"Fast-forward {default_branch}", results=results, data={"branch": default_branch, "remote": remote})

    return _error(operation, "unknown Git workflow", dry_run=dry_run)
