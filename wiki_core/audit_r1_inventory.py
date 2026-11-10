"""Bounded R1 metadata inventory; neither an audit nor an authority provider.

The host must independently admit code, repository identity, Git configuration,
commit objects (including messages), policy, ignore rules, filesystem metadata
and output before this function runs. Target bodies are not deliberately read.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path

from wiki_core.context_packet import _check_trusted_binding, qualify_folder_context
from wiki_core.context_policy import PolicyError, revision, safe_path
from wiki_core.coordination_context import CoordinationBinding, _policy
from wiki_core.git_env import local_git_tree

SHA = re.compile(r'(?:[a-f0-9]{40}|[a-f0-9]{64})\Z')
BRANCH = re.compile(r'wiki/[A-Za-z0-9][A-Za-z0-9._-]*\Z')
MAX_COMMITS = 512
MAX_ENTRIES = 30_000


def _git(root: Path, *args: str) -> bytes:
    return local_git_tree(root, '-c', 'core.fsmonitor=false',
                          '-c', 'core.untrackedCache=false',
                          '-c', 'core.hooksPath=/dev/null',
                          '-c', 'core.useReplaceRefs=false', *args)


def _nul(raw: bytes) -> list[bytes]:
    if raw and not raw.endswith(b'\0'):
        raise PolicyError('inventory unavailable')
    return [part for part in raw.split(b'\0') if part]


def _name(raw: bytes) -> str:
    try:
        value = raw.decode('utf-8')
        if safe_path(value) != value:
            raise PolicyError('inventory path unavailable')
        return value
    except (UnicodeError, ValueError) as exc:
        raise PolicyError('inventory path unavailable') from exc


def _reject_graph_overrides(root: Path) -> None:
    """Reject persistent grafts/alternates; metadata access is host-admitted."""
    for rel in ('info/grafts', 'objects/info/alternates'):
        value = _git(root, 'rev-parse', '--git-path', rel).decode('utf-8').strip()
        if not value or '\n' in value or '\r' in value:
            raise PolicyError('inventory repository unavailable')
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = root / candidate
        try:
            candidate.lstat()
        except FileNotFoundError:
            continue
        raise PolicyError('inventory graph override unavailable')


def _tree(root: Path, commit: str) -> dict:
    tree = {}
    for entry in _nul(_git(root, 'ls-tree', '-r', '-z', '--full-tree', commit)):
        meta, sep, raw_path = entry.partition(b'\t')
        fields = meta.split(b' ')
        if not sep or len(fields) != 3:
            raise PolicyError('inventory tree unavailable')
        path = _name(raw_path)
        mode, kind, oid = (field.decode('ascii') for field in fields)
        if (path in tree or mode not in ('100644', '100755') or kind != 'blob'
                or not SHA.fullmatch(oid)):
            raise PolicyError('inventory tree unsupported')
        tree[path] = {'mode': mode, 'oid': oid}
        if len(tree) > MAX_ENTRIES:
            raise PolicyError('inventory limit exceeded')
    return tree


def _index(root: Path) -> list[dict]:
    result = []
    for entry in _nul(_git(root, 'ls-files', '--stage', '--full-name', '--sparse', '-z')):
        meta, sep, raw_path = entry.partition(b'\t')
        fields = meta.split(b' ')
        if not sep or len(fields) != 3:
            raise PolicyError('inventory index unavailable')
        mode, oid, stage = (field.decode('ascii') for field in fields)
        if mode not in ('100644', '100755') or not SHA.fullmatch(oid) or stage not in ('0', '1', '2', '3'):
            raise PolicyError('inventory index unsupported')
        result.append({'path': _name(raw_path), 'mode': mode, 'oid': oid, 'stage': int(stage)})
        if len(result) > MAX_ENTRIES:
            raise PolicyError('inventory limit exceeded')
    return sorted(result, key=lambda item: (item['path'], item['stage']))


def _allowed(policy, actor: str, path: str) -> bool:
    try:
        return (policy.owner_of(path) == actor and
                policy.connection(actor, actor, path, 'interpretation', 'context') == 'approved')
    except ValueError:
        return False


def _physical(root: Path, policy, actor: str) -> dict:
    """Inventory names and lstat metadata; do not open file bodies.

    Check .gitignore against the approved policy before Git may open it. The
    host separately admits all metadata and .git/info/exclude bootstrap.
    """
    pending = [('', root)]
    rows = {}
    directories = {}
    visited = 0
    root_device = root.stat().st_dev
    while pending:
        parent, directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                if not parent and entry.name == '.git':
                    continue
                rel = _name(os.fsencode(f'{parent}/{entry.name}' if parent else entry.name))
                visited += 1
                if visited > MAX_ENTRIES:
                    raise PolicyError('inventory limit exceeded')
                row = entry.stat(follow_symlinks=False)
                if entry.name == '.git':
                    raise PolicyError('nested repository unavailable')
                if stat.S_ISLNK(row.st_mode):
                    raise PolicyError('inventory symlink unsupported')
                if stat.S_ISDIR(row.st_mode):
                    if row.st_dev != root_device:
                        raise PolicyError('inventory mount unsupported')
                    directories[rel] = {'device': row.st_dev, 'inode': row.st_ino,
                                        'mode': stat.S_IMODE(row.st_mode),
                                        'mtime_ns': row.st_mtime_ns, 'ctime_ns': row.st_ctime_ns}
                    pending.append((rel, Path(entry.path)))
                    continue
                if not stat.S_ISREG(row.st_mode) or row.st_nlink != 1:
                    raise PolicyError('worktree entry unsupported')
                if entry.name == '.gitignore' and not _allowed(policy, actor, rel):
                    raise PolicyError('ignore bootstrap unavailable')
                rows[rel] = {'mode': stat.S_IMODE(row.st_mode), 'device': row.st_dev,
                             'inode': row.st_ino, 'size': row.st_size,
                             'mtime_ns': row.st_mtime_ns, 'ctime_ns': row.st_ctime_ns,
                             'content_relation': 'unknown'}
    return {'files': rows, 'directories': directories}


def inventory(root: Path, binding: CoordinationBinding, *, context_id: str,
              approved_revision: str, base: str, head: str, branch: str) -> dict:
    """Return a candidate inventory, not evidence of admission or scanning.

    History is bounded to base..head and the parents at its boundary. The host
    must independently admit the bootstrap before invoking this function, and
    must separately admit an exact selection before any target-body reads.
    """
    if sys.platform == 'win32':
        raise PolicyError('inventory platform unavailable')
    if (not isinstance(binding, CoordinationBinding) or binding.manifest != 'wiki.config.yaml'
            or not all(isinstance(x, str) and SHA.fullmatch(x) for x in (approved_revision, base, head))
            or approved_revision != base or not isinstance(branch, str) or not BRANCH.fullmatch(branch)
            or '..' in branch or branch.endswith('.')):
        raise PolicyError('inventory authority unavailable')
    root = Path(root).resolve(strict=True)
    top = _git(root, 'rev-parse', '--show-toplevel').decode('utf-8').strip()
    if Path(top).resolve(strict=True) != root or _git(root, 'rev-parse', '--is-shallow-repository').strip() != b'false':
        raise PolicyError('inventory repository unavailable')
    _reject_graph_overrides(root)
    policy = _policy(root, binding, context_id, approved_revision)
    _check_trusted_binding(root, policy, context_id, binding)
    context_index = policy._context_indexes.get(context_id)
    if not context_index:
        raise PolicyError('inventory context unavailable')
    qualify_folder_context(root, policy, context_id, context_id, context_index, 1_000_000)
    def current_refs() -> None:
        selected_ref = 'refs/heads/' + branch
        if (revision(root, binding.trusted_ref) != base or revision(root, selected_ref) != head
                or _git(root, 'symbolic-ref', '--quiet', 'HEAD').decode('ascii').strip() != selected_ref
                or revision(root, 'HEAD') != head):
            raise PolicyError('inventory revision changed')

    current_refs()
    _git(root, 'merge-base', '--is-ancestor', base, head)
    history = []
    for line in _git(root, 'rev-list', '--parents', '--topo-order', f'{base}..{head}').decode('ascii').splitlines():
        parts = line.split()
        if not parts or any(not SHA.fullmatch(item) for item in parts):
            raise PolicyError('inventory history unavailable')
        history.append({'commit': parts[0], 'parents': parts[1:]})
        if len(history) > MAX_COMMITS:
            raise PolicyError('inventory limit exceeded')
    commits = {base} | {item['commit'] for item in history}
    commits.update(parent for item in history for parent in item['parents'])
    if len(commits) > MAX_COMMITS:
        raise PolicyError('inventory limit exceeded')
    trees = {}
    total_entries = 0
    for commit in sorted(commits):
        trees[commit] = _tree(root, commit)
        total_entries += len(trees[commit])
        if total_entries > MAX_ENTRIES:
            raise PolicyError('inventory limit exceeded')
    config = trees[base].get('wiki.config.yaml')
    if config is None or any(tree.get('wiki.config.yaml') != config for tree in trees.values()):
        raise PolicyError('normative history requires independent review')
    index = _index(root)
    config_entries = [entry for entry in index if entry['path'] == 'wiki.config.yaml']
    if (len(config_entries) != 1 or config_entries[0]['stage'] != 0
            or config_entries[0]['oid'] != config['oid'] or config_entries[0]['mode'] != config['mode']):
        raise PolicyError('normative index requires independent review')
    physical = _physical(root, policy, context_id)
    untracked = {_name(path) for path in _nul(_git(root, 'ls-files', '--others', '--exclude-standard', '-z'))}
    ignored = {_name(path) for path in _nul(_git(root, 'ls-files', '--others', '--ignored', '--exclude-standard', '-z'))}
    tracked = {item['path'] for item in index}
    physical_files = set(physical['files'])
    if (untracked & ignored or tracked & (untracked | ignored)
            or physical_files != (tracked & physical_files) | untracked | ignored):
        raise PolicyError('inventory worktree coverage unavailable')
    paths = physical_files | tracked | {path for tree in trees.values() for path in tree}
    if len(paths) > MAX_ENTRIES:
        raise PolicyError('inventory limit exceeded')
    authorization = [{'path': path, 'current_policy': 'permitted' if _allowed(policy, context_id, path) else 'denied'}
                     for path in sorted(paths)]
    denied = {item['path'] for item in authorization if item['current_policy'] == 'denied'}
    objects = [(path, entry['oid']) for tree in trees.values() for path, entry in tree.items()]
    objects.extend((entry['path'], entry['oid']) for entry in index)
    denied_oids = {oid for path, oid in objects if path in denied}
    aliases = sorted({oid for path, oid in objects if path not in denied and oid in denied_oids})
    current_refs()
    if _index(root) != index or _physical(root, policy, context_id) != physical:
        raise PolicyError('inventory changed')
    if ({_name(path) for path in _nul(_git(root, 'ls-files', '--others', '--exclude-standard', '-z'))} != untracked
            or {_name(path) for path in _nul(_git(root, 'ls-files', '--others', '--ignored', '--exclude-standard', '-z'))} != ignored):
        raise PolicyError('inventory ignore classification changed')
    current_refs()
    result = {'schema_version': 'wiki.audit-r1-inventory/v1', 'context_id': context_id,
              'approved_revision': approved_revision, 'trusted_ref': binding.trusted_ref,
              'base': base, 'head': head, 'branch': branch,
              'root_identity_sha256': hashlib.sha256(str(root).encode()).hexdigest(),
              'history': history, 'trees': trees, 'index': index, 'physical': physical,
              'untracked': sorted(untracked), 'ignored': sorted(ignored),
              'missing_tracked': sorted(tracked - physical_files), 'authorization': authorization,
              'denied_oid_aliases': aliases,
              'coverage': {'history': 'bounded_interval_and_boundary_parents_inventoried',
                           'commit_messages': 'bootstrap_read_not_scanned', 'trees': 'inventoried',
                           'index': 'inventoried', 'worktree': 'metadata_only',
                           'untracked': 'inventoried', 'ignored': 'inventoried'},
              'bootstrap_authority': 'external_not_verified',
              'bootstrap_reads': {'commit_objects': 'read_may_include_messages',
                                  'ignore_rules': 'read_may_overlap_target_paths',
                                  'policy': 'read_may_overlap_target_paths',
                                  'context': 'read_may_overlap_target_paths'},
              'other_target_bodies': 'not_intentionally_read',
              'global_audit': 'not_performed', 'selection_admission': 'not_verified',
              'historical_policy': 'not_qualified', 'worktree_policy': 'not_inspected',
              'live_observation': 'not_verified',
              'concurrency_isolation': 'external_not_verified',
              'ignore_config_identity': 'external_not_verified'}
    result['inventory_sha256'] = hashlib.sha256(json.dumps(result, sort_keys=True,
        ensure_ascii=True, separators=(',', ':')).encode()).hexdigest()
    return result


def select(inventory_result: dict, requested: list[dict]) -> dict:
    """Bind explicitly requested inputs to one inventory; do not read bodies.

    The host must decide whether the request covers its entire gate and must
    independently approve the returned selection before any selected body is
    opened. This helper verifies current-policy eligibility only; historical
    authorization, host identity, snapshot and runtime remain external.
    """
    if (not isinstance(inventory_result, dict) or not isinstance(requested, list)
            or not requested or len(requested) > MAX_ENTRIES):
        raise PolicyError('selection unavailable')
    saved = inventory_result.get('inventory_sha256')
    body = {key: value for key, value in inventory_result.items() if key != 'inventory_sha256'}
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=True,
        separators=(',', ':')).encode()).hexdigest()
    if saved != digest or body.get('schema_version') != 'wiki.audit-r1-inventory/v1':
        raise PolicyError('selection inventory unavailable')
    allowed = {entry['path'] for entry in body['authorization'] if entry['current_policy'] == 'permitted'}
    aliases = set(body['denied_oid_aliases'])
    commits = set(body['trees'])
    index = {(entry['path'], entry['stage']): entry for entry in body['index']}
    selected = []
    seen = set()
    for item in requested:
        if not isinstance(item, dict) or not isinstance(item.get('kind'), str):
            raise PolicyError('selection unavailable')
        kind = item['kind']
        if (kind == 'message' and set(item) == {'kind', 'revision'}
                and isinstance(item['revision'], str) and item['revision'] in commits):
            row = {'kind': kind, 'revision': item['revision']}
        elif kind == 'git_blob' and set(item) == {'kind', 'revision', 'path'}:
            path, rev = item['path'], item['revision']
            if not isinstance(path, str) or not isinstance(rev, str):
                raise PolicyError('selection unavailable')
            entry = body['trees'].get(rev, {}).get(path)
            if path not in allowed or entry is None or entry['oid'] in aliases:
                raise PolicyError('selection unavailable')
            row = {'kind': kind, 'revision': rev, 'path': path, **entry}
        elif kind == 'index_blob' and set(item) == {'kind', 'path', 'stage'}:
            path, stage = item['path'], item['stage']
            if not isinstance(path, str) or type(stage) is not int:
                raise PolicyError('selection unavailable')
            entry = index.get((path, stage))
            if path not in allowed or entry is None or entry['oid'] in aliases:
                raise PolicyError('selection unavailable')
            row = {'kind': kind, **entry}
        elif kind == 'worktree' and set(item) == {'kind', 'path'}:
            path = item['path']
            if not isinstance(path, str):
                raise PolicyError('selection unavailable')
            entry = body['physical']['files'].get(path)
            if path not in allowed or entry is None:
                raise PolicyError('selection unavailable')
            row = {'kind': kind, 'path': path, **entry}
        else:
            raise PolicyError('selection unavailable')
        key = json.dumps(row, sort_keys=True, ensure_ascii=True, separators=(',', ':'))
        if key in seen:
            raise PolicyError('selection unavailable')
        seen.add(key)
        selected.append(row)
    selected.sort(key=lambda value: (value['kind'], json.dumps(
        value, sort_keys=True, ensure_ascii=True, separators=(',', ':'))))
    result = {'schema_version': 'wiki.audit-r1-selection/v1', 'inventory_sha256': saved,
              'inputs': selected, 'gate_coverage': 'not_verified',
              'selected_categories': sorted({item['kind'] for item in selected}),
              'limits': {'max_item_bytes': 2_000_000, 'max_total_bytes': 8_000_000},
              'external_admission': 'not_verified', 'historical_policy': 'not_qualified',
              'target_bodies': 'not_read_by_selector'}
    result['selection_sha256'] = hashlib.sha256(json.dumps(result, sort_keys=True,
        ensure_ascii=True, separators=(',', ':')).encode()).hexdigest()
    return result


def _worktree_bytes(root: Path, row: dict) -> bytes:
    path = root / row['path']
    before = path.lstat()
    def signature(item):
        return (item.st_dev, item.st_ino, stat.S_IMODE(item.st_mode), item.st_size,
                item.st_mtime_ns, item.st_ctime_ns)
    expected = (row['device'], row['inode'], row['mode'], row['size'], row['mtime_ns'], row['ctime_ns'])
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or signature(before) != expected:
        raise PolicyError('selected file changed')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        if opened.st_nlink != 1 or signature(opened) != expected:
            raise PolicyError('selected file changed')
        content = stream.read(row['size'] + 1)
        after = os.fstat(stream.fileno())
    if len(content) != row['size'] or signature(after) != expected or signature(path.lstat()) != expected:
        raise PolicyError('selected file changed')
    return content


def scan_selected(root: Path, binding: CoordinationBinding, *, context_id: str,
                  approved_revision: str, base: str, head: str, branch: str,
                  requested: list[dict], inventory_sha256: str, selection_sha256: str,
                  admit) -> dict:
    """Scan selected text for secrets under a trusted host's live admission.

    The host must independently authorize bootstrap before invocation and bind
    ``admit`` to a qualified actor, whole-selection scope, current/historical
    policy and output audience. It must prevent concurrent writers. This code
    cannot authenticate the callback or replace the consumer's audit gates.
    An error after selected reads reports partial coverage without content.
    """
    from wiki_core.detectors.secrets import scan_secrets

    if not callable(admit):
        raise PolicyError('selection admission unavailable')
    first = inventory(root, binding, context_id=context_id, approved_revision=approved_revision,
                      base=base, head=head, branch=branch)
    if first['inventory_sha256'] != inventory_sha256:
        raise PolicyError('inventory changed')
    selection = select(first, requested)
    if selection['selection_sha256'] != selection_sha256:
        raise PolicyError('selection changed')
    def admitted() -> bool:
        try:
            isolated = json.loads(json.dumps(selection, ensure_ascii=True, sort_keys=True))
            return admit(isolated) is True
        except Exception as exc:
            raise PolicyError('selection admission unavailable') from exc

    if not admitted():
        raise PolicyError('selection admission unavailable')
    root = Path(root).resolve(strict=True)
    def still_current() -> bool:
        selected_ref = 'refs/heads/' + branch
        return (revision(root, binding.trusted_ref) == base and revision(root, selected_ref) == head
                and _git(root, 'symbolic-ref', '--quiet', 'HEAD').decode('ascii').strip() == selected_ref
                and revision(root, 'HEAD') == head)

    sizes = []
    completed = 0
    checked_sizes = 0
    findings = 0
    try:
        for item in selection['inputs']:
            if not admitted() or not still_current():
                raise PolicyError('selection admission changed')
            if item['kind'] == 'worktree':
                size = item['size']
            else:
                oid = item['revision'] if item['kind'] == 'message' else item['oid']
                size = int(_git(root, 'cat-file', '-s', oid).decode('ascii').strip())
            checked_sizes += 1
            if size < 0 or size > 2_000_000:
                raise PolicyError('selected size unavailable')
            sizes.append(size)
        if sum(sizes) > 8_000_000:
            raise PolicyError('selection budget exceeded')
        for item, expected_size in zip(selection['inputs'], sizes):
            if not admitted() or not still_current():
                raise PolicyError('selection admission changed')
            if item['kind'] == 'worktree':
                raw = _worktree_bytes(root, item)
            else:
                kind = 'commit' if item['kind'] == 'message' else 'blob'
                oid = item['revision'] if kind == 'commit' else item['oid']
                raw = _git(root, 'cat-file', kind, oid)
            if len(raw) != expected_size or b'\0' in raw:
                raise PolicyError('selected content unavailable')
            if item['kind'] == 'message':
                _, separator, raw = raw.partition(b'\n\n')
                if not separator:
                    raise PolicyError('selected message unavailable')
            if raw.startswith(b'version https://git-lfs.github.com/spec/v1'):
                raise PolicyError('selected content unavailable')
            findings += len(scan_secrets(raw.decode('utf-8')))
            completed += 1
        after = inventory(root, binding, context_id=context_id, approved_revision=approved_revision,
                          base=base, head=head, branch=branch)
        if after['inventory_sha256'] != inventory_sha256 or not admitted():
            raise PolicyError('inventory changed')
    except Exception:
        return {'state': 'partial', 'scanned_count': completed,
                'size_checked_count': checked_sizes,
                'secret_findings': findings, 'required_count': len(selection['inputs']),
                'scope': 'explicit_selected_text_secret_scan',
                'selection_sha256': selection_sha256, 'global_audit': 'not_performed',
                'gate_coverage': 'not_verified', 'host_admission': 'not_verified',
                'historical_policy': 'external_not_verified',
                'concurrency_isolation': 'external_not_verified', 'live_observation': 'not_verified'}
    return {'state': 'failed' if findings else 'completed', 'scanned_count': completed,
            'size_checked_count': checked_sizes,
            'secret_findings': findings, 'required_count': len(selection['inputs']),
            'scope': 'explicit_selected_text_secret_scan',
            'selection_sha256': selection_sha256, 'global_audit': 'not_performed',
            'gate_coverage': 'not_verified', 'host_admission': 'not_verified',
            'historical_policy': 'external_not_verified',
            'concurrency_isolation': 'external_not_verified', 'live_observation': 'not_verified'}
