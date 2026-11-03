"""Operational coordinator identities and trusted local dialogue routing.

Profiles preserve action attribution and history, never authorize task bodies.
Canonical task packets are prepared by coordination_context. Runtime ownership,
STOP and execution admission remain with the runtime.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable

import yaml

from wiki_core.repository_reader import RepositoryReader
from wiki_core.action_state import legacy_action_state_from_body, resolve_action_state
from wiki_core.frontmatter import parse_frontmatter
from wiki_core.action_dialogue import dialogue_summary
from wiki_core.web.fronts import fronts_projection

POLICY_FILE = "wiki.coordination.yaml"
SCHEMA = "wiki_coordination.v1"
PROFILE_ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


class CoordinationError(ValueError):
    pass


class _UniqueLoader(yaml.SafeLoader):
    pass


def _unique_mapping(loader, node, deep=False):
    pairs = loader.construct_pairs(node, deep=deep)
    result = {}
    for key, value in pairs:
        if not isinstance(key, str) or key in result:
            raise CoordinationError("duplicate or invalid policy key")
        result[key] = value
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def _read(root: Path, relative: str) -> bytes:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise CoordinationError("unsafe context path")
    target = root
    for part in path.parts:
        target /= part
        if target.is_symlink():
            raise CoordinationError("symlink context paths are not supported")
    if not target.is_file() or target.stat().st_size > 2_000_000:
        raise CoordinationError(f"context file missing or too large: {relative}")
    return target.read_bytes()


def _strings(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(x, str) or not x for x in value):
        raise CoordinationError(f"{label} must be a list of nonempty strings")
    if len(value) != len(set(value)):
        raise CoordinationError(f"duplicate {label}")
    return value


def load_policy(root: Path) -> tuple[dict[str, Any], str] | None:
    if not (root / POLICY_FILE).exists():
        return None
    raw = _read(root, POLICY_FILE)
    try:
        policy = yaml.load(raw, Loader=_UniqueLoader)
    except yaml.YAMLError as exc:
        raise CoordinationError("invalid coordination policy") from exc
    if not isinstance(policy, dict) or policy.get("schema_version") != SCHEMA:
        raise CoordinationError("unsupported coordination policy")
    profiles = policy.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise CoordinationError("profiles are required")
    claimed: set[str] = set()
    _strings(policy.get("common_context", []), "common_context")
    for name, profile in profiles.items():
        if not isinstance(name, str) or not PROFILE_ID.fullmatch(name) or not isinstance(profile, dict):
            raise CoordinationError("invalid profile")
        if not isinstance(profile.get("label"), str) or not profile["label"].strip():
            raise CoordinationError("profile label is required")
        for action in _strings(profile.get("action_ids", []), "action_ids"):
            if action in claimed:
                raise CoordinationError(f"multiple primary coordinators: {action}")
            claimed.add(action)
        _strings(profile.get("context_pages", []), "context_pages")
        _strings(profile.get("front_refs", []), "front_refs")
        access = profile.get("access_requirements", [])
        if not isinstance(access, list):
            raise CoordinationError("access_requirements must be a list")
        for requirement in access:
            required = {"service", "expected_identity", "method", "source_ref"}
            descriptive = required | {"operation", "resource", "recovery"}
            if (not isinstance(requirement, dict)
                or not required <= set(requirement)
                or set(requirement) - descriptive - {"action_ids"}
                or any(not isinstance(v, str) or not v.strip()
                       for key, v in requirement.items() if key in descriptive)):
                raise CoordinationError("invalid access requirement")
            if "action_ids" in requirement:
                scoped = _strings(requirement["action_ids"], "access action_ids")
                if not scoped or not set(scoped) <= set(profile.get("action_ids", [])):
                    raise CoordinationError("access requirement belongs to another coordinator")
        _strings(profile.get("required_tools", []), "required_tools")
        if not isinstance(profile.get("scope"), str) or not profile["scope"].strip():
            raise CoordinationError("profile scope is required")
    return policy, hashlib.sha256(raw).hexdigest()


def coordination_index(root: Path, snapshot: dict[str, Any], *,
                       _profile_id: str | None = None, _action_id: str | None = None,
                       _authorize_ref: Callable[[str, str], None] | None = None,
                       _reader: RepositoryReader | None = None) -> dict[str, Any]:
    loaded = load_policy(root)
    result: dict[str, Any] = {"schema_version": SCHEMA, "configured": bool(loaded),
        "runtime_connected": False, "execution_ready": False,
        "policy_mode": "legacy_coordination_compatibility", "policy_enforced": False,
        "trust_boundary": "caller_trust", "coverage": "legacy_snapshot_or_memory_catalogue",
        "profiles": [], "actions": [], "unmapped_action_ids": [],
        "snapshot_id": snapshot.get("manifest.json", {}).get("snapshot_id", "")}
    pages = snapshot.get("pages.json", {}).get("pages", [])
    # A protected one-action context must not expand its authorized readset.
    if _authorize_ref is None and _profile_id is None and _reader is None:
        result.update(fronts_projection(root, pages, loaded[0]["profiles"] if loaded else {}, _read))
    if not loaded:
        return result
    policy, policy_sha = loaded
    result["policy_sha256"] = policy_sha
    by_id = {p["id"]: p for p in pages}
    if len(by_id) != len(pages):
        raise CoordinationError("duplicate canonical page identity")
    mapped = {}
    for name, profile in policy["profiles"].items():
        result["profiles"].append({"id": name, "label": profile["label"],
                                   "scope": profile["scope"], "action_ids": profile.get("action_ids", []),
                                   "front_refs": profile.get("front_refs", []),
                                   "access_requirements": profile.get("access_requirements", []),
                                   "required_tools": profile.get("required_tools", []), "access_verified": False})
        for action in profile.get("action_ids", []):
            if by_id.get(action, {}).get("page_type") != "action":
                raise CoordinationError(f"unknown canonical action: {action}")
            mapped[action] = name
    for p in pages:
        if p.get("page_type") != "action":
            continue
        if _profile_id is not None and (mapped.get(p["id"]) != _profile_id or p["id"] != _action_id):
            continue
        work = p.get("work") or {}
        if _authorize_ref:
            _authorize_ref(p["path"], p.get("content_sha256", ""))
        raw = _reader.read(p["path"])["content"] if _reader else _read(root, p["path"])
        if hashlib.sha256(raw).hexdigest() != p.get("content_sha256"):
            raise CoordinationError("action revision changed; refresh")
        fm, _ = parse_frontmatter(raw.decode("utf-8"))
        if fm.get("page_id") != p["id"] or fm.get("page_type") != "action":
            raise CoordinationError("canonical action identity mismatch")
        try:
            dialogue = dialogue_summary(fm.get("action_dialogue", []))
        except ValueError:
            raise CoordinationError("invalid_action_dialogue: " + p["id"]) from None
        result["actions"].append({"action_id": p["id"], "path": p["path"],
            "content_sha256": p.get("content_sha256"), "coordinator": mapped.get(p["id"]),
            "state": work.get("state"), "owner_ref": work.get("owner_ref"),
            "executor_label": fm.get("executor_label"), "execution_ready": False,
            "dialogue": dialogue})
        if p["id"] not in mapped:
            result["unmapped_action_ids"].append(p["id"])
    return result


def profile_packet_migration() -> dict[str, Any]:
    """Constant response: profile identity never authorizes task content."""
    return {"ok": False, "error_code": "coordination_context_required",
            "migration": {"required": ["context_id", "approved_revision", "content_revision", "task"],
                          "cli": "--context-id --approved-revision --revision --packet-request",
                          "endpoint": "/api/coordination/protected/packet"},
            "runtime_connected": False, "execution_ready": False}


def context_packet(root: Path, config: Any, snapshot: dict[str, Any] | None,
                   profile_id: str, action_id: str | None = None, *,
                   authorize_ref: Callable[[str, str], None] | None = None,
                   revision: str = "HEAD") -> dict[str, Any]:
    """Retired compatibility entry point; never reads caller-selected content."""
    return profile_packet_migration()


def dialogue_action(root: Path, page_ref: str, action_id: str, event: Any) -> dict[str, Any]:
    """Read one explicit action; IDs remain routing identities, never read grants."""
    from wiki_core.action_transition import _contained_action_path
    from wiki_core.config import load_config
    from wiki_core.paths import WikiPaths
    supplied = Path(page_ref)
    if supplied.is_absolute() or ".." in supplied.parts:
        raise CoordinationError("unsafe action path")
    path, page_ref = _contained_action_path(root, page_ref)
    actions = WikiPaths(root.resolve(), load_config(root)).actions_dir
    if not path.is_relative_to(actions):
        raise CoordinationError("action outside configured actions directory")
    validate_dialogue_route(root, page_ref, event)
    raw = _read(root, page_ref)
    fm, body = parse_frontmatter(raw.decode("utf-8"))
    if fm.get("page_id") != action_id:
        raise CoordinationError("canonical action identity mismatch")
    state = resolve_action_state(fm, legacy_state=legacy_action_state_from_body(body)).state
    return {"path": page_ref, "state": state}


def transition_dialogue_action(root: Path, page_ref: str, action_id: str, event: Any,
                               *, expected_sha256: str, as_operator: bool = False):
    """Validate the exact route inside the existing action transaction fence."""
    from wiki_core.action_transition import (
        _TRANSITION_LOCK, _action_file_lock, _contained_action_path,
        _transition_action_page_locked,
    )
    if not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise CoordinationError("invalid expected action revision")
    # Reject lexical escapes before normalizing the path for the writer lock.
    if Path(page_ref).is_absolute() or ".." in Path(page_ref).parts:
        raise CoordinationError("unsafe action path")
    _, canonical_ref = _contained_action_path(root, page_ref)
    with _TRANSITION_LOCK, _action_file_lock(root, canonical_ref):
        action = dialogue_action(root, canonical_ref, action_id, event)
        return _transition_action_page_locked(
            root, action["path"], action["state"], expected_sha256=expected_sha256,
            dialogue_event=event,
            dialogue_actor="operator" if as_operator else "coordinator:" + event["coordinator"],
            next_action=event.get("text") if event.get("kind") == "direction" else None)


def validate_dialogue_route(root: Path, page_ref: str, event: Any) -> None:
    """Validate the local adapter's route, never infer execution permission."""
    if not isinstance(event, dict):
        raise CoordinationError("invalid dialogue event")
    loaded = load_policy(root)
    if not loaded:
        raise CoordinationError("coordinator mapping required")
    fm, _ = parse_frontmatter(_read(root, page_ref).decode("utf-8"))
    profile = loaded[0]["profiles"].get(event.get("coordinator")) if isinstance(event.get("coordinator"), str) else None
    if fm.get("page_type") != "action" or not profile or fm.get("page_id") not in profile.get("action_ids", []):
        raise CoordinationError("action belongs to another coordinator")
