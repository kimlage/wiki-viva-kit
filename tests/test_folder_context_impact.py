import copy
import subprocess

import pytest
import yaml

from wiki_core.context_impact import ImpactError, assess_impact, report_review
from wiki_core.context_policy import load_policy


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE).decode().strip()


def write(root, path, text):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding='utf-8')


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, 'init', '-q'); git(tmp_path, 'config', 'user.name', 'Synthetic'); git(tmp_path, 'config', 'user.email', 'synthetic@example.invalid')
    write(tmp_path, 'AGENTS.md', '# Root\n'); write(tmp_path, 'index.md', '# Root index\n')
    write(tmp_path, 'alpha/AGENTS.md', '# Alpha\n'); write(tmp_path, 'alpha/index.md', '# Alpha index\n')
    write(tmp_path, 'alpha/source.md', '# Source one\n'); write(tmp_path, 'alpha/result.md', '# Interpretation\n')
    write(tmp_path, 'root-result.md', '# Root interpretation\n')
    root_policy = {'read': ['self'], 'write': ['self'], 'capabilities': [], 'deny': {}, 'publication': []}
    child_policy = {'read': ['.'], 'write': ['self'], 'capabilities': [], 'deny': {}, 'publication': []}
    rule = {'from_context': '.', 'to_context': 'alpha', 'selector': 'AGENTS.md',
            'use': 'interpretation', 'classification': 'context', 'expires': '2099-01-01'}
    access = {'.': {'owner': 'root operator', 'policy': root_policy, 'exports': [rule]},
              'alpha': {'owner': 'alpha operator', 'policy': child_policy, 'imports': [copy.deepcopy(rule)]}}
    write(tmp_path, 'wiki.config.yaml', yaml.safe_dump({'context_access': access}))
    git(tmp_path, 'add', '.'); git(tmp_path, 'commit', '-qm', 'source before'); git(tmp_path, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    return tmp_path


def edge(target='alpha/result.md', source='alpha/source.md', consumed=None):
    return {'edges': [{'type': 'source_ref', 'source': target, 'target': source,
                       'consumed_fields': ['*'], 'consumed_revision': consumed,
                       'use': 'interpret', 'classification': 'internal'}]}


def change(repo, path='alpha/source.md'):
    before = git(repo, 'rev-parse', 'HEAD')
    write(repo, path, '# Source changed\n'); git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'source after')
    git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    return before, git(repo, 'rev-parse', 'HEAD')


def test_folder_impact_and_report_are_review_only(repo):
    before, after = change(repo)
    policy = load_policy(repo, after, 'wiki.config.yaml')
    result = assess_impact(repo, policy, edge(consumed=before), before=before, after=after,
                           destination_context='alpha')
    assert len(result['candidates']) == 1
    candidate = result['candidates'][0]
    assert candidate['state'] == 'review_pending' and candidate['fact_freshness'] == 'not_assessed'
    review = report_review(repo, policy, candidate, disposition='still_valid',
                           reason='synthetic review', evidence_revision=after)
    assert review['verification'] == 'reported_not_verified'
    assert not review['next_impact_allowed']


def test_cross_context_grant_still_requires_requalification(repo, monkeypatch):
    from wiki_core.repository_reader import RepositoryReader
    config = yaml.safe_load((repo / 'wiki.config.yaml').read_text())
    rule = {'from_context': 'alpha', 'to_context': '.', 'selector': 'alpha/source.md',
            'use': 'interpret', 'classification': 'internal', 'expires': '2099-01-01'}
    config['context_access']['alpha']['exports'] = [rule]
    config['context_access']['.']['imports'] = [copy.deepcopy(rule)]
    write(repo, 'wiki.config.yaml', yaml.safe_dump(config))
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'authorize edge'); git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    before, after = change(repo)
    opened = []
    original = RepositoryReader.read
    def spy(self, path, **kwargs):
        opened.append(path)
        return original(self, path, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    with pytest.raises(ImpactError, match='cross-context folder authority requires requalification'):
        assess_impact(repo, load_policy(repo, after, 'wiki.config.yaml'),
                      edge(target='root-result.md', consumed=before), before=before, after=after,
                      destination_context='.')
    assert 'alpha/source.md' not in opened


def test_impact_does_not_read_a_nested_repository(repo, monkeypatch):
    from wiki_core.repository_reader import RepositoryReader
    write(repo, 'alpha/clone/source.md', '# Before\n'); git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'tracked before clone'); git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    before, after = change(repo, 'alpha/clone/source.md')
    git(repo / 'alpha/clone', 'init', '-q')
    opened = []
    original = RepositoryReader.read
    def spy(self, path, **kwargs):
        opened.append(path)
        return original(self, path, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    with pytest.raises(ImpactError, match='selected content unavailable'):
        assess_impact(repo, load_policy(repo, after, 'wiki.config.yaml'),
                      edge(source='alpha/clone/source.md', consumed=before), before=before, after=after,
                      destination_context='alpha')
    assert 'alpha/clone/source.md' not in opened
