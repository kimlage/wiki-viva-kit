"""Exercise the host binding with the folder-policy implementation when present."""
import hashlib

import pytest

pytest.importorskip('tests.test_folder_policy_core', reason='folder policy is integrated separately')
from tests.test_folder_policy_core import repo, enable_alpha, git, write
from wiki_core.coordination_context import (CoordinationBinding, ProtectedCoordinationError,
                                            capability, prepare_packet)
from wiki_core.repository_reader import RepositoryReader


def test_bound_folder_packet_revalidates_policy_and_exact_evidence(repo, monkeypatch):
    enable_alpha(repo)
    write(repo, 'alpha/source.md', 'Synthetic source\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'selected source')
    git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    sha = git(repo, 'rev-parse', 'HEAD')
    binding = CoordinationBinding(('alpha',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    request = {'context_id': 'alpha', 'approved_revision': sha, 'content_revision': sha,
               'entry_folder': 'alpha/aux',
               'task': {'task_id': 'task', 'goal': 'Review synthetic source', 'output': 'result',
                        'integrator': 'reviewer', 'max_bytes': 100000,
                        'evidence': [{'ref': 'alpha/source.md', 'reason': 'source',
                                      'use': 'interpretation', 'classification': 'context',
                                      'expected_document_sha256': hashlib.sha256(b'Synthetic source\n').hexdigest()}]}}
    assert capability(repo, binding)['available']
    packet = prepare_packet(repo, binding, request)['packet']
    assert packet['entry_folder'] == 'alpha/aux'
    assert packet['entry_index'] == 'alpha/index.md'
    assert packet['inputs'][-1]['ref'] == 'alpha/source.md'
    assert 'linked sources not inspected' in packet['coverage']['missing']

    reads = []
    original = RepositoryReader.read
    def spy(self, path, **kwargs):
        reads.append(path)
        return original(self, path, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    with pytest.raises(ProtectedCoordinationError):
        prepare_packet(repo, binding, {**request, 'entry_folder': 'alpha/child'})
    assert reads == []

    write(repo, 'unrelated.md', 'changed\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'move trusted ref')
    git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    with pytest.raises(ProtectedCoordinationError) as error:
        prepare_packet(repo, binding, request)
    assert error.value.code == 'coordination_policy_unavailable'
