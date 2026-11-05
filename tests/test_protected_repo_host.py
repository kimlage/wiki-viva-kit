import datetime as dt
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest
import yaml

from tests.test_protected_ingestion import prepared_repo, _result_for, _nested_integrator_repo
from tests.test_folder_policy_core import repo, git, write
from wiki_core.coordination_context import CoordinationBinding
from wiki_core.ingest.protected import prepare, record, consolidate
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
    assert str(external) not in json.dumps(request) and 'example.test' not in json.dumps(request)
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
    assert 'example.test' not in event and str(external) not in event


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
