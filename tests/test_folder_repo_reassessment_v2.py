"""One selected local independent Git source, two synthetic wiki consumers."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_folder_policy_v2 import project, put, git, commit
from wiki_core.folder_coordination_v2 import FolderCoordinationError, FolderHostBinding
from wiki_core.folder_integration_v2 import preflight_folder_v2
from wiki_core.folder_packet_v2 import build_folder_packet_v2
from wiki_core.folder_policy_v2 import load_folder_policy_v2
from wiki_core.folder_reassessment_host_v2 import prepare_folder_reassessment
from wiki_core.folder_reassessment_v2 import reassess_folder_source_v2, FolderReassessmentError
from wiki_core.repo_read import read_independent_repo


IDENTITY = 'example.test/group/project'


def make_flow(project, *, old_locator=IDENTITY, duplicate_locator=False):
    clone = project / 'a' / 'clone'
    clone.mkdir(parents=True)
    git(clone, 'init', '-q'); git(clone, 'config', 'user.name', 'Synthetic')
    git(clone, 'config', 'user.email', 'synthetic@example.invalid')
    git(clone, 'remote', 'add', 'origin', 'https://example.test/group/project.git')
    put(clone, 'guide.md', '---\nalpha: 1\nbeta: 2\n---\nSynthetic Git source\n')
    git(clone, 'add', '-A'); git(clone, 'commit', '-qm', 'source before')
    old = git(clone, 'rev-parse', 'HEAD')
    receipt_a = read_independent_repo(clone, IDENTITY, old, 'guide.md', field='alpha')
    receipt_b = read_independent_repo(clone, IDENTITY, old, 'guide.md', field='beta')
    put(project, '.gitignore', 'a/clone/\n')
    extra = 'source_locator: example.test/group/other\n' if duplicate_locator else ''
    put(project, 'a/repo-source.md', '---\npage_type: source\nplatform: repo\n' + extra + 'source_locator: '
        + old_locator + '\n---\nSynthetic repository node\n')
    commit(project)
    wiki_branch = git(project, 'branch', '--show-current')
    reports = []
    for number, (target, receipt) in enumerate([('a/first.md', receipt_a), ('a/second.md', receipt_b)], 1):
        base = git(project, 'rev-parse', 'HEAD')
        policy = load_folder_policy_v2(project, base)
        packet = build_folder_packet_v2(project, policy, 'a', 30000, index_path='a/index.md',
            content_revision=base, task_id=target, goal='read selected source', output=target,
            integrator='independent', evidence=[{'path':'a/repo-source.md', 'producer_folder':'a',
            'reason':'repository node', 'use':'interpret', 'classification':'internal'}])
        result = {'schema_version':'wiki.folder-task-result/v2', 'status':'completed',
            'task_id':packet['task_id'], 'context_id':packet['context_id'], 'packet_digest':packet['packet_digest'],
            'observed':[{'path': r['path'], 'kind': r['kind'], 'revision': r['revision'], 'sha256': r['sha256'],
                         'section': r.get('section'), 'field': r.get('field')} for r in packet['inputs']],
            'changes':[{'path':target, 'action':'created'}]}
        reports.append({'target':target, 'section':None, 'field':None, 'packet':packet, 'result':result, 'repo_read':receipt})
        branch = f'wiki/repo-consumer-{number}'
        git(project, 'checkout', '-qb', branch)
        put(project, target, '---\npage_type: claim\ninformation_requirements:\n  - target: a/repo-source.md\n'
            '    fields: ["*"]\n    temporal: current\n    max_age_days: 30\n    consumed_revision: "'
            + base + '"\n---\nIndependent interpretation ' + target + '\n')
        git(project, 'add', '-A'); git(project, 'commit', '-qm', 'synthetic proposal')
        head = git(project, 'rev-parse', 'HEAD')
        check = preflight_folder_v2(project, policy, base=base, head=head, branch=branch, packet=packet, result=result)
        assert check['state'] == 'independent_review_required' and check['merge'] == 'not_performed'
        # Synthetic Git history only: the fixture does not claim a real review.
        git(project, 'checkout', '-q', wiki_branch); git(project, 'merge', '--ff-only', branch)
        git(project, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    if old_locator != IDENTITY or duplicate_locator:
        put(project, 'a/repo-source.md', '---\npage_type: source\nplatform: repo\nsource_locator: '
            + IDENTITY + '\n---\nSynthetic repository node\n')
        commit(project)
    put(clone, 'guide.md', '---\nalpha: 9\nbeta: 2\n---\nSynthetic Git source changed\n')
    git(clone, 'add', '-A'); git(clone, 'commit', '-qm', 'source after')
    selected = {'root':str(clone), 'identity':IDENTITY, 'path':'guide.md', 'revision':git(clone, 'rev-parse', 'HEAD')}
    return clone, reports, selected


def call(project, reports, selected):
    policy = load_folder_policy_v2(project, 'HEAD')
    return reassess_folder_source_v2(project, policy, folder='a', source='a/repo-source.md',
                candidates=['a/first.md', 'a/second.md'], reports=reports, independent_repo=selected)


def host_call(project, binding, reports, selected):
    return prepare_folder_reassessment(project, binding, {'folder':'a',
        'approved_revision':git(project, 'rev-parse', 'refs/remotes/origin/main'),
        'source':'a/repo-source.md', 'candidates':['a/first.md', 'a/second.md'],
        'reports':reports, 'independent_repo':selected})


def test_independent_repo_selection_reassesses_two_consumers_without_writes(project):
    clone, reports, selected = make_flow(project)
    before = [git(project, 'status', '--porcelain'), git(clone, 'status', '--porcelain')]
    pages = [(project / row['target']).read_text() for row in reports]
    out = call(project, reports, selected)
    rows = {row['target']:row for row in out['consumers']}
    assert rows['a/first.md']['state'] == 'review_pending'
    assert rows['a/first.md']['repository_impact']['source_state'] == 'changed'
    assert rows['a/second.md']['state'] == 'verification_pending'
    assert rows['a/second.md']['repository_impact']['source_state'] == 'unchanged'
    assert rows['a/first.md']['repository_impact']['verification'] == 'caller_reported_not_independently_verified'
    assert out['repository']['identity_evidence'] == 'configured_origin_not_remote_authentication'
    assert selected['root'] not in json.dumps(out)
    assert [(project / row['target']).read_text() for row in reports] == pages
    assert [git(project, 'status', '--porcelain'), git(clone, 'status', '--porcelain')] == before


def test_host_bound_flow_uses_selected_repo_without_granting_access(project):
    clone, reports, selected = make_flow(project)
    binding = FolderHostBinding(project, ('a',), (('a', clone, IDENTITY, 'guide.md'),))
    out = host_call(project, binding, reports, selected)
    rows = {row['target']:row for row in out['reassessment']['consumers']}
    assert rows['a/first.md']['state'] == 'review_pending'
    assert rows['a/second.md']['state'] == 'verification_pending'
    assert rows['a/first.md']['repository_impact']['selected_revision'] == selected['revision']
    assert 'current_revision' not in rows['a/first.md']['repository_impact']
    assert out['enforcement_claim'] == 'none'


@pytest.mark.parametrize('binding_mode', ['empty', 'wrong_root', 'wrong_identity', 'wrong_folder', 'wrong_path'])
def test_host_requires_repo_allowlist_before_repo_read(project, tmp_path, monkeypatch, binding_mode):
    import wiki_core.folder_reassessment_v2 as module
    clone, reports, selected = make_flow(project)
    repo_bindings = {'empty': (), 'wrong_root': (('a', tmp_path / 'other', IDENTITY, 'guide.md'),),
                     'wrong_identity': (('a', clone, 'example.test/group/other', 'guide.md'),),
                     'wrong_folder': (('a/aux/b', clone, IDENTITY, 'guide.md'),),
                     'wrong_path': (('a', clone, IDENTITY, 'other.md'),)}[binding_mode]
    binding = FolderHostBinding(project, ('a', 'a/aux/b'), repo_bindings)
    def never(*args, **kwargs):
        pytest.fail('independent repository read without host allowlist')
    monkeypatch.setattr(module, 'read_independent_repo', never)
    with pytest.raises(FolderCoordinationError, match='independent repository unavailable'):
        host_call(project, binding, reports, selected)


@pytest.mark.parametrize('root,identity', [
    ('relative/repo', IDENTITY),
    ('/tmp/synthetic-repo', 'example.test/group/project?token=synthetic'),
])
def test_host_binding_rejects_invalid_repo_allowlist(project, root, identity):
    with pytest.raises(ValueError, match='invalid independent repository binding'):
        FolderHostBinding(project, ('a',), (('a', Path(root), identity, 'guide.md'),))


def test_host_denies_wiki_node_before_repo_read_even_with_repo_binding(project, monkeypatch):
    import yaml
    import wiki_core.folder_reassessment_v2 as module
    clone, reports, selected = make_flow(project)
    config = project / 'wiki-context-controls.yaml'; controls = yaml.safe_load(config.read_text())
    controls['controls']['a']['policy']['deny'] = {'read':['a/repo-source.md']}
    config.write_text(yaml.safe_dump(controls)); commit(project)
    binding = FolderHostBinding(project, ('a',), (('a', clone, IDENTITY, 'guide.md'),))
    def never(*args, **kwargs):
        pytest.fail('repo opened before wiki node authorization')
    monkeypatch.setattr(module, 'read_independent_repo', never)
    with pytest.raises(FolderCoordinationError):
        host_call(project, binding, reports, selected)


def test_wrong_identity_and_reported_path_are_rejected(project):
    _clone, reports, selected = make_flow(project)
    with pytest.raises(FolderReassessmentError):
        call(project, reports, {**selected, 'identity':'example.test/group/wrong'})
    reports[0]['repo_read']['path'] = 'other.md'
    with pytest.raises(FolderReassessmentError):
        call(project, reports, selected)


@pytest.mark.parametrize('invalid', ['field', 'blob'])
def test_all_receipt_selectors_are_validated_before_any_repo_read(project, monkeypatch, invalid):
    import wiki_core.folder_reassessment_v2 as module
    _clone, reports, selected = make_flow(project)
    reports[1]['repo_read'][invalid] = 7 if invalid == 'field' else 'invalid-blob'
    def never(*args, **kwargs):
        pytest.fail('repository opened before validating every report')
    monkeypatch.setattr(module, 'read_independent_repo', never)
    with pytest.raises(FolderReassessmentError):
        call(project, reports, selected)


@pytest.mark.parametrize('old_locator,duplicate', [('example.test/group/other', False), (IDENTITY, True)])
def test_historical_node_identity_must_be_unambiguous_before_repo_reads(project, monkeypatch, old_locator, duplicate):
    import wiki_core.folder_reassessment_v2 as module
    _clone, reports, selected = make_flow(project, old_locator=old_locator, duplicate_locator=duplicate)
    def never(*args, **kwargs):
        pytest.fail('repository opened before validating historical node identity')
    monkeypatch.setattr(module, 'read_independent_repo', never)
    with pytest.raises(FolderReassessmentError, match='repository source node unavailable'):
        call(project, reports, selected)


def test_missing_selected_field_blocks_only_that_consumer(project):
    clone, reports, selected = make_flow(project)
    put(clone, 'guide.md', '---\nbeta: 2\n---\nSynthetic source\n')
    git(clone, 'add', '-A'); git(clone, 'commit', '-qm', 'remove alpha')
    selected['revision'] = git(clone, 'rev-parse', 'HEAD')
    rows = {row['target']:row for row in call(project, reports, selected)['consumers']}
    assert rows['a/first.md']['state'] == 'blocked_repository_selection_unavailable'
    assert rows['a/second.md']['state'] == 'verification_pending'


def test_denied_wiki_node_blocks_before_independent_git_reads(project, monkeypatch):
    import yaml
    import wiki_core.folder_reassessment_v2 as module
    _clone, reports, selected = make_flow(project)
    config = project / 'wiki-context-controls.yaml'; controls = yaml.safe_load(config.read_text())
    controls['controls']['a']['policy']['deny'] = {'read':['a/repo-source.md']}
    config.write_text(yaml.safe_dump(controls)); commit(project)
    def never(*args, **kwargs):
        pytest.fail('independent repository was read before source authorization')
    monkeypatch.setattr(module, 'read_independent_repo', never)
    with pytest.raises(ValueError):
        call(project, reports, selected)


def test_cli_uses_existing_source_reassessment_flow(project, tmp_path):
    _clone, reports, selected = make_flow(project)
    report_file = tmp_path / 'reports.json'; report_file.write_text(json.dumps(reports))
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_folder_reassessment_v2.py'
    proc = subprocess.run([sys.executable, str(script), '--repo', str(project), '--approved-revision', 'HEAD',
            '--folder', 'a', '--source', 'a/repo-source.md', '--candidate', 'a/first.md', '--candidate', 'a/second.md',
            '--reports', str(report_file), '--independent-root', selected['root'], '--independent-identity', IDENTITY,
            '--independent-revision', selected['revision'], '--independent-path', 'guide.md'], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert {r['state'] for r in out['consumers']} == {'review_pending', 'verification_pending'}
    assert selected['root'] not in proc.stdout and 'Synthetic Git source' not in proc.stdout
