"""Explicit local authority for revision-bound query impact; no freshness certification."""
from __future__ import annotations
import re
import hashlib
import json
import subprocess
from wiki_core.context_policy import PolicyError, load_policy, historical_policy, within, is_context_policy_change
from wiki_core.context_selection import reproduce_query, select_query, requirement_query, same_selection, authority_digest
from wiki_core.information_relations import information_requirements
from wiki_core.repository_reader import RepositoryReader
from wiki_core.git_env import local_git_environment, local_git_executable


def revalidate_affected(root, *, base, head, context_id, affected, changed, current, pending_sources=None, read_budget=None, _selection_cache=None):
    if not all(isinstance(x, str) and re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', x) for x in (base, head)):
        raise ValueError('fixed query base and head required')
    def git(*args):
        return subprocess.run([local_git_executable(), '--no-lazy-fetch', '-C', str(root), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=local_git_environment())
    if git('rev-parse', '--verify', 'HEAD').stdout.decode().strip() != head:
        raise ValueError('query head differs from HEAD')
    if (git('diff', '--quiet', '--').returncode or git('diff', '--cached', '--quiet', '--').returncode
            or git('ls-files', '--others', '--exclude-standard', '-z').stdout):
        raise ValueError('query audit requires a clean worktree and index')
    tracked = set(git('ls-files', '-z').stdout.decode().split('\0'))
    if not set(current['documents']) <= tracked:
        raise ValueError('query audit graph contains untracked or ignored documents')
    # Bind the graph's actual parsed documents to the exact Git tree.  Hashes
    # compare already-read graph bytes without opening additional Git blobs.
    tree = git('ls-tree', '-r', '-z', head)
    if tree.returncode: raise ValueError('query head tree unavailable')
    blobs = {}
    for raw in tree.stdout.split(b'\0'):
        if not raw: continue
        meta, path = raw.split(b'\t', 1)
        mode, kind, oid = meta.split(b' ', 2)
        if kind == b'blob' and mode in (b'100644', b'100755'):
            blobs[path.decode('utf-8')] = oid.decode('ascii')
    from wiki_core.frontmatter import parse_frontmatter
    from wiki_core.information_relations import semantic_equal
    digest = hashlib.sha1 if len(head) == 40 else hashlib.sha256
    for path, document in current['documents'].items():
        data = document.encode('utf-8')
        actual = digest(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        if blobs.get(path) != actual or not semantic_equal(parse_frontmatter(document)[0], current['nodes'][path]):
            raise ValueError('query audit graph differs from exact HEAD')
    policy = load_policy(root, base)
    if context_id not in policy.contexts:
        raise ValueError('query context unavailable')
    base_reader, head_reader = RepositoryReader(root, base), RepositoryReader(root, head)
    normative = {p for c in policy.contexts.values() for k in ('instructions', 'skills', 'templates') for p in c[k]}
    changed_policy = bool(normative & changed) or any(is_context_policy_change(p) for p in changed)
    budget = read_budget if read_budget is not None else [32_000_000]
    outcomes = []
    pending_sources = pending_sources or {}
    selection_cache = _selection_cache if _selection_cache is not None else {}
    for row in affected:
        path, req = row['path'], row['requirement']
        requirement_id = hashlib.sha256(json.dumps(req, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()
        try:
            if req.get('query_contract') is not None:
                raise PolicyError('versioned query receipt requires its own authority')
            if changed_policy and path in changed: raise PolicyError('consumer and policy or normative input changed together')
            if policy.owner_of(path) != context_id or not policy.permits(context_id, 'read', path):
                raise PolicyError('consumer outside authorized context')
            cache_key = ('row', base, head, context_id, tuple(sorted(changed)), json.dumps(row, sort_keys=True, ensure_ascii=False))
            cached = selection_cache.get(cache_key)
            if cached is None:
                if path not in head_reader.paths: raise PolicyError('consumer removed')
                doc = head_reader.read(path)
                declared = information_requirements(doc['frontmatter'], lambda p: [p] if isinstance(p, str) and p in head_reader.paths else [])
                entry = requirement_query(req)
                replaced = req not in declared
                if replaced:
                    if row['origin'] != 'base': raise PolicyError('query declaration differs from HEAD')
                    compatible = any('query' in x and all(x.get(k) == req.get(k) for k in ('target', 'query', 'use', 'classification')) for x in declared)
                    if not compatible: raise PolicyError('query declaration removed or changed')
                    if git('merge-base', '--is-ancestor', req['consumed_revision'], req['query_policy_revision']).returncode:
                        raise PolicyError('query content is not an ancestor of its policy')
                    historical = historical_policy(policy, req['query_policy_revision'])
                    if authority_digest(historical, context_id, entry) != req['authority_digest']:
                        raise PolicyError('historical query authority differs')
                    # The replacement is checked independently; no revoked blobs are opened.
                    cached = ('replaced',)
                else:
                    proof_fields = ('target', 'query', 'use', 'classification', 'consumed_revision',
                        'query_policy_revision', 'authority_digest', 'members_digest', 'selected_digest')
                    proof_key = ('query', base, head, context_id, changed_policy,
                        json.dumps({k: req[k] for k in proof_fields}, sort_keys=True, ensure_ascii=False))
                    proof = selection_cache.get(proof_key)
                    if proof is None:
                        prior_candidates = []
                        prior, _, _ = reproduce_query(policy, context_id, RepositoryReader(root, req['consumed_revision']), entry,
                            policy_revision=req['query_policy_revision'], expected_authority=req['authority_digest'], read_budget=budget, _candidate_refs=prior_candidates)
                        if any(prior[k] != req[k] for k in ('members_digest', 'selected_digest')):
                            raise PolicyError('query receipt cannot be reproduced')
                        if base_reader.revision == req['consumed_revision']:
                            at_base, base_candidates = prior, prior_candidates
                        else:
                            base_candidates = []
                            at_base = select_query(policy, context_id, base_reader, entry, read_budget=budget, _candidate_refs=base_candidates)[0]
                        if changed_policy: at_head, head_candidates = None, []
                        elif head_reader.revision == base_reader.revision: at_head, head_candidates = at_base, base_candidates
                        elif head_reader.revision == req['consumed_revision']: at_head, head_candidates = prior, prior_candidates
                        else:
                            head_candidates = []
                            at_head = select_query(policy, context_id, head_reader, entry, read_budget=budget, _candidate_refs=head_candidates)[0]
                        proof = (prior, at_base, at_head, head_candidates)
                    prior, at_base, at_head, head_candidates = proof
                    checks = (prior, at_base) if at_head is None else (prior, at_base, at_head)
                    if any(path in {m['ref'] for m in selection['members']} for selection in checks):
                        raise PolicyError('query consumer cannot be a member')
                    selection_cache[proof_key] = proof
                    cached = ('selection', prior, at_base, at_head, head_candidates)
                # Cache only successfully established proof within this audit operation.
                selection_cache[cache_key] = cached
            if cached[0] == 'replaced': continue
            _, prior, at_base, at_head, head_candidates = cached
            if changed_policy:
                outcomes.append({'path': path, 'state': 'review_pending', 'reason': 'dynamic_query_requalification_required',
                    'seed': path, 'query_id': prior['query_id'], 'requirement_id': requirement_id, 'fields': ['*'], 'causes': [], 'chain': [], 'priority': 'immediate',
                    'verification_performed': False})
                continue
            filter_fields = set(req['query']['filters'])
            if 'field' in req['query']: selected_fields = {req['query']['field']}
            elif 'section' in req['query']: selected_fields = {'body'}
            else: selected_fields = {'*'}
            members = {m['ref'] for m in at_head['members']}
            upstream = []
            for ref, has_page_id in head_candidates:
                pending = pending_sources.get(ref, set())
                interested = filter_fields | selected_fields | {'page_id'} if ref in members else filter_fields | (set() if has_page_id else {'page_id'})
                if pending and ('*' in pending or '*' in interested or pending & interested): upstream.append(ref)
            # The anchor is a separately consumed mandatory collection contract.
            if req['target'] in pending_sources: upstream.append(req['target'])
            selection_changed = not same_selection(prior, at_base) or not same_selection(prior, at_head)
            if selection_changed or upstream:
                if path in changed: raise PolicyError('changed consumer requires equivalent selection')
                outcomes.append({'path': path, 'state': 'review_pending', 'reason': 'dynamic_query_changed' if selection_changed else 'dynamic_query_upstream_pending',
                    'seed': next((p for p in sorted(changed) if p == path or p == req['target'] or within(p, req['query']['scope'])), path) if selection_changed else upstream[0],
                    'query_id': prior['query_id'], 'requirement_id': requirement_id, 'fields': ['*'], 'causes': [], 'chain': [],
                    'priority': 'immediate', 'verification_performed': False})
        except (ValueError, KeyError, TypeError, OSError):
            outcomes.append({'path': path, 'state': 'unknown', 'reason': 'dynamic_query_requires_authorized_revalidation', 'seed': path})
    policy.fresh()
    if git('rev-parse', '--verify', 'HEAD').stdout.decode().strip() != head:
        raise ValueError('query head changed during evaluation')
    return outcomes
