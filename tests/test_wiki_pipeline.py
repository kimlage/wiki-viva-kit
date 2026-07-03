"""Integration test for the ingestion orchestrator (anti-island regression).

Runs the full chain (manifest -> text/chunks -> index -> PII pre-scan ->
LLM context packet -> score-event) over a fixture source in tmp_path and
asserts each artifact is produced and coherent. No network; nothing is written
outside tmp_path. Ensures the modules (score/detectors/llm/index) stop being
islands triggered only by a manual CLI.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wiki_core.config import DEFAULT_CONTEXT_DEEP_READ_PROMPT_VERSION, WikiConfig
from wiki_core.index.sqlite import search
from wiki_core.ingest import run

LOREM = ("living wiki pipeline integration with enough text to span several chunks " * 40).strip()
AWS_KEY = "AKIAIOSFODNN7EXAMPLE"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_pipeline_produces_all_artifacts(tmp_path: Path) -> None:
    config = WikiConfig(repo_id="acme-wiki", owner_label="Alex Doe")
    src = tmp_path / "source.md"
    _write(src, "# Source\n\n" + LOREM + "\n")

    result = run(str(src), "system", tmp_path, config)
    derived = tmp_path / "data/derived/wiki"

    # 1. manifest
    assert result.manifest_path and (tmp_path / result.manifest_path).exists()
    assert (derived / "source-manifests" / f"{result.source_id}.json").exists()

    # 2. text + chunks
    assert result.chunk_count > 0
    assert (derived / "source-text" / f"{result.source_id}.json").exists()
    chunks_file = derived / "chunks" / f"{result.source_id}.json"
    assert chunks_file.exists()
    chunks_data = json.loads(chunks_file.read_text(encoding="utf-8"))
    assert chunks_data["schema_version"] == "wiki_chunks.v1"
    assert len(chunks_data["chunks"]) == result.chunk_count

    # 3. index
    assert result.chunks_indexed == result.chunk_count
    assert (derived / "indexes" / "wiki.sqlite").exists()

    # 4. LLM packet emitted and pending (empty cache) -> the auditor gate now has something to watch
    assert result.request_path and (tmp_path / result.request_path).exists()
    request = json.loads(
        (derived / "extraction-events" / f"{result.source_id}-llm-context-request.json").read_text(encoding="utf-8")
    )
    assert request["pending_llm_calls"] == result.chunk_count
    assert request["prompt_version"] == DEFAULT_CONTEXT_DEEP_READ_PROMPT_VERSION
    assert result.llm_context_status == "pending"

    # 5. score-event append-only
    assert result.score_event_id
    events = (derived / "score-events.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(events) == 1
    event = json.loads(events[0])
    assert event["event_type"] == "ingestar_fonte_valida"
    assert event["context"] == "system"

    # 6. proposal starts in the state machine
    assert result.gate_state == "created"


def test_pipeline_blocks_secret_in_source(tmp_path: Path) -> None:
    config = WikiConfig()
    src = tmp_path / "with_secret.md"
    _write(src, "service config\n\naws_key = " + AWS_KEY + "\n\n" + LOREM + "\n")

    result = run(str(src), "system", tmp_path, config)
    assert result.secret_findings, "the pre-screening should detect the secret in the source"
    # the raw secret never appears in the redacted excerpt
    assert all(AWS_KEY not in finding["excerpt"] for finding in result.secret_findings)

    # Scan-first: a secret BLOCKS before persisting — NOTHING goes to data/derived.
    assert result.blocked is True
    assert result.written is False
    assert result.gate_state == "blocked"
    assert result.llm_context_status == "blocked"
    assert result.manifest_path is None
    assert result.chunks_path is None
    assert result.request_path is None
    assert result.score_event_id is None
    derived = tmp_path / "data/derived/wiki"
    leaked = [
        str(p)
        for p in derived.rglob("*")
        if p.is_file() and AWS_KEY in p.read_text(encoding="utf-8", errors="ignore")
    ]
    assert not leaked, f"the secret leaked into derived artifacts: {leaked}"
    sqlite = derived / "indexes" / "wiki.sqlite"
    assert not sqlite.exists() or AWS_KEY.encode() not in sqlite.read_bytes()


def test_pipeline_reingest_prunes_stale_version_from_index(tmp_path: Path) -> None:
    config = WikiConfig()
    src = tmp_path / "source.md"
    _write(src, "# Source\n\nstaleword only in v1\n\n" + LOREM + "\n")
    first = run(str(src), "system", tmp_path, config)

    # Edit the source and re-ingest: new digest, hence a new source_id.
    _write(src, "# Source\n\nfreshword only in v2\n\n" + LOREM + "\n")
    second = run(str(src), "system", tmp_path, config)
    assert first.source_id != second.source_id

    db = tmp_path / "data/derived/wiki/indexes/wiki.sqlite"
    # The old version no longer answers searches; only the new one does.
    assert search(db, "staleword") == []
    fresh_hits = search(db, "freshword")
    assert fresh_hits and {h["source_id"] for h in fresh_hits} == {second.source_id}
    assert {h["source_id"] for h in search(db, "pipeline")} == {second.source_id}


def test_pipeline_dry_run_writes_nothing(tmp_path: Path) -> None:
    config = WikiConfig()
    src = tmp_path / "source.md"
    _write(src, "# Source\n\n" + LOREM + "\n")

    result = run(str(src), "system", tmp_path, config, write=False)
    assert result.chunk_count > 0  # computed in memory
    assert result.manifest_path is None  # but not written
    assert result.chunks_path is None
    assert result.score_event_id is None
    assert not (tmp_path / "data/derived/wiki/chunks").exists()


def test_stream_cursor_written_only_after_durable_writes(tmp_path: Path) -> None:
    """F8: with a --stream id, the cursor lands ONLY after every durable write,
    and a dry-run writes NO cursor (nothing durable happened)."""
    from wiki_core.paths import WikiPaths
    from wiki_core.source_state import read_state, stream_cursor

    config = WikiConfig(repo_id="acme-wiki", owner_label="Alex Doe")
    src = tmp_path / "source.md"
    _write(src, "# Source\n\n" + LOREM + "\n")
    paths = WikiPaths(tmp_path, config)

    # Dry run: nothing durable => no cursor.
    dry = run(str(src), "system", tmp_path, config, write=False, stream_id="#financeiro", ts="2026-07-03T00:00:00Z")
    assert dry.stream_cursor_written is False
    assert read_state(paths.source_state, dry.source_id)["streams"] == {}

    # Real run: cursor written after the event, keyed by the stream id.
    result = run(str(src), "system", tmp_path, config, stream_id="#financeiro", ts="2026-07-03T00:00:00Z")
    assert result.stream_cursor_written is True
    cursor = stream_cursor(read_state(paths.source_state, result.source_id), "#financeiro")
    assert cursor["updated_at"] == "2026-07-03"
    assert cursor["last_unit"]  # a real chunk id


def test_no_stream_id_leaves_cursor_state_untouched(tmp_path: Path) -> None:
    from wiki_core.paths import WikiPaths

    config = WikiConfig(repo_id="acme-wiki", owner_label="Alex Doe")
    src = tmp_path / "source.md"
    _write(src, "# Source\n\n" + LOREM + "\n")
    result = run(str(src), "system", tmp_path, config)
    assert result.stream_cursor_written is False
    assert not (WikiPaths(tmp_path, config).source_state).exists()
