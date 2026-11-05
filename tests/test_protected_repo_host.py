import datetime as dt
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from tests.test_protected_ingestion import prepared_repo, _result_for, _nested_integrator_repo
from tests.test_folder_policy_core import repo, git, write
from wiki_core.coordination_context import CoordinationBinding
from tests.test_protected_ingestion import prepare, record, consolidate
from wiki_core.repo_host import RepositoryGrant


@pytest.fixture
def configured(prepared_repo):
    root, _ = prepared_repo
    external = root.parent / (root.name + '-independent')
    external.mkdir()
    git(external, 'init', '-q'); git(external, 'config', 'user.name', 'Synthetic')
    git(external, 'config', 'user.email', 'synthetic@example.invalid')
    git(external, 'remote', 'add', 'origin', 'https://example.test/team/independent.git')
    write(external, 'guide.md', '# Synthetic guide\nPrecise Git evidence.\n')
    write(external, 'private-unselected.md', 'SENTINEL SHOULD NEVER BE SELECTED\n')
    git(external, 'add', '.'); git(external, 'commit', '-qm', 'independent selection')
    commit = git(external, 'rev-parse', 'HEAD')
    config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
    config['context_access']['.']['policy']['capabilities'] = ['independent_git.read']
    config['context_access']['.']['policy']['publication'] = ['independent_git.derived_proposal']
    write(root, 'wiki.config.yaml', yaml.safe_dump(config))
    git(root, 'add', 'wiki.config.yaml'); git(root, 'commit', '-qm', 'grant capability')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    revision = git(root, 'rev-parse', 'HEAD')
    grant = RepositoryGrant('guide', external.resolve(), 'example.test/team/independent',
                            commit, 'guide.md', '.', '.', 10000)
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml', (grant,))
    args = dict(context_id='.', approved_revision=revision, entry_folder='.', entry_index='index.md',
                source_ref='source.txt', repository_selection='guide')
    return root, external.resolve(), binding, args


def test_host_exact_selection_complete_journey_and_provenance(configured, monkeypatch):
    root, external, binding, args = configured
    import wiki_core.repository_reader as rr
    original = rr.local_git_tree
    external_calls = []
    def tree(repo_root, *command):
        if repo_root == external:
            external_calls.append(command)
            assert command[-2:] == ('--', ':(literal)guide.md')
        return original(repo_root, *command)
    monkeypatch.setattr(rr, 'local_git_tree', tree)
    prepared = prepare(root, binding, **args, source_context='system')
    request = prepared['request']
    selection = request['repository_context']
    assert 'Use the selected repository_context' in request['instructions']
    assert selection['text'].endswith('Precise Git evidence.\n')
    assert selection['selection_id'] == 'guide' and len(selection['blob']) in (40, 64)
    assert str(external) not in json.dumps(request)
    assert selection['repository_identity'] == 'example.test/team/independent'
    assert external_calls
    ids = {'source_id': prepared['source_id'], 'request_id': prepared['request_id']}
    result = _result_for(request)
    assert record(root, binding, **args, **ids, results=[result])['recorded'] == 1
    target = ('memories/system/ingestion/events/2026-11-04-' +
              hashlib.sha256(prepared['source_id'].encode()).hexdigest() + '-' + prepared['request_id'] + '.md')
    publisher = replace(binding.repository_grants[0], event_target=target)
    publication_host = CoordinationBinding(binding.contexts, binding.trusted_ref, binding.manifest, (publisher,))
    out = consolidate(root, publication_host, **args, **ids, source_page='memories/sources/synthetic.md',
                      event_target=target, date=dt.date(2026, 11, 4))
    event = (root / out['event']).read_text()
    assert selection['document_sha256'] in event and selection['revision'] in event
    assert 'example.test/team/independent' in event and str(external) not in event


def test_record_invalid_repo_page_selection_fails_before_git_body(configured, monkeypatch):
    import wiki_core.repo_host as host
    root, _external, binding, args = configured
    prepared = prepare(root, binding, **args, source_context='system')
    calls = []
    original = host._read_prepared_repo
    def spy(*a, **kw):
        calls.append(True)
        return original(*a, **kw)
    monkeypatch.setattr(host, '_read_prepared_repo', spy)
    selection = {'omit_root_entity': True, 'repository_source_pages': {'missing': 'memories/sources/synthetic.md'}}
    with pytest.raises(ValueError):
        record(root, binding, **args, source_id=prepared['source_id'], request_id=prepared['request_id'],
               context_selection=selection, results=[_result_for(prepared['request'])])
    assert calls == []


def test_all_requested_grants_checked_before_any_repository_git(configured, monkeypatch):
    root, _, binding, args = configured
    import wiki_core.ingest.protected as protected
    monkeypatch.setattr(protected, 'selected_repository', lambda *a, **k: pytest.fail('Git opened before all grants'))
    with pytest.raises(ValueError):
        prepare(root, binding, **{**args, 'repository_selection': ['guide', 'not-granted']}, source_context='system')


def test_repository_source_page_identity_mismatch_blocks_before_git(configured, monkeypatch):
    root, _, binding, args = configured
    write(root, 'memories/sources/wrong.md', '---\npage_id: wrong\npage_type: source\nplatform: repo\n'
        'source_locator: example.test/team/other\n---\n# Wrong source\n')
    git(root, 'add', '.'); git(root, 'commit', '-qm', 'select mismatched source')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    args = {**args, 'approved_revision': git(root, 'rev-parse', 'HEAD'), 'context_selection': {
        'omit_root_entity': True, 'repository_source_pages': {'guide': 'memories/sources/wrong.md'}}}
    import wiki_core.ingest.protected as protected
    monkeypatch.setattr(protected, 'selected_repository', lambda *a, **k: pytest.fail('Git opened for mismatched source'))
    with pytest.raises(ValueError):
        prepare(root, binding, **args, source_context='system')


def test_host_environment_pins_grants_and_readback_hides_paths(configured):
    from wiki_core.coordination_context import capability
    root, external, binding, args = configured
    grant = binding.repository_grants[0]
    config = {'selection_id': grant.selection_id, 'root': str(grant.root), 'identity': grant.identity,
              'revision': grant.revision, 'path': grant.path, 'executor': grant.executor,
              'integrator': grant.integrator, 'max_bytes': grant.max_bytes}
    env = {'WIKI_COORDINATION_ALLOWED_CONTEXTS': '.', 'WIKI_COORDINATION_CONTEXT_MODE': 'folder',
           'WIKI_COORDINATION_REPOSITORY_GRANTS': json.dumps([config])}
    pinned = CoordinationBinding.from_environment(env)
    report = capability(root, pinned)
    assert report['repository_selections'] == [{'selection_id': 'guide', 'executor': '.',
        'integrator': '.', 'publication_configured': False}]
    assert str(external) not in json.dumps(report) and grant.identity not in json.dumps(report)
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_coordination.py'
    command = subprocess.run([sys.executable, str(script), '--root', str(root), '--show-host-binding'],
        env={**os.environ, **env}, text=True, capture_output=True, check=True)
    assert json.loads(command.stdout)['repository_selections'] == report['repository_selections']
    env['WIKI_COORDINATION_REPOSITORY_GRANTS'] = '[{"selection_id":"a","selection_id":"b"}]'
    with pytest.raises(ValueError): CoordinationBinding.from_environment(env)


def test_unselected_missing_repository_does_not_block_host_or_selected_read(configured, monkeypatch):
    root, external, binding, args = configured
    grant = binding.repository_grants[0]
    missing_root = root.parent / (root.name + '-missing')
    def row(selection_id, path, identity, selected_path):
        return {'selection_id': selection_id, 'root': str(path), 'identity': identity,
            'revision': grant.revision, 'path': selected_path, 'executor': '.', 'integrator': '.', 'max_bytes': 10000}
    env = {'WIKI_COORDINATION_ALLOWED_CONTEXTS': '.', 'WIKI_COORDINATION_CONTEXT_MODE': 'folder',
           'WIKI_COORDINATION_REPOSITORY_GRANTS': json.dumps([
               row('guide', external, grant.identity, grant.path),
               row('missing', missing_root, 'example.test/team/missing', 'missing.md')])}
    original_stat = Path.stat
    def guarded(path, *a, **k):
        if path == missing_root: pytest.fail('unselected repository statted')
        return original_stat(path, *a, **k)
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'stat', guarded)
        host = CoordinationBinding.from_environment(env)
        assert prepare(root, host, **args, source_context='system')['request']['repository_context']['selection_id'] == 'guide'
    import wiki_core.ingest.protected as protected
    with monkeypatch.context() as patch:
        patch.setattr(protected, 'selected_repository', lambda *a, **k: pytest.fail('Git opened before all selected storage checked'))
        with pytest.raises(ValueError):
            prepare(root, host, **{**args, 'repository_selection': ['guide', 'missing']}, source_context='system')


def test_selected_repository_root_swap_after_pin_is_denied_before_git(configured, monkeypatch):
    root, external, binding, args = configured
    prepare(root, binding, **args, source_context='system')
    external.rename(external.with_name(external.name + '-preserved'))
    external.mkdir()
    import wiki_core.repo_read as repo_read
    monkeypatch.setattr(repo_read, '_git', lambda *a, **k: pytest.fail('Git opened after root swap'))
    with pytest.raises(ValueError):
        prepare(root, binding, **args, source_context='system')


def test_revocation_during_storage_walk_stops_before_external_git(configured, monkeypatch):
    root, _, binding, args = configured
    write(root, 'advance.md', '# New policy revision\n')
    git(root, 'add', 'advance.md'); git(root, 'commit', '-qm', 'advance')
    next_revision = git(root, 'rev-parse', 'HEAD')
    import wiki_core.repo_host as host
    import wiki_core.repo_read as repo_read
    original = host._storage_identity
    def revoke(*a, **kw):
        result = original(*a, **kw)
        git(root, 'update-ref', 'refs/remotes/origin/main', next_revision)
        return result
    monkeypatch.setattr(host, '_storage_identity', revoke)
    monkeypatch.setattr(repo_read, '_git', lambda *a, **k: pytest.fail('external Git opened after revocation'))
    with pytest.raises(ValueError):
        prepare(root, binding, **args, source_context='system')


@pytest.mark.parametrize('stage', ['prepare', 'inspect'])
def test_storage_changed_between_guard_checks_blocks_cache_open(configured, monkeypatch, stage):
    import sys
    import wiki_core.repo_host as host
    import wiki_core.ingest.protected as protected
    from tests.test_protected_ingestion import protected_source_stage
    from wiki_core.coordination_context import ProtectedCoordinationError
    root, external, binding, args = configured
    prepared = prepare(root, binding, **args, source_context='system')
    result = _result_for(prepared['request'])
    ids = dict(source_id=prepared['source_id'], request_id=prepared['request_id'])
    record(root, binding, **args, **ids, results=[result])
    original_repo, original_scan, original_open = protected._repository, host._storage_identity, Path.open
    state = {'armed': False, 'changed': False, 'opened': False}
    def repo_call(*a, **kw):
        if sys._getframe(1).f_code.co_name == ('guard_cache' if stage == 'prepare' else 'guard') and not state['changed']:
            state['armed'] = True
        return original_repo(*a, **kw)
    def scan(*a, **kw):
        identity = original_scan(*a, **kw)
        if state['armed'] and not state['changed']:
            (external / '.git/objects/synthetic-bad-link').symlink_to(root / 'source.txt')
            state['changed'] = True
        return identity
    def spy(path, *a, **kw):
        if path.parent.name == 'llm-cache':
            state['opened'] = True
        return original_open(path, *a, **kw)
    monkeypatch.setattr(protected, '_repository', repo_call)
    monkeypatch.setattr(host, '_storage_identity', scan)
    monkeypatch.setattr(Path, 'open', spy)
    if stage == 'prepare':
        with pytest.raises(protected.ProtectedPartialError):
            prepare(root, binding, **args, source_context='system')
    else:
        with pytest.raises(ProtectedCoordinationError):
            protected_source_stage(root, binding, 'inspect', {**args, **ids, 'view': 'results',
                'chunk_ids': [result['chunk_id']]})
    assert state['changed'] and not state['opened']


def test_two_explicit_repositories_share_one_bound_request(configured):
    root, external, binding, args = configured
    second = root.parent / (root.name + '-second')
    second.mkdir()
    git(second, 'init', '-q'); git(second, 'config', 'user.name', 'Synthetic')
    git(second, 'config', 'user.email', 'synthetic@example.invalid')
    git(second, 'remote', 'add', 'origin', 'https://example.test/team/second.git')
    write(second, 'selected.md', '# Selected second repository\n')
    git(second, 'add', '.'); git(second, 'commit', '-qm', 'selected')
    second_grant = RepositoryGrant('second', second.resolve(), 'example.test/team/second',
        git(second, 'rev-parse', 'HEAD'), 'selected.md', '.', '.', 10000)
    for name, identity in [('repo1', 'example.test/team/independent'), ('repo2', 'example.test/team/second')]:
        source = 'memories/sources/' + name + '.md'
        write(root, source, '---\npage_id: ' + name + '\npage_type: source\nplatform: repo\nsource_locator: ' + identity + '\n---\n# Source\n')
        write(root, 'memories/' + name + '-candidate.md', '---\npage_id: ' + name + '-candidate\npage_type: note\ninformation_requirements:\n'
            '- target: ' + source + '\n  fields: [body]\n  temporal: current\n  max_age_days: 30\n---\n# Candidate\n')
    git(root, 'add', '.'); git(root, 'commit', '-qm', 'explicit repository sources')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    both = CoordinationBinding(binding.contexts, binding.trusted_ref, binding.manifest,
                               (*binding.repository_grants, second_grant))
    args = {**args, 'approved_revision': git(root, 'rev-parse', 'HEAD'), 'repository_selection': ['second', 'guide'],
        'context_selection': {'omit_root_entity': True, 'repository_source_pages': {
            'guide': 'memories/sources/repo1.md', 'second': 'memories/sources/repo2.md'}}}
    prepared = prepare(root, both, **args, source_context='system')
    rows = prepared['request']['repository_context']
    assert [row['selection_id'] for row in rows] == ['guide', 'second']
    assert {row['repository_identity'] for row in rows} == {'example.test/team/independent', 'example.test/team/second'}
    assert str(external) not in json.dumps(rows) and str(second) not in json.dumps(rows)
    ids = {'source_id': prepared['source_id'], 'request_id': prepared['request_id']}
    assert record(root, both, **args, **ids, results=[_result_for(prepared['request'])])['recorded'] == 1
    target = ('memories/system/ingestion/events/2026-11-04-' +
              hashlib.sha256(prepared['source_id'].encode()).hexdigest() + '-' + prepared['request_id'] + '.md')
    publisher = CoordinationBinding(both.contexts, both.trusted_ref, both.manifest,
        tuple(replace(grant, event_target=target) for grant in both.repository_grants))
    result = consolidate(root, publisher, **args, **ids, source_page='memories/sources/synthetic.md',
        event_target=target, date=dt.date(2026, 11, 4))
    event = (root / result['event']).read_text()
    assert 'example.test/team/independent' in event and 'example.test/team/second' in event
    from wiki_core.ingest.protected import compare_repositories
    write(external, 'guide.md', '# Changed first\n'); git(external, 'add', '.'); git(external, 'commit', '-qm', 'first update')
    write(second, 'selected.md', '# Changed second\n'); git(second, 'add', '.'); git(second, 'commit', '-qm', 'second update')
    current = (replace(binding.repository_grants[0], selection_id='guide-current', revision=git(external, 'rev-parse', 'HEAD')),
               replace(second_grant, selection_id='second-current', revision=git(second, 'rev-parse', 'HEAD')))
    comparer = CoordinationBinding(both.contexts, both.trusted_ref, both.manifest, (*both.repository_grants, *current))
    for old_id, new_id, source, candidate in [('guide', 'guide-current', 'repo1', 'repo1-candidate'),
                                               ('second', 'second-current', 'repo2', 'repo2-candidate')]:
        outcome = compare_repositories(root, comparer, **args, **ids, previous_repository_selection=old_id,
            current_repository_selection=new_id, source_page='memories/sources/' + source + '.md',
            candidates=['memories/' + candidate + '.md'])
        assert outcome['repository_comparison']['changed'] and outcome['candidates'][0]['state'] == 'review_pending'
        assert outcome['candidates'][0]['file_consumption'] == 'unknown'


def test_protected_repo_comparison_only_suggests_selected_relevant_changes(configured, monkeypatch):
    from wiki_core.ingest.protected import compare_repositories
    root, external, binding, args = configured
    source_page = 'memories/sources/synthetic.md'
    write(root, source_page, '---\npage_id: source-synthetic\npage_type: source\nplatform: repo\n'
        'source_locator: example.test/team/independent\n---\n# Source\n')
    write(root, 'memories/candidate.md', '---\npage_id: candidate\npage_type: note\ninformation_requirements:\n'
        '- target: memories/sources/synthetic.md\n  fields: [body]\n  temporal: current\n  max_age_days: 30\n---\n# Candidate\n')
    write(root, 'memories/unrelated.md', '---\npage_id: unrelated\npage_type: note\n---\n# Unrelated\n')
    git(root, 'add', '.'); git(root, 'commit', '-qm', 'selected source and candidates')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    args = {**args, 'approved_revision': git(root, 'rev-parse', 'HEAD'),
            'context_selection': {'omit_root_entity': True, 'source_page': source_page}}
    prepared = prepare(root, binding, **args, source_context='system')
    ids = {'source_id': prepared['source_id'], 'request_id': prepared['request_id']}
    assert record(root, binding, **args, **ids, results=[_result_for(prepared['request'])])['recorded'] == 1
    write(root, 'memories/candidate.md', '# Unapproved working-tree replacement\n')
    write(external, 'unrelated.md', '# unrelated change\n')
    git(external, 'add', '.'); git(external, 'commit', '-qm', 'unrelated')
    new_grant = replace(binding.repository_grants[0], selection_id='current', revision=git(external, 'rev-parse', 'HEAD'))
    host = CoordinationBinding(binding.contexts, binding.trusted_ref, binding.manifest,
                               (*binding.repository_grants, new_grant))
    options = {**args, **ids, 'previous_repository_selection': 'guide', 'current_repository_selection': 'current',
               'source_page': source_page, 'candidates': ['memories/candidate.md', 'memories/unrelated.md']}
    with monkeypatch.context() as patch:
        import wiki_core.ingest.protected as protected
        patch.setattr(protected, 'selected_repository', lambda *a, **k: pytest.fail('Git opened before all grants'))
        with pytest.raises(ValueError):
            compare_repositories(root, binding, **options)
        other = root.parent / (root.name + '-same-origin')
        other.mkdir(); git(other, 'init', '-q')
        foreign = replace(binding.repository_grants[0], selection_id='foreign', root=other.resolve())
        different = CoordinationBinding(binding.contexts, binding.trusted_ref, binding.manifest,
                                        (*binding.repository_grants, foreign))
        with pytest.raises(ValueError):
            compare_repositories(root, different, **{**options, 'current_repository_selection': 'foreign'})
    unrelated = compare_repositories(root, host, **options)
    assert not unrelated['repository_comparison']['changed']
    assert all(row['state'] == 'unknown' for row in unrelated['candidates'])
    write(external, 'guide.md', '# Synthetic guide\nChanged selected evidence.\n')
    git(external, 'add', '.'); git(external, 'commit', '-qm', 'selected change')
    new_grant = replace(new_grant, revision=git(external, 'rev-parse', 'HEAD'))
    host = CoordinationBinding(binding.contexts, binding.trusted_ref, binding.manifest,
                               (*binding.repository_grants, new_grant))
    changed = compare_repositories(root, host, **options)
    assert changed['repository_comparison']['changed']
    assert [row['state'] for row in changed['candidates']] == ['review_pending', 'unknown']
    assert all(row['file_consumption'] == 'unknown' for row in changed['candidates'])
    assert changed['write'] == 'not_performed' and changed['review'] == 'not_performed'


def test_missing_or_wrong_grant_fails_before_any_external_git_or_source(configured, monkeypatch):
    root, external, binding, args = configured
    import wiki_core.repo_read as repo_read
    import wiki_core.ingest.protected as protected
    monkeypatch.setattr(repo_read, '_git', lambda *_a, **_k: pytest.fail('external Git called'))
    monkeypatch.setattr(protected, '_capture', lambda *_a, **_k: pytest.fail('source opened'))
    empty = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    for host, options in [(empty, args), (binding, {**args, 'repository_selection': 'other'})]:
        with pytest.raises(ValueError):
            prepare(root, host, **options, source_context='system')


def test_denied_capability_fails_before_external_git(configured, monkeypatch):
    root, _, binding, args = configured
    config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
    config['context_access']['.']['policy']['capabilities'] = []
    write(root, 'wiki.config.yaml', yaml.safe_dump(config))
    git(root, 'add', 'wiki.config.yaml'); git(root, 'commit', '-qm', 'deny capability')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    args['approved_revision'] = git(root, 'rev-parse', 'HEAD')
    import wiki_core.repo_read as repo_read
    monkeypatch.setattr(repo_read, '_git', lambda *_a, **_k: pytest.fail('external Git called'))
    with pytest.raises(ValueError):
        prepare(root, binding, **args, source_context='system')


def test_nested_executor_needs_its_own_capability_before_external_git(configured, monkeypatch):
    root, _, binding, _ = configured
    revision = _nested_integrator_repo(root)
    grant = binding.repository_grants[0]
    nested = RepositoryGrant(grant.selection_id, grant.root, grant.identity, grant.revision,
                             grant.path, 'alpha', '.', grant.max_bytes)
    host = CoordinationBinding(('alpha', '.'), binding.trusted_ref, binding.manifest, (nested,))
    import wiki_core.repo_read as repo_read
    monkeypatch.setattr(repo_read, '_git', lambda *_a, **_k: pytest.fail('external Git called'))
    with pytest.raises(ValueError):
        prepare(root, host, context_id='alpha', approved_revision=revision,
                entry_folder='alpha', entry_index='alpha/index.md', source_ref='alpha/source.txt',
                source_context='alpha', artifact_context='.', repository_selection='guide')


def test_revocation_after_first_metadata_command_stops_next_git(configured, monkeypatch):
    root, _, binding, args = configured
    import wiki_core.repo_read as repo_read
    original = repo_read._git
    calls = []
    def revoke(repo_root, *argv):
        calls.append(argv)
        if len(calls) > 1:
            pytest.fail('external Git ran after revocation')
        value = original(repo_root, *argv)
        git(root, 'update-ref', 'refs/remotes/origin/main', git(root, 'rev-parse', 'HEAD^'))
        return value
    monkeypatch.setattr(repo_read, '_git', revoke)
    with pytest.raises(ValueError):
        prepare(root, binding, **args, source_context='system')
    assert len(calls) == 1


def test_object_alternates_are_refused_before_external_git(configured, monkeypatch):
    root, external, binding, args = configured
    alternate = external / '.git/objects/info/alternates'
    alternate.parent.mkdir(parents=True, exist_ok=True)
    alternate.write_text('/outside/synthetic/objects\n')
    import wiki_core.repo_read as repo_read
    monkeypatch.setattr(repo_read, '_git', lambda *_a, **_kw: pytest.fail('external Git called'))
    with pytest.raises(ValueError):
        prepare(root, binding, **args, source_context='system')


def test_git_config_include_is_refused_before_external_git(configured, monkeypatch):
    root, external, binding, args = configured
    with (external / '.git/config').open('a') as stream:
        stream.write('\n[include]\n  path = /outside/synthetic/gitconfig\n')
    import wiki_core.repo_read as repo_read
    monkeypatch.setattr(repo_read, '_git', lambda *_a, **_kw: pytest.fail('external Git called'))
    with pytest.raises(ValueError):
        prepare(root, binding, **args, source_context='system')


@pytest.mark.parametrize('kind', ['symlink', 'hardlink'])
def test_redirected_object_storage_is_refused_before_external_git(configured, monkeypatch, kind):
    root, external, binding, args = configured
    objects = external / '.git/objects'
    original = next(path for path in objects.glob('[0-9a-f][0-9a-f]/*') if path.is_file())
    outside = external.parent / (external.name + '-object-copy')
    if kind == 'symlink':
        original.rename(outside)
        original.symlink_to(outside)
    else:
        os.link(original, outside)
    import wiki_core.repo_read as repo_read
    monkeypatch.setattr(repo_read, '_git', lambda *_a, **_kw: pytest.fail('external Git called'))
    with pytest.raises(ValueError):
        prepare(root, binding, **args, source_context='system')


def test_record_without_reselected_grant_never_opens_selected_request(configured, monkeypatch):
    root, _, binding, args = configured
    prepared = prepare(root, binding, **args, source_context='system')
    paths = list((root / 'data/derived/wiki/.wiki-viva-protected/extraction-events').glob('*llm-context-request.json'))
    assert len(paths) == 1
    original = Path.open
    def guarded(path, *a, **kw):
        if path == paths[0]: pytest.fail('bound request opened without selection')
        return original(path, *a, **kw)
    monkeypatch.setattr(Path, 'open', guarded)
    with pytest.raises((ValueError, OSError)):
        record(root, binding, **{**args, 'repository_selection': None}, source_id=prepared['source_id'],
               request_id=prepared['request_id'], results=[_result_for(prepared['request'])])

    old = binding.repository_grants[0]
    changed = RepositoryGrant(old.selection_id, old.root, old.identity, old.revision,
                              'private-unselected.md', old.executor, old.integrator, old.max_bytes)
    changed_host = CoordinationBinding(binding.contexts, binding.trusted_ref, binding.manifest, (changed,))
    with pytest.raises((ValueError, OSError)):
        record(root, changed_host, **args, source_id=prepared['source_id'],
               request_id=prepared['request_id'], results=[_result_for(prepared['request'])])


def test_record_revalidates_repository_storage_after_result_write(configured, monkeypatch):
    from wiki_core.ingest import protected
    root, external, binding, args = configured
    prepared = prepare(root, binding, **args, source_context='system')
    result = _result_for(prepared['request'])
    original = protected._write_once
    def move_repository(*values, **kwargs):
        value = original(*values, **kwargs)
        if values[3].parent.name == 'llm-cache':
            external.rename(external.parent / (external.name + '-moved'))
        return value
    monkeypatch.setattr(protected, '_write_once', move_repository)
    with pytest.raises(protected.ProtectedPartialError):
        record(root, binding, **args, source_id=prepared['source_id'], request_id=prepared['request_id'],
               results=[result])
    assert (root / 'data/derived/wiki/.wiki-viva-protected/llm-cache' / (result['cache_key'] + '.json')).is_file()


def test_consolidation_needs_exact_publication_grant_before_opening_request(configured, monkeypatch):
    root, _, binding, args = configured
    prepared = prepare(root, binding, **args, source_context='system')
    target = ('memories/system/ingestion/events/2026-11-04-' +
              hashlib.sha256(prepared['source_id'].encode()).hexdigest() + '-' + prepared['request_id'] + '.md')
    old_path = next((root / 'data/derived/wiki/.wiki-viva-protected/extraction-events').glob('*llm-context-request.json'))
    original = Path.open
    def guarded(path, *a, **kw):
        if path == old_path: pytest.fail('request opened without exact publication grant')
        return original(path, *a, **kw)
    monkeypatch.setattr(Path, 'open', guarded)
    options = {**args, 'source_id': prepared['source_id'], 'request_id': prepared['request_id'],
               'source_page': 'memories/sources/synthetic.md', 'event_target': target,
               'date': dt.date(2026, 11, 4)}
    wrong = replace(binding.repository_grants[0], event_target='memories/elsewhere.md')
    wrong_host = CoordinationBinding(binding.contexts, binding.trusted_ref, binding.manifest, (wrong,))
    for host in (binding, wrong_host):
        with pytest.raises(ValueError, match='repository publication unavailable'):
            consolidate(root, host, **options)
    assert not (root / target).exists()

    changed = replace(binding.repository_grants[0], path='private-unselected.md', event_target=target)
    changed_host = CoordinationBinding(binding.contexts, binding.trusted_ref, binding.manifest, (changed,))
    with pytest.raises((ValueError, OSError)):
        consolidate(root, changed_host, **options)
    assert not (root / target).exists()


def test_publication_policy_denied_before_request_or_event(configured, monkeypatch):
    root, _, binding, args = configured
    config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
    config['context_access']['.']['policy']['publication'] = []
    write(root, 'wiki.config.yaml', yaml.safe_dump(config))
    git(root, 'add', 'wiki.config.yaml'); git(root, 'commit', '-qm', 'deny publication')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    args['approved_revision'] = git(root, 'rev-parse', 'HEAD')
    prepared = prepare(root, binding, **args, source_context='system')
    target = ('memories/system/ingestion/events/2026-11-04-' +
              hashlib.sha256(prepared['source_id'].encode()).hexdigest() + '-' + prepared['request_id'] + '.md')
    old_path = next((root / 'data/derived/wiki/.wiki-viva-protected/extraction-events').glob('*llm-context-request.json'))
    original = Path.open
    def guarded(path, *a, **kw):
        if path == old_path: pytest.fail('request opened without publication policy')
        return original(path, *a, **kw)
    monkeypatch.setattr(Path, 'open', guarded)
    grant = replace(binding.repository_grants[0], event_target=target)
    host = CoordinationBinding(binding.contexts, binding.trusted_ref, binding.manifest, (grant,))
    with pytest.raises(ValueError, match='repository publication unavailable'):
        consolidate(root, host, **args, source_id=prepared['source_id'], request_id=prepared['request_id'],
                    source_page='memories/sources/synthetic.md', event_target=target, date=dt.date(2026, 11, 4))
    assert not (root / target).exists()


def test_external_content_counts_towards_context_budget_before_effects(configured):
    root, external, binding, args = configured
    write(external, 'guide.md', 'large synthetic context ' * 300)
    git(external, 'add', 'guide.md'); git(external, 'commit', '-qm', 'larger selected context')
    old = binding.repository_grants[0]
    new = RepositoryGrant(old.selection_id, old.root, old.identity, git(external, 'rev-parse', 'HEAD'),
                          old.path, old.executor, old.integrator, old.max_bytes)
    host = CoordinationBinding(binding.contexts, binding.trusted_ref, binding.manifest, (new,))
    with pytest.raises(ValueError, match='byte budget'):
        prepare(root, host, **args, source_context='system', context_max_bytes=4000)
    assert not (root / 'data/derived').exists()
