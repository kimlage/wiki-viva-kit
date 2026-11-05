import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from wiki_core.context_impact import ImpactError, assess_impact, report_review
from wiki_core.context_policy import load_policy
from wiki_core.context_requirements import assess_approved_impact


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


def test_folder_approved_markdown_requirement_is_selected(repo):
    consumed = git(repo, 'rev-parse', 'HEAD')
    requirement = {'target': 'alpha/source.md', 'fields': ['*'], 'temporal': 'current',
                   'max_age_days': 30, 'consumed_revision': consumed,
                   'use': 'interpret', 'classification': 'internal'}
    page = {'page_id': 'synthetic-interpretation', 'page_type': 'claim',
            'information_requirements': [requirement]}
    write(repo, 'alpha/result.md', '---\n' + yaml.safe_dump(page) + '---\nInterpretation\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'record requirement'); git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    before, after = change(repo)
    result = assess_approved_impact(repo, load_policy(repo, after, 'wiki.config.yaml'),
                                    consumers=['alpha/result.md'], before=before, after=after,
                                    destination_context='alpha')
    assert [row['target'] for row in result['candidates']] == ['alpha/result.md']
    assert result['candidates'][0]['state'] == 'review_pending'


def test_normative_requirement_ignores_unrelated_change_but_blocks_changed_rule(repo):
    write(repo, 'alpha/aux/AGENTS.md', '# Local rule\n')
    git(repo, 'add', 'alpha/aux/AGENTS.md'); git(repo, 'commit', '-qm', 'local rule'); git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    old = git(repo, 'rev-parse', 'HEAD')
    req = {'target': 'alpha/aux/AGENTS.md', 'fields': ['*'], 'temporal': 'current',
           'max_age_days': 30, 'consumed_revision': old, 'use': 'normative',
           'classification': 'context', 'source_kind': 'mandatory', 'authority_format': 'folder',
           'entry_folder': 'alpha/aux', 'entry_index': 'alpha/index.md'}
    graph = {'edges': [{'type': 'operational_prerequisite', 'field': 'information_requirements',
                        'source': 'alpha/result.md', 'target': req['target'], 'requirement': req}]}
    write(repo, 'beta/unrelated.md', '# unrelated\n'); git(repo, 'add', 'beta/unrelated.md'); git(repo, 'commit', '-qm', 'unrelated'); git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    current = git(repo, 'rev-parse', 'HEAD')
    output = assess_impact(repo, load_policy(repo, current, 'wiki.config.yaml'), graph,
                           before=old, after=current, destination_context='alpha')
    assert output['candidates'] == []
    write(repo, req['target'], '# Changed local rule\n'); git(repo, 'add', req['target']); git(repo, 'commit', '-qm', 'rule changed'); git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    current = git(repo, 'rev-parse', 'HEAD')
    with pytest.raises(ImpactError, match='review pending'):
        assess_impact(repo, load_policy(repo, current, 'wiki.config.yaml'), graph,
                      before=old, after=current, destination_context='alpha')


def test_folder_impact_cli_from_context_directory(repo, tmp_path):
    before, after = change(repo)
    graph = tmp_path / 'graph.json'
    graph.write_text(json.dumps(edge(consumed=before)))
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_context_flow.py'
    command = [sys.executable, str(script), '--approved-revision', after, 'impact',
               '--graph', str(graph), '--before', before, '--after', after, '--context', 'alpha']
    completed = subprocess.run(command, cwd=repo / 'alpha', capture_output=True, text=True, check=True)
    assert json.loads(completed.stdout)['candidates'][0]['state'] == 'review_pending'
    git(repo / 'alpha', 'init', '-q')
    nested = subprocess.run(command, cwd=repo / 'alpha', capture_output=True, text=True)
    assert nested.returncode != 0  # Never fall back to the outer wiki.


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


def test_impact_cannot_skip_auxiliary_instructions(repo, monkeypatch):
    from wiki_core.repository_reader import RepositoryReader
    child = 'alpha/aux/child'
    write(repo, 'alpha/aux/AGENTS.md', '# Auxiliary instruction\n')
    write(repo, child + '/AGENTS.md', '# Child instruction\n')
    write(repo, child + '/index.md', '# Child index\n')
    write(repo, child + '/source.md', '# Source before\n')
    write(repo, child + '/result.md', '# Interpretation\n')
    config = yaml.safe_load((repo / 'wiki.config.yaml').read_text())
    def grant(owner, ref):
        return {'from_context': owner, 'to_context': child, 'selector': ref,
                'use': 'interpretation', 'classification': 'context', 'expires': '2099-01-01'}
    grants = [grant('.', 'AGENTS.md'), grant('alpha', 'alpha/AGENTS.md'), grant('alpha', 'alpha/index.md')]
    config['context_access']['.']['exports'].append(grants[0])
    config['context_access']['alpha']['exports'] = grants[1:]
    config['context_access'][child] = {'owner': 'child operator',
        'policy': {'read': ['.'], 'write': ['self'], 'capabilities': [], 'deny': {}, 'publication': []},
        'imports': grants}
    write(repo, 'wiki.config.yaml', yaml.safe_dump(config)); git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'child without auxiliary grant'); git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    before, after = change(repo, child + '/source.md')
    opened = []
    original = RepositoryReader.read
    def spy(self, path, **kwargs):
        opened.append(path)
        return original(self, path, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    with pytest.raises(ImpactError, match='authorized requalification'):
        assess_impact(repo, load_policy(repo, after, 'wiki.config.yaml'),
                      edge(target=child + '/result.md', source=child + '/source.md', consumed=before),
                      before=before, after=after, destination_context=child)
    assert 'alpha/aux/AGENTS.md' not in opened
    auxiliary = grant('alpha', 'alpha/aux/AGENTS.md')
    config['context_access']['alpha']['exports'].append(auxiliary)
    config['context_access'][child]['imports'].append(copy.deepcopy(auxiliary))
    write(repo, 'wiki.config.yaml', yaml.safe_dump(config)); git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'authorize auxiliary'); git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    allowed = git(repo, 'rev-parse', 'HEAD')
    candidate = assess_impact(repo, load_policy(repo, allowed, 'wiki.config.yaml'),
        edge(target=child + '/result.md', source=child + '/source.md', consumed=before),
        before=before, after=allowed, destination_context=child)['candidates'][0]
    config['context_access']['alpha']['exports'].pop()
    config['context_access'][child]['imports'].pop()
    write(repo, 'wiki.config.yaml', yaml.safe_dump(config)); git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'revoke auxiliary'); git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    revoked = git(repo, 'rev-parse', 'HEAD')
    opened.clear()
    with pytest.raises(ImpactError, match='authorized requalification'):
        report_review(repo, load_policy(repo, revoked, 'wiki.config.yaml'), candidate,
                      disposition='still_valid', reason='review', evidence_revision=revoked)
    assert 'alpha/aux/AGENTS.md' not in opened
