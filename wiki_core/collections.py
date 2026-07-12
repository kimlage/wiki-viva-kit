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

from dataclasses import dataclass
from typing import Any, Iterable

from wiki_core.frontmatter import list_values

COLLECTION_RELATION_TYPE = "collection_member"
COLLECTION_SPEC_KEYS = frozenset({"member_types", "members", "contexts"})


@dataclass(frozen=True)
class CollectionCompilation:
    """One immutable-inventory collection pass shared by snapshot payloads.

    The records inside each tuple remain ordinary JSON-shaped dictionaries,
    but the compilation itself is a single value: callers cannot accidentally
    recompute membership with different defaults between page counts, graph
    edges and diagnostics.
    """

    memberships: tuple[dict[str, str], ...]
    reference_diagnostics: tuple[dict[str, str], ...]
    cycle_diagnostics: tuple[dict[str, Any], ...]


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


def directed_cycle_paths(edges: Iterable[tuple[str, str]]) -> list[list[str]]:
    """Return deterministic actionable paths for directed cycles.

    Each path repeats its first node at the end (``a -> b -> a``), which makes
    the edge that must be removed visible to an author.  Rotations of the same
    directed cycle are canonicalized so input ordering cannot change the
    diagnostic.  The detector deliberately reports at least one path per
    cyclic component; it is a gate diagnostic, not an exponential enumeration
    of every possible simple cycle.
    """

    adjacency: dict[str, set[str]] = {}
    nodes: set[str] = set()
    for raw_source, raw_target in edges:
        source = str(raw_source or "").strip()
        target = str(raw_target or "").strip()
        if not source or not target:
            continue
        adjacency.setdefault(source, set()).add(target)
        nodes.update((source, target))

    state: dict[str, int] = {}
    cycles: set[tuple[str, ...]] = set()

    def canonical(path: list[str]) -> tuple[str, ...]:
        core = path[:-1]
        rotations = [core[index:] + core[:index] for index in range(len(core))]
        selected = min(tuple(rotation) for rotation in rotations)
        return (*selected, selected[0])

    for start in sorted(nodes):
        if state.get(start, 0) != 0:
            continue
        state[start] = 1
        path = [start]
        positions = {start: 0}
        frames = [(start, iter(sorted(adjacency.get(start, set()))))]
        while frames:
            _node, neighbors = frames[-1]
            try:
                target = next(neighbors)
            except StopIteration:
                frames.pop()
                completed = path.pop()
                positions.pop(completed, None)
                state[completed] = 2
                continue
            target_state = state.get(target, 0)
            if target_state == 0:
                state[target] = 1
                positions[target] = len(path)
                path.append(target)
                frames.append(
                    (target, iter(sorted(adjacency.get(target, set()))))
                )
            elif target_state == 1:
                cycle = path[positions[target] :] + [target]
                cycles.add(canonical(cycle))
    return [list(path) for path in sorted(cycles)]


def relation_cycle_diagnostics(
    edges: Iterable[dict[str, Any]],
    relation_types: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Detect cycles only for relation types that explicitly forbid them.

    Legacy vocabularies that omit ``allows_cycles`` are left readable: the
    contract opts into this stricter check only when the type says ``false``.
    Conversely, types such as authored citations or participation that declare
    ``allows_cycles: true`` remain valid even when reciprocal.
    """

    edges_by_type: dict[str, list[tuple[str, str]]] = {}
    for edge in edges:
        relation_type = str(edge.get("type") or "")
        definition = relation_types.get(relation_type) or {}
        if definition.get("allows_cycles") is not False:
            continue
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source and target:
            edges_by_type.setdefault(relation_type, []).append((source, target))

    diagnostics: list[dict[str, Any]] = []
    for relation_type in sorted(edges_by_type):
        for path in directed_cycle_paths(edges_by_type[relation_type]):
            diagnostics.append(
                {
                    "code": "forbidden_relation_cycle",
                    "relation_type": relation_type,
                    "cycle_path": path,
                    "cycle_path_text": " -> ".join(path),
                }
            )
    return diagnostics


def collection_cycle_diagnostics(
    pages: Iterable[dict[str, Any]],
    *,
    defaults_by_type: dict[str, dict[str, Any]] | None = None,
    allows_cycles: bool = False,
    memberships: Iterable[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Return collection cycles resolved through canonical page IDs and paths.

    Normal membership output continues to omit self-membership.  This audit
    view adds *explicitly authored* self-edges back solely for validation, so a
    silent ``collection_refs: [self]`` cannot bypass the vocabulary contract.
    A typed selector that includes the anchor's own page type still follows the
    compiler contract and excludes the anchor itself; it is not a real edge and
    therefore is not a cycle.
    """

    if allows_cycles:
        return []
    records = list(pages)
    defaults = defaults_by_type or {}
    compiled_memberships = (
        list(memberships)
        if memberships is not None
        else collection_memberships(
            records,
            defaults_by_type=defaults,
        )
    )
    membership_by_edge = {
        (str(item["member"]), str(item["collection"])): dict(item)
        for item in compiled_memberships
    }
    by_id = {str(page.get("id") or ""): page for page in records}
    for page in records:
        page_id = str(page.get("id") or "")
        if not page_id:
            continue
        spec = collection_spec(
            page,
            defaults.get(str(page.get("page_type") or "")),
        )
        if page_ref_matches(member_collection_refs(page), page):
            membership_by_edge.setdefault(
                (page_id, page_id),
                {
                    "member": page_id,
                    "collection": page_id,
                    "basis": "member.collection_refs",
                    "origin": "member",
                    "declaration_page": page_id,
                    "declaration_path": str(page.get("path") or ""),
                    "template_type": "",
                },
            )
        elif page_ref_matches(spec["members"], page):
            declared = _values(page).get("collection")
            declared = declared if isinstance(declared, dict) else {}
            origin = "collection_page" if "members" in declared else "template_default"
            membership_by_edge.setdefault(
                (page_id, page_id),
                {
                    "member": page_id,
                    "collection": page_id,
                    "basis": "collection.members",
                    "origin": origin,
                    "declaration_page": page_id,
                    "declaration_path": str(page.get("path") or ""),
                    "template_type": str(page.get("page_type") or "")
                    if origin == "template_default"
                    else "",
                },
            )

    diagnostics: list[dict[str, Any]] = []
    for path in directed_cycle_paths(membership_by_edge):
        page_paths = [
            str((by_id.get(page_id) or {}).get("path") or "")
            for page_id in path
        ]
        cycle_edges = [
            dict(membership_by_edge[(path[index], path[index + 1])])
            for index in range(len(path) - 1)
        ]
        diagnostics.append(
            {
                "code": "forbidden_collection_cycle",
                "relation_type": COLLECTION_RELATION_TYPE,
                "cycle_path": path,
                "cycle_path_text": " -> ".join(path),
                "page_paths": page_paths,
                "cycle_edges": cycle_edges,
            }
        )
    return diagnostics


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


def compile_collections(
    pages: Iterable[dict[str, Any]],
    *,
    defaults_by_type: dict[str, dict[str, Any]] | None = None,
    allows_cycles: bool = False,
) -> CollectionCompilation:
    """Compile membership and every derived diagnostic from one membership pass."""

    records = list(pages)
    defaults = defaults_by_type or {}
    memberships = collection_memberships(records, defaults_by_type=defaults)
    return CollectionCompilation(
        memberships=tuple(memberships),
        reference_diagnostics=tuple(
            collection_reference_diagnostics(
                records,
                defaults_by_type=defaults,
            )
        ),
        cycle_diagnostics=tuple(
            collection_cycle_diagnostics(
                records,
                defaults_by_type=defaults,
                allows_cycles=allows_cycles,
                memberships=memberships,
            )
        ),
    )
