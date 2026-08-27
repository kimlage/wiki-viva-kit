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
import re
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

from wiki_core.config import WikiConfig
from wiki_core.frontmatter import parse_frontmatter
from wiki_core.paths import WikiPaths
from wiki_core.source_recipe import extract_recipe_mapping, parse_recipe, validate_recipe
from wiki_core.source_state import read_state, stream_cursor
from wiki_core.web.source_groups import build_source_groups_payload

SOURCE_ENTITIES_SCHEMA_VERSION = "wiki_web_source_entities.v1"
SOURCE_ICON_PREFIX = "/source-icons/"
SOURCE_ICON_EXTENSIONS = {".avif", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}

_SYNC_STATES = {"ok", "partial", "failed", "running", "queued", "never"}


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


def _visual_identity(values: dict[str, Any]) -> dict[str, str] | None:
    """Project a portable, local-only source brand declaration."""
    raw = values.get("visual_identity")
    if not isinstance(raw, dict):
        return None
    key = str(raw.get("key") or "").strip().lower()
    label = str(raw.get("label") or "").strip()
    asset_path = str(raw.get("asset_path") or "").strip()
    background = str(raw.get("background") or "transparent").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", key):
        return None
    if not label or len(label) > 80 or any(ord(char) < 32 for char in label):
        return None
    if not asset_path.startswith(SOURCE_ICON_PREFIX) or "\\" in asset_path:
        return None
    relative = asset_path.removeprefix("/")
    parsed = PurePosixPath(relative)
    if parsed.as_posix() != relative or ".." in parsed.parts or parsed.suffix.lower() not in SOURCE_ICON_EXTENSIONS:
        return None
    if background not in {"transparent", "light", "dark"}:
        return None
    return {
        "key": key,
        "label": label,
        "asset_path": asset_path,
        "background": background,
    }


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


def _ingestion_events_index(paths: WikiPaths) -> dict[str, dict[str, str]]:
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
            current = index.get(source_id)
            if current is None or when > current["date"]:
                index[source_id] = {"date": when, "event": paths.rel(path)}
    return index


def _source_record(
    root: Path,
    paths: WikiPaths,
    page_path: Path,
    today: dt.date,
    events_index: dict[str, dict[str, str]] | None = None,
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

    # Versioned sync evidence is the clean-clone fallback. Cursor state is a
    # mutable derived cache and therefore may be absent after clone/deploy. For
    # a source with exactly ONE selected stream, an explicit successful sync
    # receipt can safely establish that stream's freshness. Multi-stream
    # sources still require individual cursors; one source-level date cannot
    # prove which subset was processed.
    last_status = str(sync.get("last_status") or "never")
    if last_status not in _SYNC_STATES:
        last_status = "never"
    last_run_at = str(sync.get("last_run_at") or "")
    last_event_ref = str(sync.get("last_event_ref") or "")
    sync_derived = False
    if last_status == "never" and events_index:
        derived = events_index.get(source_id)
        if derived and derived["date"]:
            last_status = (
                "partial"
                if str(values.get("ingestion_state") or "") == "partial"
                else "ok"
            )
            last_run_at = last_run_at or derived["date"]
            last_event_ref = last_event_ref or derived["event"]
            sync_derived = True
    # Assisted migration sometimes seeded sync=never even though the source
    # already carried a versioned ingestion timestamp. That authored history is
    # evidence of a completed ingestion and must outrank the empty seed.
    authored_ingested_at = str(values.get("last_ingested_at") or "").strip()
    evidenced_status = (
        "partial" if str(values.get("ingestion_state") or "") == "partial" else "ok"
    )
    if last_status == "never" and authored_ingested_at:
        last_status = evidenced_status
        last_run_at = authored_ingested_at
        sync_derived = True

    state = read_state(paths.source_state, source_id)
    versioned_streams = sync.get("streams") if isinstance(sync.get("streams"), dict) else {}
    pipelines = recipe_json.get("pipelines") or []
    cadence = _cadence_for(pipelines)
    schedule = recipe_json.get("schedule") or None
    schedule_mode = str(schedule.get("mode") or "") if isinstance(schedule, dict) else ""
    time_based_freshness = schedule_mode == "recurring"
    # A shared recipe may govern multiple source pages. A stream scoped with
    # filters.source_ref belongs only to that source; unscoped streams remain
    # visible for backwards compatibility.
    source_streams = [
        stream for stream in recipe_json.get("streams") or []
        if not str((stream.get("filters") or {}).get("source_ref") or "")
        or str((stream.get("filters") or {}).get("source_ref")) == source_id
    ]
    selected_stream_count = sum(1 for stream in source_streams if stream.get("selected", True))

    streams_out: list[dict[str, Any]] = []
    pending = 0
    newest_age: int | None = None
    for stream in source_streams:
        # A per-stream cadence_days > 0 overrides the pipeline cadence.
        stream_cadence = _int_or_zero(stream.get("cadence_days")) or cadence
        if not stream.get("selected", True):
            streams_out.append({
                **stream,
                "cursor_age_days": None,
                "freshness_basis": "not_selected",
                "cadence_days": stream_cadence,
                "breached": False,
            })
            continue
        stream_id = str(stream.get("id") or "")
        cursor = stream_cursor(state, stream_id)
        # Freshness comes from `updated_at` (a real ISO date). The `cursor` token
        # is an opaque sha/id, NOT a date — never parse it as one.
        age = _iso_days_ago(str(cursor.get("updated_at") or ""), today)
        freshness_basis = "stream_cursor"
        if age is None:
            receipt = versioned_streams.get(stream_id)
            if isinstance(receipt, dict) and str(receipt.get("last_status") or "never") == "ok":
                age = _iso_days_ago(
                    str(receipt.get("last_run_at") or receipt.get("updated_at") or ""),
                    today,
                )
                freshness_basis = "versioned_stream_receipt"
        if age is None and selected_stream_count == 1 and last_status == "ok":
            age = _iso_days_ago(last_run_at or str(values.get("last_ingested_at") or ""), today)
            if age is not None:
                # Keep the public v1 read-model label stable while adopting the
                # newer per-stream receipt semantics additively.
                freshness_basis = "versioned_source_sync"
        # Only recurring sources age into an overdue state. A one-shot source is
        # complete after capture; on-demand and event-driven sources wait for a
        # trigger and must never become stale merely because time passed.
        processing_state = str((stream.get("filters") or {}).get("processing_state") or "").lower()
        workflow_pending = processing_state in {"discovered", "changed", "pending", "queued"}
        breached = workflow_pending or bool(time_based_freshness and stream_cadence and (age is None or age > stream_cadence))
        if workflow_pending:
            freshness_basis = "processing_state"
        if breached:
            pending += 1
        if age is not None and (newest_age is None or age < newest_age):
            newest_age = age
        streams_out.append(
            {
                **stream,
                "cursor_age_days": age,
                "freshness_basis": freshness_basis if workflow_pending or time_based_freshness else f"schedule_{schedule_mode or 'unconfigured'}",
                "cadence_days": stream_cadence,
                "breached": breached,
            }
        )

    # next_due_days: from the schedule cadence (if recurring) vs the freshest
    # cursor; None when no schedule or nothing has synced yet.
    next_due_days: int | None = None
    if schedule_mode == "recurring" and isinstance(schedule, dict) and _int_or_zero(schedule.get("cadence_days")) > 0 and newest_age is not None:
        next_due_days = _int_or_zero(schedule.get("cadence_days")) - newest_age

    selected_total = sum(1 for s in streams_out if s.get("selected", True))
    fresh = sum(1 for s in streams_out if s.get("selected", True) and not s.get("breached"))

    refresh_argv = ((recipe_json.get("refresh") or {}).get("argv") or []) if recipe_json else []
    ingest = (recipe_json.get("ingest") or {}) if recipe_json else {}
    ingest_argv = ingest.get("argv") or []
    mcp_hint = str(ingest.get("mcp_hint") or "")
    update_mode = (
        "deterministic_connector"
        if refresh_argv
        else "script"
        if ingest_argv
        else "agent_connector"
        if mcp_hint
        else "manual_export"
    )

    return {
        "source_id": source_id,
        "path": rel,
        "title": str(values.get("title") or source_id),
        "context": str(values.get("context") or ""),
        "platform": str(values.get("platform") or recipe_json.get("platform") or ""),
        "locator": str(values.get("source_locator") or recipe_json.get("locator") or ""),
        "source_kind": str(recipe_json.get("source_kind") or ""),
        **({"visual_identity": identity} if (identity := _visual_identity(values)) else {}),
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
        },
        "recipe_ok": bool(recipe_json) and not recipe_errors,
        "recipe_errors": recipe_errors,
        "how_to_export": recipe_json.get("how_to_export") or "",
        # Safe operational summary for the cockpit. Commands remain available
        # only through the governed preview; this projection exposes no secret.
        "update_route": {
            "mode": update_mode,
            "mcp_hint": mcp_hint,
            "runnable": update_mode in {"script", "deterministic_connector"},
            "requires_agent": update_mode == "agent_connector",
        },
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
    grouping = build_source_groups_payload(root, config, records)
    return {
        "schema_version": SOURCE_ENTITIES_SCHEMA_VERSION,
        "sources": records,
        "source_groups": grouping,
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
        "Run the deterministic ingestion pipeline; its derived stream cursor is a "
        "processing checkpoint, while the closed ingestion event + versioned source "
        "sync receipt prove canonical completion. Do not weaken privacy on any stream.",
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
