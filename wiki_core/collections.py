"""Deterministic collection membership without rewriting canonical hierarchy.

``moc_parent`` answers *where a page lives*.  A collection answers *which
index/subworld also owns it for navigation*.  The two relations are deliberately
orthogonal: a page may keep one canonical parent while belonging to any number
of declared collections.

Collections can declare members from either side:

* member-side ``collection_refs: [collection-page-id]``;
* collection-side ``collection.members: [member-page-id]``;
* collection-side typed membership through ``collection.member_types``.

Typed membership defaults to the collection page's context.  A collection must
declare ``contexts: ['*']`` to span every context, which keeps broad indexes
explicit and reviewable.
"""

from __future__ import annotations

from typing import Any, Iterable

from wiki_core.frontmatter import list_values

COLLECTION_RELATION_TYPE = "collection_member"
COLLECTION_SPEC_KEYS = frozenset({"member_types", "members", "contexts"})


def validate_collection_declaration(page: dict[str, Any]) -> list[str]:
    """Validate the page-level authoring shape without resolving references."""

    values = _values(page)
    errors: list[str] = []
    if "collection_refs" in values and not isinstance(values.get("collection_refs"), list):
        errors.append("collection_refs must be a list")
    if "collection_ref" in values and not isinstance(values.get("collection_ref"), str):
        errors.append("collection_ref must be a string")
    if "collection" not in values:
        return errors
    declared = values.get("collection")
    if not isinstance(declared, dict):
        errors.append("collection must be an object")
        return errors
    for key in sorted(set(declared) - COLLECTION_SPEC_KEYS):
        errors.append(f"collection has unknown key `{key}`")
    for key in sorted(COLLECTION_SPEC_KEYS & set(declared)):
        if not isinstance(declared.get(key), list):
            errors.append(f"collection.{key} must be a list")
    return errors


def _values(page: dict[str, Any]) -> dict[str, Any]:
    raw = page.get("values")
    return raw if isinstance(raw, dict) else page


def page_ref_matches(value: Any, page: dict[str, Any]) -> bool:
    """Return whether ``value`` contains the page's canonical id or path."""

    refs = set(list_values(value))
    return bool({str(page.get("id") or ""), str(page.get("path") or "")} & refs)


def collection_spec(
    page: dict[str, Any], default: dict[str, Any] | None = None
) -> dict[str, list[str]]:
    """Return a normalized collection contract, page declaration winning.

    The merge is intentionally shallow and list-shaped.  It is deterministic,
    serializable and sufficient for the three supported membership modes.
    """

    declared = _values(page).get("collection")
    merged: dict[str, Any] = dict(default or {})
    if isinstance(declared, dict):
        merged.update(declared)
    return {
        "member_types": sorted(set(list_values(merged.get("member_types")))),
        "members": sorted(set(list_values(merged.get("members")))),
        "contexts": sorted(set(list_values(merged.get("contexts")))),
    }


def member_collection_refs(page: dict[str, Any]) -> list[str]:
    values = _values(page)
    return sorted(
        set(
            [
                *list_values(values.get("collection_ref")),
                *list_values(values.get("collection_refs")),
            ]
        )
    )


def _context_matches(
    anchor: dict[str, Any], target: dict[str, Any], contexts: list[str]
) -> bool:
    if "*" in contexts:
        return True
    target_context = str(target.get("context") or "")
    if contexts:
        return target_context in contexts
    return bool(target_context) and target_context == str(anchor.get("context") or "")


def collection_membership_basis(
    anchor: dict[str, Any],
    target: dict[str, Any],
    *,
    default: dict[str, Any] | None = None,
) -> str | None:
    """Explain why ``target`` belongs to ``anchor``, or return ``None``.

    Explicit member-side links win over collection-side enumeration, which wins
    over a typed collection query.  The precedence makes emitted provenance
    stable when more than one declaration describes the same membership.
    """

    if str(anchor.get("id") or "") == str(target.get("id") or ""):
        return None
    if page_ref_matches(member_collection_refs(target), anchor):
        return "member.collection_refs"

    spec = collection_spec(anchor, default)
    if page_ref_matches(spec["members"], target):
        return "collection.members"
    if (
        str(target.get("page_type") or "") in spec["member_types"]
        and _context_matches(anchor, target, spec["contexts"])
    ):
        return "collection.member_types"
    return None


def collection_memberships(
    pages: Iterable[dict[str, Any]],
    *,
    defaults_by_type: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    """Compile all memberships in near-linear time for snapshot generation."""

    records = list(pages)
    defaults = defaults_by_type or {}
    by_ref: dict[str, dict[str, Any]] = {}
    by_type: dict[str, list[dict[str, Any]]] = {}
    for page in records:
        for ref in (str(page.get("id") or ""), str(page.get("path") or "")):
            if ref:
                by_ref.setdefault(ref, page)
        by_type.setdefault(str(page.get("page_type") or ""), []).append(page)

    memberships: dict[tuple[str, str], dict[str, str]] = {}

    def add(
        member: dict[str, Any],
        anchor: dict[str, Any],
        basis: str,
        *,
        origin: str,
        declaration: dict[str, Any],
    ) -> None:
        member_id = str(member.get("id") or "")
        anchor_id = str(anchor.get("id") or "")
        if not member_id or not anchor_id or member_id == anchor_id:
            return
        key = (member_id, anchor_id)
        memberships.setdefault(
            key,
            {
                "member": member_id,
                "collection": anchor_id,
                "basis": basis,
                "origin": origin,
                "declaration_page": str(declaration.get("id") or ""),
                "declaration_path": str(declaration.get("path") or ""),
                "template_type": str(anchor.get("page_type") or "")
                if origin == "template_default"
                else "",
            },
        )

    # Strongest declaration first: member-side explicit references.
    for member in records:
        for ref in member_collection_refs(member):
            anchor = by_ref.get(ref)
            if anchor is not None:
                add(
                    member,
                    anchor,
                    "member.collection_refs",
                    origin="member",
                    declaration=member,
                )

    for anchor in records:
        declared = _values(anchor).get("collection")
        declared = declared if isinstance(declared, dict) else {}
        spec = collection_spec(
            anchor, defaults.get(str(anchor.get("page_type") or ""))
        )
        for ref in spec["members"]:
            member = by_ref.get(ref)
            if member is not None:
                add(
                    member,
                    anchor,
                    "collection.members",
                    origin="collection_page"
                    if "members" in declared
                    else "template_default",
                    declaration=anchor,
                )
        for page_type in spec["member_types"]:
            for member in by_type.get(page_type, []):
                if _context_matches(anchor, member, spec["contexts"]):
                    add(
                        member,
                        anchor,
                        "collection.member_types",
                        origin="collection_page"
                        if "member_types" in declared
                        else "template_default",
                        declaration=anchor,
                    )

    return [memberships[key] for key in sorted(memberships)]


def collection_reference_diagnostics(
    pages: Iterable[dict[str, Any]],
    *,
    defaults_by_type: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    """Return unresolved explicit collection references instead of dropping them."""

    records = list(pages)
    defaults = defaults_by_type or {}
    known_refs = {
        ref
        for page in records
        for ref in (str(page.get("id") or ""), str(page.get("path") or ""))
        if ref
    }
    diagnostics: list[dict[str, str]] = []
    for member in records:
        for ref in member_collection_refs(member):
            if ref not in known_refs:
                diagnostics.append(
                    {
                        "code": "unresolved_collection_ref",
                        "page_id": str(member.get("id") or ""),
                        "path": str(member.get("path") or ""),
                        "field": "collection_refs",
                        "ref": ref,
                        "origin": "member",
                    }
                )
    for anchor in records:
        declared = _values(anchor).get("collection")
        declared = declared if isinstance(declared, dict) else {}
        spec = collection_spec(
            anchor, defaults.get(str(anchor.get("page_type") or ""))
        )
        for ref in spec["members"]:
            if ref not in known_refs:
                diagnostics.append(
                    {
                        "code": "unresolved_collection_member",
                        "page_id": str(anchor.get("id") or ""),
                        "path": str(anchor.get("path") or ""),
                        "field": "collection.members",
                        "ref": ref,
                        "origin": "collection_page"
                        if "members" in declared
                        else "template_default",
                    }
                )
    return sorted(
        diagnostics,
        key=lambda item: (item["path"], item["field"], item["ref"]),
    )
