"""Approved captures cannot deliver legacy unbound recording instructions."""

import json
import shutil
import sys

import pytest
import yaml

from test_ingestion_budget import BASE, approved, execute, git, load_script
from wiki_core.config import load_config
from wiki_core.ingest import run
from wiki_core.llm import context_pass
from wiki_core.paths import WikiPaths
from tests.test_protected_ingestion import prepared_repo, prepare, record
from tests.test_folder_policy_core import repo
from wiki_core.coordination_context import CoordinationBinding


def folder_args(prepared_repo):
    root, sha = prepared_repo
    return root, CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml'), dict(
        context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')


def _pin_version(root, version):
    path = root / 'wiki.config.yaml'
    config = yaml.safe_load(path.read_text())
    config.setdefault('llm', {}).setdefault('prompt_versions', {})['context_deep_read'] = version
    path.write_text(yaml.safe_dump(config))
    git(root, 'add', 'wiki.config.yaml')
    git(root, 'commit', '-qm', 'Configure synthetic prompt version')
    sha = git(root, 'rev-parse', 'HEAD')
    git(root, 'update-ref', 'refs/remotes/origin/main', sha)
    return sha


@pytest.mark.parametrize('version', ['v1', 'v2', 'v3', 'v4', 'v999'])
def test_approved_ingest_and_context_pass_reject_unsafe_version_without_replacing_request(
        prepared_repo, monkeypatch, capsys, version):
    root, binding, args = folder_args(prepared_repo)
    prepare(root, binding, **args, source_context='system')
    request_path = next((root / 'data/derived').rglob('*llm-context-request.json'))
    original = request_path.read_bytes()
    sha = _pin_version(root, version)
    with pytest.raises(context_pass.ContextRequestBlocked, match='v5'):
        prepare(root, binding, **{**args, 'approved_revision': sha}, source_context='system')
    assert request_path.read_bytes() == original

    llm = load_script('wiki_llm_context_pass')
    old_args = ['wiki_llm_context_pass.py', '--root', str(root), '--source', 'source.txt',
            '--context', 'system', '--approved-revision', sha, '--policy-context', 'root']
    # The recording payload need not exist: the version gate must refuse before it is read.
    for action in (['--emit-request'], ['--check'], ['--record-result', str(root / 'missing-result.json')]):
        monkeypatch.setattr(sys, 'argv', [*old_args, *action])
        with pytest.raises(SystemExit) as exc:
            llm.main()
        assert exc.value.code == 2
        assert 'wiki_coordination.py --source-stage' in capsys.readouterr().err
        assert request_path.read_bytes() == original


@pytest.mark.parametrize('version', ['v1', 'v2', 'v3'])
def test_historical_prompt_versions_still_work_in_working_tree_compatibility(approved, version, monkeypatch, capsys):
    root, source, _, _ = approved
    _pin_version(root, version)
    result = run(str(source), 'system', root, load_config(root))
    assert not result.blocked and result.request_path
    request = json.loads((root / result.request_path).read_text())
    assert request['prompt_version'] == version
    assert f'context_deep_read {version}' in request['prompt']
    assert '--record-result <file-or-stdin>.json --context <context>' in request['prompt']
    assert 'source_authorization' not in request

    llm = load_script('wiki_llm_context_pass')
    monkeypatch.setattr(sys, 'argv', ['wiki_llm_context_pass.py', '--root', str(root),
        '--source', str(source), '--context', 'system', '--emit-request'])
    assert llm.main() == 0
    reemitted = root / capsys.readouterr().out.strip()
    renewed = json.loads(reemitted.read_text())
    assert renewed['prompt_version'] == version
    assert f'context_deep_read {version}' in renewed['prompt']
    assert 'source_authorization' not in renewed


def test_approved_default_prompt_gives_source_bound_recording_example(prepared_repo):
    root, binding, args = folder_args(prepared_repo)
    prepared = prepare(root, binding, **args, source_context='system')
    request = prepared['request']
    assert request['prompt_version'] == 'v5'
    assert request['block_context_package']['authority_format'] == 'folder'
    assert request['source_authorization']['use'] == 'interpretation'
    prompt = request['prompt']
    assert all(flag in prompt for flag in ('--context-id', '--approved-revision', '--source-stage record'))
    assert 'compatibility' in prompt.lower()
    assert all(term in request['instructions'] for term in ('source', 'approved revision', 'policy context', 'byte limits'))
    assert '--record-result <file-or-stdin>.json --context <context>' not in prompt

    template = json.loads((BASE / 'tests/fixtures/e2e/context_pass_result.sample.json').read_text())
    row = request['chunks'][0]
    payload = {**template, **{key: request[key] for key in ('source_id', 'prompt_version', 'schema_version', 'model_profile')},
               **{key: row[key] for key in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')},
               'perspectives_required': request['perspectives_required'],
               'perspectives': {key: {'status': 'extracted'} for key in request['perspectives_required']}}
    assert record(root, binding, **args, source_id=prepared['source_id'],
                  request_id=prepared['request_id'], results=[payload])['recorded'] == 1


def test_missing_v4_never_falls_back_to_existing_v1_in_approved_flow(prepared_repo, monkeypatch, tmp_path):
    root, binding, args = folder_args(prepared_repo)
    prepare(root, binding, **args, source_context='system')
    request_path = next((root / 'data/derived').rglob('*llm-context-request.json'))
    original = request_path.read_bytes()
    prompts = tmp_path / 'legacy-prompts'
    prompts.mkdir()
    shutil.copy(context_pass.PROMPTS_DIR / 'context_deep_read.v1.md', prompts)
    monkeypatch.setattr(context_pass, 'PROMPTS_DIR', prompts)

    with pytest.raises(context_pass.ContextRequestBlocked, match='v5'):
        prepare(root, binding, **args, source_context='system')
    assert request_path.read_bytes() == original


def test_unsafe_version_blocks_empty_approved_capture_before_any_artifacts(prepared_repo, monkeypatch):
    root, binding, args = folder_args(prepared_repo)
    (root / 'source.txt').write_text('')
    git(root, 'add', 'source.txt')
    sha = _pin_version(root, 'v3')
    import wiki_core.ingest.protected as protected
    monkeypatch.setattr(protected, '_capture', lambda *a, **k: pytest.fail('source opened'))
    with pytest.raises(context_pass.ContextRequestBlocked, match='v5'):
        prepare(root, binding, **{**args, 'approved_revision': sha}, source_context='system')
    assert not (root / 'data/derived').exists()


def test_approved_prompt_disappearing_after_version_gate_never_falls_back(prepared_repo, monkeypatch, tmp_path):
    root, binding, args = folder_args(prepared_repo)
    prompts = tmp_path / 'race-prompts'
    prompts.mkdir()
    for version in ('v1', 'v5'):
        shutil.copy(context_pass.PROMPTS_DIR / f'context_deep_read.{version}.md', prompts)
    monkeypatch.setattr(context_pass, 'PROMPTS_DIR', prompts)
    original_check = context_pass.require_approved_prompt_version
    checks = 0

    def remove_after_build_gate(version, *, folder=False):
        nonlocal checks
        original_check(version, folder=folder)
        checks += 1
        if checks == 2:
            (prompts / 'context_deep_read.v5.md').unlink()

    # The pipeline imports its own reference; patch both so disappearance
    # occurs immediately after the builder's separate approval check.
    import wiki_core.ingest.protected as protected
    monkeypatch.setattr(context_pass, 'require_approved_prompt_version', remove_after_build_gate)
    monkeypatch.setattr(protected, 'require_approved_prompt_version', remove_after_build_gate)
    with pytest.raises(context_pass.ContextRequestBlocked, match='v5'):
        prepare(root, binding, **args, source_context='system')
    assert checks == 2
    assert not (root / 'data/derived').exists()
