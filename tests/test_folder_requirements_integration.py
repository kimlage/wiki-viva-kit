"""Folder packet, preflight and requirements use the same reported read set."""
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tests.test_folder_policy_core import repo, enable_alpha, folder_policy, git, write
from wiki_core.context_integration import preflight
from wiki_core.context_packet import build_packet
from wiki_core.context_requirements import requirements_from_result

KIT = Path(__file__).resolve().parents[1]


def task_result(packet, output):
    return {
        'schema_version': 'wiki.task-result/v1', 'status': 'completed',
        'task_id': packet['task_id'], 'context_id': packet['context_id'],
        'packet_digest': packet['packet_digest'],
        'changes': [{'path': output, 'action': 'created'}],
        'read_coverage': {'observed_refs': packet['declared_read_set'],
                          'observed_queries': [row['query_id'] for row in packet.get('query_selections', [])],
                          'missing': packet['coverage']['missing']},
        'blockers': [],
    }


def propose(repo, output):
    git(repo, 'checkout', '-qb', 'wiki/folder-requirements')
    write(repo, output, '# Independent interpretation\n')
    git(repo, 'add', output)
    git(repo, 'commit', '-qm', 'propose interpretation')
    return git(repo, 'rev-parse', 'HEAD')


@pytest.mark.parametrize('historical_content', [False, True])
def test_query_anchor_equal_to_index_passes_preflight_and_requirements(repo, historical_content):
    enable_alpha(repo)
    write(repo, 'alpha/index.md', '---\npage_id: alpha-index\npage_type: source_catalog\n---\n# Index\n')
    write(repo, 'alpha/items/one.md', '---\npage_id: one\npage_type: claim\nstatus: active\namount: 5\n---\n# One\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'authorize query fixture')
    git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    content_revision = git(repo, 'rev-parse', 'HEAD')
    if historical_content:
        write(repo, 'unrelated.md', '# Unrelated change\n')
        git(repo, 'add', 'unrelated.md')
        git(repo, 'commit', '-qm', 'unrelated approved change')
        git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    base = git(repo, 'rev-parse', 'HEAD')
    policy = folder_policy(repo)
    query = {'target': 'alpha/index.md', 'reason': 'selected collection', 'use': 'interpret',
             'classification': 'synthetic', 'query': {'scope': 'alpha/items', 'filters': {'status': 'active'},
             'field': 'amount', 'max_enumerated': 20, 'max_matches': 10, 'max_scan_bytes': 100000}}
    selected = build_packet(repo, policy, 'alpha', content_revision, [], 100000, task_id='query',
                            goal='interpret', output='alpha/output.md', integrator='operator',
                            entry_folder='alpha/aux', queries=[query])
    assert sum(item['ref'] == 'alpha/index.md' for item in selected['inputs']) == 2
    reads = [item for item in selected['declared_read_set'] if item['ref'] == 'alpha/index.md']
    assert len(reads) == (2 if historical_content else 1)
    assert {item['revision'] for item in reads} == {base, content_revision}
    result = task_result(selected, 'alpha/output.md')
    head = propose(repo, 'alpha/output.md')
    checked = preflight(repo, policy, context_id='alpha', base=base, head=head,
                        branch='wiki/folder-requirements', packet=selected, result=result)
    assert checked['state'] == 'independent_review_required'
    git(repo, 'update-ref', 'refs/remotes/origin/main', head)
    derived = requirements_from_result(repo, folder_policy(repo), packet=selected, result=result,
        output_path='alpha/output.md', proposal_head=head, temporal='current', max_age_days=30)
    assert any(row.get('query') == query['query'] and row['target'] == query['target']
               for row in derived['information_requirements'])
    assert derived['read_claim'] == 'reported_not_verified'


def enable_additional_reader(repo, output):
    enable_alpha(repo)
    config = yaml.safe_load((repo/'wiki.config.yaml').read_text())
    refs = [('.', 'AGENTS.md'), ('alpha', 'alpha/AGENTS.override.md'),
            ('alpha', 'alpha/aux/AGENTS.md'), ('alpha', 'alpha/index.md'), ('alpha', output)]
    rules = [{'from_context': owner, 'to_context': 'beta', 'selector': ref,
              'use': 'interpretation', 'classification': 'context', 'expires': '2099-01-01'}
             for owner, ref in refs]
    config['context_access']['.']['exports'].append(rules[0])
    config['context_access']['alpha']['exports'] = rules[1:]
    config['context_access']['beta'] = {'owner': 'beta operator', 'imports': copy.deepcopy(rules),
        'policy': {'read': ['.'], 'write': ['self'], 'capabilities': [], 'deny': {}, 'publication': []}}
    write(repo, 'wiki.config.yaml', yaml.safe_dump(config))
    git(repo, 'add', 'wiki.config.yaml')
    git(repo, 'commit', '-qm', 'authorize explicit additional reader')
    git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')


def test_local_operator_must_repeat_additional_reader_for_cli_stages(repo, tmp_path):
    output = 'alpha/output.md'
    enable_additional_reader(repo, output)
    base = git(repo, 'rev-parse', 'HEAD')
    selected = build_packet(repo, folder_policy(repo), 'alpha', base, [], 100000, task_id='readers',
                            goal='interpret', output=output, integrator='operator',
                            entry_folder='alpha/aux', additional_readers=('beta',))
    result = task_result(selected, output)
    head = propose(repo, output)
    files = tmp_path.parent/(tmp_path.name + '-local-operator')
    files.mkdir()
    packet_path = files/'packet.json'
    result_path = files/'result.json'
    packet_path.write_text(json.dumps(selected), encoding='utf-8')
    result_path.write_text(json.dumps(result), encoding='utf-8')
    prefix = [sys.executable, str(KIT/'scripts/wiki_context_flow.py'), '--repo', str(repo)]
    preflight_args = ['preflight', '--context', 'alpha', '--base', base, '--head', head,
                      '--branch', 'wiki/folder-requirements', '--packet', str(packet_path), '--result', str(result_path)]
    def run(revision, args, readers=()):
        return subprocess.run(prefix + ['--approved-revision', revision] + args + list(readers),
                              capture_output=True, text=True)
    assert run(base, preflight_args).returncode != 0
    assert run(base, preflight_args, ['--additional-reader', 'alpha']).returncode != 0
    preflight_result = run(base, preflight_args, ['--additional-reader', 'beta'])
    assert preflight_result.returncode == 0, preflight_result.stderr
    assert json.loads(preflight_result.stdout)['state'] == 'independent_review_required'
    git(repo, 'update-ref', 'refs/remotes/origin/main', head)
    requirement_args = ['requirements', '--packet', str(packet_path), '--result', str(result_path),
                        '--output', output, '--proposal-head', head, '--temporal', 'current', '--max-age-days', '30']
    assert run(head, requirement_args).returncode != 0
    assert run(head, requirement_args, ['--additional-reader', 'alpha']).returncode != 0
    requirement_result = run(head, requirement_args, ['--additional-reader', 'beta'])
    assert requirement_result.returncode == 0, requirement_result.stderr
    assert json.loads(requirement_result.stdout)['read_claim'] == 'reported_not_verified'
