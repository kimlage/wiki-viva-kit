from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from wiki_core.config import WikiConfig
from wiki_core.detectors import Finding, scan_file
from wiki_core.source_manifest import build_manifest


def _contexts(config: WikiConfig) -> list[str]:
    values = [config.default_context, *config.contexts]
    return list(dict.fromkeys(context for context in values if context))


def _finding_payload(finding: Finding) -> dict[str, Any]:
    return {
        "kind": finding.kind,
        "category": finding.category,
        "severity": finding.severity,
        "line": finding.line,
        "excerpt": finding.excerpt,
        "detector": finding.detector,
    }


def _safe_repo_path(root: Path, source: str) -> Path | None:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        return None
    path = Path(source).expanduser()
    if not path.is_absolute():
        path = root / path
    try:
        resolved = path.resolve()
        resolved.relative_to(root.resolve())
    except (OSError, ValueError):
        return None
    return resolved


def _load_targets(root: Path, context: str, config: WikiConfig) -> dict[str, Any]:
    target_path = root / "wiki.targets.yaml"
    fallback = {
        "context": context,
        "target_pages": [config.root_entity.get("page") or f"{config.paths.get('memory_root', 'memories')}/index.md"],
        "target_entities": [],
    }
    if not target_path.exists():
        return fallback
    raw = yaml.safe_load(target_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return fallback
    entry = raw.get(context) or raw.get(config.default_context) or {}
    if not isinstance(entry, dict):
        return fallback
    pages = [str(value) for value in entry.get("pages", []) if str(value).strip()]
    entities = [str(value) for value in entry.get("entities", []) if str(value).strip()]
    return {
        "context": context,
        "target_pages": pages or fallback["target_pages"],
        "target_entities": entities,
    }


def _risk_flags(manifest: dict[str, Any], findings: list[Finding], local_path: Path | None) -> list[str]:
    flags: list[str] = []
    source_type = str(manifest.get("source_type") or "file")
    if manifest.get("exists") is False:
        flags.append("file_not_found")
    if source_type == "url":
        flags.append("remote_freshness_required")
    if source_type in {"pdf", "spreadsheet", "document", "email"}:
        flags.append("private_raw_review")
    if local_path is None and source_type != "url":
        flags.append("outside_repo_or_unreadable_path")
    if any(finding.category == "secret" for finding in findings):
        flags.append("secret_block")
    if any(finding.category == "pii" for finding in findings):
        flags.append("pii_private_ok_public_boundary_review")
    return list(dict.fromkeys(flags))


def triage_source(root: Path, config: WikiConfig, source: str, *, context: str | None = None) -> dict[str, Any]:
    source = source.strip()
    if not source:
        return {"ok": False, "error": "source is required"}
    selected_context = context.strip() if context else config.default_context
    if selected_context not in _contexts(config):
        selected_context = config.default_context

    local_path = _safe_repo_path(root, source)
    manifest_source = str(local_path) if local_path is not None else source
    manifest = build_manifest(manifest_source, selected_context)
    findings: list[Finding] = []
    if local_path is not None and local_path.exists() and local_path.is_file():
        findings = scan_file(local_path)

    flags = _risk_flags(manifest, findings, local_path)
    secret_block = "secret_block" in flags
    targets = _load_targets(root, selected_context, config)
    next_steps = [
        "run_ingest_dry_run",
        "review_source_manifest",
        "create_or_switch_proposal_branch",
        "execute_llm_context_pass_after_extraction",
    ]
    if secret_block:
        next_steps = ["remove_or_redact_access_secret_before_ingestion", "rerun_source_triage"]
    elif manifest.get("exists") is False:
        next_steps = ["fix_source_path_or_use_remote_url", "rerun_source_triage"]

    return {
        "ok": not secret_block,
        "source": source,
        "context": selected_context,
        "available_contexts": _contexts(config),
        "manifest": manifest,
        "source_id": manifest.get("source_id"),
        "source_type": manifest.get("source_type"),
        "exists": manifest.get("exists"),
        "risk_flags": flags,
        "secret_block": secret_block,
        "findings": [_finding_payload(finding) for finding in findings],
        "targets": targets,
        "next_steps": next_steps,
    }
