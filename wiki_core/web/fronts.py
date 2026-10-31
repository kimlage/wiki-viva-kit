"""A read-only view of canonical fronts, never a second backlog.

Projects/initiatives are discoverable without an executor. Coordination may
add references to differently typed context pages; all facts stay on those
pages. A document's date or assigned coordinator never proves live execution.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable

from wiki_core.frontmatter import list_values, parse_frontmatter


def fronts_projection(
    root: Path,
    pages: list[dict[str, Any]],
    profiles: dict[str, Any],
    read: Callable[[Path, str], bytes],
) -> dict[str, Any]:
    by_ref = {ref: page for page in pages for ref in (page["id"], page["path"])}
    selected = {p["id"]: p for p in pages if p.get("page_type") in {"project", "initiative"}}
    assigned: dict[str, set[str]] = {}
    action_profiles = {action: key for key, profile in profiles.items()
                       for action in profile.get("action_ids", [])}
    parent_actions: dict[str, list[dict[str, Any]]] = {}
    for action in pages:
        if action.get("page_type") == "action":
            parent = str((action.get("work") or {}).get("parent_ref") or "")
            parent_actions.setdefault(parent, []).append(action)
    warnings: list[dict[str, str]] = []
    for key, profile in profiles.items():
        for ref in profile.get("front_refs", []):
            page = by_ref.get(ref)
            if page is None:
                warnings.append({"code": "front_reference_unresolved", "ref": ref})
                continue
            selected[page["id"]] = page
            assigned.setdefault(page["id"], set()).add(key)

    fronts = []
    for page_id, page in sorted(selected.items()):
        try:
            raw = read(root, page["path"])
            if hashlib.sha256(raw).hexdigest() != page.get("content_sha256"):
                warnings.append({"code": "front_revision_changed", "ref": page_id})
                continue
            values, _ = parse_frontmatter(raw.decode("utf-8"))
        except (ValueError, OSError, UnicodeError):
            warnings.append({"code": "front_content_unavailable", "ref": page_id})
            continue
        if values.get("page_id") != page_id:
            warnings.append({"code": "front_identity_changed", "ref": page_id})
            continue
        actions = {}
        for ref in list_values(values.get("actions")):
            action = by_ref.get(ref)
            if action is None or action.get("page_type") != "action":
                warnings.append({"code": "front_action_unresolved", "ref": ref})
            else:
                actions[action["id"]] = action
        for ref in (page_id, page["path"]):
            for action in parent_actions.get(ref, []):
                actions[action["id"]] = action
        active = [action for action in actions.values()
                  if (action.get("work") or {}).get("state") not in {"done", "cancelled"}]
        coordinators = assigned.get(page_id, set()) | {
            action_profiles[action_id] for action_id in actions if action_id in action_profiles
        }
        # Editorial tags often preserve historical states. Only an explicit
        # current status is projected; no linked action can reopen its front.
        declared_status = str(values.get("status") or "unknown")
        fronts.append({
            "page_id": page_id, "path": page["path"], "title": page.get("title", page_id),
            "page_type": page.get("page_type", ""), "context": page.get("context", ""),
            "declared_status": declared_status,
            "recorded_at": str(values.get("verified_at") or page.get("updated_at") or ""),
            "owner_ref": str(values.get("owner_ref") or values.get("owner") or ""),
            "coordinators": sorted(coordinators), "action_ids": sorted(actions),
            "active_action_ids": sorted(action["id"] for action in active),
            "evidence_refs": list_values(values.get("evidence_refs")),
            "source_refs": list_values(values.get("source_refs")),
            "next_action": str(values.get("next_action") or "") or None,
            "blocker_reason": str(values.get("blocker_reason") or "") or None,
            "summary": str(page.get("summary") or ""),
            "content_sha256": page.get("content_sha256", ""),
            "live_execution": "unknown",
        })
    return {"fronts": fronts, "front_warnings": warnings}
