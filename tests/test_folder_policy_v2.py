"""Synthetic opt-in v2 policy preview; no v1 authorization or receipts."""
import subprocess

import pytest
import yaml

from wiki_core.context_packet import build_packet
from wiki_core.context_policy import PolicyError
from wiki_core.folder_policy_v2 import FORMAT, folder_id, load_folder_policy_v2


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


def put(root, path, text):
    p = root / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding='utf-8')


def commit(root):
    git(root, 'add', '-A'); git(root, 'commit', '-qm', 'synthetic')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')


@pytest.fixture
def project(tmp_path):
    git(tmp_path, 'init', '-q'); git(tmp_path, 'config', 'user.name', 'Synthetic')
    git(tmp_path, 'config', 'user.email', 'synthetic@example.invalid')
    put(tmp_path, 'AGENTS.md', 'Project instructions\n')
    put(tmp_path, 'README.md', 'Project index\n')
    put(tmp_path, 'a/AGENTS.md', 'Context a\n')
    put(tmp_path, 'a/index.md', 'Context a index\n')
    put(tmp_path, 'a/aux/AGENTS.md', 'Auxiliary instruction\n')
    put(tmp_path, 'a/aux/b/AGENTS.md', 'Regular child\n')
    put(tmp_path, 'a/aux/b/AGENTS.override.md', 'Override child\n')
    put(tmp_path, 'a/aux/b/index.md', 'Child index\n')
    controls = {
        '.': {'policy': {'read': ['self'], 'write': ['self'], 'capabilities': [], 'deny': {}, 'publication': []}, 'imports': [], 'exports': []},
        'a': {'policy': {'read': ['self'], 'write': ['self']}, 'imports': [], 'exports': []},
        'a/aux/b': {'policy': {'read': ['self'], 'write': ['self']}, 'imports': [], 'exports': []},
    }
    put(tmp_path, 'wiki-context-controls.yaml', yaml.safe_dump({'schema_version': FORMAT, 'controls': controls}))
    commit(tmp_path)
    return tmp_path


def test_folder_derived_lineage_without_manifest_or_repeated_parents(project):
    p = load_folder_policy_v2(project, 'HEAD')
    child = folder_id('a/aux/b')
    assert [c['root'] for c in p.lineage(child)] == ['.', 'a', 'a/aux/b']
    assert p.contexts[child]['instructions'] == ['a/aux/b/AGENTS.override.md']
    assert p.owner_of('a/aux/b/report.md') == child
    assert p.effective[child]['read'] == ['a/aux/b']
    assert p.folder_ids['a/aux/b'] != 'a/aux/b'
    assert p.unindexed_instruction_folders == ['a/aux']
    with pytest.raises(PolicyError, match='ownership unavailable'):
        p.owner_of('a/aux/notes.md')
    assert p.format_version == FORMAT and p._binding is not None
    with pytest.raises(PolicyError, match='v1 receipts require explicit migration'):
        build_packet(project, p, child, 'HEAD', [], 5000, task_id='x', goal='x', output='x', integrator='x')


def test_missing_controls_or_unapproved_revision_fails_closed(project):
    config = project / 'wiki-context-controls.yaml'
    data = yaml.safe_load(config.read_text())
    del data['controls']['a/aux/b']
    config.write_text(yaml.safe_dump(data)); commit(project)
    p = load_folder_policy_v2(project, 'HEAD')
    assert p.effective[folder_id('a/aux/b')]['read'] == []
    assert p.effective[folder_id('a/aux/b')]['write'] == []
    assert not p.permits(folder_id('a/aux/b'), 'read', 'a/aux/b/file.md')
    git(project, 'update-ref', 'refs/remotes/origin/main', 'HEAD^')
    with pytest.raises(PolicyError, match='not current trusted'):
        load_folder_policy_v2(project, 'HEAD')


def test_child_cannot_expand_parent_and_folder_move_changes_id(project):
    config = project / 'wiki-context-controls.yaml'
    data = yaml.safe_load(config.read_text())
    data['controls']['a']['policy']['read'] = ['finance']
    # Root permits '.' so the first child can have finance, but child root must
    # contain its descendants; use the nested child to test inherited ceiling.
    data['controls']['a/aux/b']['policy']['read'] = ['a/other']
    config.write_text(yaml.safe_dump(data)); commit(project)
    with pytest.raises(PolicyError, match='child widens read'):
        load_folder_policy_v2(project, 'HEAD')
    assert folder_id('a/aux/b') != folder_id('a/moved/b')


def test_bilateral_connection_uses_folder_paths_without_a_second_hierarchy(project):
    config = project / 'wiki-context-controls.yaml'
    data = yaml.safe_load(config.read_text())
    source = 'a/aux/b/source.md'
    data['controls']['a']['policy']['read'] = ['self']
    grant = {'from_context': 'a/aux/b', 'to_context': 'a', 'selector': source,
             'use': 'interpret', 'classification': 'synthetic', 'expires': '2099-01-01'}
    data['controls']['a']['imports'] = [grant]
    config.write_text(yaml.safe_dump(data)); commit(project)
    p = load_folder_policy_v2(project, 'HEAD')
    assert p.contexts[folder_id('a')]['imports'] and not p.contexts[folder_id('a/aux/b')]['exports']
    data['controls']['a/aux/b']['exports'] = [grant]
    config.write_text(yaml.safe_dump(data)); commit(project)
    p = load_folder_policy_v2(project, 'HEAD')
    assert p.contexts[folder_id('a')]['imports'] == p.contexts[folder_id('a/aux/b')]['exports']
    assert p.connection(folder_id('a/aux/b'), folder_id('a'), source, 'interpret', 'synthetic') == 'approved'


def test_v2_packet_selects_physical_instructions_and_only_selected_index(project):
    from wiki_core.folder_packet_v2 import build_folder_packet_v2
    p = load_folder_policy_v2(project, 'HEAD')
    packet = build_folder_packet_v2(project, p, 'a/aux/b', 10000, index_path='a/aux/b/index.md', content_revision='HEAD', task_id='x', goal='x', output='x', integrator='x')
    assert packet['schema_version'] == 'wiki.folder-task-context/v2'
    assert [row['path'] for row in packet['inputs']] == ['AGENTS.md', 'a/AGENTS.md', 'a/aux/AGENTS.md',
                                                           'a/aux/b/AGENTS.override.md', 'a/aux/b/index.md']
    assert all(row['revision'] == p.policy_revision for row in packet['inputs'])
    assert all(len(row['sha256']) == 64 for row in packet['inputs'])
    assert packet['bytes_used'] <= packet['max_bytes']
    with pytest.raises(PolicyError, match='byte budget'):
        build_folder_packet_v2(project, p, 'a/aux/b', 1, index_path='a/aux/b/index.md', content_revision='HEAD', task_id='x', goal='x', output='x', integrator='x')
    with pytest.raises(PolicyError, match='not a context'):
        build_folder_packet_v2(project, p, 'a/aux', 10000, index_path='a/aux/index.md', content_revision='HEAD', task_id='x', goal='x', output='x', integrator='x')


def test_v2_packet_denies_absent_controls_and_fails_when_approval_moves(project):
    from wiki_core.folder_packet_v2 import build_folder_packet_v2
    config = project / 'wiki-context-controls.yaml'
    data = yaml.safe_load(config.read_text()); del data['controls']['a/aux/b']
    config.write_text(yaml.safe_dump(data)); commit(project)
    p = load_folder_policy_v2(project, 'HEAD')
    with pytest.raises(PolicyError, match='index is not authorized'):
        build_folder_packet_v2(project, p, 'a/aux/b', 10000, index_path='a/aux/b/index.md', content_revision='HEAD', task_id='x', goal='x', output='x', integrator='x')
    git(project, 'update-ref', 'refs/remotes/origin/main', 'HEAD^')
    with pytest.raises(PolicyError, match='not current trusted'):
        build_folder_packet_v2(project, p, 'a/aux/b', 10000, index_path='a/aux/b/index.md', content_revision='HEAD', task_id='x', goal='x', output='x', integrator='x')


def test_missing_index_is_not_a_silent_new_owner(project):
    config = project / 'wiki-context-controls.yaml'
    data = yaml.safe_load(config.read_text()); del data['controls']['a/aux/b']
    config.write_text(yaml.safe_dump(data)); (project / 'a/aux/b/index.md').unlink(); commit(project)
    p = load_folder_policy_v2(project, 'HEAD')
    assert 'a/aux/b' not in p.folder_ids
    assert 'a/aux/b' in p.unindexed_instruction_folders
    with pytest.raises(PolicyError, match='ownership unavailable'):
        p.owner_of('a/aux/b/report.md')
    from wiki_core.folder_packet_v2 import build_folder_packet_v2
    with pytest.raises(PolicyError, match='not a context'):
        build_folder_packet_v2(project, p, 'a/aux/b', 10000, index_path='a/aux/b/index.md', content_revision='HEAD', task_id='x', goal='x', output='x', integrator='x')


def test_v1_and_v2_policies_cannot_reuse_protected_receipts(project):
    from wiki_core.context_policy import historical_policy
    from wiki_core.context_selection import select_query
    from wiki_core.repository_reader import RepositoryReader
    p = load_folder_policy_v2(project, 'HEAD')
    with pytest.raises(PolicyError, match='v1 receipts require explicit migration'):
        historical_policy(p, p.policy_revision)
    with pytest.raises(PolicyError, match='v1 receipts require explicit migration'):
        select_query(p, folder_id('a'), RepositoryReader(project, 'HEAD'), {})


def test_v2_explicit_source_selection_requires_bilateral_connection(project):
    from wiki_core.folder_packet_v2 import build_folder_packet_v2
    source = 'a/aux/b/source.md'
    put(project, source, '---\namount: 12\nother: untouched\n---\nSource body\n')
    config = project / 'wiki-context-controls.yaml'
    data = yaml.safe_load(config.read_text())
    grant = {'from_context': 'a/aux/b', 'to_context': 'a', 'selector': source, 'field': 'amount',
             'use': 'interpret', 'classification': 'synthetic', 'expires': '2099-01-01'}
    data['controls']['a']['imports'] = [grant]
    config.write_text(yaml.safe_dump(data)); commit(project)
    evidence = [{'path': source, 'producer_folder': 'a/aux/b', 'reason': 'Review value', 'use': 'interpret',
                 'classification': 'synthetic', 'field': 'amount'}]
    p = load_folder_policy_v2(project, 'HEAD')
    with pytest.raises(PolicyError, match='connection unavailable'):
        build_folder_packet_v2(project, p, 'a', 20000, index_path='a/index.md', content_revision='HEAD', task_id='x', goal='x', output='x', integrator='x', evidence=evidence)
    data['controls']['a/aux/b']['exports'] = [grant]
    config.write_text(yaml.safe_dump(data)); commit(project)
    p = load_folder_policy_v2(project, 'HEAD')
    result = build_folder_packet_v2(project, p, 'a', 20000, index_path='a/index.md', content_revision='HEAD', task_id='x', goal='x', output='x', integrator='x', evidence=evidence)
    selected = result['inputs'][-1]
    assert selected['text'] == '12' and selected['field'] == 'amount'
    assert selected['revision'] == p.policy_revision and len(selected['document_sha256']) == 64
    wrong = [{**evidence[0], 'field': 'other'}]
    with pytest.raises(PolicyError, match='connection unavailable'):
        build_folder_packet_v2(project, p, 'a', 20000, index_path='a/index.md', content_revision='HEAD', task_id='x', goal='x', output='x', integrator='x', evidence=wrong)


def test_real_v2_cli_reads_approved_git_and_selects_local_source(project, tmp_path):
    import json
    import sys
    from pathlib import Path
    source = 'a/own.md'
    put(project, source, '---\namount: 5\n---\nOwn source\n')
    commit(project)
    request = tmp_path.parent / (tmp_path.name + '-v2-evidence.json')
    request.write_text(json.dumps({'max_bytes': 20000, 'task_id': 'synthetic', 'goal': 'read source',
                                  'output': 'a/proposal.md', 'integrator': 'reviewer',
                                  'evidence': [{'path': source, 'producer_folder': 'a', 'reason': 'read',
                                                'use': 'interpret', 'classification': 'synthetic', 'field': 'amount'}]}))
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_context.py'
    run = subprocess.run([sys.executable, str(script), '--repo', str(project), '--approved-revision', 'HEAD',
                          'pack', 'a', '--content-revision', 'HEAD', '--index', 'a/index.md', '--request', str(request)],
                         text=True, capture_output=True, check=True)
    packet = json.loads(run.stdout)
    assert packet['inputs'][-1]['text'] == '5'
    assert packet['inputs'][-1]['revision'] == git(project, 'rev-parse', 'HEAD')
    assert packet['schema_version'] == 'wiki.folder-task-context/v2'


def proposal_v2(project):
    from wiki_core.folder_packet_v2 import build_folder_packet_v2
    put(project, 'a/source.md', '---\namount: 5\n---\nUnselected body\n')
    commit(project)
    base = git(project, 'rev-parse', 'HEAD')
    p = load_folder_policy_v2(project, 'HEAD')
    evidence = [{'path': 'a/source.md', 'producer_folder': 'a', 'reason': 'source', 'use': 'interpret',
                 'classification': 'synthetic', 'field': 'amount'}]
    packet = build_folder_packet_v2(project, p, 'a', 20000, index_path='a/index.md', content_revision='HEAD', task_id='task', goal='review source',
                                    output='a/report.md', integrator='independent', evidence=evidence)
    git(project, 'checkout', '-qb', 'wiki/folder-task')
    put(project, 'a/report.md', '---\npage_type: claim\n---\nInterpretation based on selected value\n')
    git(project, 'add', '-A'); git(project, 'commit', '-qm', 'proposal')
    head = git(project, 'rev-parse', 'HEAD')
    observed = [{'path': row['path'], 'kind': row['kind'], 'revision': row['revision'], 'sha256': row['sha256'],
                 'section': row.get('section'), 'field': row.get('field')} for row in packet['inputs']]
    result = {'schema_version': 'wiki.folder-task-result/v2', 'status': 'completed', 'task_id': packet['task_id'],
              'context_id': packet['context_id'], 'packet_digest': packet['packet_digest'], 'observed': observed,
              'changes': [{'path': 'a/report.md', 'action': 'created'}]}
    return p, base, head, packet, result


def test_v2_preflight_reproduces_packet_and_requires_independent_review(project):
    from wiki_core.folder_integration_v2 import preflight_folder_v2, FolderIntegrationError
    p, base, head, packet, result = proposal_v2(project)
    args = {'base': base, 'head': head, 'branch': 'wiki/folder-task', 'packet': packet, 'result': result}
    check = preflight_folder_v2(project, p, **args)
    assert check['state'] == 'independent_review_required' and check['merge'] == 'not_performed'
    bad = dict(result); bad['observed'] = bad['observed'][:-1]
    with pytest.raises(FolderIntegrationError, match='exact reported read'):
        preflight_folder_v2(project, p, **{**args, 'result': bad})
    bad = dict(result); bad['schema_version'] = 'wiki.task-result/v1'
    with pytest.raises(FolderIntegrationError, match='v1 results need explicit migration'):
        preflight_folder_v2(project, p, **{**args, 'result': bad})
    bad_packet = dict(packet); bad_packet['schema_version'] = 'wiki.task-context/v1'
    with pytest.raises(FolderIntegrationError, match='v1 packets need explicit migration'):
        preflight_folder_v2(project, p, **{**args, 'packet': bad_packet})


def test_v2_preflight_requires_declared_output_even_without_host(project):
    from wiki_core.folder_integration_v2 import preflight_folder_v2, FolderIntegrationError
    p, base, _, packet, result = proposal_v2(project)
    git(project, 'rm', '-q', 'a/report.md')
    put(project, 'a/other.md', '---\npage_type: claim\n---\nSynthetic other claim\n')
    git(project, 'add', '-A'); git(project, 'commit', '-qm', 'different output')
    result['changes'] = [{'path':'a/other.md', 'action':'created'}]
    with pytest.raises(FolderIntegrationError, match='declared output change unavailable'):
        preflight_folder_v2(project, p, base=base, head=git(project, 'rev-parse', 'HEAD'),
                            branch='wiki/folder-task', packet=packet, result=result)


def test_v2_preflight_allows_additional_authorized_changes_with_output(project):
    from wiki_core.folder_integration_v2 import preflight_folder_v2
    p, base, _, packet, result = proposal_v2(project)
    put(project, 'a/other.md', '---\npage_type: claim\n---\nSynthetic other claim\n')
    git(project, 'add', '-A'); git(project, 'commit', '-qm', 'additional claim')
    result['changes'].append({'path':'a/other.md', 'action':'created'})
    out = preflight_folder_v2(project, p, base=base, head=git(project, 'rev-parse', 'HEAD'),
                              branch='wiki/folder-task', packet=packet, result=result)
    assert out['state']=='independent_review_required' and len(out['changes'])==2


@pytest.mark.parametrize('path', ['a/new/AGENTS.md', 'a/new/AGENTS.override.md', 'a/new/index.md', 'wiki-context-controls.yaml'])
def test_v2_preflight_rejects_boundary_changes(project, path):
    from wiki_core.folder_integration_v2 import preflight_folder_v2, FolderIntegrationError
    p, base, _, packet, result = proposal_v2(project)
    put(project, path, 'Boundary change\n'); git(project, 'add', '-A'); git(project, 'commit', '-qm', 'boundary')
    head = git(project, 'rev-parse', 'HEAD')
    with pytest.raises(FolderIntegrationError, match='boundary or instructions'):
        preflight_folder_v2(project, p, base=base, head=head, branch='wiki/folder-task', packet=packet, result=result)


def test_v2_preflight_blocks_changed_consumed_slice(project):
    from wiki_core.folder_integration_v2 import preflight_folder_v2, FolderIntegrationError
    p, base, _, packet, result = proposal_v2(project)
    put(project, 'a/source.md', '---\namount: 9\n---\nUnselected body\n')
    git(project, 'add', '-A'); git(project, 'commit', '-qm', 'changed source')
    head = git(project, 'rev-parse', 'HEAD')
    result['changes'].append({'path': 'a/source.md', 'action': 'modified'})
    with pytest.raises(FolderIntegrationError, match='existing output needs a reported whole prior read'):
        preflight_folder_v2(project, p, base=base, head=head, branch='wiki/folder-task', packet=packet, result=result)


def test_v2_historical_content_is_explicit_and_current_denial_precedes_read(project, monkeypatch):
    from wiki_core.folder_packet_v2 import build_folder_packet_v2
    from wiki_core.repository_reader import RepositoryReader
    put(project, 'a/source.md', '---\namount: 5\n---\nOld\n'); commit(project)
    old = git(project, 'rev-parse', 'HEAD')
    put(project, 'a/source.md', '---\namount: 9\n---\nNew\n'); commit(project)
    p = load_folder_policy_v2(project, 'HEAD')
    evidence = [{'path': 'a/source.md', 'producer_folder': 'a', 'reason': 'compare', 'use': 'interpret',
                 'classification': 'synthetic', 'field': 'amount'}]
    result = build_folder_packet_v2(project, p, 'a', 20000, index_path='a/index.md', content_revision=old, task_id='x', goal='x',
                                    output='x', integrator='x', evidence=evidence)
    assert result['inputs'][-1]['text'] == '5' and result['inputs'][-1]['revision'] == old
    assert result['policy_revision'] != result['content_revision']
    config = project / 'wiki-context-controls.yaml'; data = yaml.safe_load(config.read_text())
    data['controls']['a']['policy']['deny'] = {'read': ['a/source.md']}
    config.write_text(yaml.safe_dump(data)); commit(project)
    p = load_folder_policy_v2(project, 'HEAD')
    original = RepositoryReader.read
    def checked(self, ref, *args, **kwargs):
        if ref == 'a/source.md': raise AssertionError('denied historical body was read')
        return original(self, ref, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', checked)
    with pytest.raises(PolicyError, match='connection unavailable'):
        build_folder_packet_v2(project, p, 'a', 20000, index_path='a/index.md', content_revision=old, task_id='x', goal='x',
                               output='x', integrator='x', evidence=evidence)


def test_v2_selective_impact_preserves_independent_interpretation(project):
    from wiki_core.folder_impact_v2 import assess_folder_source_v2
    _, base, _, packet, result = proposal_v2(project)
    git(project, 'checkout', '-q', '-')
    git(project, 'merge', '--ff-only', 'wiki/folder-task')
    git(project, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    target = project / 'a/report.md'; interpretation = target.read_text()
    put(project, 'a/source.md', '---\namount: 5\n---\nChanged unselected body\n'); commit(project)
    p = load_folder_policy_v2(project, 'HEAD')
    out = assess_folder_source_v2(project, p, packet=packet, result=result, target='a/report.md', source='a/source.md', field='amount')
    assert out['state'] == 'verification_pending' and out['candidates'][0]['source_state'] == 'unchanged'
    put(project, 'a/source.md', '---\namount: 9\n---\nChanged unselected body\n'); commit(project)
    p = load_folder_policy_v2(project, 'HEAD')
    out = assess_folder_source_v2(project, p, packet=packet, result=result, target='a/report.md', source='a/source.md', field='amount')
    assert out['state'] == 'review_pending' and out['candidates'][0]['consumed_revision'] == base
    assert out['candidates'][0]['interpretation'] == 'independent'
    assert target.read_text() == interpretation


def test_v2_impact_checks_current_authority_before_historical_source(project, monkeypatch):
    from wiki_core.folder_impact_v2 import assess_folder_source_v2, FolderImpactError
    from wiki_core.repository_reader import RepositoryReader
    _, _, _, packet, result = proposal_v2(project)
    git(project, 'checkout', '-q', '-'); git(project, 'merge', '--ff-only', 'wiki/folder-task')
    git(project, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    config = project / 'wiki-context-controls.yaml'; data = yaml.safe_load(config.read_text())
    data['controls']['a']['policy']['deny'] = {'read': ['a/source.md']}
    config.write_text(yaml.safe_dump(data)); commit(project)
    p = load_folder_policy_v2(project, 'HEAD')
    original = RepositoryReader.read
    def checked(self, ref, *args, **kwargs):
        if ref == 'a/source.md': raise AssertionError('denied historical source was read')
        return original(self, ref, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', checked)
    with pytest.raises(FolderImpactError, match='current input authority unavailable'):
        assess_folder_source_v2(project, p, packet=packet, result=result, target='a/report.md', source='a/source.md', field='amount')


def test_v2_preflight_refuses_unmigrated_information_requirements(project):
    from wiki_core.folder_integration_v2 import preflight_folder_v2, FolderIntegrationError
    p, base, _, packet, result = proposal_v2(project)
    put(project, 'a/report.md', '---\ninformation_requirements:\n  - target: a/source.md\n---\nInterpretation\n')
    git(project, 'add', '-A'); git(project, 'commit', '-qm', 'legacy requirements')
    with pytest.raises(FolderIntegrationError, match='requirement migration'):
        preflight_folder_v2(project, p, base=base, head=git(project, 'rev-parse', 'HEAD'),
                            branch='wiki/folder-task', packet=packet, result=result)
