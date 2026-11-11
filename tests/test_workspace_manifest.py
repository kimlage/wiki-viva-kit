from copy import deepcopy

import pytest

from wiki_core.workspace_manifest import WorkspaceManifestError, validate_manifest


def fixture():
    return {'schema': 'wiki-workspace/v1', 'directories': ['team', 'team/repos'],
            'links': [{'path': 'team/index.md', 'target': 'wiki:memories/team/index.md'}],
            'repositories': [{'path': 'team/repos/app', 'identity': 'git.example.com/org/app',
                              'remote': 'git@git.example.com:org/app.git', 'default_branch': 'main'}]}


def test_valid_declaration_does_not_claim_workspace_or_auth_checked():
    result = validate_manifest(fixture())
    assert result['manifest'] == 'valid'
    assert result['workspace'] == result['remote_authentication'] == 'not_checked'
    assert result['boundary'] == 'concurrent_rename_not_qualified'


@pytest.mark.parametrize('bad', ['/tmp/x', '../secret', 'team/../secret', 'team//x', 'team/./x', 'C:\\work'])
def test_refuses_nonportable_paths(bad):
    data = fixture(); data['directories'].append(bad)
    with pytest.raises(WorkspaceManifestError): validate_manifest(data)


@pytest.mark.parametrize('target', ['/etc/passwd', 'wiki:../secret', 'wiki:/etc/passwd', 'other:foo'])
def test_refuses_nonportable_link_targets(target):
    data = fixture(); data['links'][0]['target'] = target
    with pytest.raises(WorkspaceManifestError): validate_manifest(data)


@pytest.mark.parametrize('remote', ['https://user:pass@git.example.com/org/app', 'https://git.example.com/org/app?token=abc', 'file:///tmp/app'])
def test_refuses_credentials_and_unsafe_remote(remote):
    data = fixture(); data['repositories'][0]['remote'] = remote
    with pytest.raises(WorkspaceManifestError): validate_manifest(data)


def test_refuses_identity_mismatch_and_conflicts():
    data = fixture(); data['repositories'][0]['identity'] = 'git.example.com/org/other'
    with pytest.raises(WorkspaceManifestError): validate_manifest(data)
    data = fixture(); data['links'].append({'path': 'team/repos', 'target': 'skills:tool'})
    with pytest.raises(WorkspaceManifestError): validate_manifest(data)
    data = fixture(); data['links'].append({'path': 'team/index.md/child', 'target': 'wiki:other'})
    with pytest.raises(WorkspaceManifestError): validate_manifest(data)


def test_refuses_unknown_fields_and_duplicate_paths():
    data = fixture(); data['extra'] = True
    with pytest.raises(WorkspaceManifestError): validate_manifest(data)
    data = fixture(); data['directories'].append('team')
    with pytest.raises(WorkspaceManifestError): validate_manifest(data)


@pytest.mark.parametrize('bad', ['CON', 'team/foo.', 'team/.git/config', 'team/AUX.txt'])
def test_refuses_platform_reserved_paths(bad):
    data = fixture(); data['directories'].append(bad)
    with pytest.raises(WorkspaceManifestError): validate_manifest(data)


def test_refuses_case_collision_and_invalid_git_branch():
    data = fixture(); data['directories'].append('Team/other')
    with pytest.raises(WorkspaceManifestError): validate_manifest(data)
    data = fixture(); data['repositories'][0]['default_branch'] = 'a.lock/b'
    with pytest.raises(WorkspaceManifestError): validate_manifest(data)
