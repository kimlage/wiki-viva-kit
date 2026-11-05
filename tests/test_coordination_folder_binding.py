"""The host, not the request, chooses folder authority and its allowlist."""
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from tests.test_context_flow import git, repo
from wiki_core import coordination_context as coord


@pytest.fixture
def folder_binding():
    return coord.CoordinationBinding(('finance/costs',), 'refs/remotes/origin/main', 'wiki.config.yaml')


def payload(repo):
    revision = git(repo, 'rev-parse', 'HEAD')
    return {'context_id': 'finance/costs', 'approved_revision': revision,
            'content_revision': revision, 'entry_folder': 'finance/costs/aux',
            'task': {'task_id': 'task', 'goal': 'Review', 'output': 'result',
                     'integrator': 'reviewer', 'max_bytes': 20000, 'evidence': []}}


def stub_folder_policy(monkeypatch):
    calls = []
    def load(root, revision, manifest, *, trusted_ref):
        calls.append((revision, manifest, trusted_ref))
        return SimpleNamespace(contexts={'finance/costs': {}, '.': {}},
                               format_version='folder', policy_revision=revision,
                               owner_of=lambda path: 'finance/costs')
    monkeypatch.setattr(coord, 'load_policy', load)
    return calls


def test_folder_binding_is_fixed_at_host_start_and_paths_are_literal():
    env = {'WIKI_COORDINATION_ALLOWED_CONTEXTS': '.,finance/costs',
           'WIKI_COORDINATION_TRUSTED_REF': 'refs/remotes/origin/main',
           'WIKI_COORDINATION_CONTEXT_MODE': 'folder'}
    binding = coord.CoordinationBinding.from_environment(env)
    env['WIKI_COORDINATION_CONTEXT_MODE'] = 'v1'
    env['WIKI_COORDINATION_ALLOWED_CONTEXTS'] = 'other'
    assert binding.contexts == ('.', 'finance/costs')
    assert binding.manifest == 'wiki.config.yaml'
    with pytest.raises(FrozenInstanceError):
        binding.manifest = 'context.yaml'
    for name in ('../finance', '/finance', 'finance/../tax', 'finance/*', ''):
        with pytest.raises(ValueError):
            coord.CoordinationBinding((name,), 'refs/remotes/origin/main', 'wiki.config.yaml')
    with pytest.raises(ValueError):
        coord.CoordinationBinding.from_environment({'WIKI_COORDINATION_CONTEXT_MODE': 'folder'})
    with pytest.raises(ValueError):
        coord.CoordinationBinding.from_environment({'WIKI_COORDINATION_ALLOWED_CONTEXTS': 'x',
                                                     'WIKI_COORDINATION_CONTEXT_MODE': 'other'})
    with pytest.raises(ValueError):
        coord.CoordinationBinding.from_environment({'WIKI_COORDINATION_ALLOWED_CONTEXTS': 'x',
                                                     'WIKI_COORDINATION_MANIFEST': 'wiki.config.yaml'})


def test_folder_packet_forwards_only_host_fixed_authority(repo, monkeypatch, folder_binding):
    loads = stub_folder_policy(monkeypatch)
    calls = []
    def build(root, policy, context_id, revision, evidence, max_bytes, **kwargs):
        calls.append((context_id, kwargs))
        return {'inputs': []}
    monkeypatch.setattr(coord, 'build_packet', build)
    data = payload(repo)
    data['entry_index'] = 'finance/costs/index.md'
    assert coord.prepare_packet(repo, folder_binding, data)['mode'] == 'approved'
    assert loads == [(data['approved_revision'], 'wiki.config.yaml', 'refs/remotes/origin/main')]
    assert calls[0][1]['entry_folder'] == 'finance/costs/aux'
    assert calls[0][1]['entry_index'] == 'finance/costs/index.md'
    for name, value in [('manifest', 'context.yaml'), ('trusted_ref', 'refs/heads/main'),
                        ('policy_context', 'tax')]:
        with pytest.raises(coord.ProtectedCoordinationError) as error:
            coord.prepare_packet(repo, folder_binding, {**data, name: value})
        assert error.value.code == 'coordination_invalid_request'
    with pytest.raises(coord.ProtectedCoordinationError) as error:
        coord.prepare_packet(repo, folder_binding, {**data, 'context_id': 'finance/tax'})
    assert error.value.code == 'coordination_not_authorized'
    with pytest.raises(coord.ProtectedCoordinationError):
        coord.prepare_packet(repo, folder_binding, {**data, 'entry_folder': '../tax'})
    assert len(calls) == 1


def test_folder_packet_checks_expected_digest_of_explicit_evidence(repo, monkeypatch, folder_binding):
    stub_folder_policy(monkeypatch)
    data = payload(repo)
    data['task']['evidence'] = [{'ref': 'finance/costs/source.md', 'producer': 'finance/costs',
                                 'reason': 'source', 'use': 'interpretation', 'classification': 'context',
                                 'expected_document_sha256': 'a' * 64}]
    def build(*args, **kwargs):
        return {'inputs': [{'kind': 'evidence', 'document_sha256': 'b' * 64},
                           {'kind': 'evidence', 'document_sha256': 'a' * 64}]}
    monkeypatch.setattr(coord, 'build_packet', build)
    assert coord.prepare_packet(repo, folder_binding, data)['mode'] == 'approved'
    data['task']['evidence'][0]['expected_document_sha256'] = 'b' * 64
    with pytest.raises(coord.ProtectedCoordinationError):
        coord.prepare_packet(repo, folder_binding, data)


def test_binding_rejects_wrong_policy_format_and_preflight_packet(repo, monkeypatch, folder_binding):
    data = payload(repo)
    monkeypatch.setattr(coord, 'load_policy', lambda *a, **kw: SimpleNamespace(
        contexts={'finance/costs': {}}, policy_revision=data['approved_revision']))
    with pytest.raises(coord.ProtectedCoordinationError) as error:
        coord.prepare_packet(repo, folder_binding, data)
    assert error.value.code == 'coordination_policy_unavailable'
    stub_folder_policy(monkeypatch)
    preflight = {'context_id': data['context_id'], 'approved_revision': data['approved_revision'],
                 'base': data['approved_revision'], 'head': data['approved_revision'],
                 'branch': 'wiki/test', 'packet': {'capability_evidence': None,
                                                   'required_capabilities': []}, 'result': {}}
    monkeypatch.setattr(coord, 'preflight', lambda *a, **kw: pytest.fail('wrong authority reached preflight'))
    with pytest.raises(coord.ProtectedCoordinationError) as error:
        coord.prepare_preflight(repo, folder_binding, preflight)
    assert error.value.code == 'coordination_preflight_unavailable'


def test_v1_binding_does_not_accept_folder_payload(repo, monkeypatch):
    binding = coord.CoordinationBinding(('costs',), 'refs/remotes/origin/main')
    monkeypatch.setattr(coord, 'load_policy', lambda *a, **kw: pytest.fail('invalid payload was loaded'))
    data = payload(repo)
    data['context_id'] = 'costs'
    with pytest.raises(coord.ProtectedCoordinationError) as error:
        coord.prepare_packet(repo, binding, data)
    assert error.value.code == 'coordination_invalid_request'
