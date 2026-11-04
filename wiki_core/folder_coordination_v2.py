"""Opt-in, host-bound folder coordination; no transport or ACL is provided.

Only trusted host code may construct and retain a binding. Request data must
never be used to configure it. The host must independently authorize access
to repository metadata and the mechanical controls; this module cannot prove
an actor's identity or sandbox its filesystem. The approval ref is fixed to
origin/main and must be maintained by the host's separate review process.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from wiki_core.context_policy import _git, safe_path
from wiki_core.folder_declarations_v2 import preauthorize_index
from wiki_core.folder_integration_v2 import preflight_folder_v2
from wiki_core.folder_packet_v2 import build_folder_packet_v2
from wiki_core.folder_policy_v2 import _at_revision, load_folder_policy_v2
from wiki_core.repo_read import contains_access_secrets, remote_identity


class FolderCoordinationError(ValueError):
    """Opaque host-facing error; it contains no repository or source data."""


@dataclass(frozen=True)
class FolderHostBinding:
    """Trusted host configuration, not a user-supplied capability assertion."""

    root: Path
    folders: tuple[str, ...]
    independent_repos: tuple[tuple[str, Path, str, str], ...] = ()

    def __post_init__(self):
        try:
            root = Path(self.root)
        except (OSError, RuntimeError, ValueError, TypeError):
            raise ValueError('invalid host root') from None
        if not root.is_absolute():
            raise ValueError('absolute host root required')
        if not isinstance(self.folders, tuple) or not 1 <= len(self.folders) <= 64:
            raise ValueError('bounded host folders required')
        try:
            folders = tuple(safe_path(value, allow_root=True) for value in self.folders)
        except (ValueError, TypeError):
            raise ValueError('invalid host folder binding') from None
        if folders != self.folders or len(set(folders)) != len(folders):
            raise ValueError('invalid host folder binding')
        try:
            root = root.resolve()
        except (OSError, RuntimeError, ValueError, TypeError):
            raise ValueError('invalid host root') from None
        object.__setattr__(self, 'root', root)
        if not isinstance(self.independent_repos, tuple) or len(self.independent_repos) > 32:
            raise ValueError('invalid independent repository binding')
        normalized = []
        try:
            for pair in self.independent_repos:
                if not isinstance(pair, tuple) or len(pair) != 4 or not isinstance(pair[2], str):
                    raise ValueError('invalid binding')
                folder = safe_path(pair[0], allow_root=True)
                repo_root = Path(pair[1])
                identity = pair[2]
                repo_path = safe_path(pair[3])
                if (folder not in self.folders or not repo_root.is_absolute()
                        or remote_identity('https://' + identity)[0] != identity):
                    raise ValueError('invalid binding')
                normalized.append((folder, repo_root.resolve(), identity, repo_path))
        except (OSError, RuntimeError, ValueError, TypeError):
            raise ValueError('invalid independent repository binding') from None
        if len(set(normalized)) != len(normalized):
            raise ValueError('invalid independent repository binding')
        object.__setattr__(self, 'independent_repos', tuple(normalized))


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', value):
        raise FolderCoordinationError('fixed revision required')
    return value


def _bound_policy(root, binding, folder, approved):
    # Reject outside the binding before any repository or policy body access.
    if not isinstance(binding, FolderHostBinding):
        raise FolderCoordinationError('host binding unavailable')
    if not isinstance(folder, str) or folder not in binding.folders:
        raise FolderCoordinationError('folder unavailable or unauthorized')
    try:
        requested_root = Path(root).resolve()
    except (OSError, RuntimeError, ValueError, TypeError):
        raise FolderCoordinationError('repository unavailable or unauthorized') from None
    if requested_root != binding.root:
        raise FolderCoordinationError('repository unavailable or unauthorized')
    approved = _sha(approved)
    try:
        policy = load_folder_policy_v2(binding.root, approved)
        if folder not in policy.folder_ids:
            raise ValueError('folder unavailable')
        return policy
    except (ValueError, OSError, KeyError, TypeError):
        raise FolderCoordinationError('approved folder policy unavailable') from None


def _output_authorized(policy, folder, output):
    context = policy.folder_ids[folder]
    output = safe_path(output)
    if (policy.owner_of(output) != context or not policy.permits(context, 'read', output)
            or not policy.permits(context, 'write', output)):
        raise FolderCoordinationError('output unavailable or unauthorized')


def _preauthorize_evidence(root, policy, folder, content, evidence):
    """Check all current and historical selectors before any source body."""
    if not isinstance(evidence, list) or len(evidence) > 128 or contains_access_secrets(evidence):
        raise FolderCoordinationError('evidence unavailable or unauthorized')
    context = policy.folder_ids[folder]
    selections = []
    allowed = {'path', 'producer_folder', 'reason', 'use', 'classification', 'section', 'field'}
    for entry in evidence:
        if (not isinstance(entry, dict) or set(entry) - allowed
                or not all(isinstance(entry.get(k), str) and entry[k].strip()
                           for k in ('path', 'producer_folder', 'reason', 'use', 'classification'))
                or ('section' in entry and 'field' in entry)
                or any(k in entry and (not isinstance(entry[k], str) or not entry[k].strip())
                       for k in ('section', 'field'))):
            raise FolderCoordinationError('evidence unavailable or unauthorized')
        path = safe_path(entry['path'])
        producer = policy.folder_ids.get(entry['producer_folder'])
        kwargs = {key: entry[key] for key in ('section', 'field') if key in entry}
        if producer is None or policy.connection(producer, context, path, entry['use'],
                                                  entry['classification'], **kwargs) != 'approved':
            raise FolderCoordinationError('evidence unavailable or unauthorized')
        selections.append((entry, path, producer, kwargs))
    _git(root, 'merge-base', '--is-ancestor', content, policy.policy_revision)
    if content == policy.policy_revision or not selections:
        return
    # The host must be authorized for this repository's mechanical control
    # bodies and metadata; no sibling instruction/source body is opened here.
    historical = _at_revision(Path(root), content, policy.controls_path)
    if historical.folder_ids.get(folder) != context:
        raise FolderCoordinationError('historical authority unavailable')
    for entry, path, producer, kwargs in selections:
        if (historical.folder_ids.get(entry['producer_folder']) != producer
                or historical.connection(producer, context, path, entry['use'],
                                         entry['classification'], **kwargs) != 'approved'):
            raise FolderCoordinationError('historical authority unavailable')


def prepare_folder_packet(root, binding, payload):
    """Compose an exact v2 packet for one host-authorized folder and revision."""
    required = {'folder', 'approved_revision', 'content_revision', 'task'}
    if not isinstance(payload, dict) or set(payload) != required:
        raise FolderCoordinationError('invalid request')
    if contains_access_secrets(payload):
        raise FolderCoordinationError('invalid request')
    policy = _bound_policy(root, binding, payload['folder'], payload['approved_revision'])
    task = payload['task']
    keys = {'index_path', 'task_id', 'goal', 'output', 'integrator', 'max_bytes', 'evidence'}
    if (not isinstance(task, dict) or not keys <= set(task) or set(task) - (keys | {'index_section', 'ingestion_binding'})
            or type(task['max_bytes']) is not int or not 1 <= task['max_bytes'] <= 1_000_000):
        raise FolderCoordinationError('invalid request')
    try:
        content = _sha(payload['content_revision'])
        folder = payload['folder']
        _output_authorized(policy, folder, task['output'])
        preauthorize_index(policy, folder, task['index_path'])
        _preauthorize_evidence(binding.root, policy, folder, content, task['evidence'])
        policy = policy.fresh()
        packet = build_folder_packet_v2(binding.root, policy, folder, task['max_bytes'],
                    content_revision=content, index_path=task['index_path'],
                    index_section=task.get('index_section'), task_id=task['task_id'],
                    goal=task['goal'], output=task['output'], integrator=task['integrator'],
                    evidence=task['evidence'], ingestion_binding=task.get('ingestion_binding'))
        policy.fresh()
        return {'schema_version': 'wiki.folder-host-packet/v2', 'mode': 'host_bound',
                'packet': packet, 'enforcement_claim': 'none'}
    except FolderCoordinationError:
        raise
    except (ValueError, OSError, KeyError, TypeError, AttributeError):
        raise FolderCoordinationError('folder packet unavailable') from None


def prepare_folder_preflight(root, binding, payload):
    """Preflight an exact v2 proposal, without approving, merging or executing."""
    required = {'folder', 'approved_revision', 'base', 'head', 'branch', 'packet', 'result'}
    if not isinstance(payload, dict) or not required <= set(payload) or set(payload) - (required | {'source_request'}):
        raise FolderCoordinationError('invalid request')
    if contains_access_secrets(payload):
        raise FolderCoordinationError('invalid request')
    policy = _bound_policy(root, binding, payload['folder'], payload['approved_revision'])
    try:
        base, head = _sha(payload['base']), _sha(payload['head'])
        if base != policy.policy_revision:
            raise FolderCoordinationError('approved base unavailable')
        packet = payload['packet']
        if (not isinstance(packet, dict) or packet.get('schema_version') != 'wiki.folder-task-context/v2'
                or packet.get('context_folder') != payload['folder']
                or packet.get('context_id') != policy.folder_ids[payload['folder']]
                or packet.get('policy_revision') != policy.policy_revision
                or packet.get('start_folder') is not None):
            raise FolderCoordinationError('folder packet unavailable')
        if (not isinstance(payload['result'], dict)
                or payload['result'].get('schema_version') != 'wiki.folder-task-result/v2'
                or contains_access_secrets(packet) or contains_access_secrets(payload['result'])):
            raise FolderCoordinationError('folder result unavailable')
        changes = payload['result'].get('changes')
        if (not isinstance(changes, list) or not any(
                isinstance(change, dict) and change.get('path') == packet.get('output')
                and change.get('action') in ('created', 'modified', 'deleted') for change in changes)):
            raise FolderCoordinationError('declared output change unavailable')
        _output_authorized(policy, payload['folder'], packet['output'])
        preauthorize_index(policy, payload['folder'], packet['index_path'])
        by_id = {value: key for key, value in policy.folder_ids.items()}
        evidence = []
        for row in packet['inputs']:
            if row.get('kind') != 'evidence':
                continue
            entry = {key: row[key] for key in ('path', 'reason', 'use', 'classification')}
            entry['producer_folder'] = by_id[row['producer_context']]
            for key in ('section', 'field'):
                if row.get(key) is not None:
                    entry[key] = row[key]
            evidence.append(entry)
        _preauthorize_evidence(binding.root, policy, payload['folder'], _sha(packet['content_revision']), evidence)
        policy = policy.fresh()
        outcome = preflight_folder_v2(binding.root, policy, base=base, head=head,
                         branch=payload['branch'], packet=packet, result=payload['result'],
                         binding=binding, source_request=payload.get('source_request'))
        policy.fresh()
        return {'schema_version': 'wiki.folder-host-preflight/v2', 'mode': 'host_bound',
                'preflight': outcome, 'enforcement_claim': 'none'}
    except FolderCoordinationError:
        raise
    except (ValueError, OSError, KeyError, TypeError, AttributeError):
        raise FolderCoordinationError('folder preflight unavailable') from None
