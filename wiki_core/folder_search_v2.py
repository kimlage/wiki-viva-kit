"""Bounded literal search of an explicitly authorized folder or selected source."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path, PurePosixPath

from wiki_core.context_policy import safe_path, within
from wiki_core.folder_coordination_v2 import _bound_policy
from wiki_core.folder_declarations_v2 import preauthorize_index, authorized_instruction_chain, authorized_index
from wiki_core.repo_read import contains_access_secrets
from wiki_core.repository_reader import RepositoryReader


class FolderSearchError(ValueError):
    """Opaque failure; denied source paths and content are not returned."""
    def __init__(self, code='folder_search_unavailable_or_unauthorized'):
        self.code = code
        super().__init__(code)


def search_folder(root, binding, *, approved_revision, folder, index_path, query,
                  scope=None, raw_capture=None, repository=None, max_files=256,
                  max_bytes=1_000_000, max_hits=100):
    """Search complete authorized selections; no global index or model is used.

    The host binding is trusted configuration, not a capability or sandbox.
    A RAW association is caller asserted; a repo's configured origin is not
    remote authentication. No result proves a human/agent read or freshness.
    """
    try:
        if (not isinstance(query, str) or not query.strip() or len(query) > 512
                or any(ord(char) < 32 or ord(char) == 127 for char in query) or contains_access_secrets(query)
                or sum(value is not None for value in (scope, raw_capture, repository)) != 1
                or type(max_files) is not int or not 1 <= max_files <= 256
                or type(max_bytes) is not int or not 1 <= max_bytes <= 2_000_000
                or type(max_hits) is not int or not 1 <= max_hits <= 1000):
            raise ValueError('invalid bounded search')
        policy = _bound_policy(root, binding, folder, approved_revision)
        root = binding.root
        context = policy.folder_ids[folder]
        preauthorize_index(policy, folder, index_path)
        reader = RepositoryReader(root, policy.policy_revision)
        if reader.invalid_paths:
            raise ValueError('repository metadata unavailable')
        try:
            chain = authorized_instruction_chain(policy, reader, folder, max_bytes=max_bytes)
        except ValueError as exc:
            if str(exc) == 'mandatory content exceeds byte budget':
                raise FolderSearchError('folder_search_budget_exceeded') from None
            raise
        authorized_index(policy, folder, index_path, chain)
        mandatory = list(dict.fromkeys([index_path, *[ref for row in chain for ref in row['declarations']['mandatory']]]))
        context_paths = list(dict.fromkeys([*[row['path'] for row in chain], *mandatory]))
        context_bytes = sum(reader.blob_size(path) for path in context_paths)
        if context_bytes > max_bytes:
            raise FolderSearchError('folder_search_budget_exceeded')
        for path in mandatory:
            item = reader.read(path)
            if not item['text'].strip() or contains_access_secrets(item['text']):
                raise ValueError('mandatory context unavailable')
        needle = query.casefold()
        hits = []
        truncated = False
        inspected = 0
        scanned_bytes = 0
        source_page_bytes = 0

        def scan(text, provenance):
            nonlocal truncated
            if contains_access_secrets(text):
                raise ValueError('secret detected in selected content')
            for number, line in enumerate(text.splitlines(), 1):
                if needle in line.casefold():
                    if len(hits) < max_hits:
                        hits.append({**provenance, 'line':number})
                    else:
                        truncated = True

        if scope is not None:
            scope = safe_path(scope, allow_root=True)
            if scope == '.':
                # ContextPolicy.permits accepts file paths, not the root token.
                # Require the equivalent root-wide grant; descendants are still
                # checked individually below, including inherited denials.
                limits = policy.effective[context]
                if folder != '.' or '.' not in limits['read'] or '.' in limits['deny']['read']:
                    raise ValueError('scope unavailable')
            elif not within(scope, folder) or policy.owner_of(scope) != context or not policy.permits(context, 'read', scope):
                raise ValueError('scope unavailable')
            if scope != '.':
                from wiki_core.context_policy import _git
                if _git(root, 'cat-file', '-t', f'{policy.policy_revision}:{scope}').strip() != b'tree':
                    raise ValueError('scope unavailable')
            selected = []
            for path in reader.unsupported_paths:
                if not within(path, scope):
                    continue
                try:
                    if policy.owner_of(path) == context and policy.permits(context, 'read', path):
                        raise FolderSearchError('folder_search_unsupported_content')
                except FolderSearchError:
                    raise
                except ValueError:
                    continue
            for path in reader.paths:
                if not within(path, scope) or not path.endswith('.md'):
                    continue
                parts = PurePosixPath(path).parts
                if (parts[-1] in ('AGENTS.md', 'AGENTS.override.md', 'CLAUDE.md', 'CLAUDE.local.md', 'SKILL.md')
                        or any(part in ('.skills', 'skills', '.codex', '.claude') for part in parts)):
                    continue
                try:
                    if policy.owner_of(path) == context and policy.permits(context, 'read', path):
                        selected.append(path)
                except ValueError:
                    continue
            if len(selected) > max_files or context_bytes + sum(reader.blob_size(path) for path in selected) > max_bytes:
                raise FolderSearchError('folder_search_budget_exceeded')
            for path in selected:
                item = reader.read(path)
                scan(item['text'], {'path':path, 'revision':reader.revision, 'sha256':item['content_sha256']})
                inspected += 1
                scanned_bytes += reader.blob_size(path)
            coverage = 'authorized_tracked_markdown_in_selected_owner_only'
            selection = {'kind':'scope', 'scope':scope}
            limitations = ['Nested owners, denied paths, instructions, untracked files and independent repositories are excluded.',
                           'No global absence, actual read or external freshness is established.']
        elif raw_capture is not None:
            from wiki_core.folder_ingestion_v2 import _check_local_boundaries
            from wiki_core.folder_policy_v2 import _at_revision
            from wiki_core.folder_source_provenance_v2 import _capture_valid
            from wiki_core.context_selection import _metadata
            from wiki_core.source_manifest import source_origin
            if not isinstance(raw_capture, dict) or contains_access_secrets(raw_capture):
                raise ValueError('invalid raw selection')
            _capture_valid(raw_capture)
            ref = safe_path(raw_capture['ref']); canonical = safe_path(raw_capture['canonical_ref'])
            old = raw_capture['canonical_revision']
            if not isinstance(old, str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', old):
                raise ValueError('invalid historical revision')
            from wiki_core.context_policy import _git
            _git(root, 'merge-base', '--is-ancestor', old, policy.policy_revision)
            historical = _at_revision(root, old, policy.controls_path)
            if historical.folder_ids.get(folder) != context:
                raise ValueError('historical context unavailable')
            for selected in (ref, canonical):
                producer = policy.owner_of(selected)
                if (policy.connection(producer, context, selected, 'interpretation', 'source') != 'approved'
                        or historical.owner_of(selected) != producer
                        or historical.connection(producer, context, selected, 'interpretation', 'source') != 'approved'):
                    raise ValueError('source authority unavailable')
            historical_reader = RepositoryReader(root, old)
            if canonical not in historical_reader.paths:
                raise ValueError('canonical source unavailable')
            canonical_bytes = historical_reader.blob_size(canonical)
            source_page_bytes = canonical_bytes
            if context_bytes + canonical_bytes > max_bytes:
                raise FolderSearchError('folder_search_budget_exceeded')
            source_doc = historical_reader.read(canonical)
            source_meta = _metadata(source_doc)
            if (contains_access_secrets(source_doc['text']) or source_doc['content_sha256'] != raw_capture['canonical_sha256']
                    or source_meta.get('page_type') != 'source'
                    or not isinstance(source_meta.get('platform'), str) or not source_meta['platform'].strip()
                    or not isinstance(source_meta.get('source_locator'), str) or not source_meta['source_locator'].strip()):
                raise ValueError('canonical source unavailable')
            _check_local_boundaries(root, ref)
            path = root / ref
            raw_budget = max_bytes - context_bytes - canonical_bytes
            if raw_budget < 1:
                raise FolderSearchError('folder_search_budget_exceeded')
            if not path.is_file() or source_origin(str(path), root) != raw_capture['source_origin']:
                raise ValueError('raw selection unavailable or over budget')
            if path.stat().st_size > raw_budget:
                raise FolderSearchError('folder_search_budget_exceeded')
            with path.open('rb') as stream:
                data = stream.read(raw_budget + 1)
            if len(data) > raw_budget:
                raise FolderSearchError('folder_search_budget_exceeded')
            if hashlib.sha256(data).hexdigest() != raw_capture['source_sha256']:
                raise ValueError('raw source changed')
            text = data.decode('utf-8')
            scan(text, {'path':ref, 'source_ref':canonical, 'source_revision':old,
                        'source_sha256':raw_capture['canonical_sha256'], 'sha256':raw_capture['source_sha256']})
            inspected = 1; scanned_bytes = len(data)
            coverage = 'explicit_selected_raw_utf8_file_only'
            selection = {'kind':'raw', 'path':ref, 'source_ref':canonical,
                         'source_revision':old, 'source_sha256':raw_capture['canonical_sha256'],
                         'sha256':raw_capture['source_sha256']}
            limitations = ['Source-page association is caller selected and unverified.',
                           'External origin and freshness are not verified.']
        else:
            from wiki_core.folder_reassessment_v2 import _repository_node_matches
            from wiki_core.repo_read import read_independent_repo
            if not isinstance(repository, dict) or set(repository) != {'source_ref', 'root', 'identity', 'revision', 'path'}:
                raise ValueError('invalid repository selection')
            source = safe_path(repository['source_ref']); repo_path = safe_path(repository['path'])
            repo_root = Path(repository['root'])
            repo_revision = repository['revision']; identity = repository['identity']
            if not repo_root.is_absolute():
                raise ValueError('repository not bound')
            repo_root = repo_root.resolve()
            if (not isinstance(repo_revision, str)
                    or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', repo_revision)
                    or (folder, repo_root, identity, repo_path) not in binding.independent_repos):
                raise ValueError('repository not bound')
            producer = policy.owner_of(source)
            if (source not in reader.paths or policy.connection(producer, context, source,
                    'interpretation', 'source') != 'approved'):
                raise ValueError('repository source unavailable')
            source_bytes = reader.blob_size(source)
            source_page_bytes = source_bytes
            repo_budget = max_bytes - context_bytes - source_bytes
            if repo_budget < 1:
                raise FolderSearchError('folder_search_budget_exceeded')
            source_doc = reader.read(source)
            if (contains_access_secrets(source_doc['text'])
                    or not _repository_node_matches(source_doc['text'], identity)):
                raise ValueError('repository source identity unavailable')
            try:
                item = read_independent_repo(repo_root, identity, repo_revision, repo_path, max_bytes=repo_budget)
            except ValueError as exc:
                if str(exc) == 'repository_file_too_large':
                    raise FolderSearchError('folder_search_budget_exceeded') from None
                raise
            scan(item['text'], {'source_ref':source, 'source_revision':reader.revision,
                                'source_sha256':source_doc['content_sha256'], 'repository':identity,
                                'path':repo_path, 'revision':item['revision'], 'sha256':item['content_sha256']})
            inspected = 1; scanned_bytes = len(item['text'].encode('utf-8'))
            coverage = 'explicit_selected_repository_git_blob_only'
            selection = {'kind':'repository', 'source_ref':source, 'source_revision':reader.revision,
                         'source_sha256':source_doc['content_sha256'], 'repository':identity,
                         'path':repo_path, 'revision':item['revision'], 'sha256':item['content_sha256']}
            limitations = ['Configured origin identifies the local repository but does not authenticate a remote.',
                           'External freshness and unselected paths are not assessed.']
        policy.fresh()
        return {'schema_version':'wiki.folder-literal-search/v2', 'folder':folder,
                'policy_revision':policy.policy_revision, 'query':query,
                'index_path':index_path, 'selection':selection,
                'status':'matches' if hits else 'no_matches_in_selection', 'coverage':coverage,
                'inspected_count':inspected, 'scanned_bytes':scanned_bytes, 'context_bytes':context_bytes,
                'source_page_bytes':source_page_bytes, 'hits':hits,
                'truncated':truncated, 'limitations':limitations,
                'freshness':'not_assessed', 'read_verification':'not_performed', 'enforcement_claim':'none'}
    except FolderSearchError:
        raise
    except (ValueError, OSError, TypeError, KeyError, AttributeError, RuntimeError, RecursionError):
        raise FolderSearchError() from None
