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

# These are relation semantics, never exemptions for whole pages or contexts.
STRUCTURAL = frozenset({"moc_parent", "collection_member", "ownership", "participation"})
ASSOCIATION = frozenset({"related_page", "related_holon", "navigation_link", "record_context_reference"})
REFERENCE = frozenset({"source_ref", "markdown_link", "untyped_reference"})
NAVIGATION_HEADINGS = frozenset({"related", "relacionados", "navigation", "navegação"})


def _path_from_link(root: Path, source_rel: str, href: str) -> str | None:
    """Lexical repository link; never follow a symlink while discovering sources."""
    parsed = urlsplit(href)
    if parsed.scheme or parsed.netloc or not parsed.path or parsed.path.endswith("/"):
        return None
    path = unquote(parsed.path)
    if "\\" in path or any(ord(c) < 32 for c in path):
        return None
    relative = posixpath.normpath(path.lstrip("/") if path.startswith("/")
                                 else posixpath.join(posixpath.dirname(source_rel), path))
    return relative if relative != ".." and not relative.startswith("../") else None


def _body_occurrences(root: Path, path: str, body: str, navigation_targets: set[str]):
    """Exclude only complete, positively parsed navigation list items.

    Keep the existing conservative link inventory (including uncertain syntax)
    and use CommonMark block/inline structure solely to prove navigation. A
    nested heading cannot change the enclosing section, and a factual occurrence
    elsewhere in the same page is never suppressed by matching endpoints.
    """
    tokens, authored_roles = parse_role_markdown(body)
    sections = []
    navigation_ranges = []
    section = ""
    top_list = None
    for index, token in enumerate(tokens):
        if token.type == "heading_open" and token.level == 0:
            section = tokens[index + 1].content.strip().casefold()
            sections.append((token.map[0], section))
        if token.level == 0 and token.type in {"bullet_list_open", "ordered_list_open"}:
            top_list = token.type
        if token.level == 0 and token.type in {"bullet_list_close", "ordered_list_close"}:
            top_list = None
        if not (token.type == "list_item_open" and token.level == 1
                and top_list == "bullet_list_open" and section in NAVIGATION_HEADINGS):
            continue
        end = index + 1
        while not (tokens[end].type == "list_item_close" and tokens[end].level == 1):
            end += 1
        item = tokens[index + 1:end]
        if [part.type for part in item] != ["paragraph_open", "inline", "paragraph_close"]:
            continue
        depth = 0
        links = 0
        link_only = True
        children = item[1].children or []
        # Existing MOC conventions also declare structural navigation in the
        # body. This is an exact relation label, not arbitrary text before ':';
        # Evidence/Source/Responsibility labels do not receive this treatment.
        explicit_moc = (bool(children) and children[0].type == "text"
                        and children[0].content.strip().casefold()
                        in {"moc:", "parent moc:", "moc pai:"})
        for child in children[1:] if explicit_moc else children:
            if child.type == "link_open":
                depth += 1
                links += 1
            elif child.type == "link_close":
                depth -= 1
            elif depth:
                continue  # Labels may contain formatting; they are still labels.
            elif child.type in {"softbreak", "hardbreak"}:
                continue
            elif child.type != "text" or re.sub(r"[\s,;.·|/()—–-]", "", child.content):
                link_only = False
        if link_only and links and depth == 0:
            navigation_ranges.append((*token.map, explicit_moc,
                                      children[0].content.strip() if explicit_moc else None))

    for match in MARKDOWN_LINK_RE.finditer(body):
        target = _path_from_link(root, path, match.group(1))
        if not target:
            continue
        line = body[:match.start()].count("\n")
        section = next((title for start, title in reversed(sections) if start <= line), "")
        matched = [(explicit, label) for start, end, explicit, label in navigation_ranges
                   if start <= line < end]
        explicit_moc = any(explicit for explicit, _label in matched)
        navigation = bool(matched) and (explicit_moc or target in navigation_targets)
        edge = dict(source=path, target=target,
                   type="navigation_link" if navigation else "markdown_link",
                   direction="directed", basis="markdown_body", path=path, field="body",
                   body_line=line + 1, body_offset=match.start(), section=section,
                   body_relation_label=next((label for explicit, label in matched if explicit), None),
                   classification=("explicit_body_moc_navigation" if navigation and explicit_moc
                                   else "local_typed_navigation_item" if navigation
                                   else "conservative_citation"))
        yield project_link_role(edge, authored_roles.get((match.start(), match.end())))

    # Reference-style links are real dependencies too. Their destination is
    # stored in a definition elsewhere, so the legacy inline regex misses them.
    for token_index, token in enumerate(tokens):
        if token.type != "inline" or token.map is None:
            continue
        for child_index, child in enumerate(token.children or []):
            if child.type != "link_open" or "label" not in child.meta:
                continue
            target = _path_from_link(root, path, child.attrGet("href") or "")
            if not target:
                continue
            # Conservative occurrence location is the entire inline block.
            # Reference-definition edits are separately a whole-page delta.
            edge = dict(source=path, target=target, type="markdown_link",
                       direction="directed", basis="markdown_body", path=path, field="body",
                       body_line=token.map[0] + 1,
                       body_offset=f"commonmark:{token_index}:{child_index}",
                       section=next((title for start, title in reversed(sections)
                                     if start <= token.map[0]), ""),
                       classification="reference_style_citation")
            yield project_link_role(edge, authored_roles.get(child.meta.get("_wiki_body_link_span")))


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
                if field == "related_holons":
                    # The authored template-block contract uses this field for
                    # contextual reach (relations/culture), separately from
                    # source_refs/evidence. It does not assert factual support.
                    edges.append(dict(source=page.path, target=target, type="related_holon",
                                      direction="directed", basis="frontmatter", path=page.path,
                                      field=field))
                    continue
                if field == "owner":
                    edges.append(dict(source=target, target=page.path, type="ownership",
                                      direction="directed", basis="frontmatter", path=page.path,
                                      field=field))
                    continue
                # Untyped reachability metadata is not silently discarded.
                edges.append(dict(source=page.path, target=target, type="untyped_reference",
                                  direction="directed", basis="frontmatter", path=page.path,
                                  field=field))
        navigation_targets = {
            e["target"] if e["source"] == page.path else e["source"]
            for e in edges if e["path"] == page.path
            and e["type"] in STRUCTURAL | {"related_page", "related_holon"}
            and page.path in {e["source"], e["target"]}
        }
        for occurrence in _body_occurrences(root, page.path, body, navigation_targets):
            edges.append(occurrence)
    return {"documents": {p.path: (root / p.path).read_bytes().decode("utf-8") for p in pages},
            "nodes": {p.path: p.values for p in pages}, "edges": edges,
            "errors": sorted(set(errors))}


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
        for raw in graph["edges"]:
            edge = {**raw, "origin": origin}
            kind = edge["type"]
            if kind in STRUCTURAL:
                nonpropagating.append({**edge, "reason": "structural_relation"})
                continue
            if kind in ASSOCIATION:
                nonpropagating.append({**edge, "reason": "association_or_explicit_navigation"})
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
                if e["type"] in REFERENCE and e["target"] in tracked} - memory_paths
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
    result = evaluate_impact(current, base, changed, today=today or dt.date.today(),
                             documentary_only=documentary_only, freshness_reviews=freshness_reviews)
    if (before != input_hashes(root, config, evidence)
            or changes != collect_git_changes(base_sha, root=root)
            or head != run_git(["rev-parse", "--verify", "HEAD"], root=root).strip()):
        raise ValueError("freshness inputs changed during evaluation; rerun on stable inputs")
    result.update(base_sha=base_sha, head_sha=head, input_sha256=before,
                  changed_paths=sorted(changes.paths), untracked_paths=sorted(changes.untracked_paths))
    return result
