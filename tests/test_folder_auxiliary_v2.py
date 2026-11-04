"""Synthetic actor-scoped, revision-bound auxiliary instructions."""
from __future__ import annotations

import pytest
import yaml

from tests.test_folder_policy_v2 import project, put, commit
from wiki_core.context_policy import PolicyError
from wiki_core.folder_auxiliary_v2 import has_auxiliary_declaration, qualify_auxiliary
from wiki_core.folder_policy_v2 import folder_id, load_folder_policy_v2
from wiki_core.repository_reader import RepositoryReader


MARKER = ('## Wiki v2: auxiliary\n\n'
          'This folder adds instructions; ownership stays with the nearest context.\n')


def qualify(repo, folder='a', start='a/aux'):
    policy = load_folder_policy_v2(repo, 'HEAD')
    reader = RepositoryReader(repo, policy.policy_revision)
    return policy, qualify_auxiliary(policy, reader, folder, start, max_bytes=50000)


def test_auxiliary_view_retains_existing_owner_without_mutating_base(project):
    put(project, 'a/aux/AGENTS.md', '# Local rules\n\n' + MARKER)
    put(project, 'a/aux/notes.md', 'Synthetic note.\n')
    commit(project)
    base, scoped = qualify(project)
    with pytest.raises(PolicyError, match='ownership unavailable'):
        base.owner_of('a/aux/notes.md')
    assert scoped.owner_of('a/aux/notes.md') == folder_id('a')
    assert scoped.owner_of('a/aux/b/report.md') == folder_id('a/aux/b')
    assert scoped.effective == base.effective
    assert scoped.folder_ids == base.folder_ids
    assert scoped.permits(folder_id('a'), 'read', 'a/aux/notes.md') == base.permits(folder_id('a'), 'read', 'a/aux/notes.md')
    with pytest.raises(PolicyError, match='ownership unavailable'):
        scoped.fresh().owner_of('a/aux/notes.md')


@pytest.mark.parametrize('value', [
    '# No marker\n',
    '### Wiki v2: auxiliary\n\nThis folder adds instructions; ownership stays with the nearest context.\n',
    '## Wiki v2: auxiliary\n\nThis is a context.\n',
    MARKER + '\n' + MARKER,
    MARKER + '\nExtra text in the marker section.\n',
])
def test_unmarked_or_malformed_auxiliary_is_rejected(project, value):
    put(project, 'a/aux/AGENTS.md', value)
    commit(project)
    assert not has_auxiliary_declaration(value)
    with pytest.raises(PolicyError, match='declaration missing or invalid'):
        qualify(project)


def test_worktree_marker_is_not_approved(project):
    # A proposed uncommitted marker has no authority at the approved SHA.
    put(project, 'a/aux/AGENTS.md', '# Proposed only\n\n' + MARKER)
    with pytest.raises(PolicyError, match='declaration missing or invalid'):
        qualify(project)


def test_denied_marker_and_wrong_owner_fail_before_any_marker_read(project, monkeypatch):
    put(project, 'a/aux/AGENTS.md', '# Rules\n\n' + MARKER)
    config = project / 'wiki-context-controls.yaml'
    data = yaml.safe_load(config.read_text())
    data['controls']['a']['policy']['deny'] = {'read': ['self/aux/AGENTS.md']}
    config.write_text(yaml.safe_dump(data))
    commit(project)
    policy = load_folder_policy_v2(project, 'HEAD')
    reader = RepositoryReader(project, policy.policy_revision)
    original_read, original_size = reader.read, reader.blob_size
    def guarded_read(path, *args, **kwargs):
        if path == 'a/aux/AGENTS.md': pytest.fail('denied marker body read')
        return original_read(path, *args, **kwargs)
    def guarded_size(path):
        if path == 'a/aux/AGENTS.md': pytest.fail('denied marker metadata read')
        return original_size(path)
    monkeypatch.setattr(reader, 'read', guarded_read)
    monkeypatch.setattr(reader, 'blob_size', guarded_size)
    with pytest.raises(PolicyError, match='not authorized'):
        qualify_auxiliary(policy, reader, 'a', 'a/aux', max_bytes=50000)
    with pytest.raises(PolicyError, match='outside selected context'):
        qualify_auxiliary(policy, reader, '.', 'a/aux', max_bytes=50000)


def _packet(repo, policy, *, source='a/aux/source.md', output='a/aux/report.md', index='a/index.md', start='a/aux'):
    from wiki_core.folder_packet_v2 import build_folder_packet_v2
    evidence = [{'path': source, 'producer_folder': 'a', 'reason': 'synthetic source',
                 'use': 'interpret', 'classification': 'synthetic'}]
    return build_folder_packet_v2(repo, policy, 'a', 50000, content_revision=policy.policy_revision,
                                  index_path=index, task_id='fixture', goal='review', output=output,
                                  integrator='reviewer', evidence=evidence, start_folder=start)


def _result(packet, output):
    return {'schema_version': 'wiki.folder-task-result/v2', 'status': 'completed',
            'task_id': packet['task_id'], 'context_id': packet['context_id'],
            'packet_digest': packet['packet_digest'],
            'observed': [{'path': row['path'], 'kind': row['kind'], 'revision': row['revision'],
                          'sha256': row['sha256'], 'section': row.get('section'), 'field': row.get('field')}
                         for row in packet['inputs']],
            'changes': [{'path': output, 'action': 'created'}]}


def test_auxiliary_packet_preflight_and_selective_reassessment(project):
    from tests.test_folder_policy_v2 import git
    from wiki_core.folder_impact_v2 import assess_folder_source_v2
    from wiki_core.folder_integration_v2 import preflight_folder_v2
    put(project, 'a/aux/AGENTS.md', '# Auxiliary rules\n\n' + MARKER)
    put(project, 'a/aux/source.md', 'Synthetic source.\n')
    commit(project)
    approved = git(project, 'rev-parse', 'HEAD')
    policy = load_folder_policy_v2(project, approved)
    packet = _packet(project, policy)
    assert packet['context_id'] == folder_id('a')
    assert packet['context_folder'] == 'a' and packet['start_folder'] == 'a/aux'
    assert [row['path'] for row in packet['inputs']] == ['AGENTS.md', 'a/AGENTS.md', 'a/aux/AGENTS.md',
                                                          'a/index.md', 'a/aux/source.md']
    result = _result(packet, 'a/aux/report.md')
    git(project, 'checkout', '-qb', 'wiki/auxiliary-fixture')
    put(project, 'a/aux/report.md', '---\npage_type: claim\n---\nSynthetic independent interpretation.\n')
    git(project, 'add', 'a/aux/report.md')
    git(project, 'commit', '-qm', 'proposed claim')
    head = git(project, 'rev-parse', 'HEAD')
    check = preflight_folder_v2(project, policy, base=approved, head=head,
                                branch='wiki/auxiliary-fixture', packet=packet, result=result)
    assert check['state'] == 'independent_review_required' and check['merge'] == 'not_performed'
    git(project, 'update-ref', 'refs/remotes/origin/main', head)
    current = load_folder_policy_v2(project, head)
    unchanged = assess_folder_source_v2(project, current, packet=packet, result=result,
                                        target='a/aux/report.md', source='a/aux/source.md')
    assert unchanged['state'] == 'verification_pending'
    put(project, 'a/aux/source.md', 'Synthetic source updated.\n')
    commit(project)
    current = load_folder_policy_v2(project, 'HEAD')
    changed = assess_folder_source_v2(project, current, packet=packet, result=result,
                                      target='a/aux/report.md', source='a/aux/source.md')
    assert changed['state'] == 'review_pending'
    assert (project / 'a/aux/report.md').read_text().endswith('Synthetic independent interpretation.\n')


def test_auxiliary_rejects_denied_output_and_index_before_marker_read(project, monkeypatch):
    from wiki_core.folder_packet_v2 import build_folder_packet_v2
    put(project, 'a/aux/AGENTS.md', '# Auxiliary rules\n\n' + MARKER)
    put(project, 'a/aux/source.md', 'source\n')
    config = project / 'wiki-context-controls.yaml'
    data = yaml.safe_load(config.read_text())
    data['controls']['a']['policy']['deny'] = {'write': ['self/aux/report.md']}
    config.write_text(yaml.safe_dump(data))
    commit(project)
    policy = load_folder_policy_v2(project, 'HEAD')
    original = RepositoryReader.read
    def guarded(self, ref, *args, **kwargs):
        if ref == 'a/aux/AGENTS.md': pytest.fail('marker body read before authorization')
        return original(self, ref, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', guarded)
    with pytest.raises(PolicyError, match='output is not authorized'):
        _packet(project, policy)
    with pytest.raises(PolicyError, match='index is not authorized'):
        build_folder_packet_v2(project, policy, 'a', 50000, content_revision='HEAD',
                               index_path='a/aux/b/index.md', task_id='x', goal='x',
                               output='a/aux/other.md', integrator='x', start_folder='a/aux')


def test_auxiliary_marker_revocation_blocks_before_old_evidence(project, monkeypatch):
    from wiki_core.folder_impact_v2 import FolderImpactError, assess_folder_source_v2
    from tests.test_folder_policy_v2 import git
    put(project, 'a/aux/AGENTS.md', '# Auxiliary rules\n\n' + MARKER)
    put(project, 'a/aux/source.md', 'Synthetic source.\n')
    commit(project)
    policy = load_folder_policy_v2(project, 'HEAD')
    packet = _packet(project, policy)
    result = _result(packet, 'a/aux/report.md')
    put(project, 'a/aux/report.md', '---\npage_type: claim\n---\nSynthetic interpretation.\n')
    commit(project)
    put(project, 'a/aux/AGENTS.md', '# Marker removed\n')
    commit(project)
    current = load_folder_policy_v2(project, 'HEAD')
    original = RepositoryReader.read
    def guarded(self, ref, *args, **kwargs):
        if ref == 'a/aux/source.md': pytest.fail('evidence read after marker revocation')
        return original(self, ref, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', guarded)
    with pytest.raises(FolderImpactError):
        assess_folder_source_v2(project, current, packet=packet, result=result,
                                target='a/aux/report.md', source='a/aux/source.md')


def test_auxiliary_body_budget_precedes_read(project, monkeypatch):
    put(project, 'a/aux/AGENTS.md', '# Rules\n\n' + MARKER)
    commit(project)
    policy = load_folder_policy_v2(project, 'HEAD')
    reader = RepositoryReader(project, policy.policy_revision)
    original = reader.read
    def guarded(ref, *args, **kwargs):
        if ref == 'a/aux/AGENTS.md': pytest.fail('oversized marker body read')
        return original(ref, *args, **kwargs)
    monkeypatch.setattr(reader, 'read', guarded)
    with pytest.raises(PolicyError, match='exceed byte budget'):
        qualify_auxiliary(policy, reader, 'a', 'a/aux', max_bytes=1)


def test_auxiliary_cross_owner_mandatory_reference_never_reads_body(project, monkeypatch):
    marker = '# Rules\n\n' + MARKER + '\n## Wiki v2: mandatory references\n\n- [Other](b/secret.md)\n'
    put(project, 'a/aux/AGENTS.md', marker)
    put(project, 'a/aux/source.md', 'source\n')
    put(project, 'a/aux/b/secret.md', 'Other owner\n')
    commit(project)
    policy = load_folder_policy_v2(project, 'HEAD')
    original = RepositoryReader.read
    def guarded(self, ref, *args, **kwargs):
        if ref == 'a/aux/b/secret.md': pytest.fail('cross-owner mandatory body read')
        return original(self, ref, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', guarded)
    with pytest.raises(PolicyError, match='another context'):
        _packet(project, policy)


def test_auxiliary_cannot_declare_its_own_index(project):
    marker = '# Rules\n\n' + MARKER + '\n## Wiki v2: indexes\n\n- [Index](local.md)\n'
    put(project, 'a/aux/AGENTS.md', marker)
    put(project, 'a/aux/source.md', 'source\n')
    put(project, 'a/aux/local.md', 'not a context index\n')
    commit(project)
    policy = load_folder_policy_v2(project, 'HEAD')
    with pytest.raises(PolicyError, match='cannot declare a context index'):
        _packet(project, policy)


def test_auxiliary_ref_moving_during_packet_fails_closed(project, monkeypatch):
    from tests.test_folder_policy_v2 import git
    put(project, 'a/aux/AGENTS.md', '# Rules\n\n' + MARKER)
    put(project, 'a/aux/source.md', 'source\n')
    commit(project)
    approved = git(project, 'rev-parse', 'HEAD')
    put(project, 'a/aux/AGENTS.md', '# Marker removed\n')
    git(project, 'add', 'a/aux/AGENTS.md')
    git(project, 'commit', '-qm', 'unapproved removal')
    new_head = git(project, 'rev-parse', 'HEAD')
    policy = load_folder_policy_v2(project, approved)
    original = RepositoryReader.read
    moved = False
    def moving(self, ref, *args, **kwargs):
        nonlocal moved
        if ref == 'a/aux/AGENTS.md' and not moved:
            moved = True
            git(project, 'update-ref', 'refs/remotes/origin/main', new_head)
        return original(self, ref, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', moving)
    with pytest.raises(PolicyError, match='not current trusted'):
        _packet(project, policy)


def test_nested_indexed_context_is_not_reowned_by_parent_auxiliary(project):
    put(project, 'a/aux/AGENTS.md', '# Parent auxiliary\n\n' + MARKER)
    put(project, 'a/aux/b/local/AGENTS.md', '# Child auxiliary\n\n' + MARKER)
    put(project, 'a/aux/b/local/note.md', 'synthetic\n')
    commit(project)
    policy = load_folder_policy_v2(project, 'HEAD')
    reader = RepositoryReader(project, policy.policy_revision)
    scoped = qualify_auxiliary(policy, reader, 'a/aux/b', 'a/aux/b/local', max_bytes=50000)
    assert scoped.owner_of('a/aux/b/local/note.md') == folder_id('a/aux/b')
    with pytest.raises(PolicyError, match='ownership unavailable'):
        scoped.owner_of('a/aux/note.md')
