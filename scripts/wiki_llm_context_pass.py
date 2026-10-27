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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wiki_core.config import DEFAULT_CONTEXT_DEEP_READ_PROMPT_VERSION, load_config
from wiki_core.ids import sha256_text
from wiki_core.index.sqlite import search
from wiki_core.input_stage import input_context_for_source
from wiki_core.llm import CONTEXT_PASS_SCHEMA_VERSION, build_context_request, source_pending, write_result
from wiki_core.paths import WikiPaths
from wiki_core.source_config import find_source_config, merge_perspectives
from wiki_core.source_manifest import build_manifest


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


def _emitted_cache_keys(paths: WikiPaths) -> set[str]:
    """cache_keys of ALL context requests already emitted on disk.

    Used to validate PROVENANCE: a result can only be recorded if its cache_key
    matches a chunk of an emitted request. Without this, any JSON with the right
    keys and a made-up cache_key would close the required_context_pass gate
    (forgeable gate — finding 17).
    """
    keys: set[str] = set()
    if not paths.extraction_events.exists():
        return keys
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
        for chunk in data.get("chunks", []):
            key = chunk.get("cache_key")
            if key:
                keys.add(str(key))
    return keys


def _record_results(paths: WikiPaths, payload_path: str, *, allow_unrequested: bool = False) -> int:
    raw = sys.stdin.read() if payload_path == "-" else Path(payload_path).read_text(encoding="utf-8")
    data = json.loads(raw)
    results = data if isinstance(data, list) else [data]
    known = set() if allow_unrequested else _emitted_cache_keys(paths)
    written = []
    for result in results:
        key = str(result.get("cache_key", ""))
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
        try:
            out = write_result(paths.llm_cache, result)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        written.append(str(out.relative_to(ROOT)))
    print(json.dumps({"recorded": written, "count": len(written)}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source")
    parser.add_argument("--query")
    parser.add_argument("--context", required=True)
    parser.add_argument("--profile")
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

    config = load_config(ROOT)
    paths = WikiPaths(ROOT, config)
    paths.ensure()

    if args.record_result:
        return _record_results(paths, args.record_result, allow_unrequested=args.allow_unrequested)

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
        manifest = build_manifest(args.source, args.context, root=ROOT)
        try:
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
        source_config = find_source_config(ROOT, config, args.source)
        input_context = input_context_for_source(ROOT, config, args.source)
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

    pending = source_pending(manifest, chunks, paths.llm_cache, prompt_version, schema_version, model_profile)

    if args.check:
        report = {
            "source_id": manifest.get("source_id"),
            "chunks": len(chunks),
            "pending_llm_calls": pending,
            "required_context_pass": required,
            "ok": not (required and pending > 0),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if (required and pending > 0) else 0

    perspectives_required, perspectives_optional = merge_perspectives(
        source_config,
        required=args.required_perspective,
        optional=args.optional_perspective,
        root_required=list(input_context.get("perspectives_required") or []),
        root_optional=list(input_context.get("perspectives_optional") or []),
    )
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
    )
    if source_config:
        request["source_config_ref"] = source_config["path"]
        request["source_config_perspectives_applied"] = True

    if args.emit_request:
        out = paths.extraction_events / f"{request['source_id']}-llm-context-request.json"
        out.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(out.relative_to(ROOT))
        return 0

    print(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
