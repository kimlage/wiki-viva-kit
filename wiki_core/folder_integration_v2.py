"""Narrow v2 preflight; produces a review candidate and performs no merge."""
from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath

import yaml

from wiki_core.context_policy import PolicyError, UniqueLoader, _git, safe_path
from wiki_core.frontmatter import FRONTMATTER_RE
from wiki_core.repo_read import contains_access_secrets
from wiki_core.folder_packet_v2 import build_folder_packet_v2
from wiki_core.folder_policy_v2 import FORMAT
from wiki_core.repository_reader import RepositoryReader
from wiki_core.folder_auxiliary_v2 import qualify_auxiliary
from wiki_core.information_relations import information_requirements


class FolderIntegrationError(ValueError):
    pass


def _check_current_requirements(prior, document, path, status, packet, approved):
    """Bound a narrow declaration subset to current, explicitly reported inputs.

    This does not establish that a report was executed or that a source is
    factually fresh, and does not migrate any v1 receipt or historical query.
    """
    absent = object()
    old = prior['frontmatter'].get('information_requirements', absent) if prior else absent
    new = document['frontmatter'].get('information_requirements', absent)
    if old is absent and new is absent:
        return 0
    # The standard Markdown reader uses a permissive YAML loader. Ambiguous
    # duplicate keys cannot establish that provenance was preserved.
    for item in (prior, document):
        if item is None:
            continue
        match = FRONTMATTER_RE.match(item['text'])
        if match is None:
            raise FolderIntegrationError('v2 requirement migration and revalidation unavailable')
        try:
            strict = yaml.load(match.group(1), Loader=UniqueLoader)
        except (ValueError, TypeError, yaml.YAMLError, RecursionError):
            raise FolderIntegrationError('v2 requirement migration and revalidation unavailable') from None
        if not isinstance(strict, dict):
            raise FolderIntegrationError('v2 requirement migration and revalidation unavailable')
    if status == 'M':
        # Python equality conflates e.g. 30 and 30.0 (or True and 1). The
        # existing declaration must retain its value *and JSON type*, not
        # merely compare equal after YAML parsing.
        if old is absent or new is absent:
            raise FolderIntegrationError('v2 requirement migration and revalidation unavailable')
        try:
            old_json = json.dumps(old, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
            new_json = json.dumps(new, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
        except (TypeError, ValueError, OverflowError, RecursionError):
            raise FolderIntegrationError('v2 requirement migration and revalidation unavailable') from None
        if old_json != new_json:
            raise FolderIntegrationError('v2 requirement migration and revalidation unavailable')
    if status not in ('A', 'M') or (status == 'M' and not prior):
        raise FolderIntegrationError('v2 requirement migration and revalidation unavailable')
    if not isinstance(new, list):
        raise FolderIntegrationError('v2 requirement migration and revalidation unavailable')
    if not new:
        return 0
    try:
        requirements = information_requirements(document['frontmatter'],
                    lambda ref: [ref] if isinstance(ref, str) and ref in approved.paths else [])
    except (ValueError, TypeError):
        raise FolderIntegrationError('v2 requirement migration and revalidation unavailable') from None
    evidence = [row for row in packet['inputs'] if row['kind'] == 'evidence']
    seen = set()
    for req in requirements:
        if (req['temporal'] != 'current' or req['target'] == path
                or any(name in req for name in ('query', 'members_digest', 'selected_digest',
                                                'query_policy_revision', 'authority_digest', 'source_kind'))
                or (status == 'A' and 'consumed_revision' not in req)
                or ('consumed_revision' in req and req['consumed_revision'] != approved.revision)):
            raise FolderIntegrationError('v2 requirement migration and revalidation unavailable')
        for selector in req['fields']:
            if selector == '*':
                section, field = None, None
            elif selector.startswith('field:'):
                section, field = None, selector.removeprefix('field:')
            elif selector.startswith('section:'):
                section, field = selector.removeprefix('section:'), None
            else:
                raise FolderIntegrationError('v2 requirement migration and revalidation unavailable')
            key = (req['target'], section, field)
            if key in seen:
                raise FolderIntegrationError('v2 requirement migration and revalidation unavailable')
            seen.add(key)
            matches = [row for row in evidence if row['path'] == req['target']
                       and row.get('section') == section and row.get('field') == field
                       and row['revision'] == approved.revision
                       and row['use'] == req.get('use', 'interpret')
                       and row['classification'] == req.get('classification', 'internal')]
            if len(matches) != 1:
                raise FolderIntegrationError('v2 requirement migration and revalidation unavailable')
    return len(seen)


def _rebuild(root, policy, packet):
    if not isinstance(packet, dict) or packet.get('schema_version') != 'wiki.folder-task-context/v2':
        raise FolderIntegrationError('v2 packet required; v1 packets need explicit migration')
    if not isinstance(packet.get('inputs'), list):
        raise FolderIntegrationError('invalid v2 packet')
    by_id = {v: k for k, v in policy.folder_ids.items()}
    evidence = []
    try:
        for row in packet['inputs']:
            if row['kind'] != 'evidence':
                continue
            item = {'path': row['path'], 'producer_folder': by_id[row['producer_context']],
                    'reason': row['reason'], 'use': row['use'], 'classification': row['classification']}
            for field in ('section', 'field'):
                if row.get(field) is not None:
                    item[field] = row[field]
            evidence.append(item)
        rebuilt = build_folder_packet_v2(root, policy, packet['context_folder'], packet['max_bytes'],
                    content_revision=packet['content_revision'],
                    index_path=packet['index_path'], index_section=packet['index_section'],
                    start_folder=packet.get('start_folder'),
                    task_id=packet['task_id'], goal=packet['goal'], output=packet['output'],
                    integrator=packet['integrator'], evidence=evidence)
    except (ValueError, KeyError, TypeError) as exc:
        raise FolderIntegrationError('v2 packet cannot be reproduced') from exc
    if rebuilt != packet:
        raise FolderIntegrationError('v2 packet cannot be reproduced')
    return rebuilt


def preflight_folder_v2(root, policy, *, base, head, branch, packet, result):
    """Check exact v2 reads and branch; independent review remains required."""
    if getattr(policy, 'format_version', None) != FORMAT or not policy._binding or Path(policy._binding[0]) != Path(root).resolve():
        raise FolderIntegrationError('bound v2 policy required')
    policy = policy.fresh()
    if not isinstance(branch, str) or not re.fullmatch(r'wiki/[A-Za-z0-9][A-Za-z0-9._-]*', branch) or '..' in branch or branch.endswith('.'):
        raise FolderIntegrationError('invalid proposal branch')
    approved = RepositoryReader(root, base)
    proposed = RepositoryReader(root, head)
    if approved.revision != policy.policy_revision:
        raise FolderIntegrationError('approved base moved')
    try:
        branch_sha = _git(root, 'rev-parse', '--verify', 'refs/heads/' + branch + '^{commit}').decode().strip()
        if branch_sha != proposed.revision:
            raise FolderIntegrationError('proposal branch moved')
        _git(root, 'merge-base', '--is-ancestor', approved.revision, proposed.revision)
    except PolicyError as exc:
        raise FolderIntegrationError('proposal Git precondition failed') from exc
    packet = _rebuild(root, policy, packet)
    if packet.get('start_folder') is not None:
        try:
            policy = qualify_auxiliary(policy, approved, packet['context_folder'],
                                       packet['start_folder'], max_bytes=packet['max_bytes'])
        except (PolicyError, ValueError, KeyError) as exc:
            raise FolderIntegrationError('auxiliary authority unavailable') from exc
    required = {'schema_version', 'status', 'task_id', 'context_id', 'packet_digest', 'observed', 'changes'}
    if not isinstance(result, dict) or set(result) != required or result.get('schema_version') != 'wiki.folder-task-result/v2':
        raise FolderIntegrationError('v2 result required; v1 results need explicit migration')
    if contains_access_secrets(result):
        raise FolderIntegrationError('secret detected in result')
    if result['status'] != 'completed' or any(result[k] != packet[k] for k in ('task_id', 'context_id', 'packet_digest')):
        raise FolderIntegrationError('result does not match v2 packet')
    expected = [{'path': row['path'], 'kind': row['kind'], 'revision': row['revision'], 'sha256': row['sha256'],
                 'section': row.get('section'), 'field': row.get('field')} for row in packet['inputs']]
    if result['observed'] != expected:
        raise FolderIntegrationError('all selected inputs require an exact reported read')
    raw = _git(root, 'diff', '--no-ext-diff', '--no-textconv', '--no-renames', '--name-status', '-z', approved.revision, proposed.revision).split(b'\0')
    if raw and raw[-1] == b'': raw.pop()
    if len(raw) % 2:
        raise FolderIntegrationError('unsupported diff')
    changes = []
    statuses = {}
    for i in range(0, len(raw), 2):
        try:
            status = raw[i].decode('utf-8'); path = safe_path(raw[i+1].decode('utf-8'))
            name = PurePosixPath(path).name
            if status not in ('A', 'M', 'D'):
                raise FolderIntegrationError('unsupported diff')
            normative_paths = {ref for c in policy.contexts.values() for key in ('instructions', 'skills', 'templates') for ref in c[key]}
            normative_paths.update(row['path'] for row in packet['inputs'] if row['kind'] == 'mandatory')
            parts = PurePosixPath(path).parts
            if (name in ('AGENTS.md', 'AGENTS.override.md', 'CLAUDE.md', 'CLAUDE.local.md', 'SKILL.md', 'index.md', 'context.yaml')
                    or path in (policy.controls_path, 'README.md') or path in normative_paths
                    or any(part in ('.skills', 'skills', '.claude', '.codex') for part in parts)):
                raise FolderIntegrationError('context boundary or instructions require separate review')
            if policy.owner_of(path) != packet['context_id'] or not policy.permits(packet['context_id'], 'read', path) or not policy.permits(packet['context_id'], 'write', path):
                raise FolderIntegrationError('proposal outside v2 context')
        except (PolicyError, UnicodeError) as exc:
            raise FolderIntegrationError('proposal context unavailable') from exc
        statuses[path] = status
        changes.append({'path': path, 'action': {'A': 'created', 'M': 'modified', 'D': 'deleted'}[status]})
    reported = result['changes']
    if (not isinstance(reported, list)
            or any(not isinstance(row, dict) or set(row) != {'path', 'action'}
                   or not isinstance(row['path'], str) or row['action'] not in ('created', 'modified', 'deleted') for row in reported)):
        raise FolderIntegrationError('invalid reported changes')
    if not changes or sorted(changes, key=lambda x: x['path']) != sorted(reported, key=lambda x: x['path']):
        raise FolderIntegrationError('reported changes differ from proposal')
    # Establish authority and boundary changes from Git metadata before any
    # proposal body is read. Existing output needs an exact prior full read.
    covered_requirements = 0
    for path, status in statuses.items():
        if status in ('M', 'D'):
            prior_reads = [row for row in packet['inputs'] if row['kind'] == 'evidence' and row['path'] == path
                           and row.get('section') is None and row.get('field') is None
                           and row['revision'] == approved.revision]
            if not prior_reads or path not in approved.paths:
                raise FolderIntegrationError('existing output needs a reported whole prior read')
            prior = approved.read(path)
            if any(row['sha256'] != prior['content_sha256'] for row in prior_reads):
                raise FolderIntegrationError('existing output prior read differs')
    for row in packet['inputs']:
        is_prior_output = (statuses.get(row['path']) in ('M', 'D') and row['kind'] == 'evidence'
                           and row.get('section') is None and row.get('field') is None
                           and row['revision'] == approved.revision)
        if is_prior_output:
            continue
        try:
            item = proposed.read(row['path'], section=row.get('section'), field=row.get('field'))
        except ValueError as exc:
            raise FolderIntegrationError('selected input missing in proposal') from exc
        if item['content_digest'] != row['sha256']:
            raise FolderIntegrationError('selected input changed in proposal')
    for path, status in statuses.items():
        prior = approved.read(path) if path in approved.paths else None
        if status != 'D':
            document = proposed.read(path)
            if contains_access_secrets(document['text']):
                raise FolderIntegrationError('secret detected in proposed content')
            covered_requirements += _check_current_requirements(prior, document, path, status, packet, approved)
            if (PurePosixPath(path).suffix != '.md' or document['frontmatter'].get('page_type') != 'claim'
                    or (prior and prior['frontmatter'].get('page_type') != 'claim')):
                raise FolderIntegrationError('ambiguous or normative change requires separate review')
        elif prior and 'information_requirements' in prior['frontmatter']:
            raise FolderIntegrationError('v2 requirement migration and revalidation unavailable')
        elif not prior or PurePosixPath(path).suffix != '.md' or prior['frontmatter'].get('page_type') != 'claim':
            raise FolderIntegrationError('ambiguous or normative change requires separate review')
    policy.fresh()
    if _git(root, 'rev-parse', '--verify', 'refs/heads/' + branch + '^{commit}').decode().strip() != proposed.revision:
        raise FolderIntegrationError('proposal branch moved')
    out = {'schema_version': 'wiki.folder-preflight/v2', 'state': 'independent_review_required',
            'policy_revision': policy.policy_revision, 'base': approved.revision, 'head': proposed.revision,
            'branch': branch, 'context_id': packet['context_id'], 'packet_digest': packet['packet_digest'],
            'changes': changes, 'review': 'not_performed', 'gates': 'not_performed', 'merge': 'not_performed',
            'read_coverage': 'reported_not_independently_verified', 'enforcement_claim': 'none'}
    if covered_requirements:
        out['requirements_handling'] = {'coverage': 'explicit_current_reported_selections_only',
              'count': covered_requirements, 'freshness': 'not_assessed',
              'legacy_receipt_migration': 'not_performed'}
    return out
