"""An undeclared message projection is not qualified source provenance."""
import hashlib
import json

import pytest

from tests.test_folder_policy_core import repo
from tests.test_protected_ingestion import prepared_repo, prepare, protected_source_stage
from wiki_core.coordination_context import CoordinationBinding, ProtectedCoordinationError


@pytest.mark.parametrize('declaration', [
    {'source_representation': 'sanitized_projection'},
    {'protected_provenance': {'representation': 'sanitized_projection'}},
])
def test_declared_projection_is_rejected_before_source_open(prepared_repo, monkeypatch, declaration):
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    # This original is synthetic and remains in memory. The selected file is
    # an illustrative projection, not a qualified transformation.
    original = b'Subject: Example\r\n\r\nhttps://tracking.invalid/unique-synthetic-id\r\n'
    projection = b'A review was requested.\n'
    assert b'tracking.invalid' in original and b'tracking.invalid' not in projection
    (root / 'source.txt').write_bytes(projection)

    from pathlib import Path
    original_open = Path.open

    def deny_source_open(path, *args, **kwargs):
        if path == root / 'source.txt':
            pytest.fail('unsupported projection was opened')
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', deny_source_open)
    payload = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md',
                   source_ref='source.txt', source_context='system', **declaration)
    with pytest.raises(ProtectedCoordinationError, match='coordination_invalid_request'):
        protected_source_stage(root, binding, 'prepare', payload)
    assert not (root / 'data/derived').exists()
    assert not (root / 'memories/system/ingestion/events').exists()


def test_unmarked_projection_hash_identifies_local_file_only(prepared_repo):
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    original = b'Subject: Example\r\n\r\nhttps://tracking.invalid/unique-synthetic-id\r\n'
    projection = b'A review was requested.\n'
    (root / 'source.txt').write_bytes(projection)
    result = prepare(root, binding, context_id='.', approved_revision=sha,
                     entry_folder='.', entry_index='index.md', source_ref='source.txt', source_context='system')
    request = result['request']
    assert request['source_hash_sha256'] == hashlib.sha256(projection).hexdigest()
    assert request['source_hash_sha256'] != hashlib.sha256(original).hexdigest()
    assert 'source_representation' not in request
    assert 'tracking.invalid' not in json.dumps(request)
    # This control records today's unsafe-to-infer boundary, not approval to
    # use an unmarked projection or evidence about the provider original.
