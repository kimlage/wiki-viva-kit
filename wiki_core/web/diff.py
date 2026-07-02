from __future__ import annotations

import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from wiki_core.config import WikiConfig
from wiki_core.web.schemas import WEB_DIFF_SCHEMA_VERSION

SECRET_VALUE_RE = re.compile(
    r"(?i)(token|password|passwd|secret|api[_-]?key|cookie)(\s*[:=]\s*)([^\s]+)"
)


def _run_git(root: Path, args: list[str], *, timeout: int = 15) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)
    return proc.returncode, proc.stdout, proc.stderr


def _git_output(root: Path, args: list[str]) -> str:
    code, stdout, _stderr = _run_git(root, args)
    return stdout.strip() if code == 0 else ""


def _is_git_repo(root: Path) -> bool:
    return bool(_git_output(root, ["rev-parse", "--show-toplevel"]))


def _ref_exists(root: Path, ref: str) -> bool:
    return bool(_git_output(root, ["rev-parse", "--verify", "--quiet", ref]))


def _head_commit(root: Path) -> str:
    return _git_output(root, ["rev-parse", "HEAD"])


def _base_ref(root: Path, default_branch: str) -> str:
    for candidate in (f"origin/{default_branch}", default_branch):
        if _ref_exists(root, candidate):
            return candidate
    return ""


def _merge_base(root: Path, base_ref: str) -> str:
    if not base_ref:
        return ""
    return _git_output(root, ["merge-base", "HEAD", base_ref])


def _known_generated(path: str, config: WikiConfig) -> bool:
    generated_paths = {
        config.paths["operation_page"],
        config.paths["operational_pass_page"],
        config.paths["source_registry_page"],
        str((config.root_entity or {}).get("input_stage_page") or ""),
        "data/derived/wiki/score-events-mirror.jsonl",
    }
    return path in generated_paths or path.startswith(config.paths["derived_root"].rstrip("/") + "/")


def _category(path: str, config: WikiConfig) -> str:
    memory_root = config.paths["memory_root"].rstrip("/") + "/"
    if path.startswith(memory_root):
        return "memory"
    if path.startswith("apps/wiki-cockpit/"):
        return "web_cockpit"
    if path.startswith("wiki_core/"):
        return "core"
    if path.startswith("scripts/"):
        return "cli"
    if path.startswith("tests/"):
        return "tests"
    if path.startswith(".skills/"):
        return "agent_skill"
    if path.startswith("docs/references/templates/"):
        return "template"
    if path.startswith("docs/"):
        return "docs"
    if path in {"wiki.config.yaml", "wiki.page-types.yaml", "wiki.targets.yaml"}:
        return "config"
    return "repo"


def _risk_hints(path: str, status: str, config: WikiConfig) -> list[str]:
    hints: list[str] = []
    category = _category(path, config)
    if _known_generated(path, config):
        hints.append("generated_artifact")
    if category == "memory":
        hints.append("memory_review")
    if category in {"core", "cli", "agent_skill", "template", "config"}:
        hints.append("method_contract")
    if category == "tests":
        hints.append("test_coverage")
    # Public-boundary is about publishing WIKI CONTENT, not app build assets.
    # The old `"public" in path` fired on apps/wiki-cockpit/public/** (the
    # cockpit's own demo snapshot — 19 false alarms on the real repo). Anchor it
    # to memory-root content in a published area only.
    if category == "memory" and "public" in path.lower():
        hints.append("public_boundary")
    if status.startswith("D"):
        hints.append("deletion_review")
    return hints


def _parse_name_status(output: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0].strip()
        path = parts[-1].strip() if len(parts) > 1 else ""
        if path:
            rows.append((status, path))
    return rows


def _parse_numstat(output: str) -> dict[str, dict[str, int]]:
    stats: dict[str, dict[str, int]] = {}
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        raw_additions, raw_deletions, path = parts[0], parts[1], parts[-1]
        additions = int(raw_additions) if raw_additions.isdigit() else 0
        deletions = int(raw_deletions) if raw_deletions.isdigit() else 0
        stats[path] = {"additions": additions, "deletions": deletions}
    return stats


def _status_rows(git_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for file_row in git_payload.get("worktree", {}).get("changed_files", []):
        path = str(file_row.get("path") or "")
        if path:
            rows[path] = dict(file_row)
    return rows


def _redact(text: str) -> str:
    return SECRET_VALUE_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", text)


def _preview(root: Path, args: list[str], *, max_lines: int = 18) -> list[str]:
    code, stdout, _stderr = _run_git(root, args, timeout=20)
    if code != 0:
        return []
    preview: list[str] = []
    for raw in stdout.splitlines():
        if raw.startswith(("+++", "---")):
            continue
        if raw.startswith("@@") or raw.startswith(("+", "-")):
            line = _redact(raw.rstrip())
            preview.append(line[:220])
        if len(preview) >= max_lines:
            break
    return preview


def _file_record(
    path: str,
    status: str,
    config: WikiConfig,
    *,
    change_sources: set[str],
    numstat: dict[str, int] | None = None,
    preview: list[str] | None = None,
    working_row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "path": path,
        "status": status,
        "category": _category(path, config),
        "change_sources": sorted(change_sources),
        "additions": int((numstat or {}).get("additions") or 0),
        "deletions": int((numstat or {}).get("deletions") or 0),
        "known_generated": _known_generated(path, config),
        "staged": bool((working_row or {}).get("staged")),
        "unstaged": bool((working_row or {}).get("unstaged")),
        "risk_hints": _risk_hints(path, status, config),
        "preview": preview or [],
    }


def build_diff_payload(root: Path, config: WikiConfig, git_payload: dict[str, Any]) -> dict[str, Any]:
    default_branch = str(git_payload.get("default_branch") or "main")
    current_branch = str(git_payload.get("current_branch") or "")
    if not _is_git_repo(root):
        return {
            "schema_version": WEB_DIFF_SCHEMA_VERSION,
            "repo_id": config.repo_id,
            "available": False,
            "compare": {
                "default_branch": default_branch,
                "base_ref": "",
                "merge_base": "",
                "head_commit": "",
                "current_branch": current_branch,
            },
            "summary": {
                "file_count": 0,
                "branch_file_count": 0,
                "working_tree_file_count": 0,
                "insertions": 0,
                "deletions": 0,
                "status_counts": {},
                "privacy_review_required": False,
            },
            "commands": [],
            "files": [],
        }

    base_ref = _base_ref(root, default_branch)
    merge_base = _merge_base(root, base_ref)
    compare_range = f"{merge_base}..HEAD" if merge_base else ""
    branch_rows: list[tuple[str, str]] = []
    branch_numstat: dict[str, dict[str, int]] = {}
    if compare_range and current_branch != default_branch:
        code, stdout, _stderr = _run_git(root, ["diff", "--name-status", "-M", compare_range])
        if code == 0:
            branch_rows = _parse_name_status(stdout)
        code, stdout, _stderr = _run_git(root, ["diff", "--numstat", "-M", compare_range])
        if code == 0:
            branch_numstat = _parse_numstat(stdout)

    working_rows = _status_rows(git_payload)
    records: dict[str, dict[str, Any]] = {}

    for status, path in branch_rows:
        preview = _preview(root, ["diff", "--unified=0", "--no-ext-diff", "--no-color", compare_range, "--", path])
        records[path] = _file_record(
            path,
            status,
            config,
            change_sources={"branch"},
            numstat=branch_numstat.get(path),
            preview=preview,
            working_row=working_rows.get(path),
        )

    for path, working_row in working_rows.items():
        status = str(working_row.get("status") or "")
        source = "working_tree"
        if working_row.get("staged") and not working_row.get("unstaged"):
            source = "staged"
        if path in records:
            records[path]["change_sources"] = sorted({*records[path]["change_sources"], source})
            records[path]["staged"] = bool(working_row.get("staged"))
            records[path]["unstaged"] = bool(working_row.get("unstaged"))
            continue
        preview_args = ["diff", "--unified=0", "--no-ext-diff", "--no-color", "--", path]
        if source == "staged":
            preview_args = ["diff", "--cached", "--unified=0", "--no-ext-diff", "--no-color", "--", path]
        records[path] = _file_record(
            path,
            status,
            config,
            change_sources={source},
            preview=_preview(root, preview_args),
            working_row=working_row,
        )

    files = sorted(records.values(), key=lambda item: (str(item["category"]), str(item["path"])))
    status_counts = Counter(str(file.get("status") or "")[:1] or "?" for file in files)
    insertions = sum(int(file.get("additions") or 0) for file in files)
    deletions = sum(int(file.get("deletions") or 0) for file in files)
    privacy_required = any(
        "memory_review" in file.get("risk_hints", []) or "public_boundary" in file.get("risk_hints", [])
        for file in files
    )
    commands = [
        ["git", "diff", "--stat"],
        ["git", "diff", "--name-status"],
        ["git", "diff", "--cached", "--stat"],
        ["git", "diff", "--cached", "--name-status"],
    ]
    if compare_range:
        commands.insert(0, ["git", "diff", "--stat", compare_range])
        commands.insert(1, ["git", "diff", "--name-status", compare_range])

    return {
        "schema_version": WEB_DIFF_SCHEMA_VERSION,
        "repo_id": config.repo_id,
        "available": True,
        "compare": {
            "default_branch": default_branch,
            "base_ref": base_ref,
            "merge_base": merge_base[:12] if merge_base else "",
            "head_commit": _head_commit(root)[:12],
            "current_branch": current_branch,
        },
        "summary": {
            "file_count": len(files),
            "branch_file_count": len(branch_rows),
            "working_tree_file_count": len(working_rows),
            "insertions": insertions,
            "deletions": deletions,
            "status_counts": dict(sorted(status_counts.items())),
            "privacy_review_required": privacy_required,
        },
        "commands": commands,
        "files": files,
    }
