"""Synthetic protected coordination for bounded reads with owned inputs."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
import yaml
from jsonschema import validate

from tests.test_context_flow import git, repo  # noqa: F401 - pytest fixture
from tests.test_coordination_protected import bound_server  # noqa: F401
from wiki_core.context_integration import IntegrationError, preflight
from wiki_core.context_policy import load_policy
from wiki_core.context_packet import _finalize_packet
from wiki_core.web.admin.sessions import ADMIN_SESSION_HEADER
from wiki_core.repository_reader import RepositoryReader


OWNER = 'finance/costs'
LOG = f'{OWNER}/historical-log.md'
TECH = f'{OWNER}/technical-input.md'
OUTPUTS = [LOG] + [f'{OWNER}/target-{i:02}.md' for i in range(15)]
PREFIX = '# Synthetic history\n\n## First entry\nOnly this entry was selected.\n\n'.encode()
OUTSIDE = 'SYNTHETIC_OUTSIDE_SELECTED_HISTORY_98761'
LOG_BODY = PREFIX + (OUTSIDE + '\n').encode() + b'old synthetic row\n' * 48_000
TECH_BODY = b'# Synthetic technical input\n' + b'synthetic technical detail\n' * 17_900


def row(ref, **extra):
    return {'ref': ref, 'producer': OWNER, 'reason': 'synthetic selected evidence',
            'use': 'interpretation', 'classification': 'context', **extra}


@pytest.fixture
def case(repo, bound_server):
    server, token = bound_server
    (repo / LOG).write_bytes(LOG_BODY)
    (repo / TECH).write_bytes(TECH_BODY)
    for path in OUTPUTS[1:]:
        (repo / path).write_text('# Synthetic destination\nInitial state.\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'approved synthetic large source and targets')
    git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    base = git(repo, 'rev-parse', 'HEAD')
    selected_range = {'kind': 'utf8-line-bytes/v1', 'start': 0, 'end': len(PREFIX)}
    task = {'task_id': 'owned-range-coordination', 'goal': 'Review synthetic owned sources',
            'output': LOG, 'integrator': 'independent reviewer', 'max_bytes': 1_000_000,
            'range_mode': 'owned-evidence/v1', 'evidence': [
                row(LOG, range=selected_range, expected_document_sha256=hashlib.sha256(LOG_BODY).hexdigest()),
                row(TECH),
            ]}
    data = {'context_id': OWNER, 'approved_revision': base, 'content_revision': base,
            'entry_folder': OWNER, 'entry_index': f'{OWNER}/index.md', 'task': task}
    return {'root': repo, 'server': server, 'headers': {ADMIN_SESSION_HEADER: token}, 'base': base, 'data': data}


def post_packet(case, data=None):
    return case['server'].post('/api/coordination/protected/packet', data or case['data'], headers=case['headers'])


def propose(case, packet, *, log_body=None):
    root = case['root']
    git(root, 'checkout', '-qb', 'wiki/owned-range-technical')
    (root / LOG).write_bytes(LOG_BODY + b'## Synthetic append\n' if log_body is None else log_body)
    for path in OUTPUTS[1:]:
        with (root / path).open('a') as stream:
            stream.write('Synthetic reviewed change.\n')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'propose synthetic owned changes')
    result = {'schema_version': 'wiki.task-result/v3', 'status': 'completed',
              'task_id': packet['task_id'], 'context_id': packet['context_id'],
              'packet_digest': packet['packet_digest'],
              'changes': [{'path': path, 'action': 'modified'} for path in OUTPUTS],
              'read_coverage': {'observed_refs': copy.deepcopy(packet['declared_read_set']),
                                'missing': copy.deepcopy(packet['coverage']['missing'])}, 'blockers': []}
    return {'context_id': OWNER, 'approved_revision': case['base'], 'base': case['base'],
            'head': git(root, 'rev-parse', 'HEAD'), 'branch': 'wiki/owned-range-technical',
            'packet': packet, 'result': result}


def post_preflight(case, data):
    return case['server'].post('/api/coordination/protected/preflight', data, headers=case['headers'])


def test_http_single_packet_with_owned_log_range_and_technical_inputs(case):
    # A complete log plus the identical technical evidence cannot fit the cap.
    whole = copy.deepcopy(case['data'])
    del whole['task']['range_mode']
    del whole['task']['evidence'][0]['range']
    status, rejected = post_packet(case, whole)
    assert status == 409 and rejected['error_code'] == 'coordination_budget_exceeded'

    technical_only = copy.deepcopy(whole)
    technical_only['task']['evidence'] = technical_only['task']['evidence'][1:]
    status, incomplete = post_packet(case, technical_only)
    assert status == 200
    assert all(item['ref'] != LOG for item in incomplete['packet']['declared_read_set'])

    status, response = post_packet(case)
    assert status == 200
    packet = response['packet']
    assert packet['schema_version'] == 'wiki.task-context/v3'
    explicit = {item['ref']: item for item in packet['inputs'] if item['ref'] in (LOG, TECH)}
    assert explicit[LOG]['text'].encode() == PREFIX
    assert explicit[LOG]['document_sha256'] == hashlib.sha256(LOG_BODY).hexdigest()
    assert explicit[LOG]['sha256'] == hashlib.sha256(PREFIX).hexdigest()
    assert explicit[LOG]['revision'] == case['base']
    assert explicit[TECH]['text'].encode() == TECH_BODY
    assert packet['bytes_used'] <= 1_000_000
    assert OUTSIDE not in json.dumps(packet)
    request = propose(case, packet)
    schemas = Path(__file__).resolve().parents[1] / 'docs/references/schemas'
    validate(packet, json.loads((schemas / 'wiki-task-context-v3.schema.json').read_text()))
    validate(request['result'], json.loads((schemas / 'wiki-task-result-v3.schema.json').read_text()))
    status, accepted = post_preflight(case, request)
    assert status == 200
    assert accepted['preflight']['state'] == 'independent_review_required'
    assert accepted['preflight']['review'] == accepted['preflight']['merge'] == 'not_performed'
    assert len(accepted['preflight']['changes']) == 16


@pytest.mark.parametrize('change', ['missing_digest', 'wrong_digest', 'offset', 'other_owner', 'query'])
def test_invalid_owned_selections_are_rejected(case, change):
    data = copy.deepcopy(case['data'])
    first = data['task']['evidence'][0]
    if change == 'missing_digest':
        del first['expected_document_sha256']
    elif change == 'wrong_digest':
        first['expected_document_sha256'] = '0' * 64
    elif change == 'offset':
        first['range']['start'] = 1  # not a line boundary
    elif change == 'other_owner':
        first['producer'] = 'finance/tax'
    else:
        data['task']['queries'] = [{'unsupported': 'not a part of this contract'}]
    status, response = post_packet(case, data)
    assert status == 409
    assert 'packet' not in response and OUTSIDE not in json.dumps(response)


def test_result_must_report_all_delivered_inputs(case):
    status, response = post_packet(case)
    assert status == 200
    request = propose(case, response['packet'])
    request['result']['read_coverage']['observed_refs'] = [
        item for item in request['result']['read_coverage']['observed_refs'] if item['ref'] != LOG]
    status, rejected = post_preflight(case, request)
    assert status == 409 and rejected['error_code'] == 'coordination_preflight_unavailable'


def test_history_rewrite_outside_selected_range_is_rejected(case):
    status, response = post_packet(case)
    assert status == 200
    changed = LOG_BODY.replace(OUTSIDE.encode(), b'SYNTHETIC_REWRITTEN_OLD_HISTORY', 1)
    request = propose(case, response['packet'], log_body=changed)
    status, rejected = post_preflight(case, request)
    assert status == 409 and rejected['error_code'] == 'coordination_preflight_unavailable'


def test_stale_approved_base_is_rejected(case):
    status, response = post_packet(case)
    assert status == 200
    request = propose(case, response['packet'])
    git(case['root'], 'update-ref', 'refs/remotes/origin/main', request['head'])
    status, rejected = post_preflight(case, request)
    assert status == 409
    assert rejected['error_code'] in {'coordination_policy_unavailable', 'coordination_preflight_unavailable'}


def test_forged_packet_budget_above_host_limit_is_rejected(case):
    status, response = post_packet(case)
    assert status == 200
    packet = copy.deepcopy(response['packet'])
    packet['max_bytes'] = 1_000_001
    # Recalculate the canonical digest and result binding so failure cannot be
    # attributed merely to a malformed or stale digest.
    packet = _finalize_packet(packet, packet['max_bytes'])
    request = propose(case, packet)
    status, rejected = post_preflight(case, request)
    assert status == 409 and rejected['error_code'] == 'coordination_preflight_unavailable'


@pytest.mark.parametrize('denied_at', ['historical', 'current'])
def test_current_and_historical_denies_apply_before_reading_selected_log(case, monkeypatch, denied_at):
    root = case['root']
    config_path = root / 'wiki.config.yaml'
    config = yaml.safe_load(config_path.read_text())

    def approve(denied):
        config['context_access'][OWNER]['policy']['deny'] = {'read': [LOG]} if denied else {}
        config_path.write_text(yaml.safe_dump(config))
        git(root, 'add', 'wiki.config.yaml')
        git(root, 'commit', '-qm', 'synthetic authority change')
        git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
        return git(root, 'rev-parse', 'HEAD')

    denied_revision = approve(True)
    if denied_at == 'historical':
        current = approve(False)
        selected = denied_revision
    else:
        current = denied_revision
        selected = case['base']
    request = copy.deepcopy(case['data'])
    request['approved_revision'] = current
    request['content_revision'] = selected
    original = RepositoryReader._document
    opened = []
    def observed(reader, ref, *args, **kwargs):
        if ref == LOG:
            opened.append(ref)
        return original(reader, ref, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, '_document', observed)
    status, response = post_packet(case, request)
    assert status == 409 and 'packet' not in response
    assert opened == []


def test_new_full_document_requirement_cannot_be_met_by_partial_read(case):
    status, response = post_packet(case)
    assert status == 200
    request = propose(case, response['packet'])
    requirement = {'target': LOG, 'fields': ['*'], 'temporal': 'current', 'max_age_days': 30,
                   'consumed_revision': case['base'], 'use': 'interpretation', 'classification': 'context'}
    target = case['root'] / OUTPUTS[1]
    target.write_text('---\n' + yaml.safe_dump({'information_requirements': [requirement]}) +
                      '---\nSynthetic edited destination.\n')
    git(case['root'], 'add', OUTPUTS[1])
    git(case['root'], 'commit', '--amend', '--no-edit', '-q')
    request['head'] = git(case['root'], 'rev-parse', 'HEAD')
    status, rejected = post_preflight(case, request)
    assert status == 409 and rejected['error_code'] == 'coordination_preflight_unavailable'
    policy = load_policy(case['root'], case['base'], 'wiki.config.yaml', trusted_ref='refs/remotes/origin/main')
    with pytest.raises(IntegrationError, match='requirement does not match task evidence'):
        preflight(case['root'], policy, context_id=OWNER, base=request['base'], head=request['head'],
                  branch=request['branch'], packet=request['packet'], result=request['result'],
                  trusted_binding=case['server'].server.coordination_binding, allow_owned_ranges=True)


def test_extra_destination_owned_by_another_context_is_rejected(case):
    status, response = post_packet(case)
    assert status == 200
    request = propose(case, response['packet'])
    cross = 'finance/tax/source.md'
    with (case['root'] / cross).open('a') as stream:
        stream.write('\nSynthetic disallowed owner change.\n')
    git(case['root'], 'add', cross)
    git(case['root'], 'commit', '--amend', '--no-edit', '-q')
    request['head'] = git(case['root'], 'rev-parse', 'HEAD')
    request['result']['changes'].append({'path': cross, 'action': 'modified'})
    status, rejected = post_preflight(case, request)
    assert status == 409 and rejected['error_code'] == 'coordination_preflight_unavailable'
