"""Projection of reported folder queries into canonical consumer requirements.

These declarations record a reported selection, not verified execution or review.
They have their own version and cannot be interpreted as legacy v1 receipts.
"""
from __future__ import annotations

import json
from wiki_core.context_selection import normalize_query
from wiki_core.folder_query_packet_v2 import build_folder_query_packet_v2, _query_observations
from wiki_core.repo_read import contains_access_secrets


def same_json(left, right):
    """Compare JSON values with their types, including bool versus integer."""
    return json.dumps(left, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False) == \
           json.dumps(right, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def validate_query_report(root, policy, packet, result, *, base_packet):
    """Reproduce the bounded selection and its exact reported read set."""
    if (not isinstance(packet, dict) or packet.get('schema_version') != 'wiki.folder-query-task-context/v2'
            or not same_json(packet.get('base_packet'), base_packet) or not isinstance(result, dict)
            or contains_access_secrets((packet, result))):
        raise ValueError('query report unavailable')
    try:
        queries = packet['queries']
        rebuilt = build_folder_query_packet_v2(root, policy, base_packet=base_packet,
                                               queries=[row['receipt']['request'] for row in queries])
        if not same_json(rebuilt, packet):
            raise ValueError('query packet differs')
        expected = [{'path':row['path'], 'kind':row['kind'], 'revision':row['revision'],
                     'sha256':row['sha256'], 'section':row.get('section'), 'field':row.get('field')}
                    for row in base_packet['inputs']] + _query_observations(packet)
        if (set(result) != {'schema_version','status','task_id','context_id','packet_digest',
                            'observed','observed_queries','changes'}
                or result['schema_version'] != 'wiki.folder-query-task-result/v2'
                or result['status'] != 'completed' or result['task_id'] != base_packet['task_id']
                or result['context_id'] != base_packet['context_id']
                or result['packet_digest'] != packet['packet_digest']
                or result['observed'] != expected
                or result['observed_queries'] != [row['receipt']['query_id'] for row in queries]):
            raise ValueError('query observations unavailable')
        return queries
    except (KeyError, TypeError, AttributeError):
        raise ValueError('query report unavailable') from None


def query_requirements(queries, max_age_days):
    """Return metadata only; source text and observation reports stay separate."""
    if type(max_age_days) is not int or not 0 <= max_age_days <= 3650:
        raise ValueError('query age policy unavailable')
    projections = []
    for row in queries:
        receipt = row['receipt']; request = normalize_query(receipt['request'])
        if receipt['schema_version'] != 'wiki.folder-query-receipt/v2':
            raise ValueError('folder query receipt required')
        projections.append({**({'query_index':receipt['index_path']} if request['target'] != receipt['index_path'] else {}),
            'target':request['target'], 'fields':['*'], 'temporal':'current',
            'max_age_days':max_age_days, 'consumed_revision':receipt['content_revision'],
            'use':request['use'], 'classification':request['classification'], 'query':request['query'],
            'members_digest':receipt['members_digest'], 'selected_digest':receipt['selected_digest'],
            'query_policy_revision':receipt['policy_revision'], 'authority_digest':receipt['authority_digest'],
            'query_contract':receipt['schema_version'], 'query_reason':request['reason'],
            'query_id':receipt['query_id'], 'query_receipt_digest':receipt['receipt_digest']})
    return projections
