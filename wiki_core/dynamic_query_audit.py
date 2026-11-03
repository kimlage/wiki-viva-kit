"""Explicit local authority for revision-bound query impact; no freshness certification."""
from __future__ import annotations
import re
import hashlib
import subprocess
from wiki_core.context_policy import PolicyError, load_policy, historical_policy, within
from wiki_core.context_selection import reproduce_query, select_query, requirement_query, same_selection, authority_digest
from wiki_core.information_relations import information_requirements
from wiki_core.repository_reader import RepositoryReader


def revalidate_affected(root, *, base, head, context_id, affected, changed, current):
    if not all(isinstance(x, str) and re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', x) for x in (base, head)):
        raise ValueError('fixed query base and head required')
    def git(*args):
        return subprocess.run(['git', '-C', str(root), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
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
    changed_policy = bool(normative & changed) or any(p == 'context.yaml' or p.endswith('/context.yaml') for p in changed)
    budget = [32_000_000]
    outcomes = []
    for row in affected:
        path, req = row['path'], row['requirement']
        try:
            if changed_policy: raise PolicyError('policy or normative input changed')
            if policy.owner_of(path) != context_id or not policy.permits(context_id, 'read', path):
                raise PolicyError('consumer outside authorized context')
            if path not in head_reader.paths: raise PolicyError('consumer removed')
            doc = head_reader.read(path)
            declared = information_requirements(doc['frontmatter'], lambda p: [p] if isinstance(p, str) and p in head_reader.paths else [])
            entry = requirement_query(req)
            replaced = req not in declared
            if replaced:
                if row['origin'] != 'base': raise PolicyError('query declaration differs from HEAD')
                # A canonical base declaration can be superseded only by the
                # same exact collection contract, verified independently below.
                compatible = any('query' in x and all(x.get(k) == req.get(k) for k in ('target', 'query', 'use', 'classification')) for x in declared)
                if not compatible: raise PolicyError('query declaration removed or changed')
                if git('merge-base', '--is-ancestor', req['consumed_revision'], req['query_policy_revision']).returncode:
                    raise PolicyError('query content is not an ancestor of its policy')
                historical = historical_policy(policy, req['query_policy_revision'])
                if authority_digest(historical, context_id, entry) != req['authority_digest']:
                    raise PolicyError('historical query authority differs')
                # Do not open historical member blobs under revoked authority.
                # The current replacement is separately recomputed as its own row.
                continue
            prior, _, _ = reproduce_query(policy, context_id, RepositoryReader(root, req['consumed_revision']), entry,
                policy_revision=req['query_policy_revision'], expected_authority=req['authority_digest'], read_budget=budget)
            if any(prior[k] != req[k] for k in ('members_digest', 'selected_digest')):
                raise PolicyError('query receipt cannot be reproduced')
            at_base, _, _ = select_query(policy, context_id, base_reader, entry, read_budget=budget)
            at_head, _, _ = select_query(policy, context_id, head_reader, entry, read_budget=budget)
            if any(path in {m['ref'] for m in selection['members']} for selection in (prior, at_base, at_head)):
                raise PolicyError('query consumer cannot be a member')
            if not same_selection(prior, at_base): raise PolicyError('approved query needs reread')
            if not same_selection(prior, at_head):
                if path in changed: raise PolicyError('changed consumer requires equivalent selection')
                outcomes.append({'path': path, 'state': 'review_pending', 'reason': 'dynamic_query_changed',
                    'seed': next((p for p in sorted(changed) if p == path or p == req['target'] or within(p, req['query']['scope'])), path),
                    'fields': ['*'], 'causes': [], 'chain': [],
                    'priority': 'immediate', 'verification_performed': False})
        except (ValueError, KeyError, TypeError, OSError):
            outcomes.append({'path': path, 'state': 'unknown', 'reason': 'dynamic_query_requires_authorized_revalidation', 'seed': path})
    policy.fresh()
    if git('rev-parse', '--verify', 'HEAD').stdout.decode().strip() != head:
        raise ValueError('query head changed during evaluation')
    return outcomes
