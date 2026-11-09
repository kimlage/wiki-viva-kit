"""Bounded, explicitly reported reads of a synthetic self-owned log."""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from jsonschema import ValidationError, validate

from tests.test_context_flow import (
    folder_requirements_policy, folder_requirements_setup, git, repo,
)
from wiki_core.context_integration import IntegrationError, preflight
from wiki_core.context_packet import build_packet, validate_result
from wiki_core.context_policy import PolicyError, load_policy
from wiki_core.coordination_context import (
    CoordinationBinding, ProtectedCoordinationError, prepare_packet, prepare_preflight,
)
from wiki_core.git_env import local_git_environment


CONTEXT = 'finance/costs'
LOG = 'finance/costs/result.md'
PREFIX = '# Synthetic log\n\n## Première entrée\nOnly this entry was read.\n\n'.encode()
OUTSIDE = 'SYNTHETIC_OUTSIDE_SELECTION_42861'
BODY = PREFIX + ('## Later entry\n' + OUTSIDE + '\n' + 'synthetic line\n' * 2000).encode()


@pytest.fixture
def bound_log(repo):
    binding = folder_requirements_setup(repo)
    (repo / LOG).write_bytes(BODY)
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'synthetic approved unmarked log')
    git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    base = git(repo, 'rev-parse', 'HEAD')
    return {'root': repo, 'binding': binding, 'policy': folder_requirements_policy(repo), 'base': base}


def evidence(**overrides):
    row = {'ref': LOG, 'producer': CONTEXT, 'reason': 'synthetic first entry',
           'use': 'interpret', 'classification': 'synthetic',
           'range': {'kind': 'utf8-line-bytes/v1', 'start': 0, 'end': len(PREFIX)}}
    row.update(overrides)
    return row


def build(case, *, rows=None, output=LOG, binding=None, allow=True, revision=None, **kwargs):
    return build_packet(case['root'], case['policy'], CONTEXT, revision or case['base'],
                        [evidence()] if rows is None else rows, 200000,
                        task_id='bounded-log-test', goal='review a selected log slice',
                        output=output, integrator='independent reviewer',
                        entry_folder=CONTEXT,
                        trusted_binding=case['binding'] if binding is None else binding,
                        allow_owned_range=allow, **kwargs)


def result_for(packet):
    return {'schema_version': 'wiki.task-result/v2', 'status': 'completed',
            'task_id': packet['task_id'], 'context_id': packet['context_id'],
            'packet_digest': packet['packet_digest'],
            'changes': [{'path': LOG, 'action': 'modified'}],
            'read_coverage': {'observed_refs': copy.deepcopy(packet['declared_read_set']),
                              'missing': list(packet['coverage']['missing'])},
            'blockers': []}


def proposal(case, packet, replacement=None):
    root = case['root']
    git(root, 'checkout', '-qb', 'wiki/bounded-log-test')
    (root / LOG).write_bytes(BODY + b'## New entry\nSynthetic append.\n' if replacement is None else replacement)
    git(root, 'add', LOG)
    git(root, 'commit', '-qm', 'synthetic candidate')
    return {'context_id': CONTEXT, 'base': case['base'], 'head': git(root, 'rev-parse', 'HEAD'),
            'branch': 'wiki/bounded-log-test', 'packet': packet, 'result': result_for(packet),
            'trusted_binding': case['binding'], 'allow_owned_range': True}


def approve_log(case, content):
    """Advance only the synthetic approved repository and its bound ref."""
    root = case['root']
    (root / LOG).write_bytes(content)
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'advance approved synthetic log')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    case['base'] = git(root, 'rev-parse', 'HEAD')
    case['policy'] = folder_requirements_policy(root)


def approve_log_read_permission(case, *, denied):
    root = case['root']
    config_path = root / 'wiki.config.yaml'
    config = yaml.safe_load(config_path.read_text())
    config['context_access'][CONTEXT]['policy']['deny'] = {'read': [LOG]} if denied else {}
    config_path.write_text(yaml.safe_dump(config))
    git(root, 'add', 'wiki.config.yaml')
    git(root, 'commit', '-qm', 'change synthetic log read permission')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    case['base'] = git(root, 'rev-parse', 'HEAD')
    case['policy'] = folder_requirements_policy(root)


def test_self_owned_slice_is_exactly_bound_and_append_is_review_candidate(bound_log):
    packet = build(bound_log)
    assert packet['schema_version'] == 'wiki.task-context/v2'
    selected = [item for item in packet['inputs'] if item['ref'] == LOG]
    assert len(selected) == 1
    assert selected[0]['range'] == evidence()['range']
    assert selected[0]['text'].encode() == PREFIX
    assert selected[0]['sha256'] == hashlib.sha256(PREFIX).hexdigest()
    assert selected[0]['revision'] == bound_log['base']
    assert any(item.get('range') == evidence()['range'] and item['ref'] == LOG
               for item in packet['declared_read_set'])
    assert OUTSIDE not in json.dumps(packet, ensure_ascii=False)
    result = result_for(packet)
    schemas = Path(__file__).resolve().parents[1] / 'docs/references/schemas'
    validate(packet, json.loads((schemas / 'wiki-task-context-v2.schema.json').read_text()))
    validate(result, json.loads((schemas / 'wiki-task-result-v2.schema.json').read_text()))
    validate_result(result, packet)
    out = preflight(bound_log['root'], bound_log['policy'], **proposal(bound_log, packet))
    assert out['state'] == 'independent_review_required'
    assert out['review'] == out['gates'] == out['merge'] == 'not_performed'
    assert OUTSIDE not in json.dumps(out, ensure_ascii=False)


@pytest.mark.parametrize('replacement', [
    b'# A changed beginning\n',
    BODY.replace(b'## Later entry', b'## Changed old entry'),
    BODY[:-1],
    BODY + b'<!-- wiki:section id=synthetic version=1 -->\n## Candidate marker\n',
], ids=['changed-prefix', 'changed-unselected-history', 'truncate', 'appended-candidate-marker'])
def test_prior_log_cannot_be_rewritten_or_candidate_marker_authorize_it(bound_log, replacement):
    packet = build(bound_log)
    args = proposal(bound_log, packet, replacement)
    if replacement.startswith(BODY):
        # An append containing a new candidate marker must not alter the
        # approved range read; a marker cannot turn that read into a section.
        out = preflight(bound_log['root'], bound_log['policy'], **args)
        assert out['state'] == 'independent_review_required'
        assert not any(item.get('section') == 'synthetic' for item in packet['declared_read_set'])
    else:
        with pytest.raises((IntegrationError, PolicyError, ValueError)):
            preflight(bound_log['root'], bound_log['policy'], **args)


@pytest.mark.parametrize('byte_range', [
    {'kind': 'utf8-line-bytes/v1', 'start': -1, 'end': 4},
    {'kind': 'utf8-line-bytes/v1', 'start': 1, 'end': len(PREFIX)},
    {'kind': 'utf8-line-bytes/v1', 'start': 0, 'end': len(PREFIX) - 2},
    {'kind': 'utf8-line-bytes/v1', 'start': 0, 'end': 0},
    {'kind': 'utf8-line-bytes/v1', 'start': False, 'end': len(PREFIX)},
    {'kind': 'utf8-line-bytes/v1', 'start': 0, 'end': len(BODY) + 1},
    {'kind': 'utf8-line-bytes/v1', 'start': 0, 'end': 65537},
    {'kind': 'other', 'start': 0, 'end': len(PREFIX)},
])
def test_invalid_range_and_budget_fail_closed(bound_log, byte_range):
    with pytest.raises((PolicyError, ValueError)):
        build(bound_log, rows=[evidence(range=byte_range)])


def test_slice_limit_is_enforced_even_when_the_line_and_file_are_large_enough(bound_log):
    long_line = b'x' * 65536 + b'\n'
    approve_log(bound_log, long_line + b'a second line\n')
    with pytest.raises((PolicyError, ValueError)):
        build(bound_log, rows=[evidence(range={
            'kind': 'utf8-line-bytes/v1', 'start': 0, 'end': len(long_line),
        })])


def test_crlf_boundaries_are_exact_and_cannot_split_crlf(bound_log):
    first = '# Entrée\r\nFirst entry.\r\n'.encode()
    approve_log(bound_log, first + b'## Later\r\nOther content.\r\n')
    row = evidence(range={'kind': 'utf8-line-bytes/v1', 'start': 0, 'end': len(first)})
    packet = build(bound_log, rows=[row])
    selected = next(item for item in packet['inputs'] if item['ref'] == LOG)
    assert selected['text'].encode() == first
    assert selected['sha256'] == hashlib.sha256(first).hexdigest()
    row['range']['end'] -= 1  # between CR and LF
    with pytest.raises((PolicyError, ValueError)):
        build(bound_log, rows=[row])


def test_reader_and_packet_do_not_return_unselected_body_or_frontmatter(bound_log):
    from wiki_core.repository_reader import RepositoryReader
    private_marker = 'synthetic-page-id-outside-range-42861'
    frontmatter = ('---\npage_id: ' + private_marker + '\ntitle: ' + OUTSIDE + '\n---\n').encode()
    approve_log(bound_log, frontmatter + BODY)
    selected_range = {'kind': 'utf8-line-bytes/v1', 'start': len(frontmatter),
                      'end': len(frontmatter) + len(PREFIX)}
    observed = RepositoryReader(bound_log['root'], bound_log['base']).read(LOG, byte_range=selected_range)
    # Recursively inspect the entire return, including byte content and any
    # metadata such as page_id, body, text and frontmatter.
    serialized = json.dumps(observed, ensure_ascii=False,
                            default=lambda value: value.decode('utf-8') if isinstance(value, bytes) else str(value))
    assert private_marker not in serialized and OUTSIDE not in serialized
    packet = build(bound_log, rows=[evidence(range=selected_range)])
    serialized_packet = json.dumps(packet, ensure_ascii=False)
    assert private_marker not in serialized_packet and OUTSIDE not in serialized_packet


def test_invalid_utf8_source_is_rejected(bound_log):
    approve_log(bound_log, PREFIX + b'## Later\n\xff invalid UTF-8\n')
    with pytest.raises((PolicyError, ValueError)):
        build(bound_log)


def test_historical_slice_can_be_requalified_only_when_approved_log_is_append_only(bound_log):
    historical = bound_log['base']
    approved = BODY + b'## Approved later entry\nSynthetic history.\n'
    approve_log(bound_log, approved)
    packet = build(bound_log, revision=historical)
    assert next(item for item in packet['inputs'] if item['ref'] == LOG)['revision'] == historical
    args = proposal(bound_log, packet, approved + b'## Proposed append\nSynthetic proposal.\n')
    assert preflight(bound_log['root'], bound_log['policy'], **args)['state'] == 'independent_review_required'


def test_historical_slice_rejects_rewritten_approved_log(bound_log):
    historical = bound_log['base']
    # Keep the selected prefix identical while rewriting an unselected part of
    # the previously approved log: a partial read is not permission to rewrite.
    altered = BODY.replace(b'## Later entry', b'## Rewritten old entry')
    approve_log(bound_log, altered)
    packet = build(bound_log, revision=historical)
    args = proposal(bound_log, packet, altered + b'## Proposed append\nNew.\n')
    with pytest.raises((IntegrationError, PolicyError, ValueError)):
        preflight(bound_log['root'], bound_log['policy'], **args)


def test_historical_range_refuses_changed_owner_before_opening_log(bound_log, monkeypatch):
    from wiki_core.repository_reader import RepositoryReader
    root, historical = bound_log['root'], bound_log['base']
    config_path = root / 'wiki.config.yaml'
    config = yaml.safe_load(config_path.read_text())
    config['context_access'][CONTEXT]['owner'] = 'Another synthetic owner'
    config_path.write_text(yaml.safe_dump(config))
    git(root, 'add', 'wiki.config.yaml')
    git(root, 'commit', '-qm', 'change synthetic context owner')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    bound_log['base'] = git(root, 'rev-parse', 'HEAD')
    bound_log['policy'] = folder_requirements_policy(root)
    original = RepositoryReader._document
    def deny_log(reader, ref, *args, **kwargs):
        assert ref != LOG, 'historical log opened after owner changed'
        return original(reader, ref, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, '_document', deny_log)
    with pytest.raises((PolicyError, ValueError)):
        build(bound_log, revision=historical)


@pytest.mark.parametrize('denied_at', ['historical', 'current'])
def test_range_read_requires_historical_and_current_permission_before_blob_open(bound_log, monkeypatch, denied_at):
    from wiki_core.repository_reader import RepositoryReader
    if denied_at == 'historical':
        approve_log_read_permission(bound_log, denied=True)
        historical = bound_log['base']
        approve_log_read_permission(bound_log, denied=False)
    else:
        historical = bound_log['base']
        approve_log_read_permission(bound_log, denied=True)
    original = RepositoryReader._document
    def deny_log(reader, ref, *args, **kwargs):
        assert ref != LOG, 'log opened despite missing historical or current authority'
        return original(reader, ref, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, '_document', deny_log)
    with pytest.raises((PolicyError, ValueError)):
        build(bound_log, revision=historical)


def test_result_cannot_claim_a_different_slice_or_drop_its_boundaries(bound_log):
    packet = build(bound_log)
    result = result_for(packet)
    for change in ('drop', 'shift'):
        altered = copy.deepcopy(result)
        selected = next(item for item in altered['read_coverage']['observed_refs'] if item['ref'] == LOG)
        if change == 'drop':
            selected.pop('range')
        else:
            selected['range']['end'] -= 1
        with pytest.raises((PolicyError, ValueError)):
            validate_result(altered, packet)


def test_v2_schemas_reject_unsupported_query_reader_and_range_shapes(bound_log):
    packet = build(bound_log)
    schemas = Path(__file__).resolve().parents[1] / 'docs/references/schemas'
    packet_schema = json.loads((schemas / 'wiki-task-context-v2.schema.json').read_text())
    result_schema = json.loads((schemas / 'wiki-task-result-v2.schema.json').read_text())
    result = result_for(packet)
    validate(packet, packet_schema)
    validate(result, result_schema)
    mutations = []
    for field in ('inputs', 'declared_read_set'):
        missing = copy.deepcopy(packet)
        next(item for item in missing[field] if 'range' in item).pop('range')
        mutations.append(missing)
        extra = copy.deepcopy(packet)
        next(item for item in extra[field] if 'range' not in item)['range'] = evidence()['range']
        mutations.append(extra)
    for key, value in (
        ('authority_format', 'v1'), ('query_fingerprint', '0' * 64),
        ('additional_readers', [CONTEXT]), ('query_selections', []),
    ):
        altered = copy.deepcopy(packet)
        altered[key] = value
        mutations.append(altered)
    altered = copy.deepcopy(packet)
    altered['coverage']['mode'] = 'authorized_owner_queries_and_explicit_read_set'
    mutations.append(altered)
    altered = copy.deepcopy(packet)
    next(item for item in altered['inputs'] if 'range' in item)['query_id'] = 'synthetic-query'
    mutations.append(altered)
    for bad in mutations:
        with pytest.raises(ValidationError):
            validate(bad, packet_schema)
    result['read_coverage']['observed_queries'] = []
    with pytest.raises(ValidationError):
        validate(result, result_schema)


def test_trusted_ref_advance_invalidates_range_preflight(bound_log):
    packet = build(bound_log)
    args = proposal(bound_log, packet)
    git(bound_log['root'], 'update-ref', 'refs/remotes/origin/main', args['head'])
    with pytest.raises((IntegrationError, PolicyError, ValueError)):
        preflight(bound_log['root'], bound_log['policy'], **args)


@pytest.mark.parametrize('binding_kind', ['missing', 'wrong_ref', 'missing_context'])
def test_range_preflight_requires_out_of_band_binding_before_any_context_blob(bound_log, monkeypatch, binding_kind):
    from wiki_core.repository_reader import RepositoryReader
    packet = build(bound_log)
    args = proposal(bound_log, packet)
    if binding_kind == 'missing':
        args['trusted_binding'] = None
    elif binding_kind == 'wrong_ref':
        args['trusted_binding'] = CoordinationBinding((CONTEXT,), 'refs/heads/main', 'wiki.config.yaml')
    else:
        args['trusted_binding'] = CoordinationBinding(('finance/tax',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    def deny_body(*_args, **_kwargs):
        pytest.fail('context content opened before range host binding validation')
    monkeypatch.setattr(RepositoryReader, '_document', deny_body)
    with pytest.raises((IntegrationError, PolicyError, ValueError)):
        preflight(bound_log['root'], bound_log['policy'], **args)


def test_candidate_marker_does_not_qualify_a_section_absent_from_approved_log(bound_log):
    row = evidence()
    row.pop('range')
    row['section'] = 'candidate-only'
    with pytest.raises((PolicyError, ValueError)):
        build_packet(bound_log['root'], bound_log['policy'], CONTEXT, bound_log['base'],
                     [row], 200000, task_id='marker-test', goal='synthetic test', output=LOG,
                     integrator='reviewer', entry_folder=CONTEXT, trusted_binding=bound_log['binding'])


@pytest.mark.parametrize('protected', ['finance/costs/index.md', 'finance/costs/AGENTS.md'])
def test_context_index_and_instructions_cannot_be_partially_selected_as_output(bound_log, monkeypatch, protected):
    from wiki_core.repository_reader import RepositoryReader
    original = RepositoryReader._document
    def deny_selected(reader, ref, *args, **kwargs):
        assert ref != protected, 'protected context body opened before refusal'
        return original(reader, ref, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, '_document', deny_selected)
    with pytest.raises((PolicyError, ValueError)):
        build(bound_log, rows=[evidence(ref=protected)], output=protected)


def test_range_task_cannot_include_a_second_same_owner_change(bound_log):
    packet = build(bound_log)
    args = proposal(bound_log, packet)
    other = bound_log['root'] / 'finance/costs/other.md'
    other.write_text('Changed independent synthetic file.\n')
    git(bound_log['root'], 'add', '.')
    git(bound_log['root'], 'commit', '-qm', 'unexpected extra file')
    args['head'] = git(bound_log['root'], 'rev-parse', 'HEAD')
    args['result']['changes'].append({'path': 'finance/costs/other.md', 'action': 'modified'})
    with pytest.raises((IntegrationError, PolicyError, ValueError)):
        preflight(bound_log['root'], bound_log['policy'], **args)


@pytest.mark.parametrize('change', ['missing_binding', 'missing_flag', 'different_output',
                                    'cross_owner', 'query', 'additional_reader', 'section'])
def test_unsupported_authority_and_selector_combinations_are_refused_before_log_open(bound_log, monkeypatch, change):
    from wiki_core.repository_reader import RepositoryReader
    original = RepositoryReader._document
    def deny_log(reader, ref, *args, **kwargs):
        assert ref not in (LOG, 'finance/tax/source.md'), 'protected body was opened'
        return original(reader, ref, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, '_document', deny_log)
    row, options = evidence(), {}
    if change == 'missing_binding':
        options['binding'] = False  # passed through as an invalid non-binding
    elif change == 'missing_flag':
        options['allow'] = False
    elif change == 'different_output':
        options['output'] = 'finance/costs/other.md'
    elif change == 'cross_owner':
        row.update(ref='finance/tax/source.md', producer='finance/tax')
        options['output'] = row['ref']
    elif change == 'query':
        options['queries'] = [{}]
    elif change == 'additional_reader':
        options['additional_readers'] = ('finance/tax',)
    else:
        row['section'] = 'candidate'
    with pytest.raises((PolicyError, ValueError, TypeError)):
        build(bound_log, rows=[row], **options)


def test_legacy_web_packet_and_preflight_do_not_enable_range(bound_log, monkeypatch):
    from wiki_core.repository_reader import RepositoryReader
    case = bound_log
    task = {'task_id': 'bounded-log-test', 'goal': 'review a selected log slice',
            'output': LOG, 'integrator': 'independent reviewer', 'max_bytes': 200000,
            'evidence': [evidence()]}
    payload = {'context_id': CONTEXT, 'approved_revision': case['base'],
               'content_revision': case['base'], 'entry_folder': CONTEXT, 'task': task}
    original = RepositoryReader._document
    def deny_log(reader, ref, *args, **kwargs):
        assert ref != LOG, 'web or legacy route opened range source'
        return original(reader, ref, *args, **kwargs)
    with monkeypatch.context() as guarded:
        guarded.setattr(RepositoryReader, '_document', deny_log)
        with pytest.raises(ProtectedCoordinationError):
            prepare_packet(case['root'], case['binding'], payload)
    packet = build(case)
    args = proposal(case, packet)
    web_payload = {'context_id': CONTEXT, 'approved_revision': case['base'],
                   **{k: args[k] for k in ('base', 'head', 'branch', 'packet', 'result')}}
    with monkeypatch.context() as guarded:
        guarded.setattr(RepositoryReader, '_document', deny_log)
        with pytest.raises(ProtectedCoordinationError):
            prepare_preflight(case['root'], case['binding'], web_payload)
        args.pop('allow_owned_range')
        with pytest.raises((IntegrationError, PolicyError, ValueError)):
            preflight(case['root'], case['policy'], **args)
    legacy = copy.deepcopy(args['result'])
    legacy['schema_version'] = 'wiki.task-result/v1'
    with pytest.raises((PolicyError, ValueError)):
        validate_result(legacy, packet)


def test_legacy_v1_policy_rejects_owned_range_before_any_context_blob(bound_log, monkeypatch):
    from wiki_core.repository_reader import RepositoryReader
    root, base = bound_log['root'], bound_log['base']
    legacy_policy = load_policy(root, base, 'context.yaml')
    legacy_binding = CoordinationBinding(('costs',), 'refs/remotes/origin/main', 'context.yaml')
    legacy_evidence = evidence(producer='costs')
    def deny_body(*_args, **_kwargs):
        pytest.fail('legacy range path opened a context body before refusal')
    monkeypatch.setattr(RepositoryReader, '_document', deny_body)
    with pytest.raises((PolicyError, ValueError)):
        build_packet(root, legacy_policy, 'costs', base, [legacy_evidence], 200000,
                     task_id='v1-range-test', goal='synthetic log read', output=LOG,
                     integrator='reviewer', trusted_binding=legacy_binding, allow_owned_range=True)


def test_host_bound_cli_packet_and_preflight_round_trip(bound_log, tmp_path):
    root, base = bound_log['root'], bound_log['base']
    scripts = Path(__file__).resolve().parents[1] / 'scripts'
    task = {'task_id': 'bounded-log-test', 'goal': 'review a selected log slice',
            'output': LOG, 'integrator': 'independent reviewer', 'max_bytes': 200000,
            'evidence': [evidence()]}
    task_path = tmp_path / 'synthetic-request.json'
    task_path.write_text(json.dumps(task), encoding='utf-8')
    command = [sys.executable, str(scripts / 'wiki_context.py'), '--repo', str(root),
               '--approved-revision', base, 'pack', CONTEXT, '--content-revision', base,
               '--request', str(task_path), '--folder', CONTEXT, '--owned-range']
    env = local_git_environment()
    denied_command = command.copy()
    denied_command[denied_command.index('--request') + 1] = str(tmp_path / 'absent.json')
    no_binding = subprocess.run(denied_command, env=env, text=True, capture_output=True)
    assert no_binding.returncode != 0
    assert 'binding' in no_binding.stderr.lower()
    env.update(WIKI_COORDINATION_ALLOWED_CONTEXTS=CONTEXT,
               WIKI_COORDINATION_TRUSTED_REF='refs/remotes/origin/main')
    packed = subprocess.run(command, env=env, text=True, capture_output=True, check=True)
    packet = json.loads(packed.stdout)
    assert packet['schema_version'] == 'wiki.task-context/v2' and OUTSIDE not in packed.stdout
    args = proposal(bound_log, packet)
    packet_path = tmp_path / 'synthetic-packet.json'
    result_path = tmp_path / 'synthetic-result.json'
    packet_path.write_text(json.dumps(packet), encoding='utf-8')
    result_path.write_text(json.dumps(args['result']), encoding='utf-8')
    check = [sys.executable, str(scripts / 'wiki_context_flow.py'), '--repo', str(root),
             '--approved-revision', base, 'preflight', '--context', CONTEXT, '--base', base,
             '--head', args['head'], '--branch', args['branch'], '--packet', str(packet_path),
             '--result', str(result_path), '--owned-range']
    checked = subprocess.run(check, env=env, text=True, capture_output=True)
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout)['state'] == 'independent_review_required'
    assert OUTSIDE not in checked.stdout
    env.pop('WIKI_COORDINATION_ALLOWED_CONTEXTS')
    env.pop('WIKI_COORDINATION_TRUSTED_REF')
    denied = subprocess.run(check, env=env, text=True, capture_output=True)
    assert denied.returncode != 0 and 'binding' in denied.stderr.lower()

