#!/usr/bin/env python3
"""Scan independently admitted changed Git text blobs; never a global audit."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_ROOT))
from scripts._common import ROOT
from wiki_core.context_packet import _check_trusted_binding, guarded_context_read, qualify_folder_context
from wiki_core.context_policy import PolicyError, revision, safe_path
from wiki_core.coordination_context import CoordinationBinding, _policy
from wiki_core.detectors import scan_text
from wiki_core.git_env import local_git_tree
from wiki_core.repository_reader import RepositoryReader, canonical_path

TEXT_SUFFIXES = frozenset({'.md', '.py', '.yaml', '.yml', '.json', '.txt', '.csv',
                           '.toml', '.ini', '.cfg', '.sh', '.js', '.jsx', '.ts',
                           '.tsx', '.mjs', '.cjs', '.css', '.html', '.xml', '.sql',
                           '.rst', '.ps1', '.bat', '.lock'})
MAX_BLOB_BYTES = 2_000_000
MAX_TOTAL_BYTES = 8_000_000
MAX_CHANGES = 512
FULL_SHA = re.compile(r'(?:[0-9a-f]{40}|[0-9a-f]{64})\Z')
SHA256 = re.compile(r'[0-9a-f]{64}\Z')
BRANCH = re.compile(r'wiki/[A-Za-z0-9][A-Za-z0-9._-]*\Z')


def _git(root: Path, *args: str) -> bytes:
    return local_git_tree(root, '-c', 'core.fsmonitor=false',
                          '-c', 'core.untrackedCache=false',
                          '-c', 'core.hooksPath=/dev/null',
                          '-c', 'core.useReplaceRefs=false', *args)


def _tree(root: Path, sha: str) -> dict[bytes, tuple[bytes, bytes, bytes]]:
    """Enumerate exact Git tree metadata without opening blob contents."""
    raw = _git(root, 'ls-tree', '-r', '-z', sha)
    if raw and not raw.endswith(b'\0'):
        raise PolicyError('proposal tree unavailable')
    tree = {}
    for item in raw.split(b'\0'):
        if not item:
            continue
        meta, separator, path = item.partition(b'\t')
        fields = meta.split(b' ')
        if not separator or len(fields) != 3 or not path or path in tree:
            raise PolicyError('proposal tree unavailable')
        tree[path] = tuple(fields)
    return tree


def _changes(before: dict, after: dict) -> list[dict[str, str]]:
    """Compare Git metadata only; a rename is deletion plus addition."""
    result = []
    for raw_path in before.keys() | after.keys():
        old, new = before.get(raw_path), after.get(raw_path)
        if old == new:
            continue
        try:
            path = raw_path.decode('utf-8')
            if canonical_path(path) != safe_path(path):
                raise PolicyError('proposal path unavailable')
        except (UnicodeError, ValueError) as exc:
            raise PolicyError('proposal path unavailable') from exc
        if Path(path).suffix.lower() not in TEXT_SUFFIXES:
            raise PolicyError('proposal path unsupported')
        if any(item is not None and (item[0] not in (b'100644', b'100755') or item[1] != b'blob')
               for item in (old, new)):
            raise PolicyError('proposal path unsupported')
        status = 'A' if old is None else 'D' if new is None else 'M'
        result.append({'status': status, 'path': path})
        if len(result) > MAX_CHANGES:
            raise PolicyError('proposal selection too large')
    if not result:
        raise PolicyError('proposal selection empty')
    return sorted(result, key=lambda row: row['path'])


def selection_digest(*, context_id: str, approved_revision: str, trusted_ref: str,
                     base: str, head: str, branch: str, changes: list[dict[str, str]]) -> str:
    """Bind a canonical path selection; the digest does not grant authority."""
    selection = {'schema_version': 'wiki.proposal-secrets-selection/v1',
                 'context_id': context_id, 'policy_revision': approved_revision,
                 'trusted_ref': trusted_ref, 'base': base, 'head': head,
                 'branch': branch, 'changes': changes}
    data = json.dumps(selection, sort_keys=True, ensure_ascii=True,
                      separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(data).hexdigest()


def _authorize_diff(policy, context_id: str, before: dict, after: dict, changes: list[dict]) -> None:
    """Reject unauthorized paths and exact blob aliases using tree metadata."""
    restricted_oids: set[bytes] = set()
    for tree in (before, after):
        for raw_path, (mode, kind, oid) in tree.items():
            try:
                path = safe_path(raw_path.decode('utf-8'))
            except (UnicodeError, ValueError) as exc:
                raise PolicyError('proposal tree cannot be classified') from exc
            try:
                canonical_path(path)
                owner = policy.owner_of(path)
                allowed = (owner == context_id and
                           policy._connection(owner, context_id, path, 'interpretation',
                                              'context', qualified=False) == 'approved')
            except ValueError:
                allowed = False
            if not allowed and kind == b'blob':
                restricted_oids.add(oid)
    for item in changes:
        path = item['path']
        if (policy.owner_of(path) != context_id
                or policy._connection(context_id, context_id, path, 'interpretation', 'context',
                                      qualified=False) != 'approved'):
            raise PolicyError('proposal selection unavailable')
        if item['status'] != 'D' and after[path.encode('utf-8')][2] in restricted_oids:
            raise PolicyError('proposal selection unavailable')


def audit_proposal(root: Path, binding: CoordinationBinding, *, context_id: str,
                   approved_revision: str, base: str, head: str, branch: str,
                   selection_sha256: str) -> dict:
    """Check changed Git blobs after independent admission; fail closed."""
    root = Path(root).resolve(strict=True)
    if (not isinstance(binding, CoordinationBinding) or binding.manifest != 'wiki.config.yaml'
            or not all(isinstance(value, str) and FULL_SHA.fullmatch(value)
                       for value in (approved_revision, base, head))
            or base != approved_revision or not isinstance(branch, str)
            or not BRANCH.fullmatch(branch) or '..' in branch or branch.endswith('.')
            or not isinstance(selection_sha256, str) or not SHA256.fullmatch(selection_sha256)):
        raise PolicyError('proposal authority unavailable')
    top = _git(root, 'rev-parse', '--show-toplevel').rstrip(b'\r\n')
    if not top or Path(top.decode('utf-8')).resolve(strict=True) != root:
        raise PolicyError('proposal root unavailable')
    policy = _policy(root, binding, context_id, approved_revision)
    _check_trusted_binding(root, policy, context_id, binding)

    def still_current() -> None:
        if (revision(root, binding.trusted_ref) != approved_revision
                or revision(root, 'refs/heads/' + branch) != head):
            raise PolicyError('proposal authority changed')

    still_current()
    _git(root, 'merge-base', '--is-ancestor', base, head)
    before, after = _tree(root, base), _tree(root, head)
    changes = _changes(before, after)
    if selection_digest(context_id=context_id, approved_revision=approved_revision,
                        trusted_ref=binding.trusted_ref, base=base, head=head,
                        branch=branch, changes=changes) != selection_sha256:
        raise PolicyError('proposal selection unavailable')
    _authorize_diff(policy, context_id, before, after, changes)
    entry_index = policy._context_indexes.get(context_id)
    if not entry_index:
        raise PolicyError('proposal context unavailable')
    qualify_folder_context(root, policy, context_id, context_id, entry_index, MAX_BLOB_BYTES)
    for item in changes:
        if policy.connection(context_id, context_id, item['path'], 'interpretation', 'context') != 'approved':
            raise PolicyError('proposal selection unavailable')
    reader = RepositoryReader(root, head)
    paths = set(reader.paths)
    scanned = [item['path'] for item in changes if item['status'] != 'D']
    if any(path not in paths for path in scanned):
        raise PolicyError('proposal content unavailable')
    total = 0
    for path in scanned:
        size = reader.blob_size(path)
        total += size
        if size > MAX_BLOB_BYTES or total > MAX_TOTAL_BYTES:
            raise PolicyError('proposal selection too large')
    findings = 0
    for path in scanned:
        still_current()
        item = guarded_context_read(reader, policy, path)
        if b'\0' in item['content'] or item['content'].startswith(b'version https://git-lfs.github.com/spec/v1'):
            raise PolicyError('proposal content unavailable')
        findings += sum(f.category == 'secret' for f in scan_text(item['text']))
    still_current()
    return {'schema_version': 'wiki.proposal-secrets-audit/v1',
            'state': 'failed' if findings else 'completed',
            'scope': 'proposal_changed_git_blobs', 'context_id': context_id,
            'policy_revision': approved_revision, 'base': base, 'head': head,
            'branch': branch, 'selection_sha256': selection_sha256,
            'scanned_count': len(scanned),
            'deleted_count': sum(item['status'] == 'D' for item in changes),
            'secret_findings': findings, 'global_audit': 'not_performed',
            'preflight': 'not_performed', 'normative_review': 'not_performed',
            'merge': 'not_performed', 'unchanged_nonbootstrap_bodies': 'not_inspected',
            'deleted_prior_nonbootstrap_bodies': 'not_inspected',
            'bootstrap_policy_and_context_bodies': 'read_external_authority_not_verified',
            'working_tree_boundary_metadata': 'inspected',
            'intermediate_history': 'not_inspected', 'working_tree_proposal_bodies': 'not_inspected'}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('context', 'approved-revision', 'base', 'head', 'branch', 'selection-sha256'):
        parser.add_argument('--' + option, required=True)
    args = parser.parse_args(argv)
    try:
        binding = CoordinationBinding.from_environment()
        result = audit_proposal(ROOT, binding, context_id=args.context,
                                approved_revision=args.approved_revision, base=args.base,
                                head=args.head, branch=args.branch,
                                selection_sha256=args.selection_sha256)
    except (ValueError, OSError, KeyError, TypeError, UnicodeError):
        print(json.dumps({'state': 'unavailable', 'scope': 'proposal_changed_git_blobs',
                          'coverage': 'unavailable', 'global_audit': 'not_performed'}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    return 0 if result['state'] == 'completed' else 1


if __name__ == '__main__':
    sys.exit(main())
