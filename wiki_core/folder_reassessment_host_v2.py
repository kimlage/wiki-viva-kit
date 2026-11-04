"""Host-bound, read-only source reassessment; not an ACL or transport."""
from __future__ import annotations

import json
from pathlib import Path

from wiki_core.context_policy import _git, safe_path, within
from wiki_core.folder_coordination_v2 import (FolderCoordinationError, _bound_policy,
    _preauthorize_evidence, _sha)
from wiki_core.folder_impact_v2 import _current_packet_authority, _preauthorize_historical_replay
from wiki_core.folder_policy_v2 import _at_revision
from wiki_core.folder_reassessment_v2 import reassess_folder_source_v2
from wiki_core.repo_read import contains_access_secrets
from wiki_core.repository_reader import RepositoryReader


def prepare_folder_reassessment(root, binding, payload):
    """Join selected declarations and reports under a trusted host binding.

    This function opens only read-only candidates, does not establish host
    identity, and does not attest execution, review, migration or freshness.
    Direct reassessment APIs/CLIs remain available only to a trusted caller.
    """
    required = {'folder', 'approved_revision', 'source', 'reports'}
    optional = {'scope', 'candidates', 'max_files', 'max_bytes', 'independent_repo', 'source_request'}
    if not isinstance(payload, dict) or not required <= set(payload) or set(payload) - required - optional:
        raise FolderCoordinationError('invalid request')
    try:
        if contains_access_secrets(payload):
            raise FolderCoordinationError('invalid request')
        if len(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()) > 2_000_000:
            raise FolderCoordinationError('request exceeds byte limit')
        folder = safe_path(payload['folder'], allow_root=True)
        source = safe_path(payload['source'])
        scope = payload.get('scope'); candidates = payload.get('candidates')
        max_files = payload.get('max_files', 256); max_bytes = payload.get('max_bytes', 1_000_000)
        if ((scope is None) == (candidates is None) or type(max_files) is not int or not 1 <= max_files <= 256
                or type(max_bytes) is not int or not 1 <= max_bytes <= 1_000_000):
            raise FolderCoordinationError('invalid selection')
        if scope is not None:
            scope = safe_path(scope, allow_root=True)
            if not within(scope, folder):
                raise FolderCoordinationError('invalid selection')
        else:
            if not isinstance(candidates, list) or not candidates or len(candidates) > max_files:
                raise FolderCoordinationError('invalid selection')
            candidates = [safe_path(item) for item in candidates]
            if len(candidates) != len(set(candidates)):
                raise FolderCoordinationError('invalid selection')
        reports = payload['reports']
        if not isinstance(reports, list) or len(reports) > 64:
            raise FolderCoordinationError('invalid reports')
        independent = payload.get('independent_repo')
        report_fields = {'target', 'section', 'field', 'packet', 'result'}
        if independent is not None:
            if not isinstance(independent, dict) or set(independent) != {'root', 'identity', 'revision', 'path'}:
                raise FolderCoordinationError('independent repository unavailable or unauthorized')
            report_fields.add('repo_read')
        report_keys = set()
        historical_reports = []
        for report in reports:
            if not isinstance(report, dict) or set(report) != report_fields:
                raise FolderCoordinationError('invalid report')
            target = safe_path(report['target']); section = report['section']; field = report['field']
            if ((section is not None and (not isinstance(section, str) or not section.strip()))
                    or (field is not None and (not isinstance(field, str) or not field.strip()))
                    or (section is not None and field is not None)
                    or (scope is not None and not within(target, scope))
                    or (candidates is not None and target not in candidates)):
                raise FolderCoordinationError('invalid report selection')
            key = (target, section, field)
            if key in report_keys:
                raise FolderCoordinationError('duplicate report')
            report_keys.add(key)
        policy = _bound_policy(root, binding, folder, payload['approved_revision'])
        if independent is not None:
            try:
                repo_root = Path(independent['root'])
                if not repo_root.is_absolute():
                    raise ValueError('relative root')
                repo_key = (folder, repo_root.resolve(), independent['identity'], safe_path(independent['path']))
                if repo_key not in binding.independent_repos:
                    raise ValueError('repository not in host binding')
                # Subsequent Git operations use the host-authorized canonical
                # root, not an alias from the request that can be retargeted.
                independent = {**independent, 'root': str(repo_key[1]), 'path': repo_key[3]}
            except (OSError, RuntimeError, ValueError, TypeError):
                raise FolderCoordinationError('independent repository unavailable or unauthorized') from None
        context = policy.folder_ids[folder]
        reader = RepositoryReader(binding.root, policy.policy_revision)
        # Validate explicit candidate ownership before checking any report or
        # opening any selected consumer. Scope enumeration is filtered by the
        # underlying inventory before its first consumer read.
        if candidates is not None:
            for target in candidates:
                if (target not in reader.paths or not target.endswith('.md')
                        or policy.owner_of(target) != context or not policy.permits(context, 'read', target)):
                    raise FolderCoordinationError('candidate authority unavailable')
        elif scope != '.' and policy.owner_of(scope) != context:
            raise FolderCoordinationError('scope authority unavailable')
        producer = policy.owner_of(source)
        if not policy.permits(producer, 'read', source) or not policy.permits(context, 'read', source):
            raise FolderCoordinationError('source authority unavailable')
        if producer != context and not reports:
            raise FolderCoordinationError('cross-owner source requires explicit evidence')
        by_id = {value:key for key,value in policy.folder_ids.items()}
        for report in reports:
            target = report['target']; packet = report['packet']; result = report['result']
            if policy.owner_of(target) != context or not policy.permits(context, 'read', target):
                raise FolderCoordinationError('consumer authority unavailable')
            if (not isinstance(packet, dict) or packet.get('schema_version') != 'wiki.folder-task-context/v2'
                    or packet.get('context_folder') != folder or packet.get('context_id') != context
                    or packet.get('output') != target or packet.get('start_folder') is not None
                    or not isinstance(packet.get('inputs'), list)
                    or not isinstance(result, dict) or result.get('schema_version') != 'wiki.folder-task-result/v2'):
                raise FolderCoordinationError('report binding unavailable')
            old = _sha(packet['policy_revision']); content = _sha(packet['content_revision'])
            _git(binding.root, 'merge-base', '--is-ancestor', content, old)
            _git(binding.root, 'merge-base', '--is-ancestor', old, policy.policy_revision)
            evidence = []; matches = 0
            for row in packet['inputs']:
                if not isinstance(row, dict):
                    raise FolderCoordinationError('invalid report input')
                if row.get('kind') != 'evidence':
                    continue
                spec = {key:row[key] for key in ('path','reason','use','classification')}
                spec['producer_folder'] = by_id[row['producer_context']]
                for key in ('section','field'):
                    if row.get(key) is not None: spec[key] = row[key]
                evidence.append(spec)
                if (row.get('path') == source and row.get('section') == report['section']
                        and row.get('field') == report['field']):
                    matches += 1
            if matches != 1:
                raise FolderCoordinationError('report source selection unavailable')
            _preauthorize_evidence(binding.root, policy, folder, content, evidence)
            historical = _at_revision(Path(binding.root), old, policy.controls_path)
            if historical.folder_ids.get(folder) != context:
                raise FolderCoordinationError('historical context unavailable')
            for spec in evidence:
                old_producer = historical.folder_ids.get(spec['producer_folder'])
                if (old_producer is None or historical.connection(old_producer, context, spec['path'],
                        spec['use'], spec['classification'], section=spec.get('section'),
                        field=spec.get('field')) != 'approved'):
                    raise FolderCoordinationError('historical evidence authority unavailable')
            historical_reports.append((packet, historical))
        # Do not reveal whether an unauthorized source is a regular Git blob or
        # an unsupported object. Source and all report connections are checked
        # first; only then may the selected source's metadata be classified.
        if reader.invalid_paths or any(source == path or source.startswith(path + '/')
                                       for path in reader.unsupported_paths):
            raise FolderCoordinationError('source metadata unavailable')
        # Only after every report's evidence is authorized may we open current
        # instruction chains, and their historic Git objects are checked before
        # the selected consumer inventory and historical replay.
        for packet, historical in historical_reports:
            _current_packet_authority(policy, packet, folder, context)
            _preauthorize_historical_replay(binding.root, policy, packet, folder, context, historical)
        policy.fresh()
        # Contextual captures must keep their request/cache binding before any
        # independent Git source is opened by the downstream reassessment.
        source_request = payload.get('source_request')
        source_auth = source_request.get('source_authorization') if isinstance(source_request, dict) else None
        from wiki_core.context_policy import UniqueLoader
        from wiki_core.frontmatter import FRONTMATTER_RE
        import yaml
        for selected_report in reports:
            selected_document = reader.read(selected_report['target'])
            frontmatter_match = FRONTMATTER_RE.match(selected_document['text'])
            try:
                selected_meta = yaml.load(frontmatter_match.group(1), Loader=UniqueLoader) if frontmatter_match else {}
            except yaml.YAMLError:
                raise FolderCoordinationError('source request unavailable') from None
            if not isinstance(selected_meta, dict):
                raise FolderCoordinationError('source request unavailable')
            has_capture = (selected_meta.get('source_authorization') is not None
                           or selected_meta.get('independent_repo_read') is not None)
            ingestion = selected_report['packet'].get('ingestion_binding')
            if (has_capture or ingestion is not None) and (not isinstance(source_auth, dict)
                    or source_request.get('block_context_package') != selected_report['packet']):
                raise FolderCoordinationError('source request unavailable')
            if ingestion is not None:
                from wiki_core.folder_capture_v2 import validate_recorded_request, validate_ingestion_projections
                validate_recorded_request(binding.root, selected_report['packet'], source_request)
                validate_ingestion_projections(source_request, selected_meta)
            elif has_capture:
                raise FolderCoordinationError('ingestion task binding required')
            if selected_meta.get('independent_repo_read') is not None:
                from wiki_core.folder_capture_v2 import inspect_reported_repository, repository_receipt_projection
                receipt = source_auth.get('independent_repo_read')
                projection = selected_meta['independent_repo_read']
                if (not isinstance(receipt, dict) or projection != repository_receipt_projection(receipt)
                        or selected_report.get('repo_read') != {**receipt, 'text':source_request.get('independent_repo_content')}):
                    raise FolderCoordinationError('repository request unavailable')
                inspect_reported_repository(binding.root, binding, folder, policy.policy_revision,
                                            selected_report['packet'], source_request, projection,
                                            selected_meta.get('independent_repo_additional_reads'))
        outcome = reassess_folder_source_v2(binding.root, policy, folder=folder, source=source,
                    reports=reports, scope=scope, candidates=candidates, max_files=max_files, max_bytes=max_bytes,
                    independent_repo=independent)
        validated_raw = set()
        validated_repo = set()
        source_auth = source_request.get('source_authorization') if isinstance(source_request, dict) else None
        if source_request is not None and not isinstance(source_auth, dict):
            raise FolderCoordinationError('source request unavailable')
        if isinstance(source_auth, dict) and source_auth.get('source_kind') == 'staged_raw':
            from wiki_core.folder_capture_v2 import inspect_raw_capture, validate_recorded_capture_request
            from wiki_core.context_policy import UniqueLoader
            from wiki_core.frontmatter import FRONTMATTER_RE
            import yaml
            if not isinstance(source_request, dict):
                raise FolderCoordinationError('raw capture request unavailable')
            packet = source_request.get('block_context_package')
            if not isinstance(packet, dict) or packet.get('context_folder') != folder:
                raise FolderCoordinationError('raw capture request unavailable')
            target = safe_path(packet['output'])
            matches = [report for report in reports if report['target'] == target and report['packet'] == packet]
            entries = [row for row in outcome['consumers'] if row['target'] == target and row['source'] == source]
            if len(matches) != 1 or len(entries) != 1:
                raise FolderCoordinationError('raw capture report unavailable')
            doc = reader.read(target)
            match = FRONTMATTER_RE.match(doc['text'])
            if match is None:
                raise FolderCoordinationError('raw capture unavailable')
            try:
                meta = yaml.load(match.group(1), Loader=UniqueLoader)
            except yaml.YAMLError:
                raise FolderCoordinationError('raw capture unavailable') from None
            capture = meta.get('source_authorization') if isinstance(meta, dict) else None
            if not isinstance(capture, dict) or capture.get('canonical_ref') != source:
                raise FolderCoordinationError('raw capture unavailable')
            validate_recorded_capture_request(binding.root, packet, source_request, capture)
            validated_raw.add(target)
            try:
                inspection = inspect_raw_capture(binding.root, binding, folder, policy.policy_revision, capture)
            except ValueError:
                entries[0]['state'] = 'blocked_raw_capture_unavailable'
            else:
                entries[0]['raw_capture_impact'] = {'captured_sha256':inspection['captured_sha256'],
                    'current_sha256':inspection['current_sha256'],
                    'local_state':'unchanged' if inspection['captured_sha256'] == inspection['current_sha256'] else 'changed',
                    'association':'caller_selected_unverified', 'external_freshness':'not_verified'}
                if inspection['captured_sha256'] != inspection['current_sha256'] and entries[0]['state'] == 'verification_pending':
                    entries[0]['state'] = 'review_pending'
        if isinstance(source_auth, dict) and source_auth.get('independent_repo_read') is not None:
            from wiki_core.folder_capture_v2 import inspect_reported_repository, repository_receipt_projection
            packet = source_request.get('block_context_package')
            if not isinstance(packet, dict) or packet.get('context_folder') != folder:
                raise FolderCoordinationError('repository request unavailable')
            target = safe_path(packet['output'])
            matched = [report for report in reports if report['target'] == target and report['packet'] == packet]
            entries = [row for row in outcome['consumers'] if row['target'] == target and row['source'] == source]
            if len(matched) != 1 or len(entries) != 1 or source_auth.get('canonical_ref') != source:
                raise FolderCoordinationError('repository request unavailable')
            doc = reader.read(target)
            projection = doc['frontmatter'].get('independent_repo_read')
            if (projection != repository_receipt_projection(source_auth['independent_repo_read'])
                    or matched[0].get('repo_read') != {**source_auth['independent_repo_read'],
                                                       'text':source_request.get('independent_repo_content')}):
                raise FolderCoordinationError('repository request unavailable')
            inspect_reported_repository(binding.root, binding, folder, policy.policy_revision,
                                        packet, source_request, projection,
                                        doc['frontmatter'].get('independent_repo_additional_reads'))
            from wiki_core.folder_ingestion_v2 import additional_repo_selections_for_request
            from wiki_core.repo_read import read_independent_repo, _git as repo_git
            additional = additional_repo_selections_for_request(binding, folder, source_auth)
            receipts = source_auth.get('independent_repo_additional_reads', [])
            changes = []
            for selected, receipt in zip(additional, receipts):
                repo_root, identity, _revision, path = selected
                if not independent or independent['identity'] != identity or Path(independent['root']).resolve() != Path(repo_root).resolve():
                    raise FolderCoordinationError('repository request unavailable')
                try:
                    repo_git(Path(repo_root), 'merge-base', '--is-ancestor', receipt['revision'], independent['revision'])
                    latest = read_independent_repo(Path(repo_root), identity, independent['revision'], path,
                                                   section=receipt.get('section'), field=receipt.get('field'))
                except ValueError:
                    entries[0]['state'] = 'blocked_repository_selection_unavailable'
                    break
                changed = latest['content_sha256'] != receipt['content_sha256']
                changes.append({'path':path, 'consumed_revision':receipt['revision'],
                                'selected_revision':latest['revision'], 'source_state':'changed' if changed else 'unchanged'})
            if changes:
                entries[0]['additional_repository_impact'] = changes
                if any(row['source_state'] == 'changed' for row in changes) and entries[0]['state'] == 'verification_pending':
                    entries[0]['state'] = 'review_pending'
            validated_repo.add(target)
        # A persisted capture is never marked verified or reviewed if its
        # corresponding contextual request was not explicitly supplied.
        for entry in outcome['consumers']:
            target = entry['target']
            document = reader.read(target)
            if document['frontmatter'].get('source_authorization') is not None and target not in validated_raw:
                entry['state'] = 'blocked_raw_capture_unavailable'
            if document['frontmatter'].get('independent_repo_read') is not None and target not in validated_repo:
                entry['state'] = 'blocked_repository_request_unavailable'
        policy.fresh()
        return {'schema_version':'wiki.folder-host-reassessment/v2','mode':'host_bound',
                'reassessment':outcome,'enforcement_claim':'none'}
    except FolderCoordinationError:
        raise
    except (ValueError, OSError, KeyError, TypeError, AttributeError, RuntimeError):
        raise FolderCoordinationError('source reassessment unavailable') from None
