"""Narrow, revision-bound context policy. Policy describes intent, not enforcement.

Scopes are repository-relative directory/file prefixes, never globs. ``self``
means the declaring context's root. The caller must supply an independently
approved Git revision; a commit identifier alone is not proof of approval.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
from pathlib import Path, PurePosixPath


class PolicyError(ValueError):
    pass


def safe_path(value: str) -> str:
    if not isinstance(value, str) or not value or '\\' in value or value.startswith('/'):
        raise PolicyError('invalid relative path')
    parts = value.split('/')
    if any(x in ('', '.', '..') for x in parts) or any(c in value for c in '*?[]'):
        raise PolicyError('invalid relative path')
    return str(PurePosixPath(value))


def within(path: str, scope: str) -> bool:
    return path == scope or path.startswith(scope + '/')


def _git(root: Path, *args: str) -> bytes:
    p = subprocess.run(['git', '-C', str(root), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode:
        raise PolicyError('Git revision or path unavailable')
    return p.stdout


def revision(root: Path, ref: str) -> str:
    if not isinstance(ref, str) or not ref or ref.startswith('-'):
        raise PolicyError('invalid revision')
    sha = _git(root, 'rev-parse', '--verify', ref + '^{commit}').decode().strip()
    if not re.fullmatch(r'[0-9a-f]{40,64}', sha):
        raise PolicyError('invalid commit')
    return sha


def git_file(root: Path, rev: str, path: str) -> bytes:
    path = safe_path(path)
    # Inspect each tree component: Git symlink blobs must never be traversed.
    parts = path.split('/')
    for i in range(1, len(parts) + 1):
        prefix = '/'.join(parts[:i])
        entry = _git(root, 'ls-tree', rev, '--', prefix).decode().strip()
        if not entry or entry.startswith('120000 ') or entry.startswith('160000 '):
            raise PolicyError('missing or unsafe Git path')
    return _git(root, 'show', f'{rev}:{path}')


def _list(value, name):
    if not isinstance(value, list) or any(not isinstance(x, str) or not x for x in value):
        raise PolicyError(f'{name} must be a list of nonempty strings')
    if len(value) != len(set(value)):
        raise PolicyError(f'duplicate {name}')
    return value


def _scope(value, root):
    if value == 'self':
        return root
    if value.startswith('self/'):
        return safe_path(root + '/' + value[5:])
    return safe_path(value)


def _keys(obj, allowed, required, label):
    if not isinstance(obj, dict) or set(obj) - set(allowed) or set(required) - set(obj):
        raise PolicyError(f'invalid {label} fields')


class ContextPolicy:
    def __init__(self, document, policy_revision):
        _keys(document, {'schema_version', 'contexts'}, {'schema_version', 'contexts'}, 'document')
        if document['schema_version'] != 'wiki.context/v1' or not isinstance(document['contexts'], list):
            raise PolicyError('invalid context document')
        self.policy_revision = policy_revision
        self.contexts = {}
        self.effective = {}
        for c in document['contexts']:
            _keys(c, {'id','parent','root','purpose','owner','instructions','skills','templates','policy','imports','exports','workflow','defaults'}, {'id','parent','root','purpose','owner','instructions','skills','templates','policy','imports','exports'}, 'context')
            if not isinstance(c['id'], str) or not re.fullmatch(r'[a-z0-9][a-z0-9/_-]*', c['id']) or c['id'] in self.contexts:
                raise PolicyError('invalid or duplicate context id')
            if not all(isinstance(c[k], str) and c[k].strip() for k in ('purpose', 'owner')):
                raise PolicyError('purpose and owner required')
            safe_path(c['root'])
            for k in ('instructions','skills','templates'):
                for p in _list(c[k], k): safe_path(p)
            _keys(c['policy'], {'read','write','capabilities','deny','publication'}, set(), 'policy')
            for k, v in c['policy'].items(): _list(v, k)
            for k in ('workflow','defaults'):
                if k in c and not isinstance(c[k], dict): raise PolicyError('invalid ' + k)
            for k in ('imports','exports'):
                if not isinstance(c[k], list): raise PolicyError('invalid connections')
                for rule in c[k]:
                    _keys(rule, {'from_context','to_context','selector','section','field','use','classification','expires'}, {'from_context','to_context','selector','use','classification','expires'}, 'connection')
                    if any(not isinstance(v, str) or not v for v in rule.values()): raise PolicyError('invalid connection')
                    safe_path(rule['selector'])
                    try: dt.date.fromisoformat(rule['expires'])
                    except ValueError as exc: raise PolicyError('invalid connection expiry') from exc
            self.contexts[c['id']] = c
        roots = [c for c in self.contexts.values() if c['parent'] is None]
        if len(roots) != 1: raise PolicyError('exactly one root required')
        for cid in self.contexts: self._resolve(cid, set())
        for c in self.contexts.values():
            for rule in c['imports'] + c['exports']:
                if rule['from_context'] not in self.contexts or rule['to_context'] not in self.contexts:
                    raise PolicyError('unknown connection context')
                if rule in c['imports'] and rule['to_context'] != c['id']: raise PolicyError('invalid consumer')
                if rule in c['exports'] and rule['from_context'] != c['id']: raise PolicyError('invalid producer')

    def _resolve(self, cid, visiting):
        if cid in self.effective: return self.effective[cid]
        if cid in visiting or cid not in self.contexts: raise PolicyError('missing or cyclic parent')
        visiting = visiting | {cid}
        c = self.contexts[cid]
        parent = c['parent']
        if parent is not None and (not isinstance(parent, str) or parent not in self.contexts): raise PolicyError('missing parent')
        base = self._resolve(parent, visiting) if parent is not None else None
        if base is None and 'deny' not in c['policy']: raise PolicyError('root must declare deny boundary')
        result = {}
        for key in ('read','write','capabilities','publication'):
            raw = c['policy'].get(key)
            if raw is None:
                if base is None: raise PolicyError('root must declare all policy boundaries')
                result[key] = list(base[key]); continue
            values = [_scope(v, c['root']) for v in raw] if key in ('read','write') else list(raw)
            if base is not None:
                for v in values:
                    if not any(within(v, p) if key in ('read','write') else v == p for p in base[key]):
                        raise PolicyError('child widens ' + key)
            result[key] = values
        own_deny = [_scope(v, c['root']) for v in c['policy'].get('deny', [])]
        result['deny'] = (list(base['deny']) if base else []) + own_deny
        self.effective[cid] = result
        return result

    def lineage(self, cid):
        if cid not in self.contexts: raise PolicyError('unknown context')
        out = []
        while cid is not None:
            c = self.contexts[cid]; out.append(c); cid = c['parent']
        return list(reversed(out))

    def permits(self, cid, action, path):
        path = safe_path(path)
        if action not in ('read','write'): raise PolicyError('invalid action')
        p = self.effective[cid]
        return any(within(path, x) for x in p[action]) and not any(within(path, x) for x in p['deny'])

    def connection(self, producer, consumer, selector, use, classification, today=None, section=None, field=None):
        safe_path(selector)
        if producer == consumer: return 'approved' if self.permits(consumer, 'read', selector) else 'denied'
        if producer not in self.contexts or consumer not in self.contexts: raise PolicyError('unknown context')
        if not self.permits(producer, 'read', selector) or not self.permits(consumer, 'read', selector): return 'denied'
        today = today or dt.date.today()
        def matches(r):
            return (r['from_context'] == producer and r['to_context'] == consumer and r['selector'] == selector and r['use'] == use and r['classification'] == classification and r.get('section') == section and r.get('field') == field and dt.date.fromisoformat(r['expires']) >= today)
        exports = [r for r in self.contexts[producer]['exports'] if matches(r)]
        imports = [r for r in self.contexts[consumer]['imports'] if matches(r)]
        return 'approved' if any(a == b for a in exports for b in imports) else 'pending'


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise PolicyError('duplicate JSON key')
        result[key] = value
    return result


def load_policy(root, approved_revision, manifest_path, *, trusted_ref='refs/remotes/origin/main'):
    """Load only the current tip of a caller-trusted approval ref.

    The caller must securely configure and refresh that ref; Git itself cannot
    attest review. Never derive trusted_ref from the proposed branch.
    """
    root = Path(root)
    sha = revision(root, approved_revision)
    if sha != revision(root, trusted_ref):
        raise PolicyError('policy revision is not current trusted approval ref')
    try: document = json.loads(git_file(root, sha, manifest_path), object_pairs_hook=_unique_object)
    except (ValueError, UnicodeDecodeError) as exc: raise PolicyError('invalid policy JSON') from exc
    return ContextPolicy(document, sha)


def capability_status(policy, cid, capability, adapter_report):
    """Reports require externally verified evidence; this function does not verify it."""
    if capability not in policy.effective[cid]['capabilities']: return 'denied'
    if not isinstance(adapter_report, dict) or adapter_report.get('verification') != 'verified' or not adapter_report.get('scope') or not adapter_report.get('limitation') or capability not in adapter_report.get('capabilities', []):
        return 'pending'
    return 'available'
