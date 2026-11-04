#!/usr/bin/env python3
"""Idempotent downstream sync for Wiki Viva Kit-owned files.

The command deliberately has only two operating modes:

* ``--dry-run`` prints B0 and never mutates the consumer;
* apply performs C1, then configured C2 generators, then explicit C3 commands.

The consumer PR is the review, rollback and promotion boundary.  ``kit.lock``
records the exact source and managed-file state without host paths or evidence.

Historical kit selection is checked before overwrite/prune, but an editable
lock cannot independently prove prior adoption. B0 needs project review.
The kit source, consumer and their Git configurations require exclusive or
cooperative custody during B0 and apply.
Descriptor-relative no-follow access prevents symlink traversal, but is not a
filesystem compare-and-swap against a non-cooperating writer. A failure after
C1 starts may leave partial changes; inspect them before continuing.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import secrets
import shlex
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wiki_core.git_env import local_git_environment, local_git_executable, local_git_tree
from wiki_core.git_safety import GitSafetyError, dangerous_local_config_keys


DEFAULT_MANIFEST = Path("docs/references/upgrades/sync-manifest.yaml")
LOCK_NAME = "kit.lock"


class SyncError(RuntimeError):
    """Expected operator-facing sync failure."""


def _run(argv: list[str], *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(argv, cwd=cwd, text=True, capture_output=True)
    if check and result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise SyncError(f"command failed ({shlex.join(argv)}): {detail}")
    return result


def _git(kit: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    try:
        result = subprocess.run([local_git_executable(), '--no-lazy-fetch', '-C', str(kit), *args],
                                input=input_bytes, capture_output=True, env=local_git_environment(), timeout=60)
    except (OSError, subprocess.TimeoutExpired, GitSafetyError) as exc:
        raise SyncError('kit Git source unavailable') from exc
    if result.returncode:
        raise SyncError('kit Git source unavailable')
    return result.stdout


def _source_clean(kit: Path) -> bool:
    # Disable status hooks; the closed environment discards inherited config.
    try:
        if dangerous_local_config_keys(kit):
            raise SyncError('kit Git config requires review')
    except GitSafetyError as exc:
        raise SyncError('kit Git config cannot be audited') from exc
    return not _git(kit, '-c', 'core.fsmonitor=false', '-c', 'core.untrackedCache=false',
                    '-c', 'core.hooksPath=/dev/null', 'status', '--porcelain=v1', '-z', '--untracked-files=all')


def _safe_rel(value: str) -> str:
    if (not isinstance(value, str) or not value or value.startswith('/') or '\\' in value
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or any(part in ('', '.', '..', '.git') for part in value.split('/'))):
        raise SyncError('unsafe kit or lock path')
    return value


def _assert_source_snapshot(kit: Path, sha: str) -> None:
    if _git(kit, 'rev-parse', '--verify', 'HEAD^{commit}').decode('ascii').strip() != sha or not _source_clean(kit):
        raise SyncError('kit source changed or is dirty; SHA-backed sync refused')


def _tree(kit: Path, sha: str) -> dict[str, tuple[str, str]]:
    try:
        raw = local_git_tree(kit, 'ls-tree', '-r', '-z', sha)
        result = {}
        for record in raw.split(b'\0'):
            if not record:
                continue
            meta, path = record.split(b'\t', 1)
            mode, kind, oid = meta.decode('ascii').split()
            ref = _safe_rel(path.decode('utf-8'))
            if ref in result:
                raise ValueError('duplicate path')
            result[ref] = (mode, oid if kind == 'blob' else '')
        return result
    except (GitSafetyError, ValueError, UnicodeError) as exc:
        raise SyncError('kit tree unavailable or invalid') from exc


def _blobs(kit: Path, oids: list[str]) -> dict[str, bytes]:
    """Read exact committed blobs after bounding their aggregate size."""
    unique = list(dict.fromkeys(oids))
    if not unique:
        return {}
    request = ''.join(oid + '\n' for oid in unique).encode('ascii')
    lines = _git(kit, 'cat-file', '--batch-check=%(objectname) %(objecttype) %(objectsize)', input_bytes=request).splitlines()
    if len(lines) != len(unique):
        raise SyncError('kit blob metadata unavailable')
    sizes = []
    for oid, line in zip(unique, lines):
        fields = line.split()
        if len(fields) != 3 or fields[0].decode('ascii') != oid or fields[1] != b'blob' or not fields[2].isdigit():
            raise SyncError('kit blob metadata invalid')
        size = int(fields[2])
        if size > 32_000_000:
            raise SyncError('kit blob exceeds size limit')
        sizes.append(size)
    if sum(sizes) > 128_000_000:
        raise SyncError('kit selected blobs exceed size limit')
    stream = _git(kit, 'cat-file', '--batch', input_bytes=request)
    cursor = 0
    result = {}
    for oid, size in zip(unique, sizes):
        end = stream.find(b'\n', cursor)
        if end < 0 or stream[cursor:end] != f'{oid} blob {size}'.encode('ascii'):
            raise SyncError('kit blob batch invalid')
        cursor = end + 1
        data = stream[cursor:cursor + size]
        cursor += size
        if len(data) != size or stream[cursor:cursor + 1] != b'\n':
            raise SyncError('kit blob batch incomplete')
        cursor += 1
        result[oid] = data
    if cursor != len(stream):
        raise SyncError('kit blob batch invalid')
    return result


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return _sha256_bytes(payload.encode("utf-8"))


def _matches(path: str, pattern: str) -> bool:
    pattern = pattern.strip("/")
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        ancestors = ("/".join(path.split("/")[:depth]) for depth in range(1, path.count("/") + 2))
        return any(fnmatch.fnmatchcase(ancestor, prefix) for ancestor in ancestors)
    # Manifest patterns are repository-root-relative. PurePosixPath.match()
    # treats a bare filename as a basename match at any depth, which made a
    # root-only block such as ``wiki.config.yaml`` also remove the demo's own
    # self-contained fixture registry.
    return fnmatch.fnmatchcase(path, pattern)


def _validate_manifest(value: dict[str, Any]) -> None:
    if value.get("schema_version") != "wiki_viva_sync_manifest.v1":
        raise SyncError("sync manifest must use wiki_viva_sync_manifest.v1")
    portable = value.get("portable")
    if not isinstance(portable, dict) or not portable.get("allow"):
        raise SyncError("sync manifest portable.allow must be a non-empty list")
    for key in ("allow", "block"):
        patterns = portable.get(key, [])
        if not isinstance(patterns, list) or not all(isinstance(item, str) for item in patterns):
            raise SyncError(f"sync manifest portable.{key} must be a list of strings")
    c2 = value.get("c2_commands", [])
    if not isinstance(c2, list) or not all(isinstance(item, list) and item for item in c2):
        raise SyncError("sync manifest c2_commands must be a list of argv lists")


def _tracked_files(kit: Path, manifest: dict[str, Any], tree: dict[str, tuple[str, str]]) -> dict[str, dict[str, Any]]:
    allowed = manifest["portable"]["allow"]
    blocked = manifest["portable"].get("block", [])
    selected: dict[str, dict[str, Any]] = {}
    for path, (mode, oid) in tree.items():
        if not any(_matches(path, pattern) for pattern in allowed):
            continue
        if any(_matches(path, pattern) for pattern in blocked):
            continue
        if mode not in {"100644", "100755"} or not oid:
            raise SyncError(f"portable selection refuses non-regular file {path} ({mode})")
        selected[path] = {"oid": oid, "mode": mode}
    if not selected:
        raise SyncError("portable selection is empty")
    blobs = _blobs(kit, [item['oid'] for item in selected.values()])
    for item in selected.values():
        payload = blobs[item.pop('oid')]
        item.update(sha256=_sha256_bytes(payload), size=len(payload), payload=payload)
    return dict(sorted(selected.items()))


def _verify_managed_history(kit: Path, lock: dict[str, Any], manifest_rel: str, paths: list[str]) -> None:
    """Check prior kit selection, not proof that it was actually adopted."""
    if not paths:
        return
    previous_sha = lock.get('source_sha')
    if not isinstance(previous_sha, str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', previous_sha):
        raise SyncError('managed history unavailable; no files changed')
    tree = _tree(kit, previous_sha)
    if manifest_rel not in tree or tree[manifest_rel][0] not in ('100644', '100755'):
        raise SyncError('managed manifest unavailable in historical kit')
    try:
        historical = yaml.safe_load(_blobs(kit, [tree[manifest_rel][1]])[tree[manifest_rel][1]])
    except (yaml.YAMLError, UnicodeError) as exc:
        raise SyncError('managed manifest invalid in historical kit') from exc
    if not isinstance(historical, dict):
        raise SyncError('managed manifest invalid in historical kit')
    _validate_manifest(historical)
    if _canonical_sha256(historical) != lock.get('manifest_sha256'):
        raise SyncError('managed manifest differs from locked historical source')
    allow = historical['portable']['allow']
    block = historical['portable'].get('block', [])
    for path in paths:
        if (not any(_matches(path, pattern) for pattern in allow)
                or any(_matches(path, pattern) for pattern in block)
                or path not in tree or tree[path][0] not in ('100644', '100755')):
            raise SyncError('managed path was not selected by historical kit')
    blobs = _blobs(kit, [tree[path][1] for path in paths])
    for path in paths:
        meta = lock['managed_files'][path]
        if meta['mode'] != tree[path][0] or meta['sha256'] != _sha256_bytes(blobs[tree[path][1]]):
            raise SyncError('managed path differs from historical kit')


def _load_lock(consumer: Path) -> dict[str, Any]:
    root_fd = _open_root(consumer)
    try:
        try:
            fd = os.open(LOCK_NAME, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=root_fd)
        except FileNotFoundError:
            return {}
        except OSError as exc:
            raise SyncError('kit.lock is unsafe or unavailable') from exc
        with os.fdopen(fd, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise SyncError('kit.lock must be a regular file')
            raw = stream.read(16_000_001)
            if len(raw) > 16_000_000:
                raise SyncError('kit.lock exceeds size limit')
        try:
            value = yaml.safe_load(raw)
        except (yaml.YAMLError, UnicodeError) as exc:
            raise SyncError('kit.lock is invalid') from exc
    finally:
        os.close(root_fd)
    if not isinstance(value, dict):
        raise SyncError('kit.lock must contain a mapping')
    if value.get("schema_version") != "wiki_viva_kit_lock.v1":
        raise SyncError("existing kit.lock has an unsupported schema_version")
    return value


def _open_root(root: Path) -> int:
    if (os.name != 'posix' or not hasattr(os, 'O_NOFOLLOW') or not hasattr(os, 'O_DIRECTORY')
            or any(fn not in os.supports_dir_fd for fn in (os.open, os.stat, os.mkdir, os.unlink, os.rename, os.link))
            or os.stat not in os.supports_follow_symlinks or os.link not in os.supports_follow_symlinks):
        raise SyncError('safe no-follow sync is unavailable on this platform')
    try:
        return os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        raise SyncError('consumer root is unsafe or unavailable') from exc


def _parent_fd(root_fd: int, rel: str, *, create: bool = False) -> int | None:
    parts = _safe_rel(rel).split('/')[:-1]
    current = os.dup(root_fd)
    try:
        for part in parts:
            try:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            except FileNotFoundError:
                if not create:
                    os.close(current)
                    return None
                os.mkdir(part, mode=0o755, dir_fd=current)
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            os.close(current)
            current = child
        return current
    except OSError as exc:
        os.close(current)
        raise SyncError('unsafe or unavailable consumer ancestor') from exc


def _file_state(root_fd: int, rel: str) -> dict[str, Any]:
    parent = _parent_fd(root_fd, rel)
    if parent is None:
        return {'kind': 'missing'}
    try:
        name = _safe_rel(rel).split('/')[-1]
        try:
            entry = os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return {'kind': 'missing'}
        if stat.S_ISLNK(entry.st_mode):
            return {'kind': 'symlink'}
        if not stat.S_ISREG(entry.st_mode):
            return {'kind': 'other'}
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
            with os.fdopen(fd, 'rb') as stream:
                opened = os.fstat(stream.fileno())
                if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (entry.st_dev, entry.st_ino):
                    raise SyncError('consumer file changed during inspection')
                digest = hashlib.sha256()
                while data := stream.read(1024 * 1024):
                    digest.update(data)
                after = os.fstat(stream.fileno())
                if (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                    raise SyncError('consumer file changed during inspection')
                return {'kind': 'file', 'sha256': digest.hexdigest(),
                        'mode': '100755' if opened.st_mode & 0o111 else '100644',
                        'identity': (opened.st_dev, opened.st_ino)}
        except OSError as exc:
            raise SyncError('consumer file changed or is unsafe') from exc
    finally:
        os.close(parent)


def _consumer_snapshot(consumer: Path, paths: dict[str, dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], tuple[int, int]]:
    root_fd = _open_root(consumer)
    try:
        info = os.fstat(root_fd)
        return {rel: _file_state(root_fd, rel) for rel in paths}, (info.st_dev, info.st_ino)
    finally:
        os.close(root_fd)


def _consumer_state(consumer: Path, paths: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return _consumer_snapshot(consumer, paths)[0]


def _git_dirty(root: Path) -> list[str]:
    try:
        if dangerous_local_config_keys(root):
            raise SyncError('consumer Git config requires review')
    except GitSafetyError as exc:
        raise SyncError('consumer Git config cannot be audited') from exc
    raw = _git(root, '-c', 'core.fsmonitor=false', '-c', 'core.untrackedCache=false',
               '-c', 'core.hooksPath=/dev/null', 'status', '--porcelain=v1', '-z', '--untracked-files=all')
    return [item for item in raw.decode('utf-8').split('\0') if item]


def build_plan(kit: Path, consumer: Path, manifest_path: Path, c3_commands: list[list[str]]) -> dict[str, Any]:
    if Path(_git(kit, 'rev-parse', '--show-toplevel').decode('utf-8').strip()).resolve() != kit.resolve():
        raise SyncError('kit path must be its Git root')
    source_sha = _git(kit, 'rev-parse', '--verify', 'HEAD^{commit}').decode('ascii').strip()
    _assert_source_snapshot(kit, source_sha)
    try:
        manifest_rel = _safe_rel(manifest_path.relative_to(kit).as_posix())
    except ValueError as exc:
        raise SyncError('sync manifest must belong to the kit') from exc
    tree_entries = _tree(kit, source_sha)
    if manifest_rel not in tree_entries or tree_entries[manifest_rel][0] not in ('100644', '100755'):
        raise SyncError('sync manifest is not a regular file in the kit commit')
    manifest_raw = _blobs(kit, [tree_entries[manifest_rel][1]])[tree_entries[manifest_rel][1]]
    try:
        manifest = yaml.safe_load(manifest_raw)
    except (yaml.YAMLError, UnicodeError) as exc:
        raise SyncError('committed sync manifest is invalid') from exc
    if not isinstance(manifest, dict):
        raise SyncError('committed sync manifest must be a mapping')
    _validate_manifest(manifest)
    files = _tracked_files(kit, manifest, tree_entries)
    prior_lock = _load_lock(consumer)
    previous = prior_lock.get("managed_files", {})
    if not isinstance(previous, dict):
        raise SyncError("kit.lock managed_files must be a mapping")
    for path, metadata in previous.items():
        _safe_rel(path)
        if (not isinstance(metadata, dict) or set(metadata) != {'sha256', 'mode'}
                or not isinstance(metadata['sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', metadata['sha256'])
                or metadata['mode'] not in ('100644', '100755')):
            raise SyncError('kit.lock managed file metadata is invalid')
    if LOCK_NAME in files or LOCK_NAME in previous:
        raise SyncError('kit.lock is a reserved sync path')
    observed = {**{path: {} for path in previous}, **files, LOCK_NAME: {}}
    current, consumer_identity = _consumer_snapshot(consumer, observed)
    if any(item['kind'] in ('symlink', 'other') for item in current.values()):
        raise SyncError('consumer has an unsafe managed destination')

    added: list[str] = []
    changed: list[str] = []
    unchanged: list[str] = []
    for rel, expected in files.items():
        actual = current[rel]
        if actual["kind"] == "missing":
            added.append(rel)
        elif actual.get("sha256") == expected["sha256"] and actual.get("mode") == expected["mode"]:
            unchanged.append(rel)
        else:
            changed.append(rel)
    removed = sorted(set(previous) - set(files))
    historical_required = sorted(set(removed) | {path for path in changed
                                  if path in previous and current[path]['kind'] == 'file'})
    _verify_managed_history(kit, prior_lock, manifest_rel, historical_required)
    if any(path not in previous and current[path]['kind'] == 'file' for path in changed):
        raise SyncError('unmanaged consumer file conflicts with kit; explicit migration required')
    for path in set(changed) | set(removed):
        if path in previous and current[path]['kind'] == 'file':
            if any(current[path][key] != previous[path][key] for key in ('sha256', 'mode')):
                raise SyncError('previously managed consumer file has local changes')
    tree = [{"path": rel, "sha256": item["sha256"], "mode": item["mode"]} for rel, item in files.items()]
    _assert_source_snapshot(kit, source_sha)
    return {
        "schema_version": "wiki_viva_sync_plan.v1",
        "mode": "B0_dry_run",
        "source_sha": source_sha,
        "manifest_sha256": _canonical_sha256(manifest),
        "portable_tree_sha256": _canonical_sha256(tree),
        "consumer_dirty": _git_dirty(consumer),
        "consumer_custody": "exclusive/cooperative custody of kit, consumer and Git configurations required during B0/apply; no filesystem CAS",
        "history_limit": "historical selection does not prove adoption; review B0",
        "c1": {
            "managed_total": len(files),
            "add": added,
            "change": changed,
            "remove_previously_managed": removed,
            "unchanged": len(unchanged),
        },
        "c2_commands": manifest.get("c2_commands", []),
        "c3_commands": c3_commands,
        "_files": files,
        "_manifest": manifest,
        "_consumer_before": current,
        "_consumer_identity": consumer_identity,
    }


def _public_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in plan.items() if not key.startswith("_")}


def _print_plan(plan: dict[str, Any], *, as_json: bool) -> None:
    public = _public_plan(plan)
    if as_json:
        print(json.dumps(public, indent=2, ensure_ascii=False, sort_keys=True))
        return
    c1 = public["c1"]
    print(f"B0 source: {public['source_sha']}")
    print(f"PRECONDITION: {public['consumer_custody']}")
    print(f"HISTORY: {public['history_limit']}")
    print(
        "C1 managed={managed_total} add={add} change={change} remove={remove} unchanged={unchanged}".format(
            managed_total=c1["managed_total"], add=len(c1["add"]), change=len(c1["change"]),
            remove=len(c1["remove_previously_managed"]), unchanged=c1["unchanged"]
        )
    )
    for label, key in (("+", "add"), ("~", "change"), ("-", "remove_previously_managed")):
        for path in c1[key]:
            print(f"  {label} {path}")
    for argv in public["c2_commands"]:
        print(f"C2: {shlex.join(argv)}")
    if public["c3_commands"]:
        for argv in public["c3_commands"]:
            print(f"C3: {shlex.join(argv)}")
    else:
        print("C3: no consumer-owned command declared")
    if public["consumer_dirty"]:
        print(f"NOTICE: consumer has {len(public['consumer_dirty'])} dirty entry/entries")


def _replace_bytes(root_fd: int, rel: str, payload: bytes, mode: str, before: dict[str, Any]) -> None:
    parent = _parent_fd(root_fd, rel, create=True)
    assert parent is not None
    name = _safe_rel(rel).split('/')[-1]
    temp = '.wiki-sync-' + secrets.token_hex(16)
    try:
        if _file_state(root_fd, rel) != before:
            raise SyncError('consumer target changed before write')
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
            os.fchmod(stream.fileno(), 0o755 if mode == '100755' else 0o644)
        if before['kind'] == 'missing':
            # Hard-link creation fails if another actor created the leaf.
            os.link(temp, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
            os.unlink(temp, dir_fd=parent)
        else:
            os.rename(temp, name, src_dir_fd=parent, dst_dir_fd=parent)
    except OSError as exc:
        raise SyncError('consumer write unavailable or target changed') from exc
    finally:
        try:
            os.unlink(temp, dir_fd=parent)
        except FileNotFoundError:
            pass
        os.close(parent)


def _copy_c1(kit: Path, consumer: Path, plan: dict[str, Any]) -> None:
    _assert_source_snapshot(kit, plan['source_sha'])
    if any(_sha256_bytes(item['payload']) != item['sha256'] for item in plan['_files'].values()):
        raise SyncError('committed kit blob changed before C1')
    root_fd = _open_root(consumer)
    try:
        info = os.fstat(root_fd)
        if (info.st_dev, info.st_ino) != plan['_consumer_identity']:
            raise SyncError('consumer root changed before C1')
        current = {path: _file_state(root_fd, path) for path in plan['_consumer_before']}
        if current != plan['_consumer_before']:
            raise SyncError('consumer managed paths changed before C1')
        if any(item['kind'] in ('symlink', 'other') for item in current.values()):
            raise SyncError('consumer has an unsafe managed destination')
        for rel in plan['c1']['remove_previously_managed']:
            if current[rel]['kind'] == 'missing':
                continue
            parent = _parent_fd(root_fd, rel)
            if parent is None:
                raise SyncError('consumer removal target changed')
            try:
                if _file_state(root_fd, rel) != current[rel]:
                    raise SyncError('consumer removal target changed')
                os.unlink(rel.split('/')[-1], dir_fd=parent)
            finally:
                os.close(parent)
        for rel in plan['c1']['add'] + plan['c1']['change']:
            item = plan['_files'][rel]
            _replace_bytes(root_fd, rel, item['payload'], item['mode'], current[rel])
    except OSError as exc:
        raise SyncError('C1 unavailable; consumer may be partially changed') from exc
    finally:
        os.close(root_fd)


def _verify_consumer(consumer: Path, plan: dict[str, Any]) -> None:
    root_fd = _open_root(consumer)
    try:
        info = os.fstat(root_fd)
        if (info.st_dev, info.st_ino) != plan['_consumer_identity']:
            raise SyncError('consumer root changed after C1')
        for path, item in plan['_files'].items():
            actual = _file_state(root_fd, path)
            if (actual.get('kind') != 'file' or actual.get('sha256') != item['sha256']
                    or actual.get('mode') != item['mode']):
                raise SyncError('consumer managed file differs from kit commit')
        for path in plan['c1']['remove_previously_managed']:
            if _file_state(root_fd, path)['kind'] != 'missing':
                raise SyncError('consumer pruned file remains or changed')
        if _file_state(root_fd, LOCK_NAME) != plan['_consumer_before'][LOCK_NAME]:
            raise SyncError('consumer kit.lock changed during sync')
    finally:
        os.close(root_fd)


def _write_lock(consumer: Path, plan: dict[str, Any]) -> None:
    lock = {
        "schema_version": "wiki_viva_kit_lock.v1",
        "source_sha": plan["source_sha"],
        "manifest_sha256": plan["manifest_sha256"],
        "portable_tree_sha256": plan["portable_tree_sha256"],
        "managed_files": {
            rel: {"sha256": item["sha256"], "mode": item["mode"]}
            for rel, item in plan["_files"].items()
        },
    }
    payload = yaml.safe_dump(lock, sort_keys=True, allow_unicode=True).encode('utf-8')
    root_fd = _open_root(consumer)
    try:
        info = os.fstat(root_fd)
        if (info.st_dev, info.st_ino) != plan['_consumer_identity']:
            raise SyncError('consumer root changed before kit.lock')
        _replace_bytes(root_fd, LOCK_NAME, payload, '100644', plan['_consumer_before'][LOCK_NAME])
    finally:
        os.close(root_fd)


def _parse_command(raw: str) -> list[str]:
    command = shlex.split(raw)
    if not command:
        raise argparse.ArgumentTypeError("command cannot be empty")
    return command


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit", type=Path, default=Path.cwd())
    parser.add_argument("--consumer", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="print B0 without mutation")
    parser.add_argument("--json", action="store_true", help="emit the plan as JSON")
    parser.add_argument("--allow-dirty", action="store_true", help="allow apply in a dirty consumer")
    parser.add_argument("--c3-command", action="append", default=[], type=_parse_command)
    args = parser.parse_args(argv)

    kit = args.kit.resolve()
    consumer = args.consumer.resolve()
    manifest_path = (args.manifest.resolve() if args.manifest else kit / DEFAULT_MANIFEST)
    try:
        if _git(kit, 'rev-parse', '--is-inside-work-tree').strip() != b'true':
            raise SyncError("--kit must be a Git worktree")
        if not consumer.is_dir():
            raise SyncError("--consumer must be an existing directory")
        if kit == consumer or kit.is_relative_to(consumer) or consumer.is_relative_to(kit):
            raise SyncError('kit and consumer must be independent roots')
        if _git(consumer, 'rev-parse', '--is-inside-work-tree').strip() != b'true':
            raise SyncError("--consumer must be a Git worktree")
        plan = build_plan(kit, consumer, manifest_path, args.c3_command)
        _print_plan(plan, as_json=args.json)
        if args.dry_run:
            return 0
        if plan["consumer_dirty"] and not args.allow_dirty:
            raise SyncError("apply requires a clean consumer; review B0 or pass --allow-dirty deliberately")
        _assert_source_snapshot(kit, plan['source_sha'])
        try:
            _copy_c1(kit, consumer, plan)
            _assert_source_snapshot(kit, plan['source_sha'])
            _verify_consumer(consumer, plan)
        except (SyncError, OSError) as exc:
            raise SyncError('C1 stopped; consumer may be partially changed; C2/C3 and lock not run') from exc
        try:
            for command in plan["c2_commands"]:
                _assert_source_snapshot(kit, plan['source_sha'])
                _run([str(part) for part in command], cwd=consumer)
            for command in plan["c3_commands"]:
                _assert_source_snapshot(kit, plan['source_sha'])
                _run(command, cwd=consumer)
            _assert_source_snapshot(kit, plan['source_sha'])
            _verify_consumer(consumer, plan)
            _write_lock(consumer, plan)
            _assert_source_snapshot(kit, plan['source_sha'])
        except (SyncError, OSError) as exc:
            raise SyncError('sync stopped after C1; consumer may be partially changed; inspect C2/C3 and kit.lock') from exc
        print(f"APPLIED source={plan['source_sha']} managed={len(plan['_files'])} lock={LOCK_NAME}")
        return 0
    except (SyncError, OSError) as exc:
        print(f"wiki_sync_from_kit: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
