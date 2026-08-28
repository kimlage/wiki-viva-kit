from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wiki_core.config import WikiConfig
from wiki_core.web.schemas import WEB_ACTION_SCHEMA_VERSION

# Redacts `key: value`, `key = value` AND JSON `"key": "value"` — the last is
# exactly what `codex exec --json` emits, so it must be covered. Group 1 = the
# key (with any surrounding quotes), group 2 = the separator (with an optional
# opening quote); the `_redact` helpers keep both and blank the value.
SECRET_VALUE_RE = re.compile(
    r"(?i)"
    r"([\"']?(?:token|password|passwd|secret|api[_-]?key|access[_-]?token|"
    r"refresh[_-]?token|id[_-]?token|openai_api_key|bearer|authorization|cookie)[\"']?)"
    r"(\s*[:=]\s*[\"']?(?:bearer\s+)?)"
    r"([^\s\"',}]+)"
)


@dataclass(frozen=True)
class OperatorCommandCard:
    id: str
    kind: str
    title: str
    human_reason: str
    risk_level: str
    default_dry_run: bool
    commands: tuple[tuple[str, ...], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "human_reason": self.human_reason,
            "risk_level": self.risk_level,
            "default_dry_run": self.default_dry_run,
            "commands": [
                {"label": _label_for(argv), "argv": list(argv), "writes": _writes(argv)}
                for argv in self.commands
            ],
        }


PYTHON_SCRIPTS: dict[str, set[tuple[str, ...]]] = {
    "scripts/wiki_operation_compile.py": {("--check",), ("--write",)},
    "scripts/wiki_operational_pass.py": {("--check",), ("--write",)},
    "scripts/wiki_source_registry.py": {("--check",), ("--write",)},
    "scripts/wiki_input_stage.py": {("--check",), ("--write",)},
    "scripts/wiki_audit.py": {("--check",)},
    "scripts/wiki_quality_report.py": {("--check",)},
    "scripts/wiki_check_methodology_coverage.py": {("--check",)},
    "scripts/wiki_semantic_inventory.py": {("--check",)},
    "scripts/wiki_pr_summary.py": {()},
    "scripts/wiki_page_graph.py": {("--check",)},
}

GIT_ALLOWED: set[tuple[str, ...]] = {
    ("status", "--short", "--branch"),
    ("branch", "--show-current"),
    ("diff", "--stat"),
    ("diff", "--name-status"),
    ("diff", "--cached", "--stat"),
    ("diff", "--cached", "--name-status"),
    ("log", "--oneline", "--decorate", "--max-count", "12"),
}


def _python_prefix(argv: tuple[str, ...]) -> tuple[str, ...] | None:
    if len(argv) < 2:
        return None
    if argv[0] not in {"python", "python3", sys.executable}:
        return None
    script = argv[1]
    if script not in PYTHON_SCRIPTS:
        return None
    return tuple(argv[2:])


def _is_allowed_python(argv: tuple[str, ...]) -> bool:
    suffix = _python_prefix(argv)
    if suffix is None:
        return False
    script = argv[1]
    return suffix in PYTHON_SCRIPTS[script]


def _is_allowed_git(argv: tuple[str, ...]) -> bool:
    return len(argv) >= 2 and argv[0] == "git" and tuple(argv[1:]) in GIT_ALLOWED


def is_allowed_argv(argv: list[str] | tuple[str, ...]) -> bool:
    normalized = tuple(argv)
    return _is_allowed_python(normalized) or _is_allowed_git(normalized)


def _writes(argv: tuple[str, ...]) -> bool:
    return "--write" in argv


def _label_for(argv: tuple[str, ...]) -> str:
    if argv[0] == "git":
        return " ".join(argv)
    if len(argv) > 1 and argv[1].startswith("scripts/"):
        return Path(argv[1]).stem.replace("_", " ")
    return " ".join(argv)


def _redact(text: str) -> str:
    return SECRET_VALUE_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)


def build_operator_command_cards(config: WikiConfig) -> dict[str, Any]:
    actions = (
        OperatorCommandCard(
            id="git-status",
            kind="review",
            title="Check workspace",
            human_reason="Shows where you are working, what changed and whether local edits are clean.",
            risk_level="read",
            default_dry_run=False,
            commands=(("git", "status", "--short", "--branch"),),
        ),
        OperatorCommandCard(
            id="review-local-changes",
            kind="review",
            title="Review content changes",
            human_reason="Shows changed content before saving a version or preparing approval.",
            risk_level="read",
            default_dry_run=False,
            commands=(("git", "diff", "--stat"), ("git", "diff", "--name-status")),
        ),
        OperatorCommandCard(
            id="refresh-cockpit-check",
            kind="refresh",
            title="Check home view",
            human_reason="Verifies whether the operational home view matches a deterministic refresh.",
            risk_level="read",
            default_dry_run=False,
            commands=(("python3", "scripts/wiki_operation_compile.py", "--check"),),
        ),
        OperatorCommandCard(
            id="refresh-cockpit-write",
            kind="refresh",
            title="Refresh home view",
            human_reason="Refreshes the operations page as a reviewable change.",
            risk_level="derive",
            default_dry_run=True,
            commands=(("python3", "scripts/wiki_operation_compile.py", "--write"),),
        ),
        OperatorCommandCard(
            id="run-honesty-gates",
            kind="review",
            title="Run approval checks",
            human_reason="Runs the deterministic checks that should be green before human approval.",
            risk_level="read",
            default_dry_run=False,
            commands=(
                ("python3", "scripts/wiki_audit.py", "--check"),
                ("python3", "scripts/wiki_check_methodology_coverage.py", "--check"),
                ("python3", "scripts/wiki_operation_compile.py", "--check"),
                ("python3", "scripts/wiki_input_stage.py", "--check"),
                ("python3", "scripts/wiki_semantic_inventory.py", "--check"),
            ),
        ),
        OperatorCommandCard(
            id="pr-summary",
            kind="approve",
            title="Build review packet",
            human_reason="Builds a human review packet from changed content, affected areas and privacy hints.",
            risk_level="read",
            default_dry_run=False,
            commands=(("python3", "scripts/wiki_pr_summary.py"),),
        ),
        OperatorCommandCard(
            id="graph-check",
            kind="review",
            title="Check content map",
            human_reason="Verifies relationship and impact constraints before approval.",
            risk_level="read",
            default_dry_run=False,
            commands=(("python3", "scripts/wiki_page_graph.py", "--check"),),
        ),
    )
    return {
        "schema_version": WEB_ACTION_SCHEMA_VERSION,
        "repo_id": config.repo_id,
        "actions": [action.to_dict() for action in actions],
    }


def _operator_command_by_id(config: WikiConfig) -> dict[str, dict[str, Any]]:
    payload = build_operator_command_cards(config)
    return {str(action["id"]): action for action in payload["actions"]}


def _normalize_python(argv: list[str]) -> list[str]:
    if argv and argv[0] in {"python", "python3"}:
        return [sys.executable, *argv[1:]]
    return argv


def run_action(
    root: Path,
    config: WikiConfig,
    action_id: str,
    *,
    dry_run: bool | None = None,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    action = _operator_command_by_id(config).get(action_id)
    if action is None:
        return {"ok": False, "action_id": action_id, "error": "unknown action", "results": []}

    should_dry_run = bool(action["default_dry_run"] if dry_run is None else dry_run)
    results: list[dict[str, Any]] = []
    for command in action["commands"]:
        argv = [str(part) for part in command["argv"]]
        if not is_allowed_argv(argv):
            results.append(
                {
                    "argv": argv,
                    "ok": False,
                    "returncode": None,
                    "stdout": "",
                    "stderr": "command is not allowlisted",
                    "dry_run": should_dry_run,
                }
            )
            continue
        if should_dry_run:
            results.append(
                {
                    "argv": argv,
                    "ok": True,
                    "returncode": None,
                    "stdout": "dry run: command not executed",
                    "stderr": "",
                    "dry_run": True,
                }
            )
            continue
        try:
            proc = subprocess.run(
                _normalize_python(argv),
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
                timeout=timeout_seconds,
            )
            results.append(
                {
                    "argv": argv,
                    "ok": proc.returncode == 0,
                    "returncode": proc.returncode,
                    "stdout": _redact(proc.stdout),
                    "stderr": _redact(proc.stderr),
                    "dry_run": False,
                }
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            results.append(
                {
                    "argv": argv,
                    "ok": False,
                    "returncode": None,
                    "stdout": "",
                    "stderr": _redact(str(exc)),
                    "dry_run": False,
                }
            )
    return {
        "ok": all(result["ok"] for result in results),
        "action_id": action_id,
        "dry_run": should_dry_run,
        "results": results,
    }
