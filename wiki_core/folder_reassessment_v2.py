"""Join an authorized consumer inventory to explicit v2 consumption reports.

This read-only preview never asserts that a declared or reported read happened.
It does not discover receipts, perform migrations, grant access or update pages.
"""
from pathlib import Path

from wiki_core.context_policy import safe_path
from wiki_core.folder_consumers_v2 import inventory_folder_consumers_v2
from wiki_core.folder_impact_v2 import assess_folder_source_v2
from wiki_core.folder_policy_v2 import FORMAT
from wiki_core.repo_read import contains_access_secrets


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


def reassess_folder_source_v2(root, policy, *, folder, source, reports,
                               scope=None, candidates=None, max_files=256, max_bytes=1_000_000):
    """Join exact authored selectors to explicit packets, with incomplete coverage visible."""
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
