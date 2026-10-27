"""Direct local retrieval: existing FTS plus explicitly observed provenance."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from wiki_core.frontmatter import parse_frontmatter
from wiki_core.index.sqlite import PAGE_SOURCE_PREFIX, search_detailed
from wiki_core.paths import WikiPaths


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
        files.extend((p, kind) for p in sorted(directory.glob(pattern)))
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
         source_id: str | None = None, limit: int = 20) -> dict:
    """Return lexical matches and gaps, never a conclusion of global absence."""
    catalog, issues = _local_catalog(root, config)
    resolved = {sid: rows[0] for sid, rows in catalog.items() if len(rows) == 1}
    allowed = None
    if context is not None:
        allowed = {sid for sid, item in resolved.items() if item["context"] == context}
    if source_id is not None:
        allowed = {source_id} if allowed is None else allowed & {source_id}
    result = search_detailed(WikiPaths(root, config).indexes / "wiki.sqlite", query,
                             limit=limit, source_ids=allowed)
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
                      context_scope="partial" if context is not None and (gaps or issues) else
                                    "resolved_metadata_only" if context is not None else "unfiltered"),
        freshness="not_evaluated", read_only=True)
    return result
