import datetime as dt
import hashlib
import json
import subprocess
import sys

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
    base = {'entry_folder': 'alpha', 'entry_index': 'alpha/index.md', 'source_ref': 'alpha/source.txt'}
    prepared = call('prepare', {**base, 'source_context': 'alpha'})
    request = prepared['request']; row = request['chunks'][0]
    sample = json.loads((Path(__file__).parent / 'fixtures/e2e/context_pass_result.sample.json').read_text())
    result = {**sample, **{key: request[key] for key in ('source_id', 'prompt_version', 'schema_version', 'model_profile')},
              **{key: row[key] for key in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')},
              'perspectives_required': [], 'perspectives': {}}
    ids = {'source_id': prepared['source_id'], 'request_id': prepared['request_id']}
    assert call('record', {**base, **ids, 'results': [result]})['recorded'] == 1
    event = ('memories/system/ingestion/events/2026-11-04-' +
             hashlib.sha256(prepared['source_id'].encode()).hexdigest() + '-' + prepared['request_id'] + '.md')
    output = call('consolidate', {**base, **ids, 'source_page': 'memories/sources/synthetic.md', 'event_target': event, 'date': '2026-11-04'})
    assert output['integration'] == 'pending review and incorporation'
    assert (root / event).is_file()


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
    with pytest.raises(ValueError):
        prepare(root, binding, context_id='alpha', approved_revision=sha, entry_folder='alpha',
            entry_index='alpha/index.md', source_ref='alpha/source.txt', source_context='alpha', artifact_context='.')


def _result_for(request):
    from pathlib import Path
    row = request['chunks'][0]
    sample = json.loads((Path(__file__).parent / 'fixtures/e2e/context_pass_result.sample.json').read_text())
    return {**sample, **{key: request[key] for key in ('source_id', 'prompt_version', 'schema_version', 'model_profile')},
            **{key: row[key] for key in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')},
            'perspectives_required': [], 'perspectives': {}}


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
