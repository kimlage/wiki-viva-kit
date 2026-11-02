#!/usr/bin/env python3
"""Contextual LLM pass delegated to the agent running the repo.

This script does NOT call any model. It:
  - gathers/selects chunks (by source or by sanitized FTS search);
  - assembles a context PACKAGE (request) with prompt + schema + chunk text;
  - records the RESULT the agent (Claude/Codex/Gemini) produced, in the cache;
  - acts as a gate (`--check`): fails while there is a pending chunk and
    `required_context_pass` is enabled.

Examples:
  python3 scripts/wiki_llm_context_pass.py --source X.pdf --context system --emit-request
  python3 scripts/wiki_llm_context_pass.py --query "pending decisions" --context system
  python3 scripts/wiki_llm_context_pass.py --record-result result.json --context system
  python3 scripts/wiki_llm_context_pass.py --source X.pdf --context system --check
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wiki_core.config import DEFAULT_CONTEXT_DEEP_READ_PROMPT_VERSION, load_config
from wiki_core.ids import sha256_text
from wiki_core.index.sqlite import search
from wiki_core.input_stage import input_context_for_source
from wiki_core.llm import CONTEXT_PASS_SCHEMA_VERSION, build_context_request, write_result
from wiki_core.llm.context_pass import (result_matches_request, ingestion_block_context,
    DEFAULT_CONTEXT_MAX_BYTES, DEFAULT_REQUEST_MAX_BYTES, ContextRequestBlocked,
    canonical_request_text, enforce_request_budget, preparation_blocker, request_limits,
    authorize_ingestion_source, revalidate_ingestion_source, approved_ingestion_inputs)
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
    hits = search(db_path, query, limit=20)
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


def _emitted_requests(paths: WikiPaths, *, sizes: dict | None = None) -> list[dict]:
    """Read emitted semantic packets for exact result provenance validation."""
    requests: list[dict] = []
    if not paths.extraction_events.exists():
        return requests
    for path in paths.extraction_events.glob("*-llm-context-request.json"):
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


def _record_results(paths: WikiPaths, payload_path: str, *, allow_unrequested: bool = False,
                    current_request: dict | None = None, limits: dict | None = None, owner: str = "Context owner/integrator", before_write=None) -> int:
    raw = sys.stdin.read() if payload_path == "-" else Path(payload_path).read_text(encoding="utf-8")
    data = json.loads(raw)
    results = data if isinstance(data, list) else [data]
    retained_sizes = {}
    requests = [] if allow_unrequested else _emitted_requests(paths, sizes=retained_sizes)
    limits = limits or request_limits()
    known = {str(row.get("cache_key")) for request in requests for row in request["chunks"] if isinstance(row, dict)}
    written = []
    for result in results:
        key = str(result.get("cache_key", "")) if isinstance(result, dict) else ""
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
                f"ERROR: cache_key {key!r} without a corresponding emitted context request "
                f"({detail}); result rejected (provenance). Emit the request before "
                "recording, or use --allow-unrequested for legitimate cases with no "
                "request on disk.",
                file=sys.stderr,
            )
            return 2
        matching = [request for request in requests if any(row.get("cache_key") == key
                    for row in request["chunks"] if isinstance(row, dict))]
        for request in matching:
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
        try:
            if before_write is not None:
                before_write()
            out = write_result(paths.llm_cache, result)
        except (ValueError, OSError) as exc:
            if before_write is not None:
                return _blocked(exc, str(current_request.get("source_id") or "requested-input"), owner)
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        written.append(str(out.relative_to(getattr(paths, "root", ROOT))))
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
    parser.add_argument("--approved-revision", help="Trusted local caller supplies current approved policy commit; this is not a remote access grant.")
    parser.add_argument("--policy-context", help="Explicit manifest context for the approved-policy adapter.")
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
    parser.add_argument(
        "--allow-unrequested",
        action="store_true",
        help="records the result even without a corresponding emitted request (skips the provenance check)",
    )
    parser.add_argument("--check", action="store_true", help="exit !=0 if there is a pending pass and required_context_pass")
    args = parser.parse_args()

    root = args.root.resolve()
    config = load_config(root)
    paths = WikiPaths(root, config)
    try:
        limits = request_limits(args.context_max_bytes, args.request_max_bytes)
    except ValueError as exc:
        return _blocked(exc, "source-context-pass", config.owner_label)
    if (args.root_entity_ref is not None or args.omit_root_entity) and not args.approved_revision:
        return _blocked(ContextRequestBlocked("root_selection_requires_approval", "Business-root selection requires explicit approved context; no compatibility fallback was used."), "source-context-pass", config.owner_label)
    if args.policy_context and not args.approved_revision:
        return _blocked(ValueError("approved revision required"), "source-context-pass", config.owner_label)
    if args.approved_revision and args.allow_unrequested:
        return _blocked(ContextRequestBlocked("approved_result_binding_required", "Approved mode refuses unrequested-result bypass; emit and read the current bound request before recording."), "source-context-pass", config.owner_label)
    if args.approved_revision and not args.source:
        return _blocked(ContextRequestBlocked("approved_source_required", "Approved mode requires an explicit source and its requested-result binding."), "source-context-pass", config.owner_label)
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

    source_guard = None
    if args.source:
        if args.approved_revision is not None:
            try:
                source_guard = authorize_ingestion_source(root, args.source, args.approved_revision, args.policy_context)
            except (ValueError, OSError) as exc:
                return _blocked(exc, "requested-input", config.owner_label)
        source = str(source_guard["path"]) if source_guard else args.source
        if not Path(source).is_absolute() and not urlsplit(source).scheme:
            source = str(root / source)
        manifest = build_manifest(source, args.context, root=root)
        try:
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
            if source_guard is not None:
                revalidate_ingestion_source(source_guard, captured_hash=str(manifest.get("hash_sha256") or ""))
                source_config, input_context = approved_ingestion_inputs(root, config, source_guard, root_entity_ref=args.root_entity_ref, omit_root_entity=args.omit_root_entity)
            else:
                source_config = find_source_config(root, config, args.source)
                input_context = input_context_for_source(root, config, args.source)
                input_context["source_config"] = source_config
        except (ValueError, OSError) as exc:
            return _blocked(exc, "requested-input", config.owner_label)
    else:
        manifest, chunks = _chunks_for_query(paths, args.query or "")
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
        request = build_context_request(
            manifest,
            chunks,
            paths.llm_cache,
            prompt_version,
            schema_version,
            model_profile,
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
            block_context_package=ingestion_block_context(root, config, input_context,
                perspectives_required, approved_revision=args.approved_revision, policy_context=args.policy_context,
                task_id=str(manifest.get("source_id") or "source-context-pass"), context_max_bytes=args.context_max_bytes,
                content_revision=source_guard["reader"].revision if source_guard else "HEAD"),
            context_max_bytes=args.context_max_bytes, request_max_bytes=args.request_max_bytes,
            source_authorization=source_guard["authorization"] if source_guard else None,
        )
        if source_config:
            request["source_config_ref"] = source_config["path"]
            request["source_config_perspectives_applied"] = True
        enforce_request_budget(request, context_max_bytes=args.context_max_bytes, request_max_bytes=args.request_max_bytes)
        if source_guard is not None:
            revalidate_ingestion_source(source_guard, captured_hash=str(manifest.get("hash_sha256") or ""))
    except (ValueError, OSError) as exc:
        return _blocked(exc, str(manifest.get("source_id") or "source-context-pass"), config.owner_label)
    if args.record_result:
        return _record_results(paths, args.record_result, allow_unrequested=args.allow_unrequested,
            current_request=request, limits=limits, owner=config.owner_label,
            before_write=(lambda: revalidate_ingestion_source(source_guard, captured_hash=str(manifest.get("hash_sha256") or ""))) if source_guard else None)
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
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(canonical_request_text(request), encoding="utf-8")
        print(out.relative_to(root))
        return 0

    print(canonical_request_text(request), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
