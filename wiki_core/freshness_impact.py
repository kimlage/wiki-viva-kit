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

from wiki_core.traversal import wiki_markdown_files
from wiki_core.git_env import local_git_environment, local_git_executable
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
    files = sorted(wiki_markdown_files(root / str(config.paths["memory_root"]), wiki_root=root))
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


def _query_policy_change_marker(root: Path, revisions: tuple[str, str], changed: set[str]) -> set[str]:
    """Treat a changed declared normative input as policy-sensitive, without granting authority."""
    import subprocess
    import yaml
    from wiki_core.context_policy import UniqueLoader, safe_path, is_context_policy_change
    if not changed:
        return set()
    if any(is_context_policy_change(path) for path in changed):
        return {'context.yaml'}
    normative = set()
    for revision in revisions:
        listing = subprocess.run([local_git_executable(), '--no-lazy-fetch', '-C', str(root), 'ls-tree', '-r', '--name-only', '-z', revision], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=local_git_environment())
        if listing.returncode:
            return {'context.yaml'}
        for raw in listing.stdout.split(b'\0'):
            if not raw or not (raw == b'context.yaml' or raw.endswith(b'/context.yaml')):
                continue
            try:
                path = raw.decode('utf-8')
                source = subprocess.run([local_git_executable(), '--no-lazy-fetch', '-C', str(root), 'show', revision + ':' + path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=local_git_environment())
                if source.returncode:
                    return {'context.yaml'}
                doc = yaml.load(source.stdout, Loader=UniqueLoader)
                if not isinstance(doc, dict):
                    return {'context.yaml'}
                for key in ('instructions', 'skills', 'templates'):
                    values = doc.get(key, [])
                    if not isinstance(values, list):
                        return {'context.yaml'}
                    normative.update(safe_path(value) for value in values)
            except (UnicodeError, ValueError, TypeError, yaml.YAMLError):
                return {'context.yaml'}
    return {'context.yaml'} if normative & changed else set()


def _merge_pending_fields(included, pending_fields):
    """Keep already discovered rows consistent when pending scope widens."""
    by_path = {row['path']: row for row in included}
    for path in set(pending_fields) & by_path.keys():
        fields = set(by_path[path]['fields']) | pending_fields[path]
        by_path[path]['fields'] = ['*'] if '*' in fields else sorted(fields)
    return by_path


def repository_report(root: Path, config: WikiConfig, base_ref: str, *,
                      today: dt.date | None = None,
                      documentary_only: dict[str, str] | None = None,
                      freshness_reviews: dict[str, dict[str, str]] | None = None,
                      query_mode: str | None = None,
                      query_context: str | None = None, query_policy_revision: str | None = None,
                      query_head: str | None = None) -> dict[str, Any]:
    """Freeze one ancestor SHA; reuse exact-base Git inventory/materialization.

    Fail closed on missing Git/base, unreadable inputs or concurrent edits. An
    unchanged tree reports debt but has no freshness blockers; maintenance uses
    the legacy global budget mode. Global audit checks run in either mode.
    """
    from scripts.wiki_page_graph import project_memory_at_commit, collect_git_changes, run_git

    query_options = (query_context, query_policy_revision, query_head)
    if query_mode not in (None, 'v1') or (any(query_options) and query_mode != 'v1'):
        raise ValueError('query audit requires explicit v1 mode; folder query audit unavailable')
    if query_mode is not None and not all(query_options):
        raise ValueError('v1 query audit requires context, approved revision and head')
    if query_mode == 'v1' and config.audit.get('information_impact', 'legacy') != 'use_scoped':
        raise ValueError('v1 query audit requires use-scoped information impact')
    if not base_ref:
        raise ValueError("impact freshness requires audit.freshness_base or --freshness-base")
    base_sha = run_git(["rev-parse", "--verify", f"{base_ref}^{{commit}}"], root=root).strip()
    head = run_git(["rev-parse", "--verify", "HEAD"], root=root).strip()
    run_git(["merge-base", "--is-ancestor", base_sha, head], root=root)
    before = input_hashes(root, config)
    changes = collect_git_changes(base_sha, root=root)
    current = authored_graph(root, config)
    base = project_memory_at_commit(base_sha,
        lambda temp, cfg: authored_graph(temp,cfg,normative_root=root,normative_revision=base_sha), root=root)
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
                if e["type"] in REFERENCE | {"historical_support", "operational_prerequisite", "projection_state", "projection"}
                and e.get('requirement',{}).get('source_kind') != 'mandatory' and e["target"] in tracked} - memory_paths
    for edge in current['edges']:
        if (edge['type']=='projection' and edge['target'] not in memory_paths and edge['target'] not in tracked):
            current['errors'].append(f"{edge['path']}: projection input must be a tracked repository artifact: {edge['target']}")
    before.update({p: h for p, h in input_hashes(root, config, evidence).items() if p in evidence})
    for graph in (base, current):
        graph["evidence_paths"] = evidence
        graph["missing_evidence"] = {p for p in evidence if before[p] is None}
        graph["nodes"].update({p: {} for p in evidence})
        # Track a declared external rule as metadata only, so its changed Git
        # path seeds traversal without reading its body as factual evidence.
        for edge in graph['edges']:
            if edge.get('requirement',{}).get('source_kind') == 'mandatory':
                graph['nodes'].setdefault(edge['target'],{})
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
        from wiki_core.information_impact import evaluate_information_impact, typed_information_reach
        has_queries = any('query' in edge.get('requirement', {}) for graph in (base, current) for edge in graph['edges'])
        impact_changed = changed | (_query_policy_change_marker(root, (base_sha, head), changed) if has_queries else set())
        typed_reasons = typed_information_reach(current, base, impact_changed) if has_queries else {}
        result = evaluate_information_impact(current, base, impact_changed, today=today or dt.date.today(), _typed_reasons=typed_reasons)
        if any((query_context, query_policy_revision, query_head)):
            if not all((query_context, query_policy_revision, query_head)) or query_policy_revision != base_sha or query_head != head:
                raise ValueError('query audit requires exact context, approved base and HEAD')
            from wiki_core.information_impact import affected_dynamic_queries
            from wiki_core.dynamic_query_audit import revalidate_affected
            affected = affected_dynamic_queries(current, base, impact_changed, set(typed_reasons))
            closure_budget = [32_000_000]
            selection_cache = {}  # Local to this exact, fenced audit only.
            outcomes = revalidate_affected(root, base=base_sha, head=head, context_id=query_context,
                                           affected=affected, changed=impact_changed, current=current, read_budget=closure_budget, _selection_cache=selection_cache)
            # Dynamic outcomes are review obligations, not edits to their pages.
            # Feed those obligations into typed dependencies and authorized
            # downstream queries until no new pending fields are discovered.
            from wiki_core.information_impact import propagate_pending_dependencies, authorized_typed_provenance
            from wiki_core.context_policy import load_policy
            closure_policy = load_policy(root, base_sha)
            pending_fields = {r['path']: set(r.get('fields', ['*'])) for r in outcomes if r['state'] == 'review_pending'}
            derived = {}; denied = set(); ordinary_sources = {}
            # The generic graph already propagated ordinary impacts. Use those
            # rows only to discover affected queries, never to rerun ordinary
            # traversal or change the global caller-trust audit boundary.
            from wiki_core.context_policy import within
            from wiki_core.information_relations import dependency_edges
            query_contracts = []
            for graph in (base, current):
                for edge in dependency_edges(graph)[0]:
                    req = edge.get('requirement', {})
                    if ('query' in req and closure_policy.owner_of(edge['dependent']) == query_context
                            and closure_policy.permits(query_context, 'read', edge['dependent'])):
                        query_contracts.append((req['target'], req['query']['scope']))
            # Recompute provenance from only explicit current-consumption
            # edges. The original global report remains unchanged; its legacy
            # reach is not permission or proof of scoped current consumption.
            for path, row in typed_reasons.items():
                if path not in current['nodes'] or not row['causes']: continue
                if not any(path == anchor or within(path, scope) for anchor, scope in query_contracts): continue
                if closure_policy.owner_of(path) == query_context and closure_policy.permits(query_context, 'read', path):
                    if authorized_typed_provenance(path, typed_reasons, closure_policy, query_context):
                        ordinary_sources.setdefault(path, set()).update(row.get('fields', ['*']))
                    else:
                        denied.add(path)
            if len(ordinary_sources) > 1000: raise ValueError('dynamic impact closure limit exceeded')
            all_outcomes = {(r['path'], r['reason'], r.get('requirement_id')): r for r in outcomes}
            if pending_fields or ordinary_sources:
                for _ in range(64):
                    expanded, reached, boundary = propagate_pending_dependencies(current, base, pending_fields, closure_policy, query_context)
                    denied.update(boundary)
                    for path, causes in reached.items():
                        existing = derived.setdefault(path, [])
                        for cause in causes:
                            if cause not in existing: existing.append(cause)
                    query_sources = {path: set(fields) for path, fields in expanded.items()}
                    for path, fields in ordinary_sources.items(): query_sources.setdefault(path, set()).update(fields)
                    affected = affected_dynamic_queries(current, base, impact_changed | set(query_sources), set(query_sources))
                    more = revalidate_affected(root, base=base_sha, head=head, context_id=query_context,
                        affected=affected, changed=impact_changed, current=current, pending_sources=query_sources, read_budget=closure_budget, _selection_cache=selection_cache)
                    for row in more: all_outcomes[(row['path'], row['reason'], row.get('requirement_id'))] = row
                    new_fields = {p: set(v) for p, v in expanded.items()}
                    for row in more:
                        if row['state'] == 'review_pending': new_fields.setdefault(row['path'], set()).update(row.get('fields', ['*']))
                    if new_fields == pending_fields: break
                    pending_fields = new_fields
                else:
                    raise ValueError('dynamic impact closure limit exceeded')
            closure_policy.fresh()
            result['integrity_blockers'] = [r for r in result['integrity_blockers'] if r['reason'] != 'dynamic_query_requires_authorized_revalidation']
            result['integrity_blockers'].extend(r for r in all_outcomes.values() if r['state'] == 'unknown')
            result['integrity_blockers'].extend({'path': p, 'reason': 'dynamic_impact_authority_boundary'} for p in sorted(denied))
            result['pending_reviews'].extend(r for r in all_outcomes.values() if r['state'] == 'review_pending')
            existing_pending = {r['path']: r for r in result['pending_reviews']}
            for path, causes in sorted(derived.items()):
                if path not in existing_pending:
                    row = {'path':path, 'state':'review_pending', 'reason':'upstream_interpretation_pending',
                        'seed':causes[0]['prerequisite'], 'fields':sorted(pending_fields[path]), 'causes':[], 'chain':[],
                        'priority':'immediate', 'verification_performed':False}
                    result['pending_reviews'].append(row); existing_pending[path] = row
                for cause in causes:
                    if cause not in existing_pending[path].setdefault('causes', []): existing_pending[path]['causes'].append(cause)
            # Every pending reason for a page must expose the full potentially
            # affected field set, not just the first path that reached it.
            for row in result['pending_reviews']:
                if row['path'] in pending_fields:
                    fields = set(row.get('fields', [])) | pending_fields[row['path']]
                    row['fields'] = ['*'] if '*' in fields else sorted(fields)
            included = _merge_pending_fields(result['included'], pending_fields)
            for path in sorted(set(pending_fields) - included.keys()):
                causes = derived.get(path, [])
                row = {'path':path, 'seed':causes[0]['prerequisite'] if causes else path, 'distance':None,
                    'fields':sorted(pending_fields[path]), 'causes':[], 'chain':[]}
                result['included'].append(row); included[path] = row
            for path, causes in derived.items():
                for cause in causes:
                    if cause not in included[path].setdefault('causes', []): included[path]['causes'].append(cause)
            result['ok'] = not result['integrity_blockers'] and not result['relation_errors']
            result['query_revalidation'] = {'context': query_context, 'policy_revision': base_sha, 'head': head,
                'affected': len(affected), 'fact_freshness': 'not_assessed',
                'audit_authority': 'global_integrator_caller_trust',
                'context_scope': 'query_recomputation_only_not_auditor_acl'}
        from wiki_core.information_use import bind_verification_coverage, assess_information_use
        qualified = bind_verification_coverage(root,current)
        if all((query_context,query_policy_revision,query_head)):
            from wiki_core.information_use import bind_normative_coverage
            qualified=bind_normative_coverage(root,qualified,closure_policy,query_context,head=head)
            result['query_revalidation']['normative_scope']='selected_context_only_not_auditor_acl'
        usage=[]
        for path, values in current['nodes'].items():
            if values.get('action_state') not in {'open','in_progress'}:continue
            assessment=assess_information_use(qualified,path,now=dt.datetime.combine(today,dt.time(12),dt.timezone.utc)
                if today is not None else dt.datetime.now(dt.timezone.utc))
            if assessment['requirements']:
                usage.append(assessment)
                for requirement in assessment['requirements']:
                    if not requirement['ready']:
                        result['pending_reviews'].append({'path':path,'seed':requirement['target'],
                            'fields':requirement['fields'],'causes':[],'chain':[],
                            'state':'review_pending','priority':'immediate','reason':'current_information_unusable',
                            'blockers':requirement['blockers'],'verification_performed':False})
        result['information_use'] = usage
        result['blockers'] = [{**r, 'state': 'unknown', 'seed': r['path']} for r in result['integrity_blockers']]
        result['unrelated_debt'] = []  # ordinary age diagnostics remain in the frontmatter audit
        result['removed_pages'] = sorted(set(base['nodes']) - set(current['nodes']))
        result['evaluated_on'] = (today or dt.date.today()).isoformat()
    else:
        if any((query_context, query_policy_revision, query_head)):
            raise ValueError("query audit requires use-scoped information impact")
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
