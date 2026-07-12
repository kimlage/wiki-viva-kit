"""One-time, repository-level adoption of a pre-gate action baseline.

Older consumers may have legitimate action state/support changes that predate
the append-only v8 transition gate.  Replaying those changes as if they
happened today would invent history.  This module instead compiles one
consumer-owned receipt for the exact commit immediately before the gate was
introduced.  The receipt is useful only on the first adoption PR; after merge,
the normal PR base contains the adopted actions and ordinary transition
receipts govern every later change.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from wiki_core.action_state import legacy_action_state_from_body, resolve_action_state
from wiki_core.action_transition import (
    _governed_support_sha256,
    _revision_sha256,
)
from wiki_core.detectors import scan_text
from wiki_core.frontmatter import parse_frontmatter


ACTION_ADOPTION_SCHEMA_VERSION = "wiki_action_transition_adoption.v1"
ACTION_ADOPTION_RECEIPT_PATH = "wiki.action-transition-adoption.yaml"
ACTION_GATE_MARKER = "def audit_action_state_transitions"

_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RECEIPT_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_INSTANT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$"
)


def _valid_instant(value: Any) -> bool:
    text = str(value or "")
    if not _INSTANT_RE.fullmatch(text):
        return False
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _receipt_id(receipt: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in receipt.items() if key != "receipt_id"}
    return f"sha256:{_canonical_sha256(payload)}"


def action_inventory(
    documents: Mapping[str, str],
) -> tuple[list[dict[str, str]], str]:
    """Return canonical action rows plus their deterministic inventory hash."""

    rows: list[dict[str, str]] = []
    page_ids: set[str] = set()
    for raw_path, text in sorted(documents.items()):
        path = PurePosixPath(str(raw_path))
        if path.is_absolute() or ".." in path.parts or path.suffix != ".md":
            raise ValueError("unsafe_action_inventory_path")
        values, body = parse_frontmatter(text)
        if str(values.get("page_type") or "") != "action":
            continue
        page_id = str(values.get("page_id") or "").strip()
        if not page_id or page_id in page_ids:
            raise ValueError("invalid_action_inventory_identity")
        resolution = resolve_action_state(
            values,
            legacy_state=legacy_action_state_from_body(body),
        )
        if not resolution.valid or resolution.source != "action_state":
            raise ValueError("invalid_action_inventory_state")
        page_ids.add(page_id)
        rows.append(
            {
                "page_id": page_id,
                "path": path.as_posix(),
                "state": resolution.state,
                "state_source": resolution.source,
                "governed_support_sha256": _governed_support_sha256(values),
                "revision_sha256": _revision_sha256(text),
            }
        )
    rows.sort(key=lambda row: (row["page_id"], row["path"]))
    return rows, _canonical_sha256(rows)


def compile_action_adoption_receipt(
    *,
    repo_id: str,
    audit_base_commit: str,
    baseline_commit: str,
    gate_introduced_commit: str,
    recorded_at: str,
    reason: str,
    documents: Mapping[str, str],
) -> dict[str, Any]:
    """Compile the content-bound receipt; Git ancestry is verified separately."""

    reason_text = str(reason or "").strip()
    if not reason_text:
        raise ValueError("missing_action_adoption_reason")
    if any(item.category in {"secret", "pii"} for item in scan_text(reason_text)):
        raise ValueError("unsafe_action_adoption_reason")
    for value in (audit_base_commit, baseline_commit, gate_introduced_commit):
        if not _COMMIT_RE.fullmatch(str(value or "")):
            raise ValueError("invalid_action_adoption_commit")
    if not _valid_instant(recorded_at):
        raise ValueError("invalid_action_adoption_recorded_at")

    rows, inventory_sha256 = action_inventory(documents)
    receipt: dict[str, Any] = {
        "schema_version": ACTION_ADOPTION_SCHEMA_VERSION,
        "repo_id": str(repo_id or "").strip(),
        "audit_base_commit": audit_base_commit,
        "baseline_commit": baseline_commit,
        "gate_introduced_commit": gate_introduced_commit,
        "recorded_at": recorded_at,
        "action_count": len(rows),
        "action_inventory_sha256": inventory_sha256,
        "reason": reason_text,
    }
    if not receipt["repo_id"]:
        raise ValueError("missing_action_adoption_repo_id")
    receipt["receipt_id"] = _receipt_id(receipt)
    return receipt


def validate_action_adoption_receipt(
    receipt: Mapping[str, Any],
    *,
    repo_id: str,
    documents: Mapping[str, str],
) -> list[str]:
    """Validate one receipt without trusting its stored count or digest."""

    errors: list[str] = []
    if str(receipt.get("schema_version") or "") != ACTION_ADOPTION_SCHEMA_VERSION:
        errors.append("unsupported_action_adoption_schema")
    if str(receipt.get("repo_id") or "") != str(repo_id or ""):
        errors.append("action_adoption_repo_mismatch")
    for field in (
        "audit_base_commit",
        "baseline_commit",
        "gate_introduced_commit",
    ):
        if not _COMMIT_RE.fullmatch(str(receipt.get(field) or "")):
            errors.append(f"invalid_action_adoption_{field}")
    if not _valid_instant(receipt.get("recorded_at")):
        errors.append("invalid_action_adoption_recorded_at")
    reason = str(receipt.get("reason") or "").strip()
    if not reason:
        errors.append("missing_action_adoption_reason")
    elif any(item.category in {"secret", "pii"} for item in scan_text(reason)):
        errors.append("unsafe_action_adoption_reason")
    try:
        rows, inventory_sha256 = action_inventory(documents)
    except ValueError as exc:
        errors.append(str(exc))
        rows, inventory_sha256 = [], ""
    if receipt.get("action_count") != len(rows):
        errors.append("action_adoption_count_mismatch")
    stored_inventory = str(receipt.get("action_inventory_sha256") or "")
    if not _SHA256_RE.fullmatch(stored_inventory) or stored_inventory != inventory_sha256:
        errors.append("action_adoption_inventory_mismatch")
    receipt_id = str(receipt.get("receipt_id") or "")
    if not _RECEIPT_ID_RE.fullmatch(receipt_id) or receipt_id != _receipt_id(receipt):
        errors.append("action_adoption_receipt_id_mismatch")
    return sorted(set(errors))


def _git(root: Path, args: list[str]) -> tuple[int, str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.returncode, completed.stdout


def action_documents_at_commit(
    root: Path,
    commit: str,
    memory_root: str,
) -> dict[str, str]:
    """Read Markdown under one configured memory root from an exact Git tree."""

    raw_prefix = str(memory_root or "").strip()
    raw_path = PurePosixPath(raw_prefix)
    if not raw_prefix or raw_path.is_absolute() or ".." in raw_path.parts:
        raise ValueError("unsafe_action_adoption_memory_root")
    prefix = raw_prefix.rstrip("/")
    code, listing = _git(
        root,
        ["ls-tree", "-r", "--name-only", commit, "--", prefix],
    )
    if code:
        raise ValueError("action_adoption_commit_unreadable")
    documents: dict[str, str] = {}
    for rel in sorted(line for line in listing.splitlines() if line.endswith(".md")):
        show_code, text = _git(root, ["show", f"{commit}:{rel}"])
        if show_code:
            raise ValueError("action_adoption_blob_unreadable")
        documents[rel] = text
    return documents


def verify_action_adoption_git_contract(
    root: Path,
    receipt: Mapping[str, Any],
    *,
    repo_id: str,
    memory_root: str,
    audit_base_commit: str,
    head: str = "HEAD",
) -> list[str]:
    """Verify exact ancestry, gate introduction and baseline inventory."""

    errors: list[str] = []
    baseline = str(receipt.get("baseline_commit") or "")
    gate = str(receipt.get("gate_introduced_commit") or "")
    if str(receipt.get("audit_base_commit") or "") != audit_base_commit:
        errors.append("action_adoption_audit_base_mismatch")

    if _git(root, ["merge-base", "--is-ancestor", audit_base_commit, gate])[0] != 0:
        errors.append("action_adoption_audit_base_not_ancestor_of_gate")

    parent_code, parent = _git(root, ["rev-parse", f"{gate}^1"])
    if parent_code or parent.strip() != baseline:
        errors.append("action_adoption_baseline_is_not_gate_parent")
    if _git(root, ["merge-base", "--is-ancestor", gate, head])[0] != 0:
        errors.append("action_adoption_gate_not_in_head")

    before_code, before_gate = _git(
        root, ["show", f"{baseline}:scripts/wiki_audit.py"]
    )
    gate_code, gate_text = _git(root, ["show", f"{gate}:scripts/wiki_audit.py"])
    if before_code or gate_code:
        errors.append("action_adoption_gate_marker_unreadable")
    else:
        if ACTION_GATE_MARKER in before_gate:
            errors.append("action_adoption_gate_marker_already_in_baseline")
        if ACTION_GATE_MARKER not in gate_text:
            errors.append("action_adoption_gate_marker_missing")

    try:
        documents = action_documents_at_commit(root, baseline, memory_root)
    except ValueError as exc:
        errors.append(str(exc))
        documents = {}
    errors.extend(
        validate_action_adoption_receipt(
            receipt,
            repo_id=repo_id,
            documents=documents,
        )
    )
    return sorted(set(errors))


def render_action_adoption_receipt(receipt: Mapping[str, Any]) -> str:
    """Render stable YAML for the consumer-owned root receipt."""

    order = (
        "schema_version",
        "repo_id",
        "audit_base_commit",
        "baseline_commit",
        "gate_introduced_commit",
        "recorded_at",
        "action_count",
        "action_inventory_sha256",
        "reason",
        "receipt_id",
    )
    payload = {key: receipt.get(key) for key in order}
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


__all__ = [
    "ACTION_ADOPTION_RECEIPT_PATH",
    "ACTION_ADOPTION_SCHEMA_VERSION",
    "ACTION_GATE_MARKER",
    "action_documents_at_commit",
    "action_inventory",
    "compile_action_adoption_receipt",
    "render_action_adoption_receipt",
    "validate_action_adoption_receipt",
    "verify_action_adoption_git_contract",
]
