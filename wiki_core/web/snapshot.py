from __future__ import annotations

import contextlib
import ctypes
import datetime as dt
import errno
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

try:  # POSIX is the supported live-publication surface (Darwin + Linux).
    import fcntl
except ImportError:  # pragma: no cover - exercised only on unsupported Windows.
    fcntl = None  # type: ignore[assignment]

from wiki_core.action_state import (
    CANONICAL_ACTION_STATES,
    legacy_action_state_from_body,
    resolve_action_state,
)
from wiki_core.collections import (
    COLLECTION_RELATION_TYPE,
    CollectionCompilation,
    compile_collections,
    member_collection_refs,
    relation_cycle_diagnostics,
)
from wiki_core.closure import build_ingestion_closure_report
from wiki_core.config import WikiConfig, load_config
from wiki_core.experience_packs import (
    CORE_VERSION as EXPERIENCE_PACK_CORE_VERSION,
    PackError,
    compose_active_packs,
    load_active_temporal_adapters,
    temporal_adapter_projection,
    validate_installation as validate_experience_pack_installation,
)
from wiki_core.events import resolve_ingestion_event_identity
from wiki_core.freshness import freshness_state, is_stale_exempt
from wiki_core.frontmatter import list_values, parse_frontmatter
from wiki_core.graph import build_page_graph
from wiki_core.output_safety import (
    OUTPUT_OWNER_FILENAME,
    OUTPUT_OWNER_SCHEMA_VERSION,
    contained_output_path,
    output_is_owned,
    read_output_owner,
    validate_managed_output_target,
    write_output_owner,
)
from wiki_core.paths import WikiPaths
from wiki_core.quality import build_quality_report
from wiki_core.source_lifecycle import (
    SOURCE_ADOPTION_STATES,
    SOURCE_FRESHNESS_STATES,
    SOURCE_LAST_ATTEMPT_STATES,
    SOURCE_LIFECYCLE_STATES,
    SOURCE_PIPELINE_STAGES,
    normalize_source_last_attempt_state,
)
from wiki_core.templates_registry import load_template_registry
from wiki_core.temporal import TEMPORAL_DATE_FIELDS
from wiki_core.web.commands import build_operator_command_cards
from wiki_core.web.diff import build_diff_payload
from wiki_core.web.git_ops import build_git_state
from wiki_core.web.schemas import (
    SNAPSHOT_FILES,
    WEB_ACTIVITY_TIMELINE_VERSION,
    WEB_BLOCK_VOCABULARY_VERSION,
    WEB_EXPERIENCE_PACK_COMPOSITION_VERSION,
    WEB_REGISTRY_MODULE_API_VERSION,
    WEB_RELATION_VOCABULARY_VERSION,
    WEB_ROUTE_CONTRACT_VERSION,
    WEB_RUNTIME_CONTRACT_VERSION,
    WEB_SEMANTIC_VISUAL_TOKENS_VERSION,
    WEB_SNAPSHOT_SCHEMA_VERSION,
    WEB_SOURCE_FRESHNESS_VERSION,
    WEB_SOURCE_LAST_ATTEMPT_VERSION,
    WEB_SOURCE_LIFECYCLE_VERSION,
    WEB_TEMPORAL_EVENT_VERSION,
    WEB_TEMPORAL_GRAPH_VERSION,
    WEB_VISUAL_GRAMMAR_VERSION,
)
from wiki_core.web.temporal import (
    build_temporal_graph_payload,
    temporal_graph_errors,
)
from wiki_core.web.timeline import build_timeline_payload

H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
H2_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
EMPHASIS_RE = re.compile(r"(\*{1,3}|_{2,3}|`{1,3})([^*_`]+?)\1")
SUMMARY_LIMIT = 260
SNAPSHOT_REVISION_RETENTION = 3
SNAPSHOT_REVISION_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
SNAPSHOT_REVISION_STORE_SUFFIX = ".wiki-revisions"
SNAPSHOT_PUBLICATION_THREAD_LOCK = threading.Lock()
SNAPSHOT_READ_RETRY_BASE_S = 0.002
SNAPSHOT_READ_RETRY_MAX_S = 0.05
SNAPSHOT_HEALTH_VALIDATION_CACHE_TTL_S = 1.0
SNAPSHOT_HEALTH_VALIDATION_CACHE_MAX_ENTRIES = 32
SNAPSHOT_HEALTH_VALIDATION_BUDGET_MS = 100.0
SNAPSHOT_CLEANUP_RECEIPT_SCHEMA_VERSION = "wiki_snapshot_cleanup_receipt.v2"
SNAPSHOT_CLEANUP_RECEIPTS_DIRNAME = "cleanup-receipts"
SNAPSHOT_CLEANUP_RECEIPT_ID_RE = re.compile(r"^[0-9a-f]{32}$")
SNAPSHOT_CLEANUP_INTENT_FILENAME = ".wiki-viva-cleanup-intent.json"
SNAPSHOT_HEALTH_VALIDATION_CACHE_LOCK = threading.Lock()
SNAPSHOT_HEALTH_VALIDATION_CACHE: dict[
    tuple[str, str, str, str],
    tuple[float, tuple[tuple[object, ...], ...], str, str | None, int],
] = {}

EXPERIENCE_PACK_COMPOSITION_FIELDS = {
    "schema_version",
    "core_version",
    "packs",
    "block_packages",
    "slots",
    "presentation",
    "composition_sha256",
}
EXPERIENCE_PACK_SLOT_KINDS = ("views", "commands", "operations", "timelines")
EXPERIENCE_PACK_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
EXPERIENCE_PACK_CAPABILITY_RE = re.compile(r"^[a-z][a-z0-9_.-]*$")
EXPERIENCE_PACK_SEMVER_RE = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"
)


class SnapshotWriteResult(dict[str, Path]):
    """Backward-compatible file map plus truthful activation/cleanup receipt."""

    def __init__(
        self,
        files: dict[str, Path],
        *,
        snapshot_id: str,
        active_revision: str,
        cleanup_warnings: tuple[str, ...] = (),
        recovery_paths: tuple[Path, ...] = (),
    ) -> None:
        super().__init__(files)
        self.committed = True
        self.snapshot_id = snapshot_id
        self.active_revision = active_revision
        self.cleanup_warnings = cleanup_warnings
        self.recovery_paths = recovery_paths


class SnapshotPublicationBlockedError(RuntimeError):
    """A pre-commit pathname race blocked publication without clobbering it."""

    def __init__(self, blocker_reason: str) -> None:
        super().__init__(f"snapshot publication blocked: {blocker_reason}")
        self.committed = False
        self.blocker_reason = blocker_reason


class SnapshotCleanupBlockedError(ValueError):
    """Cleanup stopped without deleting an untrusted entry."""

    def __init__(self, message: str, *, recovery_path: Path) -> None:
        super().__init__(message)
        self.recovery_path = recovery_path


class SnapshotDescriptorDeletionBlockedError(ValueError):
    """A descriptor-pinned delete stopped after observing replacement state."""

    def __init__(self, message: str, *, recovery_paths: tuple[Path, ...]) -> None:
        super().__init__(message)
        self.recovery_paths = recovery_paths


class _SnapshotDescriptorTreeRace(ValueError):
    """Internal signal that a pinned tree no longer matches its inventory."""


class SnapshotCleanupResult(list[Path]):
    def __init__(
        self,
        removed: list[Path],
        *,
        cleanup_warnings: tuple[str, ...] = (),
        recovery_paths: tuple[Path, ...] = (),
    ) -> None:
        super().__init__(removed)
        self.cleanup_warnings = cleanup_warnings
        self.recovery_paths = recovery_paths

RELATION_VOCABULARY_VERSION = WEB_RELATION_VOCABULARY_VERSION
RELATION_TYPES: dict[str, dict[str, Any]] = {
    "moc_parent": {
        "family": "hierarchy",
        "direction": "directed",
        "allows_multiple": True,
        "allows_cycles": False,
        "provenance_bearing": False,
        "visual_line_intent": "structural parent",
        "fallback": "parent/child row",
    },
    COLLECTION_RELATION_TYPE: {
        "family": "collection",
        "direction": "directed",
        "allows_multiple": True,
        "allows_cycles": False,
        "provenance_bearing": False,
        "visual_line_intent": "member to collection index",
        "fallback": "collection membership row",
    },
    "source_ref": {
        "family": "evidence",
        "direction": "directed",
        "allows_multiple": True,
        "allows_cycles": False,
        "provenance_bearing": True,
        "visual_line_intent": "evidence reference",
        "fallback": "source reference row",
    },
    "related_page": {
        "family": "association",
        "direction": "directed",
        "allows_multiple": True,
        "allows_cycles": True,
        "provenance_bearing": False,
        "visual_line_intent": "authored related-page association",
        "fallback": "related page row",
    },
    "markdown_link": {
        "family": "citation",
        "direction": "directed",
        "allows_multiple": True,
        "allows_cycles": True,
        "provenance_bearing": True,
        "visual_line_intent": "authored citation",
        "fallback": "linked page row",
    },
    "source_emission": {
        "family": "source_emission",
        "direction": "directed",
        "allows_multiple": True,
        "allows_cycles": False,
        "provenance_bearing": True,
        "visual_line_intent": "source to ingest event",
        "fallback": "emitted event row",
    },
    "dependency": {
        "family": "dependency",
        "direction": "directed",
        "allows_multiple": True,
        "allows_cycles": False,
        "provenance_bearing": False,
        "visual_line_intent": "blocker to dependent work",
        "fallback": "blocked-by row",
    },
    "ownership": {
        "family": "ownership",
        "direction": "directed",
        "allows_multiple": True,
        "allows_cycles": False,
        "provenance_bearing": False,
        "visual_line_intent": "owner to owned object",
        "fallback": "owner row",
    },
    "participation": {
        "family": "participation",
        "direction": "directed",
        "allows_multiple": True,
        "allows_cycles": True,
        "provenance_bearing": False,
        "visual_line_intent": "participant to event",
        "fallback": "participant row",
    },
    "evidence_supports": {
        "family": "evidence",
        "direction": "directed",
        "allows_multiple": True,
        "allows_cycles": False,
        "provenance_bearing": True,
        "visual_line_intent": "evidence to supported work",
        "fallback": "supporting evidence row",
    },
    "impact": {
        "family": "impact",
        "direction": "directed",
        "allows_multiple": True,
        "allows_cycles": False,
        "provenance_bearing": True,
        "visual_line_intent": "ingest/proposal to canonical change",
        "fallback": "affected page row",
    },
    "proposal_transition": {
        "family": "impact",
        "direction": "directed",
        "allows_multiple": True,
        "allows_cycles": False,
        "provenance_bearing": True,
        "visual_line_intent": "ingest event to review proposal",
        "fallback": "proposal transition row",
    },
    "temporal_sequence": {
        "family": "temporal",
        "direction": "directed",
        "allows_multiple": True,
        "allows_cycles": False,
        "provenance_bearing": False,
        "visual_line_intent": "earlier to later event",
        "fallback": "previous/next row",
    },
}


def _utc_now() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _today() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _git_bytes(root: Path, *args: str) -> bytes | None:
    """Run one bounded, non-interactive Git read and return its exact bytes."""

    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            check=False,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 else None


def _git_source_scope(root: Path) -> tuple[Path, str] | None:
    top_level = _git_bytes(root, "rev-parse", "--show-toplevel")
    if top_level is None:
        return None
    try:
        repo_root = Path(
            top_level.decode("utf-8", errors="surrogateescape").strip()
        ).resolve()
        source_root = root.resolve()
        relative = source_root.relative_to(repo_root)
    except (OSError, ValueError):
        return None
    return repo_root, relative.as_posix() or "."


def _dirty_worktree_hash(
    repo_root: Path, scope: str, head: str, status: bytes
) -> str:
    """Hash the complete Git-visible dirty state without leaking local paths.

    ``git diff HEAD`` covers staged and unstaged tracked content. Untracked files
    are included by repository-relative name plus bytes (or symlink target), so
    two snapshots from the same WIP receive the same source identity while any
    source edit changes it. Ignored caches remain outside the source contract.
    """

    digest = hashlib.sha256()
    digest.update(b"wiki-viva-uncommitted-source.v1\0")
    digest.update(head.encode("ascii", errors="replace"))
    digest.update(b"\0scope\0")
    digest.update(scope.encode("utf-8", errors="surrogateescape"))
    digest.update(b"\0status\0")
    digest.update(status)
    diff = _git_bytes(
        repo_root,
        "diff",
        "--binary",
        "--no-ext-diff",
        "--no-textconv",
        "--full-index",
        "HEAD",
        "--",
        scope,
    )
    if diff is None:
        digest.update(b"\0tracked-diff-unavailable\0")
    else:
        digest.update(b"\0tracked-diff\0")
        digest.update(diff)
    untracked = _git_bytes(
        repo_root,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
        "--",
        scope,
    )
    if untracked is None:
        digest.update(b"\0untracked-list-unavailable\0")
        return digest.hexdigest()
    for raw_rel in sorted(item for item in untracked.split(b"\0") if item):
        rel = raw_rel.decode("utf-8", errors="surrogateescape")
        path = repo_root / rel
        digest.update(b"\0untracked\0")
        digest.update(raw_rel)
        digest.update(b"\0")
        try:
            if path.is_symlink():
                digest.update(b"symlink\0")
                digest.update(os.readlink(path).encode("utf-8", errors="surrogateescape"))
            elif path.is_file():
                digest.update(b"file\0")
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
            else:
                digest.update(b"missing\0")
        except OSError:
            # A concurrent edit cannot be called a clean commit. Keep the
            # identity honest and deterministic for the observed status.
            digest.update(b"unreadable\0")
    return digest.hexdigest()


def _source_identity(root: Path, fallback_hash: str) -> tuple[str, str | None]:
    """Return honest v8 ``source_sha`` and legacy-safe ``source_commit``.

    ``source_commit`` is retained only for a clean checkout where it is true.
    Dirty or non-Git sources use the explicit ``uncommitted:<sha256>`` form.
    """

    git_scope = _git_source_scope(root)
    if git_scope is not None:
        repo_root, scope = git_scope
        head_raw = _git_bytes(
            repo_root, "log", "-1", "--format=%H", "--", scope
        )
        head = (
            head_raw.decode("ascii", errors="replace").strip()
            if head_raw is not None
            else ""
        )
        status = _git_bytes(
            repo_root,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--",
            scope,
        )
        if head and status == b"":
            return head, head
        if head and status is not None:
            return (
                f"uncommitted:{_dirty_worktree_hash(repo_root, scope, head, status)}",
                None,
            )
    normalized_fallback = (
        fallback_hash.lower()
        if re.fullmatch(r"[0-9a-fA-F]{64}", fallback_hash or "")
        else hashlib.sha256(str(fallback_hash).encode("utf-8")).hexdigest()
    )
    return f"uncommitted:{normalized_fallback}", None


def _canonical_value(value: Any) -> Any:
    """JSON canonical form shared with the browser boundary validator.

    JavaScript has one numeric type and serializes integral floats as integers;
    normalize Python floats the same way before hashing so static files and API
    responses verify identically after JSON parsing.
    """
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, list):
        return [_canonical_value(item) for item in value]
    if isinstance(value, tuple):
        return [_canonical_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _canonical_value(item) for key, item in value.items()}
    return value


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        _canonical_value(payload),
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _payload_integrity(payload: Any) -> dict[str, Any]:
    encoded = _canonical_json(payload)
    return {"sha256": hashlib.sha256(encoded).hexdigest(), "bytes": len(encoded)}


def _bundle_hash_for_artifacts(artifacts: dict[str, dict[str, Any]]) -> str:
    """Hash an artifact set without a snapshot-id self-reference.

    Content sidecars must carry the final ``snapshot_id`` while that ID is
    derived from the bundle itself. The bundle basis therefore normalizes only
    that embedded field out of sidecars; their full, final bytes remain covered
    separately by ``manifest.integrity``.
    """

    entries: list[str] = []
    for name in sorted(key for key in artifacts if key != "manifest.json"):
        payload = artifacts[name]
        if name.startswith("content/") and isinstance(payload, dict):
            payload = {key: value for key, value in payload.items() if key != "snapshot_id"}
        entries.append(f"{name}:{_payload_integrity(payload)['sha256']}")
    return hashlib.sha256("\n".join(entries).encode("utf-8")).hexdigest()


def _root_page_id(config: WikiConfig, pages_payload: dict[str, Any]) -> str | None:
    configured = str(config.root_entity.get("page") or "")
    for page in pages_payload.get("pages", []):
        if configured and str(page.get("path") or "") == configured:
            return str(page["id"])
    roots = [
        page
        for page in pages_payload.get("pages", [])
        if page.get("page_type") in {"root_entity", "root_index"}
    ]
    roots.sort(
        key=lambda page: (
            bool(page.get("moc_parent")),
            len(str(page.get("path") or "")),
            str(page.get("id") or ""),
        )
    )
    return str(roots[0]["id"]) if roots else None


def _title(values: dict[str, Any], body: str, fallback: str) -> str:
    explicit = str(values.get("title") or "").strip()
    if explicit:
        return explicit
    match = H1_RE.search(body)
    if match:
        return match.group(1).strip()
    return str(values.get("page_id") or fallback)


def _strip_inline_markdown(text: str) -> str:
    """Resolve links to their text and drop inline markers so summaries read
    as prose instead of leaking raw markdown syntax."""
    text = MD_IMAGE_RE.sub(lambda match: match.group(1).strip(), text)
    text = WIKILINK_RE.sub(
        lambda match: (match.group(2) or match.group(1)).strip(), text
    )
    text = MD_LINK_RE.sub(lambda match: match.group(1).strip(), text)
    previous = None
    while previous != text:
        previous = text
        text = EMPHASIS_RE.sub(r"\2", text)
    text = text.replace("**", "").replace("`", "")
    return re.sub(r"\s+", " ", text).strip()


def _summary(body: str) -> tuple[str, bool]:
    """Sanitized plain-text summary plus a truncation flag. Cuts happen at a
    sentence or word boundary near SUMMARY_LIMIT — never mid-word."""
    lines: list[str] = []
    in_code = False
    for raw in body.splitlines():
        line = raw.strip()
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not line or line.startswith(("#", "|", "---", "<!--")):
            continue
        if line.startswith("- "):
            line = line[2:].strip()
        lines.append(line)
        if len(" ".join(lines)) > SUMMARY_LIMIT + 80:
            break
    text = _strip_inline_markdown(" ".join(lines))
    if len(text) <= SUMMARY_LIMIT:
        return text, False
    window = text[:SUMMARY_LIMIT]
    sentence_end = max(window.rfind(". "), window.rfind("! "), window.rfind("? "))
    if sentence_end >= SUMMARY_LIMIT // 2:
        return window[: sentence_end + 1].strip(), True
    word_end = window.rfind(" ")
    cut = window[:word_end] if word_end > 0 else window
    return cut.rstrip(" ,;:.") + "…", True


def _freshness_state(values: dict[str, Any], *, today: dt.date | None = None) -> str:
    return freshness_state(
        values.get("updated_at") or values.get("date"),
        values.get("stale_after_days"),
        today or _today(),
        stale_exempt=is_stale_exempt(values.get("stale_exempt")),
    )


def _page_id(values: dict[str, Any], rel: str) -> str:
    return str(values.get("page_id") or rel).strip()


def _markdown_pages(root: Path, config: WikiConfig) -> list[Path]:
    memory_root = root / config.paths["memory_root"]
    if not memory_root.exists():
        return []
    return sorted(path for path in memory_root.rglob("*.md") if path.is_file())


def _page_record(
    root: Path,
    path: Path,
    config: WikiConfig,
    *,
    today: dt.date | None = None,
    temporal_adapter_fields: dict[str, frozenset[str]] | None = None,
) -> dict[str, Any]:
    rel = path.relative_to(root).as_posix()
    # Read exactly once.  The digest, frontmatter-derived metadata and summary
    # must describe one filesystem revision even when an editor replaces the
    # file while a snapshot is being built.
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    values, body = parse_frontmatter(text)
    source_refs: list[str] = []
    for source_ref in [
        *list_values(values.get("source_refs")),
        *list_values(values.get("source_ref")),
    ]:
        if source_ref not in source_refs:
            source_refs.append(source_ref)
    summary, summary_truncated = _summary(body)
    record = {
        "id": _page_id(values, rel),
        "path": rel,
        "title": _title(values, body, rel),
        "page_type": str(values.get("page_type") or ""),
        "context": str(values.get("context") or config.default_context),
        "visibility": str(values.get("visibility") or config.default_visibility),
        "status": str(values.get("status") or ""),
        "updated_at": str(values.get("updated_at") or ""),
        "stale_after_days": str(values.get("stale_after_days") or ""),
        "freshness_state": _freshness_state(values, today=today),
        "approved_state": "approved",
        "risk_flags": [],
        "source_refs": source_refs,
        "moc_parent": str(values.get("moc_parent") or ""),
        "collection_refs": member_collection_refs(values),
        "collection": values.get("collection")
        if isinstance(values.get("collection"), dict)
        else {},
        "summary": summary,
        "summary_truncated": summary_truncated,
        "content_sha256": hashlib.sha256(raw).hexdigest(),
    }
    # Preserve explicit compatibility identity for downstream read models.
    # Without these fields, legacy event pages whose authored page_type is not
    # one of the historical aliases are recognized by closure but disappear
    # from temporal and graph projections.
    for identity_field in ("event_id", "source_id"):
        if values.get(identity_field) not in (None, ""):
            record[identity_field] = str(values[identity_field])
    if isinstance(values.get("region_expectations"), dict):
        record["region_expectations"] = values["region_expectations"]
    evidence_refs: list[str] = []
    for evidence_ref in [
        *list_values(values.get("evidence_refs")),
        *list_values(values.get("evidence_for")),
        *list_values(values.get("evidence_against")),
    ]:
        if evidence_ref not in evidence_refs:
            evidence_refs.append(evidence_ref)
    record["relation_refs"] = {
        "consolidated_into": list_values(values.get("consolidated_into")),
        "proposal_ids": list_values(values.get("proposal_ids")),
        "participants": list_values(values.get("participants")),
        "related_pages": list_values(values.get("related_pages")),
        "evidence_refs": evidence_refs,
        "previous_refs": list_values(
            values.get("previous_refs") or values.get("previous_ref")
        ),
        "relation_cases": values.get("relation_cases")
        if isinstance(values.get("relation_cases"), list)
        else [],
    }
    temporal_dates = {
        field: str(values[field])
        for field in TEMPORAL_DATE_FIELDS
        if values.get(field) not in (None, "")
    }
    # Compatibility names are retained as inputs only.  The semantic adapter
    # maps them to occurred/recorded time instead of pretending they already
    # use the canonical event vocabulary.
    for field in ("captured_at", "decided_at"):
        if values.get(field) not in (None, ""):
            temporal_dates[field] = str(values[field])
    if (
        str(values.get("page_type") or "") == "decision"
        and not temporal_dates.get("decided_at")
        and values.get("date") not in (None, "")
    ):
        temporal_dates["decided_at"] = str(values["date"])
    if (
        str(values.get("page_type") or "") == "action"
        and not temporal_dates.get("due_at")
        and values.get("due") not in (None, "")
    ):
        temporal_dates["due_at"] = str(values["due"])
    adapter_projection = set(
        (temporal_adapter_fields or {}).get(str(values.get("page_type") or ""), ())
    )
    adapter_values: dict[str, Any] = {}
    for field in sorted(adapter_projection):
        if field not in values:
            continue
        value = values[field]
        if value is None or isinstance(value, (bool, int, float, str)):
            adapter_values[field] = value
        elif isinstance(value, (dt.date, dt.datetime)):
            adapter_values[field] = value.isoformat()
        elif (
            isinstance(value, list)
            and len(value) <= 128
            and all(isinstance(item, (bool, int, float, str)) for item in value)
        ):
            adapter_values[field] = list(value)
    declared_precision = values.get("temporal_precision")
    temporal_precision = (
        {
            str(key): str(value)
            for key, value in declared_precision.items()
            if str(key)
            in {
                *TEMPORAL_DATE_FIELDS,
                "captured_at",
                "decided_at",
                *adapter_projection,
            }
            and value not in (None, "")
        }
        if isinstance(declared_precision, dict)
        else {}
    )
    if temporal_dates or temporal_precision or adapter_values:
        record["temporal"] = {
            "dates": temporal_dates,
            "precision": temporal_precision,
            "action_state_history": [],
            "adapter_fields": adapter_values,
        }
    if str(values.get("page_type") or "") == "action":
        action_state = resolve_action_state(
            values,
            legacy_state=legacy_action_state_from_body(body),
        )
        record["work"] = {
            "state": action_state.state,
            "state_raw": action_state.raw,
            "state_source": action_state.source,
            "state_compatibility": action_state.compatibility,
            "state_warnings": list(action_state.warnings),
            "owner_kind": str(
                values.get("owner_kind")
                or ("page" if values.get("owner_ref") else "unassigned")
            ),
            "owner_ref": str(values.get("owner_ref") or values.get("owner") or ""),
            "created_at": str(
                values.get("created_at") or values.get("updated_at") or ""
            ),
            "due_at": str(values.get("due_at") or values.get("due") or ""),
            "completed_at": str(values.get("completed_at") or ""),
            "blocked_by": list_values(values.get("blocked_by")),
            "blocker_reason": str(values.get("blocker_reason") or ""),
            "parent_ref": str(
                values.get("parent_ref") or values.get("moc_parent") or ""
            ),
            "evidence_refs": list_values(
                values.get("evidence_refs") or values.get("source_refs")
            ),
            "next_action": str(values.get("next_action") or ""),
            "priority": str(values.get("priority") or "normal"),
            "attention_basis": str(values.get("attention_basis") or ""),
            "completion_receipt": str(values.get("completion_receipt") or ""),
            "cancellation_receipt": str(values.get("cancellation_receipt") or ""),
        }
        history = values.get("action_state_history")
        if isinstance(history, list):
            temporal = record.setdefault(
                "temporal",
                {"dates": {}, "precision": {}, "action_state_history": []},
            )
            temporal["action_state_history"] = [
                {
                    "receipt_id": str(entry.get("receipt_id") or ""),
                    "prior_receipt_id": str(entry.get("prior_receipt_id") or ""),
                    "receipt_kind": str(entry.get("kind") or ""),
                    # The canonical writer stores receipt v1 as from/to/at.
                    # The snapshot read model keeps its descriptive names for
                    # consumers while accepting the earlier projected aliases.
                    "previous_state": str(
                        entry.get("from") or entry.get("previous_state") or ""
                    ),
                    "next_state": str(
                        entry.get("to") or entry.get("next_state") or ""
                    ),
                    "recorded_at": str(
                        entry.get("at") or entry.get("recorded_at") or ""
                    ),
                }
                for entry in history
                if isinstance(entry, dict)
            ]
    if str(values.get("page_type") or "").startswith("source"):
        record["source_lifecycle_state"] = str(
            values.get("source_lifecycle_state") or values.get("lifecycle_state") or ""
        )
        record["source_blocked_reason"] = str(
            values.get("source_blocked_reason") or values.get("blocked_reason") or ""
        )
    return record


def _pages_payload_with_collections(
    root: Path,
    config: WikiConfig,
    *,
    today: dt.date | None = None,
    temporal_adapter_fields: dict[str, frozenset[str]] | None = None,
) -> tuple[dict[str, Any], CollectionCompilation]:
    reference_date = today or _today()
    pages: list[dict[str, Any]] = []
    for path in _markdown_pages(root, config):
        try:
            pages.append(
                _page_record(
                    root,
                    path,
                    config,
                    today=reference_date,
                    temporal_adapter_fields=temporal_adapter_fields,
                )
            )
        except OSError:
            # A page that vanished or turned unreadable mid-build (editor swap
            # files, concurrent git checkouts) must not abort the whole
            # snapshot: skip it and let the next build pick it up.
            continue
    pages.sort(
        key=lambda item: (str(item["context"]), str(item["title"]), str(item["path"]))
    )
    children: dict[str, int] = {}
    for page in pages:
        parent = str(page.get("moc_parent") or "")
        if parent:
            children[parent] = children.get(parent, 0) + 1
    for page in pages:
        page["moc_children_count"] = children.get(str(page["path"]), 0) + children.get(
            str(page["id"]), 0
        )
    registry = load_template_registry(root, config)
    defaults = {
        page_type: dict(registry.resolve(page_type).collection)
        for page_type in registry.raw_types
        if registry.resolve(page_type).collection
    }
    collection_compilation = compile_collections(
        pages,
        defaults_by_type=defaults,
        allows_cycles=(
            RELATION_TYPES[COLLECTION_RELATION_TYPE]["allows_cycles"] is True
        ),
    )
    collection_counts: dict[str, int] = {}
    for membership in collection_compilation.memberships:
        key = str(membership["collection"])
        collection_counts[key] = collection_counts.get(key, 0) + 1
    for page in pages:
        page["collection_members_count"] = collection_counts.get(str(page["id"]), 0)
    return (
        {
            "schema_version": "wiki_web_pages.v1",
            "repo_id": config.repo_id,
            "pages": pages,
        },
        collection_compilation,
    )


def _pages_payload(
    root: Path,
    config: WikiConfig,
    *,
    today: dt.date | None = None,
    temporal_adapter_fields: dict[str, frozenset[str]] | None = None,
) -> dict[str, Any]:
    """Compatibility wrapper for callers that only need the page payload."""

    payload, _collection_compilation = _pages_payload_with_collections(
        root,
        config,
        today=today,
        temporal_adapter_fields=temporal_adapter_fields,
    )
    return payload


OVERLAY_STATES: dict[str, set[str]] = {
    "attention": {"quiet", "watch", "urgent", "unknown"},
    "freshness": {"fresh", "stale", "never_synced", "unknown"},
    "actions": {
        "none",
        "open",
        "blocked",
        "overdue",
        "done",
        "cancelled",
        "unknown",
    },
    "ownership": {"assigned", "shared", "unassigned", "unknown"},
    "evidence": {"linked", "unrecorded", "unknown"},
    "quality": {"clear", "warning", "flagged", "unknown"},
}


def _quality_reasons_by_path(
    quality_payload: dict[str, Any], pages: list[dict[str, Any]]
) -> dict[str, list[str]]:
    """Index deterministic quality flags without treating telemetry as judgment."""

    known_paths = {str(page.get("path") or "") for page in pages}
    output: dict[str, set[str]] = {path: set() for path in known_paths if path}
    flags = quality_payload.get("quality_flags")
    if not isinstance(flags, dict):
        return {path: [] for path in output}

    # An exemption is explanatory metadata, not a quality defect. A missing
    # exemption reason remains a real flag and is intentionally not excluded.
    non_issue_flags = {"quality_exempt_pages"}

    def add(flag_id: str, candidate: Any) -> None:
        path = str(candidate or "")
        if path in output:
            output[path].add(f"quality:{flag_id}")

    for raw_flag_id, raw_records in flags.items():
        flag_id = str(raw_flag_id)
        if flag_id in non_issue_flags:
            continue
        records = raw_records if isinstance(raw_records, list) else [raw_records]
        for record in records:
            if isinstance(record, str):
                add(flag_id, record)
                continue
            if not isinstance(record, dict):
                continue
            add(flag_id, record.get("path"))
            for field in ("pages", "paths"):
                values = record.get(field)
                if isinstance(values, list):
                    for value in values:
                        add(flag_id, value)
    return {path: sorted(reasons) for path, reasons in output.items()}


def _empty_overlay_metrics() -> dict[str, dict[str, Any]]:
    return {
        overlay: {
            "state": "unknown",
            "value": None,
            "count": 0,
            "reasons": ["metric_unavailable"],
            "refs": [],
        }
        for overlay in OVERLAY_STATES
    }


def _graph_overlay_metrics(
    pages_payload: dict[str, Any],
    id_by_path: dict[str, str],
    quality_payload: dict[str, Any],
    *,
    snapshot_warnings_payload: dict[str, Any] | None = None,
    gates_payload: dict[str, Any] | None = None,
    source_lifecycle_payload: dict[str, Any] | None = None,
    root_page_id: str | None = "",
    today: dt.date | None = None,
) -> dict[str, dict[str, dict[str, Any]]]:
    """Build six explainable visual channels from canonical snapshot facts.

    Renderers consume only this normalized record. Context never chooses color,
    and every non-neutral mark carries machine-readable reasons and references.
    """

    reference = today or _today()
    pages = list(pages_payload.get("pages") or [])
    known_ids = {
        str(page.get("id") or "") for page in pages if str(page.get("id") or "")
    }
    quality_by_path = _quality_reasons_by_path(quality_payload, pages)
    source_freshness = {
        str(source.get("source_id") or ""): str(
            source.get("freshness_state") or "unknown"
        )
        for source in (source_lifecycle_payload or {}).get("sources") or []
        if isinstance(source, dict)
    }

    attention_signals: dict[str, list[tuple[str, bool, str]]] = {}
    urgent_warning_codes = {
        "q0_overload",
        "oversized_core",
        "source_blocked",
        "source_wrong_bucket",
        "governance_wrong_bucket",
    }
    for warning in (snapshot_warnings_payload or {}).get("warnings") or []:
        if not isinstance(warning, dict):
            continue
        code = str(warning.get("code") or "unknown")
        target = str(
            warning.get("page_id")
            or warning.get("source_id")
            or warning.get("anchor_id")
            or root_page_id
            or ""
        )
        if target not in known_ids:
            continue
        severity = str(warning.get("severity") or "warning")
        urgent = severity in {"error", "critical"} or code in urgent_warning_codes
        attention_signals.setdefault(target, []).append(
            (f"snapshot_warning:{code}", urgent, f"warning:{code}")
        )
    for gate in (gates_payload or {}).get("gates") or []:
        if not isinstance(gate, dict) or gate.get("status") != "fail":
            continue
        if root_page_id not in known_ids:
            continue
        gate_id = str(gate.get("id") or "unknown")
        attention_signals.setdefault(root_page_id, []).append(
            (f"gate:{gate_id}:fail", True, f"gate:{gate_id}")
        )

    def resolve_ref(value: Any) -> str | None:
        ref = str(value or "").strip()
        if not ref:
            return None
        if ref in known_ids:
            return ref
        return id_by_path.get(ref)

    actions_by_target: dict[str, list[dict[str, Any]]] = {
        page_id: [] for page_id in known_ids
    }
    valid_action_states = CANONICAL_ACTION_STATES
    for page in pages:
        if str(page.get("page_type") or "") != "action":
            continue
        work = dict(page.get("work") or {})
        action_id = str(page.get("id") or "")
        raw_state = str(work.get("state_raw") or work.get("state") or "open")
        state = raw_state if raw_state in valid_action_states else "unknown"
        if str(work.get("state") or "") in valid_action_states:
            state = str(work["state"])
        due_at = str(work.get("due_at") or "")
        due_date: dt.date | None = None
        try:
            due_date = dt.date.fromisoformat(due_at[:10]) if due_at else None
        except ValueError:
            due_date = None
        overdue = bool(
            due_date and due_date < reference and state not in {"done", "cancelled"}
        )
        owner_ref = resolve_ref(work.get("owner_ref")) or str(
            work.get("owner_ref") or ""
        )
        evidence_refs = sorted(
            {
                resolved
                for raw in [
                    *(work.get("evidence_refs") or []),
                    *(page.get("source_refs") or []),
                ]
                if (resolved := (resolve_ref(raw) or str(raw or "").strip()))
            }
        )
        record = {
            "id": action_id,
            "state": state,
            "raw_state": raw_state,
            "overdue": overdue,
            "owner_ref": owner_ref,
            "owner_kind": str(work.get("owner_kind") or "unassigned"),
            "evidence_refs": evidence_refs,
            "blocker_reason": str(work.get("blocker_reason") or ""),
            "blocked_by": list(work.get("blocked_by") or []),
            "completion_receipt": str(work.get("completion_receipt") or ""),
            "cancellation_receipt": str(work.get("cancellation_receipt") or ""),
        }
        targets = {action_id}
        raw_targets = [
            work.get("parent_ref"),
            *(page.get("source_refs") or []),
            *(work.get("evidence_refs") or []),
            *(work.get("blocked_by") or []),
        ]
        targets.update(
            resolved for raw in raw_targets if (resolved := resolve_ref(raw))
        )
        for target in sorted(targets):
            actions_by_target.setdefault(target, []).append(record)

    output: dict[str, dict[str, dict[str, Any]]] = {}
    for page in pages:
        page_id = str(page.get("id") or "")
        path = str(page.get("path") or "")
        freshness = source_freshness.get(page_id) or str(
            page.get("freshness_state") or "unknown"
        )
        freshness = (
            freshness if freshness in {"fresh", "stale", "never_synced"} else "unknown"
        )
        status = str(page.get("status") or "").lower()
        risk_flags = sorted(
            {str(flag) for flag in (page.get("risk_flags") or []) if str(flag)}
        )
        linked_actions = actions_by_target.get(page_id, [])
        own_action = next(
            (action for action in linked_actions if action["id"] == page_id), None
        )
        active_actions = [
            action
            for action in linked_actions
            if action["state"] not in {"done", "cancelled"}
        ]
        blocked_actions = [
            action for action in active_actions if action["state"] == "blocked"
        ]
        overdue_actions = [action for action in active_actions if action["overdue"]]

        attention_reasons = [f"risk:{flag}" for flag in risk_flags]
        if freshness in {"stale", "never_synced"}:
            attention_reasons.append(f"freshness:{freshness}")
        if status in {"proposal", "draft", "review", "needs_review"}:
            attention_reasons.append(f"approval:{status}")
        attention_reasons.extend(
            f"action:{action['id']}:blocked" for action in blocked_actions
        )
        attention_reasons.extend(
            f"action:{action['id']}:overdue" for action in overdue_actions
        )
        attention_reasons.extend(
            f"action:{action['id']}:{action['state']}"
            for action in active_actions
            if action not in blocked_actions and action not in overdue_actions
        )
        node_signals = attention_signals.get(page_id, [])
        attention_reasons.extend(reason for reason, _urgent, _ref in node_signals)
        attention_reasons = sorted(set(attention_reasons))
        urgent = bool(
            risk_flags
            or blocked_actions
            or overdue_actions
            or any(is_urgent for _reason, is_urgent, _ref in node_signals)
        )
        watch = bool(attention_reasons)
        attention_state = "urgent" if urgent else "watch" if watch else "quiet"

        if own_action and own_action["state"] == "blocked":
            action_state = "blocked"
        elif own_action and own_action["overdue"]:
            action_state = "overdue"
        elif own_action and own_action["state"] in {
            "open",
            "in_progress",
            "waiting_human",
        }:
            action_state = "open"
        elif own_action and own_action["state"] in {"done", "cancelled"}:
            action_state = str(own_action["state"])
        elif not linked_actions:
            action_state = "none"
        elif blocked_actions:
            action_state = "blocked"
        elif overdue_actions:
            action_state = "overdue"
        elif active_actions:
            action_state = "open"
        elif any(action["state"] == "done" for action in linked_actions):
            action_state = "done"
        elif any(action["state"] == "cancelled" for action in linked_actions):
            action_state = "cancelled"
        else:
            action_state = "unknown"

        owners = sorted(
            {
                str(action["owner_ref"])
                for action in linked_actions
                if action.get("owner_ref")
            }
        )
        ownership_state = (
            "shared"
            if len(owners) > 1
            else "assigned"
            if len(owners) == 1
            else "unassigned"
            if linked_actions
            else "unknown"
        )

        evidence_refs = sorted(
            {
                resolved
                for raw in [
                    *(page.get("source_refs") or []),
                    *(dict(page.get("work") or {}).get("evidence_refs") or []),
                    *(
                        ref
                        for action in linked_actions
                        for ref in action.get("evidence_refs") or []
                    ),
                ]
                if (resolved := (resolve_ref(raw) or str(raw or "").strip()))
            }
        )
        evidence_state = "linked" if evidence_refs else "unrecorded"

        quality_reasons = [
            *quality_by_path.get(path, []),
            *(f"risk:{flag}" for flag in risk_flags),
        ]
        own_work = dict(page.get("work") or {})
        own_state = str(own_work.get("state") or "")
        if page.get("page_type") == "action":
            if own_state and own_state not in valid_action_states:
                quality_reasons.append("action:invalid_state")
            if own_state == "blocked" and not (
                own_work.get("blocker_reason") or own_work.get("blocked_by")
            ):
                quality_reasons.append("action:blocked_without_reason")
            if own_state == "done" and not own_work.get("completion_receipt"):
                quality_reasons.append("action:done_without_receipt")
            if own_state == "cancelled" and not own_work.get("cancellation_receipt"):
                quality_reasons.append("action:cancelled_without_receipt")
        quality_reasons = sorted(set(quality_reasons))
        quality_state = (
            "flagged"
            if len(quality_reasons) > 1
            else "warning"
            if quality_reasons
            else "clear"
        )

        output[page_id] = {
            "attention": {
                "state": attention_state,
                "value": 1 if urgent else 0.5 if watch else 0,
                "count": len(attention_reasons),
                "reasons": attention_reasons,
                "refs": sorted(
                    {str(action["id"]) for action in blocked_actions + overdue_actions}
                    | {ref for _reason, _urgent, ref in node_signals}
                ),
            },
            "freshness": {
                "state": freshness,
                "value": (
                    1 if freshness == "fresh" else 0 if freshness == "stale" else None
                ),
                "count": 1,
                "reasons": [f"freshness:{freshness}"],
                "refs": [],
            },
            "actions": {
                "state": action_state,
                "value": len(active_actions),
                "count": len(linked_actions),
                "reasons": sorted(
                    {
                        f"action:{action['id']}:{action['state']}"
                        for action in linked_actions
                    }
                ),
                "refs": sorted({str(action["id"]) for action in linked_actions}),
            },
            "ownership": {
                "state": ownership_state,
                "value": len(owners) if owners else None,
                "count": len(owners),
                "reasons": (
                    ["owner:recorded"]
                    if owners
                    else ["owner:unassigned"]
                    if linked_actions
                    else ["owner:not_applicable"]
                ),
                "refs": owners,
            },
            "evidence": {
                "state": evidence_state,
                "value": len(evidence_refs),
                "count": len(evidence_refs),
                "reasons": (
                    ["evidence:linked"] if evidence_refs else ["evidence:not_recorded"]
                ),
                "refs": evidence_refs,
            },
            "quality": {
                "state": quality_state,
                "value": len(quality_reasons),
                "count": len(quality_reasons),
                "reasons": (
                    quality_reasons if quality_reasons else ["deterministic_flags:none"]
                ),
                "refs": [],
            },
        }
    return output


def _graph_payload(
    root: Path,
    config: WikiConfig,
    pages_payload: dict[str, Any],
    collection_compilation: CollectionCompilation,
    quality_payload: dict[str, Any],
    snapshot_warnings_payload: dict[str, Any],
    gates_payload: dict[str, Any],
    source_lifecycle_payload: dict[str, Any],
    *,
    today: dt.date | None = None,
) -> dict[str, Any]:
    graph = build_page_graph(root, config)
    events_dir = WikiPaths(root, config).ingest_events_dir.relative_to(root)
    pages_by_path = {str(page["path"]): page for page in pages_payload["pages"]}
    id_by_path = {rel: (node.page_id or rel) for rel, node in graph.nodes.items()}
    overlay_metrics = _graph_overlay_metrics(
        pages_payload,
        id_by_path,
        quality_payload,
        snapshot_warnings_payload=snapshot_warnings_payload,
        gates_payload=gates_payload,
        source_lifecycle_payload=source_lifecycle_payload,
        root_page_id=_root_page_id(config, pages_payload),
        today=today,
    )
    nodes = []
    edges: list[dict[str, Any]] = []
    edge_ids: set[str] = set()
    relation_diagnostics: list[dict[str, Any]] = []
    for rel, node in graph.nodes.items():
        page = pages_by_path.get(rel, {})
        nodes.append(
            {
                "id": id_by_path[rel],
                "path": rel,
                "title": page.get("title") or node.title or node.page_id or rel,
                "page_type": node.page_type,
                "context": node.context or config.default_context,
                "visibility": node.visibility,
                "status": page.get("status") or "",
                "updated_at": node.updated_at,
                "stale_after_days": node.stale_after_days,
                "freshness_state": page.get("freshness_state") or "unknown",
                "approved_state": "approved",
                "risk_flags": page.get("risk_flags") or [],
                "metrics": {
                    "inbound_links": len(node.inbound_links),
                    "outbound_links": len(node.outbound_links),
                    "source_ref_count": len(page.get("source_refs") or []),
                },
                "overlay_metrics": overlay_metrics.get(
                    id_by_path[rel], _empty_overlay_metrics()
                ),
            }
        )
        for target in node.outbound_body_links:
            if target in id_by_path:
                relation_id = hashlib.sha256(
                    f"{id_by_path[rel]}|{id_by_path[target]}|markdown_link".encode(
                        "utf-8"
                    )
                ).hexdigest()[:20]
                if relation_id in edge_ids:
                    continue
                edge_ids.add(relation_id)
                edges.append(
                    {
                        "id": relation_id,
                        "source": id_by_path[rel],
                        "target": id_by_path[target],
                        "type": "markdown_link",
                        "direction": "directed",
                        "basis": "markdown_body",
                        "provenance": {
                            "page_id": id_by_path[rel],
                            "path": rel,
                            "field": "body",
                        },
                        "observed_at": str(page.get("updated_at") or ""),
                        "status": "valid",
                        "weight": 1,
                    }
                )
    known_ids = {str(page.get("id") or "") for page in pages_payload["pages"]}

    def resolve_ref(value: Any) -> str | None:
        ref = str(value or "").strip()
        if not ref:
            return None
        if ref in known_ids:
            return ref
        return id_by_path.get(ref)

    def emit_relation(
        source_id: str | None,
        target_id: str | None,
        relation_type: str,
        page: dict[str, Any],
        field: str,
        *,
        direction: str | None = None,
        basis: str = "frontmatter",
        provenance: dict[str, Any] | None = None,
    ) -> None:
        if (
            not source_id
            or not target_id
            or source_id not in known_ids
            or target_id not in known_ids
        ):
            return
        definition = RELATION_TYPES.get(relation_type)
        if definition is None:
            return
        actual_direction = direction or str(definition["direction"])
        relation_id = hashlib.sha256(
            f"{source_id}|{target_id}|{relation_type}|{field}".encode("utf-8")
        ).hexdigest()[:20]
        if relation_id in edge_ids:
            return
        edge_ids.add(relation_id)
        edges.append(
            {
                "id": relation_id,
                "source": source_id,
                "target": target_id,
                "type": relation_type,
                "direction": actual_direction,
                "basis": basis,
                "provenance": provenance
                or {
                    "page_id": str(page.get("id") or ""),
                    "path": str(page.get("path") or ""),
                    "field": field,
                },
                "observed_at": str(page.get("updated_at") or ""),
                "status": "valid",
                "weight": 2 if definition["provenance_bearing"] else 1,
            }
        )

    for page in pages_payload["pages"]:
        page_id = str(page.get("id") or "")
        refs = dict(page.get("relation_refs") or {})
        # PageGraph intentionally flattens all frontmatter references for
        # reachability analysis.  The runtime graph must not flatten their
        # meaning: only source_refs are provenance edges, while hierarchy,
        # collections and authored associations retain their own relation
        # types.  Fields without an explicit runtime relation contract remain
        # reachability metadata instead of masquerading as source evidence.
        emit_relation(
            page_id,
            resolve_ref(page.get("moc_parent")),
            "moc_parent",
            page,
            "moc_parent",
        )
        for source_ref in page.get("source_refs") or []:
            emit_relation(
                page_id,
                resolve_ref(source_ref),
                "source_ref",
                page,
                "source_refs",
            )
        for related_page in refs.get("related_pages") or []:
            emit_relation(
                page_id,
                resolve_ref(related_page),
                "related_page",
                page,
                "related_pages",
            )
        page_path = Path(str(page.get("path") or page_id))
        try:
            page_path.relative_to(events_dir)
            in_events_directory = True
        except ValueError:
            in_events_directory = False
        event_identity = resolve_ingestion_event_identity(
            page_path,
            {
                "id": page_id,
                "page_id": page_id,
                "page_type": page.get("page_type"),
                "event_id": page.get("event_id"),
                "source_id": page.get("source_id"),
            },
            in_events_directory=in_events_directory,
        )
        if event_identity.recognized:
            for source_ref in page.get("source_refs") or []:
                emit_relation(
                    resolve_ref(source_ref),
                    page_id,
                    "source_emission",
                    page,
                    "source_refs",
                )
        for proposal_ref in refs.get("proposal_ids") or []:
            emit_relation(
                page_id,
                resolve_ref(proposal_ref),
                "proposal_transition",
                page,
                "proposal_ids",
            )
        for target_ref in refs.get("consolidated_into") or []:
            emit_relation(
                page_id, resolve_ref(target_ref), "impact", page, "consolidated_into"
            )
        work = dict(page.get("work") or {})
        if page.get("page_type") == "action":
            for blocker in work.get("blocked_by") or []:
                emit_relation(
                    resolve_ref(blocker), page_id, "dependency", page, "blocked_by"
                )
            owner_id = resolve_ref(work.get("owner_ref"))
            if owner_id:
                emit_relation(owner_id, page_id, "ownership", page, "owner_ref")
            # ``work.evidence_refs`` retains the historical UI fallback from
            # source_refs.  Only explicit evidence frontmatter is a typed
            # evidence_supports graph edge.
            for evidence in refs.get("evidence_refs") or []:
                emit_relation(
                    resolve_ref(evidence),
                    page_id,
                    "evidence_supports",
                    page,
                    "evidence_refs",
                )
        for participant in refs.get("participants") or []:
            emit_relation(
                resolve_ref(participant), page_id, "participation", page, "participants"
            )
        for previous in refs.get("previous_refs") or []:
            emit_relation(
                resolve_ref(previous),
                page_id,
                "temporal_sequence",
                page,
                "previous_refs",
            )
        for index, raw_case in enumerate(refs.get("relation_cases") or []):
            case = raw_case if isinstance(raw_case, dict) else {}
            relation_type = str(case.get("type") or "")
            target_id = resolve_ref(case.get("target"))
            direction = str(case.get("direction") or "")
            reasons: list[str] = []
            definition = RELATION_TYPES.get(relation_type)
            if definition is None:
                reasons.append("unknown_type")
            if target_id is None:
                reasons.append("invalid_endpoint")
            if (
                definition is not None
                and direction
                and direction != definition["direction"]
            ):
                reasons.append("invalid_direction")
            if (
                definition is not None
                and definition["provenance_bearing"]
                and not case.get("provenance")
            ):
                reasons.append("missing_provenance")
            if reasons:
                relation_diagnostics.append(
                    {
                        "id": f"{page_id}:relation-case:{index}",
                        "source": page_id,
                        "target": str(case.get("target") or ""),
                        "type": relation_type,
                        "status": "invalid",
                        "reasons": reasons,
                    }
                )
            else:
                emit_relation(
                    page_id,
                    target_id,
                    relation_type,
                    page,
                    f"relation_cases[{index}]",
                    direction=direction or None,
                    basis=str(case.get("basis") or "explicit_fixture"),
                    provenance=case.get("provenance")
                    if isinstance(case.get("provenance"), dict)
                    else None,
                )

    pages_by_id = {
        str(page.get("id") or ""): page for page in pages_payload["pages"]
    }
    for membership in collection_compilation.memberships:
        member_id = str(membership["member"])
        collection_id = str(membership["collection"])
        member_page = pages_by_id.get(member_id) or {}
        declaration_page = pages_by_id.get(
            str(membership.get("declaration_page") or "")
        ) or {}
        provenance_page = (
            member_page if membership["origin"] == "member" else declaration_page
        )
        emit_relation(
            member_id,
            collection_id,
            COLLECTION_RELATION_TYPE,
            provenance_page,
            "collection_refs"
            if membership["basis"] == "member.collection_refs"
            else "collection",
            basis=str(membership["basis"]),
            provenance={
                "page_id": str(provenance_page.get("id") or "")
                if membership["origin"] != "template_default"
                else "",
                "path": str(provenance_page.get("path") or "")
                if membership["origin"] != "template_default"
                else "wiki.templates.yaml",
                "field": "collection_refs"
                if membership["origin"] == "member"
                else "collection"
                if membership["origin"] == "collection_page"
                else f"templates.types.{membership['template_type']}.collection",
                "origin": str(membership["origin"]),
            },
        )
    for diagnostic in collection_compilation.reference_diagnostics:
        diagnostic_key = f"{diagnostic['field']}|{diagnostic['ref']}"
        diagnostic_hash = hashlib.sha256(diagnostic_key.encode("utf-8")).hexdigest()[:12]
        relation_diagnostics.append(
            {
                "id": (
                    f"{diagnostic['page_id']}:collection-diagnostic:"
                    f"{diagnostic_hash}"
                ),
                "source": diagnostic["page_id"],
                "target": diagnostic["ref"],
                "type": COLLECTION_RELATION_TYPE,
                "status": "invalid",
                "reasons": ["invalid_endpoint", diagnostic["code"]],
                "basis": diagnostic["field"],
                "provenance": {
                    "page_id": diagnostic["page_id"],
                    "path": diagnostic["path"],
                    "field": diagnostic["field"],
                    "origin": diagnostic["origin"],
                },
            }
        )
    for diagnostic in collection_compilation.cycle_diagnostics:
        cycle_path = [str(item) for item in diagnostic["cycle_path"]]
        diagnostic_key = "|".join(cycle_path)
        diagnostic_hash = hashlib.sha256(
            diagnostic_key.encode("utf-8")
        ).hexdigest()[:12]
        relation_diagnostics.append(
            {
                "id": f"collection-cycle:{diagnostic_hash}",
                "source": cycle_path[0],
                "target": cycle_path[1],
                "type": COLLECTION_RELATION_TYPE,
                "status": "invalid",
                "reasons": [
                    "cycle_forbidden",
                    str(diagnostic["code"]),
                ],
                "basis": "collection_membership_cycle",
                "cycle_path": cycle_path,
                "cycle_path_text": str(diagnostic["cycle_path_text"]),
                "page_paths": list(diagnostic["page_paths"]),
                "cycle_edges": list(diagnostic["cycle_edges"]),
            }
        )

    relation_type_records = [
        {
            "id": relation_id,
            "version": RELATION_VOCABULARY_VERSION,
            "label": relation_id.replace("_", " "),
            "source_entity_kinds": ["page"],
            "target_entity_kinds": ["page"],
            **definition,
            "traversal": "provenance"
            if definition["provenance_bearing"]
            else "context",
        }
        for relation_id, definition in sorted(RELATION_TYPES.items())
    ]
    return {
        "schema_version": "wiki_web_graph.v2",
        "overlay_metrics_version": WEB_SEMANTIC_VISUAL_TOKENS_VERSION,
        "relation_vocabulary_version": RELATION_VOCABULARY_VERSION,
        "relation_types": relation_type_records,
        "repo_id": config.repo_id,
        "nodes": sorted(nodes, key=lambda item: str(item["id"])),
        "edges": sorted(
            edges,
            key=lambda item: (
                str(item["source"]),
                str(item["target"]),
                str(item["type"]),
            ),
        ),
        "relation_diagnostics": sorted(
            relation_diagnostics, key=lambda item: str(item["id"])
        ),
        "wanted_pages": {
            target: list(refs) for target, refs in graph.wanted_pages.items()
        },
    }


def _section_records(markdown: str) -> list[dict[str, Any]]:
    matches = list(H2_RE.finditer(markdown))
    sections: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        body = markdown[start:end].strip()
        bullets = [
            line[2:].strip()
            for line in body.splitlines()
            if line.strip().startswith("- ")
        ]
        sections.append(
            {"title": match.group(1).strip(), "body": body, "bullets": bullets}
        )
    return sections


def _operations_payload(root: Path, config: WikiConfig) -> dict[str, Any]:
    paths = WikiPaths(root, config)
    values: dict[str, Any] = {}
    body = ""
    if paths.operation_page.exists():
        values, body = parse_frontmatter(paths.operation_page)
    return {
        "schema_version": "wiki_web_operations.v1",
        "repo_id": config.repo_id,
        "path": config.paths["operation_page"],
        "title": _title(values, body, "Operations"),
        "updated_at": str(values.get("updated_at") or ""),
        "stale_after_days": str(values.get("stale_after_days") or ""),
        "freshness_state": _freshness_state(values),
        "sections": _section_records(body),
    }


def _sources_payload(pages_payload: dict[str, Any]) -> dict[str, Any]:
    sources = [
        page
        for page in pages_payload["pages"]
        if str(page.get("page_type") or "").startswith("source")
        or "/sources/" in str(page.get("path") or "")
    ]
    return {"schema_version": "wiki_web_sources.v1", "sources": sources}


def _safe_source_entities(
    root: Path,
    config: WikiConfig,
    *,
    today: dt.date | None = None,
) -> dict[str, Any]:
    """Rich per-source read model (identity + recipe streams + sync + cursor
    freshness). Wrapped like _safe_ingestion so a malformed recipe never breaks
    the whole snapshot — the dock shows the error instead."""
    try:
        from wiki_core.web.sources import build_sources_payload

        return build_sources_payload(root, config, today=today)
    except Exception:  # noqa: BLE001
        return {
            "schema_version": "wiki_web_source_entities.v1",
            "sources": [],
            "error": "source_entities_unavailable",
            "error_code": "source_entities_unavailable",
        }


def _safe_templates(
    root: Path, config: WikiConfig, pages_payload: dict[str, Any]
) -> dict[str, Any]:
    """The declarative template registry, resolved per page type present in the
    wiki, so the cockpit can drive view/interaction from data."""
    try:
        from wiki_core.templates_registry import load_template_registry

        registry = load_template_registry(root, config)
        types = sorted(
            {
                str(p.get("page_type") or "")
                for p in pages_payload["pages"]
                if p.get("page_type")
            }
            | set(registry.raw_types)
        )
        return registry.to_json([t for t in types if t])
    except Exception as exc:  # noqa: BLE001
        return {
            "schema_version": "wiki_templates.v1",
            "types": {},
            "facets_order": [],
            "error": str(exc),
        }


def _decisions_payload(pages_payload: dict[str, Any]) -> dict[str, Any]:
    decisions = [
        page for page in pages_payload["pages"] if page.get("page_type") == "decision"
    ]
    return {"schema_version": "wiki_web_decisions.v1", "decisions": decisions}


def _freshness_payload(
    pages_payload: dict[str, Any], config: WikiConfig
) -> dict[str, Any]:
    pages = pages_payload["pages"]
    counts = {"fresh": 0, "stale": 0, "unknown": 0}
    by_context: dict[str, dict[str, int]] = {}
    stale_pages: list[dict[str, str]] = []
    for page in pages:
        state = str(page.get("freshness_state") or "unknown")
        counts[state] = counts.get(state, 0) + 1
        context = str(page.get("context") or config.default_context)
        by_context.setdefault(context, {"fresh": 0, "stale": 0, "unknown": 0})
        by_context[context][state] = by_context[context].get(state, 0) + 1
        if state == "stale":
            stale_pages.append(
                {
                    "path": str(page["path"]),
                    "title": str(page["title"]),
                    "context": context,
                }
            )
    return {
        "schema_version": "wiki_web_freshness.v1",
        "summary": counts,
        "by_context": dict(sorted(by_context.items())),
        "stale_pages": sorted(stale_pages, key=lambda item: item["path"]),
    }


def _gates_payload(root: Path, config: WikiConfig) -> dict[str, Any]:
    # Read model backed by persisted run receipts: a gate that last passed shows
    # green; "not_run" means genuinely never run. (See wiki_core.web.gates.)
    from wiki_core.web.gates import gates_payload

    return gates_payload(root, config)


def _commands_payload(actions_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "wiki_web_commands.v1",
        "commands": [
            command
            for action in actions_payload["actions"]
            for command in action.get("commands", [])
        ],
    }


def _operator_commands_payload(actions_payload: dict[str, Any]) -> dict[str, Any]:
    commands: list[dict[str, Any]] = []
    for action in actions_payload.get("actions", []):
        command_id = str(action.get("id") or "")
        commands.append(
            {
                "operator_command_id": command_id,
                "title": str(action.get("title") or command_id),
                "human_reason": str(action.get("human_reason") or ""),
                "capability": f"operator.{command_id}",
                "risk": str(action.get("risk_level") or "read"),
                "preview_required": bool(action.get("default_dry_run", True)),
                "idempotency_scope": "snapshot_and_command",
                "commands": list(action.get("commands") or []),
            }
        )
    return {
        "schema_version": "wiki_operator_commands.v1",
        "operator_commands": commands,
    }


def _work_items_payload(
    pages_payload: dict[str, Any], *, today: dt.date | None = None
) -> dict[str, Any]:
    reference = today or _today()
    items: list[dict[str, Any]] = []
    for page in pages_payload.get("pages", []):
        if page.get("page_type") != "action":
            continue
        work = dict(page.get("work") or {})
        due_at = str(work.get("due_at") or "")
        due_date: dt.date | None = None
        try:
            due_date = dt.date.fromisoformat(due_at[:10]) if due_at else None
        except ValueError:
            due_date = None
        state = str(work.get("state") or "open")
        valid_states = CANONICAL_ACTION_STATES
        valid_owner_kinds = {"human", "agent", "system", "other", "unassigned"}
        owner_kind = str(work.get("owner_kind") or "unassigned")
        warnings = [str(item) for item in work.get("state_warnings") or []]
        if state not in valid_states:
            if "invalid_action_state" not in warnings:
                warnings.append("invalid_action_state")
        if owner_kind not in valid_owner_kinds:
            warnings.append("invalid_owner_kind")
            owner_kind = "other"
        if state == "done" and not work.get("completion_receipt"):
            warnings.append("done_requires_completion_receipt")
        if state == "cancelled" and not work.get("cancellation_receipt"):
            warnings.append("cancelled_requires_cancellation_receipt")
        if state == "blocked" and not (
            work.get("blocked_by") or work.get("blocker_reason")
        ):
            warnings.append("blocked_requires_blocker")
        items.append(
            {
                "action_id": str(page.get("id") or ""),
                "page_id": str(page.get("id") or ""),
                "title": str(page.get("title") or ""),
                "state": state,
                "state_source": str(work.get("state_source") or ""),
                "state_compatibility": bool(work.get("state_compatibility")),
                "owner": {"kind": owner_kind, "ref": str(work.get("owner_ref") or "")},
                "created_at": str(work.get("created_at") or ""),
                "due_at": due_at,
                "completed_at": str(work.get("completed_at") or ""),
                "overdue": bool(
                    due_date
                    and due_date < reference
                    and state not in {"done", "cancelled"}
                ),
                "blocked_by": list(work.get("blocked_by") or []),
                "blocker_reason": str(work.get("blocker_reason") or ""),
                "parent_ref": str(work.get("parent_ref") or ""),
                "source_refs": list(page.get("source_refs") or []),
                "evidence_refs": list(work.get("evidence_refs") or []),
                "next_action": str(work.get("next_action") or ""),
                "priority": str(work.get("priority") or "normal"),
                "attention_basis": str(work.get("attention_basis") or ""),
                "completion_receipt": str(work.get("completion_receipt") or ""),
                "cancellation_receipt": str(work.get("cancellation_receipt") or ""),
                "contract_warnings": sorted(set(warnings)),
            }
        )
    return {
        "schema_version": "wiki_work_items.v1",
        "actions": sorted(items, key=lambda item: item["action_id"]),
    }


def _region_groups_payload(
    block_stacks_payload: dict[str, Any], pages_payload: dict[str, Any]
) -> dict[str, Any]:
    groups: list[dict[str, Any]] = []
    pages_by_id = {
        str(page.get("id") or ""): page for page in pages_payload.get("pages") or []
    }
    for anchor_id, record in sorted(
        dict(block_stacks_payload.get("anchors") or {}).items()
    ):
        anchor_page = pages_by_id.get(anchor_id) or {}
        declared_expectations = anchor_page.get("region_expectations")
        if not isinstance(declared_expectations, dict):
            declared_expectations = {}
        region_payload = dict((record.get("derived") or {}).get("region_groups") or {})
        for region in region_payload.get("groups") or []:
            enriched = dict(region)
            summary = dict(enriched.get("summary") or {})
            total = int(summary.get("total") or 0)
            region_id = str(enriched.get("id") or "")
            label_key = str(enriched.get("label_key") or "")
            declaration = (
                declared_expectations.get(region_id)
                or declared_expectations.get(label_key)
                or {}
            )
            if not isinstance(declaration, dict):
                declaration = {}
            default_state = (
                "optional" if enriched.get("kind") == "quadrant" else "unknown"
            )
            expectation_state = str(declaration.get("state") or default_state)
            if expectation_state not in {
                "required",
                "optional",
                "not_applicable",
                "unknown",
            }:
                expectation_state = "unknown"
            expectation_basis = str(
                declaration.get("basis")
                or (
                    "wiki.block.quadrants.v1 projects this lens but does not require members."
                    if enriched.get("kind") == "quadrant"
                    else "No explicit template, source or operator expectation is registered."
                )
            )
            if total:
                absence_state = "not_empty"
            elif expectation_state == "required":
                absence_state = "concerning"
            elif expectation_state in {"optional", "not_applicable"}:
                absence_state = "healthy"
            else:
                absence_state = "unmodeled"
            next_interaction = str(declaration.get("next_interaction") or "")
            if not next_interaction and absence_state == "concerning":
                next_interaction = "seedPage"
            elif not next_interaction and absence_state == "unmodeled":
                next_interaction = "openDock:blocks"
            enriched.update(
                {
                    "anchor_id": anchor_id,
                    "expectation": "present" if total else "empty",
                    "expectation_state": expectation_state,
                    "expectation_basis": expectation_basis,
                    "absence_state": absence_state,
                    "absence_reason": ""
                    if total
                    else str(declaration.get("absence_reason") or expectation_basis),
                    "expected_member_hints": list(
                        declaration.get("expected_member_hints") or []
                    ),
                    "expected_type_hints": list(
                        declaration.get("expected_type_hints") or []
                    ),
                    "expected_source_hints": list(
                        declaration.get("expected_source_hints") or []
                    ),
                    "expected_action_hints": list(
                        declaration.get("expected_action_hints") or []
                    ),
                    "next_safe_interaction": next_interaction,
                }
            )
            groups.append(enriched)
    return {"schema_version": "wiki_region_groups.v2", "groups": groups}


def _source_lifecycle_payload(
    pages_payload: dict[str, Any], source_entities_payload: dict[str, Any]
) -> dict[str, Any]:
    pages = {str(page.get("id") or ""): page for page in pages_payload.get("pages", [])}
    sources: list[dict[str, Any]] = []
    for source in source_entities_payload.get("sources") or []:
        source_id = str(source.get("source_id") or "")
        page = pages.get(source_id, {})
        sync = dict(source.get("sync") or {})
        declared = dict(source.get("lifecycle") or {})
        explicit = str(
            declared.get("state") or page.get("source_lifecycle_state") or ""
        )
        blocked_reason = str(
            declared.get("blocked_reason")
            or page.get("source_blocked_reason")
            or ""
        )
        last_status = str(sync.get("last_status") or "never")
        attempt_state = normalize_source_last_attempt_state(
            declared.get("last_attempt_state") or last_status
        )
        event_closure = dict(sync.get("event_closure") or {})
        emitted_page_ids = list(
            declared.get("emitted_page_ids")
            or event_closure.get("consolidated_into")
            or []
        )
        emitted_action_ids = list(declared.get("emitted_action_ids") or [])
        proposal_ids = list(declared.get("proposal_ids") or [])
        reviewed_no_change_receipt = str(
            declared.get("reviewed_no_change_receipt") or ""
        )
        has_reviewed_no_change = bool(
            reviewed_no_change_receipt or event_closure.get("reviewed_no_change")
        )
        has_closure = bool(emitted_page_ids or has_reviewed_no_change)
        adoption_state = str(declared.get("adoption_state") or "pending")
        accepted_ref = str(declared.get("accepted_ref") or "")
        adoption_accepted = adoption_state in {
            "accepted",
            "ingested",
            "reviewed_no_change",
        } and bool(accepted_ref)
        pipeline_stage = str(declared.get("pipeline_stage") or "")
        authoring_error_codes = sorted(
            {str(code) for code in declared.get("authoring_error_codes") or []}
        )
        if not pipeline_stage:
            if sync.get("last_status") in {"running", "queued"}:
                pipeline_stage = "extracted"
            elif sync.get("last_event_ref"):
                pipeline_stage = "proposal_ready"
            else:
                pipeline_stage = "configured"
        contract_warnings: list[str] = []
        if blocked_reason or last_status in {
            "failed",
            "needs_auth",
            "parser_error",
            "secret_blocked",
        }:
            lifecycle = "blocked"
        elif has_closure and adoption_accepted:
            lifecycle = "ingested"
        elif has_closure:
            lifecycle = "consolidated"
        elif explicit == "ingested":
            lifecycle = (
                "proposed" if sync.get("last_event_ref") or proposal_ids else "ready"
            )
            contract_warnings.append("ingested_requires_closure_and_accepted_ref")
        elif explicit in {
            "configured",
            "ready",
            "syncing",
            "proposed",
            "consolidated",
            "blocked",
        }:
            lifecycle = explicit
        elif (
            proposal_ids
            or sync.get("last_event_ref")
            or pipeline_stage in {"proposal_ready", "integrating", "gate_pending"}
        ):
            lifecycle = "proposed"
        elif sync.get("last_status") in {"running", "queued"} or pipeline_stage in {
            "manifested",
            "extracted",
            "indexed",
            "deep_read",
        }:
            lifecycle = "syncing"
        elif source.get("recipe_ok"):
            lifecycle = "ready"
        else:
            lifecycle = "configured"
        declared_freshness = str(declared.get("freshness_state") or "")
        if declared_freshness in {"fresh", "stale", "never_synced"}:
            freshness = declared_freshness
        elif not sync.get("last_run_at"):
            freshness = "never_synced"
        elif any(
            bool(stream.get("breached")) for stream in source.get("streams") or []
        ):
            freshness = "stale"
        else:
            freshness = "fresh"
        sources.append(
            {
                "source_id": source_id,
                "lifecycle_state": lifecycle,
                "pipeline_stage": pipeline_stage,
                "pipeline_stage_timestamps": dict(
                    declared.get("pipeline_stage_timestamps") or {}
                ),
                "adoption_state": adoption_state,
                "freshness_state": freshness,
                "last_attempt_state": attempt_state,
                "last_sync_success_at": str(
                    declared.get("last_sync_success_at")
                    or (sync.get("last_run_at") if last_status == "ok" else "")
                    or ""
                ),
                "last_ingested_at": str(declared.get("last_ingested_at") or ""),
                "last_attempt_at": str(
                    declared.get("last_attempt_at") or sync.get("last_run_at") or ""
                ),
                "blocked_reason": blocked_reason,
                "last_run_at": str(sync.get("last_run_at") or ""),
                "last_event_ref": str(sync.get("last_event_ref") or ""),
                "emitted_page_ids": emitted_page_ids,
                "emitted_action_ids": emitted_action_ids,
                "proposal_ids": proposal_ids,
                "raw_artifact_count": int(declared.get("raw_artifact_count") or 0),
                "secret_safe_log_refs": list(
                    declared.get("secret_safe_log_refs") or []
                ),
                "reviewed_no_change_receipt": reviewed_no_change_receipt,
                "accepted_ref": accepted_ref,
                "authoring_error_codes": authoring_error_codes,
                "contract_warnings": contract_warnings,
                "stream_counts": {
                    "fresh": int(sync.get("streams_fresh") or 0),
                    "total": int(sync.get("streams_total") or 0),
                },
            }
        )
    return {
        "schema_version": "wiki_source_lifecycle.v2",
        "sources": sorted(sources, key=lambda item: item["source_id"]),
    }


def _snapshot_warnings_payload(
    pages_payload: dict[str, Any],
    block_stacks_payload: dict[str, Any],
    source_lifecycle_payload: dict[str, Any],
    region_groups_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    warnings: list[dict[str, Any]] = []
    pages_by_id = {
        str(page.get("id") or ""): page for page in pages_payload.get("pages") or []
    }
    for anchor_id, record in sorted(
        dict(block_stacks_payload.get("anchors") or {}).items()
    ):
        assignments = dict(
            (record.get("derived") or {}).get("quadrant_assignments") or {}
        )
        q0_count = len(assignments.get("q0_core") or [])
        projected = sum(
            len(value or []) for key, value in assignments.items() if key != "q0_core"
        )
        if q0_count >= 8 and q0_count > projected:
            warnings.append(
                {
                    "code": "q0_overload",
                    "anchor_id": anchor_id,
                    "count": q0_count,
                    "severity": "warning",
                }
            )
        if q0_count >= 25:
            warnings.append(
                {
                    "code": "oversized_core",
                    "anchor_id": anchor_id,
                    "count": q0_count,
                    "severity": "warning",
                }
            )
        for bucket, member_ids in assignments.items():
            for member_id in member_ids or []:
                page_type = str(
                    (pages_by_id.get(str(member_id)) or {}).get("page_type") or ""
                )
                if page_type == "source" and bucket not in {"q2", "q4"}:
                    warnings.append(
                        {
                            "code": "source_wrong_bucket",
                            "anchor_id": anchor_id,
                            "page_id": member_id,
                            "bucket": bucket,
                            "severity": "warning",
                        }
                    )
                if (
                    page_type in {"operational_rule", "source_config", "template_block"}
                    and bucket != "q4"
                ):
                    warnings.append(
                        {
                            "code": "governance_wrong_bucket",
                            "anchor_id": anchor_id,
                            "page_id": member_id,
                            "bucket": bucket,
                            "severity": "warning",
                        }
                    )
        regions = ((record.get("derived") or {}).get("region_groups") or {}).get(
            "groups"
        ) or []
        totals = sorted(
            int((region.get("summary") or {}).get("total") or 0)
            for region in regions
            if int((region.get("summary") or {}).get("total") or 0) > 0
        )
        if len(totals) >= 2:
            median = totals[len(totals) // 2]
            largest = max(totals)
            if largest >= 20 and largest > max(median * 4, 0):
                warnings.append(
                    {
                        "code": "region_imbalance",
                        "anchor_id": anchor_id,
                        "largest": largest,
                        "median": median,
                        "severity": "warning",
                    }
                )
        for region in regions:
            hidden = int((region.get("summary") or {}).get("hidden") or 0)
            if hidden > 0:
                warnings.append(
                    {
                        "code": "region_hidden_density",
                        "anchor_id": anchor_id,
                        "region_id": region.get("id"),
                        "count": hidden,
                        "severity": "info",
                    }
                )
    for source in source_lifecycle_payload.get("sources") or []:
        if source.get("lifecycle_state") == "blocked":
            warnings.append(
                {
                    "code": "source_blocked",
                    "source_id": source.get("source_id"),
                    "reason": source.get("blocked_reason")
                    or source.get("last_attempt_state"),
                    "severity": "warning",
                }
            )
        for warning in source.get("contract_warnings") or []:
            warnings.append(
                {
                    "code": warning,
                    "source_id": source.get("source_id"),
                    "severity": "warning",
                }
            )
    for region in (region_groups_payload or {}).get("groups") or []:
        if region.get("absence_state") != "concerning":
            continue
        warnings.append(
            {
                "code": "region_expected_missing",
                "anchor_id": region.get("anchor_id"),
                "region_id": region.get("id"),
                "severity": "warning",
            }
        )
    return {"schema_version": "wiki_snapshot_warnings.v1", "warnings": warnings}


def snapshot_contract_errors(payloads: dict[str, dict[str, Any]]) -> list[str]:
    manifest = payloads.get("manifest.json") or {}
    errors: list[str] = []
    declared_files = list(manifest.get("files") or [])
    if len(declared_files) != len(set(declared_files)):
        errors.append("duplicate manifest file entries")
    expected_files = [
        name for name in manifest.get("files") or [] if name != "manifest.json"
    ]
    integrity = dict(manifest.get("integrity") or {})
    expected_set = set(expected_files)
    actual_set = set(payloads) - {"manifest.json"}
    for name in sorted(actual_set - expected_set):
        errors.append(f"unlisted payload: {name}")
    for name in sorted(set(integrity) - expected_set):
        errors.append(f"unlisted integrity entry: {name}")
    for name in expected_files:
        if name not in payloads:
            errors.append(f"missing payload: {name}")
            continue
        expected = str((integrity.get(name) or {}).get("sha256") or "")
        actual = _payload_integrity(payloads[name])["sha256"]
        if not expected or expected != actual:
            errors.append(f"integrity mismatch: {name}")
    source_sha = str(manifest.get("source_sha") or "")
    source_commit = manifest.get("source_commit")
    clean_source = bool(re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", source_sha))
    dirty_source = bool(re.fullmatch(r"uncommitted:[0-9a-f]{64}", source_sha))
    if not (clean_source or dirty_source):
        errors.append("invalid source_sha")
    if clean_source and source_commit != source_sha:
        errors.append("clean source_commit must match source_sha")
    if dirty_source and source_commit not in {None, ""}:
        errors.append("uncommitted source must not claim source_commit")
    actual_bundle_hash = _bundle_hash_for_artifacts(payloads)
    declared_bundle_hash = str(manifest.get("bundle_hash") or "")
    if declared_bundle_hash != actual_bundle_hash:
        errors.append("bundle hash mismatch")
    repo_id = str((manifest.get("repo") or {}).get("repo_id") or "")
    expected_snapshot_id = (
        f"{repo_id}-{actual_bundle_hash[:16]}" if repo_id else ""
    )
    if not expected_snapshot_id or manifest.get("snapshot_id") != expected_snapshot_id:
        errors.append("snapshot id does not match bundle hash")
    pages = list((payloads.get("pages.json") or {}).get("pages") or [])
    ids = [str(page.get("id") or "") for page in pages]
    duplicates = sorted(
        {page_id for page_id in ids if page_id and ids.count(page_id) > 1}
    )
    if not all(ids):
        errors.append("empty page id")
    if duplicates:
        errors.append(f"duplicate page ids: {', '.join(duplicates)}")
    for page in pages:
        page_id = str(page.get("id") or "<missing-id>")
        content_sha = str(page.get("content_sha256") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", content_sha):
            errors.append(f"invalid page content hash: {page_id}")
    raw_root_page_id = manifest.get("root_page_id")
    root_page_id = str(raw_root_page_id or "")
    empty_compat = "empty_world_compat" in (manifest.get("capabilities") or [])
    fixture = manifest.get("fixture")
    declared_genesis_zero = bool(
        isinstance(fixture, dict)
        and fixture.get("genesis_stage") == 0
        and not pages
        and (raw_root_page_id is None or raw_root_page_id == "")
    )
    if empty_compat and not declared_genesis_zero:
        errors.append(
            "empty-world compatibility requires a declared Genesis stage 0 fixture"
        )
    if not empty_compat and root_page_id not in set(ids):
        errors.append(f"root page missing: {root_page_id or '<empty>'}")
    known = set(ids)
    required_versions = {
        "snapshot",
        "runtime_contract",
        "block_vocabulary",
        "visual_grammar",
        "semantic_visual_tokens",
        "source_lifecycle",
        "source_freshness",
        "source_last_attempt",
        "registry_module_api",
        "canonical_route",
        "relation_vocabulary",
        "activity_timeline",
        "temporal_event",
        "temporal_graph",
    }
    missing_versions = required_versions - set((manifest.get("versions") or {}).keys())
    if missing_versions:
        errors.append(
            f"missing contract versions: {', '.join(sorted(missing_versions))}"
        )
    activity_timeline = payloads.get("timeline.json") or {}
    if activity_timeline.get("contract_version") != WEB_ACTIVITY_TIMELINE_VERSION:
        errors.append("activity timeline contract version mismatch")
    activity_events = activity_timeline.get("events")
    if not isinstance(activity_events, list):
        errors.append("activity timeline events must be a list")
    elif (
        activity_timeline.get("event_count") != len(activity_events)
        or activity_timeline.get("returned_count") != len(activity_events)
        or activity_timeline.get("truncated") is not False
        or activity_timeline.get("next_cursor") is not None
    ):
        errors.append("activity timeline compatibility counts disagree")
    temporal_payload = payloads.get("temporal_graph.json") or {}
    errors.extend(temporal_graph_errors(temporal_payload))
    if (
        temporal_payload.get("truncated") is not False
        or temporal_payload.get("next_cursor") is not None
        or temporal_payload.get("returned_count")
        != temporal_payload.get("total_count")
    ):
        errors.append("static temporal graph must carry its complete event set")
    capabilities = set(manifest.get("capabilities") or [])
    versions = manifest.get("versions") or {}
    pack_capability_advertised = "experience_packs" in capabilities
    pack_version_advertised = "experience_pack_composition" in versions
    pack_file_declared = "experience_packs.json" in declared_files
    pack_payload_present = "experience_packs.json" in payloads
    if any(
        (
            pack_capability_advertised,
            pack_version_advertised,
            pack_file_declared,
            pack_payload_present,
        )
    ):
        if not pack_capability_advertised:
            errors.append("experience pack composition capability missing")
        if (
            versions.get("experience_pack_composition")
            != WEB_EXPERIENCE_PACK_COMPOSITION_VERSION
        ):
            errors.append("experience pack composition manifest version mismatch")
        if not pack_file_declared:
            errors.append("experience pack composition file declaration missing")
        if not pack_payload_present:
            errors.append("experience pack composition payload missing")
        else:
            errors.extend(
                _experience_pack_composition_errors(payloads["experience_packs.json"])
            )
    graph_payload = payloads.get("graph.json") or {}
    if (
        graph_payload.get("overlay_metrics_version")
        != WEB_SEMANTIC_VISUAL_TOKENS_VERSION
    ):
        errors.append("graph overlay metrics version mismatch")
    for node in graph_payload.get("nodes") or []:
        node_id = str(node.get("id") or "<missing-id>")
        metrics = node.get("overlay_metrics")
        if not isinstance(metrics, dict) or set(metrics) != set(OVERLAY_STATES):
            errors.append(f"invalid overlay metric set: {node_id}")
            continue
        for overlay, allowed_states in OVERLAY_STATES.items():
            metric = metrics.get(overlay)
            if not isinstance(metric, dict):
                errors.append(f"invalid overlay metric: {node_id}:{overlay}")
                continue
            if metric.get("state") not in allowed_states:
                errors.append(f"invalid overlay state: {node_id}:{overlay}")
            value = metric.get("value")
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, (int, float))
            ):
                errors.append(f"invalid overlay value: {node_id}:{overlay}")
            count = metric.get("count")
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                errors.append(f"invalid overlay count: {node_id}:{overlay}")
            for field in ("reasons", "refs"):
                entries = metric.get(field)
                if not isinstance(entries, list) or any(
                    not isinstance(entry, str) for entry in entries
                ):
                    errors.append(f"invalid overlay {field}: {node_id}:{overlay}")
    relation_types = {
        str(record.get("id") or ""): record
        for record in graph_payload.get("relation_types") or []
    }
    for edge in graph_payload.get("edges") or []:
        if (
            str(edge.get("source") or "") not in known
            or str(edge.get("target") or "") not in known
        ):
            errors.append(f"dangling relation: {edge.get('id') or '<missing-id>'}")
        for field in ("id", "type", "direction", "basis", "provenance", "status"):
            if not edge.get(field):
                errors.append(
                    f"relation missing {field}: {edge.get('id') or '<missing-id>'}"
                )
        definition = relation_types.get(str(edge.get("type") or ""))
        if definition is None:
            errors.append(f"unknown relation type: {edge.get('type') or '<empty>'}")
        elif edge.get("direction") != definition.get("direction"):
            errors.append(
                f"invalid relation direction: {edge.get('id') or '<missing-id>'}"
            )
        elif definition.get("provenance_bearing") and not edge.get("provenance"):
            errors.append(
                f"provenance-bearing relation missing provenance: {edge.get('id') or '<missing-id>'}"
            )

    forbidden_cycles = {
        (
            str(diagnostic["relation_type"]),
            tuple(str(item) for item in diagnostic["cycle_path"]),
        )
        for diagnostic in relation_cycle_diagnostics(
            graph_payload.get("edges") or [], relation_types
        )
    }
    for diagnostic in graph_payload.get("relation_diagnostics") or []:
        relation_type = str(diagnostic.get("type") or "")
        definition = relation_types.get(relation_type) or {}
        reasons = {str(reason) for reason in diagnostic.get("reasons") or []}
        cycle_path = tuple(
            str(item) for item in diagnostic.get("cycle_path") or []
        )
        if (
            "cycle_forbidden" in reasons
            and definition.get("allows_cycles") is False
            and len(cycle_path) >= 2
        ):
            forbidden_cycles.add((relation_type, cycle_path))
    for relation_type, cycle_path in sorted(forbidden_cycles):
        errors.append(
            f"forbidden relation cycle ({relation_type}): "
            + " -> ".join(cycle_path)
        )

    for region in (payloads.get("region_groups.json") or {}).get("groups") or []:
        region_id = str(region.get("id") or "<missing-id>")
        summary = dict(region.get("summary") or {})
        total = int(summary.get("total") or 0)
        shown = int(summary.get("shown") or 0)
        hidden = int(summary.get("hidden") or 0)
        if shown + hidden != total:
            errors.append(f"region count mismatch: {region_id}")
        if any(str(member) not in known for member in region.get("member_ids") or []):
            errors.append(f"region has unknown member: {region_id}")
        expectation = str(region.get("expectation_state") or "")
        absence = str(region.get("absence_state") or "")
        if expectation not in {"required", "optional", "not_applicable", "unknown"}:
            errors.append(f"invalid region expectation: {region_id}")
        if absence not in {"healthy", "concerning", "unmodeled", "not_empty"}:
            errors.append(f"invalid region absence: {region_id}")
        if total == 0 and absence == "not_empty":
            errors.append(f"empty region marked not_empty: {region_id}")
        if total > 0 and absence != "not_empty":
            errors.append(f"non-empty region has absence state: {region_id}")

    valid_action_states = CANONICAL_ACTION_STATES
    valid_owner_kinds = {"human", "agent", "system", "other", "unassigned"}
    for action in (payloads.get("work_items.json") or {}).get("actions") or []:
        action_id = str(action.get("action_id") or "<missing-id>")
        if action_id not in known:
            errors.append(f"work item is not a canonical page: {action_id}")
        if action.get("state") not in valid_action_states:
            errors.append(f"invalid work state: {action_id}")
        if (action.get("owner") or {}).get("kind") not in valid_owner_kinds:
            errors.append(f"invalid work owner: {action_id}")
        if action.get("state") == "done" and not action.get("completion_receipt"):
            errors.append(f"done work missing receipt: {action_id}")
        if action.get("state") == "cancelled" and not action.get(
            "cancellation_receipt"
        ):
            errors.append(f"cancelled work missing receipt: {action_id}")

    for source in (payloads.get("source_lifecycle.json") or {}).get("sources") or []:
        source_id = str(source.get("source_id") or "<missing-id>")
        if source_id not in known:
            errors.append(f"source lifecycle is not a canonical page: {source_id}")
        if source.get("lifecycle_state") not in SOURCE_LIFECYCLE_STATES:
            errors.append(f"invalid source lifecycle: {source_id}")
        if source.get("freshness_state") not in SOURCE_FRESHNESS_STATES:
            errors.append(f"invalid source freshness: {source_id}")
        attempt_state = source.get("last_attempt_state")
        if attempt_state not in SOURCE_LAST_ATTEMPT_STATES:
            errors.append(
                f"invalid source last_attempt_state: {source_id} "
                f"value={attempt_state!r}; allowed={', '.join(SOURCE_LAST_ATTEMPT_STATES)}"
            )
        pipeline_stage = source.get("pipeline_stage")
        if pipeline_stage not in SOURCE_PIPELINE_STAGES:
            errors.append(
                f"invalid source pipeline_stage: {source_id} "
                f"value={pipeline_stage!r}; allowed={', '.join(SOURCE_PIPELINE_STAGES)}"
            )
        adoption_state = source.get("adoption_state")
        if adoption_state not in SOURCE_ADOPTION_STATES:
            errors.append(f"invalid source adoption: {source_id}")
        for code in source.get("authoring_error_codes") or []:
            # These two fields already have the more actionable, safe enum
            # diagnostics above. Avoid duplicating them in the manifest.
            if code in {
                "invalid_source_last_attempt_state",
                "invalid_source_pipeline_stage",
            }:
                continue
            errors.append(
                f"invalid source lifecycle declaration: {source_id} [{code}]"
            )
        if adoption_state == "accepted":
            if not source.get("accepted_ref") or not source.get("emitted_page_ids"):
                errors.append(
                    f"accepted source missing ref/emitted-page closure: {source_id}"
                )
        if adoption_state == "reviewed_no_change":
            if not source.get("accepted_ref") or not source.get(
                "reviewed_no_change_receipt"
            ):
                errors.append(
                    f"reviewed-no-change source missing ref/receipt: {source_id}"
                )
        if source.get("lifecycle_state") == "ingested":
            has_closure = bool(
                source.get("emitted_page_ids")
                or source.get("reviewed_no_change_receipt")
            )
            if not has_closure or not source.get("accepted_ref"):
                errors.append(
                    f"ingested source missing closure/acceptance: {source_id}"
                )
    return sorted(set(errors))


def _score_payload(
    root: Path, config: WikiConfig, pages_payload: dict[str, Any]
) -> dict[str, Any]:
    """Karma/vitality read model for the cockpit missions panel.

    Gamification stays honest: everything here is computed from the append-only
    score ledger and real page state — never fabricated. Disabled repos get an
    explicit ``enabled: false`` payload."""
    payload: dict[str, Any] = {
        "schema_version": "wiki_web_score.v1",
        "enabled": bool(config.karma_enabled),
        "event_count": 0,
        "total": 0.0,
        "level": None,
        "level_labels": {},
        "by_dimension": {},
        "badges": [],
        "vitality": {},
    }
    if not config.karma_enabled:
        return payload
    try:
        from wiki_core.paths import WikiPaths
        from wiki_core.score import (
            badge_display,
            compute_karma,
            context_vitality,
            earned_badges,
            level_display,
            level_for,
            load_events,
            resolve_events_path,
        )

        events_path = resolve_events_path(WikiPaths(root, config).derived_root)
        events = load_events(events_path)
        karma = compute_karma(events)
        level_id = level_for(float(karma["total"]))
        payload.update(
            {
                "event_count": len(events),
                "total": karma["total"],
                "by_dimension": karma["by_dimension"],
                "level": level_id,
                "level_labels": {
                    "en": level_display(level_id, "en"),
                    "es": level_display(level_id, "es"),
                    "pt": level_display(level_id, "pt"),
                },
                "badges": [
                    {
                        "id": badge_id,
                        "en": str(badge_display(badge_id, "en").get("name", badge_id)),
                        "es": str(badge_display(badge_id, "es").get("name", badge_id)),
                        "pt": str(badge_display(badge_id, "pt").get("name", badge_id)),
                        "criterion_en": str(
                            badge_display(badge_id, "en").get("criterion", "")
                        ),
                        "criterion_es": str(
                            badge_display(badge_id, "es").get("criterion", "")
                        ),
                        "criterion_pt": str(
                            badge_display(badge_id, "pt").get("criterion", "")
                        ),
                    }
                    for badge_id in earned_badges(events)
                ],
            }
        )
        pages = pages_payload.get("pages", [])
        contexts = sorted(
            {str(page.get("context") or config.default_context) for page in pages}
        )
        vitality: dict[str, Any] = {}
        for context in contexts:
            members = [
                page
                for page in pages
                if str(page.get("context") or config.default_context) == context
            ]
            meta = {
                "paginas_total": len(members),
                "paginas_atualizadas": sum(
                    1 for page in members if page.get("freshness_state") == "fresh"
                ),
                "pendencias": sum(
                    1 for page in members if page.get("freshness_state") != "fresh"
                ),
                "paginas_orfas": sum(
                    1 for page in members if not page.get("moc_parent")
                ),
                "fontes_recentes": sum(
                    1
                    for page in members
                    if str(page.get("page_type") or "").startswith("source")
                    and page.get("freshness_state") == "fresh"
                ),
            }
            vitality[context] = context_vitality(events, context, meta)
        payload["vitality"] = vitality
    except Exception as exc:  # pragma: no cover - defensive snapshot surface
        payload["error"] = str(exc)
    return payload


def _safe_blocks(
    root: Path,
    config: WikiConfig,
    *,
    today: dt.date | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The v2 block registry (blocks.json) and per-anchor resolved stacks
    (block_stacks.json). Wrapped like the other rich payloads so a malformed
    block never breaks the whole snapshot — the dock shows the error instead."""
    try:
        from wiki_core.template_blocks import blocks_payloads

        return blocks_payloads(root, config, today=today or _today())
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
        return (
            {
                "schema_version": "wiki_web_blocks.v1",
                "blocks": {},
                "vocabulary": {},
                "warnings": [],
                "error": error,
            },
            {
                "schema_version": "wiki_web_block_stacks.v1",
                "anchors": {},
                "error": error,
            },
        )


def _safe_quality(root: Path, config: WikiConfig) -> dict[str, Any]:
    try:
        report = build_quality_report(root, config)
    except Exception as exc:  # pragma: no cover - defensive snapshot surface
        return {"schema_version": "wiki_quality_report.v1", "error": str(exc)}
    return report


def _safe_ingestion(root: Path, config: WikiConfig) -> dict[str, Any]:
    try:
        return build_ingestion_closure_report(root, config)
    except Exception as exc:  # pragma: no cover - defensive snapshot surface
        return {"schema_version": "wiki_ingestion_closure.v1", "error": str(exc)}


def _experience_pack_composition_payload(root: Path) -> dict[str, Any]:
    """Compose the installed pack adapters or fail the snapshot closed.

    Pack state is unlike an optional rich read model: publishing a healthy
    empty payload after a malformed lock, drifted installed tree or composition
    conflict would hide an active runtime extension.  Compose first so lock
    parsing errors remain the kernel's safe structured ``PackError``; then
    verify the installed state and a second deterministic composition before
    allowing the payload into the atomic snapshot envelope.
    """

    composition = compose_active_packs(root)
    validation = validate_experience_pack_installation(root)
    if validation.get("status") != "valid":
        diagnostics = sorted(
            {
                f"{str(row.get('code') or 'invalid')}:{str(row.get('pack') or 'unknown')}"
                for row in validation.get("errors") or []
                if isinstance(row, dict)
            }
        )
        raise PackError(
            "active_pack_composition_invalid",
            ",".join(diagnostics) or "validation_failed",
        )
    if validation.get("composition") != composition:
        raise PackError("active_pack_composition_changed_during_snapshot")
    return composition


def _experience_pack_composition_errors(payload: Any) -> list[str]:
    """Validate the v1 composition without a runtime jsonschema dependency."""

    if not isinstance(payload, dict):
        return ["experience pack composition must be an object"]

    errors: list[str] = []
    if set(payload) != EXPERIENCE_PACK_COMPOSITION_FIELDS:
        errors.append("experience pack composition fields mismatch")
    if (
        payload.get("schema_version")
        != WEB_EXPERIENCE_PACK_COMPOSITION_VERSION
    ):
        errors.append("experience pack composition schema version mismatch")
    if payload.get("core_version") != EXPERIENCE_PACK_CORE_VERSION:
        errors.append("experience pack core version mismatch")

    packs = payload.get("packs")
    pack_ids: list[str] = []
    valid_pack_rows = isinstance(packs, list)
    if not valid_pack_rows:
        errors.append("experience pack composition packs must be a list")
        packs = []
    for row in packs:
        if (
            not isinstance(row, dict)
            or set(row) != {"id", "version"}
            or not isinstance(row.get("id"), str)
            or not EXPERIENCE_PACK_ID_RE.fullmatch(row["id"])
            or not isinstance(row.get("version"), str)
            or not EXPERIENCE_PACK_SEMVER_RE.fullmatch(row["version"])
        ):
            errors.append("invalid experience pack composition pack record")
            valid_pack_rows = False
            continue
        pack_ids.append(row["id"])
    if valid_pack_rows:
        if pack_ids != sorted(pack_ids) or len(pack_ids) != len(set(pack_ids)):
            errors.append("experience pack composition packs are not canonical")

    block_packages = payload.get("block_packages")
    if (
        not isinstance(block_packages, list)
        or any(
            not isinstance(value, str)
            or not EXPERIENCE_PACK_CAPABILITY_RE.fullmatch(value)
            for value in block_packages
        )
    ):
        errors.append("invalid experience pack block packages")
        block_packages = []
    elif block_packages != sorted(set(block_packages)):
        errors.append("experience pack block packages are not canonical")

    slots = payload.get("slots")
    if not isinstance(slots, dict) or set(slots) != set(
        EXPERIENCE_PACK_SLOT_KINDS
    ):
        errors.append("experience pack composition slot kinds mismatch")
        slots = {}
    known_packs = set(pack_ids)
    for kind in EXPERIENCE_PACK_SLOT_KINDS:
        rows = slots.get(kind)
        if not isinstance(rows, list):
            errors.append(f"experience pack {kind} slots must be a list")
            continue
        canonical_rows: list[tuple[str, str, str, str]] = []
        seen_rows: set[tuple[str, str, str, str]] = set()
        rows_valid = True
        for row in rows:
            if (
                not isinstance(row, dict)
                or set(row) != {"pack", "slot", "contribution", "mode"}
                or row.get("pack") not in known_packs
                or not isinstance(row.get("slot"), str)
                or not row["slot"].startswith(f"{kind[:-1]}.")
                or not EXPERIENCE_PACK_CAPABILITY_RE.fullmatch(row["slot"])
                or not isinstance(row.get("contribution"), str)
                or not EXPERIENCE_PACK_CAPABILITY_RE.fullmatch(
                    row["contribution"]
                )
                or not row["contribution"].startswith(f"{row['pack']}.")
                or row.get("mode") not in {"append", "exclusive"}
            ):
                errors.append(f"invalid experience pack {kind} slot record")
                rows_valid = False
                continue
            identity = (
                row["pack"],
                row["slot"],
                row["contribution"],
                row["mode"],
            )
            if identity in seen_rows:
                errors.append(f"duplicate experience pack {kind} slot record")
                rows_valid = False
            seen_rows.add(identity)
            canonical_rows.append(identity)
        if rows_valid and canonical_rows != sorted(canonical_rows):
            errors.append(f"experience pack {kind} slots are not canonical")

    presentation = payload.get("presentation")
    locale_labels: dict[str, dict[str, str]] = {}
    if (
        not isinstance(presentation, dict)
        or set(presentation) != {"default_locale", "locales"}
        or presentation.get("default_locale") != "en"
        or not isinstance(presentation.get("locales"), dict)
    ):
        errors.append("experience pack presentation contract mismatch")
    else:
        raw_locales = presentation["locales"]
        if not {"en", "es", "pt-BR"}.issubset(raw_locales) or list(raw_locales) != sorted(
            raw_locales
        ):
            errors.append("experience pack presentation locales are not canonical")
        for locale, labels in raw_locales.items():
            if (
                not isinstance(locale, str)
                or not re.fullmatch(r"[a-z]{2}(?:-[A-Z]{2})?", locale)
                or not isinstance(labels, dict)
            ):
                errors.append("invalid experience pack presentation locale")
                continue
            validated: dict[str, str] = {}
            for identifier, label in labels.items():
                if (
                    not isinstance(identifier, str)
                    or not EXPERIENCE_PACK_CAPABILITY_RE.fullmatch(identifier)
                    or not isinstance(label, str)
                    or label != label.strip()
                    or not 1 <= len(label) <= 96
                    or any(ord(character) < 32 or ord(character) == 127 for character in label)
                ):
                    errors.append("invalid experience pack presentation label")
                    continue
                owners = [
                    pack_id
                    for pack_id in pack_ids
                    if identifier == pack_id
                    or identifier.startswith(f"{pack_id}.")
                    or identifier.startswith(f"{pack_id.replace('-', '_')}_")
                ]
                if len(owners) != 1:
                    errors.append("experience pack presentation label is not pack-owned")
                    continue
                validated[identifier] = label
            if list(labels) != sorted(labels):
                errors.append("experience pack presentation labels are not canonical")
            locale_labels[locale] = validated
        if locale_labels:
            key_sets = {tuple(labels) for labels in locale_labels.values()}
            if len(key_sets) != 1:
                errors.append("experience pack presentation locale parity mismatch")
            required_labels = set(pack_ids)
            for kind in EXPERIENCE_PACK_SLOT_KINDS:
                required_labels.update(
                    row.get("contribution")
                    for row in slots.get(kind, [])
                    if isinstance(row, dict) and isinstance(row.get("contribution"), str)
                )
            for locale, labels in locale_labels.items():
                if not required_labels.issubset(labels):
                    errors.append(
                        f"experience pack presentation labels are incomplete for {locale}"
                    )

    semantic_payload = {
        "packs": payload.get("packs"),
        "block_packages": payload.get("block_packages"),
        "slots": payload.get("slots"),
        "presentation": payload.get("presentation"),
    }
    expected_hash = hashlib.sha256(_canonical_json(semantic_payload)).hexdigest()
    composition_hash = payload.get("composition_sha256")
    if (
        not isinstance(composition_hash, str)
        or not re.fullmatch(r"[0-9a-f]{64}", composition_hash)
        or composition_hash != expected_hash
    ):
        errors.append("experience pack composition hash mismatch")
    return errors


def build_snapshot(
    root: Path,
    config: WikiConfig | None = None,
    *,
    mode: str = "static",
    generated_at: str | None = None,
    content_sidecars: bool = False,
    reference_date: dt.date | None = None,
) -> dict[str, dict[str, Any]]:
    config = config or load_config(root)
    paths = WikiPaths(root, config)
    generated_at = generated_at or _utc_now()
    if reference_date is None:
        try:
            reference_date = dt.date.fromisoformat(generated_at[:10])
        except (TypeError, ValueError):
            reference_date = _today()
    experience_pack_composition_payload = _experience_pack_composition_payload(root)
    pack_temporal_adapters = load_active_temporal_adapters(root)
    git_payload = build_git_state(root, config)
    pages, collection_compilation = _pages_payload_with_collections(
        root,
        config,
        today=reference_date,
        temporal_adapter_fields=temporal_adapter_projection(
            pack_temporal_adapters
        ),
    )
    operations = _operations_payload(root, config)
    actions = build_operator_command_cards(config)
    timeline = build_timeline_payload(
        root,
        config,
        pages,
        operations,
        git_payload,
        generated_at=generated_at,
    )
    diff = build_diff_payload(root, config, git_payload)
    blocks_payload, block_stacks_payload = _safe_blocks(
        root,
        config,
        today=reference_date,
    )
    source_entities_payload = _safe_source_entities(
        root,
        config,
        today=reference_date,
    )
    operator_commands_payload = _operator_commands_payload(actions)
    work_items_payload = _work_items_payload(pages, today=reference_date)
    region_groups_payload = _region_groups_payload(block_stacks_payload, pages)
    source_lifecycle_payload = _source_lifecycle_payload(pages, source_entities_payload)
    temporal_graph_payload = build_temporal_graph_payload(
        pages,
        source_lifecycle_payload,
        timeline,
        repo_id=config.repo_id,
        generated_at=generated_at,
        pack_temporal_adapters=pack_temporal_adapters,
        ingest_events_dir=paths.rel(paths.ingest_events_dir),
        # Static snapshots carry the complete event set. Cursor pagination is
        # available in the canonical builder for a future transport endpoint;
        # a static UI never receives a next cursor it cannot resolve.
        limit=None,
    )
    snapshot_warnings_payload = _snapshot_warnings_payload(
        pages,
        block_stacks_payload,
        source_lifecycle_payload,
        region_groups_payload,
    )
    quality_payload = _safe_quality(root, config)
    gates_payload = _gates_payload(root, config)
    payloads = {
        "operations.json": operations,
        "graph.json": _graph_payload(
            root,
            config,
            pages,
            collection_compilation,
            quality_payload,
            snapshot_warnings_payload,
            gates_payload,
            source_lifecycle_payload,
            today=reference_date,
        ),
        "pages.json": pages,
        "sources.json": _sources_payload(pages),
        "source_entities.json": source_entities_payload,
        "templates.json": _safe_templates(root, config, pages),
        "actions.json": actions,
        "decisions.json": _decisions_payload(pages),
        "freshness.json": _freshness_payload(pages, config),
        "gates.json": gates_payload,
        "git.json": git_payload,
        "timeline.json": timeline,
        "temporal_graph.json": temporal_graph_payload,
        "experience_packs.json": experience_pack_composition_payload,
        "diff.json": diff,
        "ingestion.json": _safe_ingestion(root, config),
        "quality.json": quality_payload,
        "commands.json": _commands_payload(actions),
        "score.json": _score_payload(root, config, pages),
        "blocks.json": blocks_payload,
        "block_stacks.json": block_stacks_payload,
        "operator_commands.json": operator_commands_payload,
        "work_items.json": work_items_payload,
        "region_groups.json": region_groups_payload,
        "source_lifecycle.json": source_lifecycle_payload,
        "snapshot_warnings.json": snapshot_warnings_payload,
    }
    integrity = {
        name: _payload_integrity(payload) for name, payload in payloads.items()
    }
    bundle_hash = _bundle_hash_for_artifacts(payloads)
    source_sha, source_commit = _source_identity(root, bundle_hash)
    snapshot_id = f"{config.repo_id}-{bundle_hash[:16]}"
    capabilities = [
        "atomic_envelope",
        "integrity_sha256",
        "stable_page_ids",
        "validated_runtime_boundary",
        "source_lifecycle",
        "region_groups",
        "work_items",
        "operator_commands",
        "relation_vocabulary",
        "visual_grammar",
        "semantic_visual_tokens",
        "snapshot_warnings",
        "temporal_graph",
        "experience_packs",
    ]
    if content_sidecars:
        capabilities.append("content_sidecars")
    if not pages.get("pages"):
        capabilities.append("empty_world_compat")
    manifest = {
        "schema_version": WEB_SNAPSHOT_SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "root_page_id": _root_page_id(config, pages),
        "content_sidecars": content_sidecars,
        "repo": {
            "repo_id": config.repo_id,
            "language": config.language,
            "memory_root": config.paths["memory_root"],
            "default_context": config.default_context,
            "karma_enabled": config.karma_enabled,
            "default_branch": git_payload.get("default_branch") or "main",
            "branch_prefix": config.approval.get("branch_prefix", "wiki/"),
        },
        "generated_at": generated_at,
        "source_sha": source_sha,
        # v1 compatibility field. It is deliberately null for dirty/non-Git
        # inputs so a WIP snapshot never impersonates a clean commit.
        "source_commit": source_commit,
        "mode": mode,
        "capabilities": capabilities,
        "versions": {
            "snapshot": WEB_SNAPSHOT_SCHEMA_VERSION,
            "runtime_contract": WEB_RUNTIME_CONTRACT_VERSION,
            "block_vocabulary": WEB_BLOCK_VOCABULARY_VERSION,
            "visual_grammar": WEB_VISUAL_GRAMMAR_VERSION,
            "semantic_visual_tokens": WEB_SEMANTIC_VISUAL_TOKENS_VERSION,
            "source_lifecycle": WEB_SOURCE_LIFECYCLE_VERSION,
            "source_freshness": WEB_SOURCE_FRESHNESS_VERSION,
            "source_last_attempt": WEB_SOURCE_LAST_ATTEMPT_VERSION,
            "registry_module_api": WEB_REGISTRY_MODULE_API_VERSION,
            "canonical_route": WEB_ROUTE_CONTRACT_VERSION,
            "relation_vocabulary": WEB_RELATION_VOCABULARY_VERSION,
            "activity_timeline": WEB_ACTIVITY_TIMELINE_VERSION,
            "temporal_event": WEB_TEMPORAL_EVENT_VERSION,
            "temporal_graph": WEB_TEMPORAL_GRAPH_VERSION,
            "experience_pack_composition": (
                WEB_EXPERIENCE_PACK_COMPOSITION_VERSION
            ),
        },
        "files": list(SNAPSHOT_FILES),
        "integrity": integrity,
        "bundle_hash": bundle_hash,
    }
    result = {"manifest.json": manifest, **payloads}
    manifest["contract_errors"] = snapshot_contract_errors(result)
    return result


def prepare_snapshot_artifacts(
    root: Path,
    config: WikiConfig,
    payloads: dict[str, dict[str, Any]],
    *,
    content_sidecars: bool,
) -> dict[str, dict[str, Any]]:
    """Finalize one complete snapshot artifact set before any filesystem write.

    The manifest is copied, then extended with every generated content sidecar.
    Its file list, integrity map and bundle hash therefore describe the exact
    directory that will be promoted, rather than only the top-level read models.
    """

    from wiki_core.web.content import build_page_content, sidecar_name

    artifacts = dict(payloads)
    manifest = dict(artifacts.get("manifest.json") or {})
    artifacts["manifest.json"] = manifest
    capabilities = [
        str(value)
        for value in manifest.get("capabilities") or []
        if value != "content_sidecars"
    ]
    if content_sidecars:
        capabilities.append("content_sidecars")
        for page in (artifacts.get("pages.json") or {}).get("pages") or []:
            page_id = str(page.get("id") or page.get("path") or "")
            if not page_id:
                continue
            name = f"content/{sidecar_name(page_id)}"
            if name in artifacts:
                raise ValueError(f"duplicate content sidecar path: {name}")
            content = build_page_content(root, config, page_id, artifacts)
            if not content.get("ok"):
                raise ValueError(
                    f"cannot freeze content sidecar for {page_id!r}: "
                    f"{content.get('error') or 'unknown content error'}"
                )
            artifacts[name] = content
    manifest["content_sidecars"] = content_sidecars
    manifest["capabilities"] = capabilities
    sidecar_files = sorted(name for name in artifacts if name.startswith("content/"))
    manifest["files"] = [*SNAPSHOT_FILES, *sidecar_files]
    bundle_hash = _bundle_hash_for_artifacts(artifacts)
    repo_id = str((manifest.get("repo") or {}).get("repo_id") or config.repo_id)
    snapshot_id = f"{repo_id}-{bundle_hash[:16]}"
    for name in sidecar_files:
        payload = dict(artifacts[name])
        payload["snapshot_id"] = snapshot_id
        artifacts[name] = payload
    manifest["snapshot_id"] = snapshot_id
    manifest["integrity"] = {
        name: _payload_integrity(artifacts[name])
        for name in manifest["files"]
        if name != "manifest.json"
    }
    manifest["bundle_hash"] = bundle_hash
    manifest["bundle_hash_basis"] = (
        "normalized_artifacts_without_embedded_snapshot_id.v1"
    )
    manifest["contract_errors"] = []
    manifest["contract_errors"] = snapshot_contract_errors(artifacts)
    return artifacts


def _write_snapshot_artifacts(
    target_dir: Path, artifacts: dict[str, dict[str, Any]]
) -> dict[str, Path]:
    written: dict[str, Path] = {}
    for name, payload in artifacts.items():
        rel = Path(name)
        if rel.is_absolute() or not rel.parts or ".." in rel.parts:
            raise ValueError(f"unsafe snapshot artifact path: {name!r}")
        target = target_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                payload,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        written[name] = target
    return written


def _snapshot_tree_inventory(target_dir: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Inventory one snapshot tree without following or reading symlinks."""

    if target_dir.is_symlink():
        raise ValueError(f"snapshot directory is a symlink: {target_dir}")
    try:
        root_mode = target_dir.stat(follow_symlinks=False).st_mode
    except FileNotFoundError:
        raise
    if not stat.S_ISDIR(root_mode):
        raise ValueError(f"snapshot path is not a directory: {target_dir}")

    files: list[str] = []
    directories: list[str] = []

    def visit(directory: Path, relative_parent: Path) -> None:
        with os.scandir(directory) as entries:
            for entry in entries:
                relative = relative_parent / entry.name
                relative_name = relative.as_posix()
                entry_stat = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(entry_stat.st_mode):
                    raise ValueError(
                        f"snapshot directory contains symlink: {relative_name}"
                    )
                if stat.S_ISDIR(entry_stat.st_mode):
                    directories.append(relative_name)
                    visit(directory / entry.name, relative)
                elif stat.S_ISREG(entry_stat.st_mode):
                    files.append(relative_name)
                else:
                    raise ValueError(
                        "snapshot directory contains a non-regular entry: "
                        f"{relative_name}"
                    )

    visit(target_dir, Path())
    return tuple(sorted(files)), tuple(sorted(directories))


def _snapshot_tree_fingerprint(target_dir: Path) -> tuple[tuple[object, ...], ...]:
    """Return a metadata fingerprint after a strict no-follow inventory scan."""

    files, directories = _snapshot_tree_inventory(target_dir)
    fingerprint: list[tuple[object, ...]] = []
    for name in ("", *directories, *files):
        path = target_dir if not name else target_dir / name
        entry_stat = path.stat(follow_symlinks=False)
        if stat.S_ISLNK(entry_stat.st_mode):
            raise ValueError(f"snapshot fingerprint encountered symlink: {name}")
        fingerprint.append(
            (
                name,
                stat.S_IFMT(entry_stat.st_mode),
                entry_stat.st_dev,
                entry_stat.st_ino,
                entry_stat.st_size,
                entry_stat.st_mtime_ns,
                entry_stat.st_ctime_ns,
            )
        )
    return tuple(fingerprint)


def _declared_snapshot_files(manifest: dict[str, Any]) -> tuple[str, ...]:
    raw_declared = manifest.get("files")
    if not isinstance(raw_declared, list):
        raise ValueError("snapshot manifest files must be a list")
    declared: list[str] = []
    for value in raw_declared:
        if not isinstance(value, str):
            raise ValueError("snapshot manifest file names must be strings")
        relative = Path(value)
        if (
            relative.is_absolute()
            or not relative.parts
            or value != relative.as_posix()
            or any(part in {"", ".", ".."} for part in relative.parts)
            or value == OUTPUT_OWNER_FILENAME
        ):
            raise ValueError(f"unsafe snapshot artifact path: {value!r}")
        declared.append(value)
    if len(set(declared)) != len(declared):
        raise ValueError("snapshot manifest contains duplicate file names")
    if "manifest.json" not in declared:
        raise ValueError("snapshot manifest must declare manifest.json")
    return tuple(declared)


def _read_snapshot_file_bytes(target_dir: Path, name: str) -> bytes:
    """Read one regular in-tree file through a no-follow component chain."""

    relative = Path(name)
    if os.name != "posix":  # pragma: no cover - Windows flat-build fallback.
        path = target_dir / relative
        before = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or path.is_symlink():
            raise ValueError(f"snapshot artifact is unsafe: {name}")
        data = path.read_bytes()
        if path.read_bytes() != data:
            raise ValueError(f"snapshot artifact bytes changed while reading: {name}")
        after = path.stat(follow_symlinks=False)
        if (before.st_dev, before.st_ino, before.st_size) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
        ):
            raise ValueError(f"snapshot artifact changed while reading: {name}")
        return data

    directory_fd = os.open(target_dir, _directory_open_flags())
    file_fd: int | None = None
    try:
        for part in relative.parts[:-1]:
            next_fd = os.open(part, _directory_open_flags(), dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        file_fd = os.open(relative.name, flags, dir_fd=directory_fd)
        before = os.fstat(file_fd)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"snapshot artifact is not a regular file: {name}")
        with os.fdopen(file_fd, "rb", closefd=False) as handle:
            data = handle.read()
            handle.seek(0)
            if handle.read() != data:
                raise ValueError(
                    f"snapshot artifact bytes changed while reading: {name}"
                )
        after = os.fstat(file_fd)
        if (before.st_dev, before.st_ino, before.st_size) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
        ):
            raise ValueError(f"snapshot artifact changed while reading: {name}")
        return data
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(directory_fd)


def _strict_snapshot_directory_payloads(
    target_dir: Path,
    *,
    role: str,
) -> dict[str, dict[str, Any]]:
    """Load exactly the declared regular-file inventory of one snapshot."""

    before_files, before_directories = _snapshot_tree_inventory(target_dir)
    if "manifest.json" not in before_files:
        raise ValueError(f"snapshot {role} directory has no manifest.json")
    manifest_bytes = _read_snapshot_file_bytes(target_dir, "manifest.json")
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("snapshot manifest must be a JSON object")
    declared = _declared_snapshot_files(manifest)
    actual_payload_files = tuple(
        name for name in before_files if name != OUTPUT_OWNER_FILENAME
    )
    expected_directories = {
        parent.as_posix()
        for name in declared
        for parent in Path(name).parents
        if parent != Path(".")
    }
    if (
        tuple(sorted(declared)) != actual_payload_files
        or tuple(sorted(expected_directories)) != before_directories
    ):
        raise ValueError(
            f"snapshot {role} directory differs from manifest: "
            f"declared={len(declared)} actual={len(actual_payload_files)}"
        )
    artifact_bytes = {"manifest.json": manifest_bytes}
    artifact_bytes.update(
        {
            name: _read_snapshot_file_bytes(target_dir, name)
            for name in declared
            if name != "manifest.json"
        }
    )
    loaded = {
        name: json.loads(artifact_bytes[name].decode("utf-8"))
        for name in declared
    }
    after_inventory = _snapshot_tree_inventory(target_dir)
    if after_inventory != (before_files, before_directories):
        raise ValueError(f"snapshot {role} inventory changed while reading")
    errors = snapshot_contract_errors(loaded)
    if errors:
        raise ValueError(
            f"invalid {role} snapshot contract: " + "; ".join(errors)
        )
    return loaded


def _validate_snapshot_directory(target_dir: Path) -> dict[str, dict[str, Any]]:
    return _strict_snapshot_directory_payloads(target_dir, role="staging")


def _is_legacy_snapshot_directory(target_dir: Path, *, expected_repo_id: str) -> bool:
    """Recognize a complete pre-marker snapshot for one safe migration.

    A directory with any undeclared file is not considered legacy-managed.  It
    therefore cannot smuggle arbitrary user files through the ownership gate.
    """

    try:
        before_files, before_directories = _snapshot_tree_inventory(target_dir)
        manifest = json.loads(
            _read_snapshot_file_bytes(target_dir, "manifest.json").decode("utf-8")
        )
        if not isinstance(manifest, dict):
            return False
        declared = _declared_snapshot_files(manifest)
        actual = tuple(
            name for name in before_files if name != OUTPUT_OWNER_FILENAME
        )
        expected_directories = tuple(
            sorted(
                {
                    parent.as_posix()
                    for name in declared
                    for parent in Path(name).parents
                    if parent != Path(".")
                }
            )
        )
        if manifest.get("schema_version") != WEB_SNAPSHOT_SCHEMA_VERSION:
            return False
        if str((manifest.get("repo") or {}).get("repo_id") or "") != expected_repo_id:
            return False
        if tuple(sorted(declared)) != actual or expected_directories != before_directories:
            return False
        loaded = {
            name: json.loads(
                _read_snapshot_file_bytes(target_dir, name).decode("utf-8")
            )
            for name in declared
        }
        if _snapshot_tree_inventory(target_dir) != (
            before_files,
            before_directories,
        ):
            return False
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
    errors = snapshot_contract_errors(loaded)
    # v8 snapshots generated immediately before RT-34 are structurally and
    # cryptographically complete but do not yet carry per-page content hashes.
    # Recognize exactly that legacy shape so the local operator can adopt its
    # own default cache once; every other contract error remains unowned.
    return bool(errors) and all(
        error.startswith("invalid page content hash: ") for error in errors
    )


def _revision_store_path(out_dir: Path) -> Path:
    return out_dir.parent / f".{out_dir.name}{SNAPSHOT_REVISION_STORE_SUFFIX}"


def _revision_store_kind(output_kind: str) -> str:
    return f"{output_kind}_revision_store"


def _cleanup_receipts_kind(output_kind: str) -> str:
    return f"{output_kind}_cleanup_receipts"


def _cleanup_receipts_path(store: Path) -> Path:
    return store / SNAPSHOT_CLEANUP_RECEIPTS_DIRNAME


def _revision_hash(artifacts: dict[str, dict[str, Any]]) -> str:
    bundle_hash = str((artifacts.get("manifest.json") or {}).get("bundle_hash") or "")
    if not SNAPSHOT_REVISION_HASH_RE.fullmatch(bundle_hash):
        raise ValueError("snapshot bundle_hash is not a canonical sha256 revision")
    return bundle_hash


def _prepare_revision_store(
    root: Path,
    out_dir: Path,
    *,
    output_kind: str,
    repo_id: str,
) -> Path:
    store = validate_managed_output_target(
        root,
        _revision_store_path(out_dir),
        kind=_revision_store_kind(output_kind),
        repo_id=repo_id,
    )
    store.mkdir(parents=True, exist_ok=True)
    write_output_owner(
        store,
        kind=_revision_store_kind(output_kind),
        repo_id=repo_id,
    )
    leases = store / "leases"
    if leases.is_symlink() or (leases.exists() and not leases.is_dir()):
        raise ValueError(f"snapshot leases directory is unsafe: {leases}")
    leases.mkdir(exist_ok=True)
    receipts = validate_managed_output_target(
        root,
        _cleanup_receipts_path(store),
        kind=_cleanup_receipts_kind(output_kind),
        repo_id=repo_id,
    )
    receipts.mkdir(exist_ok=True)
    write_output_owner(
        receipts,
        kind=_cleanup_receipts_kind(output_kind),
        repo_id=repo_id,
    )
    _fsync_file(store / OUTPUT_OWNER_FILENAME)
    _fsync_file(receipts / OUTPUT_OWNER_FILENAME)
    _fsync_directory(leases)
    _fsync_directory(receipts)
    _fsync_directory(store)
    _fsync_directory(store.parent)
    return store


def _managed_revision_pointer_target(
    root: Path,
    out_dir: Path,
    store: Path,
    *,
    output_kind: str,
    repo_id: str,
) -> Path:
    """Resolve only a publisher-owned, repository-contained active pointer.

    This is intentionally narrower than accepting an arbitrary output symlink.
    The link must be relative, point directly into the expected sibling store,
    name one canonical sha256 revision and resolve to a matching owned bundle.
    User-provided target or ancestor symlinks therefore remain rejected.
    """

    relative = _validate_revision_pointer_store(
        root,
        out_dir,
        store,
        output_kind=output_kind,
        repo_id=repo_id,
    )
    target = out_dir.parent / relative
    try:
        if target.parent.resolve(strict=True) != store.resolve(strict=True):
            raise ValueError(f"generated output cannot be a symlink: {out_dir}")
        target_resolved = target.resolve(strict=True)
        target_resolved.relative_to(root.resolve(strict=True))
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(f"generated output cannot be a symlink: {out_dir}") from exc
    if target.is_symlink() or not target.is_dir():
        raise ValueError(f"generated output cannot be a symlink: {out_dir}")
    _validate_owned_snapshot_revision(
        target,
        requested_revision=relative.name,
        output_kind=output_kind,
        repo_id=repo_id,
    )
    return target_resolved


def _validate_revision_pointer_store(
    root: Path,
    out_dir: Path,
    store: Path,
    *,
    output_kind: str,
    repo_id: str,
) -> Path:
    """Validate pointer shape and its owned store without opening a revision.

    Publication uses this narrow pre-lock check so another serialized publisher
    may retire the previously active revision without racing validation. The
    full revision is validated only after acquiring the publication lease.
    """

    if not out_dir.is_symlink():
        raise ValueError(f"generated output is not a revision pointer: {out_dir}")
    contained_output_path(root, out_dir.parent / f".{out_dir.name}.pointer-probe")
    relative = Path(os.readlink(out_dir))
    if (
        relative.is_absolute()
        or relative.parts != (store.name, relative.name)
        or not SNAPSHOT_REVISION_HASH_RE.fullmatch(relative.name)
    ):
        raise ValueError(f"generated output cannot be a symlink: {out_dir}")
    try:
        contained_output_path(root, store)
    except ValueError as exc:
        raise ValueError(f"generated output cannot be a symlink: {out_dir}") from exc
    if not output_is_owned(
        store,
        kind=_revision_store_kind(output_kind),
        repo_id=repo_id,
    ):
        raise ValueError(f"snapshot revision store is not owned by this repo: {store}")
    return relative


def _atomic_exchange_paths(first: Path, second: Path) -> None:
    """Atomically exchange two existing directory entries on Darwin/Linux.

    Python does not expose either syscall. There is deliberately no two-rename
    fallback: on an unsupported platform the one-time legacy-directory
    migration fails closed and leaves both entries untouched.
    """

    if sys.platform != "darwin" and not sys.platform.startswith("linux"):
        raise OSError(
            errno.ENOTSUP,
            "atomic snapshot migration is supported only on Darwin and Linux; "
            "the existing directory was not changed",
        )

    libc = ctypes.CDLL(None, use_errno=True)
    encoded_first = os.fsencode(first)
    encoded_second = os.fsencode(second)
    if sys.platform == "darwin":
        rename_swap = 0x00000002
        renamex_np = libc.renamex_np
        renamex_np.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        renamex_np.restype = ctypes.c_int
        result = renamex_np(encoded_first, encoded_second, rename_swap)
    elif sys.platform.startswith("linux"):
        at_fdcwd = -100
        rename_exchange = 0x00000002
        try:
            renameat2 = libc.renameat2
        except AttributeError as exc:  # pragma: no cover - old libc only.
            raise OSError(
                errno.ENOTSUP,
                "atomic snapshot migration requires renameat2(RENAME_EXCHANGE)",
            ) from exc
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        result = renameat2(
            at_fdcwd,
            encoded_first,
            at_fdcwd,
            encoded_second,
            rename_exchange,
        )
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(
            error_number,
            os.strerror(error_number),
            f"{first} <-> {second}",
        )


def _atomic_install_directory_noreplace(source: Path, target: Path) -> None:
    """Atomically install one directory only when the target entry is absent."""

    libc = ctypes.CDLL(None, use_errno=True)
    encoded_source = os.fsencode(source)
    encoded_target = os.fsencode(target)
    if sys.platform == "darwin":
        rename_excl = 0x00000004
        renamex_np = libc.renamex_np
        renamex_np.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        renamex_np.restype = ctypes.c_int
        result = renamex_np(encoded_source, encoded_target, rename_excl)
    elif sys.platform.startswith("linux"):
        at_fdcwd = -100
        rename_noreplace = 0x00000001
        try:
            renameat2 = libc.renameat2
        except AttributeError as exc:  # pragma: no cover - old libc only.
            raise OSError(
                errno.ENOTSUP,
                "content-addressed install requires renameat2(RENAME_NOREPLACE)",
            ) from exc
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        result = renameat2(
            at_fdcwd,
            encoded_source,
            at_fdcwd,
            encoded_target,
            rename_noreplace,
        )
    else:  # pragma: no cover - live publisher rejects other platforms first.
        raise OSError(
            errno.ENOTSUP,
            "content-addressed directory install is supported only on Darwin/Linux",
        )
    if result != 0:
        error_number = ctypes.get_errno()
        if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
            raise FileExistsError(
                error_number,
                os.strerror(error_number),
                str(target),
            )
        raise OSError(
            error_number,
            os.strerror(error_number),
            f"{source} -> {target}",
        )


def _path_entry_identity(path: Path) -> tuple[int, int, int, str | None]:
    """Capture one stable directory-entry identity without following symlinks."""

    before = path.stat(follow_symlinks=False)
    link_target = os.readlink(path) if stat.S_ISLNK(before.st_mode) else None
    after = path.stat(follow_symlinks=False)
    before_identity = (
        before.st_dev,
        before.st_ino,
        stat.S_IFMT(before.st_mode),
        link_target,
    )
    after_identity = (
        after.st_dev,
        after.st_ino,
        stat.S_IFMT(after.st_mode),
        os.readlink(path) if stat.S_ISLNK(after.st_mode) else None,
    )
    if before_identity != after_identity:
        raise SnapshotPublicationBlockedError("active pathname changed during identity capture")
    return before_identity


def _stat_identity(entry_stat: os.stat_result) -> tuple[int, int, int]:
    return (
        entry_stat.st_dev,
        entry_stat.st_ino,
        stat.S_IFMT(entry_stat.st_mode),
    )


def _descriptor_entry_identity(
    directory_fd: int,
    name: str,
) -> tuple[int, int, int]:
    return _stat_identity(
        os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    )


def _descriptor_tree_children(
    inventory: dict[str, tuple[int, int, int]],
) -> dict[str, set[str]]:
    children: dict[str, set[str]] = {}
    for relative_name in inventory:
        if not relative_name:
            continue
        relative = Path(relative_name)
        parent = relative.parent.as_posix()
        if parent == ".":
            parent = ""
        children.setdefault(parent, set()).add(relative.name)
    return children


def _clear_snapshot_tree_by_descriptor(
    directory_fd: int,
    *,
    relative_directory: str,
    inventory: dict[str, tuple[int, int, int]],
    children: dict[str, set[str]],
) -> None:
    """Delete only the exact no-follow inventory below one pinned directory."""

    expected_names = children.get(relative_directory, set())
    observed_names = set(os.listdir(directory_fd))
    if observed_names != expected_names:
        raise _SnapshotDescriptorTreeRace(
            "snapshot prune inventory changed inside pinned quarantine: "
            f"expected={sorted(expected_names)!r} observed={sorted(observed_names)!r}"
        )
    for name in sorted(observed_names):
        relative_name = f"{relative_directory}/{name}" if relative_directory else name
        expected_identity = inventory.get(relative_name)
        if expected_identity is None:
            raise _SnapshotDescriptorTreeRace(
                f"snapshot prune encountered undeclared entry: {relative_name}"
            )
        try:
            observed_identity = _descriptor_entry_identity(directory_fd, name)
        except OSError as exc:
            raise _SnapshotDescriptorTreeRace(
                f"snapshot prune entry changed before open: {relative_name}"
            ) from exc
        if observed_identity != expected_identity:
            raise _SnapshotDescriptorTreeRace(
                f"snapshot prune entry identity changed: {relative_name}"
            )
        expected_type = expected_identity[2]
        if expected_type == stat.S_IFDIR:
            try:
                child_fd = os.open(
                    name,
                    _directory_open_flags(),
                    dir_fd=directory_fd,
                )
            except OSError as exc:
                raise _SnapshotDescriptorTreeRace(
                    f"snapshot prune directory changed before pin: {relative_name}"
                ) from exc
            try:
                pinned_identity = _stat_identity(os.fstat(child_fd))
                if pinned_identity != expected_identity:
                    raise _SnapshotDescriptorTreeRace(
                        f"snapshot prune directory pin mismatch: {relative_name}"
                    )
                _clear_snapshot_tree_by_descriptor(
                    child_fd,
                    relative_directory=relative_name,
                    inventory=inventory,
                    children=children,
                )
                if (
                    _descriptor_entry_identity(directory_fd, name)
                    != pinned_identity
                ):
                    raise _SnapshotDescriptorTreeRace(
                        f"snapshot prune directory changed before rmdir: {relative_name}"
                    )
                os.rmdir(name, dir_fd=directory_fd)
                os.fsync(directory_fd)
            finally:
                os.close(child_fd)
            continue
        if expected_type != stat.S_IFREG:
            raise _SnapshotDescriptorTreeRace(
                f"snapshot prune refuses non-regular entry: {relative_name}"
            )
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            file_fd = os.open(name, flags, dir_fd=directory_fd)
        except OSError as exc:
            raise _SnapshotDescriptorTreeRace(
                f"snapshot prune file changed before pin: {relative_name}"
            ) from exc
        try:
            pinned_identity = _stat_identity(os.fstat(file_fd))
            if pinned_identity != expected_identity:
                raise _SnapshotDescriptorTreeRace(
                    f"snapshot prune file pin mismatch: {relative_name}"
                )
            if _descriptor_entry_identity(directory_fd, name) != pinned_identity:
                raise _SnapshotDescriptorTreeRace(
                    f"snapshot prune file changed before unlink: {relative_name}"
                )
            os.unlink(name, dir_fd=directory_fd)
            os.fsync(directory_fd)
        finally:
            os.close(file_fd)


def _descriptor_identity_recovery_paths(
    parent_fd: int,
    parent: Path,
    *,
    expected_identity: tuple[int, int, int],
    quarantine: Path,
) -> tuple[Path, ...]:
    recovery: list[Path] = []
    if os.path.lexists(quarantine):
        recovery.append(quarantine)
    with contextlib.suppress(OSError):
        for name in os.listdir(parent_fd):
            candidate = parent / name
            try:
                identity = _descriptor_entry_identity(parent_fd, name)
            except OSError:
                continue
            if identity == expected_identity and candidate not in recovery:
                recovery.append(candidate)
    return tuple(recovery)


def _delete_snapshot_tree_descriptor_pinned(
    store: Path,
    quarantine: Path,
    *,
    expected_identity: tuple[int, int, int, str | None],
    fingerprint: tuple[tuple[object, ...], ...],
) -> None:
    """Delete one validated quarantine through pinned, no-follow descriptors.

    POSIX has no inode-conditional ``rmdir``. The parent entry is therefore
    rechecked against the pinned root immediately before the final dirfd-relative
    rmdir; a non-cooperating writer still has an unavoidable compare-to-rmdir
    micro-window, which publication health reports explicitly.
    """

    expected_root = expected_identity[:3]
    inventory = {
        str(row[0]): (int(row[2]), int(row[3]), int(row[1]))
        for row in fingerprint
    }
    if inventory.get("") != expected_root:
        raise ValueError("snapshot prune fingerprint root identity mismatch")
    children = _descriptor_tree_children(inventory)
    parent_fd = os.open(store, _directory_open_flags())
    root_fd: int | None = None
    try:
        try:
            try:
                root_fd = os.open(
                    quarantine.name,
                    _directory_open_flags(),
                    dir_fd=parent_fd,
                )
            except OSError as exc:
                raise _SnapshotDescriptorTreeRace(
                    "snapshot prune quarantine root changed before descriptor open"
                ) from exc
            pinned_root = _stat_identity(os.fstat(root_fd))
            if pinned_root != expected_root:
                raise _SnapshotDescriptorTreeRace(
                    "snapshot prune quarantine root changed before descriptor pin"
                )
            _clear_snapshot_tree_by_descriptor(
                root_fd,
                relative_directory="",
                inventory=inventory,
                children=children,
            )
            os.fsync(root_fd)
            if (
                _descriptor_entry_identity(parent_fd, quarantine.name)
                != pinned_root
            ):
                raise _SnapshotDescriptorTreeRace(
                    "snapshot prune quarantine root changed before final rmdir"
                )
            os.rmdir(quarantine.name, dir_fd=parent_fd)
            os.fsync(parent_fd)
        except (FileNotFoundError, NotADirectoryError) as exc:
            raise _SnapshotDescriptorTreeRace(
                "snapshot prune quarantine root disappeared or changed type"
            ) from exc
        except _SnapshotDescriptorTreeRace as exc:
            recovery_paths = _descriptor_identity_recovery_paths(
                parent_fd,
                store,
                expected_identity=expected_root,
                quarantine=quarantine,
            )
            raise SnapshotDescriptorDeletionBlockedError(
                str(exc),
                recovery_paths=recovery_paths,
            ) from exc
    finally:
        if root_fd is not None:
            os.close(root_fd)
        os.close(parent_fd)


def _restore_exchanged_path_or_raise(
    active_path: Path,
    candidate_path: Path,
    *,
    expected_candidate_identity: tuple[int, int, int, str | None],
) -> None:
    """Roll back an exchange only while the active entry is still our candidate."""

    try:
        observed_candidate = _path_entry_identity(active_path)
    except (FileNotFoundError, SnapshotPublicationBlockedError) as exc:
        raise RuntimeError(
            "snapshot activation race could not be rolled back safely; "
            f"displaced entry remains at {candidate_path}"
        ) from exc
    if observed_candidate != expected_candidate_identity:
        raise RuntimeError(
            "snapshot activation race changed the candidate before rollback; "
            f"displaced entry remains at {candidate_path}"
        )
    _atomic_exchange_paths(active_path, candidate_path)
    _fsync_directory_set(active_path.parent, candidate_path.parent)


def _activate_snapshot_pointer_cas(
    pointer: Path,
    out_dir: Path,
    *,
    expected_active_identity: tuple[int, int, int, str | None] | None,
) -> bool:
    """Install ``pointer`` without clobbering an absent or changed pathname.

    Returns ``True`` when an existing entry was exchanged into ``pointer`` and
    ``False`` when the candidate was installed into an absent pathname.
    """

    candidate_identity = _path_entry_identity(pointer)
    if expected_active_identity is None:
        try:
            _atomic_install_directory_noreplace(pointer, out_dir)
        except FileExistsError as exc:
            raise SnapshotPublicationBlockedError(
                "active pathname appeared after preflight; external entry preserved"
            ) from exc
        return False

    try:
        _atomic_exchange_paths(out_dir, pointer)
    except FileNotFoundError as exc:
        raise SnapshotPublicationBlockedError(
            "active pathname disappeared after preflight; no activation committed"
        ) from exc

    try:
        displaced_identity = _path_entry_identity(pointer)
    except (FileNotFoundError, SnapshotPublicationBlockedError) as exc:
        _restore_exchanged_path_or_raise(
            out_dir,
            pointer,
            expected_candidate_identity=candidate_identity,
        )
        raise SnapshotPublicationBlockedError(
            "active pathname changed during commit; displaced entry restored"
        ) from exc
    if displaced_identity != expected_active_identity:
        _restore_exchanged_path_or_raise(
            out_dir,
            pointer,
            expected_candidate_identity=candidate_identity,
        )
        raise SnapshotPublicationBlockedError(
            "active pathname changed after preflight; external entry restored"
        )
    return True


def _directory_open_flags() -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return flags


def _open_lock_at(directory_fd: int, name: str) -> Any:
    """Open one regular lock leaf relative to an already pinned directory."""

    if not name or Path(name).name != name or "\x00" in name:
        raise ValueError(f"unsafe snapshot lock name: {name!r}")
    descriptor: int | None = None
    last_missing: FileNotFoundError | None = None
    for _ in range(8):
        try:
            flags = os.O_RDWR | os.O_CREAT
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(name, flags, 0o600, dir_fd=directory_fd)
            break
        except FileNotFoundError as exc:
            # Darwin may transiently report ENOENT when several processes race
            # the first O_CREAT for the same dirfd-relative lock. The pinned
            # no-follow directory/name invariants remain unchanged on retry.
            last_missing = exc
            time.sleep(0.001)
    if descriptor is None:
        assert last_missing is not None
        raise last_missing
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ValueError(f"snapshot lock is not a regular file: {name}")
    return os.fdopen(descriptor, "a+b")


def _open_revision_lock(store: Path, revision: str) -> Any:
    """Pin parent -> store -> leases with openat/O_NOFOLLOW before lock open."""

    parent_fd = os.open(store.parent, _directory_open_flags())
    store_fd: int | None = None
    leases_fd: int | None = None
    try:
        store_fd = os.open(
            store.name,
            _directory_open_flags(),
            dir_fd=parent_fd,
        )
        leases_fd = os.open(
            "leases",
            _directory_open_flags(),
            dir_fd=store_fd,
        )
        return _open_lock_at(leases_fd, f"{revision}.lock")
    finally:
        if leases_fd is not None:
            os.close(leases_fd)
        if store_fd is not None:
            os.close(store_fd)
        os.close(parent_fd)


def _open_contained_directory_fd(root: Path, directory: Path) -> int:
    """Walk a repository-relative directory one no-follow component at a time."""

    root_resolved = root.resolve(strict=True)
    directory_resolved = directory.resolve(strict=True)
    relative = directory_resolved.relative_to(root_resolved)
    current_fd = os.open(root_resolved, _directory_open_flags())
    try:
        for part in relative.parts:
            next_fd = os.open(part, _directory_open_flags(), dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory_set(*directories: Path) -> None:
    """Attempt every distinct directory fsync before surfacing any failure."""

    failures: list[tuple[Path, OSError]] = []
    for directory in dict.fromkeys(directories):
        try:
            _fsync_directory(directory)
        except OSError as exc:
            failures.append((directory, exc))
    if failures:
        detail = ", ".join(str(directory) for directory, _exc in failures)
        raise OSError(errno.EIO, f"snapshot directory fsync failed: {detail}") from (
            failures[0][1]
        )


def _fsync_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"snapshot durable file is unsafe: {path}")
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _fsync_snapshot_tree(root: Path) -> None:
    """Flush every snapshot file, then directories from leaves to root."""

    files = sorted(path for path in root.rglob("*") if path.is_file())
    for path in files:
        if path.is_symlink():
            raise ValueError(f"snapshot staging contains a symlink: {path}")
        with path.open("rb") as handle:
            os.fsync(handle.fileno())
    directories = sorted(
        (path for path in root.rglob("*") if path.is_dir() and not path.is_symlink()),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for directory in [*directories, root]:
        _fsync_directory(directory)


@contextlib.contextmanager
def _revision_lease(store: Path, revision: str, *, exclusive: bool) -> Iterator[bool]:
    """Hold a cross-process advisory lease for one immutable revision."""

    if fcntl is None:  # pragma: no cover - Windows live publication is unsupported.
        yield False
        return
    if not SNAPSHOT_REVISION_HASH_RE.fullmatch(revision):
        raise ValueError(f"snapshot lease revision must be a sha256: {revision!r}")
    leases = store / "leases"
    if leases.is_symlink() or not leases.is_dir():
        raise ValueError(f"snapshot leases directory is unsafe: {leases}")
    try:
        handle = _open_revision_lock(store, revision)
    except FileNotFoundError:
        # A reader may have resolved a revision immediately before serialized
        # cleanup retired it. Let the active-reader loop resolve the pointer
        # again; every other lock error remains a hard unsafe-path failure.
        raise
    except OSError as exc:
        raise ValueError(
            f"snapshot lease lock is unsafe: {leases / f'{revision}.lock'}: {exc}"
        ) from exc
    acquired = False
    try:
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        if exclusive:
            operation |= fcntl.LOCK_NB
        try:
            fcntl.flock(handle.fileno(), operation)
            acquired = True
        except BlockingIOError:
            acquired = False
        yield acquired
    finally:
        if acquired:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


@contextlib.contextmanager
def _publication_lease(root: Path, out_dir: Path) -> Iterator[None]:
    """Serialize store bootstrap, activation and pruning across processes."""

    if fcntl is None:  # pragma: no cover - rejected before store creation.
        raise OSError(errno.ENOTSUP, "cross-process publication leases unavailable")
    lock_name = f".{out_dir.name}.publication.lock"
    lock_path = out_dir.parent / lock_name
    contained_output_path(root, lock_path)
    if lock_path.is_symlink() or (lock_path.exists() and not lock_path.is_file()):
        raise ValueError(f"snapshot publication lock is unsafe: {lock_path}")
    with SNAPSHOT_PUBLICATION_THREAD_LOCK:
        parent_fd: int | None = None
        try:
            parent_fd = _open_contained_directory_fd(root, out_dir.parent)
            handle = _open_lock_at(parent_fd, lock_name)
        except OSError as exc:
            raise ValueError(f"snapshot publication lock is unsafe: {lock_path}") from exc
        finally:
            if parent_fd is not None:
                os.close(parent_fd)
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()


def _load_snapshot_directory(revision_dir: Path) -> dict[str, dict[str, Any]]:
    return _strict_snapshot_directory_payloads(revision_dir, role="active")


def _validate_owned_snapshot_revision(
    revision_dir: Path,
    *,
    requested_revision: str,
    output_kind: str,
    repo_id: str,
    require_directory_name: bool = True,
) -> dict[str, dict[str, Any]]:
    """Prove requested hash == directory == manifest == recomputed bundle."""

    if not SNAPSHOT_REVISION_HASH_RE.fullmatch(requested_revision):
        raise ValueError(f"snapshot revision must be a sha256: {requested_revision!r}")
    if (
        (require_directory_name and revision_dir.name != requested_revision)
        or revision_dir.is_symlink()
        or not revision_dir.is_dir()
    ):
        raise ValueError(
            f"snapshot revision directory does not match request: {revision_dir}"
        )
    try:
        owner = json.loads(
            _read_snapshot_file_bytes(
                revision_dir,
                OUTPUT_OWNER_FILENAME,
            ).decode("utf-8")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            "snapshot revision is not owned by this repo "
            f"(missing or unsafe marker): {revision_dir}"
        ) from exc
    expected_owner = {
        "schema_version": OUTPUT_OWNER_SCHEMA_VERSION,
        "kind": output_kind,
        "repo_id": repo_id,
    }
    if owner != expected_owner:
        raise ValueError(f"snapshot revision is not owned by this repo: {revision_dir}")
    payloads = _load_snapshot_directory(revision_dir)
    manifest_repo_id = str(
        ((payloads.get("manifest.json") or {}).get("repo") or {}).get("repo_id")
        or ""
    )
    if manifest_repo_id != repo_id:
        raise ValueError(
            "snapshot revision manifest belongs to a different repository: "
            f"expected={repo_id!r} observed={manifest_repo_id!r}"
        )
    manifest_revision = str(
        (payloads.get("manifest.json") or {}).get("bundle_hash") or ""
    )
    recomputed_revision = _bundle_hash_for_artifacts(payloads)
    identities = [requested_revision, manifest_revision, recomputed_revision]
    if require_directory_name:
        identities.append(revision_dir.name)
    if len(set(identities)) != 1:
        raise ValueError(
            "snapshot revision identity mismatch: "
            f"requested={requested_revision} directory={revision_dir.name} "
            f"manifest={manifest_revision} recomputed={recomputed_revision}"
        )
    return payloads


def load_active_snapshot_artifacts(
    out_dir: Path,
    *,
    max_attempts: int = 8,
    output_kind: str = "web_snapshot",
    expected_repo_id: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Load one pinned active revision without accepting absence or a mix.

    The pointer is resolved once. All payloads then come from that immutable
    directory while a cross-process shared lease prevents pruning. A deletion
    race immediately before lease acquisition retries from the active pointer;
    corruption of a stable revision remains a hard error.

    A regular directory is accepted only for one-release compatibility during
    migration. Its manifest is confirmed after the read and a concurrent
    exchange is retried rather than returned as a mixed bundle.
    """

    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    def wait_before_retry(attempt: int) -> None:
        if attempt + 1 >= max_attempts:
            return
        time.sleep(
            min(
                SNAPSHOT_READ_RETRY_BASE_S * (2**attempt),
                SNAPSHOT_READ_RETRY_MAX_S,
            )
        )

    last_transient: OSError | None = None
    for attempt in range(max_attempts):
        if out_dir.is_symlink():
            raw_target = os.readlink(out_dir)
            relative = Path(raw_target)
            expected_store_name = _revision_store_path(out_dir).name
            if (
                relative.is_absolute()
                or len(relative.parts) != 2
                or relative.parts[0] != expected_store_name
                or not SNAPSHOT_REVISION_HASH_RE.fullmatch(relative.name)
            ):
                raise ValueError(f"unrecognized snapshot revision pointer: {out_dir}")
            store = out_dir.parent / relative.parts[0]
            if store.is_symlink() or not store.is_dir():
                raise ValueError(f"unrecognized snapshot revision store: {store}")
            store_owner = read_output_owner(store)
            if (
                store_owner is None
                or store_owner.get("kind") != _revision_store_kind(output_kind)
                or (
                    expected_repo_id is not None
                    and store_owner.get("repo_id") != expected_repo_id
                )
            ):
                raise ValueError(f"unowned snapshot revision store: {store}")
            revision_dir = out_dir.parent / relative
            try:
                with _revision_lease(store, relative.name, exclusive=False) as acquired:
                    if not acquired:
                        raise OSError(
                            errno.ENOTSUP,
                            "cross-process snapshot leases are unavailable",
                        )
                    if not revision_dir.is_dir() or revision_dir.is_symlink():
                        raise FileNotFoundError(revision_dir)
                    payloads = _validate_owned_snapshot_revision(
                        revision_dir,
                        requested_revision=relative.name,
                        output_kind=output_kind,
                        repo_id=str(store_owner.get("repo_id") or ""),
                    )
                    manifest = payloads["manifest.json"]
                    repo_id = str((manifest.get("repo") or {}).get("repo_id") or "")
                    if repo_id != store_owner.get("repo_id"):
                        raise ValueError(
                            "snapshot revision ownership differs from its manifest"
                        )
                    return payloads
            except FileNotFoundError as exc:
                last_transient = exc
                wait_before_retry(attempt)
                continue
        elif out_dir.is_dir():
            try:
                before = (out_dir / "manifest.json").read_bytes()
                payloads = _load_snapshot_directory(out_dir)
                after = (out_dir / "manifest.json").read_bytes()
            except FileNotFoundError as exc:
                last_transient = exc
                wait_before_retry(attempt)
                continue
            except ValueError:
                # A one-time atomic directory-to-pointer exchange may occur
                # after the first manifest read. Retry that transition, but do
                # not mask corruption of a stable flat directory.
                if out_dir.is_symlink():
                    wait_before_retry(attempt)
                    continue
                try:
                    after = (out_dir / "manifest.json").read_bytes()
                except FileNotFoundError as exc:
                    last_transient = exc
                    wait_before_retry(attempt)
                    continue
                if before != after:
                    wait_before_retry(attempt)
                    continue
                raise
            if before == after:
                repo_id = str(
                    ((payloads["manifest.json"].get("repo") or {}).get("repo_id"))
                    or ""
                )
                if expected_repo_id is not None and repo_id != expected_repo_id:
                    raise ValueError(
                        f"snapshot repo mismatch: expected {expected_repo_id!r}, "
                        f"observed {repo_id!r}"
                    )
                if not output_is_owned(
                    out_dir,
                    kind=output_kind,
                    repo_id=repo_id,
                ):
                    raise ValueError(
                        "flat snapshot directory is unowned; only an exact owned "
                        "build or the strict writer-side legacy migration is supported"
                    )
                return payloads
        else:
            last_transient = FileNotFoundError(out_dir)
            wait_before_retry(attempt)
    raise RuntimeError(
        f"active snapshot changed during {max_attempts} read attempts: {out_dir}"
    ) from last_transient


def _install_snapshot_revision(
    store: Path,
    artifacts: dict[str, dict[str, Any]],
    *,
    output_kind: str,
    repo_id: str,
) -> tuple[Path, bool]:
    revision = _revision_hash(artifacts)
    recomputed = _bundle_hash_for_artifacts(artifacts)
    if recomputed != revision:
        raise ValueError(
            f"requested snapshot revision differs from artifacts: {revision} != {recomputed}"
    )
    target = store / revision
    if os.path.lexists(target):
        _validate_owned_snapshot_revision(
            target,
            requested_revision=revision,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        return target, False
    staging_dir = Path(tempfile.mkdtemp(prefix=".stage-", dir=store))
    try:
        write_output_owner(
            staging_dir,
            kind=f"{output_kind}_staging",
            repo_id=repo_id,
        )
        _write_snapshot_artifacts(staging_dir, artifacts)
        _validate_snapshot_directory(staging_dir)
        _fsync_snapshot_tree(staging_dir)
        # The final immutable revision owns the normal output kind; persist the
        # ownership change before publishing its directory entry.
        write_output_owner(staging_dir, kind=output_kind, repo_id=repo_id)
        _fsync_snapshot_tree(staging_dir)
        try:
            _atomic_install_directory_noreplace(staging_dir, target)
        except FileExistsError:
            # Concurrent publishers may install the same content-addressed
            # revision. Reuse it only after validating the exact owned bundle.
            _validate_owned_snapshot_revision(
                target,
                requested_revision=revision,
                output_kind=output_kind,
                repo_id=repo_id,
            )
            return target, False
        _fsync_directory(store)
        return target, True
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)


def _prune_snapshot_revisions(
    store: Path,
    *,
    active_revision: str,
    output_kind: str,
    repo_id: str,
    retention: int = SNAPSHOT_REVISION_RETENTION,
) -> tuple[list[Path], list[str], list[Path]]:
    """Prune old inactive revisions without racing pinned cross-process readers."""

    if retention < 2:
        raise ValueError("snapshot revision retention must keep at least two revisions")
    discovered = sorted(
        (
            path
            for path in store.iterdir()
            if path.is_dir()
            and not path.is_symlink()
            and SNAPSHOT_REVISION_HASH_RE.fullmatch(path.name)
        ),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    )
    warnings: list[str] = []
    revisions: list[Path] = []
    for path in discovered:
        try:
            _validate_owned_snapshot_revision(
                path,
                requested_revision=path.name,
                output_kind=output_kind,
                repo_id=repo_id,
            )
            revisions.append(path)
        except (OSError, ValueError):
            warnings.append(f"invalid_or_unowned_revision_preserved:{path.name}")

    # Retention ranks only exact owned+valid revisions. Ambiguous directories
    # are preserved for review but can never consume a backup slot and thereby
    # cause an older valid revision to be deleted indirectly.
    inactive = [path for path in revisions if path.name != active_revision]
    keep = {active_revision, *(path.name for path in inactive[: retention - 1])}
    removed: list[Path] = []
    recovery_paths: list[Path] = []
    for path in inactive[retention - 1 :]:
        if path.name in keep:
            continue
        deleted = False
        quarantine: Path | None = None
        delete_started = False
        try:
            with _revision_lease(store, path.name, exclusive=True) as acquired:
                if not acquired:
                    warnings.append(f"revision_leased_preserved:{path.name}")
                    continue
                # Pin the directory entry before validation. A non-cooperating
                # writer may still replace the pathname while the advisory
                # lease is held; the post-rename inode check catches that race.
                expected_identity = _path_entry_identity(path)
                _validate_owned_snapshot_revision(
                    path,
                    requested_revision=path.name,
                    output_kind=output_kind,
                    repo_id=repo_id,
                )
                quarantine = store / (
                    f".prune-{path.name}-{secrets.token_hex(16)}"
                )
                _atomic_install_directory_noreplace(path, quarantine)
                _fsync_directory(store)
                if _path_entry_identity(quarantine) != expected_identity:
                    raise ValueError(
                        "snapshot revision pathname changed before quarantine"
                    )
                _validate_owned_snapshot_revision(
                    quarantine,
                    requested_revision=path.name,
                    output_kind=output_kind,
                    repo_id=repo_id,
                    require_directory_name=False,
                )
                if _path_entry_identity(quarantine) != expected_identity:
                    raise ValueError(
                        "snapshot revision quarantine identity changed during validation"
                    )
                fingerprint = _snapshot_tree_fingerprint(quarantine)
                if _path_entry_identity(quarantine) != expected_identity:
                    raise ValueError(
                        "snapshot revision quarantine changed during fingerprint"
                    )
                delete_started = True
                _delete_snapshot_tree_descriptor_pinned(
                    store,
                    quarantine,
                    expected_identity=expected_identity,
                    fingerprint=fingerprint,
                )
                quarantine = None
                deleted = True
                removed.append(path)
        except SnapshotDescriptorDeletionBlockedError as exc:
            recovery_paths.extend(exc.recovery_paths)
            warnings.append(
                f"revision_prune_descriptor_race_preserved:{path.name}"
            )
            warnings.append(f"invalid_or_unowned_revision_preserved:{path.name}")
        except (OSError, SnapshotPublicationBlockedError, ValueError):
            if quarantine is not None and os.path.lexists(quarantine):
                if delete_started:
                    warnings.append(
                        f"revision_prune_quarantine_pending:{quarantine.name}"
                    )
                else:
                    try:
                        _atomic_install_directory_noreplace(quarantine, path)
                    except FileExistsError:
                        warnings.append(
                            "revision_prune_race_quarantine_preserved:"
                            f"{quarantine.name}"
                        )
                    except OSError:
                        warnings.append(
                            "revision_prune_quarantine_restore_failed:"
                            f"{quarantine.name}"
                        )
                    else:
                        quarantine = None
                        try:
                            _fsync_directory(store)
                        except OSError:
                            warnings.append(
                                "revision_prune_restore_directory_fsync_failed:"
                                f"{path.name}"
                            )
            code = (
                "revision_deleted_directory_fsync_failed"
                if deleted
                else "invalid_or_unowned_revision_preserved"
            )
            warnings.append(f"{code}:{path.name}")
    return removed, warnings, recovery_paths


def promote_snapshot_artifacts(
    root: Path,
    out_dir: Path,
    artifacts: dict[str, dict[str, Any]],
    *,
    output_kind: str = "web_snapshot",
    force_unowned_output: bool = False,
) -> dict[str, Path]:
    """Promote one flat build artifact with rollback.

    This compatibility path is for committed demo fixtures and portable deploy
    bundles that are activated by their build/hosting layer. Live filesystem
    readers must use :func:`promote_snapshot_revisioned` instead.
    """

    errors = snapshot_contract_errors(artifacts)
    if errors:
        raise ValueError("invalid snapshot contract: " + "; ".join(errors))
    repo_id = str(
        ((artifacts.get("manifest.json") or {}).get("repo") or {}).get("repo_id")
        or "unknown"
    )
    out_dir = validate_managed_output_target(
        root,
        out_dir,
        kind=output_kind,
        repo_id=repo_id,
        force_unowned=force_unowned_output,
        recognize_legacy=lambda target: _is_legacy_snapshot_directory(
            target, expected_repo_id=repo_id
        ),
    )
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(
        tempfile.mkdtemp(prefix=f".{out_dir.name}.stage-", dir=out_dir.parent)
    )
    backup_dir = staging_dir.with_name(f"{staging_dir.name}.previous")
    old_moved = False
    try:
        _write_snapshot_artifacts(staging_dir, artifacts)
        write_output_owner(staging_dir, kind=output_kind, repo_id=repo_id)
        _validate_snapshot_directory(staging_dir)
        if out_dir.exists():
            os.replace(out_dir, backup_dir)
            old_moved = True
        try:
            os.replace(staging_dir, out_dir)
        except BaseException as promote_error:
            if old_moved and backup_dir.exists():
                if out_dir.exists():
                    shutil.rmtree(out_dir)
                try:
                    os.replace(backup_dir, out_dir)
                    old_moved = False
                except BaseException as rollback_error:
                    raise RuntimeError(
                        f"snapshot promotion and rollback failed; previous snapshot remains at {backup_dir}"
                    ) from rollback_error
            raise promote_error
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
            old_moved = False
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        # Never delete a backup after an unsuccessful rollback. Its unique
        # sibling path is the final recovery surface reported by the exception.
        if backup_dir.exists() and not old_moved:
            shutil.rmtree(backup_dir)
    return {
        name: out_dir / name
        for name in (artifacts.get("manifest.json") or {}).get("files") or []
    }


def _archive_exchanged_snapshot_directory(
    previous_dir: Path,
    store: Path,
    *,
    output_kind: str,
    repo_id: str,
) -> None:
    """Archive a valid exchanged snapshot; preserve any unrecognized tree."""

    entries = [
        path
        for path in previous_dir.iterdir()
        if path.name != OUTPUT_OWNER_FILENAME
    ]
    if not entries:
        shutil.rmtree(previous_dir)
        _fsync_directory(previous_dir.parent)
        return
    payloads = _load_snapshot_directory(previous_dir)
    manifest = payloads["manifest.json"]
    revision = str(manifest.get("bundle_hash") or "")
    manifest_repo_id = str((manifest.get("repo") or {}).get("repo_id") or "")
    if (
        not SNAPSHOT_REVISION_HASH_RE.fullmatch(revision)
        or manifest_repo_id != repo_id
        or _bundle_hash_for_artifacts(payloads) != revision
    ):
        raise ValueError("previous snapshot recovery does not match this repository")
    write_output_owner(previous_dir, kind=output_kind, repo_id=repo_id)
    _fsync_file(previous_dir / OUTPUT_OWNER_FILENAME)
    _fsync_directory(previous_dir)
    archived = store / revision
    if os.path.lexists(archived):
        _validate_owned_snapshot_revision(
            archived,
            requested_revision=revision,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        shutil.rmtree(previous_dir)
        _fsync_directory_set(previous_dir.parent, store)
        return
    try:
        _atomic_install_directory_noreplace(previous_dir, archived)
    except FileExistsError:
        # A concurrent or adversarial target is never replaced. Only an exact
        # owned revision permits the exchanged duplicate to be discarded.
        _validate_owned_snapshot_revision(
            archived,
            requested_revision=revision,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        shutil.rmtree(previous_dir)
    _fsync_directory_set(previous_dir.parent, store)


def _activation_cleanup_path(activation_dir: Path) -> Path:
    if ".cleanup-" in activation_dir.name:
        return activation_dir
    if ".activate-" not in activation_dir.name:
        raise ValueError(
            f"unrecognized snapshot activation container: {activation_dir}"
        )
    return activation_dir.with_name(
        activation_dir.name.replace(".activate-", ".cleanup-", 1)
    )


def _activation_name_for_cleanup(cleanup_dir: Path) -> str:
    if ".cleanup-" not in cleanup_dir.name:
        raise ValueError(f"unrecognized snapshot cleanup path: {cleanup_dir}")
    return cleanup_dir.name.replace(".cleanup-", ".activate-", 1)


def _cleanup_receipt_path(
    store: Path,
    cleanup_dir: Path,
    *,
    output_kind: str,
    repo_id: str,
) -> Path:
    basis = "\0".join((repo_id, output_kind, cleanup_dir.name)).encode("utf-8")
    return _cleanup_receipts_path(store) / f"{hashlib.sha256(basis).hexdigest()}.json"


def _cleanup_receipt_binding(
    *,
    receipt_id: str,
    activation_name: str,
    cleanup_name: str,
    cleanup_dev: str,
    cleanup_ino: str,
    cleanup_type: str,
    output_kind: str,
    repo_id: str,
) -> str:
    basis = "\0".join(
        (
            SNAPSHOT_CLEANUP_RECEIPT_SCHEMA_VERSION,
            receipt_id,
            activation_name,
            cleanup_name,
            cleanup_dev,
            cleanup_ino,
            cleanup_type,
            output_kind,
            repo_id,
        )
    ).encode("utf-8")
    return hashlib.sha256(basis).hexdigest()


def _expected_cleanup_receipt_static(
    cleanup_dir: Path,
    *,
    cleanup_identity: tuple[int, int, int, str | None],
    output_kind: str,
    repo_id: str,
) -> dict[str, str]:
    return {
        "schema_version": SNAPSHOT_CLEANUP_RECEIPT_SCHEMA_VERSION,
        "kind": f"{output_kind}_activation_cleanup",
        "repo_id": repo_id,
        "activation_name": _activation_name_for_cleanup(cleanup_dir),
        "cleanup_name": cleanup_dir.name,
        "cleanup_dev": str(cleanup_identity[0]),
        "cleanup_ino": str(cleanup_identity[1]),
        "cleanup_type": str(cleanup_identity[2]),
    }


def _cleanup_bound_payload(
    cleanup_dir: Path,
    *,
    receipt_id: str,
    cleanup_identity: tuple[int, int, int, str | None],
    output_kind: str,
    repo_id: str,
) -> dict[str, str]:
    if not SNAPSHOT_CLEANUP_RECEIPT_ID_RE.fullmatch(receipt_id):
        raise ValueError("snapshot cleanup identity is not high entropy")
    if cleanup_identity[2] != stat.S_IFDIR or cleanup_identity[3] is not None:
        raise ValueError("snapshot cleanup identity is not a real directory")
    payload = _expected_cleanup_receipt_static(
        cleanup_dir,
        cleanup_identity=cleanup_identity,
        output_kind=output_kind,
        repo_id=repo_id,
    )
    payload["receipt_id"] = receipt_id
    payload["binding_sha256"] = _cleanup_receipt_binding(
        receipt_id=receipt_id,
        activation_name=payload["activation_name"],
        cleanup_name=payload["cleanup_name"],
        cleanup_dev=payload["cleanup_dev"],
        cleanup_ino=payload["cleanup_ino"],
        cleanup_type=payload["cleanup_type"],
        output_kind=output_kind,
        repo_id=repo_id,
    )
    return payload


def _read_cleanup_intent(
    container: Path,
    cleanup_dir: Path,
    *,
    output_kind: str,
    repo_id: str,
) -> dict[str, str] | None:
    try:
        payload = json.loads(
            _read_snapshot_file_bytes(
                container,
                SNAPSHOT_CLEANUP_INTENT_FILENAME,
            ).decode("utf-8")
        )
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    normalized = {str(key): str(value) for key, value in payload.items()}
    receipt_id = normalized.get("receipt_id", "")
    try:
        cleanup_identity = _path_entry_identity(container)
        expected = _cleanup_bound_payload(
            cleanup_dir,
            receipt_id=receipt_id,
            cleanup_identity=cleanup_identity,
            output_kind=output_kind,
            repo_id=repo_id,
        )
    except (FileNotFoundError, SnapshotPublicationBlockedError, ValueError):
        return None
    return normalized if normalized == expected else None


def _ensure_cleanup_intent(
    container: Path,
    cleanup_dir: Path,
    *,
    output_kind: str,
    repo_id: str,
) -> dict[str, str]:
    intent = container / SNAPSHOT_CLEANUP_INTENT_FILENAME
    if os.path.lexists(intent):
        payload = _read_cleanup_intent(
            container,
            cleanup_dir,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        if payload is None:
            raise ValueError(f"snapshot cleanup intent is unsafe: {intent}")
        return payload

    cleanup_identity = _path_entry_identity(container)
    payload = _cleanup_bound_payload(
        cleanup_dir,
        receipt_id=secrets.token_hex(16),
        cleanup_identity=cleanup_identity,
        output_kind=output_kind,
        repo_id=repo_id,
    )
    descriptor, temporary_name = tempfile.mkstemp(prefix=".intent-", dir=container)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(
                (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
            )
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, intent, follow_symlinks=False)
        except FileExistsError:
            observed = _read_cleanup_intent(
                container,
                cleanup_dir,
                output_kind=output_kind,
                repo_id=repo_id,
            )
            if observed is None:
                raise ValueError(f"snapshot cleanup intent is unsafe: {intent}")
            payload = observed
        _fsync_file(intent)
        _fsync_directory(container)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        _fsync_directory(container)
    return payload


def _validate_cleanup_receipts_store(
    store: Path,
    *,
    output_kind: str,
    repo_id: str,
) -> Path:
    receipts = _cleanup_receipts_path(store)
    if receipts.is_symlink() or not receipts.is_dir():
        raise ValueError(f"snapshot cleanup receipts directory is unsafe: {receipts}")
    try:
        owner = json.loads(
            _read_snapshot_file_bytes(receipts, OUTPUT_OWNER_FILENAME).decode("utf-8")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"snapshot cleanup receipts are unowned: {receipts}") from exc
    if owner != {
        "schema_version": OUTPUT_OWNER_SCHEMA_VERSION,
        "kind": _cleanup_receipts_kind(output_kind),
        "repo_id": repo_id,
    }:
        raise ValueError(f"snapshot cleanup receipts are unowned: {receipts}")
    return receipts


def _read_cleanup_receipt(
    store: Path,
    cleanup_dir: Path,
    *,
    output_kind: str,
    repo_id: str,
    require_directory_match: bool = True,
) -> dict[str, str] | None:
    try:
        receipts = _validate_cleanup_receipts_store(
            store,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        receipt = _cleanup_receipt_path(
            store,
            cleanup_dir,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        payload = json.loads(
            _read_snapshot_file_bytes(receipts, receipt.name).decode("utf-8")
        )
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    normalized = {str(key): str(value) for key, value in payload.items()}
    receipt_id = normalized.get("receipt_id", "")
    if not SNAPSHOT_CLEANUP_RECEIPT_ID_RE.fullmatch(receipt_id):
        return None
    try:
        bound_identity = (
            int(normalized["cleanup_dev"]),
            int(normalized["cleanup_ino"]),
            int(normalized["cleanup_type"]),
            None,
        )
        expected = _cleanup_bound_payload(
            cleanup_dir,
            receipt_id=receipt_id,
            cleanup_identity=bound_identity,
            output_kind=output_kind,
            repo_id=repo_id,
        )
    except (KeyError, TypeError, ValueError):
        return None
    if normalized != expected:
        return None
    if require_directory_match:
        try:
            observed_identity = _path_entry_identity(cleanup_dir)
        except (FileNotFoundError, SnapshotPublicationBlockedError):
            return None
        if observed_identity[:3] != bound_identity[:3]:
            return None
    return normalized


def _ensure_cleanup_receipt(
    store: Path,
    cleanup_dir: Path,
    *,
    output_kind: str,
    repo_id: str,
    receipt_id: str | None = None,
) -> Path:
    receipts = _validate_cleanup_receipts_store(
        store,
        output_kind=output_kind,
        repo_id=repo_id,
    )
    receipt = _cleanup_receipt_path(
        store,
        cleanup_dir,
        output_kind=output_kind,
        repo_id=repo_id,
    )
    if os.path.lexists(receipt):
        observed = _read_cleanup_receipt(
            store,
            cleanup_dir,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        if observed is None or (
            receipt_id is not None and observed["receipt_id"] != receipt_id
        ):
            raise ValueError(f"snapshot cleanup receipt is unsafe: {receipt}")
        return receipt

    receipt_id = receipt_id or secrets.token_hex(16)
    cleanup_identity = _path_entry_identity(cleanup_dir)
    payload = _cleanup_bound_payload(
        cleanup_dir,
        receipt_id=receipt_id,
        cleanup_identity=cleanup_identity,
        output_kind=output_kind,
        repo_id=repo_id,
    )
    descriptor, temporary_name = tempfile.mkstemp(prefix=".receipt-", dir=receipts)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(
                (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
            )
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, receipt, follow_symlinks=False)
        except FileExistsError:
            if _read_cleanup_receipt(
                store,
                cleanup_dir,
                output_kind=output_kind,
                repo_id=repo_id,
            ) is None:
                raise ValueError(f"snapshot cleanup receipt is unsafe: {receipt}")
        _fsync_file(receipt)
        _fsync_directory(receipts)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        _fsync_directory(receipts)
    return receipt


def _remove_cleanup_receipt(
    store: Path,
    cleanup_dir: Path,
    *,
    output_kind: str,
    repo_id: str,
) -> None:
    receipt = _cleanup_receipt_path(
        store,
        cleanup_dir,
        output_kind=output_kind,
        repo_id=repo_id,
    )
    if _read_cleanup_receipt(
        store,
        cleanup_dir,
        output_kind=output_kind,
        repo_id=repo_id,
        require_directory_match=False,
    ) is None:
        raise ValueError(f"snapshot cleanup receipt is missing or invalid: {receipt}")
    receipt.unlink()
    _fsync_directory(receipt.parent)


def _cleanup_receipt_identity(payload: dict[str, str]) -> tuple[int, int, int]:
    try:
        identity = (
            int(payload["cleanup_dev"]),
            int(payload["cleanup_ino"]),
            int(payload["cleanup_type"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("snapshot cleanup receipt identity is invalid") from exc
    if identity[2] != stat.S_IFDIR:
        raise ValueError("snapshot cleanup receipt is not bound to a directory")
    return identity


def _open_cleanup_directory_pinned(
    cleanup_dir: Path,
    receipt_payload: dict[str, str],
) -> tuple[int, int, tuple[int, int, int]]:
    expected_identity = _cleanup_receipt_identity(receipt_payload)
    parent_fd = os.open(cleanup_dir.parent, _directory_open_flags())
    cleanup_fd: int | None = None
    try:
        cleanup_fd = os.open(
            cleanup_dir.name,
            _directory_open_flags(),
            dir_fd=parent_fd,
        )
        pinned_identity = _stat_identity(os.fstat(cleanup_fd))
        parent_identity = _descriptor_entry_identity(parent_fd, cleanup_dir.name)
        if not (
            pinned_identity == parent_identity == expected_identity
        ):
            raise SnapshotCleanupBlockedError(
                "snapshot cleanup inode differs from its durable receipt",
                recovery_path=cleanup_dir,
            )
        return parent_fd, cleanup_fd, pinned_identity
    except BaseException:
        if cleanup_fd is not None:
            os.close(cleanup_fd)
        os.close(parent_fd)
        raise


def _require_pinned_cleanup_parent_entry(
    parent_fd: int,
    cleanup_fd: int,
    cleanup_dir: Path,
    *,
    expected_identity: tuple[int, int, int],
) -> None:
    try:
        parent_identity = _descriptor_entry_identity(parent_fd, cleanup_dir.name)
    except OSError as exc:
        raise SnapshotCleanupBlockedError(
            "snapshot cleanup pathname changed while its inode was pinned",
            recovery_path=cleanup_dir,
        ) from exc
    if not (
        parent_identity == _stat_identity(os.fstat(cleanup_fd)) == expected_identity
    ):
        raise SnapshotCleanupBlockedError(
            "snapshot cleanup pathname no longer names the receipted inode",
            recovery_path=cleanup_dir,
        )


def _unlink_regular_entry_at(directory_fd: int, name: str) -> None:
    entry_stat = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    if not stat.S_ISREG(entry_stat.st_mode):
        raise ValueError(f"snapshot cleanup entry is not regular: {name}")
    os.unlink(name, dir_fd=directory_fd)
    os.fsync(directory_fd)


def _remove_receipted_cleanup_directory_pinned(
    cleanup_dir: Path,
    receipt_payload: dict[str, str],
    *,
    remove_owner_marker: bool,
    remove_intent: bool,
) -> None:
    """Remove only the cleanup inode cryptographically bound by the receipt."""

    parent_fd, cleanup_fd, expected_identity = _open_cleanup_directory_pinned(
        cleanup_dir,
        receipt_payload,
    )
    try:
        expected_entries: set[str] = set()
        if remove_owner_marker:
            expected_entries.add(OUTPUT_OWNER_FILENAME)
        if remove_intent:
            expected_entries.add(SNAPSHOT_CLEANUP_INTENT_FILENAME)
        observed_entries = set(os.listdir(cleanup_fd))
        if observed_entries != expected_entries:
            raise SnapshotCleanupBlockedError(
                "snapshot cleanup inventory changed after receipt creation",
                recovery_path=cleanup_dir,
            )
        _require_pinned_cleanup_parent_entry(
            parent_fd,
            cleanup_fd,
            cleanup_dir,
            expected_identity=expected_identity,
        )
        if remove_intent:
            _unlink_regular_entry_at(
                cleanup_fd,
                SNAPSHOT_CLEANUP_INTENT_FILENAME,
            )
        _require_pinned_cleanup_parent_entry(
            parent_fd,
            cleanup_fd,
            cleanup_dir,
            expected_identity=expected_identity,
        )
        if remove_owner_marker:
            _unlink_regular_entry_at(cleanup_fd, OUTPUT_OWNER_FILENAME)
        if os.listdir(cleanup_fd):
            raise SnapshotCleanupBlockedError(
                "snapshot cleanup gained entries before final rmdir",
                recovery_path=cleanup_dir,
            )
        os.fsync(cleanup_fd)
        _require_pinned_cleanup_parent_entry(
            parent_fd,
            cleanup_fd,
            cleanup_dir,
            expected_identity=expected_identity,
        )
        # POSIX exposes no inode-conditional rmdir. This dirfd-relative call is
        # immediately preceded by the identity comparison above, leaving only
        # the unavoidable final compare-to-rmdir micro-window.
        os.rmdir(cleanup_dir.name, dir_fd=parent_fd)
        os.fsync(parent_fd)
    finally:
        os.close(cleanup_fd)
        os.close(parent_fd)


def _restore_unattested_cleanup_container(
    cleanup_dir: Path,
    activation_dir: Path,
    *,
    observed_cleanup_identity: tuple[int, int, int, str | None],
) -> None:
    """Restore an untrusted raced entry without replacing either pathname."""

    try:
        current_identity = _path_entry_identity(cleanup_dir)
    except (FileNotFoundError, SnapshotPublicationBlockedError) as exc:
        raise SnapshotCleanupBlockedError(
            "unattested snapshot cleanup changed again and remains preserved at "
            f"{cleanup_dir}",
            recovery_path=cleanup_dir,
        ) from exc
    if current_identity != observed_cleanup_identity:
        raise SnapshotCleanupBlockedError(
            "unattested snapshot cleanup identity changed again and remains "
            f"preserved at {cleanup_dir}",
            recovery_path=cleanup_dir,
        )
    try:
        _atomic_install_directory_noreplace(cleanup_dir, activation_dir)
    except FileExistsError as exc:
        raise SnapshotCleanupBlockedError(
            "unattested snapshot cleanup could not return to an occupied "
            f"activation pathname and remains preserved at {cleanup_dir}",
            recovery_path=cleanup_dir,
        ) from exc
    except OSError as exc:
        raise SnapshotCleanupBlockedError(
            f"unattested snapshot cleanup remains preserved at {cleanup_dir}",
            recovery_path=cleanup_dir,
        ) from exc
    try:
        _fsync_directory(cleanup_dir.parent)
    except OSError as exc:
        raise SnapshotCleanupBlockedError(
            "unattested snapshot cleanup was restored but its parent fsync failed: "
            f"{activation_dir}",
            recovery_path=activation_dir,
        ) from exc
    raise SnapshotCleanupBlockedError(
        "unattested snapshot cleanup was restored without clobbering to "
        f"{activation_dir}",
        recovery_path=activation_dir,
    )


def _remove_owned_activation_container(
    activation_dir: Path,
    store: Path,
    *,
    output_kind: str,
    repo_id: str,
) -> None:
    cleanup_dir = _activation_cleanup_path(activation_dir)
    if not output_is_owned(
        activation_dir,
        kind=f"{output_kind}_activation",
        repo_id=repo_id,
    ):
        raise ValueError(f"snapshot activation container is not owned: {activation_dir}")
    marker = activation_dir / OUTPUT_OWNER_FILENAME
    intent = activation_dir / SNAPSHOT_CLEANUP_INTENT_FILENAME
    entries = set(activation_dir.iterdir())
    if marker not in entries or not entries <= {marker, intent}:
        raise ValueError(
            f"snapshot activation container is not empty: {activation_dir}"
        )

    intent_payload = (
        _read_cleanup_intent(
            activation_dir,
            cleanup_dir,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        if intent in entries
        else None
    )
    if intent in entries and intent_payload is None:
        raise ValueError(f"snapshot cleanup intent is unsafe: {intent}")

    if cleanup_dir != activation_dir:
        if intent_payload is None:
            intent_payload = _ensure_cleanup_intent(
                activation_dir,
                cleanup_dir,
                output_kind=output_kind,
                repo_id=repo_id,
            )
        try:
            activation_identity = _path_entry_identity(activation_dir)
        except (FileNotFoundError, SnapshotPublicationBlockedError) as exc:
            raise ValueError(
                f"snapshot activation changed before cleanup rename: {activation_dir}"
            ) from exc
        try:
            _atomic_install_directory_noreplace(activation_dir, cleanup_dir)
        except FileExistsError as exc:
            raise ValueError(
                f"snapshot cleanup tombstone already exists: {cleanup_dir}"
            ) from exc
        _fsync_directory(cleanup_dir.parent)
        marker = cleanup_dir / OUTPUT_OWNER_FILENAME
        intent = cleanup_dir / SNAPSHOT_CLEANUP_INTENT_FILENAME
        try:
            cleanup_identity = _path_entry_identity(cleanup_dir)
        except (FileNotFoundError, SnapshotPublicationBlockedError) as exc:
            raise ValueError(
                f"snapshot cleanup changed after rename: {cleanup_dir}"
            ) from exc
        reopened_intent = _read_cleanup_intent(
            cleanup_dir,
            cleanup_dir,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        if (
            cleanup_identity != activation_identity
            or not output_is_owned(
                cleanup_dir,
                kind=f"{output_kind}_activation",
                repo_id=repo_id,
            )
            or set(cleanup_dir.iterdir()) != {marker, intent}
            or reopened_intent != intent_payload
        ):
            _restore_unattested_cleanup_container(
                cleanup_dir,
                activation_dir,
                observed_cleanup_identity=cleanup_identity,
            )
        intent_payload = reopened_intent
    else:
        receipt_payload = _read_cleanup_receipt(
            store,
            cleanup_dir,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        if intent_payload is None and receipt_payload is None:
            raise ValueError(
                f"unreceipted snapshot cleanup tombstone is ambiguous: {cleanup_dir}"
            )

    if intent_payload is not None:
        _ensure_cleanup_receipt(
            store,
            cleanup_dir,
            output_kind=output_kind,
            repo_id=repo_id,
            receipt_id=intent_payload["receipt_id"],
        )
    receipt_payload = _read_cleanup_receipt(
        store,
        cleanup_dir,
        output_kind=output_kind,
        repo_id=repo_id,
    )
    if receipt_payload is None:
        raise SnapshotCleanupBlockedError(
            "snapshot cleanup inode does not match its receipt before removal",
            recovery_path=cleanup_dir,
        )
    _remove_receipted_cleanup_directory_pinned(
        cleanup_dir,
        receipt_payload,
        remove_owner_marker=True,
        remove_intent=intent_payload is not None,
    )
    _remove_cleanup_receipt(
        store,
        cleanup_dir,
        output_kind=output_kind,
        repo_id=repo_id,
    )


def _reconcile_snapshot_leftovers(
    root: Path,
    out_dir: Path,
    store: Path,
    *,
    output_kind: str,
    repo_id: str,
) -> tuple[list[str], list[Path]]:
    """Recover publisher-owned crash leftovers; preserve everything ambiguous."""

    warnings: list[str] = []
    recovery_paths: list[Path] = []
    for activation_dir in sorted(
        out_dir.parent.glob(f".{out_dir.name}.activate-*")
    ):
        if activation_dir.is_symlink() or not activation_dir.is_dir():
            warnings.append(f"unowned_activation_leftover_preserved:{activation_dir.name}")
            continue
        try:
            contained_output_path(root, activation_dir)
        except ValueError:
            warnings.append(f"escaped_activation_leftover_preserved:{activation_dir.name}")
            continue
        if not output_is_owned(
            activation_dir,
            kind=f"{output_kind}_activation",
            repo_id=repo_id,
        ):
            warnings.append(f"unowned_activation_leftover_preserved:{activation_dir.name}")
            continue
        entries = [
            path
            for path in activation_dir.iterdir()
            if path.name != OUTPUT_OWNER_FILENAME
        ]
        cleanup_dir = _activation_cleanup_path(activation_dir)
        intent = activation_dir / SNAPSHOT_CLEANUP_INTENT_FILENAME
        recoverable_cleanup = not entries or (
            set(entries) == {intent}
            and _read_cleanup_intent(
                activation_dir,
                cleanup_dir,
                output_kind=output_kind,
                repo_id=repo_id,
            )
            is not None
        )
        if recoverable_cleanup:
            try:
                _remove_owned_activation_container(
                    activation_dir,
                    store,
                    output_kind=output_kind,
                    repo_id=repo_id,
                )
            except (OSError, ValueError) as cleanup_error:
                explicit_recovery = getattr(cleanup_error, "recovery_path", None)
                candidate = (
                    Path(explicit_recovery)
                    if explicit_recovery is not None
                    and os.path.lexists(explicit_recovery)
                    else activation_dir
                )
                if not os.path.lexists(candidate):
                    candidate = cleanup_dir
                warnings.append(f"activation_cleanup_pending:{candidate.name}")
                if os.path.lexists(candidate):
                    recovery_paths.append(candidate)
            continue
        previous = activation_dir / "active"
        if entries != [previous] or previous.is_symlink() or not previous.is_dir():
            warnings.append(f"ambiguous_activation_leftover_preserved:{activation_dir.name}")
            recovery_paths.append(activation_dir)
            continue
        try:
            _archive_exchanged_snapshot_directory(
                previous,
                store,
                output_kind=output_kind,
                repo_id=repo_id,
            )
            _remove_owned_activation_container(
                activation_dir,
                store,
                output_kind=output_kind,
                repo_id=repo_id,
            )
        except (OSError, ValueError) as cleanup_error:
            warnings.append(f"activation_recovery_pending:{activation_dir.name}")
            explicit_recovery = getattr(cleanup_error, "recovery_path", None)
            candidate = (
                Path(explicit_recovery)
                if explicit_recovery is not None
                and os.path.lexists(explicit_recovery)
                else previous
            )
            if not os.path.lexists(candidate):
                candidate = _activation_cleanup_path(activation_dir)
            if not os.path.lexists(candidate):
                candidate = activation_dir
            if os.path.lexists(candidate):
                recovery_paths.append(candidate)

    for cleanup_dir in sorted(out_dir.parent.glob(f".{out_dir.name}.cleanup-*")):
        if cleanup_dir.is_symlink() or not cleanup_dir.is_dir():
            warnings.append(f"unsafe_cleanup_tombstone_preserved:{cleanup_dir.name}")
            continue
        receipt_payload = _read_cleanup_receipt(
            store,
            cleanup_dir,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        if receipt_payload is None:
            entries = set(cleanup_dir.iterdir())
            marker = cleanup_dir / OUTPUT_OWNER_FILENAME
            intent = cleanup_dir / SNAPSHOT_CLEANUP_INTENT_FILENAME
            intent_payload = (
                _read_cleanup_intent(
                    cleanup_dir,
                    cleanup_dir,
                    output_kind=output_kind,
                    repo_id=repo_id,
                )
                if intent in entries
                else None
            )
            if (
                entries == {marker, intent}
                and intent_payload is not None
                and output_is_owned(
                    cleanup_dir,
                    kind=f"{output_kind}_activation",
                    repo_id=repo_id,
                )
            ):
                try:
                    _remove_owned_activation_container(
                        cleanup_dir,
                        store,
                        output_kind=output_kind,
                        repo_id=repo_id,
                    )
                except (OSError, ValueError):
                    warnings.append(
                        f"owned_cleanup_tombstone_pending:{cleanup_dir.name}"
                    )
                    recovery_paths.append(cleanup_dir)
                continue
            warnings.append(
                f"unreceipted_cleanup_tombstone_preserved:{cleanup_dir.name}"
            )
            recovery_paths.append(cleanup_dir)
            continue
        entries = set(cleanup_dir.iterdir())
        if not entries:
            try:
                _remove_receipted_cleanup_directory_pinned(
                    cleanup_dir,
                    receipt_payload,
                    remove_owner_marker=False,
                    remove_intent=False,
                )
                _remove_cleanup_receipt(
                    store,
                    cleanup_dir,
                    output_kind=output_kind,
                    repo_id=repo_id,
                )
            except (OSError, ValueError) as cleanup_error:
                warnings.append(f"empty_cleanup_tombstone_pending:{cleanup_dir.name}")
                receipt = _cleanup_receipt_path(
                    store,
                    cleanup_dir,
                    output_kind=output_kind,
                    repo_id=repo_id,
                )
                explicit_recovery = getattr(cleanup_error, "recovery_path", None)
                candidate = (
                    Path(explicit_recovery)
                    if explicit_recovery is not None
                    and os.path.lexists(explicit_recovery)
                    else (cleanup_dir if cleanup_dir.exists() else receipt)
                )
                if os.path.lexists(candidate):
                    recovery_paths.append(candidate)
            continue
        marker = cleanup_dir / OUTPUT_OWNER_FILENAME
        intent = cleanup_dir / SNAPSHOT_CLEANUP_INTENT_FILENAME
        intent_payload = (
            _read_cleanup_intent(
                cleanup_dir,
                cleanup_dir,
                output_kind=output_kind,
                repo_id=repo_id,
            )
            if intent in entries
            else None
        )
        receipt_matches_intent = intent_payload is None or (
            intent_payload["receipt_id"] == receipt_payload["receipt_id"]
        )
        if (
            entries in ({marker}, {marker, intent})
            and receipt_matches_intent
            and (intent not in entries or intent_payload is not None)
            and output_is_owned(
                cleanup_dir,
                kind=f"{output_kind}_activation",
                repo_id=repo_id,
            )
        ):
            try:
                _remove_owned_activation_container(
                    cleanup_dir,
                    store,
                    output_kind=output_kind,
                    repo_id=repo_id,
                )
            except (OSError, ValueError):
                warnings.append(f"owned_cleanup_tombstone_pending:{cleanup_dir.name}")
                recovery_paths.append(cleanup_dir)
            continue
        warnings.append(f"ambiguous_cleanup_tombstone_preserved:{cleanup_dir.name}")
        recovery_paths.append(cleanup_dir)

    receipts = _validate_cleanup_receipts_store(
        store,
        output_kind=output_kind,
        repo_id=repo_id,
    )
    for receipt in sorted(receipts.glob("*.json")):
        if receipt.name == OUTPUT_OWNER_FILENAME:
            continue
        try:
            raw_payload = json.loads(
                _read_snapshot_file_bytes(receipts, receipt.name).decode("utf-8")
            )
            cleanup_name = str(raw_payload.get("cleanup_name") or "")
            if (
                Path(cleanup_name).name != cleanup_name
                or not cleanup_name.startswith(f".{out_dir.name}.cleanup-")
            ):
                raise ValueError("cleanup receipt names an unsafe path")
            cleanup_dir = out_dir.parent / cleanup_name
            expected_receipt = _cleanup_receipt_path(
                store,
                cleanup_dir,
                output_kind=output_kind,
                repo_id=repo_id,
            )
            payload = _read_cleanup_receipt(
                store,
                cleanup_dir,
                output_kind=output_kind,
                repo_id=repo_id,
                require_directory_match=False,
            )
        except (OSError, AttributeError, ValueError, json.JSONDecodeError):
            payload = None
            expected_receipt = receipt
            cleanup_dir = out_dir.parent
        if payload is None or receipt != expected_receipt:
            warnings.append(f"invalid_cleanup_receipt_preserved:{receipt.name}")
            recovery_paths.append(receipt)
            continue
        if os.path.lexists(cleanup_dir) and _read_cleanup_receipt(
            store,
            cleanup_dir,
            output_kind=output_kind,
            repo_id=repo_id,
        ) is None:
            warnings.append(
                f"cleanup_receipt_inode_mismatch_preserved:{cleanup_dir.name}"
            )
            recovery_paths.extend((cleanup_dir, receipt))
            continue
        activation_dir = out_dir.parent / payload["activation_name"]
        if not os.path.lexists(cleanup_dir) and not os.path.lexists(activation_dir):
            try:
                receipt.unlink()
                _fsync_directory(receipts)
            except OSError:
                warnings.append(f"orphan_cleanup_receipt_pending:{receipt.name}")
                recovery_paths.append(receipt)

    for staging_dir in sorted(store.glob(".stage-*")):
        if staging_dir.is_symlink() or not staging_dir.is_dir():
            warnings.append(f"unowned_staging_leftover_preserved:{staging_dir.name}")
            continue
        if not output_is_owned(
            staging_dir,
            kind=f"{output_kind}_staging",
            repo_id=repo_id,
        ):
            warnings.append(f"unowned_staging_leftover_preserved:{staging_dir.name}")
            continue
        try:
            shutil.rmtree(staging_dir)
            _fsync_directory(store)
        except OSError:
            warnings.append(f"owned_staging_cleanup_failed:{staging_dir.name}")
            recovery_paths.append(staging_dir)
    return warnings, recovery_paths


def promote_snapshot_revisioned(
    root: Path,
    out_dir: Path,
    artifacts: dict[str, dict[str, Any]],
    *,
    output_kind: str = "web_snapshot",
    force_unowned_output: bool = False,
    retention: int = SNAPSHOT_REVISION_RETENTION,
) -> SnapshotWriteResult:
    """Activate one immutable snapshot revision through an atomic pointer.

    New bundles are built and validated below a managed sibling revision store.
    The compatibility path ``out_dir/<artifact>`` is an internal relative
    symlink to the active immutable revision and is switched with one atomic
    directory-entry operation. Existing directory layouts are migrated with an
    atomic name exchange on Darwin/Linux; unsupported platforms fail closed.
    """

    if fcntl is None or not (
        sys.platform == "darwin" or sys.platform.startswith("linux")
    ):
        raise OSError(
            errno.ENOTSUP,
            "live snapshot revision publication is supported only on Darwin "
            "and Linux; use the flat build artifact path for offline deployment",
        )
    if retention < 2:
        raise ValueError("snapshot revision retention must keep at least two revisions")
    errors = snapshot_contract_errors(artifacts)
    if errors:
        raise ValueError("invalid snapshot contract: " + "; ".join(errors))
    repo_id = str(
        ((artifacts.get("manifest.json") or {}).get("repo") or {}).get("repo_id")
        or "unknown"
    )
    raw_out = Path(out_dir)
    store_path = _revision_store_path(raw_out)
    previous_pointer: Path | None = None
    expected_active_identity: tuple[int, int, int, str | None] | None = None
    if raw_out.is_symlink():
        # Validate pointer shape/store before creating or modifying any sibling
        # path. The active revision itself is read only under the publication
        # lease, so another publisher cannot prune it during validation.
        _validate_revision_pointer_store(
            root,
            raw_out,
            store_path,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        out_dir = raw_out
    else:
        out_dir = validate_managed_output_target(
            root,
            raw_out,
            kind=output_kind,
            repo_id=repo_id,
            force_unowned=force_unowned_output,
            recognize_legacy=lambda target: _is_legacy_snapshot_directory(
                target, expected_repo_id=repo_id
            ),
        )
        store_path = _revision_store_path(out_dir)
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    publication_lease = contextlib.ExitStack()
    publication_lease.enter_context(_publication_lease(root, out_dir))
    try:
        # State may have advanced while this publisher waited for the
        # cross-process lock. Revalidate the actual active path under the lock;
        # this also handles two first publishers racing an initially absent path.
        if out_dir.is_symlink():
            previous_pointer = _managed_revision_pointer_target(
                root,
                out_dir,
                store_path,
                output_kind=output_kind,
                repo_id=repo_id,
            )
            expected_active_identity = _path_entry_identity(out_dir)
        else:
            previous_pointer = None
            out_dir = validate_managed_output_target(
                root,
                out_dir,
                kind=output_kind,
                repo_id=repo_id,
                force_unowned=force_unowned_output,
                recognize_legacy=lambda target: _is_legacy_snapshot_directory(
                    target, expected_repo_id=repo_id
                ),
            )
            store_path = _revision_store_path(out_dir)
            expected_active_identity = (
                _path_entry_identity(out_dir)
                if os.path.lexists(out_dir)
                else None
            )
        store = _prepare_revision_store(
            root,
            out_dir,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        cleanup_warnings, recovery_paths = _reconcile_snapshot_leftovers(
            root,
            out_dir,
            store,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        revision_dir, _created_revision = _install_snapshot_revision(
            store,
            artifacts,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        revision = revision_dir.name
        activation_dir = Path(
            tempfile.mkdtemp(prefix=f".{out_dir.name}.activate-", dir=out_dir.parent)
        )
        write_output_owner(
            activation_dir,
            kind=f"{output_kind}_activation",
            repo_id=repo_id,
        )
        pointer = activation_dir / "active"
        pointer.symlink_to(Path(store.name) / revision, target_is_directory=True)
        _fsync_snapshot_tree(activation_dir)
    except BaseException:
        publication_lease.close()
        raise
    activation_succeeded = False
    recovery_path: Path | None = None
    try:
        exchanged_existing = _activate_snapshot_pointer_cas(
            pointer,
            out_dir,
            expected_active_identity=expected_active_identity,
        )
        activation_succeeded = True
        if exchanged_existing and previous_pointer is None:
            # One-time migration of the exact flat directory pinned at
            # preflight. A changed pathname is exchanged back by the CAS helper.
            recovery_path = pointer

        # rename(2) and exchange mutate both directory entries. Persist the
        # source activation directory and destination parent immediately after
        # the commit point, before attempting archive/prune cleanup.
        try:
            _fsync_directory(activation_dir)
        except OSError:
            cleanup_warnings.append("activation_source_directory_fsync_failed")
        try:
            _fsync_directory(out_dir.parent)
        except OSError:
            cleanup_warnings.append("active_pointer_parent_fsync_failed")

        if recovery_path is not None:
            try:
                _archive_exchanged_snapshot_directory(
                    pointer,
                    store,
                    output_kind=output_kind,
                    repo_id=repo_id,
                )
                recovery_path = None
            except (OSError, ValueError):
                cleanup_warnings.append(
                    f"previous_snapshot_recovery_pending:{activation_dir.name}"
                )
                recovery_path = pointer if pointer.exists() else activation_dir
                recovery_paths.append(recovery_path)
        try:
            _removed, prune_warnings, prune_recovery = _prune_snapshot_revisions(
                store,
                active_revision=revision,
                output_kind=output_kind,
                repo_id=repo_id,
                retention=retention,
            )
            cleanup_warnings.extend(prune_warnings)
            recovery_paths.extend(prune_recovery)
        except (OSError, ValueError):
            cleanup_warnings.append("revision_prune_failed_after_commit")
    except BaseException:
        if not activation_succeeded:
            # The one-step activation did not commit. A revision created by
            # this serialized publisher cannot be referenced, so remove only
            # that exact owned+validated directory and leave the old path alone.
            if _created_revision and revision_dir.exists():
                with contextlib.suppress(OSError, ValueError):
                    _validate_owned_snapshot_revision(
                        revision_dir,
                        requested_revision=revision,
                        output_kind=output_kind,
                        repo_id=repo_id,
                    )
                    shutil.rmtree(revision_dir)
                    _fsync_directory(store)
        raise
    finally:
        if pointer.is_symlink():
            try:
                pointer.unlink()
            except OSError:
                if activation_succeeded:
                    cleanup_warnings.append(
                        f"activation_pointer_cleanup_failed:{activation_dir.name}"
                    )
                    recovery_paths.append(pointer)
        # After a successful exchange the previous directory is either archived
        # or intentionally retained at ``recovery_path``. Never recursively
        # delete that recovery surface from a finally block.
        if activation_dir.exists() and recovery_path is None:
            try:
                _remove_owned_activation_container(
                    activation_dir,
                    store,
                    output_kind=output_kind,
                    repo_id=repo_id,
                )
            except (OSError, ValueError) as cleanup_error:
                if activation_succeeded:
                    cleanup_path = _activation_cleanup_path(activation_dir)
                    cleanup_warnings.append(
                        f"activation_container_cleanup_failed:{activation_dir.name}"
                    )
                    explicit_recovery = getattr(
                        cleanup_error,
                        "recovery_path",
                        None,
                    )
                    candidate = (
                        Path(explicit_recovery)
                        if explicit_recovery is not None
                        and os.path.lexists(explicit_recovery)
                        else (
                            activation_dir
                            if activation_dir.exists()
                            else cleanup_path
                        )
                    )
                    if not os.path.lexists(candidate):
                        candidate = _cleanup_receipt_path(
                            store,
                            cleanup_path,
                            output_kind=output_kind,
                            repo_id=repo_id,
                        )
                    if os.path.lexists(candidate):
                        recovery_paths.append(candidate)
        try:
            publication_lease.close()
        except (OSError, ValueError):
            if activation_succeeded:
                cleanup_warnings.append("publication_lock_release_failed_after_commit")
    files = {
        name: out_dir / name
        for name in (artifacts.get("manifest.json") or {}).get("files") or []
    }
    snapshot_id = str((artifacts.get("manifest.json") or {}).get("snapshot_id") or "")
    unique_recovery = tuple(dict.fromkeys(recovery_paths))
    return SnapshotWriteResult(
        files,
        snapshot_id=snapshot_id,
        active_revision=revision,
        cleanup_warnings=tuple(dict.fromkeys(cleanup_warnings)),
        recovery_paths=unique_recovery,
    )


def prune_snapshot_revisions(
    root: Path,
    out_dir: Path,
    *,
    output_kind: str = "web_snapshot",
    repo_id: str,
    retention: int = SNAPSHOT_REVISION_RETENTION,
) -> SnapshotCleanupResult:
    """Prune inactive revisions while preserving active and leased bundles."""

    store = _revision_store_path(out_dir)
    _validate_revision_pointer_store(
        root,
        out_dir,
        store,
        output_kind=output_kind,
        repo_id=repo_id,
    )
    with _publication_lease(root, out_dir):
        active = _managed_revision_pointer_target(
            root,
            out_dir,
            store,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        cleanup_warnings, recovery_paths = _reconcile_snapshot_leftovers(
            root,
            out_dir,
            store,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        removed, prune_warnings, prune_recovery = _prune_snapshot_revisions(
            store,
            active_revision=active.name,
            output_kind=output_kind,
            repo_id=repo_id,
            retention=retention,
        )
        cleanup_warnings.extend(prune_warnings)
        recovery_paths.extend(prune_recovery)
    return SnapshotCleanupResult(
        removed,
        cleanup_warnings=tuple(dict.fromkeys(cleanup_warnings)),
        recovery_paths=tuple(dict.fromkeys(recovery_paths)),
    )


def validate_snapshot_output_location(
    root: Path,
    out_dir: Path,
    *,
    repo_id: str,
    output_kind: str = "web_snapshot",
) -> Path:
    """Preflight snapshot containment before the expensive snapshot build."""

    if out_dir.is_symlink():
        _validate_revision_pointer_store(
            root,
            out_dir,
            _revision_store_path(out_dir),
            output_kind=output_kind,
            repo_id=repo_id,
        )
        return out_dir
    return contained_output_path(root, out_dir)


def _snapshot_health_identity(
    root: Path,
    out_dir: Path,
    store: Path,
    *,
    output_kind: str,
    repo_id: str,
    max_attempts: int = 8,
) -> tuple[str, str | None, int, bool, float]:
    """Read a lease-pinned identity, caching only unchanged tree metadata."""

    started = time.perf_counter()
    last_transient: OSError | None = None
    for attempt in range(max_attempts):
        relative = _validate_revision_pointer_store(
            root,
            out_dir,
            store,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        target = out_dir.parent / relative
        try:
            with _revision_lease(store, relative.name, exclusive=False) as acquired:
                if not acquired:
                    raise OSError(
                        errno.ENOTSUP,
                        "cross-process snapshot leases are unavailable",
                    )
                if not target.is_dir() or target.is_symlink():
                    raise FileNotFoundError(target)
                fingerprint = _snapshot_tree_fingerprint(target)
                cache_key = (
                    str(out_dir.parent.resolve(strict=True) / out_dir.name),
                    output_kind,
                    repo_id,
                    relative.name,
                )
                now = time.monotonic()
                with SNAPSHOT_HEALTH_VALIDATION_CACHE_LOCK:
                    cached = SNAPSHOT_HEALTH_VALIDATION_CACHE.get(cache_key)
                if (
                    cached is not None
                    and cached[0] >= now
                    and cached[1] == fingerprint
                ):
                    return (
                        cached[2],
                        cached[3],
                        cached[4],
                        True,
                        (time.perf_counter() - started) * 1000,
                    )

                payloads = _validate_owned_snapshot_revision(
                    target,
                    requested_revision=relative.name,
                    output_kind=output_kind,
                    repo_id=repo_id,
                )
                manifest = payloads["manifest.json"]
                snapshot_id = str(manifest.get("snapshot_id") or "") or None
                cache_value = (
                    now + SNAPSHOT_HEALTH_VALIDATION_CACHE_TTL_S,
                    fingerprint,
                    relative.name,
                    snapshot_id,
                    len(payloads),
                )
                with SNAPSHOT_HEALTH_VALIDATION_CACHE_LOCK:
                    if (
                        len(SNAPSHOT_HEALTH_VALIDATION_CACHE)
                        >= SNAPSHOT_HEALTH_VALIDATION_CACHE_MAX_ENTRIES
                    ):
                        oldest_key = min(
                            SNAPSHOT_HEALTH_VALIDATION_CACHE,
                            key=lambda key: SNAPSHOT_HEALTH_VALIDATION_CACHE[key][0],
                        )
                        SNAPSHOT_HEALTH_VALIDATION_CACHE.pop(oldest_key, None)
                    SNAPSHOT_HEALTH_VALIDATION_CACHE[cache_key] = cache_value
                return (
                    relative.name,
                    snapshot_id,
                    len(payloads),
                    False,
                    (time.perf_counter() - started) * 1000,
                )
        except FileNotFoundError as exc:
            last_transient = exc
            if attempt + 1 < max_attempts:
                time.sleep(
                    min(
                        SNAPSHOT_READ_RETRY_BASE_S * (2**attempt),
                        SNAPSHOT_READ_RETRY_MAX_S,
                    )
                )
                continue
    raise RuntimeError(
        f"active snapshot changed during {max_attempts} health attempts: {out_dir}"
    ) from last_transient


def snapshot_publication_status(
    root: Path,
    out_dir: Path,
    *,
    repo_id: str,
    output_kind: str = "web_snapshot",
) -> dict[str, Any]:
    """Return explicit publication capability and fully validated active identity."""

    platform_supported = fcntl is not None and (
        sys.platform == "darwin" or sys.platform.startswith("linux")
    )
    primitive: str | None = None
    if sys.platform == "darwin":
        primitive = "renamex_np(RENAME_SWAP)"
    elif sys.platform.startswith("linux"):
        with contextlib.suppress(AttributeError):
            getattr(ctypes.CDLL(None), "renameat2")
            primitive = "renameat2(RENAME_EXCHANGE)"

    layout = "absent"
    active_revision: str | None = None
    active_snapshot_id: str | None = None
    pointer_state = "not_applicable"
    validation_artifact_count = 0
    validation_cache_hit = False
    validation_duration_ms = 0.0
    store = _revision_store_path(out_dir)
    if out_dir.is_symlink():
        layout = "immutable_revision_relative_pointer"
        try:
            (
                active_revision,
                active_snapshot_id,
                validation_artifact_count,
                validation_cache_hit,
                validation_duration_ms,
            ) = _snapshot_health_identity(
                root,
                out_dir,
                store,
                output_kind=output_kind,
                repo_id=repo_id,
            )
            pointer_state = "full_inventory_owner_repo_and_hash_valid"
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
            pointer_state = "invalid"
    elif out_dir.is_dir():
        layout = "flat_build_directory"
    elif out_dir.exists():
        layout = "unsafe_non_directory"

    activation_owned_pending = 0
    activation_unowned_preserved = 0
    for candidate in out_dir.parent.glob(f".{out_dir.name}.activate-*"):
        if candidate.is_symlink() or not candidate.is_dir():
            activation_unowned_preserved += 1
        elif output_is_owned(
            candidate,
            kind=f"{output_kind}_activation",
            repo_id=repo_id,
        ):
            activation_owned_pending += 1
        else:
            activation_unowned_preserved += 1
    cleanup_empty_pending = 0
    cleanup_owned_pending = 0
    cleanup_ambiguous_preserved = 0
    for candidate in out_dir.parent.glob(f".{out_dir.name}.cleanup-*"):
        if candidate.is_symlink() or not candidate.is_dir():
            cleanup_ambiguous_preserved += 1
            continue
        receipt_payload = _read_cleanup_receipt(
            store,
            candidate,
            output_kind=output_kind,
            repo_id=repo_id,
        )
        if receipt_payload is None:
            entries = set(candidate.iterdir())
            marker = candidate / OUTPUT_OWNER_FILENAME
            intent = candidate / SNAPSHOT_CLEANUP_INTENT_FILENAME
            intent_payload = (
                _read_cleanup_intent(
                    candidate,
                    candidate,
                    output_kind=output_kind,
                    repo_id=repo_id,
                )
                if intent in entries
                else None
            )
            if (
                entries == {marker, intent}
                and intent_payload is not None
                and output_is_owned(
                    candidate,
                    kind=f"{output_kind}_activation",
                    repo_id=repo_id,
                )
            ):
                cleanup_owned_pending += 1
            else:
                cleanup_ambiguous_preserved += 1
            continue
        entries = set(candidate.iterdir())
        if not entries:
            cleanup_empty_pending += 1
        else:
            marker = candidate / OUTPUT_OWNER_FILENAME
            intent = candidate / SNAPSHOT_CLEANUP_INTENT_FILENAME
            intent_payload = (
                _read_cleanup_intent(
                    candidate,
                    candidate,
                    output_kind=output_kind,
                    repo_id=repo_id,
                )
                if intent in entries
                else None
            )
            if (
                entries in ({marker}, {marker, intent})
                and (intent not in entries or intent_payload is not None)
                and (
                    intent_payload is None
                    or intent_payload["receipt_id"] == receipt_payload["receipt_id"]
                )
                and output_is_owned(
                    candidate,
                    kind=f"{output_kind}_activation",
                    repo_id=repo_id,
                )
            ):
                cleanup_owned_pending += 1
            else:
                cleanup_ambiguous_preserved += 1
    cleanup_orphan_receipts_pending = 0
    cleanup_invalid_receipts_preserved = 0
    receipts = _cleanup_receipts_path(store)
    if receipts.is_dir() and not receipts.is_symlink():
        for receipt in receipts.glob("*.json"):
            if receipt.name == OUTPUT_OWNER_FILENAME:
                continue
            try:
                raw_payload = json.loads(
                    _read_snapshot_file_bytes(receipts, receipt.name).decode("utf-8")
                )
                cleanup_name = str(raw_payload.get("cleanup_name") or "")
                if (
                    Path(cleanup_name).name != cleanup_name
                    or not cleanup_name.startswith(f".{out_dir.name}.cleanup-")
                ):
                    raise ValueError("unsafe cleanup name")
                cleanup_dir = out_dir.parent / cleanup_name
                payload = _read_cleanup_receipt(
                    store,
                    cleanup_dir,
                    output_kind=output_kind,
                    repo_id=repo_id,
                    require_directory_match=False,
                )
            except (OSError, AttributeError, ValueError, json.JSONDecodeError):
                payload = None
                cleanup_dir = out_dir.parent
            if payload is None:
                cleanup_invalid_receipts_preserved += 1
                continue
            if os.path.lexists(cleanup_dir) and _read_cleanup_receipt(
                store,
                cleanup_dir,
                output_kind=output_kind,
                repo_id=repo_id,
            ) is None:
                cleanup_invalid_receipts_preserved += 1
                continue
            activation_dir = out_dir.parent / payload["activation_name"]
            if not os.path.lexists(cleanup_dir) and not os.path.lexists(
                activation_dir
            ):
                cleanup_orphan_receipts_pending += 1
    owned_recovery = (
        activation_owned_pending
        + cleanup_empty_pending
        + cleanup_owned_pending
        + cleanup_orphan_receipts_pending
    )
    unowned_recovery = (
        activation_unowned_preserved
        + cleanup_ambiguous_preserved
        + cleanup_invalid_receipts_preserved
    )
    leases_state = "absent"
    if store.is_dir() and not store.is_symlink():
        leases = store / "leases"
        leases_state = (
            "safe_directory"
            if leases.is_dir() and not leases.is_symlink()
            else "unsafe"
        )
    return {
        "version": "wiki_filesystem_snapshot_publication.v1",
        "publication_supported": platform_supported,
        "platform": sys.platform,
        "layout": layout,
        "pointer_state": pointer_state,
        "active_revision": active_revision,
        "active_snapshot_id": active_snapshot_id,
        "reader_contract": "filesystem_consumer_resolves_pointer_once_and_validates_envelope",
        "validation": {
            "mode": "lease_pinned_full_inventory_owner_repo_and_sha256",
            "cache_ttl_seconds": SNAPSHOT_HEALTH_VALIDATION_CACHE_TTL_S,
            "budget_ms": SNAPSHOT_HEALTH_VALIDATION_BUDGET_MS,
            "cache_hit": validation_cache_hit,
            "metadata_fingerprint_checked_on_cache_hit": True,
            "artifact_count": validation_artifact_count,
            "duration_ms": round(validation_duration_ms, 3),
            "within_budget": (
                validation_duration_ms <= SNAPSHOT_HEALTH_VALIDATION_BUDGET_MS
            ),
        },
        "retention": SNAPSHOT_REVISION_RETENTION,
        "leases_state": leases_state,
        "recovery": {
            "owned_pending": owned_recovery,
            "unowned_preserved": unowned_recovery,
            "activation_owned_pending": activation_owned_pending,
            "activation_unowned_preserved": activation_unowned_preserved,
            "cleanup_empty_pending": cleanup_empty_pending,
            "cleanup_owned_pending": cleanup_owned_pending,
            "cleanup_ambiguous_preserved": cleanup_ambiguous_preserved,
            "cleanup_orphan_receipts_pending": cleanup_orphan_receipts_pending,
            "cleanup_invalid_receipts_preserved": (
                cleanup_invalid_receipts_preserved
            ),
        },
        "legacy_directory_migration": {
            "supported": platform_supported and primitive is not None,
            "primitive": primitive,
            "filesystem_support": "probed_on_first_exchange",
        },
        "durability": {
            "live_files_fsynced_before_activation": platform_supported,
            "revision_store_and_staging_directories_fsynced_before_commit": (
                platform_supported
            ),
            "activation_source_and_destination_parent_fsync_attempted_after_commit": (
                platform_supported
            ),
            "archive_source_and_destination_directories_fsync_attempted": (
                platform_supported
            ),
            "post_commit_fsync_failures_return_cleanup_warnings": True,
            "flat_build_host_activation_required": True,
        },
        "deletion_safety": {
            "prune_recursive_delete": "descriptor_pinned_no_follow",
            "cleanup_receipt_binding": "directory_dev_ino_type",
            "posix_final_compare_to_rmdir_window": (
                "unavoidable_without_inode_conditional_rmdir"
            ),
        },
        "flat_build_supported": True,
    }


def write_snapshot(
    root: Path,
    out_dir: Path,
    config: WikiConfig | None = None,
    *,
    clean: bool = False,
    mode: str = "static",
    content_sidecars: bool = False,
    force_unowned_output: bool = False,
    publication: str = "auto",
) -> dict[str, Path] | SnapshotWriteResult:
    config = config or load_config(root)
    payloads = build_snapshot(
        root, config, mode=mode, content_sidecars=content_sidecars
    )
    artifacts = prepare_snapshot_artifacts(
        root, config, payloads, content_sidecars=content_sidecars
    )
    errors = snapshot_contract_errors(artifacts)
    if errors:
        raise ValueError("invalid snapshot contract: " + "; ".join(errors))
    # ``clean`` remains a CLI/API compatibility argument. A complete immutable
    # revision is activated as one unit, so stale per-file artifacts cannot
    # survive in the active view.
    _ = clean
    if publication not in {"auto", "live", "flat_build"}:
        raise ValueError("publication must be auto, live or flat_build")
    live_supported = fcntl is not None and (
        sys.platform == "darwin" or sys.platform.startswith("linux")
    )
    use_flat_build = publication == "flat_build" or (
        publication == "auto" and mode == "static" and not live_supported
    )
    if use_flat_build:
        return promote_snapshot_artifacts(
            root,
            out_dir,
            artifacts,
            force_unowned_output=force_unowned_output,
        )
    return promote_snapshot_revisioned(
        root,
        out_dir,
        artifacts,
        force_unowned_output=force_unowned_output,
    )
