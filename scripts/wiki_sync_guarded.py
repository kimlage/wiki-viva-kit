#!/usr/bin/env python3
"""Host-admitted, plan-bound C1 sync; independent approval is external."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import unicodedata
from pathlib import Path

sys.dont_write_bytecode = True
import yaml

CODE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_ROOT))
from scripts import wiki_sync_from_kit as legacy
from wiki_core.context_packet import _check_trusted_binding, qualify_folder_context
from wiki_core.context_policy import UniqueLoader, revision, safe_path
from wiki_core.coordination_context import CoordinationBinding, _policy
from wiki_core.git_env import local_git_tree, local_git_environment, local_git_executable
from wiki_core.repository_reader import canonical_path

SCHEMA = 'wiki.guarded-sync-selection/v1'
PLAN_SCHEMA = 'wiki.guarded-sync-plan/v1'
LOCK = 'kit.lock'
SHA = re.compile(r'(?:[a-f0-9]{40}|[a-f0-9]{64})\Z')
HASH = re.compile(r'[a-f0-9]{64}\Z')
MAX_SELECTION = 10_000
MAX_TOTAL = 128_000_000


class GuardedSyncError(ValueError):
    """The selection, authority or state is unavailable."""


def _digest(value) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True,
                         separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _path(path: str) -> str:
    if not isinstance(path, str) or safe_path(path) != canonical_path(path):
        raise GuardedSyncError('selection unavailable')
    for part in path.split('/'):
        if (part.endswith(('.', ' ')) or any(c in part for c in '<>:"|?*')
                or part.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL',
                    *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}):
            raise GuardedSyncError('selection unavailable')
    return path


def temp_path_for(source_sha: str, path: str) -> str:
    """A deterministic, separately admitted temporary path for one target."""
    _path(path)
    token = hashlib.sha256((source_sha + '\0' + path).encode('utf-8')).hexdigest()
    parent = path.rpartition('/')[0]
    name = '.wiki-sync-' + token
    return f'{parent}/{name}' if parent else name


def select_contract(context_id: str, policy_revision: str, trusted_ref: str,
                    source_sha: str, paths: list[str], *,
                    manifest_path: str = 'docs/references/upgrades/sync-manifest.yaml') -> dict:
    """Build a proposed selection; this helper does not authorize it."""
    if not isinstance(paths, list) or len(paths) > MAX_SELECTION:
        raise GuardedSyncError('selection unavailable')
    paths = sorted(_path(path) for path in paths)
    if not paths or LOCK not in paths or len(paths) != len(set(paths)):
        raise GuardedSyncError('selection unavailable')
    temps = sorted(temp_path_for(source_sha, path) for path in paths)
    ancestors = set()
    for path in paths + temps:
        parts = path.split('/')
        for count in range(1, len(parts)):
            ancestors.add('/'.join(parts[:count]))
    all_files = paths + temps
    folded = [unicodedata.normalize('NFC', item).casefold() for item in all_files]
    folded_dirs = [unicodedata.normalize('NFC', item).casefold() for item in ancestors]
    if (len(folded) != len(set(folded)) or len(folded_dirs) != len(set(folded_dirs))
            or set(folded) & set(folded_dirs)):
        raise GuardedSyncError('selection unavailable')
    if any(path in ancestors for path in all_files):
        raise GuardedSyncError('selection unavailable')
    return {'schema_version': SCHEMA, 'context_id': context_id,
            'policy_revision': policy_revision, 'trusted_ref': trusted_ref,
            'source_sha': source_sha, 'manifest_path': _path(manifest_path),
            'paths': paths, 'temp_paths': temps,
            'metadata_paths': sorted(ancestors)}


def selection_digest(selection: dict) -> str:
    return _digest(selection)


def _git(root: Path, *args: str) -> bytes:
    return local_git_tree(root, '-c', 'core.fsmonitor=false',
                          '-c', 'core.untrackedCache=false',
                          '-c', 'core.hooksPath=/dev/null',
                          '-c', 'core.useReplaceRefs=false', *args)


def _git_head(root: Path) -> str:
    value = _git(root, 'rev-parse', '--verify', 'HEAD^{commit}').decode('ascii').strip()
    if not SHA.fullmatch(value):
        raise GuardedSyncError('revision unavailable')
    return value


def _root(root: Path) -> Path:
    resolved = Path(root).resolve(strict=True)
    top = _git(resolved, 'rev-parse', '--show-toplevel').rstrip(b'\r\n').decode('utf-8')
    if Path(top).resolve(strict=True) != resolved:
        raise GuardedSyncError('root unavailable')
    return resolved


def _tree(root: Path, sha: str) -> dict:
    data = _git(root, 'ls-tree', '-r', '-z', sha)
    if data and not data.endswith(b'\0'):
        raise GuardedSyncError('source unavailable')
    tree = {}
    for row in data.split(b'\0'):
        if not row:
            continue
        meta, sep, path = row.partition(b'\t')
        fields = meta.split(b' ')
        if not sep or len(fields) != 3:
            raise GuardedSyncError('source unavailable')
        name = path.decode('utf-8')
        if name in tree:
            raise GuardedSyncError('source unavailable')
        tree[name] = tuple(field.decode('ascii') for field in fields)
    return tree


def _source(root: Path, source_sha: str, manifest_rel: str):
    if _git_head(root) != source_sha:
        raise GuardedSyncError('source revision changed')
    manifest_rel = _path(manifest_rel)
    tree = _tree(root, source_sha)
    row = tree.get(manifest_rel)
    if row is None or row[0] not in ('100644', '100755') or row[1] != 'blob':
        raise GuardedSyncError('source manifest unavailable')
    manifest = yaml.load(_git(root, 'cat-file', 'blob', row[2]).decode('utf-8'), Loader=UniqueLoader)
    if not isinstance(manifest, dict):
        raise GuardedSyncError('source manifest unavailable')
    legacy._validate_manifest(manifest)
    if manifest.get('c2_commands', []):
        raise GuardedSyncError('C2 is not supported by this route')
    selected = {}
    for name, (mode, kind, oid) in tree.items():
        if not any(legacy._matches(name, pattern) for pattern in manifest['portable']['allow']):
            continue
        if any(legacy._matches(name, pattern) for pattern in manifest['portable'].get('block', [])):
            continue
        _path(name)
        if name == LOCK or mode not in ('100644', '100755') or kind != 'blob':
            raise GuardedSyncError('source selection unavailable')
        selected[name] = {'mode': mode, 'oid': oid}
    if not selected or len(selected) > MAX_SELECTION:
        raise GuardedSyncError('source selection unavailable')
    payloads = {}
    total = 0
    for name, row in sorted(selected.items()):
        data = _git(root, 'cat-file', 'blob', row['oid'])
        total += len(data)
        if total > MAX_TOTAL:
            raise GuardedSyncError('source selection unavailable')
        payloads[name] = {'mode': row['mode'], 'sha256': hashlib.sha256(data).hexdigest(),
                          'size': len(data), 'payload': data}
    if _git_head(root) != source_sha:
        raise GuardedSyncError('source revision changed')
    return manifest, payloads


def _authorize(policy, context_id: str, selection: dict) -> None:
    """Authorize every selected name before inspecting consumer paths."""
    for path in selection['paths'] + selection['temp_paths']:
        if (policy.owner_of(path) != context_id
                or policy.connection(context_id, context_id, path, 'interpretation', 'context') != 'approved'
                or not policy.permits(context_id, 'write', path)):
            raise GuardedSyncError('selection unavailable')
    for path in selection['metadata_paths']:
        if (policy.owner_of(path) != context_id
                or policy.connection(context_id, context_id, path, 'interpretation', 'context') != 'approved'):
            raise GuardedSyncError('selection unavailable')


def _lstat(root: Path, rel: str):
    try:
        return (root / rel).lstat()
    except FileNotFoundError:
        return None


def _parents(root: Path, selection: dict) -> None:
    """Require admitted directories to exist, without following symlinks."""
    result = {}
    for rel in sorted(selection['metadata_paths'], key=lambda path: (path.count('/'), path)):
        row = _lstat(root, rel)
        if row is None or not stat.S_ISDIR(row.st_mode):
            raise GuardedSyncError('parent unavailable')
        # Git-boundary metadata is an independently admitted bootstrap input.
        if _lstat(root, rel + '/.git') is not None:
            raise GuardedSyncError('nested repository unavailable')
        result[rel] = {'dev': row.st_dev, 'ino': row.st_ino, 'mode': row.st_mode,
                       'mtime_ns': row.st_mtime_ns, 'ctime_ns': row.st_ctime_ns}
    return result


def _snapshot(root: Path, rel: str):
    """Read an already authorized regular file and bind its mode/content."""
    before = _lstat(root, rel)
    if before is None:
        return {'kind': 'missing'}, None
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > MAX_TOTAL:
        raise GuardedSyncError('target unavailable')
    def signature(row):
        return (row.st_dev, row.st_ino, row.st_mode, row.st_nlink, row.st_size,
                row.st_mtime_ns, row.st_ctime_ns)
    fd = os.open(root / rel, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        if signature(opened) != signature(before):
            raise GuardedSyncError('target changed')
        data = stream.read(MAX_TOTAL + 1)
        readback = os.fstat(stream.fileno())
    after = _lstat(root, rel)
    if (after is None or signature(before) != signature(after)
            or signature(before) != signature(readback) or len(data) != before.st_size):
        raise GuardedSyncError('target changed')
    mode = '100755' if os.access(root / rel, os.X_OK) else '100644'
    return {'kind': 'file', 'mode': mode, 'fs_mode': format(stat.S_IMODE(before.st_mode), '04o'),
            'sha256': hashlib.sha256(data).hexdigest()}, data


def _lock(root: Path):
    state, raw = _snapshot(root, LOCK)
    if raw is None:
        return state, {}
    if len(raw) > 4_000_000:
        raise GuardedSyncError('lock unavailable')
    value = yaml.load(raw.decode('utf-8'), Loader=UniqueLoader)
    if not isinstance(value, dict) or value.get('schema_version') != 'wiki_viva_kit_lock.v1':
        raise GuardedSyncError('lock unavailable')
    managed = value.get('managed_files', {})
    if not isinstance(managed, dict):
        raise GuardedSyncError('lock unavailable')
    for path, row in managed.items():
        _path(path)
        if (path == LOCK or not isinstance(row, dict) or not isinstance(row.get('sha256'), str)
                or not HASH.fullmatch(row['sha256']) or row.get('mode') not in ('100644', '100755')):
            raise GuardedSyncError('lock unavailable')
    return state, managed


def _index_clean(root: Path, head: str, paths: list[str]) -> None:
    """Reject staged differences only for the already admitted path set."""
    for start in range(0, len(paths), 24):
        selected = paths[start:start + 24]
        specs = [':(literal)' + path for path in selected]
        expected = _git(root, 'ls-tree', '-r', '-z', head, '--', *specs)
        staged = _git(root, 'ls-files', '--stage', '-z', '--', *specs)
        if ((expected and not expected.endswith(b'\0')) or (staged and not staged.endswith(b'\0'))):
            raise GuardedSyncError('selected index unavailable or changed')
        allowed = set(selected)
        tree = {}
        index = {}
        for raw in expected.split(b'\0'):
            if not raw: continue
            meta, sep, name = raw.partition(b'\t')
            fields = meta.split(b' ')
            path = name.decode('utf-8')
            if (not sep or len(fields) != 3 or path not in allowed or path in tree
                    or fields[1] != b'blob' or fields[0] not in (b'100644', b'100755')):
                raise GuardedSyncError('selected index unavailable or changed')
            tree[path] = (fields[0], fields[2])
        for raw in staged.split(b'\0'):
            if not raw: continue
            meta, sep, name = raw.partition(b'\t')
            fields = meta.split(b' ')
            path = name.decode('utf-8')
            if (not sep or len(fields) != 3 or path not in allowed or path in index
                    or fields[2] != b'0' or fields[0] not in (b'100644', b'100755')):
                raise GuardedSyncError('selected index unavailable or changed')
            index[path] = (fields[0], fields[1])
        if tree != index:
            raise GuardedSyncError('selected index unavailable or changed')


def _identity(root: Path) -> str:
    """Bind the plan to this local root; identity remains host-qualified."""
    return hashlib.sha256(str(root).encode('utf-8')).hexdigest()


def _future_lock(source_sha: str, manifest_sha: str, tree_sha: str, files: dict) -> bytes:
    lock = {'schema_version': 'wiki_viva_kit_lock.v1', 'source_sha': source_sha,
            'manifest_sha256': manifest_sha, 'portable_tree_sha256': tree_sha,
            'managed_files': {path: {'sha256': item['sha256'], 'mode': item['mode']}
                              for path, item in files.items()}}
    return yaml.safe_dump(lock, sort_keys=True, allow_unicode=True).encode('utf-8')


def _build(kit: Path, consumer: Path, binding: CoordinationBinding, *, context_id: str,
           approved_revision: str, source_sha: str, selection: dict, selection_sha256: str,
           manifest_path: str):
    if sys.platform == 'win32':
        raise GuardedSyncError('guarded sync unavailable on Windows')
    if (not isinstance(binding, CoordinationBinding) or binding.manifest != 'wiki.config.yaml'
            or not isinstance(source_sha, str) or not SHA.fullmatch(source_sha)
            or not isinstance(approved_revision, str) or not SHA.fullmatch(approved_revision)
            or not isinstance(selection_sha256, str) or not HASH.fullmatch(selection_sha256)
            or not isinstance(selection, dict)):
        raise GuardedSyncError('authority unavailable')
    selection = json.loads(json.dumps(selection, ensure_ascii=True, sort_keys=True,
                                      separators=(',', ':')))
    kit, consumer = _root(kit), _root(consumer)
    if kit == consumer or kit in consumer.parents or consumer in kit.parents:
        raise GuardedSyncError('roots unavailable')
    expected = select_contract(context_id, approved_revision, binding.trusted_ref, source_sha,
                               selection.get('paths'), manifest_path=manifest_path)
    if expected != selection or selection_digest(selection) != selection_sha256:
        raise GuardedSyncError('selection unavailable')
    manifest, files = _source(kit, source_sha, manifest_path)
    policy = _policy(consumer, binding, context_id, approved_revision)
    _check_trusted_binding(consumer, policy, context_id, binding)
    index = policy._context_indexes.get(context_id)
    if not index:
        raise GuardedSyncError('context unavailable')
    qualify_folder_context(consumer, policy, context_id, context_id, index, 1_000_000)
    _authorize(policy, context_id, selection)
    # Lock is read only after independent bootstrap and exact policy admission.
    lock_state, previous = _lock(consumer)
    paths = sorted(set(files) | set(previous) | {LOCK})
    if paths != selection['paths']:
        raise GuardedSyncError('selection unavailable')
    directories = _parents(consumer, selection)
    for path in selection['temp_paths']:
        if _lstat(consumer, path) is not None:
            raise GuardedSyncError('temporary path unavailable')
    consumer_head = _git_head(consumer)
    _index_clean(consumer, consumer_head, selection['paths'] + selection['temp_paths'])
    states = {LOCK: lock_state}
    for path in paths:
        if path != LOCK:
            states[path] = _snapshot(consumer, path)[0]
    added, changed, unchanged = [], [], []
    for path, item in files.items():
        actual = states[path]
        if actual['kind'] == 'missing':
            added.append(path)
        elif actual.get('sha256') == item['sha256'] and actual.get('mode') == item['mode']:
            unchanged.append(path)
        else:
            old = previous.get(path)
            if not old or actual.get('sha256') != old['sha256'] or actual.get('mode') != old['mode']:
                raise GuardedSyncError('target conflict')
            changed.append(path)
    removed = sorted(set(previous) - set(files))
    for path in removed:
        actual, old = states[path], previous[path]
        if actual['kind'] != 'missing' and (actual.get('sha256') != old['sha256'] or actual.get('mode') != old['mode']):
            raise GuardedSyncError('target conflict')
    source_tree = [{'path': path, 'sha256': item['sha256'], 'mode': item['mode']}
                   for path, item in files.items()]
    manifest_sha = legacy._canonical_sha256(manifest)
    tree_sha = legacy._canonical_sha256(source_tree)
    lock_after = _future_lock(source_sha, manifest_sha, tree_sha, files)
    future_lock_sha = hashlib.sha256(lock_after).hexdigest()
    lock_write = lock_state.get('kind') != 'file' or lock_state.get('sha256') != future_lock_sha
    plan = {'schema_version': PLAN_SCHEMA, 'context_id': context_id,
            'policy_revision': approved_revision, 'trusted_ref': binding.trusted_ref,
            'source_sha': source_sha, 'manifest_path': manifest_path,
            'manifest_sha256': manifest_sha, 'portable_tree_sha256': tree_sha,
            'selection_sha256': selection_sha256, 'selection': selection,
            'kit_root_sha256': _identity(kit), 'consumer_root_sha256': _identity(consumer),
            'consumer_head': consumer_head, 'consumer_dirty': 'not_inspected',
            'states': states, 'directory_states': directories,
            'temp_states': {path: 'missing' for path in selection['temp_paths']},
            'c1': {'managed_total': len(files), 'add': added, 'change': changed, 'remove_previously_managed': removed,
                   'unchanged': unchanged,
                   'temporary_effects': sorted(temp_path_for(source_sha, path)
                       for path in added + changed + ([LOCK] if lock_write else []))},
            'c2_commands': [], 'c3_commands': [],
            'lock_after': {'sha256': future_lock_sha, 'write': lock_write,
                           'fs_mode': '0600' if lock_write else lock_state.get('fs_mode')}}
    if _git_head(kit) != source_sha or _git_head(consumer) != consumer_head:
        raise GuardedSyncError('revision changed')
    policy.fresh()
    if _parents(consumer, selection) != directories:
        raise GuardedSyncError('parent changed')
    for path in selection['temp_paths']:
        if _lstat(consumer, path) is not None:
            raise GuardedSyncError('temporary path unavailable')
    for path, expected_state in states.items():
        if _snapshot(consumer, path)[0] != expected_state:
            raise GuardedSyncError('target changed')
    _index_clean(consumer, consumer_head, selection['paths'] + selection['temp_paths'])
    plan['plan_sha256'] = _digest(plan)
    return plan, files, lock_after, policy, kit, consumer


def prepare_plan(kit: Path, consumer: Path, binding: CoordinationBinding, *, context_id: str,
                 approved_revision: str, source_sha: str, selection: dict, selection_sha256: str,
                 manifest_path: str = 'docs/references/upgrades/sync-manifest.yaml') -> dict:
    """Return a private reviewable plan. The host independently approves it."""
    return _build(kit, consumer, binding, context_id=context_id, approved_revision=approved_revision,
                  source_sha=source_sha, selection=selection, selection_sha256=selection_sha256,
                  manifest_path=manifest_path)[0]


def _active(kit: Path, consumer: Path, policy, selection: dict, plan: dict,
            *, full: bool, path: str | None = None) -> None:
    if _git_head(kit) != plan['source_sha'] or _git_head(consumer) != plan['consumer_head']:
        raise GuardedSyncError('revision changed')
    if revision(consumer, policy._binding[1]) != plan['policy_revision']:
        raise GuardedSyncError('policy changed')
    if full or path is None:
        policy.fresh()
        _authorize(policy, plan['context_id'], selection)
        parents = _parents(consumer, selection)
    else:
        temporary = temp_path_for(plan['source_sha'], path)
        if path not in selection['paths'] or temporary not in selection['temp_paths']:
            raise GuardedSyncError('selection unavailable')
        parts = path.split('/')
        ancestors = ['/'.join(parts[:count]) for count in range(1, len(parts))]
        if any(item not in selection['metadata_paths'] for item in ancestors):
            raise GuardedSyncError('selection unavailable')
        _authorize(policy, plan['context_id'], {'paths': [path],
                   'temp_paths': [temporary], 'metadata_paths': ancestors})
        parents = _parents(consumer, {'metadata_paths': ancestors})
    if full:
        if parents != plan['directory_states']:
            raise GuardedSyncError('parent changed')
    else:
        for path, row in parents.items():
            original = plan['directory_states'][path]
            if any(row[key] != original[key] for key in ('dev', 'ino', 'mode')):
                raise GuardedSyncError('parent changed')
    if _snapshot(consumer, LOCK)[0] != plan['states'][LOCK]:
        raise GuardedSyncError('lock changed')
    if full:
        for path in selection['temp_paths']:
            if _lstat(consumer, path) is not None:
                raise GuardedSyncError('temporary path unavailable')
        for path, expected in plan['states'].items():
            if _snapshot(consumer, path)[0] != expected:
                raise GuardedSyncError('target changed')
        _index_clean(consumer, plan['consumer_head'], selection['paths'] + selection['temp_paths'])


def _write(kit: Path, consumer: Path, policy, selection: dict, plan: dict,
           path: str, data: bytes, mode: int, expected: dict) -> None:
    _active(kit, consumer, policy, selection, plan, full=False, path=path)
    if _snapshot(consumer, path)[0] != expected:
        raise GuardedSyncError('target changed')
    temporary = temp_path_for(plan['source_sha'], path)
    if temporary not in selection['temp_paths'] or _lstat(consumer, temporary) is not None:
        raise GuardedSyncError('temporary path unavailable')
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(consumer / temporary, flags, 0o600)
    ours = os.fstat(fd)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        row = _lstat(consumer, temporary)
        if row is None or (row.st_dev, row.st_ino) != (ours.st_dev, ours.st_ino):
            raise GuardedSyncError('temporary path changed')
        os.chmod(consumer / temporary, mode)
        _active(kit, consumer, policy, selection, plan, full=False, path=path)
        if _snapshot(consumer, path)[0] != expected:
            raise GuardedSyncError('target changed')
        row = _lstat(consumer, temporary)
        if row is None or (row.st_dev, row.st_ino) != (ours.st_dev, ours.st_ino):
            raise GuardedSyncError('temporary path changed')
        os.replace(consumer / temporary, consumer / path)
    finally:
        row = _lstat(consumer, temporary)
        if row is not None and (row.st_dev, row.st_ino) == (ours.st_dev, ours.st_ino):
            (consumer / temporary).unlink()


def _verify_final(kit: Path, consumer: Path, policy, selection: dict, plan: dict, files: dict) -> None:
    """Read back all selected C1, lock and refs after effects."""
    if (_git_head(kit) != plan['source_sha'] or _git_head(consumer) != plan['consumer_head']
            or revision(consumer, policy._binding[1]) != plan['policy_revision']):
        raise GuardedSyncError('revision changed')
    policy.fresh()
    _authorize(policy, plan['context_id'], selection)
    parents = _parents(consumer, selection)
    for path, row in parents.items():
        original = plan['directory_states'][path]
        if any(row[key] != original[key] for key in ('dev', 'ino', 'mode')):
            raise GuardedSyncError('parent changed')
    for path in selection['temp_paths']:
        if _lstat(consumer, path) is not None:
            raise GuardedSyncError('temporary path unavailable')
    _index_clean(consumer, plan['consumer_head'], selection['paths'] + selection['temp_paths'])
    for path, item in files.items():
        actual = _snapshot(consumer, path)[0]
        if actual.get('sha256') != item['sha256'] or actual.get('mode') != item['mode']:
            raise GuardedSyncError('target verification failed')
        if path in plan['c1']['unchanged'] and actual != plan['states'][path]:
            raise GuardedSyncError('target changed')
        if path in plan['c1']['add'] + plan['c1']['change']:
            expected_mode = '0755' if item['mode'] == '100755' else '0644'
            if actual.get('fs_mode') != expected_mode:
                raise GuardedSyncError('target verification failed')
    for path in plan['c1']['remove_previously_managed']:
        if _lstat(consumer, path) is not None:
            raise GuardedSyncError('target verification failed')
    lock_state = _snapshot(consumer, LOCK)[0]
    if plan['lock_after']['write']:
        if (lock_state.get('sha256') != plan['lock_after']['sha256']
                or lock_state.get('fs_mode') != plan['lock_after']['fs_mode']):
            raise GuardedSyncError('lock verification failed')
    elif lock_state != plan['states'][LOCK]:
        raise GuardedSyncError('lock changed')
    if (_git_head(kit) != plan['source_sha'] or _git_head(consumer) != plan['consumer_head']
            or revision(consumer, policy._binding[1]) != plan['policy_revision']):
        raise GuardedSyncError('revision changed')


def apply_plan(kit: Path, consumer: Path, binding: CoordinationBinding, *, context_id: str,
               approved_revision: str, source_sha: str, selection: dict, selection_sha256: str,
               expected_plan_sha256: str,
               manifest_path: str = 'docs/references/upgrades/sync-manifest.yaml') -> dict:
    """Rebuild and compare before effects; host authenticates approval externally."""
    if not isinstance(expected_plan_sha256, str) or not HASH.fullmatch(expected_plan_sha256):
        raise GuardedSyncError('plan approval unavailable')
    plan, files, lock_after, policy, kit, consumer = _build(
        kit, consumer, binding, context_id=context_id, approved_revision=approved_revision,
        source_sha=source_sha, selection=selection, selection_sha256=selection_sha256,
        manifest_path=manifest_path)
    selection = plan['selection']
    if plan['plan_sha256'] != expected_plan_sha256:
        raise GuardedSyncError('plan changed')
    _active(kit, consumer, policy, selection, plan, full=True)
    attempted = False
    try:
        for path in plan['c1']['remove_previously_managed']:
            if plan['states'][path]['kind'] == 'missing':
                continue
            _active(kit, consumer, policy, selection, plan, full=False, path=path)
            if _snapshot(consumer, path)[0] != plan['states'][path]:
                raise GuardedSyncError('target changed')
            attempted = True
            (consumer / path).unlink()
        for path in plan['c1']['add'] + plan['c1']['change']:
            attempted = True
            _write(kit, consumer, policy, selection, plan, path, files[path]['payload'],
                   0o755 if files[path]['mode'] == '100755' else 0o644, plan['states'][path])
        _active(kit, consumer, policy, selection, plan, full=False)
        _index_clean(consumer, plan['consumer_head'], selection['paths'] + selection['temp_paths'])
        for path, item in files.items():
            current = _snapshot(consumer, path)[0]
            if current.get('sha256') != item['sha256'] or current.get('mode') != item['mode']:
                raise GuardedSyncError('target verification failed')
            if path in plan['c1']['unchanged'] and current != plan['states'][path]:
                raise GuardedSyncError('target changed')
            if path in plan['c1']['add'] + plan['c1']['change']:
                expected_mode = '0755' if item['mode'] == '100755' else '0644'
                if current.get('fs_mode') != expected_mode:
                    raise GuardedSyncError('target verification failed')
        for path in plan['c1']['remove_previously_managed']:
            if _lstat(consumer, path) is not None:
                raise GuardedSyncError('target verification failed')
        if plan['lock_after']['write']:
            attempted = True
            _write(kit, consumer, policy, selection, plan, LOCK, lock_after, 0o600, plan['states'][LOCK])
        _verify_final(kit, consumer, policy, selection, plan, files)
    except Exception as exc:
        if attempted:
            raise GuardedSyncError('sync failed; partial effects may remain') from exc
        raise
    return {'ok': True, 'source_sha': source_sha, 'plan_sha256': plan['plan_sha256'],
            'managed_count': len(files), 'consumer_dirty': 'not_inspected',
            'external_approval': 'not_verified'}


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise GuardedSyncError('selection unavailable')
        result[key] = value
    return result


def _selection_file(path: Path, kit: Path, consumer: Path) -> dict:
    """Read an independently admitted selection outside both repositories."""
    path = Path(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > 4_000_000:
        raise GuardedSyncError('selection unavailable')
    real = path.resolve(strict=True)
    if real.is_relative_to(kit.resolve()) or real.is_relative_to(consumer.resolve()):
        raise GuardedSyncError('selection unavailable')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino, opened.st_nlink, opened.st_size) != (before.st_dev, before.st_ino, before.st_nlink, before.st_size):
            raise GuardedSyncError('selection unavailable')
        raw = stream.read(4_000_001)
        after = os.fstat(stream.fileno())
    if (len(raw) != before.st_size or len(raw) > 4_000_000
            or (after.st_dev, after.st_ino, after.st_nlink, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            != (opened.st_dev, opened.st_ino, opened.st_nlink, opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns)):
        raise GuardedSyncError('selection unavailable')
    selection = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_pairs)
    if not isinstance(selection, dict):
        raise GuardedSyncError('selection unavailable')
    return selection


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('kit', 'consumer', 'context', 'approved-revision', 'source-sha',
                   'selection-file', 'selection-sha256'):
        parser.add_argument('--' + option, required=True)
    parser.add_argument('--manifest', default='docs/references/upgrades/sync-manifest.yaml',
                        help='exact kit-relative manifest path')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--expected-plan-sha256')
    args = parser.parse_args(argv)
    if sys.platform == 'win32':
        print('guarded sync unavailable on Windows', file=sys.stderr)
        return 2
    if args.dry_run == (args.expected_plan_sha256 is not None):
        print('guarded sync requires B0 or externally approved apply digest', file=sys.stderr)
        return 2
    try:
        kit, consumer = Path(args.kit), Path(args.consumer)
        selection = _selection_file(Path(args.selection_file), kit, consumer)
        binding = CoordinationBinding.from_environment()
        kwargs = {'context_id': args.context, 'approved_revision': args.approved_revision,
                  'source_sha': args.source_sha, 'selection': selection,
                  'selection_sha256': args.selection_sha256, 'manifest_path': args.manifest}
        if args.dry_run:
            plan = prepare_plan(kit, consumer, binding, **kwargs)
            out = {'ok': True, 'mode': 'B0', 'plan_sha256': plan['plan_sha256'],
                   'source_sha': plan['source_sha'], 'managed_count': plan['c1']['managed_total'],
                   'add_count': len(plan['c1']['add']), 'change_count': len(plan['c1']['change']),
                   'remove_count': len(plan['c1']['remove_previously_managed']),
                   'consumer_dirty': 'not_inspected', 'external_approval': 'not_verified'}
        else:
            out = apply_plan(kit, consumer, binding, expected_plan_sha256=args.expected_plan_sha256, **kwargs)
        print(json.dumps(out, sort_keys=True, separators=(',', ':')))
        return 0
    except (ValueError, OSError, KeyError, TypeError, RuntimeError,
            yaml.YAMLError, subprocess.TimeoutExpired):
        # No consumer paths, lock bytes or exception details are disclosed.
        print('guarded sync unavailable; inspect authorized diagnostics and possible partial effects', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
