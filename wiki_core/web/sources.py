"""Source entity read model + brief composer for the cockpit's Fontes surface.

Reads the true source-of-truth — source pages (identity + machine `sync` block),
their `source_config` recipes (platform/pipelines/streams), and the per-source
cursor state — and rolls them into `source_entities.json` v2: one rich record
per source with sync telemetry and per-stream freshness vs its cadence. Also
composes an ingestion brief for a source's stale streams (the agent's executable
manual becomes the grounding).

Mirrors the shape of gates.py/diff.py/intake.py: a schema constant, a public
builder, and a public action fn — no side effects in the builder.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from wiki_core.config import WikiConfig
from wiki_core.frontmatter import list_values, parse_frontmatter
from wiki_core.paths import WikiPaths
from wiki_core.source_recipe import extract_recipe_mapping, parse_recipe, validate_recipe
from wiki_core.source_state import read_state, stream_cursor

SOURCE_ENTITIES_SCHEMA_VERSION = "wiki_web_source_entities.v1"

_SYNC_STATES = {
    "ok",
    "partial",
    "failed",
    "needs_auth",
    "parser_error",
    "secret_blocked",
    "running",
    "queued",
    "never",
}


def _iso_days_ago(value: str, today: dt.date) -> int | None:
    """Whole days between an ISO date/datetime and today; None if unparseable."""
    if not value:
        return None
    head = str(value).strip()[:10]
    try:
        when = dt.date.fromisoformat(head)
    except ValueError:
        return None
    return (today - when).days


def _int_or_zero(value: Any) -> int:
    """Coerce a cadence_days-like value to a non-negative int; 0 on garbage.
    A hand-authored recipe can carry a non-numeric cadence — it must never crash
    the read model or the /brief endpoint."""
    try:
        return max(int(str(value).strip()), 0)
    except (TypeError, ValueError):
        return 0


def _cadence_for(pipelines: list[dict[str, Any]]) -> int:
    """The cadence that governs stream freshness — the content pipeline's, else
    the shortest declared cadence, else 0 (never breaches)."""
    content = [p for p in pipelines if p.get("kind") == "content"]
    pool = content or pipelines
    days = [d for p in pool if (d := _int_or_zero(p.get("cadence_days"))) > 0]
    return min(days) if days else 0


def _contained(root: Path, rel: str) -> Path | None:
    """Resolve a repo-relative reference and REFUSE anything that escapes the
    repo root (``../`` or an absolute path). Prevents a hand-authored
    ``config_ref`` from reading an arbitrary file off disk into the read model."""
    candidate = Path(rel)
    if candidate.is_absolute():
        return None
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return None
    return resolved


def _ingestion_events_index(paths: WikiPaths) -> dict[str, dict[str, Any]]:
    """The wiki's OWN record of syncs: the newest ingestion event per source.

    A source page's `sync:` block is the machine-updated telemetry — but a wiki
    whose content was born by ingestion has EVENTS referencing each source
    (`source_refs:`), and "never synced" next to those events would be a lie.
    This index lets the read model fall back to the newest event when the sync
    block is absent or still says `never`."""
    index: dict[str, dict[str, str]] = {}
    memory_root = paths.memory_root
    if not memory_root.exists():
        return index
    for path in memory_root.rglob("*.md"):
        try:
            values, _ = parse_frontmatter(path)
        except Exception:  # noqa: BLE001 — one broken page must not kill the read model
            continue
        if str(values.get("page_type") or "") != "ingestion_event":
            continue
        when = str(values.get("updated_at") or "")
        refs = values.get("source_refs") if isinstance(values.get("source_refs"), list) else []
        for ref in refs:
            source_id = str(ref)
            closure = values.get("impact_closure") if isinstance(values.get("impact_closure"), dict) else {}
            consolidated_into = list_values(values.get("consolidated_into"))
            no_change = list_values(closure.get("no_change"))
            current = index.get(source_id)
            if current is None or when > current["date"]:
                index[source_id] = {
                    "date": when,
                    "event": paths.rel(path),
                    "consolidated_into": consolidated_into,
                    "reviewed_no_change": bool(no_change),
                    "no_change": no_change,
                    "gate_state": str(values.get("gate_state") or values.get("status") or ""),
                }
    return index


def _source_record(
    root: Path,
    paths: WikiPaths,
    page_path: Path,
    today: dt.date,
    events_index: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    values, _ = parse_frontmatter(page_path)
    if str(values.get("page_type") or "") != "source":
        return None
    rel = paths.rel(page_path)
    source_id = str(values.get("page_id") or rel)
    sync = values.get("sync") if isinstance(values.get("sync"), dict) else {}
    stewards = values.get("stewards") if isinstance(values.get("stewards"), list) else []

    # Recipe (from the config page it points to, or a co-located config).
    recipe_json: dict[str, Any] = {}
    recipe_errors: list[str] = []
    config_ref = str(values.get("config_ref") or "").strip()
    config_path = _contained(root, config_ref) if config_ref else None
    if config_path is not None and config_path.is_file():
        mapping = extract_recipe_mapping(config_path.read_text(encoding="utf-8"))
        if mapping is not None:
            recipe = parse_recipe(mapping)
            recipe_errors = validate_recipe(recipe)
            recipe_json = recipe.to_json()

    state = read_state(paths.source_state, source_id)
    pipelines = recipe_json.get("pipelines") or []
    cadence = _cadence_for(pipelines)

    streams_out: list[dict[str, Any]] = []
    pending = 0
    newest_age: int | None = None
    for stream in recipe_json.get("streams") or []:
        # A per-stream cadence_days > 0 overrides the pipeline cadence.
        stream_cadence = _int_or_zero(stream.get("cadence_days")) or cadence
        if not stream.get("selected", True):
            streams_out.append({**stream, "cursor_age_days": None, "cadence_days": stream_cadence, "breached": False})
            continue
        cursor = stream_cursor(state, str(stream.get("id") or ""))
        # Freshness comes from `updated_at` (a real ISO date). The `cursor` token
        # is an opaque sha/id, NOT a date — never parse it as one.
        age = _iso_days_ago(str(cursor.get("updated_at") or ""), today)
        breached = bool(stream_cadence and (age is None or age > stream_cadence))
        if breached:
            pending += 1
        if age is not None and (newest_age is None or age < newest_age):
            newest_age = age
        streams_out.append(
            {**stream, "cursor_age_days": age, "cadence_days": stream_cadence, "breached": breached}
        )

    # next_due_days: from the schedule cadence (if recurring) vs the freshest
    # cursor; None when no schedule or nothing has synced yet.
    schedule = recipe_json.get("schedule") or None
    next_due_days: int | None = None
    if isinstance(schedule, dict) and _int_or_zero(schedule.get("cadence_days")) > 0 and newest_age is not None:
        next_due_days = _int_or_zero(schedule.get("cadence_days")) - newest_age

    selected_total = sum(1 for s in streams_out if s.get("selected", True))
    fresh = sum(1 for s in streams_out if s.get("selected", True) and not s.get("breached"))

    last_status = str(sync.get("last_status") or "never")
    if last_status not in _SYNC_STATES:
        last_status = "never"
    last_run_at = str(sync.get("last_run_at") or "")
    last_event_ref = str(sync.get("last_event_ref") or "")
    sync_derived = False
    if last_status == "never" and events_index:
        # The wiki itself remembers this source being ingested — the newest
        # ingestion event outranks a missing/never sync block.
        derived = events_index.get(source_id)
        if derived and derived["date"]:
            last_status = "ok"
            last_run_at = last_run_at or derived["date"]
            last_event_ref = last_event_ref or derived["event"]
            sync_derived = True

    event_closure = dict((events_index or {}).get(source_id) or {})
    lifecycle_values = values.get("source_lifecycle") if isinstance(values.get("source_lifecycle"), dict) else {}
    pipeline_timestamps = lifecycle_values.get("pipeline_stage_timestamps")
    if not isinstance(pipeline_timestamps, dict):
        pipeline_timestamps = {}

    def lifecycle_value(key: str, fallback: Any = "") -> Any:
        direct = values.get(f"source_{key}")
        if direct not in (None, "", []):
            return direct
        return lifecycle_values.get(key, fallback)

    return {
        "source_id": source_id,
        "path": rel,
        "title": str(values.get("title") or source_id),
        "context": str(values.get("context") or ""),
        "platform": str(values.get("platform") or recipe_json.get("platform") or ""),
        "locator": str(values.get("source_locator") or recipe_json.get("locator") or ""),
        "owner": str(values.get("owner") or ""),
        "stewards": [s for s in stewards if isinstance(s, dict)],
        "config_ref": config_ref,
        "updated_at": str(values.get("updated_at") or ""),
        "sync": {
            "last_run_at": last_run_at,
            "last_status": last_status,
            "last_event_ref": last_event_ref,
            # True when the status was derived from the newest ingestion event
            # (no machine sync block yet) — the UI can say so honestly.
            "derived_from_event": sync_derived,
            "streams_fresh": fresh,
            "streams_total": selected_total,
            "event_closure": {
                "consolidated_into": list(event_closure.get("consolidated_into") or []),
                "reviewed_no_change": bool(event_closure.get("reviewed_no_change")),
                "no_change": list(event_closure.get("no_change") or []),
                "gate_state": str(event_closure.get("gate_state") or ""),
            },
        },
        "lifecycle": {
            "state": str(lifecycle_values.get("state") or lifecycle_value("lifecycle_state") or values.get("lifecycle_state") or ""),
            "freshness_state": str(lifecycle_value("freshness_state") or ""),
            "last_attempt_state": str(lifecycle_value("last_attempt_state") or ""),
            "pipeline_stage": str(lifecycle_value("pipeline_stage") or ""),
            "pipeline_stage_timestamps": {str(k): str(v) for k, v in pipeline_timestamps.items()},
            "adoption_state": str(lifecycle_value("adoption_state") or values.get("ingestion_state") or ""),
            "last_sync_success_at": str(lifecycle_value("last_sync_success_at") or ""),
            "last_ingested_at": str(lifecycle_value("last_ingested_at") or values.get("last_ingested_at") or ""),
            "last_attempt_at": str(lifecycle_value("last_attempt_at") or ""),
            "emitted_page_ids": list_values(lifecycle_value("emitted_page_ids", [])),
            "emitted_action_ids": list_values(lifecycle_value("emitted_action_ids", [])),
            "proposal_ids": list_values(lifecycle_value("proposal_ids", [])),
            "raw_artifact_count": _int_or_zero(lifecycle_value("raw_artifact_count", 0)),
            "secret_safe_log_refs": list_values(lifecycle_value("secret_safe_log_refs", [])),
            "reviewed_no_change_receipt": str(lifecycle_value("reviewed_no_change_receipt") or ""),
            "accepted_ref": str(lifecycle_value("accepted_ref") or ""),
        },
        "recipe_ok": bool(recipe_json) and not recipe_errors,
        "recipe_errors": recipe_errors,
        "how_to_export": recipe_json.get("how_to_export") or "",
        "pipelines": pipelines,
        "streams": streams_out,
        "pending_streams": pending,
        # Rich config (v2): the auth POINTER (never a value), the sync schedule,
        # and days until the next scheduled sync (negative = overdue).
        "auth": recipe_json.get("auth") or None,
        "schedule": recipe_json.get("schedule") or None,
        "next_due_days": next_due_days,
    }


def build_sources_payload(
    root: Path,
    config: WikiConfig,
    *,
    today: dt.date | None = None,
) -> dict[str, Any]:
    """Rich per-source read model. Reads source pages + recipes + cursor state
    (never the raw manifests — those stay in ingestion.json)."""
    today = today or dt.date.today()
    paths = WikiPaths(root, config)
    sources_dir = paths.sources_dir
    events_index = _ingestion_events_index(paths)
    records: list[dict[str, Any]] = []
    if sources_dir.exists():
        for path in sorted(sources_dir.rglob("*.md")):
            if "/config/" in paths.rel(path):
                continue
            record = _source_record(root, paths, path, today, events_index)
            if record is not None:
                records.append(record)
    records.sort(key=lambda r: (-r["pending_streams"], r["source_id"]))
    return {
        "schema_version": SOURCE_ENTITIES_SCHEMA_VERSION,
        "sources": records,
        "summary": {
            "total": len(records),
            "with_recipe": sum(1 for r in records if r["recipe_ok"]),
            "pending": sum(r["pending_streams"] for r in records),
        },
    }


def compose_source_brief_spec(
    root: Path,
    config: WikiConfig,
    source_id: str,
    *,
    today: dt.date | None = None,
) -> dict[str, Any]:
    """Build a BriefSpec that ingests a source's stale/selected streams. The
    recipe (channels, filters, export manual, targets) becomes the grounding —
    the agent never rediscovers context. Returns {ok, spec} or {ok:false}."""
    payload = build_sources_payload(root, config, today=today)
    source = next((s for s in payload["sources"] if s["source_id"] == source_id), None)
    if source is None:
        return {"ok": False, "error": f"unknown source `{source_id}`"}
    stale = [s for s in source["streams"] if s.get("selected", True) and s.get("breached")]
    targets = sorted({t for s in stale for t in (s.get("target_pages") or [])})
    channels = ", ".join(s["id"] for s in stale) or "all selected streams"
    # Per-stream filter detail so the agent ingests exactly the declared slice.
    filter_lines = [
        f"  - {s['id']}: " + (", ".join(f"{k}={v}" for k, v in (s.get("filters") or {}).items()) or "no filters")
        + (f" → {', '.join(s['target_pages'])}" if s.get("target_pages") else "")
        for s in stale
    ]
    auth = source.get("auth") or None
    auth_line = ""
    if isinstance(auth, dict) and auth.get("method") and auth.get("method") != "none":
        scopes = ", ".join(auth.get("scopes") or [])
        auth_line = (
            f"Auth: read the credential from {auth['method']} `{auth.get('ref', '')}`"
            + (f" (scopes: {scopes})" if scopes else "")
            + ". If it is absent, STOP and report — do NOT proceed unauthenticated."
        )
    intent_lines = [
        f"Ingest the source `{source_id}` ({source['platform']} · {source['locator']}).",
        f"Streams to refresh (past cadence): {channels}.",
        filter_lines and "Per-stream slice:\n" + "\n".join(filter_lines) or "",
        auth_line,
        source["how_to_export"] and f"How to export:\n{source['how_to_export']}" or "",
        # The single honesty line: the sandbox cannot reach the network.
        "NETWORK IS OFF in the sandbox — do NOT attempt a live fetch. Ingest the "
        "already-exported RAW at the export location above; if it is missing, STOP "
        "and report what to export.",
        "Run the deterministic ingestion pipeline; each stream's cursor is written "
        "only after its event commits (F8). Do not weaken privacy on any stream.",
    ]
    spec = {
        "mission_kind": "ingest",
        "theme": f"ingest-{source_id}",
        "grounding": {
            "source": {"path": source["config_ref"] or source["path"], "context": source["context"]},
            "page_ids": targets,
            "attach_context_package": True,
        },
        "intent": "\n\n".join(line for line in intent_lines if line),
    }
    return {"ok": True, "spec": spec, "pending": len(stale)}
