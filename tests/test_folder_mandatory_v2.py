"""Public fixtures for explicit canonical references and index selection."""
import subprocess
from pathlib import Path

import pytest
import yaml

from wiki_core.context_packet import build_packet
from wiki_core.context_policy import PolicyError, load_policy
from wiki_core.folder_declarations_v2 import parse_folder_declarations
from wiki_core.folder_packet_v2 import build_folder_packet_v2
from wiki_core.folder_policy_v2 import folder_id, load_folder_policy_v2
from wiki_core.repository_reader import RepositoryReader


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, check=True).stdout.strip()


def put(root, path, text):
    dst = root / path
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(text, encoding='utf-8')


def commit(root):
    git(root, 'add', '-A'); git(root, 'commit', '-qm', 'synthetic fixture')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')


@pytest.fixture
def equivalent_repo(tmp_path):
    git(tmp_path, 'init', '-q'); git(tmp_path, 'config', 'user.name', 'Synthetic')
    git(tmp_path, 'config', 'user.email', 'synthetic@example.invalid')
    put(tmp_path, 'AGENTS.md', '# Project\n\nOrdinary [navigation](docs/unused.md).\n\n'
        '## Wiki v2: mandatory references\n\n- [Contract](docs/contract.md)\n'
        '- [Skill](.skills/common/SKILL.md)\n- [Template](docs/template.md)\n\n'
        '## Wiki v2: indexes\n\n- [Wiki index](memories/index.md)\n')
    put(tmp_path, 'README.md', 'Repository development notes\n')
    put(tmp_path, 'memories/index.md', 'Canonical synthetic global index\n')
    put(tmp_path, 'docs/contract.md', 'Synthetic contract body\n')
    put(tmp_path, '.skills/common/SKILL.md', 'Synthetic shared skill body\n')
    put(tmp_path, 'docs/template.md', 'Synthetic template body\n')
    put(tmp_path, 'a/AGENTS.md', '# Area\n\n## Wiki v2: mandatory references\n\n- [Domain skill](skills/domain/SKILL.md)\n')
    put(tmp_path, 'a/index.md', 'Synthetic selected area index\n')
    put(tmp_path, 'a/skills/domain/SKILL.md', 'Synthetic area skill body\n')
    root_policy = {'read':['self'],'write':['self'],'capabilities':[],'deny':{},'publication':[]}
    root = {'schema_version':'wiki.context/v1','id':'root','parent':None,'root':'.','purpose':'synthetic','owner':'fixture',
            'instructions':['AGENTS.md','docs/contract.md'],'skills':['.skills/common/SKILL.md'],
            'templates':['docs/template.md'],'policy':root_policy,'imports':[],'exports':[]}
    child = {'schema_version':'wiki.context/v1','id':'area','parent':'root','root':'a','purpose':'synthetic','owner':'fixture',
             'instructions':[],'skills':['a/skills/domain/SKILL.md'],'templates':[],
             'policy':{'read':['self'],'write':['self']},'imports':[],'exports':[]}
    controls = {'schema_version':'wiki.folder-controls/v2','controls':{
        '.':{'policy':root_policy,'imports':[],'exports':[]},
        'a':{'policy':child['policy'],'imports':[],'exports':[]}}}
    put(tmp_path, 'context.yaml', yaml.safe_dump(root))
    put(tmp_path, 'a/context.yaml', yaml.safe_dump(child))
    put(tmp_path, 'wiki-context-controls.yaml', yaml.safe_dump(controls))
    commit(tmp_path)
    return tmp_path


def kwargs(index):
    return {'content_revision':'HEAD','index_path':index,'task_id':'fixture','goal':'review',
            'output':'a/result.md','integrator':'independent'}


def test_required_canonical_bodies_match_v1_and_only_selected_index_is_read(equivalent_repo, monkeypatch):
    repo = equivalent_repo
    v1 = load_policy(repo, 'HEAD')
    old = build_packet(repo, v1, 'area', 'HEAD', [], 50000,
                       task_id='fixture', goal='review', output='a/result.md', integrator='independent')
    p = load_folder_policy_v2(repo, 'HEAD')
    original = RepositoryReader.read
    def spy(self, ref, *args, **kwargs):
        if ref == 'memories/index.md': raise AssertionError('unselected global index was read')
        return original(self, ref, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    new = build_folder_packet_v2(repo, p, 'a', 50000, **kwargs('a/index.md'))
    v1_bodies = {item['ref']: (item['text'], item['sha256']) for item in old['inputs'] if item['kind'] == 'mandatory'}
    v2_bodies = {item['path']: (item['text'], item['sha256']) for item in new['inputs'] if item['kind'] in ('instruction','mandatory')}
    assert v1_bodies.items() <= v2_bodies.items()
    assert [x['path'] for x in new['inputs'] if x['kind']=='index'] == ['a/index.md']
    assert 'docs/unused.md' not in v2_bodies


def test_root_requires_explicit_declared_canonical_index(equivalent_repo):
    p = load_folder_policy_v2(equivalent_repo, 'HEAD')
    root = build_folder_packet_v2(equivalent_repo, p, '.', 50000, **kwargs('memories/index.md'))
    assert [row['path'] for row in root['inputs'] if row['kind']=='index'] == ['memories/index.md']
    with pytest.raises(PolicyError, match='not declared'):
        build_folder_packet_v2(equivalent_repo, p, '.', 50000, **kwargs('README.md'))
    with pytest.raises(TypeError):
        build_folder_packet_v2(equivalent_repo, p, '.', 50000, content_revision='HEAD',
                               task_id='x', goal='x', output='x', integrator='x')


def test_cross_owner_mandatory_link_fails_before_body_read(equivalent_repo, monkeypatch):
    agent = equivalent_repo / 'AGENTS.md'
    agent.write_text(agent.read_text().replace('- [Contract](docs/contract.md)',
                     '- [Contract](docs/contract.md)\n- [Other](a/skills/domain/SKILL.md)'))
    commit(equivalent_repo)
    p = load_folder_policy_v2(equivalent_repo, 'HEAD')
    original = RepositoryReader.read
    def spy(self, ref, *args, **kwargs):
        if ref == 'a/skills/domain/SKILL.md': raise AssertionError('cross-owner body read')
        return original(self, ref, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    with pytest.raises(PolicyError, match='another context'):
        build_folder_packet_v2(equivalent_repo, p, 'a', 50000, **kwargs('a/index.md'))


def test_inherited_deny_blocks_mandatory_body_in_v1_and_v2(equivalent_repo, monkeypatch):
    repo = equivalent_repo
    path = repo / 'a/context.yaml'; v1 = yaml.safe_load(path.read_text())
    v1['policy']['deny'] = {'read':['docs/contract.md']}
    path.write_text(yaml.safe_dump(v1))
    control = repo / 'wiki-context-controls.yaml'; v2 = yaml.safe_load(control.read_text())
    v2['controls']['a']['policy']['deny'] = {'read':['docs/contract.md']}
    control.write_text(yaml.safe_dump(v2)); commit(repo)
    old = load_policy(repo, 'HEAD'); new = load_folder_policy_v2(repo, 'HEAD')
    original = RepositoryReader.read
    def spy(self, ref, *args, **kwargs):
        if ref == 'docs/contract.md': raise AssertionError('denied mandatory body read')
        return original(self, ref, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    with pytest.raises(PolicyError, match='read denied'):
        build_packet(repo, old, 'area', 'HEAD', [], 50000, task_id='x', goal='x', output='x', integrator='x')
    with pytest.raises(PolicyError, match='mandatory reference denied'):
        build_folder_packet_v2(repo, new, 'a', 50000, **kwargs('a/index.md'))


def test_mandatory_budget_fails_before_oversize_body_read(equivalent_repo, monkeypatch):
    put(equivalent_repo, 'docs/contract.md', 'X' * 10000); commit(equivalent_repo)
    p = load_folder_policy_v2(equivalent_repo, 'HEAD')
    original = RepositoryReader.read
    def spy(self, ref, *args, **kwargs):
        if ref == 'docs/contract.md': raise AssertionError('oversize mandatory body read')
        return original(self, ref, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    with pytest.raises(PolicyError, match='mandatory content exceeds byte budget'):
        build_folder_packet_v2(equivalent_repo, p, 'a', 5000, **kwargs('a/index.md'))


@pytest.mark.parametrize('entry', ['- [Escape](../../outside.md)', '- [Remote](https://example.invalid/rule)',
                                   '- [Query](doc.md?token=abc)', '- [Encoded](%2e%2e/%2e%2e/outside.md)',
                                   '- [One](a.md) and [Two](b.md)', 'Plain unstructured text'])
def test_bad_or_ambiguous_declarations_fail_closed(entry):
    text = '# Instructions\n\n## Wiki v2: mandatory references\n\n' + entry + '\n'
    with pytest.raises(PolicyError):
        parse_folder_declarations('AGENTS.md', text)


def test_selected_index_section_is_explicit_and_not_the_whole_index(equivalent_repo):
    put(equivalent_repo, 'memories/index.md', '# Global\n\n<!-- wiki:section id=allowed version=1 -->\n## Allowed\nSelected slice\n\n<!-- wiki:section id=other version=1 -->\n## Other\nUnselected slice\n')
    commit(equivalent_repo)
    p = load_folder_policy_v2(equivalent_repo, 'HEAD')
    packet = build_folder_packet_v2(equivalent_repo, p, '.', 50000,
                                    **kwargs('memories/index.md'), index_section='allowed')
    row = next(item for item in packet['inputs'] if item['kind'] == 'index')
    assert row['section'] == 'allowed' and 'Selected slice' in row['text']
    assert 'Unselected slice' not in row['text']


def test_preflight_refuses_mandatory_reference_before_head_body(equivalent_repo, monkeypatch):
    from wiki_core.folder_integration_v2 import preflight_folder_v2, FolderIntegrationError
    repo = equivalent_repo; base = git(repo, 'rev-parse', 'HEAD'); p = load_folder_policy_v2(repo, 'HEAD')
    packet = build_folder_packet_v2(repo, p, '.', 50000, **kwargs('memories/index.md'))
    git(repo, 'checkout', '-qb', 'wiki/rule-change')
    put(repo, 'docs/contract.md', 'Modified rule\n'); git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'rule')
    head = git(repo, 'rev-parse', 'HEAD')
    result = {'schema_version':'wiki.folder-task-result/v2', 'status':'completed', 'task_id':packet['task_id'],
              'context_id':packet['context_id'], 'packet_digest':packet['packet_digest'],
              'observed':[{'path':r['path'],'kind':r['kind'],'revision':r['revision'],'sha256':r['sha256'],
                           'section':r.get('section'),'field':r.get('field')} for r in packet['inputs']],
              'changes':[{'path':'docs/contract.md','action':'modified'}]}
    original = RepositoryReader.read
    def spy(self, ref, *args, **kwargs):
        if self.revision == head: raise AssertionError('HEAD body read before normative boundary')
        return original(self, ref, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    with pytest.raises(FolderIntegrationError, match='boundary or instructions'):
        preflight_folder_v2(repo, p, base=base, head=head, branch='wiki/rule-change', packet=packet, result=result)


def test_impact_rechecks_newly_denied_mandatory_before_historical_replay(equivalent_repo, monkeypatch):
    from wiki_core.folder_impact_v2 import assess_folder_source_v2, FolderImpactError
    repo = equivalent_repo
    put(repo, 'a/source.md', 'Synthetic source\n'); commit(repo)
    p = load_folder_policy_v2(repo, 'HEAD')
    evidence = [{'path':'a/source.md','producer_folder':'a','reason':'synthetic','use':'interpret','classification':'synthetic'}]
    packet = build_folder_packet_v2(repo, p, 'a', 50000, **kwargs('a/index.md'), evidence=evidence)
    git(repo, 'checkout', '-qb', 'wiki/mandatory-impact')
    put(repo, 'a/result.md', '---\npage_type: claim\n---\nInterpretation\n')
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'output')
    result = {'schema_version':'wiki.folder-task-result/v2','status':'completed','task_id':packet['task_id'],
              'context_id':packet['context_id'],'packet_digest':packet['packet_digest'],
              'observed':[{'path':r['path'],'kind':r['kind'],'revision':r['revision'],'sha256':r['sha256'],
                           'section':r.get('section'),'field':r.get('field')} for r in packet['inputs']],
              'changes':[{'path':'a/result.md','action':'created'}]}
    git(repo, 'checkout', '-q', '-'); git(repo, 'merge', '--ff-only', 'wiki/mandatory-impact')
    git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    controls=repo/'wiki-context-controls.yaml'; data=yaml.safe_load(controls.read_text())
    data['controls']['a']['policy']['deny']={'read':['docs/contract.md']}
    controls.write_text(yaml.safe_dump(data)); commit(repo)
    p = load_folder_policy_v2(repo, 'HEAD'); original=RepositoryReader.read
    def spy(self, ref, *args, **kwargs):
        if ref == 'docs/contract.md': raise AssertionError('denied mandatory body read')
        return original(self, ref, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    with pytest.raises(FolderImpactError, match='authority unavailable'):
        assess_folder_source_v2(repo, p, packet=packet, result=result, target='a/result.md', source='a/source.md')


@pytest.mark.parametrize('text', [
    '> ## Wiki v2: mandatory references\n>\n> - [Ignored](other.md)\n',
    '- ## Wiki v2: mandatory references\n  - [Ignored](other.md)\n',
    '```markdown\n## Wiki v2: mandatory references\n\n- [Ignored](other.md)\n```\n',
])
def test_nested_or_fenced_heading_is_not_a_declaration(text):
    assert parse_folder_declarations('AGENTS.md', text) == {'mandatory':[], 'indexes':[]}
