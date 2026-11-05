"""Approved folder selection retains the existing policy's boundaries."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest
import yaml

from tests.test_ingestion_budget import approved, git
from wiki_core.config import load_config
from wiki_core.ingest import run
from wiki_core.paths import WikiPaths


def approve_folder(approved):
    root, source, previous, policy = approved
    # Grant explicit writes for this synthetic owner; path selection itself
    # must never add a permission.
    policy['policy']['write'] = ['self']
    (root / 'context.yaml').write_text(yaml.safe_dump(policy))
    (root / 'area' / 'aux').mkdir(parents=True)
    (root / 'area' / 'AGENTS.md').write_text('approved-area-instruction\n')
    (root / 'area' / 'index.md').write_text('approved-area-index\n')
    (root / 'area' / 'aux' / 'AGENTS.override.md').write_text('approved-aux-instruction\n')
    git(root, 'add', 'area', 'context.yaml')
    git(root, 'commit', '-qm', 'Add approved folder context')
    sha = git(root, 'rev-parse', 'HEAD')
    git(root, 'update-ref', 'refs/remotes/origin/main', sha)
    return root, source, previous, sha


def test_approved_folder_uses_approved_git_not_unapproved_worktree(approved):
    root, source, _, sha = approve_folder(approved)
    (root / 'area' / 'AGENTS.md').write_text('unapproved-area-instruction\n')
    (root / 'area' / 'index.md').write_text('unapproved-area-index\n')
    (root / 'area' / 'aux' / 'AGENTS.override.md').write_text('unapproved-aux-instruction\n')
    result = run(str(source), 'system', root, load_config(root), entry_folder='area/aux',
                 approved_revision=sha, policy_context='root', record_score=False)
    assert not result.blocked, result.blockers
    request = json.loads((root / result.request_path).read_text())
    encoded = json.dumps(request['block_context_package'], ensure_ascii=False)
    for body in ('approved-area-instruction', 'approved-area-index', 'approved-aux-instruction'):
        assert body in encoded
    assert 'unapproved-' not in encoded
    assert request['source_authorization']['policy_revision'] == sha
    assert request['source_authorization']['context_id'] == 'root'


def test_wrong_owner_fails_before_source_or_context_body_read(approved, monkeypatch):
    root, source, _, _ = approved
    (root / 'other').mkdir()
    (root / 'other' / 'AGENTS.md').write_text('other instruction\n')
    (root / 'other' / 'index.md').write_text('other index\n')
    child = {'schema_version': 'wiki.context/v1', 'id': 'other', 'parent': 'root',
             'root': 'other', 'purpose': 'Other owner', 'owner': 'Other coordinator',
             'instructions': ['other/AGENTS.md'], 'skills': [], 'templates': [],
             'imports': [], 'exports': [], 'policy': {'read': ['self'], 'write': [],
             'capabilities': [], 'publication': [], 'deny': {}}}
    (root / 'other' / 'context.yaml').write_text(yaml.safe_dump(child))
    git(root, 'add', 'other')
    git(root, 'commit', '-qm', 'Approve independently owned folder')
    sha = git(root, 'rev-parse', 'HEAD')
    git(root, 'update-ref', 'refs/remotes/origin/main', sha)
    original_open = Path.open
    def guarded_open(path, *args, **kwargs):
        if path == source or path.name in {'AGENTS.md', 'index.md'}:
            pytest.fail('content opened for a mismatched policy owner')
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guarded_open)
    from wiki_core.repository_reader import RepositoryReader
    monkeypatch.setattr(RepositoryReader, 'read', lambda *_args, **_kwargs: pytest.fail('context body read'))
    result = run(str(source), 'system', root, load_config(root), entry_folder='other',
                 approved_revision=sha, policy_context='root', record_score=False)
    assert result.blocked and not result.written
    assert not WikiPaths(root, load_config(root)).derived_root.exists()


def test_approved_repo_without_grant_fails_before_repo_read(approved, monkeypatch):
    root, source, _, sha = approve_folder(approved)
    import wiki_core.repo_read as repo_read
    monkeypatch.setattr(repo_read, '_prepare_repo_read', lambda *_args, **_kwargs: pytest.fail('independent Git opened'))
    result = run(str(source), 'system', root, load_config(root), entry_folder='area/aux',
                 approved_revision=sha, policy_context='root', record_score=False,
                 repo_selections=[('area/clone', 'example.test/org/repo', 'a' * 40, 'README.md')])
    assert result.blocked and not result.written
    assert not WikiPaths(root, load_config(root)).derived_root.exists()


def test_approved_folder_revalidates_policy_before_persistence(approved, monkeypatch):
    root, source, previous, sha = approve_folder(approved)
    import wiki_core.ingest.pipeline as pipeline
    original = pipeline.build_context_request
    invoked = []
    def revoke_after_request(*args, **kwargs):
        request = original(*args, **kwargs)
        invoked.append(True)
        git(root, 'update-ref', 'refs/remotes/origin/main', previous)
        return request
    monkeypatch.setattr(pipeline, 'build_context_request', revoke_after_request)
    result = run(str(source), 'system', root, load_config(root), entry_folder='area/aux',
                 approved_revision=sha, policy_context='root', record_score=False)
    assert invoked and result.blocked and not result.written
    assert not WikiPaths(root, load_config(root)).derived_root.exists()


def test_approved_folder_record_and_consolidate_require_current_authority(approved, monkeypatch, tmp_path, capsys):
    from tests.test_local_result_cache import module, result_for
    root, source, previous, sha = approve_folder(approved)
    config = load_config(root)
    prepared = run(str(source), 'system', root, config, entry_folder='area/aux',
                   approved_revision=sha, policy_context='root', record_score=False)
    assert not prepared.blocked, prepared.blockers
    request = json.loads((root / prepared.request_path).read_text())
    payload = tmp_path / 'result.json'
    payload.write_text(json.dumps(list({row['cache_key']: result_for(request, row)
                                       for row in request['chunks']}.values())))
    flags = ['--approved-revision', sha, '--policy-context', 'root']
    cli = module('wiki_llm_context_pass')
    record = ['wiki_llm_context_pass.py', '--root', str(root), '--source', str(source),
              '--context', 'system', '--folder', 'area/aux', '--request', prepared.request_path,
              '--record-result', str(payload), *flags]
    monkeypatch.chdir(root)
    git(root, 'update-ref', 'refs/remotes/origin/main', previous)
    monkeypatch.setattr(sys, 'argv', record)
    assert cli.main() != 0
    capsys.readouterr()
    paths = WikiPaths(root, config)
    assert not list(paths.llm_cache.rglob('*.json'))
    git(root, 'update-ref', 'refs/remotes/origin/main', sha)
    assert cli.main() == 0
    capsys.readouterr()
    assert list(paths.llm_cache.rglob('*.json'))

    paths.ingest_events_dir.mkdir(parents=True, exist_ok=True)
    consolidate = module('wiki_consolidate')
    monkeypatch.setattr(consolidate, 'ROOT', root)
    argv = ['wiki_consolidate.py', '--source', prepared.source_id, '--request', prepared.request_path,
            '--context', 'system', '--source-page', 'source.md', '--emit-event', '--packet',
            '--source-file', str(source), *flags]
    git(root, 'update-ref', 'refs/remotes/origin/main', previous)
    monkeypatch.setattr(sys, 'argv', argv)
    assert consolidate.main() != 0
    capsys.readouterr()
    assert not list(paths.ingest_events_dir.glob('*.md'))
    assert not list(paths.extraction_events.glob('*-integration-packet.json'))
    git(root, 'update-ref', 'refs/remotes/origin/main', sha)
    assert consolidate.main() == 0
    capsys.readouterr()
    assert len(list(paths.ingest_events_dir.glob('*.md'))) == 1
