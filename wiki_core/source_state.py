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
        **stream_cursor(state, stream_id),
        "cursor": cursor,
        "last_unit": last_unit,
        "updated_at": updated_at,
    }
    file = _state_file(state_root, source_id)
    tmp = file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(file)
    return state


def merge_review_requests(state: dict, stream_id: str, requests: list[dict]) -> dict:
    """Coalesce information obligations in the existing stream cursor state.

    This pure merge performs no fetch and no factual acknowledgement. Discovery
    or a successful script cannot clear a review request. Callers persist this
    through the source-state writer under their existing mutation authority.
    """
    import copy
    import hashlib
    merged = copy.deepcopy(state)
    streams = merged.setdefault('streams', {})
    stream = streams.setdefault(stream_id, {})
    current = {r['request_id']: r for r in stream.get('review_requests', [])}
    projected = {}
    for request in requests:
        if (not isinstance(request, dict)
                or set(request) != {'scope', 'fields', 'consumer', 'condition', 'priority'}
                or not all(isinstance(request[k], str) and request[k] for k in ('scope','consumer','condition'))
                or not isinstance(request['fields'], list) or not request['fields']
                or any(not isinstance(f, str) or not f for f in request['fields'])
                or request['priority'] not in {'immediate','active','on_demand'}):
            raise ValueError('invalid source review request')
        fields = sorted(set(request['fields']))
        key = hashlib.sha256(json.dumps([merged['source_id'], stream_id, request['scope'], fields],
                                       separators=(',', ':')).encode()).hexdigest()
        previous = current.get(key, {})
        active = projected.get(key, {})
        consumers = sorted(set(active.get('consumers', [])) | {request['consumer']})
        conditions = sorted(set(active.get('conditions', [])) | {request['condition']})
        order = {'immediate':0,'active':1,'on_demand':2}
        priority = min([request['priority'],active.get('priority',request['priority'])],key=order.get)
        fulfilled = {a.get('condition') for a in previous.get('attempts', []) if a.get('status') == 'verified'}
        if previous.get('status') == 'verified':
            fulfilled.update(previous.get('conditions', []))
        status = 'verified' if set(conditions) <= fulfilled else 'review_pending'
        if status != 'verified' and conditions and all(any(a.get('condition') == c and a.get('status') == 'blocked' for a in previous.get('attempts', [])) for c in conditions):
            status = 'blocked'
        projected[key] = {**previous, 'request_id':key,'scope':request['scope'],'fields':fields,
                        'consumers':consumers,'conditions':conditions,'priority':priority,
                        'status':status}
    # The input is the complete active projection for this source/stream.
    # Retain attempt history, but do not keep closed consumers urgent forever.
    for key, previous in current.items():
        if key not in projected:
            projected[key] = {**previous, 'consumers': [], 'conditions': [],
                              'priority': 'on_demand', 'status': 'inactive'}
    current = projected
    stream['review_requests'] = sorted(current.values(),key=lambda r:({'immediate':0,'active':1,'on_demand':2}[r['priority']],r['request_id']))
    return merged


def review_attempt_allowed(request: dict, condition: str, *, max_attempts: int) -> bool:
    """A repeated blocker is not a retry budget; require a changed condition.

    No implicit attempt budget is granted. The existing executor still owns
    credentials, previews, authorization and receipts for the actual work.
    """
    if type(max_attempts) is not int or max_attempts <= 0 or not isinstance(condition,str) or not condition:
        return False
    attempts = request.get('attempts', [])
    return (len(attempts) < max_attempts
            and not any(a.get('condition') == condition and a.get('status') == 'blocked' for a in attempts))
