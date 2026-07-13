"""Fail-closed contracts for two-lane downstream upgrades.

Lane A certifies one immutable portable release and emits a canonical capsule.
Lane B plans and proves the exact consumer delta.  This module is deliberately
deterministic: it does not mutate repositories, execute gates or contain an LLM
client.  It validates the evidence produced by a future resumable runner.
"""

from __future__ import annotations

import copy
import fnmatch
import hashlib
import json
import math
import os
import re
import stat
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml
from jsonschema import Draft202012Validator

from wiki_core.detectors import scan_text


RELEASE_CAPSULE_SCHEMA_VERSION = "wiki_viva_upgrade_release_capsule.v1"
IMPACT_REGISTRY_SCHEMA_VERSION = "wiki_viva_upgrade_impact_registry.v1"
ADOPTION_RECEIPT_SCHEMA_VERSION = "wiki_viva_upgrade_adoption_receipt.v1"
EXECUTION_ATTESTATION_SCHEMA_VERSION = "wiki_viva_upgrade_execution_attestation.v1"
TOOLCHAIN_PROBE_SCHEMA_VERSION = "wiki_viva_toolchain_probe.v1"

GATE_CLASSES = (
    "upstream_certified",
    "consumer_always",
    "affected",
    "canary",
    "background_certification",
)

# These current-consumer invariants are intentionally independent of Lane A:
# no capsule or impact derivation may turn them into reusable proof.
NEVER_REUSABLE_GATES = frozenset(
    {
        "audit",
        "public_evidence_redaction",
        "input_stage",
        "operational_pass",
        "semantic_inventory",
        "adapter_identity",
        "snapshot_contract",
        "real_canary",
        "diff_check",
        "rollback_report_verification",
    }
)

_ROOT = Path(__file__).resolve().parents[1]
RELEASE_CAPSULE_SCHEMA_PATH = (
    _ROOT
    / "docs/references/schemas/wiki-upgrade-release-capsule-v1.schema.json"
)
IMPACT_REGISTRY_SCHEMA_PATH = (
    _ROOT
    / "docs/references/schemas/wiki-upgrade-impact-registry-v1.schema.json"
)

_SHA_RE = re.compile(r"^[0-9a-f]{40,64}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{1,127}$")
_CONTRACT_RE = re.compile(r"^[a-z][a-z0-9_.:+-]{1,127}$")
_LOCAL_PATH_RE = re.compile(
    r"(?:/Users/|/home/|file://|(?<![\w.-])~[/\\]|[A-Za-z]:\\|\\\\[^\\\s]+\\)"
)
_PRIVATE_PATH_RE = re.compile(
    r"(?:^|[/\\])(?:private|data[/\\]raw|data[/\\]derived)(?:[/\\]|$)",
    re.IGNORECASE,
)
_PRIVATE_ROUTE_RE = re.compile(r"^/(?:private|consumer|real)(?:/|$)", re.IGNORECASE)
_PLACEHOLDER_COMMAND_RE = re.compile(
    r"(?i)(?:\b(?:todo|tbd|placeholder|replace[_ -]?with|manual|fabricated)\b|"
    r"^\s*(?:true|:|exit\s+0|echo\b.*)\s*$)"
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(?:api[_-]?key|secret|token|password|passwd|cookie|authorization)"
    r"\s*[:=]\s*[^\s,;]+"
)
_IDENTITY_FIELDS = (
    "source_sha",
    "package_sha256",
    "portable_tree_sha256",
    "consumer_B0",
    "consumer_C3",
    "command_registry_sha256",
    "toolchain_sha256",
)
_UPSTREAM_IDENTITY_FIELDS = (
    "source_sha",
    "package_sha256",
    "portable_tree_sha256",
    "command_registry_sha256",
    "toolchain_sha256",
)
_RECEIPT_FIELDS = {
    "schema_version",
    "status",
    "identity",
    "identity_sha256",
    "capsule_sha256",
    "impact_registry_sha256",
    "impact_derivation_sha256",
    "plan_sha256",
    "resume",
    "boundaries",
    "gate_results",
    "omitted_gates",
    "rollback_verification",
    "report_verification",
    "receipt_sha256",
}
_ATTESTATION_AUTHORITY = object()
_ADOPTION_EVIDENCE_AUTHORITY = object()


@dataclass(frozen=True)
class ReleaseCapsuleAuthority:
    """External inputs required to verify one Lane A capsule.

    ``verified_attestation_sha256`` is a trust anchor supplied by the CI/release
    authority, not a digest read from the capsule itself.  A caller without
    that external value cannot seal or verify production evidence.
    """

    package: Mapping[str, Any]
    impact_registry: Mapping[str, Any]
    source_root: Path
    visual_root: Path
    gate_output_root: Path
    verified_attestation_sha256: str


@dataclass(frozen=True)
class VerifiedReleaseCapsule:
    """Opaque proof that capsule artifacts were recomputed and attested."""

    digest: str
    source_sha: str
    package_sha256: str
    portable_tree_sha256: str
    visual_manifest_sha256: str
    attestation_sha256: str
    _authority: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._authority is not _ATTESTATION_AUTHORITY:
            raise TypeError(
                "VerifiedReleaseCapsule can only be created by fail-closed verification"
            )


@dataclass(frozen=True)
class AdoptionEvidenceAuthority:
    """Local exact-subject roots used to verify one Lane B execution run."""

    consumer_root: Path
    run_root: Path


@dataclass(frozen=True)
class VerifiedAdoptionEvidence:
    """Opaque proof that receipt hashes resolve to real run and Git artifacts."""

    receipt_digest: str
    consumer_C3: str
    gate_results_sha256: str
    state_sha256: str
    rollback_sha256: str
    private_report_sha256: str
    public_report_sha256: str
    _authority: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._authority is not _ADOPTION_EVIDENCE_AUTHORITY:
            raise TypeError(
                "VerifiedAdoptionEvidence can only be created by fail-closed verification"
            )


class UpgradeLaneError(ValueError):
    """Raised when a two-lane upgrade contract cannot be proved exactly."""


def load_mapping(path: Path) -> dict[str, Any]:
    """Load a JSON/YAML mapping without accepting non-object roots."""

    text = path.read_text(encoding="utf-8")
    payload = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
    if not isinstance(payload, dict):
        raise UpgradeLaneError(f"{path}: expected a mapping root")
    return payload


def _finite_json(value: Any, *, active: set[int] | None = None, depth: int = 0) -> bool:
    if depth > 128:
        return False
    if value is None or isinstance(value, (str, bool, int)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if not isinstance(value, (dict, list)):
        return False
    seen = active if active is not None else set()
    identity = id(value)
    if identity in seen:
        return False
    seen.add(identity)
    try:
        if isinstance(value, dict):
            return all(
                isinstance(key, str)
                and _finite_json(item, active=seen, depth=depth + 1)
                for key, item in value.items()
            )
        return all(_finite_json(item, active=seen, depth=depth + 1) for item in value)
    finally:
        seen.remove(identity)


def canonical_json(value: Any) -> str:
    """Return the one canonical representation used by every lane digest."""

    if not _finite_json(value):
        raise UpgradeLaneError("payload must be finite, acyclic JSON data")
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _schema_errors(payload: Mapping[str, Any], schema_path: Path) -> list[str]:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = Draft202012Validator(schema).iter_errors(payload)
    return [
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(errors, key=lambda item: list(item.absolute_path))
    ]


def _require_schema(payload: Mapping[str, Any], schema_path: Path, *, label: str) -> None:
    errors = _schema_errors(payload, schema_path)
    if errors:
        raise UpgradeLaneError(f"{label} schema rejected: {'; '.join(errors)}")


def _require_exact_keys(payload: Mapping[str, Any], expected: set[str], *, label: str) -> None:
    actual = set(payload)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise UpgradeLaneError(
            f"{label} fields must be exact; missing={missing}, extra={extra}"
        )


def _assert_sha(value: object, *, label: str, sha256: bool = False) -> str:
    pattern = _SHA256_RE if sha256 else _SHA_RE
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        kind = "SHA-256" if sha256 else "Git/SHA digest"
        raise UpgradeLaneError(f"{label} must be a lowercase {kind}")
    return value


def _canonical_repo_path(raw: object, *, label: str, allow_glob: bool = False) -> str:
    if not isinstance(raw, str) or not raw or raw != raw.strip():
        raise UpgradeLaneError(f"{label} must be a non-empty canonical path")
    if (
        raw.startswith(("/", "~"))
        or "\\" in raw
        or "//" in raw
        or "\x00" in raw
        or any(part in {"", ".", ".."} for part in raw.split("/"))
        or (not allow_glob and any(character in raw for character in "*?[]"))
    ):
        raise UpgradeLaneError(f"{label} must be one repo-relative POSIX path")
    return raw


def _walk_strings(value: Any, *, key: str = "") -> Iterable[tuple[str, str]]:
    if isinstance(value, dict):
        for child_key, child in value.items():
            yield from _walk_strings(child, key=str(child_key))
    elif isinstance(value, list):
        for child in value:
            yield from _walk_strings(child, key=key)
    elif isinstance(value, str):
        yield key, value


def _assert_public_safe_payload(payload: Mapping[str, Any], *, label: str) -> None:
    """Reject host paths, private evidence roots, private routes and secrets."""

    for key, value in _walk_strings(payload):
        if _LOCAL_PATH_RE.search(value):
            raise UpgradeLaneError(f"{label} contains a host-local path")
        if _SECRET_ASSIGNMENT_RE.search(value):
            raise UpgradeLaneError(f"{label} contains secret/private data")
        if _PRIVATE_PATH_RE.search(value):
            raise UpgradeLaneError(f"{label} contains a private evidence path")
        if "route" in key and _PRIVATE_ROUTE_RE.match(value):
            raise UpgradeLaneError(f"{label} contains a private consumer route")
    masked = re.sub(
        r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{64}|[0-9A-Fa-f]{40})(?![0-9A-Fa-f])",
        "<digest>",
        canonical_json(payload),
    )
    findings = [
        finding
        for finding in scan_text(masked)
        if finding.category in {"secret", "pii"}
    ]
    if findings:
        kinds = ", ".join(sorted({finding.kind for finding in findings}))
        raise UpgradeLaneError(f"{label} contains secret/private data: {kinds}")


def _unique_ids(items: Sequence[Mapping[str, Any]], *, label: str) -> list[str]:
    ids = [str(item.get("id", "")) for item in items]
    if len(ids) != len(set(ids)):
        raise UpgradeLaneError(f"{label} IDs must be unique")
    if ids != sorted(ids):
        raise UpgradeLaneError(f"{label} must be sorted by id")
    return ids


def _command_digest(command: str) -> str:
    return hashlib.sha256(command.encode("utf-8")).hexdigest()


def _git_bytes(root: Path, arguments: Sequence[str], *, label: str) -> bytes:
    environment = dict(os.environ)
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        env=environment,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise UpgradeLaneError(f"{label} could not be read from exact Git authority")
    return result.stdout


def _safe_file_bytes(root: Path, raw_path: object, *, label: str) -> tuple[str, bytes]:
    relative = _canonical_repo_path(raw_path, label=f"{label} path")
    root = root.resolve(strict=True)
    current = root
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink():
            raise UpgradeLaneError(f"{label} must not traverse a symlink")
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(root)
    except (FileNotFoundError, ValueError) as exc:
        raise UpgradeLaneError(f"{label} is missing or outside its evidence root") from exc
    before = resolved.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise UpgradeLaneError(f"{label} must be one regular, non-hard-linked file")
    if before.st_size > 64 * 1024 * 1024:
        raise UpgradeLaneError(f"{label} exceeds the evidence size limit")
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
        raise UpgradeLaneError(f"{label} changed while it was read")
    return relative, raw


def _portable_tree_metadata(
    *, package: Mapping[str, Any], source_root: Path, source_sha: str
) -> tuple[str, int]:
    release = package.get("release")
    portable = package.get("portable_import")
    if not isinstance(release, Mapping) or not isinstance(portable, Mapping):
        raise UpgradeLaneError("release package omits release/portable_import authority")
    if release.get("source_sha") != source_sha:
        raise UpgradeLaneError("release package and capsule source_sha differ")
    allow = portable.get("allow")
    block = portable.get("block")
    if (
        not isinstance(allow, list)
        or not allow
        or not isinstance(block, list)
        or not block
        or any(not isinstance(value, str) for value in [*allow, *block])
    ):
        raise UpgradeLaneError("portable allow/block authority is incomplete")
    for group, patterns in (("allow", allow), ("block", block)):
        for pattern in patterns:
            _canonical_repo_path(
                pattern, label=f"portable {group} pattern", allow_glob=True
            )
            if pattern in {"*", "**", "**/*"}:
                raise UpgradeLaneError(f"portable {group} pattern is repository-wide")
    source_root = source_root.resolve(strict=True)
    top = _git_bytes(
        source_root, ["rev-parse", "--show-toplevel"], label="source repository"
    ).decode("utf-8", "strict").strip()
    if Path(top).resolve() != source_root:
        raise UpgradeLaneError("source_root must be the exact Git repository root")
    resolved_sha = _git_bytes(
        source_root,
        ["rev-parse", "--verify", f"{source_sha}^{{commit}}"],
        label="source subject",
    ).decode("ascii", "strict").strip()
    if resolved_sha != source_sha:
        raise UpgradeLaneError("source_sha must be the exact full Git commit")
    listing = _git_bytes(
        source_root,
        ["ls-tree", "-r", "-z", "--full-tree", source_sha],
        label="portable source tree",
    )
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in listing.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, object_type, object_id = metadata.decode("ascii").split(" ", 2)
            path = raw_path.decode("utf-8", "strict")
        except (ValueError, UnicodeDecodeError) as exc:
            raise UpgradeLaneError("portable Git tree contains an invalid entry") from exc
        _canonical_repo_path(path, label="portable Git path")
        if path in seen:
            raise UpgradeLaneError("portable Git tree contains duplicate paths")
        seen.add(path)
        if any(fnmatch.fnmatchcase(path, pattern) for pattern in block):
            continue
        if not any(fnmatch.fnmatchcase(path, pattern) for pattern in allow):
            continue
        if object_type != "blob" or mode not in {"100644", "100755"}:
            raise UpgradeLaneError("portable tree contains a symlink/submodule/special entry")
        raw = _git_bytes(
            source_root, ["cat-file", "blob", object_id], label="portable blob"
        )
        entries.append(
            {
                "path": path,
                "mode": mode,
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    entries.sort(key=lambda item: item["path"])
    if not entries:
        raise UpgradeLaneError("portable allowlist selects no files at source_sha")
    attestation = {
        "schema_version": "wiki_viva_portable_tree.v1",
        "source_sha": source_sha,
        "package_sha256": canonical_sha256(package),
        "allow": allow,
        "block": block,
        "entries": entries,
    }
    return canonical_sha256(attestation), len(entries)


def _visual_manifest_metadata(
    *, visual_root: Path, manifest_ref: object
) -> tuple[str, int]:
    relative, raw = _safe_file_bytes(
        visual_root, manifest_ref, label="visual evidence manifest"
    )
    if not relative.endswith(".json"):
        raise UpgradeLaneError("visual evidence manifest must be JSON")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpgradeLaneError("visual evidence manifest is not valid UTF-8 JSON") from exc
    if not isinstance(payload, Mapping) or set(payload) != {
        "schema_version",
        "entries",
    }:
        raise UpgradeLaneError("visual evidence manifest fields are invalid")
    if payload.get("schema_version") != "wiki_visual_evidence_manifest.v1":
        raise UpgradeLaneError("visual evidence manifest schema is invalid")
    entries = payload.get("entries")
    required = {
        "id",
        "path",
        "sha256",
        "bytes",
        "route",
        "browser",
        "viewport",
        "capture_dimensions",
        "state",
        "public_synthetic",
    }
    if not isinstance(entries, list) or not entries or len(entries) > 256:
        raise UpgradeLaneError("visual evidence manifest entry count is invalid")
    ids: list[str] = []
    try:
        from wiki_core.release_receipt import (
            ReleaseReceiptError,
            visual_evidence_file_metadata,
        )
    except ImportError as exc:
        raise UpgradeLaneError("strict visual evidence verifier is unavailable") from exc
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping) or set(entry) != required:
            raise UpgradeLaneError(f"visual evidence entry {index} fields are invalid")
        entry_id = str(entry.get("id") or "")
        ids.append(entry_id)
        viewport = entry.get("viewport")
        if (
            _ID_RE.fullmatch(entry_id) is None
            or entry.get("public_synthetic") is not True
            or entry.get("browser") not in {"chromium", "firefox", "webkit"}
            or not isinstance(entry.get("route"), str)
            or not str(entry["route"]).startswith("/demo/")
            or not isinstance(viewport, Mapping)
            or set(viewport) != {"width", "height"}
            or any(
                isinstance(viewport.get(axis), bool)
                or not isinstance(viewport.get(axis), int)
                or not 240 <= viewport.get(axis) <= 7680
                for axis in ("width", "height")
            )
            or _ID_RE.fullmatch(str(entry.get("state") or "")) is None
        ):
            raise UpgradeLaneError(f"visual evidence entry {index} is not public-synthetic")
        try:
            metadata = visual_evidence_file_metadata(
                visual_root,
                entry.get("path"),
                label=f"visual evidence image {entry_id}",
            )
        except (ReleaseReceiptError, OSError, ValueError) as exc:
            raise UpgradeLaneError(
                f"visual evidence image {entry_id} failed strict verification"
            ) from exc
        if (
            metadata["sha256"] != entry.get("sha256")
            or metadata["bytes"] != entry.get("bytes")
            or metadata["dimensions"] != entry.get("capture_dimensions")
        ):
            raise UpgradeLaneError(
                f"visual evidence image {entry_id} hash/bytes/dimensions differ"
            )
    if ids != sorted(set(ids)):
        raise UpgradeLaneError("visual evidence manifest IDs must be sorted and unique")
    _assert_public_safe_payload(dict(payload), label="visual evidence manifest")
    return hashlib.sha256(raw).hexdigest(), len(entries)


def _gate_output_metadata(
    *, gate_output_root: Path, output_ref: object, gate_id: str
) -> dict[str, Any]:
    relative, raw = _safe_file_bytes(
        gate_output_root, output_ref, label=f"gate output {gate_id}"
    )
    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise UpgradeLaneError(f"gate output {gate_id} must be UTF-8 text") from exc
    if "\x00" in text:
        raise UpgradeLaneError(f"gate output {gate_id} contains binary data")
    _assert_public_safe_payload({"output": text}, label=f"gate output {gate_id}")
    return {
        "output_ref": relative,
        "output_sha256": hashlib.sha256(raw).hexdigest(),
        "output_bytes": len(raw),
    }


def _toolchain_probe_metadata(
    *, gate_output_root: Path, probe_ref: object, run_id: object
) -> tuple[str, int, dict[str, dict[str, str]], list[dict[str, Any]]]:
    relative, raw = _safe_file_bytes(
        gate_output_root, probe_ref, label="toolchain probe manifest"
    )
    if not relative.endswith(".json"):
        raise UpgradeLaneError("toolchain probe manifest must be JSON")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpgradeLaneError("toolchain probe manifest is not valid UTF-8 JSON") from exc
    if not isinstance(payload, Mapping) or set(payload) != {
        "schema_version",
        "run_id",
        "entries",
    }:
        raise UpgradeLaneError("toolchain probe manifest fields are invalid")
    if (
        payload.get("schema_version") != TOOLCHAIN_PROBE_SCHEMA_VERSION
        or payload.get("run_id") != run_id
    ):
        raise UpgradeLaneError("toolchain probe manifest belongs to another run")
    entries = payload.get("entries")
    expected_ids = ["browser", "node", "python", "runner"]
    required = {
        "id",
        "name",
        "version",
        "provenance",
        "probe_argv",
        "exit_code",
        "output_ref",
        "output_sha256",
        "output_bytes",
    }
    if not isinstance(entries, list) or len(entries) != len(expected_ids):
        raise UpgradeLaneError("toolchain probe must cover four exact tools")
    tools: dict[str, dict[str, str]] = {}
    bindings: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping) or set(entry) != required:
            raise UpgradeLaneError(f"toolchain probe entry {index} fields are invalid")
        tool_id = entry.get("id")
        name = entry.get("name")
        version = entry.get("version")
        argv = entry.get("probe_argv")
        if (
            tool_id != expected_ids[index]
            or not isinstance(name, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", name) is None
            or not isinstance(version, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}", version) is None
            or entry.get("provenance") != "executed"
            or entry.get("exit_code") != 0
            or not isinstance(argv, list)
            or not argv
            or any(
                not isinstance(argument, str)
                or not argument
                or "\x00" in argument
                or "\n" in argument
                or argument in {"sh", "bash", "zsh", "-c"}
                for argument in argv
            )
        ):
            raise UpgradeLaneError(f"toolchain probe entry {index} is not executed/exact")
        metadata = _gate_output_metadata(
            gate_output_root=gate_output_root,
            output_ref=entry.get("output_ref"),
            gate_id=f"toolchain-{tool_id}",
        )
        if any(entry.get(field) != metadata[field] for field in metadata):
            raise UpgradeLaneError(f"toolchain probe output binding mismatch: {tool_id}")
        _relative, output = _safe_file_bytes(
            gate_output_root,
            entry.get("output_ref"),
            label=f"toolchain probe output {tool_id}",
        )
        text = output.decode("utf-8", "strict")
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(version)}(?![A-Za-z0-9])", text) is None:
            raise UpgradeLaneError(
                f"toolchain probe output does not contain declared version: {tool_id}"
            )
        tools[str(tool_id)] = {"name": name, "version": version}
        bindings.append(
            {
                "id": tool_id,
                "name": name,
                "version": version,
                "provenance": "executed",
                "probe_argv": list(argv),
                "exit_code": 0,
                **metadata,
            }
        )
    _assert_public_safe_payload(dict(payload), label="toolchain probe manifest")
    return hashlib.sha256(raw).hexdigest(), len(entries), tools, bindings


def _verify_package_registry_contract(
    *,
    package: Mapping[str, Any],
    impact_registry: Mapping[str, Any],
    command_registry: Sequence[Mapping[str, Any]],
    release_id: object,
) -> str:
    """Bind package policy, versioned impact registry and capsule commands."""

    if package.get("schema_version") != "wiki_viva_upgrade_package.v3":
        raise UpgradeLaneError("Lane A capsule requires an exact v3 upgrade package")
    release = package.get("release")
    try:
        from wiki_core.upgrade import boundary_operations_sha256, package_is_pinned
    except ImportError as exc:
        raise UpgradeLaneError("package pinning verifier is unavailable") from exc
    if (
        not isinstance(release, Mapping)
        or release.get("id") != release_id
        or not package_is_pinned(dict(package))
    ):
        raise UpgradeLaneError(
            "capsule package is invalid, release_id differs, or release is not "
            "pinned/releasable"
        )
    registry_sha256 = verify_impact_registry(impact_registry)
    registered = [dict(item) for item in impact_registry["gate_catalog"]]
    if list(command_registry) != registered:
        raise UpgradeLaneError(
            "capsule command registry differs from versioned impact registry"
        )
    migration = package.get("migration")
    if not isinstance(migration, Mapping):
        raise UpgradeLaneError("v3 package omits migration gate policy")
    required = migration.get("required_gates")
    commands = migration.get("gate_commands")
    policies = migration.get("gate_policies")
    impact = migration.get("impact_registry")
    ids = [item["id"] for item in registered]
    if (
        required != ids
        or not isinstance(commands, Mapping)
        or set(commands) != set(ids)
        or not isinstance(policies, Mapping)
        or set(policies) != set(ids)
    ):
        raise UpgradeLaneError(
            "package required gates/commands/policies differ from impact registry"
        )
    for item in registered:
        gate_id = item["id"]
        policy = policies[gate_id]
        if (
            commands.get(gate_id) != item["command"]
            or not isinstance(policy, Mapping)
            or policy.get("class") != item["class"]
            or policy.get("command_id") != gate_id
        ):
            raise UpgradeLaneError(
                f"package command/class identity differs for gate: {gate_id}"
            )
    if migration.get("command_registry_sha256") != canonical_sha256(registered):
        raise UpgradeLaneError(
            "package command registry digest differs from impact registry"
        )
    if (
        not isinstance(impact, Mapping)
        or impact.get("schema_version") != IMPACT_REGISTRY_SCHEMA_VERSION
        or impact.get("sha256") != registry_sha256
    ):
        raise UpgradeLaneError("package impact registry digest is stale")
    portable = package.get("portable_import")
    boundary = migration.get("boundary_operations")
    boundary_policy = impact_registry["boundary_policy"]
    if (
        not isinstance(portable, Mapping)
        or sorted(portable.get("allow") or [])
        != sorted(boundary_policy["c1_portable_patterns"])
        or not isinstance(boundary, Mapping)
    ):
        raise UpgradeLaneError("package C1 ownership differs from impact registry")
    generators = boundary.get("c2_generators")
    c3_adapter = boundary.get("c3_adapter")
    if not isinstance(generators, list) or not isinstance(c3_adapter, Mapping):
        raise UpgradeLaneError("package boundary operations are incomplete")
    if (
        set(boundary)
        != {"schema_version", "c2_generators", "c3_adapter", "registry_sha256"}
        or boundary.get("schema_version")
        != "wiki_viva_upgrade_boundary_operations.v1"
        or boundary_operations_sha256(boundary) != boundary.get("registry_sha256")
    ):
        raise UpgradeLaneError("package boundary operations digest is invalid")
    c2_patterns = sorted(
        pattern
        for generator in generators
        if isinstance(generator, Mapping)
        for pattern in generator.get("owns_patterns") or []
    )
    if c2_patterns != sorted(boundary_policy["c2_generated_patterns"]):
        raise UpgradeLaneError("package C2 ownership differs from impact registry")
    if sorted(c3_adapter.get("owns_patterns") or []) != sorted(
        boundary_policy["c3_consumer_patterns"]
    ):
        raise UpgradeLaneError("package C3 ownership differs from impact registry")
    return registry_sha256


def collect_release_attestation(
    payload: Mapping[str, Any],
    *,
    package: Mapping[str, Any],
    impact_registry: Mapping[str, Any],
    source_root: Path,
    visual_root: Path,
    gate_output_root: Path,
) -> dict[str, Any]:
    """Recompute the public evidence an external Lane A authority must attest."""

    capsule = copy.deepcopy(dict(payload))
    registry = capsule.get("command_registry")
    gates = capsule.get("certified_gates")
    if not isinstance(registry, list) or not all(isinstance(item, Mapping) for item in registry):
        raise UpgradeLaneError("release capsule command_registry must be a list of mappings")
    if not isinstance(gates, list) or not gates or not all(isinstance(item, Mapping) for item in gates):
        raise UpgradeLaneError("release capsule certified_gates must be a non-empty mapping list")
    registry = sorted((dict(item) for item in registry), key=lambda item: str(item.get("id", "")))
    gates = sorted((dict(item) for item in gates), key=lambda item: str(item.get("id", "")))
    command_registry_sha256 = canonical_sha256(registry)
    _verify_package_registry_contract(
        package=package,
        impact_registry=impact_registry,
        command_registry=registry,
        release_id=capsule.get("release_id"),
    )
    (
        toolchain_probe_sha256,
        toolchain_probe_count,
        toolchain,
        toolchain_probes,
    ) = _toolchain_probe_metadata(
        gate_output_root=gate_output_root,
        probe_ref=capsule.get("toolchain_probe_ref"),
        run_id=capsule.get("run_id"),
    )
    toolchain_sha256 = canonical_sha256(toolchain)
    source_sha = _assert_sha(capsule.get("source_sha"), label="capsule source_sha")
    package_sha256 = canonical_sha256(package)
    portable_tree_sha256, portable_count = _portable_tree_metadata(
        package=package, source_root=source_root, source_sha=source_sha
    )
    visual_manifest_sha256, visual_count = _visual_manifest_metadata(
        visual_root=visual_root,
        manifest_ref=capsule.get("visual_manifest_ref"),
    )
    command_by_id = {item["id"]: item for item in registry}
    outputs: list[dict[str, Any]] = []
    for gate in gates:
        gate_id = str(gate.get("id") or "")
        registered = command_by_id.get(gate_id)
        if (
            registered is None
            or registered.get("class") != "upstream_certified"
            or gate.get("class") != "upstream_certified"
            or gate.get("provenance") != "executed"
            or gate.get("status") != "passed"
            or gate.get("exit_code") != 0
            or gate.get("subject_sha") != source_sha
            or gate.get("command_sha256")
            != _command_digest(str(registered.get("command") or ""))
        ):
            raise UpgradeLaneError(
                f"gate {gate_id or '<missing>'} lacks exact executed Lane A identity"
            )
        metadata = _gate_output_metadata(
            gate_output_root=gate_output_root,
            output_ref=gate.get("output_ref"),
            gate_id=gate_id,
        )
        outputs.append(
            {
                "id": gate_id,
                "provenance": "executed",
                "status": "passed",
                "exit_code": 0,
                "subject_sha": source_sha,
                "command_sha256": gate["command_sha256"],
                **metadata,
            }
        )
    expected_upstream = {
        item["id"] for item in registry if item.get("class") == "upstream_certified"
    }
    if {item["id"] for item in outputs} != expected_upstream:
        raise UpgradeLaneError("attestation must cover every upstream-certified gate")
    return {
        "schema_version": EXECUTION_ATTESTATION_SCHEMA_VERSION,
        "authority": {
            "kind": "external_sha256",
            "id": str(capsule.get("attestation_authority_id") or ""),
        },
        "run_id": str(capsule.get("run_id") or ""),
        "release_id": str(capsule.get("release_id") or ""),
        "source_sha": source_sha,
        "package_sha256": package_sha256,
        "portable_tree_sha256": portable_tree_sha256,
        "portable_tree_entry_count": portable_count,
        "visual_manifest_sha256": visual_manifest_sha256,
        "visual_manifest_entry_count": visual_count,
        "command_registry_sha256": command_registry_sha256,
        "toolchain": toolchain,
        "toolchain_sha256": toolchain_sha256,
        "toolchain_probe_sha256": toolchain_probe_sha256,
        "toolchain_probe_entry_count": toolchain_probe_count,
        "toolchain_probes": toolchain_probes,
        "gate_outputs": outputs,
    }


def _require_authority(authority: ReleaseCapsuleAuthority | None) -> ReleaseCapsuleAuthority:
    if not isinstance(authority, ReleaseCapsuleAuthority):
        raise UpgradeLaneError(
            "release capsule requires exact package/tree/visual/output authority and external attestation"
        )
    _assert_sha(
        authority.verified_attestation_sha256,
        label="verified external attestation",
        sha256=True,
    )
    return authority


def _verify_external_attestation(
    capsule: Mapping[str, Any],
    *,
    authority: ReleaseCapsuleAuthority,
    expected: Mapping[str, Any],
) -> str:
    _relative, raw = _safe_file_bytes(
        authority.gate_output_root,
        capsule.get("attestation_ref"),
        label="execution attestation",
    )
    digest = hashlib.sha256(raw).hexdigest()
    if digest != authority.verified_attestation_sha256:
        raise UpgradeLaneError("execution attestation lacks the external trust anchor")
    if digest != capsule.get("attestation_sha256"):
        raise UpgradeLaneError("release capsule attestation_sha256 mismatch")
    try:
        attestation = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpgradeLaneError("execution attestation is not valid UTF-8 JSON") from exc
    if not isinstance(attestation, Mapping) or dict(attestation) != dict(expected):
        raise UpgradeLaneError(
            "execution attestation does not bind exact tree/visual/gate outputs"
        )
    if (
        attestation.get("schema_version") != EXECUTION_ATTESTATION_SCHEMA_VERSION
        or attestation.get("authority")
        != {
            "kind": "external_sha256",
            "id": capsule.get("attestation_authority_id"),
        }
        or not _ID_RE.fullmatch(str(attestation.get("run_id") or ""))
    ):
        raise UpgradeLaneError("execution attestation authority/run identity is invalid")
    _assert_public_safe_payload(dict(attestation), label="execution attestation")
    return digest


def seal_release_capsule(
    payload: Mapping[str, Any], *, authority: ReleaseCapsuleAuthority | None = None
) -> dict[str, Any]:
    """Build a capsule only from recomputed artifacts and external attestation."""

    authority = _require_authority(authority)
    capsule = copy.deepcopy(dict(payload))
    capsule.pop("capsule_sha256", None)
    capsule["schema_version"] = RELEASE_CAPSULE_SCHEMA_VERSION
    release = authority.package.get("release")
    if not isinstance(release, Mapping):
        raise UpgradeLaneError("release package omits release identity")
    capsule["release_id"] = release.get("id")
    registry = capsule.get("command_registry")
    gates = capsule.get("certified_gates")
    if not isinstance(registry, list) or not all(isinstance(item, dict) for item in registry):
        raise UpgradeLaneError("release capsule command_registry must be a list of mappings")
    if not isinstance(gates, list) or not all(isinstance(item, dict) for item in gates):
        raise UpgradeLaneError("release capsule certified_gates must be a list of mappings")
    capsule["command_registry"] = sorted(registry, key=lambda item: str(item.get("id", "")))
    capsule["certified_gates"] = sorted(gates, key=lambda item: str(item.get("id", "")))
    _unique_ids(capsule["command_registry"], label="command registry")
    for item in capsule["command_registry"]:
        gate_id = item.get("id")
        command = item.get("command")
        if not isinstance(gate_id, str) or _ID_RE.fullmatch(gate_id) is None:
            raise UpgradeLaneError("release capsule command registry has an invalid gate id")
        if item.get("class") not in GATE_CLASSES:
            raise UpgradeLaneError(f"unknown gate class for {gate_id}")
        if not isinstance(command, str) or _PLACEHOLDER_COMMAND_RE.search(command):
            raise UpgradeLaneError(
                f"command registry entry is placeholder/manual: {gate_id}"
            )
    capsule["command_registry_sha256"] = canonical_sha256(capsule["command_registry"])
    _assert_public_safe_payload(capsule, label="release capsule inputs")
    evidence = collect_release_attestation(
        capsule,
        package=authority.package,
        impact_registry=authority.impact_registry,
        source_root=authority.source_root,
        visual_root=authority.visual_root,
        gate_output_root=authority.gate_output_root,
    )
    capsule["package_sha256"] = evidence["package_sha256"]
    capsule["portable_tree_sha256"] = evidence["portable_tree_sha256"]
    capsule["portable_tree_entry_count"] = evidence["portable_tree_entry_count"]
    capsule["visual_manifest_sha256"] = evidence["visual_manifest_sha256"]
    capsule["visual_manifest_entry_count"] = evidence["visual_manifest_entry_count"]
    capsule["toolchain"] = evidence["toolchain"]
    capsule["toolchain_sha256"] = evidence["toolchain_sha256"]
    capsule["toolchain_probe_sha256"] = evidence["toolchain_probe_sha256"]
    capsule["toolchain_probe_entry_count"] = evidence[
        "toolchain_probe_entry_count"
    ]
    output_by_id = {item["id"]: item for item in evidence["gate_outputs"]}
    for gate in capsule["certified_gates"]:
        output = output_by_id[gate["id"]]
        gate["output_ref"] = output["output_ref"]
        gate["output_sha256"] = output["output_sha256"]
        gate["output_bytes"] = output["output_bytes"]
    capsule["gate_receipt_sha256"] = canonical_sha256(capsule["certified_gates"])
    capsule["attestation_sha256"] = authority.verified_attestation_sha256
    _verify_external_attestation(capsule, authority=authority, expected=evidence)
    capsule["capsule_sha256"] = canonical_sha256(capsule)
    verify_release_capsule(capsule, authority=authority)
    return capsule


def verify_release_capsule(
    capsule: Mapping[str, Any], *, authority: ReleaseCapsuleAuthority | None = None
) -> VerifiedReleaseCapsule:
    """Recompute and verify every artifact bound by a certified Lane A capsule."""

    authority = _require_authority(authority)
    _require_schema(capsule, RELEASE_CAPSULE_SCHEMA_PATH, label="release capsule")
    _assert_public_safe_payload(capsule, label="release capsule")
    registry = capsule["command_registry"]
    certified = capsule["certified_gates"]
    registry_ids = _unique_ids(registry, label="command registry")
    certified_ids = _unique_ids(certified, label="certified gates")
    command_by_id: dict[str, Mapping[str, Any]] = {}
    for item in registry:
        gate_id = item["id"]
        if _ID_RE.fullmatch(gate_id) is None:
            raise UpgradeLaneError(f"invalid gate id in command registry: {gate_id!r}")
        if item["class"] not in GATE_CLASSES:
            raise UpgradeLaneError(f"unknown gate class for {gate_id}")
        command = item["command"]
        if _PLACEHOLDER_COMMAND_RE.search(command):
            raise UpgradeLaneError(f"command registry entry is placeholder/manual: {gate_id}")
        command_by_id[gate_id] = item
    if canonical_sha256(registry) != capsule["command_registry_sha256"]:
        raise UpgradeLaneError("release capsule command_registry_sha256 mismatch")
    if canonical_sha256(capsule["toolchain"]) != capsule["toolchain_sha256"]:
        raise UpgradeLaneError("release capsule toolchain_sha256 mismatch")
    if canonical_sha256(certified) != capsule["gate_receipt_sha256"]:
        raise UpgradeLaneError("release capsule gate_receipt_sha256 mismatch")
    evidence = collect_release_attestation(
        capsule,
        package=authority.package,
        impact_registry=authority.impact_registry,
        source_root=authority.source_root,
        visual_root=authority.visual_root,
        gate_output_root=authority.gate_output_root,
    )
    for field in (
        "package_sha256",
        "portable_tree_sha256",
        "portable_tree_entry_count",
        "visual_manifest_sha256",
        "visual_manifest_entry_count",
        "command_registry_sha256",
        "toolchain_sha256",
        "toolchain_probe_sha256",
        "toolchain_probe_entry_count",
    ):
        if capsule.get(field) != evidence[field]:
            raise UpgradeLaneError(f"release capsule recomputed {field} mismatch")
    if capsule.get("toolchain") != evidence["toolchain"]:
        raise UpgradeLaneError("release capsule recomputed toolchain mismatch")
    output_by_id = {item["id"]: item for item in evidence["gate_outputs"]}
    for result in certified:
        gate_id = result["id"]
        registered = command_by_id.get(gate_id)
        output = output_by_id.get(gate_id)
        if registered is None or output is None:
            raise UpgradeLaneError(f"certified gate lacks registry/output binding: {gate_id}")
        if registered["class"] != "upstream_certified" or result["class"] != "upstream_certified":
            raise UpgradeLaneError(f"Lane A may certify only upstream_certified gates: {gate_id}")
        if result["provenance"] != "executed" or result["status"] != "passed":
            raise UpgradeLaneError(f"certified gate lacks executed passing evidence: {gate_id}")
        if result["exit_code"] != 0:
            raise UpgradeLaneError(f"certified gate exit code is not zero: {gate_id}")
        if result["subject_sha"] != capsule["source_sha"]:
            raise UpgradeLaneError(f"certified gate is stale for source subject: {gate_id}")
        if result["command_sha256"] != _command_digest(registered["command"]):
            raise UpgradeLaneError(f"certified gate command digest mismatch: {gate_id}")
        for field in ("output_ref", "output_sha256", "output_bytes"):
            if result.get(field) != output[field]:
                raise UpgradeLaneError(f"certified gate output binding mismatch: {gate_id}")
    if set(certified_ids) != {
        gate_id
        for gate_id in registry_ids
        if command_by_id[gate_id]["class"] == "upstream_certified"
    }:
        raise UpgradeLaneError("capsule must carry executed proof for every upstream gate")
    attestation_sha256 = _verify_external_attestation(
        capsule, authority=authority, expected=evidence
    )
    unsigned = dict(capsule)
    claimed_digest = unsigned.pop("capsule_sha256")
    digest = canonical_sha256(unsigned)
    if digest != claimed_digest:
        raise UpgradeLaneError("release capsule canonical digest mismatch")
    return VerifiedReleaseCapsule(
        digest=digest,
        source_sha=capsule["source_sha"],
        package_sha256=capsule["package_sha256"],
        portable_tree_sha256=capsule["portable_tree_sha256"],
        visual_manifest_sha256=capsule["visual_manifest_sha256"],
        attestation_sha256=attestation_sha256,
        _authority=_ATTESTATION_AUTHORITY,
    )


def seal_impact_registry(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize and seal a versioned path/contract/gate impact registry."""

    registry = copy.deepcopy(dict(payload))
    registry.pop("registry_sha256", None)
    registry["schema_version"] = IMPACT_REGISTRY_SCHEMA_VERSION
    if isinstance(registry.get("gate_catalog"), list):
        registry["gate_catalog"] = sorted(
            registry["gate_catalog"], key=lambda item: str(item.get("id", ""))
        )
    if isinstance(registry.get("full_matrix_gates"), list):
        registry["full_matrix_gates"] = sorted(set(registry["full_matrix_gates"]))
    if isinstance(registry.get("surfaces"), list):
        normalized_surfaces = []
        for raw in registry["surfaces"]:
            surface = dict(raw)
            for key in ("path_patterns", "contracts", "gates", "depends_on"):
                if isinstance(surface.get(key), list):
                    surface[key] = sorted(set(surface[key]))
            normalized_surfaces.append(surface)
        registry["surfaces"] = sorted(
            normalized_surfaces, key=lambda item: str(item.get("id", ""))
        )
    if isinstance(registry.get("boundary_policy"), dict):
        for key, value in registry["boundary_policy"].items():
            if isinstance(value, list):
                registry["boundary_policy"][key] = sorted(set(value))
    registry["registry_sha256"] = canonical_sha256(registry)
    verify_impact_registry(registry)
    return registry


def verify_impact_registry(registry: Mapping[str, Any]) -> str:
    """Verify registry closure and its fail-closed fallback policy."""

    _require_schema(registry, IMPACT_REGISTRY_SCHEMA_PATH, label="impact registry")
    gates = registry["gate_catalog"]
    surfaces = registry["surfaces"]
    gate_ids = _unique_ids(gates, label="gate catalog")
    surface_ids = _unique_ids(surfaces, label="impact surfaces")
    gate_class = {item["id"]: item["class"] for item in gates}
    if not NEVER_REUSABLE_GATES.issubset(gate_class):
        missing = sorted(NEVER_REUSABLE_GATES - set(gate_class))
        raise UpgradeLaneError(f"impact registry omits never-reusable gates: {missing}")
    invalid_reuse = sorted(
        gate_id
        for gate_id in NEVER_REUSABLE_GATES
        if gate_class[gate_id] not in {"consumer_always", "canary"}
    )
    if invalid_reuse:
        raise UpgradeLaneError(
            f"never-reusable gates must be consumer_always/canary: {invalid_reuse}"
        )
    full_matrix = registry["full_matrix_gates"]
    if full_matrix != sorted(gate_ids):
        raise UpgradeLaneError("full_matrix_gates must contain the complete sorted gate catalog")
    surface_by_id = {item["id"]: item for item in surfaces}
    for surface in surfaces:
        for pattern in surface["path_patterns"]:
            _canonical_repo_path(
                pattern,
                label=f"surface {surface['id']} path pattern",
                allow_glob=True,
            )
        unknown_gates = sorted(set(surface["gates"]) - set(gate_ids))
        if unknown_gates:
            raise UpgradeLaneError(
                f"surface {surface['id']} references unknown gates: {unknown_gates}"
            )
        unknown_dependencies = sorted(set(surface["depends_on"]) - set(surface_ids))
        if unknown_dependencies:
            raise UpgradeLaneError(
                f"surface {surface['id']} references unknown dependencies: {unknown_dependencies}"
            )
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(surface_id: str) -> None:
        if surface_id in visiting:
            raise UpgradeLaneError(f"impact registry dependency cycle at {surface_id}")
        if surface_id in visited:
            return
        visiting.add(surface_id)
        for dependency in surface_by_id[surface_id]["depends_on"]:
            visit(dependency)
        visiting.remove(surface_id)
        visited.add(surface_id)

    for surface_id in surface_ids:
        visit(surface_id)
    for patterns in registry["boundary_policy"].values():
        for pattern in patterns:
            _canonical_repo_path(pattern, label="boundary pattern", allow_glob=True)
    unsigned = dict(registry)
    claimed_digest = unsigned.pop("registry_sha256")
    digest = canonical_sha256(unsigned)
    if digest != claimed_digest:
        raise UpgradeLaneError("impact registry canonical digest mismatch")
    return digest


def _matches(path: str, patterns: Sequence[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def select_impacted_gates(
    registry: Mapping[str, Any],
    *,
    changed_paths: Sequence[str],
    changed_contracts: Sequence[str],
) -> dict[str, Any]:
    """Select exact gates, escalating unknown impact to the complete matrix."""

    registry_sha256 = verify_impact_registry(registry)
    paths = sorted(
        {
            _canonical_repo_path(path, label="changed path")
            for path in changed_paths
        }
    )
    contracts = sorted(set(changed_contracts))
    for contract in contracts:
        if not isinstance(contract, str) or _CONTRACT_RE.fullmatch(contract) is None:
            raise UpgradeLaneError(f"changed contract is not canonical: {contract!r}")
    surfaces = registry["surfaces"]
    matched: set[str] = set()
    unknown_paths: list[str] = []
    unknown_contracts: list[str] = []
    for path in paths:
        path_matches = {
            item["id"] for item in surfaces if _matches(path, item["path_patterns"])
        }
        if not path_matches:
            unknown_paths.append(path)
        matched.update(path_matches)
    for contract in contracts:
        contract_matches = {
            item["id"] for item in surfaces if contract in item["contracts"]
        }
        if not contract_matches:
            unknown_contracts.append(contract)
        matched.update(contract_matches)
    surface_by_id = {item["id"]: item for item in surfaces}

    def add_dependencies(surface_id: str) -> None:
        for dependency in surface_by_id[surface_id]["depends_on"]:
            if dependency not in matched:
                matched.add(dependency)
                add_dependencies(dependency)

    for surface_id in list(matched):
        add_dependencies(surface_id)
    gate_class = {item["id"]: item["class"] for item in registry["gate_catalog"]}
    unknown = bool(unknown_paths or unknown_contracts)
    lane_a_surface = any(surface_by_id[item]["lane"] == "lane_a" for item in matched)
    if unknown or lane_a_surface:
        selected = set(registry["full_matrix_gates"])
        requires_lane_a = True
        escalation = "unknown_impact_full_lane" if unknown else "portable_change_lane_a"
    else:
        selected = {
            gate_id
            for gate_id, class_name in gate_class.items()
            if class_name in {"consumer_always", "canary"}
        }
        for surface_id in matched:
            selected.update(surface_by_id[surface_id]["gates"])
        selected.update(NEVER_REUSABLE_GATES)
        requires_lane_a = False
        escalation = "consumer_delta"
    omitted = sorted(set(gate_class) - selected)
    derivation = {
        "schema_version": "wiki_viva_upgrade_impact_derivation.v1",
        "registry_sha256": registry_sha256,
        "changed_paths": paths,
        "changed_contracts": contracts,
        "matched_surfaces": sorted(matched),
        "unknown_paths": unknown_paths,
        "unknown_contracts": unknown_contracts,
        "selected_gates": sorted(selected),
        "omitted_gates": omitted,
        "requires_lane_a": requires_lane_a,
        "escalation": escalation,
    }
    return {**derivation, "derivation_sha256": canonical_sha256(derivation)}


def validate_canary_evidence(
    package: Mapping[str, Any],
    evidence: Mapping[str, Any],
    *,
    selected_gates: Sequence[str],
    gate_catalog: Sequence[Mapping[str, Any]],
    subject_sha: str,
) -> None:
    """Require one real, error-free canary observation and exact visual coverage."""

    _assert_sha(subject_sha, label="canary consumer subject")
    selected = set(selected_gates)
    canary_ids = {
        str(item.get("id"))
        for item in gate_catalog
        if isinstance(item, Mapping)
        and item.get("class") == "canary"
        and item.get("id") in selected
    }
    if not canary_ids:
        return
    network = evidence.get("network")
    console = evidence.get("console")
    screenshots = evidence.get("screenshots")
    if not all(isinstance(items, list) for items in (network, console, screenshots)):
        raise UpgradeLaneError("canary evidence lists are missing")
    for gate_id in sorted(canary_ids):
        network_summaries = [
            item
            for item in network
            if isinstance(item, Mapping)
            and item.get("gate_id") == gate_id
            and item.get("subject_sha") == subject_sha
            and item.get("capture") == "gate_emitted_sanitized_network_summary"
        ]
        if (
            len(network_summaries) != 1
            or isinstance(network_summaries[0].get("request_count"), bool)
            or not isinstance(network_summaries[0].get("request_count"), int)
            or network_summaries[0]["request_count"] <= 0
            or network_summaries[0].get("error_count") != 0
        ):
            raise UpgradeLaneError(
                f"canary network evidence must prove requests>0 and errors=0: {gate_id}"
            )
        console_summaries = [
            item
            for item in console
            if isinstance(item, Mapping)
            and item.get("gate_id") == gate_id
            and item.get("subject_sha") == subject_sha
            and item.get("capture") == "gate_emitted_browser_console_summary"
        ]
        if len(console_summaries) != 1 or console_summaries[0].get("error_count") != 0:
            raise UpgradeLaneError(
                f"canary browser console must prove zero errors: {gate_id}"
            )
    migration = package.get("migration")
    profiles = migration.get("visual_profiles") if isinstance(migration, Mapping) else None
    if (
        not isinstance(profiles, list)
        or not profiles
        or len(profiles) != len(set(profiles))
        or any(not isinstance(profile, str) or not profile for profile in profiles)
    ):
        raise UpgradeLaneError("package visual profiles are not exact and unique")
    canary_screenshots = [
        item
        for item in screenshots
        if isinstance(item, Mapping)
        and item.get("gate_id") in canary_ids
        and item.get("subject_sha") == subject_sha
    ]
    if len(canary_screenshots) != len(profiles):
        raise UpgradeLaneError("canary screenshots do not exactly cover visual profiles")
    seen_profiles: set[str] = set()
    seen_observations: set[tuple[str, str, int, int]] = set()
    for item in canary_screenshots:
        profile = item.get("profile")
        route = item.get("route")
        viewport = item.get("viewport")
        if (
            profile not in profiles
            or not isinstance(route, str)
            or not route.startswith("/")
            or _PRIVATE_ROUTE_RE.match(route)
            or not isinstance(viewport, Mapping)
            or set(viewport) != {"width", "height"}
            or any(
                isinstance(viewport.get(axis), bool)
                or not isinstance(viewport.get(axis), int)
                or not 240 <= viewport[axis] <= 7680
                for axis in ("width", "height")
            )
            or item.get("width") != viewport["width"]
            or item.get("height") != viewport["height"]
        ):
            raise UpgradeLaneError("canary screenshot profile/route/viewport is invalid")
        observation = (profile, route, viewport["width"], viewport["height"])
        if profile in seen_profiles or observation in seen_observations:
            raise UpgradeLaneError("duplicate canary visual profile/route/viewport")
        seen_profiles.add(profile)
        seen_observations.add(observation)
    if seen_profiles != set(profiles):
        raise UpgradeLaneError("canary visual profile coverage differs from package")


def adoption_identity(payload: Mapping[str, Any]) -> dict[str, str]:
    """Validate and return the exact seven-term receipt reuse identity."""

    _require_exact_keys(payload, set(_IDENTITY_FIELDS), label="adoption identity")
    identity: dict[str, str] = {}
    for field in _IDENTITY_FIELDS:
        identity[field] = _assert_sha(
            payload[field],
            label=f"adoption identity {field}",
            sha256=field not in {"source_sha", "consumer_B0", "consumer_C3"},
        )
    return identity


def _catalog_maps(registry: Mapping[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    classes = {item["id"]: item["class"] for item in registry["gate_catalog"]}
    commands = {item["id"]: item["command"] for item in registry["gate_catalog"]}
    return classes, commands


def _require_verified_capsule_token(
    capsule: Mapping[str, Any], verified: VerifiedReleaseCapsule | None
) -> VerifiedReleaseCapsule:
    unsigned = dict(capsule)
    claimed_digest = unsigned.pop("capsule_sha256", None)
    if (
        not isinstance(verified, VerifiedReleaseCapsule)
        or verified._authority is not _ATTESTATION_AUTHORITY
        or claimed_digest != verified.digest
        or canonical_sha256(unsigned) != verified.digest
        or capsule.get("source_sha") != verified.source_sha
        or capsule.get("package_sha256") != verified.package_sha256
        or capsule.get("portable_tree_sha256") != verified.portable_tree_sha256
        or capsule.get("visual_manifest_sha256") != verified.visual_manifest_sha256
        or capsule.get("attestation_sha256") != verified.attestation_sha256
    ):
        raise UpgradeLaneError(
            "shape-only release capsule cannot authorize omission or adoption"
        )
    return verified


def verify_gate_omissions(
    registry: Mapping[str, Any],
    selection: Mapping[str, Any],
    omissions: Sequence[Mapping[str, Any]],
    capsule: Mapping[str, Any],
    *,
    verified_capsule: VerifiedReleaseCapsule | None = None,
) -> None:
    """Reject any omission not proved by the capsule or impact derivation."""

    verify_impact_registry(registry)
    _require_verified_capsule_token(capsule, verified_capsule)
    if canonical_sha256(registry["gate_catalog"]) != capsule[
        "command_registry_sha256"
    ]:
        raise UpgradeLaneError(
            "impact registry command catalog does not match the release capsule"
        )
    classes, _commands = _catalog_maps(registry)
    selected = set(selection["selected_gates"])
    expected_omitted = set(classes) - selected
    entries: dict[str, Mapping[str, Any]] = {}
    for item in omissions:
        _require_exact_keys(
            item,
            {"gate_id", "reason", "derivation_sha256"},
            label="gate omission",
        )
        gate_id = item["gate_id"]
        if gate_id in entries:
            raise UpgradeLaneError(f"duplicate gate omission: {gate_id}")
        entries[gate_id] = item
    if set(entries) != expected_omitted:
        raise UpgradeLaneError(
            "gate omissions must exactly cover the catalog minus selected gates"
        )
    certified_ids = {item["id"] for item in capsule["certified_gates"]}
    for gate_id, omission in entries.items():
        if gate_id in NEVER_REUSABLE_GATES:
            raise UpgradeLaneError(f"never-reusable gate cannot be omitted: {gate_id}")
        class_name = classes[gate_id]
        if class_name == "upstream_certified":
            if (
                omission["reason"] != "verified_upstream_capsule"
                or gate_id not in certified_ids
                or omission["derivation_sha256"] != capsule["capsule_sha256"]
            ):
                raise UpgradeLaneError(
                    f"upstream gate omission lacks exact capsule proof: {gate_id}"
                )
        elif class_name in {"consumer_always", "canary"}:
            raise UpgradeLaneError(f"mandatory consumer gate cannot be omitted: {gate_id}")
        elif (
            omission["reason"] != "not_affected"
            or omission["derivation_sha256"] != selection["derivation_sha256"]
        ):
            raise UpgradeLaneError(
                f"gate omission lacks exact impact derivation: {gate_id}"
            )


def validate_boundary_ownership(
    boundaries: Mapping[str, Any],
    registry: Mapping[str, Any],
    *,
    package: Mapping[str, Any],
) -> None:
    """Prove C1/C2/C3 ownership against the exact package allow/block policy."""

    _require_exact_keys(boundaries, {"C1", "C2", "C3"}, label="commit boundaries")
    policy = registry["boundary_policy"]
    migration = package.get("migration")
    boundary_operations = (
        migration.get("boundary_operations")
        if isinstance(migration, Mapping)
        else None
    )
    try:
        from wiki_core.upgrade import boundary_operations_sha256
    except ImportError as exc:
        raise UpgradeLaneError("boundary operations verifier is unavailable") from exc
    if (
        not isinstance(boundary_operations, Mapping)
        or boundary_operations.get("schema_version")
        != "wiki_viva_upgrade_boundary_operations.v1"
        or boundary_operations_sha256(boundary_operations)
        != boundary_operations.get("registry_sha256")
    ):
        raise UpgradeLaneError("package boundary operations are missing or stale")
    generators = boundary_operations.get("c2_generators")
    c3_adapter = boundary_operations.get("c3_adapter")
    if not isinstance(generators, list) or not isinstance(c3_adapter, Mapping):
        raise UpgradeLaneError("package boundary operations are incomplete")
    generator_owners: list[tuple[tuple[str, ...], str]] = []
    c2_declared: list[str] = []
    for generator in generators:
        if not isinstance(generator, Mapping):
            raise UpgradeLaneError("package C2 generator must be a mapping")
        command = generator.get("command")
        patterns = generator.get("owns_patterns")
        if (
            not isinstance(command, str)
            or not command
            or not isinstance(patterns, list)
            or not patterns
            or any(not isinstance(pattern, str) for pattern in patterns)
        ):
            raise UpgradeLaneError("package C2 generator contract is incomplete")
        generator_owners.append(
            (tuple(patterns), hashlib.sha256(command.encode("utf-8")).hexdigest())
        )
        c2_declared.extend(patterns)
    if sorted(c2_declared) != sorted(policy["c2_generated_patterns"]):
        raise UpgradeLaneError("package C2 ownership differs from impact registry")
    if sorted(c3_adapter.get("owns_patterns") or []) != sorted(
        policy["c3_consumer_patterns"]
    ):
        raise UpgradeLaneError("package C3 ownership differs from impact registry")
    portable = package.get("portable_import")
    if not isinstance(portable, Mapping):
        raise UpgradeLaneError("upgrade package omits portable_import ownership")
    allow = portable.get("allow")
    block = portable.get("block")
    if (
        not isinstance(allow, list)
        or not allow
        or not isinstance(block, list)
        or not block
        or any(not isinstance(pattern, str) for pattern in [*allow, *block])
    ):
        raise UpgradeLaneError("upgrade package portable allow/block is incomplete")
    for group, patterns in (("allow", allow), ("block", block)):
        for pattern in patterns:
            _canonical_repo_path(
                pattern,
                label=f"package portable {group} pattern",
                allow_glob=True,
            )
    if sorted(set(allow)) != sorted(set(policy["c1_portable_patterns"])):
        raise UpgradeLaneError(
            "impact registry C1 ownership differs from package portable allowlist"
        )
    seen: dict[str, str] = {}
    for boundary in ("C1", "C2", "C3"):
        items = boundaries[boundary]
        if not isinstance(items, list):
            raise UpgradeLaneError(f"{boundary} must be a list")
        for item in items:
            required = {"path", "sha256"}
            if boundary == "C1":
                operation = item.get("operation")
                required = (
                    {"path", "operation", "sha256", "source_sha256"}
                    if operation == "upsert"
                    else {"path", "operation", "before_sha256"}
                )
            elif boundary == "C2":
                operation = item.get("operation")
                required = (
                    {"path", "operation", "sha256", "generator_sha256"}
                    if operation == "upsert"
                    else {
                        "path",
                        "operation",
                        "before_sha256",
                        "generator_sha256",
                    }
                )
            elif boundary == "C3":
                operation = item.get("operation")
                required = (
                    {"path", "operation", "sha256"}
                    if operation == "upsert"
                    else {"path", "operation", "before_sha256"}
                )
            _require_exact_keys(item, required, label=f"{boundary} entry")
            path = _canonical_repo_path(item["path"], label=f"{boundary} path")
            if item.get("operation", "upsert") == "upsert":
                _assert_sha(item["sha256"], label=f"{boundary} sha256", sha256=True)
            elif boundary in {"C1", "C2", "C3"} and item.get("operation") == "delete":
                _assert_sha(
                    item["before_sha256"],
                    label=f"{boundary} before_sha256",
                    sha256=True,
                )
            else:
                raise UpgradeLaneError(f"{boundary} operation is invalid: {path}")
            if path in seen:
                raise UpgradeLaneError(
                    f"boundary path appears in both {seen[path]} and {boundary}: {path}"
                )
            seen[path] = boundary
            if _matches(path, policy["domain_content_patterns"]):
                raise UpgradeLaneError(
                    f"domain content is forbidden in technical boundary {boundary}: {path}"
                )
            if boundary == "C1":
                if item.get("operation") == "upsert":
                    _assert_sha(
                        item["source_sha256"],
                        label="C1 source_sha256",
                        sha256=True,
                    )
                    if item["sha256"] != item["source_sha256"]:
                        raise UpgradeLaneError(
                            f"C1 file is not byte-equal to Lane A: {path}"
                        )
                elif item.get("operation") == "delete":
                    _assert_sha(
                        item["before_sha256"],
                        label="C1 before_sha256",
                        sha256=True,
                    )
                else:
                    raise UpgradeLaneError(f"C1 operation is invalid: {path}")
                if _matches(path, block) or not _matches(path, allow):
                    raise UpgradeLaneError(
                        f"consumer/generated path mixed into C1 by package policy: {path}"
                    )
                if _matches(path, policy["c2_generated_patterns"]) or _matches(
                    path, policy["c3_consumer_patterns"]
                ):
                    raise UpgradeLaneError(f"C1 path has ambiguous boundary ownership: {path}")
            elif boundary == "C2":
                _assert_sha(
                    item["generator_sha256"], label="C2 generator_sha256", sha256=True
                )
                if item.get("operation") not in {"upsert", "delete"}:
                    raise UpgradeLaneError(f"C2 operation is invalid: {path}")
                if not _matches(path, policy["c2_generated_patterns"]):
                    raise UpgradeLaneError(f"non-generated path mixed into C2: {path}")
                owners = [
                    generator_sha256
                    for patterns, generator_sha256 in generator_owners
                    if _matches(path, patterns)
                ]
                if len(owners) != 1 or item["generator_sha256"] != owners[0]:
                    raise UpgradeLaneError(
                        f"C2 generator proof differs from package command: {path}"
                    )
            else:
                if item.get("operation") not in {"upsert", "delete"}:
                    raise UpgradeLaneError(f"C3 operation is invalid: {path}")
                if not _matches(path, policy["c3_consumer_patterns"]):
                    raise UpgradeLaneError(f"portable/generated path mixed into C3: {path}")


def validate_c1_projection(
    c1_entries: Sequence[Mapping[str, Any]],
    *,
    package: Mapping[str, Any],
    source_entries: Mapping[str, str],
    before_entries: Mapping[str, str],
    after_entries: Mapping[str, str],
) -> None:
    """Prove C1 is the complete source projection, including stale deletions."""

    portable = package.get("portable_import")
    if not isinstance(portable, Mapping):
        raise UpgradeLaneError("upgrade package omits portable_import projection")
    allow = portable.get("allow")
    block = portable.get("block")
    if not isinstance(allow, list) or not isinstance(block, list):
        raise UpgradeLaneError("portable projection allow/block is invalid")

    def normalized(entries: Mapping[str, str], *, label: str) -> dict[str, str]:
        result: dict[str, str] = {}
        for raw_path, digest in entries.items():
            path = _canonical_repo_path(raw_path, label=f"{label} path")
            result[path] = _assert_sha(
                digest, label=f"{label} sha256", sha256=True
            )
        return result

    source = normalized(source_entries, label="C1 source projection")
    before = normalized(before_entries, label="C1 before projection")
    after = normalized(after_entries, label="C1 after projection")
    for path in source:
        if _matches(path, block) or not _matches(path, allow):
            raise UpgradeLaneError(f"C1 source projection violates package policy: {path}")
    before_portable = {
        path: digest
        for path, digest in before.items()
        if _matches(path, allow) and not _matches(path, block)
    }
    after_portable = {
        path: digest
        for path, digest in after.items()
        if _matches(path, allow) and not _matches(path, block)
    }
    if after_portable != source:
        raise UpgradeLaneError("C1 after tree is not the exact portable source projection")
    expected: list[dict[str, Any]] = []
    for path in sorted(set(before_portable) | set(source)):
        before_digest = before_portable.get(path)
        source_digest = source.get(path)
        if source_digest is None:
            expected.append(
                {
                    "path": path,
                    "operation": "delete",
                    "before_sha256": before_digest,
                }
            )
        elif source_digest != before_digest:
            expected.append(
                {
                    "path": path,
                    "operation": "upsert",
                    "sha256": source_digest,
                    "source_sha256": source_digest,
                }
            )
    if [dict(item) for item in c1_entries] != expected:
        raise UpgradeLaneError(
            "C1 boundary does not exactly cover portable upserts and deletions"
        )


def seal_adoption_receipt(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Seal an adoption receipt without making unexecuted evidence valid."""

    receipt = copy.deepcopy(dict(payload))
    receipt.pop("receipt_sha256", None)
    receipt["schema_version"] = ADOPTION_RECEIPT_SCHEMA_VERSION
    identity = adoption_identity(receipt["identity"])
    receipt["identity_sha256"] = canonical_sha256(identity)
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    return receipt


def _private_json_artifact(
    root: Path, relative: str, *, label: str
) -> tuple[dict[str, Any], bytes]:
    _relative, raw = _safe_file_bytes(root, relative, label=label)
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpgradeLaneError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise UpgradeLaneError(f"{label} must contain a mapping")
    return payload, raw


def verify_adoption_evidence(
    receipt: Mapping[str, Any],
    *,
    authority: AdoptionEvidenceAuthority,
    package: Mapping[str, Any],
    registry: Mapping[str, Any],
    selection: Mapping[str, Any],
) -> VerifiedAdoptionEvidence:
    """Resolve receipt claims to real run files and the current consumer C3."""

    if not isinstance(authority, AdoptionEvidenceAuthority):
        raise UpgradeLaneError("adoption evidence authority is required")
    _require_exact_keys(receipt, _RECEIPT_FIELDS, label="adoption receipt")
    unsigned_receipt = dict(receipt)
    receipt_digest = unsigned_receipt.pop("receipt_sha256", None)
    if receipt_digest != canonical_sha256(unsigned_receipt):
        raise UpgradeLaneError("adoption receipt canonical digest mismatch")
    consumer = authority.consumer_root.resolve(strict=True)
    run_root = authority.run_root.resolve(strict=True)
    try:
        run_relative = run_root.relative_to(consumer).as_posix()
    except ValueError as exc:
        raise UpgradeLaneError("adoption run root is outside the consumer") from exc
    if not run_relative.startswith(".wiki-viva/upgrade/runs/"):
        raise UpgradeLaneError("adoption run root is outside the ignored runner boundary")
    repository = _git_bytes(
        consumer, ["rev-parse", "--show-toplevel"], label="consumer repository"
    ).decode("utf-8", "strict").strip()
    if Path(repository).resolve() != consumer:
        raise UpgradeLaneError("consumer_root must be the exact Git repository root")
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", run_relative],
        cwd=consumer,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if ignored.returncode != 0:
        raise UpgradeLaneError("adoption evidence root is not Git-ignored")
    identity = adoption_identity(receipt["identity"])
    head = _git_bytes(
        consumer, ["rev-parse", "HEAD"], label="consumer HEAD"
    ).decode("ascii", "strict").strip()
    if head != identity["consumer_C3"]:
        raise UpgradeLaneError("adoption evidence consumer HEAD differs from C3")
    if _git_bytes(
        consumer,
        ["status", "--porcelain", "--untracked-files=no"],
        label="consumer tracked state",
    ):
        raise UpgradeLaneError("adoption evidence consumer has tracked worktree changes")
    b0_tree = _git_bytes(
        consumer,
        ["rev-parse", f"{identity['consumer_B0']}^{{tree}}"],
        label="consumer B0 tree",
    ).decode("ascii", "strict").strip()
    ancestry = subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            identity["consumer_B0"],
            identity["consumer_C3"],
        ],
        cwd=consumer,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if ancestry.returncode != 0:
        raise UpgradeLaneError("consumer B0 is not an ancestor of C3")
    state, state_raw = _private_json_artifact(
        run_root, "state.json", label="adoption runner state"
    )
    if (
        state.get("schema_version") != "wiki_viva_upgrade_runner_state.v1"
        or state.get("plan_sha256") != receipt["plan_sha256"]
        or state.get("identity_sha256") != receipt["identity_sha256"]
        or state.get("capsule_sha256") != receipt["capsule_sha256"]
        or state.get("impact_registry_sha256")
        != receipt["impact_registry_sha256"]
        or state.get("toolchain_sha256") != identity["toolchain_sha256"]
        or not isinstance(state.get("gate_results"), Mapping)
    ):
        raise UpgradeLaneError("adoption runner state is stale or incomplete")
    state_results = state["gate_results"]
    receipt_results = receipt["gate_results"]
    if not isinstance(receipt_results, list):
        raise UpgradeLaneError("adoption receipt gate results are invalid")
    receipt_by_id = {
        str(item.get("id")): item
        for item in receipt_results
        if isinstance(item, Mapping)
    }
    if set(state_results) != set(receipt_by_id):
        raise UpgradeLaneError("runner state and receipt gate coverage differ")
    for gate_id, result in receipt_by_id.items():
        state_result = state_results[gate_id]
        if not isinstance(state_result, Mapping) or any(
            state_result.get(key) != value for key, value in result.items()
        ):
            raise UpgradeLaneError(f"runner state gate result differs: {gate_id}")
        _relative, output = _safe_file_bytes(
            run_root, f"logs/{gate_id}.log", label=f"adoption gate log {gate_id}"
        )
        if hashlib.sha256(output).hexdigest() != result.get("output_sha256"):
            raise UpgradeLaneError(f"adoption gate log hash differs: {gate_id}")
    rollback, rollback_raw = _private_json_artifact(
        run_root, "rollback.json", label="rollback execution"
    )
    rollback_unsigned = dict(rollback)
    rollback_digest = rollback_unsigned.pop("evidence_sha256", None)
    if (
        rollback.get("schema_version") != "wiki_viva_upgrade_rollback_execution.v1"
        or rollback.get("provenance") != "executed"
        or rollback.get("status") != "verified"
        or rollback.get("subject_sha") != identity["consumer_C3"]
        or rollback.get("consumer_B0") != identity["consumer_B0"]
        or rollback.get("before_tree_sha") != b0_tree
        or rollback.get("rolled_back_tree_sha") != b0_tree
        or rollback.get("tree_equal") is not True
        or rollback.get("method") != "reverse_binary_patch_in_disposable_clone"
        or rollback.get("boundary_digest")
        != canonical_sha256(receipt["boundaries"])
        or rollback_digest != canonical_sha256(rollback_unsigned)
        or receipt["rollback_verification"].get("evidence_sha256")
        != rollback_digest
    ):
        raise UpgradeLaneError("rollback artifact does not prove exact B0 restoration")
    private_report, private_raw = _private_json_artifact(
        run_root,
        "migration-report.private.json",
        label="private migration report",
    )
    if (
        private_report.get("schema_version") != "wiki_viva_upgrade_runner_report.v1"
        or private_report.get("status") != "complete"
        or private_report.get("plan_sha256") != receipt["plan_sha256"]
        or private_report.get("identity") != receipt["identity"]
        or private_report.get("rollback_evidence_sha256") != rollback_digest
        or private_report.get("promotion_ready") is not True
        or private_report.get("human_gate_required") is not True
        or receipt["report_verification"].get("evidence_sha256")
        != hashlib.sha256(private_raw).hexdigest()
    ):
        raise UpgradeLaneError("private migration report is stale or unbound")
    report_results = private_report.get("gate_results")
    expected_report_results = [
        {
            "id": result["id"],
            "class": result["class"],
            "status": result["status"],
            "output_sha256": result["output_sha256"],
        }
        for result in sorted(receipt_results, key=lambda item: item["id"])
    ]
    if report_results != expected_report_results:
        raise UpgradeLaneError("migration report gate results differ from receipt")
    evidence = private_report.get("evidence")
    if not isinstance(evidence, Mapping):
        raise UpgradeLaneError("migration report evidence inventory is missing")
    expected_inventory: dict[str, list[dict[str, Any]]] = {
        "gate_logs": [],
        "screenshots": [],
        "console": [],
        "network": [],
    }
    for gate_id in sorted(state_results):
        result = state_results[gate_id]
        expected_inventory["gate_logs"].append(
            {
                "gate_id": gate_id,
                "subject_sha": result.get("subject_sha"),
                "command_sha256": result.get("command_sha256"),
                "output_sha256": result.get("output_sha256"),
            }
        )
        captured = result.get("_evidence")
        if not isinstance(captured, Mapping) or set(captured) != {
            "screenshots",
            "console",
            "network",
        }:
            raise UpgradeLaneError(f"runner state evidence is missing: {gate_id}")
        for kind in ("screenshots", "console", "network"):
            entries = captured.get(kind)
            if not isinstance(entries, list) or not all(
                isinstance(item, dict) for item in entries
            ):
                raise UpgradeLaneError(f"runner state {kind} evidence is invalid")
            expected_inventory[kind].extend(entries)
    for kind, expected_entries in expected_inventory.items():
        if evidence.get(kind) != expected_entries:
            raise UpgradeLaneError(
                f"migration report {kind} inventory differs from runner state"
            )
    validate_canary_evidence(
        package,
        evidence,
        selected_gates=selection["selected_gates"],
        gate_catalog=registry["gate_catalog"],
        subject_sha=identity["consumer_C3"],
    )
    for kind in ("screenshots", "console", "network"):
        entries = evidence.get(kind)
        if not isinstance(entries, list):
            raise UpgradeLaneError(f"migration report {kind} evidence is invalid")
        for item in entries:
            if not isinstance(item, Mapping) or item.get("subject_sha") != identity[
                "consumer_C3"
            ]:
                raise UpgradeLaneError(f"migration report {kind} evidence is stale")
            artifact_file = item.get("artifact_file")
            if artifact_file is None:
                continue
            gate_id = _canonical_repo_path(
                item.get("gate_id"), label=f"{kind} gate id"
            )
            if "/" in gate_id:
                raise UpgradeLaneError(f"{kind} gate id is not canonical")
            relative, artifact = _safe_file_bytes(
                run_root,
                f"evidence/{gate_id}/{artifact_file}",
                label=f"{kind} evidence artifact",
            )
            if hashlib.sha256(artifact).hexdigest() != item.get("sha256"):
                raise UpgradeLaneError(f"{kind} evidence artifact hash differs")
            if kind == "screenshots":
                try:
                    from wiki_core.release_receipt import visual_evidence_file_metadata

                    metadata = visual_evidence_file_metadata(
                        run_root, relative, label="canary screenshot"
                    )
                except (OSError, ValueError) as exc:
                    raise UpgradeLaneError("canary screenshot failed strict PNG verification") from exc
                if (
                    metadata["sha256"] != item.get("sha256")
                    or metadata["dimensions"]
                    != {"width": item.get("width"), "height": item.get("height")}
                ):
                    raise UpgradeLaneError("canary screenshot metadata differs")
            elif item.get("capture") in {
                "gate_emitted_sanitized_network_summary",
                "gate_emitted_browser_console_summary",
            }:
                try:
                    summary = json.loads(artifact)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise UpgradeLaneError(
                        f"{kind} summary artifact is not valid JSON"
                    ) from exc
                if (
                    not isinstance(summary, Mapping)
                    or summary.get("payloads_redacted") is not True
                    or summary.get("error_count") != item.get("error_count")
                    or (
                        kind == "network"
                        and summary.get("request_count")
                        != item.get("request_count")
                    )
                ):
                    raise UpgradeLaneError(
                        f"{kind} summary artifact differs from evidence inventory"
                    )
    public_report, public_raw = _private_json_artifact(
        run_root,
        "migration-report.public.json",
        label="public migration report",
    )
    _assert_public_safe_payload(public_report, label="public migration report")
    public_serialized = canonical_json(public_report)
    if (
        public_report.get("public_redacted") is not True
        or "identity" in public_report
        or public_report.get("identity_sha256") != receipt["identity_sha256"]
        or "consumer_B0" in public_serialized
        or "consumer_C3" in public_serialized
        or identity["consumer_B0"] in public_serialized
        or identity["consumer_C3"] in public_serialized
        or public_report.get("plan_sha256") != receipt["plan_sha256"]
        or public_report.get("human_gate_required") is not True
    ):
        raise UpgradeLaneError("public migration report is stale or not redacted")
    _relative, default_report = _safe_file_bytes(
        run_root, "migration-report.json", label="default migration report"
    )
    if default_report != public_raw:
        raise UpgradeLaneError("default migration report is not the public projection")
    return VerifiedAdoptionEvidence(
        receipt_digest=str(receipt_digest),
        consumer_C3=identity["consumer_C3"],
        gate_results_sha256=canonical_sha256(receipt_results),
        state_sha256=hashlib.sha256(state_raw).hexdigest(),
        rollback_sha256=hashlib.sha256(rollback_raw).hexdigest(),
        private_report_sha256=hashlib.sha256(private_raw).hexdigest(),
        public_report_sha256=hashlib.sha256(public_raw).hexdigest(),
        _authority=_ADOPTION_EVIDENCE_AUTHORITY,
    )


def _require_verified_adoption_evidence(
    receipt: Mapping[str, Any], verified: VerifiedAdoptionEvidence | None
) -> VerifiedAdoptionEvidence:
    unsigned = dict(receipt)
    claimed = unsigned.pop("receipt_sha256", None)
    if (
        not isinstance(verified, VerifiedAdoptionEvidence)
        or verified._authority is not _ADOPTION_EVIDENCE_AUTHORITY
        or claimed != verified.receipt_digest
        or canonical_sha256(unsigned) != verified.receipt_digest
        or receipt.get("identity", {}).get("consumer_C3") != verified.consumer_C3
        or canonical_sha256(receipt.get("gate_results"))
        != verified.gate_results_sha256
    ):
        raise UpgradeLaneError(
            "shape-only adoption receipt cannot authorize reuse or promotion"
        )
    return verified


def verify_adoption_receipt(
    receipt: Mapping[str, Any],
    *,
    expected_identity: Mapping[str, Any],
    expected_plan_sha256: str,
    capsule: Mapping[str, Any],
    verified_capsule: VerifiedReleaseCapsule | None,
    verified_evidence: VerifiedAdoptionEvidence | None,
    package: Mapping[str, Any],
    registry: Mapping[str, Any],
    selection: Mapping[str, Any],
) -> str:
    """Verify receipt reuse against all seven identity terms, fail closed."""

    _require_exact_keys(receipt, _RECEIPT_FIELDS, label="adoption receipt")
    if receipt["schema_version"] != ADOPTION_RECEIPT_SCHEMA_VERSION:
        raise UpgradeLaneError("unsupported adoption receipt schema_version")
    if receipt["status"] != "passed":
        raise UpgradeLaneError("only passed adoption receipts are reusable")
    _assert_public_safe_payload(receipt, label="adoption receipt")
    capsule_sha256 = _require_verified_capsule_token(
        capsule, verified_capsule
    ).digest
    if canonical_sha256(package) != capsule["package_sha256"]:
        raise UpgradeLaneError(
            "adoption package does not match the verified release capsule"
        )
    registry_sha256 = verify_impact_registry(registry)
    identity = adoption_identity(receipt["identity"])
    expected = adoption_identity(expected_identity)
    for field in _IDENTITY_FIELDS:
        if identity[field] != expected[field]:
            raise UpgradeLaneError(f"adoption receipt identity mismatch: {field}")
    for field in _UPSTREAM_IDENTITY_FIELDS:
        if identity[field] != capsule[field]:
            raise UpgradeLaneError(f"capsule/receipt identity mismatch: {field}")
    identity_sha256 = canonical_sha256(identity)
    if receipt["identity_sha256"] != identity_sha256:
        raise UpgradeLaneError("adoption receipt identity_sha256 mismatch")
    if receipt["capsule_sha256"] != capsule_sha256:
        raise UpgradeLaneError("adoption receipt capsule_sha256 mismatch")
    if receipt["impact_registry_sha256"] != registry_sha256:
        raise UpgradeLaneError("adoption receipt impact registry is stale")
    if canonical_sha256(registry["gate_catalog"]) != identity[
        "command_registry_sha256"
    ]:
        raise UpgradeLaneError(
            "current impact registry command catalog differs from receipt identity"
        )
    _assert_sha(expected_plan_sha256, label="expected plan_sha256", sha256=True)
    if receipt["plan_sha256"] != expected_plan_sha256:
        raise UpgradeLaneError("adoption receipt plan is stale")
    resume = receipt["resume"]
    _require_exact_keys(
        resume,
        {"identity_sha256", "plan_sha256", "completed_gates"},
        label="resume state",
    )
    if resume["identity_sha256"] != identity_sha256:
        raise UpgradeLaneError("resume state identity is stale")
    if resume["plan_sha256"] != expected_plan_sha256:
        raise UpgradeLaneError("resume state plan is stale")
    if selection["registry_sha256"] != registry_sha256:
        raise UpgradeLaneError("impact selection used a stale registry")
    if receipt["impact_derivation_sha256"] != selection["derivation_sha256"]:
        raise UpgradeLaneError("adoption receipt impact derivation mismatch")
    if selection["requires_lane_a"]:
        raise UpgradeLaneError("impact requires a new Lane A capsule before adoption")
    classes, commands = _catalog_maps(registry)
    selected = set(selection["selected_gates"])
    if not NEVER_REUSABLE_GATES.issubset(selected):
        raise UpgradeLaneError("impact selection omitted a never-reusable gate")
    results = receipt["gate_results"]
    if not isinstance(results, list) or not results:
        raise UpgradeLaneError("adoption receipt must contain executed gate results")
    result_by_id: dict[str, Mapping[str, Any]] = {}
    for result in results:
        _require_exact_keys(
            result,
            {
                "id",
                "class",
                "provenance",
                "status",
                "exit_code",
                "subject_sha",
                "command_sha256",
                "output_sha256",
            },
            label="gate result",
        )
        gate_id = result["id"]
        if gate_id in result_by_id:
            raise UpgradeLaneError(f"duplicate gate result: {gate_id}")
        if gate_id not in selected or gate_id not in classes:
            raise UpgradeLaneError(f"gate result is not selected/registered: {gate_id}")
        if result["class"] != classes[gate_id]:
            raise UpgradeLaneError(f"gate result class mismatch: {gate_id}")
        if result["provenance"] != "executed":
            raise UpgradeLaneError(f"manual/fabricated evidence is forbidden: {gate_id}")
        if result["status"] != "passed" or result["exit_code"] != 0:
            raise UpgradeLaneError(f"gate result did not pass: {gate_id}")
        if result["subject_sha"] != identity["consumer_C3"]:
            raise UpgradeLaneError(f"gate result is stale after C3 changed: {gate_id}")
        if result["command_sha256"] != _command_digest(commands[gate_id]):
            raise UpgradeLaneError(f"gate result command digest mismatch: {gate_id}")
        _assert_sha(result["output_sha256"], label="gate output_sha256", sha256=True)
        result_by_id[gate_id] = result
    if set(result_by_id) != selected:
        raise UpgradeLaneError("gate results must exactly cover selected gates")
    completed = resume["completed_gates"]
    if completed != sorted(selected):
        raise UpgradeLaneError("resume completed_gates are stale or incomplete")
    verify_gate_omissions(
        registry,
        selection,
        receipt["omitted_gates"],
        capsule,
        verified_capsule=verified_capsule,
    )
    validate_boundary_ownership(
        receipt["boundaries"], registry, package=package
    )
    for field in ("rollback_verification", "report_verification"):
        verification = receipt[field]
        _require_exact_keys(
            verification,
            {"provenance", "status", "subject_sha", "evidence_sha256"},
            label=field,
        )
        if verification["provenance"] != "executed":
            raise UpgradeLaneError(f"{field} must come from execution")
        if verification["status"] != "verified":
            raise UpgradeLaneError(f"{field} is not verified")
        if verification["subject_sha"] != identity["consumer_C3"]:
            raise UpgradeLaneError(f"{field} is stale after C3 changed")
        _assert_sha(
            verification["evidence_sha256"],
            label=f"{field} evidence_sha256",
            sha256=True,
        )
    _require_verified_adoption_evidence(receipt, verified_evidence)
    unsigned = dict(receipt)
    claimed_digest = unsigned.pop("receipt_sha256")
    digest = canonical_sha256(unsigned)
    if digest != claimed_digest:
        raise UpgradeLaneError("adoption receipt canonical digest mismatch")
    return digest


__all__ = [
    "ADOPTION_RECEIPT_SCHEMA_VERSION",
    "AdoptionEvidenceAuthority",
    "EXECUTION_ATTESTATION_SCHEMA_VERSION",
    "GATE_CLASSES",
    "IMPACT_REGISTRY_SCHEMA_VERSION",
    "NEVER_REUSABLE_GATES",
    "RELEASE_CAPSULE_SCHEMA_VERSION",
    "TOOLCHAIN_PROBE_SCHEMA_VERSION",
    "ReleaseCapsuleAuthority",
    "UpgradeLaneError",
    "VerifiedReleaseCapsule",
    "VerifiedAdoptionEvidence",
    "adoption_identity",
    "canonical_json",
    "canonical_sha256",
    "collect_release_attestation",
    "load_mapping",
    "seal_adoption_receipt",
    "seal_impact_registry",
    "seal_release_capsule",
    "select_impacted_gates",
    "validate_boundary_ownership",
    "validate_c1_projection",
    "validate_canary_evidence",
    "verify_adoption_evidence",
    "verify_adoption_receipt",
    "verify_gate_omissions",
    "verify_impact_registry",
    "verify_release_capsule",
]
