from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from wiki_core.closure import build_ingestion_closure_report
from wiki_core.config import WikiConfig, load_config
from wiki_core.freshness import freshness_state, is_stale_exempt
from wiki_core.frontmatter import list_values, parse_frontmatter
from wiki_core.graph import build_page_graph
from wiki_core.paths import WikiPaths
from wiki_core.quality import build_quality_report
from wiki_core.web.commands import build_operator_command_cards
from wiki_core.web.diff import build_diff_payload
from wiki_core.web.git_ops import build_git_state
from wiki_core.web.schemas import (
    SNAPSHOT_FILES,
    WEB_BLOCK_VOCABULARY_VERSION,
    WEB_REGISTRY_MODULE_API_VERSION,
    WEB_RELATION_VOCABULARY_VERSION,
    WEB_ROUTE_CONTRACT_VERSION,
    WEB_RUNTIME_CONTRACT_VERSION,
    WEB_SEMANTIC_VISUAL_TOKENS_VERSION,
    WEB_SNAPSHOT_SCHEMA_VERSION,
    WEB_SOURCE_FRESHNESS_VERSION,
    WEB_SOURCE_LAST_ATTEMPT_VERSION,
    WEB_SOURCE_LIFECYCLE_VERSION,
    WEB_VISUAL_GRAMMAR_VERSION,
)
from wiki_core.web.timeline import build_timeline_payload

H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
H2_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
EMPHASIS_RE = re.compile(r"(\*{1,3}|_{2,3}|`{1,3})([^*_`]+?)\1")
SUMMARY_LIMIT = 260

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
    "source_ref": {
        "family": "evidence",
        "direction": "directed",
        "allows_multiple": True,
        "allows_cycles": False,
        "provenance_bearing": True,
        "visual_line_intent": "evidence reference",
        "fallback": "source reference row",
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


def _root_page_id(config: WikiConfig, pages_payload: dict[str, Any]) -> str:
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
    return str(roots[0]["id"]) if roots else ""


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
    root: Path, path: Path, config: WikiConfig, *, today: dt.date | None = None
) -> dict[str, Any]:
    rel = path.relative_to(root).as_posix()
    values, body = parse_frontmatter(path)
    source_refs = list_values(values.get("source_refs"))
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
        "summary": summary,
        "summary_truncated": summary_truncated,
    }
    if isinstance(values.get("region_expectations"), dict):
        record["region_expectations"] = values["region_expectations"]
    record["relation_refs"] = {
        "consolidated_into": list_values(values.get("consolidated_into")),
        "proposal_ids": list_values(values.get("proposal_ids")),
        "participants": list_values(values.get("participants")),
        "previous_refs": list_values(
            values.get("previous_refs") or values.get("previous_ref")
        ),
        "relation_cases": values.get("relation_cases")
        if isinstance(values.get("relation_cases"), list)
        else [],
    }
    if str(values.get("page_type") or "") == "action":
        record["work"] = {
            "state": str(
                values.get("action_state")
                or values.get("state")
                or values.get("status")
                or "open"
            ),
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
    if str(values.get("page_type") or "").startswith("source"):
        record["source_lifecycle_state"] = str(
            values.get("source_lifecycle_state") or values.get("lifecycle_state") or ""
        )
        record["source_blocked_reason"] = str(
            values.get("source_blocked_reason") or values.get("blocked_reason") or ""
        )
    return record


def _pages_payload(root: Path, config: WikiConfig) -> dict[str, Any]:
    today = _today()
    pages: list[dict[str, Any]] = []
    for path in _markdown_pages(root, config):
        try:
            pages.append(_page_record(root, path, config, today=today))
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
    return {
        "schema_version": "wiki_web_pages.v1",
        "repo_id": config.repo_id,
        "pages": pages,
    }


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
    root_page_id: str = "",
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
    valid_action_states = {
        "open",
        "in_progress",
        "blocked",
        "waiting_human",
        "done",
        "cancelled",
    }
    for page in pages:
        if str(page.get("page_type") or "") != "action":
            continue
        work = dict(page.get("work") or {})
        action_id = str(page.get("id") or "")
        raw_state = str(work.get("state") or "open")
        state = raw_state if raw_state in valid_action_states else "unknown"
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
    quality_payload: dict[str, Any],
    snapshot_warnings_payload: dict[str, Any],
    gates_payload: dict[str, Any],
    source_lifecycle_payload: dict[str, Any],
) -> dict[str, Any]:
    graph = build_page_graph(root, config)
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
    )
    nodes = []
    edges = []
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
                edges.append(
                    {
                        "id": hashlib.sha256(
                            f"{id_by_path[rel]}|{id_by_path[target]}|markdown_link".encode(
                                "utf-8"
                            )
                        ).hexdigest()[:20],
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
        for target in node.outbound_frontmatter_refs:
            if target in id_by_path:
                edge_type = (
                    "moc_parent" if target == page.get("moc_parent") else "source_ref"
                )
                edges.append(
                    {
                        "id": hashlib.sha256(
                            f"{id_by_path[rel]}|{id_by_path[target]}|{edge_type}".encode(
                                "utf-8"
                            )
                        ).hexdigest()[:20],
                        "source": id_by_path[rel],
                        "target": id_by_path[target],
                        "type": edge_type,
                        "direction": "directed",
                        "basis": "frontmatter",
                        "provenance": {
                            "page_id": id_by_path[rel],
                            "path": rel,
                            "field": edge_type,
                        },
                        "observed_at": str(page.get("updated_at") or ""),
                        "status": "valid",
                        "weight": 2 if edge_type == "moc_parent" else 1,
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
        if any(edge.get("id") == relation_id for edge in edges):
            return
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
        if page.get("page_type") == "ingestion_event":
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
            for evidence in work.get("evidence_refs") or []:
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


def _safe_source_entities(root: Path, config: WikiConfig) -> dict[str, Any]:
    """Rich per-source read model (identity + recipe streams + sync + cursor
    freshness). Wrapped like _safe_ingestion so a malformed recipe never breaks
    the whole snapshot — the dock shows the error instead."""
    try:
        from wiki_core.web.sources import build_sources_payload

        return build_sources_payload(root, config)
    except Exception as exc:  # noqa: BLE001
        return {
            "schema_version": "wiki_web_source_entities.v1",
            "sources": [],
            "error": str(exc),
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
        valid_states = {
            "open",
            "in_progress",
            "blocked",
            "waiting_human",
            "done",
            "cancelled",
        }
        valid_owner_kinds = {"human", "agent", "system", "other", "unassigned"}
        owner_kind = str(work.get("owner_kind") or "unassigned")
        warnings: list[str] = []
        if state not in valid_states:
            warnings.append("invalid_action_state")
            state = "open"
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
                "contract_warnings": warnings,
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
        blocked_reason = str(page.get("source_blocked_reason") or "")
        last_status = str(sync.get("last_status") or "never")
        attempt_state = str(declared.get("last_attempt_state") or last_status)
        if attempt_state in {"partial", "never", "running", "queued"}:
            attempt_state = (
                "failed"
                if attempt_state == "partial"
                else "ok"
                if attempt_state in {"running", "queued"}
                else "never"
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
    root_page_id = str(manifest.get("root_page_id") or "")
    empty_compat = "empty_world_compat" in (manifest.get("capabilities") or [])
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
    }
    missing_versions = required_versions - set((manifest.get("versions") or {}).keys())
    if missing_versions:
        errors.append(
            f"missing contract versions: {', '.join(sorted(missing_versions))}"
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

    valid_action_states = {
        "open",
        "in_progress",
        "blocked",
        "waiting_human",
        "done",
        "cancelled",
    }
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

    lifecycle_states = {
        "configured",
        "ready",
        "syncing",
        "proposed",
        "consolidated",
        "ingested",
        "blocked",
    }
    freshness_states = {"fresh", "stale", "never_synced"}
    attempt_states = {
        "never",
        "ok",
        "failed",
        "needs_auth",
        "parser_error",
        "secret_blocked",
    }
    pipeline_stages = {
        "configured",
        "manifested",
        "extracted",
        "indexed",
        "deep_read",
        "proposal_ready",
        "integrating",
        "gate_pending",
        "complete",
    }
    for source in (payloads.get("source_lifecycle.json") or {}).get("sources") or []:
        source_id = str(source.get("source_id") or "<missing-id>")
        if source_id not in known:
            errors.append(f"source lifecycle is not a canonical page: {source_id}")
        if source.get("lifecycle_state") not in lifecycle_states:
            errors.append(f"invalid source lifecycle: {source_id}")
        if source.get("freshness_state") not in freshness_states:
            errors.append(f"invalid source freshness: {source_id}")
        if source.get("last_attempt_state") not in attempt_states:
            errors.append(f"invalid source attempt: {source_id}")
        if source.get("pipeline_stage") not in pipeline_stages:
            errors.append(f"invalid source pipeline stage: {source_id}")
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
                    "pt": level_display(level_id, "pt"),
                },
                "badges": [
                    {
                        "id": badge_id,
                        "en": str(badge_display(badge_id, "en").get("name", badge_id)),
                        "pt": str(badge_display(badge_id, "pt").get("name", badge_id)),
                        "criterion_en": str(
                            badge_display(badge_id, "en").get("criterion", "")
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
    root: Path, config: WikiConfig
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The v2 block registry (blocks.json) and per-anchor resolved stacks
    (block_stacks.json). Wrapped like the other rich payloads so a malformed
    block never breaks the whole snapshot — the dock shows the error instead."""
    try:
        from wiki_core.template_blocks import blocks_payloads

        return blocks_payloads(root, config, today=_today())
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


def build_snapshot(
    root: Path,
    config: WikiConfig | None = None,
    *,
    mode: str = "static",
    generated_at: str | None = None,
    content_sidecars: bool = False,
) -> dict[str, dict[str, Any]]:
    config = config or load_config(root)
    generated_at = generated_at or _utc_now()
    git_payload = build_git_state(root, config)
    pages = _pages_payload(root, config)
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
    blocks_payload, block_stacks_payload = _safe_blocks(root, config)
    source_entities_payload = _safe_source_entities(root, config)
    operator_commands_payload = _operator_commands_payload(actions)
    work_items_payload = _work_items_payload(pages)
    region_groups_payload = _region_groups_payload(block_stacks_payload, pages)
    source_lifecycle_payload = _source_lifecycle_payload(pages, source_entities_payload)
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
            quality_payload,
            snapshot_warnings_payload,
            gates_payload,
            source_lifecycle_payload,
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
            artifacts[name] = build_page_content(root, config, page_id, artifacts)
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
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        written[name] = target
    return written


def _validate_snapshot_directory(target_dir: Path) -> None:
    manifest_path = target_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    declared = [str(name) for name in manifest.get("files") or []]
    actual = sorted(
        path.relative_to(target_dir).as_posix()
        for path in target_dir.rglob("*")
        if path.is_file() and not path.is_symlink()
    )
    if sorted(declared) != actual:
        raise ValueError(
            "snapshot staging directory differs from manifest: "
            f"declared={len(declared)} actual={len(actual)}"
        )
    loaded = {
        name: json.loads((target_dir / name).read_text(encoding="utf-8"))
        for name in declared
    }
    errors = snapshot_contract_errors(loaded)
    if errors:
        raise ValueError("invalid staged snapshot contract: " + "; ".join(errors))


def promote_snapshot_artifacts(
    out_dir: Path, artifacts: dict[str, dict[str, Any]]
) -> dict[str, Path]:
    """Write, validate and promote a complete snapshot with rollback safety."""

    errors = snapshot_contract_errors(artifacts)
    if errors:
        raise ValueError("invalid snapshot contract: " + "; ".join(errors))
    if out_dir.is_symlink():
        raise ValueError(f"snapshot output cannot be a symlink: {out_dir}")
    if out_dir.exists() and not out_dir.is_dir():
        raise ValueError(f"snapshot output must be a directory: {out_dir}")
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(
        tempfile.mkdtemp(prefix=f".{out_dir.name}.stage-", dir=out_dir.parent)
    )
    backup_dir = staging_dir.with_name(f"{staging_dir.name}.previous")
    old_moved = False
    try:
        _write_snapshot_artifacts(staging_dir, artifacts)
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


def write_snapshot(
    root: Path,
    out_dir: Path,
    config: WikiConfig | None = None,
    *,
    clean: bool = False,
    mode: str = "static",
    content_sidecars: bool = False,
) -> dict[str, Path]:
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
    # ``clean`` remains a CLI/API compatibility argument. Atomic full-directory
    # promotion always removes stale artifacts, which is the only safe v8 mode.
    _ = clean
    return promote_snapshot_artifacts(out_dir, artifacts)
