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
from wiki_core.frontmatter import parse_frontmatter
from wiki_core.paths import WikiPaths
from wiki_core.source_recipe import extract_recipe_mapping, parse_recipe, validate_recipe
from wiki_core.source_state import read_state, stream_cursor

SOURCE_ENTITIES_SCHEMA_VERSION = "wiki_web_source_entities.v1"

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


def _cadence_for(pipelines: list[dict[str, Any]]) -> int:
    """The cadence that governs stream freshness — the content pipeline's, else
    the shortest declared cadence, else 0 (never breaches)."""
    content = [p for p in pipelines if p.get("kind") == "content"]
    pool = content or pipelines
    days = [int(p.get("cadence_days") or 0) for p in pool if int(p.get("cadence_days") or 0) > 0]
    return min(days) if days else 0


def _source_record(
    root: Path,
    paths: WikiPaths,
    page_path: Path,
    today: dt.date,
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
    config_path = (root / config_ref) if config_ref else None
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
    for stream in recipe_json.get("streams") or []:
        if not stream.get("selected", True):
            streams_out.append({**stream, "cursor_age_days": None, "cadence_days": cadence, "breached": False})
            continue
        cursor = stream_cursor(state, str(stream.get("id") or ""))
        age = _iso_days_ago(str(cursor.get("updated_at") or cursor.get("cursor") or ""), today)
        breached = bool(cadence and (age is None or age > cadence))
        if breached:
            pending += 1
        streams_out.append(
            {**stream, "cursor_age_days": age, "cadence_days": cadence, "breached": breached}
        )

    selected_total = sum(1 for s in streams_out if s.get("selected", True))
    fresh = sum(1 for s in streams_out if s.get("selected", True) and not s.get("breached"))

    last_status = str(sync.get("last_status") or "never")
    if last_status not in _SYNC_STATES:
        last_status = "never"

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
            "last_run_at": str(sync.get("last_run_at") or ""),
            "last_status": last_status,
            "last_event_ref": str(sync.get("last_event_ref") or ""),
            "streams_fresh": fresh,
            "streams_total": selected_total,
        },
        "recipe_ok": bool(recipe_json) and not recipe_errors,
        "recipe_errors": recipe_errors,
        "how_to_export": recipe_json.get("how_to_export") or "",
        "pipelines": pipelines,
        "streams": streams_out,
        "pending_streams": pending,
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
    records: list[dict[str, Any]] = []
    if sources_dir.exists():
        for path in sorted(sources_dir.rglob("*.md")):
            if "/config/" in paths.rel(path):
                continue
            record = _source_record(root, paths, path, today)
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
    intent_lines = [
        f"Ingest the source `{source_id}` ({source['platform']} · {source['locator']}).",
        f"Streams to refresh (past cadence): {channels}.",
        source["how_to_export"] and f"How to export:\n{source['how_to_export']}" or "",
        "Run the deterministic ingestion pipeline; each stream's cursor is written "
        "only after its event commits. Do not weaken privacy on any stream.",
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
