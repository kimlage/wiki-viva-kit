"""End-to-end ingestion orchestrator for the living wiki.

Chains the deterministic steps that previously existed only as CLIs/islands:

    extract -> pre-scan (secrets BLOCK before persisting; PII is informative,
            welcome on a private page) -> manifest + text + chunks -> index
            -> LLM context packet (emits the -request.json the gate watches)
            -> score-event (ingestar_fonte_valida)

Scan-first: the pre-scan runs BEFORE writing any artifact. If there is a secret,
NOTHING is persisted (manifest, text, chunks, index, request, score) — before,
the secret was already in data/derived and indexed in FTS when the "block"
happened.

Does NOT write canonical memory nor call a model: the LLM pass stays delegated
to the agent running the repo (the skill reads the -request.json and writes the
result to the cache). The result carries gate_state=created and an
llm_context_status derived from the REAL chunks, so the proposal reflects
artifacts that actually exist.
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterator

from wiki_core.chunking import chunk_text
from wiki_core.config import DEFAULT_CONTEXT_DEEP_READ_PROMPT_VERSION, WikiConfig
from wiki_core.detectors import scan_file, scan_text
from wiki_core.extractors import extract_source
from wiki_core.index.sqlite import index_source
from wiki_core.input_stage import input_context_for_source
from wiki_core.llm import build_context_request
from wiki_core.llm.context_pass import (CONTEXT_PASS_SCHEMA_VERSION, ingestion_block_context,
    DEFAULT_CONTEXT_MAX_BYTES, DEFAULT_REQUEST_MAX_BYTES, preparation_blocker,
    enforce_request_budget, canonical_request_text, request_limits, ContextRequestBlocked,
    authorize_ingestion_source, revalidate_ingestion_source, approved_ingestion_inputs,
    require_approved_prompt_version)
from wiki_core.paths import WikiPaths
from wiki_core.score import record_event
from wiki_core.source_config import find_source_config, merge_perspectives
from wiki_core.source_manifest import (build_manifest, write_manifest, chunk_document,
                                      write_source_artifact, require_capture_not_regressed)

SCHEMA_VERSION = "wiki_ingest_pipeline.v1"
IngestObserver = Callable[[str, int, dict[str, object]], None]


@contextmanager
def _observed(
    observer: IngestObserver | None,
    stage: str,
    **metrics: object,
) -> Iterator[dict[str, object]]:
    """Emit opt-in timings without changing the functional result."""

    started = time.perf_counter_ns()
    dynamic: dict[str, object] = {}
    try:
        yield dynamic
    finally:
        if observer is not None:
            observer(stage, time.perf_counter_ns() - started, {**metrics, **dynamic})


@dataclass(frozen=True)
class IngestResult:
    source_id: str
    context: str
    source_type: str
    written: bool
    blocked: bool
    manifest_path: str | None
    text_path: str | None
    chunks_path: str | None
    chunk_count: int
    chunks_indexed: int
    request_path: str | None
    pending_llm_calls: int
    secret_findings: list[dict[str, object]]
    pii_findings: list[dict[str, object]]
    score_event_id: str | None
    gate_state: str
    llm_context_status: str
    warnings: list[str]
    stream_id: str | None = None
    stream_cursor_written: bool = False
    index_diagnostics: dict[str, int] = field(default_factory=dict)
    blockers: list[dict[str, object]] = field(default_factory=list)
    context_error_code: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": SCHEMA_VERSION, **asdict(self)}


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _blocked_preparation(context, config, exc):
    report = preparation_blocker(exc, "requested-input", config.owner_label)
    return IngestResult(source_id="", context=context, source_type="unverified",
        written=False, blocked=True, manifest_path=None, text_path=None, chunks_path=None,
        chunk_count=0, chunks_indexed=0, request_path=None, pending_llm_calls=0,
        secret_findings=[], pii_findings=[], score_event_id=None, gate_state="blocked",
        llm_context_status="blocked", warnings=[], blockers=[report["blocker"]],
        context_error_code=report["error_code"])


def run(
    source: str,
    context: str,
    root: Path,
    config: WikiConfig,
    *,
    write: bool = True,
    record_score: bool = True,
    actor: str | None = None,
    ts: str | None = None,
    stream_id: str | None = None,
    observer: IngestObserver | None = None,
    approved_revision: str | None = None,
    policy_context: str | None = None,
    context_max_bytes: int = DEFAULT_CONTEXT_MAX_BYTES,
    request_max_bytes: int = DEFAULT_REQUEST_MAX_BYTES,
    root_entity_ref: str | None = None,
    omit_root_entity: bool = False,
    entry_folder: str | None = None,
    entry_index: str | None = None,
) -> IngestResult:
    """Run the deterministic pipeline for ``source`` and return an IngestResult.

    With ``write=False`` (dry-run) nothing is written to disk: chunks/packet are
    computed in memory and the index/score are not touched.
    """
    paths = WikiPaths(root, config)
    source_guard = None
    try:
        request_limits(context_max_bytes, request_max_bytes)
        if (approved_revision is not None or policy_context is not None) and (entry_folder is not None or entry_index is not None):
            raise ValueError('folder selection cannot replace an approved policy')
        if entry_index is not None and entry_folder is None:
            raise ValueError('index requires a context folder')
        if (root_entity_ref is not None or omit_root_entity) and not approved_revision:
            raise ContextRequestBlocked("root_selection_requires_approval", "Business-root selection requires explicit approved context; no compatibility fallback was used.")
        if approved_revision is not None or policy_context is not None:
            if not approved_revision or not policy_context:
                raise ContextRequestBlocked("approved_source_context_required", "Approved ingestion requires a current approved revision and explicit policy context.")
            prompt_version = str(config.llm.get("prompt_versions", {}).get(
                "context_deep_read", DEFAULT_CONTEXT_DEEP_READ_PROMPT_VERSION))
            require_approved_prompt_version(prompt_version)
            source_guard = authorize_ingestion_source(root, source, approved_revision, policy_context)
            source = str(source_guard["path"])
    except (ValueError, OSError) as exc:
        return _blocked_preparation(context, config, exc)

    source_path = Path(source).expanduser()
    source_bytes = source_path.stat().st_size if source_path.is_file() else None
    with _observed(observer, "manifest_hash", bytes_read=source_bytes):
        manifest = build_manifest(source, context, root=root)
    if source_guard is not None:
        try:
            revalidate_ingestion_source(source_guard, captured_hash=str(manifest.get("hash_sha256") or ""))
        except (ValueError, OSError) as exc:
            return _blocked_preparation(context, config, exc)
    source_id = str(manifest["source_id"])
    source_type = str(manifest["source_type"])
    warnings: list[str] = []

    src_path = source_path
    is_local_file = bool(manifest.get("exists")) and source_type != "url" and src_path.is_file()

    # --- Extraction and chunking in MEMORY (nothing written yet) ---
    chunk_dicts: list[dict[str, object]] = []
    extracted = None
    chunk_count = 0
    if is_local_file:
        with _observed(observer, "extraction", bytes_read=source_bytes) as metrics:
            extracted = extract_source(source, source_type)
            metrics["text_characters"] = len(extracted.text)
        warnings = list(extracted.warnings)
        target = int(config.llm.get("chunk_target_tokens", 1200))
        overlap = int(config.llm.get("chunk_overlap_tokens", 150))
        with _observed(
            observer,
            "chunking",
            text_characters=len(extracted.text),
        ) as metrics:
            text_chunks = chunk_text(source_id, extracted.text, target, overlap)
            metrics["chunk_count"] = len(text_chunks)
        chunk_count = len(text_chunks)
        chunk_dicts = [
            {
                "chunk_id": chunk.chunk_id,
                "ordinal": chunk.ordinal,
                "hash_sha256": chunk.hash_sha256,
                "token_estimate": chunk.token_estimate,
                "text": chunk.text,
            }
            for chunk in text_chunks
        ]

    # --- SCAN-FIRST: pre-screening BEFORE any persistence ---
    # Scans the raw file AND the extracted text (covers a secret that only shows
    # up in the text of a PDF/spreadsheet, invisible in the raw bytes).
    secret_findings: list[dict[str, object]] = []
    pii_findings: list[dict[str, object]] = []
    if is_local_file:
        with _observed(observer, "raw_scan", bytes_read=source_bytes) as metrics:
            findings = list(scan_file(src_path))
            metrics["finding_count"] = len(findings)
        if extracted is not None and extracted.text:
            with _observed(
                observer,
                "extracted_text_scan",
                text_characters=len(extracted.text),
            ) as metrics:
                extracted_findings = list(scan_text(extracted.text))
                metrics["finding_count"] = len(extracted_findings)
            findings += extracted_findings
        seen: set[tuple[str, int, str]] = set()
        for finding in findings:
            dedup = (finding.kind, finding.line, finding.excerpt)
            if dedup in seen:
                continue
            seen.add(dedup)
            row = {"kind": finding.kind, "line": finding.line, "excerpt": finding.excerpt}
            if finding.category == "secret":
                secret_findings.append(row)
            elif finding.category == "pii":
                pii_findings.append(row)

    # A secret in the source BLOCKS: nothing is persisted (scan-first).
    blocked = bool(secret_findings)
    if write and not blocked and extracted is not None:
        try:
            require_capture_not_regressed(paths.chunks / f"{source_id}.json",
                chunk_document(manifest, chunk_dicts, warnings=warnings))
        except ValueError as exc:
            blocked = True
            warnings.append(str(exc))
    request_path: str | None = None
    request = None
    pending = 0
    blockers = []
    context_error_code = None
    if chunk_dicts and not blocked:
        try:
            prompt_version = str(
                config.llm.get("prompt_versions", {}).get(
                    "context_deep_read", DEFAULT_CONTEXT_DEEP_READ_PROMPT_VERSION
                )
            )
            model_profile = str(config.llm.get("default_model_profile", "deep_context"))
            with _observed(observer, "input_stage_context") as metrics:
                if source_guard is not None:
                    source_config, input_context = approved_ingestion_inputs(root, config, source_guard, root_entity_ref=root_entity_ref, omit_root_entity=omit_root_entity)
                else:
                    source_config = find_source_config(root, config, source)
                    input_context = input_context_for_source(root, config, source)
                    input_context["source_config"] = source_config
                perspectives_required, perspectives_optional = merge_perspectives(
                    source_config,
                    required=[],
                    optional=[],
                    root_required=list(input_context.get("perspectives_required") or []),
                    root_optional=list(input_context.get("perspectives_optional") or []),
                )
                metrics["target_page_count"] = len(input_context.get("target_pages") or [])
                metrics["perspective_count"] = len(perspectives_required) + len(perspectives_optional)
            with _observed(observer, "llm_request", chunk_count=len(chunk_dicts)) as metrics:
                context_package = ingestion_block_context(root, config, input_context,
                    perspectives_required, approved_revision=approved_revision, policy_context=policy_context,
                    task_id=source_id, context_max_bytes=context_max_bytes,
                    content_revision=source_guard["reader"].revision if source_guard else "HEAD",
                    entry_folder=entry_folder, entry_index=entry_index)
                request = build_context_request(
                    manifest,
                    chunk_dicts,
                    paths.llm_cache,
                    prompt_version,
                    CONTEXT_PASS_SCHEMA_VERSION,
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
                    block_context_package=context_package,
                    context_max_bytes=context_max_bytes, request_max_bytes=request_max_bytes,
                    source_authorization=source_guard["authorization"] if source_guard else None,
                )
                metrics["pending_llm_calls"] = int(request.get("pending_llm_calls", 0))
            if source_config:
                request["source_config_ref"] = source_config["path"]
                request["source_config_perspectives_applied"] = True
            enforce_request_budget(request, context_max_bytes=context_max_bytes, request_max_bytes=request_max_bytes)
            pending = int(request.get("pending_llm_calls", 0))
        except (ValueError, OSError) as exc:
            report = preparation_blocker(exc, source_id, config.owner_label)
            blockers.append(report["blocker"])
            context_error_code = report["error_code"]
            pending = chunk_count
            request = None
            blocked = True
    # This fence covers zero-chunk captures too: they may replace artifacts or
    # prune an existing index even though no LLM request was assembled.
    if source_guard is not None and not blocked:
        try:
            revalidate_ingestion_source(source_guard, captured_hash=str(manifest.get("hash_sha256") or ""))
        except (ValueError, OSError) as exc:
            report = preparation_blocker(exc, source_id, config.owner_label)
            blockers.append(report["blocker"])
            context_error_code = report["error_code"]
            pending = chunk_count
            request = None
            blocked = True
    if write and entry_folder is not None and not blocked:
        # Until requests and captures support multiple local contexts, never
        # replace an existing source's artifacts when entering another folder.
        try:
            from wiki_core.llm.context_pass import _folder_documents
            if request is not None:
                current = _folder_documents(root, entry_folder, entry_index, context_max_bytes)
                if context_package['documents'][:len(current)] != current:
                    raise ValueError('selected folder context changed before persistence')
                current_manifest = build_manifest(source, context, root=root)
                if current_manifest.get('hash_sha256') != manifest.get('hash_sha256'):
                    raise ValueError('selected source changed before persistence')
            from wiki_core.traversal import require_wiki_path
            existing = (paths.source_manifests / f'{source_id}.json',
                        paths.source_text / f'{source_id}.json',
                        paths.chunks / f'{source_id}.json',
                        paths.extraction_events / f'{source_id}-llm-context-request.json')
            selected = [require_wiki_path(root, path.relative_to(root).as_posix()) for path in existing]
            if any(path.exists() for path in selected):
                raise ContextRequestBlocked('existing_source_context_conflict',
                    'Existing source capture or request was preserved; contextual reuse is not available yet.')
        except (ValueError, OSError) as exc:
            report = preparation_blocker(exc, source_id, config.owner_label)
            blockers.append(report['blocker']); context_error_code = report['error_code']
            pending = chunk_count; request = None; blocked = True
    persist = write and not blocked

    if persist:
        paths.ensure()

    text_path: str | None = None
    chunks_path: str | None = None
    manifest_path: str | None = None
    if persist:
        with _observed(observer, "persistence") as metrics:
            manifest_file = write_manifest(manifest, paths.source_manifests)
            manifest_path = _rel(manifest_file, root)
            written_files = [manifest_file]
            if is_local_file and extracted is not None:
                text_file = paths.source_text / f"{source_id}.json"
                text_file.write_text(
                    json.dumps(
                        {
                            "schema_version": "wiki_extracted_text.v1",
                            "source_id": source_id,
                            "source_uri": source,
                            "source_type": source_type,
                            "context": context,
                            "warnings": warnings,
                            "text_characters": len(extracted.text),
                            "units": extracted.units,
                        },
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                text_path = _rel(text_file, root)
                chunks_file = paths.chunks / f"{source_id}.json"
                write_source_artifact(chunks_file, chunk_document(manifest, chunk_dicts, warnings=warnings))
                chunks_path = _rel(chunks_file, root)
                written_files.extend([text_file, chunks_file])
            metrics["files_written"] = len(written_files)
            metrics["bytes_written"] = sum(path.stat().st_size for path in written_files)

    chunks_indexed = 0
    index_diagnostics = {}
    if persist and (chunk_dicts or extracted is not None and not warnings):
        # INCREMENTAL indexing: only the just-written source is (re)indexed,
        # instead of a full rebuild of the whole directory on every ingestion
        # (finding 13).
        with _observed(observer, "fts") as metrics:
            index_result = index_source(
                paths.indexes / "wiki.sqlite", paths.chunks / f"{source_id}.json"
            )
            chunks_indexed = int(index_result.get("chunks_indexed", 0))
            index_diagnostics = {key: index_result[key] for key in
                ("ambiguous_origins", "unresolved_indexed_sources", "preserved_incomplete_sources")
                if index_result.get(key)}
            metrics["chunks_indexed"] = chunks_indexed
            index_path = paths.indexes / "wiki.sqlite"
            metrics["sqlite_bytes"] = index_path.stat().st_size if index_path.exists() else None

    if persist and request is not None:
        request_file = paths.extraction_events / f"{source_id}-llm-context-request.json"
        request_file.write_text(
            canonical_request_text(request),
            encoding="utf-8",
        )
        request_path = _rel(request_file, root)


    score_event_id: str | None = None
    if persist and record_score and chunk_count > 0:
        with _observed(observer, "score_event"):
            event = record_event(
                paths.derived_root / "score-events.jsonl",
                event_type="ingestar_fonte_valida",
                actor=actor or config.owner_label,
                context=context,
                ts=ts,
                dedup_key=f"ingest:{source_id}",
            )
            score_event_id = event.event_id

    if blocked:
        llm_context_status = "blocked"
    elif not chunk_dicts:
        llm_context_status = "skipped"
    elif pending > 0:
        llm_context_status = "pending"
    else:
        llm_context_status = "recorded"

    # F8 — the stream cursor is written ONLY here, after every durable write
    # (manifest, text, chunks, index, event) has landed. A crash before this
    # point re-reads next time; the manifest sha dedup makes that safe. Never on
    # a dry-run or a blocked ingest.
    stream_cursor_written = False
    if persist and not blocked and stream_id and chunk_count > 0:
        from wiki_core.source_state import write_stream_cursor

        last_unit = chunk_dicts[-1]["chunk_id"] if chunk_dicts else ""
        # The freshness read parses `updated_at` as an ISO date, so it must
        # ALWAYS be a real date — never empty and never a content sha. The
        # standard CLI passes no ts, so fall back to the manifest's captured_at
        # (when this source was actually read), never to an opaque id.
        stamp = str(ts or manifest.get("captured_at") or "")
        write_stream_cursor(
            paths.source_state,
            source_id,
            stream_id,
            cursor=stamp or str(manifest.get("source_id") or ""),
            last_unit=str(last_unit),
            updated_at=stamp[:10],
        )
        stream_cursor_written = True

    return IngestResult(
        source_id=source_id,
        context=context,
        source_type=source_type,
        written=persist,
        blocked=blocked,
        manifest_path=manifest_path,
        text_path=text_path,
        chunks_path=chunks_path,
        chunk_count=chunk_count,
        chunks_indexed=chunks_indexed,
        request_path=request_path,
        pending_llm_calls=pending,
        secret_findings=secret_findings,
        pii_findings=pii_findings,
        score_event_id=score_event_id,
        gate_state="blocked" if blocked else "created",
        llm_context_status=llm_context_status,
        warnings=warnings,
        stream_id=stream_id,
        stream_cursor_written=stream_cursor_written,
        index_diagnostics=index_diagnostics,
        blockers=blockers, context_error_code=context_error_code,
    )
