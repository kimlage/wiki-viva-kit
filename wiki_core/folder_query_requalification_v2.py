"""Rebuild explicit query reports before proposing a replacement declaration."""
from __future__ import annotations

import json
from wiki_core.folder_query_history_v2 import assess_folder_query_history_v2
from wiki_core.folder_query_requirements_v2 import query_requirements, same_json
from wiki_core.repo_read import contains_access_secrets


def prepare_query_replacements(root, policy, *, folder, target, prior_requirements, query_rows, reports):
    """Return exact proposed replacements; independent review is still required."""
    if (not isinstance(reports, list) or not 1 <= len(reports) <= 8
            or not isinstance(prior_requirements, list) or contains_access_secrets(reports)):
        raise ValueError('query requalification unavailable')
    if len(json.dumps(reports, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()) > 2_000_000:
        raise ValueError('query requalification exceeds byte limit')
    replacements = {}
    for report in reports:
        if (not isinstance(report, dict)
                or set(report) != {'target', 'query_id', 'packet', 'result', 'integrated_revision'}
                or report['target'] != target or not isinstance(report['query_id'], str)
                or report['query_id'] in replacements or not isinstance(report['packet'], dict)
                or not isinstance(report['packet'].get('base_packet'), dict)
                or report['packet']['base_packet'].get('context_folder') != folder
                or report['packet']['base_packet'].get('output') != target):
            raise ValueError('invalid query requalification report')
        qid = report['query_id']
        old = [item for item in prior_requirements if isinstance(item, dict)
               and item.get('query_contract') == 'wiki.folder-query-receipt/v2' and item.get('query_id') == qid]
        current = [item for item in query_rows if item.get('receipt', {}).get('query_id') == qid]
        historical = report['packet'].get('queries') if isinstance(report['packet'], dict) else None
        old_rows = [item for item in historical if isinstance(item, dict)
                    and item.get('receipt', {}).get('query_id') == qid] if isinstance(historical, list) else []
        if (len(old) != 1 or len(current) != 1 or len(old_rows) != 1
                or not same_json(query_requirements(old_rows, old[0]['max_age_days']), old)):
            raise ValueError('query requalification does not match prior declaration')
        impact = assess_folder_query_history_v2(root, policy, packet=report['packet'], result=report['result'],
                                               integrated_revision=report['integrated_revision'], query_id=qid)
        current_receipt = current[0]['receipt']
        if (impact['target'] != target or impact['state'] != 'review_pending'
                or impact['query_state'] not in ('changed', 'unchanged')
                or impact['after_members_digest'] != current_receipt['members_digest']
                or impact['after_selected_digest'] != current_receipt['selected_digest']):
            raise ValueError('query requalification cannot be reproduced')
        replacements[qid] = query_requirements(current, old[0]['max_age_days'])[0]
    return replacements
