"""Narrow v2 preflight; produces a review candidate and performs no merge."""
from __future__ import annotations

import hashlib
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


def _declares_capture_source(document, ref, revision):
    requirements = document['frontmatter'].get('information_requirements')
    return isinstance(requirements, list) and any(
        isinstance(req, dict) and req.get('target') == ref and req.get('fields') == ['*']
        and req.get('temporal') == 'current' and req.get('consumed_revision') == revision
        and req.get('use', 'interpret') == 'interpretation' and req.get('classification', 'internal') == 'source'
        for req in requirements)


def _check_current_requirements(prior, document, path, status, packet, approved, *,
                                ingestion_source=None, query_rows=(), require_queries=False,
                                policy=None, query_requalifications=None, requalify_source=False):
    """Bound a narrow declaration subset to current, explicitly reported inputs.

    This does not establish that a report was executed or that a source is
    factually fresh, and does not migrate any v1 receipt or historical query.
    """
    absent = object()
    old = prior['frontmatter'].get('information_requirements', absent) if prior else absent
    new = document['frontmatter'].get('information_requirements', absent)
    if old is absent and new is absent and not require_queries:
        return 0
    # Require strict parsing of both exact versions before comparing declarations.
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
    if status not in ('A', 'M') or (status == 'M' and not prior) or not isinstance(new, list):
        raise FolderIntegrationError('v2 requirement migration and revalidation unavailable')
    if query_requalifications is not None and status != 'M':
        raise FolderIntegrationError('query requalification requires an existing output')
    validate = new
    if status == 'M':
        # Preserve existing declarations, except an explicitly requalified
        # source; reported queries may be appended.
        if old is absent:
            if ingestion_source is None and not query_rows:
                raise FolderIntegrationError('v2 requirement migration and revalidation unavailable')
            old = []
        if not isinstance(old, list):
            raise FolderIntegrationError('v2 requirement migration and revalidation unavailable')
        from wiki_core.folder_query_requirements_v2 import same_json
        replacements = {}
        if query_requalifications is not None:
            if ingestion_source is not None or requalify_source or not query_rows or policy is None:
                raise FolderIntegrationError('query requalification unavailable')
            try:
                from wiki_core.folder_query_requalification_v2 import prepare_query_replacements
                replacements = prepare_query_replacements(approved.root, policy, folder=packet['context_folder'],
                    target=path, prior_requirements=old, query_rows=query_rows, reports=query_requalifications)
            except (ValueError, OSError, TypeError, KeyError, AttributeError, RecursionError):
                raise FolderIntegrationError('query requalification unavailable') from None
        if requalify_source:
            indices = [i for i, row in enumerate(old) if isinstance(row, dict) and row.get('target') == ingestion_source]
            if len(indices) != 1 or len(new) != len(old) + len(query_rows):
                raise FolderIntegrationError('ingestion source requalification unavailable')
            index = indices[0]
            changed = new[index] if isinstance(new[index], dict) else {}
            previous_revision = old[index].get('consumed_revision')
            if (not isinstance(previous_revision, str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', previous_revision)
                    or not same_json({**old[index], 'consumed_revision':approved.revision}, changed)
                    or not same_json(old[:index], new[:index])
                    or not same_json(old[index+1:], new[index+1:len(old)])):
                raise FolderIntegrationError('ingestion source requalification unavailable')
            validate = [changed, *new[len(old):]]
        else:
            try:
                def canonical(value):
                    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
                replaced = [replacements.get(item.get('query_id'), item) if isinstance(item, dict) else item for item in old]
                if canonical(replaced) != canonical(new[:len(old)]):
                    raise ValueError('old requirements changed')
            except (TypeError, ValueError, OverflowError, RecursionError):
                raise FolderIntegrationError('v2 requirement migration and revalidation unavailable') from None
            validate = [replacements[item['query_id']] for item in old
                        if isinstance(item, dict) and item.get('query_id') in replacements] + new[len(old):]
            if ingestion_source is None:
                if query_rows:
                    if len(validate) != len(query_rows):
                        raise FolderIntegrationError('folder query requirements unavailable')
                elif validate:
                    raise FolderIntegrationError('v2 requirement migration and revalidation unavailable')
                else:
                    validate = new  # preserve existing behavior for non-ingestion tasks
            elif (len(validate) != 1 + len(query_rows) or not isinstance(validate[0], dict)
                  or validate[0].get('target') != ingestion_source
                  or any(not isinstance(item, dict) or item.get('target') == ingestion_source for item in old)):
                raise FolderIntegrationError('ingestion source addition unavailable')
        old_query_ids = {item.get('query_id') for item in old if isinstance(item, dict)
                         and item.get('query_id') and item.get('query_id') not in replacements}
        new_query_ids = {item.get('query_id') for item in new[len(old):] if isinstance(item, dict) and item.get('query_id')}
        if old_query_ids & new_query_ids:
            raise FolderIntegrationError('duplicate folder query requirement')
    if not validate and require_queries:
        raise FolderIntegrationError('folder query requirements unavailable')
    if not validate:
        return 0
    try:
        tracked = set(approved.paths)
        requirements = information_requirements({'information_requirements': validate},
                    lambda ref: [ref] if isinstance(ref, str) and ref in tracked else [])
    except (ValueError, TypeError):
        raise FolderIntegrationError('v2 requirement migration and revalidation unavailable') from None
    evidence = [row for row in packet['inputs'] if row['kind'] == 'evidence']
    seen = set()
    seen_queries = set()
    for req in requirements:
        if req.get('query_contract') == 'wiki.folder-query-receipt/v2':
            from wiki_core.folder_query_requirements_v2 import query_requirements, same_json
            candidates = query_requirements(query_rows, req['max_age_days'])
            if not any(same_json(req, item) for item in candidates) or req['query_id'] in seen_queries:
                raise FolderIntegrationError('folder query requirement differs from report')
            seen_queries.add(req['query_id'])
            continue
        if (req['temporal'] != 'current' or req['target'] == path
                or any(name in req for name in ('query', 'members_digest', 'selected_digest',
                                                'query_policy_revision', 'authority_digest', 'source_kind'))
                or ((status == 'A' or ingestion_source is not None) and 'consumed_revision' not in req)
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
    if (require_queries or seen_queries) and seen_queries != {row['receipt']['query_id'] for row in query_rows}:
        raise FolderIntegrationError('folder query requirements unavailable')
    return len(seen) + len(seen_queries)


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
                    integrator=packet['integrator'], evidence=evidence,
                    ingestion_binding=packet.get('ingestion_binding'))
    except (ValueError, KeyError, TypeError) as exc:
        raise FolderIntegrationError('v2 packet cannot be reproduced') from exc
    if rebuilt != packet:
        raise FolderIntegrationError('v2 packet cannot be reproduced')
    return rebuilt


def preflight_folder_v2(root, policy, *, base, head, branch, packet, result,
                        binding=None, source_request=None, query_packet=None, query_result=None,
                        requalify_source=False, query_requalifications=None):
    """Check exact v2 reads and branch; independent review remains required."""
    if requalify_source and query_requalifications is not None:
        raise FolderIntegrationError('source and query requalification require separate proposals')
    if type(requalify_source) is not bool or (requalify_source and (binding is None or not isinstance(source_request, dict))):
        raise FolderIntegrationError('explicit host-bound requalification required')
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
    query_rows = ()
    if query_packet is not None or query_result is not None:
        try:
            from wiki_core.folder_query_requirements_v2 import validate_query_report, same_json
            query_rows = validate_query_report(root, policy, query_packet, query_result, base_packet=packet)
            if not same_json(query_result['changes'], result['changes']):
                raise ValueError('query result changes differ from base result')
        except (ValueError, OSError, TypeError, KeyError, AttributeError, RecursionError):
            raise FolderIntegrationError('query report unavailable') from None
    ingestion = packet.get('ingestion_binding')
    if query_requalifications is not None and (not query_rows or ingestion is not None):
        raise FolderIntegrationError('query requalification unavailable')
    if ingestion is not None:
        if binding is None or not isinstance(source_request, dict):
            raise FolderIntegrationError('ingestion task requires host-bound request')
        from wiki_core.folder_query_requirements_v2 import same_json
        if not same_json(source_request.get('folder_query_packet'), query_packet):
            raise FolderIntegrationError('query context differs from recorded request')
        if query_packet is not None:
            from wiki_core.llm.context_pass import _CONTEXT_FIELDS
            if 'folder_query_packet' not in _CONTEXT_FIELDS:
                raise FolderIntegrationError('query fingerprint binding unavailable')
        try:
            from wiki_core.folder_capture_v2 import validate_recorded_request
            validate_recorded_request(root, packet, source_request)
        except (ValueError, OSError, TypeError, KeyError, AttributeError, RecursionError):
            raise FolderIntegrationError('ingestion request unavailable') from None
    elif source_request is not None:
        raise FolderIntegrationError('ingestion task binding required')
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
    if not any(row['path'] == packet['output'] for row in changes):
        raise FolderIntegrationError('declared output change unavailable')
    if query_requalifications is not None and statuses[packet['output']] != 'M':
        raise FolderIntegrationError('query requalification requires an existing output')
    if ingestion is not None and statuses[packet['output']] == 'D':
        raise FolderIntegrationError('ingestion output must exist')
    if query_rows:
        from wiki_core.context_policy import within
        if ingestion is not None and statuses[packet['output']] == 'D':
            raise FolderIntegrationError('query output must exist')
        for row in query_rows:
            scope = row['receipt']['request']['query']['scope']
            anchor = row['receipt']['index_path']
            if any(path == anchor or within(path, scope) for path in statuses):
                raise FolderIntegrationError('proposal changes query scope')
    # Establish authority and boundary changes from Git metadata before any
    # proposal body is read. Existing output needs an exact prior full read.
    covered_requirements = 0
    modified_ingestion_bodies = []
    capture_inspected = False
    repo_inspected = False
    capture_preserved = False
    repo_preserved = False
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
        if path == packet['output'] and requalify_source and (status != 'M' or ingestion is None):
            raise FolderIntegrationError('requalification requires an existing ingestion-bound claim')
        if status != 'D':
            document = proposed.read(path)
            if contains_access_secrets(document['text']):
                raise FolderIntegrationError('secret detected in proposed content')
            ingestion_source = None
            if status == 'M' and (path != packet['output'] or ingestion is None):
                from wiki_core.folder_query_requirements_v2 import same_json
                from wiki_core.folder_source_provenance_v2 import SINGLETON, FIELD
                projection = (*SINGLETON, FIELD, 'source_refs')
                old_projection = {key:prior['frontmatter'][key] for key in projection if key in prior['frontmatter']}
                new_projection = {key:document['frontmatter'][key] for key in projection if key in document['frontmatter']}
                if not same_json(old_projection, new_projection):
                    raise FolderIntegrationError('prior ingestion projections changed')
            preserve_prior_projections = status == 'M' and path == packet['output'] and bool(query_rows) and ingestion is None
            if preserve_prior_projections:
                from wiki_core.folder_query_requirements_v2 import same_json
                projection = ('source_authorization', 'independent_repo_read',
                              'independent_repo_additional_reads', 'independent_repo_source_ref',
                              'folder_source_provenance')
                old_projection = {key:prior['frontmatter'][key] for key in projection if key in prior['frontmatter']}
                new_projection = {key:document['frontmatter'][key] for key in projection if key in document['frontmatter']}
                if not same_json(old_projection, new_projection):
                    raise FolderIntegrationError('prior ingestion projections changed')
            if status == 'M' and path == packet['output'] and ingestion is not None:
                try:
                    auth = source_request['source_authorization']
                    ingestion_source = safe_path(auth['canonical_ref'])
                    previous_hash = auth['existing_output_sha256']
                    if previous_hash != prior['content_sha256']:
                        raise ValueError('selected prior output differs')
                    source_doc = approved.read(ingestion_source)
                    source_id = source_doc['frontmatter']['page_id']
                    if (source_doc['frontmatter'].get('page_type') != 'source'
                            or not isinstance(source_id, str) or not source_id.startswith('source-')):
                        raise ValueError('source identity unavailable')
                    prior_frontmatter = FRONTMATTER_RE.match(prior['text'])
                    proposed_frontmatter = FRONTMATTER_RE.match(document['text'])
                    if prior_frontmatter is None or proposed_frontmatter is None:
                        raise ValueError('existing body unavailable')
                    before_body = prior['text'][prior_frontmatter.end():]
                    after_body = document['text'][proposed_frontmatter.end():]
                    modified_ingestion_bodies.append({'path':path,
                        'before_sha256':hashlib.sha256(before_body.encode('utf-8')).hexdigest(),
                        'after_sha256':hashlib.sha256(after_body.encode('utf-8')).hexdigest(),
                        'semantic_review':'independent_review_required'})
                    old_meta, new_meta = prior['frontmatter'], document['frontmatter']
                    from wiki_core.folder_source_provenance_v2 import add_projection, requalify_projection, SINGLETON, FIELD
                    projection = set(SINGLETON) | {FIELD}
                    expected_projection = requalify_projection(old_meta, auth) if requalify_source else add_projection(old_meta, auth)
                    actual_projection = {key:new_meta[key] for key in projection if key in new_meta}
                    from wiki_core.folder_query_requirements_v2 import same_json
                    if not same_json(actual_projection, expected_projection):
                        raise ValueError('existing provenance changed or current source differs')
                    old_refs = old_meta.get('source_refs', [])
                    if not isinstance(old_refs, list) or any(not isinstance(ref, str) for ref in old_refs):
                        raise ValueError('source references unavailable')
                    old_requirements = old_meta.get('information_requirements', [])
                    if (not isinstance(old_requirements, list) or any(not isinstance(row, dict)
                            or (not requalify_source and row.get('target') in (ingestion_source, source_id)) for row in old_requirements)):
                        raise ValueError('prior source requirement needs separate revalidation')
                    if requalify_source and source_id not in old_refs:
                        raise ValueError('selected source reference unavailable')
                    wanted_refs = old_refs if source_id in old_refs else [*old_refs, source_id]
                    if new_meta.get('source_refs') != wanted_refs:
                        raise ValueError('source references changed')
                    excluded = projection | {'source_refs', 'information_requirements'}
                    def canonical_meta(meta):
                        return json.dumps({k:v for k,v in meta.items() if k not in excluded},
                                          ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
                    if canonical_meta(old_meta) != canonical_meta(new_meta):
                        raise ValueError('existing metadata changed')
                except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
                    raise FolderIntegrationError('existing ingestion provenance unavailable') from None
            covered_requirements += _check_current_requirements(prior, document, path, status, packet, approved,
                 ingestion_source=ingestion_source, query_rows=query_rows if path == packet['output'] else (),
                 require_queries=bool(query_rows and path == packet['output']), policy=policy,
                 query_requalifications=query_requalifications if path == packet['output'] else None,
                 requalify_source=requalify_source and path == packet['output'])
            selected_meta = document['frontmatter']
            if path == packet['output'] and ingestion is not None:
                if status == 'A' and 'folder_source_provenance' in document['frontmatter']:
                    raise FolderIntegrationError('new claim cannot introduce additional source projections')
                try:
                    from wiki_core.folder_capture_v2 import validate_ingestion_projections
                    validate_ingestion_projections(source_request, document['frontmatter'])
                    from wiki_core.folder_source_provenance_v2 import selected_projection
                    selected_meta = selected_projection(document['frontmatter'], source_request['source_authorization']['canonical_ref'])
                except (ValueError, TypeError, KeyError, AttributeError):
                    raise FolderIntegrationError('ingestion projections unavailable') from None
            elif 'folder_source_provenance' in document['frontmatter']:
                if not preserve_prior_projections:
                    raise FolderIntegrationError('folder source provenance requires an ingestion-bound task')
                try:
                    from wiki_core.folder_source_provenance_v2 import validate_provenance
                    validate_provenance(document['frontmatter'])
                    entries = document['frontmatter']['folder_source_provenance']['entries']
                    capture_preserved |= any('source_authorization' in row for row in entries)
                    repo_preserved |= any('independent_repo_read' in row for row in entries)
                except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
                    raise FolderIntegrationError('prior source projections unavailable') from None
            capture = selected_meta.get('source_authorization')
            if capture is not None:
                # A RAW association needs the original explicit request and
                # recorded results under a trusted folder binding. A direct
                # preflight cannot elevate a hash copied into Markdown.
                if preserve_prior_projections:
                    capture_preserved = True
                elif path != packet['output'] or binding is None or not isinstance(source_request, dict):
                    raise FolderIntegrationError('raw capture requires host-bound revalidation')
                else:
                    try:
                        from wiki_core.folder_capture_v2 import inspect_raw_capture, validate_recorded_capture_request
                        if not _declares_capture_source(document, capture['canonical_ref'], policy.policy_revision):
                            raise ValueError('capture source requirement unavailable')
                        validate_recorded_capture_request(root, packet, source_request, capture)
                        inspection = inspect_raw_capture(root, binding, packet['context_folder'], policy.policy_revision, capture)
                        if inspection['captured_sha256'] != inspection['current_sha256']:
                            raise ValueError('capture changed')
                        capture_inspected = True
                    except (ValueError, OSError, TypeError, KeyError, AttributeError, RecursionError):
                        raise FolderIntegrationError('raw capture unavailable or changed') from None
            repo_receipt = selected_meta.get('independent_repo_read')
            additional_repos = selected_meta.get('independent_repo_additional_reads')
            if additional_repos is not None and repo_receipt is None:
                raise FolderIntegrationError('repository selection requires host-bound revalidation')
            if repo_receipt is not None:
                if preserve_prior_projections:
                    repo_preserved = True
                elif path != packet['output'] or binding is None or not isinstance(source_request, dict):
                    raise FolderIntegrationError('repository selection requires host-bound revalidation')
                else:
                    try:
                        from wiki_core.folder_capture_v2 import inspect_reported_repository
                        if not _declares_capture_source(document, source_request['source_authorization']['canonical_ref'],
                                                        policy.policy_revision):
                            raise ValueError('repository source requirement unavailable')
                        inspect_reported_repository(root, binding, packet['context_folder'], policy.policy_revision,
                                                    packet, source_request, repo_receipt, additional_repos)
                        repo_inspected = True
                    except (ValueError, OSError, TypeError, KeyError, AttributeError, RecursionError):
                        raise FolderIntegrationError('repository selection unavailable or changed') from None
            if (PurePosixPath(path).suffix != '.md' or document['frontmatter'].get('page_type') != 'claim'
                    or (prior and prior['frontmatter'].get('page_type') != 'claim')):
                raise FolderIntegrationError('ambiguous or normative change requires separate review')
        elif prior and any(key in prior['frontmatter'] for key in ('information_requirements',
                'source_authorization', 'independent_repo_read', 'independent_repo_additional_reads',
                'independent_repo_source_ref', 'folder_source_provenance', 'source_refs')):
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
    if modified_ingestion_bodies:
        out['modified_ingestion_bodies'] = modified_ingestion_bodies
    if covered_requirements:
        out['requirements_handling'] = {'coverage': 'explicit_current_reported_selections_only',
              'count': covered_requirements, 'freshness': 'not_assessed',
              'legacy_receipt_migration': 'not_performed'}
    if capture_inspected:
        out['capture_handling'] = {'local_bytes': 'matched', 'external_origin': 'not_verified',
                                   'external_freshness': 'not_verified', 'execution': 'not_proven'}
    if repo_inspected:
        out['repository_handling'] = {'selection': 'matched_request',
                                      'remote_authentication': 'not_verified', 'execution': 'not_proven'}
    if query_requalifications is not None:
        out['query_requalification'] = {'count':len(query_requalifications),
            'state':'independent_review_required', 'review':'not_performed', 'freshness':'not_assessed'}
    if capture_preserved or repo_preserved:
        out['prior_ingestion_provenance'] = {
            'capture': 'preserved_not_revalidated' if capture_preserved else 'absent',
            'repository': 'preserved_not_revalidated' if repo_preserved else 'absent'}
    return out
