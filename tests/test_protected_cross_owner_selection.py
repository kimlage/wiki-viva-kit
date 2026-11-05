"""Protected ingestion uses the host binding for selected foreign context."""
import copy
import json
from pathlib import Path

import pytest
import yaml

from tests.test_folder_policy_core import repo, write, git, enable_alpha
from tests.test_protected_ingestion import prepared_repo, _nested_integrator_repo
from wiki_core.coordination_context import CoordinationBinding
from wiki_core.ingest.protected import prepare, record
from wiki_core.repository_reader import RepositoryReader


def test_protected_source_selection_rebinds_foreign_owner_before_read(prepared_repo, monkeypatch):
    root, _ = prepared_repo
    enable_alpha(root)
    config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
    rule = {'from_context': 'alpha', 'to_context': '.', 'selector': 'alpha/shared-source.md',
            'use': 'interpretation', 'classification': 'source', 'expires': '2099-01-01'}
    config['context_access']['.']['imports'] = [copy.deepcopy(rule)]
    config['context_access']['alpha']['exports'] = [copy.deepcopy(rule)]
    write(root, 'wiki.config.yaml', yaml.safe_dump(config))
    write(root, 'alpha/shared-source.md', '---\npage_id: shared-source\npage_type: source\n---\n# Shared source\n')
    git(root, 'add', '.'); git(root, 'commit', '-qm', 'authorize selected source context')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    sha = git(root, 'rev-parse', 'HEAD')
    args = {'context_id': '.', 'approved_revision': sha, 'entry_folder': '.', 'entry_index': 'index.md',
            'source_ref': 'source.txt', 'source_context': 'system',
            'context_selection': {'omit_root_entity': True, 'source_page': 'alpha/shared-source.md'}}
    limited = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    original = RepositoryReader.read
    opened = []
    def spy(reader, ref, **kwargs):
        opened.append(ref)
        return original(reader, ref, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    with pytest.raises(ValueError, match='authorized requalification'):
        prepare(root, limited, **args)
    assert 'alpha/shared-source.md' not in opened
    assert 'alpha/AGENTS.override.md' not in opened
    binding = CoordinationBinding(('.', 'alpha'), 'refs/remotes/origin/main', 'wiki.config.yaml')
    prepared = prepare(root, binding, **args)
    request = prepared['request']
    selected = request['block_context_package']['inputs']
    assert any(item['ref'] == 'alpha/shared-source.md' for item in selected)
    assert not any(item['ref'] == 'alpha/AGENTS.override.md' for item in selected)
    row = request['chunks'][0]
    sample = json.loads((Path(__file__).parent / 'fixtures/e2e/context_pass_result.sample.json').read_text())
    result = {**sample, **{key: request[key] for key in ('source_id', 'prompt_version', 'schema_version', 'model_profile')},
              **{key: row[key] for key in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')},
              'perspectives_required': request['perspectives_required'], 'perspectives': {}}
    ids = {'source_id': prepared['source_id'], 'request_id': prepared['request_id']}
    opened.clear()
    with pytest.raises(ValueError, match='authorized requalification'):
        record(root, limited, **{key: value for key, value in args.items() if key != 'source_context'}, **ids, results=[result])
    assert 'alpha/shared-source.md' not in opened
    assert record(root, binding, **{key: value for key, value in args.items() if key != 'source_context'}, **ids, results=[result])['recorded'] == 1
    from wiki_core.ingest.protected import _scoped_stage
    @_scoped_stage
    def shared_stage_cache():
        prepare(root, binding, **args)
        opened.clear()
        with pytest.raises(ValueError, match='authorized requalification'):
            prepare(root, limited, **args)
        assert 'alpha/shared-source.md' not in opened
    shared_stage_cache()


@pytest.mark.parametrize('grant_case', ['none', 'missing_raw', 'both'])
def test_nested_executor_reads_selected_root_page_only_with_exact_grant(prepared_repo, monkeypatch, grant_case):
    root, _ = prepared_repo
    _nested_integrator_repo(root)
    page = 'memories/sources/synthetic.md'
    config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
    source_rule = {'from_context': '.', 'to_context': 'alpha', 'selector': page,
                   'use': 'interpretation', 'classification': 'source', 'expires': '2099-01-01'}
    source_file_rule = {**source_rule, 'selector': 'source.txt'}
    config['context_access']['alpha']['policy']['read'].append('source.txt')
    grants = [] if grant_case == 'none' else [source_rule]
    if grant_case == 'both': grants.append(source_file_rule)
    config['context_access']['.']['exports'].extend(grants)
    config['context_access']['alpha']['imports'].extend(copy.deepcopy(grants))
    write(root, 'wiki.config.yaml', yaml.safe_dump(config))
    # Always create a new approved fixture revision, including the denied case.
    write(root, 'synthetic-fixture.md', '# Synthetic fixture\n')
    git(root, 'add', '.'); git(root, 'commit', '-qm', 'explicit root source selection')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    sha = git(root, 'rev-parse', 'HEAD')
    args = {'context_id': 'alpha', 'approved_revision': sha, 'entry_folder': 'alpha',
            'entry_index': 'alpha/index.md', 'source_ref': 'source.txt', 'source_context': 'alpha',
            'artifact_context': '.', 'context_selection': {'omit_root_entity': True, 'source_page': page}}
    binding = CoordinationBinding(('.', 'alpha'), 'refs/remotes/origin/main', 'wiki.config.yaml')
    opened = []
    original = RepositoryReader.read
    def spy(reader, ref, **kwargs):
        opened.append(ref)
        return original(reader, ref, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    if grant_case != 'both':
        original_open = Path.open
        def path_spy(path, *values, **kwargs):
            assert path != root / 'source.txt', 'unauthorized raw source opened'
            return original_open(path, *values, **kwargs)
        monkeypatch.setattr(Path, 'open', path_spy)
        with pytest.raises(ValueError): prepare(root, binding, **args)
        if grant_case == 'none': assert page not in opened
        return
    prepared = prepare(root, binding, **args)
    request = prepared['request']
    assert any(item['ref'] == page for item in request['block_context_package']['inputs'])
    assert request['block_context_package']['additional_readers'] == ['.']
    row = request['chunks'][0]
    sample = json.loads((Path(__file__).parent / 'fixtures/e2e/context_pass_result.sample.json').read_text())
    result = {**sample, **{key: request[key] for key in ('source_id', 'prompt_version', 'schema_version', 'model_profile')},
              **{key: row[key] for key in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')},
              'perspectives_required': request['perspectives_required'], 'perspectives': {}}
    ids = {'source_id': prepared['source_id'], 'request_id': prepared['request_id']}
    assert record(root, binding, **{key: value for key, value in args.items() if key != 'source_context'}, **ids, results=[result])['recorded'] == 1
