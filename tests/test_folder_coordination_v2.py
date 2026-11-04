"""Host-bound folder coordination, exercised only with synthetic repositories."""
from copy import deepcopy

import pytest
import yaml

from tests.test_folder_policy_v2 import project, put, git, commit
from wiki_core.folder_coordination_v2 import (FolderCoordinationError, FolderHostBinding,
                                             prepare_folder_packet, prepare_folder_preflight)
from wiki_core.repository_reader import RepositoryReader


def request(repo, *, folder='a', content=None, evidence=None):
    approved = git(repo, 'rev-parse', 'refs/remotes/origin/main')
    return {'folder': folder, 'approved_revision': approved, 'content_revision': content or approved,
            'task': {'index_path': folder + '/index.md', 'task_id': 'synthetic', 'goal': 'review',
                     'output': folder + '/report.md', 'integrator': 'independent', 'max_bytes': 20000,
                     'evidence': evidence or []}}


def selector(path):
    return {'path': path, 'producer_folder': 'a', 'reason': 'synthetic',
            'use': 'interpret', 'classification': 'synthetic'}


def test_host_binding_composes_lineage_and_preflights_exact_v2_result(project):
    put(project, 'a/source.md', 'Synthetic source\n'); commit(project)
    binding = FolderHostBinding(project, ('a',))
    task = request(project, evidence=[selector('a/source.md')])
    packet = prepare_folder_packet(project, binding, task)['packet']
    assert [item['path'] for item in packet['inputs']] == ['AGENTS.md', 'a/AGENTS.md', 'a/index.md', 'a/source.md']
    assert packet['policy_revision'] == task['approved_revision'] == packet['content_revision']
    git(project, 'checkout', '-qb', 'wiki/host-folder')
    put(project, 'a/report.md', '---\npage_type: claim\n---\nInterpretation\n')
    git(project, 'add', '-A'); git(project, 'commit', '-qm', 'synthetic proposal')
    head = git(project, 'rev-parse', 'HEAD')
    observed = [{'path': r['path'], 'kind': r['kind'], 'revision': r['revision'], 'sha256': r['sha256'],
                 'section': r.get('section'), 'field': r.get('field')} for r in packet['inputs']]
    result = {'schema_version': 'wiki.folder-task-result/v2', 'status': 'completed',
              'task_id': packet['task_id'], 'context_id': packet['context_id'],
              'packet_digest': packet['packet_digest'], 'observed': observed,
              'changes': [{'path': 'a/report.md', 'action': 'created'}]}
    data = {'folder': 'a', 'approved_revision': task['approved_revision'], 'base': task['approved_revision'],
            'head': head, 'branch': 'wiki/host-folder', 'packet': packet, 'result': result}
    out = prepare_folder_preflight(project, binding, data)
    assert out['enforcement_claim'] == 'none'
    assert out['preflight']['state'] == 'independent_review_required'
    assert out['preflight']['merge'] == 'not_performed'
    bad = deepcopy(data); bad['result']['schema_version'] = 'wiki.task-result/v1'
    with pytest.raises(FolderCoordinationError):
        prepare_folder_preflight(project, binding, bad)
    bad = deepcopy(data); bad['packet']['schema_version'] = 'wiki.task-context/v1'
    with pytest.raises(FolderCoordinationError):
        prepare_folder_preflight(project, binding, bad)


def test_missing_binding_wrong_root_and_nested_folder_fail_before_policy_read(project, tmp_path, monkeypatch):
    import wiki_core.folder_coordination_v2 as module
    task = request(project)
    def never(*args, **kwargs):
        pytest.fail('policy opened before host binding authorization')
    monkeypatch.setattr(module, 'load_folder_policy_v2', never)
    with pytest.raises(FolderCoordinationError, match='host binding unavailable'):
        prepare_folder_packet(project, None, task)
    binding = FolderHostBinding(project, ('a',))
    with pytest.raises(FolderCoordinationError, match='repository unavailable'):
        prepare_folder_packet(tmp_path / 'other', binding, task)
    task['folder'] = 'a/aux/b'
    with pytest.raises(FolderCoordinationError, match='folder unavailable'):
        prepare_folder_packet(project, binding, task)


def test_approved_ref_and_nonancestor_fail_before_source_bodies(project, monkeypatch):
    put(project, 'a/source.md', 'Synthetic source\n'); commit(project)
    binding = FolderHostBinding(project, ('a',)); task = request(project, evidence=[selector('a/source.md')])
    tree = git(project, 'rev-parse', 'HEAD^{tree}')
    unrelated = git(project, 'commit-tree', tree, '-m', 'unrelated synthetic history')
    original = RepositoryReader.read
    def spy(self, path, *args, **kwargs):
        if path != 'wiki-context-controls.yaml':
            pytest.fail('body opened before ancestry check')
        return original(self, path, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    with pytest.raises(FolderCoordinationError):
        prepare_folder_packet(project, binding, {**task, 'content_revision': unrelated})
    with pytest.raises(FolderCoordinationError):
        prepare_folder_packet(project, binding, {**task, 'approved_revision': unrelated})


def test_every_current_evidence_is_authorized_before_any_source_body(project, monkeypatch):
    for name in ('first', 'second'):
        put(project, f'a/{name}.md', f'Synthetic {name}\n')
    config = project / 'wiki-context-controls.yaml'; data = yaml.safe_load(config.read_text())
    data['controls']['a']['policy']['deny'] = {'read': ['a/second.md']}
    config.write_text(yaml.safe_dump(data)); commit(project)
    task = request(project, evidence=[selector('a/first.md'), selector('a/second.md')])
    original = RepositoryReader.read
    def spy(self, path, *args, **kwargs):
        if path in ('a/first.md', 'a/second.md'):
            pytest.fail('source body opened before all current authority checks')
        return original(self, path, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    with pytest.raises(FolderCoordinationError, match='evidence unavailable'):
        prepare_folder_packet(project, FolderHostBinding(project, ('a',)), task)


def test_every_historical_evidence_is_authorized_before_any_source_body(project, monkeypatch):
    for name in ('first', 'second'):
        put(project, f'a/{name}.md', f'Synthetic {name}\n')
    config = project / 'wiki-context-controls.yaml'; data = yaml.safe_load(config.read_text())
    data['controls']['a']['policy']['deny'] = {'read': ['a/second.md']}
    config.write_text(yaml.safe_dump(data)); commit(project)
    old = git(project, 'rev-parse', 'HEAD')
    del data['controls']['a']['policy']['deny']
    config.write_text(yaml.safe_dump(data)); commit(project)
    task = request(project, content=old, evidence=[selector('a/first.md'), selector('a/second.md')])
    original = RepositoryReader.read
    def spy(self, path, *args, **kwargs):
        if path in ('a/first.md', 'a/second.md'):
            pytest.fail('source body opened before all historical authority checks')
        return original(self, path, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    with pytest.raises(FolderCoordinationError, match='historical authority unavailable'):
        prepare_folder_packet(project, FolderHostBinding(project, ('a',)), task)


def test_unrelated_owner_and_unbound_output_are_not_opened(project, monkeypatch):
    put(project, 'a/aux/b/private.md', 'Synthetic protected body\n'); commit(project)
    task = request(project, evidence=[{'path': 'a/aux/b/private.md', 'producer_folder': 'a/aux/b',
                    'reason': 'synthetic', 'use': 'interpret', 'classification': 'synthetic'}])
    original = RepositoryReader.read
    def spy(self, path, *args, **kwargs):
        if path == 'a/aux/b/private.md': pytest.fail('unapproved sibling body opened')
        return original(self, path, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    with pytest.raises(FolderCoordinationError):
        prepare_folder_packet(project, FolderHostBinding(project, ('a',)), task)
    task['task']['evidence'] = []
    task['task']['output'] = 'a/aux/b/report.md'
    with pytest.raises(FolderCoordinationError, match='output unavailable'):
        prepare_folder_packet(project, FolderHostBinding(project, ('a',)), task)


def test_moved_approved_ref_never_returns_a_packet(project, monkeypatch):
    put(project, 'a/source.md', 'Synthetic source\n'); commit(project)
    task = request(project, evidence=[selector('a/source.md')])
    tree = git(project, 'rev-parse', 'HEAD^{tree}')
    later = git(project, 'commit-tree', tree, '-p', 'HEAD', '-m', 'ref moved')
    original = RepositoryReader.read
    def spy(self, path, *args, **kwargs):
        item = original(self, path, *args, **kwargs)
        if path == 'a/index.md': git(project, 'update-ref', 'refs/remotes/origin/main', later)
        return item
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    with pytest.raises(FolderCoordinationError):
        prepare_folder_packet(project, FolderHostBinding(project, ('a',)), task)


def test_preflight_revocation_blocks_all_evidence_before_replay(project, monkeypatch):
    for name in ('first', 'second'):
        put(project, f'a/{name}.md', f'Synthetic {name}\n')
    commit(project)
    binding = FolderHostBinding(project, ('a',))
    task = request(project, evidence=[selector('a/first.md'), selector('a/second.md')])
    packet = prepare_folder_packet(project, binding, task)['packet']
    config = project / 'wiki-context-controls.yaml'; data = yaml.safe_load(config.read_text())
    data['controls']['a']['policy']['deny'] = {'read': ['a/second.md']}
    config.write_text(yaml.safe_dump(data)); commit(project)
    current = git(project, 'rev-parse', 'HEAD')
    # A caller cannot bypass preauthorization by relabelling stale packet metadata.
    packet['policy_revision'] = current
    payload = {'folder': 'a', 'approved_revision': current, 'base': current, 'head': current,
               'branch': 'wiki/synthetic', 'packet': packet,
               'result': {'schema_version': 'wiki.folder-task-result/v2',
                          'changes': [{'path': packet['output'], 'action': 'created'}]}}
    original = RepositoryReader.read
    def spy(self, path, *args, **kwargs):
        if path in ('a/first.md', 'a/second.md'):
            pytest.fail('source body opened before current preflight authorization')
        return original(self, path, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    with pytest.raises(FolderCoordinationError, match='evidence unavailable'):
        prepare_folder_preflight(project, binding, payload)


def test_v1_result_is_rejected_before_preflight_replays_packet(project, monkeypatch):
    task = request(project)
    binding = FolderHostBinding(project, ('a',))
    packet = prepare_folder_packet(project, binding, task)['packet']
    payload = {'folder': 'a', 'approved_revision': task['approved_revision'],
               'base': task['approved_revision'], 'head': task['approved_revision'],
               'branch': 'wiki/synthetic', 'packet': packet,
               'result': {'schema_version': 'wiki.task-result/v1'}}
    original = RepositoryReader.read
    def spy(self, path, *args, **kwargs):
        if path != 'wiki-context-controls.yaml':
            pytest.fail('body opened before v1 result rejection')
        return original(self, path, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    with pytest.raises(FolderCoordinationError, match='folder result unavailable'):
        prepare_folder_preflight(project, binding, payload)


def test_sensitive_selector_rejected_before_policy_load_without_traceback_leak(project, monkeypatch):
    import traceback
    import wiki_core.folder_coordination_v2 as module
    task = request(project)
    marker = 'synthetic-private-token-value'
    task['task']['index_section'] = 'https://example.invalid/x?token=' + marker
    def never(*args, **kwargs):
        pytest.fail('policy loaded before secret check')
    monkeypatch.setattr(module, 'load_folder_policy_v2', never)
    with pytest.raises(FolderCoordinationError) as caught:
        prepare_folder_packet(project, FolderHostBinding(project, ('a',)), task)
    assert marker not in ''.join(traceback.format_exception(caught.value))


def test_underlying_error_is_not_disclosed_in_packet_or_preflight_traceback(project, monkeypatch):
    import traceback
    import wiki_core.folder_coordination_v2 as module
    binding = FolderHostBinding(project, ('a',))
    task = request(project)
    packet = prepare_folder_packet(project, binding, task)['packet']
    marker = 'synthetic-sensitive-section-name'
    task['task']['index_section'] = marker
    with pytest.raises(FolderCoordinationError) as caught:
        prepare_folder_packet(project, binding, task)
    assert marker not in ''.join(traceback.format_exception(caught.value))

    payload = {'folder': 'a', 'approved_revision': task['approved_revision'],
               'base': task['approved_revision'], 'head': task['approved_revision'],
               'branch': 'wiki/synthetic', 'packet': packet,
               'result': {'schema_version': 'wiki.folder-task-result/v2',
                          'changes': [{'path': packet['output'], 'action': 'created'}]}}
    def fail(*args, **kwargs):
        raise ValueError(marker)
    monkeypatch.setattr(module, 'preauthorize_index', fail)
    with pytest.raises(FolderCoordinationError) as caught:
        prepare_folder_preflight(project, binding, payload)
    assert marker not in ''.join(traceback.format_exception(caught.value))


def test_root_resolution_errors_are_opaque(project, monkeypatch):
    import traceback
    from pathlib import Path
    binding = FolderHostBinding(project, ('a',))
    task = request(project)
    marker = 'synthetic-private-root'
    def fail(*args, **kwargs):
        raise RuntimeError(marker)
    monkeypatch.setattr(Path, 'resolve', fail)
    with pytest.raises(FolderCoordinationError) as caught:
        prepare_folder_packet(project, binding, task)
    assert marker not in ''.join(traceback.format_exception(caught.value))
    with pytest.raises(ValueError) as caught:
        FolderHostBinding(project, ('a',))
    assert marker not in ''.join(traceback.format_exception(caught.value))


def test_preflight_requires_change_to_declared_output(project):
    binding = FolderHostBinding(project, ('a',))
    task = request(project)
    packet = prepare_folder_packet(project, binding, task)['packet']
    git(project, 'checkout', '-qb', 'wiki/unrelated-only')
    put(project, 'a/unrelated.md', 'Different output\n')
    git(project, 'add', '-A'); git(project, 'commit', '-qm', 'unrelated proposal')
    observed = [{'path': row['path'], 'kind': row['kind'], 'revision': row['revision'],
                 'sha256': row['sha256'], 'section': row.get('section'), 'field': row.get('field')}
                for row in packet['inputs']]
    result = {'schema_version': 'wiki.folder-task-result/v2', 'status': 'completed',
              'task_id': packet['task_id'], 'context_id': packet['context_id'],
              'packet_digest': packet['packet_digest'], 'observed': observed,
              'changes': [{'path': 'a/unrelated.md', 'action': 'created'}]}
    payload = {'folder': 'a', 'approved_revision': task['approved_revision'],
               'base': task['approved_revision'], 'head': git(project, 'rev-parse', 'HEAD'),
               'branch': 'wiki/unrelated-only', 'packet': packet, 'result': result}
    with pytest.raises(FolderCoordinationError, match='declared output'):
        prepare_folder_preflight(project, binding, payload)
