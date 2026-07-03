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
from dataclasses import asdict, dataclass
from pathlib import Path

from wiki_core.chunking import chunk_text
from wiki_core.config import DEFAULT_CONTEXT_DEEP_READ_PROMPT_VERSION, WikiConfig
from wiki_core.detectors import scan_file, scan_text
from wiki_core.extractors import extract_source
from wiki_core.index.sqlite import index_source
from wiki_core.input_stage import input_context_for_source
from wiki_core.llm import build_context_request
from wiki_core.llm.context_pass import CONTEXT_PASS_SCHEMA_VERSION
from wiki_core.paths import WikiPaths
from wiki_core.score import record_event
from wiki_core.source_config import find_source_config, merge_perspectives
from wiki_core.source_manifest import build_manifest, write_manifest

SCHEMA_VERSION = "wiki_ingest_pipeline.v1"


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

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": SCHEMA_VERSION, **asdict(self)}


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


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
) -> IngestResult:
    """Run the deterministic pipeline for ``source`` and return an IngestResult.

    With ``write=False`` (dry-run) nothing is written to disk: chunks/packet are
    computed in memory and the index/score are not touched.
    """
    paths = WikiPaths(root, config)

    manifest = build_manifest(source, context)
    source_id = str(manifest["source_id"])
    source_type = str(manifest["source_type"])
    warnings: list[str] = []

    src_path = Path(source).expanduser()
    is_local_file = bool(manifest.get("exists")) and source_type != "url" and src_path.is_file()

    # --- Extraction and chunking in MEMORY (nothing written yet) ---
    chunk_dicts: list[dict[str, object]] = []
    extracted = None
    chunk_count = 0
    if is_local_file:
        extracted = extract_source(source, source_type)
        warnings = list(extracted.warnings)
        target = int(config.llm.get("chunk_target_tokens", 1200))
        overlap = int(config.llm.get("chunk_overlap_tokens", 150))
        text_chunks = chunk_text(source_id, extracted.text, target, overlap)
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
        findings = list(scan_file(src_path))
        if extracted is not None and extracted.text:
            findings += list(scan_text(extracted.text))
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
    persist = write and not blocked

    if persist:
        paths.ensure()

    manifest_path = _rel(write_manifest(manifest, paths.source_manifests), root) if persist else None

    text_path: str | None = None
    chunks_path: str | None = None
    if persist and is_local_file and extracted is not None:
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
        chunks_file.write_text(
            json.dumps(
                {
                    "schema_version": "wiki_chunks.v1",
                    "source_id": source_id,
                    "source_hash_sha256": manifest.get("hash_sha256"),
                    "chunks": chunk_dicts,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        chunks_path = _rel(chunks_file, root)

    chunks_indexed = 0
    if persist and chunk_dicts:
        # INCREMENTAL indexing: only the just-written source is (re)indexed,
        # instead of a full rebuild of the whole directory on every ingestion
        # (finding 13).
        index_result = index_source(
            paths.indexes / "wiki.sqlite", paths.chunks / f"{source_id}.json"
        )
        chunks_indexed = int(index_result.get("chunks_indexed", 0))

    request_path: str | None = None
    pending = 0
    if chunk_dicts and not blocked:
        prompt_version = str(
            config.llm.get("prompt_versions", {}).get(
                "context_deep_read", DEFAULT_CONTEXT_DEEP_READ_PROMPT_VERSION
            )
        )
        model_profile = str(config.llm.get("default_model_profile", "deep_context"))
        source_config = find_source_config(root, config, source)
        input_context = input_context_for_source(root, config, source)
        perspectives_required, perspectives_optional = merge_perspectives(
            source_config,
            required=[],
            optional=[],
            root_required=list(input_context.get("perspectives_required") or []),
            root_optional=list(input_context.get("perspectives_optional") or []),
        )
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
        )
        if source_config:
            request["source_config_ref"] = source_config["path"]
            request["source_config_perspectives_applied"] = True
        pending = int(request.get("pending_llm_calls", 0))
        if persist:
            request_file = paths.extraction_events / f"{source_id}-llm-context-request.json"
            request_file.write_text(
                json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            request_path = _rel(request_file, root)

    score_event_id: str | None = None
    if persist and record_score and chunk_count > 0:
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
        write_stream_cursor(
            paths.source_state,
            source_id,
            stream_id,
            cursor=ts or str(manifest.get("content_sha") or manifest.get("source_id") or ""),
            last_unit=str(last_unit),
            updated_at=(ts or "")[:10],
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
    )
