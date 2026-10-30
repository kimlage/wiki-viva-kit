"""Change-scoped freshness, using the existing authored relation contracts.

No page/type exemptions: structural edges do not propagate factual freshness.
Untyped Markdown citations remain conservative dependencies. This report is
private operational evidence (paths/IDs), not a sanitized public export.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import posixpath
from urllib.parse import unquote, urlsplit
import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from wiki_core.config import WikiConfig
from wiki_core.freshness import freshness_state, is_stale_exempt
from wiki_core.frontmatter import list_values, parse_frontmatter
from wiki_core.graph.page_graph import FRONTMATTER_REF_FIELDS, MARKDOWN_LINK_RE
from wiki_core.markdown_link_roles import parse_role_markdown, project_link_role
from wiki_core.semantic_inventory import (
    RELATION_DIRECTIONS, _authored_pages, _expected_relations, _page_indexes,
)

from wiki_core.information_relations import (
    STRUCTURAL, ASSOCIATION, REFERENCE, NAVIGATION_HEADINGS,
    _path_from_link, _body_occurrences, authored_graph, dependency_edges,
)


def factual_changes(current: dict, base: dict, changed: set[str]) -> tuple[set[str], list[dict]]:
    """Separate native communication from incorporation of factual content.

    WHOLE continues to consume every factual assertion and dependency of an
    action. A received, unincorporated comment does not change those assertions.
    Complete document bytes remain in the readset and Git diff.
    No edge is removed: another factual seed still reaches the old content and
    its original freshness date.
    """
    from wiki_core.action_transition import operational_comment_receipt
    factual = set(changed)
    comments = []
    for path in sorted(set(changed) & base["documents"].keys() & current["documents"].keys()):
        receipt = operational_comment_receipt(base["documents"][path], current["documents"][path])
        if receipt is not None:
            factual.remove(path)
            comments.append({"path": path, **receipt})
    return factual, comments


def evaluate_impact(
    current: dict[str, Any], base: dict[str, Any], changed: set[str], *, today: dt.date,
    documentary_only: dict[str, str] | None = None,
    freshness_reviews: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Dependents of changes, then prerequisites; never fan out from shared sources."""
    declarations = documentary_only or {}
    # An exact-path review may also classify a referenced tracked input. A
    # retired input qualifies only after all current factual citations to it
    # are gone; historical edges remain and another factual seed still reaches
    # its missing-evidence blocker. Memory-page deletion never qualifies.
    reviewable = (base["documents"].keys() & current["documents"].keys()) | current.get("reviewable_evidence", set())
    if not isinstance(declarations, dict) or any(
        path not in changed or path not in reviewable
        or not isinstance(reason, str) or not reason.strip()
        for path, reason in declarations.items()
    ):
        raise ValueError("documentary-only review requires changed existing paths and a rationale")
    for path in declarations:
        for field in ("updated_at", "stale_after_days", "stale_exempt"):
            if current["nodes"][path].get(field) != base["nodes"][path].get(field):
                raise ValueError("documentary-only edits cannot renew dates or change freshness policy")
    changed, comments = factual_changes(current, base, changed)
    # An independently reviewed proposal may classify an edit as documentary.
    # This suppresses only its initial seed, never its factual dependencies or
    # a review obligation reached from another changed source.
    changed -= declarations.keys()
    nodes = current["nodes"]
    all_paths = set(nodes) | set(base["nodes"])
    seeds = sorted((changed & all_paths) | (set(base["nodes"]) - set(nodes)))
    edges: list[dict[str, Any]] = []
    nonpropagating = []
    for origin, graph in (("base", base), ("current", current)):
        dependencies, contextual = dependency_edges(graph, origin=origin)
        edges.extend(dependencies)
        nonpropagating.extend(contextual)
    edges.sort(key=lambda e: (e["prerequisite"], e["dependent"], e["type"],
                              e["path"], e["field"], e["origin"]))
    downstream: dict[str, list[dict]] = defaultdict(list)
    upstream: dict[str, list[dict]] = defaultdict(list)
    for edge in edges:
        downstream[edge["prerequisite"]].append(edge)
        upstream[edge["dependent"]].append(edge)
    reasons = {p: dict(reason="changed_page", seed=p, via=None, chain=[]) for p in seeds}

    def expand(start, adjacency: dict, endpoint: str, phase: str) -> None:
        queue = deque(start)
        visited = set(start)
        while queue:
            parent = queue.popleft()
            for edge in adjacency[parent]:
                target = edge[endpoint]
                if target in visited:
                    continue
                reasons.setdefault(target, dict(reason=phase, seed=reasons[parent]["seed"],
                    via=parent, chain=[*reasons[parent]["chain"], edge]))
                visited.add(target)
                queue.append(target)

    expand(seeds, downstream, "dependent", "affected_dependent")
    # Required evidence never starts a new downstream traversal into siblings.
    expand(sorted(reasons), upstream, "prerequisite", "required_dependency")

    def verdict(path: str) -> str:
        if path in current.get("evidence_paths", set()):
            return "source_artifact" if path not in current.get("missing_evidence", set()) else "unknown"
        values = nodes[path]
        return freshness_state(values.get("updated_at"), values.get("stale_after_days"),
                               today, stale_exempt=is_stale_exempt(values.get("stale_exempt")))

    included = [dict(path=p, state=verdict(p) if p in nodes else "removed", **reasons[p])
                for p in sorted(reasons)]
    debt = [dict(path=p, state=verdict(p), reason="outside_change_dependency_closure")
            for p in sorted(set(nodes) - set(reasons)) if verdict(p) in {"stale", "unknown"}]
    # Age is still reported. A proposal can resolve an age finding only through
    # an explicit, independently reviewed disposition with fresh, changed
    # evidence citing this exact page. It never cuts graph traversal or makes
    # an old source fresh. Unknown evidence is not reviewable this way.
    reviews = freshness_reviews or {}
    if not isinstance(reviews, dict):
        raise ValueError("freshness review must be a mapping")
    included_by_path = {row["path"]: row for row in included}
    reviewed = []
    for path, review in sorted(reviews.items()):
        if (path not in current["documents"] or path not in base["documents"]
                or included_by_path.get(path, {}).get("state") != "stale"):
            raise ValueError(f"freshness review requires an existing stale page in the closure: {path}")
        if (not isinstance(review, dict)
                or set(review) != {"disposition", "evidence", "rationale", "limits"}
                or any(not isinstance(value, str) or not value.strip() for value in review.values())
                or review["disposition"] not in {"historical", "verified_local", "verified_live", "known_gap"}):
            raise ValueError(f"freshness review requires disposition, evidence, rationale and limits: {path}")
        for field in ("updated_at", "stale_after_days", "stale_exempt"):
            if nodes[path].get(field) != base["nodes"][path].get(field):
                raise ValueError(f"freshness review cannot renew dates or change freshness policy: {path}")
        evidence = review["evidence"]
        if (evidence == path or evidence not in changed
                or evidence not in current["documents"] or verdict(evidence) != "fresh"
                or not any(edge["source"] == evidence and edge["target"] == path
                           and edge["type"] in REFERENCE for edge in current["edges"])):
            raise ValueError(f"freshness review needs fresh changed evidence citing the exact page: {path}")
        reviewed.append({**included_by_path[path], **review})
    blockers = [r for r in included if r["state"] in {"stale", "unknown"} and r["path"] not in reviews]
    result = dict(schema_version="wiki_freshness_impact.v1", evaluated_on=today.isoformat(),
                seeds=seeds, included=included, blockers=blockers, unrelated_debt=debt,
                removed_pages=sorted(set(base["nodes"]) - set(nodes)),
                nonpropagating_relations=nonpropagating,
                relation_errors=current["errors"], base_relation_diagnostics=base["errors"],
                ok=not blockers and not current["errors"])
    if reviewed:
        result["reviewed_findings"] = reviewed
    if comments:
        result["operational_comments"] = comments
    if declarations:
        result["documentary_only"] = declarations
    return result


def input_hashes(root: Path, config: WikiConfig, evidence_paths=()) -> dict[str, str | None]:
    files = sorted((root / str(config.paths["memory_root"])).rglob("*.md"))
    files.append(root / "wiki.config.yaml")
    result = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in files}
    from wiki_core.source_integrity import _worktree_entry
    for ref in sorted(evidence_paths):
        path = root / ref
        if path.exists() or path.is_symlink():
            result[ref] = hashlib.sha256(_worktree_entry(root, "100755" if path.stat().st_mode & 0o111 else "100644", ref)).hexdigest()
        else:
            result[ref] = None
    return result


def repository_report(root: Path, config: WikiConfig, base_ref: str, *,
                      today: dt.date | None = None,
                      documentary_only: dict[str, str] | None = None,
                      freshness_reviews: dict[str, dict[str, str]] | None = None) -> dict[str, Any]:
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
    changed = set(changes.paths)
    # Referenced tracked artifacts are ordinary source dependencies, without a
    # separately authored hash registry. Retain old links when an artifact or
    # citation is removed. Ignored caches and external URLs remain source-owner
    # concerns; they cannot become implicit inputs through a Markdown link.
    base_tracked = set(run_git(["ls-tree", "-r", "--name-only", "-z", base_sha], root=root).split("\0"))
    tracked = set(base_tracked)
    tracked.update(run_git(["ls-files", "-z"], root=root).split("\0"))
    memory_paths = set(current["nodes"]) | set(base["nodes"])
    evidence = {e["target"] for g in (base, current) for e in g["edges"]
                if e["type"] in REFERENCE | {"historical_support", "operational_prerequisite", "projection_state"} and e["target"] in tracked} - memory_paths
    before.update({p: h for p, h in input_hashes(root, config, evidence).items() if p in evidence})
    for graph in (base, current):
        graph["evidence_paths"] = evidence
        graph["missing_evidence"] = {p for p in evidence if before[p] is None}
        graph["nodes"].update({p: {} for p in evidence})
    current_citations = {e["target"] for e in current["edges"] if e["type"] in REFERENCE}
    current["reviewable_evidence"] = {
        p for p in evidence & base_tracked
        if before[p] is not None or p not in current_citations
    }
    if config.audit.get("freshness_records"):
        raise ValueError("freshness_records is retired; remove the pointer after reviewing the migration diff")
    information_policy = config.audit.get("information_impact", "legacy")
    if information_policy not in {"legacy", "shadow", "use_scoped"}:
        raise ValueError("information_impact must be legacy, shadow or use_scoped")
    if information_policy == "use_scoped":
        if documentary_only or freshness_reviews:
            raise ValueError("use-scoped impact does not accept per-proposal freshness waivers")
        from wiki_core.information_impact import evaluate_information_impact
        result = evaluate_information_impact(current, base, changed, today=today or dt.date.today())
        result['blockers'] = [{**r, 'state': 'unknown', 'seed': r['path']} for r in result['integrity_blockers']]
        result['unrelated_debt'] = []  # ordinary age diagnostics remain in the frontmatter audit
        result['removed_pages'] = sorted(set(base['nodes']) - set(current['nodes']))
        result['evaluated_on'] = (today or dt.date.today()).isoformat()
    else:
        result = evaluate_impact(current, base, changed, today=today or dt.date.today(),
                                 documentary_only=documentary_only, freshness_reviews=freshness_reviews)
        if information_policy == "shadow":
            from wiki_core.information_impact import evaluate_information_impact
            result["information_impact"] = evaluate_information_impact(
                current, base, changed, today=today or dt.date.today())
    if (before != input_hashes(root, config, evidence)
            or changes != collect_git_changes(base_sha, root=root)
            or head != run_git(["rev-parse", "--verify", "HEAD"], root=root).strip()):
        raise ValueError("freshness inputs changed during evaluation; rerun on stable inputs")
    result.update(base_sha=base_sha, head_sha=head, input_sha256=before,
                  changed_paths=sorted(changes.paths), untracked_paths=sorted(changes.untracked_paths))
    return result
