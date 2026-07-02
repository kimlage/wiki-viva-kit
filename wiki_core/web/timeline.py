from __future__ import annotations

import datetime as dt
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from wiki_core.config import WikiConfig
from wiki_core.web.schemas import WEB_TIMELINE_SCHEMA_VERSION


def _to_utc_iso(raw: str) -> str | None:
    value = str(raw or "").strip()
    if not value:
        return None
    try:
        if "T" in value:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            parsed = dt.datetime.combine(dt.date.fromisoformat(value[:10]), dt.time.min)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _event_date(timestamp: str) -> dt.date | None:
    try:
        return dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _git_log_events(root: Path, *, max_count: int = 18) -> list[dict[str, Any]]:
    try:
        proc = subprocess.run(
            [
                "git",
                "log",
                f"--max-count={max_count}",
                "--date=iso-strict",
                "--pretty=format:%H%x1f%aI%x1f%s",
            ],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    events: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        parts = line.split("\x1f", 2)
        if len(parts) != 3:
            continue
        commit, authored_at, subject = parts
        timestamp = _to_utc_iso(authored_at)
        if not timestamp:
            continue
        events.append(
            {
                "id": f"git-{commit[:12]}",
                "kind": "git_commit",
                "timestamp": timestamp,
                "label": subject[:160],
                "context": "git",
                "path": "",
                "status": "committed",
                "weight": 2,
                "commit": commit[:12],
            }
        )
    return events


def _band_counts(events: list[dict[str, Any]], generated_at: str) -> dict[str, int]:
    today = _event_date(generated_at) or dt.datetime.now(dt.timezone.utc).date()
    bands = {"last_7_days": 0, "last_30_days": 0, "older": 0, "undated": 0}
    for event in events:
        timestamp = str(event.get("timestamp") or "")
        event_date = _event_date(timestamp)
        if event_date is None:
            bands["undated"] += 1
            continue
        age = (today - event_date).days
        if age <= 7:
            bands["last_7_days"] += 1
        elif age <= 30:
            bands["last_30_days"] += 1
        else:
            bands["older"] += 1
    return bands


def build_timeline_payload(
    root: Path,
    config: WikiConfig,
    pages_payload: dict[str, Any],
    operations_payload: dict[str, Any],
    git_payload: dict[str, Any],
    *,
    generated_at: str,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = [
        {
            "id": "snapshot-generated",
            "kind": "snapshot",
            "timestamp": generated_at,
            "label": "Snapshot generated",
            "context": "system",
            "path": "",
            "status": str(git_payload.get("proposal", {}).get("human_gate_state") or ""),
            "weight": 1,
            "commit": "",
        }
    ]

    operation_time = _to_utc_iso(str(operations_payload.get("updated_at") or ""))
    if operation_time:
        events.append(
            {
                "id": "operations-updated",
                "kind": "operations_updated",
                "timestamp": operation_time,
                "label": str(operations_payload.get("title") or "Operations"),
                "context": "system",
                "path": str(operations_payload.get("path") or config.paths["operation_page"]),
                "status": str(operations_payload.get("freshness_state") or "unknown"),
                "weight": 3,
                "commit": "",
            }
        )

    for page in pages_payload.get("pages", []):
        timestamp = _to_utc_iso(str(page.get("updated_at") or ""))
        if not timestamp:
            continue
        freshness = str(page.get("freshness_state") or "unknown")
        events.append(
            {
                "id": f"page-{page.get('id') or page.get('path')}",
                "kind": "page_updated",
                "timestamp": timestamp,
                "label": str(page.get("title") or page.get("path") or "")[:160],
                "context": str(page.get("context") or config.default_context),
                "path": str(page.get("path") or ""),
                "status": freshness,
                "weight": 2 if freshness == "fresh" else 1,
                "commit": "",
            }
        )

    events.extend(_git_log_events(root))
    events.sort(key=lambda item: (str(item.get("timestamp") or ""), str(item.get("id") or "")), reverse=True)

    by_kind = Counter(str(event.get("kind") or "unknown") for event in events)
    by_context = Counter(str(event.get("context") or config.default_context) for event in events)
    timestamps = [str(event.get("timestamp") or "") for event in events if event.get("timestamp")]

    return {
        "schema_version": WEB_TIMELINE_SCHEMA_VERSION,
        "repo_id": config.repo_id,
        "generated_at": generated_at,
        "summary": {
            "event_count": len(events),
            "first_at": min(timestamps) if timestamps else "",
            "last_at": max(timestamps) if timestamps else "",
            "by_kind": dict(sorted(by_kind.items())),
            "by_context": dict(sorted(by_context.items())),
        },
        "bands": _band_counts(events, generated_at),
        "events": events[:160],
    }
