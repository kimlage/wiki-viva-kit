"""Isolated experiment: reuse source artifacts for an explicitly selected Git blob.

The mapping is fixture code, not a supported ingestion or authorization API.
"""
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from tests.test_repo_read import git, repo
from wiki_core.chunking import chunk_text
from wiki_core.index.sqlite import index_source, search
from wiki_core.llm import build_context_request, CONTEXT_PASS_SCHEMA_VERSION
from wiki_core.llm.context_pass import context_fingerprint
from wiki_core.repo_read import read_independent_repo, RepoReadError
import pytest
from wiki_core.source_manifest import build_manifest, chunk_document


def _candidate_manifest(receipt):
    origin = {'kind': 'repository_path', 'repository': receipt['repository']['identity'],
              'locator': receipt['path']}
    origin['id'] = hashlib.sha256(json.dumps(origin, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    digest = receipt['document_sha256']
    return {'schema_version': 'wiki_source_manifest.v1',
            'source_id': f"source-v2-{origin['id']}-guide-md-{digest[:16]}",
            'source_uri': receipt['path'], 'source_origin': origin, 'source_type': 'markdown',
            'context': 'system', 'captured_at': '2026-01-01T00:00:00+00:00',
            'hash_sha256': digest, 'repository_read': {k: v for k, v in receipt.items() if k != 'text'}}


def test_selected_git_blob_composes_with_existing_source_artifacts_but_loses_revision_on_recapture(repo, tmp_path):
    identity = 'example.test/group/project'
    first_sha = git(repo, 'rev-parse', 'HEAD')
    first = read_independent_repo(repo, identity, first_sha, 'guide.md')
    (repo / 'guide.md').write_text('Uncommitted working tree difference.\n')
    local_manifest = build_manifest(str(repo / 'guide.md'), 'system', root=tmp_path)
    manifest = _candidate_manifest(first)
    assert local_manifest['hash_sha256'] != manifest['hash_sha256']
    assert manifest['repository_read']['revision'] == first_sha
    assert manifest['repository_read']['blob'] == first['blob']
    assert 'caller_authorization_required' in first['access']
    # Re-read the exact host-supplied selection; WIP must not replace the blob.
    assert read_independent_repo(repo, identity, first_sha, 'guide.md') == first

    chunks = [asdict(row) for row in chunk_text(manifest['source_id'], first['text'])]
    data = chunk_document(manifest, chunks)
    path = tmp_path / 'chunks' / f"{manifest['source_id']}.json"
    path.parent.mkdir(); path.write_text(json.dumps(data))
    db = tmp_path / 'index.sqlite'
    assert index_source(db, path)['chunks_indexed'] == 1
    assert search(db, 'Useful')[0]['source_id'] == manifest['source_id']
    request = build_context_request(manifest, chunks, tmp_path / 'cache', 'v4',
                                    CONTEXT_PASS_SCHEMA_VERSION, 'deep_context')
    assert request['chunks'][0]['provenance']['origin_id'] == manifest['source_origin']['id']
    assert 'repository_read' not in request

    (repo / 'unrelated.md').write_text('Another file.\n')
    git(repo, 'add', 'unrelated.md'); git(repo, 'commit', '-qm', 'unrelated change')
    second_sha = git(repo, 'rev-parse', 'HEAD')
    second = read_independent_repo(repo, identity, second_sha, 'guide.md')
    second_manifest = _candidate_manifest(second)
    assert first_sha != second_sha and first['text'] == second['text']
    assert first['blob'] == second['blob'] and first != second
    assert manifest['source_id'] == second_manifest['source_id']
    assert manifest['repository_read']['revision'] != second_manifest['repository_read']['revision']

    # Folder-v2 already binds this receipt to its semantic request fingerprint.
    # This demonstrates that separate contextual identities are possible; it
    # does not make the v1 recording route honor or retain these requests.
    def with_receipt(receipt):
        return {**request, 'source_authorization': {
            'independent_repo_read': {k: v for k, v in receipt.items() if k != 'text'}},
            'independent_repo_content': receipt['text']}
    provenance = request['chunks'][0]['provenance']
    assert context_fingerprint(with_receipt(first), provenance) != context_fingerprint(with_receipt(second), provenance)

    git(repo, 'remote', 'set-url', 'origin', 'https://example.test/group/another.git')
    with pytest.raises(RepoReadError, match='repository_identity_mismatch'):
        read_independent_repo(repo, identity, first_sha, 'guide.md')
