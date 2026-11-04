"""Read-only, host-scoped inspection of an explicitly declared staged capture."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import yaml

from wiki_core.context_policy import _git, safe_path, UniqueLoader
from wiki_core.frontmatter import FRONTMATTER_RE
from wiki_core.folder_coordination_v2 import _bound_policy
from wiki_core.folder_ingestion_v2 import _check_local_boundaries
from wiki_core.folder_policy_v2 import _at_revision
from wiki_core.repo_read import contains_access_secrets
from wiki_core.repository_reader import RepositoryReader
from wiki_core.source_manifest import source_origin


CAPTURE_KEYS = frozenset({'source_kind', 'ref', 'source_revision', 'source_sha256', 'source_origin',
                          'canonical_ref', 'canonical_revision', 'canonical_sha256', 'association',
                          'external_origin_verification', 'external_freshness'})


def validate_recorded_request(root, packet, request):
    """Verify an explicit request and its existing result cache; not execution proof."""
    from wiki_core.config import load_config
    from wiki_core.folder_ingestion_v2 import validate_folder_artifact_paths
    from wiki_core.llm.context_pass import read_matching_result
    from wiki_core.paths import WikiPaths

    try:
        if (not isinstance(request, dict) or contains_access_secrets(request)
                or len(json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()) > 2_000_000):
            raise ValueError('invalid request')
        auth = request['source_authorization']
        from wiki_core.folder_ingestion_v2 import ingestion_binding_for_authorization
        if (request.get('context_binding_version') != 2 or request.get('block_context_package') != packet
                or not isinstance(auth, dict) or packet.get('ingestion_binding') != ingestion_binding_for_authorization(auth)
                or request.get('source_hash_sha256') != auth.get('source_sha256')):
            raise ValueError('capture binding unavailable')
        chunks = request['chunks']
        if not isinstance(chunks, list) or not 1 <= len(chunks) <= 256:
            raise ValueError('capture results unavailable')
        keys = [row.get('cache_key') for row in chunks if isinstance(row, dict)]
        if len(keys) != len(chunks) or len(keys) != len(set(keys)):
            raise ValueError('invalid capture results')
        paths = WikiPaths(Path(root), load_config(Path(root)))
        validate_folder_artifact_paths(root, paths, request['source_id'])
        if any(read_matching_result(paths.llm_cache, request, row, root=root) is None for row in chunks):
            raise ValueError('capture results unavailable')
    except (ValueError, OSError, TypeError, KeyError, AttributeError, RecursionError):
        raise ValueError('capture request unavailable') from None


def validate_recorded_capture_request(root, packet, request, capture):
    validate_recorded_request(root, packet, request)
    try:
        auth = request['source_authorization']
        if {key:auth[key] for key in CAPTURE_KEYS} != capture:
            raise ValueError('capture binding unavailable')
    except (ValueError, TypeError, KeyError):
        raise ValueError('capture request unavailable') from None


def repository_receipt_projection(receipt):
    """Retain exact local Git identity and digests, never repository text."""
    return {'identity': receipt['repository']['identity'],
            **{key: receipt[key] for key in ('revision', 'path', 'blob', 'document_sha256',
                                            'content_sha256', 'section', 'field')}}


def validate_ingestion_projections(request, metadata):
    """Require the canonical minimal projections dictated by the recorded authorization."""
    try:
        auth = request['source_authorization']
        capture = ({key: auth[key] for key in CAPTURE_KEYS}
                   if auth['source_kind'] == 'staged_raw' else None)
        receipt = auth.get('independent_repo_read')
        repo = repository_receipt_projection(receipt) if receipt is not None else None
        additional = [repository_receipt_projection(row)
                      for row in auth.get('independent_repo_additional_reads', [])] or None
        if (metadata.get('source_authorization') != capture
                or metadata.get('independent_repo_read') != repo
                or metadata.get('independent_repo_additional_reads') != additional):
            raise ValueError('ingestion projections differ')
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ValueError('ingestion projections unavailable') from None


def inspect_reported_repository(root, binding, folder, approved_revision, packet, request, projection, additional_projections=None):
    """Revalidate the explicitly bound prior repo selection and reported request."""
    from wiki_core.folder_ingestion_v2 import independent_repo_selection_for_request, additional_repo_selections_for_request
    from wiki_core.folder_reassessment_v2 import _repository_node_matches
    from wiki_core.repo_read import read_independent_repo
    try:
        policy = _bound_policy(root, binding, folder, approved_revision)
        validate_recorded_request(binding.root, packet, request)
        auth = request['source_authorization']; receipt = auth['independent_repo_read']
        if repository_receipt_projection(receipt) != projection:
            raise ValueError('repository metadata differs')
        chosen = independent_repo_selection_for_request(binding, folder, auth)
        if chosen is None:
            raise ValueError('repository selection unavailable')
        additional = additional_repo_selections_for_request(binding, folder, auth)
        receipts = auth.get('independent_repo_additional_reads', [])
        contents = request.get('independent_repo_additional_content', [])
        if (not isinstance(receipts, list) or not isinstance(contents, list)
                or len(receipts) != len(additional) or len(contents) != len(additional)
                or [repository_receipt_projection(row) for row in receipts] != (additional_projections or [])):
            raise ValueError('additional repository selections differ')
        repo_root, identity, revision, path = chosen
        node_ref = safe_path(auth['canonical_ref'])
        context = policy.folder_ids[folder]
        producer = policy.owner_of(node_ref)
        if policy.connection(producer, context, node_ref, 'interpretation', 'source') != 'approved':
            raise ValueError('source authority unavailable')
        node = RepositoryReader(binding.root, policy.policy_revision).read(node_ref)
        if not _repository_node_matches(node['text'], identity):
            raise ValueError('repository node unavailable')
        read = read_independent_repo(Path(repo_root), identity, revision, path,
                                     section=receipt.get('section'), field=receipt.get('field'))
        if ({key:value for key,value in read.items() if key != 'text'} != receipt
                or read['text'] != request.get('independent_repo_content')):
            raise ValueError('repository selection differs')
        for extra, extra_receipt, extra_content in zip(additional, receipts, contents):
            extra_root, extra_identity, extra_revision, extra_path = extra
            if extra_identity != identity:
                raise ValueError('repository identity differs')
            extra_read = read_independent_repo(Path(extra_root), extra_identity, extra_revision, extra_path,
                                               section=extra_receipt.get('section'), field=extra_receipt.get('field'))
            if ({key:value for key,value in extra_read.items() if key != 'text'} != extra_receipt
                    or extra_read['text'] != extra_content):
                raise ValueError('repository selection differs')
        policy.fresh()
        return {'identity':identity, 'path':path, 'revision':revision,
                'content_sha256':read['content_sha256'], 'verification':'caller_reported_not_independently_verified'}
    except (ValueError, OSError, TypeError, KeyError, AttributeError, RecursionError):
        raise ValueError('repository request unavailable') from None


def inspect_raw_capture(root, binding, folder, approved_revision, capture):
    """Recheck a selected RAW file and canonical source; never write or grant access.

    The host must have authority to read complete blobs. Matching local bytes
    does not authenticate an external origin or establish external freshness.
    """
    try:
        if (not isinstance(capture, dict) or set(capture) != CAPTURE_KEYS or contains_access_secrets(capture)
                or capture['source_kind'] != 'staged_raw' or capture['source_revision'] is not None
                or capture['association'] != 'caller_selected_unverified'
                or capture['external_origin_verification'] != 'not_verified'
                or capture['external_freshness'] != 'not_verified'):
            raise ValueError('invalid capture')
        ref = safe_path(capture['ref']); canonical = safe_path(capture['canonical_ref'])
        if ref == canonical:
            raise ValueError('invalid association')
        old = capture['canonical_revision']
        if (not isinstance(old, str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', old)
                or any(not isinstance(capture[key], str) or not re.fullmatch(r'[0-9a-f]{64}', capture[key])
                       for key in ('source_sha256', 'canonical_sha256'))):
            raise ValueError('invalid capture identity')
        policy = _bound_policy(root, binding, folder, approved_revision)
        root = binding.root
        context = policy.folder_ids[folder]
        _git(root, 'merge-base', '--is-ancestor', old, policy.policy_revision)
        historical = _at_revision(Path(root), old, policy.controls_path)
        if historical.folder_ids.get(folder) != context:
            raise ValueError('historical context unavailable')
        for selected in (ref, canonical):
            producer = policy.owner_of(selected)
            if (policy.connection(producer, context, selected, 'interpretation', 'source') != 'approved'
                    or historical.owner_of(selected) != producer
                    or historical.connection(producer, context, selected, 'interpretation', 'source') != 'approved'):
                raise ValueError('source authority unavailable')
        # Historical source-page bytes are read only after both policies have
        # authorized both selected paths. No source body is returned.
        reader = RepositoryReader(root, old)
        document = reader.read(canonical)
        match = FRONTMATTER_RE.match(document['text'])
        if match is None:
            raise ValueError('canonical source unavailable')
        try:
            fm = yaml.load(match.group(1), Loader=UniqueLoader)
        except yaml.YAMLError:
            raise ValueError('canonical source unavailable') from None
        if not isinstance(fm, dict):
            raise ValueError('canonical source unavailable')
        if (document['content_sha256'] != capture['canonical_sha256']
                or fm.get('page_type') != 'source' or not isinstance(fm.get('platform'), str)
                or not fm['platform'].strip() or not isinstance(fm.get('source_locator'), str)
                or not fm['source_locator'].strip()):
            raise ValueError('canonical source unavailable')
        _check_local_boundaries(root, ref)
        path = Path(root) / ref
        if not path.is_file() or source_origin(str(path), root) != capture['source_origin']:
            raise ValueError('capture unavailable')
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        policy.fresh()
        return {'captured_sha256': capture['source_sha256'], 'current_sha256': digest.hexdigest(),
                'association': 'caller_selected_unverified', 'external_freshness': 'not_verified'}
    except (ValueError, OSError, TypeError, KeyError, AttributeError, RecursionError):
        raise ValueError('capture unavailable or unauthorized') from None
