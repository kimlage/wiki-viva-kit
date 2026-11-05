import datetime as dt
import json

import pytest
import yaml

from tests.test_folder_policy_core import repo, write, git
from wiki_core.coordination_context import CoordinationBinding, ProtectedCoordinationError, protected_source_stage
from wiki_core.ingest.protected import prepare, record, consolidate


@pytest.fixture
def prepared_repo(repo):
    write(repo, '.gitignore', 'data/derived/\n')
    write(repo, 'index.md', '# Root index\n')
    write(repo, 'source.txt', 'A small synthetic source for the contextual read.\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'source and root index')
    git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    return repo, git(repo, 'rev-parse', 'HEAD')


def test_prepare_in_authorized_partition(prepared_repo):
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    result = prepare(root, binding, context_id='.', approved_revision=sha,
        entry_folder='.', entry_index='index.md', source_ref='source.txt', source_context='system')
    assert result['request']['block_context_package']['authority_format'] == 'folder'
    assert result['request']['source_authorization']['ref'] == 'source.txt'
    assert len(result['request']['chunks']) == 1


def test_complete_protected_proposal_and_local_search_boundary(prepared_repo):
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md',
                source_ref='source.txt')
    prepared = prepare(root, binding, **args, source_context='system')
    request = prepared['request']
    row = request['chunks'][0]
    sample = json.loads((__import__('pathlib').Path(__file__).parent / 'fixtures/e2e/context_pass_result.sample.json').read_text())
    result = {**sample, **{key: request[key] for key in ('source_id', 'prompt_version', 'schema_version', 'model_profile')},
              **{key: row[key] for key in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')},
              'perspectives_required': request['perspectives_required'], 'perspectives': {}}
    ids = dict(source_id=prepared['source_id'], request_id=prepared['request_id'])
    assert record(root, binding, **args, **ids, results=[result])['recorded'] == 1
    output = consolidate(root, binding, **args, **ids, source_page='source.txt',
        event_target='memories/system/ingestion/events/synthetic.md', date=dt.date(2026, 11, 4))
    assert output['integration'] == 'pending review and incorporation'
    assert (root / output['event']).is_file()
    from wiki_core.find import find
    from wiki_core.config import load_config
    protected = 'data/derived/wiki/.wiki-viva-protected'
    with pytest.raises(ValueError, match='protected selection'):
        find(root, load_config(root), 'synthetic', selections=[protected])


def test_host_binding_is_required_before_source_open(prepared_repo, monkeypatch):
    root, sha = prepared_repo
    payload = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md',
                   source_ref='source.txt', source_context='system')
    from pathlib import Path
    original = Path.open
    def no_source(path, *args, **kwargs):
        if path == root / 'source.txt':
            pytest.fail('source opened before host authorization')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', no_source)
    with pytest.raises(ProtectedCoordinationError):
        protected_source_stage(root, None, 'prepare', payload)
    binding = CoordinationBinding(('alpha',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    with pytest.raises(ProtectedCoordinationError):
        protected_source_stage(root, binding, 'prepare', payload)
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    with pytest.raises(ProtectedCoordinationError):
        protected_source_stage(root, binding, 'prepare', {**payload, 'manifest': 'context.yaml'})


def test_host_stages_are_revision_bound(prepared_repo):
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    payload = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md',
                   source_ref='source.txt', source_context='system')
    output = protected_source_stage(root, binding, 'prepare', payload)['result']
    row = output['request']['chunks'][0]
    sample = json.loads((__import__('pathlib').Path(__file__).parent / 'fixtures/e2e/context_pass_result.sample.json').read_text())
    result = {**sample, **{key: output['request'][key] for key in ('source_id', 'prompt_version', 'schema_version', 'model_profile')},
              **{key: row[key] for key in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')},
              'perspectives_required': [], 'perspectives': {}}
    base = {key: value for key, value in payload.items() if key != 'source_context'}
    base.update(source_id=output['source_id'], request_id=output['request_id'])
    git(root, 'update-ref', '-d', 'refs/remotes/origin/main')
    with pytest.raises(ProtectedCoordinationError):
        protected_source_stage(root, binding, 'record', {**base, 'results': [result]})
    assert not list((root / 'data/derived/wiki/.wiki-viva-protected/llm-cache').glob('*.json'))


def test_child_cannot_write_artifacts_owned_by_root(repo):
    config = yaml.safe_load((repo / 'wiki.config.yaml').read_text())
    rule = {'from_context': '.', 'to_context': 'alpha', 'selector': 'AGENTS.md',
            'use': 'interpretation', 'classification': 'context', 'expires': '2099-01-01'}
    config['context_access']['.']['exports'] = [rule]
    config['context_access']['alpha']['imports'] = [rule]
    config['context_access']['alpha']['policy']['read'] = ['self', 'AGENTS.md']
    write(repo, 'wiki.config.yaml', yaml.safe_dump(config))
    write(repo, '.gitignore', 'data/derived/\n')
    write(repo, 'alpha/source.txt', 'Synthetic authorized alpha input.\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'alpha source and explicit connection')
    git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    sha = git(repo, 'rev-parse', 'HEAD')
    binding = CoordinationBinding(('alpha',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    with pytest.raises(ValueError, match='artifact unavailable'):
        prepare(repo, binding, context_id='alpha', approved_revision=sha,
            entry_folder='alpha', entry_index='alpha/index.md',
            source_ref='alpha/source.txt', source_context='system')
    assert not (repo / 'data/derived/wiki/.wiki-viva-protected').exists()


def test_unignored_cache_blocks_before_source_read(prepared_repo, monkeypatch):
    root, _ = prepared_repo
    (root / '.gitignore').unlink()
    git(root, 'add', '-u')
    git(root, 'commit', '-qm', 'remove derived exclusion')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    sha = git(root, 'rev-parse', 'HEAD')
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    from pathlib import Path
    original = Path.open
    def no_source(path, *args, **kwargs):
        if path == root / 'source.txt':
            pytest.fail('source opened despite unignored cache')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', no_source)
    with pytest.raises(ValueError, match='excluded from Git'):
        prepare(root, binding, context_id='.', approved_revision=sha, entry_folder='.',
                entry_index='index.md', source_ref='source.txt', source_context='system')


def test_authority_revoked_mid_capture_reports_partial(prepared_repo, monkeypatch):
    from wiki_core.ingest import protected
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    original = protected.write_manifest
    def revoke_after_manifest(*args, **kwargs):
        result = original(*args, **kwargs)
        git(root, 'update-ref', '-d', 'refs/remotes/origin/main')
        return result
    monkeypatch.setattr(protected, 'write_manifest', revoke_after_manifest)
    payload = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md',
                   source_ref='source.txt', source_context='system')
    with pytest.raises(ProtectedCoordinationError) as exc:
        protected_source_stage(root, binding, 'prepare', payload)
    assert exc.value.code == 'coordination_partial_effects'
    assert len(list((root / 'data/derived/wiki/.wiki-viva-protected/source-manifests').glob('*.json'))) == 1


def test_same_source_two_contexts_preserves_capture(prepared_repo):
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    first = prepare(root, binding, **args, source_context='system')
    manifest = root / 'data/derived/wiki/.wiki-viva-protected/source-manifests' / (first['source_id'] + '.json')
    original = manifest.read_bytes()
    second = prepare(root, binding, **args, source_context='second')
    assert first['source_id'] == second['source_id']
    assert first['request_id'] != second['request_id']
    assert manifest.read_bytes() == original


def test_compatibility_readers_do_not_open_protected_artifacts(prepared_repo, monkeypatch):
    from pathlib import Path
    from scripts import wiki_consolidate, wiki_gc, wiki_llm_context_pass, wiki_audit, wiki_new_ingest
    from wiki_core.config import load_config
    from wiki_core.find import find
    from wiki_core.paths import WikiPaths
    from wiki_core.quality import _chunk_payloads
    from wiki_core.traversal import is_protected_artifact
    from wiki_core.web import normal_proposal
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    prepared = prepare(root, binding, context_id='.', approved_revision=sha, entry_folder='.',
                       entry_index='index.md', source_ref='source.txt', source_context='system')
    paths = WikiPaths(root, load_config(root))
    base = root / 'data/derived/wiki/.wiki-viva-protected'
    request = next((base / 'extraction-events').glob('*-llm-context-request.json'))
    test_text = base / 'not-for-search.txt'
    test_text.write_text('synthetic hidden marker')
    original = Path.open
    def sentinel(path, *args, **kwargs):
        if is_protected_artifact(path):
            pytest.fail('compatibility route opened protected artifact')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', sentinel)
    with pytest.raises(ValueError):
        wiki_consolidate._request_for(paths, prepared['source_id'], str(request))
    assert wiki_llm_context_pass._emitted_requests(paths) == []
    assert wiki_llm_context_pass._record_results(paths, str(request)) == 2
    with pytest.raises(ValueError, match='protected artifacts'):
        wiki_new_ingest.build_proposal(str(request), 'system', dt.date(2026, 11, 4), 'draft')
    assert _chunk_payloads(paths) == []
    assert wiki_gc.find_orphans(paths, set(), wiki_root=root) == {}
    monkeypatch.setattr(wiki_audit, 'ROOT', root)
    errors = []
    wiki_audit.audit_llm_cache_metadata(errors, paths.config)
    assert errors == []
    assert all('.wiki-viva-protected' not in row['path']
               for row in find(root, paths.config, 'synthetic', selections=['.']).get('hits', []))
    with pytest.raises(normal_proposal.ProposalError):
        normal_proposal.load_material(root, paths.config, {
            'material_path': request.relative_to(root).as_posix(), 'material_sha256': '0' * 64})


def test_protected_component_is_casefolded():
    from pathlib import Path
    from wiki_core.traversal import is_protected_artifact
    assert is_protected_artifact(Path('data/.WIKI-VIVA-PROTECTED/cache.json'))


def test_rewritten_request_cannot_forge_source_chunks(prepared_repo):
    from wiki_core.ingest import protected
    from wiki_core.config import load_config
    from wiki_core.paths import WikiPaths
    from dataclasses import replace
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    prepared = prepare(root, binding, **args, source_context='system')
    forged = json.loads(json.dumps(prepared['request']))
    forged['chunks'][0]['text'] = 'forged synthetic content'
    forged['protected_request_id'] = protected._request_identity(forged)
    config = load_config(root)
    paths = WikiPaths(root, replace(config, paths={**config.paths,
        'derived_root': config.paths['derived_root'] + '/.wiki-viva-protected'}))
    target = protected._request_path(paths, prepared['source_id'], forged['protected_request_id'])
    target.write_text(json.dumps(forged))
    with pytest.raises(ValueError, match='request source changed'):
        record(root, binding, **args, source_id=prepared['source_id'],
               request_id=forged['protected_request_id'], results=[])
