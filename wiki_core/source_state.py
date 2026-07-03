"""Per-source incremental cursor state — the Singer STATE analogue.

Cursors live here, in a mutable derived artifact, NEVER in the versioned source
config (F7). The write-timing invariant (F8) is enforced by the caller: a
stream's cursor is committed ONLY after its manifest + normalized event are
durably written, trading duplicates (deduped by manifest sha) over silent loss.
This module gives that caller an atomic, per-source read/update/write API.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _state_file(state_root: Path, source_id: str) -> Path:
    safe = source_id.replace("/", "_").replace("..", "_")
    return state_root / f"{safe}.json"


def read_state(state_root: Path, source_id: str) -> dict[str, Any]:
    """Return the source's state ({"streams": {stream_id: {...}}}), or an empty
    skeleton. Never raises on a missing/corrupt file — a lost cursor means a
    full re-read, which the manifest dedup makes safe."""
    file = _state_file(state_root, source_id)
    if not file.is_file():
        return {"schema_version": "wiki_source_state.v1", "source_id": source_id, "streams": {}}
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"schema_version": "wiki_source_state.v1", "source_id": source_id, "streams": {}}
    if not isinstance(data, dict):
        return {"schema_version": "wiki_source_state.v1", "source_id": source_id, "streams": {}}
    data.setdefault("streams", {})
    return data


def stream_cursor(state: dict[str, Any], stream_id: str) -> dict[str, Any]:
    streams = state.get("streams") or {}
    entry = streams.get(stream_id)
    return dict(entry) if isinstance(entry, dict) else {}


def write_stream_cursor(
    state_root: Path,
    source_id: str,
    stream_id: str,
    cursor: str,
    *,
    last_unit: str = "",
    updated_at: str = "",
) -> dict[str, Any]:
    """Persist a stream's cursor. The CALLER must invoke this only AFTER the
    ingested data for that cursor is durably committed (F8). Atomic write via a
    temp file + replace so a crash never leaves a half-written state."""
    state_root.mkdir(parents=True, exist_ok=True)
    state = read_state(state_root, source_id)
    state["streams"][stream_id] = {
        "cursor": cursor,
        "last_unit": last_unit,
        "updated_at": updated_at,
    }
    file = _state_file(state_root, source_id)
    tmp = file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(file)
    return state
