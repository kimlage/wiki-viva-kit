import datetime as dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tests.test_folder_policy_core import repo, write, git
from wiki_core.coordination_context import CoordinationBinding, ProtectedCoordinationError, protected_source_stage as _stage
from wiki_core.ingest.protected import prepare as _prepare, record as _record, consolidate as _consolidate


def prepare(*args, **kwargs):
    return _prepare(*args, **{'context_selection': {'omit_root_entity': True}, **kwargs})


def record(*args, **kwargs):
    return _record(*args, **{'context_selection': {'omit_root_entity': True}, **kwargs})


def consolidate(*args, **kwargs):
    return _consolidate(*args, **{'context_selection': {'omit_root_entity': True}, **kwargs})


def protected_source_stage(root, binding, stage, payload):
    return _stage(root, binding, stage, {'context_selection': {'omit_root_entity': True}, **payload})


@pytest.fixture
def prepared_repo(repo):
    write(repo, '.gitignore', 'data/derived/\n')
    write(repo, 'index.md', '# Root index\n')
    write(repo, 'source.txt', 'A small synthetic source for the contextual read.\n')
    write(repo, 'memories/sources/synthetic.md', '---\npage_id: source-synthetic\npage_type: source\n---\n# Source\n')
    write(repo, 'memories/sources/Source: Example.md', '---\npage_id: source-example\npage_type: source\n---\n# Source\n')
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
    assert result['legacy_coverage'].startswith('shared legacy artifacts not inspected')


def test_complete_protected_proposal_and_local_search_boundary(prepared_repo):
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md',
                source_ref='source.txt')
    source_context = 'system\npage_type: claim'
    prepared = protected_source_stage(root, binding, 'prepare', {**args, 'source_context': source_context})['result']
    request = prepared['request']
    from wiki_core.llm.context_pass import canonical_request_text
    assert request['byte_accounting']['request_bytes'] == len(canonical_request_text(request).encode('utf-8'))
    row = request['chunks'][0]
    sample = json.loads((__import__('pathlib').Path(__file__).parent / 'fixtures/e2e/context_pass_result.sample.json').read_text())
    result = {**sample, **{key: request[key] for key in ('source_id', 'prompt_version', 'schema_version', 'model_profile')},
              **{key: row[key] for key in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')},
              'perspectives_required': request['perspectives_required'], 'perspectives': {}}
    ids = dict(source_id=prepared['source_id'], request_id=prepared['request_id'])
    assert protected_source_stage(root, binding, 'record', {**args, **ids, 'results': [result]})['result']['recorded'] == 1
    event = ('memories/system/ingestion/events/2026-11-04-' +
             hashlib.sha256(prepared['source_id'].encode()).hexdigest() + '-' + prepared['request_id'] + '.md')
    source_page = 'memories/sources/Source: Example.md'
    output = protected_source_stage(root, binding, 'consolidate', {**args, **ids,
        'source_page': source_page, 'event_target': event, 'date': '2026-11-04'})['result']
    assert output['integration'] == 'pending review and incorporation'
    assert (root / output['event']).is_file()
    assert 'source_type: markdown' in (root / output['event']).read_text()
    from wiki_core.frontmatter import parse_frontmatter
    frontmatter, _ = parse_frontmatter(root / output['event'])
    assert frontmatter['context'] == source_context and frontmatter['page_type'] == 'ingestion_event'
    assert frontmatter['moc_parent'] == source_page
    assert frontmatter['protected_provenance']['policy_revision'] == sha
    assert frontmatter['protected_provenance']['source_page_association'] == 'operator_selected_unverified'
    assert 'Source%3A%20Example.md' in (root / output['event']).read_text()
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


def test_physical_index_replaced_before_write_stops_cached_stage(prepared_repo, monkeypatch):
    import wiki_core.ingest.protected as protected
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    original = protected._capture_matches
    def replace_index(*args, **kwargs):
        result = original(*args, **kwargs)
        index = root / 'index.md'
        index.unlink()
        index.symlink_to(root / 'source.txt')
        return result
    monkeypatch.setattr(protected, '_capture_matches', replace_index)
    with pytest.raises(ValueError):
        prepare(root, binding, context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md',
                source_ref='source.txt', source_context='system')
    assert not list((root / 'data/derived/wiki/.wiki-viva-protected').rglob('*.json'))


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
    original = protected._write_once
    def revoke_after_manifest(*args, **kwargs):
        result = original(*args, **kwargs)
        if args[3].parent.name == 'source-manifests':
            git(root, 'update-ref', '-d', 'refs/remotes/origin/main')
        return result
    monkeypatch.setattr(protected, '_write_once', revoke_after_manifest)
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
    from scripts import wiki_consolidate, wiki_gc, wiki_llm_context_pass, wiki_audit, wiki_new_ingest, wiki_export_batch
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
    cache = base / 'llm-cache'
    cache.mkdir()
    (cache / ('a' * 64 + '.json')).write_text('{}')
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
    with pytest.raises(ValueError, match='protected artifacts'):
        wiki_export_batch.build_batch_requests([request], model='synthetic', max_tokens=100, include_cached=True)
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
    from dataclasses import replace
    bad_config = replace(paths.config, paths={**paths.config.paths,
        'derived_root': 'data/derived/wiki/.wiki-viva-protected'})
    bad_paths = WikiPaths(root, bad_config)
    with pytest.raises(ValueError):
        wiki_gc.find_orphans(bad_paths, set(), wiki_root=root)
    with pytest.raises(ValueError):
        _chunk_payloads(bad_paths)
    with pytest.raises(wiki_audit.AuditPathBoundaryError):
        wiki_audit.audit_llm_cache_metadata([], bad_config)
    from wiki_core.index.sqlite import index_source, search_detailed
    with pytest.raises(ValueError):
        index_source(root / 'index.sqlite', next((base / 'chunks').glob('*.json')))
    assert search_detailed(base / 'index.sqlite', 'synthetic')['status'] == 'index_error'


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
    protected.enforce_request_budget(forged,
        context_max_bytes=forged['request_limits']['context_max_bytes'],
        request_max_bytes=forged['request_limits']['request_max_bytes'])
    config = load_config(root)
    paths = WikiPaths(root, replace(config, paths={**config.paths,
        'derived_root': config.paths['derived_root'] + '/.wiki-viva-protected'}))
    target = protected._request_path(paths, prepared['source_id'], forged['protected_request_id'])
    target.write_text(json.dumps(forged))
    with pytest.raises(ValueError, match='request source changed'):
        record(root, binding, **args, source_id=prepared['source_id'],
               request_id=forged['protected_request_id'], results=[])


def test_revocation_after_first_source_open_prevents_reopen(prepared_repo, monkeypatch):
    from pathlib import Path
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    original = Path.open
    opens = []
    class RevokeOnClose:
        def __init__(self, stream): self.stream = stream
        def __enter__(self): return self.stream
        def __exit__(self, *args):
            self.stream.close()
            git(root, 'update-ref', '-d', 'refs/remotes/origin/main')
    def tracked(path, *args, **kwargs):
        if path == root / 'source.txt':
            opens.append(path)
            return RevokeOnClose(original(path, *args, **kwargs))
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', tracked)
    with pytest.raises(ValueError):
        prepare(root, binding, context_id='.', approved_revision=sha, entry_folder='.',
                entry_index='index.md', source_ref='source.txt', source_context='system')
    assert len(opens) == 1
    assert not (root / 'data/derived/wiki/.wiki-viva-protected').exists()


def test_revocation_after_last_request_write_reports_partial(prepared_repo, monkeypatch):
    from wiki_core.ingest import protected
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    original = protected._write_once
    def revoke_after_request(*args, **kwargs):
        result = original(*args, **kwargs)
        if args[3].parent.name == 'extraction-events':
            git(root, 'update-ref', '-d', 'refs/remotes/origin/main')
        return result
    monkeypatch.setattr(protected, '_write_once', revoke_after_request)
    payload = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md',
                   source_ref='source.txt', source_context='system')
    with pytest.raises(ProtectedCoordinationError) as exc:
        protected_source_stage(root, binding, 'prepare', payload)
    assert exc.value.code == 'coordination_partial_effects'
    assert len(list((root / 'data/derived/wiki/.wiki-viva-protected/extraction-events').glob('*.json'))) == 1


def test_event_cannot_be_instruction_file(prepared_repo):
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    prepared = prepare(root, binding, **args, source_context='system')
    with pytest.raises(ValueError, match='event target unavailable'):
        consolidate(root, binding, **args, source_id=prepared['source_id'], request_id=prepared['request_id'],
            source_page='memories/sources/synthetic.md', event_target='memories/AGENTS.md', date=dt.date(2026, 11, 4))
    assert not (root / 'memories/AGENTS.md').exists()


def test_cli_local_operator_prepare_record_consolidate(prepared_repo):
    from pathlib import Path
    root, _ = prepared_repo
    sha = _nested_integrator_repo(root)
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_coordination.py'
    def call(stage, payload):
        completed = subprocess.run([sys.executable, str(script), '--root', str(root),
            '--context-id', 'alpha', '--integrator-context', '.', '--approved-revision', sha, '--source-stage', stage],
            input=json.dumps(payload), text=True, capture_output=True, check=True)
        return json.loads(completed.stdout)['result']
    base = {'entry_folder': 'alpha', 'entry_index': 'alpha/index.md', 'source_ref': 'alpha/source.txt',
            'context_selection': {'omit_root_entity': True}}
    prepared = call('prepare', {**base, 'source_context': 'alpha'})
    request = prepared['request']; row = request['chunks'][0]
    sample = json.loads((Path(__file__).parent / 'fixtures/e2e/context_pass_result.sample.json').read_text())
    result = {**sample, **{key: request[key] for key in ('source_id', 'prompt_version', 'schema_version', 'model_profile')},
              **{key: row[key] for key in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')},
              'perspectives_required': [], 'perspectives': {}}
    ids = {'source_id': prepared['source_id'], 'request_id': prepared['request_id']}
    assert call('record', {**base, **ids, 'results': [result]})['recorded'] == 1
    inspected = call('inspect', {**base, **ids, 'view': 'results', 'chunk_ids': [row['chunk_id']]})
    assert inspected['results'] == [{'chunk_id': row['chunk_id'], 'result': result}]
    repeated = call('prepare', {**base, 'source_context': 'alpha'})
    assert repeated['request_id'] == prepared['request_id']
    assert repeated['request']['chunks'][0]['result_exists'] is True
    event = ('memories/system/ingestion/events/2026-11-04-' +
             hashlib.sha256(prepared['source_id'].encode()).hexdigest() + '-' + prepared['request_id'] + '.md')
    output = call('consolidate', {**base, **ids, 'source_page': 'memories/sources/synthetic.md', 'event_target': event, 'date': '2026-11-04'})
    assert output['integration'] == 'pending review and incorporation'
    assert (root / event).is_file()
    inspected = call('inspect', {**base, **ids, 'view': 'integration', 'candidates': []})
    assert inspected['packet']['source_id'] == prepared['source_id']
    assert inspected['packet']['source_hash_sha256'] == request['source_hash_sha256']
    assert inspected['event_status'] == 'not checked'
    assert inspected['integration'] == 'not assessed'


def test_cli_packet_uses_folder_authority(prepared_repo, tmp_path):
    from pathlib import Path
    root, sha = prepared_repo
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_coordination.py'
    request = tmp_path / 'task.json'
    request.write_text(json.dumps({'task_id': 'synthetic', 'goal': 'read source', 'output': 'proposal',
        'integrator': 'root', 'max_bytes': 100000, 'evidence': []}))
    completed = subprocess.run([sys.executable, str(script), '--root', str(root),
        '--context-id', '.', '--approved-revision', sha, '--packet-request', str(request), '--index', 'index.md'],
        text=True, capture_output=True, check=True)
    output = json.loads(completed.stdout)
    assert output['caller_boundary'] == 'trusted_local_operator'
    assert output['packet']['authority_format'] == 'folder'


def test_valid_unicode_is_preserved_and_invalid_utf8_is_blocked(prepared_repo):
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md',
                source_ref='source.txt', source_context='system')
    text = 'Informação: 漢字 e 你好.\n' * 10
    (root / 'source.txt').write_text(text, encoding='utf-8')
    result = prepare(root, binding, **args)
    assert '漢字 e 你好' in ''.join(row['text'] for row in result['request']['chunks'])
    (root / 'source.txt').write_bytes(b'bad\xffencoding')
    with pytest.raises(ValueError, match='encoding'):
        prepare(root, binding, **args)


def test_final_request_budget_counts_identifier_before_write(prepared_repo):
    from wiki_core.llm.context_pass import canonical_request_text
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md',
                source_ref='source.txt', source_context='system')
    (root / 'source.txt').write_text('synthetic data ' * 1200)
    result = prepare(root, binding, **args, request_max_bytes=50_000)
    request = result['request']
    assert request['byte_accounting']['request_bytes'] == len(canonical_request_text(request).encode('utf-8'))
    assert 10_000 <= request['byte_accounting']['request_bytes'] < 50_000
    count = len(list((root / 'data/derived/wiki/.wiki-viva-protected/extraction-events').glob('*.json')))
    with pytest.raises(ValueError):
        prepare(root, binding, **args, request_max_bytes=request['byte_accounting']['request_bytes'] - 1)
    assert len(list((root / 'data/derived/wiki/.wiki-viva-protected/extraction-events').glob('*.json'))) == count


def test_escaped_content_over_retention_limit_blocks_before_writes(prepared_repo):
    root, sha = prepared_repo
    (root / 'source.txt').write_bytes(b'\x01' * 400_000)
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    with pytest.raises(ValueError, match='retention limit'):
        prepare(root, binding, context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md',
                source_ref='source.txt', source_context='system', request_max_bytes=4_000_000)
    assert not (root / 'data/derived/wiki/.wiki-viva-protected').exists()


def test_invalid_or_missing_source_page_blocks_before_event(prepared_repo):
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    prepared = prepare(root, binding, **args, source_context='system')
    ids = dict(source_id=prepared['source_id'], request_id=prepared['request_id'])
    event = ('memories/system/ingestion/events/2026-11-04-' +
             hashlib.sha256(prepared['source_id'].encode()).hexdigest() + '-' + prepared['request_id'] + '.md')
    for page in ('memories/sources/missing.md', 'memories/sources/bad.md'):
        if page.endswith('bad.md'):
            write(root, page, '---\npage_id: claim-example\npage_type: claim\n---\n# Not a source\n')
        with pytest.raises((ValueError, OSError)):
            consolidate(root, binding, **args, **ids, source_page=page,
                event_target=event, date=dt.date(2026, 11, 4))
    assert not (root / event).exists()


def _nested_integrator_repo(root):
    config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
    root_to_alpha = [
        {'from_context': '.', 'to_context': 'alpha', 'selector': 'AGENTS.md',
         'use': 'interpretation', 'classification': 'context', 'expires': '2099-01-01'},
        {'from_context': '.', 'to_context': 'alpha', 'selector': 'memories/sources/synthetic.md',
         'use': 'interpretation', 'classification': 'artifact', 'expires': '2099-01-01'},
    ]
    alpha_to_root = [
        {'from_context': 'alpha', 'to_context': '.', 'selector': ref,
         'use': 'interpretation', 'classification': classification, 'expires': '2099-01-01'}
        for ref, classification in [('alpha/AGENTS.override.md', 'context'),
                                    ('alpha/index.md', 'context'), ('alpha/source.txt', 'source')]
    ]
    config['context_access']['.']['exports'] = root_to_alpha
    config['context_access']['alpha']['imports'] = root_to_alpha
    config['context_access']['alpha']['exports'] = alpha_to_root
    config['context_access']['.']['imports'] = alpha_to_root
    config['context_access']['alpha']['policy']['read'] = ['self', 'AGENTS.md', 'memories/sources/synthetic.md']
    write(root, 'wiki.config.yaml', yaml.safe_dump(config))
    write(root, 'alpha/source.txt', 'Synthetic nested context source.\n')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'authorized nested integrator')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    return git(root, 'rev-parse', 'HEAD')


def test_nested_context_with_explicit_authorized_integrator(prepared_repo):
    root, _ = prepared_repo
    sha = _nested_integrator_repo(root)
    binding = CoordinationBinding(('alpha', '.'), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='alpha', approved_revision=sha, entry_folder='alpha',
                entry_index='alpha/index.md', source_ref='alpha/source.txt', artifact_context='.')
    prepared = prepare(root, binding, **args, source_context='alpha')
    assert prepared['request']['block_context_package']['context_id'] == 'alpha'
    assert prepared['request']['block_context_package']['integrator'] == '.'
    assert prepared['request']['block_context_package']['additional_readers'] == ['.']
    ids = dict(source_id=prepared['source_id'], request_id=prepared['request_id'])
    record(root, binding, **args, **ids, results=[_result_for(prepared['request'])])
    event = ('memories/system/ingestion/events/2026-11-04-' +
             hashlib.sha256(prepared['source_id'].encode()).hexdigest() + '-' + prepared['request_id'] + '.md')
    output = consolidate(root, binding, **args, **ids, source_page='memories/sources/synthetic.md',
                         event_target=event, date=dt.date(2026, 11, 4))
    assert output['integration'] == 'pending review and incorporation'
    assert (root / event).is_file()


def test_nested_source_packet_preflight_requires_host_bound_additional_reader(prepared_repo):
    from wiki_core.coordination_context import prepare_preflight
    root, _ = prepared_repo
    sha = _nested_integrator_repo(root)
    config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
    proposal_grant = {'from_context': 'alpha', 'to_context': '.', 'selector': 'alpha/proposal.md',
        'use': 'interpretation', 'classification': 'context', 'expires': '2099-01-01'}
    config['context_access']['alpha']['exports'].append(proposal_grant)
    config['context_access']['.']['imports'].append(proposal_grant)
    write(root, 'wiki.config.yaml', yaml.safe_dump(config))
    git(root, 'add', 'wiki.config.yaml'); git(root, 'commit', '-qm', 'authorize integrator proposal')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    sha = git(root, 'rev-parse', 'HEAD')
    binding = CoordinationBinding(('alpha', '.'), 'refs/remotes/origin/main', 'wiki.config.yaml')
    prepared = prepare(root, binding, context_id='alpha', approved_revision=sha, entry_folder='alpha',
        entry_index='alpha/index.md', source_ref='alpha/source.txt', source_context='alpha', artifact_context='.')
    packet = prepared['request']['block_context_package']
    git(root, 'checkout', '-qb', 'wiki/source-preflight')
    write(root, 'alpha/proposal.md', '# Explicit proposal\n')
    git(root, 'add', 'alpha/proposal.md'); git(root, 'commit', '-qm', 'proposal')
    head = git(root, 'rev-parse', 'HEAD')
    result = {'schema_version': 'wiki.task-result/v1', 'status': 'completed', 'task_id': packet['task_id'],
        'context_id': 'alpha', 'packet_digest': packet['packet_digest'],
        'changes': [{'path': 'alpha/proposal.md', 'action': 'created'}], 'blockers': [],
        'read_coverage': {'observed_refs': packet['declared_read_set'], 'missing': packet['coverage']['missing']}}
    payload = {'context_id': 'alpha', 'approved_revision': sha, 'base': sha, 'head': head,
        'branch': 'wiki/source-preflight', 'packet': packet, 'result': result}
    with pytest.raises(ProtectedCoordinationError): prepare_preflight(root, binding, payload)
    with pytest.raises(ProtectedCoordinationError):
        prepare_preflight(root, binding, {**payload, 'additional_readers': ['beta']})
    out = prepare_preflight(root, binding, {**payload, 'additional_readers': ['.']})
    assert out['preflight']['state'] == 'independent_review_required'


def test_record_multiple_chunks_reports_extraction_count(prepared_repo, monkeypatch):
    import time
    import wiki_core.ingest.protected as protected
    root, sha = prepared_repo
    (root / 'source.txt').write_text(''.join(f'Synthetic evidence {i} with bounded detail.\n' for i in range(1200)))
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    prepared = prepare(root, binding, **args, source_context='system')
    request = prepared['request']
    assert len(request['chunks']) >= 3
    sample = json.loads((__import__('pathlib').Path(__file__).parent / 'fixtures/e2e/context_pass_result.sample.json').read_text())
    results = [{**sample, **{key: request[key] for key in ('source_id', 'prompt_version', 'schema_version', 'model_profile')},
        **{key: row[key] for key in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')},
        'perspectives_required': [], 'perspectives': {}} for row in request['chunks']]
    calls = []
    original = protected.extract_captured
    def tracked(*a, **kw):
        calls.append(1)
        return original(*a, **kw)
    monkeypatch.setattr(protected, 'extract_captured', tracked)
    start = time.perf_counter()
    out = record(root, binding, **args, source_id=prepared['source_id'], request_id=prepared['request_id'], results=results)
    print('record_chunks', len(results), 'extractions', len(calls), 'seconds', round(time.perf_counter() - start, 3))
    assert out['recorded'] == len(results)
    assert len(calls) == 1


def test_cached_capture_rehashes_after_request_read_before_result_write(prepared_repo, monkeypatch):
    import wiki_core.ingest.protected as protected
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    prepared = prepare(root, binding, **args, source_context='system')
    result = _result_for(prepared['request'])
    reads = []
    original = protected._read_json
    def mutate_after_request(*values, **kwargs):
        output = original(*values, **kwargs)
        path = values[3]
        if path.name.endswith('-llm-context-request.json'):
            reads.append(1)
            if len(reads) == 1:
                (root / 'source.txt').write_text('Changed after request read.\n')
        return output
    monkeypatch.setattr(protected, '_read_json', mutate_after_request)
    with pytest.raises(ValueError):
        record(root, binding, **args, source_id=prepared['source_id'], request_id=prepared['request_id'], results=[result])
    assert len(reads) == 1
    assert not list((root / 'data/derived/wiki/.wiki-viva-protected/llm-cache').glob('*.json'))


@pytest.mark.parametrize('changed', ['source', 'request', 'ref', 'cache'])
def test_record_batch_stops_after_changed_first_write(prepared_repo, monkeypatch, changed):
    from wiki_core.ingest import protected
    root, sha = prepared_repo
    (root / 'source.txt').write_text(''.join(f'Synthetic evidence {i} with bounded detail.\n' for i in range(500)))
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    first = prepare(root, binding, **args, source_context='system')
    request = first['request']
    assert len(request['chunks']) >= 2
    sample = _result_for(request)
    results = [{**sample, **{key: row[key] for key in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')}}
               for row in request['chunks'][:2]]
    directory = root / 'data/derived/wiki/.wiki-viva-protected'
    request_path = next(directory.rglob('*' + first['request_id'] + '-llm-context-request.json'))
    cache = directory / 'llm-cache'
    write_once = protected._write_once
    writes = []
    def mutate(*values, **kwargs):
        value = write_once(*values, **kwargs)
        if values[3].parent.name == 'llm-cache':
            writes.append(values[3])
            if len(writes) == 1:
                if changed == 'ref':
                    git(root, 'update-ref', '-d', 'refs/remotes/origin/main')
                elif changed == 'cache':
                    moved = directory / 'moved-cache'
                    cache.rename(moved)
                    cache.symlink_to(moved, target_is_directory=True)
                else:
                    target = root / 'source.txt' if changed == 'source' else request_path
                    with target.open('a') as stream:
                        stream.write(' ')
        return value
    monkeypatch.setattr(protected, '_write_once', mutate)
    with pytest.raises(protected.ProtectedPartialError):
        record(root, binding, **args, source_id=first['source_id'], request_id=first['request_id'], results=results)
    assert len(writes) == 1
    saved = directory / ('moved-cache' if changed == 'cache' else 'llm-cache')
    assert (saved / (results[0]['cache_key'] + '.json')).is_file()
    assert not (saved / (results[1]['cache_key'] + '.json')).exists()


@pytest.mark.parametrize('changed', ['source', 'request'])
def test_record_checks_change_after_bound_before_first_write(prepared_repo, monkeypatch, changed):
    from wiki_core.ingest import protected
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    first = prepare(root, binding, **args, source_context='system')
    directory = root / 'data/derived/wiki/.wiki-viva-protected'
    request_path = next(directory.rglob('*' + first['request_id'] + '-llm-context-request.json'))
    original = protected._open_bound
    def mutate(*values, **kwargs):
        value = original(*values, **kwargs)
        target = root / 'source.txt' if changed == 'source' else request_path
        with target.open('a') as stream:
            stream.write(' ')
        return value
    monkeypatch.setattr(protected, '_open_bound', mutate)
    with pytest.raises(ValueError):
        record(root, binding, **args, source_id=first['source_id'], request_id=first['request_id'],
               results=[_result_for(first['request'])])
    assert not list((directory / 'llm-cache').glob('*.json'))


def test_record_revalidates_after_last_full_reconstruction(prepared_repo, monkeypatch):
    from wiki_core.ingest import protected
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    first = prepare(root, binding, **args, source_context='system')
    original = protected._open_bound
    calls = []
    def revoke(*values, **kwargs):
        value = original(*values, **kwargs)
        calls.append(True)
        if len(calls) == 2:
            git(root, 'update-ref', '-d', 'refs/remotes/origin/main')
        return value
    monkeypatch.setattr(protected, '_open_bound', revoke)
    with pytest.raises(protected.ProtectedPartialError):
        record(root, binding, **args, source_id=first['source_id'], request_id=first['request_id'],
               results=[_result_for(first['request'])])
    assert len(calls) == 2
    assert len(list((root / 'data/derived/wiki/.wiki-viva-protected/llm-cache').glob('*.json'))) == 1


def test_record_batch_preserves_existing_result(prepared_repo):
    from wiki_core.ingest import protected
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    first = prepare(root, binding, **args, source_context='system')
    result = _result_for(first['request'])
    ids = dict(source_id=first['source_id'], request_id=first['request_id'])
    assert record(root, binding, **args, **ids, results=[result])['recorded'] == 1
    saved = root / 'data/derived/wiki/.wiki-viva-protected/llm-cache' / (result['cache_key'] + '.json')
    original = saved.read_bytes()
    assert record(root, binding, **args, **ids, results=[result])['recorded'] == 1
    with pytest.raises(protected.ProtectedPartialError):
        record(root, binding, **args, **ids, results=[{**result, 'synthetic_extra': 'different'}])
    assert saved.read_bytes() == original


def test_consolidation_candidates_use_approved_git_content_not_working_tree(prepared_repo, monkeypatch):
    root, _ = prepared_repo
    candidate = root / 'memories/candidates/approved.md'
    approved_text = '---\npage_id: approved-topic\npage_type: claim\ntitle: Approved Topic\n---\nApproved body.\n'
    write(root, 'memories/candidates/approved.md', approved_text)
    git(root, 'add', '.'); git(root, 'commit', '-qm', 'approve candidate')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    sha = git(root, 'rev-parse', 'HEAD')
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    prepared = prepare(root, binding, **args, source_context='system')
    result = {**_result_for(prepared['request']), 'entities': [{'name': 'Approved Topic', 'type': 'topic'}]}
    ids = {'source_id': prepared['source_id'], 'request_id': prepared['request_id']}
    record(root, binding, **args, **ids, results=[result])
    candidate.write_text('---\npage_id: unapproved\npage_type: claim\ntitle: WIP Sentinel\n---\nWIP body.\n')
    original_open = Path.open
    def guarded(path, *a, **kw):
        if path == candidate:
            pytest.fail('unapproved working-tree candidate opened')
        return original_open(path, *a, **kw)
    monkeypatch.setattr(Path, 'open', guarded)
    target = ('memories/system/ingestion/events/2026-11-04-' +
        hashlib.sha256(prepared['source_id'].encode()).hexdigest() + '-' + prepared['request_id'] + '.md')
    consolidate(root, binding, **args, **ids, source_page='memories/sources/synthetic.md',
        event_target=target, date=dt.date(2026, 11, 4), candidates=['memories/candidates/approved.md'])
    stored = next((root / 'data/derived/wiki/.wiki-viva-protected/extraction-events').glob('*integration-packet.json'))
    packet = json.loads(stored.read_text())
    assert 'WIP Sentinel' not in json.dumps(packet)
    assert packet['candidate_provenance'] == [{'path': 'memories/candidates/approved.md', 'revision': sha,
        'blob': git(root, 'rev-parse', sha + ':memories/candidates/approved.md'),
        'sha256': hashlib.sha256(approved_text.encode()).hexdigest()}]
    assert any(page['page_id'] == 'approved-topic' for item in packet['entities'] for page in item['pages'])
    inspected = protected_source_stage(root, binding, 'inspect', {**args, **ids, 'view': 'integration',
        'candidates': ['memories/candidates/approved.md']})['result']
    assert inspected['packet'] == packet
    with pytest.raises(ProtectedCoordinationError):
        protected_source_stage(root, binding, 'inspect', {**args, **ids, 'view': 'integration', 'candidates': []})
    packet['source_hash_sha256'] = '0' * 64
    stored.write_text(json.dumps(packet))
    with pytest.raises(ProtectedCoordinationError):
        protected_source_stage(root, binding, 'inspect', {**args, **ids, 'view': 'integration',
            'candidates': ['memories/candidates/approved.md']})


def test_inspection_revalidates_authority_after_result_read(prepared_repo, monkeypatch):
    import wiki_core.ingest.protected as protected
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    prepared = prepare(root, binding, **args, source_context='system')
    result = _result_for(prepared['request'])
    ids = dict(source_id=prepared['source_id'], request_id=prepared['request_id'])
    record(root, binding, **args, **ids, results=[result])
    git(root, 'commit', '--allow-empty', '-qm', 'synthetic revoked ref')
    next_sha = git(root, 'rev-parse', 'HEAD')
    original = protected._read_json
    observed = []
    def revoke_after_result(*a, **kw):
        value = original(*a, **kw)
        if a[3].name == result['cache_key'] + '.json':
            observed.append(True)
            git(root, 'update-ref', 'refs/remotes/origin/main', next_sha)
        return value
    monkeypatch.setattr(protected, '_read_json', revoke_after_result)
    with pytest.raises(ProtectedCoordinationError):
        protected_source_stage(root, binding, 'inspect', {**args, **ids, 'view': 'results',
            'chunk_ids': [result['chunk_id']]})
    assert observed == [True]


def test_inspection_rechecks_result_boundary_after_read(prepared_repo, monkeypatch):
    import wiki_core.ingest.protected as protected
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    prepared = prepare(root, binding, **args, source_context='system')
    result = _result_for(prepared['request'])
    ids = dict(source_id=prepared['source_id'], request_id=prepared['request_id'])
    record(root, binding, **args, **ids, results=[result])
    original = protected._read_json
    moved = []
    def replace_boundary(*a, **kw):
        value = original(*a, **kw)
        path = a[3]
        if path.name == result['cache_key'] + '.json':
            backup = path.parent.with_name(path.parent.name + '-moved')
            path.parent.rename(backup)
            path.parent.symlink_to(backup, target_is_directory=True)
            moved.append(True)
        return value
    monkeypatch.setattr(protected, '_read_json', replace_boundary)
    with pytest.raises(ProtectedCoordinationError):
        protected_source_stage(root, binding, 'inspect', {**args, **ids, 'view': 'results',
            'chunk_ids': [result['chunk_id']]})
    assert moved == [True]


def test_inspection_rechecks_result_contents_before_return(prepared_repo, monkeypatch):
    import wiki_core.ingest.protected as protected
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    prepared = prepare(root, binding, **args, source_context='system')
    result = _result_for(prepared['request'])
    ids = dict(source_id=prepared['source_id'], request_id=prepared['request_id'])
    record(root, binding, **args, **ids, results=[result])
    original = protected._read_json
    changed = []
    def mutate(*a, **kw):
        value = original(*a, **kw)
        if a[3].name == result['cache_key'] + '.json' and not changed:
            a[3].write_text(json.dumps({**result, 'synthetic_review_note': 'changed'}))
            changed.append(True)
        return value
    monkeypatch.setattr(protected, '_read_json', mutate)
    with pytest.raises(ProtectedCoordinationError):
        protected_source_stage(root, binding, 'inspect', {**args, **ids, 'view': 'results',
            'chunk_ids': [result['chunk_id']]})
    assert changed == [True]


def test_inspection_detects_prior_result_changed_during_final_readback(prepared_repo, monkeypatch):
    import wiki_core.ingest.protected as protected
    root, sha = prepared_repo
    (root / 'source.txt').write_text(''.join(f'Synthetic evidence {i} with bounded detail.\n' for i in range(500)))
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    prepared = prepare(root, binding, **args, source_context='system')
    request = prepared['request']; rows = request['chunks'][:2]
    assert len(rows) == 2
    sample = _result_for(request)
    results = [{**sample, **{key: row[key] for key in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')}} for row in rows]
    ids = dict(source_id=prepared['source_id'], request_id=prepared['request_id'])
    record(root, binding, **args, **ids, results=results)
    cache = root / 'data/derived/wiki/.wiki-viva-protected/llm-cache'
    original = protected._read_json; counts = {}
    def mutate(*a, **kw):
        value = original(*a, **kw)
        if a[3].parent.name == 'llm-cache':
            name = a[3].name
            counts[name] = counts.get(name, 0) + 1
            if name == rows[1]['cache_key'] + '.json' and counts[name] == 2:
                (cache / (rows[0]['cache_key'] + '.json')).write_text(json.dumps({**results[0], 'synthetic_note': 'changed'}))
        return value
    monkeypatch.setattr(protected, '_read_json', mutate)
    with pytest.raises(ProtectedCoordinationError):
        protected_source_stage(root, binding, 'inspect', {**args, **ids, 'view': 'results',
            'chunk_ids': [row['chunk_id'] for row in rows]})


def test_inspection_revalidates_once_per_batch(prepared_repo, monkeypatch):
    import wiki_core.ingest.protected as protected
    root, sha = prepared_repo
    (root / 'source.txt').write_text(''.join(f'Synthetic evidence {i} with bounded detail.\n' for i in range(1200)))
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    prepared = prepare(root, binding, **args, source_context='system')
    request = prepared['request']
    assert len(request['chunks']) >= 3
    sample = _result_for(request)
    results = [{**sample, **{key: row[key] for key in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')}}
               for row in request['chunks']]
    ids = dict(source_id=prepared['source_id'], request_id=prepared['request_id'])
    record(root, binding, **args, **ids, results=results)
    calls = []
    original = protected._open_bound
    def count(*a, **kw):
        calls.append(1)
        return original(*a, **kw)
    monkeypatch.setattr(protected, '_open_bound', count)
    inspected = protected_source_stage(root, binding, 'inspect', {**args, **ids, 'view': 'results',
        'chunk_ids': [row['chunk_id'] for row in request['chunks']]})['result']
    assert [item['result'] for item in inspected['results']] == results
    assert len(calls) == 3


def test_inspection_rechecks_packet_contents_before_return(prepared_repo, monkeypatch):
    import wiki_core.ingest.protected as protected
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    prepared = prepare(root, binding, **args, source_context='system')
    ids = dict(source_id=prepared['source_id'], request_id=prepared['request_id'])
    record(root, binding, **args, **ids, results=[_result_for(prepared['request'])])
    target = ('memories/system/ingestion/events/2026-11-04-' +
              hashlib.sha256(prepared['source_id'].encode()).hexdigest() + '-' + prepared['request_id'] + '.md')
    consolidate(root, binding, **args, **ids, source_page='memories/sources/synthetic.md',
                event_target=target, date=dt.date(2026, 11, 4))
    original = protected._read_json
    changed = []
    def mutate(*a, **kw):
        value = original(*a, **kw)
        if a[3].name.endswith('-integration-packet.json') and not changed:
            a[3].write_text(json.dumps({**value, 'synthetic_review_note': 'changed'}))
            changed.append(True)
        return value
    monkeypatch.setattr(protected, '_read_json', mutate)
    with pytest.raises(ProtectedCoordinationError):
        protected_source_stage(root, binding, 'inspect', {**args, **ids, 'view': 'integration', 'candidates': []})
    assert changed == [True]


def test_inspection_rechecks_candidate_after_final_packet_readback(prepared_repo, monkeypatch):
    import wiki_core.ingest.protected as protected
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    prepared = prepare(root, binding, **args, source_context='system')
    ids = dict(source_id=prepared['source_id'], request_id=prepared['request_id'])
    record(root, binding, **args, **ids, results=[_result_for(prepared['request'])])
    ref = 'memories/sources/synthetic.md'
    target = ('memories/system/ingestion/events/2026-11-04-' +
              hashlib.sha256(prepared['source_id'].encode()).hexdigest() + '-' + prepared['request_id'] + '.md')
    consolidate(root, binding, **args, **ids, source_page=ref, event_target=target,
                date=dt.date(2026, 11, 4), candidates=[ref])
    original = protected._read_json; reads = []
    def mutate(*a, **kw):
        value = original(*a, **kw)
        if a[3].name.endswith('-integration-packet.json'):
            reads.append(True)
            if len(reads) == 2:
                path = root / ref; moved = path.with_name('synthetic-moved.md')
                path.rename(moved); path.symlink_to(moved)
        return value
    monkeypatch.setattr(protected, '_read_json', mutate)
    with pytest.raises(ProtectedCoordinationError):
        protected_source_stage(root, binding, 'inspect', {**args, **ids, 'view': 'integration', 'candidates': [ref]})
    assert len(reads) == 2


@pytest.mark.parametrize('changed', ['source', 'request'])
def test_inspection_checks_source_and_request_before_first_cache_read(prepared_repo, monkeypatch, changed):
    import wiki_core.ingest.protected as protected
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    prepared = prepare(root, binding, **args, source_context='system')
    result = _result_for(prepared['request'])
    ids = dict(source_id=prepared['source_id'], request_id=prepared['request_id'])
    record(root, binding, **args, **ids, results=[result])
    original = protected._open_bound
    changed_once = []
    def mutate(*a, **kw):
        value = original(*a, **kw)
        if not changed_once:
            target = (root / 'source.txt' if changed == 'source' else
                next((root / 'data/derived/wiki/.wiki-viva-protected').rglob('*' + ids['request_id'] + '-llm-context-request.json')))
            target.write_text('Synthetic changed content\n')
            changed_once.append(True)
        return value
    original_open = Path.open
    cache_opened = []
    def spy(path, *a, **kw):
        if path.name == result['cache_key'] + '.json':
            cache_opened.append(path)
        return original_open(path, *a, **kw)
    monkeypatch.setattr(protected, '_open_bound', mutate)
    monkeypatch.setattr(Path, 'open', spy)
    with pytest.raises(ProtectedCoordinationError):
        protected_source_stage(root, binding, 'inspect', {**args, **ids, 'view': 'results',
            'chunk_ids': [result['chunk_id']]})
    assert changed_once == [True] and cache_opened == []


def test_inspection_requires_host_and_exact_selected_result(prepared_repo, monkeypatch):
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    prepared = prepare(root, binding, **args, source_context='system')
    result = _result_for(prepared['request'])
    ids = dict(source_id=prepared['source_id'], request_id=prepared['request_id'])
    record(root, binding, **args, **ids, results=[result])
    payload = {**args, **ids, 'view': 'results', 'chunk_ids': [result['chunk_id']]}
    from wiki_core.llm.context_pass import canonical_request_text
    envelope = protected_source_stage(root, binding, 'inspect', payload)
    size = len(canonical_request_text(envelope['result']).encode('utf-8'))
    assert len(canonical_request_text(envelope).encode('utf-8')) > size
    assert protected_source_stage(root, binding, 'inspect', {**payload, 'max_output_bytes': size})['result'] == envelope['result']
    with pytest.raises(ProtectedCoordinationError):
        protected_source_stage(root, binding, 'inspect', {**payload, 'max_output_bytes': size - 1})
    with pytest.raises(ProtectedCoordinationError):
        protected_source_stage(root, binding, 'inspect', {**payload, 'max_output_bytes': 1})
    result_file = next((root / 'data/derived/wiki/.wiki-viva-protected').rglob(result['cache_key'] + '.json'))
    result_file.write_text(json.dumps({**result, 'chunk_hash_sha256': '0' * 64}))
    with pytest.raises(ProtectedCoordinationError):
        protected_source_stage(root, binding, 'inspect', payload)
    result_file.write_text(json.dumps(result))
    original = Path.open
    def forbid_result(path, *a, **kw):
        if path.name == result['cache_key'] + '.json':
            pytest.fail('unauthorized or unselected result opened')
        return original(path, *a, **kw)
    monkeypatch.setattr(Path, 'open', forbid_result)
    with pytest.raises(ProtectedCoordinationError):
        protected_source_stage(root, None, 'inspect', payload)
    with pytest.raises(ProtectedCoordinationError):
        protected_source_stage(root, binding, 'inspect', {**payload, 'chunk_ids': ['missing']})


def test_consolidation_rechecks_candidate_boundary_before_writing(prepared_repo, monkeypatch):
    import wiki_core.ingest.protected as protected
    root, _ = prepared_repo
    write(root, 'memories/candidates/approved.md', '---\npage_id: approved\npage_type: claim\n---\n# Approved\n')
    git(root, 'add', '.'); git(root, 'commit', '-qm', 'approve candidate')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    sha = git(root, 'rev-parse', 'HEAD')
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    prepared = prepare(root, binding, **args, source_context='system')
    ids = {'source_id': prepared['source_id'], 'request_id': prepared['request_id']}
    record(root, binding, **args, **ids, results=[_result_for(prepared['request'])])
    original = protected._approved_candidate_documents
    def cross_boundary(*a, **kw):
        docs = original(*a, **kw)
        (root / 'memories/candidates/.git').mkdir()
        return docs
    monkeypatch.setattr(protected, '_approved_candidate_documents', cross_boundary)
    target = ('memories/system/ingestion/events/2026-11-04-' +
        hashlib.sha256(prepared['source_id'].encode()).hexdigest() + '-' + prepared['request_id'] + '.md')
    with pytest.raises(ValueError):
        consolidate(root, binding, **args, **ids, source_page='memories/sources/synthetic.md',
            event_target=target, date=dt.date(2026, 11, 4), candidates=['memories/candidates/approved.md'])
    assert not (root / target).exists()
    assert not list((root / 'data/derived/wiki/.wiki-viva-protected/extraction-events').glob('*integration-packet.json'))


def test_consolidation_reports_partial_if_candidate_boundary_changes_after_write(prepared_repo, monkeypatch):
    import wiki_core.ingest.protected as protected
    root, _ = prepared_repo
    write(root, 'memories/candidates/approved.md', '---\npage_id: approved\npage_type: claim\n---\n# Approved\n')
    git(root, 'add', '.'); git(root, 'commit', '-qm', 'approve candidate')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    sha = git(root, 'rev-parse', 'HEAD')
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    prepared = prepare(root, binding, **args, source_context='system')
    ids = {'source_id': prepared['source_id'], 'request_id': prepared['request_id']}
    record(root, binding, **args, **ids, results=[_result_for(prepared['request'])])
    original = protected._read_json
    def cross_after_read(*a, **kw):
        result = original(*a, **kw)
        if a[3].name.endswith('-integration-packet.json'):
            (root / 'memories/candidates/.git').mkdir()
        return result
    monkeypatch.setattr(protected, '_read_json', cross_after_read)
    target = ('memories/system/ingestion/events/2026-11-04-' +
        hashlib.sha256(prepared['source_id'].encode()).hexdigest() + '-' + prepared['request_id'] + '.md')
    with pytest.raises(protected.ProtectedPartialError):
        consolidate(root, binding, **args, **ids, source_page='memories/sources/synthetic.md',
            event_target=target, date=dt.date(2026, 11, 4), candidates=['memories/candidates/approved.md'])
    assert (root / target).is_file()
    assert list((root / 'data/derived/wiki/.wiki-viva-protected/extraction-events').glob('*integration-packet.json'))


def test_nested_result_cannot_drop_integrator_before_read(prepared_repo, monkeypatch):
    from pathlib import Path
    from wiki_core.traversal import is_protected_artifact
    root, _ = prepared_repo
    sha = _nested_integrator_repo(root)
    binding = CoordinationBinding(('alpha', '.'), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='alpha', approved_revision=sha, entry_folder='alpha',
                entry_index='alpha/index.md', source_ref='alpha/source.txt')
    prepared = prepare(root, binding, **args, source_context='alpha', artifact_context='.')
    original = Path.open
    def sentinel(path, *values, **kwargs):
        if is_protected_artifact(path):
            pytest.fail('protected artifact opened after dropping integrator')
        return original(path, *values, **kwargs)
    monkeypatch.setattr(Path, 'open', sentinel)
    with pytest.raises(ValueError):
        record(root, binding, **args, source_id=prepared['source_id'], request_id=prepared['request_id'], results=[])


def test_integrator_without_source_connection_is_denied_before_open(prepared_repo, monkeypatch):
    from pathlib import Path
    root, _ = prepared_repo
    _nested_integrator_repo(root)
    config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
    for context, key in [('.', 'imports'), ('alpha', 'exports')]:
        config['context_access'][context][key] = [r for r in config['context_access'][context][key]
                                                   if r['selector'] != 'alpha/source.txt']
    write(root, 'wiki.config.yaml', yaml.safe_dump(config))
    git(root, 'add', 'wiki.config.yaml'); git(root, 'commit', '-qm', 'remove source connection')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    sha = git(root, 'rev-parse', 'HEAD')
    binding = CoordinationBinding(('alpha', '.'), 'refs/remotes/origin/main', 'wiki.config.yaml')
    original = Path.open
    def no_source(path, *args, **kwargs):
        if path == root / 'alpha/source.txt':
            pytest.fail('source opened without integrator connection')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', no_source)
    with pytest.raises(ValueError, match='source unavailable'):
        prepare(root, binding, context_id='alpha', approved_revision=sha, entry_folder='alpha',
            entry_index='alpha/index.md', source_ref='alpha/source.txt', source_context='alpha', artifact_context='.')


def test_integrator_without_instruction_connection_is_denied_before_blob(prepared_repo, monkeypatch):
    from wiki_core.repository_reader import RepositoryReader
    root, _ = prepared_repo
    _nested_integrator_repo(root)
    config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
    for context, key in [('.', 'imports'), ('alpha', 'exports')]:
        config['context_access'][context][key] = [r for r in config['context_access'][context][key]
                                                   if r['selector'] != 'alpha/AGENTS.override.md']
    write(root, 'wiki.config.yaml', yaml.safe_dump(config))
    git(root, 'add', 'wiki.config.yaml'); git(root, 'commit', '-qm', 'remove instruction connection')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    sha = git(root, 'rev-parse', 'HEAD')
    binding = CoordinationBinding(('alpha', '.'), 'refs/remotes/origin/main', 'wiki.config.yaml')
    original = RepositoryReader.read
    def guarded(reader, path, *args, **kwargs):
        if path == 'alpha/AGENTS.override.md':
            pytest.fail('instruction opened without integrator connection')
        return original(reader, path, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', guarded)
    with pytest.raises(ValueError):
        prepare(root, binding, context_id='alpha', approved_revision=sha, entry_folder='alpha',
            entry_index='alpha/index.md', source_ref='alpha/source.txt', source_context='alpha', artifact_context='.')


def test_integrator_not_in_host_binding_fails_before_any_context_body(prepared_repo, monkeypatch):
    from wiki_core.repository_reader import RepositoryReader
    root, _ = prepared_repo
    sha = _nested_integrator_repo(root)
    binding = CoordinationBinding(('alpha',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    monkeypatch.setattr(RepositoryReader, 'read', lambda *_args, **_kwargs: pytest.fail('body opened without host binding'))
    with pytest.raises(ProtectedCoordinationError) as exc:
        protected_source_stage(root, binding, 'prepare', dict(context_id='alpha', approved_revision=sha,
            entry_folder='alpha', entry_index='alpha/index.md', source_ref='alpha/source.txt',
            source_context='alpha', artifact_context='.'))
    assert exc.value.status == 'denied'


def test_one_source_two_authorized_folder_interpretations(prepared_repo):
    root, _ = prepared_repo
    config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
    root_exports, root_imports = [], []
    for name in ('alpha', 'beta'):
        if name == 'beta':
            config['context_access'][name] = {'owner': 'beta operator',
                'policy': {'read': ['self'], 'write': ['self'], 'capabilities': [], 'deny': {}, 'publication': []}}
        config['context_access'][name]['policy']['read'] = ['self', 'AGENTS.md', 'source.txt']
        imports = [
            {'from_context': '.', 'to_context': name, 'selector': ref,
             'use': 'interpretation', 'classification': kind, 'expires': '2099-01-01'}
            for ref, kind in [('AGENTS.md', 'context'), ('source.txt', 'source')]
        ]
        instruction = f'{name}/AGENTS.override.md' if name == 'alpha' else f'{name}/AGENTS.md'
        exports = [
            {'from_context': name, 'to_context': '.', 'selector': ref,
             'use': 'interpretation', 'classification': 'context', 'expires': '2099-01-01'}
            for ref in (instruction, f'{name}/index.md')
        ]
        config['context_access'][name]['imports'] = imports
        config['context_access'][name]['exports'] = exports
        root_exports.extend(imports); root_imports.extend(exports)
    config['context_access']['.']['exports'] = root_exports
    config['context_access']['.']['imports'] = root_imports
    write(root, 'wiki.config.yaml', yaml.safe_dump(config))
    git(root, 'add', 'wiki.config.yaml'); git(root, 'commit', '-qm', 'authorize two interpretations')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    sha = git(root, 'rev-parse', 'HEAD')
    binding = CoordinationBinding(('alpha', 'beta', '.'), 'refs/remotes/origin/main', 'wiki.config.yaml')
    def args(name):
        return dict(context_id=name, approved_revision=sha, entry_folder=name, entry_index=f'{name}/index.md',
                    source_ref='source.txt', artifact_context='.')
    first = prepare(root, binding, **args('alpha'), source_context='alpha')
    manifest = root / 'data/derived/wiki/.wiki-viva-protected/source-manifests' / (first['source_id'] + '.json')
    initial = manifest.read_bytes()
    second = prepare(root, binding, **args('beta'), source_context='beta')
    assert first['source_id'] == second['source_id'] and first['request_id'] != second['request_id']
    assert manifest.read_bytes() == initial
    for name, prepared in [('alpha', first), ('beta', second)]:
        result = _result_for(prepared['request'])
        assert record(root, binding, **args(name), source_id=prepared['source_id'],
                      request_id=prepared['request_id'], results=[result])['recorded'] == 1
    cache = root / 'data/derived/wiki/.wiki-viva-protected/llm-cache'
    assert len(list(cache.glob('*.json'))) == 2


def _result_for(request):
    from pathlib import Path
    row = request['chunks'][0]
    sample = json.loads((Path(__file__).parent / 'fixtures/e2e/context_pass_result.sample.json').read_text())
    return {**sample, **{key: request[key] for key in ('source_id', 'prompt_version', 'schema_version', 'model_profile')},
            **{key: row[key] for key in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')},
            'perspectives_required': [], 'perspectives': {}}


def test_prepare_rechecks_exact_cache_without_changing_retained_request(prepared_repo):
    from wiki_core.llm.context_pass import canonical_request_text
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    first = prepare(root, binding, **args, source_context='system')
    directory = root / 'data/derived/wiki/.wiki-viva-protected'
    request_path = next(directory.rglob('*' + first['request_id'] + '-llm-context-request.json'))
    before = request_path.read_bytes()
    record(root, binding, **args, source_id=first['source_id'], request_id=first['request_id'],
           results=[_result_for(first['request'])])
    again = prepare(root, binding, **args, source_context='system')
    assert again['request_id'] == first['request_id']
    assert request_path.read_bytes() == before
    assert again['request']['chunks'][0]['result_exists'] is True
    assert again['request']['chunks'][0]['result_source_id'] == first['source_id']
    assert again['request']['cached_calls'] == 1 and again['request']['pending_llm_calls'] == 0
    assert again['request']['byte_accounting']['request_bytes'] == len(canonical_request_text(again['request']).encode())


@pytest.mark.parametrize('contents', ['null', '{broken'])
def test_prepare_blocks_corrupt_cached_result(prepared_repo, contents):
    from wiki_core.ingest.protected import ProtectedPartialError
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    first = prepare(root, binding, **args, source_context='system')
    record(root, binding, **args, source_id=first['source_id'], request_id=first['request_id'],
           results=[_result_for(first['request'])])
    cache = root / 'data/derived/wiki/.wiki-viva-protected/llm-cache' / (first['request']['chunks'][0]['cache_key'] + '.json')
    cache.write_text(contents)
    with pytest.raises(ProtectedPartialError, match='cache readback unavailable'):
        prepare(root, binding, **args, source_context='system')
    assert cache.read_text() == contents


def test_prepare_revalidates_after_cache_open(prepared_repo, monkeypatch):
    from wiki_core.ingest import protected
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    first = prepare(root, binding, **args, source_context='system')
    record(root, binding, **args, source_id=first['source_id'], request_id=first['request_id'],
           results=[_result_for(first['request'])])
    read = protected._read_json
    def revoke(*values, **kwargs):
        result = read(*values, **kwargs)
        if values[3].parent.name == 'llm-cache':
            git(root, 'update-ref', '-d', 'refs/remotes/origin/main')
        return result
    monkeypatch.setattr(protected, '_read_json', revoke)
    with pytest.raises(protected.ProtectedPartialError, match='cache readback unavailable'):
        prepare(root, binding, **args, source_context='system')


def test_prepare_checks_revocation_before_cache_open(prepared_repo, monkeypatch):
    from wiki_core.ingest import protected
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    first = prepare(root, binding, **args, source_context='system')
    record(root, binding, **args, source_id=first['source_id'], request_id=first['request_id'],
           results=[_result_for(first['request'])])
    original = protected._open_bound
    def revoke(*values, **kwargs):
        result = original(*values, **kwargs)
        git(root, 'update-ref', '-d', 'refs/remotes/origin/main')
        return result
    opened = []
    read = Path.open
    def spy(path, *values, **kwargs):
        if path.parent.name == 'llm-cache':
            opened.append(path)
        return read(path, *values, **kwargs)
    monkeypatch.setattr(protected, '_open_bound', revoke)
    monkeypatch.setattr(Path, 'open', spy)
    with pytest.raises(protected.ProtectedPartialError, match='cache readback unavailable'):
        prepare(root, binding, **args, source_context='system')
    assert opened == []


def test_prepare_rechecks_cache_boundary_after_read(prepared_repo, monkeypatch):
    from wiki_core.ingest import protected
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    first = prepare(root, binding, **args, source_context='system')
    result = _result_for(first['request'])
    record(root, binding, **args, source_id=first['source_id'], request_id=first['request_id'], results=[result])
    cache = root / 'data/derived/wiki/.wiki-viva-protected/llm-cache'
    read = protected._read_json
    def replace_directory(*values, **kwargs):
        observed = read(*values, **kwargs)
        if values[3].name == result['cache_key'] + '.json':
            moved = cache.parent / 'moved-cache'
            cache.rename(moved)
            cache.symlink_to(moved, target_is_directory=True)
        return observed
    monkeypatch.setattr(protected, '_read_json', replace_directory)
    with pytest.raises(protected.ProtectedPartialError, match='cache readback unavailable'):
        prepare(root, binding, **args, source_context='system')
    assert cache.is_symlink()


def test_prepare_revalidates_once_per_batch(prepared_repo, monkeypatch):
    from wiki_core.ingest import protected
    root, sha = prepared_repo
    (root / 'source.txt').write_text(''.join(f'Synthetic evidence {i} with bounded detail.\n' for i in range(1200)))
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    calls = []
    original = protected._open_bound
    def count(*a, **kw):
        calls.append(1)
        return original(*a, **kw)
    monkeypatch.setattr(protected, '_open_bound', count)
    result = prepare(root, binding, **args, source_context='system')
    assert len(result['request']['chunks']) >= 3
    assert len(calls) == 2


def test_consolidation_rejects_combined_result_budget_before_effects(prepared_repo, monkeypatch):
    from wiki_core.ingest import protected
    root, sha = prepared_repo
    (root / 'source.txt').write_text(''.join(f'Synthetic evidence {i} with bounded detail.\n' for i in range(1200)))
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    prepared = prepare(root, binding, **args, source_context='system')
    request = prepared['request']
    assert len(request['chunks']) >= 3
    ids = dict(source_id=prepared['source_id'], request_id=prepared['request_id'])
    sample = _result_for(request)
    # This fixture exercises byte accounting, not the separate secret detector.
    detect = protected.contains_access_secrets
    def synthetic_detection(value):
        if isinstance(value, dict) and 'synthetic_padding' in value:
            return False
        if isinstance(value, list) and value and all(isinstance(x, dict) and 'synthetic_padding' in x for x in value):
            return False
        return detect(value)
    monkeypatch.setattr(protected, 'contains_access_secrets', synthetic_detection)
    for row in request['chunks'][:2]:
        result = {**sample, **{key: row[key] for key in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')},
                  'synthetic_padding': ['.'] * 130_000}
        record(root, binding, **args, **ids, results=[result])
    target = ('memories/system/ingestion/events/2026-11-04-' +
              hashlib.sha256(prepared['source_id'].encode()).hexdigest() + '-' + prepared['request_id'] + '.md')
    with pytest.raises(ProtectedCoordinationError) as error:
        protected_source_stage(root, binding, 'consolidate', {**args, **ids,
            'source_page': 'memories/sources/synthetic.md', 'event_target': target, 'date': '2026-11-04'})
    assert error.value.code == 'coordination_result_budget_exceeded'
    assert not (root / target).exists()
    assert not list((root / 'data/derived/wiki/.wiki-viva-protected').rglob('*integration-packet.json'))


def test_consolidation_counts_inspection_envelope_before_effects(prepared_repo, monkeypatch):
    import wiki_core.consolidate as consolidation
    from wiki_core.llm.context_pass import canonical_request_text
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    prepared = prepare(root, binding, **args, source_context='system')
    ids = dict(source_id=prepared['source_id'], request_id=prepared['request_id'])
    record(root, binding, **args, **ids, results=[_result_for(prepared['request'])])
    wrapper = {'view': 'integration', **ids, 'packet': {'padding': ''},
               'event_status': 'not checked', 'integration': 'not assessed'}
    padding_size = 2_000_001 - len(canonical_request_text(wrapper).encode('utf-8'))
    packet = {'padding': '.' * padding_size}
    assert len(canonical_request_text(packet).encode('utf-8')) < 2_000_000
    monkeypatch.setattr(consolidation, 'build_packet', lambda *a, **kw: packet)
    target = ('memories/system/ingestion/events/2026-11-04-' +
              hashlib.sha256(prepared['source_id'].encode()).hexdigest() + '-' + prepared['request_id'] + '.md')
    with pytest.raises(ProtectedCoordinationError) as error:
        protected_source_stage(root, binding, 'consolidate', {**args, **ids,
            'source_page': 'memories/sources/synthetic.md', 'event_target': target, 'date': '2026-11-04'})
    assert error.value.code == 'coordination_result_budget_exceeded'
    assert not (root / target).exists()
    assert not list((root / 'data/derived/wiki/.wiki-viva-protected').rglob('*integration-packet.json'))


@pytest.mark.parametrize('changed', ['source', 'request'])
def test_prepare_stops_batch_when_source_or_request_changes(prepared_repo, monkeypatch, changed):
    from wiki_core.ingest import protected
    root, sha = prepared_repo
    (root / 'source.txt').write_text(''.join(f'Synthetic evidence {i} with bounded detail.\n' for i in range(1200)))
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    first = prepare(root, binding, **args, source_context='system')
    assert len(first['request']['chunks']) >= 3
    record(root, binding, **args, source_id=first['source_id'], request_id=first['request_id'],
           results=[_result_for(first['request'])])
    request_path = next((root / 'data/derived/wiki/.wiki-viva-protected').rglob('*' + first['request_id'] + '-llm-context-request.json'))
    read = protected._read_json
    cache_reads = []
    def mutate(*a, **kw):
        value = read(*a, **kw)
        if a[3].parent.name == 'llm-cache':
            cache_reads.append(a[3])
            target = root / 'source.txt' if changed == 'source' else request_path
            with target.open('a') as stream:
                stream.write(' ')
        return value
    monkeypatch.setattr(protected, '_read_json', mutate)
    with pytest.raises(protected.ProtectedPartialError):
        prepare(root, binding, **args, source_context='system')
    assert len(cache_reads) == 1


@pytest.mark.parametrize('changed', ['source', 'request'])
def test_prepare_checks_stamps_after_initial_bound_before_cache(prepared_repo, monkeypatch, changed):
    from wiki_core.ingest import protected
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    first = prepare(root, binding, **args, source_context='system')
    result = _result_for(first['request'])
    record(root, binding, **args, source_id=first['source_id'], request_id=first['request_id'], results=[result])
    original_bound = protected._open_bound
    mutated = []
    def change(*a, **kw):
        value = original_bound(*a, **kw)
        if not mutated:
            target = (root / 'source.txt' if changed == 'source' else
                next((root / 'data/derived/wiki/.wiki-viva-protected').rglob('*' + first['request_id'] + '-llm-context-request.json')))
            target.write_text('Synthetic changed content\n')
            mutated.append(True)
        return value
    original_open = Path.open
    opened = []
    def spy(path, *a, **kw):
        if path.name == result['cache_key'] + '.json':
            opened.append(path)
        return original_open(path, *a, **kw)
    monkeypatch.setattr(protected, '_open_bound', change)
    monkeypatch.setattr(Path, 'open', spy)
    with pytest.raises(protected.ProtectedPartialError):
        prepare(root, binding, **args, source_context='system')
    assert mutated == [True] and opened == []


def test_revocation_after_last_result_write_reports_partial(prepared_repo, monkeypatch):
    from wiki_core.ingest import protected
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    prepared = prepare(root, binding, **args, source_context='system')
    original = protected._write_once
    def revoke_after_result(*values, **kwargs):
        result = original(*values, **kwargs)
        if values[3].parent.name == 'llm-cache':
            git(root, 'update-ref', '-d', 'refs/remotes/origin/main')
        return result
    monkeypatch.setattr(protected, '_write_once', revoke_after_result)
    with pytest.raises(protected.ProtectedPartialError):
        record(root, binding, **args, source_id=prepared['source_id'], request_id=prepared['request_id'],
               results=[_result_for(prepared['request'])])
    assert len(list((root / 'data/derived/wiki/.wiki-viva-protected/llm-cache').glob('*.json'))) == 1


def test_revocation_after_event_write_reports_partial(prepared_repo, monkeypatch):
    from pathlib import Path
    from wiki_core.ingest import protected
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    prepared = prepare(root, binding, **args, source_context='system')
    ids = dict(source_id=prepared['source_id'], request_id=prepared['request_id'])
    record(root, binding, **args, **ids, results=[_result_for(prepared['request'])])
    event = ('memories/system/ingestion/events/2026-11-04-' +
             hashlib.sha256(prepared['source_id'].encode()).hexdigest() + '-' + prepared['request_id'] + '.md')
    original = Path.open
    class RevokeOnClose:
        def __init__(self, stream): self.stream = stream
        def __enter__(self): return self.stream
        def __exit__(self, *values):
            self.stream.close()
            git(root, 'update-ref', '-d', 'refs/remotes/origin/main')
    def tracked(path, *values, **kwargs):
        if path == root / event and values and values[0] == 'x':
            return RevokeOnClose(original(path, *values, **kwargs))
        return original(path, *values, **kwargs)
    monkeypatch.setattr(Path, 'open', tracked)
    with pytest.raises(protected.ProtectedPartialError):
        consolidate(root, binding, **args, **ids, source_page='memories/sources/synthetic.md',
                    event_target=event, date=dt.date(2026, 11, 4))
    assert (root / event).is_file()
