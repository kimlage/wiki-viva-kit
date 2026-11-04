"""Synthetic v2 query replay with current authority checked first."""
from copy import deepcopy

import pytest
import yaml

from tests.test_folder_query_packet_v2 import setup_query, result_for
from tests.test_folder_query_v2 import project, put, commit, git
from wiki_core.folder_policy_v2 import load_folder_policy_v2
from wiki_core.folder_query_history_v2 import assess_folder_query_history_v2, FolderQueryHistoryError
from wiki_core.repository_reader import RepositoryReader


def created(project):
    _, _, _, packet = setup_query(project)
    result = result_for(packet, [{'path': 'a/result.md', 'action': 'created'}])
    put(project, 'a/result.md', '---\npage_type: claim\n---\nInterpretation\n')
    commit(project)
    return packet, result, git(project, 'rev-parse', 'HEAD')


@pytest.mark.parametrize('changed', [False, True])
def test_replays_query_and_keeps_review_open(project, changed):
    packet, result, integrated = created(project)
    if changed:
        put(project, 'a/items/one.md', '---\npage_id: one\nstatus: active\namount: 99\n---\nNew\n')
        commit(project)
    policy = load_folder_policy_v2(project, 'HEAD')
    outcome = assess_folder_query_history_v2(project, policy, packet=packet, result=result, integrated_revision=integrated)
    assert outcome['state'] == 'review_pending'
    assert outcome['query_state'] == ('changed' if changed else 'unchanged')
    assert outcome['consumed_revision'] == packet['base_packet']['policy_revision']
    assert outcome['read_verification'] == 'reported_not_independently_verified'
    assert outcome['output_binding'] == 'matching_integrated_bytes_only'


def test_revoked_scope_blocks_before_historical_bodies(project, monkeypatch):
    packet, result, integrated = created(project)
    config = project / 'wiki-context-controls.yaml'
    data = yaml.safe_load(config.read_text())
    data['controls']['a']['policy']['deny'] = {'read': ['a/items']}
    config.write_text(yaml.safe_dump(data)); commit(project)
    policy = load_folder_policy_v2(project, 'HEAD')
    old = packet['base_packet']['policy_revision']; original = RepositoryReader.read
    def spy(self, path, *args, **kwargs):
        if self.revision == old and path != 'wiki-context-controls.yaml':
            raise AssertionError('historical body opened after scope revocation')
        return original(self, path, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    with pytest.raises(FolderQueryHistoryError):
        assess_folder_query_history_v2(project, policy, packet=packet, result=result, integrated_revision=integrated)


def test_forged_query_receipt_and_unrelated_output_are_rejected(project):
    packet, result, integrated = created(project)
    policy = load_folder_policy_v2(project, 'HEAD')
    forged = deepcopy(packet); forged['queries'][0]['receipt']['selected_digest'] = '0' * 64
    with pytest.raises(FolderQueryHistoryError):
        assess_folder_query_history_v2(project, policy, packet=forged, result=result, integrated_revision=integrated)
    unrelated = deepcopy(result); unrelated['changes'][0]['path'] = 'a/unrelated.md'
    with pytest.raises(FolderQueryHistoryError):
        assess_folder_query_history_v2(project, policy, packet=packet, result=unrelated, integrated_revision=integrated)


def test_changed_normative_body_blocks_before_historical_reads(project, monkeypatch):
    packet, result, integrated = created(project)
    put(project, 'a/AGENTS.md', 'Changed instructions\n'); commit(project)
    policy = load_folder_policy_v2(project, 'HEAD')
    old = packet['base_packet']['policy_revision']; original = RepositoryReader.read
    def spy(self, path, *args, **kwargs):
        if self.revision == old and path != 'wiki-context-controls.yaml':
            raise AssertionError('historical body opened with changed rules')
        return original(self, path, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    with pytest.raises(FolderQueryHistoryError):
        assess_folder_query_history_v2(project, policy, packet=packet, result=result, integrated_revision=integrated)


@pytest.mark.parametrize('action', ['modified', 'deleted'])
def test_existing_output_replays_only_with_complete_prior_evidence(project, action):
    from tests.test_folder_query_v2 import fixture_query
    from wiki_core.folder_packet_v2 import build_folder_packet_v2
    from wiki_core.folder_query_packet_v2 import build_folder_query_packet_v2
    _, _, entry = fixture_query(project)
    put(project, 'a/result.md', '---\npage_type: claim\n---\nPrior\n'); commit(project)
    policy = load_folder_policy_v2(project, 'HEAD'); before = git(project, 'rev-parse', 'HEAD')
    base = build_folder_packet_v2(project, policy, 'a', 50000, index_path='a/index.md', content_revision=before,
        task_id='x', goal='x', output='a/result.md', integrator='x',
        evidence=[{'path':'a/result.md', 'producer_folder':'a', 'reason':'prior output',
                   'use':'interpret', 'classification':'synthetic'}])
    packet = build_folder_query_packet_v2(project, policy, base_packet=base, queries=[entry])
    result = result_for(packet, [{'path':'a/result.md', 'action':action}])
    if action == 'deleted': (project/'a/result.md').unlink()
    else: put(project, 'a/result.md', '---\npage_type: claim\n---\nUpdated\n')
    commit(project); integrated = git(project, 'rev-parse', 'HEAD')
    policy = load_folder_policy_v2(project, 'HEAD')
    outcome = assess_folder_query_history_v2(project, policy, packet=packet, result=result, integrated_revision=integrated)
    assert outcome['state'] == 'review_pending'
    assert outcome['output_binding'] == ('matching_integrated_absence_only' if action == 'deleted' else 'matching_integrated_bytes_only')


def test_revoked_extra_evidence_blocks_before_old_bodies(project, monkeypatch):
    from tests.test_folder_query_v2 import fixture_query
    from wiki_core.folder_packet_v2 import build_folder_packet_v2
    from wiki_core.folder_query_packet_v2 import build_folder_query_packet_v2
    _, _, entry = fixture_query(project)
    put(project, 'a/extra.md', 'Additional evidence\n'); commit(project)
    p = load_folder_policy_v2(project, 'HEAD'); old = git(project, 'rev-parse', 'HEAD')
    base = build_folder_packet_v2(project, p, 'a', 50000, index_path='a/index.md', content_revision=old,
        task_id='x', goal='x', output='a/result.md', integrator='x',
        evidence=[{'path':'a/extra.md', 'producer_folder':'a', 'reason':'extra',
                   'use':'interpret', 'classification':'synthetic'}])
    packet = build_folder_query_packet_v2(project, p, base_packet=base, queries=[entry])
    result = result_for(packet, [{'path':'a/result.md', 'action':'created'}])
    put(project, 'a/result.md', 'Created\n'); commit(project); integrated = git(project, 'rev-parse', 'HEAD')
    config = project/'wiki-context-controls.yaml'; data = yaml.safe_load(config.read_text())
    data['controls']['a']['policy']['deny'] = {'read':['a/extra.md']}
    config.write_text(yaml.safe_dump(data)); commit(project); p = load_folder_policy_v2(project, 'HEAD')
    original = RepositoryReader.read
    def spy(self, path, *args, **kwargs):
        if self.revision == old and path != 'wiki-context-controls.yaml':
            raise AssertionError('historical body opened before evidence authorization')
        return original(self, path, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    with pytest.raises(FolderQueryHistoryError):
        assess_folder_query_history_v2(project, p, packet=packet, result=result, integrated_revision=integrated)


def test_modified_without_prior_evidence_remains_blocked(project):
    from tests.test_folder_query_v2 import fixture_query
    from wiki_core.folder_packet_v2 import build_folder_packet_v2
    from wiki_core.folder_query_packet_v2 import build_folder_query_packet_v2
    _, _, entry = fixture_query(project)
    put(project, 'a/result.md', 'Prior\n'); commit(project)
    p = load_folder_policy_v2(project, 'HEAD'); old = git(project, 'rev-parse', 'HEAD')
    base = build_folder_packet_v2(project, p, 'a', 50000, index_path='a/index.md', content_revision=old,
                                  task_id='x', goal='x', output='a/result.md', integrator='x')
    packet = build_folder_query_packet_v2(project, p, base_packet=base, queries=[entry])
    result = result_for(packet, [{'path':'a/result.md', 'action':'modified'}])
    put(project, 'a/result.md', 'Updated\n'); commit(project); integrated = git(project, 'rev-parse', 'HEAD')
    p = load_folder_policy_v2(project, 'HEAD')
    with pytest.raises(FolderQueryHistoryError, match='whole prior output evidence required'):
        assess_folder_query_history_v2(project, p, packet=packet, result=result, integrated_revision=integrated)


def test_symlink_never_counts_as_deleted_output(project):
    from tests.test_folder_query_v2 import fixture_query
    from wiki_core.folder_packet_v2 import build_folder_packet_v2
    from wiki_core.folder_query_packet_v2 import build_folder_query_packet_v2
    _, _, entry = fixture_query(project)
    put(project, 'a/result.md', 'Prior\n'); commit(project)
    p = load_folder_policy_v2(project, 'HEAD'); old = git(project, 'rev-parse', 'HEAD')
    base = build_folder_packet_v2(project, p, 'a', 50000, index_path='a/index.md', content_revision=old,
        task_id='x', goal='x', output='a/result.md', integrator='x',
        evidence=[{'path':'a/result.md', 'producer_folder':'a', 'reason':'prior',
                   'use':'interpret', 'classification':'synthetic'}])
    packet = build_folder_query_packet_v2(project, p, base_packet=base, queries=[entry])
    result = result_for(packet, [{'path':'a/result.md', 'action':'deleted'}])
    (project/'a/result.md').unlink(); (project/'a/result.md').symlink_to('index.md')
    commit(project); integrated = git(project, 'rev-parse', 'HEAD')
    p = load_folder_policy_v2(project, 'HEAD')
    with pytest.raises(FolderQueryHistoryError):
        assess_folder_query_history_v2(project, p, packet=packet, result=result, integrated_revision=integrated)
