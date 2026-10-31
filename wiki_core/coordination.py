"""Read-only, revision-bound context for existing runtime coordinators.

This is an adapter over canonical pages, never a task store or dispatcher.
Runtime ownership, deduplication, STOP and execution admission remain with the
runtime. Preparing context is not evidence that an agent read or acted on it.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable

import yaml

from wiki_core.web.content import build_page_content
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
                       _authorize_ref: Callable[[str, str], None] | None = None) -> dict[str, Any]:
    loaded = load_policy(root)
    result: dict[str, Any] = {"schema_version": SCHEMA, "configured": bool(loaded),
        "runtime_connected": False, "execution_ready": False,
        "profiles": [], "actions": [], "unmapped_action_ids": [],
        "snapshot_id": snapshot.get("manifest.json", {}).get("snapshot_id", "")}
    pages = snapshot.get("pages.json", {}).get("pages", [])
    # A protected one-action context must not expand its authorized readset.
    if _authorize_ref is None and _profile_id is None:
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
        raw = _read(root, p["path"])
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


def context_packet(root: Path, config: Any, snapshot: dict[str, Any],
                   profile_id: str, action_id: str | None = None, *,
                   authorize_ref: Callable[[str, str], None] | None = None) -> dict[str, Any]:
    if authorize_ref and not action_id:
        raise CoordinationError("protected context requires an exact action")
    index = coordination_index(root, snapshot,
        _profile_id=profile_id if authorize_ref else None,
        _action_id=action_id, _authorize_ref=authorize_ref)
    loaded = load_policy(root)
    if not loaded or loaded[1] != index.get("policy_sha256"):
        raise CoordinationError("coordination policy missing or changed")
    policy, policy_sha = loaded
    if profile_id not in policy["profiles"]:
        raise CoordinationError("unknown coordinator")
    profile = policy["profiles"][profile_id]
    selected = profile.get("action_ids", [])
    if action_id:
        if action_id not in selected:
            raise CoordinationError("action belongs to another coordinator")
        selected = [action_id]
    pages = snapshot.get("pages.json", {}).get("pages", [])
    by_id = {p["id"]: p for p in pages}
    by_path = {p["path"]: p for p in pages}
    refs = policy.get("common_context", []) + profile.get("context_pages", []) + selected + [r["source_ref"] for r in profile.get("access_requirements", [])]
    required: dict[str, dict[str, Any]] = {}
    procedures: dict[str, bytes] = {}
    procedure_paths = []
    for ref in refs:
        page = by_id.get(ref) or by_path.get(ref)
        if page:
            if authorize_ref:
                authorize_ref(page["path"], page["content_sha256"])
            required[page["id"]] = page
        elif ref == "AGENTS.md" or (ref.startswith(".skills/") and ref.endswith("/SKILL.md")):
            if authorize_ref:
                authorize_ref(ref, "")
            procedure_paths.append(ref)
        else:
            raise CoordinationError(f"unknown context page: {ref}")
    # Expand the action's explicit context, parent and source relations one hop.
    # Do not recurse through a root hub and silently ingest the entire wiki.
    unresolved = []
    information_edges = []
    for action in selected:
        content = build_page_content(root, config, action, snapshot)
        if not content.get("ok"):
            raise CoordinationError("action revision changed; refresh")
        fm = content["frontmatter"]
        from wiki_core.information_relations import operational_consumption_edges
        def resolve_information(ref):
            matches = [p['path'] for p in pages if p['path'] == ref or p['id'] == ref]
            return sorted(set(matches))
        try:
            consumption = operational_consumption_edges(root, by_id[action]['path'], fm, content['body'], resolve_information)
        except ValueError as exc:
            raise CoordinationError(str(exc)) from exc
        for requirement in consumption:
            matches = resolve_information(requirement['target'])
            if len(matches) != 1:
                raise CoordinationError('information target missing or ambiguous')
            target = by_path[matches[0]]
            if authorize_ref:
                authorize_ref(target['path'], target['content_sha256'])
            required[target['id']] = target
            target_content = build_page_content(root, config, target['id'], snapshot)
            if not target_content.get('ok'):
                raise CoordinationError('information revision changed; refresh')
            evidence_refs = target_content['frontmatter'].get('evidence_refs', [])
            if not isinstance(evidence_refs, list) or any(not isinstance(ref, str) for ref in evidence_refs):
                raise CoordinationError('invalid information evidence references')
            pending_evidence=list(evidence_refs)
            loaded_evidence={target['path']}
            while pending_evidence:
                ref=pending_evidence.pop()
                matches = resolve_information(ref)
                if len(matches) != 1:
                    raise CoordinationError('information evidence missing or ambiguous')
                evidence = by_path[matches[0]]
                required[evidence['id']] = evidence
                if evidence['path'] in loaded_evidence:continue
                loaded_evidence.add(evidence['path'])
                if authorize_ref:
                    authorize_ref(evidence['path'],evidence['content_sha256'])
                evidence_content=build_page_content(root,config,evidence['id'],snapshot)
                if not evidence_content.get('ok'):
                    raise CoordinationError('information evidence revision changed; refresh')
                if evidence_content['frontmatter'].get('page_type')=='claim':
                    further=evidence_content['frontmatter'].get('evidence_refs',[])
                    if not isinstance(further,list) or any(not isinstance(item,str) for item in further):
                        raise CoordinationError('invalid information evidence references')
                    pending_evidence.extend(further)
            information_edges.append({**requirement, 'target': target['path']})
        for field in ("source_refs", "related_pages", "related_holons", "roles", "responsibilities", "claims", "decisions", "evidence_refs", "moc_parent"):
            values = fm.get(field, [])
            if isinstance(values, str):
                values = [values]
            if not isinstance(values, list) or any(not isinstance(ref, str) for ref in values):
                raise CoordinationError("invalid action context relation")
            for ref in values:
                page = by_id.get(ref) or by_path.get(ref)
                if page:
                    required[page["id"]] = page
                else:
                    unresolved.append({"action_id": action, "field": field, "ref": ref})
        for link in content.get("resolved_links", []):
            if link.get("kind") == "page" and link.get("page_id") in by_id:
                required[link["page_id"]] = by_id[link["page_id"]]
    # Resolve one hop using the already authorized action. Relations never grant
    # access: authorize the entire closure before reading any related body.
    if authorize_ref:
        if unresolved:
            raise CoordinationError("required context reference unresolved")
        for page in required.values():
            authorize_ref(page["path"], page["content_sha256"])
    for ref in procedure_paths:
        raw = _read(root, ref)
        if authorize_ref:
            authorize_ref(ref, hashlib.sha256(raw).hexdigest())
        procedures[ref] = raw
    contents = []
    for page in required.values():
        # Same boundaries and immutable hashes as the existing page reader.
        _read(root, page["path"])
        content = build_page_content(root, config, page["id"], snapshot)
        if not content.get("ok"):
            raise CoordinationError("context revision changed; refresh")
        contents.append({"id": page["id"], "path": page["path"],
                         "content_sha256": page["content_sha256"],
                         "frontmatter": content["frontmatter"], "body": content["body"]})
    packet = {"schema_version": SCHEMA, "profile": profile_id,
        "label": profile["label"], "scope": profile["scope"],
        "access_requirements": profile.get("access_requirements", []),
        "required_tools": profile.get("required_tools", []), "access_verified": False,
        "policy_sha256": policy_sha, "snapshot_id": index["snapshot_id"],
        "unresolved_context_refs": unresolved,
        "actions": [a for a in index["actions"] if a["action_id"] in selected],
        "pages": contents,
        "procedures": [{"path": path, "content_sha256": hashlib.sha256(raw).hexdigest(),
                        "body": raw.decode("utf-8")} for path, raw in procedures.items()],
        "runtime_connected": False, "execution_ready": False,
        "limits": ["Context prepared, not proof of agent reading or execution.",
                   "Coordinator is not the domain owner or executor.",
                   "Preserve STOP, waiting_human, terminal states and existing runtime reservations.",
                   "No automatic dispatch; runtime must validate context revisions and admission."]}
    if information_edges:
        from wiki_core.information_use import assess_information_use, bind_verification_coverage
        information_graph = {'nodes': {p['path']: p['frontmatter'] for p in contents},
                             'documents': {p['path']: p['body'] for p in contents},
                             'edges': information_edges, 'errors': []}
        information_graph = bind_verification_coverage(root, information_graph)
        # Preserve preparation of a refresh/history mission: readiness is a
        # separate assessment. The real dispatch boundary enforces it.
        packet['information_use'] = [assess_information_use(information_graph, by_id[action]['path'],
            now=dt.datetime.now(dt.timezone.utc)) for action in selected]
    # Refuse mixed revisions, including a policy/procedure edit during composition.
    if hashlib.sha256(_read(root, POLICY_FILE)).hexdigest() != policy_sha:
        raise CoordinationError("coordination policy changed; refresh")
    for content in contents:
        if hashlib.sha256(_read(root, content["path"])).hexdigest() != content["content_sha256"]:
            raise CoordinationError("context revision changed; refresh")
    for path, raw in procedures.items():
        if _read(root, path) != raw:
            raise CoordinationError("procedure changed; refresh")
    packet["context_sha256"] = digest(packet)
    return packet


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
