from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from wiki_core.config import WikiConfig
from wiki_core.output_safety import (
    contained_output_path,
    prepare_managed_output_directory,
)
from wiki_core.web.snapshot import (
    build_snapshot,
    prepare_snapshot_artifacts,
    promote_snapshot_artifacts,
)


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
    force_unowned_output: bool = False,
) -> dict[str, Path]:
    """Write portable web-cockpit deploy inputs without choosing a host.

    The ``data_boundary`` is ENFORCED, not just declared: with the default
    ``synthetic_or_public`` boundary the bundle REFUSES to publish a snapshot
    that contains private pages (frontmatter ``visibility: private_*``) — a
    published bundle exports page bodies verbatim, so this gate is what stands
    between an operator's private memory and a public host. Pass
    ``data_boundary="private_ok"`` only for a deploy target you trust with
    private data (and say so in the deployment proof review).
    """

    clean_snapshot_base = _clean_base(snapshot_base)
    # Validate the nested base before creating or marking anything.  A value
    # such as ../../personal must not escape the deploy bundle and leave even a
    # partial output behind.
    snapshot_dir = contained_output_path(
        out_dir, _snapshot_dir(out_dir, clean_snapshot_base)
    )
    # Build and freeze the complete payload in memory before creating any
    # deploy output. Public-boundary refusal must happen before a single private
    # page body or sidecar can be promoted to a deployable directory.
    payloads = build_snapshot(
        root,
        config,
        mode=runtime_mode,
        content_sidecars=content_sidecars,
    )
    artifacts = prepare_snapshot_artifacts(
        root,
        config,
        content_sidecars=content_sidecars,
        payloads=payloads,
    )
    if data_boundary != "private_ok":
        pages = (artifacts.get("pages.json") or {}).get("pages") or []
        private_count = sum(
            1
            if str(page.get("visibility") or "").startswith("private")
            else 0
            for page in pages
            if isinstance(page, dict)
        )
        if private_count:
            raise ValueError(
                f"deploy bundle refused: {private_count} private page(s) in the snapshot "
                f"under data_boundary={data_boundary!r}. A published bundle "
                "exports page bodies verbatim. Either publish from a wiki with no private "
                "pages, or explicitly pass data_boundary='private_ok' for a trusted target."
            )
    out_dir = prepare_managed_output_directory(
        root,
        out_dir,
        kind="web_deploy_bundle",
        repo_id=config.repo_id,
        clean=False,
        force_unowned=force_unowned_output,
    )
    # ``clean`` remains a CLI/API compatibility argument. Atomic promotion
    # replaces the complete managed snapshot directory on every successful run.
    _ = clean
    written_snapshot = promote_snapshot_artifacts(
        root,
        snapshot_dir,
        artifacts,
        force_unowned_output=force_unowned_output,
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
