"""Deterministic downstream-upgrade contracts for Wiki Viva v8.

This module is intentionally read-only.  It inventories public package metadata,
compares portable files, compiles a preflight report and validates migration
evidence.  It never copies toolkit files or changes a consumer repository.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable

import yaml

from wiki_core.detectors import scan_text


UPGRADE_PACKAGE_SCHEMA_VERSION = "wiki_viva_upgrade_package.v1"
CONSUMER_INVENTORY_SCHEMA_VERSION = "wiki_viva_consumer_inventory.v1"
PREFLIGHT_SCHEMA_VERSION = "wiki_viva_upgrade_preflight.v1"
GATE_EVIDENCE_SCHEMA_VERSION = "wiki_viva_gate_evidence.v1"
MIGRATION_EVIDENCE_SCHEMA_VERSION = "wiki_viva_migration_evidence.v1"
MIGRATION_REPORT_SCHEMA_VERSION = "wiki_viva_migration_report.v1"

CONSUMER_TYPES = {
    "public_example",
    "private_operational_wiki",
    "client_internal_wiki",
    "pilot",
    "adapter_only",
    "unknown",
}
RUNTIMES = {"legacy", "compat", "v8", "no_cockpit", "unknown"}
OPERATORS = {
    "none",
    "static_demo",
    "localhost_operator",
    "source_sync",
    "codex_jobs",
    "unknown",
}
PRIVACY_RISKS = {
    "public_safe",
    "private_pii",
    "financial_personal",
    "client_internal",
    "secret_adjacent",
    "unknown",
}
UPGRADE_WAVES = {"public_kit", "pilot", "wave_1", "wave_2", "paused", "blocked"}

_SHA_RE = re.compile(r"[0-9a-f]{40,64}")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_UNPINNED = {
    "",
    "head",
    "main",
    "unreleased",
    "required_at_release",
    "set_at_release",
    "unknown",
}
_RELEASABLE_STATUSES = {"candidate", "release_candidate", "ready", "released"}
_SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "coverage",
    "test-results",
    "playwright-report",
    ".playwright-cli",
}


def load_mapping(path: Path) -> dict[str, Any]:
    """Load JSON or YAML and require a mapping root."""

    text = path.read_text(encoding="utf-8")
    data = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping root")
    return data


def canonical_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def deterministic_id(prefix: str, data: Any) -> str:
    digest = hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}:{digest}"


def _require_mapping(value: Any, name: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        errors.append(f"{name} must be a mapping")
        return {}
    return value


def _require_list(value: Any, name: str, errors: list[str]) -> list[Any]:
    if not isinstance(value, list):
        errors.append(f"{name} must be a list")
        return []
    return value


def validate_upgrade_package(package: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if package.get("schema_version") != UPGRADE_PACKAGE_SCHEMA_VERSION:
        errors.append(f"schema_version must be {UPGRADE_PACKAGE_SCHEMA_VERSION}")
    release = _require_mapping(package.get("release"), "release", errors)
    for field in ("id", "status", "source_sha", "plan"):
        if field not in release:
            errors.append(f"release.{field} is required")
    portable = _require_mapping(
        package.get("portable_import"), "portable_import", errors
    )
    allow = _require_list(portable.get("allow"), "portable_import.allow", errors)
    block = _require_list(portable.get("block"), "portable_import.block", errors)
    if not allow:
        errors.append("portable_import.allow cannot be empty")
    if not block:
        errors.append("portable_import.block cannot be empty")
    for group, values in (("allow", allow), ("block", block)):
        for value in values:
            if (
                not isinstance(value, str)
                or not value.strip()
                or value.startswith("/")
                or ".." in Path(value).parts
            ):
                errors.append(
                    f"portable_import.{group} contains an unsafe pattern: {value!r}"
                )
    schemas = _require_mapping(
        package.get("contract_versions"), "contract_versions", errors
    )
    for field in (
        "snapshot",
        "blocks",
        "visual_grammar",
        "runtime",
        "source_lifecycle",
    ):
        if not str(schemas.get(field) or "").strip():
            errors.append(f"contract_versions.{field} is required")
    compatibility = _require_list(package.get("compatibility"), "compatibility", errors)
    for index, entry in enumerate(compatibility):
        row = _require_mapping(entry, f"compatibility[{index}]", errors)
        for field in (
            "surface",
            "v8_behavior",
            "warning_becomes_error",
            "removal_target",
        ):
            if not str(row.get(field) or "").strip():
                errors.append(f"compatibility[{index}].{field} is required")
    preflight = _require_mapping(package.get("preflight"), "preflight", errors)
    required_gates = _require_list(
        preflight.get("required_gates"), "preflight.required_gates", errors
    )
    if not required_gates:
        errors.append("preflight.required_gates cannot be empty")
    migration = _require_mapping(package.get("migration"), "migration", errors)
    migration_gates = _require_list(
        migration.get("required_gates"), "migration.required_gates", errors
    )
    if not migration_gates:
        errors.append("migration.required_gates cannot be empty")
    return errors


def package_is_pinned(package: dict[str, Any]) -> bool:
    release = package.get("release") if isinstance(package.get("release"), dict) else {}
    sha = str(release.get("source_sha") or "").strip().lower()
    release_id = str(release.get("id") or "").strip().lower()
    status = str(release.get("status") or "").strip().lower()
    return bool(
        _valid_sha(sha)
        and release_id not in _UNPINNED
        and status in _RELEASABLE_STATUSES
    )


def validate_consumer_inventory(inventory: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if inventory.get("schema_version") != CONSUMER_INVENTORY_SCHEMA_VERSION:
        errors.append(f"schema_version must be {CONSUMER_INVENTORY_SCHEMA_VERSION}")
    if not _DATE_RE.fullmatch(str(inventory.get("verified_on") or "")):
        errors.append("verified_on must be YYYY-MM-DD")
    consumers = _require_list(inventory.get("consumers"), "consumers", errors)
    seen: set[str] = set()
    for index, value in enumerate(consumers):
        prefix = f"consumers[{index}]"
        consumer = _require_mapping(value, prefix, errors)
        consumer_id = str(consumer.get("id") or "")
        if not consumer_id:
            errors.append(f"{prefix}.id is required")
        elif consumer_id in seen:
            errors.append(f"duplicate consumer id: {consumer_id}")
        seen.add(consumer_id)
        repository = _require_mapping(
            consumer.get("repository"), f"{prefix}.repository", errors
        )
        for field in ("name", "path", "remote", "owner"):
            if not str(repository.get(field) or "").strip():
                errors.append(f"{prefix}.repository.{field} is required")
        if consumer.get("consumer_type") not in CONSUMER_TYPES:
            errors.append(
                f"{prefix}.consumer_type must be one of {sorted(CONSUMER_TYPES)}"
            )
        if consumer.get("current_runtime") not in RUNTIMES:
            errors.append(f"{prefix}.current_runtime must be one of {sorted(RUNTIMES)}")
        if consumer.get("local_operator") not in OPERATORS:
            errors.append(f"{prefix}.local_operator must be one of {sorted(OPERATORS)}")
        if consumer.get("privacy_risk") not in PRIVACY_RISKS:
            errors.append(
                f"{prefix}.privacy_risk must be one of {sorted(PRIVACY_RISKS)}"
            )
        if consumer.get("upgrade_wave") not in UPGRADE_WAVES:
            errors.append(
                f"{prefix}.upgrade_wave must be one of {sorted(UPGRADE_WAVES)}"
            )
        for field in (
            "current_kit_version",
            "current_layout",
            "local_templates",
            "drift_status",
        ):
            if field not in consumer:
                errors.append(f"{prefix}.{field} is required")
    return errors


def consumer_from_inventory(
    inventory: dict[str, Any], consumer_id: str
) -> dict[str, Any]:
    for consumer in inventory.get("consumers") or []:
        if isinstance(consumer, dict) and consumer.get("id") == consumer_id:
            return consumer
    raise KeyError(f"consumer not found in inventory: {consumer_id}")


def _matches(path: str, pattern: str) -> bool:
    normalized = path.lstrip("./")
    candidate = pattern.lstrip("./")
    if candidate.endswith("/**"):
        prefix = candidate[:-3].rstrip("/")
        # ``foo/**`` is a directory contract, so it includes both ``foo`` and
        # every descendant. Match the prefix as a glob as well: portable
        # package entries such as ``.skills/wiki-*/**`` otherwise fall into
        # this branch and are incorrectly treated as a literal directory.
        return fnmatch.fnmatchcase(normalized, prefix) or fnmatch.fnmatchcase(
            normalized, candidate
        )
    if candidate.endswith("/"):
        return normalized.startswith(candidate)
    return normalized == candidate or fnmatch.fnmatchcase(normalized, candidate)


def portable_path_status(path: str, package: dict[str, Any]) -> tuple[bool, str]:
    portable = package.get("portable_import") or {}
    for pattern in portable.get("block") or []:
        if _matches(path, str(pattern)):
            return False, f"blocked by {pattern}"
    for pattern in portable.get("allow") or []:
        if _matches(path, str(pattern)):
            return True, f"allowed by {pattern}"
    return False, "not in portable allowlist"


def _iter_files(root: Path) -> Iterable[str]:
    if not root.exists():
        return []
    files: list[str] = []
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        files.append(rel.as_posix())
    return sorted(files)


def _ignore_patterns(root: Path) -> list[str]:
    path = root / ".toolkit-drift-ignore"
    if not path.exists():
        return []
    return sorted(
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def compare_portable_files(
    kit_root: Path,
    consumer_root: Path,
    package: dict[str, Any],
    *,
    source_sha: str | None = None,
) -> dict[str, Any]:
    """Compare allowlisted files byte-for-byte.

    When ``source_sha`` is supplied, the public side comes from that exact Git
    tree rather than the kit checkout's working tree.  This matters for release
    metadata commits made after the payload they pin: preflight must never
    silently compare a consumer with later, unpinned files on disk.
    """

    ignored_patterns = _ignore_patterns(consumer_root)

    def selected(root: Path) -> set[str]:
        return {
            rel
            for rel in _iter_files(root)
            if portable_path_status(rel, package)[0]
            and not any(_matches(rel, pattern) for pattern in ignored_patterns)
        }

    source_blobs: dict[str, str] = {}
    if source_sha:
        source_blobs = _git_tree_blobs(kit_root, source_sha)
        kit_files = {
            rel
            for rel in source_blobs
            if portable_path_status(rel, package)[0]
            and not any(_matches(rel, pattern) for pattern in ignored_patterns)
        }
    else:
        kit_files = selected(kit_root)
    consumer_files = selected(consumer_root)
    shared = kit_files & consumer_files
    if source_sha:
        blob_payloads = _git_blob_payloads(
            kit_root, {source_blobs[rel] for rel in shared}
        )
        differing = sorted(
            rel
            for rel in shared
            if blob_payloads[source_blobs[rel]] != (consumer_root / rel).read_bytes()
        )
    else:
        differing = sorted(
            rel
            for rel in shared
            if (kit_root / rel).read_bytes() != (consumer_root / rel).read_bytes()
        )
    report = {
        "only_in_kit": sorted(kit_files - consumer_files),
        "only_in_consumer": sorted(consumer_files - kit_files),
        "content_differs": differing,
        "ignored_per_repo": ignored_patterns,
        "source_mode": "pinned_git_tree" if source_sha else "working_tree",
        "source_sha": source_sha or "",
    }
    report["drift_total"] = sum(
        len(report[key])
        for key in ("only_in_kit", "only_in_consumer", "content_differs")
    )
    return report


def _git_commit_available(root: Path, sha: str) -> bool:
    if not sha:
        return False
    try:
        subprocess.run(
            ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
            cwd=root,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


def _git_tree_blobs(root: Path, sha: str) -> dict[str, str]:
    """Return repository-relative blob paths for one exact Git tree."""

    try:
        raw = subprocess.check_output(
            ["git", "ls-tree", "-r", "-z", sha],
            cwd=root,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"release source_sha is unavailable in kit checkout: {sha}") from exc
    blobs: dict[str, str] = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        metadata, separator, raw_path = record.partition(b"\t")
        parts = metadata.split()
        if not separator or len(parts) != 3 or parts[1] != b"blob":
            continue
        path = raw_path.decode("utf-8", errors="surrogateescape")
        blobs[path] = parts[2].decode("ascii")
    return blobs


def _git_blob_payloads(root: Path, object_ids: set[str]) -> dict[str, bytes]:
    """Read many Git blobs through one batch process."""

    if not object_ids:
        return {}
    ordered = sorted(object_ids)
    process = subprocess.Popen(
        ["git", "cat-file", "--batch"],
        cwd=root,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    process.stdin.write("".join(f"{oid}\n" for oid in ordered).encode("ascii"))
    process.stdin.close()
    payloads: dict[str, bytes] = {}
    try:
        for requested in ordered:
            header = process.stdout.readline().decode("ascii", errors="replace").strip()
            parts = header.split()
            if len(parts) != 3 or parts[1] != "blob":
                raise ValueError(f"could not read release blob {requested}: {header}")
            size = int(parts[2])
            payload = process.stdout.read(size)
            terminator = process.stdout.read(1)
            if len(payload) != size or terminator != b"\n":
                raise ValueError(f"truncated release blob {requested}")
            payloads[requested] = payload
    finally:
        stderr = process.stderr.read().decode("utf-8", errors="replace").strip()
        return_code = process.wait()
    if return_code != 0:
        raise ValueError(f"could not read release blobs: {stderr or return_code}")
    return payloads


def _git(root: Path, *args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=root, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def git_state(root: Path) -> dict[str, Any]:
    status = _git(root, "status", "--porcelain=v1")
    entries = sorted(line for line in status.splitlines() if line)
    return {
        "head_sha": _git(root, "rev-parse", "HEAD"),
        "branch": _git(root, "branch", "--show-current"),
        "status_short": entries,
        "dirty_count": len(entries),
    }


def _safe_config(root: Path) -> dict[str, Any]:
    config_path = root / "wiki.config.yaml"
    if not config_path.exists():
        return {}
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def configured_layout(root: Path) -> dict[str, Any]:
    config = _safe_config(root)
    paths = config.get("paths") if isinstance(config.get("paths"), dict) else {}
    contexts = config.get("contexts") or []
    if isinstance(contexts, str):
        contexts = [item.strip() for item in contexts.split(",") if item.strip()]
    if not isinstance(contexts, list):
        contexts = []
    return {
        "language": str(config.get("language") or "en"),
        "context_count": len(contexts),
        "memory_root": str(paths.get("memory_root") or "memories"),
        "references_root": str(paths.get("references_root") or "docs/references"),
        "derived_root": str(paths.get("derived_root") or "data/derived/wiki"),
        "cockpit_root": "apps/wiki-cockpit"
        if (root / "apps/wiki-cockpit").is_dir()
        else "",
    }


def discover_local_overrides(root: Path) -> dict[str, Any]:
    known = [
        "wiki.config.yaml",
        "wiki.targets.yaml",
        "wiki.templates.local.yaml",
        "wiki.page-types.yaml",
        "wiki.page-types.local.yaml",
        "apps/wiki-cockpit/public/wiki-cockpit.config.json",
        ".toolkit-drift-ignore",
    ]
    present = [rel for rel in known if (root / rel).exists()]
    secret_adjacent = sum(
        1 for rel in (".env", ".env.local", ".env.production") if (root / rel).exists()
    )
    source_adapter_count = (
        sum(
            1
            for path in (root / "scripts").glob("wiki_*source*.py")
            if path.is_file() and not path.is_symlink()
        )
        if (root / "scripts").is_dir()
        else 0
    )
    return {
        "known_files": present,
        "source_adapter_count": source_adapter_count,
        "secret_adjacent_file_count": secret_adjacent,
    }


def _snapshot_state(
    root: Path, layout: dict[str, Any], allow_sample: bool
) -> dict[str, Any]:
    derived = (
        root
        / str(layout.get("derived_root") or "data/derived/wiki")
        / "web-snapshot"
        / "manifest.json"
    )
    sample = root / "apps/wiki-cockpit/public/sample-snapshot/manifest.json"
    candidate: Path | None = (
        derived
        if derived.exists()
        else sample
        if allow_sample and sample.exists()
        else None
    )
    if candidate is None:
        return {"available": False, "kind": "missing", "manifest": ""}
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "available": False,
            "kind": "invalid",
            "manifest": candidate.relative_to(root).as_posix(),
        }
    return {
        "available": True,
        "kind": "real" if candidate == derived else "public_sample",
        "manifest": candidate.relative_to(root).as_posix(),
        "schema_version": str(payload.get("schema_version") or ""),
        "snapshot_id": str(payload.get("snapshot_id") or ""),
        "bundle_hash": str(payload.get("bundle_hash") or ""),
    }


def validate_gate_evidence(
    evidence: dict[str, Any], required: list[str], head_sha: str
) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    if evidence.get("schema_version") != GATE_EVIDENCE_SCHEMA_VERSION:
        errors.append(
            f"gate evidence schema_version must be {GATE_EVIDENCE_SCHEMA_VERSION}"
        )
    if str(evidence.get("consumer_head") or "") != head_sha:
        errors.append(
            "gate evidence consumer_head does not match the current consumer HEAD"
        )
    gates = evidence.get("gates") if isinstance(evidence.get("gates"), list) else []
    by_id = {
        str(item.get("id")): item
        for item in gates
        if isinstance(item, dict) and item.get("id")
    }
    for gate_id in required:
        gate = by_id.get(str(gate_id))
        if gate is None:
            errors.append(f"missing required gate evidence: {gate_id}")
        elif gate_id == "toolkit_drift" and gate.get("status") not in {
            "pass",
            "reviewed",
        }:
            errors.append("toolkit_drift evidence must be pass or reviewed")
        elif gate_id != "toolkit_drift" and gate.get("status") != "pass":
            errors.append(f"required gate did not pass: {gate_id}")
        elif not str(gate.get("command") or "").strip():
            errors.append(f"required gate has no recorded command: {gate_id}")
    return errors, {
        "required": required,
        "recorded": sorted(by_id),
        "statuses": {
            gate_id: str(by_id[gate_id].get("status") or "")
            for gate_id in sorted(by_id)
        },
        "all_pass": not errors,
    }


def _redacted_identifier(kind: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{kind}:sha256:{digest}"


def _check(
    check_id: str, status: str, evidence: str, blocking: bool = True
) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": status,
        "blocking": blocking,
        "evidence": evidence,
    }


def build_preflight_report(
    *,
    kit_root: Path,
    consumer_root: Path,
    package: dict[str, Any],
    consumer: dict[str, Any],
    gate_evidence: dict[str, Any] | None,
    checked_on: str,
    redact: bool = False,
) -> dict[str, Any]:
    """Compile a deterministic, read-only preflight report for one consumer."""

    package_errors = validate_upgrade_package(package)
    if package_errors:
        raise ValueError("invalid upgrade package: " + "; ".join(package_errors))
    if not _DATE_RE.fullmatch(checked_on):
        raise ValueError("checked_on must be YYYY-MM-DD")
    if not consumer_root.is_dir():
        raise ValueError(f"consumer root does not exist: {consumer_root}")

    state = git_state(consumer_root)
    layout = configured_layout(consumer_root)
    overrides = discover_local_overrides(consumer_root)
    release_pinned = package_is_pinned(package)
    release_sha = str((package.get("release") or {}).get("source_sha") or "")
    release_source_available = release_pinned and _git_commit_available(
        kit_root, release_sha
    )
    if release_source_available:
        drift = compare_portable_files(
            kit_root, consumer_root, package, source_sha=release_sha
        )
    else:
        drift = {
            "only_in_kit": [],
            "only_in_consumer": [],
            "content_differs": [],
            "ignored_per_repo": _ignore_patterns(consumer_root),
            "drift_total": 0,
            "source_mode": "pinned_git_tree",
            "source_sha": release_sha,
        }
    allow_sample = consumer.get("local_operator") == "static_demo"
    snapshot = _snapshot_state(consumer_root, layout, allow_sample=allow_sample)
    required_gates = [
        str(value)
        for value in (package.get("preflight") or {}).get("required_gates") or []
    ]
    gate_errors, gate_summary = validate_gate_evidence(
        gate_evidence or {}, required_gates, state["head_sha"]
    )

    checks: list[dict[str, Any]] = []
    checks.append(
        _check(
            "release_pinned",
            "pass" if release_pinned else "fail",
            "exact public release and SHA"
            if release_pinned
            else "release source_sha is not pinned",
        )
    )
    checks.append(
        _check(
            "release_source_available",
            "pass" if release_source_available else "fail",
            f"pinned Git tree available: {release_sha}"
            if release_source_available
            else f"pinned Git tree unavailable: {release_sha or 'missing'}",
        )
    )
    branch_prefix = str(
        (package.get("preflight") or {}).get("branch_prefix") or "wiki/"
    )
    branch_ok = bool(state["branch"] and state["branch"].startswith(branch_prefix))
    checks.append(
        _check(
            "upgrade_branch",
            "pass" if branch_ok else "fail",
            state["branch"] or "detached/unknown",
        )
    )
    checks.append(
        _check(
            "clean_worktree",
            "pass" if state["dirty_count"] == 0 else "fail",
            f"dirty_count={state['dirty_count']}",
        )
    )
    checks.append(
        _check(
            "current_gates",
            "pass" if not gate_errors else "fail",
            "; ".join(gate_errors)
            if gate_errors
            else "all required gates passed at current HEAD",
        )
    )
    drift_evidence_status = str(
        (gate_summary.get("statuses") or {}).get("toolkit_drift") or ""
    )
    if not release_source_available:
        checks.append(
            _check(
                "toolkit_drift",
                "fail",
                "cannot compare drift because the pinned release tree is unavailable",
            )
        )
    elif drift["drift_total"] == 0 and drift_evidence_status == "pass":
        checks.append(_check("toolkit_drift", "pass", "drift_total=0"))
    elif drift["drift_total"] > 0 and drift_evidence_status == "reviewed":
        checks.append(
            _check(
                "toolkit_drift",
                "warn",
                f"drift_total={drift['drift_total']}; explicitly reviewed for import/adaptation",
                blocking=False,
            )
        )
    else:
        checks.append(
            _check(
                "toolkit_drift",
                "fail",
                f"drift_total={drift['drift_total']}; evidence_status={drift_evidence_status or 'missing'}",
            )
        )
    snapshot_required = consumer.get("current_runtime") not in {"no_cockpit", "unknown"}
    snapshot_ok = snapshot["available"] or not snapshot_required
    checks.append(
        _check(
            "current_snapshot",
            "pass" if snapshot_ok else "fail",
            f"kind={snapshot['kind']}",
            blocking=snapshot_required,
        )
    )
    target_snapshot = str(
        (package.get("contract_versions") or {}).get("snapshot") or ""
    )
    current_snapshot = str(snapshot.get("schema_version") or "")
    if (
        snapshot["available"]
        and target_snapshot
        and current_snapshot != target_snapshot
    ):
        checks.append(
            _check(
                "snapshot_schema_migration",
                "warn",
                f"current={current_snapshot or 'unknown'}; target={target_snapshot}",
                blocking=False,
            )
        )
    privacy_risk = str(consumer.get("privacy_risk") or "unknown")
    redaction_required = bool(
        consumer.get("evidence_redaction_required", privacy_risk != "public_safe")
    )
    privacy_ok = privacy_risk not in {"unknown", "secret_adjacent"} and (
        not redaction_required or redact
    )
    checks.append(
        _check(
            "privacy_evidence",
            "pass" if privacy_ok else "fail",
            f"risk={privacy_risk}; redacted={redact}",
        )
    )
    if overrides["known_files"] or overrides["source_adapter_count"]:
        checks.append(
            _check(
                "local_overrides",
                "warn",
                "local overrides require reviewed adaptation",
                blocking=False,
            )
        )

    blockers = [
        item["id"] for item in checks if item["status"] == "fail" and item["blocking"]
    ]
    warnings = [item["id"] for item in checks if item["status"] == "warn"]
    status_paths = state["status_short"]
    status_entry_count = len(status_paths)
    consumer_head = state["head_sha"]
    if redact:
        # A hash per private path is still linkable and vulnerable to guessing
        # from a small set of likely repository filenames. Public evidence only
        # needs the aggregate dirty count; detailed paths stay in the private
        # consumer-side report.
        status_paths = []
        consumer_head = (
            _redacted_identifier("consumer-head", consumer_head)
            if consumer_head
            else ""
        )
        if snapshot.get("snapshot_id"):
            snapshot["snapshot_id"] = _redacted_identifier(
                "snapshot", str(snapshot["snapshot_id"])
            )
    repository = (
        consumer.get("repository")
        if isinstance(consumer.get("repository"), dict)
        else {}
    )
    report = {
        "schema_version": PREFLIGHT_SCHEMA_VERSION,
        "checked_on": checked_on,
        "status": "ready" if not blockers else "blocked",
        "source_package": {
            "release": str((package.get("release") or {}).get("id") or ""),
            "source_sha": str((package.get("release") or {}).get("source_sha") or ""),
            "plan": str((package.get("release") or {}).get("plan") or ""),
        },
        "consumer_before": {
            "id": str(consumer.get("id") or ""),
            "repository": str(repository.get("name") or consumer_root.name),
            "path": "<redacted-local-path>" if redact else str(consumer_root.resolve()),
            "branch": state["branch"],
            "head_sha": consumer_head,
            "current_kit_version": str(
                consumer.get("current_kit_version") or "untracked"
            ),
            "status_short": status_paths,
            "status_entry_count": status_entry_count,
        },
        "layout": layout,
        "runtime": str(consumer.get("current_runtime") or "unknown"),
        "local_operator": str(consumer.get("local_operator") or "unknown"),
        "local_overrides": overrides,
        "privacy": {
            "risk": privacy_risk,
            "redaction_required": redaction_required,
            "report_redacted": redact,
        },
        "drift": drift
        if not redact
        else {
            "drift_total": drift["drift_total"],
            "only_in_kit_count": len(drift["only_in_kit"]),
            "only_in_consumer_count": len(drift["only_in_consumer"]),
            "content_differs_count": len(drift["content_differs"]),
            "ignored_per_repo_count": len(drift["ignored_per_repo"]),
        },
        "snapshot": snapshot,
        "gate_evidence": gate_summary,
        "checks": checks,
        "blockers": blockers,
        "warnings": warnings,
    }
    report["report_id"] = deterministic_id("preflight", report)
    return report


def migration_evidence_template(package: dict[str, Any]) -> dict[str, Any]:
    required_gates = [
        str(value)
        for value in (package.get("migration") or {}).get("required_gates") or []
    ]
    return {
        "schema_version": MIGRATION_EVIDENCE_SCHEMA_VERSION,
        "source": {
            "release": str((package.get("release") or {}).get("id") or ""),
            "sha": "REPLACE_WITH_PINNED_PUBLIC_SHA",
            "plan": str((package.get("release") or {}).get("plan") or ""),
        },
        "consumer_before": {
            "repository": "consumer-id",
            "branch": "wiki/upgrade-v8",
            "head_sha": "REPLACE_WITH_PREVIOUS_CONSUMER_SHA",
            "kit_version": "untracked",
            "gate_status": "pass",
        },
        "consumer_after": {
            "branch": "wiki/upgrade-v8",
            "import_commit_sha": "REPLACE_WITH_IMPORT_COMMIT_SHA",
            "artifact_commit_sha": None,
            "adaptation_commit_sha": None,
        },
        "files_imported": ["wiki_core/upgrade.py"],
        "local_overrides_kept": ["wiki.config.yaml", "wiki.targets.yaml"],
        "warnings": [],
        "fixtures_added": [],
        "gates": [
            {
                "id": gate_id,
                "command": f"record exact {gate_id} command",
                "status": "pass",
            }
            for gate_id in required_gates
        ],
        "visual_qa_evidence": [
            {
                "profile": profile,
                "route_ref": "public-fixture:canonical-root",
                "center_ref": "public-fixture:root",
                "viewport": "1440x1000" if profile == "desktop" else "390x844",
                "browser": "chromium" if profile != "mobile" else "webkit",
                "screenshot_ref": f"qa/{profile}.png",
                "console_status": "clean",
                "network_status": "clean",
                "sample_fallback": False,
            }
            for profile in ("desktop", "mobile", "fallback")
        ],
        "rollback": {
            "previous_sha": "REPLACE_WITH_PREVIOUS_CONSUMER_SHA",
            "import_commit_sha": "REPLACE_WITH_IMPORT_COMMIT_SHA",
            "command": "git revert <adaptation> <artifacts> <import>",
            "preserves_local_paths": [
                "wiki.config.yaml",
                "wiki.targets.yaml",
                "memories/",
            ],
        },
    }


def _valid_sha(value: Any) -> bool:
    sha = str(value or "").lower()
    return bool(_SHA_RE.fullmatch(sha) and len(set(sha)) >= 4)


def validate_migration_evidence(
    evidence: dict[str, Any], package: dict[str, Any], *, public_export: bool = False
) -> list[str]:
    errors: list[str] = []
    if not package_is_pinned(package):
        errors.append("upgrade package release is blocked or source_sha is not pinned")
    if evidence.get("schema_version") != MIGRATION_EVIDENCE_SCHEMA_VERSION:
        errors.append(f"schema_version must be {MIGRATION_EVIDENCE_SCHEMA_VERSION}")
    source = _require_mapping(evidence.get("source"), "source", errors)
    if not str(source.get("release") or "").strip():
        errors.append("source.release is required")
    if not _valid_sha(source.get("sha")):
        errors.append("source.sha must be an exact 40-64 character Git SHA")
    if not str(source.get("plan") or "").strip():
        errors.append("source.plan is required")
    package_sha = str((package.get("release") or {}).get("source_sha") or "")
    package_release = str((package.get("release") or {}).get("id") or "")
    package_plan = str((package.get("release") or {}).get("plan") or "")
    if source.get("release") != package_release:
        errors.append("source.release does not match the upgrade package")
    if _valid_sha(package_sha) and source.get("sha") != package_sha:
        errors.append("source.sha does not match the pinned upgrade package")
    if source.get("plan") != package_plan:
        errors.append("source.plan does not match the upgrade package")

    before = _require_mapping(
        evidence.get("consumer_before"), "consumer_before", errors
    )
    for field in ("repository", "branch", "kit_version", "gate_status"):
        if not str(before.get(field) or "").strip():
            errors.append(f"consumer_before.{field} is required")
    if not _valid_sha(before.get("head_sha")):
        errors.append("consumer_before.head_sha must be an exact Git SHA")
    after = _require_mapping(evidence.get("consumer_after"), "consumer_after", errors)
    if not str(after.get("branch") or "").startswith("wiki/"):
        errors.append("consumer_after.branch must use the wiki/ prefix")
    if not _valid_sha(after.get("import_commit_sha")):
        errors.append("consumer_after.import_commit_sha must be an exact Git SHA")
    for field in ("artifact_commit_sha", "adaptation_commit_sha"):
        if after.get(field) not in (None, "") and not _valid_sha(after.get(field)):
            errors.append(f"consumer_after.{field} must be null or an exact Git SHA")

    imported = _require_list(evidence.get("files_imported"), "files_imported", errors)
    if not imported:
        errors.append("files_imported cannot be empty")
    for rel in imported:
        if str(rel).endswith("/"):
            errors.append(f"files_imported must list files, not directories: {rel!r}")
        allowed, reason = portable_path_status(str(rel), package)
        if not allowed:
            errors.append(
                f"files_imported contains non-portable path {rel!r}: {reason}"
            )
    _require_list(evidence.get("local_overrides_kept"), "local_overrides_kept", errors)
    warnings = _require_list(evidence.get("warnings"), "warnings", errors)
    for index, value in enumerate(warnings):
        warning = _require_mapping(value, f"warnings[{index}]", errors)
        for field in ("code", "message", "removal_window"):
            if not str(warning.get(field) or "").strip():
                errors.append(f"warnings[{index}].{field} is required")
    _require_list(evidence.get("fixtures_added"), "fixtures_added", errors)

    gates = _require_list(evidence.get("gates"), "gates", errors)
    by_gate = {
        str(item.get("id")): item
        for item in gates
        if isinstance(item, dict) and item.get("id")
    }
    required_gates = [
        str(value)
        for value in (package.get("migration") or {}).get("required_gates") or []
    ]
    for gate_id in required_gates:
        gate = by_gate.get(gate_id)
        if gate is None:
            errors.append(f"missing migration gate: {gate_id}")
        elif gate.get("status") != "pass":
            errors.append(f"migration gate did not pass: {gate_id}")
        elif not str(gate.get("command") or "").strip():
            errors.append(f"migration gate has no exact command: {gate_id}")

    visual = _require_list(
        evidence.get("visual_qa_evidence"), "visual_qa_evidence", errors
    )
    profiles = {str(item.get("profile")) for item in visual if isinstance(item, dict)}
    for required_profile in ("desktop", "mobile", "fallback"):
        if required_profile not in profiles:
            errors.append(f"visual_qa_evidence missing profile: {required_profile}")
    for index, value in enumerate(visual):
        item = _require_mapping(value, f"visual_qa_evidence[{index}]", errors)
        for field in (
            "route_ref",
            "center_ref",
            "viewport",
            "browser",
            "screenshot_ref",
        ):
            if not str(item.get(field) or "").strip():
                errors.append(f"visual_qa_evidence[{index}].{field} is required")
        if item.get("sample_fallback") is not False:
            errors.append(f"visual_qa_evidence[{index}].sample_fallback must be false")
        if item.get("console_status") != "clean":
            errors.append(f"visual_qa_evidence[{index}].console_status must be clean")
        if item.get("network_status") != "clean":
            errors.append(f"visual_qa_evidence[{index}].network_status must be clean")

    rollback = _require_mapping(evidence.get("rollback"), "rollback", errors)
    if not _valid_sha(rollback.get("previous_sha")):
        errors.append("rollback.previous_sha must be an exact Git SHA")
    if not _valid_sha(rollback.get("import_commit_sha")):
        errors.append("rollback.import_commit_sha must be an exact Git SHA")
    if rollback.get("previous_sha") != before.get("head_sha"):
        errors.append("rollback.previous_sha must match consumer_before.head_sha")
    if rollback.get("import_commit_sha") != after.get("import_commit_sha"):
        errors.append(
            "rollback.import_commit_sha must match consumer_after.import_commit_sha"
        )
    command = str(rollback.get("command") or "")
    if not command.startswith("git revert "):
        errors.append("rollback.command must use a reviewable git revert command")
    preserved = _require_list(
        rollback.get("preserves_local_paths"), "rollback.preserves_local_paths", errors
    )
    if not preserved:
        errors.append("rollback.preserves_local_paths cannot be empty")

    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    findings = scan_text(serialized)
    for finding in findings:
        if finding.category == "secret":
            errors.append(
                f"migration evidence contains access-secret pattern: {finding.kind}"
            )
        if public_export and finding.category == "pii":
            errors.append(
                f"public migration evidence contains PII pattern: {finding.kind}"
            )
    if public_export:
        if re.search(r"(?:/Users/|/home/|[A-Za-z]:\\)", serialized):
            errors.append("public migration evidence contains an absolute local path")
        if re.search(r"https?://[^\s\"']+\?[^\s\"']+", serialized):
            errors.append(
                "public migration evidence contains a URL with query parameters"
            )
        for index, value in enumerate(visual):
            if not isinstance(value, dict):
                continue
            route = str(value.get("route_ref") or "")
            center = str(value.get("center_ref") or "")
            if not (
                route.startswith("public-fixture:") or route.startswith("route:sha256:")
            ):
                errors.append(
                    f"visual_qa_evidence[{index}].route_ref is not public-safe"
                )
            if not (
                center.startswith("public-fixture:")
                or center.startswith("center:sha256:")
            ):
                errors.append(
                    f"visual_qa_evidence[{index}].center_ref is not public-safe"
                )
    return sorted(set(errors))


def compile_migration_report(
    evidence: dict[str, Any], package: dict[str, Any], *, public_export: bool = False
) -> dict[str, Any]:
    errors = validate_migration_evidence(evidence, package, public_export=public_export)
    before = json.loads(json.dumps(evidence.get("consumer_before") or {}))
    after = json.loads(json.dumps(evidence.get("consumer_after") or {}))
    rollback = json.loads(json.dumps(evidence.get("rollback") or {}))
    if public_export:
        replacements: dict[str, str] = {}
        before_sha = str(before.get("head_sha") or "")
        if before_sha:
            replacements[before_sha] = _redacted_identifier("consumer-head", before_sha)
            before["head_sha"] = replacements[before_sha]
        for field in (
            "import_commit_sha",
            "artifact_commit_sha",
            "adaptation_commit_sha",
        ):
            value = str(after.get(field) or "")
            if value:
                replacements[value] = _redacted_identifier(
                    f"consumer-{field.removesuffix('_sha')}", value
                )
                after[field] = replacements[value]
        for field in ("previous_sha", "import_commit_sha"):
            value = str(rollback.get(field) or "")
            if value:
                redacted = replacements.get(value) or _redacted_identifier(
                    f"rollback-{field.removesuffix('_sha')}", value
                )
                replacements[value] = redacted
                rollback[field] = redacted
        command = str(rollback.get("command") or "")
        for raw, redacted in replacements.items():
            command = command.replace(raw, redacted)
        rollback["command"] = command

    payload = {
        "schema_version": MIGRATION_REPORT_SCHEMA_VERSION,
        "status": "complete" if not errors else "blocked",
        "public_export": public_export,
        "source": evidence.get("source") or {},
        "consumer_before": before,
        "consumer_after": after,
        "files_imported": sorted(
            set(str(value) for value in evidence.get("files_imported") or [])
        ),
        "local_overrides_kept": sorted(
            set(str(value) for value in evidence.get("local_overrides_kept") or [])
        ),
        "warnings": evidence.get("warnings") or [],
        "fixtures_added": sorted(
            set(str(value) for value in evidence.get("fixtures_added") or [])
        ),
        "gates": evidence.get("gates") or [],
        "visual_qa_evidence": evidence.get("visual_qa_evidence") or [],
        "rollback": rollback,
        "validation_errors": errors,
    }
    payload["report_id"] = deterministic_id("migration", payload)
    return payload


def _md(value: Any) -> str:
    return (
        str(value if value not in (None, "") else "—")
        .replace("|", "\\|")
        .replace("\n", " ")
    )


def render_migration_report_markdown(report: dict[str, Any]) -> str:
    source = report.get("source") or {}
    before = report.get("consumer_before") or {}
    after = report.get("consumer_after") or {}
    rollback = report.get("rollback") or {}
    lines = [
        "# Wiki Viva v8 downstream migration report",
        "",
        f"- Report: `{_md(report.get('report_id'))}`",
        f"- Status: `{_md(report.get('status'))}`",
        f"- Source: `{_md(source.get('release'))}` at `{_md(source.get('sha'))}`",
        f"- Consumer: `{_md(before.get('repository'))}`",
        "",
        "```mermaid",
        "flowchart LR",
        '    Before["Consumer before"] --> Import["Faithful public import"]',
        '    Import --> Artifacts["Regenerated artifacts"]',
        '    Artifacts --> Adapt["Local adaptations"]',
        '    Adapt --> Gates["Gates and redacted QA"]',
        '    Gates --> Review["Human PR gate"]',
        "```",
        "",
        "## Commit boundary",
        "",
        "| Boundary | SHA / value |",
        "| --- | --- |",
        f"| Before HEAD | `{_md(before.get('head_sha'))}` |",
        f"| Import commit | `{_md(after.get('import_commit_sha'))}` |",
        f"| Artifact commit | `{_md(after.get('artifact_commit_sha'))}` |",
        f"| Adaptation commit | `{_md(after.get('adaptation_commit_sha'))}` |",
        "",
        "## Imported portable files",
        "",
    ]
    lines.extend(
        f"- `{_md(value)}`" for value in report.get("files_imported") or ["None"]
    )
    lines.extend(["", "## Local overrides kept", ""])
    lines.extend(
        f"- `{_md(value)}`" for value in report.get("local_overrides_kept") or ["None"]
    )
    lines.extend(
        ["", "## Gates", "", "| Gate | Status | Command |", "| --- | --- | --- |"]
    )
    for gate in report.get("gates") or []:
        lines.append(
            f"| `{_md(gate.get('id'))}` | `{_md(gate.get('status'))}` | `{_md(gate.get('command'))}` |"
        )
    lines.extend(
        [
            "",
            "## Visual QA evidence",
            "",
            "| Profile | Route | Viewport | Browser | Sample fallback |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for item in report.get("visual_qa_evidence") or []:
        lines.append(
            f"| `{_md(item.get('profile'))}` | `{_md(item.get('route_ref'))}` | `{_md(item.get('viewport'))}` | "
            f"`{_md(item.get('browser'))}` | `{_md(item.get('sample_fallback'))}` |"
        )
    lines.extend(
        [
            "",
            "## Rollback",
            "",
            f"- Previous SHA: `{_md(rollback.get('previous_sha'))}`",
            f"- Import SHA: `{_md(rollback.get('import_commit_sha'))}`",
            f"- Command: `{_md(rollback.get('command'))}`",
            f"- Preserved local paths: {', '.join(f'`{_md(value)}`' for value in rollback.get('preserves_local_paths') or [])}",
        ]
    )
    if report.get("validation_errors"):
        lines.extend(["", "## Blocking validation errors", ""])
        lines.extend(f"- {_md(value)}" for value in report["validation_errors"])
    return "\n".join(lines).rstrip() + "\n"
