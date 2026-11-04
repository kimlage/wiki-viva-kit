"""Direct local retrieval: existing FTS plus explicitly observed provenance."""
from __future__ import annotations

import json
import hashlib
from collections import defaultdict
from pathlib import Path

from wiki_core.frontmatter import parse_frontmatter
from wiki_core.detectors.secrets import scan_secrets
from wiki_core.index.sqlite import PAGE_SOURCE_PREFIX, search_detailed
from wiki_core.index.page_collection import current_page_signature
from wiki_core.paths import WikiPaths
from wiki_core.traversal import is_in_nested_git, wiki_files, wiki_markdown_files


def _find_selected(root: Path, query: str, selections, limit: int) -> dict:
    """Search explicitly selected working-tree text, without opening the index."""
    if (not isinstance(query, str) or not query.split() or len(query) > 4096
            or type(limit) is not int or not 1 <= limit <= 1000
            or not isinstance(selections, (list, tuple)) or not 1 <= len(selections) <= 16
            or any(not isinstance(item, str) or len(item) > 4096 for item in selections)):
        raise ValueError('invalid selected search')
    if scan_secrets(query) or any(scan_secrets(item) for item in selections):
        raise ValueError('selected search unavailable')
    root = Path(root).resolve()
    files = set()
    for value in selections:
        if (not isinstance(value, str) or not value
                or any(part in ('..', '.git') for part in Path(value).parts)):
            raise ValueError('invalid selected path')
        path = Path(value)
        path = path if path.is_absolute() else root / path
        try:
            path.relative_to(root)
        except ValueError:
            raise ValueError('selected path outside wiki') from None
        if is_in_nested_git(path, wiki_root=root):
            raise ValueError('selected path crosses repository boundary')
        if path.is_dir():
            if is_in_nested_git(path / '_wiki_selection_', wiki_root=root):
                raise ValueError('selected path crosses repository boundary')
            files.update(item for item in wiki_files(path, wiki_root=root, max_entries=10000)
                         if item.suffix.lower() in ('.md', '.markdown', '.txt'))
        elif path.is_file() and path.suffix.lower() in ('.md', '.markdown', '.txt'):
            files.add(path)
        else:
            raise ValueError('selected path unavailable or unsupported')
    if len(files) > 1000:
        raise ValueError('selected search file limit exceeded')
    # Validate the complete selection and its size before opening any body.
    sizes = []
    for path in sorted(files):
        if scan_secrets(path.relative_to(root).as_posix()):
            raise ValueError('selected search unavailable')
        if is_in_nested_git(path, wiki_root=root) or not path.is_file():
            raise ValueError('selected file unavailable')
        size = path.stat().st_size
        if size > 1_000_000:
            raise ValueError('selected search file too large')
        sizes.append((path, size))
    if sum(size for _, size in sizes) > 8_000_000:
        raise ValueError('selected search byte limit exceeded')
    terms = [term.casefold() for term in query.split()]
    hits = []
    read_bytes = 0
    files_read = 0
    for path, _ in sizes:
        if len(hits) == limit:
            break
        if is_in_nested_git(path, wiki_root=root):
            raise ValueError('selected file unavailable')
        with path.open('rb') as stream:
            raw = stream.read(1_000_001)
        files_read += 1
        if len(raw) > 1_000_000:
            raise ValueError('selected search file too large')
        read_bytes += len(raw)
        if read_bytes > 8_000_000:
            raise ValueError('selected search byte limit exceeded')
        text = raw.decode('utf-8')
        if scan_secrets(text):
            raise ValueError('selected search content unavailable')
        folded = text.casefold()
        if all(term in folded for term in terms) and len(hits) < limit:
            pos = folded.find(terms[0])
            # Case folding can expand characters; map its offset back to text.
            offset = 0
            for i, char in enumerate(text):
                if offset >= pos:
                    break
                offset += len(char.casefold())
            else:
                i = len(text)
            hits.append({'path': path.relative_to(root).as_posix(), 'text': text[max(0, i - 120):i + 280],
                         'content_sha256': hashlib.sha256(raw).hexdigest(), 'origin': 'working_tree'})
    return {'schema_version': 'wiki_find.v1', 'status': 'ok' if hits else 'no_matches', 'query': query,
            'hits': hits, 'scope': {'selection': list(selections), 'matching': 'casefold_substring_and'},
            'coverage': {'context_scope': 'explicit_selection_partial', 'index': 'not_used',
                         'files_selected': len(sizes), 'files_read': files_read,
                         'files_not_read': len(sizes) - files_read,
                         'repository_boundaries': 'excluded'},
            'freshness': 'not_evaluated', 'read_only': True}


def _local_catalog(root: Path, config) -> tuple[dict, list]:
    """Read existing metadata only; do not ingest, re-chunk or rebuild."""
    root = root.resolve()
    paths = WikiPaths(root, config)
    entries = defaultdict(list)
    issues = []
    files = []
    for directory, kind, pattern in [(paths.source_manifests, "manifest", "*.json"),
                                      (paths.memory_root, "page", "**/*.md")]:
        if not directory.resolve().is_relative_to(root):
            issues.append(dict(kind=kind, reason="metadata_path_outside_local_catalog"))
            continue
        if kind == "manifest" and is_in_nested_git(directory / '_catalog_selection_', wiki_root=root):
            issues.append(dict(kind=kind, reason="metadata_path_crosses_repository_boundary"))
            continue
        candidates = wiki_markdown_files(directory, wiki_root=root) if kind == "page" else sorted(directory.glob(pattern))
        files.extend((p, kind) for p in candidates)
    for path, kind in files:
        ref = path.relative_to(root).as_posix()
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            issues.append(dict(path=ref, reason="metadata_path_outside_local_catalog"))
            continue
        try:
            if kind == "manifest":
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or data.get("schema_version") != "wiki_source_manifest.v1":
                    raise ValueError("manifest schema")
                identity = data.get("source_id")
                item = dict(kind="source", metadata_path=ref, locator=data.get("source_uri"),
                            source_hash_sha256=data.get("hash_sha256"), captured_at=data.get("captured_at"))
            else:
                data, _body = parse_frontmatter(path)
                page_id = data.get("page_id")
                if not page_id:
                    continue
                if not isinstance(page_id, str):
                    raise ValueError("page identity")
                identity = PAGE_SOURCE_PREFIX + page_id
                item = dict(kind="page", page_id=page_id, path=ref, locator=ref)
            if not isinstance(identity, str) or not identity.strip():
                raise ValueError("catalog identity")
            context = data.get("context")
            item.update(context=context if isinstance(context, str) and context.strip() else None,
                        metadata_observation="local_at_query_time", indexed_revision="unknown")
            entries[identity].append(item)
        except (OSError, UnicodeError, ValueError):
            issues.append(dict(path=ref, reason="metadata_unreadable_or_invalid"))
    return dict(entries), issues


def find(root: Path, config, query: str, *, context: str | None = None,
         source_id: str | None = None, limit: int = 20, selections=None) -> dict:
    """Return lexical matches and gaps, never a conclusion of global absence."""
    if selections is not None:
        if context is not None or source_id is not None:
            raise ValueError('selected search cannot combine indexed filters')
        try:
            return _find_selected(root, query, selections, limit)
        except (OSError, UnicodeError):
            raise ValueError('selected search unavailable') from None
    catalog, issues = _local_catalog(root, config)
    resolved = {sid: rows[0] for sid, rows in catalog.items() if len(rows) == 1}
    allowed = None
    if context is not None:
        allowed = {sid for sid, item in resolved.items() if item["context"] == context}
    if source_id is not None:
        allowed = {source_id} if allowed is None else allowed & {source_id}
    paths = WikiPaths(root, config)
    source_only = source_id is not None and not source_id.startswith(PAGE_SOURCE_PREFIX)
    signature = None
    if not source_only:
        try:
            signature = current_page_signature(paths)
        except (OSError, UnicodeError, ValueError):
            signature = "unavailable"
            issues.append(dict(kind="page", reason="page_index_current_state_unavailable"))
    result = search_detailed(paths.indexes / "wiki.sqlite", query,
                             limit=limit, source_ids=allowed, page_signature=signature,
                             source_only=source_only, wiki_root=root)
    indexed_ids = result.pop("indexed_source_ids")
    gaps = []
    for sid in indexed_ids:
        if source_id is not None and sid != source_id:
            continue
        reason = ("metadata_missing" if sid not in catalog else
                  "metadata_ambiguous" if sid not in resolved else
                  "context_missing" if resolved[sid]["context"] is None else None)
        if reason:
            gaps.append(dict(source_id=sid, reason=reason))
    for hit in result["hits"]:
        item = resolved.get(hit["source_id"])
        hit["provenance"] = item if item else dict(
            status="ambiguous" if hit["source_id"] in catalog else "missing",
            indexed_revision="unknown")
    result.update(schema_version="wiki_find.v1",
        scope=dict(context=context, source_id=source_id, filtered_before_limit=True,
                   metadata_gaps=gaps, catalog_issues=issues),
        coverage=dict(index_revision="unknown", source_completeness="unknown",
                      page_index="not_checked_source_only" if source_only else "checked",
                      context_scope="partial" if context is not None and (gaps or issues) else
                                    "resolved_metadata_only" if context is not None else "unfiltered"),
        freshness="not_evaluated", read_only=True)
    return result
