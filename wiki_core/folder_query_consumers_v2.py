"""Selectively reassess declared folder-query consumers; never attest reads."""
from __future__ import annotations

from wiki_core.context_policy import safe_path, within
from wiki_core.folder_coordination_v2 import _bound_policy
from wiki_core.folder_consumers_v2 import inventory_folder_consumers_v2
from wiki_core.folder_query_history_v2 import assess_folder_query_history_v2
from wiki_core.folder_query_requirements_v2 import query_requirements, same_json
from wiki_core.repo_read import contains_access_secrets


def reassess_query_consumers(root, binding, *, folder, approved_revision, changed_paths,
                             reports, candidates=None, scope=None, max_files=256, max_bytes=1_000_000):
    """Inspect authorized consumers; missing historical reports remain pending."""
    if (not isinstance(changed_paths, list) or not 1 <= len(changed_paths) <= 64
            or not isinstance(reports, list) or len(reports) > 64
            or contains_access_secrets((changed_paths, reports))):
        raise ValueError('query reassessment unavailable')
    paths = [safe_path(path) for path in changed_paths]
    if len(set(paths)) != len(paths):
        raise ValueError('duplicate changed path')
    policy = _bound_policy(root, binding, folder, approved_revision)
    inventory = inventory_folder_consumers_v2(root, policy, folder=folder, scope=scope,
        candidates=candidates, max_files=max_files, max_bytes=max_bytes)
    indexed = {}
    for report in reports:
        if not isinstance(report, dict) or set(report) != {'target', 'query_id', 'packet', 'result', 'integrated_revision'}:
            raise ValueError('invalid query report')
        target = safe_path(report['target'])
        key = (target, report['query_id'])
        if key in indexed:
            raise ValueError('duplicate query report')
        indexed[key] = report
    rows = []
    used = set()
    for consumer in inventory['consumers']:
        for req in consumer['requirements']:
            if req.get('query_contract') != 'wiki.folder-query-receipt/v2':
                continue
            matched = [path for path in paths if path == req['target'] or within(path, req['query']['scope'])]
            if not matched:
                continue
            key = (consumer['path'], req['query_id'])
            if key in used:
                raise ValueError('duplicate consumer requirement')
            used.add(key)
            entry = {'target': consumer['path'], 'query_id': req['query_id'],
                     'changed_paths': matched, 'state': 'declared_without_report'}
            report = indexed.get(key)
            if report is not None:
                packet = report['packet']
                if (not isinstance(packet, dict) or packet.get('schema_version') != 'wiki.folder-query-task-context/v2'
                        or packet.get('base_packet', {}).get('context_folder') != folder
                        or packet.get('base_packet', {}).get('output') != consumer['path']
                        or not isinstance(packet.get('queries'), list) or not 1 <= len(packet['queries']) <= 8):
                    raise ValueError('query report differs from declaration')
                selected = [row for row in packet['queries'] if isinstance(row, dict)
                            and isinstance(row.get('receipt'), dict) and row['receipt'].get('query_id') == req['query_id']]
                if len(selected) != 1 or not same_json(query_requirements(selected, req['max_age_days']), [req]):
                    raise ValueError('query report differs from declaration')
                impact = assess_folder_query_history_v2(root, policy, packet=packet, result=report['result'],
                                                       integrated_revision=report['integrated_revision'], query_id=req['query_id'])
                entry['state'] = impact['state']
                entry['query_state'] = impact['query_state']
                entry['read_verification'] = impact['read_verification']
                entry['output_binding'] = impact['output_binding']
            rows.append(entry)
    if set(indexed) - used:
        raise ValueError('report outside selected query consumers')
    policy.fresh()
    return {'schema_version':'wiki.folder-query-consumer-reassessment/v2',
            'folder':folder, 'policy_revision':policy.policy_revision, 'consumers':rows,
            'coverage':inventory['coverage'], 'reads':'reported_not_independently_verified',
            'review':'not_performed', 'enforcement_claim':'none'}
