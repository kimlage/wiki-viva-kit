"""Isolated composition experiment; not an ingestion or authorization API."""
from dataclasses import asdict
from pathlib import Path
import json

import pytest

from tests.test_repo_read import repo, git
from wiki_core.chunking import chunk_text
from wiki_core.ids import sha256_text
from wiki_core.llm import CONTEXT_PASS_SCHEMA_VERSION, build_context_request
from wiki_core.llm.context_pass import result_matches_request, ContextRequestBlocked
from wiki_core.repo_read import read_independent_repo, RepoReadError


def test_git_receipt_composes_with_existing_request_but_still_needs_host_revalidation(repo, tmp_path):
    identity = 'example.test/group/project'
    old_sha = git(repo, 'rev-parse', 'HEAD')
    selection = (repo, identity, old_sha, 'guide.md')
    old = read_independent_repo(*selection)
    source_text = 'Synthetic wiki source node.'
    source_id = 'source-synthetic'
    manifest = {'source_id': source_id, 'context': 'system',
                'hash_sha256': sha256_text(source_text),
                'source_origin': {'id': 'a' * 64}}
    chunks = [asdict(row) for row in chunk_text(source_id, source_text)]

    def request_for(receipt, *, context_limit=100_000):
        # Proposed mapping only: a document in the existing context package.
        document = {'path': receipt['path'], 'text': receipt['text'],
                    'content_sha256': receipt['content_sha256'],
                    'repository_root': str(repo.resolve()),
                    'repository_read': {k: v for k, v in receipt.items() if k != 'text'}}
        package = {'schema_version': 'wiki_block_stack.v1', 'documents': [document],
                   'policy_mode': 'legacy_working_tree_compatibility', 'policy_enforced': False}
        return build_context_request(manifest, chunks, tmp_path / 'cache', 'v4',
                                     CONTEXT_PASS_SCHEMA_VERSION, 'deep_context',
                                     block_context_package=package, context_max_bytes=context_limit)

    first = request_for(old)
    row = first['chunks'][0]
    document = first['block_context_package']['documents'][0]
    assert document['repository_root'] == str(repo.resolve())
    assert document['repository_read']['repository']['identity'] == identity
    assert document['repository_read']['revision'] == old_sha
    assert document['repository_read']['path'] == 'guide.md'
    assert document['repository_read']['blob'] == old['blob']
    assert 'caller_authorization_required' in document['repository_read']['access']
    assert first['byte_accounting']['context_bytes'] >= len(old['text'].encode())
    with pytest.raises(ContextRequestBlocked, match='budget'):
        request_for(old, context_limit=10)

    template = json.loads((Path(__file__).parent / 'fixtures/e2e/context_pass_result.sample.json').read_text())
    result = {**template, 'perspectives': {}, **{key: first[key] for key in ('source_id', 'prompt_version', 'schema_version', 'model_profile')},
              **{key: row[key] for key in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')}}
    assert result_matches_request(result, first, row, recording=True)
    (repo / 'unrelated.md').write_text('synthetic unrelated change\n')
    git(repo, 'add', 'unrelated.md'); git(repo, 'commit', '-qm', 'unrelated')
    current = read_independent_repo(repo, identity, git(repo, 'rev-parse', 'HEAD'), 'guide.md')
    assert current['blob'] == old['blob'] and current['revision'] != old['revision']
    second = request_for(current)
    assert second['source_id'] == first['source_id']
    assert second['chunks'][0]['cache_key'] != row['cache_key']
    assert not result_matches_request(result, second, second['chunks'][0], recording=True)
    assert read_independent_repo(*selection) == old
    git(repo, 'remote', 'set-url', 'origin', 'https://example.test/group/another.git')
    with pytest.raises(RepoReadError, match='repository_identity_mismatch'):
        read_independent_repo(*selection)
