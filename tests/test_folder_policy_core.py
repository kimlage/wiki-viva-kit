import copy
import subprocess

import pytest
import yaml
import json
import sys
from pathlib import Path
from jsonschema import validate

from wiki_core.context_policy import PolicyError, load_policy, historical_policy
from wiki_core.context_packet import build_packet
from wiki_core.context_integration import preflight, IntegrationError


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE).decode().strip()


def write(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, 'init', '-q')
    git(tmp_path, 'config', 'user.name', 'Synthetic')
    git(tmp_path, 'config', 'user.email', 'synthetic@example.invalid')
    write(tmp_path, 'AGENTS.md', '# Root\n')
    write(tmp_path, 'alpha/AGENTS.md', '# Alpha old\n')
    write(tmp_path, 'alpha/AGENTS.override.md', '# Alpha override\n')
    write(tmp_path, 'alpha/index.md', '# Alpha index\n')
    write(tmp_path, 'alpha/aux/AGENTS.md', '# Auxiliary, no index\n')
    write(tmp_path, 'alpha/child/AGENTS.md', '# Child\n')
    write(tmp_path, 'alpha/child/index.md', '# Child index\n')
    write(tmp_path, 'beta/AGENTS.md', '# Beta\n')
    write(tmp_path, 'beta/index.md', '# Beta index\n')
    grants = {'read': ['self'], 'write': ['self'], 'capabilities': [], 'deny': {}, 'publication': []}
    access = {'.': {'owner': 'root operator', 'policy': copy.deepcopy(grants)},
              'alpha': {'owner': 'alpha operator', 'policy': copy.deepcopy(grants)}}
    write(tmp_path, 'wiki.config.yaml', yaml.safe_dump({'repo_id': 'synthetic', 'context_access': access}))
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-qm', 'approved synthetic tree')
    git(tmp_path, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    return tmp_path


def folder_policy(repo):
    return load_policy(repo, 'HEAD', 'wiki.config.yaml')


def test_physical_contexts_override_and_auxiliary_with_no_grant(repo):
    policy = folder_policy(repo)
    assert set(policy.contexts) == {'.', 'alpha', 'alpha/child', 'beta'}
    assert [c['id'] for c in policy.lineage('alpha/child')] == ['.', 'alpha', 'alpha/child']
    assert policy.contexts['alpha']['instructions'] == ['alpha/AGENTS.override.md']
    assert policy.owner_of('alpha/aux/data.md') == 'alpha'
    assert policy.owner_of('alpha/child/data.md') == 'alpha/child'
    # Discovery alone supplies no grants before authorized body qualification.
    assert not policy.permits('alpha', 'read', 'alpha/data.md')
    assert not policy.permits('alpha/child', 'read', 'alpha/child/data.md')
    assert not policy.permits('beta', 'read', 'beta/data.md')
    assert policy.connection('alpha/child', 'alpha', 'alpha/child/data.md', 'interpret', 'internal') == 'denied'
    assert policy.format_version == 'folder'
    with pytest.raises(PolicyError, match='entry folder required'):
        build_packet(repo, policy, 'alpha', 'HEAD', [], 100000,
                     task_id='x', goal='x', output='x', integrator='x')


def test_working_tree_changes_are_not_an_approved_hierarchy(repo):
    original = folder_policy(repo)
    write(repo, 'alpha/child/AGENTS.override.md', '# Unapproved\n')
    write(repo, 'alpha/aux/index.md', '# Unapproved index\n')
    again = folder_policy(repo)
    assert again.contexts == original.contexts
    assert again.contexts['alpha/child']['instructions'] == ['alpha/child/AGENTS.md']


def test_access_requires_exact_bilateral_rule_without_a_second_tree(repo):
    config = yaml.safe_load((repo / 'wiki.config.yaml').read_text())
    rule = {'from_context': 'alpha', 'to_context': '.', 'selector': 'alpha/a.md',
            'use': 'interpret', 'classification': 'internal', 'expires': '2099-01-01'}
    config['context_access']['.']['imports'] = [rule]
    config['context_access']['alpha']['exports'] = [copy.deepcopy(rule)]
    write(repo, 'wiki.config.yaml', yaml.safe_dump(config))
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'explicit connection'); git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    policy = folder_policy(repo)
    # Access rules are not activated by metadata discovery alone.
    assert policy.connection('alpha', '.', 'alpha/a.md', 'interpret', 'internal') == 'denied'
    assert policy.connection('beta', '.', 'beta/a.md', 'interpret', 'internal') == 'denied'


def test_access_configuration_cannot_redeclare_hierarchy(repo):
    config = yaml.safe_load((repo / 'wiki.config.yaml').read_text())
    config['context_access']['alpha']['parent'] = '.'
    write(repo, 'wiki.config.yaml', yaml.safe_dump(config))
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'invalid hierarchy'); git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    with pytest.raises(PolicyError, match='context access fields'): folder_policy(repo)


def test_missing_owner_and_stale_scope_are_refused(repo):
    grants = {'read': ['self']}
    write(repo, 'wiki.config.yaml', yaml.safe_dump({'context_access': {'beta': {'policy': grants}}}))
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'owner absent'); git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    with pytest.raises(PolicyError, match='explicit owner'): folder_policy(repo)
    write(repo, 'wiki.config.yaml', yaml.safe_dump({'context_access': {'missing': {'owner': 'nobody'}}}))
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'stale selector'); git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    with pytest.raises(PolicyError, match='no context folder'): folder_policy(repo)


def test_current_approval_must_remain_pinned(repo):
    policy = folder_policy(repo)
    write(repo, 'new.md', '# change\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'new revision'); git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    with pytest.raises(PolicyError, match='not current trusted approval'): policy.fresh()


def test_tracked_symlink_cannot_define_context(repo):
    path = repo / 'bad' / 'AGENTS.md'
    path.parent.mkdir()
    path.symlink_to('../AGENTS.md')
    write(repo, 'bad/index.md', '# Bad\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'invalid instruction'); git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    with pytest.raises(PolicyError, match='unsafe context tree entry'): folder_policy(repo)


def enable_alpha(repo):
    config = yaml.safe_load((repo / 'wiki.config.yaml').read_text())
    config['context_access']['alpha']['policy']['read'] = ['.']
    rule = {'from_context': '.', 'to_context': 'alpha', 'selector': 'AGENTS.md',
            'use': 'interpretation', 'classification': 'context', 'expires': '2099-01-01'}
    config['context_access']['.']['exports'] = [rule]
    config['context_access']['alpha']['imports'] = [copy.deepcopy(rule)]
    write(repo, 'wiki.config.yaml', yaml.safe_dump(config))
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'authorize synthetic task'); git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')


def packet(repo, folder='alpha/aux'):
    return build_packet(repo, folder_policy(repo), 'alpha', 'HEAD', [], 100000,
                        task_id='task', goal='goal', output='output', integrator='operator',
                        entry_folder=folder)


def test_folder_packet_requires_authorization_before_bodies(repo, monkeypatch):
    from wiki_core.repository_reader import RepositoryReader
    opened = []
    original = RepositoryReader.read
    def spy(self, path, **kwargs):
        opened.append(path)
        return original(self, path, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    with pytest.raises(PolicyError, match='not authorized'):
        packet(repo)
    assert opened == []


def test_folder_packet_binds_auxiliary_chain_and_index(repo):
    enable_alpha(repo)
    value = packet(repo)
    assert value['authority_format'] == 'folder'
    assert value['entry_folder'] == 'alpha/aux'
    assert value['entry_index'] == 'alpha/index.md'
    assert [item['ref'] for item in value['inputs']] == [
        'AGENTS.md', 'alpha/AGENTS.override.md', 'alpha/aux/AGENTS.md', 'alpha/index.md']
    assert 'linked sources not inspected' in value['coverage']['missing']
    schema = json.loads((__import__('pathlib').Path(__file__).resolve().parents[1] /
                         'docs/references/schemas/wiki-task-context-v1.schema.json').read_text())
    validate(value, schema)


def test_empty_override_falls_back_only_after_authorized_read(repo):
    enable_alpha(repo)
    write(repo, 'alpha/AGENTS.override.md', '  \n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'empty override'); git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    result = packet(repo)
    refs = [item['ref'] for item in result['inputs'] if item['kind'] == 'mandatory']
    assert 'alpha/AGENTS.md' in refs
    assert 'alpha/AGENTS.override.md' not in refs
    assert any(item['ref'] == 'alpha/AGENTS.override.md' and item['reason'] == 'qualified context boundary'
               for item in result['inputs'])


def test_empty_index_cannot_qualify_context(repo):
    enable_alpha(repo)
    write(repo, 'alpha/index.md', '  \n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'empty index'); git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    with pytest.raises(PolicyError, match='index empty or unavailable'):
        packet(repo)


def test_nested_git_boundary_refused_before_body_reads(repo, monkeypatch):
    from wiki_core.repository_reader import RepositoryReader
    enable_alpha(repo)
    git(repo / 'alpha', 'init', '-q')
    opened = []
    original = RepositoryReader.read
    def spy(self, path, **kwargs):
        opened.append(path)
        return original(self, path, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    with pytest.raises(PolicyError, match='entry folder unavailable'):
        packet(repo)
    assert opened == []


def test_evidence_under_nested_git_is_not_read(repo, monkeypatch):
    from wiki_core.repository_reader import RepositoryReader
    enable_alpha(repo)
    write(repo, 'alpha/clone/record.md', '# Tracked in parent\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'tracked before clone'); git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    git(repo / 'alpha/clone', 'init', '-q')
    opened = []
    original = RepositoryReader.read
    def spy(self, path, **kwargs):
        opened.append(path)
        return original(self, path, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    evidence = [{'ref': 'alpha/clone/record.md', 'producer': 'alpha',
                 'reason': 'selected', 'use': 'interpretation', 'classification': 'context'}]
    with pytest.raises(PolicyError, match='context body unavailable'):
        build_packet(repo, folder_policy(repo), 'alpha', 'HEAD', evidence, 100000,
                     task_id='task', goal='goal', output='output', integrator='operator',
                     entry_folder='alpha/aux')
    assert 'alpha/clone/record.md' not in opened


def test_preflight_rejects_whole_diff_before_reading_nested_clone(repo, monkeypatch):
    from wiki_core.repository_reader import RepositoryReader
    enable_alpha(repo)
    write(repo, 'alpha/clone/record.md', '# Tracked before clone\n')
    write(repo, 'alpha/a-safe.md', '# Original\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'tracked sources'); git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    policy = folder_policy(repo)
    base = git(repo, 'rev-parse', 'HEAD')
    selected = packet(repo)
    git(repo, 'checkout', '-qb', 'wiki/folder-clone-diff')
    write(repo, 'alpha/clone/record.md', '# Proposed inside clone\n')
    write(repo, 'alpha/a-safe.md', '# Proposed ordinary file\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'two changes')
    head = git(repo, 'rev-parse', 'HEAD')
    git(repo / 'alpha/clone', 'init', '-q')
    result = {'schema_version': 'wiki.task-result/v1', 'status': 'completed',
              'task_id': 'task', 'context_id': 'alpha', 'packet_digest': selected['packet_digest'],
              'changes': [{'path': 'alpha/clone/record.md', 'action': 'modified'},
                          {'path': 'alpha/a-safe.md', 'action': 'modified'}],
              'read_coverage': {'observed_refs': selected['declared_read_set'], 'missing': selected['coverage']['missing']}, 'blockers': []}
    opened = []
    original = RepositoryReader.read
    def spy(self, path, **kwargs):
        opened.append(path)
        return original(self, path, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    with pytest.raises(IntegrationError, match='crosses repository boundary'):
        preflight(repo, policy, context_id='alpha', base=base, head=head,
                  branch='wiki/folder-clone-diff', packet=selected, result=result)
    assert 'alpha/clone/record.md' not in opened
    assert 'alpha/a-safe.md' not in opened


def test_folder_packet_preflight_requires_exact_current_inputs(repo):
    enable_alpha(repo)
    policy = folder_policy(repo)
    base = git(repo, 'rev-parse', 'HEAD')
    selected = packet(repo)
    git(repo, 'checkout', '-qb', 'wiki/folder-task')
    write(repo, 'alpha/output.md', '# Proposed result\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'proposal')
    head = git(repo, 'rev-parse', 'HEAD')
    result = {'schema_version': 'wiki.task-result/v1', 'status': 'completed',
              'task_id': 'task', 'context_id': 'alpha', 'packet_digest': selected['packet_digest'],
              'changes': [{'path': 'alpha/output.md', 'action': 'created'}],
              'read_coverage': {'observed_refs': selected['declared_read_set'], 'missing': selected['coverage']['missing']}, 'blockers': []}
    output = preflight(repo, policy, context_id='alpha', base=base, head=head,
                       branch='wiki/folder-task', packet=selected, result=result)
    assert output['state'] == 'independent_review_required'
    assert output['review'] == output['merge'] == 'not_performed'
    assert output['coverage_missing'] == ['linked sources not inspected']
    schema = json.loads((__import__('pathlib').Path(__file__).resolve().parents[1] /
                         'docs/references/schemas/wiki-context-integration-v1.schema.json').read_text())
    validate(output, schema)
    no_read = copy.deepcopy(result); no_read['read_coverage']['observed_refs'] = []
    with pytest.raises(IntegrationError, match='invalid task result'):
        preflight(repo, policy, context_id='alpha', base=base, head=head,
                  branch='wiki/folder-task', packet=selected, result=no_read)
    no_missing = copy.deepcopy(result); no_missing['read_coverage']['missing'] = []
    with pytest.raises(IntegrationError, match='invalid task result'):
        preflight(repo, policy, context_id='alpha', base=base, head=head,
                  branch='wiki/folder-task', packet=selected, result=no_missing)
    git(repo, 'update-ref', 'refs/remotes/origin/main', head)
    with pytest.raises(ValueError, match='not current trusted approval'):
        preflight(repo, policy, context_id='alpha', base=base, head=head,
                  branch='wiki/folder-task', packet=selected, result=result)


def test_folder_preflight_rejects_config_authority_change(repo):
    enable_alpha(repo)
    policy = folder_policy(repo)
    base = git(repo, 'rev-parse', 'HEAD')
    selected = packet(repo)
    git(repo, 'checkout', '-qb', 'wiki/folder-policy-change')
    with (repo / 'wiki.config.yaml').open('a') as stream: stream.write('\n# policy edit\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'policy proposal')
    head = git(repo, 'rev-parse', 'HEAD')
    result = {'schema_version': 'wiki.task-result/v1', 'status': 'completed',
              'task_id': 'task', 'context_id': 'alpha', 'packet_digest': selected['packet_digest'],
              'changes': [{'path': 'wiki.config.yaml', 'action': 'modified'}],
              'read_coverage': {'observed_refs': selected['declared_read_set'], 'missing': selected['coverage']['missing']}, 'blockers': []}
    with pytest.raises(IntegrationError, match='policy change'):
        preflight(repo, policy, context_id='alpha', base=base, head=head,
                  branch='wiki/folder-policy-change', packet=selected, result=result)


def test_explicit_evidence_reason_may_match_automatic_label(repo):
    enable_alpha(repo)
    write(repo, 'alpha/evidence.md', '# evidence\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'source'); git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    policy = folder_policy(repo)
    base = git(repo, 'rev-parse', 'HEAD')
    evidence = [{'ref': 'alpha/evidence.md', 'producer': 'alpha', 'reason': 'selected context index',
                 'use': 'interpretation', 'classification': 'context'}]
    selected = build_packet(repo, policy, 'alpha', base, evidence, 100000, task_id='task',
                            goal='goal', output='output', integrator='operator', entry_folder='alpha/aux')
    git(repo, 'checkout', '-qb', 'wiki/folder-reason')
    write(repo, 'alpha/output.md', '# result\n'); git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'output')
    result = {'schema_version': 'wiki.task-result/v1', 'status': 'completed', 'task_id': 'task',
              'context_id': 'alpha', 'packet_digest': selected['packet_digest'],
              'changes': [{'path': 'alpha/output.md', 'action': 'created'}],
              'read_coverage': {'observed_refs': selected['declared_read_set'], 'missing': selected['coverage']['missing']}, 'blockers': []}
    assert preflight(repo, policy, context_id='alpha', base=base, head=git(repo, 'rev-parse', 'HEAD'),
                     branch='wiki/folder-reason', packet=selected, result=result)['state'] == 'independent_review_required'


@pytest.mark.parametrize('change', ['delete', 'empty'])
def test_context_index_boundary_change_needs_separate_review(repo, change):
    enable_alpha(repo)
    policy = folder_policy(repo)
    base = git(repo, 'rev-parse', 'HEAD')
    selected = packet(repo)
    git(repo, 'checkout', '-qb', 'wiki/folder-index-change')
    if change == 'delete': (repo / 'alpha/index.md').unlink()
    else: write(repo, 'alpha/index.md', '  \n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'change context boundary')
    result = {'schema_version': 'wiki.task-result/v1', 'status': 'completed', 'task_id': 'task',
              'context_id': 'alpha', 'packet_digest': selected['packet_digest'],
              'changes': [{'path': 'alpha/index.md', 'action': 'deleted' if change == 'delete' else 'modified'}],
              'read_coverage': {'observed_refs': selected['declared_read_set'], 'missing': selected['coverage']['missing']}, 'blockers': []}
    with pytest.raises(IntegrationError, match='context boundary change'):
        preflight(repo, policy, context_id='alpha', base=base, head=git(repo, 'rev-parse', 'HEAD'),
                  branch='wiki/folder-index-change', packet=selected, result=result)


def test_folder_cli_uses_physical_cwd_and_rejects_legacy_new_packet(repo, tmp_path):
    enable_alpha(repo)
    root = Path(__file__).resolve().parents[1]
    request = tmp_path / 'request.json'
    request.write_text(json.dumps({'task_id': 'task', 'goal': 'goal', 'output': 'output',
                                   'integrator': 'operator', 'max_bytes': 100000, 'evidence': []}))
    args = [sys.executable, str(root / 'scripts/wiki_context.py'), '--repo', str(repo),
            '--approved-revision', git(repo, 'rev-parse', 'HEAD'), 'pack', 'alpha',
            '--content-revision', git(repo, 'rev-parse', 'HEAD'), '--request', str(request)]
    completed = subprocess.run(args, cwd=repo / 'alpha/aux', capture_output=True, text=True, check=True)
    output = json.loads(completed.stdout)
    assert output['entry_folder'] == 'alpha/aux'
    assert len(completed.stdout.encode('utf-8')) == output['bytes_used']
    denied = subprocess.run(args[:2] + ['--manifest', 'context.yaml'] + args[2:],
                            cwd=repo / 'alpha/aux', capture_output=True, text=True)
    assert denied.returncode != 0


def test_legacy_history_is_read_without_mapping_old_identity(tmp_path):
    git(tmp_path, 'init', '-q'); git(tmp_path, 'config', 'user.name', 'Synthetic'); git(tmp_path, 'config', 'user.email', 'synthetic@example.invalid')
    legacy = {'schema_version': 'wiki.context/v1', 'id': 'old-root', 'parent': None, 'root': '.',
              'purpose': 'legacy', 'owner': 'operator', 'instructions': [], 'skills': [], 'templates': [],
              'policy': {'read': ['self'], 'write': [], 'capabilities': [], 'deny': {}, 'publication': []},
              'imports': [], 'exports': []}
    write(tmp_path, 'context.yaml', yaml.safe_dump(legacy))
    write(tmp_path, 'wiki.config.yaml', yaml.safe_dump({'repo_id': 'synthetic'}))
    git(tmp_path, 'add', '.'); git(tmp_path, 'commit', '-qm', 'old policy')
    old = git(tmp_path, 'rev-parse', 'HEAD')
    write(tmp_path, 'AGENTS.md', '# Root\n')
    write(tmp_path, 'wiki.config.yaml', yaml.safe_dump({'context_access': {'.': {'owner': 'operator'}}}))
    git(tmp_path, 'add', '.'); git(tmp_path, 'commit', '-qm', 'folder policy'); git(tmp_path, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    current = load_policy(tmp_path, 'HEAD', 'wiki.config.yaml')
    with pytest.raises(PolicyError, match='manifest must be selected'):
        historical_policy(current, old)
    history = historical_policy(current, old, historical_manifest='context.yaml')
    assert set(history.contexts) == {'old-root'}
    assert set(current.contexts) == {'.'}
    # Both files coexist at the new revision. The receipt format, never file
    # presence, chooses which historical policy is reconstructed.
    assert set(historical_policy(current, git(tmp_path, 'rev-parse', 'HEAD'), historical_manifest='context.yaml').contexts) == {'old-root'}
    assert set(historical_policy(current, git(tmp_path, 'rev-parse', 'HEAD'), authority_format='folder').contexts) == {'.'}
    assert history._binding is None
    with pytest.raises(PolicyError, match='unbound'):
        build_packet(tmp_path, history, 'old-root', old, [], 100000,
                     task_id='task', goal='goal', output='output', integrator='operator')
