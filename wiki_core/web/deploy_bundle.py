from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from wiki_core.config import WikiConfig
from wiki_core.web.snapshot import write_snapshot


def _clean_base(value: str) -> str:
    cleaned = value.strip().rstrip("/")
    return cleaned or "/snapshot"


def _snapshot_dir(out_dir: Path, snapshot_base: str) -> Path:
    if "://" in snapshot_base:
        return out_dir / "snapshot"
    return out_dir / snapshot_base.lstrip("/")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _deployment_proof(
    *,
    repo_id: str,
    runtime_mode: str,
    snapshot_base: str,
    repo_label: str,
    data_boundary: str,
    target: str,
    snapshot_count: int,
) -> str:
    return "\n".join(
        [
            "# Web Cockpit Deployment Proof",
            "",
            f"- Repo: `{repo_id}`",
            f"- Target: `{target}`",
            f"- Runtime mode: `{runtime_mode}`",
            f"- Snapshot base: `{snapshot_base}`",
            f"- Repo label: `{repo_label or repo_id}`",
            f"- Data boundary: `{data_boundary}`",
            f"- Snapshot files: `{snapshot_count}`",
            "",
            "## Required Review",
            "",
            "- [ ] Confirm the snapshot contains only data allowed for this deployment boundary.",
            "- [ ] Confirm `wiki-cockpit.config.json` points at the intended static snapshot or trusted operator API.",
            "- [ ] Confirm hosted deployments do not receive broad repository tokens by default.",
            "- [ ] Confirm writes, if any, still go through proposal branches and Pull Requests.",
            "",
            "## Suggested Build",
            "",
            "```sh",
            "cd apps/wiki-cockpit",
            "npm ci",
            "npm run build",
            "```",
            "",
        ]
    )


def write_deploy_bundle(
    root: Path,
    out_dir: Path,
    config: WikiConfig,
    *,
    snapshot_base: str = "/snapshot",
    api_base: str = "",
    repo_label: str = "",
    runtime_mode: str = "static",
    data_boundary: str = "synthetic_or_public",
    target: str = "static",
    clean: bool = False,
    content_sidecars: bool = True,
) -> dict[str, Path]:
    """Write portable web-cockpit deploy inputs without choosing a host."""

    out_dir.mkdir(parents=True, exist_ok=True)
    clean_snapshot_base = _clean_base(snapshot_base)
    snapshot_dir = _snapshot_dir(out_dir, clean_snapshot_base)
    written_snapshot = write_snapshot(
        root, snapshot_dir, config, clean=clean, mode=runtime_mode, content_sidecars=content_sidecars
    )
    runtime_config = {
        "api_base": api_base.strip().rstrip("/"),
        "snapshot_base": clean_snapshot_base,
        "repo_label": repo_label.strip() or config.repo_id,
        "mode": runtime_mode,
        # Static/hosted deploys can never *run* Codex (there is no operator
        # server to launch it), but they still honor the repo's opt-out so the
        # surface is hidden when codex.enabled is false. The live capability
        # (installed/authed/usable) only ever comes from /api/codex/capability.
        "codex": {"enabled": bool(config.codex_enabled)},
    }
    config_path = out_dir / "wiki-cockpit.config.json"
    proof_path = out_dir / "DEPLOYMENT.md"
    _write_json(config_path, runtime_config)
    proof_path.write_text(
        _deployment_proof(
            repo_id=config.repo_id,
            runtime_mode=runtime_mode,
            snapshot_base=clean_snapshot_base,
            repo_label=runtime_config["repo_label"],
            data_boundary=data_boundary,
            target=target,
            snapshot_count=len(written_snapshot),
        ),
        encoding="utf-8",
    )
    return {"config": config_path, "proof": proof_path, **written_snapshot}
