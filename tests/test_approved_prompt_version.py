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


@pytest.mark.parametrize('version', ['v1', 'v2', 'v3', 'v999'])
def test_approved_ingest_and_context_pass_reject_unsafe_version_without_replacing_request(
        approved, monkeypatch, capsys, version):
    root, source, _, _ = approved
    first = execute(approved)
    assert not first.blocked and first.request_path
    request_path = root / first.request_path
    original = request_path.read_bytes()
    sha = _pin_version(root, version)

    blocked = run(str(source), 'system', root, load_config(root),
                  approved_revision=sha, policy_context='root')
    assert blocked.blocked and not blocked.written and blocked.blockers
    assert blocked.context_error_code == 'approved_prompt_migration_required'
    assert request_path.read_bytes() == original

    llm = load_script('wiki_llm_context_pass')
    args = ['wiki_llm_context_pass.py', '--mode', 'v1', '--root', str(root), '--source', str(source),
            '--context', 'system', '--approved-revision', sha, '--policy-context', 'root']
    # The recording payload need not exist: the version gate must refuse before it is read.
    for action in (['--emit-request'], ['--check'], ['--record-result', str(root / 'missing-result.json')]):
        monkeypatch.setattr(sys, 'argv', [*args, *action])
        assert llm.main() == 2
        report = json.loads(capsys.readouterr().out)
        assert report['blocked'] and report['blockers']
        assert report['error_code'] == 'approved_prompt_migration_required'
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
    monkeypatch.setattr(sys, 'argv', ['wiki_llm_context_pass.py', '--mode', 'working-tree', '--root', str(root),
        '--source', str(source), '--context', 'system', '--emit-request'])
    assert llm.main() == 0
    reemitted = root / capsys.readouterr().out.strip()
    renewed = json.loads(reemitted.read_text())
    assert renewed['prompt_version'] == version
    assert f'context_deep_read {version}' in renewed['prompt']
    assert 'source_authorization' not in renewed


def test_approved_default_prompt_gives_source_bound_recording_example(approved, monkeypatch, capsys):
    root, source, sha, _ = approved
    result = execute(approved)
    assert not result.blocked and result.request_path
    request = json.loads((root / result.request_path).read_text())
    assert request['prompt_version'] == 'v4'
    assert request['block_context_package']['schema_version'] == 'wiki.task-context/v1'
    assert request['source_authorization']['use'] == 'interpretation'
    prompt = request['prompt']
    assert all(flag in prompt for flag in ('--source', '--approved-revision', '--policy-context',
                                            '--context-max-bytes', '--request-max-bytes', '--record-result'))
    assert 'compatibility' in prompt.lower()
    assert all(term in request['instructions'] for term in ('source', 'approved revision', 'policy context', 'byte limits'))
    assert '--record-result <file-or-stdin>.json --context <context>' not in prompt

    template = json.loads((BASE / 'tests/fixtures/e2e/context_pass_result.sample.json').read_text())
    row = request['chunks'][0]
    payload = {**template, **{key: request[key] for key in ('source_id', 'prompt_version', 'schema_version', 'model_profile')},
               **{key: row[key] for key in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')},
               'perspectives_required': request['perspectives_required'],
               'perspectives': {key: {'status': 'extracted'} for key in request['perspectives_required']}}
    result_path = root / 'result.json'
    result_path.write_text(json.dumps(payload))
    llm = load_script('wiki_llm_context_pass')
    monkeypatch.setattr(sys, 'argv', ['wiki_llm_context_pass.py', '--mode', 'v1', '--root', str(root), '--source', str(source),
        '--context', 'system', '--approved-revision', sha, '--policy-context', 'root',
        '--context-max-bytes', '100000', '--request-max-bytes', '256000', '--record-result', str(result_path)])
    assert llm.main() == 0
    assert json.loads(capsys.readouterr().out)['count'] == 1
    assert (WikiPaths(root, load_config(root)).llm_cache / f"{row['cache_key']}.json").exists()


def test_missing_v4_never_falls_back_to_existing_v1_in_approved_flow(approved, monkeypatch, capsys, tmp_path):
    root, source, sha, _ = approved
    first = execute(approved)
    assert not first.blocked and first.request_path
    request_path = root / first.request_path
    original = request_path.read_bytes()
    prompts = tmp_path / 'legacy-prompts'
    prompts.mkdir()
    shutil.copy(context_pass.PROMPTS_DIR / 'context_deep_read.v1.md', prompts)
    monkeypatch.setattr(context_pass, 'PROMPTS_DIR', prompts)

    blocked = execute(approved)
    assert blocked.blocked and blocked.context_error_code == 'approved_prompt_migration_required'
    assert not blocked.written and request_path.read_bytes() == original
    llm = load_script('wiki_llm_context_pass')
    monkeypatch.setattr(sys, 'argv', ['wiki_llm_context_pass.py', '--mode', 'v1', '--root', str(root), '--source', str(source),
        '--context', 'system', '--approved-revision', sha, '--policy-context', 'root', '--emit-request'])
    assert llm.main() == 2
    report = json.loads(capsys.readouterr().out)
    assert report['error_code'] == 'approved_prompt_migration_required'
    assert request_path.read_bytes() == original


def test_unsafe_version_blocks_empty_approved_capture_before_any_artifacts(approved):
    root, source, _, _ = approved
    source.write_text('')
    git(root, 'add', 'source.md')
    sha = _pin_version(root, 'v3')
    result = run(str(source), 'system', root, load_config(root),
                 approved_revision=sha, policy_context='root')
    assert result.blocked and result.context_error_code == 'approved_prompt_migration_required'
    assert not result.written and result.request_path is None
    assert not WikiPaths(root, load_config(root)).derived_root.exists()


def test_approved_prompt_disappearing_after_version_gate_never_falls_back(approved, monkeypatch, tmp_path):
    root, _, _, _ = approved
    prompts = tmp_path / 'race-prompts'
    prompts.mkdir()
    for version in ('v1', 'v4'):
        shutil.copy(context_pass.PROMPTS_DIR / f'context_deep_read.{version}.md', prompts)
    monkeypatch.setattr(context_pass, 'PROMPTS_DIR', prompts)
    original_check = context_pass.require_approved_prompt_version
    checks = 0

    def remove_after_build_gate(version):
        nonlocal checks
        original_check(version)
        checks += 1
        if checks == 2:
            (prompts / 'context_deep_read.v4.md').unlink()

    # The pipeline imports its own reference; patch both so disappearance
    # occurs immediately after the builder's separate approval check.
    import wiki_core.ingest.pipeline as pipeline
    monkeypatch.setattr(context_pass, 'require_approved_prompt_version', remove_after_build_gate)
    monkeypatch.setattr(pipeline, 'require_approved_prompt_version', remove_after_build_gate)
    result = execute(approved)
    assert checks == 2
    assert result.blocked and result.context_error_code == 'approved_prompt_migration_required'
    assert not result.written and result.request_path is None
    assert not WikiPaths(root, load_config(root)).derived_root.exists()
