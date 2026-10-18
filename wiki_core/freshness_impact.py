"""Change-scoped freshness, using the existing authored relation contracts.

No page/type exemptions: structural edges do not propagate factual freshness.
Untyped Markdown citations remain conservative dependencies. This report is
private operational evidence (paths/IDs), not a sanitized public export.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from wiki_core.config import WikiConfig
from wiki_core.freshness import freshness_state, is_stale_exempt
from wiki_core.frontmatter import list_values, parse_frontmatter
from wiki_core.graph.page_graph import FRONTMATTER_REF_FIELDS, _markdown_body_links
from wiki_core.semantic_inventory import (
    RELATION_DIRECTIONS, _authored_pages, _expected_relations, _page_indexes,
)

# These are relation semantics, never exemptions for whole pages or contexts.
STRUCTURAL = frozenset({"moc_parent", "collection_member", "ownership", "participation"})
REFERENCE = frozenset({"source_ref", "related_page", "markdown_link", "untyped_reference"})


def authored_graph(root: Path, config: WikiConfig) -> dict[str, Any]:
    """Project the existing semantic-inventory model plus real Markdown body links."""
    pages = _authored_pages(root, config)
    _unique_by_id, by_path, duplicates = _page_indexes(pages)
    # Current duplicates block as integrity errors. Historical duplicates must
    # still be readable when the proposed change repairs them. Resolve ambiguous
    # IDs conservatively to every authored path instead of dropping their edges.
    by_id = {p.page_id: p for p in reversed(pages)}
    paths_by_id: dict[str, list[str]] = defaultdict(list)
    for page in pages:
        paths_by_id[page.page_id].append(page.path)
    # Source emission duplicates the source_ref dependency in the same direction;
    # the inventory's optional event expansion is unnecessary for this closure.
    relations, unresolved = _expected_relations(pages, by_id, by_path, {})
    edges = []
    errors = list(duplicates) + list(unresolved)
    for source, target, kind, direction, basis, _pid, path, field in sorted(relations):
        if direction != RELATION_DIRECTIONS[kind]:
            errors.append(f"{path}: invalid relation direction in {field}")
            continue
        for a in paths_by_id[source]:
            for b in paths_by_id[target]:
                edges.append(dict(source=a, target=b, type=kind, direction=direction,
                                  basis=basis, path=path, field=field))
    for page in pages:
        file = root / page.path
        if file.is_symlink():
            errors.append(f"{page.path}: symlink memory cannot establish freshness evidence")
        _values, body = parse_frontmatter(file)
        represented = {e["field"] for e in edges if e["path"] == page.path}
        for field in FRONTMATTER_REF_FIELDS:
            if field in represented:
                continue
            targets = set()
            for ref in list_values(page.values.get(field)):
                targets.update([ref] if ref in by_path else paths_by_id.get(ref, []))
            for target in sorted(targets):
                if field == "owner":
                    edges.append(dict(source=target, target=page.path, type="ownership",
                                      direction="directed", basis="frontmatter", path=page.path,
                                      field=field))
                    continue
                # Untyped reachability metadata is not silently discarded.
                edges.append(dict(source=page.path, target=target, type="untyped_reference",
                                  direction="directed", basis="frontmatter", path=page.path,
                                  field=field))
        for target in _markdown_body_links(root, page.path, body):
            if target not in by_path:
                # Non-memory documents are checked by the global link auditor.
                continue
            edges.append(dict(source=page.path, target=target, type="markdown_link",
                              direction="directed", basis="markdown_body", path=page.path,
                              field="body"))
    return {"nodes": {p.path: p.values for p in pages}, "edges": edges,
            "errors": sorted(set(errors))}


def evaluate_impact(
    current: dict[str, Any], base: dict[str, Any], changed: set[str], *, today: dt.date,
) -> dict[str, Any]:
    """Dependents of changes, then prerequisites; never fan out from shared sources."""
    nodes = current["nodes"]
    all_paths = set(nodes) | set(base["nodes"])
    seeds = sorted((changed & all_paths) | (set(base["nodes"]) - set(nodes)))
    edges: list[dict[str, Any]] = []
    nonpropagating = []
    for origin, graph in (("base", base), ("current", current)):
        for raw in graph["edges"]:
            edge = {**raw, "origin": origin}
            kind = edge["type"]
            if kind in STRUCTURAL:
                nonpropagating.append({**edge, "reason": "structural_relation"})
                continue
            # Normalize factual dependency as prerequisite -> dependent.
            a, b = edge["source"], edge["target"]
            prerequisite, dependent = (b, a) if kind in REFERENCE else (a, b)
            edges.append({**edge, "prerequisite": prerequisite, "dependent": dependent})
    edges.sort(key=lambda e: (e["prerequisite"], e["dependent"], e["type"],
                              e["path"], e["field"], e["origin"]))
    downstream: dict[str, list[dict]] = defaultdict(list)
    upstream: dict[str, list[dict]] = defaultdict(list)
    for edge in edges:
        downstream[edge["prerequisite"]].append(edge)
        upstream[edge["dependent"]].append(edge)
    reasons = {p: dict(reason="changed_page", seed=p, via=None, chain=[]) for p in seeds}

    def expand(start: list[str], adjacency: dict, endpoint: str, phase: str) -> None:
        queue = deque(start)
        visited = set(start)
        while queue:
            parent = queue.popleft()
            for edge in adjacency[parent]:
                target = edge[endpoint]
                if target not in reasons:
                    reasons[target] = dict(reason=phase, seed=reasons[parent]["seed"],
                                           via=parent, chain=[*reasons[parent]["chain"], edge])
                if target not in visited:
                    visited.add(target)
                    queue.append(target)

    expand(seeds, downstream, "dependent", "affected_dependent")
    expand(sorted(reasons), upstream, "prerequisite", "required_dependency")

    def verdict(path: str) -> str:
        values = nodes[path]
        return freshness_state(values.get("updated_at"), values.get("stale_after_days"),
                               today, stale_exempt=is_stale_exempt(values.get("stale_exempt")))

    included = [dict(path=p, state=verdict(p) if p in nodes else "removed", **reasons[p])
                for p in sorted(reasons)]
    debt = [dict(path=p, state=verdict(p), reason="outside_change_dependency_closure")
            for p in sorted(set(nodes) - set(reasons)) if verdict(p) != "fresh"]
    blockers = [r for r in included if r["state"] in {"stale", "unknown"}]
    return dict(schema_version="wiki_freshness_impact.v1", evaluated_on=today.isoformat(),
                seeds=seeds, included=included, blockers=blockers, unrelated_debt=debt,
                removed_pages=sorted(set(base["nodes"]) - set(nodes)),
                nonpropagating_relations=nonpropagating,
                relation_errors=current["errors"], base_relation_diagnostics=base["errors"],
                ok=not blockers and not current["errors"])


def input_hashes(root: Path, config: WikiConfig) -> dict[str, str]:
    files = sorted((root / str(config.paths["memory_root"])).rglob("*.md"))
    files.append(root / "wiki.config.yaml")
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in files}


def repository_report(root: Path, config: WikiConfig, base_ref: str, *,
                      today: dt.date | None = None) -> dict[str, Any]:
    """Freeze one ancestor SHA; reuse exact-base Git inventory/materialization.

    Fail closed on missing Git/base, unreadable inputs or concurrent edits. An
    unchanged tree reports debt but has no freshness blockers; maintenance uses
    the legacy global budget mode. Global audit checks run in either mode.
    """
    from scripts.wiki_page_graph import project_memory_at_commit, collect_git_changes, run_git

    if not base_ref:
        raise ValueError("impact freshness requires audit.freshness_base or --freshness-base")
    base_sha = run_git(["rev-parse", "--verify", f"{base_ref}^{{commit}}"], root=root).strip()
    head = run_git(["rev-parse", "--verify", "HEAD"], root=root).strip()
    run_git(["merge-base", "--is-ancestor", base_sha, head], root=root)
    before = input_hashes(root, config)
    changes = collect_git_changes(base_sha, root=root)
    current = authored_graph(root, config)
    base = project_memory_at_commit(base_sha, authored_graph, root=root)
    result = evaluate_impact(current, base, set(changes.paths), today=today or dt.date.today())
    if (before != input_hashes(root, config)
            or changes != collect_git_changes(base_sha, root=root)
            or head != run_git(["rev-parse", "--verify", "HEAD"], root=root).strip()):
        raise ValueError("freshness inputs changed during evaluation; rerun on stable inputs")
    result.update(base_sha=base_sha, head_sha=head, input_sha256=before,
                  changed_paths=sorted(changes.paths), untracked_paths=sorted(changes.untracked_paths))
    return result
