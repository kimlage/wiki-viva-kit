import copy

import pytest
import yaml

from tests.test_folder_policy_core import repo, git  # noqa: F401
from wiki_core.context_packet import qualify_folder_context
from wiki_core.context_policy import PolicyError, load_policy
from wiki_core.repository_reader import RepositoryReader


@pytest.mark.parametrize('deny_index', [True, False])
def test_denied_index_is_refused_before_instruction_bodies(repo, monkeypatch, deny_index):
    path = repo / 'wiki.config.yaml'
    config = yaml.safe_load(path.read_text())
    rule = {'from_context': '.', 'to_context': 'alpha', 'selector': 'AGENTS.md',
            'use': 'interpretation', 'classification': 'context', 'expires': '2099-01-01'}
    config['context_access']['.']['exports'] = [copy.deepcopy(rule)]
    config['context_access']['alpha']['imports'] = [copy.deepcopy(rule)]
    config['context_access']['alpha']['policy']['read'] = ['self', 'AGENTS.md']
    if deny_index:
        config['context_access']['alpha']['policy']['deny'] = {'read': ['alpha/index.md']}
    path.write_text(yaml.safe_dump(config))
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'synthetic index grant')
    git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    policy = load_policy(repo, 'HEAD', 'wiki.config.yaml')
    opened = []
    original = RepositoryReader.read
    def observe(reader, ref, *args, **kwargs):
        opened.append(ref)
        return original(reader, ref, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', observe)
    if deny_index:
        with pytest.raises(PolicyError, match='not authorized'):
            qualify_folder_context(repo, policy, 'alpha', 'alpha', 'alpha/index.md', 20000)
        assert opened == []
    else:
        qualify_folder_context(repo, policy, 'alpha', 'alpha', 'alpha/index.md', 20000)
        assert 'AGENTS.md' in opened and 'alpha/index.md' in opened
