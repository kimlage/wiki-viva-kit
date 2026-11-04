"""Security regressions for v2 composition, replay and proposal boundaries."""
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tests.test_folder_policy_v2 import project, put, git, commit, proposal_v2
from wiki_core.context_policy import PolicyError
from wiki_core.folder_impact_v2 import FolderImpactError, assess_folder_source_v2
from wiki_core.folder_integration_v2 import FolderIntegrationError, preflight_folder_v2
from wiki_core.folder_packet_v2 import build_folder_packet_v2
from wiki_core.folder_policy_v2 import load_folder_policy_v2
from wiki_core.repository_reader import RepositoryReader


def test_policy_discovery_never_opens_unselected_instructions(project, monkeypatch):
    put(project, 'other/AGENTS.md', 'Unrelated instruction body\n')
    put(project, 'other/index.md', 'Unrelated index body\n')
    commit(project)
    original = RepositoryReader.read
    def spy(self, ref, *args, **kwargs):
        if ref in ('other/AGENTS.md', 'other/index.md'):
            raise AssertionError('unselected content read during discovery')
        return original(self, ref, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    p = load_folder_policy_v2(project, 'HEAD')
    packet = build_folder_packet_v2(project, p, 'a', 20000, index_path='a/index.md', content_revision='HEAD',
                                    task_id='x', goal='x', output='a/out.md', integrator='x')
    assert all(not row['path'].startswith('other/') for row in packet['inputs'])


def test_impact_checks_all_current_inputs_before_any_historical_replay(project, monkeypatch):
    put(project, 'a/first.md', 'First synthetic source\n')
    put(project, 'a/second.md', 'Second synthetic source\n')
    commit(project)
    p = load_folder_policy_v2(project, 'HEAD')
    evidence = [{'path': f'a/{name}.md', 'producer_folder': 'a', 'reason': 'synthetic', 'use': 'interpret',
                 'classification': 'synthetic'} for name in ('first', 'second')]
    packet = build_folder_packet_v2(project, p, 'a', 20000, index_path='a/index.md', content_revision='HEAD', task_id='x', goal='x',
                                    output='a/report.md', integrator='x', evidence=evidence)
    git(project, 'checkout', '-qb', 'wiki/two-sources')
    put(project, 'a/report.md', 'Independent interpretation\n')
    git(project, 'add', '-A'); git(project, 'commit', '-qm', 'reported output')
    git(project, 'checkout', '-q', '-'); git(project, 'merge', '--ff-only', 'wiki/two-sources')
    git(project, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    observed = [{'path': row['path'], 'kind': row['kind'], 'revision': row['revision'], 'sha256': row['sha256'],
                 'section': row.get('section'), 'field': row.get('field')} for row in packet['inputs']]
    result = {'schema_version': 'wiki.folder-task-result/v2', 'status': 'completed', 'task_id': packet['task_id'],
              'context_id': packet['context_id'], 'packet_digest': packet['packet_digest'], 'observed': observed,
              'changes': [{'path': 'a/report.md', 'action': 'created'}]}
    config = project / 'wiki-context-controls.yaml'; data = yaml.safe_load(config.read_text())
    data['controls']['a']['policy']['deny'] = {'read': ['a/second.md']}
    config.write_text(yaml.safe_dump(data)); commit(project)
    p = load_folder_policy_v2(project, 'HEAD')
    original = RepositoryReader.read
    def spy(self, ref, *args, **kwargs):
        if ref == 'a/second.md':
            raise AssertionError('revoked source body read during replay')
        return original(self, ref, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    with pytest.raises(FolderImpactError, match='current input authority unavailable'):
        assess_folder_source_v2(project, p, packet=packet, result=result,
                                target='a/report.md', source='a/first.md')


@pytest.mark.parametrize('change', ['addition', 'removal', 'rename', 'override'])
def test_preflight_refuses_boundaries_before_reading_any_head_body(project, monkeypatch, change):
    p, base, _, packet, result = proposal_v2(project)
    source = project / 'a/aux/b/AGENTS.md'
    if change == 'addition':
        put(project, 'a/new/AGENTS.md', 'New boundary\n')
    elif change == 'removal':
        source.unlink()
    elif change == 'rename':
        source.rename(source.with_name('MOVED.md'))
    else:
        put(project, 'a/new/AGENTS.override.md', 'Override boundary\n')
    git(project, 'add', '-A'); git(project, 'commit', '-qm', 'boundary')
    head = git(project, 'rev-parse', 'HEAD')
    original = RepositoryReader.read
    def spy(self, ref, *args, **kwargs):
        if self.revision == head:
            raise AssertionError('head body read before boundary checks')
        return original(self, ref, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    with pytest.raises(FolderIntegrationError, match='boundary or instructions'):
        preflight_folder_v2(project, p, base=base, head=head, branch='wiki/folder-task', packet=packet, result=result)


@pytest.mark.parametrize('operation', ['modified', 'deleted'])
def test_preflight_requires_full_prior_read_for_existing_output(project, operation):
    p, base, _, packet, result = proposal_v2(project)
    path = project / 'a/source.md'
    if operation == 'deleted': path.unlink()
    else: path.write_text('Modified source without whole read\n')
    git(project, 'add', '-A'); git(project, 'commit', '-qm', 'change existing')
    head = git(project, 'rev-parse', 'HEAD')
    result['changes'].append({'path': 'a/source.md', 'action': operation})
    with pytest.raises(FolderIntegrationError, match='existing output needs a reported whole prior read'):
        preflight_folder_v2(project, p, base=base, head=head, branch='wiki/folder-task', packet=packet, result=result)


def test_unverified_result_does_not_close_unchanged_impact(project):
    put(project, 'a/prior.md', 'Previously existing output\n')
    put(project, 'a/source.md', 'Unchanged source\n')
    commit(project)
    p = load_folder_policy_v2(project, 'HEAD')
    evidence = [{'path': 'a/source.md', 'producer_folder': 'a', 'reason': 'synthetic', 'use': 'interpret', 'classification': 'synthetic'}]
    packet = build_folder_packet_v2(project, p, 'a', 20000, index_path='a/index.md', content_revision='HEAD', task_id='x', goal='x',
                                    output='a/prior.md', integrator='x', evidence=evidence)
    observed = [{'path': row['path'], 'kind': row['kind'], 'revision': row['revision'], 'sha256': row['sha256'],
                 'section': row.get('section'), 'field': row.get('field')} for row in packet['inputs']]
    fabricated = {'schema_version': 'wiki.folder-task-result/v2', 'status': 'completed', 'task_id': packet['task_id'],
                  'context_id': packet['context_id'], 'packet_digest': packet['packet_digest'], 'observed': observed,
                  'changes': [{'path': 'a/prior.md', 'action': 'modified'}]}
    out = assess_folder_source_v2(project, p, packet=packet, result=fabricated, target='a/prior.md', source='a/source.md')
    assert out['state'] == 'verification_pending' and out['candidates']
    assert out['candidates'][0]['verification'] == 'reported_not_independently_verified'


@pytest.mark.parametrize('script,args', [
    ('wiki_folder_packet_v2.py', ['--content-revision','HEAD','--index','a/index.md','--max-bytes','20000','--task-id','x','--goal','x','--output','x','--integrator','x','a']),
    ('wiki_folder_preflight_v2.py', ['--base','HEAD','--head','HEAD','--branch','wiki/x','--packet','x','--result','x']),
    ('wiki_folder_impact_v2.py', ['--packet','x','--result','x','--target','a/x','--source','a/y']),
])
def test_cli_never_accepts_caller_selected_controls(project, script, args):
    put(project, 'alternate.yaml', 'schema_version: wiki.folder-controls/v2\ncontrols: {}\n'); commit(project)
    tool = Path(__file__).resolve().parents[1] / 'scripts' / script
    call = subprocess.run([sys.executable, str(tool), '--repo', str(project), '--approved-revision', 'HEAD',
                           '--controls', 'alternate.yaml', *args], capture_output=True, text=True)
    assert call.returncode != 0 and not call.stdout
    assert 'invalid_arguments' in call.stderr
    with pytest.raises(TypeError):
        load_folder_policy_v2(project, 'HEAD', 'alternate.yaml')
    with pytest.raises(TypeError):
        load_folder_policy_v2(project, 'HEAD', trusted_ref='HEAD')


@pytest.mark.parametrize('operation', ['created', 'modified', 'deleted'])
def test_preflight_rejects_skill_changes_as_normative(project, operation):
    path = 'a/skills/sample/SKILL.md'
    if operation != 'created':
        put(project, path, 'Previously approved skill\n'); commit(project)
    p, base, _, packet, result = proposal_v2(project)
    if operation == 'deleted': (project / path).unlink()
    else: put(project, path, 'New or changed skill\n')
    git(project, 'add', '-A'); git(project, 'commit', '-qm', 'skill change')
    head = git(project, 'rev-parse', 'HEAD')
    result['changes'].append({'path': path, 'action': operation})
    with pytest.raises(FolderIntegrationError, match='boundary or instructions'):
        preflight_folder_v2(project, p, base=base, head=head, branch='wiki/folder-task', packet=packet, result=result)


@pytest.mark.parametrize('body', ['---\npage_type: operational_rule\n---\nRule\n',
                                  '---\npage_type: process\n---\nProcess\n',
                                  'No declared page type\n'])
def test_preflight_fails_closed_for_normative_or_ambiguous_markdown(project, body):
    p, base, _, packet, result = proposal_v2(project)
    path = 'a/new.md'; put(project, path, body)
    git(project, 'add', '-A'); git(project, 'commit', '-qm', 'document')
    result['changes'].append({'path': path, 'action': 'created'})
    with pytest.raises(FolderIntegrationError, match='ambiguous or normative change'):
        preflight_folder_v2(project, p, base=base, head=git(project, 'rev-parse', 'HEAD'),
                            branch='wiki/folder-task', packet=packet, result=result)


@pytest.mark.parametrize('location', ['instruction', 'index', 'evidence'])
@pytest.mark.parametrize('query', ['?X-Goog-Signature=synthetic', '?X%2DGoog%2DSignature=synthetic', '?x=1&amp;X-Goog-Signature=synthetic'])
def test_v2_rejects_encoded_access_urls_without_echoing(project, location, query):
    fake_url = 'https://files.example.invalid/synthetic' + query
    evidence = []
    if location == 'instruction': put(project, 'a/AGENTS.md', fake_url)
    elif location == 'index': put(project, 'a/index.md', fake_url)
    else:
        put(project, 'a/source.md', fake_url)
        evidence = [{'path':'a/source.md','producer_folder':'a','reason':'synthetic',
                     'use':'interpret','classification':'synthetic'}]
    commit(project)
    p = load_folder_policy_v2(project, 'HEAD')
    with pytest.raises(ValueError) as error:
        build_folder_packet_v2(project, p, 'a', 20000, index_path='a/index.md', content_revision='HEAD',
                               task_id='x', goal='x', output='a/out.md', integrator='x', evidence=evidence)
    assert fake_url not in str(error.value)


def test_impact_rechecks_approval_before_returning_unverified_unchanged(project, monkeypatch):
    put(project, 'a/prior.md', 'Prior output\n')
    put(project, 'a/source.md', 'Same source\n'); commit(project)
    p = load_folder_policy_v2(project, 'HEAD')
    evidence = [{'path':'a/source.md','producer_folder':'a','reason':'synthetic','use':'interpret','classification':'synthetic'}]
    packet = build_folder_packet_v2(project, p, 'a', 20000, index_path='a/index.md', content_revision='HEAD', task_id='x', goal='x',
                                    output='a/prior.md', integrator='x', evidence=evidence)
    observed = [{'path':r['path'],'kind':r['kind'],'revision':r['revision'],'sha256':r['sha256'],
                 'section':r.get('section'),'field':r.get('field')} for r in packet['inputs']]
    result = {'schema_version':'wiki.folder-task-result/v2','status':'completed','task_id':'x',
              'context_id':packet['context_id'],'packet_digest':packet['packet_digest'],'observed':observed,
              'changes':[{'path':'a/prior.md','action':'modified'}]}
    tree = git(project, 'rev-parse', 'HEAD^{tree}')
    later = git(project, 'commit-tree', tree, '-p', 'HEAD', '-m', 'synthetic ref move')
    original = RepositoryReader.read
    seen = []
    def spy(self, ref, *args, **kwargs):
        result = original(self, ref, *args, **kwargs)
        if ref == 'a/source.md':
            seen.append(ref)
            if len(seen) == 2: git(project, 'update-ref', 'refs/remotes/origin/main', later)
        return result
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    with pytest.raises(FolderImpactError, match='source or authority unavailable'):
        assess_folder_source_v2(project, p, packet=packet, result=result, target='a/prior.md', source='a/source.md')
    assert len(seen) == 2


@pytest.mark.parametrize('operation', ['modified', 'deleted'])
def test_preflight_accepts_existing_claim_only_with_full_prior_read(project, operation):
    path = 'a/existing.md'
    put(project, path, '---\npage_type: claim\n---\nEarlier interpretation\n'); commit(project)
    base = git(project, 'rev-parse', 'HEAD'); p = load_folder_policy_v2(project, 'HEAD')
    evidence = [{'path': path, 'producer_folder': 'a', 'reason': 'prior output', 'use': 'interpret', 'classification': 'synthetic'}]
    packet = build_folder_packet_v2(project, p, 'a', 20000, index_path='a/index.md', content_revision=base,
                                    task_id='x', goal='x', output=path, integrator='x', evidence=evidence)
    git(project, 'checkout', '-qb', 'wiki/existing-claim')
    if operation == 'deleted': (project / path).unlink()
    else: put(project, path, '---\npage_type: claim\n---\nUpdated interpretation\n')
    git(project, 'add', '-A'); git(project, 'commit', '-qm', 'existing claim')
    observed = [{'path': row['path'], 'kind': row['kind'], 'revision': row['revision'], 'sha256': row['sha256'],
                 'section': row.get('section'), 'field': row.get('field')} for row in packet['inputs']]
    result = {'schema_version': 'wiki.folder-task-result/v2', 'status': 'completed', 'task_id': packet['task_id'],
              'context_id': packet['context_id'], 'packet_digest': packet['packet_digest'], 'observed': observed,
              'changes': [{'path': path, 'action': operation}]}
    outcome = preflight_folder_v2(project, p, base=base, head=git(project, 'rev-parse', 'HEAD'),
                                  branch='wiki/existing-claim', packet=packet, result=result)
    assert outcome['state'] == 'independent_review_required' and outcome['merge'] == 'not_performed'


@pytest.mark.parametrize('script', ['wiki_folder_packet_v2.py', 'wiki_folder_preflight_v2.py',
                                    'wiki_folder_impact_v2.py', 'wiki_folder_context.py'])
def test_context_cli_invalid_arguments_never_echo_sensitive_values(project, script):
    fake = 'https://example.invalid/path?X-Goog-Signature=synthetic'
    tool = Path(__file__).resolve().parents[1] / 'scripts' / script
    call = subprocess.run([sys.executable, str(tool), '--unknown', fake], capture_output=True, text=True)
    assert call.returncode == 2 and not call.stdout
    assert fake not in call.stderr and 'invalid_arguments' in call.stderr


@pytest.mark.parametrize('script,args', [
    ('wiki_folder_packet_v2.py', ['--content-revision','HEAD','--index','a/index.md','--max-bytes','20000','--task-id','x','--goal','x','--output','x','--integrator','x','--evidence','SENSITIVE','a']),
    ('wiki_folder_preflight_v2.py', ['--base','HEAD','--head','HEAD','--branch','wiki/x','--packet','SENSITIVE','--result','x']),
    ('wiki_folder_impact_v2.py', ['--packet','SENSITIVE','--result','x','--target','a/x','--source','a/y']),
])
def test_v2_cli_file_errors_never_echo_sensitive_paths(project, script, args):
    fake = 'https://example.invalid/path?X-Goog-Signature=synthetic'
    tool = Path(__file__).resolve().parents[1] / 'scripts' / script
    actual = [fake if x == 'SENSITIVE' else x for x in args]
    call = subprocess.run([sys.executable, str(tool), '--repo', str(project), '--approved-revision', 'HEAD', *actual],
                          capture_output=True, text=True)
    assert call.returncode != 0 and not call.stdout
    assert fake not in call.stderr and 'operation_failed' in call.stderr


def test_impact_refuses_nonancestor_historical_replay_before_source_body(project, monkeypatch):
    _, _, _, packet, result = proposal_v2(project)
    git(project, 'checkout', '-q', '-'); git(project, 'merge', '--ff-only', 'wiki/folder-task')
    git(project, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    p = load_folder_policy_v2(project, 'HEAD')
    tree = git(project, 'rev-parse', 'HEAD^{tree}')
    unrelated = git(project, 'commit-tree', tree, '-m', 'unrelated history')
    fake_packet = {**packet, 'policy_revision': unrelated}
    original = RepositoryReader.read
    def spy(self, ref, *args, **kwargs):
        if ref == 'a/source.md': raise AssertionError('untrusted historical source read')
        return original(self, ref, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    with pytest.raises(FolderImpactError, match='source or authority unavailable'):
        assess_folder_source_v2(project, p, packet=fake_packet, result=result,
                                target='a/report.md', source='a/source.md', field='amount')
