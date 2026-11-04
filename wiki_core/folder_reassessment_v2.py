"""Join an authorized consumer inventory to explicit v2 consumption reports.

This read-only preview never asserts that a declared or reported read happened.
It does not discover receipts, perform migrations, grant access or update pages.
"""
import json
from pathlib import Path
import re

import yaml

from wiki_core.context_policy import UniqueLoader, safe_path
from wiki_core.frontmatter import FRONTMATTER_RE
from wiki_core.folder_consumers_v2 import inventory_folder_consumers_v2
from wiki_core.folder_impact_v2 import assess_folder_source_v2
from wiki_core.folder_policy_v2 import FORMAT
from wiki_core.repo_read import contains_access_secrets, read_independent_repo, remote_identity, RepoReadError, _git as repo_git
from wiki_core.repository_reader import RepositoryReader


class FolderReassessmentError(ValueError):
    pass


def _selector(field):
    if field == '*':
        return None, None
    if field.startswith('field:'):
        return None, field.removeprefix('field:')
    if field.startswith('section:'):
        return field.removeprefix('section:'), None
    return None


def _repository_node_matches(text, expected):
    """A wiki source node names a repository; it never grants access to it."""
    match = FRONTMATTER_RE.match(text) if isinstance(text, str) else None
    if not match:
        return False
    try:
        metadata = yaml.load(match.group(1), Loader=UniqueLoader)
        if (not isinstance(metadata, dict) or metadata.get('page_type') != 'source'
                or metadata.get('platform') != 'repo' or not isinstance(metadata.get('source_locator'), str)):
            return False
        locator = metadata['source_locator']
        return (locator if locator == expected else remote_identity(locator)[0]) == expected
    except (ValueError, TypeError, yaml.YAMLError, RecursionError):
        return False


def reassess_folder_source_v2(root, policy, *, folder, source, reports,
                               scope=None, candidates=None, max_files=256, max_bytes=1_000_000,
                               independent_repo=None):
    """Join exact authored selectors to explicit packets, with incomplete coverage visible."""
    if independent_repo is not None:
        return _reassess_independent_repo(root, policy, folder=folder, source=source, reports=reports,
                    scope=scope, candidates=candidates, max_files=max_files, max_bytes=max_bytes,
                    selection=independent_repo)
    if getattr(policy, 'format_version', None) != FORMAT or not policy._binding or Path(policy._binding[0]) != Path(root).resolve():
        raise FolderReassessmentError('bound v2 policy required')
    policy = policy.fresh()
    source = safe_path(source)
    if not isinstance(reports, list) or len(reports) > 64 or contains_access_secrets(reports):
        raise FolderReassessmentError('bounded secret-free reports required')
    index = {}
    for row in reports:
        if not isinstance(row, dict) or set(row) != {'target', 'section', 'field', 'packet', 'result'}:
            raise FolderReassessmentError('invalid explicit report')
        target = safe_path(row['target'])
        section, field = row['section'], row['field']
        if ((section is not None and (not isinstance(section, str) or not section))
                or (field is not None and (not isinstance(field, str) or not field))
                or (section is not None and field is not None)):
            raise FolderReassessmentError('invalid explicit selector')
        key = (target, section, field)
        if key in index:
            raise FolderReassessmentError('duplicate explicit report')
        index[key] = row

    inventory = inventory_folder_consumers_v2(root, policy, folder=folder, scope=scope,
                    candidates=candidates, max_files=max_files, max_bytes=max_bytes,
                    retain_unresolved_target=source if source.endswith('.md') else None)
    rows = []
    used = set()
    declared = set()
    for consumer in inventory['consumers']:
        target = consumer['path']
        for requirement in consumer['requirements']:
            if requirement['target'] != source:
                continue
            for field in requirement['fields']:
                key = (target, field)
                if key in declared:
                    raise FolderReassessmentError('ambiguous repeated requirement selector')
                declared.add(key)
                entry = {'target': target, 'source': source, 'selector': field,
                         'temporal': requirement['temporal'], 'max_age_days': requirement['max_age_days']}
                selector = _selector(field)
                if requirement.get('query') or requirement.get('source_kind'):
                    entry['state'] = 'unsupported_requirement'
                elif selector is None:
                    entry['state'] = 'unsupported_selector'
                elif requirement['temporal'] == 'historical':
                    entry['state'] = 'historical_review_required'
                else:
                    section, selected_field = selector
                    report_key = (target, section, selected_field)
                    report = index.get(report_key)
                    if report is None:
                        entry['state'] = 'declared_without_report'
                    else:
                        # An authored pin or use restriction cannot be silently
                        # matched to a different consumption report.
                        packet = report['packet']
                        inputs = packet.get('inputs') if isinstance(packet, dict) else None
                        matching = [item for item in inputs if isinstance(item, dict)
                                    and item.get('kind') == 'evidence' and item.get('path') == source
                                    and item.get('section') == section and item.get('field') == selected_field] if isinstance(inputs, list) else []
                        if (len(matching) != 1
                                or matching[0].get('use') != requirement.get('use', 'interpret')
                                or matching[0].get('classification') != requirement.get('classification', 'internal')
                                or ('consumed_revision' in requirement
                                    and requirement['consumed_revision'] != matching[0].get('revision'))):
                            raise FolderReassessmentError('report differs from declared source constraints')
                        impact = assess_folder_source_v2(root, policy, packet=report['packet'], result=report['result'],
                                  target=target, source=source, section=section, field=selected_field)
                        entry['state'] = impact['state']
                        entry['impact'] = impact['candidates'][0]
                        used.add(report_key)
                rows.append(entry)
    if set(index) != used:
        raise FolderReassessmentError('report does not match a supported selected requirement')
    policy.fresh()
    result = {'schema_version': 'wiki.folder-source-reassessment/v2', 'policy_revision': policy.policy_revision,
              'context_id': inventory['context_id'], 'source': source, 'selection': inventory['selection'],
              'inspected_count': inventory['inspected_count'], 'consumers': rows,
              'coverage': 'selected_authorized_consumer_paths_and_explicit_reports_only',
              'verification': 'declarations_and_reports_are_not_execution_proof',
              'changes': 'none'}
    if contains_access_secrets(result):
        raise FolderReassessmentError('secret detected in reassessment')
    return result


def _reassess_independent_repo(root, policy, *, folder, source, reports, scope, candidates,
                               max_files, max_bytes, selection):
    """Compare reported local Git selections; a caller's report is not a read proof."""
    if (not isinstance(selection, dict) or set(selection) != {'root', 'identity', 'revision', 'path'}
            or not isinstance(selection['root'], str) or not Path(selection['root']).is_absolute()
            or not isinstance(selection['identity'], str) or not isinstance(selection['revision'], str)
            or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', selection['revision'])
            or contains_access_secrets(selection)):
        raise FolderReassessmentError('independent repository selection unavailable')
    path = safe_path(selection['path'])
    if not isinstance(reports, list) or not reports or len(reports) > 64 or contains_access_secrets(reports):
        raise FolderReassessmentError('explicit bounded repository reports required')
    try:
        if len(json.dumps(reports, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()) > 2_000_000:
            raise FolderReassessmentError('repository reports exceed byte limit')
    except (TypeError, ValueError, RecursionError):
        raise FolderReassessmentError('invalid repository reports') from None
    normalized = []
    receipts = {}
    for report in reports:
        if not isinstance(report, dict) or set(report) != {'target', 'section', 'field', 'packet', 'result', 'repo_read'}:
            raise FolderReassessmentError('invalid repository report')
        if report['section'] is not None or report['field'] is not None:
            raise FolderReassessmentError('whole repository source node selection required')
        receipt = report['repo_read']
        if (not isinstance(receipt, dict) or set(receipt) != {'schema_version', 'repository', 'revision', 'path', 'blob',
                    'document_sha256', 'content_sha256', 'section', 'field', 'text', 'access'}
                or receipt.get('schema_version') != 'wiki.independent-repo-read/v1'
                or not isinstance(receipt.get('repository'), dict)
                or set(receipt['repository']) != {'identity', 'remote_name', 'transport', 'identity_evidence'}
                or receipt['repository'].get('identity') != selection['identity']
                or receipt['repository'].get('remote_name') != 'origin'
                or receipt['repository'].get('transport') not in ('https', 'ssh')
                or receipt['repository'].get('identity_evidence') != 'configured_origin_not_remote_authentication'
                or receipt.get('path') != path or not isinstance(receipt.get('revision'), str)
                or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', receipt['revision'])
                or not isinstance(receipt['blob'], str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', receipt['blob'])
                or any(not isinstance(receipt[k], str) or not re.fullmatch(r'[0-9a-f]{64}', receipt[k])
                       for k in ('document_sha256', 'content_sha256'))
                or not isinstance(receipt['text'], str) or not isinstance(receipt['access'], str)
                or (receipt['section'] is not None and (not isinstance(receipt['section'], str) or not receipt['section'].strip()))
                or (receipt['field'] is not None and (not isinstance(receipt['field'], str) or not receipt['field'].strip()))
                or (receipt['section'] is not None and receipt['field'] is not None)):
            raise FolderReassessmentError('repository report identity unavailable')
        key = (safe_path(report['target']), report['section'], report['field'])
        if key in receipts:
            raise FolderReassessmentError('duplicate repository report')
        receipts[key] = receipt
        normalized.append({k: report[k] for k in ('target', 'section', 'field', 'packet', 'result')})

    # The existing path validates *all* selected consumers and their wiki-node
    # reports before this function opens any independent-repository content.
    out = reassess_folder_source_v2(root, policy, folder=folder, source=source, reports=normalized,
                  scope=scope, candidates=candidates, max_files=max_files, max_bytes=max_bytes)
    node = RepositoryReader(root, policy.policy_revision).read(safe_path(source))
    if not _repository_node_matches(node['text'], selection['identity']):
        raise FolderReassessmentError('repository source node unavailable')
    for report in normalized:
        inputs = report['packet']['inputs']
        matches = [row for row in inputs if row.get('kind') == 'evidence' and row.get('path') == source
                   and row.get('section') is None and row.get('field') is None]
        if len(matches) != 1 or not _repository_node_matches(matches[0].get('text'), selection['identity']):
            raise FolderReassessmentError('reported repository source node unavailable')

    for entry in out['consumers']:
        selector = _selector(entry['selector'])
        if selector is None:
            continue
        key = (entry['target'], selector[0], selector[1])
        if key not in receipts:
            continue
        receipt = receipts[key]
        try:
            prior = read_independent_repo(Path(selection['root']), selection['identity'], receipt['revision'], path,
                                          section=receipt.get('section'), field=receipt.get('field'))
            if prior != receipt:
                raise FolderReassessmentError('reported repository selection differs')
            repo_git(Path(selection['root']), 'merge-base', '--is-ancestor', receipt['revision'], selection['revision'])
        except (ValueError, OSError, TypeError):
            raise FolderReassessmentError('reported repository selection unavailable') from None
        try:
            latest = read_independent_repo(Path(selection['root']), selection['identity'], selection['revision'], path,
                                           section=receipt.get('section'), field=receipt.get('field'))
        except (RepoReadError, OSError, TypeError):
            entry['state'] = 'blocked_repository_selection_unavailable'
            continue
        changed = prior['content_sha256'] != latest['content_sha256']
        entry['repository_impact'] = {'repository': selection['identity'], 'path': path,
              'consumed_revision': prior['revision'], 'current_revision': latest['revision'],
              'section': prior['section'], 'field': prior['field'],
              'before_digest': prior['content_sha256'], 'after_digest': latest['content_sha256'],
              'source_state': 'changed' if changed else 'unchanged',
              'verification': 'caller_reported_not_independently_verified'}
        if changed and entry['state'] == 'verification_pending':
            entry['state'] = 'review_pending'
    policy.fresh()
    out['coverage'] = 'selected_wiki_consumers_and_explicit_repository_reports_only'
    out['repository'] = {'identity': selection['identity'], 'path': path,
                         'revision': selection['revision'], 'identity_evidence': 'configured_origin_not_remote_authentication'}
    out['verification'] = 'repository_consumption_and_execution_not_independently_verified'
    if contains_access_secrets(out):
        raise FolderReassessmentError('secret detected in reassessment')
    return out
