#!/usr/bin/env python3
"""Certify and adopt fail-closed, resumable two-lane wiki upgrades.

``certify`` executes Lane A against one releasable public source and emits an
immutable release capsule plus its external attestation/receipt authority.
``verify-capsule`` independently recomputes that exact sealed public authority.
``plan`` is read-only and seals the Lane B conceptual delta at a clean B0.
``adopt`` can create the exact C1/C2/C3 chain from that plan, records real
command output, verifies a reverse-patch rollback in a disposable clone and
emits an adoption receipt plus machine- and human-readable reports.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import datetime as dt
import fnmatch
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import unquote_to_bytes
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


RUNNER_VERSION = "1.3.0"


def _runner_payload_manifest(runtime_root: Path) -> dict[str, Any]:
    """Hash the byte-exact Python/schema closure that executes this runner."""

    runtime_root = runtime_root.resolve(strict=True)
    candidates = [
        runtime_root / "scripts/wiki_upgrade.py",
        runtime_root / "scripts/_common.py",
        runtime_root / "scripts/_git_subject.py",
        runtime_root / "scripts/wiki_toolchain_probe.py",
    ]
    core_root = runtime_root / "wiki_core"
    schema_root = runtime_root / "docs/references/schemas"
    if not core_root.is_dir() or not schema_root.is_dir():
        raise ValueError("runner payload closure is incomplete")
    candidates.extend(path for path in core_root.rglob("*.py"))
    candidates.extend(path for path in schema_root.rglob("*.json"))
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in sorted(candidates, key=lambda value: value.as_posix()):
        if path.is_symlink() or not path.is_file():
            raise ValueError("runner payload contains a missing or unsafe file")
        resolved = path.resolve(strict=True)
        try:
            relative = resolved.relative_to(runtime_root).as_posix()
        except ValueError as exc:
            raise ValueError("runner payload escaped its runtime root") from exc
        if relative in seen:
            continue
        seen.add(relative)
        raw = resolved.read_bytes()
        mode = "100755" if resolved.stat().st_mode & 0o111 else "100644"
        entries.append(
            {
                "path": relative,
                "mode": mode,
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    if len(entries) < 4:
        raise ValueError("runner payload closure is incomplete")
    return {
        "schema_version": "wiki_viva_upgrade_runner_payload.v1",
        "scope": "python_and_schema_runtime_closure",
        "entrypoint": "scripts/wiki_upgrade.py",
        "entries": entries,
    }


def _runner_identity_version(runtime_root: Path) -> str:
    manifest = _runner_payload_manifest(runtime_root)
    serialized = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return f"{RUNNER_VERSION}+payload.{hashlib.sha256(serialized).hexdigest()}"


# A source copy can prove its byte identity with only the standard library.
# This executes before third-party and repo-local imports by design.
if __name__ == "__main__" and sys.argv[1:] == ["--version"]:
    try:
        print(
            "wiki-upgrade "
            + _runner_identity_version(Path(__file__).resolve().parents[1])
        )
    except (OSError, ValueError):
        print("wiki-upgrade invalid-runtime-payload", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(0)

from jsonschema import Draft202012Validator

try:
    from scripts._common import ROOT
except ModuleNotFoundError:
    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))

from wiki_core.upgrade_lanes import (
    AdoptionEvidenceAuthority,
    EXECUTION_ATTESTATION_SCHEMA_VERSION,
    ReleaseCapsuleAuthority,
    UpgradeLaneError,
    VerifiedReleaseCapsule,
    canonical_json,
    canonical_sha256,
    consumer_c3_authority_from_git,
    consumer_c3_authority_patterns,
    collect_release_attestation,
    load_mapping,
    public_migration_report_projection,
    seal_adoption_receipt,
    seal_release_capsule,
    select_impacted_gates,
    select_promotion_gates,
    validate_canary_evidence,
    validate_c1_projection,
    validate_boundary_ownership,
    verify_config_bound_c3_git_content,
    verify_consumer_c3_authority,
    verify_adoption_receipt,
    verify_adoption_evidence,
    verify_gate_omissions,
    verify_impact_registry,
    verify_release_capsule,
)
from wiki_core.upgrade import (
    BOUNDARY_OPERATIONS_SCHEMA_VERSION,
    package_is_pinned,
    validate_upgrade_package,
)
from wiki_core.detectors import scan_text


PLAN_SCHEMA_VERSION = "wiki_viva_upgrade_plan.v4"
STATE_SCHEMA_VERSION = "wiki_viva_upgrade_runner_state.v4"
REPORT_SCHEMA_VERSION = "wiki_viva_upgrade_runner_report.v3"
ROLLBACK_SCHEMA_VERSION = "wiki_viva_upgrade_rollback_execution.v1"
CERTIFICATION_RECEIPT_SCHEMA_VERSION = "wiki_viva_upgrade_certification_receipt.v1"

_TWO_LANE_PACKAGE = "wiki_viva_upgrade_package.v3"
_SUPPORTED_PACKAGES = {_TWO_LANE_PACKAGE}


def _matches_repo_pattern(path: str, pattern: str) -> bool:
    """Match one repo glob without allowing a skill-name ``*`` across ``/``."""

    pattern_parts = pattern.split("/")
    if (
        len(pattern_parts) == 3
        and pattern_parts[0] == ".skills"
        and pattern_parts[2] == "**"
    ):
        path_parts = path.split("/")
        return (
            len(path_parts) >= 3
            and path_parts[0] == ".skills"
            and fnmatch.fnmatchcase(path_parts[1], pattern_parts[1])
        )
    return fnmatch.fnmatchcase(path, pattern)


def _matches_repo_patterns(path: str, patterns: Sequence[str]) -> bool:
    return any(_matches_repo_pattern(path, pattern) for pattern in patterns)


def _acceptance_budget_policy(package: Mapping[str, Any]) -> dict[str, Any]:
    migration = package.get("migration")
    policy = (
        migration.get("acceptance_budget")
        if isinstance(migration, Mapping)
        else None
    )
    expected = {
        "schema_version": "wiki_viva_upgrade_acceptance_budget_policy.v1",
        "scope": "plan_to_real_canary",
        "limit_seconds": 1200,
        "enforcement": "promotion_blocking",
    }
    if policy != expected:
        raise RunnerError(
            "invalid_acceptance_budget_policy",
            "the package does not enforce the 20-minute plan-to-canary budget",
            lane="lane_a",
            surface="acceptance_budget",
            contract="wiki_viva_upgrade_acceptance_budget_policy.v1",
            next_action="repair and recertify the package acceptance policy",
        )
    return expected


def _pending_acceptance_budget(
    package: Mapping[str, Any], *, plan_started_unix_ns: int
) -> dict[str, Any]:
    return _pending_acceptance_budget_at(
        package, plan_started_at=_acceptance_timestamp(plan_started_unix_ns)
    )


def _pending_acceptance_budget_at(
    package: Mapping[str, Any], *, plan_started_at: str
) -> dict[str, Any]:
    policy = _acceptance_budget_policy(package)
    _acceptance_timestamp_microseconds(plan_started_at)
    return {
        "schema_version": "wiki_viva_upgrade_acceptance_budget.v1",
        "scope": policy["scope"],
        "limit_seconds": policy["limit_seconds"],
        "enforcement": policy["enforcement"],
        "plan_started_at": plan_started_at,
        "canary_completed_at": None,
        "elapsed_milliseconds": None,
        "status": "pending",
    }


_ACCEPTANCE_TIMESTAMP_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$"
)
_UNIX_EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)


def _acceptance_timestamp(unix_ns: int) -> str:
    if isinstance(unix_ns, bool) or not isinstance(unix_ns, int) or unix_ns <= 0:
        raise RunnerError(
            "invalid_acceptance_budget_clock",
            "the acceptance budget timestamp is invalid",
            surface="acceptance_budget",
        )
    seconds, nanoseconds = divmod(unix_ns, 1_000_000_000)
    try:
        value = dt.datetime.fromtimestamp(seconds, tz=dt.timezone.utc).replace(
            microsecond=nanoseconds // 1_000
        )
    except (OverflowError, OSError, ValueError) as exc:
        raise RunnerError(
            "invalid_acceptance_budget_clock",
            "the acceptance budget timestamp is outside the supported UTC range",
            surface="acceptance_budget",
        ) from exc
    return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _acceptance_timestamp_microseconds(value: object) -> int:
    if not isinstance(value, str) or _ACCEPTANCE_TIMESTAMP_RE.fullmatch(value) is None:
        raise RunnerError(
            "invalid_acceptance_budget_clock",
            "the acceptance budget timestamp is not canonical UTC RFC3339",
            surface="acceptance_budget",
        )
    try:
        parsed = dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=dt.timezone.utc
        )
    except ValueError as exc:
        raise RunnerError(
            "invalid_acceptance_budget_clock",
            "the acceptance budget timestamp is not a real UTC instant",
            surface="acceptance_budget",
        ) from exc
    delta = parsed - _UNIX_EPOCH
    microseconds = (
        delta.days * 86_400_000_000
        + delta.seconds * 1_000_000
        + delta.microseconds
    )
    if microseconds <= 0:
        raise RunnerError(
            "invalid_acceptance_budget_clock",
            "the acceptance budget timestamp must be after the Unix epoch",
            surface="acceptance_budget",
        )
    return microseconds


def _validate_acceptance_budget_record(
    value: object, *, expected_plan: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RunnerError(
            "invalid_acceptance_budget",
            "the plan-to-canary budget record is missing",
            surface="acceptance_budget",
        )
    expected_keys = {
        "schema_version",
        "scope",
        "limit_seconds",
        "enforcement",
        "plan_started_at",
        "canary_completed_at",
        "elapsed_milliseconds",
        "status",
    }
    record = dict(value)
    if (
        set(record) != expected_keys
        or record.get("schema_version")
        != "wiki_viva_upgrade_acceptance_budget.v1"
        or record.get("scope") != "plan_to_real_canary"
        or record.get("limit_seconds") != 1200
        or record.get("enforcement") != "promotion_blocking"
    ):
        raise RunnerError(
            "invalid_acceptance_budget",
            "the plan-to-canary budget contract is incomplete or weakened",
            surface="acceptance_budget",
        )
    started = _acceptance_timestamp_microseconds(record.get("plan_started_at"))
    completed_value = record.get("canary_completed_at")
    elapsed = record.get("elapsed_milliseconds")
    status = record.get("status")
    if status == "pending":
        if completed_value is not None or elapsed is not None:
            raise RunnerError(
                "stale_acceptance_budget",
                "a pending acceptance budget contains a measurement",
                surface="acceptance_budget",
            )
    elif status in {"met", "exceeded"}:
        completed = _acceptance_timestamp_microseconds(completed_value)
        if (
            completed < started
            or isinstance(elapsed, bool)
            or not isinstance(elapsed, int)
            or elapsed < 0
        ):
            raise RunnerError(
                "invalid_acceptance_budget_clock",
                "the canary completion clock moved backwards or is invalid",
                surface="acceptance_budget",
            )
        expected_elapsed = (completed - started + 999) // 1_000
        expected_status = "met" if expected_elapsed <= 1_200_000 else "exceeded"
        if elapsed != expected_elapsed or status != expected_status:
            raise RunnerError(
                "stale_acceptance_budget",
                "the acceptance budget elapsed time or status was altered",
                surface="acceptance_budget",
            )
    else:
        raise RunnerError(
            "invalid_acceptance_budget",
            "the acceptance budget status is invalid",
            surface="acceptance_budget",
        )
    if expected_plan is not None:
        plan_record = _validate_acceptance_budget_record(
            expected_plan.get("acceptance_budget")
        )
        for key in (
            "schema_version",
            "scope",
            "limit_seconds",
            "enforcement",
            "plan_started_at",
        ):
            if record[key] != plan_record[key]:
                raise RunnerError(
                    "stale_acceptance_budget",
                    "the run budget differs from its sealed plan",
                    surface="acceptance_budget",
                )
    return record


def _complete_acceptance_budget(
    value: Mapping[str, Any], *, canary_completed_unix_ns: int | None = None
) -> dict[str, Any]:
    record = _validate_acceptance_budget_record(value)
    if record["status"] != "pending":
        return record
    completed_unix_ns = (
        time.time_ns()
        if canary_completed_unix_ns is None
        else canary_completed_unix_ns
    )
    completed_at = _acceptance_timestamp(completed_unix_ns)
    completed = _acceptance_timestamp_microseconds(completed_at)
    started = _acceptance_timestamp_microseconds(record["plan_started_at"])
    if completed < started:
        raise RunnerError(
            "invalid_acceptance_budget_clock",
            "the canary completion clock moved backwards",
            surface="acceptance_budget",
            contract="wiki_viva_upgrade_acceptance_budget.v1",
            next_action="discard the invalid temporal evidence and rerun the plan",
        )
    elapsed = (completed - started + 999) // 1_000
    record.update(
        {
            "canary_completed_at": completed_at,
            "elapsed_milliseconds": elapsed,
            "status": "met" if elapsed <= 1_200_000 else "exceeded",
        }
    )
    return _validate_acceptance_budget_record(record)


def _validate_pending_plan_acceptance_budget(
    plan: Mapping[str, Any], package: Mapping[str, Any]
) -> dict[str, Any]:
    """Verify the sealed plan budget before any consumer mutation or gate work."""

    plan_budget = _validate_acceptance_budget_record(plan.get("acceptance_budget"))
    policy = _acceptance_budget_policy(package)
    if any(
        plan_budget[key] != value
        for key, value in policy.items()
        if key != "schema_version"
    ) or plan_budget["status"] != "pending":
        raise RunnerError(
            "stale_acceptance_budget",
            "the sealed plan budget differs from the certified package",
            surface="acceptance_budget",
        )
    return plan_budget


_CERTIFICATION_RECEIPT_SCHEMA = (
    ROOT
    / "docs/references/schemas/wiki-upgrade-certification-receipt-v1.schema.json"
)
_SHA_RE = re.compile(r"^[0-9a-f]{40,64}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GATE_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{1,127}$")
_VISUAL_ENTRY_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_VISUAL_CAPTURE_STATE_RE = re.compile(r"^capture-[0-9a-f]{64}$")
_CONTROL_TOKEN_RE = re.compile(r"(?:\$\(|`|\x00|\r|\n)")
_SHELL_TOKENS = {"|", "||", "&", "&&", ";", ">", ">>", "<", "<<"}
_HOST_PATH_RE = re.compile(
    r"(?:"
    r"(?<![\w.-])/(?:Users|home|tmp|opt|var|etc|usr|root|srv|mnt|Volumes|Library|System|Applications)(?:/|$)"
    r"|file://|(?<![\w.-])~[/\\]|[A-Za-z]:\\|\\\\[^\\\s]+\\"
    r")"
)
_PRIVATE_EVIDENCE_RE = re.compile(
    r"(?:^|[/\\])(?:private|data[/\\]raw|data[/\\]derived)(?:[/\\]|$)",
    re.IGNORECASE,
)
_PRIVATE_ROUTE_RE = re.compile(
    r"(?:"
    r"(?<![A-Za-z0-9._~-])/(?:private|consumer|real)(?![A-Za-z0-9._~-])"
    r"|(?:https?|wss?)://[^/\s]+/(?:private|consumer|real)(?![A-Za-z0-9._~-])"
    r")",
    re.IGNORECASE,
)
_PERCENT_ESCAPE_RE = re.compile(r"%[0-9A-Fa-f]{2}")
_MAX_PERCENT_DECODE_ROUNDS = 3
_MAX_CERTIFICATION_FILE_BYTES = 64 * 1024 * 1024
_MAX_GATE_OUTPUT_BYTES = 16 * 1024 * 1024
_MAX_GATE_ARTIFACT_FILE_BYTES = 64 * 1024 * 1024
_MAX_GATE_ARTIFACT_TOTAL_BYTES = 128 * 1024 * 1024
_MAX_GATE_ARTIFACT_FILES = 512
_DOWNSTREAM_OPERATOR_ENV_KEYS = (
    "WIKI_COCKPIT_SNAPSHOT_URL",
    "WIKI_COCKPIT_REAL_BASE_URL",
    "WIKI_COCKPIT_EXPECT_REPO_ID",
    "WIKI_COCKPIT_EXPECT_SNAPSHOT_REVISION",
    "WIKI_COCKPIT_EXPECT_SNAPSHOT_HASH",
    "WIKI_COCKPIT_EXPECT_CONSUMER_HEAD",
    "WIKI_COCKPIT_EXPECT_PUBLIC_RELEASE_SHA",
    "WIKI_COCKPIT_EXPECT_ADAPTER_HASH",
    "WIKI_COCKPIT_EXPECT_SNAPSHOT_VERSION",
    "WIKI_COCKPIT_EXPECT_RUNTIME_VERSION",
    "WIKI_COCKPIT_EXPECT_SERVER_VERSION",
    "WIKI_COCKPIT_EXPECT_TEMPORAL_GRAPH_VERSION",
    "WIKI_COCKPIT_EXPECT_TEMPORAL_EVENT_VERSION",
    "WIKI_COCKPIT_EXPECT_EXPERIENCE_PACK_COMPOSITION_VERSION",
    "WIKI_COCKPIT_EXPECT_COMPOSITION_SHA256",
    "WIKI_COCKPIT_EXPECT_ACTIVE_PACKS",
    "WIKI_COCKPIT_EXPECT_CAPABILITIES",
    "WIKI_COCKPIT_MIN_PAGES",
)
_WRITE_LOCK = threading.Lock()


class RunnerError(ValueError):
    """A public-safe, actionable runner failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        lane: str = "lane_b",
        surface: str = "upgrade_runner",
        contract: str = PLAN_SCHEMA_VERSION,
        next_action: str = "repair the rejected input and generate a new plan",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.lane = lane
        self.surface = surface
        self.contract = contract
        self.next_action = next_action


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _emit(payload: Mapping[str, Any], *, stream: Any = sys.stdout) -> None:
    """Emit only path-free, payload-free progress summaries."""

    with _WRITE_LOCK:
        print(json.dumps(dict(payload), sort_keys=True), file=stream, flush=True)


def _failure_payload(error: RunnerError) -> dict[str, Any]:
    return {
        "schema_version": "wiki_viva_upgrade_failure.v1",
        "status": "failed",
        "lane": error.lane,
        "surface": error.surface,
        "contract": error.contract,
        "error_code": error.code,
        "message": error.message,
        "next_action": error.next_action,
    }


def _git(
    root: Path,
    args: Sequence[str],
    *,
    input_bytes: bytes | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and result.returncode != 0:
        raise RunnerError(
            "git_contract_failed",
            "the consumer Git contract could not be verified",
            surface="consumer_git",
            next_action="restore a clean, complete Git checkout and retry",
        )
    return result


def _head(root: Path) -> str:
    value = _git(root, ["rev-parse", "HEAD"]).stdout.decode("ascii", "strict").strip()
    if _SHA_RE.fullmatch(value) is None:
        raise RunnerError("invalid_git_subject", "the consumer HEAD is not a full Git subject")
    return value


def _require_clean(root: Path) -> None:
    status = _git(root, ["status", "--porcelain=v1", "--untracked-files=all"]).stdout
    if status:
        raise RunnerError(
            "consumer_not_clean",
            "the consumer subject is not a clean B0/C3",
            surface="consumer_B0_C3",
            next_action="commit or remove tracked and untracked changes, then plan again",
        )


def _require_upgrade_branch(root: Path, package: Mapping[str, Any]) -> str:
    preflight = package.get("preflight")
    prefix = preflight.get("branch_prefix") if isinstance(preflight, dict) else None
    if (
        not isinstance(prefix, str)
        or not prefix
        or prefix.startswith(("/", ".", "-"))
        or ".." in prefix
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,63}", prefix) is None
    ):
        raise RunnerError(
            "invalid_upgrade_branch_policy",
            "the package preflight branch prefix is invalid",
            lane="lane_a",
            surface="preflight_branch",
        )
    result = _git(root, ["symbolic-ref", "--quiet", "--short", "HEAD"], check=False)
    branch = result.stdout.decode("utf-8", "strict").strip() if result.returncode == 0 else ""
    if not branch or not branch.startswith(prefix):
        raise RunnerError(
            "upgrade_branch_required",
            "downstream planning and adoption require a named package-approved review branch",
            surface="preflight_branch",
            contract="human_pr_gate",
            next_action=f"check out a {prefix} review branch at the exact B0 subject",
        )
    return branch


def _commit(root: Path, raw: str | None, *, fallback: str) -> str:
    value = raw or fallback
    result = _git(root, ["rev-parse", "--verify", f"{value}^{{commit}}"])
    sha = result.stdout.decode("ascii", "strict").strip()
    if _SHA_RE.fullmatch(sha) is None:
        raise RunnerError("invalid_boundary_subject", "a migration boundary is not a commit")
    return sha


def _require_ancestry(root: Path, commits: Sequence[str]) -> None:
    for before, after in zip(commits, commits[1:]):
        result = _git(root, ["rev-list", "--parents", "-n", "1", after])
        lineage = result.stdout.decode("ascii", "strict").strip().split()
        if lineage != [after, before]:
            raise RunnerError(
                "boundary_ancestry_mismatch",
                "B0, C1, C2 and C3 are not one direct single-parent ancestry chain",
                surface="commit_boundaries",
                next_action=(
                    "supply four consecutive single-parent migration subjects with no "
                    "intermediate or merge commit"
                ),
            )


def _changed_paths(root: Path, before: str, after: str) -> list[str]:
    if before == after:
        return []
    raw = _git(
        root,
        ["diff", "--no-renames", "--name-only", "-z", before, after, "--"],
    ).stdout
    values = [item.decode("utf-8", "strict") for item in raw.split(b"\0") if item]
    return sorted(set(values))


def _blob(root: Path, commit: str, path: str) -> bytes:
    entry = _regular_git_entry(root, commit, path)
    if entry is None:
        raise RunnerError(
            "boundary_deletion_unsupported",
            "a boundary contains a deletion that cannot be attested byte-for-byte",
            surface="commit_boundaries",
            next_action="split deletions into a reviewed consumer adaptation and regenerate the plan",
        )
    return entry["bytes"]


def _regular_git_entry(
    root: Path, commit: str, path: str
) -> dict[str, Any] | None:
    """Read one exact regular Git blob, including its executable mode."""

    listing = _git(root, ["ls-tree", "-z", commit, "--", path]).stdout
    records = [record for record in listing.split(b"\0") if record]
    if not records:
        return None
    if len(records) != 1:
        raise RunnerError(
            "invalid_boundary_tree_entry",
            "a boundary path resolves to multiple Git tree entries",
            surface="commit_boundaries",
        )
    try:
        metadata, raw_path = records[0].split(b"\t", 1)
        mode, object_type, object_id = metadata.decode("ascii").split(" ", 2)
        observed_path = raw_path.decode("utf-8", "strict")
    except (ValueError, UnicodeDecodeError) as exc:
        raise RunnerError(
            "invalid_boundary_tree_entry",
            "a boundary contains an invalid Git tree entry",
            surface="commit_boundaries",
        ) from exc
    if observed_path != path or object_type != "blob" or mode not in {"100644", "100755"}:
        raise RunnerError(
            "unsafe_boundary_tree_entry",
            "C1, C2 and C3 may contain only regular Git files with mode 100644 or 100755",
            surface="commit_boundaries",
            next_action="replace symlinks, submodules or special entries with regular reviewed files",
        )
    raw = _git(root, ["cat-file", "blob", object_id]).stdout
    return {"mode": mode, "bytes": raw, "sha256": _sha256_bytes(raw)}


def _package_c2_generator_sha256(
    package: Mapping[str, Any], path: str
) -> str | None:
    if package.get("schema_version") != _TWO_LANE_PACKAGE:
        return None
    operations = _boundary_operations(package)
    owners = [
        generator
        for generator in operations["c2_generators"]
        if isinstance(generator, Mapping)
        and isinstance(generator.get("owns_patterns"), list)
        and _matches_repo_patterns(path, generator["owns_patterns"])
    ]
    if len(owners) != 1 or not isinstance(owners[0].get("command"), str):
        raise RunnerError(
            "c2_generator_ownership_mismatch",
            "a C2 path does not resolve to exactly one package-owned generator",
            surface="C2",
            contract=BOUNDARY_OPERATIONS_SCHEMA_VERSION,
        )
    return _sha256_bytes(owners[0]["command"].encode("utf-8"))


def _portable_commit_entries(
    root: Path,
    commit: str,
    package: Mapping[str, Any],
) -> dict[str, dict[str, str]]:
    portable = package["portable_import"]
    allow = portable["allow"]
    block = portable["block"]
    listing = _git(root, ["ls-tree", "-r", "-z", "--full-tree", commit]).stdout
    entries: dict[str, dict[str, str]] = {}
    for record in listing.split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        mode, object_type, object_id = metadata.decode("ascii").split(" ", 2)
        path = raw_path.decode("utf-8", "strict")
        if _matches_repo_patterns(path, block):
            continue
        if not _matches_repo_patterns(path, allow):
            continue
        if object_type != "blob" or mode not in {"100644", "100755"}:
            raise RunnerError(
                "unsafe_portable_projection_entry",
                "a portable projection contains a symlink, submodule or special entry",
                surface="C1",
            )
        raw = _git(root, ["cat-file", "blob", object_id]).stdout
        entries[path] = {"mode": mode, "sha256": _sha256_bytes(raw)}
    return entries


def _build_boundaries(
    *,
    consumer: Path,
    kit: Path,
    source_sha: str,
    package_sha256: str,
    commits: Mapping[str, str],
    registry: Mapping[str, Any],
    package: Mapping[str, Any],
    consumer_c3_authority: Mapping[str, Any],
) -> dict[str, list[dict[str, str]]]:
    boundaries: dict[str, list[dict[str, str]]] = {"C1": [], "C2": [], "C3": []}
    for path in _changed_paths(consumer, commits["B0"], commits["C1"]):
        before = _regular_git_entry(consumer, commits["B0"], path)
        after = _regular_git_entry(consumer, commits["C1"], path)
        if after is None:
            if before is None:
                raise RunnerError(
                    "invalid_c1_deletion",
                    "a C1 deletion has no regular before file",
                    surface="C1",
                )
            boundaries["C1"].append(
                {
                    "operation": "delete",
                    "path": path,
                    "before_mode": before["mode"],
                    "before_sha256": before["sha256"],
                }
            )
        else:
            source = _regular_git_entry(kit, source_sha, path)
            if source is None:
                raise RunnerError(
                    "missing_c1_source_file",
                    "a C1 upsert has no regular file in the certified source",
                    surface="C1",
                )
            boundaries["C1"].append(
                {
                    "operation": "upsert",
                    "path": path,
                    "mode": after["mode"],
                    "sha256": after["sha256"],
                    "source_mode": source["mode"],
                    "source_sha256": source["sha256"],
                }
            )
    for path in _changed_paths(consumer, commits["C1"], commits["C2"]):
        before = _regular_git_entry(consumer, commits["C1"], path)
        after = _regular_git_entry(consumer, commits["C2"], path)
        if after is None:
            if before is None:
                raise RunnerError(
                    "invalid_c2_deletion",
                    "a C2 deletion has no regular before file",
                    surface="C2",
                )
            before_digest = before["sha256"]
            generator_digest = _package_c2_generator_sha256(package, path)
            if generator_digest is None:
                generator_digest = canonical_sha256(
                    {
                        "contract": "wiki_viva_generated_artifact_derivation.v1",
                        "operation": "delete",
                        "source_sha": source_sha,
                        "package_sha256": package_sha256,
                        "before_sha256": before_digest,
                    }
                )
            boundaries["C2"].append(
                {
                    "operation": "delete",
                    "path": path,
                    "before_mode": before["mode"],
                    "before_sha256": before_digest,
                    "generator_sha256": generator_digest,
                }
            )
        else:
            artifact_digest = after["sha256"]
            generator_digest = _package_c2_generator_sha256(package, path)
            if generator_digest is None:
                generator_digest = canonical_sha256(
                    {
                        "contract": "wiki_viva_generated_artifact_derivation.v1",
                        "operation": "upsert",
                        "source_sha": source_sha,
                        "package_sha256": package_sha256,
                        "artifact_sha256": artifact_digest,
                    }
                )
            boundaries["C2"].append(
                {
                    "operation": "upsert",
                    "path": path,
                    "mode": after["mode"],
                    "sha256": artifact_digest,
                    "generator_sha256": generator_digest,
                }
            )
    for path in _changed_paths(consumer, commits["C2"], commits["C3"]):
        before = _regular_git_entry(consumer, commits["C2"], path)
        after = _regular_git_entry(consumer, commits["C3"], path)
        if after is None:
            if before is None:
                raise RunnerError(
                    "invalid_c3_deletion",
                    "a C3 deletion has no regular before file",
                    surface="C3",
                )
            boundaries["C3"].append(
                {
                    "operation": "delete",
                    "path": path,
                    "before_mode": before["mode"],
                    "before_sha256": before["sha256"],
                }
            )
        else:
            boundaries["C3"].append(
                {
                    "operation": "upsert",
                    "path": path,
                    "mode": after["mode"],
                    "sha256": after["sha256"],
                }
            )
    try:
        validate_boundary_ownership(
            boundaries,
            registry,
            package=package,
            consumer_c3_authority=consumer_c3_authority,
        )
        verify_config_bound_c3_git_content(
            consumer,
            commits=commits,
            boundaries=boundaries,
            authority=consumer_c3_authority,
            package=package,
        )
        validate_c1_projection(
            boundaries["C1"],
            package=package,
            source_entries={
                path: {"mode": str(item["mode"]), "sha256": str(item["sha256"])}
                for path, item in _portable_entries(package, kit, source_sha).items()
            },
            before_entries=_portable_commit_entries(
                consumer, commits["B0"], package
            ),
            after_entries=_portable_commit_entries(
                consumer, commits["C1"], package
            ),
        )
    except UpgradeLaneError as exc:
        raise RunnerError(
            "boundary_ownership_mismatch",
            "C1, C2 and C3 mix portable, generated, consumer or domain ownership",
            surface="commit_boundaries",
            next_action="split the commits by ownership and regenerate the plan",
        ) from exc
    return boundaries


def _portable_entries(
    package: Mapping[str, Any], kit: Path, source_sha: str
) -> dict[str, dict[str, Any]]:
    portable = package.get("portable_import")
    if not isinstance(portable, dict):
        raise RunnerError("invalid_portable_policy", "the package portable policy is missing")
    allow = portable.get("allow")
    block = portable.get("block")
    if (
        not isinstance(allow, list)
        or not allow
        or not isinstance(block, list)
        or not block
        or any(not isinstance(value, str) for value in [*allow, *block])
    ):
        raise RunnerError("invalid_portable_policy", "the package portable allow/block policy is incomplete")
    listing = _git(kit, ["ls-tree", "-r", "-z", "--full-tree", source_sha]).stdout
    entries: dict[str, dict[str, Any]] = {}
    for record in listing.split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        mode, object_type, object_id = metadata.decode("ascii").split(" ", 2)
        path = raw_path.decode("utf-8", "strict")
        if _matches_repo_patterns(path, block):
            continue
        if not _matches_repo_patterns(path, allow):
            continue
        if object_type != "blob" or mode not in {"100644", "100755"}:
            raise RunnerError(
                "unsafe_portable_entry",
                "the portable projection contains a symlink, submodule or special entry",
                lane="lane_a",
                surface="portable_tree",
            )
        raw = _git(kit, ["cat-file", "blob", object_id]).stdout
        entries[path] = {
            "mode": mode,
            "bytes": raw,
            "sha256": _sha256_bytes(raw),
        }
    if not entries:
        raise RunnerError("empty_portable_projection", "the certified portable projection is empty")
    return entries


def _consumer_portable_paths(
    consumer: Path, package: Mapping[str, Any]
) -> set[str]:
    portable = package["portable_import"]
    allow = portable["allow"]
    block = portable["block"]
    tracked = _git(consumer, ["ls-files", "-z"]).stdout
    return {
        path
        for path in (
            item.decode("utf-8", "strict") for item in tracked.split(b"\0") if item
        )
        if _matches_repo_patterns(path, allow)
        and not _matches_repo_patterns(path, block)
    }


def _verify_complete_c1_projection(
    *,
    consumer: Path,
    c1: str,
    package: Mapping[str, Any],
    source_entries: Mapping[str, Mapping[str, Any]],
) -> str:
    portable = package["portable_import"]
    allow = portable["allow"]
    block = portable["block"]
    listing = _git(consumer, ["ls-tree", "-r", "-z", "--full-tree", c1]).stdout
    observed: dict[str, dict[str, str]] = {}
    for record in listing.split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        mode, object_type, _object_id = metadata.decode("ascii").split(" ", 2)
        path = raw_path.decode("utf-8", "strict")
        if _matches_repo_patterns(path, block):
            continue
        if not _matches_repo_patterns(path, allow):
            continue
        if object_type != "blob" or mode not in {"100644", "100755"}:
            raise RunnerError(
                "unsafe_c1_projection_entry",
                "C1 contains a non-regular portable entry",
                surface="C1",
            )
        observed[path] = {
            "mode": mode,
            "sha256": _sha256_bytes(_blob(consumer, c1, path)),
        }
    expected = {
        path: {"mode": str(entry["mode"]), "sha256": str(entry["sha256"])}
        for path, entry in sorted(source_entries.items())
    }
    if observed != expected:
        raise RunnerError(
            "c1_portable_projection_mismatch",
            "C1 is not the complete byte-and-mode-equal certified portable tree",
            surface="C1",
            next_action="recreate C1 from the exact capsule allow/block projection",
        )
    return canonical_sha256(observed)


def _prospective_c1_paths(
    consumer: Path,
    package: Mapping[str, Any],
    entries: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    changed: set[str] = set(_consumer_portable_paths(consumer, package)) - set(entries)
    for path, entry in entries.items():
        destination = consumer / path
        expected_executable = entry["mode"] == "100755"
        try:
            metadata = destination.lstat()
        except OSError:
            metadata = None
        regular = metadata is not None and stat.S_ISREG(metadata.st_mode)
        actual_executable = bool(metadata.st_mode & 0o111) if regular else False
        if (
            not regular
            or _sha256_bytes(destination.read_bytes()) != entry["sha256"]
            or actual_executable != expected_executable
        ):
            changed.add(path)
    return sorted(changed)


def _safe_consumer_file(consumer: Path, path: str) -> Path:
    if (
        not path
        or path.startswith(("/", "~"))
        or "\\" in path
        or ".." in Path(path).parts
    ):
        raise RunnerError("unsafe_mutation_path", "a planned mutation path escapes the consumer")
    destination = consumer / path
    cursor = destination
    while cursor != consumer:
        if cursor.exists() and cursor.is_symlink():
            raise RunnerError("unsafe_mutation_symlink", "a planned mutation path traverses a symlink")
        cursor = cursor.parent
    return destination


def _apply_c1(
    consumer: Path,
    package: Mapping[str, Any],
    entries: Mapping[str, Mapping[str, Any]],
) -> str:
    source_paths = set(entries)
    for path in sorted(_consumer_portable_paths(consumer, package) - source_paths):
        destination = _safe_consumer_file(consumer, path)
        if destination.exists():
            destination.unlink()
    for path, entry in sorted(entries.items()):
        destination = _safe_consumer_file(consumer, path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.parent / f".{destination.name}.wiki-upgrade"
        _atomic_write(temporary, entry["bytes"])
        os.replace(temporary, destination)
        destination.chmod(0o755 if entry["mode"] == "100755" else 0o644)
    _git(consumer, ["add", "-A"])
    return _commit_index(consumer, "wiki: faithful public import (C1)")


def _commit_index(consumer: Path, subject: str) -> str:
    if _git(consumer, ["diff", "--cached", "--quiet"], check=False).returncode == 0:
        return _head(consumer)
    result = _git(consumer, ["commit", "-q", "-m", subject], check=False)
    if result.returncode != 0:
        raise RunnerError(
            "boundary_commit_failed",
            "the runner could not create a deterministic migration boundary commit",
            surface="commit_boundaries",
            next_action="configure Git author identity and resume the unchanged plan",
        )
    return _head(consumer)


def _named_commands(raw_specs: Sequence[str], *, kit: Path, label: str) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    seen: set[str] = set()
    for spec in raw_specs:
        command_id, separator, command = spec.partition("::")
        if (
            not separator
            or _GATE_ID_RE.fullmatch(command_id) is None
            or command_id in seen
            or not command.strip()
        ):
            raise RunnerError(
                "invalid_mutation_command",
                f"a {label} command must use unique canonical id::command syntax",
                surface=label,
            )
        seen.add(command_id)
        _parse_command(command, kit_root=kit)
        commands.append({"id": command_id, "command": command})
    return commands


def _boundary_operations(package: Mapping[str, Any]) -> Mapping[str, Any]:
    migration = package.get("migration")
    operations = (
        migration.get("boundary_operations")
        if isinstance(migration, Mapping)
        else None
    )
    if package.get("schema_version") != _TWO_LANE_PACKAGE:
        return operations if isinstance(operations, Mapping) else {}
    if (
        not isinstance(operations, Mapping)
        or operations.get("schema_version") != BOUNDARY_OPERATIONS_SCHEMA_VERSION
        or not isinstance(operations.get("c2_generators"), list)
        or not isinstance(operations.get("c3_adapter"), Mapping)
        or not isinstance(operations.get("registry_sha256"), str)
    ):
        raise RunnerError(
            "invalid_boundary_operations",
            "the v3 package omits its exact C2/C3 execution authority",
            lane="lane_a",
            surface="boundary_operations",
            next_action="repair and recertify the versioned upgrade package",
        )
    return operations


def _c2_commands_for_plan(
    package: Mapping[str, Any], raw_specs: Sequence[str], *, kit: Path
) -> list[dict[str, Any]]:
    explicit = _named_commands(raw_specs, kit=kit, label="C2")
    if package.get("schema_version") != _TWO_LANE_PACKAGE:
        return explicit
    operations = _boundary_operations(package)
    packaged: list[dict[str, Any]] = []
    for raw in operations["c2_generators"]:
        if not isinstance(raw, Mapping):
            raise RunnerError(
                "invalid_boundary_operations",
                "a package C2 generator is not executable metadata",
                lane="lane_a",
                surface="C2",
            )
        generator_id = raw.get("id")
        command = raw.get("command")
        if not isinstance(generator_id, str) or not isinstance(command, str):
            raise RunnerError(
                "invalid_boundary_operations",
                "a package C2 generator identity is incomplete",
                lane="lane_a",
                surface="C2",
            )
        _parse_command(command, kit_root=kit)
        packaged.append({"id": generator_id, "command": command})
    if explicit and canonical_sha256(explicit) != canonical_sha256(packaged):
        raise RunnerError(
            "c2_generator_contract_mismatch",
            "a supplied C2 command differs from the package-certified generator registry",
            surface="C2",
            contract=BOUNDARY_OPERATIONS_SCHEMA_VERSION,
            next_action="remove the override and use the package-owned C2 generator",
        )
    return packaged


def _c3_commands_for_plan(
    package: Mapping[str, Any], raw_specs: Sequence[str], *, kit: Path
) -> list[dict[str, Any]]:
    commands = _named_commands(raw_specs, kit=kit, label="C3")
    if package.get("schema_version") != _TWO_LANE_PACKAGE:
        return commands
    operations = _boundary_operations(package)
    adapter = operations["c3_adapter"]
    if adapter.get("mode") != "consumer_plan_commands":
        raise RunnerError(
            "invalid_c3_adapter_contract",
            "the package C3 adapter mode is unsupported",
            lane="lane_a",
            surface="C3",
        )
    if not commands:
        raise RunnerError(
            "missing_c3_adapter_command",
            "the consumer-owned C3 boundary requires at least one plan-sealed adapter command",
            surface="C3",
            contract=str(adapter.get("contract") or "consumer_adapter"),
            next_action="supply the exact consumer adapter/config command when creating the plan",
        )
    return commands


def _run_mutation_commands(
    commands: Sequence[Mapping[str, str]],
    *,
    consumer: Path,
    kit: Path,
    log_path: Path,
    label: str,
    ownership_by_id: Mapping[str, Sequence[str]] | None = None,
) -> list[dict[str, str]]:
    combined = bytearray()
    receipts: list[dict[str, str]] = []
    expected_head = _head(consumer)
    previous_state = _worktree_state(consumer) if ownership_by_id is not None else {}
    for item in commands:
        if ownership_by_id is not None and item["id"] not in ownership_by_id:
            raise RunnerError(
                "mutation_command_ownership_missing",
                f"a runner-owned {label} command has no package ownership declaration",
                surface=label,
            )
        argv = _parse_command(item["command"], kit_root=kit)
        environment = {
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "CI"}
        }
        environment["WIKI_VIVA_KIT_ROOT"] = str(kit.resolve())
        try:
            result = subprocess.run(
                argv,
                cwd=consumer,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=1200,
            )
        except subprocess.TimeoutExpired as exc:
            output = exc.output if isinstance(exc.output, bytes) else b""
            combined.extend(f"command:{item['id']}\n".encode("utf-8"))
            combined.extend(output)
            combined.extend(b"\n")
            _atomic_write(log_path, bytes(combined))
            raise RunnerError(
                "mutation_command_timeout",
                f"a runner-owned {label} command exceeded its bounded runtime",
                surface=label,
                next_action="repair the bounded stage command and resume the unchanged plan",
            ) from exc
        combined.extend(f"command:{item['id']}\n".encode("utf-8"))
        combined.extend(result.stdout)
        combined.extend(b"\n")
        _atomic_write(log_path, bytes(combined))
        if _head(consumer) != expected_head:
            raise RunnerError(
                "mutation_command_changed_history",
                f"a runner-owned {label} command changed Git HEAD/history",
                surface=label,
                next_action="remove Git history mutation from the stage command and generate a new plan",
            )
        if result.returncode != 0:
            raise RunnerError(
                "mutation_command_failed",
                f"a runner-owned {label} command failed",
                surface=label,
                next_action="repair the command and generate a new plan",
            )
        if ownership_by_id is not None:
            current_state = _worktree_state(consumer)
            changed_by_command = sorted(
                path
                for path in set(previous_state) | set(current_state)
                if previous_state.get(path) != current_state.get(path)
            )
            _require_stage_paths(
                changed_by_command,
                ownership_by_id[item["id"]],
                label=f"{label} generator {item['id']}",
            )
            previous_state = current_state
        receipts.append(
            {
                "id": item["id"],
                "command_sha256": _sha256_bytes(item["command"].encode("utf-8")),
                "output_sha256": _sha256_bytes(result.stdout),
            }
        )
    _atomic_write(log_path, bytes(combined))
    return receipts


def _worktree_state(root: Path) -> dict[str, str]:
    tracked = _git(root, ["ls-files", "-z", "--cached"]).stdout
    untracked = _git(
        root, ["ls-files", "-z", "--others", "--exclude-standard"]
    ).stdout
    paths = sorted(
        {
            item.decode("utf-8", "strict")
            for item in [*tracked.split(b"\0"), *untracked.split(b"\0")]
            if item
        }
    )
    state: dict[str, str] = {}
    for path in paths:
        target = root / path
        if target.is_symlink():
            state[path] = "symlink:" + _sha256_bytes(
                os.readlink(target).encode("utf-8")
            )
        elif target.is_file():
            executable = bool(target.stat().st_mode & 0o111)
            state[path] = (
                ("100755:" if executable else "100644:")
                + _sha256_bytes(target.read_bytes())
            )
        else:
            state[path] = "deleted"
    return state


@contextlib.contextmanager
def _disposable_stage_clone(consumer: Path, base_sha: str) -> Iterable[Path]:
    with tempfile.TemporaryDirectory(prefix="wiki-upgrade-stage-") as temporary:
        clone = Path(temporary) / "consumer"
        result = subprocess.run(
            ["git", "clone", "--quiet", "--no-local", str(consumer), str(clone)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode != 0:
            raise RunnerError(
                "mutation_stage_clone_failed",
                "a disposable boundary staging clone could not be created",
                surface="commit_boundaries",
            )
        _git(clone, ["checkout", "--quiet", "--detach", base_sha])
        for key in ("user.name", "user.email"):
            value = _git(consumer, ["config", "--get", key], check=False)
            if value.returncode == 0 and value.stdout.strip():
                _git(
                    clone,
                    ["config", key, value.stdout.decode("utf-8", "strict").strip()],
                )
        yield clone


def _fetch_prepared_commit(consumer: Path, clone: Path, commit_sha: str) -> None:
    result = _git(
        consumer,
        ["fetch", "--quiet", "--no-tags", str(clone), commit_sha],
        check=False,
    )
    if result.returncode != 0:
        raise RunnerError(
            "mutation_prepared_commit_fetch_failed",
            "a disposable boundary commit could not be imported into the consumer",
            surface="commit_boundaries",
        )


def _advance_prepared_phase(
    *,
    consumer: Path,
    state: dict[str, Any],
    state_path: Path,
    target_phase: str,
    base_sha: str,
) -> None:
    prepared_phase = f"{target_phase}_prepared"
    if state.get("phase") != prepared_phase:
        return
    commit_sha = str(state["commits"].get(target_phase) or "")
    _commit(consumer, commit_sha, fallback=commit_sha)
    _require_clean(consumer)
    current = _head(consumer)
    if current == base_sha:
        merged = _git(
            consumer,
            ["merge", "--ff-only", "--quiet", commit_sha],
            check=False,
        )
        if merged.returncode != 0:
            raise RunnerError(
                "mutation_prepared_commit_not_fast_forward",
                "a prepared boundary commit is not an exact fast-forward",
                surface=target_phase,
            )
    elif current != commit_sha:
        raise RunnerError(
            "stale_mutation_head",
            "consumer HEAD differs from both the recorded phase and prepared commit",
            surface=target_phase,
        )
    _require_clean(consumer)
    state["phase"] = target_phase
    _atomic_write(state_path, _json_bytes(state))


def _require_stage_paths(
    paths: Sequence[str],
    patterns: Sequence[str],
    *,
    label: str,
    forbidden_patterns: Sequence[str] = (),
    forbidden_exceptions: Sequence[str] = (),
) -> None:
    unknown = [
        path
        for path in paths
        if not _matches_repo_patterns(path, patterns)
        or (
            _matches_repo_patterns(path, forbidden_patterns)
            and not _matches_repo_patterns(path, forbidden_exceptions)
        )
    ]
    if unknown:
        raise RunnerError(
            "mutation_boundary_mixing",
            f"the {label} command changed a path outside its owned boundary",
            surface=label,
            next_action="split portable, generated and consumer-owned mutations",
        )


def _validate_declared_boundaries(
    package: Mapping[str, Any],
    commits: Mapping[str, str],
    boundaries: Mapping[str, Sequence[Mapping[str, str]]],
) -> None:
    migration = package.get("migration")
    declared = migration.get("commit_boundaries") if isinstance(migration, dict) else None
    if not isinstance(declared, list) or not declared:
        return
    expected = {
        "faithful_public_import": "C1",
        "regenerated_artifacts": "C2",
        "downstream_adaptations": "C3",
    }
    commit_key = {
        "faithful_public_import": "C1",
        "regenerated_artifacts": "C2",
        "downstream_adaptations": "C3",
    }
    previous = commits["B0"]
    for boundary_name in declared:
        key = commit_key.get(str(boundary_name))
        if key is None:
            raise RunnerError(
                "unknown_commit_boundary",
                "the package declares an unsupported migration boundary",
                surface="commit_boundaries",
            )
        if commits[key] == previous or not boundaries[key]:
            raise RunnerError(
                "empty_or_collapsed_boundary",
                "a package-declared C1, C2 or C3 boundary is empty or shares a commit",
                surface=key,
                next_action="create the distinct package-declared commit, then plan the exact chain",
            )
        previous = commits[key]
    if set(expected).intersection(str(value) for value in declared) == set(expected):
        if len({commits[key] for key in ("B0", "C1", "C2", "C3")}) != 4:
            raise RunnerError(
                "collapsed_three_commit_chain",
                "the v8 migration contract requires three distinct ordered commits after B0",
                surface="commit_boundaries",
                next_action="split faithful import, regeneration and consumer adaptations",
            )


def _boundary_execution(
    command_specs: Sequence[str],
    boundaries: Mapping[str, Sequence[Mapping[str, str]]],
    *,
    consumer: Path,
    kit: Path,
    commits: Mapping[str, str],
    evidence_path: Path,
) -> dict[str, Any]:
    c2 = list(boundaries["C2"])
    if not c2:
        return {"schema_version": "wiki_viva_boundary_execution.v1", "C2": []}
    if not command_specs:
        raise RunnerError(
            "missing_c2_execution_evidence",
            "non-empty C2 requires a runner-executed generator replay",
            surface="C2",
            next_action="supply one or more --c2-generator-command id::command values",
        )
    commands: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for spec in command_specs:
        generator_id, separator, command = spec.partition("::")
        if (
            not separator
            or _GATE_ID_RE.fullmatch(generator_id) is None
            or generator_id in seen_ids
            or not command.strip()
        ):
            raise RunnerError(
                "invalid_c2_generator_command",
                "a C2 generator command must use unique canonical id::command syntax",
                surface="C2",
            )
        seen_ids.add(generator_id)
        commands.append(
            {
                "id": generator_id,
                "command": command,
                "argv": _parse_command(command, kit_root=kit),
            }
        )
    combined_log = bytearray()
    expected = {item["path"]: item for item in c2}
    with tempfile.TemporaryDirectory(prefix="wiki-upgrade-c2-replay-") as temporary:
        clone = Path(temporary) / "consumer"
        cloned = subprocess.run(
            ["git", "clone", "--quiet", "--no-local", str(consumer), str(clone)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if cloned.returncode != 0:
            raise RunnerError(
                "c2_replay_clone_failed",
                "the disposable C2 replay clone could not be created",
                surface="C2",
            )
        _git(clone, ["checkout", "--quiet", "--detach", commits["C1"]])
        replay_head = _head(clone)
        command_receipts: list[dict[str, str]] = []
        for command in commands:
            environment = {
                key: value
                for key, value in os.environ.items()
                if key in {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "CI"}
            }
            environment["WIKI_VIVA_KIT_ROOT"] = str(kit.resolve())
            try:
                result = subprocess.run(
                    command["argv"],
                    cwd=clone,
                    env=environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    check=False,
                    timeout=1200,
                )
            except subprocess.TimeoutExpired as exc:
                output = exc.output if isinstance(exc.output, bytes) else b""
                combined_log.extend(
                    f"generator:{command['id']}\n".encode("utf-8")
                )
                combined_log.extend(output)
                combined_log.extend(b"\n")
                _atomic_write(evidence_path, bytes(combined_log))
                raise RunnerError(
                    "c2_generator_timeout",
                    "a package-registered C2 generator exceeded its bounded runtime",
                    surface="C2",
                    next_action="repair the deterministic generator and resume the unchanged plan",
                ) from exc
            combined_log.extend(f"generator:{command['id']}\n".encode("utf-8"))
            combined_log.extend(result.stdout)
            combined_log.extend(b"\n")
            _atomic_write(evidence_path, bytes(combined_log))
            if _head(clone) != replay_head:
                raise RunnerError(
                    "c2_generator_changed_history",
                    "a C2 generator changed Git HEAD/history in the disposable replay",
                    surface="C2",
                    next_action="make C2 generation a worktree-only deterministic command",
                )
            if result.returncode != 0:
                raise RunnerError(
                    "c2_generator_failed",
                    "a registered C2 generator failed in the disposable replay clone",
                    surface="C2",
                    next_action="repair the generator before planning adoption",
                )
            command_receipts.append(
                {
                    "id": command["id"],
                    "command_sha256": _sha256_bytes(command["command"].encode("utf-8")),
                    "output_sha256": _sha256_bytes(result.stdout),
                }
            )
        modified = _git(clone, ["diff", "--name-only", "-z", "--"]).stdout
        changed = {
            item.decode("utf-8", "strict") for item in modified.split(b"\0") if item
        }
        untracked = _git(clone, ["ls-files", "--others", "--exclude-standard", "-z"]).stdout
        changed.update(
            item.decode("utf-8", "strict") for item in untracked.split(b"\0") if item
        )
        if changed != set(expected):
            raise RunnerError(
                "c2_replay_surface_mismatch",
                "generator replay changed a surface outside C2 or omitted a C2 artifact",
                surface="C2",
                next_action="repair generator scope or split the migration boundaries",
            )
        for path, boundary in expected.items():
            replayed = clone / path
            if boundary.get("operation") == "delete":
                matches = not replayed.exists() and not replayed.is_symlink()
            else:
                try:
                    replayed_stat = replayed.lstat()
                except OSError:
                    replayed_stat = None
                replayed_mode = (
                    "100755"
                    if replayed_stat is not None
                    and stat.S_ISREG(replayed_stat.st_mode)
                    and replayed_stat.st_mode & 0o111
                    else "100644"
                )
                matches = (
                    replayed_stat is not None
                    and stat.S_ISREG(replayed_stat.st_mode)
                    and replayed_mode == boundary.get("mode")
                    and _sha256_bytes(replayed.read_bytes()) == boundary.get("sha256")
                )
            if not matches:
                raise RunnerError(
                    "c2_replay_byte_mismatch",
                    "generator replay did not reproduce an exact C2 artifact",
                    surface="C2",
                    next_action="regenerate C2 from the registered command and recommit it",
                )
    log_bytes = bytes(combined_log)
    _atomic_write(evidence_path, log_bytes)
    _absolute, output_ref = _repo_relative(consumer, evidence_path)
    command_sha256 = canonical_sha256(command_receipts)
    output_sha256 = _sha256_bytes(log_bytes)
    generator_id = "c2_regeneration_replay"
    entries = []
    for path, boundary in sorted(expected.items()):
        entry = {
            "path": path,
            "operation": boundary["operation"],
            "provenance": "executed",
            "generator_id": generator_id,
            "command_sha256": command_sha256,
            "output_sha256": output_sha256,
            "output_ref": output_ref,
        }
        if boundary["operation"] == "delete":
            entry["before_mode"] = boundary["before_mode"]
            entry["before_sha256"] = boundary["before_sha256"]
        else:
            entry["mode"] = boundary["mode"]
            entry["artifact_sha256"] = boundary["sha256"]
        entries.append(entry)
    return {
        "schema_version": "wiki_viva_boundary_execution.v1",
        "C2": entries,
    }


def _verify_boundary_execution(
    boundaries: Mapping[str, Sequence[Mapping[str, str]]],
    execution: Any,
    *,
    consumer: Path,
) -> None:
    if not isinstance(execution, dict):
        raise RunnerError("invalid_c2_execution_evidence", "the plan omits C2 execution evidence", surface="C2")
    # Reuse the exact validator without trusting an external file at adoption.
    c2 = list(boundaries["C2"])
    if set(execution) != {"schema_version", "C2"} or execution.get("schema_version") != "wiki_viva_boundary_execution.v1":
        raise RunnerError("invalid_c2_execution_evidence", "the plan C2 evidence shape is invalid", surface="C2")
    entries = execution.get("C2")
    if not isinstance(entries, list):
        raise RunnerError("invalid_c2_execution_evidence", "the plan C2 evidence is invalid", surface="C2")
    expected = {item["path"]: item for item in c2}
    if len(entries) != len(expected):
        raise RunnerError("stale_c2_execution_evidence", "the plan C2 evidence is incomplete", surface="C2")
    for entry in entries:
        operation = entry.get("operation") if isinstance(entry, dict) else None
        expected_fields = (
            {
                "path",
                "operation",
                "provenance",
                "generator_id",
                "command_sha256",
                "output_sha256",
                "output_ref",
                "mode",
                "artifact_sha256",
            }
            if operation == "upsert"
            else {
                "path",
                "operation",
                "provenance",
                "generator_id",
                "command_sha256",
                "output_sha256",
                "output_ref",
                "before_mode",
                "before_sha256",
            }
        )
        if (
            not isinstance(entry, dict)
            or set(entry) != expected_fields
            or entry.get("provenance") != "executed"
            or entry.get("generator_id") != "c2_regeneration_replay"
            or entry.get("path") not in expected
            or entry.get("operation")
            != expected[entry["path"]].get("operation")
            or (
                entry.get("operation") == "upsert"
                and (
                    expected[entry["path"]].get("mode") != entry.get("mode")
                    or expected[entry["path"]].get("sha256")
                    != entry.get("artifact_sha256")
                )
            )
            or (
                entry.get("operation") == "delete"
                and (
                    expected[entry["path"]].get("before_mode")
                    != entry.get("before_mode")
                    or expected[entry["path"]].get("before_sha256")
                    != entry.get("before_sha256")
                )
            )
        ):
            raise RunnerError("manual_evidence_rejected", "the plan contains stale or manual C2 evidence", surface="C2")
        output_ref = entry.get("output_ref")
        if not isinstance(output_ref, str):
            raise RunnerError("invalid_c2_execution_evidence", "the plan C2 output reference is invalid", surface="C2")
        output_path = _require_ignored_output(consumer, Path(output_ref))
        if not output_path.is_file() or _sha256_bytes(output_path.read_bytes()) != entry.get("output_sha256"):
            raise RunnerError(
                "stale_c2_execution_output",
                "the plan C2 execution output is stale",
                surface="C2",
                next_action="rerun regeneration and create a new plan",
            )


def _bind_c2_generators(
    boundaries: dict[str, list[dict[str, str]]],
    execution: Mapping[str, Any],
    *,
    package: Mapping[str, Any],
) -> None:
    by_path = {entry["path"]: entry for entry in execution.get("C2", [])}
    for boundary in boundaries["C2"]:
        evidence = by_path.get(boundary["path"])
        if evidence is None:
            continue
        generator_sha256 = _package_c2_generator_sha256(
            package, boundary["path"]
        )
        if generator_sha256 is not None:
            boundary["generator_sha256"] = generator_sha256
        else:
            boundary["generator_sha256"] = canonical_sha256(
                {
                    "generator_id": evidence["generator_id"],
                    "command_sha256": evidence["command_sha256"],
                    "output_sha256": evidence["output_sha256"],
                }
            )


def _repo_relative(root: Path, candidate: Path) -> tuple[Path, str]:
    root = root.resolve()
    absolute = candidate if candidate.is_absolute() else root / candidate
    parent = absolute.parent.resolve()
    resolved = parent / absolute.name
    try:
        relative = resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise RunnerError(
            "unsafe_output_boundary",
            "runner output must stay inside the consumer repository",
            surface="private_evidence_output",
            next_action="choose a Git-ignored, untracked path inside the consumer",
        ) from exc
    cursor = resolved
    while cursor != root:
        if cursor.exists() and cursor.is_symlink():
            raise RunnerError(
                "unsafe_output_symlink",
                "runner output cannot traverse or replace a symbolic link",
                surface="private_evidence_output",
                next_action="choose a real Git-ignored directory inside the consumer",
            )
        cursor = cursor.parent
    return resolved, relative


def _require_ignored_output(root: Path, candidate: Path) -> Path:
    absolute, relative = _repo_relative(root, candidate)
    tracked = _git(root, ["ls-files", "--error-unmatch", "--", relative], check=False)
    if tracked.returncode == 0:
        raise RunnerError(
            "tracked_evidence_output",
            "runner evidence must never overwrite a tracked file",
            surface="private_evidence_output",
            next_action="use an ignored and untracked evidence path",
        )
    ignored = _git(root, ["check-ignore", "-q", "--", relative], check=False)
    if ignored.returncode != 0:
        raise RunnerError(
            "unignored_evidence_output",
            "runner evidence output is not covered by the consumer ignore policy",
            surface="private_evidence_output",
            next_action="ignore the evidence directory explicitly, commit that policy, and retry",
        )
    return absolute


def _atomic_write(path: Path, data: bytes) -> None:
    if path.is_symlink():
        raise RunnerError("unsafe_output_symlink", "runner output cannot replace a symbolic link")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_create_once(path: Path, data: bytes) -> bool:
    """Install immutable first-write evidence atomically without replacement."""

    if path.is_symlink():
        raise RunnerError(
            "unsafe_output_symlink",
            "runner evidence cannot replace a symbolic link",
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            return False
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return True
    finally:
        temporary.unlink(missing_ok=True)


def _read_exact_private_file(path: Path, *, label: str) -> bytes:
    if path.is_symlink():
        raise RunnerError(
            "unsafe_private_evidence",
            f"{label} cannot be a symbolic link",
            surface="private_evidence_output",
        )
    try:
        resolved = path.resolve(strict=True)
        before = resolved.stat()
    except (FileNotFoundError, OSError) as exc:
        raise RunnerError(
            "missing_private_evidence",
            f"{label} is missing",
            surface="private_evidence_output",
        ) from exc
    if not resolved.is_file() or before.st_nlink != 1 or before.st_size > 1024 * 1024:
        raise RunnerError(
            "unsafe_private_evidence",
            f"{label} is not one bounded regular file",
            surface="private_evidence_output",
        )
    raw = resolved.read_bytes()
    after = resolved.stat()
    if (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_nlink,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_nlink,
    ):
        raise RunnerError(
            "changed_private_evidence",
            f"{label} changed while it was read",
            surface="private_evidence_output",
        )
    return raw


def _normalize_version(raw: str) -> str:
    value = raw.strip().splitlines()[0] if raw.strip() else ""
    value = re.sub(r"^(?:Python|Version|v)\s*", "", value, flags=re.IGNORECASE)
    if not value or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}", value) is None:
        raise RunnerError(
            "toolchain_probe_failed",
            "a required tool did not return a canonical version",
            lane="lane_a",
            surface="toolchain",
            next_action="install the exact certified toolchain and generate a new plan",
        )
    return value


def _probe_command_version(argv: Sequence[str], *, cwd: Path) -> str:
    try:
        result = subprocess.run(
            list(argv),
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=30,
            text=True,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RunnerError(
            "toolchain_probe_failed",
            "a required certified tool is unavailable",
            lane="lane_a",
            surface="toolchain",
            next_action="install the exact certified toolchain and retry",
        ) from exc
    if result.returncode != 0:
        raise RunnerError(
            "toolchain_probe_failed",
            "a required certified tool could not be executed",
            lane="lane_a",
            surface="toolchain",
            next_action="install the exact certified toolchain and retry",
        )
    return _normalize_version(result.stdout)


_PYTHON_RESOLVED_PROBE = """
import hashlib
import importlib.metadata as metadata
import json
import platform

entries = sorted({
    (
        str(distribution.metadata.get("Name") or "").strip().lower().replace("_", "-"),
        str(distribution.version).strip(),
    )
    for distribution in metadata.distributions()
    if str(distribution.metadata.get("Name") or "").strip()
    and str(distribution.version).strip()
})
dependencies = [{"name": name, "version": version} for name, version in entries]
encoded = json.dumps(
    dependencies, ensure_ascii=False, sort_keys=True, separators=(",", ":")
).encode("utf-8")
print(json.dumps({
    "schema_version": "wiki_viva_python_resolved_toolchain.v1",
    "implementation": platform.python_implementation().lower(),
    "python_version": platform.python_version(),
    "dependencies": dependencies,
    "dependencies_sha256": hashlib.sha256(encoded).hexdigest(),
}, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
""".strip()


_PLAYWRIGHT_CHROMIUM_PROBE = """
const playwright = require(process.argv[1]);
const packageJson = require(process.argv[1] + '/package.json');
(async () => {
  const browser = await playwright.chromium.launch({headless: true});
  const payload = {
    schema_version: 'wiki_viva_browser_engine_toolchain.v1',
    browser: 'chromium',
    browser_version: browser.version(),
    playwright_version: packageJson.version,
  };
  await browser.close();
  process.stdout.write(JSON.stringify(payload));
})().catch((error) => {
  process.stderr.write(String(error));
  process.exit(2);
});
""".strip()


_PYTHON_PLAYWRIGHT_CHROMIUM_PROBE = """
import importlib.metadata as metadata
import json
from playwright.sync_api import sync_playwright

with sync_playwright() as runtime:
    browser = runtime.chromium.launch(headless=True)
    payload = {
        "schema_version": "wiki_viva_browser_engine_toolchain.v1",
        "browser": "chromium",
        "browser_version": browser.version,
        "playwright_version": metadata.version("playwright"),
    }
    browser.close()
print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
""".strip()


def _toolchain_probe_output(argv: Sequence[str], *, cwd: Path) -> bytes:
    try:
        result = subprocess.run(
            list(argv),
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RunnerError(
            "toolchain_probe_failed",
            "a required certified tool is unavailable",
            lane="lane_a",
            surface="toolchain",
            next_action="install the exact certified toolchain and retry",
        ) from exc
    if result.returncode != 0:
        raise RunnerError(
            "toolchain_probe_failed",
            "a required certified tool could not be executed",
            lane="lane_a",
            surface="toolchain",
            next_action="install the exact certified toolchain and retry",
        )
    return result.stdout


def _probe_json_object(
    raw: bytes, *, label: str, fields: set[str]
) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8", "strict"))
    except (UnicodeDecodeError, ValueError, TypeError) as exc:
        raise RunnerError(
            "toolchain_probe_failed",
            f"the {label} probe did not return canonical JSON",
            lane="lane_a",
            surface="toolchain",
        ) from exc
    if not isinstance(payload, dict) or set(payload) != fields:
        raise RunnerError(
            "toolchain_probe_failed",
            f"the {label} probe contract is incomplete",
            lane="lane_a",
            surface="toolchain",
        )
    return payload


def _python_toolchain_identity(raw: bytes) -> dict[str, str]:
    payload = _probe_json_object(
        raw,
        label="resolved Python",
        fields={
            "schema_version",
            "implementation",
            "python_version",
            "dependencies",
            "dependencies_sha256",
        },
    )
    if payload["schema_version"] != "wiki_viva_python_resolved_toolchain.v1":
        raise RunnerError(
            "toolchain_probe_failed",
            "the resolved Python probe schema is unsupported",
            lane="lane_a",
            surface="toolchain",
        )
    dependencies = payload["dependencies"]
    if not isinstance(dependencies, list) or not all(
        isinstance(item, dict)
        and set(item) == {"name", "version"}
        and isinstance(item["name"], str)
        and item["name"]
        and isinstance(item["version"], str)
        and item["version"]
        for item in dependencies
    ):
        raise RunnerError(
            "toolchain_probe_failed",
            "the resolved Python dependency inventory is invalid",
            lane="lane_a",
            surface="toolchain",
        )
    normalized = sorted(
        dependencies, key=lambda item: (item["name"], item["version"])
    )
    dependency_digest = canonical_sha256(normalized)
    if dependencies != normalized or payload["dependencies_sha256"] != dependency_digest:
        raise RunnerError(
            "toolchain_probe_failed",
            "the resolved Python dependency digest is stale",
            lane="lane_a",
            surface="toolchain",
        )
    implementation = str(payload["implementation"]).lower()
    python_version = _normalize_version(str(payload["python_version"]))
    name = f"{implementation}-resolved"
    version = f"{python_version}+deps.{dependency_digest}"
    if (
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", name) is None
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}", version) is None
    ):
        raise RunnerError(
            "toolchain_probe_failed",
            "the resolved Python identity is not canonical",
            lane="lane_a",
            surface="toolchain",
        )
    return {"name": name, "version": version}


def _active_python_alias() -> str:
    """Return a public PATH alias for the interpreter executing this runner."""

    try:
        active = Path(sys.executable).resolve(strict=True)
    except OSError as exc:
        raise RunnerError(
            "toolchain_probe_failed",
            "the executing Python interpreter cannot be resolved",
            lane="lane_a",
            surface="toolchain",
        ) from exc
    for alias in ("python3", "python"):
        executable = shutil.which(alias)
        if executable is None:
            continue
        try:
            if Path(executable).resolve(strict=True) == active:
                return alias
        except OSError:
            continue
    raise RunnerError(
        "toolchain_probe_failed",
        "no public PATH alias resolves to the Python executing this runner",
        lane="lane_a",
        surface="toolchain",
        next_action="run the upgrade with the certified Python exposed as python or python3",
    )


def _python_toolchain_probe(
    *, cwd: Path
) -> tuple[dict[str, str], list[str], bytes]:
    argv = [_active_python_alias(), "scripts/wiki_toolchain_probe.py", "python"]
    raw = _toolchain_probe_output(argv, cwd=cwd)
    return _python_toolchain_identity(raw), argv, raw


def _playwright_module_root(kit_root: Path) -> Path:
    candidates = [
        kit_root / "apps/wiki-cockpit/node_modules/playwright",
        ROOT / "apps/wiki-cockpit/node_modules/playwright",
    ]
    executable = shutil.which("playwright")
    if executable:
        resolved = Path(executable).resolve()
        for parent in (resolved.parent, *resolved.parents):
            if parent.name == "node_modules":
                candidates.append(parent / "playwright")
                break
    for candidate in candidates:
        if candidate.is_dir() and (candidate / "package.json").is_file():
            return candidate.resolve(strict=True)
    raise RunnerError(
        "toolchain_probe_failed",
        "the installed Playwright module is unavailable for engine verification",
        lane="lane_a",
        surface="toolchain",
        next_action="install the exact Playwright package and browser engine",
    )


def _browser_toolchain_identity(raw: bytes) -> dict[str, str]:
    payload = _probe_json_object(
        raw,
        label="Playwright browser engine",
        fields={
            "schema_version",
            "browser",
            "browser_version",
            "playwright_version",
        },
    )
    if (
        payload["schema_version"] != "wiki_viva_browser_engine_toolchain.v1"
        or payload["browser"] != "chromium"
    ):
        raise RunnerError(
            "toolchain_probe_failed",
            "the browser engine probe contract is unsupported",
            lane="lane_a",
            surface="toolchain",
        )
    playwright_version = _normalize_version(str(payload["playwright_version"]))
    browser_version = _normalize_version(str(payload["browser_version"]))
    version = f"{playwright_version}+chromium.{browser_version}"
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}", version) is None:
        raise RunnerError(
            "toolchain_probe_failed",
            "the Playwright/browser engine identity is not canonical",
            lane="lane_a",
            surface="toolchain",
        )
    return {"name": "playwright-chromium", "version": version}


def _browser_toolchain_probe(
    *, kit_root: Path
) -> tuple[dict[str, str], list[str], bytes]:
    try:
        module_root = _playwright_module_root(kit_root)
    except RunnerError:
        argv = [_active_python_alias(), "scripts/wiki_toolchain_probe.py", "browser"]
        raw = _toolchain_probe_output(argv, cwd=kit_root)
    else:
        argv = ["node", "-e", _PLAYWRIGHT_CHROMIUM_PROBE, "./playwright"]
        raw = _toolchain_probe_output(argv, cwd=module_root.parent)
    return _browser_toolchain_identity(raw), argv, raw


def _probe_browser_version(name: str, *, kit_root: Path) -> str:
    if name == "playwright-chromium":
        return _browser_toolchain_probe(kit_root=kit_root)[0]["version"]
    if name == "playwright":
        return _probe_command_version(["playwright", "--version"], cwd=kit_root)
    if name in {"chromium", "chrome", "webkit", "firefox"}:
        modules = [
            kit_root / "apps/wiki-cockpit/node_modules/playwright",
            ROOT / "apps/wiki-cockpit/node_modules/playwright",
        ]
        module = next((path for path in modules if path.exists()), None)
        if module is None:
            executable = "google-chrome" if name == "chrome" else name
            return _probe_command_version([executable, "--version"], cwd=kit_root)
        browser_name = "chromium" if name == "chrome" else name
        program = (
            "const p=require(process.argv[1]);"
            "const b=p[process.argv[2]];"
            "(async()=>{const x=await b.launch({headless:true});"
            "process.stdout.write(x.version());await x.close();})()"
            ".catch(()=>process.exit(2));"
        )
        return _probe_command_version(
            ["node", "-e", program, str(module.resolve()), browser_name],
            cwd=kit_root,
        )
    return _probe_command_version([name, "--version"], cwd=kit_root)


def _probe_toolchain(capsule: Mapping[str, Any], *, kit_root: Path) -> str:
    expected = capsule.get("toolchain")
    if not isinstance(expected, dict) or set(expected) != {
        "python",
        "node",
        "browser",
        "runner",
    }:
        raise RunnerError(
            "invalid_toolchain_contract",
            "the release capsule toolchain contract is incomplete",
            lane="lane_a",
            surface="toolchain",
        )
    python_identity, _python_argv, _python_raw = _python_toolchain_probe(
        cwd=kit_root
    )
    browser_identity, _browser_argv, _browser_raw = _browser_toolchain_probe(
        kit_root=kit_root
    )
    actual = {
        "python": python_identity,
        "node": {
            "name": "node",
            "version": _probe_command_version(["node", "--version"], cwd=kit_root),
        },
        "browser": browser_identity,
        "runner": {
            "name": "wiki-upgrade",
            "version": _runner_identity_version(
                Path(__file__).resolve().parents[1]
            ),
        },
    }
    if actual != expected or canonical_sha256(actual) != capsule.get("toolchain_sha256"):
        raise RunnerError(
            "toolchain_identity_mismatch",
            "the active runtime differs from the exact certified toolchain",
            lane="lane_a",
            surface="toolchain",
            next_action="activate the certified Python, Node, browser and runner versions",
        )
    return canonical_sha256(actual)


def _require_v3_cli_package(package_path: Path) -> dict[str, Any]:
    """Reject transition packages before capsule loading or any mutation."""

    try:
        package = load_mapping(package_path)
    except (OSError, ValueError, TypeError) as exc:
        raise RunnerError(
            "invalid_upgrade_package",
            "the upgrade package could not be loaded safely",
            lane="lane_a",
            surface="upgrade_package",
        ) from exc
    if package.get("schema_version") != _TWO_LANE_PACKAGE:
        raise RunnerError(
            "legacy_package_requires_original_runbook",
            "wiki_upgrade.py executes only the v3 two-lane contract",
            lane="lane_b",
            surface="transition_package",
            contract=str(package.get("schema_version") or "unknown_package_schema"),
            next_action=(
                "keep the in-flight v1/v2 migration on its original runbook and "
                "execute every migration.required_gates entry; do not reuse v3 receipts"
            ),
        )
    return package


def _safe_relative_path(raw: object, *, label: str) -> str:
    if not isinstance(raw, str) or not raw or "\x00" in raw or "\\" in raw:
        raise RunnerError(
            "unsafe_certification_path",
            f"{label} is not a safe relative path",
            lane="lane_a",
            surface="certification_authority",
        )
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts or candidate.as_posix() != raw:
        raise RunnerError(
            "unsafe_certification_path",
            f"{label} is not a canonical relative path",
            lane="lane_a",
            surface="certification_authority",
        )
    return raw


def _read_fd_pinned_regular(
    root: Path,
    relative: str,
    *,
    label: str,
    max_bytes: int,
    lane: str,
    surface: str,
    unsafe_code: str,
    missing_code: str,
) -> bytes:
    """Read one root-relative regular file through an immutable descriptor chain."""

    if os.name != "posix":
        raise RunnerError(
            unsafe_code,
            f"{label} requires descriptor-pinned POSIX verification",
            lane=lane,
            surface=surface,
        )
    parts = Path(relative).parts
    opened: list[int] = []
    descriptor: int | None = None
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    file_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(root.resolve(strict=True), directory_flags)
        opened.append(descriptor)
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise RunnerError(
                unsafe_code,
                f"{label} authority root is not a directory",
                lane=lane,
                surface=surface,
            )
        for part in parts[:-1]:
            descriptor = os.open(part, directory_flags, dir_fd=descriptor)
            opened.append(descriptor)
            if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise RunnerError(
                    unsafe_code,
                    f"{label} traverses a non-directory component",
                    lane=lane,
                    surface=surface,
                )
        descriptor = os.open(parts[-1], file_flags, dir_fd=descriptor)
        opened.append(descriptor)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size > max_bytes
        ):
            raise RunnerError(
                unsafe_code,
                f"{label} is not one bounded regular, non-hard-linked file",
                lane=lane,
                surface=surface,
            )
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, max_bytes + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise RunnerError(
                    unsafe_code,
                    f"{label} exceeds its evidence size limit",
                    lane=lane,
                    surface=surface,
                )
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_nlink,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_nlink,
        ):
            raise RunnerError(
                unsafe_code,
                f"{label} changed while its pinned descriptor was read",
                lane=lane,
                surface=surface,
            )
        return b"".join(chunks)
    except RunnerError:
        raise
    except FileNotFoundError as exc:
        raise RunnerError(
            missing_code,
            f"{label} is missing from its authority root",
            lane=lane,
            surface=surface,
        ) from exc
    except OSError as exc:
        raise RunnerError(
            unsafe_code,
            f"{label} could not be opened without link traversal",
            lane=lane,
            surface=surface,
        ) from exc
    finally:
        for handle in reversed(opened):
            with contextlib.suppress(OSError):
                os.close(handle)


def _safe_certification_file(
    root: Path, raw_path: object, *, label: str
) -> tuple[str, bytes]:
    relative = _safe_relative_path(raw_path, label=f"{label} path")
    return relative, _read_fd_pinned_regular(
        root,
        relative,
        label=label,
        max_bytes=_MAX_CERTIFICATION_FILE_BYTES,
        lane="lane_a",
        surface="certification_authority",
        unsafe_code="unsafe_certification_file",
        missing_code="missing_certification_file",
    )


def _require_public_certification_output(raw: bytes, *, gate_id: str) -> None:
    if not raw or len(raw) > 64 * 1024 * 1024:
        raise RunnerError(
            "invalid_certification_output",
            "a certification gate produced empty or oversized evidence",
            lane="lane_a",
            surface=gate_id,
        )
    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise RunnerError(
            "binary_certification_output",
            "a certification gate output is not public UTF-8 text",
            lane="lane_a",
            surface=gate_id,
        ) from exc
    try:
        views = _percent_decoded_views(text)
    except (UnicodeDecodeError, ValueError) as exc:
        raise RunnerError(
            "private_certification_output",
            "a Lane A gate output contains invalid or excessively nested percent-encoded private evidence",
            lane="lane_a",
            surface=gate_id,
        ) from exc
    if any(
        "\x00" in view
        or _HOST_PATH_RE.search(view)
        or _PRIVATE_EVIDENCE_RE.search(view)
        or _PRIVATE_ROUTE_RE.search(view)
        for view in views
    ):
        raise RunnerError(
            "private_certification_output",
            "a Lane A gate output contains a host-local or private evidence reference",
            lane="lane_a",
            surface=gate_id,
            next_action="repair the public synthetic gate output before recertifying",
        )
    findings = []
    for view in views:
        masked = re.sub(
            r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{64}|[0-9A-Fa-f]{40})(?![0-9A-Fa-f])",
            "<digest>",
            view,
        )
        findings.extend(
            finding
            for finding in scan_text(masked)
            if finding.category in {"secret", "pii"}
        )
    if findings:
        raise RunnerError(
            "private_certification_output",
            "a Lane A gate output contains secret or personal data",
            lane="lane_a",
            surface=gate_id,
            next_action="remove private data from the public fixture and run a new certification",
        )


def _percent_decoded_views(value: str) -> tuple[str, ...]:
    """Return bounded views for literal, encoded and double-encoded output."""

    views = [value]
    current = value
    for _ in range(_MAX_PERCENT_DECODE_ROUNDS):
        if _PERCENT_ESCAPE_RE.search(current) is None:
            break
        decoded = unquote_to_bytes(current).decode("utf-8", "strict")
        if decoded == current:
            break
        views.append(decoded)
        current = decoded
    if _PERCENT_ESCAPE_RE.search(current) is not None:
        raise ValueError("percent encoding exceeds the public normalization bound")
    return tuple(views)


def _prepare_certification_output(source_root: Path, requested: Path) -> Path:
    output = requested.expanduser().resolve()
    if output.exists():
        raise RunnerError(
            "certification_output_exists",
            "Lane A certification requires a new immutable output directory",
            lane="lane_a",
            surface="certification_authority",
            next_action="choose a new output directory; never overwrite a certification run",
        )
    with contextlib.suppress(ValueError):
        relative = output.relative_to(source_root.resolve())
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", relative.as_posix()],
            cwd=source_root,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if ignored.returncode != 0:
            raise RunnerError(
                "tracked_certification_output",
                "Lane A evidence inside the source checkout must be Git-ignored",
                lane="lane_a",
                surface="certification_authority",
                next_action="use an ignored directory or an output root outside the repository",
            )
    output.mkdir(parents=True, mode=0o700)
    return output


def _stage_visual_authority(
    *, source_root: Path, manifest_ref: str, destination_root: Path
) -> None:
    relative, manifest_raw = _safe_certification_file(
        source_root, manifest_ref, label="source visual manifest"
    )
    try:
        payload = json.loads(manifest_raw)
    except (UnicodeDecodeError, ValueError, TypeError) as exc:
        raise RunnerError(
            "invalid_visual_manifest",
            "the source visual manifest is malformed",
            lane="lane_a",
            surface="visual_manifest",
        ) from exc
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, list) or not entries:
        raise RunnerError(
            "invalid_visual_manifest",
            "the source visual manifest has no public synthetic entries",
            lane="lane_a",
            surface="visual_manifest",
        )
    files = [relative]
    for entry in entries:
        if not isinstance(entry, dict):
            raise RunnerError(
                "invalid_visual_manifest",
                "the source visual manifest contains a non-object entry",
                lane="lane_a",
                surface="visual_manifest",
            )
        entry_id = entry.get("id")
        state = entry.get("state")
        if (
            not isinstance(entry_id, str)
            or _VISUAL_ENTRY_ID_RE.fullmatch(entry_id) is None
            or not isinstance(state, str)
            or _VISUAL_CAPTURE_STATE_RE.fullmatch(state) is None
        ):
            raise RunnerError(
                "invalid_visual_manifest",
                "a source visual entry lacks exact record-backed identity",
                lane="lane_a",
                surface="visual_manifest",
            )
        files.extend(
            [
                _safe_relative_path(entry.get("path"), label="visual image"),
                _safe_relative_path(
                    f"records/{entry_id}.json", label="visual capture record"
                ),
            ]
        )
    if len(files) != len(set(files)):
        raise RunnerError(
            "duplicate_visual_artifact",
            "the source visual manifest repeats an artifact path",
            lane="lane_a",
            surface="visual_manifest",
        )
    for item in files:
        _safe_relative, raw = _safe_certification_file(
            source_root, item, label="visual authority file"
        )
        _atomic_write(destination_root / item, raw)


def _certification_toolchain(
    *, source_root: Path, gate_output_root: Path, run_id: str
) -> tuple[str, dict[str, dict[str, str]]]:
    try:
        source_runner_identity = _runner_identity_version(source_root)
        active_runner_identity = _runner_identity_version(
            Path(__file__).resolve().parents[1]
        )
    except (OSError, ValueError) as exc:
        raise RunnerError(
            "runner_identity_mismatch",
            "the source or active runner closure is incomplete",
            lane="lane_a",
            surface="toolchain",
        ) from exc
    if source_runner_identity != active_runner_identity:
        raise RunnerError(
            "runner_identity_mismatch",
            "the executing runner closure differs byte-for-byte from source_sha",
            lane="lane_a",
            surface="toolchain",
            next_action="execute certification with the runner from the exact source worktree",
        )
    python_alias = _active_python_alias()
    browser_argv = [python_alias, "scripts/wiki_toolchain_probe.py", "browser"]
    browser_raw = _toolchain_probe_output(browser_argv, cwd=source_root)
    browser_identity = _browser_toolchain_identity(browser_raw)
    python_argv = [python_alias, "scripts/wiki_toolchain_probe.py", "python"]
    python_raw = _toolchain_probe_output(python_argv, cwd=source_root)
    python_identity = _python_toolchain_identity(python_raw)
    node_argv = ["node", "--version"]
    node_raw = _toolchain_probe_output(node_argv, cwd=source_root)
    node_identity = {"name": "node", "version": _normalize_version(node_raw.decode("utf-8", "strict"))}
    runner_argv = [python_alias, "scripts/wiki_upgrade.py", "--version"]
    runner_raw = _toolchain_probe_output(runner_argv, cwd=source_root)
    runner_identity = {"name": "wiki-upgrade", "version": source_runner_identity}
    probes: list[tuple[str, dict[str, str], list[str], bytes]] = [
        ("browser", browser_identity, browser_argv, browser_raw),
        ("node", node_identity, node_argv, node_raw),
        ("python", python_identity, python_argv, python_raw),
        ("runner", runner_identity, runner_argv, runner_raw),
    ]
    entries: list[dict[str, Any]] = []
    toolchain: dict[str, dict[str, str]] = {}
    for tool_id, identity, argv, raw in probes:
        name = identity["name"]
        version = identity["version"]
        _require_public_certification_output(raw, gate_id=f"toolchain-{tool_id}")
        probe_text = raw.decode("utf-8", "strict")
        evidence_raw = raw
        if re.search(
            rf"(?<![A-Za-z0-9]){re.escape(version)}(?![A-Za-z0-9])",
            probe_text,
        ) is None:
            # Preserve the exact command output and append one canonical,
            # derived identity line.  Node's native `v22...` prefix otherwise
            # fails the core's deliberate token-boundary verification.
            evidence_raw += f"{name} {version}\n".encode("utf-8")
        output_ref = f"toolchain/{tool_id}.log"
        _atomic_write(gate_output_root / output_ref, evidence_raw)
        toolchain[tool_id] = identity
        entries.append(
            {
                "id": tool_id,
                **identity,
                "provenance": "executed",
                "probe_argv": argv,
                "exit_code": 0,
                "output_ref": output_ref,
                "output_sha256": _sha256_bytes(evidence_raw),
                "output_bytes": len(evidence_raw),
            }
        )
    probe_ref = "toolchain/probe-manifest.json"
    _atomic_write(
        gate_output_root / probe_ref,
        _json_bytes(
            {
                "schema_version": "wiki_viva_toolchain_probe.v1",
                "run_id": run_id,
                "entries": entries,
            }
        ),
    )
    return probe_ref, toolchain


def _certification_environment() -> dict[str, str]:
    allowed = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "CI", "TZ"}
    }
    allowed["PYTHONUNBUFFERED"] = "1"
    allowed["TZ"] = "UTC"
    return allowed


def _run_certification_gate(
    gate: Mapping[str, Any],
    *,
    source_root: Path,
    gate_output_root: Path,
    source_sha: str,
    timeout: int,
    heartbeat: float,
) -> dict[str, Any]:
    gate_id = str(gate["id"])
    command = str(gate["command"])
    argv = _parse_command(command, kit_root=source_root)
    output_ref = f"outputs/{gate_id}.log"
    output_path = gate_output_root / output_ref
    output_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    _emit({"event": "certification_gate_started", "lane": "lane_a", "gate": gate_id})
    with output_path.open("wb") as log:
        try:
            process = subprocess.Popen(
                argv,
                cwd=source_root,
                stdout=log,
                stderr=subprocess.STDOUT,
                env=_certification_environment(),
                start_new_session=True,
            )
        except OSError as exc:
            raise RunnerError(
                "certification_gate_unavailable",
                "a Lane A gate command could not be started",
                lane="lane_a",
                surface=gate_id,
            ) from exc
        next_heartbeat = started + max(0.1, heartbeat)
        exit_code = 1
        while process.poll() is None:
            now = time.monotonic()
            if now - started > timeout:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                exit_code = 124
                break
            if now >= next_heartbeat:
                _emit(
                    {
                        "event": "certification_gate_heartbeat",
                        "lane": "lane_a",
                        "gate": gate_id,
                        "elapsed_seconds": round(now - started, 3),
                    }
                )
                next_heartbeat = now + max(0.1, heartbeat)
            time.sleep(min(0.1, max(0.02, heartbeat / 10)))
        else:
            exit_code = int(process.returncode or 0)
        log.flush()
        os.fsync(log.fileno())
    raw = output_path.read_bytes()
    status = "passed" if exit_code == 0 else "failed"
    _emit(
        {
            "event": "certification_gate_completed",
            "lane": "lane_a",
            "gate": gate_id,
            "status": status,
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
    )
    if status == "passed":
        _require_public_certification_output(raw, gate_id=gate_id)
    return {
        "id": gate_id,
        "class": gate["class"],
        "provenance": "executed",
        "status": status,
        "exit_code": exit_code,
        "subject_sha": source_sha,
        "command_sha256": _sha256_bytes(command.encode("utf-8")),
        "output_ref": output_ref,
        "output_sha256": _sha256_bytes(raw),
        "output_bytes": len(raw),
    }


def _execute_certification_matrix(
    *,
    package: Mapping[str, Any],
    catalog: Sequence[Mapping[str, Any]],
    source_root: Path,
    gate_output_root: Path,
    source_sha: str,
    jobs: int,
    timeout: int,
    heartbeat: float,
) -> list[dict[str, Any]]:
    policies = package["migration"]["gate_policies"]
    upstream_ids = {
        str(item["id"])
        for item in catalog
        if item["class"] == "upstream_certified"
    }
    if not upstream_ids:
        raise RunnerError(
            "missing_upstream_certification_gates",
            "the package has no upstream_certified gates to seal into a capsule",
            lane="lane_a",
            surface="gate_registry",
        )
    invalid_dependencies = {
        str(item["id"]): sorted(
            dependency
            for dependency in policies[item["id"]].get("depends_on", [])
            if dependency not in upstream_ids
        )
        for item in catalog
        if item["class"] == "upstream_certified"
    }
    invalid_dependencies = {
        gate_id: dependencies
        for gate_id, dependencies in invalid_dependencies.items()
        if dependencies
    }
    if invalid_dependencies:
        raise RunnerError(
            "invalid_lane_a_gate_dependency",
            "an upstream-certified gate depends on a consumer-owned gate",
            lane="lane_a",
            surface="gate_registry",
            next_action=(
                "make Lane A upstream gates self-contained; keep canary and "
                "background certification in Lane B"
            ),
        )
    selected = {
        str(item["id"]): {
            **dict(item),
            "depends_on": [
                dependency
                for dependency in policies[item["id"]].get("depends_on", [])
                if dependency in upstream_ids
            ],
            "resource_group": policies[item["id"]]["resource_group"],
        }
        for item in catalog
        if item["class"] == "upstream_certified"
    }
    remaining = dict(selected)
    completed: dict[str, dict[str, Any]] = {}
    while remaining:
        ready = [
            gate
            for gate in remaining.values()
            if set(gate["depends_on"]).issubset(completed)
        ]
        if not ready:
            raise RunnerError(
                "certification_gate_dependency_deadlock",
                "Lane A selected gates contain an unresolved dependency cycle",
                lane="lane_a",
                surface="gate_registry",
            )
        wave: list[Mapping[str, Any]] = []
        resources: set[str] = set()
        for gate in sorted(ready, key=lambda item: item["id"]):
            resource = str(gate["resource_group"])
            if resource in resources:
                continue
            resources.add(resource)
            wave.append(gate)
        _require_clean(source_root)
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(jobs, len(wave))
        ) as executor:
            futures = {
                executor.submit(
                    _run_certification_gate,
                    gate,
                    source_root=source_root,
                    gate_output_root=gate_output_root,
                    source_sha=source_sha,
                    timeout=timeout,
                    heartbeat=heartbeat,
                ): gate
                for gate in wave
            }
            wave_results = [future.result() for future in futures]
        _require_clean(source_root)
        if _head(source_root) != source_sha:
            raise RunnerError(
                "changed_certification_subject",
                "a Lane A gate changed the exact source subject",
                lane="lane_a",
                surface="portable_source",
            )
        failed = [result for result in wave_results if result["status"] != "passed"]
        if failed:
            raise RunnerError(
                "certification_gate_failed",
                "a required Lane A certification gate failed",
                lane="lane_a",
                surface=sorted(result["id"] for result in failed)[0],
                next_action=(
                    "freeze this failed release subject, inspect the retained private "
                    "runner log, fix the defect publicly, and form a new source/package "
                    "subject; never retry or relabel this subject"
                ),
            )
        for result in wave_results:
            completed[result["id"]] = result
            remaining.pop(result["id"], None)
    return [completed[gate_id] for gate_id in sorted(completed)]


def _validate_package_contract(package: dict[str, Any]) -> None:
    errors = validate_upgrade_package(package)
    if package.get("schema_version") == _TWO_LANE_PACKAGE:
        schema_path = ROOT / "docs/references/schemas/wiki-upgrade-package-v3.schema.json"
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            schema_errors = list(Draft202012Validator(schema).iter_errors(package))
        except (OSError, ValueError, TypeError) as exc:
            raise RunnerError(
                "upgrade_package_schema_unavailable",
                "the runner cannot load its versioned v3 package schema",
                lane="lane_a",
                surface="upgrade_package",
            ) from exc
        if schema_errors:
            errors = [*errors, "schema"]
    if errors:
        raise RunnerError(
            "invalid_upgrade_package",
            "the upgrade package failed its complete versioned schema and semantic contract",
            lane="lane_a",
            surface="upgrade_package",
            next_action="repair and recertify the public package before adoption",
        )


def _certification_preflight(
    *, package: dict[str, Any], registry: dict[str, Any], source_root: Path
) -> tuple[str, list[dict[str, Any]]]:
    _validate_package_contract(package)
    if package.get("schema_version") != _TWO_LANE_PACKAGE:
        raise RunnerError(
            "legacy_package_cannot_be_certified",
            "Lane A certification requires the v3 package contract",
            lane="lane_a",
            surface="upgrade_package",
        )
    if not package_is_pinned(package):
        raise RunnerError(
            "release_not_releasable",
            "the package release is not pinned in a releasable status",
            lane="lane_a",
            surface="release_status",
            next_action=(
                "complete public validation and human review, promote the package status, "
                "then certify the exact merged source subject"
            ),
        )
    try:
        registry_sha256 = verify_impact_registry(registry)
    except UpgradeLaneError as exc:
        raise RunnerError(
            "invalid_impact_registry",
            "the Lane A impact/command registry failed closed validation",
            lane="lane_a",
            surface="impact_registry",
        ) from exc
    catalog = registry.get("gate_catalog")
    migration = package.get("migration")
    if not isinstance(catalog, list) or not isinstance(migration, dict):
        raise RunnerError(
            "invalid_certification_registry",
            "the package or impact registry omits its executable gate catalog",
            lane="lane_a",
            surface="gate_registry",
        )
    commands = migration.get("gate_commands")
    policies = migration.get("gate_policies")
    package_impact = migration.get("impact_registry")
    projection = sorted(
        (
            {
                "id": gate_id,
                "class": policies[gate_id]["class"],
                "command": commands[gate_id],
            }
            for gate_id in commands
        ),
        key=lambda item: item["id"],
    ) if isinstance(commands, dict) and isinstance(policies, dict) else []
    if (
        projection != catalog
        or migration.get("required_gates") != [item["id"] for item in catalog]
        or migration.get("command_registry_sha256") != canonical_sha256(catalog)
        or not isinstance(package_impact, dict)
        or package_impact.get("sha256") != registry_sha256
    ):
        raise RunnerError(
            "package_registry_binding_mismatch",
            "the package and impact registry do not define one exact command authority",
            lane="lane_a",
            surface="gate_registry",
            next_action="regenerate and review the package and impact registry together",
        )
    source = source_root.resolve(strict=True)
    top = _git(source, ["rev-parse", "--show-toplevel"]).stdout.decode(
        "utf-8", "strict"
    ).strip()
    if Path(top).resolve() != source:
        raise RunnerError(
            "invalid_source_root",
            "Lane A source-root must be the exact Git repository root",
            lane="lane_a",
            surface="portable_source",
        )
    source_sha = str(package["release"]["source_sha"])
    resolved = _commit(source, source_sha, fallback=source_sha)
    if resolved != source_sha or _head(source) != source_sha:
        raise RunnerError(
            "source_subject_not_checked_out",
            "Lane A must execute at the exact package source_sha",
            lane="lane_a",
            surface="portable_source",
            next_action="check out the exact source_sha in a clean release worktree",
        )
    _require_clean(source)
    return source_sha, [dict(item) for item in catalog]


def _certification_receipt_digest(
    receipt: Mapping[str, Any],
    *,
    package: Mapping[str, Any],
    registry: Mapping[str, Any],
    capsule: Mapping[str, Any],
    gate_output_root: Path,
) -> str:
    try:
        schema = json.loads(_CERTIFICATION_RECEIPT_SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        errors = sorted(
            Draft202012Validator(schema).iter_errors(dict(receipt)),
            key=lambda item: list(item.absolute_path),
        )
    except (OSError, ValueError, TypeError) as exc:
        raise RunnerError(
            "certification_receipt_schema_unavailable",
            "the Lane A certification receipt schema is unavailable",
            lane="lane_a",
            surface="certification_receipt",
        ) from exc
    if errors:
        raise RunnerError(
            "invalid_certification_receipt",
            "the Lane A certification receipt failed its versioned schema",
            lane="lane_a",
            surface="certification_receipt",
        )
    unsigned = dict(receipt)
    claimed = unsigned.pop("receipt_sha256", None)
    digest = canonical_sha256(unsigned)
    if claimed != digest:
        raise RunnerError(
            "stale_certification_receipt",
            "the Lane A certification receipt digest is stale",
            lane="lane_a",
            surface="certification_receipt",
        )
    catalog = registry.get("gate_catalog")
    if not isinstance(catalog, list):
        raise RunnerError(
            "invalid_certification_registry",
            "the certification receipt has no exact command authority",
            lane="lane_a",
            surface="gate_registry",
        )
    command_by_id = {item["id"]: item for item in catalog}
    expected = sorted(
        item["id"]
        for item in catalog
        if item["class"] == "upstream_certified"
    )
    results = receipt.get("gate_results")
    if (
        receipt.get("certification_gate_ids") != expected
        or receipt.get("upstream_gate_ids") != expected
        or not isinstance(results, list)
        or [item.get("id") for item in results if isinstance(item, dict)] != expected
    ):
        raise RunnerError(
            "incomplete_certification_receipt",
            "the receipt does not cover exactly every upstream certification gate",
            lane="lane_a",
            surface="certification_receipt",
        )
    source_sha = capsule.get("source_sha")
    for result in results:
        registered = command_by_id.get(result["id"])
        if (
            registered is None
            or result["class"] != registered["class"]
            or result["subject_sha"] != source_sha
            or result["command_sha256"]
            != _sha256_bytes(registered["command"].encode("utf-8"))
        ):
            raise RunnerError(
                "stale_certification_gate_identity",
                "a certification result differs from source or command authority",
                lane="lane_a",
                surface=result["id"],
            )
        _relative, raw = _safe_certification_file(
            gate_output_root,
            result["output_ref"],
            label=f"certification gate output {result['id']}",
        )
        if (
            _sha256_bytes(raw) != result["output_sha256"]
            or len(raw) != result["output_bytes"]
        ):
            raise RunnerError(
                "stale_certification_gate_output",
                "a certification output no longer matches its receipt",
                lane="lane_a",
                surface=result["id"],
            )
        _require_public_certification_output(raw, gate_id=result["id"])
    expected_top = {
        "release_id": capsule.get("release_id"),
        "source_sha": source_sha,
        "package_sha256": canonical_sha256(package),
        "portable_tree_sha256": capsule.get("portable_tree_sha256"),
        "command_registry_sha256": capsule.get("command_registry_sha256"),
        "toolchain_sha256": capsule.get("toolchain_sha256"),
        "visual_manifest_sha256": capsule.get("visual_manifest_sha256"),
        "capsule_sha256": capsule.get("capsule_sha256"),
        "attestation_sha256": capsule.get("attestation_sha256"),
    }
    if any(receipt.get(key) != value for key, value in expected_top.items()):
        raise RunnerError(
            "stale_certification_identity",
            "the certification receipt differs from package or capsule identity",
            lane="lane_a",
            surface="certification_receipt",
        )
    return digest


def _certify(args: argparse.Namespace) -> int:
    package = _require_v3_cli_package(args.package)
    try:
        registry = load_mapping(args.impact_registry)
    except (OSError, ValueError, TypeError) as exc:
        raise RunnerError(
            "invalid_impact_registry",
            "the Lane A impact registry could not be loaded",
            lane="lane_a",
            surface="impact_registry",
        ) from exc
    source_root = args.source_root.resolve()
    source_sha, catalog = _certification_preflight(
        package=package, registry=registry, source_root=source_root
    )
    authority_id = str(args.attestation_authority_id or "")
    if _GATE_ID_RE.fullmatch(authority_id) is None:
        raise RunnerError(
            "invalid_attestation_authority",
            "the Lane A attestation authority id is invalid",
            lane="lane_a",
            surface="execution_attestation",
        )
    package_sha256 = canonical_sha256(package)
    run_id = args.run_id or f"lane-a-{source_sha[:12]}-{package_sha256[:12]}"
    if _GATE_ID_RE.fullmatch(run_id) is None:
        raise RunnerError(
            "invalid_certification_run_id",
            "the Lane A run id is invalid",
            lane="lane_a",
            surface="certification_receipt",
        )
    output_root = _prepare_certification_output(source_root, args.out_dir)
    visual_root = output_root / "visual"
    gate_output_root = output_root / "gate-output"
    visual_root.mkdir(mode=0o700)
    gate_output_root.mkdir(mode=0o700)
    manifest_ref = _safe_relative_path(
        args.visual_manifest_ref, label="visual manifest"
    )
    _stage_visual_authority(
        source_root=args.visual_root.resolve(),
        manifest_ref=manifest_ref,
        destination_root=visual_root,
    )
    toolchain_probe_ref, _toolchain = _certification_toolchain(
        source_root=source_root,
        gate_output_root=gate_output_root,
        run_id=run_id,
    )
    results = _execute_certification_matrix(
        package=package,
        catalog=catalog,
        source_root=source_root,
        gate_output_root=gate_output_root,
        source_sha=source_sha,
        jobs=args.jobs,
        timeout=args.gate_timeout,
        heartbeat=args.heartbeat_seconds,
    )
    certified = [
        dict(result)
        for result in results
        if result["class"] == "upstream_certified"
    ]
    capsule_seed = {
        "release_id": package["release"]["id"],
        "status": "certified",
        "source_sha": source_sha,
        "package_sha256": "0" * 64,
        "portable_tree_sha256": "0" * 64,
        "command_registry": catalog,
        "toolchain": _toolchain,
        "toolchain_probe_ref": toolchain_probe_ref,
        "certified_gates": certified,
        "run_id": run_id,
        "visual_manifest_ref": manifest_ref,
        "visual_manifest_sha256": "0" * 64,
        "attestation_authority_id": authority_id,
        "attestation_ref": "execution-attestation.json",
    }
    try:
        attestation = collect_release_attestation(
            capsule_seed,
            package=package,
            impact_registry=registry,
            source_root=source_root,
            visual_root=visual_root,
            gate_output_root=gate_output_root,
        )
    except UpgradeLaneError as exc:
        raise RunnerError(
            "certification_attestation_rejected",
            "the executed Lane A evidence could not form an exact attestation",
            lane="lane_a",
            surface="execution_attestation",
        ) from exc
    if attestation.get("schema_version") != EXECUTION_ATTESTATION_SCHEMA_VERSION:
        raise RunnerError(
            "invalid_execution_attestation",
            "the generated Lane A attestation schema is invalid",
            lane="lane_a",
            surface="execution_attestation",
        )
    attestation_raw = _json_bytes(attestation)
    _atomic_write(gate_output_root / "execution-attestation.json", attestation_raw)
    attestation_sha256 = _sha256_bytes(attestation_raw)
    authority = ReleaseCapsuleAuthority(
        package=package,
        impact_registry=registry,
        source_root=source_root,
        visual_root=visual_root,
        gate_output_root=gate_output_root,
        verified_attestation_sha256=attestation_sha256,
    )
    try:
        capsule = seal_release_capsule(capsule_seed, authority=authority)
    except UpgradeLaneError as exc:
        raise RunnerError(
            "release_capsule_rejected",
            "the executed Lane A evidence could not seal a verified release capsule",
            lane="lane_a",
            surface="release_capsule",
        ) from exc
    capsule_ref = "release-capsule.json"
    capsule_raw = _json_bytes(capsule)
    _atomic_write(output_root / capsule_ref, capsule_raw)
    receipt: dict[str, Any] = {
        "schema_version": CERTIFICATION_RECEIPT_SCHEMA_VERSION,
        "status": "passed",
        "lane": "lane_a",
        "release_id": capsule["release_id"],
        "run_id": run_id,
        "source_sha": source_sha,
        "package_sha256": capsule["package_sha256"],
        "portable_tree_sha256": capsule["portable_tree_sha256"],
        "command_registry_sha256": capsule["command_registry_sha256"],
        "toolchain_sha256": capsule["toolchain_sha256"],
        "visual_manifest_sha256": capsule["visual_manifest_sha256"],
        "capsule_ref": capsule_ref,
        "capsule_sha256": capsule["capsule_sha256"],
        "attestation_ref": capsule["attestation_ref"],
        "attestation_sha256": capsule["attestation_sha256"],
        "authority_ref": "release-authority.json",
        "certification_gate_ids": [result["id"] for result in results],
        "upstream_gate_ids": [
            result["id"]
            for result in results
            if result["class"] == "upstream_certified"
        ],
        "gate_results": results,
        "human_gate_required": True,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    _certification_receipt_digest(
        receipt,
        package=package,
        registry=registry,
        capsule=capsule,
        gate_output_root=gate_output_root,
    )
    receipt_ref = "certification-receipt.json"
    receipt_raw = _json_bytes(receipt)
    _atomic_write(output_root / receipt_ref, receipt_raw)
    trust_ref = "trusted-attestation-sha256.txt"
    trust_raw = f"{attestation_sha256}\n".encode("ascii")
    _atomic_write(output_root / trust_ref, trust_raw)
    authority_bundle = {
        "schema_version": "wiki_viva_release_capsule_authority.v1",
        "visual_root": "visual",
        "gate_output_root": "gate-output",
        "release_capsule_ref": capsule_ref,
        "release_capsule_file_sha256": _sha256_bytes(capsule_raw),
        "certification_receipt_ref": receipt_ref,
        "certification_receipt_file_sha256": _sha256_bytes(receipt_raw),
        "trust_anchor_ref": trust_ref,
        "trust_anchor_file_sha256": _sha256_bytes(trust_raw),
    }
    _atomic_write(
        output_root / "release-authority.json", _json_bytes(authority_bundle)
    )
    _emit(
        {
            "schema_version": "wiki_viva_upgrade_certification_summary.v1",
            "status": "certified",
            "lane": "lane_a",
            "release_id": capsule["release_id"],
            "run_id": run_id,
            "source_sha": source_sha,
            "capsule_sha256": capsule["capsule_sha256"],
            "receipt_sha256": receipt["receipt_sha256"],
            "upstream_gate_count": len(receipt["upstream_gate_ids"]),
            "human_gate_required": True,
        }
    )
    return 0


def _load_artifacts(
    package_path: Path,
    capsule_path: Path,
    registry_path: Path,
    *,
    kit_root: Path,
    authority_path: Path,
    trusted_attestation_sha256: str,
    require_sealed_authority: bool = False,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    VerifiedReleaseCapsule,
]:
    try:
        package = load_mapping(package_path)
        capsule = load_mapping(capsule_path)
        registry = load_mapping(registry_path)
        _probe_toolchain(capsule, kit_root=kit_root)
        _validate_package_contract(package)
        authority_bundle = load_mapping(authority_path)
        base_authority_fields = {
            "schema_version",
            "visual_root",
            "gate_output_root",
        }
        sealed_authority_fields = base_authority_fields | {
            "release_capsule_ref",
            "release_capsule_file_sha256",
            "certification_receipt_ref",
            "certification_receipt_file_sha256",
            "trust_anchor_ref",
            "trust_anchor_file_sha256",
        }
        authority_fields = frozenset(authority_bundle)
        allowed_authority_fields = (
            {frozenset(sealed_authority_fields)}
            if require_sealed_authority
            else {
                frozenset(base_authority_fields),
                frozenset(sealed_authority_fields),
            }
        )
        if (
            authority_fields not in allowed_authority_fields
            or authority_bundle.get("schema_version")
            != "wiki_viva_release_capsule_authority.v1"
        ):
            raise UpgradeLaneError("release authority bundle fields are invalid")
        authority_base = authority_path.resolve().parent

        def authority_root(field: str) -> Path:
            raw = authority_bundle[field]
            if (
                not isinstance(raw, str)
                or not raw
                or Path(raw).is_absolute()
                or ".." in Path(raw).parts
            ):
                raise UpgradeLaneError(f"release authority {field} is unsafe")
            resolved = (authority_base / raw).resolve(strict=True)
            resolved.relative_to(authority_base)
            return resolved

        visual_authority_root = authority_root("visual_root")
        gate_authority_root = authority_root("gate_output_root")
        if authority_fields == frozenset(sealed_authority_fields):
            capsule_ref, capsule_raw = _safe_certification_file(
                authority_base,
                authority_bundle["release_capsule_ref"],
                label="sealed release capsule",
            )
            receipt_ref, receipt_raw = _safe_certification_file(
                authority_base,
                authority_bundle["certification_receipt_ref"],
                label="sealed certification receipt",
            )
            _trust_ref, trust_raw = _safe_certification_file(
                authority_base,
                authority_bundle["trust_anchor_ref"],
                label="sealed attestation trust anchor",
            )
            if (
                (authority_base / capsule_ref).resolve() != capsule_path.resolve()
                or _sha256_bytes(capsule_raw)
                != authority_bundle["release_capsule_file_sha256"]
                or _sha256_bytes(receipt_raw)
                != authority_bundle["certification_receipt_file_sha256"]
                or _sha256_bytes(trust_raw)
                != authority_bundle["trust_anchor_file_sha256"]
                or trust_raw.decode("ascii", "strict").strip()
                != trusted_attestation_sha256
            ):
                raise UpgradeLaneError("sealed release authority file binding differs")
            try:
                receipt = json.loads(receipt_raw)
            except (UnicodeDecodeError, ValueError, TypeError) as exc:
                raise UpgradeLaneError("certification receipt is malformed") from exc
            if (
                not isinstance(receipt, dict)
                or receipt.get("capsule_ref") != capsule_ref
                or receipt.get("authority_ref") != authority_path.name
            ):
                raise UpgradeLaneError("certification receipt authority binding differs")
            _certification_receipt_digest(
                receipt,
                package=package,
                registry=registry,
                capsule=capsule,
                gate_output_root=gate_authority_root,
            )

        authority = ReleaseCapsuleAuthority(
            package=package,
            impact_registry=registry,
            source_root=kit_root.resolve(),
            visual_root=visual_authority_root,
            gate_output_root=gate_authority_root,
            verified_attestation_sha256=trusted_attestation_sha256,
        )
        verified_capsule = verify_release_capsule(capsule, authority=authority)
        registry_digest = verify_impact_registry(registry)
    except RunnerError:
        raise
    except (OSError, ValueError, UpgradeLaneError) as exc:
        raise RunnerError(
            "lane_contract_rejected",
            "a package, release capsule or impact registry failed closed validation",
            lane="lane_a",
            surface="release_capsule_or_impact_registry",
            next_action="rebuild and certify the public release artifacts before adoption",
        ) from exc
    schema = package.get("schema_version")
    if schema not in _SUPPORTED_PACKAGES:
        raise RunnerError(
            "unsupported_package_schema",
            "the package schema is not supported by this runner",
            lane="lane_a",
            surface="upgrade_package",
            next_action="certify the package with a supported schema",
        )
    release = package.get("release")
    migration = package.get("migration")
    if not isinstance(release, dict) or not isinstance(migration, dict):
        raise RunnerError("invalid_package_shape", "the package omits release or migration policy")
    package_digest = canonical_sha256(package)
    if capsule.get("package_sha256") != package_digest:
        raise RunnerError(
            "package_capsule_digest_mismatch",
            "the package digest does not match the certified capsule",
            lane="lane_a",
            surface="upgrade_package",
            next_action="use the exact package sealed into the capsule",
        )
    if release.get("source_sha") != capsule.get("source_sha"):
        raise RunnerError(
            "source_capsule_mismatch",
            "the package source subject does not match the certified capsule",
            lane="lane_a",
            surface="portable_source",
            next_action="use one exact package and capsule pair",
        )
    if capsule.get("command_registry_sha256") != canonical_sha256(
        registry.get("gate_catalog")
    ):
        raise RunnerError(
            "command_registry_mismatch",
            "the impact registry command catalog differs from the capsule",
            lane="lane_a",
            surface="command_registry",
            next_action="use the exact versioned registry sealed into the capsule",
        )
    if capsule.get("command_registry") != registry.get("gate_catalog"):
        raise RunnerError(
            "command_registry_payload_mismatch",
            "the capsule and impact registry do not contain the same command registry",
            lane="lane_a",
            surface="command_registry",
            next_action="recertify one exact command registry payload",
        )
    if schema == _TWO_LANE_PACKAGE:
        gate_catalog = registry.get("gate_catalog")
        gate_commands = migration.get("gate_commands")
        gate_policies = migration.get("gate_policies")
        package_impact = migration.get("impact_registry")
        if (
            not isinstance(gate_catalog, list)
            or not isinstance(gate_commands, dict)
            or not isinstance(gate_policies, dict)
            or not isinstance(package_impact, dict)
        ):
            raise RunnerError(
                "package_registry_binding_missing",
                "the v3 package omits executable registry bindings",
                lane="lane_a",
                surface="upgrade_package",
            )
        projection = sorted(
            (
                {
                    "id": gate_id,
                    "class": gate_policies[gate_id]["class"],
                    "command": gate_commands[gate_id],
                }
                for gate_id in gate_commands
            ),
            key=lambda item: item["id"],
        )
        if (
            projection != gate_catalog
            or migration.get("command_registry_sha256") != canonical_sha256(projection)
            or package_impact.get("sha256") != registry_digest
            or package_impact.get("schema_version") != registry.get("schema_version")
        ):
            raise RunnerError(
                "package_registry_binding_mismatch",
                "package commands, policies or impact digest differ from the certified registry",
                lane="lane_a",
                surface="impact_and_command_registry",
                next_action="regenerate the package, registry and capsule as one immutable release",
            )
    if verified_capsule.digest != capsule.get("capsule_sha256") or registry_digest != registry.get(
        "registry_sha256"
    ):
        raise RunnerError("artifact_digest_mismatch", "a sealed artifact digest is stale")
    return package, capsule, registry, verified_capsule


def _verify_capsule(args: argparse.Namespace) -> int:
    """Verify one exact Lane A authority without opening a consumer run."""

    package = _require_v3_cli_package(args.package)
    _validate_package_contract(package)
    if not package_is_pinned(package):
        raise RunnerError(
            "release_not_releasable",
            "the package release is not pinned in a releasable status",
            lane="lane_a",
            surface="release_status",
            next_action=(
                "complete public validation and human review, promote the package status, "
                "then certify the exact merged source subject"
            ),
        )
    package, capsule, registry, verified_capsule = _load_artifacts(
        args.package,
        args.capsule,
        args.impact_registry,
        kit_root=args.kit_root,
        authority_path=args.authority,
        trusted_attestation_sha256=args.trusted_attestation_sha256,
        require_sealed_authority=True,
    )
    summary = {
        "schema_version": "wiki_viva_release_capsule_verification_summary.v1",
        "status": "verified",
        "lane": "lane_a",
        "release_id": capsule["release_id"],
        "source_sha": capsule["source_sha"],
        "capsule_sha256": verified_capsule.digest,
        "package_sha256": canonical_sha256(package),
        "portable_tree_sha256": capsule["portable_tree_sha256"],
        "command_registry_sha256": capsule["command_registry_sha256"],
        "impact_registry_sha256": registry["registry_sha256"],
        "toolchain_sha256": capsule["toolchain_sha256"],
        "visual_manifest_sha256": capsule["visual_manifest_sha256"],
        "attestation_sha256": capsule["attestation_sha256"],
        "human_gate_required": True,
    }
    _require_public_certification_output(
        _json_bytes(summary), gate_id="verify-capsule"
    )
    _emit(summary)
    return 0


def _required_gate_ids(package: Mapping[str, Any]) -> list[str]:
    migration = package.get("migration")
    values = migration.get("required_gates") if isinstance(migration, dict) else None
    if (
        not isinstance(values, list)
        or not values
        or any(not isinstance(value, str) or _GATE_ID_RE.fullmatch(value) is None for value in values)
        or len(values) != len(set(values))
    ):
        raise RunnerError("invalid_required_gates", "migration.required_gates is not exact")
    return list(values)


def _two_lane_selection(
    package: Mapping[str, Any],
    capsule: Mapping[str, Any],
    registry: Mapping[str, Any],
    verified_capsule: VerifiedReleaseCapsule,
    paths: Sequence[str],
    contracts: Sequence[str],
    *,
    consumer_c3_authority: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, str]], list[dict[str, str]]]:
    required = set(_required_gate_ids(package))
    catalog = list(registry["gate_catalog"])
    catalog_ids = {item["id"] for item in catalog}
    if required != catalog_ids:
        raise RunnerError(
            "package_registry_gate_mismatch",
            "the v3 package and impact registry do not declare the same gate set",
            lane="lane_a",
            surface="gate_policy",
            next_action="recertify one package, registry and capsule tuple",
        )
    try:
        selection = select_promotion_gates(
            package,
            registry,
            changed_paths=list(paths),
            changed_contracts=list(contracts),
            consumer_c3_authority=consumer_c3_authority,
        )
    except UpgradeLaneError as exc:
        raise RunnerError(
            "impact_derivation_rejected",
            "the changed path or contract set could not be derived safely",
            surface="impact_registry",
            next_action="correct canonical impact inputs or execute the full Lane A path",
        ) from exc
    certified = {item["id"] for item in capsule["certified_gates"]}
    omissions = [
        {
            "gate_id": gate_id,
            "reason": "verified_upstream_capsule" if gate_id in certified else "not_affected",
            "derivation_sha256": (
                capsule["capsule_sha256"] if gate_id in certified else selection["derivation_sha256"]
            ),
        }
        for gate_id in selection["omitted_gates"]
    ]
    if not selection["requires_lane_a"]:
        try:
            verify_gate_omissions(
                registry,
                selection,
                omissions,
                capsule,
                verified_capsule=verified_capsule,
            )
        except UpgradeLaneError as exc:
            raise RunnerError(
                "gate_omission_unproved",
                "at least one omitted gate lacks capsule or impact proof",
                surface="gate_policy",
                next_action="select the gate or repair its exact derivation",
            ) from exc
    policies = package["migration"].get("gate_policies")
    if not isinstance(policies, Mapping) or set(policies) != required:
        raise RunnerError(
            "invalid_gate_policy_registry",
            "the package gate policy does not cover the exact command registry",
            lane="lane_a",
            surface="gate_policy",
        )
    selected = set(selection["selected_gates"])
    execution_catalog: list[dict[str, Any]] = []
    for item in catalog:
        if item["id"] not in selected:
            continue
        policy = policies.get(item["id"])
        policy = policy if isinstance(policy, dict) else {}
        dependencies = policy.get("depends_on", [])
        if not isinstance(dependencies, list) or any(
            not isinstance(value, str) for value in dependencies
        ):
            raise RunnerError(
                "invalid_gate_dependency_policy",
                "a selected gate has an invalid dependency policy",
                surface=item["id"],
                next_action="repair the versioned package gate policy",
            )
        resource_group = policy.get("resource_group", f"gate_{item['id']}")
        if not isinstance(resource_group, str) or re.fullmatch(
            r"[a-z][a-z0-9_]{1,63}", resource_group
        ) is None:
            raise RunnerError(
                "invalid_gate_resource_policy",
                "a selected gate has an invalid resource group",
                surface=item["id"],
            )
        execution_catalog.append(
            {
                **dict(item),
                "asserts": list(policy.get("asserts", [])),
                "depends_on": sorted(set(dependencies)),
                "resource_group": resource_group,
                "required_for_promotion": bool(
                    policy.get("required_for_promotion", True)
                ),
            }
        )
    return selection, omissions, execution_catalog


def _parse_command(command: str, *, kit_root: Path) -> list[str]:
    if _CONTROL_TOKEN_RE.search(command):
        raise RunnerError("unsafe_gate_command", "a gate command contains shell control syntax")
    try:
        argv = shlex.split(command, posix=True)
    except ValueError as exc:
        raise RunnerError("unsafe_gate_command", "a gate command cannot be tokenized safely") from exc
    if not argv or any(token in _SHELL_TOKENS for token in argv):
        raise RunnerError("unsafe_gate_command", "a gate command requires a forbidden shell")
    normalized: list[str] = []
    for token in argv:
        if token == "$WIKI_VIVA_KIT_ROOT":
            normalized.append(str(kit_root.resolve()))
        elif "$" in token:
            raise RunnerError("unsafe_gate_variable", "a gate command uses an unbound variable")
        else:
            normalized.append(token)
    if normalized[0] in {"python", "python3"}:
        # The registry binds the reviewed, portable command spelling while the
        # runner closure binds how that spelling is executed.  Resolve both
        # accepted Python spellings through the same public alias used by the
        # toolchain probe so a divergent PATH ``python3`` cannot execute gates
        # under a different dependency set than the one sealed in the capsule.
        normalized[0] = _active_python_alias()
    return normalized


def _plan_digest(plan: Mapping[str, Any]) -> str:
    unsigned = dict(plan)
    unsigned.pop("plan_sha256", None)
    return canonical_sha256(unsigned)


def _verify_plan_digest(plan: Mapping[str, Any]) -> str:
    expected_fields = {
        "schema_version",
        "runner_version",
        "status",
        "mode",
        "package_schema_version",
        "release_id",
        "capsule_sha256",
        "impact_registry_sha256",
        "consumer_c3_authority",
        "consumer_c3_authority_sha256",
        "identity",
        "boundary_commits",
        "boundaries",
        "boundary_execution",
        "preflight",
        "mutation",
        "impact_inputs",
        "selection",
        "omitted_gates",
        "gate_catalog",
        "conceptual_diff",
        "acceptance_budget",
        "acceptance_anchor",
        "plan_sha256",
    }
    mutation = plan.get("mutation")
    mutation_strategy = (
        mutation.get("strategy") if isinstance(mutation, Mapping) else None
    )
    if mutation_strategy == "runner_owned_completed":
        expected_fields.add("pre_mutation_plan_sha256")
    elif mutation_strategy not in {None, "runner_owned"}:
        raise RunnerError(
            "invalid_plan_shape",
            "the adoption plan mutation strategy is invalid",
            surface="adoption_plan",
        )
    if set(plan) != expected_fields:
        raise RunnerError(
            "invalid_plan_shape",
            "the adoption plan has unknown or missing fields",
            surface="adoption_plan",
        )
    if plan.get("schema_version") != PLAN_SCHEMA_VERSION:
        raise RunnerError("unsupported_plan_schema", "the adoption plan schema is unsupported")
    if (
        plan.get("runner_version") != RUNNER_VERSION
        or plan.get("mode") != "canary"
        or plan.get("package_schema_version") != _TWO_LANE_PACKAGE
        or plan.get("status") not in {"ready", "ready_to_mutate", "requires_lane_a"}
        or not isinstance(plan.get("release_id"), str)
        or not plan["release_id"]
    ):
        raise RunnerError(
            "invalid_plan_metadata",
            "the adoption plan runner, mode, package or release metadata is invalid",
            surface="adoption_plan",
        )
    digest = _plan_digest(plan)
    if plan.get("plan_sha256") != digest:
        raise RunnerError(
            "plan_digest_mismatch",
            "the adoption plan was modified after it was sealed",
            surface="adoption_plan",
            next_action="discard it and generate a new read-only plan",
        )
    return digest


def _validate_plan_presentation(plan: Mapping[str, Any]) -> None:
    """Recompute the exact status and conceptual diff shown before mutation."""

    impact = plan.get("impact_inputs")
    selection = plan.get("selection")
    boundaries = plan.get("boundaries")
    mutation = plan.get("mutation")
    if (
        not isinstance(impact, Mapping)
        or set(impact) != {"changed_paths", "changed_contracts"}
        or not isinstance(selection, Mapping)
        or not isinstance(boundaries, Mapping)
        or set(boundaries) != {"C1", "C2", "C3"}
        or any(not isinstance(boundaries[key], list) for key in boundaries)
    ):
        raise RunnerError(
            "invalid_plan_presentation",
            "the adoption plan cannot derive its conceptual diff",
            surface="conceptual_diff",
        )
    changed_paths = impact.get("changed_paths")
    changed_contracts = impact.get("changed_contracts")
    if (
        not isinstance(changed_paths, list)
        or changed_paths != sorted(set(changed_paths))
        or any(not isinstance(value, str) for value in changed_paths)
        or not isinstance(changed_contracts, list)
        or changed_contracts != sorted(set(changed_contracts))
        or any(not isinstance(value, str) for value in changed_contracts)
    ):
        raise RunnerError(
            "invalid_plan_presentation",
            "the adoption plan impact inputs are not canonical",
            surface="conceptual_diff",
        )
    required_selection = {
        "matched_surfaces",
        "unknown_paths",
        "unknown_contracts",
        "selected_gates",
        "omitted_gates",
        "escalation",
        "requires_lane_a",
    }
    if not required_selection.issubset(selection):
        raise RunnerError(
            "invalid_plan_presentation",
            "the adoption plan selection cannot derive its conceptual diff",
            surface="conceptual_diff",
        )
    strategy = mutation.get("strategy") if isinstance(mutation, Mapping) else None
    if strategy == "runner_owned":
        prospective = mutation.get("c1_prospective_paths")
        if not isinstance(prospective, list):
            raise RunnerError(
                "invalid_plan_presentation",
                "the pre-mutation C1 projection is incomplete",
                surface="conceptual_diff",
            )
        boundary_counts = {
            "C1": len(prospective),
            "C2": 0,
            "C3": len(changed_paths),
        }
    else:
        boundary_counts = {key: len(boundaries[key]) for key in ("C1", "C2", "C3")}
    expected_diff = {
        "boundary_file_counts": boundary_counts,
        "changed_path_count": len(changed_paths),
        "changed_contract_count": len(changed_contracts),
        "matched_surfaces": selection["matched_surfaces"],
        "unknown_path_count": len(selection["unknown_paths"]),
        "unknown_contract_count": len(selection["unknown_contracts"]),
        "selected_gate_count": len(selection["selected_gates"]),
        "omitted_gate_count": len(selection["omitted_gates"]),
        "escalation": selection["escalation"],
    }
    expected_status = (
        "requires_lane_a"
        if selection["requires_lane_a"]
        else "ready_to_mutate"
        if strategy == "runner_owned"
        else "ready"
    )
    if plan.get("conceptual_diff") != expected_diff or plan.get("status") != expected_status:
        raise RunnerError(
            "stale_or_forged_conceptual_diff",
            "the plan status or conceptual diff cannot be reproduced",
            surface="conceptual_diff",
            next_action="generate a new read-only plan before mutation",
        )


def _acceptance_attempt_identity(plan: Mapping[str, Any]) -> str:
    """Derive the immutable plan attempt independently of its clock/evidence."""

    required = {
        "capsule_sha256",
        "impact_registry_sha256",
        "identity",
        "boundary_commits",
        "impact_inputs",
        "mutation",
        "consumer_c3_authority_sha256",
        "preflight",
        "boundary_execution",
    }
    if not required.issubset(plan):
        raise RunnerError(
            "invalid_acceptance_anchor",
            "the plan lacks fields required for its acceptance attempt identity",
            surface="acceptance_budget",
        )
    return canonical_sha256(
        {
            "schema_version": "wiki_viva_upgrade_acceptance_attempt.v2",
            "capsule_sha256": plan["capsule_sha256"],
            "impact_registry_sha256": plan["impact_registry_sha256"],
            "identity": plan["identity"],
            "boundary_commits": plan["boundary_commits"],
            "impact_inputs": plan["impact_inputs"],
            "mutation": plan["mutation"],
            "consumer_c3_authority_sha256": plan[
                "consumer_c3_authority_sha256"
            ],
            "preflight_sha256": canonical_sha256(plan["preflight"]),
            "boundary_execution_sha256": canonical_sha256(
                plan["boundary_execution"]
            ),
        }
    )


def _acceptance_anchor_path(plan_path: Path, attempt_identity_sha256: str) -> Path:
    if _SHA256_RE.fullmatch(attempt_identity_sha256) is None:
        raise RunnerError(
            "invalid_acceptance_anchor",
            "the acceptance attempt identity is not a SHA-256 digest",
            surface="acceptance_budget",
        )
    return plan_path.parent / f"acceptance-anchor-{attempt_identity_sha256}.json"


def _validate_acceptance_anchor_payload(
    payload: object, *, expected_attempt_identity_sha256: str
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise RunnerError(
            "invalid_acceptance_anchor",
            "the acceptance clock anchor is malformed",
            surface="acceptance_budget",
        )
    anchor = dict(payload)
    if set(anchor) != {
        "schema_version",
        "authority",
        "attempt_identity_sha256",
        "plan_started_at",
        "anchor_sha256",
    } or anchor.get("schema_version") != "wiki_viva_upgrade_acceptance_anchor.v1":
        raise RunnerError(
            "invalid_acceptance_anchor",
            "the acceptance clock anchor contract is incomplete",
            surface="acceptance_budget",
        )
    if anchor.get("authority") != {
        "kind": "external_sha256",
        "id": "wiki_upgrade_plan_first_write",
    } or anchor.get("attempt_identity_sha256") != expected_attempt_identity_sha256:
        raise RunnerError(
            "stale_acceptance_anchor",
            "the acceptance clock anchor belongs to another migration attempt",
            surface="acceptance_budget",
        )
    _acceptance_timestamp_microseconds(anchor.get("plan_started_at"))
    unsigned = dict(anchor)
    claimed = unsigned.pop("anchor_sha256")
    if _SHA256_RE.fullmatch(str(claimed)) is None or claimed != canonical_sha256(unsigned):
        raise RunnerError(
            "stale_acceptance_anchor",
            "the acceptance clock anchor digest is stale",
            surface="acceptance_budget",
        )
    return anchor


def _load_or_create_acceptance_anchor(
    *,
    consumer: Path,
    plan_path: Path,
    attempt_identity_sha256: str,
    invocation_started_unix_ns: int,
) -> tuple[dict[str, Any], str]:
    path = _require_ignored_output(
        consumer, _acceptance_anchor_path(plan_path, attempt_identity_sha256)
    )
    started_at = _acceptance_timestamp(invocation_started_unix_ns)
    seed: dict[str, Any] = {
        "schema_version": "wiki_viva_upgrade_acceptance_anchor.v1",
        "authority": {
            "kind": "external_sha256",
            "id": "wiki_upgrade_plan_first_write",
        },
        "attempt_identity_sha256": attempt_identity_sha256,
        "plan_started_at": started_at,
    }
    seed["anchor_sha256"] = canonical_sha256(seed)
    raw = _json_bytes(seed)
    if not _atomic_create_once(path, raw):
        raw = _read_exact_private_file(path, label="acceptance clock anchor")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, ValueError, TypeError) as exc:
        raise RunnerError(
            "invalid_acceptance_anchor",
            "the acceptance clock anchor is not valid UTF-8 JSON",
            surface="acceptance_budget",
        ) from exc
    anchor = _validate_acceptance_anchor_payload(
        payload, expected_attempt_identity_sha256=attempt_identity_sha256
    )
    return anchor, _sha256_bytes(raw)


def _verify_acceptance_anchor(
    *,
    plan: Mapping[str, Any],
    plan_path: Path,
    consumer: Path,
    trusted_file_sha256: str,
) -> dict[str, Any]:
    reference = plan.get("acceptance_anchor")
    expected_attempt = _acceptance_attempt_identity(plan)
    if not isinstance(reference, Mapping) or dict(reference) != {
        "schema_version": "wiki_viva_upgrade_acceptance_anchor_reference.v1",
        "attempt_identity_sha256": expected_attempt,
        "anchor_sha256": reference.get("anchor_sha256") if isinstance(reference, Mapping) else None,
        "file_sha256": reference.get("file_sha256") if isinstance(reference, Mapping) else None,
    }:
        raise RunnerError(
            "invalid_acceptance_anchor",
            "the plan acceptance anchor reference is incomplete or stale",
            surface="acceptance_budget",
        )
    if (
        _SHA256_RE.fullmatch(str(trusted_file_sha256)) is None
        or reference.get("file_sha256") != trusted_file_sha256
    ):
        raise RunnerError(
            "untrusted_acceptance_anchor",
            "the plan clock lacks its out-of-band SHA-256 trust anchor",
            surface="acceptance_budget",
            next_action="use the exact digest emitted by the original plan command",
        )
    path = _require_ignored_output(
        consumer, _acceptance_anchor_path(plan_path, expected_attempt)
    )
    raw = _read_exact_private_file(path, label="acceptance clock anchor")
    if _sha256_bytes(raw) != trusted_file_sha256:
        raise RunnerError(
            "untrusted_acceptance_anchor",
            "the acceptance clock anchor bytes differ from external authority",
            surface="acceptance_budget",
        )
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, ValueError, TypeError) as exc:
        raise RunnerError(
            "invalid_acceptance_anchor",
            "the acceptance clock anchor is not valid UTF-8 JSON",
            surface="acceptance_budget",
        ) from exc
    anchor = _validate_acceptance_anchor_payload(
        payload, expected_attempt_identity_sha256=expected_attempt
    )
    if (
        reference.get("anchor_sha256") != anchor["anchor_sha256"]
        or plan.get("acceptance_budget", {}).get("plan_started_at")
        != anchor["plan_started_at"]
    ):
        raise RunnerError(
            "stale_acceptance_anchor",
            "the plan clock was reset or detached from its first-write anchor",
            surface="acceptance_budget",
        )
    return anchor


def _preflight_commands(
    package: Mapping[str, Any],
    explicit_specs: Sequence[str],
    *,
    kit: Path,
) -> list[dict[str, str]]:
    preflight = package.get("preflight")
    required = preflight.get("required_gates") if isinstance(preflight, dict) else None
    if not isinstance(required, list) or not required:
        raise RunnerError(
            "invalid_preflight_contract",
            "the upgrade package has no exact read-only preflight gate set",
            lane="lane_a",
            surface="preflight",
        )
    required_ids = [str(value) for value in required]
    mapping_value = preflight.get("gate_mapping") if isinstance(preflight, dict) else None
    if package.get("schema_version") == _TWO_LANE_PACKAGE:
        if (
            not isinstance(mapping_value, Mapping)
            or set(str(key) for key in mapping_value) != set(required_ids)
            or any(not isinstance(value, str) for value in mapping_value.values())
        ):
            raise RunnerError(
                "invalid_preflight_gate_mapping",
                "the v3 package does not map every preflight assertion to one registered gate",
                lane="lane_a",
                surface="preflight",
                next_action="repair and recertify the versioned upgrade package",
            )
        gate_mapping = {str(key): str(value) for key, value in mapping_value.items()}
    else:
        gate_mapping = {gate_id: gate_id for gate_id in required_ids}
    explicit = {
        item["id"]: item["command"]
        for item in _named_commands(explicit_specs, kit=kit, label="preflight")
    }
    if not set(explicit).issubset(set(required_ids)):
        raise RunnerError(
            "unexpected_preflight_command",
            "a supplied preflight command is not required by the package",
            surface="preflight",
        )
    migration = package.get("migration")
    registered = migration.get("gate_commands") if isinstance(migration, dict) else {}
    registered = registered if isinstance(registered, dict) else {}
    commands: list[dict[str, str]] = []
    for gate_id in required_ids:
        command_id = gate_mapping[gate_id]
        package_command = registered.get(command_id)
        command = explicit.get(gate_id, package_command)
        if (
            package.get("schema_version") == _TWO_LANE_PACKAGE
            and gate_id in explicit
            and explicit[gate_id] != package_command
        ):
            raise RunnerError(
                "preflight_command_contract_mismatch",
                "a supplied preflight command differs from its package-mapped gate command",
                surface=gate_id,
                contract="wiki_viva_upgrade_package.v3",
                next_action="remove the override and use the package gate mapping",
            )
        if not isinstance(command, str) or not command.strip():
            raise RunnerError(
                "missing_preflight_command",
                "a package-required preflight gate has no runner-executable command",
                surface=str(gate_id),
                next_action="repair the package gate mapping and command registry",
            )
        _parse_command(command, kit_root=kit)
        commands.append(
            {"id": str(gate_id), "command_id": command_id, "command": command}
        )
    return commands


def _execute_preflight(
    *,
    package: Mapping[str, Any],
    explicit_specs: Sequence[str],
    consumer: Path,
    kit: Path,
    b0: str,
    output_root: Path,
) -> dict[str, Any]:
    commands = _preflight_commands(package, explicit_specs, kit=kit)
    key = canonical_sha256(
        {
            "consumer_B0": b0,
            "package_sha256": canonical_sha256(package),
            "commands": commands,
        }
    )[:16]
    evidence_root = output_root / f"preflight-{key}"
    results: list[dict[str, Any]] = []
    for item in commands:
        if _head(consumer) != b0:
            raise RunnerError(
                "preflight_subject_changed",
                "preflight no longer runs against the exact B0 subject",
                surface=item["id"],
            )
        log = _require_ignored_output(consumer, evidence_root / f"{item['id']}.log")
        try:
            result = subprocess.run(
                _parse_command(item["command"], kit_root=kit),
                cwd=consumer,
                env=_gate_environment(
                    evidence_root,
                    kit,
                    item["id"],
                    subject_sha=b0,
                    public_release_sha=str(package["release"]["source_sha"]),
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=1200,
            )
        except subprocess.TimeoutExpired as exc:
            output = exc.output if isinstance(exc.output, bytes) else b""
            _atomic_write(log, output)
            _require_clean(consumer)
            raise RunnerError(
                "preflight_gate_timeout",
                "a required read-only B0 preflight gate exceeded its bounded runtime",
                surface=item["id"],
                next_action="repair the exact B0 gate runtime before planning adoption",
            ) from exc
        _atomic_write(log, result.stdout)
        _require_clean(consumer)
        if _head(consumer) != b0 or result.returncode != 0:
            raise RunnerError(
                "preflight_gate_failed",
                "a required read-only B0 preflight gate failed or changed the consumer",
                surface=item["id"],
                next_action="repair the exact B0 consumer before planning adoption",
            )
        _absolute, output_ref = _repo_relative(consumer, log)
        results.append(
            {
                "id": item["id"],
                "command_id": item["command_id"],
                "provenance": "executed",
                "status": "passed",
                "exit_code": 0,
                "subject_sha": b0,
                "command": item["command"],
                "command_sha256": _sha256_bytes(item["command"].encode("utf-8")),
                "output_sha256": _sha256_bytes(result.stdout),
                "output_ref": output_ref,
                "output_bytes": len(result.stdout),
            }
        )
    payload = {
        "schema_version": "wiki_viva_upgrade_preflight_execution.v1",
        "subject_sha": b0,
        "results": results,
    }
    return {**payload, "preflight_sha256": canonical_sha256(payload)}


def _verify_preflight(
    plan: Mapping[str, Any],
    *,
    package: Mapping[str, Any],
    consumer: Path,
    kit: Path,
) -> None:
    preflight = plan.get("preflight")
    if not isinstance(preflight, dict):
        raise RunnerError("missing_preflight_evidence", "the plan omits B0 preflight evidence")
    if set(preflight) != {
        "schema_version",
        "subject_sha",
        "results",
        "preflight_sha256",
    }:
        raise RunnerError(
            "stale_preflight_evidence",
            "the B0 preflight evidence shape is not exact",
        )
    unsigned = dict(preflight)
    claimed = unsigned.pop("preflight_sha256", None)
    if claimed != canonical_sha256(unsigned):
        raise RunnerError("stale_preflight_evidence", "the B0 preflight digest is stale")
    package_preflight = package.get("preflight")
    required = (
        package_preflight.get("required_gates")
        if isinstance(package_preflight, dict)
        else None
    )
    migration = package.get("migration")
    registered = migration.get("gate_commands") if isinstance(migration, dict) else {}
    registered = registered if isinstance(registered, dict) else {}
    mapping_value = (
        package_preflight.get("gate_mapping")
        if isinstance(package_preflight, dict)
        else None
    )
    if package.get("schema_version") == _TWO_LANE_PACKAGE:
        if not isinstance(mapping_value, Mapping):
            raise RunnerError(
                "stale_preflight_evidence",
                "the package preflight mapping is missing",
            )
        gate_mapping = {str(key): str(value) for key, value in mapping_value.items()}
    else:
        gate_mapping = {str(value): str(value) for value in required or []}
    results = preflight.get("results")
    if (
        preflight.get("schema_version") != "wiki_viva_upgrade_preflight_execution.v1"
        or preflight.get("subject_sha") != plan["identity"]["consumer_B0"]
        or not isinstance(results, list)
        or not isinstance(required, list)
        or {item.get("id") for item in results if isinstance(item, dict)} != set(required)
    ):
        raise RunnerError("stale_preflight_evidence", "the B0 preflight identity is incomplete")
    for result in results:
        if not isinstance(result, dict) or set(result) != {
            "id",
            "command_id",
            "provenance",
            "status",
            "exit_code",
            "subject_sha",
            "command",
            "command_sha256",
            "output_sha256",
            "output_ref",
            "output_bytes",
        }:
            raise RunnerError(
                "stale_preflight_evidence",
                "a B0 preflight result has unknown or missing fields",
            )
        gate_id = result["id"]
        command_id = result.get("command_id")
        output_ref = result.get("output_ref")
        command = result.get("command")
        if (
            result.get("provenance") != "executed"
            or result.get("status") != "passed"
            or result.get("exit_code") != 0
            or result.get("subject_sha") != plan["identity"]["consumer_B0"]
            or command_id != gate_mapping.get(gate_id)
            or not isinstance(command, str)
            or (
                package.get("schema_version") == _TWO_LANE_PACKAGE
                and command != registered.get(command_id)
            )
            or (
                package.get("schema_version") != _TWO_LANE_PACKAGE
                and command_id in registered
                and command != registered[command_id]
            )
            or result.get("command_sha256")
            != _sha256_bytes(command.encode("utf-8"))
            or not isinstance(output_ref, str)
        ):
            raise RunnerError("stale_preflight_evidence", "a B0 preflight result is stale")
        _parse_command(command, kit_root=kit)
        output = _require_ignored_output(consumer, Path(output_ref))
        if (
            not output.is_file()
            or output.stat().st_size != result.get("output_bytes")
            or _sha256_bytes(output.read_bytes()) != result.get("output_sha256")
        ):
            raise RunnerError("stale_preflight_output", "a B0 preflight log is missing or stale")


def _worktree_changed_paths(consumer: Path) -> list[str]:
    modified = _git(consumer, ["diff", "--name-only", "-z", "--"]).stdout
    untracked = _git(
        consumer, ["ls-files", "--others", "--exclude-standard", "-z"]
    ).stdout
    return sorted(
        {
            item.decode("utf-8", "strict")
            for item in [*modified.split(b"\0"), *untracked.split(b"\0")]
            if item
        }
    )


def _materialize_mutation_plan(
    *,
    preplan: Mapping[str, Any],
    plan_path: Path,
    package: Mapping[str, Any],
    capsule: Mapping[str, Any],
    registry: Mapping[str, Any],
    verified_capsule: VerifiedReleaseCapsule,
    consumer: Path,
    kit: Path,
    resume: bool,
) -> dict[str, Any]:
    execution_path = plan_path.parent / f"execution-plan-{preplan['plan_sha256'][:16]}.json"
    mutation_state_path = plan_path.parent / f"mutation-state-{preplan['plan_sha256'][:16]}.json"

    def require_execution_lineage(execution: Mapping[str, Any]) -> None:
        pre_mutation = preplan.get("mutation")
        completed_mutation = execution.get("mutation")
        commits = execution.get("boundary_commits")
        boundaries = execution.get("boundaries")
        impact = execution.get("impact_inputs")
        pre_impact = preplan.get("impact_inputs")
        if (
            not isinstance(pre_mutation, Mapping)
            or pre_mutation.get("strategy") != "runner_owned"
            or not isinstance(completed_mutation, Mapping)
            or completed_mutation.get("strategy") != "runner_owned_completed"
            or set(completed_mutation)
            != {*pre_mutation, "c1_commit", "c2_commit", "c3_commit"}
            or any(
                completed_mutation.get(key) != value
                for key, value in pre_mutation.items()
                if key != "strategy"
            )
            or not isinstance(commits, Mapping)
            or set(commits) != {"B0", "C1", "C2", "C3"}
            or completed_mutation.get("c1_commit") != commits.get("C1")
            or completed_mutation.get("c2_commit") != commits.get("C2")
            or completed_mutation.get("c3_commit") != commits.get("C3")
            or execution.get("preflight") != preplan.get("preflight")
            or not isinstance(boundaries, Mapping)
            or set(boundaries) != {"C1", "C2", "C3"}
            or not isinstance(boundaries.get("C3"), list)
            or not isinstance(impact, Mapping)
            or set(impact) != {"changed_paths", "changed_contracts"}
            or not isinstance(pre_impact, Mapping)
            or set(pre_impact) != {"changed_paths", "changed_contracts"}
        ):
            raise RunnerError(
                "stale_execution_plan_lineage",
                "the materialized execution plan no longer derives from its anchored pre-mutation plan",
                surface="impact_derivation",
            )
        c3_paths = {
            item.get("path")
            for item in boundaries["C3"]
            if isinstance(item, Mapping) and isinstance(item.get("path"), str)
        }
        if len(c3_paths) != len(boundaries["C3"]):
            raise RunnerError(
                "stale_execution_plan_lineage",
                "the materialized execution plan has invalid C3 impact paths",
                surface="impact_derivation",
            )
        expected_paths = sorted(set(pre_impact["changed_paths"]) | c3_paths)
        expected_contracts = sorted(set(pre_impact["changed_contracts"]))
        if impact.get("changed_paths") != expected_paths or impact.get(
            "changed_contracts"
        ) != expected_contracts:
            raise RunnerError(
                "stale_execution_plan_lineage",
                "the execution plan omits or invents an anchored C3 path or contract",
                surface="impact_derivation",
                next_action="discard the execution plan and resume from the exact anchored pre-mutation plan",
            )

    if execution_path.is_file():
        if not resume:
            raise RunnerError(
                "resume_required",
                "this pre-mutation plan already produced an execution plan",
                surface="resume_state",
                next_action="use adopt --resume with the unchanged pre-mutation plan",
            )
        try:
            execution = json.loads(execution_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise RunnerError("invalid_execution_plan", "the materialized execution plan is malformed") from exc
        _verify_plan_digest(execution)
        if (
            execution.get("pre_mutation_plan_sha256") != preplan["plan_sha256"]
            or execution.get("acceptance_anchor") != preplan.get("acceptance_anchor")
            or execution.get("acceptance_budget") != preplan.get("acceptance_budget")
        ):
            raise RunnerError(
                "stale_execution_plan_anchor",
                "the materialized execution plan is detached from its anchored pre-mutation plan",
                surface="acceptance_budget",
                next_action="discard the stale execution evidence and restart from the exact anchored plan",
            )
        require_execution_lineage(execution)
        replay_commands = preplan["mutation"]["c2_commands"]
        replay_evidence_path = _require_ignored_output(
            consumer,
            plan_path.parent
            / f"c2-resume-replay-{execution['plan_sha256'][:16]}.log",
        )
        _boundary_execution(
            [f"{item['id']}::{item['command']}" for item in replay_commands],
            execution["boundaries"],
            consumer=consumer,
            kit=kit,
            commits=execution["boundary_commits"],
            evidence_path=replay_evidence_path,
        )
        return execution
    b0 = preplan["identity"]["consumer_B0"]
    consumer_c3_authority = preplan.get("consumer_c3_authority")
    if not isinstance(consumer_c3_authority, Mapping):
        raise RunnerError(
            "missing_consumer_c3_authority",
            "the pre-mutation plan omits its B0-derived C3 authority",
            surface="C3",
        )
    try:
        consumer_c3_authority_sha256 = verify_consumer_c3_authority(
            consumer_c3_authority,
            consumer_root=consumer,
            consumer_B0=b0,
            package=package,
        )
    except UpgradeLaneError as exc:
        raise RunnerError(
            "stale_consumer_c3_authority",
            "the pre-mutation C3 authority differs from the exact B0 config",
            surface="C3",
        ) from exc
    if (
        preplan.get("consumer_c3_authority_sha256")
        != consumer_c3_authority_sha256
    ):
        raise RunnerError(
            "stale_consumer_c3_authority",
            "the pre-mutation C3 authority digest is stale",
            surface="C3",
        )
    mutation = preplan.get("mutation")
    if not isinstance(mutation, dict) or mutation.get("strategy") != "runner_owned":
        raise RunnerError("invalid_mutation_plan", "the plan has no runner-owned mutation contract")
    mutation_identity = canonical_sha256(
        {
            "plan_sha256": preplan["plan_sha256"],
            "consumer_B0": b0,
            "capsule_sha256": preplan["capsule_sha256"],
            "mutation": mutation,
        }
    )
    if mutation_state_path.is_file():
        if not resume:
            raise RunnerError(
                "resume_required",
                "runner-owned boundary materialization already has resumable state",
                surface="resume_state",
                next_action="rerun adopt --resume with the unchanged plan",
            )
        try:
            mutation_state = json.loads(mutation_state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise RunnerError(
                "invalid_mutation_resume_state",
                "runner-owned boundary state is malformed",
                surface="resume_state",
            ) from exc
        mutation_state_fields = {
            "schema_version",
            "mutation_identity_sha256",
            "consumer_B0",
            "consumer_c3_authority_sha256",
            "phase",
            "commits",
        }
        phase = mutation_state.get("phase") if isinstance(mutation_state, dict) else None
        expected_commit_keys = {
            "B0": {"B0"},
            "C1_prepared": {"B0", "C1"},
            "C1": {"B0", "C1"},
            "C2_prepared": {"B0", "C1", "C2"},
            "C2": {"B0", "C1", "C2"},
            "C3_prepared": {"B0", "C1", "C2", "C3"},
            "C3": {"B0", "C1", "C2", "C3"},
        }.get(str(phase))
        commits_value = (
            mutation_state.get("commits")
            if isinstance(mutation_state, dict)
            else None
        )
        if (
            not isinstance(mutation_state, dict)
            or set(mutation_state) != mutation_state_fields
            or mutation_state.get("schema_version")
            != "wiki_viva_upgrade_mutation_state.v2"
            or mutation_state.get("mutation_identity_sha256") != mutation_identity
            or mutation_state.get("consumer_B0") != b0
            or mutation_state.get("consumer_c3_authority_sha256")
            != consumer_c3_authority_sha256
            or expected_commit_keys is None
            or not isinstance(commits_value, dict)
            or set(commits_value) != expected_commit_keys
            or commits_value.get("B0") != b0
            or any(
                not isinstance(value, str)
                or re.fullmatch(r"[0-9a-f]{40}", value) is None
                for value in commits_value.values()
            )
        ):
            raise RunnerError(
                "stale_mutation_resume_state",
                "runner-owned boundary state belongs to another plan or subject",
                surface="resume_state",
            )
    else:
        _require_clean(consumer)
        if _head(consumer) != b0:
            raise RunnerError(
                "mutation_not_at_b0",
                "runner-owned adoption must start from the exact clean B0",
                surface="consumer_B0",
                next_action="check out B0 and rerun adopt without altering the plan",
            )
        mutation_state = {
            "schema_version": "wiki_viva_upgrade_mutation_state.v2",
            "mutation_identity_sha256": mutation_identity,
            "consumer_B0": b0,
            "consumer_c3_authority_sha256": consumer_c3_authority_sha256,
            "phase": "B0",
            "commits": {"B0": b0},
        }
        _atomic_write(mutation_state_path, _json_bytes(mutation_state))
    if mutation_state["phase"] == "C1_prepared":
        _advance_prepared_phase(
            consumer=consumer,
            state=mutation_state,
            state_path=mutation_state_path,
            target_phase="C1",
            base_sha=b0,
        )
    if mutation_state["phase"] == "C2_prepared":
        _advance_prepared_phase(
            consumer=consumer,
            state=mutation_state,
            state_path=mutation_state_path,
            target_phase="C2",
            base_sha=str(mutation_state["commits"].get("C1") or ""),
        )
    if mutation_state["phase"] == "C3_prepared":
        _advance_prepared_phase(
            consumer=consumer,
            state=mutation_state,
            state_path=mutation_state_path,
            target_phase="C3",
            base_sha=str(mutation_state["commits"].get("C2") or ""),
        )
    operations = _boundary_operations(package)
    portable = package.get("portable_import")
    portable_allow = (
        list(portable.get("allow") or []) if isinstance(portable, Mapping) else []
    )
    portable_block = (
        list(portable.get("block") or []) if isinstance(portable, Mapping) else []
    )
    if package.get("schema_version") == _TWO_LANE_PACKAGE:
        adapter = operations["c3_adapter"]
        if (
            mutation.get("boundary_operations_sha256")
            != operations.get("registry_sha256")
            or mutation.get("c3_adapter_contract") != adapter.get("contract")
            or mutation.get("c3_owned_patterns") != adapter.get("owns_patterns")
            or mutation.get("consumer_c3_authority_sha256")
            != consumer_c3_authority_sha256
        ):
            raise RunnerError(
                "stale_boundary_operations",
                "the plan C2/C3 authority differs from the current certified package",
                surface="boundary_operations",
                next_action="discard the stale plan and compile a new one",
            )
        c2_owned_patterns = [
            pattern
            for generator in operations["c2_generators"]
            for pattern in generator["owns_patterns"]
        ]
        c2_ownership = {
            str(generator["id"]): list(generator["owns_patterns"])
            for generator in operations["c2_generators"]
        }
        configured_c3_patterns = consumer_c3_authority_patterns(
            consumer_c3_authority
        )
        c3_owned_patterns = [
            *list(adapter["owns_patterns"]),
            *configured_c3_patterns,
        ]
        c3_ownership = {
            str(item["id"]): c3_owned_patterns
            for item in mutation.get("c3_commands", [])
        }
    else:
        c2_owned_patterns = list(
            registry["boundary_policy"]["c2_generated_patterns"]
        )
        c3_owned_patterns = list(
            registry["boundary_policy"]["c3_consumer_patterns"]
        )
        c2_ownership = None
        c3_ownership = None
        configured_c3_patterns = []
    entries = _portable_entries(package, kit, capsule["source_sha"])
    projection = {
        path: {"mode": value["mode"], "sha256": value["sha256"]}
        for path, value in sorted(entries.items())
    }
    if canonical_sha256(projection) != mutation.get("c1_projection_sha256"):
        raise RunnerError(
            "stale_c1_projection",
            "the certified portable projection changed after planning",
            surface="C1",
            next_action="generate a new plan for the current capsule",
        )
    if mutation_state["phase"] == "B0":
        if _head(consumer) != b0:
            raise RunnerError(
                "stale_mutation_head",
                "the consumer HEAD differs from the recorded B0 mutation phase",
                surface="C1",
            )
        _require_clean(consumer)
        with _disposable_stage_clone(consumer, b0) as stage:
            c1 = _apply_c1(stage, package, entries)
            if _verify_complete_c1_projection(
                consumer=stage,
                c1=c1,
                package=package,
                source_entries=entries,
            ) != mutation.get("c1_projection_sha256"):
                raise RunnerError(
                    "c1_projection_digest_mismatch",
                    "the materialized C1 projection differs from the read-only plan",
                    surface="C1",
                )
            _fetch_prepared_commit(consumer, stage, c1)
        mutation_state["phase"] = "C1_prepared"
        mutation_state["commits"]["C1"] = c1
        _atomic_write(mutation_state_path, _json_bytes(mutation_state))
        _advance_prepared_phase(
            consumer=consumer,
            state=mutation_state,
            state_path=mutation_state_path,
            target_phase="C1",
            base_sha=b0,
        )
    else:
        c1 = str(mutation_state["commits"].get("C1") or "")
        _commit(consumer, c1, fallback=c1)
        if mutation_state["phase"] == "C1" and _head(consumer) != c1:
            raise RunnerError(
                "stale_mutation_head",
                "the consumer HEAD differs from the recorded C1 mutation phase",
                surface="C1",
            )
        _verify_complete_c1_projection(
            consumer=consumer,
            c1=c1,
            package=package,
            source_entries=entries,
        )

    c2_log = plan_path.parent / f"c2-run-{preplan['plan_sha256'][:16]}.log"
    if mutation_state["phase"] == "C1":
        if _head(consumer) != c1:
            raise RunnerError(
                "stale_mutation_head",
                "the consumer HEAD differs from the recorded C1 mutation phase",
                surface="C2",
            )
        _require_clean(consumer)
        with _disposable_stage_clone(consumer, c1) as stage:
            _run_mutation_commands(
                mutation.get("c2_commands", []),
                consumer=stage,
                kit=kit,
                log_path=c2_log,
                label="C2",
                ownership_by_id=c2_ownership,
            )
            c2_paths = _worktree_changed_paths(stage)
            _require_stage_paths(
                c2_paths,
                c2_owned_patterns,
                label="C2",
            )
            _git(stage, ["add", "-A"])
            c2 = _commit_index(stage, "wiki: regenerated artifacts (C2)")
            _fetch_prepared_commit(consumer, stage, c2)
        mutation_state["phase"] = "C2_prepared"
        mutation_state["commits"]["C2"] = c2
        _atomic_write(mutation_state_path, _json_bytes(mutation_state))
        _advance_prepared_phase(
            consumer=consumer,
            state=mutation_state,
            state_path=mutation_state_path,
            target_phase="C2",
            base_sha=c1,
        )
    else:
        c2 = str(mutation_state["commits"].get("C2") or "")
        _commit(consumer, c2, fallback=c2)
        if mutation_state["phase"] == "C2" and _head(consumer) != c2:
            raise RunnerError(
                "stale_mutation_head",
                "the consumer HEAD differs from the recorded C2 mutation phase",
                surface="C2",
            )

    c3_log = plan_path.parent / f"c3-run-{preplan['plan_sha256'][:16]}.log"
    if mutation_state["phase"] == "C2":
        if _head(consumer) != c2:
            raise RunnerError(
                "stale_mutation_head",
                "the consumer HEAD differs from the recorded C2 mutation phase",
                surface="C3",
            )
        _require_clean(consumer)
        with _disposable_stage_clone(consumer, c2) as stage:
            _run_mutation_commands(
                mutation.get("c3_commands", []),
                consumer=stage,
                kit=kit,
                log_path=c3_log,
                label="C3",
                ownership_by_id=c3_ownership,
            )
            c3_paths = _worktree_changed_paths(stage)
            _require_stage_paths(
                c3_paths,
                c3_owned_patterns,
                label="C3",
                forbidden_patterns=[
                    *portable_allow,
                    *registry["boundary_policy"]["domain_content_patterns"],
                ],
                forbidden_exceptions=[*portable_block, *configured_c3_patterns],
            )
            _git(stage, ["add", "-A"])
            c3 = _commit_index(stage, "wiki: downstream adaptations (C3)")
            _fetch_prepared_commit(consumer, stage, c3)
        mutation_state["phase"] = "C3_prepared"
        mutation_state["commits"]["C3"] = c3
        _atomic_write(mutation_state_path, _json_bytes(mutation_state))
        _advance_prepared_phase(
            consumer=consumer,
            state=mutation_state,
            state_path=mutation_state_path,
            target_phase="C3",
            base_sha=c2,
        )
    else:
        c3 = str(mutation_state["commits"].get("C3") or "")
    _require_clean(consumer)
    if _head(consumer) != c3:
        raise RunnerError(
            "stale_mutation_head",
            "the consumer HEAD differs from the recorded C3 mutation phase",
            surface="C3",
        )

    commits = {"B0": b0, "C1": c1, "C2": c2, "C3": c3}
    _require_ancestry(consumer, [commits[key] for key in ("B0", "C1", "C2", "C3")])
    boundaries = _build_boundaries(
        consumer=consumer,
        kit=kit,
        source_sha=capsule["source_sha"],
        package_sha256=capsule["package_sha256"],
        commits=commits,
        registry=registry,
        package=package,
        consumer_c3_authority=consumer_c3_authority,
    )
    boundary_execution = _boundary_execution(
        [f"{item['id']}::{item['command']}" for item in mutation.get("c2_commands", [])],
        boundaries,
        consumer=consumer,
        kit=kit,
        commits=commits,
        evidence_path=c2_log,
    )
    _bind_c2_generators(boundaries, boundary_execution, package=package)
    validate_boundary_ownership(
        boundaries,
        registry,
        package=package,
        consumer_c3_authority=consumer_c3_authority,
    )
    _validate_declared_boundaries(package, commits, boundaries)

    exact_changed_paths = sorted(
        set(preplan["impact_inputs"]["changed_paths"])
        | {item["path"] for item in boundaries["C3"]}
    )
    exact_changed_contracts = list(preplan["impact_inputs"]["changed_contracts"])
    selection, omissions, gate_catalog = _two_lane_selection(
        package,
        capsule,
        registry,
        verified_capsule,
        exact_changed_paths,
        exact_changed_contracts,
        consumer_c3_authority=consumer_c3_authority,
    )
    execution = json.loads(json.dumps(preplan))
    execution["status"] = "requires_lane_a" if selection["requires_lane_a"] else "ready"
    execution["pre_mutation_plan_sha256"] = preplan["plan_sha256"]
    execution["boundary_commits"] = commits
    execution["boundaries"] = boundaries
    execution["boundary_execution"] = boundary_execution
    execution["impact_inputs"] = {
        "changed_paths": exact_changed_paths,
        "changed_contracts": sorted(set(exact_changed_contracts)),
    }
    execution["selection"] = selection
    execution["omitted_gates"] = omissions
    execution["gate_catalog"] = sorted(gate_catalog, key=lambda item: item["id"])
    execution["identity"]["consumer_C3"] = c3
    execution["mutation"] = {
        **mutation,
        "strategy": "runner_owned_completed",
        "c1_commit": c1,
        "c2_commit": c2,
        "c3_commit": c3,
    }
    execution["conceptual_diff"]["boundary_file_counts"] = {
        key: len(value) for key, value in boundaries.items()
    }
    execution["conceptual_diff"].update(
        {
            "changed_path_count": len(exact_changed_paths),
            "changed_contract_count": len(set(exact_changed_contracts)),
            "matched_surfaces": selection["matched_surfaces"],
            "unknown_path_count": len(selection["unknown_paths"]),
            "unknown_contract_count": len(selection["unknown_contracts"]),
            "selected_gate_count": len(selection["selected_gates"]),
            "omitted_gate_count": len(selection["omitted_gates"]),
            "escalation": selection["escalation"],
        }
    )
    execution.pop("plan_sha256", None)
    execution["plan_sha256"] = _plan_digest(execution)
    _atomic_write(execution_path, _json_bytes(execution))
    if (
        execution.get("pre_mutation_plan_sha256") != preplan["plan_sha256"]
        or execution.get("acceptance_anchor") != preplan.get("acceptance_anchor")
        or execution.get("acceptance_budget") != preplan.get("acceptance_budget")
    ):
        raise RunnerError(
            "stale_execution_plan_anchor",
            "the generated execution plan is detached from its anchored pre-mutation plan",
            surface="acceptance_budget",
        )
    require_execution_lineage(execution)
    return execution


def _plan(args: argparse.Namespace) -> int:
    plan_started_unix_ns = time.time_ns()
    consumer = args.consumer_root.resolve()
    kit = args.kit_root.resolve()
    _require_v3_cli_package(args.package)
    package, capsule, registry, verified_capsule = _load_artifacts(
        args.package,
        args.capsule,
        args.impact_registry,
        kit_root=kit,
        authority_path=args.authority,
        trusted_attestation_sha256=args.trusted_attestation_sha256,
    )
    _require_upgrade_branch(consumer, package)
    _require_clean(consumer)
    target = _require_ignored_output(
        consumer, args.out or Path(".wiki-viva/upgrade/plan.json")
    )
    current = _head(consumer)
    source_sha = str(capsule["source_sha"])
    _commit(kit, source_sha, fallback=source_sha)
    automatic_mutation = not any(
        (args.consumer_c1, args.consumer_c2, args.consumer_c3)
    )
    b0 = _commit(consumer, args.consumer_b0, fallback=current)
    try:
        consumer_c3_authority = consumer_c3_authority_from_git(
            consumer, b0, package
        )
        consumer_c3_authority_sha256 = str(
            consumer_c3_authority["authority_sha256"]
        )
    except UpgradeLaneError as exc:
        raise RunnerError(
            "invalid_consumer_c3_authority",
            "the exact B0 config cannot derive the fail-closed C3 authority",
            surface="C3",
            next_action="repair wiki.config.yaml at B0 and generate a new plan",
        ) from exc
    preflight_execution = _execute_preflight(
        package=package,
        explicit_specs=args.preflight_command,
        consumer=consumer,
        kit=kit,
        b0=b0,
        output_root=target.parent,
    )
    mutation: dict[str, Any] | None = None
    if automatic_mutation:
        if current != b0:
            raise RunnerError(
                "current_b0_mismatch",
                "planning must run from the clean pre-mutation B0 subject",
                surface="consumer_B0",
                next_action="check out B0 and generate the read-only plan again",
            )
        entries = _portable_entries(package, kit, source_sha)
        projection = {
            path: {"mode": value["mode"], "sha256": value["sha256"]}
            for path, value in sorted(entries.items())
        }
        prospective_c1 = _prospective_c1_paths(consumer, package, entries)
        c2_commands = _c2_commands_for_plan(
            package, args.c2_generator_command, kit=kit
        )
        c3_commands = _c3_commands_for_plan(
            package, args.c3_adapter_command, kit=kit
        )
        operations = _boundary_operations(package)
        c3_adapter = (
            operations.get("c3_adapter")
            if isinstance(operations.get("c3_adapter"), Mapping)
            else {}
        )
        commits = {"B0": b0, "C1": b0, "C2": b0, "C3": b0}
        boundaries = {"C1": [], "C2": [], "C3": []}
        boundary_execution = {
            "schema_version": "wiki_viva_boundary_execution.v1",
            "C2": [],
        }
        mutation = {
            "strategy": "runner_owned",
            "c1_projection_sha256": canonical_sha256(projection),
            "c1_prospective_paths": prospective_c1,
            "c2_commands": c2_commands,
            "c3_commands": c3_commands,
            "boundary_operations_sha256": operations.get("registry_sha256"),
            "c3_adapter_contract": c3_adapter.get("contract"),
            "c3_owned_patterns": list(c3_adapter.get("owns_patterns") or []),
            "consumer_c3_authority_sha256": consumer_c3_authority_sha256,
        }
    else:
        commits = {
            "B0": b0,
            "C1": _commit(consumer, args.consumer_c1, fallback=b0),
            "C2": _commit(consumer, args.consumer_c2, fallback=args.consumer_c1 or b0),
            "C3": _commit(consumer, args.consumer_c3, fallback=current),
        }
        if current != commits["B0"]:
            raise RunnerError(
                "current_b0_mismatch",
                "planning an existing chain must still run from clean B0",
                surface="consumer_B0",
                next_action="check out B0, generate the plan, then check out C3 for adopt",
            )
        _require_ancestry(
            consumer, [commits[key] for key in ("B0", "C1", "C2", "C3")]
        )
        boundaries = _build_boundaries(
            consumer=consumer,
            kit=kit,
            source_sha=source_sha,
            package_sha256=capsule["package_sha256"],
            commits=commits,
            registry=registry,
            package=package,
            consumer_c3_authority=consumer_c3_authority,
        )
        _verify_complete_c1_projection(
            consumer=consumer,
            c1=commits["C1"],
            package=package,
            source_entries=_portable_entries(package, kit, source_sha),
        )
        c2_evidence_path = _require_ignored_output(
            consumer, target.parent / "c2-regenerator.log"
        )
        c2_commands = _c2_commands_for_plan(
            package, args.c2_generator_command, kit=kit
        )
        boundary_execution = _boundary_execution(
            [f"{item['id']}::{item['command']}" for item in c2_commands],
            boundaries,
            consumer=consumer,
            kit=kit,
            commits=commits,
            evidence_path=c2_evidence_path,
        )
        _bind_c2_generators(boundaries, boundary_execution, package=package)
        validate_boundary_ownership(
            boundaries,
            registry,
            package=package,
            consumer_c3_authority=consumer_c3_authority,
        )
        _validate_declared_boundaries(package, commits, boundaries)
    changed_paths = sorted(
        set(args.changed_path or [])
        | {item["path"] for item in boundaries["C3"]}
    )
    changed_contracts = list(args.changed_contract or [])
    selection, omissions, gate_catalog = _two_lane_selection(
        package,
        capsule,
        registry,
        verified_capsule,
        changed_paths,
        changed_contracts,
        consumer_c3_authority=consumer_c3_authority,
    )
    identity = {
        "source_sha": capsule["source_sha"],
        "package_sha256": capsule["package_sha256"],
        "portable_tree_sha256": capsule["portable_tree_sha256"],
        "consumer_B0": commits["B0"],
        "consumer_C3": commits["C3"],
        "command_registry_sha256": capsule["command_registry_sha256"],
        "toolchain_sha256": capsule["toolchain_sha256"],
    }
    plan: dict[str, Any] = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "runner_version": RUNNER_VERSION,
        "status": (
            "requires_lane_a"
            if selection["requires_lane_a"]
            else "ready_to_mutate"
            if automatic_mutation
            else "ready"
        ),
        "mode": "canary",
        "package_schema_version": package["schema_version"],
        "release_id": package["release"].get("id"),
        "capsule_sha256": capsule["capsule_sha256"],
        "impact_registry_sha256": registry["registry_sha256"],
        "consumer_c3_authority": consumer_c3_authority,
        "consumer_c3_authority_sha256": consumer_c3_authority_sha256,
        "identity": identity,
        "boundary_commits": commits,
        "boundaries": boundaries,
        "boundary_execution": boundary_execution,
        "preflight": preflight_execution,
        "mutation": mutation,
        "impact_inputs": {
            "changed_paths": sorted(set(changed_paths)),
            "changed_contracts": sorted(set(changed_contracts)),
        },
        "selection": selection,
        "omitted_gates": omissions,
        "gate_catalog": sorted(gate_catalog, key=lambda item: item["id"]),
        "conceptual_diff": {
            "boundary_file_counts": (
                {
                    "C1": len(mutation["c1_prospective_paths"]),
                    "C2": 0,
                    "C3": len(set(changed_paths)),
                }
                if mutation
                else {key: len(value) for key, value in boundaries.items()}
            ),
            "changed_path_count": len(set(changed_paths)),
            "changed_contract_count": len(set(changed_contracts)),
            "matched_surfaces": selection["matched_surfaces"],
            "unknown_path_count": len(selection["unknown_paths"]),
            "unknown_contract_count": len(selection["unknown_contracts"]),
            "selected_gate_count": len(selection["selected_gates"]),
            "omitted_gate_count": len(selection["omitted_gates"]),
            "escalation": selection["escalation"],
        },
    }
    attempt_identity_sha256 = _acceptance_attempt_identity(plan)
    acceptance_anchor, acceptance_anchor_file_sha256 = (
        _load_or_create_acceptance_anchor(
            consumer=consumer,
            plan_path=target,
            attempt_identity_sha256=attempt_identity_sha256,
            invocation_started_unix_ns=plan_started_unix_ns,
        )
    )
    plan["acceptance_budget"] = _pending_acceptance_budget_at(
        package, plan_started_at=acceptance_anchor["plan_started_at"]
    )
    plan["acceptance_anchor"] = {
        "schema_version": "wiki_viva_upgrade_acceptance_anchor_reference.v1",
        "attempt_identity_sha256": attempt_identity_sha256,
        "anchor_sha256": acceptance_anchor["anchor_sha256"],
        "file_sha256": acceptance_anchor_file_sha256,
    }
    plan["plan_sha256"] = _plan_digest(plan)
    _atomic_write(target, _json_bytes(plan))
    _emit(
        {
            "schema_version": "wiki_viva_upgrade_plan_summary.v1",
            "status": plan["status"],
            "lane": "lane_a_then_b" if selection["requires_lane_a"] else "lane_b",
            "selection": selection["escalation"],
            "selected_gate_count": len(selection["selected_gates"]),
            "omitted_gate_count": len(selection["omitted_gates"]),
            "plan_sha256": plan["plan_sha256"],
            "acceptance_anchor_sha256": acceptance_anchor_file_sha256,
            "conceptual_diff": plan["conceptual_diff"],
        }
    )
    return 0


def _validate_current_plan(
    *,
    plan: Mapping[str, Any],
    package: Mapping[str, Any],
    capsule: Mapping[str, Any],
    registry: Mapping[str, Any],
    verified_capsule: VerifiedReleaseCapsule,
    consumer: Path,
    kit: Path,
) -> None:
    _verify_plan_digest(plan)
    _validate_pending_plan_acceptance_budget(plan, package)
    if plan.get("capsule_sha256") != capsule["capsule_sha256"]:
        raise RunnerError("stale_plan_capsule", "the plan targets a different release capsule")
    if plan.get("impact_registry_sha256") != registry["registry_sha256"]:
        raise RunnerError("stale_plan_registry", "the plan targets a stale impact registry")
    expected_identity = {
        "source_sha": capsule["source_sha"],
        "package_sha256": capsule["package_sha256"],
        "portable_tree_sha256": capsule["portable_tree_sha256"],
        "consumer_B0": plan["boundary_commits"]["B0"],
        "consumer_C3": plan["boundary_commits"]["C3"],
        "command_registry_sha256": capsule["command_registry_sha256"],
        "toolchain_sha256": capsule["toolchain_sha256"],
    }
    if plan.get("identity") != expected_identity:
        raise RunnerError(
            "stale_plan_identity",
            "the plan identity differs from its package, capsule or boundary subjects",
            surface="receipt_identity",
            next_action="generate a new plan for the exact seven-term identity",
        )
    authority = plan.get("consumer_c3_authority")
    if not isinstance(authority, Mapping):
        raise RunnerError(
            "missing_consumer_c3_authority",
            "the plan omits its B0-derived C3 authority",
            surface="C3",
        )
    try:
        authority_sha256 = verify_consumer_c3_authority(
            authority,
            consumer_root=consumer,
            consumer_B0=expected_identity["consumer_B0"],
            package=package,
        )
    except UpgradeLaneError as exc:
        raise RunnerError(
            "stale_consumer_c3_authority",
            "the plan C3 authority differs from the exact B0 config",
            surface="C3",
        ) from exc
    if plan.get("consumer_c3_authority_sha256") != authority_sha256:
        raise RunnerError(
            "stale_consumer_c3_authority",
            "the plan C3 authority digest is stale",
            surface="C3",
        )
    _verify_preflight(plan, package=package, consumer=consumer, kit=kit)
    _require_clean(consumer)
    if _head(consumer) != expected_identity["consumer_C3"]:
        raise RunnerError(
            "changed_consumer_C3",
            "consumer C3 changed after the plan was generated",
            surface="consumer_C3",
            next_action="invalidate stale results and generate a new plan at the new C3",
        )
    commits = plan.get("boundary_commits")
    if not isinstance(commits, dict) or set(commits) != {"B0", "C1", "C2", "C3"}:
        raise RunnerError("invalid_plan_boundaries", "the plan boundary subjects are incomplete")
    _require_ancestry(consumer, [commits[key] for key in ("B0", "C1", "C2", "C3")])
    rebuilt = _build_boundaries(
        consumer=consumer,
        kit=kit,
        source_sha=capsule["source_sha"],
        package_sha256=capsule["package_sha256"],
        commits=commits,
        registry=registry,
        package=package,
        consumer_c3_authority=authority,
    )
    _verify_complete_c1_projection(
        consumer=consumer,
        c1=commits["C1"],
        package=package,
        source_entries=_portable_entries(package, kit, capsule["source_sha"]),
    )
    _verify_boundary_execution(
        rebuilt, plan.get("boundary_execution"), consumer=consumer
    )
    _bind_c2_generators(rebuilt, plan["boundary_execution"], package=package)
    validate_boundary_ownership(
        rebuilt,
        registry,
        package=package,
        consumer_c3_authority=authority,
    )
    _validate_declared_boundaries(package, commits, rebuilt)
    if canonical_sha256(rebuilt) != canonical_sha256(plan.get("boundaries")):
        raise RunnerError(
            "stale_boundary_evidence",
            "C1, C2 or C3 bytes changed after planning",
            surface="commit_boundaries",
            next_action="discard stale evidence and generate a new plan",
        )
    paths = plan["impact_inputs"]["changed_paths"]
    contracts = plan["impact_inputs"]["changed_contracts"]
    rebuilt_c3_paths = {item["path"] for item in rebuilt["C3"]}
    if not rebuilt_c3_paths.issubset(paths):
        raise RunnerError(
            "stale_execution_impact_inputs",
            "the plan impact inputs omit a real C3 boundary path",
            surface="impact_derivation",
            next_action="generate a new exact plan before running gates",
        )
    selection, omissions, catalog = _two_lane_selection(
        package,
        capsule,
        registry,
        verified_capsule,
        paths,
        contracts,
        consumer_c3_authority=authority,
    )
    for key, expected in (
        ("selection", selection),
        ("omitted_gates", omissions),
        ("gate_catalog", sorted(catalog, key=lambda item: item["id"])),
    ):
        if canonical_sha256(plan.get(key)) != canonical_sha256(expected):
            raise RunnerError(
                "stale_or_forged_plan_derivation",
                "the plan gate selection or omission proof cannot be reproduced",
                surface="impact_derivation",
                next_action="generate a new plan from the current registry",
            )
    _validate_plan_presentation(plan)


def _validate_pre_mutation_plan(
    *,
    plan: Mapping[str, Any],
    package: Mapping[str, Any],
    capsule: Mapping[str, Any],
    registry: Mapping[str, Any],
    verified_capsule: VerifiedReleaseCapsule,
    consumer: Path,
    kit: Path,
) -> None:
    mutation = plan.get("mutation")
    if not isinstance(mutation, dict) or mutation.get("strategy") != "runner_owned":
        return
    _validate_pending_plan_acceptance_budget(plan, package)
    expected_mutation_fields = {
        "strategy",
        "c1_projection_sha256",
        "c1_prospective_paths",
        "c2_commands",
        "c3_commands",
        "boundary_operations_sha256",
        "c3_adapter_contract",
        "c3_owned_patterns",
        "consumer_c3_authority_sha256",
    }
    if set(mutation) != expected_mutation_fields:
        raise RunnerError(
            "invalid_mutation_plan",
            "the runner-owned mutation plan has unknown or missing fields",
            surface="boundary_operations",
        )
    expected_identity = {
        "source_sha": capsule["source_sha"],
        "package_sha256": capsule["package_sha256"],
        "portable_tree_sha256": capsule["portable_tree_sha256"],
        "consumer_B0": plan["boundary_commits"]["B0"],
        "consumer_C3": plan["boundary_commits"]["B0"],
        "command_registry_sha256": capsule["command_registry_sha256"],
        "toolchain_sha256": capsule["toolchain_sha256"],
    }
    if (
        plan.get("capsule_sha256") != capsule["capsule_sha256"]
        or plan.get("impact_registry_sha256") != registry["registry_sha256"]
        or plan.get("identity") != expected_identity
    ):
        raise RunnerError(
            "stale_pre_mutation_identity",
            "the read-only plan no longer binds the exact capsule, B0 or registry",
            surface="receipt_identity",
        )
    authority = plan.get("consumer_c3_authority")
    if not isinstance(authority, Mapping):
        raise RunnerError(
            "missing_consumer_c3_authority",
            "the read-only plan omits its B0-derived C3 authority",
            surface="C3",
        )
    try:
        authority_sha256 = verify_consumer_c3_authority(
            authority,
            consumer_root=consumer,
            consumer_B0=expected_identity["consumer_B0"],
            package=package,
        )
    except UpgradeLaneError as exc:
        raise RunnerError(
            "stale_consumer_c3_authority",
            "the read-only C3 authority differs from the exact B0 config",
            surface="C3",
        ) from exc
    if (
        plan.get("consumer_c3_authority_sha256") != authority_sha256
        or mutation.get("consumer_c3_authority_sha256") != authority_sha256
    ):
        raise RunnerError(
            "stale_consumer_c3_authority",
            "the read-only C3 authority digest is stale",
            surface="C3",
        )
    _verify_preflight(plan, package=package, consumer=consumer, kit=kit)
    paths = plan["impact_inputs"]["changed_paths"]
    contracts = plan["impact_inputs"]["changed_contracts"]
    selection, omissions, catalog = _two_lane_selection(
        package,
        capsule,
        registry,
        verified_capsule,
        paths,
        contracts,
        consumer_c3_authority=authority,
    )
    for key, expected in (
        ("selection", selection),
        ("omitted_gates", omissions),
        ("gate_catalog", sorted(catalog, key=lambda item: item["id"])),
    ):
        if canonical_sha256(plan.get(key)) != canonical_sha256(expected):
            raise RunnerError(
                "stale_or_forged_plan_derivation",
                "the pre-mutation impact selection or omission proof cannot be reproduced",
                surface="impact_derivation",
            )
    _validate_plan_presentation(plan)
    entries = _portable_entries(package, kit, capsule["source_sha"])
    projection = {
        path: {"mode": item["mode"], "sha256": item["sha256"]}
        for path, item in sorted(entries.items())
    }
    if mutation.get("c1_projection_sha256") != canonical_sha256(projection):
        raise RunnerError(
            "stale_c1_projection",
            "the read-only C1 projection differs from the certified portable tree",
            surface="C1",
        )
    if package.get("schema_version") == _TWO_LANE_PACKAGE:
        operations = _boundary_operations(package)
        adapter = operations["c3_adapter"]
        expected_c2 = _c2_commands_for_plan(package, [], kit=kit)
        if (
            mutation.get("c2_commands") != expected_c2
            or mutation.get("boundary_operations_sha256")
            != operations.get("registry_sha256")
            or mutation.get("c3_adapter_contract") != adapter.get("contract")
            or mutation.get("c3_owned_patterns") != adapter.get("owns_patterns")
        ):
            raise RunnerError(
                "stale_boundary_operations",
                "the pre-mutation plan differs from the package-owned C2/C3 authority",
                surface="boundary_operations",
            )
    c3_commands = mutation.get("c3_commands")
    if not isinstance(c3_commands, list) or (
        package.get("schema_version") == _TWO_LANE_PACKAGE and not c3_commands
    ):
        raise RunnerError(
            "invalid_c3_adapter_contract",
            "the pre-mutation plan omits its consumer-owned C3 commands",
            surface="C3",
            contract=str(mutation.get("c3_adapter_contract") or "consumer_adapter"),
        )
    seen_c3: set[str] = set()
    for item in c3_commands:
        if (
            not isinstance(item, Mapping)
            or set(item) != {"id", "command"}
            or not isinstance(item.get("id"), str)
            or _GATE_ID_RE.fullmatch(item["id"]) is None
            or item["id"] in seen_c3
            or not isinstance(item.get("command"), str)
        ):
            raise RunnerError(
                "invalid_c3_adapter_contract",
                "a plan-sealed C3 command has an invalid identity",
                surface="C3",
            )
        seen_c3.add(item["id"])
        _parse_command(item["command"], kit_root=kit)


@contextlib.contextmanager
def _run_lock(path: Path) -> Iterable[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RunnerError(
            "adoption_already_running",
            "another process owns this plan's adoption lock",
            surface="resume_state",
            next_action="let the active run finish or remove a confirmed stale lock",
        ) from exc
    try:
        os.write(descriptor, b"wiki-upgrade-runner\n")
        os.close(descriptor)
        yield
    finally:
        path.unlink(missing_ok=True)


def _validate_resume_state(state: Mapping[str, Any], plan: Mapping[str, Any], run_dir: Path) -> None:
    expected = {
        "schema_version",
        "status",
        "plan_sha256",
        "identity_sha256",
        "capsule_sha256",
        "impact_registry_sha256",
        "toolchain_sha256",
        "consumer_c3_authority_sha256",
        "boundary_commits",
        "run_started_unix_ns",
        "acceptance_budget",
        "gate_results",
    }
    if set(state) != expected or state.get("schema_version") != STATE_SCHEMA_VERSION:
        raise RunnerError("invalid_resume_state", "the resume state shape is invalid")
    if state.get("plan_sha256") != plan["plan_sha256"]:
        raise RunnerError("stale_resume_plan", "resume state belongs to a stale plan")
    if state.get("identity_sha256") != canonical_sha256(plan["identity"]):
        raise RunnerError("stale_resume_identity", "resume state belongs to a stale B0/C3 identity")
    if state.get("consumer_c3_authority_sha256") != plan.get(
        "consumer_c3_authority_sha256"
    ):
        raise RunnerError(
            "stale_resume_consumer_c3_authority",
            "resume state belongs to a stale B0-derived C3 authority",
            surface="C3",
        )
    if state.get("boundary_commits") != plan.get("boundary_commits"):
        raise RunnerError(
            "stale_resume_boundaries",
            "resume state belongs to a different B0/C1/C2/C3 chain",
            surface="commit_boundaries",
        )
    for field in ("capsule_sha256", "impact_registry_sha256", "toolchain_sha256"):
        expected_value = (
            plan["identity"][field] if field == "toolchain_sha256" else plan[field]
        )
        if state.get(field) != expected_value:
            raise RunnerError(
                "stale_resume_artifact",
                "resume state was produced with a different capsule, registry or toolchain",
                surface="resume_state",
                next_action="start a new run for the current exact identity",
            )
    results = state.get("gate_results")
    if not isinstance(results, dict):
        raise RunnerError("invalid_resume_results", "resume gate results are not a mapping")
    budget = _validate_acceptance_budget_record(
        state.get("acceptance_budget"), expected_plan=plan
    )
    catalog = {item["id"]: item for item in plan["gate_catalog"]}
    selected = set(plan["selection"]["selected_gates"])
    if not set(results).issubset(selected):
        raise RunnerError(
            "stale_resume_gate_set",
            "resume contains a result outside the current selected gate set",
            surface="gate_evidence",
            next_action="start a new exact-subject run",
        )
    for gate_id, result in results.items():
        if not isinstance(result, dict) or result.get("provenance") != "executed":
            raise RunnerError(
                "manual_evidence_rejected",
                "resume contains manual or fabricated gate evidence",
                surface="gate_evidence",
                next_action="rerun the gate through the runner",
            )
        gate = catalog.get(gate_id)
        if (
            state.get("status") != "complete"
            and gate is not None
            and gate.get("class") not in {"upstream_certified", "canary"}
            and result.get("status") == "passed"
        ):
            previous_revalidation = result.get("_resume_revalidation")
            previous_attempt = (
                previous_revalidation.get("attempt", 0)
                if isinstance(previous_revalidation, Mapping)
                else 0
            )
            result["status"] = "revalidation_required"
            result["_resume_revalidation"] = {
                "reason": "portable_external_execution_authority_absent",
                "attempt": (
                    previous_attempt + 1
                    if isinstance(previous_attempt, int)
                    and not isinstance(previous_attempt, bool)
                    and previous_attempt >= 0
                    else 1
                ),
                "previous_output_sha256": (
                    result.get("output_sha256")
                    if isinstance(result.get("output_sha256"), str)
                    and _SHA256_RE.fullmatch(result["output_sha256"])
                    else "untrusted"
                ),
            }
            _emit(
                {
                    "event": "gate_revalidation_required",
                    "lane": "lane_b",
                    "phase": gate["class"],
                    "gate": gate_id,
                    "reason": "portable_external_execution_authority_absent",
                },
                stream=sys.stderr,
            )
            continue
        _acceptance_timestamp_microseconds(result.get("_completed_at"))
        if (
            gate is None
            or result.get("class") != gate["class"]
            or result.get("subject_sha") != plan["identity"]["consumer_C3"]
            or result.get("command_sha256")
            != _sha256_bytes(gate["command"].encode("utf-8"))
        ):
            raise RunnerError(
                "stale_resume_gate_identity",
                "a gate result is stale for C3, command registry or gate policy",
                surface=gate_id,
                next_action="rerun the gate under the current seven-term identity",
            )
        if result.get("status") != "passed":
            continue
        log_raw = _read_fd_pinned_regular(
            run_dir,
            f"logs/{gate_id}.log",
            label=f"resumed gate log {gate_id}",
            max_bytes=_MAX_GATE_OUTPUT_BYTES,
            lane="lane_b",
            surface="gate_evidence",
            unsafe_code="stale_resume_output",
            missing_code="stale_resume_output",
        )
        _require_safe_gate_text(
            log_raw, gate_id=gate_id, artifact="resumed stdout/stderr"
        )
        if _sha256_bytes(log_raw) != result.get("output_sha256"):
            raise RunnerError(
                "stale_resume_output",
                "a completed gate log is missing or no longer matches its receipt",
                surface="gate_evidence",
                next_action="start a new run; stale results cannot be resumed",
            )
        _validate_gate_evidence_manifest(gate_id, result, run_dir)
    canary_completed_at = _completed_canary_at(state, plan)
    if (
        canary_completed_at is None
        and budget["status"] != "pending"
        or canary_completed_at is not None
        and budget["status"] in {"met", "exceeded"}
        and budget["canary_completed_at"] != canary_completed_at
    ):
        raise RunnerError(
            "stale_acceptance_budget",
            "resume canary results and budget measurement disagree",
            surface="acceptance_budget",
        )


def _state_template(plan: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "status": "running",
        "plan_sha256": plan["plan_sha256"],
        "identity_sha256": canonical_sha256(plan["identity"]),
        "capsule_sha256": plan["capsule_sha256"],
        "impact_registry_sha256": plan["impact_registry_sha256"],
        "toolchain_sha256": plan["identity"]["toolchain_sha256"],
        "consumer_c3_authority_sha256": plan[
            "consumer_c3_authority_sha256"
        ],
        "boundary_commits": dict(plan["boundary_commits"]),
        "run_started_unix_ns": time.time_ns(),
        "acceptance_budget": _validate_acceptance_budget_record(
            plan["acceptance_budget"]
        ),
        "gate_results": {},
    }


def _canary_results_projection(
    state: Mapping[str, Any], plan: Mapping[str, Any]
) -> list[dict[str, Any]]:
    canary_ids = sorted(
        item["id"]
        for item in plan["gate_catalog"]
        if item.get("class") == "canary"
        and item["id"] in plan["selection"]["selected_gates"]
    )
    projection: list[dict[str, Any]] = []
    for gate_id in canary_ids:
        result = state.get("gate_results", {}).get(gate_id)
        if not isinstance(result, Mapping):
            raise RunnerError(
                "missing_canary_completion_evidence",
                "the completion anchor lacks a selected real canary result",
                lane="lane_b",
                surface="canary",
            )
        projection.append(
            {
                "id": gate_id,
                "class": result.get("class"),
                "status": result.get("status"),
                "subject_sha": result.get("subject_sha"),
                "command_sha256": result.get("command_sha256"),
                "output_sha256": result.get("output_sha256"),
                "completed_at": result.get("_completed_at"),
                "evidence_sha256": canonical_sha256(result.get("_evidence")),
            }
        )
    return projection


def _validate_canary_completion_anchor(
    payload: object,
    *,
    plan: Mapping[str, Any],
    completed_at: str,
    canary_results_sha256: str,
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise RunnerError(
            "invalid_canary_completion_anchor",
            "the real canary completion anchor is malformed",
            lane="lane_b",
            surface="acceptance_budget",
        )
    anchor = dict(payload)
    expected_keys = {
        "schema_version",
        "authority",
        "plan_sha256",
        "identity_sha256",
        "canary_completed_at",
        "canary_results_sha256",
        "anchor_sha256",
    }
    unsigned = dict(anchor)
    claimed = unsigned.pop("anchor_sha256", None)
    if (
        set(anchor) != expected_keys
        or anchor.get("schema_version")
        != "wiki_viva_upgrade_canary_completion_anchor.v1"
        or anchor.get("authority")
        != {
            "kind": "external_sha256",
            "id": "wiki_upgrade_real_canary_first_completion",
        }
        or anchor.get("plan_sha256") != plan["plan_sha256"]
        or anchor.get("identity_sha256") != canonical_sha256(plan["identity"])
        or anchor.get("canary_completed_at") != completed_at
        or anchor.get("canary_results_sha256") != canary_results_sha256
        or claimed != canonical_sha256(unsigned)
    ):
        raise RunnerError(
            "stale_canary_completion_anchor",
            "the real canary completion anchor is stale or unbound",
            lane="lane_b",
            surface="acceptance_budget",
            next_action="use the original post-canary anchor and unchanged run state",
        )
    return anchor


def _record_completed_canary_budget(
    state: dict[str, Any],
    plan: Mapping[str, Any],
    state_path: Path,
    run_dir: Path,
    *,
    trusted_file_sha256: str | None,
    allow_anchor_create: bool,
) -> tuple[dict[str, str] | None, str | None]:
    completed_at = _completed_canary_at(state, plan)
    if completed_at is None:
        if (run_dir / "canary-completion-anchor.json").exists():
            raise RunnerError(
                "stale_canary_completion_anchor",
                "a canary completion anchor exists without completed canary evidence",
                lane="lane_b",
                surface="acceptance_budget",
            )
        return None, None
    completed_microseconds = _acceptance_timestamp_microseconds(completed_at)
    budget = _validate_acceptance_budget_record(
        state.get("acceptance_budget"), expected_plan=plan
    )
    if budget["status"] == "pending":
        state["acceptance_budget"] = _complete_acceptance_budget(
            budget,
            canary_completed_unix_ns=completed_microseconds * 1_000,
        )
        _atomic_write(state_path, _json_bytes(state))
    elif budget["canary_completed_at"] != completed_at:
        raise RunnerError(
            "stale_acceptance_budget",
            "the measured budget is not bound to the completed real canary",
            surface="acceptance_budget",
        )
    canary_results_sha256 = canonical_sha256(
        _canary_results_projection(state, plan)
    )
    seed: dict[str, Any] = {
        "schema_version": "wiki_viva_upgrade_canary_completion_anchor.v1",
        "authority": {
            "kind": "external_sha256",
            "id": "wiki_upgrade_real_canary_first_completion",
        },
        "plan_sha256": plan["plan_sha256"],
        "identity_sha256": canonical_sha256(plan["identity"]),
        "canary_completed_at": completed_at,
        "canary_results_sha256": canary_results_sha256,
    }
    seed["anchor_sha256"] = canonical_sha256(seed)
    raw = _json_bytes(seed)
    path = run_dir / "canary-completion-anchor.json"
    created = False
    if not path.exists():
        if not allow_anchor_create:
            raise RunnerError(
                "missing_canary_completion_anchor",
                "completed canary state lacks its first-write completion authority",
                lane="lane_b",
                surface="acceptance_budget",
                next_action="discard the unanchored run and execute a new exact plan",
            )
        created = _atomic_create_once(path, raw)
    if not created:
        raw = _read_exact_private_file(path, label="canary completion anchor")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, ValueError, TypeError) as exc:
        raise RunnerError(
            "invalid_canary_completion_anchor",
            "the canary completion anchor is not valid UTF-8 JSON",
            lane="lane_b",
            surface="acceptance_budget",
        ) from exc
    anchor = _validate_canary_completion_anchor(
        payload,
        plan=plan,
        completed_at=completed_at,
        canary_results_sha256=canary_results_sha256,
    )
    file_sha256 = _sha256_bytes(raw)
    if created:
        _emit(
            {
                "schema_version": "wiki_viva_upgrade_canary_completion_summary.v1",
                "status": "anchored",
                "lane": "lane_b",
                "plan_sha256": plan["plan_sha256"],
                "canary_completion_anchor_sha256": file_sha256,
                "promotion_ready": False,
            }
        )
    if not created and trusted_file_sha256 is None:
        raise RunnerError(
            "untrusted_canary_completion_anchor",
            "resuming after the real canary requires its out-of-band completion digest",
            lane="lane_b",
            surface="acceptance_budget",
            next_action="pass the digest emitted by the original canary invocation",
        )
    if trusted_file_sha256 is not None and (
        _SHA256_RE.fullmatch(trusted_file_sha256) is None
        or trusted_file_sha256 != file_sha256
    ):
        raise RunnerError(
            "untrusted_canary_completion_anchor",
            "the canary completion bytes differ from out-of-band authority",
            lane="lane_b",
            surface="acceptance_budget",
        )
    reference = {
        "schema_version": "wiki_viva_upgrade_canary_completion_anchor_reference.v1",
        "anchor_sha256": anchor["anchor_sha256"],
        "file_sha256": file_sha256,
    }
    return reference, file_sha256


def _completed_canary_at(
    state: Mapping[str, Any], plan: Mapping[str, Any]
) -> str | None:
    canary_ids = {
        item["id"]
        for item in plan["gate_catalog"]
        if item.get("class") == "canary"
        and item["id"] in plan["selection"]["selected_gates"]
    }
    if not canary_ids or not all(
        state["gate_results"].get(gate_id, {}).get("status") == "passed"
        for gate_id in canary_ids
    ):
        return None
    completed = [
        state["gate_results"][gate_id].get("_completed_at")
        for gate_id in sorted(canary_ids)
    ]
    for value in completed:
        _acceptance_timestamp_microseconds(value)
    return max(completed, key=_acceptance_timestamp_microseconds)


def _gate_environment(
    run_dir: Path,
    kit_root: Path,
    gate_id: str,
    *,
    subject_sha: str,
    public_release_sha: str,
    require_operator_environment: bool = False,
) -> dict[str, str]:
    allowed = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "CI"}
    }
    supplied_operator = {
        key: os.environ[key]
        for key in _DOWNSTREAM_OPERATOR_ENV_KEYS
        if key in os.environ
    }
    if supplied_operator or require_operator_environment:
        missing = sorted(set(_DOWNSTREAM_OPERATOR_ENV_KEYS) - set(supplied_operator))
        if missing:
            raise RunnerError(
                "incomplete_operator_environment",
                "the real canary operator environment is incomplete",
                surface="real_canary",
                contract="canary_real",
                next_action="provide every versioned WIKI_COCKPIT operator binding",
            )
        if (
            supplied_operator["WIKI_COCKPIT_EXPECT_CONSUMER_HEAD"] != subject_sha
            or supplied_operator["WIKI_COCKPIT_EXPECT_PUBLIC_RELEASE_SHA"]
            != public_release_sha
        ):
            raise RunnerError(
                "stale_operator_environment",
                "the real canary operator environment targets another C3 or public release",
                surface="real_canary",
                contract="canary_real",
                next_action="regenerate operator bindings for the exact plan identity",
            )
        allowed.update(supplied_operator)
    allowed["WIKI_VIVA_KIT_ROOT"] = str(kit_root.resolve())
    allowed["WIKI_UPGRADE_RUN_DIR"] = str(run_dir.resolve())
    allowed["WIKI_UPGRADE_GATE_ID"] = gate_id
    allowed["WIKI_UPGRADE_GATE_ARTIFACT_DIR"] = str(
        (run_dir / "gate-artifacts" / gate_id).resolve()
    )
    allowed["PYTHONUNBUFFERED"] = "1"
    return allowed


def _require_safe_gate_text(raw: bytes, *, gate_id: str, artifact: str) -> None:
    """Reject secret-bearing or host/private gate output before runner persistence."""

    if len(raw) > _MAX_GATE_ARTIFACT_FILE_BYTES:
        raise RunnerError(
            "oversized_gate_evidence",
            "a gate evidence payload exceeds the bounded runner allowance",
            surface=gate_id,
        )
    try:
        text = raw.decode("utf-8", "strict")
        views = _percent_decoded_views(text)
    except (UnicodeDecodeError, ValueError) as exc:
        raise RunnerError(
            "binary_or_nested_gate_evidence",
            "textual gate evidence is not bounded canonical UTF-8",
            surface=gate_id,
            next_action="emit a redacted UTF-8 summary instead of raw gate data",
        ) from exc
    if any(
        "\x00" in view
        or _HOST_PATH_RE.search(view)
        or _PRIVATE_EVIDENCE_RE.search(view)
        or _PRIVATE_ROUTE_RE.search(view)
        for view in views
    ):
        raise RunnerError(
            "private_gate_evidence",
            "gate evidence contains a host-local path or private route",
            surface=gate_id,
            next_action=f"redact the {artifact} payload before rerunning the gate",
        )
    for view in views:
        masked = re.sub(
            r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{64}|[0-9A-Fa-f]{40})(?![0-9A-Fa-f])",
            "<digest>",
            view,
        )
        if any(finding.category == "secret" for finding in scan_text(masked)):
            raise RunnerError(
                "secret_gate_evidence",
                "gate evidence contains an access secret",
                surface=gate_id,
                next_action=f"remove the secret from {artifact} and rerun the gate",
            )


def _gate_artifact_files(artifact_dir: Path, *, gate_id: str) -> list[tuple[str, bytes]]:
    """Inventory a finished gate artifact tree through pinned POSIX descriptors."""

    if not os.path.lexists(artifact_dir):
        return []
    if os.name != "posix":
        raise RunnerError(
            "unsafe_gate_artifact",
            "gate evidence collection requires descriptor-pinned POSIX traversal",
            surface=gate_id,
        )
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    file_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    root_path = Path(os.path.abspath(artifact_dir))
    try:
        root_before = os.lstat(root_path)
        root_descriptor = os.open(root_path, directory_flags)
    except OSError as exc:
        raise RunnerError(
            "unsafe_gate_artifact",
            "the gate artifact root is missing, linked or not a real directory",
            surface=gate_id,
        ) from exc
    files: list[tuple[str, bytes]] = []
    total_bytes = 0

    def fail(message: str, *, cause: OSError | None = None) -> None:
        error = RunnerError(
            "unsafe_gate_artifact",
            message,
            surface=gate_id,
            next_action="remove linked, special, changing or oversized gate artifacts and rerun",
        )
        if cause is None:
            raise error
        raise error from cause

    def walk(directory: int, prefix: tuple[str, ...], depth: int) -> None:
        nonlocal total_bytes
        if depth > 16:
            fail("the gate artifact tree exceeds the bounded directory depth")
        try:
            names = sorted(os.listdir(directory))
        except OSError as exc:
            fail("the gate artifact directory changed during inventory", cause=exc)
        for name in names:
            if not isinstance(name, str) or name in {"", ".", ".."} or "/" in name:
                fail("the gate artifact tree contains an unsafe entry name")
            try:
                listed = os.stat(name, dir_fd=directory, follow_symlinks=False)
            except OSError as exc:
                fail("a gate artifact changed during inventory", cause=exc)
            relative_parts = (*prefix, name)
            relative = "/".join(relative_parts)
            if stat.S_ISLNK(listed.st_mode):
                fail("the gate artifact tree contains a symbolic link")
            if stat.S_ISDIR(listed.st_mode):
                try:
                    child = os.open(name, directory_flags, dir_fd=directory)
                except OSError as exc:
                    fail("a gate artifact directory cannot be opened safely", cause=exc)
                try:
                    opened = os.fstat(child)
                    if (listed.st_dev, listed.st_ino) != (opened.st_dev, opened.st_ino):
                        fail("a gate artifact directory changed while it was opened")
                    walk(child, relative_parts, depth + 1)
                finally:
                    with contextlib.suppress(OSError):
                        os.close(child)
                continue
            if not stat.S_ISREG(listed.st_mode):
                fail("the gate artifact tree contains a special file")
            try:
                descriptor = os.open(name, file_flags, dir_fd=directory)
            except OSError as exc:
                fail("a gate artifact cannot be opened without link traversal", cause=exc)
            try:
                before = os.fstat(descriptor)
                if (
                    (listed.st_dev, listed.st_ino) != (before.st_dev, before.st_ino)
                    or not stat.S_ISREG(before.st_mode)
                    or before.st_nlink != 1
                    or before.st_size > _MAX_GATE_ARTIFACT_FILE_BYTES
                ):
                    fail("a gate artifact is linked, changed or exceeds its size limit")
                chunks: list[bytes] = []
                file_bytes = 0
                while True:
                    chunk = os.read(
                        descriptor,
                        min(
                            1024 * 1024,
                            _MAX_GATE_ARTIFACT_FILE_BYTES + 1 - file_bytes,
                        ),
                    )
                    if not chunk:
                        break
                    file_bytes += len(chunk)
                    if file_bytes > _MAX_GATE_ARTIFACT_FILE_BYTES:
                        fail("a gate artifact exceeds its size limit")
                    chunks.append(chunk)
                after = os.fstat(descriptor)
                if (
                    before.st_dev,
                    before.st_ino,
                    before.st_size,
                    before.st_mtime_ns,
                    before.st_nlink,
                ) != (
                    after.st_dev,
                    after.st_ino,
                    after.st_size,
                    after.st_mtime_ns,
                    after.st_nlink,
                ):
                    fail("a gate artifact changed while its pinned descriptor was read")
                total_bytes += file_bytes
                if total_bytes > _MAX_GATE_ARTIFACT_TOTAL_BYTES:
                    fail("the gate artifact tree exceeds its total size limit")
                files.append((relative, b"".join(chunks)))
                if len(files) > _MAX_GATE_ARTIFACT_FILES:
                    fail("the gate artifact tree exceeds its file-count limit")
            finally:
                with contextlib.suppress(OSError):
                    os.close(descriptor)

    try:
        root_opened = os.fstat(root_descriptor)
        if (
            not stat.S_ISDIR(root_before.st_mode)
            or not stat.S_ISDIR(root_opened.st_mode)
            or (root_before.st_dev, root_before.st_ino)
            != (root_opened.st_dev, root_opened.st_ino)
        ):
            fail("the gate artifact root changed while it was opened")
        walk(root_descriptor, (), 0)
        return files
    finally:
        with contextlib.suppress(OSError):
            os.close(root_descriptor)


def _collect_gate_evidence(
    *,
    gate_id: str,
    gate_class: str,
    subject_sha: str,
    output_sha256: str,
    artifact_dir: Path,
    run_dir: Path,
) -> dict[str, list[dict[str, Any]]]:
    evidence_root = run_dir / "evidence"
    if os.path.lexists(evidence_root):
        evidence_root_mode = os.lstat(evidence_root).st_mode
        if stat.S_ISLNK(evidence_root_mode) or not stat.S_ISDIR(
            evidence_root_mode
        ):
            raise RunnerError(
                "unsafe_gate_evidence_destination",
                "the runner evidence root is linked or not a real directory",
                surface=gate_id,
            )
    else:
        evidence_root.mkdir(parents=True)
    evidence_dir = evidence_root / gate_id
    if os.path.lexists(evidence_dir):
        evidence_dir_mode = os.lstat(evidence_dir).st_mode
        if stat.S_ISLNK(evidence_dir_mode) or not stat.S_ISDIR(evidence_dir_mode):
            raise RunnerError(
                "unsafe_gate_evidence_destination",
                "the gate evidence destination is linked or not a real directory",
                surface=gate_id,
            )
    else:
        evidence_dir.mkdir()
    screenshots: list[dict[str, Any]] = []
    console = [
        {
            "ref": f"console-{gate_id}",
            "gate_id": gate_id,
            "subject_sha": subject_sha,
            "capture": "process_stdout_stderr",
            "sha256": canonical_sha256(
                {
                    "kind": "captured_process_console",
                    "gate_id": gate_id,
                    "subject_sha": subject_sha,
                    "output_sha256": output_sha256,
                }
            ),
        }
    ]
    network: list[dict[str, Any]] = []
    artifact_files = _gate_artifact_files(artifact_dir, gate_id=gate_id)
    if artifact_files:
        artifact_by_path = dict(artifact_files)
        visual_by_artifact: dict[str, dict[str, Any]] = {}
        visual_summary_raw = artifact_by_path.get("visual-evidence-summary.json")
        if visual_summary_raw is not None:
            _require_safe_gate_text(
                visual_summary_raw,
                gate_id=gate_id,
                artifact="visual evidence summary",
            )
            try:
                visual_summary = json.loads(visual_summary_raw)
            except (OSError, UnicodeError, ValueError, TypeError) as exc:
                raise RunnerError(
                    "invalid_visual_evidence_summary",
                    "the canary visual evidence summary is malformed",
                    surface=gate_id,
                ) from exc
            entries = visual_summary.get("entries") if isinstance(visual_summary, dict) else None
            if (
                not isinstance(visual_summary, dict)
                or set(visual_summary) != {"schema_version", "entries"}
                or visual_summary.get("schema_version")
                != "wiki_viva_canary_visual_summary.v1"
                or not isinstance(entries, list)
                or not entries
            ):
                raise RunnerError(
                    "invalid_visual_evidence_summary",
                    "the canary visual evidence summary is contract-incomplete",
                    surface=gate_id,
                )
            seen_profiles: set[str] = set()
            for entry in entries:
                viewport = entry.get("viewport") if isinstance(entry, dict) else None
                artifact = entry.get("artifact") if isinstance(entry, dict) else None
                profile = entry.get("profile") if isinstance(entry, dict) else None
                route = entry.get("route") if isinstance(entry, dict) else None
                if (
                    not isinstance(entry, dict)
                    or set(entry) != {"profile", "artifact", "route", "viewport"}
                    or not isinstance(artifact, str)
                    or Path(artifact).name != artifact
                    or not artifact.lower().endswith(".png")
                    or not isinstance(profile, str)
                    or _GATE_ID_RE.fullmatch(profile) is None
                    or profile in seen_profiles
                    or not isinstance(route, str)
                    or not route.startswith("/")
                    or re.match(r"^/(?:private|consumer|real)(?:/|$)", route, re.IGNORECASE)
                    or not isinstance(viewport, dict)
                    or set(viewport) != {"width", "height"}
                    or any(
                        isinstance(viewport.get(axis), bool)
                        or not isinstance(viewport.get(axis), int)
                        or not 240 <= viewport[axis] <= 7680
                        for axis in ("width", "height")
                    )
                    or artifact in visual_by_artifact
                ):
                    raise RunnerError(
                        "invalid_visual_evidence_summary",
                        "a canary visual profile, route or viewport is invalid or duplicated",
                        surface=gate_id,
                    )
                seen_profiles.add(profile)
                visual_by_artifact[artifact] = dict(entry)
        seen_visual_artifacts: set[str] = set()
        for relative, data in artifact_files:
            source = Path(relative)
            digest = _sha256_bytes(data)
            lower = source.name.lower()
            if source.suffix.lower() == ".png":
                visual = visual_by_artifact.get(source.name)
                if visual is None:
                    raise RunnerError(
                        "unbound_visual_evidence",
                        "a canary screenshot lacks profile, route and viewport binding",
                        surface=gate_id,
                    )
                destination = evidence_dir / f"screenshot-{digest}.png"
                _atomic_write(destination, data)
                dimensions = _png_dimensions(destination)
                viewport = visual["viewport"]
                if dimensions != (viewport["width"], viewport["height"]):
                    raise RunnerError(
                        "visual_viewport_mismatch",
                        "a canary screenshot dimensions differ from its declared viewport",
                        surface=gate_id,
                    )
                seen_visual_artifacts.add(source.name)
                screenshots.append(
                    {
                        "ref": f"screenshot-{digest[:16]}",
                        "gate_id": gate_id,
                        "subject_sha": subject_sha,
                        "sha256": digest,
                        "width": dimensions[0] if dimensions else 0,
                        "height": dimensions[1] if dimensions else 0,
                        "profile": visual["profile"],
                        "route": visual["route"],
                        "viewport": viewport,
                        "artifact_file": destination.name,
                    }
                )
            elif "network" in lower or source.suffix.lower() == ".har":
                _require_safe_gate_text(
                    data, gate_id=gate_id, artifact="network evidence"
                )
                if lower == "network-summary.json":
                    try:
                        summary = json.loads(data.decode("utf-8"))
                    except (UnicodeError, ValueError, TypeError) as exc:
                        raise RunnerError(
                            "invalid_network_capture_summary",
                            "the canary network summary is malformed",
                            surface=gate_id,
                        ) from exc
                    expected_keys = {
                        "schema_version",
                        "capture_method",
                        "request_count",
                        "error_count",
                        "payloads_redacted",
                    }
                    if (
                        not isinstance(summary, dict)
                        or set(summary) != expected_keys
                        or summary.get("schema_version")
                        != "wiki_viva_network_capture_summary.v1"
                        or summary.get("payloads_redacted") is not True
                        or isinstance(summary.get("request_count"), bool)
                        or not isinstance(summary.get("request_count"), int)
                        or summary["request_count"] <= 0
                        or isinstance(summary.get("error_count"), bool)
                        or not isinstance(summary.get("error_count"), int)
                        or summary["error_count"] != 0
                    ):
                        raise RunnerError(
                            "invalid_network_capture_summary",
                            "the canary network summary is not redacted or contract-complete",
                            surface=gate_id,
                        )
                else:
                    summary = None
                destination = evidence_dir / f"network-{digest}.bin"
                _atomic_write(destination, data)
                network.append(
                    {
                        "ref": f"network-{digest[:16]}",
                        "gate_id": gate_id,
                        "subject_sha": subject_sha,
                        "sha256": digest,
                        "capture": (
                            "gate_emitted_sanitized_network_summary"
                            if summary is not None
                            else "gate_emitted_private_network_artifact"
                        ),
                        "request_count": summary["request_count"] if summary else None,
                        "error_count": summary["error_count"] if summary else None,
                        "artifact_file": destination.name,
                    }
                )
            elif "console" in lower:
                _require_safe_gate_text(
                    data, gate_id=gate_id, artifact="console evidence"
                )
                if lower == "browser-console-summary.json":
                    try:
                        summary = json.loads(data.decode("utf-8"))
                    except (UnicodeError, ValueError, TypeError) as exc:
                        raise RunnerError(
                            "invalid_browser_console_summary",
                            "the browser console summary is malformed",
                            surface=gate_id,
                        ) from exc
                    if (
                        not isinstance(summary, dict)
                        or set(summary)
                        != {
                            "schema_version",
                            "error_count",
                            "warning_count",
                            "payloads_redacted",
                        }
                        or summary.get("schema_version")
                        != "wiki_viva_browser_console_summary.v1"
                        or summary.get("payloads_redacted") is not True
                        or any(
                            isinstance(summary.get(field), bool)
                            or not isinstance(summary.get(field), int)
                            or summary[field] < 0
                            for field in ("error_count", "warning_count")
                        )
                    ):
                        raise RunnerError(
                            "invalid_browser_console_summary",
                            "the browser console summary is not redacted or contract-complete",
                            surface=gate_id,
                        )
                    if summary.get("error_count") != 0:
                        raise RunnerError(
                            "browser_console_errors_observed",
                            "the real canary browser console observed errors",
                            surface=gate_id,
                        )
                else:
                    summary = None
                destination = evidence_dir / f"console-{digest}.bin"
                _atomic_write(destination, data)
                console.append(
                    {
                        "ref": f"console-{digest[:16]}",
                        "gate_id": gate_id,
                        "subject_sha": subject_sha,
                        "sha256": digest,
                        "capture": (
                            "gate_emitted_browser_console_summary"
                            if summary is not None
                            else "gate_emitted_private_console_artifact"
                        ),
                        "error_count": summary["error_count"] if summary else None,
                        "warning_count": summary["warning_count"] if summary else None,
                        "artifact_file": destination.name,
                    }
                )
        if set(visual_by_artifact) != seen_visual_artifacts:
            raise RunnerError(
                "missing_visual_evidence_artifact",
                "the canary visual summary references a missing screenshot",
                surface=gate_id,
            )
    return {"screenshots": screenshots, "console": console, "network": network}


def _gate_contract(gate: Mapping[str, Any]) -> str:
    assertions = gate.get("asserts")
    if isinstance(assertions, list) and assertions and isinstance(assertions[0], str):
        return assertions[0]
    return PLAN_SCHEMA_VERSION


def _progress_fields(
    *, completed: int, total: int, run_started_unix_ns: int
) -> dict[str, Any]:
    elapsed = max(0.0, (time.time_ns() - run_started_unix_ns) / 1_000_000_000)
    eta = (
        max(0.0, elapsed / completed * (total - completed))
        if completed > 0 and total >= completed
        else None
    )
    return {
        "completed": completed,
        "total": total,
        "elapsed_seconds": round(elapsed, 3),
        "eta_seconds": round(eta, 3) if eta is not None else None,
    }


def _run_gate(
    gate: Mapping[str, str],
    *,
    consumer: Path,
    kit: Path,
    run_dir: Path,
    subject_sha: str,
    public_release_sha: str,
    timeout: int,
    heartbeat: float,
    completed_before: int,
    total_count: int,
    run_started_unix_ns: int,
    resume_revalidation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    gate_id = gate["id"]
    command = gate["command"]
    argv = _parse_command(command, kit_root=kit)
    if gate_id == "rollback_report_verification":
        expected_tail = ["scripts/wiki_upgrade.py", "verify-rollback-report", "--check"]
        if len(argv) < 4 or argv[-3:] != expected_tail:
            raise RunnerError(
                "rollback_gate_command_mismatch",
                "rollback_report_verification must call the versioned runner verifier",
                surface="rollback_report_verification",
                next_action="restore the command from the versioned impact registry",
            )
        argv[-3] = str(Path(__file__).resolve())
    logs_root = run_dir / "logs"
    artifacts_root = run_dir / "gate-artifacts"
    evidence_root = run_dir / "evidence"
    for owned_root in (logs_root, artifacts_root, evidence_root):
        if os.path.lexists(owned_root) and (
            stat.S_ISLNK(os.lstat(owned_root).st_mode)
            or not stat.S_ISDIR(os.lstat(owned_root).st_mode)
        ):
            owned_root.unlink()
        owned_root.mkdir(parents=True, exist_ok=True)
    log_path = logs_root / f"{gate_id}.log"
    artifact_dir = artifacts_root / gate_id
    evidence_dir = evidence_root / gate_id
    for stale_path in (log_path, artifact_dir, evidence_dir):
        if not os.path.lexists(stale_path):
            continue
        stale_mode = os.lstat(stale_path).st_mode
        if stat.S_ISDIR(stale_mode):
            shutil.rmtree(stale_path)
        else:
            stale_path.unlink()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    _emit(
        {
            "event": "gate_started",
            "lane": "lane_b",
            "phase": gate["class"],
            "gate": gate_id,
            **_progress_fields(
                completed=completed_before,
                total=total_count,
                run_started_unix_ns=run_started_unix_ns,
            ),
        },
        stream=sys.stderr,
    )
    started = time.monotonic()
    exit_code = 1
    output = bytearray()
    output_oversized = threading.Event()
    output_reader_errors: list[BaseException] = []
    process = subprocess.Popen(
        argv,
        cwd=consumer,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=_gate_environment(
            run_dir,
            kit,
            gate_id,
            subject_sha=subject_sha,
            public_release_sha=public_release_sha,
            require_operator_environment="test:e2e:operator" in command,
        ),
        start_new_session=True,
    )
    assert process.stdout is not None

    def drain_output() -> None:
        try:
            while True:
                chunk = process.stdout.read(64 * 1024)
                if not chunk:
                    return
                remaining = _MAX_GATE_OUTPUT_BYTES + 1 - len(output)
                if remaining > 0:
                    output.extend(chunk[:remaining])
                if len(output) > _MAX_GATE_OUTPUT_BYTES or len(chunk) > remaining:
                    output_oversized.set()
        except BaseException as exc:  # pragma: no cover - defensive pipe failure
            output_reader_errors.append(exc)

    def terminate_process() -> None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()

    reader = threading.Thread(
        target=drain_output,
        name=f"wiki-upgrade-output-{gate_id}",
        daemon=True,
    )
    reader.start()
    next_heartbeat = started + max(0.1, heartbeat)
    while process.poll() is None:
        now = time.monotonic()
        if output_oversized.is_set():
            terminate_process()
            exit_code = 125
            break
        if now - started > timeout:
            terminate_process()
            exit_code = 124
            break
        if now >= next_heartbeat:
            _emit(
                {
                    "event": "gate_heartbeat",
                    "lane": "lane_b",
                    "phase": gate["class"],
                    "gate": gate_id,
                    **_progress_fields(
                        completed=completed_before,
                        total=total_count,
                        run_started_unix_ns=run_started_unix_ns,
                    ),
                },
                stream=sys.stderr,
            )
            next_heartbeat = now + max(0.1, heartbeat)
        time.sleep(min(0.1, max(0.02, heartbeat / 10)))
    else:
        exit_code = int(process.returncode or 0)
    reader.join(timeout=5)
    if reader.is_alive():
        terminate_process()
        reader.join(timeout=5)
    process.stdout.close()
    if reader.is_alive() or output_reader_errors:
        raise RunnerError(
            "gate_output_capture_failed",
            "the gate output stream could not be captured safely",
            surface=gate_id,
        )
    if output_oversized.is_set():
        raise RunnerError(
            "oversized_gate_output",
            "the gate stdout/stderr stream exceeds the bounded runner allowance",
            surface=gate_id,
            next_action="use a quiet registered reporter and rerun the gate",
        )
    output_raw = bytes(output)
    _require_safe_gate_text(
        output_raw,
        gate_id=gate_id,
        artifact="stdout/stderr",
    )
    if (
        not os.path.lexists(logs_root)
        or stat.S_ISLNK(os.lstat(logs_root).st_mode)
        or not stat.S_ISDIR(os.lstat(logs_root).st_mode)
    ):
        raise RunnerError(
            "unsafe_gate_log_destination",
            "the runner log destination changed while the gate executed",
            surface=gate_id,
        )
    _atomic_write(log_path, output_raw)
    output_sha256 = _sha256_bytes(output_raw)
    status = "passed" if exit_code == 0 else "failed"
    _emit(
        {
            "event": "gate_completed",
            "lane": "lane_b",
            "phase": gate["class"],
            "gate": gate_id,
            "status": status,
            **_progress_fields(
                completed=completed_before + (1 if status == "passed" else 0),
                total=total_count,
                run_started_unix_ns=run_started_unix_ns,
            ),
        },
        stream=sys.stderr,
    )
    result = {
        "id": gate_id,
        "class": gate["class"],
        "provenance": "executed",
        "status": status,
        "exit_code": exit_code,
        "subject_sha": subject_sha,
        "command_sha256": _sha256_bytes(command.encode("utf-8")),
        "output_sha256": output_sha256,
    }
    if resume_revalidation is not None:
        result["_resume_revalidation"] = {
            **dict(resume_revalidation),
            "result": "reexecuted",
        }
    result["_evidence"] = _collect_gate_evidence(
        gate_id=gate_id,
        gate_class=gate["class"],
        subject_sha=subject_sha,
        output_sha256=output_sha256,
        artifact_dir=artifact_dir,
        run_dir=run_dir,
    )
    result["_completed_at"] = _acceptance_timestamp(time.time_ns())
    return result


def _execute_group(
    gates: Sequence[Mapping[str, str]],
    *,
    state: dict[str, Any],
    state_path: Path,
    consumer: Path,
    kit: Path,
    run_dir: Path,
    subject_sha: str,
    public_release_sha: str,
    jobs: int,
    timeout: int,
    heartbeat: float,
    total_count: int,
) -> None:
    pending = [
        gate
        for gate in gates
        if state["gate_results"].get(gate["id"], {}).get("status") != "passed"
    ]
    if not pending:
        return
    completed_before = sum(
        1 for result in state["gate_results"].values() if result.get("status") == "passed"
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(jobs, len(pending)))) as pool:
        future_gate = {
            pool.submit(
                _run_gate,
                gate,
                consumer=consumer,
                kit=kit,
                run_dir=run_dir,
                subject_sha=subject_sha,
                public_release_sha=public_release_sha,
                timeout=timeout,
                heartbeat=heartbeat,
                completed_before=completed_before,
                total_count=total_count,
                run_started_unix_ns=state["run_started_unix_ns"],
                resume_revalidation=(
                    state["gate_results"].get(gate["id"], {}).get(
                        "_resume_revalidation"
                    )
                    if state["gate_results"].get(gate["id"], {}).get("status")
                    == "revalidation_required"
                    else None
                ),
            ): gate
            for gate in pending
        }
        for future in concurrent.futures.as_completed(future_gate):
            gate = future_gate[future]
            try:
                result = future.result()
            except (OSError, RunnerError, ValueError) as exc:
                if isinstance(exc, RunnerError):
                    if exc.contract == PLAN_SCHEMA_VERSION:
                        raise RunnerError(
                            exc.code,
                            exc.message,
                            lane=exc.lane,
                            surface=exc.surface,
                            contract=_gate_contract(gate),
                            next_action=exc.next_action,
                        ) from exc
                    raise
                raise RunnerError(
                    "gate_execution_error",
                    "a registered gate could not be executed",
                    surface=gate["id"],
                    contract=_gate_contract(gate),
                    next_action="repair the gate runtime and resume the same exact plan",
                ) from exc
            state["gate_results"][gate["id"]] = result
            _atomic_write(state_path, _json_bytes(state))
            completed_now = sum(
                1
                for value in state["gate_results"].values()
                if value.get("status") == "passed"
            )
            _emit(
                {
                    "event": "matrix_progress",
                    "lane": "lane_b",
                    "phase": gate["class"],
                    "gate": gate["id"],
                    **_progress_fields(
                        completed=completed_now,
                        total=total_count,
                        run_started_unix_ns=state["run_started_unix_ns"],
                    ),
                },
                stream=sys.stderr,
            )
    failed = sorted(
        gate["id"]
        for gate in pending
        if state["gate_results"].get(gate["id"], {}).get("status") != "passed"
    )
    if failed:
        state["status"] = "failed"
        _atomic_write(state_path, _json_bytes(state))
        raise RunnerError(
            "gate_group_failed",
            "one or more selected gates failed; their real output was retained",
            surface=failed[0],
            contract=_gate_contract(
                next(gate for gate in pending if gate["id"] == failed[0])
            ),
            next_action="repair the named surface and resume this unchanged plan",
        )


def _execute_phase_dag(
    gates: Sequence[Mapping[str, Any]],
    *,
    selected_ids: set[str],
    state: dict[str, Any],
    state_path: Path,
    consumer: Path,
    kit: Path,
    run_dir: Path,
    subject_sha: str,
    public_release_sha: str,
    jobs: int,
    timeout: int,
    heartbeat: float,
) -> None:
    remaining = {
        gate["id"]: gate
        for gate in gates
        if state["gate_results"].get(gate["id"], {}).get("status") != "passed"
    }
    while remaining:
        completed = {
            gate_id
            for gate_id, result in state["gate_results"].items()
            if result.get("status") == "passed"
        }
        ready = [
            gate
            for gate in remaining.values()
            if all(
                dependency in selected_ids and dependency in completed
                for dependency in gate.get("depends_on", [])
            )
        ]
        if not ready:
            raise RunnerError(
                "gate_dependency_deadlock",
                "selected gates contain an unsatisfied dependency or phase inversion",
                surface=sorted(remaining)[0],
                next_action="repair gate dependencies so prerequisites precede canary/background work",
            )
        # One gate from each resource group may enter a parallel wave.  Other
        # gates in the same group wait for the next deterministic wave.
        wave: list[Mapping[str, Any]] = []
        resources: set[str] = set()
        for gate in sorted(ready, key=lambda item: item["id"]):
            resource = str(gate.get("resource_group") or f"gate_{gate['id']}")
            if resource in resources:
                continue
            resources.add(resource)
            wave.append(gate)
        _execute_group(
            wave,
            state=state,
            state_path=state_path,
            consumer=consumer,
            kit=kit,
            run_dir=run_dir,
            subject_sha=subject_sha,
            public_release_sha=public_release_sha,
            jobs=jobs,
            timeout=timeout,
            heartbeat=heartbeat,
            total_count=len(selected_ids),
        )
        for gate in wave:
            remaining.pop(gate["id"], None)


def _rollback_execution(consumer: Path, plan: Mapping[str, Any]) -> dict[str, Any]:
    b0 = plan["identity"]["consumer_B0"]
    c3 = plan["identity"]["consumer_C3"]
    expected_tree = _git(consumer, ["rev-parse", f"{b0}^{{tree}}"]).stdout.decode().strip()
    with tempfile.TemporaryDirectory(prefix="wiki-upgrade-rollback-") as temporary:
        clone = Path(temporary) / "consumer"
        clone_result = subprocess.run(
            ["git", "clone", "--quiet", "--no-local", str(consumer), str(clone)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if clone_result.returncode != 0:
            raise RunnerError(
                "rollback_clone_failed",
                "the disposable rollback clone could not be created",
                surface="rollback",
                next_action="repair local Git cloning and resume the unchanged plan",
            )
        _git(clone, ["checkout", "--quiet", "--detach", c3])
        patch = _git(consumer, ["diff", "--binary", b0, c3, "--"]).stdout
        if patch:
            applied = _git(clone, ["apply", "--reverse", "--index", "--binary", "-"], input_bytes=patch, check=False)
            if applied.returncode != 0:
                raise RunnerError(
                    "rollback_apply_failed",
                    "the exact reverse migration patch failed in the disposable clone",
                    surface="rollback",
                    next_action="repair the migration boundary or rollback policy before promotion",
                )
        rolled_tree = _git(clone, ["write-tree"]).stdout.decode().strip()
        worktree_equal = _git(clone, ["diff", "--quiet", b0, "--"], check=False).returncode == 0
        untracked = _git(clone, ["ls-files", "--others", "--exclude-standard"]).stdout
        tree_equal = rolled_tree == expected_tree and worktree_equal and not untracked
    evidence = {
        "schema_version": ROLLBACK_SCHEMA_VERSION,
        "provenance": "executed",
        "status": "verified" if tree_equal else "mismatch",
        "subject_sha": c3,
        "consumer_B0": b0,
        "before_tree_sha": expected_tree,
        "rolled_back_tree_sha": rolled_tree,
        "tree_equal": tree_equal,
        "method": "reverse_binary_patch_in_disposable_clone",
        "boundary_digest": canonical_sha256(plan["boundaries"]),
    }
    evidence["evidence_sha256"] = canonical_sha256(evidence)
    if not tree_equal:
        raise RunnerError(
            "rollback_tree_mismatch",
            "executed rollback did not reproduce the exact B0 tree",
            surface="rollback",
            next_action="block promotion and repair the rollback boundary",
        )
    return evidence


def _png_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        header = path.read_bytes()[:24]
    except OSError:
        return None
    if len(header) == 24 and header[:8] == b"\x89PNG\r\n\x1a\n" and header[12:16] == b"IHDR":
        return struct.unpack(">II", header[16:24])
    return None


def _empty_evidence() -> dict[str, Any]:
    return {
        "gate_logs": [],
        "screenshots": [],
        "console": [],
        "network": [],
        "capture_status": {
            "screenshots": "not_produced_by_selected_gates",
            "console": "not_produced_by_selected_gates",
            "network": "not_produced_by_selected_gates",
        },
    }


def _evidence_inventory(state: Mapping[str, Any]) -> dict[str, Any]:
    gate_logs: list[dict[str, Any]] = []
    screenshots: list[dict[str, Any]] = []
    console: list[dict[str, Any]] = []
    network: list[dict[str, Any]] = []
    for gate_id, result in sorted(state["gate_results"].items()):
        if result.get("status") != "passed":
            continue
        gate_logs.append(
            {
                "gate_id": gate_id,
                "subject_sha": result["subject_sha"],
                "command_sha256": result["command_sha256"],
                "output_sha256": result["output_sha256"],
            }
        )
        captured = result.get("_evidence")
        if not isinstance(captured, dict):
            raise RunnerError(
                "missing_run_owned_evidence",
                "a completed gate has no runner-owned evidence manifest",
                surface=gate_id,
                next_action="rerun the gate through the current runner",
            )
        screenshots.extend(item for item in captured.get("screenshots", []) if isinstance(item, dict))
        console.extend(item for item in captured.get("console", []) if isinstance(item, dict))
        network.extend(item for item in captured.get("network", []) if isinstance(item, dict))
    return {
        "gate_logs": gate_logs,
        "screenshots": screenshots,
        "console": console,
        "network": network,
        "capture_status": {
            "screenshots": "captured" if screenshots else "not_produced_by_selected_gates",
            "console": "captured" if console else "not_produced_by_selected_gates",
            "network": "captured" if network else "not_produced_by_selected_gates",
        },
    }


def _require_evidence_contract(
    package: Mapping[str, Any],
    evidence: Mapping[str, Any],
    *,
    selected_gates: Sequence[str],
    gate_catalog: Sequence[Mapping[str, Any]],
    subject_sha: str,
) -> None:
    gate_logs = evidence.get("gate_logs")
    console = evidence.get("console")
    if (
        not isinstance(gate_logs, list)
        or {item.get("gate_id") for item in gate_logs if isinstance(item, dict)}
        != set(selected_gates)
        or not isinstance(console, list)
        or {item.get("gate_id") for item in console if isinstance(item, dict)}
        != set(selected_gates)
    ):
        raise RunnerError(
            "run_owned_evidence_incomplete",
            "selected gates are not exactly covered by runner-owned log and console evidence",
            surface="gate_evidence",
            next_action="rerun the exact selected matrix through this runner",
        )
    canary_ids = {
        item["id"] for item in gate_catalog if item.get("class") == "canary"
    }
    network = evidence.get("network")
    if canary_ids and (
        not isinstance(network, list)
        or not canary_ids.issubset(
            {
                item.get("gate_id")
                for item in network
                if isinstance(item, dict)
                and item.get("capture")
                == "gate_emitted_sanitized_network_summary"
            }
        )
    ):
        raise RunnerError(
            "canary_network_evidence_incomplete",
            "real canary gates lack a runner-owned network capture observation",
            surface="real_canary",
            next_action="rerun canary with the gate artifact directory enabled",
        )
    if canary_ids and (
        not isinstance(console, list)
        or not canary_ids.issubset(
            {
                item.get("gate_id")
                for item in console
                if isinstance(item, dict)
                and item.get("capture")
                == "gate_emitted_browser_console_summary"
            }
        )
    ):
        raise RunnerError(
            "canary_browser_console_evidence_incomplete",
            "real canary gates lack a redacted browser console summary",
            surface="real_canary",
            next_action="emit browser-console-summary.json from the real canary gate",
        )
    migration = package.get("migration")
    profiles = migration.get("visual_profiles") if isinstance(migration, dict) else None
    if not isinstance(profiles, list) or not profiles:
        return
    screenshots = evidence.get("screenshots")
    valid = (
        isinstance(screenshots, list)
        and len(screenshots) >= len(profiles)
        and all(
            isinstance(item, dict)
            and int(item.get("width", 0)) > 0
            and int(item.get("height", 0)) > 0
            for item in screenshots
        )
    )
    if not valid:
        raise RunnerError(
            "visual_evidence_incomplete",
            "the current run did not produce all package-required visual profiles",
            surface="canary_visual_evidence",
            next_action="rerun the real canary with screenshot capture for every declared profile",
        )
    try:
        validate_canary_evidence(
            package,
            evidence,
            selected_gates=selected_gates,
            gate_catalog=gate_catalog,
            subject_sha=subject_sha,
        )
    except UpgradeLaneError as exc:
        raise RunnerError(
            "canary_evidence_contract_failed",
            "real canary evidence lacks exact error-free network, console or visual proof",
            surface="real_canary",
            contract="canary_real",
            next_action="rerun the canary through the versioned artifact-producing harness",
        ) from exc


def _validate_gate_evidence_manifest(
    gate_id: str,
    result: Mapping[str, Any],
    run_dir: Path,
) -> None:
    evidence = result.get("_evidence")
    if not isinstance(evidence, dict) or set(evidence) != {
        "screenshots",
        "console",
        "network",
    }:
        raise RunnerError(
            "missing_run_owned_evidence",
            "a resumed result lacks its runner-owned evidence manifest",
            surface=gate_id,
            next_action="start a new run for this exact plan",
        )
    subject_sha = result.get("subject_sha")
    expected_console = canonical_sha256(
        {
            "kind": "captured_process_console",
            "gate_id": gate_id,
            "subject_sha": subject_sha,
            "output_sha256": result.get("output_sha256"),
        }
    )
    console = evidence.get("console")
    if not isinstance(console, list) or not any(
        isinstance(item, dict)
        and item.get("gate_id") == gate_id
        and item.get("subject_sha") == subject_sha
        and item.get("sha256") == expected_console
        for item in console
    ):
        raise RunnerError(
            "stale_console_evidence",
            "runner-owned console evidence is stale or missing",
            surface=gate_id,
            next_action="rerun the gate instead of reusing evidence",
        )
    for kind in ("screenshots", "console", "network"):
        entries = evidence.get(kind)
        if not isinstance(entries, list):
            raise RunnerError("invalid_run_owned_evidence", "a gate evidence list is invalid", surface=gate_id)
        for item in entries:
            if not isinstance(item, dict) or item.get("gate_id") != gate_id or item.get("subject_sha") != subject_sha:
                raise RunnerError("stale_run_owned_evidence", "gate evidence is bound to another gate or C3", surface=gate_id)
            artifact_file = item.get("artifact_file")
            if artifact_file is None:
                continue
            if not isinstance(artifact_file, str) or Path(artifact_file).name != artifact_file:
                raise RunnerError("unsafe_run_owned_evidence", "a gate artifact reference is unsafe", surface=gate_id)
            artifact_raw = _read_fd_pinned_regular(
                run_dir,
                f"evidence/{gate_id}/{artifact_file}",
                label=f"resumed {kind} evidence for {gate_id}",
                max_bytes=_MAX_GATE_ARTIFACT_FILE_BYTES,
                lane="lane_b",
                surface=gate_id,
                unsafe_code="unsafe_run_owned_evidence",
                missing_code="stale_run_owned_evidence",
            )
            if kind in {"console", "network"}:
                _require_safe_gate_text(
                    artifact_raw,
                    gate_id=gate_id,
                    artifact=f"resumed {kind} evidence",
                )
            if _sha256_bytes(artifact_raw) != item.get("sha256"):
                raise RunnerError(
                    "stale_run_owned_evidence",
                    "a runner-owned artifact no longer matches its manifest",
                    surface=gate_id,
                    next_action="start a new exact-subject run",
                )


def _report(
    plan: Mapping[str, Any],
    gate_results: Sequence[Mapping[str, Any]],
    rollback: Mapping[str, Any],
    evidence: Mapping[str, Any],
    acceptance_budget: Mapping[str, Any],
    *,
    status: str,
) -> dict[str, Any]:
    budget = _validate_acceptance_budget_record(
        acceptance_budget, expected_plan=plan
    )
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": status,
        "lane": "lane_b",
        "mode": "canary",
        "plan_sha256": plan["plan_sha256"],
        "consumer_c3_authority_sha256": plan[
            "consumer_c3_authority_sha256"
        ],
        "identity": plan["identity"],
        "selection": {
            "escalation": plan["selection"]["escalation"],
            "impact_derivation_sha256": plan["selection"]["derivation_sha256"],
            "selected_gate_count": len(plan["selection"]["selected_gates"]),
            "omitted_gate_count": len(plan["selection"]["omitted_gates"]),
            "matched_surfaces": plan["selection"]["matched_surfaces"],
        },
        "boundaries": {
            "digest": canonical_sha256(plan["boundaries"]),
            "counts": {key: len(value) for key, value in plan["boundaries"].items()},
        },
        "gate_results": [
            {
                "id": item["id"],
                "class": item["class"],
                "status": item["status"],
                "output_sha256": item["output_sha256"],
            }
            for item in sorted(gate_results, key=lambda value: value["id"])
        ],
        "rollback_evidence_sha256": rollback["evidence_sha256"],
        "acceptance_budget": budget,
        "evidence": evidence,
        "promotion_ready": status == "complete" and budget["status"] == "met",
        "human_gate_required": True,
    }


def _render_report(report: Mapping[str, Any]) -> str:
    selection = report["selection"]
    boundaries = report["boundaries"]["counts"]
    budget = report["acceptance_budget"]
    budget_summary = (
        f"{budget['elapsed_milliseconds']} ms ({budget['status']})"
        if "elapsed_milliseconds" in budget
        else f"{budget['status']} (limit {budget['limit_seconds']} s)"
    )
    return "\n".join(
        [
            "# Wiki Viva downstream adoption report",
            "",
            f"- Status: `{report['status']}`",
            f"- Lane: `{report['lane']}`",
            f"- Mode: `{report['mode']}`",
            f"- Plan: `{report['plan_sha256']}`",
            f"- Impact derivation: `{selection['impact_derivation_sha256']}`",
            f"- Gates: {selection['selected_gate_count']} selected; {selection['omitted_gate_count']} omitted with proof",
            f"- Boundaries: C1={boundaries['C1']}, C2={boundaries['C2']}, C3={boundaries['C3']}",
            f"- Rollback: `{report['rollback_evidence_sha256']}`",
            f"- Plan-to-canary: `{budget_summary}`",
            f"- Promotion ready: `{str(report['promotion_ready']).lower()}`",
            "- Final promotion still requires PR review and the human gate.",
            "",
        ]
    )


def _public_report_projection(report: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return public_migration_report_projection(report)
    except UpgradeLaneError as exc:
        raise RunnerError(
            "public_report_projection_rejected",
            "the private report cannot form the exact safe public projection",
            surface="public_evidence_redaction",
            next_action="block promotion and repair the private report contract",
        ) from exc


def _resolve_verification_run(args: argparse.Namespace) -> Path:
    if args.run_dir:
        return args.run_dir.resolve()
    environment = os.environ.get("WIKI_UPGRADE_RUN_DIR")
    if environment:
        return Path(environment).resolve()
    pointer = Path.cwd() / ".wiki-viva/upgrade/latest.json"
    try:
        payload = json.loads(pointer.read_text(encoding="utf-8"))
        run_key = payload["run_key"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RunnerError(
            "rollback_report_not_found",
            "no completed or candidate rollback report is available",
            surface="rollback_report_verification",
            next_action="run adopt for the exact plan before verifying its report",
        ) from exc
    if not isinstance(run_key, str) or re.fullmatch(r"[0-9a-f]{16}", run_key) is None:
        raise RunnerError("invalid_latest_pointer", "the latest run pointer is invalid")
    return (Path.cwd() / ".wiki-viva/upgrade/runs" / run_key).resolve()


def _verify_rollback_report(args: argparse.Namespace) -> int:
    run_dir = _resolve_verification_run(args)
    cwd = Path.cwd().resolve()
    try:
        run_dir.relative_to(cwd)
    except ValueError as exc:
        raise RunnerError(
            "unsafe_verification_root",
            "rollback verification must stay inside the consumer checkout",
            surface="rollback_report_verification",
        ) from exc
    report_path = run_dir / "migration-report.private.json"
    if not report_path.is_file():
        report_path = run_dir / "migration-report.candidate.json"
    if not report_path.is_file():
        report_path = run_dir / "migration-report.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        rollback = json.loads((run_dir / "rollback.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise RunnerError(
            "invalid_rollback_report",
            "rollback or migration report evidence is missing or malformed",
            surface="rollback_report_verification",
            next_action="rerun rollback verification through adopt",
        ) from exc
    claimed = rollback.get("evidence_sha256")
    unsigned = dict(rollback)
    unsigned.pop("evidence_sha256", None)
    budget = _validate_acceptance_budget_record(report.get("acceptance_budget"))
    valid = (
        report.get("schema_version") == REPORT_SCHEMA_VERSION
        and report.get("status") in {"candidate", "complete"}
        and rollback.get("schema_version") == ROLLBACK_SCHEMA_VERSION
        and rollback.get("provenance") == "executed"
        and rollback.get("status") == "verified"
        and rollback.get("tree_equal") is True
        and claimed == canonical_sha256(unsigned)
        and report.get("rollback_evidence_sha256") == claimed
        and report.get("identity", {}).get("consumer_C3") == rollback.get("subject_sha")
        and report.get("promotion_ready")
        is (report.get("status") == "complete" and budget["status"] == "met")
    )
    if not valid:
        raise RunnerError(
            "rollback_report_mismatch",
            "rollback and migration report evidence do not prove the same exact subject",
            surface="rollback_report_verification",
            next_action="block promotion and execute rollback/report generation again",
        )
    _emit(
        {
            "schema_version": "wiki_viva_upgrade_rollback_report_check.v1",
            "status": "verified",
            "lane": "lane_b",
            "surface": "rollback_report_verification",
            "evidence_sha256": claimed,
        }
    )
    return 0


def _receipt_result(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: result[key]
        for key in (
            "id",
            "class",
            "provenance",
            "status",
            "exit_code",
            "subject_sha",
            "command_sha256",
            "output_sha256",
        )
    }


def _adopt(args: argparse.Namespace) -> int:
    if args.mode != "canary":
        raise RunnerError(
            "unsupported_adoption_mode",
            "only the reversible canary adoption mode is supported",
            surface="canary",
        )
    if args.pause_before_canary and args.resume:
        raise RunnerError(
            "invalid_pause_resume_mode",
            "a resumed adoption cannot pause again before canary",
            surface="resume_state",
            next_action="remove --pause-before-canary when resuming the exact plan",
        )
    if args.pause_before_canary and args.pause_before_background:
        raise RunnerError(
            "invalid_pause_mode",
            "an adoption can pause at only one lane boundary per invocation",
            surface="resume_state",
            next_action="choose the fast-adoption or post-canary handoff boundary",
        )
    consumer = args.consumer_root.resolve()
    kit = args.kit_root.resolve()
    _require_v3_cli_package(args.package)
    plan_path = _require_ignored_output(consumer, args.plan)
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise RunnerError("invalid_plan_file", "the adoption plan is missing or malformed") from exc
    package, capsule, registry, verified_capsule = _load_artifacts(
        args.package,
        args.capsule,
        args.impact_registry,
        kit_root=kit,
        authority_path=args.authority,
        trusted_attestation_sha256=args.trusted_attestation_sha256,
    )
    _require_upgrade_branch(consumer, package)
    _verify_plan_digest(plan)
    _verify_acceptance_anchor(
        plan=plan,
        plan_path=plan_path,
        consumer=consumer,
        trusted_file_sha256=args.trusted_acceptance_anchor_sha256,
    )
    _validate_pre_mutation_plan(
        plan=plan,
        package=package,
        capsule=capsule,
        registry=registry,
        verified_capsule=verified_capsule,
        consumer=consumer,
        kit=kit,
    )
    if plan["selection"]["requires_lane_a"]:
        raise RunnerError(
            "lane_a_required",
            "impact is unknown or portable and requires a new Lane A capsule",
            lane="lane_a",
            surface="impact_derivation",
            next_action="run the full upstream certification lane, then generate a new adoption plan",
        )
    _emit(
        {
            "schema_version": "wiki_viva_upgrade_conceptual_diff.v1",
            "status": "reviewed_before_mutation",
            "lane": "lane_b",
            "conceptual_diff": plan["conceptual_diff"],
            "plan_sha256": plan["plan_sha256"],
        }
    )
    planned_mutation = plan.get("mutation")
    if isinstance(planned_mutation, dict) and planned_mutation.get("strategy") == "runner_owned":
        plan = _materialize_mutation_plan(
            preplan=plan,
            plan_path=plan_path,
            package=package,
            capsule=capsule,
            registry=registry,
            verified_capsule=verified_capsule,
            consumer=consumer,
            kit=kit,
            resume=args.resume,
        )
    _validate_current_plan(
        plan=plan,
        package=package,
        capsule=capsule,
        registry=registry,
        verified_capsule=verified_capsule,
        consumer=consumer,
        kit=kit,
    )
    if plan["status"] != "ready":
        raise RunnerError(
            "adoption_plan_not_ready",
            "the plan did not materialize an exact C1/C2/C3 execution subject",
            surface="commit_boundaries",
            next_action="complete or resume runner-owned mutation before executing gates",
        )
    run_key = plan["plan_sha256"][:16]
    run_dir = _require_ignored_output(
        consumer, Path(".wiki-viva/upgrade/runs") / run_key / "state.json"
    ).parent
    state_path = run_dir / "state.json"
    lock_path = run_dir / "run.lock"
    run_dir.mkdir(parents=True, exist_ok=True)
    with _run_lock(lock_path):
        canary_completion_anchor: dict[str, str] | None = None
        trusted_canary_completion_sha256 = (
            args.trusted_canary_completion_anchor_sha256
        )
        if state_path.exists():
            if not args.resume:
                raise RunnerError(
                    "resume_required",
                    "this exact plan already has resumable runner state",
                    surface="resume_state",
                    next_action="use --resume or generate a new plan identity",
                )
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError) as exc:
                raise RunnerError("invalid_resume_state", "the resume state is malformed") from exc
            _validate_resume_state(state, plan, run_dir)
            if state.get("status") == "complete":
                raise RunnerError(
                    "completed_run_not_resumable",
                    "a completed adoption receipt is historical evidence, not reusable promotion proof",
                    lane="lane_b",
                    surface="resume_state",
                    contract="never_reusable_gates",
                    next_action=(
                        "use the existing generated report for its original PR/human gate; "
                        "if policy requires reexecution, create a new consumer subject and plan identity"
                    ),
                )
            canary_was_complete = _completed_canary_at(state, plan) is not None
            (
                canary_completion_anchor,
                anchored_digest,
            ) = _record_completed_canary_budget(
                state,
                plan,
                state_path,
                run_dir,
                trusted_file_sha256=trusted_canary_completion_sha256,
                allow_anchor_create=False,
            )
            if anchored_digest is not None:
                trusted_canary_completion_sha256 = anchored_digest
            if state.get("status") != "complete":
                state["status"] = "running"
                _atomic_write(state_path, _json_bytes(state))
        else:
            state = _state_template(plan)
            canary_was_complete = False
            _atomic_write(state_path, _json_bytes(state))

        receipt_path = run_dir / "adoption-receipt.json"
        if state["status"] == "complete":
            raise RunnerError(
                "completed_run_not_resumable",
                "a completed adoption receipt is historical evidence, not reusable promotion proof",
                lane="lane_b",
                surface="resume_state",
                contract="never_reusable_gates",
                next_action=(
                    "use the existing generated report for its original PR/human gate; "
                    "if policy requires reexecution, create a new consumer subject and plan identity"
                ),
            )

        gates = [dict(item) for item in plan["gate_catalog"]]
        rollback_gate = [item for item in gates if item["id"] == "rollback_report_verification"]
        ordinary = [item for item in gates if item["id"] != "rollback_report_verification"]
        groups = [
            [item for item in ordinary if item["class"] in {"consumer_always", "affected", "upstream_certified"}],
            [item for item in ordinary if item["class"] == "canary"],
            [item for item in ordinary if item["class"] == "background_certification"],
        ]
        selected_ids = set(plan["selection"]["selected_gates"])
        groups_to_run = (
            groups[:1]
            if args.pause_before_canary
            else groups[:2]
            if args.pause_before_background
            else groups
        )
        for group in groups_to_run:
            _execute_phase_dag(
                group,
                selected_ids=selected_ids,
                state=state,
                state_path=state_path,
                consumer=consumer,
                kit=kit,
                run_dir=run_dir,
                subject_sha=plan["identity"]["consumer_C3"],
                public_release_sha=plan["identity"]["source_sha"],
                jobs=args.jobs,
                timeout=args.gate_timeout,
                heartbeat=args.heartbeat_seconds,
            )
        (
            current_completion_anchor,
            anchored_digest,
        ) = _record_completed_canary_budget(
            state,
            plan,
            state_path,
            run_dir,
            trusted_file_sha256=trusted_canary_completion_sha256,
            allow_anchor_create=not canary_was_complete,
        )
        if current_completion_anchor is not None:
            canary_completion_anchor = current_completion_anchor
        if anchored_digest is not None:
            trusted_canary_completion_sha256 = anchored_digest

        if args.pause_before_canary:
            state["status"] = "paused_before_canary"
            _atomic_write(state_path, _json_bytes(state))
            _emit(
                {
                    "schema_version": "wiki_viva_upgrade_adoption_summary.v1",
                    "status": "paused_before_canary",
                    "lane": "lane_b",
                    "resumed": False,
                    "reused_receipt": False,
                    "plan_sha256": plan["plan_sha256"],
                    "completed_gate_count": len(state["gate_results"]),
                    "promotion_ready": False,
                    "human_gate_required": True,
                    "next_action": "resume the exact plan in the canary lane",
                }
            )
            return 0

        if args.pause_before_background:
            selected_background = {
                item["id"]
                for item in groups[2]
                if item["id"] in selected_ids
            }
            if not selected_background:
                raise RunnerError(
                    "missing_background_handoff_work",
                    "the plan selects no background certification gate to resume",
                    lane="lane_b",
                    surface="background_certification",
                    next_action="continue the exact plan without a background pause",
                )
            state["status"] = "paused_before_background"
            _atomic_write(state_path, _json_bytes(state))
            _emit(
                {
                    "schema_version": "wiki_viva_upgrade_adoption_summary.v1",
                    "status": "paused_before_background",
                    "lane": "lane_b",
                    "resumed": bool(args.resume),
                    "reused_receipt": False,
                    "plan_sha256": plan["plan_sha256"],
                    "completed_gate_count": len(state["gate_results"]),
                    "pending_background_gates": sorted(selected_background),
                    "canary_completion_anchor_sha256": (
                        trusted_canary_completion_sha256
                    ),
                    "promotion_ready": False,
                    "human_gate_required": True,
                    "next_action": (
                        "resume the exact consumer handoff in the background "
                        "certification lane"
                    ),
                }
            )
            return 0

        rollback = _rollback_execution(consumer, plan)
        _atomic_write(run_dir / "rollback.json", _json_bytes(rollback))
        preliminary_results = [_receipt_result(value) for value in state["gate_results"].values()]
        candidate = _report(
            plan,
            preliminary_results,
            rollback,
            _empty_evidence(),
            state["acceptance_budget"],
            status="candidate",
        )
        _atomic_write(run_dir / "migration-report.candidate.json", _json_bytes(candidate))
        latest = _require_ignored_output(consumer, Path(".wiki-viva/upgrade/latest.json"))
        _atomic_write(latest, _json_bytes({"schema_version": "wiki_viva_upgrade_latest.v1", "run_key": run_key}))

        _execute_phase_dag(
            rollback_gate,
            selected_ids=selected_ids,
            state=state,
            state_path=state_path,
            consumer=consumer,
            kit=kit,
            run_dir=run_dir,
            subject_sha=plan["identity"]["consumer_C3"],
            public_release_sha=plan["identity"]["source_sha"],
            jobs=1,
            timeout=args.gate_timeout,
            heartbeat=args.heartbeat_seconds,
        )
        results = sorted(
            (_receipt_result(value) for value in state["gate_results"].values()),
            key=lambda item: item["id"],
        )
        if {item["id"] for item in results} != set(plan["selection"]["selected_gates"]):
            raise RunnerError(
                "selected_gate_coverage_mismatch",
                "executed results do not exactly cover the selected gate set",
                surface="gate_evidence",
                next_action="resume the exact plan until every selected gate executes",
            )
        evidence = _evidence_inventory(state)
        _require_evidence_contract(
            package,
            evidence,
            selected_gates=plan["selection"]["selected_gates"],
            gate_catalog=plan["gate_catalog"],
            subject_sha=plan["identity"]["consumer_C3"],
        )
        report = _report(
            plan,
            results,
            rollback,
            evidence,
            state["acceptance_budget"],
            status="complete",
        )
        report_bytes = _json_bytes(report)
        public_report = _public_report_projection(report)
        public_report_bytes = _json_bytes(public_report)
        _atomic_write(run_dir / "migration-report.private.json", report_bytes)
        _atomic_write(
            run_dir / "migration-report.private.md",
            _render_report(report).encode("utf-8"),
        )
        _atomic_write(run_dir / "migration-report.public.json", public_report_bytes)
        _atomic_write(
            run_dir / "migration-report.public.md",
            _render_report(public_report).encode("utf-8"),
        )
        # Stable default is the public-redacted projection.  Raw command logs
        # and the richer private report remain ignored sidecars.
        _atomic_write(run_dir / "migration-report.json", public_report_bytes)
        rollback_receipt = {
            "provenance": "executed",
            "status": "verified",
            "subject_sha": plan["identity"]["consumer_C3"],
            "evidence_sha256": rollback["evidence_sha256"],
        }
        report_receipt = {
            "provenance": "executed",
            "status": "verified",
            "subject_sha": plan["identity"]["consumer_C3"],
            "evidence_sha256": _sha256_bytes(report_bytes),
        }
        acceptance_budget = _validate_acceptance_budget_record(
            state["acceptance_budget"], expected_plan=plan
        )
        if (
            canary_completion_anchor is None
            or trusted_canary_completion_sha256 is None
        ):
            raise RunnerError(
                "missing_canary_completion_anchor",
                "final adoption evidence lacks external real-canary completion authority",
                lane="lane_b",
                surface="acceptance_budget",
            )
        receipt_status = (
            "passed" if acceptance_budget["status"] == "met" else "blocked"
        )
        receipt = seal_adoption_receipt(
            {
                "status": receipt_status,
                "identity": plan["identity"],
                "capsule_sha256": capsule["capsule_sha256"],
                "impact_registry_sha256": registry["registry_sha256"],
                "impact_derivation_sha256": plan["selection"]["derivation_sha256"],
                "plan_sha256": plan["plan_sha256"],
                "consumer_c3_authority_sha256": plan[
                    "consumer_c3_authority_sha256"
                ],
                "acceptance_budget": acceptance_budget,
                "canary_completion_anchor": canary_completion_anchor,
                "resume": {
                    "identity_sha256": canonical_sha256(plan["identity"]),
                    "plan_sha256": plan["plan_sha256"],
                    "completed_gates": sorted(plan["selection"]["selected_gates"]),
                },
                "boundary_commits": plan["boundary_commits"],
                "boundaries": plan["boundaries"],
                "gate_results": results,
                "omitted_gates": plan["omitted_gates"],
                "rollback_verification": rollback_receipt,
                "report_verification": report_receipt,
            }
        )
        _atomic_write(receipt_path, _json_bytes(receipt))
        state["status"] = "complete"
        _atomic_write(state_path, _json_bytes(state))
        try:
            verified_evidence = verify_adoption_evidence(
                receipt,
                authority=AdoptionEvidenceAuthority(
                    consumer_root=consumer,
                    run_root=run_dir,
                    trusted_canary_completion_anchor_sha256=(
                        trusted_canary_completion_sha256
                    ),
                ),
                package=package,
                registry=registry,
                selection=plan["selection"],
            )
            if receipt_status == "passed":
                verify_adoption_receipt(
                    receipt,
                    expected_identity=plan["identity"],
                    expected_plan_sha256=plan["plan_sha256"],
                    capsule=capsule,
                    verified_capsule=verified_capsule,
                    verified_evidence=verified_evidence,
                    package=package,
                    registry=registry,
                    selection=plan["selection"],
                    consumer_c3_authority=plan["consumer_c3_authority"],
                )
        except UpgradeLaneError as exc:
            state["status"] = "running"
            _atomic_write(state_path, _json_bytes(state))
            raise RunnerError(
                "adoption_evidence_rejected",
                "the generated receipt does not resolve to exact runner and Git evidence",
                surface="adoption_receipt",
                contract="rollback_report_verification",
                next_action="block promotion and rerun the exact plan evidence",
            ) from exc
        # Completion remains durable only after the receipt/evidence verifier
        # succeeds. A failed verifier restores the resumable running state.
    _emit(
        {
            "schema_version": "wiki_viva_upgrade_adoption_summary.v1",
            "status": "complete" if receipt_status == "passed" else "blocked",
            "lane": "lane_b",
            "resumed": bool(args.resume),
            "reused_receipt": False,
            "plan_sha256": plan["plan_sha256"],
            "selected_gate_count": len(results),
            "acceptance_budget": acceptance_budget,
            "canary_completion_anchor_sha256": (
                trusted_canary_completion_sha256
            ),
            "promotion_ready": receipt_status == "passed",
            "human_gate_required": True,
            "contract": "wiki_viva_upgrade_acceptance_budget.v1",
            "next_action": (
                "open the human-gated promotion PR"
                if receipt_status == "passed"
                else "inspect the Lane B bottleneck and run a new plan; do not promote"
            ),
        }
    )
    return 0 if receipt_status == "passed" else 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version",
        action="version",
        version=(
            "wiki-upgrade "
            + _runner_identity_version(Path(__file__).resolve().parents[1])
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    certify = subparsers.add_parser(
        "certify",
        help="execute and seal one immutable public Lane A certification",
    )
    certify.add_argument("--package", type=Path, required=True)
    certify.add_argument("--impact-registry", type=Path, required=True)
    certify.add_argument("--source-root", type=Path, required=True)
    certify.add_argument("--visual-root", type=Path, required=True)
    certify.add_argument("--visual-manifest-ref", required=True)
    certify.add_argument("--out-dir", type=Path, required=True)
    certify.add_argument("--attestation-authority-id", required=True)
    certify.add_argument("--run-id")
    certify.add_argument("--jobs", type=int, default=4)
    certify.add_argument("--gate-timeout", type=int, default=1200)
    certify.add_argument("--heartbeat-seconds", type=float, default=10.0)
    certify.set_defaults(handler=_certify)

    verify_capsule = subparsers.add_parser(
        "verify-capsule",
        help="verify one exact sealed public Lane A release authority",
    )
    verify_capsule.add_argument("--package", type=Path, required=True)
    verify_capsule.add_argument("--capsule", type=Path, required=True)
    verify_capsule.add_argument("--impact-registry", type=Path, required=True)
    verify_capsule.add_argument(
        "--authority",
        type=Path,
        required=True,
        help="sealed release authority bundle emitted by certify",
    )
    verify_capsule.add_argument(
        "--trusted-attestation-sha256",
        required=True,
        help="out-of-band SHA-256 trust anchor; never inferred from the capsule",
    )
    verify_capsule.add_argument("--kit-root", type=Path, required=True)
    verify_capsule.set_defaults(handler=_verify_capsule)

    plan = subparsers.add_parser("plan", help="compile a sealed read-only Lane B plan")
    plan.add_argument("--package", type=Path, required=True)
    plan.add_argument("--capsule", type=Path, required=True)
    plan.add_argument("--impact-registry", type=Path, required=True)
    plan.add_argument(
        "--authority",
        type=Path,
        required=True,
        help="release authority bundle with visual and gate-output evidence roots",
    )
    plan.add_argument(
        "--trusted-attestation-sha256",
        required=True,
        help="out-of-band SHA-256 trust anchor; never inferred from the capsule",
    )
    plan.add_argument("--consumer-root", type=Path, required=True)
    plan.add_argument("--kit-root", type=Path, default=ROOT)
    plan.add_argument("--changed-path", action="append", default=[])
    plan.add_argument("--changed-contract", action="append", default=[])
    plan.add_argument("--consumer-b0")
    plan.add_argument("--consumer-c1")
    plan.add_argument("--consumer-c2")
    plan.add_argument("--consumer-c3")
    plan.add_argument(
        "--preflight-command",
        action="append",
        default=[],
        metavar="ID::COMMAND",
        help="runner-executed read-only B0 command for a package preflight gate",
    )
    plan.add_argument(
        "--c2-generator-command",
        action="append",
        default=[],
        metavar="ID::COMMAND",
        help=(
            "safe command replayed in a disposable C1 clone; repeat as needed "
            "to prove every non-empty C2 artifact byte-for-byte"
        ),
    )
    plan.add_argument(
        "--c3-adapter-command",
        action="append",
        default=[],
        metavar="ID::COMMAND",
        help=(
            "consumer-owned adapter/config/test command executed by adopt after C2; "
            "repeat as needed"
        ),
    )
    plan.add_argument("--out", type=Path)
    plan.set_defaults(handler=_plan)

    adopt = subparsers.add_parser("adopt", help="execute/resume a sealed adoption plan")
    adopt.add_argument("--plan", type=Path, required=True)
    adopt.add_argument("--package", type=Path, required=True)
    adopt.add_argument("--capsule", type=Path, required=True)
    adopt.add_argument("--impact-registry", type=Path, required=True)
    adopt.add_argument("--authority", type=Path, required=True)
    adopt.add_argument("--trusted-attestation-sha256", required=True)
    adopt.add_argument(
        "--trusted-acceptance-anchor-sha256",
        required=True,
        help="out-of-band SHA-256 emitted by the original plan command",
    )
    adopt.add_argument(
        "--trusted-canary-completion-anchor-sha256",
        help=(
            "out-of-band SHA-256 emitted when the exact run first completes "
            "the real canary; required to resume a post-canary run"
        ),
    )
    adopt.add_argument("--consumer-root", type=Path, required=True)
    adopt.add_argument("--kit-root", type=Path, required=True)
    adopt.add_argument("--mode", choices=["canary"], default="canary")
    adopt.add_argument("--resume", action="store_true")
    adopt.add_argument(
        "--pause-before-canary",
        action="store_true",
        help=(
            "execute C1/C2/C3 plus fast consumer gates, persist exact state, "
            "and stop before canary/background/rollback-report verification"
        ),
    )
    adopt.add_argument(
        "--pause-before-background",
        action="store_true",
        help=(
            "execute through the real canary, persist the exact consumer state, "
            "and stop before consumer-owned background gates and final reports"
        ),
    )
    adopt.add_argument("--jobs", type=int, default=4)
    adopt.add_argument("--gate-timeout", type=int, default=1200)
    adopt.add_argument("--heartbeat-seconds", type=float, default=10.0)
    adopt.set_defaults(handler=_adopt)

    verify = subparsers.add_parser(
        "verify-rollback-report",
        help="verify the executed rollback and generated report pair",
    )
    verify.add_argument("--check", action="store_true")
    verify.add_argument("--run-dir", type=Path, help=argparse.SUPPRESS)
    verify.set_defaults(handler=_verify_rollback_report)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if getattr(args, "jobs", 1) < 1 or getattr(args, "jobs", 1) > 16:
        parser.error("--jobs must be between 1 and 16")
    if getattr(args, "gate_timeout", 1) < 1:
        parser.error("--gate-timeout must be positive")
    if getattr(args, "heartbeat_seconds", 1.0) <= 0:
        parser.error("--heartbeat-seconds must be positive")
    try:
        return int(args.handler(args))
    except RunnerError as error:
        _emit(_failure_payload(error))
        return 2
    except UpgradeLaneError:
        error = RunnerError(
            "verified_contract_rejected",
            "a sealed Lane A or Lane B contract failed closed validation",
            next_action="discard stale evidence and regenerate it through the runner",
        )
        _emit(_failure_payload(error))
        return 2
    except KeyboardInterrupt:
        error = RunnerError(
            "interrupted_resumable_run",
            "execution was interrupted; completed exact-subject results remain resumable",
            surface="resume_state",
            next_action="rerun adopt with --resume and the same exact inputs",
        )
        _emit(_failure_payload(error))
        return 130
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        error = RunnerError(
            "invalid_or_unavailable_input",
            "an input or runtime dependency could not be validated safely",
            next_action="repair the named plan inputs without changing scope, then retry",
        )
        _emit(_failure_payload(error))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
