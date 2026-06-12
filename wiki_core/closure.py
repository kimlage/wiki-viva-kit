from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from wiki_core.config import WikiConfig
from wiki_core.graph.page_graph import parse_frontmatter
from wiki_core.paths import WikiPaths

INGESTION_CLOSURE_REPORT_SCHEMA_VERSION = "wiki_ingestion_closure_report.v2"

EVENT_INDEX_FILENAMES = {"readme.md", "index.md"}
FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n?", re.DOTALL)

CANDIDATE_HEADINGS = {
    "claims": {"Claims candidates", "Candidate claims", "Claims candidatos"},
    "decisions": {"Candidate decisions", "Decisoes candidatas", "Decisões candidatas"},
    "actions": {"Candidate actions", "Acoes candidatas", "Ações candidatas"},
}


def _list_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        if not value.strip() or value.strip() == "[]":
            return []
        return [value.strip()]
    return [str(value).strip()]


def _body(path: Path) -> str:
    return FRONTMATTER_RE.sub("", path.read_text(encoding="utf-8", errors="replace"), count=1)


def _event_pages(paths: WikiPaths) -> list[Path]:
    if not paths.ingest_events_dir.exists():
        return []
    return sorted(paths.ingest_events_dir.rglob("*.md"))


def _source_pages(paths: WikiPaths) -> list[Path]:
    if not paths.sources_dir.exists():
        return []
    return sorted(paths.sources_dir.rglob("*.md"))


def _is_ingestion_event_page(path: Path, values: dict[str, Any]) -> bool:
    if path.name.lower() in EVENT_INDEX_FILENAMES:
        return False
    if values.get("page_type") == "ingestion_event":
        return True
    return bool(values.get("event_id") or values.get("source_id"))


def _bullet_count_under_headings(text: str, headings: set[str]) -> int:
    in_section = False
    count = 0
    for line in text.splitlines():
        if line.startswith("## "):
            in_section = line[3:].strip() in headings
            continue
        if in_section and line.startswith("#"):
            in_section = False
        if in_section and line.lstrip().startswith(("- ", "* ")):
            count += 1
    return count


def _candidate_counts(values: dict[str, Any], text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for key, headings in CANDIDATE_HEADINGS.items():
        counts[key] = len(_list_values(values.get(key))) + _bullet_count_under_headings(text, headings)
    return counts


def build_ingestion_closure_report(root: Path, config: WikiConfig) -> dict[str, Any]:
    paths = WikiPaths(root, config)
    events: list[dict[str, Any]] = []
    events_by_source_ref: dict[str, list[str]] = {}
    closed_events_by_source_ref: dict[str, list[str]] = {}
    events_without_consolidated_into: list[str] = []
    consolidated_targets: set[str] = set()
    source_candidate_counts: dict[str, dict[str, int]] = {}
    source_consolidated_targets: dict[str, set[str]] = {}

    for path in _event_pages(paths):
        values = parse_frontmatter(path)
        if not _is_ingestion_event_page(path, values):
            continue
        rel = paths.rel(path)
        text = _body(path)
        consolidated = _list_values(values.get("consolidated_into"))
        source_refs = _list_values(values.get("source_refs"))
        source_refs.extend(_list_values(values.get("source_ref")))
        source_refs.extend(_list_values(values.get("source_id")))
        candidate_counts = _candidate_counts(values, text)
        candidate_total = sum(candidate_counts.values())
        unique_source_refs = sorted(set(source_refs))
        unique_consolidated = sorted(set(consolidated))
        if not consolidated:
            events_without_consolidated_into.append(rel)
        else:
            consolidated_targets.update(unique_consolidated)
        for source_ref in unique_source_refs:
            events_by_source_ref.setdefault(source_ref, []).append(rel)
            counts = source_candidate_counts.setdefault(
                source_ref, {"claims": 0, "decisions": 0, "actions": 0}
            )
            for key, value in candidate_counts.items():
                counts[key] += value
            source_consolidated_targets.setdefault(source_ref, set()).update(unique_consolidated)
            if unique_consolidated:
                closed_events_by_source_ref.setdefault(source_ref, []).append(rel)
        events.append(
            {
                "path": rel,
                "event_id": str(values.get("event_id") or values.get("page_id") or ""),
                "page_type": str(values.get("page_type") or ""),
                "source_refs": unique_source_refs,
                "consolidated_into": unique_consolidated,
                "closed": bool(unique_consolidated),
                "candidate_counts": candidate_counts,
                "candidate_total": candidate_total,
                "consolidated_targets_count": len(unique_consolidated),
                "candidate_units_per_target": round(
                    candidate_total / max(len(unique_consolidated), 1), 2
                ),
            }
        )

    ingested_sources: list[dict[str, Any]] = []
    ingested_sources_without_closed_event: list[str] = []
    for path in _source_pages(paths):
        values = parse_frontmatter(path)
        if values.get("page_type") != "source":
            continue
        if str(values.get("ingestion_state") or "") != "ingested":
            continue
        rel = paths.rel(path)
        page_id = str(values.get("page_id") or "")
        source_keys = [key for key in (page_id, rel) if key]
        matched_event_paths = sorted(
            {
                event_path
                for key in source_keys
                for event_path in events_by_source_ref.get(key, [])
            }
        )
        closed_event_paths = sorted(
            {
                event_path
                for key in source_keys
                for event_path in closed_events_by_source_ref.get(key, [])
            }
        )
        candidate_counts = {"claims": 0, "decisions": 0, "actions": 0}
        targets: set[str] = set()
        for key in source_keys:
            for field, value in source_candidate_counts.get(key, {}).items():
                candidate_counts[field] += value
            targets.update(source_consolidated_targets.get(key, set()))
        matched = bool(closed_event_paths)
        record = {
            "path": rel,
            "page_id": page_id,
            "last_ingested_at": str(values.get("last_ingested_at") or ""),
            "has_closed_event": matched,
            "event_paths": matched_event_paths,
            "closed_event_paths": closed_event_paths,
            "candidate_counts": candidate_counts,
            "candidate_total": sum(candidate_counts.values()),
            "consolidated_targets": sorted(targets),
            "consolidated_targets_count": len(targets),
            "candidate_units_per_target": round(sum(candidate_counts.values()) / max(len(targets), 1), 2),
        }
        ingested_sources.append(record)
        if not matched:
            ingested_sources_without_closed_event.append(rel)

    candidate_claims = sum(event["candidate_counts"]["claims"] for event in events)
    candidate_decisions = sum(event["candidate_counts"]["decisions"] for event in events)
    candidate_actions = sum(event["candidate_counts"]["actions"] for event in events)
    candidate_total = candidate_claims + candidate_decisions + candidate_actions
    return {
        "schema_version": INGESTION_CLOSURE_REPORT_SCHEMA_VERSION,
        "repo_id": config.repo_id,
        "summary": {
            "events_total": len(events),
            "events_closed": len([event for event in events if event["closed"]]),
            "events_without_consolidated_into": len(events_without_consolidated_into),
            "ingested_sources": len(ingested_sources),
            "ingested_sources_without_closed_event": len(ingested_sources_without_closed_event),
            "candidate_claims": candidate_claims,
            "candidate_decisions": candidate_decisions,
            "candidate_actions": candidate_actions,
            "candidate_total": candidate_total,
            "consolidated_targets": len(consolidated_targets),
            "candidate_units_per_target": round(candidate_total / max(len(consolidated_targets), 1), 2),
        },
        "quality_flags": {
            "events_without_consolidated_into": events_without_consolidated_into,
            "ingested_sources_without_closed_event": ingested_sources_without_closed_event,
        },
        "events": events,
        "ingested_sources": ingested_sources,
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Wiki ingestion closure report",
        "",
        f"Schema: `{report['schema_version']}`.",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for key in (
        "events_total",
        "events_closed",
        "events_without_consolidated_into",
        "ingested_sources",
        "ingested_sources_without_closed_event",
        "candidate_claims",
        "candidate_decisions",
        "candidate_actions",
        "candidate_total",
        "consolidated_targets",
        "candidate_units_per_target",
    ):
        lines.append(f"| `{key}` | {summary[key]} |")

    flags = report["quality_flags"]
    lines.extend(["", "## Quality Flags", "", "### Events without consolidated_into", ""])
    if flags["events_without_consolidated_into"]:
        lines.extend(f"- `{path}`" for path in flags["events_without_consolidated_into"])
    else:
        lines.append("- None.")
    lines.extend(["", "### Ingested sources without closed event", ""])
    if flags["ingested_sources_without_closed_event"]:
        lines.extend(f"- `{path}`" for path in flags["ingested_sources_without_closed_event"])
    else:
        lines.append("- None.")
    lines.extend(["", "## Source Compression", ""])
    if report["ingested_sources"]:
        lines.extend(
            [
                "| Source | Events | Closed events | Candidates | Targets | Candidate units/target |",
                "| --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for source in report["ingested_sources"]:
            lines.append(
                f"| `{source['path']}` | {len(source['event_paths'])} | "
                f"{len(source['closed_event_paths'])} | {source['candidate_total']} | "
                f"{source['consolidated_targets_count']} | "
                f"{source['candidate_units_per_target']} |"
            )
    else:
        lines.append("- None.")
    lines.append("")
    return "\n".join(lines)
