import json
from pathlib import Path

import pytest
import yaml

from tests.test_protected_ingestion import prepared_repo
from tests.test_folder_policy_core import repo, git, write
from wiki_core.coordination_context import CoordinationBinding
from wiki_core.ingest.protected import prepare, record
from wiki_core.llm.context_pass import ContextRequestBlocked


def configured(prepared_repo, *, version='v5'):
    root, _ = prepared_repo
    config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
    config['root_entity'] = {'page': 'memories/root.md', 'perspective_bundle': {'required': ['lens'], 'optional': []}}
    config['llm'] = {'prompt_versions': {'context_deep_read': version}}
    write(root, 'wiki.config.yaml', yaml.safe_dump(config))
    write(root, 'memories/root.md', '---\npage_id: root\npage_type: root_entity\n---\n# Root\n')
    write(root, 'memories/lens.md', '---\npage_id: lens\npage_type: perspective\n---\n# Lens\nPreserve exceptions.\n')
    git(root, 'add', '.'); git(root, 'commit', '-qm', 'configure lens')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    sha = git(root, 'rev-parse', 'HEAD')
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md',
                source_ref='source.txt', perspective_refs={'lens': 'memories/lens.md'},
                context_selection={'root_entity': 'memories/root.md'})
    return root, binding, args


def test_selected_required_perspective_is_bound_and_recorded(prepared_repo):
    root, binding, args = configured(prepared_repo)
    request = prepare(root, binding, **args, source_context='system')
    data = request['request']
    assert data['perspectives_required'] == ['lens']
    assert 'wiki_coordination.py --context-id' in data['prompt']
    assert '--source-stage record' in data['prompt']
    assert '--policy-context CONTEXT_ID' not in data['prompt']
    assert 'Preserve exceptions.' in next(row['text'] for row in data['block_context_package']['inputs']
                                           if row['ref'] == 'memories/lens.md')
    assert data['source_authorization']['perspective_refs'] == args['perspective_refs']
    sample = json.loads((Path(__file__).parent / 'fixtures/e2e/context_pass_result.sample.json').read_text())
    row = data['chunks'][0]
    result = {**sample, **{key: data[key] for key in ('source_id', 'prompt_version', 'schema_version', 'model_profile')},
              **{key: row[key] for key in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')},
              'perspectives_required': ['lens'], 'perspectives': {'lens': {'status': 'extracted'}}}
    ids = {'source_id': request['source_id'], 'request_id': request['request_id']}
    with pytest.raises(ValueError):
        record(root, binding, **{**args, 'perspective_refs': None}, **ids, results=[result])
    with pytest.raises(ValueError):
        record(root, binding, **args, **ids, results=[{**result, 'perspectives': {}}])
    assert record(root, binding, **args, **ids, results=[result])['recorded'] == 1


@pytest.mark.parametrize('version', ['v1', 'v2', 'v3', 'v4', 'v999'])
def test_old_prompt_is_blocked_before_source_capture(prepared_repo, monkeypatch, version):
    root, binding, args = configured(prepared_repo, version=version)
    import wiki_core.ingest.protected as protected
    monkeypatch.setattr(protected, '_capture', lambda *a, **k: pytest.fail('source captured'))
    with pytest.raises(ContextRequestBlocked, match='v5'):
        prepare(root, binding, **args, source_context='system')
    assert not (root / 'data/derived').exists()


def test_required_perspective_must_be_selected_before_source_capture(prepared_repo, monkeypatch):
    root, binding, args = configured(prepared_repo)
    import wiki_core.ingest.protected as protected
    monkeypatch.setattr(protected, '_capture', lambda *a, **k: pytest.fail('source captured'))
    with pytest.raises(ValueError, match='perspective selection'):
        prepare(root, binding, **{**args, 'perspective_refs': None}, source_context='system')


def test_denied_perspective_stops_before_capture_or_perspective_body(prepared_repo, monkeypatch):
    root, binding, args = configured(prepared_repo)
    config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
    config['context_access']['.']['policy']['deny'] = {'read': ['memories/lens.md']}
    write(root, 'wiki.config.yaml', yaml.safe_dump(config))
    git(root, 'add', '.'); git(root, 'commit', '-qm', 'deny lens')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    args['approved_revision'] = git(root, 'rev-parse', 'HEAD')
    import wiki_core.ingest.protected as protected
    from wiki_core.repository_reader import RepositoryReader
    original = RepositoryReader.read
    def guarded(reader, ref, *a, **kw):
        if ref == 'memories/lens.md':
            pytest.fail('denied perspective body opened')
        return original(reader, ref, *a, **kw)
    monkeypatch.setattr(RepositoryReader, 'read', guarded)
    monkeypatch.setattr(protected, '_capture', lambda *a, **k: pytest.fail('source captured'))
    with pytest.raises(ValueError):
        prepare(root, binding, **args, source_context='system')


def test_missing_v5_never_falls_back_to_legacy_prompt(prepared_repo, monkeypatch, tmp_path):
    root, binding, args = configured(prepared_repo)
    from wiki_core.llm import context_pass
    import wiki_core.ingest.protected as protected
    prompts = tmp_path / 'prompts'; prompts.mkdir()
    (prompts / 'context_deep_read.v1.md').write_text('legacy')
    monkeypatch.setattr(context_pass, 'PROMPTS_DIR', prompts)
    monkeypatch.setattr(protected, '_capture', lambda *a, **k: pytest.fail('source captured'))
    with pytest.raises(ContextRequestBlocked, match='v5'):
        prepare(root, binding, **args, source_context='system')


def test_v5_disappearing_after_gate_never_falls_back(prepared_repo, monkeypatch, tmp_path):
    root, binding, args = configured(prepared_repo)
    from wiki_core.llm import context_pass
    import wiki_core.ingest.protected as protected
    prompts = tmp_path / 'prompts'; prompts.mkdir()
    (prompts / 'context_deep_read.v5.md').write_text('current')
    (prompts / 'context_deep_read.v1.md').write_text('legacy')
    monkeypatch.setattr(context_pass, 'PROMPTS_DIR', prompts)
    check = context_pass.require_approved_prompt_version
    calls = []
    def disappear(version, *, folder=False):
        check(version, folder=folder)
        calls.append(version)
        if len(calls) == 2:
            (prompts / 'context_deep_read.v5.md').unlink()
    monkeypatch.setattr(context_pass, 'require_approved_prompt_version', disappear)
    monkeypatch.setattr(protected, 'require_approved_prompt_version', disappear)
    with pytest.raises(ContextRequestBlocked, match='v5'):
        prepare(root, binding, **args, source_context='system')
    assert len(calls) == 2
    assert not (root / 'data/derived').exists()


def test_source_declaring_an_unqualified_configuration_is_blocked(prepared_repo):
    root, binding, args = configured(prepared_repo)
    write(root, 'source.txt', '---\nconfig_ref: memories/source-config.md\n---\nUnqualified source.\n')
    with pytest.raises(ValueError, match='requires explicit qualification'):
        prepare(root, binding, **args, source_context='system')
    assert not (root / 'data/derived').exists()


def test_nested_executor_does_not_implicitly_select_global_lenses(prepared_repo):
    root, binding, args = configured(prepared_repo)
    selected = {**args, 'context_selection': {'omit_root_entity': True}, 'perspective_refs': None}
    result = prepare(root, binding, **selected, source_context='system')
    assert result['request']['perspectives_required'] == []
    assert 'memories/root.md' not in {row['ref'] for row in result['request']['block_context_package']['inputs']}


def test_missing_explicit_root_selection_blocks_before_source_capture(prepared_repo, monkeypatch):
    root, binding, args = configured(prepared_repo)
    import wiki_core.ingest.protected as protected
    monkeypatch.setattr(protected, '_capture', lambda *a, **k: pytest.fail('source captured'))
    with pytest.raises(ValueError, match='explicit context selection'):
        prepare(root, binding, **{**args, 'context_selection': None}, source_context='system')
