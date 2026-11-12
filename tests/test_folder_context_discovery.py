"""Synthetic regressions for explicit folder-context discovery exclusions."""

import copy
import subprocess

import pytest
import yaml

from wiki_core.context_packet import build_packet
from wiki_core.context_policy import (
    PolicyError, _folder_policy_at, historical_policy, load_policy, revision,
)
from wiki_core.coordination_context import CoordinationBinding
from wiki_core.repository_reader import RepositoryReader


SNAPSHOT = 'docs/references/ext-workspace/tree'
DOCUMENT = f'{SNAPSHOT}/team/AGENTS.md'


def git(root, *args):
    return subprocess.check_output(
        ['git', '-C', str(root), *args], stderr=subprocess.PIPE
    ).decode().strip()


def write(root, path, text='# Synthetic document\n'):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding='utf-8')


def commit(root, config):
    write(root, 'wiki.config.yaml', yaml.safe_dump(config))
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'Synthetic context policy')
    return revision(root, 'HEAD')


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, 'init', '-q')
    git(tmp_path, 'config', 'user.name', 'Synthetic')
    git(tmp_path, 'config', 'user.email', 'synthetic@example.invalid')
    for path in ('AGENTS.md', 'memories/index.md', 'memories/team/AGENTS.md',
                 'memories/team/index.md', f'{SNAPSHOT}/AGENTS.md',
                 f'{SNAPSHOT}/README.md', DOCUMENT):
        write(tmp_path, path)
    grants = {'read': ['self'], 'write': ['self'], 'capabilities': [],
              'deny': {}, 'publication': []}
    config = {'repo_id': 'synthetic', 'context_access': {
        folder: {'owner': 'Operator', 'policy': copy.deepcopy(grants)}
        for folder in ('.', 'memories/team')}}
    commit(tmp_path, config)
    return tmp_path, config


def connection(policy, path=DOCUMENT, consumer='.'):
    return policy._connection(policy.owner_of(path), consumer, path,
                              'interpretation', 'context', qualified=False)


def approve(root, config):
    sha = commit(root, config)
    git(root, 'update-ref', 'refs/remotes/origin/main', sha)
    return load_policy(root, sha, 'wiki.config.yaml')


def packet(root, policy, path=DOCUMENT, *, content_revision=None,
           entry_folder='.', trusted_binding=None):
    evidence = [{'ref': path, 'producer': policy.owner_of(path),
                 'reason': 'Selected synthetic reference',
                 'use': 'interpretation', 'classification': 'context'}]
    return build_packet(
        root, policy, '.', content_revision or policy.policy_revision,
        evidence, 100000, task_id='synthetic', goal='Inspect selected reference',
        output='proposal', integrator='Operator', entry_folder=entry_folder,
        trusted_binding=trusted_binding,
    )


def test_default_discovers_documentary_snapshot_without_grants(repo):
    root, _config = repo
    policy = _folder_policy_at(root, revision(root, 'HEAD'))
    assert set(policy.contexts) == {'.', 'memories/team', SNAPSHOT}
    assert policy.contexts[SNAPSHOT]['owner'] == 'unassigned'
    assert policy.effective[SNAPSHOT]['read'] == []
    assert policy.owner_of(DOCUMENT) == SNAPSHOT
    assert connection(policy) == 'denied'


def test_explicit_exclusion_restores_real_owner_and_connection(repo):
    root, config = repo
    config['context_discovery'] = {'exclude': [SNAPSHOT]}
    policy = _folder_policy_at(root, commit(root, config))
    assert set(policy.contexts) == {'.', 'memories/team'}
    assert policy.owner_of(DOCUMENT) == '.'
    assert connection(policy) == 'approved'


@pytest.mark.parametrize('discovery', [{}, {'exclude': []}])
def test_empty_discovery_configuration_preserves_default(repo, discovery):
    root, config = repo
    config['context_discovery'] = discovery
    policy = _folder_policy_at(root, commit(root, config))
    assert policy.owner_of(DOCUMENT) == SNAPSHOT
    assert connection(policy) == 'denied'


@pytest.mark.parametrize('instruction', ['AGENTS.md', 'AGENTS.override.md'])
def test_exclusion_covers_subtree_but_not_sibling_prefix(repo, instruction):
    root, config = repo
    (root / SNAPSHOT / 'AGENTS.md').unlink()
    write(root, f'{SNAPSHOT}/{instruction}')
    write(root, f'{SNAPSHOT}/team/index.md')
    sibling = f'{SNAPSHOT}-other'
    write(root, f'{sibling}/{instruction}')
    write(root, f'{sibling}/README.md')
    config['context_access'][sibling] = copy.deepcopy(config['context_access']['memories/team'])
    config['context_discovery'] = {'exclude': [SNAPSHOT]}
    policy = _folder_policy_at(root, commit(root, config))
    assert set(policy.contexts) == {'.', 'memories/team', sibling}
    assert policy.owner_of(DOCUMENT) == '.'
    assert policy.owner_of(f'{sibling}/{instruction}') == sibling
    assert connection(policy, f'{sibling}/{instruction}') == 'pending'


def test_excluded_tree_belongs_to_nearest_remaining_context(repo):
    root, config = repo
    write(root, 'docs/AGENTS.md')
    write(root, 'docs/index.md')
    config['context_access']['docs'] = copy.deepcopy(config['context_access']['memories/team'])
    # The excluded prefix need not itself contain instructions or an index.
    config['context_discovery'] = {'exclude': ['docs/references/ext-workspace']}
    policy = _folder_policy_at(root, commit(root, config))
    assert policy.owner_of(DOCUMENT) == 'docs'
    assert connection(policy, consumer='docs') == 'approved'
    assert connection(policy) == 'pending'


@pytest.mark.parametrize('discovery', [
    None, [], 'docs', {'ignored': []}, {'exclude': None}, {'exclude': 'docs'},
    {'exclude': [False]}, {'exclude': [SNAPSHOT, SNAPSHOT]},
    {'exclude': ['.']}, {'exclude': ['']}, {'exclude': ['/docs']},
    {'exclude': ['docs/../memories']}, {'exclude': ['docs/']},
    {'exclude': ['docs/*']}, {'exclude': ['docs?']},
    {'exclude': ['docs\\references']}, {'exclude': ['docs/\x01']},
])
def test_invalid_discovery_configuration_fails_closed(repo, discovery):
    root, config = repo
    config['context_discovery'] = discovery
    with pytest.raises(PolicyError):
        _folder_policy_at(root, commit(root, config))


@pytest.mark.parametrize('declared', [SNAPSHOT, f'{SNAPSHOT}/team'])
def test_exclusion_cannot_hide_explicit_access_even_without_grants(repo, declared):
    root, config = repo
    config['context_discovery'] = {'exclude': [SNAPSHOT]}
    config['context_access'][declared] = {}
    with pytest.raises(PolicyError, match='conflicts with explicit access'):
        _folder_policy_at(root, commit(root, config))


def test_exclusion_does_not_skip_unsafe_tree_validation(repo):
    root, config = repo
    config['context_discovery'] = {'exclude': [SNAPSHOT]}
    (root / DOCUMENT).unlink()
    (root / DOCUMENT).symlink_to('../AGENTS.md')
    with pytest.raises(PolicyError, match='unsafe context tree entry'):
        _folder_policy_at(root, commit(root, config))


def test_exclusion_allows_selected_root_owned_packet_and_keeps_instruction_chain(repo):
    root, config = repo
    write(root, 'README.md')
    config['context_discovery'] = {'exclude': [SNAPSHOT]}
    policy = approve(root, config)
    result = packet(root, policy)
    selected = next(item for item in result['inputs'] if item['ref'] == DOCUMENT)
    assert selected['producer'] == '.'
    assert selected['text'] == '# Synthetic document\n'
    assert {item['ref'] for item in result['inputs']} == {'AGENTS.md', 'README.md', DOCUMENT}
    # Excluding ownership is not permission to omit physical entry instructions.
    entered = packet(root, policy, entry_folder=f'{SNAPSHOT}/team')
    assert {item['ref'] for item in entered['inputs'] if item['kind'] == 'mandatory'} == {
        'AGENTS.md', f'{SNAPSHOT}/AGENTS.md', DOCUMENT,
    }


def test_exclusion_preserves_read_denies_before_selected_body(repo, monkeypatch):
    root, config = repo
    write(root, 'README.md')
    config['context_discovery'] = {'exclude': [SNAPSHOT]}
    config['context_access']['.']['policy']['deny'] = {'read': [DOCUMENT]}
    policy = approve(root, config)
    opened = []
    original = RepositoryReader.read

    def read(self, path, **kwargs):
        opened.append(path)
        return original(self, path, **kwargs)

    monkeypatch.setattr(RepositoryReader, 'read', read)
    assert connection(policy) == 'denied'
    with pytest.raises(PolicyError, match='connection denied'):
        packet(root, policy)
    assert DOCUMENT not in opened


def test_exclusions_use_approved_revision_and_do_not_reauthorize_history(repo, monkeypatch):
    root, config = repo
    write(root, 'README.md')
    before = approve(root, config)
    config['context_discovery'] = {'exclude': [SNAPSHOT]}
    write(root, 'wiki.config.yaml', yaml.safe_dump(config))
    assert before.fresh().owner_of(DOCUMENT) == SNAPSHOT
    candidate = commit(root, config)
    assert before.fresh().owner_of(DOCUMENT) == SNAPSHOT
    with pytest.raises(PolicyError, match='not current trusted approval'):
        load_policy(root, candidate, 'wiki.config.yaml')
    git(root, 'update-ref', 'refs/remotes/origin/main', candidate)
    current = load_policy(root, candidate, 'wiki.config.yaml')
    assert current.owner_of(DOCUMENT) == '.'
    old = historical_policy(current, before.policy_revision, authority_format='folder')
    assert old.owner_of(DOCUMENT) == SNAPSHOT
    with pytest.raises(PolicyError, match='not current trusted approval'):
        before.fresh()
    opened = []
    original = RepositoryReader.read

    def read(self, path, **kwargs):
        opened.append(path)
        return original(self, path, **kwargs)

    monkeypatch.setattr(RepositoryReader, 'read', read)
    with pytest.raises(PolicyError, match='historical evidence read not authorized'):
        packet(root, current, content_revision=before.policy_revision)
    assert DOCUMENT not in opened


def test_wide_child_requires_wide_ancestors_but_siblings_remain_narrow(repo):
    root, config = repo
    parent, child, sibling = 'memories/org', 'memories/org/eng', 'memories/org/ops'
    for folder in (parent, child, sibling):
        write(root, f'{folder}/AGENTS.md')
        write(root, f'{folder}/index.md')
        config['context_access'][folder] = copy.deepcopy(config['context_access']['memories/team'])
    config['context_access'][child]['policy']['read'] = ['.']
    with pytest.raises(PolicyError, match='child widens read'):
        _folder_policy_at(root, commit(root, config))
    config['context_access'][parent]['policy']['read'] = ['.']
    policy = _folder_policy_at(root, commit(root, config))
    target = 'memories/team/index.md'
    assert policy._permits_unqualified(parent, 'read', target)
    assert policy._permits_unqualified(child, 'read', target)
    assert not policy._permits_unqualified(sibling, 'read', target)
    assert policy.effective[child]['write'] == [child]
    assert connection(policy, target, child) == 'pending'


def test_root_read_requires_exact_bilateral_connections_for_foreign_packet(repo, monkeypatch):
    root, config = repo
    write(root, 'README.md')
    target = 'memories/team/report.md'
    write(root, target, '# Synthetic report\n')
    rule = {'from_context': 'memories/team', 'to_context': '.', 'selector': target,
            'use': 'interpretation', 'classification': 'context', 'expires': '2099-01-01'}
    # A producer also needs its explicitly authorized mandatory ancestor input.
    ancestor = {**rule, 'from_context': '.', 'to_context': 'memories/team', 'selector': 'AGENTS.md'}
    config['context_access']['.']['exports'] = [ancestor]
    config['context_access']['memories/team']['imports'] = [copy.deepcopy(ancestor)]
    config['context_access']['memories/team']['policy']['read'] = ['self', 'AGENTS.md']
    binding = CoordinationBinding(('.', 'memories/team'), 'refs/remotes/origin/main')
    opened = []
    original = RepositoryReader.read

    def read(self, path, **kwargs):
        opened.append(path)
        return original(self, path, **kwargs)

    monkeypatch.setattr(RepositoryReader, 'read', read)
    for one_sided in (False, True):
        config['context_access']['.']['imports'] = [copy.deepcopy(rule)] if one_sided else []
        policy = approve(root, config)
        assert policy._permits_unqualified('.', 'read', target)
        assert connection(policy, target) == 'pending'
        with pytest.raises(PolicyError, match='connection not approved'):
            packet(root, policy, target, trusted_binding=binding)
        assert opened == []
    config['context_access']['memories/team']['exports'] = [copy.deepcopy(rule)]
    policy = approve(root, config)
    assert connection(policy, target) == 'approved'
    result = packet(root, policy, target, trusted_binding=binding)
    assert next(item for item in result['inputs'] if item['ref'] == target)['text'] == '# Synthetic report\n'
    assert connection(policy, 'memories/team/index.md') == 'pending'
    # A directory selector does not authorize its descendants.
    rule['selector'] = 'memories/team'
    config['context_access']['.']['imports'] = [copy.deepcopy(rule)]
    config['context_access']['memories/team']['exports'] = [copy.deepcopy(rule)]
    assert connection(approve(root, config), target) == 'pending'
    rule['selector'] = 'memories/team/*.md'
    config['context_access']['.']['imports'] = [rule]
    with pytest.raises(PolicyError, match='invalid relative path'):
        _folder_policy_at(root, commit(root, config))
