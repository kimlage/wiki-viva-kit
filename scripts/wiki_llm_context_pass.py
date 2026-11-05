#!/usr/bin/env python3
"""Contextual LLM pass delegated to the agent running the repo.

This script does NOT call any model. It:
  - gathers/selects chunks (by source or by sanitized FTS search);
  - assembles a context PACKAGE (request) with prompt + schema + chunk text;
  - records the RESULT the agent (Claude/Codex/Gemini) produced, in the cache;
  - acts as a gate (`--check`): fails while there is a pending chunk and
    `required_context_pass` is enabled.

Approved-context examples (use the same authorized source, approval, context and limits):
  python3 scripts/wiki_llm_context_pass.py --source SOURCE --context SOURCE_CONTEXT \\
    --approved-revision APPROVED_SHA --policy-context CONTEXT_ID --emit-request
  python3 scripts/wiki_llm_context_pass.py --source SOURCE --context SOURCE_CONTEXT \\
    --approved-revision APPROVED_SHA --policy-context CONTEXT_ID --record-result result.json
  python3 scripts/wiki_llm_context_pass.py --source SOURCE --context SOURCE_CONTEXT \\
    --approved-revision APPROVED_SHA --policy-context CONTEXT_ID --check

Working-tree compatibility example (not evidence of approved policy or freshness):
  python3 scripts/wiki_llm_context_pass.py --query "pending decisions" --context system

Approved mode requires an explicit source and refuses query mode, unrequested-result
bypass and invalid or missing authority; it never falls back to compatibility.
See docs/references/guides/bounded-ingestion.md.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

CODE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_ROOT))
from scripts._common import ROOT

from wiki_core.config import DEFAULT_CONTEXT_DEEP_READ_PROMPT_VERSION, load_config
from wiki_core.ids import sha256_text
from wiki_core.index.sqlite import search
from wiki_core.index.page_collection import current_page_signature
from wiki_core.input_stage import input_context_for_source
from wiki_core.llm import CONTEXT_PASS_SCHEMA_VERSION, build_context_request, write_result
from wiki_core.llm.context_pass import (result_matches_request, ingestion_block_context,
    DEFAULT_CONTEXT_MAX_BYTES, DEFAULT_REQUEST_MAX_BYTES, ContextRequestBlocked,
    canonical_request_text, enforce_request_budget, preparation_blocker, request_limits)
from wiki_core.paths import WikiPaths
from wiki_core.source_config import find_source_config, merge_perspectives
from wiki_core.source_manifest import build_manifest, resolve_source_manifest


def _source_artifact(path: Path, schema: str, source_id: str) -> dict[str, object]:
    """Read an explicitly requested source, never turn missing input into success."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"source_artifact_missing: {path.parent.name}/{path.name}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"source_artifact_invalid_json: {path.parent.name}/{path.name}") from exc
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"source_artifact_unreadable: {path.parent.name}/{path.name}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != schema:
        raise ValueError(f"source_artifact_schema: {path.parent.name}/{path.name}")
    if data.get("source_id") != source_id:
        raise ValueError(f"source_artifact_identity: {path.parent.name}/{path.name}")
    return data


def _chunks_for_source(paths: WikiPaths, manifest: dict[str, object]) -> list[dict[str, object]]:
    source_id = str(manifest["source_id"])
    if getattr(paths, 'root', None) is not None:
        from wiki_core.traversal import require_wiki_boundaries
        require_wiki_boundaries(paths.root, files=(paths.chunks / f'{source_id}.json',
                                                  paths.source_text / f'{source_id}.json'))
    if manifest.get("exists") is False:
        raise ValueError("source_not_found: extract the requested source before checking it")
    data = _source_artifact(paths.chunks / f"{source_id}.json", "wiki_chunks.v1", source_id)
    if "source_hash_sha256" not in data or data["source_hash_sha256"] != manifest.get("hash_sha256"):
        raise ValueError("source_artifact_hash: chunks do not match the requested source")
    chunks = data.get("chunks")
    if not isinstance(chunks, list):
        raise ValueError("source_chunks_schema: an explicit chunks array is required")
    ids: set[str] = set()
    for chunk in chunks:
        if not isinstance(chunk, dict) or not isinstance(chunk.get("text"), str) or not chunk["text"].strip():
            raise ValueError("source_chunk_schema: each chunk requires nonempty text")
        chunk_id = chunk.get("chunk_id")
        if (not isinstance(chunk_id, str) or not chunk_id.startswith(f"{source_id}-chunk-")
                or chunk_id in ids or chunk.get("source_id", source_id) != source_id):
            raise ValueError("source_chunk_identity: chunk ids must be unique and belong to this source")
        if chunk.get("hash_sha256") != sha256_text(chunk["text"]):
            raise ValueError("source_chunk_hash: chunk text does not match its digest")
        ids.add(chunk_id)
    if chunks:
        return chunks

    # The ingestion pipeline legitimately writes chunks=[] and no LLM request
    # for empty input. Extraction failures also produce zero chunks, so require
    # the retained extraction observation before accepting this empty result.
    extracted = _source_artifact(paths.source_text / f"{source_id}.json", "wiki_extracted_text.v1", source_id)
    warnings = extracted.get("warnings")
    units = extracted.get("units")
    characters = extracted.get("text_characters")
    if (not isinstance(warnings, list) or any(not isinstance(w, str) for w in warnings)
            or not isinstance(units, list) or type(characters) is not int or characters < 0
            or any(not isinstance(u, dict) or not isinstance(u.get("text"), str) for u in units)):
        raise ValueError("source_extraction_schema: empty chunks require a complete extraction observation")
    if warnings:
        # Do not echo arbitrary extractor messages: they can include source text.
        raise ValueError("source_extraction_warning: review extraction warnings before accepting empty chunks")
    if any(u["text"].strip() for u in units):
        raise ValueError("source_extraction_not_empty: zero chunks conflict with extracted text")
    # For empty/whitespace-only input the current producers retain one text
    # unit or join units with newlines (CSV, workbook and document). Email also
    # matches this join when headers are empty; substantive headers were rejected
    # above. Count the separators, not just the units, and reject unexplained text.
    if characters != len("\n".join(u["text"] for u in units)):
        raise ValueError("source_extraction_count_mismatch: character count does not match empty units")
    return chunks


def _chunks_for_query(paths: WikiPaths, query: str) -> tuple[dict[str, object], list[dict[str, object]]]:
    db_path = paths.indexes / "wiki.sqlite"
    hits = search(db_path, query, limit=20, page_signature=current_page_signature(paths), wiki_root=paths.root)
    chunks = [
        {
            "chunk_id": hit["chunk_id"],
            "source_id": hit["source_id"],
            "context": hit.get("metadata", {}).get("context"),
            "source_origin": ({"id": hit["metadata"]["source_origin_id"]}
                              if hit.get("metadata", {}).get("source_origin_id") else None),
            "hash_sha256": sha256_text(str(hit["text"])),
            "text": hit["text"],
            "token_estimate": max(1, len(str(hit["text"]).split())),
        }
        for hit in hits
    ]
    manifest = {
        "source_id": f"query-{sha256_text(query)[:12]}",
        "hash_sha256": sha256_text(query),
    }
    return manifest, chunks


def _emitted_requests(paths: WikiPaths, *, sizes: dict | None = None, source_id: str | None = None,
                      local_request: dict | None = None) -> list[dict]:
    """Read emitted semantic packets for exact result provenance validation."""
    requests: list[dict] = []
    if getattr(paths, 'root', None) is not None:
        from wiki_core.traversal import require_wiki_boundaries
        require_wiki_boundaries(paths.root, directories=(paths.extraction_events,))
    if not paths.extraction_events.exists():
        return requests
    if local_request is not None:
        from wiki_core.llm.context_pass import local_request_path, load_local_request
        path = local_request_path(paths, local_request)
        data = load_local_request(paths, path)
        if sizes is not None:
            sizes[id(data)] = path.stat().st_size
        return [data]
    if source_id is not None:
        if not isinstance(source_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,511}", source_id):
            return requests
        exact = paths.extraction_events / f"{source_id}-llm-context-request.json"
        candidates = [exact] if not exact.is_symlink() and exact.is_file() else []
    else:  # Explicit trusted compatibility inspection retains its old scan.
        candidates = paths.extraction_events.glob("*-llm-context-request.json")
    candidates = list(candidates)
    if getattr(paths, 'root', None) is not None:
        require_wiki_boundaries(paths.root, files=candidates)
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # Not silent: a corrupt request shrinks the set of known cache_keys,
            # which can reject a legitimate result. The auditor errors on it too.
            print(
                f"WARN: unreadable LLM context request (invalid JSON), ignored "
                f"for provenance: {path.name}",
                file=sys.stderr,
            )
            continue
        if isinstance(data, dict) and isinstance(data.get("chunks"), list):
            requests.append(data)
            if sizes is not None:
                sizes[id(data)] = path.stat().st_size
    return requests


def _emitted_cache_keys(paths: WikiPaths) -> set[str]:
    return {str(row["cache_key"]) for request in _emitted_requests(paths)
            for row in request["chunks"] if isinstance(row, dict) and row.get("cache_key")}


def _retained_local_request(paths: WikiPaths, source_id: str, max_bytes: int, request_path: str) -> dict:
    """Read one explicit request before reopening selected Git bodies."""
    from wiki_core.llm.context_pass import load_local_request
    if not isinstance(source_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,511}', source_id):
        raise ValueError('retained local request unavailable')
    try:
        request = load_local_request(paths, Path(request_path), max_bytes=max_bytes)
    except (OSError, ValueError, UnicodeError, OverflowError, RecursionError):
        raise ValueError('retained local request unavailable') from None
    if request.get('source_id') != source_id:
        raise ValueError('retained local request unavailable')
    return request


def _record_results(paths: WikiPaths, payload_path: str, *, allow_unrequested: bool = False,
                    current_request: dict | None = None, limits: dict | None = None, owner: str = "Context owner/integrator", before_write=None,
                    preserve_existing: bool = False) -> int:
    from wiki_core.traversal import is_protected_artifact
    if payload_path != '-' and is_protected_artifact(Path(payload_path)):
        return _blocked(ContextRequestBlocked('protected_result_unavailable',
            'Protected artifacts require bound dispatch.'), 'requested-input', owner)
    if preserve_existing:
        try:
            from wiki_core.context_selection import strict_json_loads
            if payload_path == '-':
                raw = sys.stdin.read(2_000_001)
                if len(raw.encode('utf-8')) > 2_000_000:
                    raise ValueError('result input unavailable')
            else:
                with Path(payload_path).open('rb') as stream:
                    content = stream.read(2_000_001)
                if len(content) > 2_000_000:
                    raise ValueError('result input unavailable')
                raw = content.decode('utf-8')
            data = strict_json_loads(raw)
        except (ValueError, OSError, UnicodeError, RecursionError):
            return _blocked(ContextRequestBlocked('local_result_unavailable',
                'Selected result input is unavailable or invalid.'), 'requested-input', owner)
    else:
        raw = sys.stdin.read() if payload_path == "-" else Path(payload_path).read_text(encoding="utf-8")
        data = json.loads(raw)
    results = data if isinstance(data, list) else [data]
    retained_sizes = {}
    from wiki_core.llm.context_pass import is_local_folder_request, result_cache_for_request
    local_request = is_local_folder_request(current_request)
    if local_request and (allow_unrequested or not preserve_existing or not callable(before_write)):
        return _blocked(ContextRequestBlocked('local_context_revalidation_required',
            'Record with the selected local source and folder so current inputs can be revalidated.'),
            'requested-input', owner)
    target_cache = result_cache_for_request(paths.llm_cache, current_request) if local_request else paths.llm_cache
    approved_current = current_request is not None and current_request.get("block_context_package", {}).get("schema_version") == "wiki.task-context/v1"
    source_id = str(current_request.get("source_id") or "") if (approved_current or preserve_existing) else None
    if local_request and source_id:
        try:
            from wiki_core.traversal import require_wiki_path
            from wiki_core.llm.context_pass import local_request_path
            request_file = local_request_path(paths, current_request)
            require_wiki_path(paths.root, request_file.relative_to(paths.root).as_posix())
        except (ValueError, OSError) as exc:
            return _blocked(exc, 'requested-input', owner)
    try:
        if getattr(paths, 'root', None) is not None:
            from wiki_core.traversal import require_wiki_boundaries
            keys = [row.get('cache_key') for row in results if isinstance(row, dict)]
            require_wiki_boundaries(paths.root, directories=(target_cache,), files=(
                target_cache / f'{key}.json' for key in keys
                if isinstance(key, str) and re.fullmatch(r'[0-9a-f]{64}', key)))
        if allow_unrequested:
            requests = []
        elif local_request:
            requests = _emitted_requests(paths, sizes=retained_sizes, source_id=source_id, local_request=current_request)
        else:
            requests = _emitted_requests(paths, sizes=retained_sizes, source_id=source_id)
    except (ValueError, OSError):
        print('ERROR: derived path crosses a repository boundary; result not recorded.', file=sys.stderr)
        return 2
    limits = limits or request_limits()
    known = {str(row.get("cache_key")) for request in requests for row in request["chunks"] if isinstance(row, dict)}
    written = []
    completed = False
    try:
        for result in results:
            key = result.get("cache_key") if isinstance(result, dict) else None
            if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key):
                print("ERROR: invalid cache_key shape; expected a lowercase SHA-256 digest.", file=sys.stderr)
                return 2
            if not allow_unrequested and key not in known:
                # No silent escape: ZERO requests on disk also rejects (the old
                # `and known` guard let any result through when extraction-events
                # was empty, making the provenance gate forgeable by deletion).
                detail = (
                    "no emitted context request found on disk"
                    if not known
                    else "no emitted context request contains this cache_key"
                )
                print(
                    "ERROR: result without a corresponding emitted context request "
                    f"({detail}); result rejected (provenance). Emit the request before "
                    "recording, or use --allow-unrequested for legitimate cases with no "
                    "request on disk.",
                    file=sys.stderr,
                )
                return 2
            matching = [request for request in requests if any(row.get("cache_key") == key
                        for row in request["chunks"] if isinstance(row, dict))]
            for request in matching:
                if is_local_folder_request(request) and (not local_request or not preserve_existing or not callable(before_write)):
                    return _blocked(ContextRequestBlocked('local_context_revalidation_required',
                        'Record with the selected local source and folder so current inputs can be revalidated.'),
                        'requested-input', owner)
                retained_limits = request.get("request_limits")
                if retained_limits is not None and retained_limits != limits:
                    return _blocked(ContextRequestBlocked("request_limits_changed", "Re-emit the request under the current explicit byte budgets before recording."),
                                    str(request.get("source_id") or "source-context-pass"), owner)
                context_bytes = len(canonical_request_text(request.get("block_context_package") or {}).encode()) - 1
                if retained_sizes[id(request)] > limits["request_max_bytes"] or context_bytes > limits["context_max_bytes"]:
                    return _blocked(ContextRequestBlocked("retained_request_exceeds_budget", "The retained request exceeds the current byte budget; choose a smaller stage and re-emit before recording."),
                                    str(request.get("source_id") or "source-context-pass"), owner)
                if request.get("block_context_package", {}).get("schema_version") == "wiki.task-context/v1":
                    if current_request is None or current_request.get("block_context_package", {}).get("schema_version") != "wiki.task-context/v1":
                        return _blocked(ContextRequestBlocked("approved_context_revalidation_required", "Record approved results with the explicit source, approved revision and policy context so current authority can be revalidated."),
                                        str(request.get("source_id") or "source-context-pass"), owner)
            if current_request is not None and not any(result_matches_request(result, current_request, row, recording=True)
                    for row in current_request["chunks"] if row.get("cache_key") == key):
                return _blocked(ContextRequestBlocked("current_request_changed", "The current context, source or limits changed; emit and read the current request before recording."),
                                str(current_request.get("source_id") or "source-context-pass"), owner)
            if not allow_unrequested and not any(
                    result_matches_request(result, request, row, recording=True)
                    for request in requests for row in request["chunks"]
                    if isinstance(row, dict) and row.get("cache_key") == key):
                print("ERROR: result does not match the emitted context, source, chunk or schema", file=sys.stderr)
                return 2
            if before_write is not None and not local_request:
                try:
                    before_write()
                except (ValueError, OSError) as exc:
                    if preserve_existing and written:
                        return _blocked(ContextRequestBlocked('local_persistence_partial',
                            f'Local recording stopped after {len(written)} completed result(s); '
                            'inspect them before retrying.'),
                            str(current_request.get('source_id') or 'requested-input'), owner)
                    return _blocked(exc, str(current_request.get('source_id') or 'requested-input'), owner)
            try:
                if preserve_existing:
                    from wiki_core.traversal import require_wiki_path
                    require_wiki_path(paths.root, (target_cache / f'{key}.json').relative_to(paths.root).as_posix())
                out = (write_result(paths.llm_cache, result, preserve_existing=True,
                                    request=current_request, before_write=before_write)
                       if preserve_existing else write_result(paths.llm_cache, result))
            except (ValueError, OSError) as exc:
                if preserve_existing:
                    return _blocked(ContextRequestBlocked('local_persistence_partial',
                        f'Local result persistence stopped after {len(written)} completed result(s); '
                        'additional partial effects may exist and must be inspected before retrying.'),
                        str(current_request.get('source_id') or 'requested-input'), owner)
                if before_write is not None:
                    return _blocked(exc, str(current_request.get("source_id") or "requested-input"), owner)
                print("ERROR: invalid result or unavailable cache output; verify the declared schema and current bound request.", file=sys.stderr)
                return 2
            written.append(str(out.relative_to(getattr(paths, "root", ROOT))))
        completed = True
    finally:
        if preserve_existing and written and not completed:
            print(f"Local recording stopped after {len(written)} completed result(s); "
                  "inspect them before retrying.", file=sys.stderr)
    print(json.dumps({"recorded": written, "count": len(written)}, ensure_ascii=False, indent=2))
    return 0


def _blocked(exc, source_id, owner):
    report = preparation_blocker(exc, source_id, owner)
    print(json.dumps({"ok": False, "blocked": True, "source_id": source_id,
        "error_code": report["error_code"], "blockers": [report["blocker"]]}, ensure_ascii=False, sort_keys=True))
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--source")
    parser.add_argument("--query")
    parser.add_argument("--context", required=True)
    parser.add_argument("--profile")
    parser.add_argument("--approved-revision", help="Retired v1 option; use the folder source-stage.")
    parser.add_argument("--policy-context", help="Retired v1 option; use the folder source-stage.")
    parser.add_argument("--folder", help="Local context folder relative to the wiki root; defaults to nested cwd.")
    parser.add_argument("--index", help="Selected context index relative to the wiki root; required for the root.")
    parser.add_argument("--repo", nargs=4, action="append", metavar=("ROOT", "IDENTITY", "REVISION", "PATH"),
                        help="Explicit independent Git file; repeat the selection when recording.")
    parser.add_argument("--context-max-bytes", type=int, default=DEFAULT_CONTEXT_MAX_BYTES)
    parser.add_argument("--request-max-bytes", type=int, default=DEFAULT_REQUEST_MAX_BYTES)
    business_root = parser.add_mutually_exclusive_group()
    business_root.add_argument("--root-entity-ref", help="Explicit authorized business-root page; this does not grant access.")
    business_root.add_argument("--omit-root-entity", action="store_true", help="Explicitly omit the business root with missing coverage; mandatory lineage rules still apply.")
    parser.add_argument(
        "--required-perspective",
        action="append",
        default=[],
        help="required perspective page_id for this deep-read request",
    )
    parser.add_argument(
        "--optional-perspective",
        action="append",
        default=[],
        help="optional perspective page_id for this deep-read request",
    )
    parser.add_argument("--emit-request", action="store_true", help="writes the package to extraction-events/")
    parser.add_argument("--record-result", help="path to JSON (object or array) or '-' for stdin")
    parser.add_argument("--request", help="exact retained folder request; required to record a Git-bound result")
    parser.add_argument(
        "--allow-unrequested",
        action="store_true",
        help="records the result even without a corresponding emitted request (skips the provenance check)",
    )
    parser.add_argument("--check", action="store_true", help="exit !=0 if there is a pending pass and required_context_pass")
    args = parser.parse_args()
    if args.approved_revision is not None or args.policy_context is not None:
        parser.error('new approved v1 ingestion is retired; use wiki_coordination.py --source-stage with a trusted host binding')
    if args.request is not None and (not args.request or not args.record_result or not args.source):
        parser.error('--request requires an exact path, source and result recording')

    root = args.root.resolve()
    from wiki_core.llm.context_pass import local_entry_selection
    try:
        entry_folder, entry_index = local_entry_selection(root, args.folder, args.index, cwd=Path.cwd(),
            approved_revision=args.approved_revision, policy_context=args.policy_context)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    if args.repo is not None and entry_folder is None:
        parser.error('repository selection requires a local folder')
    if args.request is not None and entry_folder is None:
        parser.error('request selection requires a local folder')
    if entry_folder is not None and (args.allow_unrequested or args.query or args.required_perspective
                                     or args.optional_perspective or not args.source or not args.source.strip()):
        parser.error('folder entry requires an explicit source and its requested result')
    config = load_config(root)
    paths = WikiPaths(root, config)
    try:
        limits = request_limits(args.context_max_bytes, args.request_max_bytes)
    except ValueError as exc:
        return _blocked(exc, "source-context-pass", config.owner_label)
    try:
        from wiki_core.traversal import require_wiki_boundaries
        require_wiki_boundaries(root, directories=(paths.source_manifests, paths.source_text, paths.chunks,
            paths.extraction_events, paths.llm_cache))
    except (ValueError, OSError) as exc:
        if args.query and not args.source:
            return _blocked(ContextRequestBlocked("query_index_unavailable",
                "The query input or index crosses a repository boundary; inspect its location."),
                "query-context-pass", config.owner_label)
        return _blocked(exc, "source-context-pass", config.owner_label)
    selected_context = None
    selected_source = None
    if entry_folder is not None:
        try:
            from wiki_core.repo_read import contains_access_secrets
            from wiki_core.llm.context_pass import validate_local_entry_source
            if contains_access_secrets([args.context, args.source, args.record_result]):
                raise ValueError('source selection unavailable')
            try:
                selected_context = ingestion_block_context(root, config, {}, [], entry_folder=entry_folder,
                    entry_index=entry_index, context_max_bytes=args.context_max_bytes)
            except (ValueError, OSError) as exc:
                raise ContextRequestBlocked('local_folder_unavailable',
                    'Selected folder instructions or index are unavailable; no fallback was used.') from exc
            if args.source:
                selected_source = validate_local_entry_source(root, args.source)
            if args.repo is not None:
                expected_documents = None
                if args.record_result:
                    if args.request is None:
                        raise ValueError('explicit retained request required for Git-bound result')
                    # Locate the source's one retained request from the current
                    # selected source, never from a result payload or a scan.
                    selected_source = validate_local_entry_source(root, selected_source)
                    observed = build_manifest(selected_source, args.context, root=root)
                    retained = _retained_local_request(paths, str(observed['source_id']), args.request_max_bytes, args.request)
                    package = retained.get('block_context_package')
                    if (not isinstance(package, dict) or not isinstance(package.get('documents'), list)
                            or any(not isinstance(row, dict) for row in package['documents'])
                            or package.get('entry_folder') != selected_context.get('entry_folder')
                            or package.get('entry_index') != selected_context.get('entry_index')
                            or retained.get('source_hash_sha256') != observed.get('hash_sha256')
                            or retained.get('source_context') != args.context
                            or retained.get('request_limits') != limits):
                        raise ValueError('retained local request differs')
                    expected_documents = package['documents']
                    local_documents = [row for row in expected_documents
                                       if isinstance(row, dict) and row.get('origin') != 'independent_git']
                    if local_documents != selected_context['documents']:
                        raise ValueError('retained local context differs')
                selected_context = ingestion_block_context(root, config, {}, [], entry_folder=entry_folder,
                    entry_index=entry_index, context_max_bytes=args.context_max_bytes, repo_selections=args.repo,
                    expected_documents=expected_documents)
        except (ValueError, OSError) as exc:
            return _blocked(exc, 'requested-input', config.owner_label)
    if args.root_entity_ref is not None or args.omit_root_entity:
        return _blocked(ContextRequestBlocked("root_selection_requires_approval", "Business-root selection requires explicit approved context; no compatibility fallback was used."), "source-context-pass", config.owner_label)
    if args.record_result and not args.source and not args.query:
        return _record_results(paths, args.record_result, allow_unrequested=args.allow_unrequested,
            limits=limits, owner=config.owner_label)

    if not args.source and not args.query:
        parser.error("provide --source, --query or --record-result")

    prompt_versions = dict(config.llm.get("prompt_versions", {}))
    prompt_version = str(
        prompt_versions.get("context_deep_read", DEFAULT_CONTEXT_DEEP_READ_PROMPT_VERSION)
    )
    schema_version = CONTEXT_PASS_SCHEMA_VERSION
    model_profile = args.profile or str(config.llm.get("default_model_profile", "deep_context"))
    required = bool(config.llm.get("required_context_pass", True))

    if args.source:
        source = selected_source if entry_folder is not None else args.source
        if not Path(source).is_absolute() and not urlsplit(source).scheme:
            source = str(root / source)
        try:
            if entry_folder is not None:
                source = validate_local_entry_source(root, source)
            manifest = build_manifest(source, args.context, root=root)
        except (ValueError, OSError) as exc:
            if entry_folder is None:
                raise
            return _blocked(exc, 'requested-input', config.owner_label)
        try:
            if entry_folder is not None:
                from wiki_core.traversal import require_wiki_path
                source_id = str(manifest['source_id'])
                for path in (paths.source_manifests / f'{source_id}.json', paths.source_text / f'{source_id}.json',
                             paths.chunks / f'{source_id}.json', paths.llm_cache):
                    require_wiki_path(root, path.relative_to(root).as_posix())
            else:
                manifest = resolve_source_manifest(manifest, paths.source_manifests, paths.chunks, root=root)
            chunks = _chunks_for_source(paths, manifest)
        except ValueError as exc:
            if args.check:
                print(json.dumps({
                    "source_id": manifest["source_id"], "required_context_pass": required,
                    "ok": False, "error": str(exc),
                    "remediation": (
                        "Restore the same source if missing. Regenerate its artifacts with "
                        "python3 scripts/wiki_ingest.py --source <source> --context <context>; "
                        "resolve extraction warnings or missing dependencies, then repeat this check. "
                        "Do not replace missing or inconsistent artifacts with empty lists."
                    ),
                }, ensure_ascii=False, indent=2))
            else:
                print(f"ERROR: {exc}. Re-extract the source and review its artifacts.", file=sys.stderr)
            return 2
        try:
            if entry_folder is not None:
                from wiki_core.input_stage import local_folder_input_context
                source_config, input_context = None, local_folder_input_context()
            else:
                source_config = find_source_config(root, config, args.source)
                input_context = input_context_for_source(root, config, args.source)
                input_context["source_config"] = source_config
        except (ValueError, OSError) as exc:
            return _blocked(exc, "requested-input", config.owner_label)
    else:
        try:
            manifest, chunks = _chunks_for_query(paths, args.query or "")
        except (ValueError, OSError):
            return _blocked(ContextRequestBlocked("query_index_unavailable",
                "The query index is unavailable or outside the selected wiki; inspect its location and rebuild if needed."),
                "query-context-pass", config.owner_label)
        source_config = None
        input_context = {
            "root_entity": None,
            "input_channel": None,
            "quadrant_map": {},
            "quadrant_semantics": {},
            "quadrant_boundary_rule": "",
            "target_pages": [],
            "perspectives_required": [],
            "perspectives_optional": [],
            "input_stage_status": "query",
        }

    manifest["context"] = args.context
    perspectives_required, perspectives_optional = merge_perspectives(
        source_config,
        required=args.required_perspective,
        optional=args.optional_perspective,
        root_required=list(input_context.get("perspectives_required") or []),
        root_optional=list(input_context.get("perspectives_optional") or []),
    )
    try:
        context_package = selected_context if entry_folder is not None else ingestion_block_context(root, config, input_context,
            perspectives_required, task_id=str(manifest.get("source_id") or "source-context-pass"),
            context_max_bytes=args.context_max_bytes,
            entry_folder=entry_folder, entry_index=entry_index)
        request = build_context_request(
            manifest,
            chunks,
            paths.llm_cache,
            prompt_version,
            schema_version,
            model_profile,
            context_root=root,
            perspectives_required=perspectives_required,
            perspectives_optional=perspectives_optional,
            root_entity=input_context.get("root_entity") if isinstance(input_context.get("root_entity"), dict) else None,
            input_channel=input_context.get("input_channel") if isinstance(input_context.get("input_channel"), dict) else None,
            quadrant_map=input_context.get("quadrant_map") if isinstance(input_context.get("quadrant_map"), dict) else None,
            quadrant_semantics=input_context.get("quadrant_semantics")
            if isinstance(input_context.get("quadrant_semantics"), dict)
            else None,
            quadrant_boundary_rule=str(input_context.get("quadrant_boundary_rule") or ""),
            target_pages=list(input_context.get("target_pages") or []),
            input_stage_status=str(input_context.get("input_stage_status") or ""),
            block_context_package=context_package,
            context_max_bytes=args.context_max_bytes, request_max_bytes=args.request_max_bytes,
            cache_root=root if entry_folder is not None else None,
        )
        if source_config:
            request["source_config_ref"] = source_config["path"]
            request["source_config_perspectives_applied"] = True
        enforce_request_budget(request, context_max_bytes=args.context_max_bytes, request_max_bytes=args.request_max_bytes)
    except (ValueError, OSError) as exc:
        return _blocked(exc, str(manifest.get("source_id") or "source-context-pass"), config.owner_label)

    def revalidate_entry():
        from wiki_core.llm.context_pass import validate_local_entry_source
        current = ingestion_block_context(root, config, {}, [], entry_folder=entry_folder,
            entry_index=entry_index, context_max_bytes=args.context_max_bytes, repo_selections=args.repo,
            expected_documents=context_package['documents'])
        current_source = validate_local_entry_source(root, source)
        observed = build_manifest(current_source, args.context, root=root)
        if (context_package != current
                or observed.get('hash_sha256') != manifest.get('hash_sha256')):
            raise ValueError('selected source or folder context changed')

    if args.record_result:
        if args.request is not None:
            try:
                retained = _retained_local_request(paths, str(request['source_id']), args.request_max_bytes, args.request)
                if retained['folder_request_id'] != request.get('folder_request_id'):
                    raise ValueError('selected request differs from current context')
            except (ValueError, OSError, KeyError):
                return _blocked(ContextRequestBlocked('local_request_unavailable',
                    'The selected request does not match the current source and context.'), 'requested-input', config.owner_label)
        return _record_results(paths, args.record_result, allow_unrequested=args.allow_unrequested,
            current_request=request, limits=limits, owner=config.owner_label,
            before_write=revalidate_entry if entry_folder is not None else None,
            preserve_existing=entry_folder is not None)
    if args.check:
        report = {
            "source_id": manifest.get("source_id"),
            "chunks": len(chunks),
            "pending_llm_calls": request["pending_llm_calls"],
            "required_context_pass": required,
            "ok": not (required and request["pending_llm_calls"] > 0),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if (required and request["pending_llm_calls"] > 0) else 0

    if args.emit_request:
        out = paths.extraction_events / f"{request['source_id']}-llm-context-request.json"
        if entry_folder is not None:
            try:
                revalidate_entry()
                from wiki_core.llm.context_pass import retain_local_request
                out = retain_local_request(paths, request)
            except (ValueError, OSError) as exc:
                return _blocked(ContextRequestBlocked('local_persistence_partial',
                    'Local request persistence stopped; partial effects may exist and must be inspected before retrying.'),
                    str(manifest.get('source_id') or 'source-context-pass'), config.owner_label)
        else:
            try:
                require_wiki_boundaries(root, files=(out,))
            except (ValueError, OSError) as exc:
                return _blocked(exc, str(request['source_id']), config.owner_label)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(canonical_request_text(request), encoding="utf-8")
        print(out.relative_to(root))
        return 0

    print(canonical_request_text(request), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
