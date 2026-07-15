"""Fail-closed contracts for two-lane downstream upgrades.

Lane A certifies one immutable portable release and emits a canonical capsule.
Lane B plans and proves the exact consumer delta.  This module is deliberately
deterministic: it does not mutate repositories, execute gates or contain an LLM
client.  It validates the evidence produced by a future resumable runner.
"""

from __future__ import annotations

import copy
import datetime as dt
import fnmatch
import hashlib
import io
import json
import math
import os
import re
import stat
from urllib.parse import parse_qsl, unquote_to_bytes, urlsplit
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml
from jsonschema import Draft202012Validator

from wiki_core.config import WikiConfig
from wiki_core.detectors import scan_text
from wiki_core.git_safety import (
    GitSafetyError,
    require_safe_local_config,
    resolved_git_executable,
    sanitized_git_argv,
    sanitized_git_environment,
)
from wiki_core.process_safety import ProcessSafetyError, run_bounded_process
from wiki_core.node_workspace import (
    MANIFEST_RELATIVE as NODE_WORKSPACE_POLICY_RELATIVE,
    PACKAGE_LOCK_RELATIVE as NODE_WORKSPACE_PACKAGE_LOCK_RELATIVE,
    PACKAGE_RELATIVE as NODE_WORKSPACE_PACKAGE_RELATIVE,
    NodeWorkspaceError,
    authority_identity_sha256,
    npm_workspace_toolchain_identity,
    validate_authority as validate_node_workspace_authority,
    validate_policy as validate_node_workspace_policy,
)


LEGACY_RELEASE_CAPSULE_SCHEMA_VERSION = "wiki_viva_upgrade_release_capsule.v1"
RELEASE_CAPSULE_SCHEMA_VERSION = "wiki_viva_upgrade_release_capsule.v2"
IMPACT_REGISTRY_SCHEMA_VERSION = "wiki_viva_upgrade_impact_registry.v1"
ADOPTION_RECEIPT_SCHEMA_VERSION = "wiki_viva_upgrade_adoption_receipt.v4"
LEGACY_EXECUTION_ATTESTATION_SCHEMA_VERSION = (
    "wiki_viva_upgrade_execution_attestation.v1"
)
EXECUTION_ATTESTATION_SCHEMA_VERSION = "wiki_viva_upgrade_execution_attestation.v2"
LEGACY_TOOLCHAIN_PROBE_SCHEMA_VERSION = "wiki_viva_toolchain_probe.v1"
TOOLCHAIN_PROBE_SCHEMA_VERSION = "wiki_viva_toolchain_probe.v2"
CONSUMER_C3_AUTHORITY_SCHEMA_VERSION = "wiki_viva_upgrade_consumer_c3_authority.v1"
CONFIG_BOUND_C3_POLICY_SCHEMA_VERSION = "wiki_viva_config_bound_c3_policy.v1"
VISUAL_CAPTURE_SCHEMA_VERSION = "wiki_visual_evidence_capture.v2"
VISUAL_MANIFEST_SCHEMA_VERSION = "wiki_visual_evidence_manifest.v1"
VISUAL_CAPTURE_METHOD = "playwright_served_public_synthetic"

VISUAL_PROFILE_CONTRACTS: dict[str, dict[str, Any]] = {
    "desktop": {
        "route": "/demo/w?center=root-alex-rivera&view=quadrants&tour=0",
        "canary_route": "/w?view=quadrants&tour=0",
        "view": "quadrants",
        "viewport": {"width": 1440, "height": 1000},
        "canary_viewport": {"width": 1440, "height": 1000},
        "action_count": 0,
        "state": "webgl",
        "runtime_mode": "v8",
    },
    "mobile": {
        "route": "/demo/w?view=timeline&tour=0",
        "canary_route": "/w?view=timeline&tour=0",
        "view": "timeline",
        "viewport": {"width": 390, "height": 844},
        "canary_viewport": {"width": 390, "height": 844},
        "action_count": 0,
        "state": "timeline",
        "runtime_mode": "v8",
    },
    "fallback": {
        "route": ("/demo/w?center=root-alex-rivera&view=quadrants&visual=1&tour=0"),
        "canary_route": "/w?view=quadrants&visual=1&tour=0",
        "view": "quadrants",
        "viewport": {"width": 1280, "height": 900},
        "canary_viewport": {"width": 1440, "height": 1000},
        "action_count": 0,
        "state": "fallback",
        "runtime_mode": "v8",
    },
    "quadrant_collection_two_step": {
        "route": (
            "/demo/w?center=root-alex-rivera&view=quadrants&lens=q2_pratica"
            "&overlay=actions&tour=0"
        ),
        "canary_route": ("/w?view=quadrants&lens=q2_pratica&overlay=actions&tour=0"),
        "view": "quadrants",
        "viewport": {"width": 1440, "height": 1000},
        "canary_viewport": {"width": 1440, "height": 1000},
        "action_count": 2,
        "state": "quadrant_collection_two_step",
        "runtime_mode": "v8",
    },
}

CONFIG_BOUND_C3_ROLE_SPECS = (
    {
        "id": "command_reference_page",
        "kind": "exact_markdown",
        "path_key": "command_reference_page",
        "impact_contract": "wiki_consumer_command_reference.v1",
        "mode": "100644",
        "suffix": ".md",
    },
    {
        "id": "operational_pass_page",
        "kind": "exact_markdown",
        "path_key": "operational_pass_page",
        "impact_contract": "wiki_consumer_operational_pass.v1",
        "mode": "100644",
        "suffix": ".md",
    },
    {
        "id": "release_records",
        "kind": "inert_markdown_subtree",
        "path_key": "references_root",
        "subtree": "releases",
        "impact_contract": "wiki_consumer_release_record.v1",
        "mode": "100644",
        "suffix": ".md",
    },
)

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
LEGACY_RELEASE_CAPSULE_SCHEMA_PATH = (
    _ROOT / "docs/references/schemas/wiki-upgrade-release-capsule-v1.schema.json"
)
RELEASE_CAPSULE_SCHEMA_PATH = (
    _ROOT / "docs/references/schemas/wiki-upgrade-release-capsule-v2.schema.json"
)
IMPACT_REGISTRY_SCHEMA_PATH = (
    _ROOT / "docs/references/schemas/wiki-upgrade-impact-registry-v1.schema.json"
)
UPGRADE_PACKAGE_V3_SCHEMA_PATH = (
    _ROOT / "docs/references/schemas/wiki-upgrade-package-v3.schema.json"
)

_SHA_RE = re.compile(r"^[0-9a-f]{40,64}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{1,127}$")
_CANARY_ROUTE_VALUE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_CONTRACT_RE = re.compile(r"^[a-z][a-z0-9_.:+-]{1,127}$")
_LOCAL_PATH_RE = re.compile(
    r"(?:"
    r"(?<![\w.-])/(?:Applications|Library|System|Users|Volumes|__w|bin|boot|builds|dev|etc|github|home|lib|lib64|media|mnt|nix|opt|proc|root|run|sbin|srv|sys|tmp|usr|var|workspace)(?:/|$)"
    r"|file://|(?<![\w.-])~[/\\]|[A-Za-z]:\\|\\\\[^\\\s]+\\"
    r")"
)
_PRIVATE_PATH_RE = re.compile(
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
_PRIVATE_VISUAL_TOKEN_RE = re.compile(
    r"(?:^|[^a-z0-9])(?:private|consumer|real)(?:$|[^a-z0-9])",
    re.IGNORECASE,
)
_SECRET_QUERY_KEY_RE = re.compile(
    r"(?:authorization|cookie|credential|password|secret|session|signature|token|api[-_]?key)",
    re.IGNORECASE,
)
_PERCENT_ESCAPE_RE = re.compile(r"%[0-9A-Fa-f]{2}")
_MAX_PERCENT_DECODE_ROUNDS = 3
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
    "consumer_c3_authority_sha256",
    "acceptance_budget",
    "canary_completion_anchor",
    "resume",
    "boundary_commits",
    "boundaries",
    "gate_results",
    "omitted_gates",
    "rollback_verification",
    "report_verification",
    "receipt_sha256",
}
_ACCEPTANCE_BUDGET_FIELDS = {
    "schema_version",
    "scope",
    "limit_seconds",
    "enforcement",
    "plan_started_at",
    "canary_completed_at",
    "elapsed_milliseconds",
    "status",
}
_ACCEPTANCE_TIMESTAMP_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$"
)
_UNIX_EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
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
    trusted_canary_completion_anchor_sha256: str


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
    consumer_c3_authority_sha256: str
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
    payload = (
        json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
    )
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


def _require_schema(
    payload: Mapping[str, Any], schema_path: Path, *, label: str
) -> None:
    errors = _schema_errors(payload, schema_path)
    if errors:
        raise UpgradeLaneError(f"{label} schema rejected: {'; '.join(errors)}")


def _require_exact_keys(
    payload: Mapping[str, Any], expected: set[str], *, label: str
) -> None:
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
    if isinstance(value, Mapping):
        for child_key, child in value.items():
            if isinstance(child_key, str):
                # Mapping keys are publication data too.  Treating only leaf
                # values as data lets a forged report smuggle a path or route
                # through an otherwise innocuous nested key.
                yield "<mapping-key>", child_key
            yield from _walk_strings(child, key=str(child_key))
    elif isinstance(value, list):
        for child in value:
            yield from _walk_strings(child, key=key)
    elif isinstance(value, str):
        yield key, value


def _assert_public_safe_payload(payload: Mapping[str, Any], *, label: str) -> None:
    """Reject host paths, private evidence roots, private routes and secrets."""

    for key, value in _walk_strings(payload):
        try:
            views = _percent_decoded_views(value)
        except (UnicodeDecodeError, ValueError) as exc:
            raise UpgradeLaneError(
                f"{label} contains invalid percent-encoded publication data"
            ) from exc
        for view in views:
            if _LOCAL_PATH_RE.search(view):
                raise UpgradeLaneError(f"{label} contains a host-local path")
            if _SECRET_ASSIGNMENT_RE.search(view):
                raise UpgradeLaneError(f"{label} contains secret/private data")
            if _PRIVATE_PATH_RE.search(view):
                raise UpgradeLaneError(f"{label} contains a private evidence path")
            if _PRIVATE_ROUTE_RE.search(view):
                raise UpgradeLaneError(f"{label} contains a private consumer route")
    findings = []
    for view in _percent_decoded_views(canonical_json(payload)):
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
        kinds = ", ".join(sorted({finding.kind for finding in findings}))
        raise UpgradeLaneError(f"{label} contains secret/private data: {kinds}")


def _percent_decoded_views(value: str) -> tuple[str, ...]:
    """Return bounded canonical views so encoded private routes cannot hide."""

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


def _contains_private_route(value: str) -> bool:
    try:
        return any(
            _PRIVATE_ROUTE_RE.search(view) for view in _percent_decoded_views(value)
        )
    except (UnicodeDecodeError, ValueError):
        return True


def _public_visual_route(value: object, *, label: str) -> str:
    """Return one bounded /demo route with encoded private state rejected."""

    if not isinstance(value, str) or not value or len(value) > 1024:
        raise UpgradeLaneError(f"{label} must be a bounded public demo route")
    try:
        views = _percent_decoded_views(value)
    except (UnicodeDecodeError, ValueError) as exc:
        raise UpgradeLaneError(f"{label} contains invalid percent encoding") from exc
    for view in views:
        parsed = urlsplit(view)
        if (
            parsed.scheme
            or parsed.netloc
            or parsed.fragment
            or not (parsed.path == "/demo" or parsed.path.startswith("/demo/"))
            or _PRIVATE_VISUAL_TOKEN_RE.search(view)
        ):
            raise UpgradeLaneError(f"{label} is not a public-synthetic /demo route")
        for key, item in parse_qsl(
            parsed.query, keep_blank_values=True, strict_parsing=False
        ):
            if _SECRET_QUERY_KEY_RE.search(key) or _PRIVATE_VISUAL_TOKEN_RE.search(
                item
            ):
                raise UpgradeLaneError(
                    f"{label} contains private or credential-shaped query state"
                )
    return value


def validate_canary_profile_route(profile: object, value: object) -> str:
    """Require one canonical native operator route for a versioned profile."""

    if not isinstance(profile, str) or profile not in VISUAL_PROFILE_CONTRACTS:
        raise UpgradeLaneError("canary visual profile has no native route contract")
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise UpgradeLaneError("canary visual route must be one bounded native route")
    if _contains_private_route(value):
        raise UpgradeLaneError("canary visual route contains private state")
    spec = VISUAL_PROFILE_CONTRACTS[profile]
    expected = urlsplit(str(spec["canary_route"]))
    expected_query = dict(
        parse_qsl(expected.query, keep_blank_values=True, strict_parsing=True)
    )
    allowed_dynamic = {"group"} if profile == "quadrant_collection_two_step" else set()
    try:
        views = _percent_decoded_views(value)
    except (UnicodeDecodeError, ValueError) as exc:
        raise UpgradeLaneError(
            "canary visual route has invalid percent encoding"
        ) from exc
    for view in views:
        parsed = urlsplit(view)
        pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=False)
        keys = [key for key, _item in pairs]
        query = dict(pairs)
        if (
            parsed.scheme
            or parsed.netloc
            or parsed.fragment
            or parsed.path != expected.path
            or len(keys) != len(set(keys))
            or not set(query).issubset(set(expected_query) | allowed_dynamic)
            or any(query.get(key) != item for key, item in expected_query.items())
            or any(
                _CANARY_ROUTE_VALUE_RE.fullmatch(item) is None
                for key, item in pairs
                if key in allowed_dynamic
            )
        ):
            raise UpgradeLaneError(
                "canary visual route differs from its native profile contract"
            )
    return value


def _unique_ids(items: Sequence[Mapping[str, Any]], *, label: str) -> list[str]:
    ids = [str(item.get("id", "")) for item in items]
    if len(ids) != len(set(ids)):
        raise UpgradeLaneError(f"{label} IDs must be unique")
    if ids != sorted(ids):
        raise UpgradeLaneError(f"{label} must be sorted by id")
    return ids


def _command_digest(command: str) -> str:
    return hashlib.sha256(command.encode("utf-8")).hexdigest()


def _require_safe_git_authority(root: Path, *, label: str) -> None:
    """Reject repository-local configuration capable of process execution."""

    try:
        require_safe_local_config(root)
    except GitSafetyError as exc:
        raise UpgradeLaneError(
            f"{label} Git configuration contains executable policy"
        ) from exc


def _git_bytes(
    root: Path,
    arguments: Sequence[str],
    *,
    label: str,
    input_bytes: bytes | None = None,
) -> bytes:
    try:
        executable = resolved_git_executable()
        result = run_bounded_process(
            sanitized_git_argv(arguments, executable=executable),
            cwd=root,
            env=sanitized_git_environment(executable=executable),
            timeout=120,
            output_limit=256 * 1024 * 1024,
            input_bytes=input_bytes,
            input_limit=64 * 1024 * 1024,
        )
    except (GitSafetyError, OSError, ProcessSafetyError) as exc:
        raise UpgradeLaneError(
            f"{label} could not be read from exact Git authority"
        ) from exc
    if result.returncode != 0:
        raise UpgradeLaneError(f"{label} could not be read from exact Git authority")
    return result.output


def _git_blob_payloads(
    root: Path, object_ids: Sequence[str], *, label: str
) -> dict[str, bytes]:
    """Read an exact set of blobs through one bounded Git batch."""

    ordered = sorted(set(object_ids))
    if not ordered:
        return {}
    if any(re.fullmatch(r"[0-9a-f]{40,64}", value) is None for value in ordered):
        raise UpgradeLaneError(f"{label} contains an invalid Git object identity")
    raw = _git_bytes(
        root,
        ["cat-file", "--batch"],
        label=label,
        input_bytes="".join(f"{value}\n" for value in ordered).encode("ascii"),
    )
    payloads: dict[str, bytes] = {}
    stream = io.BytesIO(raw)
    for expected in ordered:
        try:
            fields = stream.readline().decode("ascii", "strict").strip().split()
        except UnicodeDecodeError as exc:
            raise UpgradeLaneError(f"{label} has a non-canonical batch header") from exc
        if len(fields) != 3 or fields[0] != expected or fields[1] != "blob":
            raise UpgradeLaneError(f"{label} is incomplete or not a blob batch")
        try:
            size = int(fields[2])
        except ValueError as exc:
            raise UpgradeLaneError(f"{label} has an invalid blob size") from exc
        if size < 0 or size > 256 * 1024 * 1024:
            raise UpgradeLaneError(f"{label} exceeds the bounded blob authority")
        payload = stream.read(size)
        if len(payload) != size or stream.read(1) != b"\n":
            raise UpgradeLaneError(f"{label} is truncated")
        payloads[expected] = payload
    if stream.read(1):
        raise UpgradeLaneError(f"{label} has trailing batch output")
    return payloads


def _git_regular_blob(
    root: Path,
    commit: str,
    path: str,
    *,
    label: str,
) -> dict[str, str] | None:
    """Return one exact regular Git blob projection or ``None`` when absent."""

    listing = _git_bytes(
        root,
        ["ls-tree", "-z", commit, "--", path],
        label=f"{label} tree entry",
    )
    records = [record for record in listing.split(b"\0") if record]
    if not records:
        return None
    if len(records) != 1:
        raise UpgradeLaneError(f"{label} resolves to multiple Git tree entries")
    try:
        metadata, raw_path = records[0].split(b"\t", 1)
        mode, object_type, object_id = metadata.decode("ascii").split(" ", 2)
        observed_path = raw_path.decode("utf-8", "strict")
    except (ValueError, UnicodeDecodeError) as exc:
        raise UpgradeLaneError(f"{label} has an invalid Git tree entry") from exc
    if observed_path != path:
        raise UpgradeLaneError(f"{label} differs from the requested Git path")
    if object_type != "blob" or mode not in {"100644", "100755"}:
        raise UpgradeLaneError(
            f"{label} must be a regular Git blob with mode 100644 or 100755"
        )
    raw = _git_bytes(
        root,
        ["cat-file", "blob", object_id],
        label=f"{label} blob",
    )
    return {"mode": mode, "sha256": hashlib.sha256(raw).hexdigest()}


def _config_bound_c3_policy(package: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the package-sealed, deliberately narrow B0 path policy."""

    migration = package.get("migration")
    operations = (
        migration.get("boundary_operations") if isinstance(migration, Mapping) else None
    )
    adapter = operations.get("c3_adapter") if isinstance(operations, Mapping) else None
    policy = (
        adapter.get("configured_ownership") if isinstance(adapter, Mapping) else None
    )
    if not isinstance(policy, Mapping):
        raise UpgradeLaneError("package omits config-bound C3 ownership policy")
    _require_exact_keys(
        policy,
        {"schema_version", "config_path", "roles"},
        label="config-bound C3 ownership policy",
    )
    if (
        policy.get("schema_version") != CONFIG_BOUND_C3_POLICY_SCHEMA_VERSION
        or policy.get("config_path") != "wiki.config.yaml"
        or policy.get("roles") != list(CONFIG_BOUND_C3_ROLE_SPECS)
    ):
        raise UpgradeLaneError("config-bound C3 ownership policy is not exact")
    return policy


def _git_regular_blob_bytes(
    root: Path,
    commit: str,
    path: str,
    *,
    label: str,
) -> tuple[str, bytes] | None:
    """Read one committed regular blob and preserve its exact Git mode."""

    listing = _git_bytes(
        root,
        ["ls-tree", "-z", commit, "--", path],
        label=f"{label} tree entry",
    )
    records = [record for record in listing.split(b"\0") if record]
    if not records:
        return None
    if len(records) != 1:
        raise UpgradeLaneError(f"{label} resolves to multiple Git tree entries")
    try:
        metadata, raw_path = records[0].split(b"\t", 1)
        mode, object_type, object_id = metadata.decode("ascii").split(" ", 2)
        observed_path = raw_path.decode("utf-8", "strict")
    except (ValueError, UnicodeDecodeError) as exc:
        raise UpgradeLaneError(f"{label} has an invalid Git tree entry") from exc
    if observed_path != path:
        raise UpgradeLaneError(f"{label} differs from the requested Git path")
    if object_type != "blob" or mode not in {"100644", "100755"}:
        raise UpgradeLaneError(f"{label} is not a regular Git blob")
    raw = _git_bytes(
        root,
        ["cat-file", "blob", object_id],
        label=f"{label} blob",
    )
    return mode, raw


def _authority_without_digest(authority: Mapping[str, Any]) -> dict[str, Any]:
    unsigned = copy.deepcopy(dict(authority))
    unsigned.pop("authority_sha256", None)
    return unsigned


def _validate_consumer_c3_authority_shape(
    authority: Mapping[str, Any],
) -> str:
    _require_exact_keys(
        authority,
        {
            "schema_version",
            "consumer_B0",
            "package_sha256",
            "policy_sha256",
            "config",
            "layout",
            "exact_markdown_paths",
            "release_records",
            "authority_sha256",
        },
        label="consumer C3 authority",
    )
    if authority.get("schema_version") != CONSUMER_C3_AUTHORITY_SCHEMA_VERSION:
        raise UpgradeLaneError("consumer C3 authority schema_version is invalid")
    _assert_sha(authority.get("consumer_B0"), label="consumer C3 authority B0")
    _assert_sha(
        authority.get("package_sha256"),
        label="consumer C3 authority package",
        sha256=True,
    )
    _assert_sha(
        authority.get("policy_sha256"),
        label="consumer C3 authority policy",
        sha256=True,
    )
    config = authority.get("config")
    layout = authority.get("layout")
    exact = authority.get("exact_markdown_paths")
    release = authority.get("release_records")
    if not isinstance(config, Mapping):
        raise UpgradeLaneError("consumer C3 authority config is invalid")
    _require_exact_keys(config, {"path", "mode", "sha256"}, label="B0 config")
    if config.get("path") != "wiki.config.yaml" or config.get("mode") != "100644":
        raise UpgradeLaneError(
            "consumer C3 authority config must be inert wiki.config.yaml"
        )
    _assert_sha(config.get("sha256"), label="B0 config blob", sha256=True)
    if not isinstance(layout, Mapping):
        raise UpgradeLaneError("consumer C3 authority layout is invalid")
    _require_exact_keys(
        layout,
        {"memory_root", "references_root"},
        label="consumer C3 authority layout",
    )
    memory_root = _canonical_repo_path(
        layout.get("memory_root"), label="consumer memory root"
    )
    references_root = _canonical_repo_path(
        layout.get("references_root"), label="consumer references root"
    )
    if (
        memory_root == references_root
        or memory_root.startswith(f"{references_root}/")
        or references_root.startswith(f"{memory_root}/")
    ):
        raise UpgradeLaneError("consumer memory and references roots must be disjoint")
    if not isinstance(exact, list) or len(exact) != 2:
        raise UpgradeLaneError("consumer C3 exact Markdown authority is incomplete")
    expected_exact = list(CONFIG_BOUND_C3_ROLE_SPECS[:2])
    observed_roles: list[str] = []
    observed_paths: list[str] = []
    for item, spec in zip(exact, expected_exact):
        if not isinstance(item, Mapping):
            raise UpgradeLaneError("consumer C3 exact Markdown role is invalid")
        _require_exact_keys(
            item,
            {"role", "path", "impact_contract", "mode", "suffix"},
            label="consumer C3 exact Markdown role",
        )
        path = _canonical_repo_path(item.get("path"), label="configured C3 path")
        if (
            item.get("role") != spec["id"]
            or item.get("impact_contract") != spec["impact_contract"]
            or item.get("mode") != "100644"
            or item.get("suffix") != ".md"
            or not path.endswith(".md")
            or not path.startswith(f"{memory_root}/")
        ):
            raise UpgradeLaneError("consumer C3 exact Markdown role is outside policy")
        observed_roles.append(str(item["role"]))
        observed_paths.append(path)
    if len(observed_paths) != len(set(observed_paths)):
        raise UpgradeLaneError("consumer C3 exact Markdown paths must be distinct")
    if not isinstance(release, Mapping):
        raise UpgradeLaneError("consumer release-record authority is invalid")
    _require_exact_keys(
        release,
        {"role", "root", "impact_contract", "mode", "suffix"},
        label="consumer release-record authority",
    )
    release_root = _canonical_repo_path(
        release.get("root"), label="consumer release-record root"
    )
    release_spec = CONFIG_BOUND_C3_ROLE_SPECS[2]
    if (
        release.get("role") != release_spec["id"]
        or release.get("impact_contract") != release_spec["impact_contract"]
        or release.get("mode") != "100644"
        or release.get("suffix") != ".md"
        or release_root != f"{references_root}/releases"
    ):
        raise UpgradeLaneError("consumer release-record authority is outside policy")
    claimed = _assert_sha(
        authority.get("authority_sha256"),
        label="consumer C3 authority digest",
        sha256=True,
    )
    if canonical_sha256(_authority_without_digest(authority)) != claimed:
        raise UpgradeLaneError("consumer C3 authority canonical digest mismatch")
    return claimed


def derive_consumer_c3_authority(
    *,
    consumer_B0: str,
    package: Mapping[str, Any],
    config_mode: str,
    config_bytes: bytes,
) -> dict[str, Any]:
    """Resolve the only C3 domain exceptions from the exact B0 config blob."""

    _assert_sha(consumer_B0, label="consumer C3 authority B0")
    policy = _config_bound_c3_policy(package)
    if config_mode != "100644" or len(config_bytes) > 4 * 1024 * 1024:
        raise UpgradeLaneError("B0 wiki.config.yaml must be one bounded 100644 blob")
    if b"\0" in config_bytes:
        raise UpgradeLaneError("B0 wiki.config.yaml must be UTF-8 text")
    try:
        config_text = config_bytes.decode("utf-8", "strict")
        raw = yaml.safe_load(config_text)
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise UpgradeLaneError("B0 wiki.config.yaml is not valid UTF-8 YAML") from exc
    if not isinstance(raw, Mapping):
        raise UpgradeLaneError("B0 wiki.config.yaml must contain a mapping")
    if any(finding.category == "secret" for finding in scan_text(config_text)):
        raise UpgradeLaneError("B0 wiki.config.yaml contains an access secret")
    raw_paths = raw.get("paths", {})
    if raw_paths is None:
        raw_paths = {}
    if not isinstance(raw_paths, Mapping):
        raise UpgradeLaneError("B0 wiki.config.yaml paths must be a mapping")
    paths = dict(WikiConfig().paths)
    for key in {
        "memory_root",
        "references_root",
        "command_reference_page",
        "operational_pass_page",
    }:
        if key in raw_paths:
            value = raw_paths[key]
            if not isinstance(value, str) or not value:
                raise UpgradeLaneError(f"B0 config path {key} must be a string")
            paths[key] = value
    memory_root = _canonical_repo_path(
        paths["memory_root"], label="consumer memory root"
    )
    references_root = _canonical_repo_path(
        paths["references_root"], label="consumer references root"
    )
    exact_items: list[dict[str, str]] = []
    for spec in CONFIG_BOUND_C3_ROLE_SPECS[:2]:
        path = _canonical_repo_path(
            paths[str(spec["path_key"])],
            label=f"configured {spec['id']} path",
        )
        exact_items.append(
            {
                "role": str(spec["id"]),
                "path": path,
                "impact_contract": str(spec["impact_contract"]),
                "mode": "100644",
                "suffix": ".md",
            }
        )
    release_root = _canonical_repo_path(
        f"{references_root}/releases", label="configured release-record root"
    )
    authority: dict[str, Any] = {
        "schema_version": CONSUMER_C3_AUTHORITY_SCHEMA_VERSION,
        "consumer_B0": consumer_B0,
        "package_sha256": canonical_sha256(package),
        "policy_sha256": canonical_sha256(policy),
        "config": {
            "path": str(policy["config_path"]),
            "mode": config_mode,
            "sha256": hashlib.sha256(config_bytes).hexdigest(),
        },
        "layout": {
            "memory_root": memory_root,
            "references_root": references_root,
        },
        "exact_markdown_paths": exact_items,
        "release_records": {
            "role": "release_records",
            "root": release_root,
            "impact_contract": "wiki_consumer_release_record.v1",
            "mode": "100644",
            "suffix": ".md",
        },
    }
    authority["authority_sha256"] = canonical_sha256(authority)
    _validate_consumer_c3_authority_shape(authority)

    migration = package.get("migration")
    generated = (
        migration.get("generated_artifact_patterns")
        if isinstance(migration, Mapping)
        else []
    )
    portable = package.get("portable_import")
    allow = portable.get("allow") if isinstance(portable, Mapping) else []
    block = portable.get("block") if isinstance(portable, Mapping) else []
    probes = [
        *(item["path"] for item in exact_items),
        f"{release_root}/authority-probe.md",
    ]
    for path in probes:
        if _matches(path, generated or []):
            raise UpgradeLaneError("configured C3 authority overlaps C2 ownership")
        if _matches(path, allow or []) and not _matches(path, block or []):
            raise UpgradeLaneError("configured C3 authority overlaps C1 ownership")
        first = path.split("/", 1)[0]
        if first in {
            ".git",
            ".wiki-viva",
            ".evidence",
            "evidence",
            "private",
            "secrets",
        } or path.startswith(("data/raw/", "data/derived/")):
            raise UpgradeLaneError("configured C3 authority enters a forbidden root")
    return authority


def consumer_c3_authority_from_git(
    consumer_root: Path,
    consumer_B0: str,
    package: Mapping[str, Any],
) -> dict[str, Any]:
    """Reconstruct C3 authority from ``consumer_B0:wiki.config.yaml`` only."""

    consumer = consumer_root.resolve(strict=True)
    _require_safe_git_authority(consumer, label="consumer authority")
    policy = _config_bound_c3_policy(package)
    config_path = _canonical_repo_path(policy["config_path"], label="B0 config path")
    entry = _git_regular_blob_bytes(
        consumer,
        consumer_B0,
        config_path,
        label="B0 wiki.config.yaml",
    )
    if entry is None:
        raise UpgradeLaneError("B0 wiki.config.yaml is missing")
    mode, raw = entry
    return derive_consumer_c3_authority(
        consumer_B0=consumer_B0,
        package=package,
        config_mode=mode,
        config_bytes=raw,
    )


def verify_consumer_c3_authority(
    authority: Mapping[str, Any],
    *,
    consumer_root: Path,
    consumer_B0: str,
    package: Mapping[str, Any],
) -> str:
    """Compare a plan-carried authority with a fresh B0 Git derivation."""

    expected = consumer_c3_authority_from_git(consumer_root, consumer_B0, package)
    if dict(authority) != expected:
        raise UpgradeLaneError("consumer C3 authority differs from exact B0 config")
    return _validate_consumer_c3_authority_shape(authority)


def classify_consumer_c3_path(path: str, authority: Mapping[str, Any]) -> str | None:
    """Return the exact config-derived technical role for one C3 path."""

    _validate_consumer_c3_authority_shape(authority)
    normalized = _canonical_repo_path(path, label="consumer C3 path")
    for item in authority["exact_markdown_paths"]:
        if normalized == item["path"]:
            return str(item["role"])
    release = authority["release_records"]
    if normalized.startswith(f"{release['root']}/") and normalized.endswith(
        str(release["suffix"])
    ):
        return str(release["role"])
    return None


def consumer_c3_authority_patterns(
    authority: Mapping[str, Any],
) -> list[str]:
    _validate_consumer_c3_authority_shape(authority)
    return [
        *(str(item["path"]) for item in authority["exact_markdown_paths"]),
        f"{authority['release_records']['root']}/**",
    ]


def verify_config_bound_c3_git_content(
    consumer_root: Path,
    *,
    commits: Mapping[str, str],
    boundaries: Mapping[str, Any],
    authority: Mapping[str, Any],
    package: Mapping[str, Any],
) -> None:
    """Prove authorized technical postimages are inert Markdown in Git."""

    verify_consumer_c3_authority(
        authority,
        consumer_root=consumer_root,
        consumer_B0=str(commits.get("B0") or ""),
        package=package,
    )
    c3_items = boundaries.get("C3")
    if not isinstance(c3_items, list):
        raise UpgradeLaneError("C3 boundary is invalid")
    c2 = _assert_sha(commits.get("C2"), label="consumer C2")
    c3 = _assert_sha(commits.get("C3"), label="consumer C3")
    release_root = str(authority["release_records"]["root"])
    for item in c3_items:
        if not isinstance(item, Mapping):
            raise UpgradeLaneError("C3 boundary entry is invalid")
        path = _canonical_repo_path(item.get("path"), label="C3 path")
        role = classify_consumer_c3_path(path, authority)
        under_release_root = path.startswith(f"{release_root}/")
        if role is None:
            if under_release_root:
                raise UpgradeLaneError("release record must be a Markdown descendant")
            continue
        subject = c3 if item.get("operation") == "upsert" else c2
        entry = _git_regular_blob_bytes(
            consumer_root,
            subject,
            path,
            label=f"configured C3 {role}",
        )
        if entry is None:
            raise UpgradeLaneError("configured C3 Markdown blob is missing")
        mode, raw = entry
        if mode != "100644" or not path.endswith(".md") or b"\0" in raw:
            raise UpgradeLaneError(
                "configured C3 artifact must be inert 100644 Markdown"
            )
        try:
            text = raw.decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise UpgradeLaneError("configured C3 Markdown must be UTF-8") from exc
        if item.get("operation") == "upsert" and any(
            finding.category == "secret" for finding in scan_text(text)
        ):
            raise UpgradeLaneError("configured C3 Markdown contains an access secret")


def _safe_file_bytes(root: Path, raw_path: object, *, label: str) -> tuple[str, bytes]:
    """Read one evidence file through a descriptor-pinned POSIX path walk.

    The root and every descendant directory stay open while the final file is
    read.  ``openat`` + ``O_NOFOLLOW`` closes the check/use gap left by
    ``Path.resolve``/``Path.read_bytes`` when another process swaps a path.
    """

    if (
        os.name != "posix"
        or not hasattr(os, "O_NOFOLLOW")
        or os.open not in os.supports_dir_fd
    ):
        raise UpgradeLaneError(
            f"{label} requires descriptor-pinned POSIX evidence reads"
        )
    relative = _canonical_repo_path(raw_path, label=f"{label} path")
    if root.is_symlink():
        raise UpgradeLaneError(f"{label} evidence root must not be a symlink")
    try:
        authority_root = root.resolve(strict=True)
    except OSError as exc:
        raise UpgradeLaneError(f"{label} evidence root is missing") from exc
    opened: list[int] = []
    descriptor: int | None = None
    close_on_exec = getattr(os, "O_CLOEXEC", 0)
    nonblocking = getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(
            authority_root,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | close_on_exec,
        )
        opened.append(descriptor)
        root_stat = os.fstat(descriptor)
        if not stat.S_ISDIR(root_stat.st_mode):
            raise UpgradeLaneError(f"{label} evidence root is not a directory")
        parts = Path(relative).parts
        for part in parts[:-1]:
            descriptor = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | close_on_exec,
                dir_fd=descriptor,
            )
            opened.append(descriptor)
            if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise UpgradeLaneError(f"{label} must not traverse a non-directory")
        descriptor = os.open(
            parts[-1],
            os.O_RDONLY | os.O_NOFOLLOW | close_on_exec | nonblocking,
            dir_fd=descriptor,
        )
        opened.append(descriptor)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise UpgradeLaneError(f"{label} must be one regular, non-hard-linked file")
        limit = 64 * 1024 * 1024
        if before.st_size > limit:
            raise UpgradeLaneError(f"{label} exceeds the evidence size limit")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, limit + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise UpgradeLaneError(f"{label} exceeds the evidence size limit")
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
            raise UpgradeLaneError(f"{label} changed while it was read")
        return relative, b"".join(chunks)
    except UpgradeLaneError:
        raise
    except OSError as exc:
        raise UpgradeLaneError(
            f"{label} could not be opened without symlink traversal"
        ) from exc
    finally:
        for handle in reversed(opened):
            try:
                os.close(handle)
            except OSError:
                pass


def _portable_tree_metadata(
    *, package: Mapping[str, Any], source_root: Path, source_sha: str
) -> tuple[str, int]:
    release = package.get("release")
    portable = package.get("portable_import")
    if not isinstance(release, Mapping) or not isinstance(portable, Mapping):
        raise UpgradeLaneError(
            "release package omits release/portable_import authority"
        )
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
    _require_safe_git_authority(source_root, label="source authority")
    top = (
        _git_bytes(
            source_root, ["rev-parse", "--show-toplevel"], label="source repository"
        )
        .decode("utf-8", "strict")
        .strip()
    )
    if Path(top).resolve() != source_root:
        raise UpgradeLaneError("source_root must be the exact Git repository root")
    resolved_sha = (
        _git_bytes(
            source_root,
            ["rev-parse", "--verify", f"{source_sha}^{{commit}}"],
            label="source subject",
        )
        .decode("ascii", "strict")
        .strip()
    )
    if resolved_sha != source_sha:
        raise UpgradeLaneError("source_sha must be the exact full Git commit")
    listing = _git_bytes(
        source_root,
        ["ls-tree", "-r", "-z", "--full-tree", source_sha],
        label="portable source tree",
    )
    selected: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for record in listing.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, object_type, object_id = metadata.decode("ascii").split(" ", 2)
            path = raw_path.decode("utf-8", "strict")
        except (ValueError, UnicodeDecodeError) as exc:
            raise UpgradeLaneError(
                "portable Git tree contains an invalid entry"
            ) from exc
        _canonical_repo_path(path, label="portable Git path")
        if path in seen:
            raise UpgradeLaneError("portable Git tree contains duplicate paths")
        seen.add(path)
        if _matches(path, block):
            continue
        if not _matches(path, allow):
            continue
        if object_type != "blob" or mode not in {"100644", "100755"}:
            raise UpgradeLaneError(
                "portable tree contains a symlink/submodule/special entry"
            )
        selected.append((path, mode, object_id))
    payloads = _git_blob_payloads(
        source_root,
        [object_id for _path, _mode, object_id in selected],
        label="portable blobs",
    )
    entries: list[dict[str, Any]] = []
    for path, mode, object_id in selected:
        raw = payloads[object_id]
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


_VISUAL_MANIFEST_ENTRY_FIELDS = {
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
_VISUAL_CAPTURE_RECORD_FIELDS = {
    "schema_version",
    "profile",
    "source_sha",
    "package_sha256",
    "requested_route",
    "route",
    "viewport",
    "view",
    "runtime_mode",
    "browser_toolchain",
    "browser_toolchain_sha256",
    "image",
    "console_summary",
    "network_summary",
    "capture",
}


def _nonnegative_int(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value >= 0


def _visual_capture_record_metadata(
    *,
    visual_root: Path,
    profile: str,
    entry: Mapping[str, Any],
    source_sha: str,
    package_sha256: str,
    browser_toolchain: Mapping[str, str],
) -> tuple[str, str]:
    """Verify the record whose digest is carried by one v1 manifest entry."""

    record_ref = f"records/{profile}.json"
    relative, raw = _safe_file_bytes(
        visual_root, record_ref, label=f"visual capture record {profile}"
    )
    try:
        record = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpgradeLaneError(
            f"visual capture record {profile} is not valid UTF-8 JSON"
        ) from exc
    if (
        not isinstance(record, Mapping)
        or set(record) != _VISUAL_CAPTURE_RECORD_FIELDS
        or raw != (canonical_json(record) + "\n").encode("utf-8")
        or record.get("schema_version") != VISUAL_CAPTURE_SCHEMA_VERSION
        or record.get("profile") != profile
        or record.get("source_sha") != source_sha
        or record.get("package_sha256") != package_sha256
        or record.get("browser_toolchain") != dict(browser_toolchain)
        or record.get("browser_toolchain_sha256") != canonical_sha256(browser_toolchain)
        or entry.get("state") != f"capture-{hashlib.sha256(raw).hexdigest()}"
    ):
        raise UpgradeLaneError(
            f"visual capture record {profile} identity or canonical digest differs"
        )
    spec = VISUAL_PROFILE_CONTRACTS[profile]
    requested_route = _public_visual_route(
        record.get("requested_route"), label=f"visual profile {profile} requested route"
    )
    route = _public_visual_route(
        record.get("route"), label=f"visual profile {profile} route"
    )
    if (
        requested_route != spec["route"]
        or route != entry.get("route")
        or record.get("viewport") != spec["viewport"]
        or record.get("view") != spec["view"]
        or record.get("runtime_mode") != spec["runtime_mode"]
        or entry.get("viewport") != spec["viewport"]
    ):
        raise UpgradeLaneError(
            f"visual capture record {profile} route, view, runtime mode or viewport differs"
        )
    image = record.get("image")
    if not isinstance(image, Mapping) or set(image) != {
        "path",
        "sha256",
        "bytes",
        "dimensions",
    }:
        raise UpgradeLaneError(f"visual capture record {profile} image is invalid")
    try:
        from wiki_core.release_receipt import (
            ReleaseReceiptError,
            visual_evidence_file_metadata,
        )
    except ImportError as exc:
        raise UpgradeLaneError(
            "strict visual evidence verifier is unavailable"
        ) from exc
    try:
        metadata = visual_evidence_file_metadata(
            visual_root,
            image.get("path"),
            label=f"visual evidence image {profile}",
        )
    except (ReleaseReceiptError, OSError, ValueError) as exc:
        raise UpgradeLaneError(
            f"visual evidence image {profile} failed strict verification"
        ) from exc
    if (
        dict(image) != metadata
        or image.get("dimensions") != spec["viewport"]
        or entry.get("path") != image["path"]
        or entry.get("sha256") != image["sha256"]
        or entry.get("bytes") != image["bytes"]
        or entry.get("capture_dimensions") != spec["viewport"]
        or entry.get("browser") != "chromium"
        or entry.get("public_synthetic") is not True
    ):
        raise UpgradeLaneError(
            f"visual evidence image {profile} must equal its DPR-1 viewport"
        )
    console = record.get("console_summary")
    network = record.get("network_summary")
    capture = record.get("capture")
    if (
        not isinstance(console, Mapping)
        or set(console)
        != {
            "capture",
            "warning_count",
            "error_count",
            "page_error_count",
            "truncated",
        }
        or console.get("capture") != "sanitized_counts_only"
        or any(
            not _nonnegative_int(console.get(key))
            for key in ("warning_count", "error_count", "page_error_count")
        )
        or console.get("error_count") != 0
        or console.get("page_error_count") != 0
        or console.get("truncated") is not False
    ):
        raise UpgradeLaneError(
            f"visual capture record {profile} console summary is incomplete"
        )
    if (
        not isinstance(network, Mapping)
        or set(network)
        != {
            "capture",
            "request_count",
            "response_error_count",
            "request_failed_count",
            "truncated",
        }
        or network.get("capture") != "sanitized_counts_only"
        or any(
            not _nonnegative_int(network.get(key))
            for key in (
                "request_count",
                "response_error_count",
                "request_failed_count",
            )
        )
        or network.get("request_count", 0) < 1
        or network.get("response_error_count") != 0
        or network.get("request_failed_count") != 0
        or network.get("truncated") is not False
    ):
        raise UpgradeLaneError(
            f"visual capture record {profile} network summary is incomplete"
        )
    if (
        not isinstance(capture, Mapping)
        or set(capture) != {"method", "action_count", "state", "settled"}
        or capture.get("method") != VISUAL_CAPTURE_METHOD
        or capture.get("action_count") != spec["action_count"]
        or capture.get("state") != spec["state"]
        or capture.get("settled") is not True
    ):
        raise UpgradeLaneError(f"visual capture record {profile} method/state differs")
    _assert_public_safe_payload(dict(record), label=f"visual capture record {profile}")
    return str(image["path"]), relative


def _verify_visual_inventory(visual_root: Path, *, expected_files: set[str]) -> None:
    root = visual_root.resolve(strict=True)
    if visual_root.is_symlink():
        raise UpgradeLaneError("visual evidence root must not be a symlink")
    actual_files: set[str] = set()
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in [*directories, *files]:
            candidate = current_path / name
            if candidate.is_symlink():
                raise UpgradeLaneError("visual evidence inventory contains a symlink")
        for name in files:
            candidate = current_path / name
            metadata = candidate.stat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise UpgradeLaneError(
                    "visual evidence inventory contains a hardlink or special file"
                )
            actual_files.add(candidate.relative_to(root).as_posix())
    if actual_files != expected_files:
        raise UpgradeLaneError(
            "visual evidence inventory contains missing or undeclared files"
        )


def _visual_manifest_metadata(
    *,
    visual_root: Path,
    manifest_ref: object,
    expected_profiles: Sequence[str],
    source_sha: str,
    package_sha256: str,
    browser_toolchain: Mapping[str, str],
) -> tuple[str, int]:
    relative, raw = _safe_file_bytes(
        visual_root, manifest_ref, label="visual evidence manifest"
    )
    if relative != "visual-manifest.json":
        raise UpgradeLaneError("visual evidence manifest path must be exact")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpgradeLaneError(
            "visual evidence manifest is not valid UTF-8 JSON"
        ) from exc
    if not isinstance(payload, Mapping) or set(payload) != {
        "schema_version",
        "entries",
    }:
        raise UpgradeLaneError("visual evidence manifest fields are invalid")
    if payload.get("schema_version") != VISUAL_MANIFEST_SCHEMA_VERSION:
        raise UpgradeLaneError("visual evidence manifest schema is invalid")
    entries = payload.get("entries")
    profiles = [str(profile) for profile in expected_profiles]
    if (
        not profiles
        or len(profiles) != len(set(profiles))
        or any(profile not in VISUAL_PROFILE_CONTRACTS for profile in profiles)
    ):
        raise UpgradeLaneError("package visual profiles have no exact capture contract")
    if not isinstance(entries, list) or len(entries) != len(profiles):
        raise UpgradeLaneError(
            "visual evidence manifest does not exactly cover package visual profiles"
        )
    ids = [
        str(entry.get("id") or "") if isinstance(entry, Mapping) else ""
        for entry in entries
    ]
    if ids != sorted(profiles):
        raise UpgradeLaneError(
            "visual evidence manifest must exactly cover sorted package visual profiles"
        )
    expected_files = {relative}
    for index, entry in enumerate(entries):
        if (
            not isinstance(entry, Mapping)
            or set(entry) != _VISUAL_MANIFEST_ENTRY_FIELDS
        ):
            raise UpgradeLaneError(f"visual evidence entry {index} fields are invalid")
        entry_id = ids[index]
        viewport = entry.get("viewport")
        if (
            _ID_RE.fullmatch(entry_id) is None
            or entry.get("public_synthetic") is not True
            or entry.get("browser") != "chromium"
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
            or re.fullmatch(r"capture-[0-9a-f]{64}", str(entry.get("state") or ""))
            is None
        ):
            raise UpgradeLaneError(
                f"visual evidence entry {index} is not public-synthetic"
            )
        image_ref, record_ref = _visual_capture_record_metadata(
            visual_root=visual_root,
            profile=entry_id,
            entry=entry,
            source_sha=source_sha,
            package_sha256=package_sha256,
            browser_toolchain=browser_toolchain,
        )
        expected_files.update({image_ref, record_ref})
    if raw != (canonical_json(payload) + "\n").encode("utf-8"):
        raise UpgradeLaneError("visual evidence manifest bytes are not canonical")
    _assert_public_safe_payload(dict(payload), label="visual evidence manifest")
    _verify_visual_inventory(visual_root, expected_files=expected_files)
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
    *,
    gate_output_root: Path,
    probe_ref: object,
    run_id: object,
    capsule_schema_version: object,
) -> tuple[str, int, dict[str, dict[str, str]], list[dict[str, Any]]]:
    relative, raw = _safe_file_bytes(
        gate_output_root, probe_ref, label="toolchain probe manifest"
    )
    if not relative.endswith(".json"):
        raise UpgradeLaneError("toolchain probe manifest must be JSON")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpgradeLaneError(
            "toolchain probe manifest is not valid UTF-8 JSON"
        ) from exc
    if not isinstance(payload, Mapping) or set(payload) != {
        "schema_version",
        "run_id",
        "entries",
    }:
        raise UpgradeLaneError("toolchain probe manifest fields are invalid")
    if capsule_schema_version == LEGACY_RELEASE_CAPSULE_SCHEMA_VERSION:
        expected_probe_schema = LEGACY_TOOLCHAIN_PROBE_SCHEMA_VERSION
        expected_ids = ["browser", "node", "python", "runner"]
    elif capsule_schema_version == RELEASE_CAPSULE_SCHEMA_VERSION:
        expected_probe_schema = TOOLCHAIN_PROBE_SCHEMA_VERSION
        expected_ids = ["browser", "node", "npm", "python", "runner"]
    else:
        raise UpgradeLaneError("release capsule schema is unsupported")
    if (
        payload.get("schema_version") != expected_probe_schema
        or payload.get("run_id") != run_id
    ):
        raise UpgradeLaneError("toolchain probe manifest belongs to another run")
    entries = payload.get("entries")
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
        raise UpgradeLaneError(
            f"toolchain probe must cover {len(expected_ids)} exact tools"
        )
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
            raise UpgradeLaneError(
                f"toolchain probe entry {index} is not executed/exact"
            )
        metadata = _gate_output_metadata(
            gate_output_root=gate_output_root,
            output_ref=entry.get("output_ref"),
            gate_id=f"toolchain-{tool_id}",
        )
        if any(entry.get(field) != metadata[field] for field in metadata):
            raise UpgradeLaneError(
                f"toolchain probe output binding mismatch: {tool_id}"
            )
        _relative, output = _safe_file_bytes(
            gate_output_root,
            entry.get("output_ref"),
            label=f"toolchain probe output {tool_id}",
        )
        text = output.decode("utf-8", "strict")
        if (
            re.search(rf"(?<![A-Za-z0-9]){re.escape(version)}(?![A-Za-z0-9])", text)
            is None
        ):
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
    capsule_schema_version: object,
) -> str:
    """Bind package policy, versioned impact registry and capsule commands."""

    legacy_capsule_v1 = capsule_schema_version == LEGACY_RELEASE_CAPSULE_SCHEMA_VERSION
    if (
        not legacy_capsule_v1
        and capsule_schema_version != RELEASE_CAPSULE_SCHEMA_VERSION
    ):
        raise UpgradeLaneError("release capsule schema is unsupported")
    if package.get("schema_version") != "wiki_viva_upgrade_package.v3":
        raise UpgradeLaneError("Lane A capsule requires an exact v3 upgrade package")
    release = package.get("release")
    try:
        from wiki_core.upgrade import (
            BOUNDARY_OPERATIONS_SCHEMA_VERSION,
            boundary_operations_sha256,
            package_is_pinned,
            release_node_command_violation,
            validate_legacy_capsule_v1_package,
            validate_upgrade_package,
        )
    except ImportError as exc:
        raise UpgradeLaneError("package pinning verifier is unavailable") from exc
    _require_schema(package, UPGRADE_PACKAGE_V3_SCHEMA_PATH, label="upgrade package")
    package_errors = (
        validate_legacy_capsule_v1_package(dict(package))
        if legacy_capsule_v1
        else validate_upgrade_package(dict(package))
    )
    if package_errors:
        raise UpgradeLaneError(
            "Lane A capsule upgrade package is semantically invalid: "
            + "; ".join(package_errors[:8])
        )
    if (
        not isinstance(release, Mapping)
        or release.get("id") != release_id
        or not package_is_pinned(dict(package))
    ):
        raise UpgradeLaneError(
            "capsule package is invalid, release_id differs, or release is not "
            "pinned/releasable"
        )
    registry_sha256 = _verify_impact_registry(
        impact_registry,
        enforce_node_workspace_contract=not legacy_capsule_v1,
    )
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
        if not legacy_capsule_v1:
            resource_group = str(policy.get("resource_group") or "")
            violation = release_node_command_violation(
                item["command"],
                node_required=resource_group.startswith(("node_", "browser_")),
            )
            if violation is not None:
                raise UpgradeLaneError(
                    f"package command violates Node workspace policy: {gate_id}: "
                    f"{violation}"
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
        or boundary.get("schema_version") != BOUNDARY_OPERATIONS_SCHEMA_VERSION
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
    configured_policy = _config_bound_c3_policy(package)
    configured_roles = [str(item["id"]) for item in configured_policy["roles"]]
    if boundary_policy.get("configured_c3_roles") != configured_roles:
        raise UpgradeLaneError(
            "package config-bound C3 roles differ from impact registry"
        )
    return registry_sha256


def _source_node_workspace_policy(
    *, source_root: Path, source_sha: str
) -> dict[str, Any]:
    """Read and verify the portable Node policy from the exact Git subject."""

    blobs: dict[str, bytes] = {}
    for relative, label in (
        (NODE_WORKSPACE_POLICY_RELATIVE, "Node workspace policy"),
        (NODE_WORKSPACE_PACKAGE_RELATIVE, "Node workspace package"),
        (NODE_WORKSPACE_PACKAGE_LOCK_RELATIVE, "Node workspace package lock"),
    ):
        result = _git_regular_blob_bytes(
            source_root,
            source_sha,
            relative.as_posix(),
            label=label,
        )
        if result is None:
            raise UpgradeLaneError(f"{label} is absent from the exact source subject")
        mode, raw = result
        if mode != "100644":
            raise UpgradeLaneError(f"{label} must be an inert 100644 Git blob")
        blobs[relative.as_posix()] = raw
    try:
        decoded = json.loads(
            blobs[NODE_WORKSPACE_POLICY_RELATIVE.as_posix()].decode("utf-8", "strict")
        )
        policy = validate_node_workspace_policy(decoded)
        package = json.loads(
            blobs[NODE_WORKSPACE_PACKAGE_RELATIVE.as_posix()].decode("utf-8", "strict")
        )
        package_lock = json.loads(
            blobs[NODE_WORKSPACE_PACKAGE_LOCK_RELATIVE.as_posix()].decode(
                "utf-8", "strict"
            )
        )
    except (UnicodeDecodeError, json.JSONDecodeError, NodeWorkspaceError) as exc:
        raise UpgradeLaneError("exact-source Node workspace policy is invalid") from exc
    if (
        hashlib.sha256(blobs[NODE_WORKSPACE_PACKAGE_RELATIVE.as_posix()]).hexdigest()
        != policy["package_json_sha256"]
        or hashlib.sha256(
            blobs[NODE_WORKSPACE_PACKAGE_LOCK_RELATIVE.as_posix()]
        ).hexdigest()
        != policy["package_lock_sha256"]
    ):
        raise UpgradeLaneError(
            "exact-source Node workspace policy differs from package/lock bytes"
        )
    scripts = package.get("scripts") if isinstance(package, Mapping) else None
    if (
        not isinstance(package, Mapping)
        or package.get("packageManager") != policy["package_manager"]
        or not isinstance(scripts, Mapping)
        or any(name not in scripts for name in policy["allowed_scripts"])
        or not isinstance(package_lock, Mapping)
        or package_lock.get("lockfileVersion") != 3
    ):
        raise UpgradeLaneError(
            "exact-source Node package/lock contract differs from portable policy"
        )
    return policy


def _node_workspace_authority_metadata(
    *,
    capsule: Mapping[str, Any],
    source_root: Path,
    source_sha: str,
    toolchain: Mapping[str, Mapping[str, str]],
) -> tuple[dict[str, Any], str]:
    """Bind one path-free Node authority to exact source policy and probes."""

    if capsule.get("schema_version") != RELEASE_CAPSULE_SCHEMA_VERSION:
        raise UpgradeLaneError(
            "Node workspace authority is defined only for release capsule v2"
        )
    try:
        authority = validate_node_workspace_authority(
            capsule.get("node_workspace_authority")
        )
        digest = authority_identity_sha256(authority)
        expected_npm = npm_workspace_toolchain_identity(authority)
    except NodeWorkspaceError as exc:
        raise UpgradeLaneError(
            f"release capsule Node workspace authority is invalid: {exc.code}"
        ) from exc
    claimed_digest = capsule.get("node_workspace_authority_sha256")
    if claimed_digest != digest:
        raise UpgradeLaneError(
            "release capsule node_workspace_authority_sha256 mismatch"
        )
    if authority.get("source_sha") != source_sha:
        raise UpgradeLaneError(
            "release capsule Node workspace authority belongs to another source"
        )
    policy = _source_node_workspace_policy(
        source_root=source_root, source_sha=source_sha
    )
    if authority.get("policy_sha256") != policy.get("policy_sha256"):
        raise UpgradeLaneError(
            "release capsule Node workspace authority policy differs from exact source"
        )
    node = authority["node"]
    expected_node = {
        "name": "node-resolved",
        "version": (
            f"{node['version']}+{node['platform_system']}."
            f"{node['platform_machine']}.runtime.{node['runtime_tree_sha256']}"
        ),
    }
    if toolchain.get("node") != expected_node:
        raise UpgradeLaneError(
            "release capsule Node toolchain differs from workspace authority"
        )
    if toolchain.get("npm") != expected_npm:
        raise UpgradeLaneError(
            "release capsule npm toolchain differs from workspace authority"
        )
    _assert_public_safe_payload(
        {"node_workspace_authority": authority},
        label="Node workspace authority",
    )
    return authority, digest


def collect_release_attestation(
    payload: Mapping[str, Any],
    *,
    package: Mapping[str, Any],
    impact_registry: Mapping[str, Any],
    source_root: Path,
    visual_root: Path,
    gate_output_root: Path,
) -> dict[str, Any]:
    """Recompute the public evidence an external Lane A authority must attest.

    Files can prove integrity and internal consistency, but no local JSON field
    can prove that Chromium actually produced them.  Productive provenance is
    therefore the out-of-band SHA-256 attestation made by a trusted workflow
    that ran ``wiki_visual_evidence.py capture`` and passed that exact output
    directly to certification.  There is deliberately no local/test flag that
    upgrades structural verification into productive authority.
    """

    capsule = copy.deepcopy(dict(payload))
    capsule_schema = capsule.get("schema_version")
    if capsule_schema not in {
        LEGACY_RELEASE_CAPSULE_SCHEMA_VERSION,
        RELEASE_CAPSULE_SCHEMA_VERSION,
    }:
        raise UpgradeLaneError("release capsule schema is unsupported")
    registry = capsule.get("command_registry")
    gates = capsule.get("certified_gates")
    if not isinstance(registry, list) or not all(
        isinstance(item, Mapping) for item in registry
    ):
        raise UpgradeLaneError(
            "release capsule command_registry must be a list of mappings"
        )
    if (
        not isinstance(gates, list)
        or not gates
        or not all(isinstance(item, Mapping) for item in gates)
    ):
        raise UpgradeLaneError(
            "release capsule certified_gates must be a non-empty mapping list"
        )
    registry = sorted(
        (dict(item) for item in registry), key=lambda item: str(item.get("id", ""))
    )
    gates = sorted(
        (dict(item) for item in gates), key=lambda item: str(item.get("id", ""))
    )
    command_registry_sha256 = canonical_sha256(registry)
    _verify_package_registry_contract(
        package=package,
        impact_registry=impact_registry,
        command_registry=registry,
        release_id=capsule.get("release_id"),
        capsule_schema_version=capsule_schema,
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
        capsule_schema_version=capsule.get("schema_version"),
    )
    toolchain_sha256 = canonical_sha256(toolchain)
    source_sha = _assert_sha(capsule.get("source_sha"), label="capsule source_sha")
    node_workspace_binding: dict[str, Any] = {}
    if capsule_schema == RELEASE_CAPSULE_SCHEMA_VERSION:
        node_workspace_authority, node_workspace_authority_sha256 = (
            _node_workspace_authority_metadata(
                capsule=capsule,
                source_root=source_root,
                source_sha=source_sha,
                toolchain=toolchain,
            )
        )
        node_workspace_binding = {
            "node_workspace_authority": node_workspace_authority,
            "node_workspace_authority_sha256": (node_workspace_authority_sha256),
        }
        attestation_schema = EXECUTION_ATTESTATION_SCHEMA_VERSION
    elif capsule_schema == LEGACY_RELEASE_CAPSULE_SCHEMA_VERSION:
        attestation_schema = LEGACY_EXECUTION_ATTESTATION_SCHEMA_VERSION
    else:
        raise UpgradeLaneError("release capsule schema is unsupported")
    package_sha256 = canonical_sha256(package)
    portable_tree_sha256, portable_count = _portable_tree_metadata(
        package=package, source_root=source_root, source_sha=source_sha
    )
    migration = package.get("migration")
    profiles = (
        migration.get("visual_profiles") if isinstance(migration, Mapping) else None
    )
    if not isinstance(profiles, list):
        raise UpgradeLaneError("package omits exact visual profiles")
    visual_manifest_sha256, visual_count = _visual_manifest_metadata(
        visual_root=visual_root,
        manifest_ref=capsule.get("visual_manifest_ref"),
        expected_profiles=profiles,
        source_sha=source_sha,
        package_sha256=package_sha256,
        browser_toolchain=toolchain["browser"],
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
        "schema_version": attestation_schema,
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
        "visual_capture_trust": {
            "model": "external_capture_execution_attestation",
            "capture_method": VISUAL_CAPTURE_METHOD,
            "bundle_verification": "structural_only",
            "productive_authority": "external_sha256",
        },
        "command_registry_sha256": command_registry_sha256,
        "toolchain": toolchain,
        "toolchain_sha256": toolchain_sha256,
        "toolchain_probe_sha256": toolchain_probe_sha256,
        "toolchain_probe_entry_count": toolchain_probe_count,
        "toolchain_probes": toolchain_probes,
        **node_workspace_binding,
        "gate_outputs": outputs,
    }


def _require_authority(
    authority: ReleaseCapsuleAuthority | None,
) -> ReleaseCapsuleAuthority:
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
    expected_schema = (
        LEGACY_EXECUTION_ATTESTATION_SCHEMA_VERSION
        if capsule.get("schema_version") == LEGACY_RELEASE_CAPSULE_SCHEMA_VERSION
        else EXECUTION_ATTESTATION_SCHEMA_VERSION
    )
    if (
        attestation.get("schema_version") != expected_schema
        or attestation.get("authority")
        != {
            "kind": "external_sha256",
            "id": capsule.get("attestation_authority_id"),
        }
        or not _ID_RE.fullmatch(str(attestation.get("run_id") or ""))
    ):
        raise UpgradeLaneError(
            "execution attestation authority/run identity is invalid"
        )
    _assert_public_safe_payload(dict(attestation), label="execution attestation")
    return digest


def seal_release_capsule(
    payload: Mapping[str, Any], *, authority: ReleaseCapsuleAuthority | None = None
) -> dict[str, Any]:
    """Build a capsule only from recomputed artifacts and external attestation."""

    if payload.get("schema_version") == LEGACY_RELEASE_CAPSULE_SCHEMA_VERSION:
        raise UpgradeLaneError(
            "release capsule v1 is immutable verification-only history and cannot be resealed"
        )
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
    if not isinstance(registry, list) or not all(
        isinstance(item, dict) for item in registry
    ):
        raise UpgradeLaneError(
            "release capsule command_registry must be a list of mappings"
        )
    if not isinstance(gates, list) or not all(isinstance(item, dict) for item in gates):
        raise UpgradeLaneError(
            "release capsule certified_gates must be a list of mappings"
        )
    capsule["command_registry"] = sorted(
        registry, key=lambda item: str(item.get("id", ""))
    )
    capsule["certified_gates"] = sorted(gates, key=lambda item: str(item.get("id", "")))
    _unique_ids(capsule["command_registry"], label="command registry")
    from wiki_core.upgrade import release_node_command_violation

    for item in capsule["command_registry"]:
        gate_id = item.get("id")
        command = item.get("command")
        if not isinstance(gate_id, str) or _ID_RE.fullmatch(gate_id) is None:
            raise UpgradeLaneError(
                "release capsule command registry has an invalid gate id"
            )
        if item.get("class") not in GATE_CLASSES:
            raise UpgradeLaneError(f"unknown gate class for {gate_id}")
        if not isinstance(command, str) or _PLACEHOLDER_COMMAND_RE.search(command):
            raise UpgradeLaneError(
                f"command registry entry is placeholder/manual: {gate_id}"
            )
        violation = release_node_command_violation(command)
        if violation is not None:
            raise UpgradeLaneError(
                f"command registry entry violates Node workspace policy: "
                f"{gate_id}: {violation}"
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
    capsule["toolchain_probe_entry_count"] = evidence["toolchain_probe_entry_count"]
    capsule["node_workspace_authority"] = evidence["node_workspace_authority"]
    capsule["node_workspace_authority_sha256"] = evidence[
        "node_workspace_authority_sha256"
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
    capsule_schema = capsule.get("schema_version")
    if capsule_schema == LEGACY_RELEASE_CAPSULE_SCHEMA_VERSION:
        schema_path = LEGACY_RELEASE_CAPSULE_SCHEMA_PATH
    elif capsule_schema == RELEASE_CAPSULE_SCHEMA_VERSION:
        schema_path = RELEASE_CAPSULE_SCHEMA_PATH
    else:
        raise UpgradeLaneError("release capsule schema is unsupported")
    _require_schema(capsule, schema_path, label="release capsule")
    _assert_public_safe_payload(capsule, label="release capsule")
    registry = capsule["command_registry"]
    certified = capsule["certified_gates"]
    registry_ids = _unique_ids(registry, label="command registry")
    certified_ids = _unique_ids(certified, label="certified gates")
    command_by_id: dict[str, Mapping[str, Any]] = {}
    from wiki_core.upgrade import release_node_command_violation

    for item in registry:
        gate_id = item["id"]
        if _ID_RE.fullmatch(gate_id) is None:
            raise UpgradeLaneError(f"invalid gate id in command registry: {gate_id!r}")
        if item["class"] not in GATE_CLASSES:
            raise UpgradeLaneError(f"unknown gate class for {gate_id}")
        command = item["command"]
        if _PLACEHOLDER_COMMAND_RE.search(command):
            raise UpgradeLaneError(
                f"command registry entry is placeholder/manual: {gate_id}"
            )
        if capsule_schema == RELEASE_CAPSULE_SCHEMA_VERSION:
            violation = release_node_command_violation(command)
            if violation is not None:
                raise UpgradeLaneError(
                    f"command registry entry violates Node workspace policy: "
                    f"{gate_id}: {violation}"
                )
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
    if capsule_schema == RELEASE_CAPSULE_SCHEMA_VERSION:
        for field in (
            "node_workspace_authority",
            "node_workspace_authority_sha256",
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
            raise UpgradeLaneError(
                f"certified gate lacks registry/output binding: {gate_id}"
            )
        if (
            registered["class"] != "upstream_certified"
            or result["class"] != "upstream_certified"
        ):
            raise UpgradeLaneError(
                f"Lane A may certify only upstream_certified gates: {gate_id}"
            )
        if result["provenance"] != "executed" or result["status"] != "passed":
            raise UpgradeLaneError(
                f"certified gate lacks executed passing evidence: {gate_id}"
            )
        if result["exit_code"] != 0:
            raise UpgradeLaneError(f"certified gate exit code is not zero: {gate_id}")
        if result["subject_sha"] != capsule["source_sha"]:
            raise UpgradeLaneError(
                f"certified gate is stale for source subject: {gate_id}"
            )
        if result["command_sha256"] != _command_digest(registered["command"]):
            raise UpgradeLaneError(f"certified gate command digest mismatch: {gate_id}")
        for field in ("output_ref", "output_sha256", "output_bytes"):
            if result.get(field) != output[field]:
                raise UpgradeLaneError(
                    f"certified gate output binding mismatch: {gate_id}"
                )
    if set(certified_ids) != {
        gate_id
        for gate_id in registry_ids
        if command_by_id[gate_id]["class"] == "upstream_certified"
    }:
        raise UpgradeLaneError(
            "capsule must carry executed proof for every upstream gate"
        )
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
            for key in (
                "path_patterns",
                "configured_path_roles",
                "contracts",
                "gates",
                "depends_on",
            ):
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


def _verify_impact_registry(
    registry: Mapping[str, Any], *, enforce_node_workspace_contract: bool
) -> str:
    """Verify registry closure, optionally under the frozen v1 Node policy."""

    _require_schema(registry, IMPACT_REGISTRY_SCHEMA_PATH, label="impact registry")
    gates = registry["gate_catalog"]
    surfaces = registry["surfaces"]
    gate_ids = _unique_ids(gates, label="gate catalog")
    if enforce_node_workspace_contract:
        from wiki_core.upgrade import release_node_command_violation

        for gate in gates:
            violation = release_node_command_violation(gate["command"])
            if violation is not None:
                raise UpgradeLaneError(
                    "impact registry command violates Node workspace policy: "
                    f"{gate['id']}: {violation}"
                )
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
        raise UpgradeLaneError(
            "full_matrix_gates must contain the complete sorted gate catalog"
        )
    surface_by_id = {item["id"]: item for item in surfaces}
    configured_roles = registry["boundary_policy"].get("configured_c3_roles", [])
    expected_roles = [str(item["id"]) for item in CONFIG_BOUND_C3_ROLE_SPECS]
    if configured_roles != expected_roles:
        raise UpgradeLaneError(
            "impact registry config-bound C3 roles are missing or out of order"
        )
    surface_roles: set[str] = set()
    configured_contract_by_role = {
        str(item["id"]): str(item["impact_contract"])
        for item in CONFIG_BOUND_C3_ROLE_SPECS
    }
    configured_contracts = set(configured_contract_by_role.values())
    role_surface_counts = {role: 0 for role in configured_roles}
    for surface in surfaces:
        for pattern in surface["path_patterns"]:
            _canonical_repo_path(
                pattern,
                label=f"surface {surface['id']} path pattern",
                allow_glob=True,
            )
        roles = surface.get("configured_path_roles", [])
        if not isinstance(roles, list) or any(
            not isinstance(role, str) or role not in configured_roles for role in roles
        ):
            raise UpgradeLaneError(
                f"surface {surface['id']} has an unknown configured path role"
            )
        surface_roles.update(roles)
        expected_surface_contracts = {
            configured_contract_by_role[role] for role in roles
        }
        observed_surface_contracts = configured_contracts.intersection(
            surface["contracts"]
        )
        if observed_surface_contracts != expected_surface_contracts:
            raise UpgradeLaneError(
                f"surface {surface['id']} config-bound role/contract binding differs"
            )
        for role in roles:
            role_surface_counts[role] += 1
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
    if surface_roles != set(configured_roles):
        raise UpgradeLaneError(
            "impact surfaces do not cover the exact config-bound C3 role set"
        )
    duplicated_roles = sorted(
        role for role, count in role_surface_counts.items() if count != 1
    )
    if duplicated_roles:
        raise UpgradeLaneError(
            "each config-bound C3 role must bind exactly one impact surface: "
            f"{duplicated_roles}"
        )
    for key, patterns in registry["boundary_policy"].items():
        if key == "configured_c3_roles":
            continue
        for pattern in patterns:
            _canonical_repo_path(pattern, label="boundary pattern", allow_glob=True)
    unsigned = dict(registry)
    claimed_digest = unsigned.pop("registry_sha256")
    digest = canonical_sha256(unsigned)
    if digest != claimed_digest:
        raise UpgradeLaneError("impact registry canonical digest mismatch")
    return digest


def verify_impact_registry(registry: Mapping[str, Any]) -> str:
    """Verify the strict registry contract used by new releases and adoption."""

    return _verify_impact_registry(registry, enforce_node_workspace_contract=True)


def _matches_pattern(path: str, pattern: str) -> bool:
    """Match one repo glob without letting a skill-name ``*`` cross ``/``."""

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


def _matches(path: str, patterns: Sequence[str]) -> bool:
    return any(_matches_pattern(path, pattern) for pattern in patterns)


def select_impacted_gates(
    registry: Mapping[str, Any],
    *,
    changed_paths: Sequence[str],
    changed_contracts: Sequence[str],
    consumer_c3_authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Select exact gates, escalating unknown impact to the complete matrix."""

    registry_sha256 = verify_impact_registry(registry)
    paths = sorted(
        {_canonical_repo_path(path, label="changed path") for path in changed_paths}
    )
    contracts = sorted(set(changed_contracts))
    for contract in contracts:
        if not isinstance(contract, str) or _CONTRACT_RE.fullmatch(contract) is None:
            raise UpgradeLaneError(f"changed contract is not canonical: {contract!r}")
    surfaces = registry["surfaces"]
    authority_sha256: str | None = None
    configured_memory_root: str | None = None
    configured_memory_surface_ids: list[str] = []
    if consumer_c3_authority is not None:
        authority_sha256 = _validate_consumer_c3_authority_shape(consumer_c3_authority)
        configured_memory_root = str(consumer_c3_authority["layout"]["memory_root"])
        configured_memory_surface_ids = [
            str(item["id"])
            for item in surfaces
            if "wiki_content.v1" in item["contracts"]
        ]
    matched: set[str] = set()
    unknown_paths: list[str] = []
    unknown_contracts: list[str] = []
    for path in paths:
        path_matches = {
            item["id"] for item in surfaces if _matches(path, item["path_patterns"])
        }
        configured_memory_impact_unknown = False
        if configured_memory_root is not None and path.startswith(
            f"{configured_memory_root}/"
        ):
            if len(configured_memory_surface_ids) == 1:
                path_matches.add(configured_memory_surface_ids[0])
            else:
                configured_memory_impact_unknown = True
        configured_role = (
            classify_consumer_c3_path(path, consumer_c3_authority)
            if consumer_c3_authority is not None
            else None
        )
        if configured_role is not None:
            path_matches.update(
                item["id"]
                for item in surfaces
                if configured_role in item.get("configured_path_roles", [])
            )
        lane_a_matches = {
            surface_id
            for surface_id in path_matches
            if next(item for item in surfaces if item["id"] == surface_id)["lane"]
            == "lane_a"
        }
        if lane_a_matches:
            path_matches = lane_a_matches
        if configured_memory_impact_unknown or not path_matches:
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
        "consumer_c3_authority_sha256": authority_sha256,
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


def select_promotion_gates(
    package: Mapping[str, Any],
    registry: Mapping[str, Any],
    *,
    changed_paths: Sequence[str],
    changed_contracts: Sequence[str],
    consumer_c3_authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive the exact promotion-blocking Lane B gate selection.

    Impact decides affected gates.  A package may additionally mark background
    certification gates as promotion-blocking; those gates and their complete
    dependency closure are selected even when they are intentionally scheduled
    after the real canary.
    """

    policy = _config_bound_c3_policy(package)
    if consumer_c3_authority is None:
        raise UpgradeLaneError("promotion selection omits consumer C3 authority")
    _validate_consumer_c3_authority_shape(consumer_c3_authority)
    if consumer_c3_authority.get("package_sha256") != canonical_sha256(
        package
    ) or consumer_c3_authority.get("policy_sha256") != canonical_sha256(policy):
        raise UpgradeLaneError("consumer C3 authority differs from package policy")
    selection = select_impacted_gates(
        registry,
        changed_paths=changed_paths,
        changed_contracts=changed_contracts,
        consumer_c3_authority=consumer_c3_authority,
    )
    migration = package.get("migration")
    policies = (
        migration.get("gate_policies") if isinstance(migration, Mapping) else None
    )
    required = (
        migration.get("required_gates") if isinstance(migration, Mapping) else None
    )
    catalog_ids = {item["id"] for item in registry["gate_catalog"]}
    if (
        not isinstance(required, list)
        or set(required) != catalog_ids
        or not isinstance(policies, Mapping)
        or set(policies) != catalog_ids
    ):
        raise UpgradeLaneError(
            "package promotion policy does not cover the exact impact gate catalog"
        )
    if selection["requires_lane_a"]:
        return selection

    selected = set(selection["selected_gates"])
    selected.update(
        gate_id
        for gate_id, policy in policies.items()
        if isinstance(policy, Mapping)
        and policy.get("class") == "background_certification"
        and policy.get("required_for_promotion") is True
    )
    frontier = list(selected)
    while frontier:
        gate_id = frontier.pop()
        policy = policies.get(gate_id)
        dependencies = policy.get("depends_on") if isinstance(policy, Mapping) else None
        if not isinstance(dependencies, list) or any(
            not isinstance(dependency, str) or dependency not in catalog_ids
            for dependency in dependencies
        ):
            raise UpgradeLaneError(
                f"package promotion gate dependencies are invalid: {gate_id}"
            )
        for dependency in dependencies:
            if dependency not in selected:
                selected.add(dependency)
                frontier.append(dependency)

    derivation = {
        key: value for key, value in selection.items() if key != "derivation_sha256"
    }
    derivation["selected_gates"] = sorted(selected)
    derivation["omitted_gates"] = sorted(catalog_ids - selected)
    return {**derivation, "derivation_sha256": canonical_sha256(derivation)}


def _require_canonical_promotion_selection(
    package: Mapping[str, Any],
    registry: Mapping[str, Any],
    selection: Mapping[str, Any],
    *,
    consumer_c3_authority: Mapping[str, Any],
) -> None:
    paths = selection.get("changed_paths")
    contracts = selection.get("changed_contracts")
    if not isinstance(paths, list) or not isinstance(contracts, list):
        raise UpgradeLaneError("impact selection omits canonical impact inputs")
    expected = select_promotion_gates(
        package,
        registry,
        changed_paths=paths,
        changed_contracts=contracts,
        consumer_c3_authority=consumer_c3_authority,
    )
    if dict(selection) != expected:
        raise UpgradeLaneError(
            "impact selection differs from package-required promotion gates"
        )


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
    profiles = (
        migration.get("visual_profiles") if isinstance(migration, Mapping) else None
    )
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
        raise UpgradeLaneError(
            "canary screenshots do not exactly cover visual profiles"
        )
    seen_profiles: set[str] = set()
    seen_observations: set[tuple[str, str, str, str, int, int]] = set()
    for item in canary_screenshots:
        profile = item.get("profile")
        route = item.get("route")
        runtime_mode = item.get("runtime_mode")
        view = item.get("view")
        viewport = item.get("viewport")
        spec = (
            VISUAL_PROFILE_CONTRACTS.get(profile) if isinstance(profile, str) else None
        )
        try:
            canonical_route = validate_canary_profile_route(profile, route)
        except UpgradeLaneError as exc:
            raise UpgradeLaneError(
                "canary screenshot profile/route/view/runtime/viewport is invalid"
            ) from exc
        if (
            profile not in profiles
            or spec is None
            or view != spec["view"]
            or runtime_mode != spec["runtime_mode"]
            or not isinstance(viewport, Mapping)
            or set(viewport) != {"width", "height"}
            or any(
                isinstance(viewport.get(axis), bool)
                or not isinstance(viewport.get(axis), int)
                or not 240 <= viewport[axis] <= 7680
                for axis in ("width", "height")
            )
            or viewport != spec["canary_viewport"]
            or item.get("width") != viewport["width"]
            or item.get("height") != viewport["height"]
        ):
            raise UpgradeLaneError(
                "canary screenshot profile/route/view/runtime/viewport is invalid"
            )
        observation = (
            profile,
            canonical_route,
            view,
            runtime_mode,
            viewport["width"],
            viewport["height"],
        )
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


def _acceptance_timestamp_microseconds(value: object) -> int:
    if not isinstance(value, str) or _ACCEPTANCE_TIMESTAMP_RE.fullmatch(value) is None:
        raise UpgradeLaneError(
            "acceptance budget timestamp is not canonical UTC RFC3339"
        )
    try:
        parsed = dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=dt.timezone.utc
        )
    except ValueError as exc:
        raise UpgradeLaneError(
            "acceptance budget timestamp is not a real UTC instant"
        ) from exc
    delta = parsed - _UNIX_EPOCH
    microseconds = (
        delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds
    )
    if microseconds <= 0:
        raise UpgradeLaneError(
            "acceptance budget timestamp must be after the Unix epoch"
        )
    return microseconds


def validate_acceptance_budget(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the immutable plan-to-canary promotion budget measurement."""

    _require_exact_keys(payload, _ACCEPTANCE_BUDGET_FIELDS, label="acceptance budget")
    if (
        payload.get("schema_version") != "wiki_viva_upgrade_acceptance_budget.v1"
        or payload.get("scope") != "plan_to_real_canary"
        or payload.get("limit_seconds") != 1200
        or payload.get("enforcement") != "promotion_blocking"
    ):
        raise UpgradeLaneError("acceptance budget policy is invalid")
    started = _acceptance_timestamp_microseconds(payload.get("plan_started_at"))
    completed_value = payload.get("canary_completed_at")
    elapsed = payload.get("elapsed_milliseconds")
    status = payload.get("status")
    if status == "pending":
        if completed_value is not None or elapsed is not None:
            raise UpgradeLaneError("pending acceptance budget contains a measurement")
    elif status in {"met", "exceeded"}:
        completed = _acceptance_timestamp_microseconds(completed_value)
        if (
            completed < started
            or isinstance(elapsed, bool)
            or not isinstance(elapsed, int)
            or elapsed < 0
        ):
            raise UpgradeLaneError("acceptance budget timestamps are invalid")
        expected_elapsed = (completed - started + 999) // 1_000
        if elapsed != expected_elapsed:
            raise UpgradeLaneError("acceptance budget elapsed time is stale")
        expected_status = "met" if elapsed <= 1_200_000 else "exceeded"
        if status != expected_status:
            raise UpgradeLaneError("acceptance budget status contradicts elapsed time")
    else:
        raise UpgradeLaneError("acceptance budget status is invalid")
    return dict(payload)


def public_acceptance_budget_projection(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the only acceptance-budget fields safe for a public report.

    The private receipt remains the authority for the measured instants and
    elapsed duration.  A completed public report exposes only the typed policy
    and its promotion outcome, so host timing cannot become publication data.
    """

    budget = validate_acceptance_budget(payload)
    if budget["status"] not in {"met", "exceeded"}:
        raise UpgradeLaneError(
            "public acceptance budget requires a completed real canary"
        )
    return {
        "schema_version": "wiki_viva_upgrade_acceptance_budget_public.v1",
        "scope": budget["scope"],
        "limit_seconds": budget["limit_seconds"],
        "enforcement": budget["enforcement"],
        "status": budget["status"],
    }


def public_migration_report_projection(
    report: Mapping[str, Any],
) -> dict[str, Any]:
    """Derive the exact, fail-closed public projection of a private report."""

    _require_exact_keys(
        report,
        {
            "schema_version",
            "status",
            "lane",
            "mode",
            "plan_sha256",
            "consumer_c3_authority_sha256",
            "identity",
            "selection",
            "boundaries",
            "gate_results",
            "rollback_evidence_sha256",
            "acceptance_budget",
            "evidence",
            "promotion_ready",
            "human_gate_required",
        },
        label="private migration report",
    )
    identity = adoption_identity(report["identity"])
    evidence = report["evidence"]
    if not isinstance(evidence, Mapping):
        raise UpgradeLaneError("private migration report evidence is invalid")
    _require_exact_keys(
        evidence,
        {"gate_logs", "screenshots", "console", "network", "capture_status"},
        label="private migration report evidence",
    )
    for kind in ("gate_logs", "screenshots", "console", "network"):
        if not isinstance(evidence[kind], list):
            raise UpgradeLaneError(
                f"private migration report {kind} evidence is invalid"
            )
    projection = {
        "schema_version": report["schema_version"],
        "status": report["status"],
        "lane": report["lane"],
        "mode": report["mode"],
        "plan_sha256": report["plan_sha256"],
        "selection": copy.deepcopy(report["selection"]),
        "boundaries": copy.deepcopy(report["boundaries"]),
        "gate_results": copy.deepcopy(report["gate_results"]),
        "rollback_evidence_sha256": report["rollback_evidence_sha256"],
        "acceptance_budget": public_acceptance_budget_projection(
            report["acceptance_budget"]
        ),
        "promotion_ready": report["promotion_ready"],
        "human_gate_required": report["human_gate_required"],
        "public_redacted": True,
        "identity_sha256": canonical_sha256(identity),
        "upstream_identity": {
            field: identity[field] for field in _UPSTREAM_IDENTITY_FIELDS
        },
        "consumer_subjects": "redacted",
        "evidence": {
            "gate_log_count": len(evidence["gate_logs"]),
            "screenshot_count": len(evidence["screenshots"]),
            "console_count": len(evidence["console"]),
            "network_count": len(evidence["network"]),
            "manifest_sha256": canonical_sha256(evidence),
            "raw_private_evidence": "omitted",
        },
    }
    serialized = canonical_json(projection)
    if any(identity[field] in serialized for field in ("consumer_B0", "consumer_C3")):
        raise UpgradeLaneError(
            "public migration report contains a private consumer subject"
        )
    _assert_public_safe_payload(projection, label="public migration report")
    return projection


def _integrity_gate_results(
    receipt: Mapping[str, Any],
    *,
    identity: Mapping[str, str],
    registry: Mapping[str, Any],
    selection: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    """Validate gate execution claims for passed and integrity-only blocked runs."""

    identity_sha256 = canonical_sha256(identity)
    if receipt.get("identity_sha256") != identity_sha256:
        raise UpgradeLaneError("adoption receipt identity_sha256 mismatch")
    registry_sha256 = verify_impact_registry(registry)
    if receipt.get("impact_registry_sha256") != registry_sha256:
        raise UpgradeLaneError("adoption receipt impact registry is stale")
    if selection.get("registry_sha256") != registry_sha256:
        raise UpgradeLaneError("impact selection used a stale registry")
    if receipt.get("impact_derivation_sha256") != selection.get("derivation_sha256"):
        raise UpgradeLaneError("adoption receipt impact derivation mismatch")
    if selection.get("requires_lane_a") is not False:
        raise UpgradeLaneError("impact requires a new Lane A capsule before adoption")
    if (
        canonical_sha256(registry["gate_catalog"])
        != identity["command_registry_sha256"]
    ):
        raise UpgradeLaneError(
            "current impact registry command catalog differs from receipt identity"
        )

    classes, commands = _catalog_maps(registry)
    selected_values = selection.get("selected_gates")
    if not isinstance(selected_values, list) or not all(
        isinstance(gate_id, str) for gate_id in selected_values
    ):
        raise UpgradeLaneError("impact selection gates are invalid")
    selected = set(selected_values)
    if not NEVER_REUSABLE_GATES.issubset(selected):
        raise UpgradeLaneError("impact selection omitted a never-reusable gate")
    results = receipt.get("gate_results")
    if not isinstance(results, list) or not results:
        raise UpgradeLaneError("adoption receipt must contain executed gate results")

    result_by_id: dict[str, Mapping[str, Any]] = {}
    for result in results:
        if not isinstance(result, Mapping):
            raise UpgradeLaneError("adoption receipt gate results are invalid")
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
        if not isinstance(gate_id, str):
            raise UpgradeLaneError("gate result id is invalid")
        if gate_id in result_by_id:
            raise UpgradeLaneError(f"duplicate gate result: {gate_id}")
        if gate_id not in selected or gate_id not in classes:
            raise UpgradeLaneError(f"gate result is not selected/registered: {gate_id}")
        if result["class"] != classes[gate_id]:
            raise UpgradeLaneError(f"gate result class mismatch: {gate_id}")
        if result["provenance"] != "executed":
            raise UpgradeLaneError(
                f"manual/fabricated evidence is forbidden: {gate_id}"
            )
        if (
            result["status"] != "passed"
            or isinstance(result["exit_code"], bool)
            or result["exit_code"] != 0
        ):
            raise UpgradeLaneError(f"gate result did not pass: {gate_id}")
        if result["subject_sha"] != identity["consumer_C3"]:
            raise UpgradeLaneError(f"gate result is stale after C3 changed: {gate_id}")
        if result["command_sha256"] != _command_digest(commands[gate_id]):
            raise UpgradeLaneError(f"gate result command digest mismatch: {gate_id}")
        _assert_sha(result["output_sha256"], label="gate output_sha256", sha256=True)
        result_by_id[gate_id] = result
    if set(result_by_id) != selected:
        raise UpgradeLaneError("gate results must exactly cover selected gates")
    resume = receipt.get("resume")
    if not isinstance(resume, Mapping):
        raise UpgradeLaneError("resume state is invalid")
    _require_exact_keys(
        resume,
        {"identity_sha256", "plan_sha256", "completed_gates"},
        label="resume state",
    )
    if resume["identity_sha256"] != identity_sha256:
        raise UpgradeLaneError("resume state identity is stale")
    if resume["plan_sha256"] != receipt.get("plan_sha256"):
        raise UpgradeLaneError("resume state plan is stale")
    if resume["completed_gates"] != sorted(selected):
        raise UpgradeLaneError("resume completed_gates are stale or incomplete")
    return result_by_id


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
    if canonical_sha256(registry["gate_catalog"]) != capsule["command_registry_sha256"]:
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
            raise UpgradeLaneError(
                f"mandatory consumer gate cannot be omitted: {gate_id}"
            )
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
    consumer_c3_authority: Mapping[str, Any],
) -> None:
    """Prove C1/C2/C3 ownership against the exact package allow/block policy."""

    _require_exact_keys(boundaries, {"C1", "C2", "C3"}, label="commit boundaries")
    policy = registry["boundary_policy"]
    migration = package.get("migration")
    boundary_operations = (
        migration.get("boundary_operations") if isinstance(migration, Mapping) else None
    )
    try:
        from wiki_core.upgrade import (
            BOUNDARY_OPERATIONS_SCHEMA_VERSION,
            boundary_operations_sha256,
        )
    except ImportError as exc:
        raise UpgradeLaneError("boundary operations verifier is unavailable") from exc
    if (
        not isinstance(boundary_operations, Mapping)
        or boundary_operations.get("schema_version")
        != BOUNDARY_OPERATIONS_SCHEMA_VERSION
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
    configured_policy = _config_bound_c3_policy(package)
    configured_roles = [str(item["id"]) for item in configured_policy["roles"]]
    if policy.get("configured_c3_roles") != configured_roles:
        raise UpgradeLaneError(
            "package config-bound C3 roles differ from impact registry"
        )
    authority_sha256 = _validate_consumer_c3_authority_shape(consumer_c3_authority)
    if (
        consumer_c3_authority.get("package_sha256") != canonical_sha256(package)
        or consumer_c3_authority.get("policy_sha256")
        != canonical_sha256(configured_policy)
        or authority_sha256 != consumer_c3_authority.get("authority_sha256")
    ):
        raise UpgradeLaneError("consumer C3 authority differs from package policy")
    configured_patterns = consumer_c3_authority_patterns(consumer_c3_authority)
    configured_memory_root = str(consumer_c3_authority["layout"]["memory_root"])
    release_root = str(consumer_c3_authority["release_records"]["root"])
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
                    {
                        "path",
                        "operation",
                        "mode",
                        "sha256",
                        "source_mode",
                        "source_sha256",
                    }
                    if operation == "upsert"
                    else {"path", "operation", "before_mode", "before_sha256"}
                )
            elif boundary == "C2":
                operation = item.get("operation")
                required = (
                    {
                        "path",
                        "operation",
                        "mode",
                        "sha256",
                        "generator_sha256",
                    }
                    if operation == "upsert"
                    else {
                        "path",
                        "operation",
                        "before_mode",
                        "before_sha256",
                        "generator_sha256",
                    }
                )
            elif boundary == "C3":
                operation = item.get("operation")
                required = (
                    {"path", "operation", "mode", "sha256"}
                    if operation == "upsert"
                    else {"path", "operation", "before_mode", "before_sha256"}
                )
            _require_exact_keys(item, required, label=f"{boundary} entry")
            path = _canonical_repo_path(item["path"], label=f"{boundary} path")
            if item.get("operation", "upsert") == "upsert":
                if item.get("mode") not in {"100644", "100755"}:
                    raise UpgradeLaneError(
                        f"{boundary} upsert is not a regular Git file: {path}"
                    )
                _assert_sha(item["sha256"], label=f"{boundary} sha256", sha256=True)
            elif boundary in {"C1", "C2", "C3"} and item.get("operation") == "delete":
                if item.get("before_mode") not in {"100644", "100755"}:
                    raise UpgradeLaneError(
                        f"{boundary} deletion did not remove a regular Git file: {path}"
                    )
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
            configured_role = classify_consumer_c3_path(path, consumer_c3_authority)
            under_release_root = path.startswith(f"{release_root}/")
            if under_release_root and configured_role is None:
                raise UpgradeLaneError(
                    f"release record must be inert Markdown in C3: {path}"
                )
            if configured_role is not None and boundary != "C3":
                raise UpgradeLaneError(
                    f"config-derived technical path is allowed only in C3: {path}"
                )
            is_domain_content = (
                _matches(path, policy["domain_content_patterns"])
                or path == configured_memory_root
                or path.startswith(f"{configured_memory_root}/")
            )
            if is_domain_content and not (
                boundary == "C3" and configured_role is not None
            ):
                raise UpgradeLaneError(
                    f"domain content is forbidden in technical boundary {boundary}: {path}"
                )
            if boundary == "C1":
                if item.get("operation") == "upsert":
                    if item.get("source_mode") not in {"100644", "100755"}:
                        raise UpgradeLaneError(
                            f"C1 source is not a regular Git file: {path}"
                        )
                    _assert_sha(
                        item["source_sha256"],
                        label="C1 source_sha256",
                        sha256=True,
                    )
                    if (
                        item["sha256"] != item["source_sha256"]
                        or item["mode"] != item["source_mode"]
                    ):
                        raise UpgradeLaneError(
                            f"C1 file is not byte-and-mode-equal to Lane A: {path}"
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
                # The consumer skill namespace intentionally has a broad C3
                # owner (``.skills/*/**``) while portable ``wiki-*`` skills
                # remain C1.  The package portable allow/block policy is the
                # authoritative precedence rule, so only generated ownership
                # can make an already-authorized C1 path ambiguous here.
                if _matches(path, policy["c2_generated_patterns"]):
                    raise UpgradeLaneError(
                        f"C1 path has ambiguous boundary ownership: {path}"
                    )
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
                if _matches(path, allow) and not _matches(path, block):
                    raise UpgradeLaneError(f"portable path mixed into C3: {path}")
                if _matches(path, policy["c2_generated_patterns"]):
                    raise UpgradeLaneError(f"generated path mixed into C3: {path}")
                if not _matches(path, policy["c3_consumer_patterns"]) and not _matches(
                    path, configured_patterns
                ):
                    raise UpgradeLaneError(
                        f"portable/generated path mixed into C3: {path}"
                    )
                if configured_role is not None:
                    mode = (
                        item.get("mode")
                        if item.get("operation") == "upsert"
                        else item.get("before_mode")
                    )
                    if mode != "100644" or not path.endswith(".md"):
                        raise UpgradeLaneError(
                            f"configured C3 artifact must be inert 100644 Markdown: {path}"
                        )


def validate_c1_projection(
    c1_entries: Sequence[Mapping[str, Any]],
    *,
    package: Mapping[str, Any],
    source_entries: Mapping[str, Mapping[str, str]],
    before_entries: Mapping[str, Mapping[str, str]],
    after_entries: Mapping[str, Mapping[str, str]],
) -> None:
    """Prove C1 is the complete byte-and-mode source projection."""

    portable = package.get("portable_import")
    if not isinstance(portable, Mapping):
        raise UpgradeLaneError("upgrade package omits portable_import projection")
    allow = portable.get("allow")
    block = portable.get("block")
    if not isinstance(allow, list) or not isinstance(block, list):
        raise UpgradeLaneError("portable projection allow/block is invalid")

    def normalized(
        entries: Mapping[str, Mapping[str, str]], *, label: str
    ) -> dict[str, dict[str, str]]:
        result: dict[str, dict[str, str]] = {}
        for raw_path, raw_entry in entries.items():
            path = _canonical_repo_path(raw_path, label=f"{label} path")
            if not isinstance(raw_entry, Mapping):
                raise UpgradeLaneError(f"{label} entry must bind mode and sha256")
            _require_exact_keys(raw_entry, {"mode", "sha256"}, label=f"{label} entry")
            mode = raw_entry.get("mode")
            if mode not in {"100644", "100755"}:
                raise UpgradeLaneError(f"{label} entry is not a regular Git file")
            result[path] = {
                "mode": str(mode),
                "sha256": _assert_sha(
                    raw_entry.get("sha256"), label=f"{label} sha256", sha256=True
                ),
            }
        return result

    source = normalized(source_entries, label="C1 source projection")
    before = normalized(before_entries, label="C1 before projection")
    after = normalized(after_entries, label="C1 after projection")
    for path in source:
        if _matches(path, block) or not _matches(path, allow):
            raise UpgradeLaneError(
                f"C1 source projection violates package policy: {path}"
            )
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
        raise UpgradeLaneError(
            "C1 after tree is not the exact portable source projection"
        )
    expected: list[dict[str, Any]] = []
    for path in sorted(set(before_portable) | set(source)):
        before_entry = before_portable.get(path)
        source_entry = source.get(path)
        if source_entry is None:
            if before_entry is None:
                raise UpgradeLaneError("C1 projection deletion lacks its before file")
            expected.append(
                {
                    "path": path,
                    "operation": "delete",
                    "before_mode": before_entry["mode"],
                    "before_sha256": before_entry["sha256"],
                }
            )
        elif source_entry != before_entry:
            expected.append(
                {
                    "path": path,
                    "operation": "upsert",
                    "mode": source_entry["mode"],
                    "sha256": source_entry["sha256"],
                    "source_mode": source_entry["mode"],
                    "source_sha256": source_entry["sha256"],
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


def _verify_git_boundary_chain(
    consumer: Path,
    receipt: Mapping[str, Any],
) -> None:
    """Recompute the direct B0 -> C1 -> C2 -> C3 receipt projection from Git."""

    commits = receipt.get("boundary_commits")
    if not isinstance(commits, Mapping):
        raise UpgradeLaneError("adoption receipt omits Git boundary commits")
    _require_exact_keys(commits, {"B0", "C1", "C2", "C3"}, label="Git boundary commits")
    normalized = {
        key: _assert_sha(commits[key], label=f"Git boundary {key}")
        for key in ("B0", "C1", "C2", "C3")
    }
    identity = adoption_identity(receipt["identity"])
    if (
        normalized["B0"] != identity["consumer_B0"]
        or normalized["C3"] != identity["consumer_C3"]
    ):
        raise UpgradeLaneError("Git boundary endpoints differ from receipt identity")
    for before, after in zip(
        ("B0", "C1", "C2"),
        ("C1", "C2", "C3"),
    ):
        lineage = (
            _git_bytes(
                consumer,
                ["rev-list", "--parents", "-n", "1", normalized[after]],
                label=f"consumer {after} lineage",
            )
            .decode("ascii", "strict")
            .strip()
            .split()
        )
        if lineage != [normalized[after], normalized[before]]:
            raise UpgradeLaneError(
                "consumer B0, C1, C2 and C3 are not one direct single-parent chain"
            )

    boundaries = receipt.get("boundaries")
    if not isinstance(boundaries, Mapping):
        raise UpgradeLaneError("adoption receipt boundaries are invalid")
    for before, after in zip(
        ("B0", "C1", "C2"),
        ("C1", "C2", "C3"),
    ):
        raw_paths = _git_bytes(
            consumer,
            [
                "diff",
                "--no-renames",
                "--name-only",
                "-z",
                normalized[before],
                normalized[after],
                "--",
            ],
            label=f"consumer {after} changed paths",
        )
        changed_paths = sorted(
            item.decode("utf-8", "strict") for item in raw_paths.split(b"\0") if item
        )
        entries = boundaries.get(after)
        if not isinstance(entries, list):
            raise UpgradeLaneError(f"adoption receipt {after} boundary is invalid")
        declared_paths = [
            (
                _canonical_repo_path(item.get("path"), label=f"{after} Git path")
                if isinstance(item, Mapping)
                else ""
            )
            for item in entries
        ]
        if declared_paths != changed_paths or len(declared_paths) != len(
            set(declared_paths)
        ):
            raise UpgradeLaneError(
                f"{after} receipt boundary differs from the exact Git diff"
            )
        for item in entries:
            path = item["path"]
            before_entry = _git_regular_blob(
                consumer,
                normalized[before],
                path,
                label=f"consumer {before} path {path}",
            )
            after_entry = _git_regular_blob(
                consumer,
                normalized[after],
                path,
                label=f"consumer {after} path {path}",
            )
            if after_entry is not None:
                if (
                    item.get("operation") != "upsert"
                    or item.get("mode") != after_entry["mode"]
                    or item.get("sha256") != after_entry["sha256"]
                ):
                    raise UpgradeLaneError(
                        f"{after} receipt upsert differs from the committed Git mode/blob: {path}"
                    )
            else:
                if before_entry is None:
                    raise UpgradeLaneError(
                        f"{after} receipt deletion has no committed before file: {path}"
                    )
                if (
                    item.get("operation") != "delete"
                    or item.get("before_mode") != before_entry["mode"]
                    or item.get("before_sha256") != before_entry["sha256"]
                ):
                    raise UpgradeLaneError(
                        f"{after} receipt deletion differs from the committed Git mode/blob: {path}"
                    )


def _verify_canary_completion_anchor(
    receipt: Mapping[str, Any],
    *,
    authority: AdoptionEvidenceAuthority,
    run_root: Path,
    state_results: Mapping[str, Any],
    registry: Mapping[str, Any],
    selection: Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    """Verify the first-write canary timestamp against out-of-band authority."""

    reference = receipt.get("canary_completion_anchor")
    if not isinstance(reference, Mapping):
        raise UpgradeLaneError("adoption receipt omits canary completion authority")
    _require_exact_keys(
        reference,
        {"schema_version", "anchor_sha256", "file_sha256"},
        label="canary completion anchor reference",
    )
    if (
        reference.get("schema_version")
        != "wiki_viva_upgrade_canary_completion_anchor_reference.v1"
    ):
        raise UpgradeLaneError("unsupported canary completion anchor reference")
    trusted = _assert_sha(
        authority.trusted_canary_completion_anchor_sha256,
        label="trusted canary completion anchor",
        sha256=True,
    )
    _relative, raw = _safe_file_bytes(
        run_root,
        "canary-completion-anchor.json",
        label="canary completion anchor",
    )
    file_sha256 = hashlib.sha256(raw).hexdigest()
    if reference.get("file_sha256") != trusted or file_sha256 != trusted:
        raise UpgradeLaneError(
            "canary completion anchor differs from out-of-band authority"
        )
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpgradeLaneError(
            "canary completion anchor is not valid UTF-8 JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise UpgradeLaneError("canary completion anchor must contain a mapping")
    _require_exact_keys(
        payload,
        {
            "schema_version",
            "authority",
            "plan_sha256",
            "identity_sha256",
            "canary_completed_at",
            "canary_results_sha256",
            "anchor_sha256",
        },
        label="canary completion anchor",
    )
    unsigned = dict(payload)
    claimed = unsigned.pop("anchor_sha256")
    canary_ids = sorted(
        item["id"]
        for item in registry["gate_catalog"]
        if item.get("class") == "canary" and item["id"] in selection["selected_gates"]
    )
    canary_projection: list[dict[str, Any]] = []
    for gate_id in canary_ids:
        result = state_results.get(gate_id)
        if not isinstance(result, Mapping):
            raise UpgradeLaneError("canary completion anchor lacks a selected canary")
        canary_projection.append(
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
    if (
        payload.get("schema_version") != "wiki_viva_upgrade_canary_completion_anchor.v1"
        or payload.get("authority")
        != {
            "kind": "external_sha256",
            "id": "wiki_upgrade_real_canary_first_completion",
        }
        or payload.get("plan_sha256") != receipt.get("plan_sha256")
        or payload.get("identity_sha256") != receipt.get("identity_sha256")
        or payload.get("canary_completed_at")
        != receipt.get("acceptance_budget", {}).get("canary_completed_at")
        or payload.get("canary_results_sha256") != canonical_sha256(canary_projection)
        or claimed != canonical_sha256(unsigned)
        or reference.get("anchor_sha256") != claimed
    ):
        raise UpgradeLaneError("canary completion anchor is stale or unbound")
    _acceptance_timestamp_microseconds(payload["canary_completed_at"])
    return payload, file_sha256


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
    if receipt.get("schema_version") != ADOPTION_RECEIPT_SCHEMA_VERSION:
        raise UpgradeLaneError("unsupported adoption receipt schema_version")
    unsigned_receipt = dict(receipt)
    receipt_digest = unsigned_receipt.pop("receipt_sha256", None)
    if receipt_digest != canonical_sha256(unsigned_receipt):
        raise UpgradeLaneError("adoption receipt canonical digest mismatch")
    consumer = authority.consumer_root.resolve(strict=True)
    run_root = authority.run_root.resolve(strict=True)
    _require_safe_git_authority(consumer, label="consumer authority")
    try:
        run_relative = run_root.relative_to(consumer).as_posix()
    except ValueError as exc:
        raise UpgradeLaneError("adoption run root is outside the consumer") from exc
    run_parts = Path(run_relative).parts
    expected_run_key = str(receipt.get("plan_sha256") or "")[:16]
    if (
        len(run_parts) < 3
        or run_parts[-2] != "runs"
        or re.fullmatch(r"[0-9a-f]{16}", run_parts[-1]) is None
        or run_parts[-1] != expected_run_key
    ):
        raise UpgradeLaneError(
            "adoption run root is outside its exact plan-parent runs boundary"
        )
    repository = (
        _git_bytes(
            consumer, ["rev-parse", "--show-toplevel"], label="consumer repository"
        )
        .decode("utf-8", "strict")
        .strip()
    )
    if Path(repository).resolve() != consumer:
        raise UpgradeLaneError("consumer_root must be the exact Git repository root")
    try:
        _git_bytes(
            consumer,
            ["check-ignore", "-q", run_relative],
            label="adoption evidence ignore policy",
        )
    except UpgradeLaneError as exc:
        raise UpgradeLaneError("adoption evidence root is not Git-ignored") from exc
    identity = adoption_identity(receipt["identity"])
    head = (
        _git_bytes(consumer, ["rev-parse", "HEAD"], label="consumer HEAD")
        .decode("ascii", "strict")
        .strip()
    )
    if head != identity["consumer_C3"]:
        raise UpgradeLaneError("adoption evidence consumer HEAD differs from C3")
    if _git_bytes(
        consumer,
        ["status", "--porcelain=v1", "--untracked-files=all"],
        label="consumer worktree state",
    ):
        raise UpgradeLaneError(
            "adoption evidence consumer has tracked or untracked worktree changes"
        )
    b0_tree = (
        _git_bytes(
            consumer,
            ["rev-parse", f"{identity['consumer_B0']}^{{tree}}"],
            label="consumer B0 tree",
        )
        .decode("ascii", "strict")
        .strip()
    )
    consumer_c3_authority = consumer_c3_authority_from_git(
        consumer, identity["consumer_B0"], package
    )
    consumer_c3_authority_sha256 = str(consumer_c3_authority["authority_sha256"])
    if receipt.get("consumer_c3_authority_sha256") != consumer_c3_authority_sha256:
        raise UpgradeLaneError("adoption receipt C3 authority is stale")
    _require_canonical_promotion_selection(
        package,
        registry,
        selection,
        consumer_c3_authority=consumer_c3_authority,
    )
    _verify_git_boundary_chain(consumer, receipt)
    validate_boundary_ownership(
        receipt["boundaries"],
        registry,
        package=package,
        consumer_c3_authority=consumer_c3_authority,
    )
    verify_config_bound_c3_git_content(
        consumer,
        commits=receipt["boundary_commits"],
        boundaries=receipt["boundaries"],
        authority=consumer_c3_authority,
        package=package,
    )
    state, state_raw = _private_json_artifact(
        run_root, "state.json", label="adoption runner state"
    )
    _require_exact_keys(
        state,
        {
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
        },
        label="adoption runner state",
    )
    receipt_budget = validate_acceptance_budget(receipt["acceptance_budget"])
    if (
        receipt.get("status") not in {"passed", "blocked"}
        or state.get("schema_version") != "wiki_viva_upgrade_runner_state.v4"
        or state.get("status") != "complete"
        or state.get("plan_sha256") != receipt["plan_sha256"]
        or state.get("identity_sha256") != receipt["identity_sha256"]
        or state.get("capsule_sha256") != receipt["capsule_sha256"]
        or state.get("impact_registry_sha256") != receipt["impact_registry_sha256"]
        or state.get("toolchain_sha256") != identity["toolchain_sha256"]
        or state.get("consumer_c3_authority_sha256") != consumer_c3_authority_sha256
        or state.get("boundary_commits") != receipt["boundary_commits"]
        or state.get("acceptance_budget") != receipt_budget
        or not isinstance(state.get("gate_results"), Mapping)
    ):
        raise UpgradeLaneError("adoption runner state is stale or incomplete")
    state_results = state["gate_results"]
    receipt_results = receipt["gate_results"]
    if not isinstance(receipt_results, list):
        raise UpgradeLaneError("adoption receipt gate results are invalid")
    receipt_by_id = _integrity_gate_results(
        receipt,
        identity=identity,
        registry=registry,
        selection=selection,
    )
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
    canary_ids = {
        item["id"]
        for item in registry["gate_catalog"]
        if item.get("class") == "canary" and item["id"] in selection["selected_gates"]
    }
    canary_completed = [
        state_results[gate_id].get("_completed_at")
        for gate_id in sorted(canary_ids)
        if state_results.get(gate_id, {}).get("status") == "passed"
    ]
    if len(canary_completed) != len(canary_ids):
        raise UpgradeLaneError("adoption runner state lacks a completed real canary")
    for value in canary_completed:
        _acceptance_timestamp_microseconds(value)
    if not canary_completed or receipt_budget["canary_completed_at"] != max(
        canary_completed, key=_acceptance_timestamp_microseconds
    ):
        raise UpgradeLaneError(
            "acceptance budget is not bound to the completed real canary"
        )
    _verify_canary_completion_anchor(
        receipt,
        authority=authority,
        run_root=run_root,
        state_results=state_results,
        registry=registry,
        selection=selection,
    )
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
        or rollback.get("boundary_digest") != canonical_sha256(receipt["boundaries"])
        or rollback_digest != canonical_sha256(rollback_unsigned)
        or receipt["rollback_verification"].get("evidence_sha256") != rollback_digest
    ):
        raise UpgradeLaneError("rollback artifact does not prove exact B0 restoration")
    private_report, private_raw = _private_json_artifact(
        run_root,
        "migration-report.private.json",
        label="private migration report",
    )
    expected_report_selection = {
        "escalation": selection["escalation"],
        "impact_derivation_sha256": selection["derivation_sha256"],
        "selected_gate_count": len(selection["selected_gates"]),
        "omitted_gate_count": len(selection["omitted_gates"]),
        "matched_surfaces": selection["matched_surfaces"],
    }
    receipt_boundaries = receipt["boundaries"]
    if (
        not isinstance(receipt_boundaries, Mapping)
        or set(receipt_boundaries) != {"C1", "C2", "C3"}
        or not all(
            isinstance(receipt_boundaries[boundary], list)
            for boundary in ("C1", "C2", "C3")
        )
    ):
        raise UpgradeLaneError("adoption receipt boundaries are invalid")
    expected_report_boundaries = {
        "digest": canonical_sha256(receipt_boundaries),
        "counts": {
            boundary: len(receipt_boundaries[boundary])
            for boundary in ("C1", "C2", "C3")
        },
    }
    promotion_ready = receipt["status"] == "passed"
    if (
        private_report.get("schema_version") != "wiki_viva_upgrade_runner_report.v3"
        or private_report.get("status") != "complete"
        or private_report.get("lane") != "lane_b"
        or private_report.get("mode") != "canary"
        or private_report.get("plan_sha256") != receipt["plan_sha256"]
        or private_report.get("consumer_c3_authority_sha256")
        != consumer_c3_authority_sha256
        or private_report.get("identity") != receipt["identity"]
        or private_report.get("selection") != expected_report_selection
        or private_report.get("boundaries") != expected_report_boundaries
        or private_report.get("rollback_evidence_sha256") != rollback_digest
        or private_report.get("acceptance_budget") != receipt_budget
        or private_report.get("promotion_ready") is not promotion_ready
        or private_report.get("human_gate_required") is not True
        or receipt["report_verification"].get("evidence_sha256")
        != hashlib.sha256(private_raw).hexdigest()
    ):
        raise UpgradeLaneError("private migration report is stale or unbound")
    if (receipt["status"] == "passed" and receipt_budget["status"] != "met") or (
        receipt["status"] == "blocked" and receipt_budget["status"] != "exceeded"
    ):
        raise UpgradeLaneError("receipt promotion status contradicts acceptance budget")
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
            if (
                not isinstance(item, Mapping)
                or item.get("subject_sha") != identity["consumer_C3"]
            ):
                raise UpgradeLaneError(f"migration report {kind} evidence is stale")
            artifact_file = item.get("artifact_file")
            if artifact_file is None:
                continue
            gate_id = _canonical_repo_path(item.get("gate_id"), label=f"{kind} gate id")
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
                    raise UpgradeLaneError(
                        "canary screenshot failed strict PNG verification"
                    ) from exc
                if metadata["sha256"] != item.get("sha256") or metadata[
                    "dimensions"
                ] != {"width": item.get("width"), "height": item.get("height")}:
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
                        and summary.get("request_count") != item.get("request_count")
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
    expected_public_report = public_migration_report_projection(private_report)
    if (
        public_report != expected_public_report
        or "consumer_B0" in public_serialized
        or "consumer_C3" in public_serialized
        or identity["consumer_B0"] in public_serialized
        or identity["consumer_C3"] in public_serialized
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
        consumer_c3_authority_sha256=consumer_c3_authority_sha256,
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
        or canonical_sha256(receipt.get("gate_results")) != verified.gate_results_sha256
        or receipt.get("consumer_c3_authority_sha256")
        != verified.consumer_c3_authority_sha256
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
    consumer_c3_authority: Mapping[str, Any],
) -> str:
    """Verify receipt reuse against all seven identity terms, fail closed."""

    _require_exact_keys(receipt, _RECEIPT_FIELDS, label="adoption receipt")
    if receipt["schema_version"] != ADOPTION_RECEIPT_SCHEMA_VERSION:
        raise UpgradeLaneError("unsupported adoption receipt schema_version")
    _require_canonical_promotion_selection(
        package,
        registry,
        selection,
        consumer_c3_authority=consumer_c3_authority,
    )
    if receipt["status"] != "passed":
        raise UpgradeLaneError("only passed adoption receipts are reusable")
    if validate_acceptance_budget(receipt["acceptance_budget"])["status"] != "met":
        raise UpgradeLaneError("only within-budget adoption receipts are reusable")
    _assert_public_safe_payload(receipt, label="adoption receipt")
    capsule_sha256 = _require_verified_capsule_token(capsule, verified_capsule).digest
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
    if (
        canonical_sha256(registry["gate_catalog"])
        != identity["command_registry_sha256"]
    ):
        raise UpgradeLaneError(
            "current impact registry command catalog differs from receipt identity"
        )
    _assert_sha(expected_plan_sha256, label="expected plan_sha256", sha256=True)
    if receipt["plan_sha256"] != expected_plan_sha256:
        raise UpgradeLaneError("adoption receipt plan is stale")
    authority_sha256 = _validate_consumer_c3_authority_shape(consumer_c3_authority)
    if (
        receipt.get("consumer_c3_authority_sha256") != authority_sha256
        or consumer_c3_authority.get("consumer_B0") != identity["consumer_B0"]
        or consumer_c3_authority.get("package_sha256") != identity["package_sha256"]
    ):
        raise UpgradeLaneError("adoption receipt C3 authority mismatch")
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
            raise UpgradeLaneError(
                f"manual/fabricated evidence is forbidden: {gate_id}"
            )
        if (
            result["status"] != "passed"
            or isinstance(result["exit_code"], bool)
            or result["exit_code"] != 0
        ):
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
        receipt["boundaries"],
        registry,
        package=package,
        consumer_c3_authority=consumer_c3_authority,
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
    "CONSUMER_C3_AUTHORITY_SCHEMA_VERSION",
    "AdoptionEvidenceAuthority",
    "EXECUTION_ATTESTATION_SCHEMA_VERSION",
    "LEGACY_EXECUTION_ATTESTATION_SCHEMA_VERSION",
    "GATE_CLASSES",
    "IMPACT_REGISTRY_SCHEMA_VERSION",
    "NEVER_REUSABLE_GATES",
    "RELEASE_CAPSULE_SCHEMA_VERSION",
    "LEGACY_RELEASE_CAPSULE_SCHEMA_VERSION",
    "TOOLCHAIN_PROBE_SCHEMA_VERSION",
    "LEGACY_TOOLCHAIN_PROBE_SCHEMA_VERSION",
    "VISUAL_CAPTURE_METHOD",
    "VISUAL_CAPTURE_SCHEMA_VERSION",
    "VISUAL_MANIFEST_SCHEMA_VERSION",
    "VISUAL_PROFILE_CONTRACTS",
    "ReleaseCapsuleAuthority",
    "UpgradeLaneError",
    "VerifiedReleaseCapsule",
    "VerifiedAdoptionEvidence",
    "adoption_identity",
    "canonical_json",
    "canonical_sha256",
    "classify_consumer_c3_path",
    "collect_release_attestation",
    "consumer_c3_authority_from_git",
    "consumer_c3_authority_patterns",
    "derive_consumer_c3_authority",
    "load_mapping",
    "public_acceptance_budget_projection",
    "public_migration_report_projection",
    "seal_adoption_receipt",
    "seal_impact_registry",
    "seal_release_capsule",
    "select_impacted_gates",
    "select_promotion_gates",
    "validate_acceptance_budget",
    "validate_boundary_ownership",
    "validate_c1_projection",
    "validate_canary_evidence",
    "validate_canary_profile_route",
    "verify_adoption_evidence",
    "verify_adoption_receipt",
    "verify_config_bound_c3_git_content",
    "verify_consumer_c3_authority",
    "verify_gate_omissions",
    "verify_impact_registry",
    "verify_release_capsule",
]
