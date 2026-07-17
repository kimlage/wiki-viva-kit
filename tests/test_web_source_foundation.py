"""Builder tests for `wiki_web_source_foundation.v1` (plan §19.1).

The builder is pure — every case hand-assembles the already-built read models
it consumes (pages/graph/source entities/lifecycle/events); the secret and
sanitization cases additionally run the REAL `build_sources_payload()` on a
tmp repo so fail-closed behavior is exercised end-to-end.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import subprocess
from pathlib import Path
from typing import Any

import jsonschema
import pytest
import yaml

from wiki_core.config import WikiConfig, load_config
from wiki_core.source_recipe import SOURCE_RECIPE_SAFETY_ERROR_CODE
from wiki_core.web.source_foundation import (
    SOURCE_FOUNDATION_SCHEMA_VERSION,
    build_source_foundation_payload,
)
from wiki_core.web.sources import build_sources_payload

SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs/references/schemas/wiki-web-source-foundation-v1.schema.json"
)
EVENTS_DIR = "memories/system/ingestion/events"
GENERATED_AT = "2026-07-17T00:00:00Z"


# ---------------------------------------------------------------- factories


def _page(page_id: str, **over: Any) -> dict[str, Any]:
    record = {
        "id": page_id,
        "path": f"memories/{page_id}.md",
        "title": page_id,
        "page_type": "note",
        "context": "system",
        "updated_at": "2026-07-01",
        "source_refs": [],
    }
    record.update(over)
    return record


def _stream(stream_id: str, **over: Any) -> dict[str, Any]:
    record = {
        "id": stream_id,
        "label": stream_id,
        "selected": True,
        "filters": {},
        "privacy": "private_self",
        "target_pages": [],
        "skip_reason": "",
        "cadence_days": 7,
        "cursor_age_days": 2,
        "breached": False,
    }
    record.update(over)
    return record


def _source(source_id: str, **over: Any) -> dict[str, Any]:
    record = {
        "source_id": source_id,
        "path": f"memories/sources/{source_id}.md",
        "title": source_id,
        "context": "system",
        "platform": "slack",
        "owner": "person-kim",
        "config_ref": "",
        "sync": {"last_run_at": "2026-07-01T00:00:00Z", "last_status": "ok"},
        "recipe_ok": True,
        "recipe_errors": [],
        "pipelines": [{"kind": "content", "cadence_days": 7}],
        "streams": [],
        "pending_streams": 0,
        "next_due_days": None,
    }
    record.update(over)
    return record


def _bare_source(source_id: str, **over: Any) -> dict[str, Any]:
    """A day-1 source: declared page, no recipe, never synced."""
    return _source(
        source_id,
        recipe_ok=False,
        pipelines=[],
        streams=[],
        sync={"last_run_at": "", "last_status": "never"},
        **over,
    )


def _lifecycle(source_id: str, **over: Any) -> dict[str, Any]:
    record = {
        "source_id": source_id,
        "lifecycle_state": "ready",
        "pipeline_stage": "configured",
        "pipeline_stage_timestamps": {},
        "adoption_state": "pending",
    }
    record.update(over)
    return record


def _event(name: str, **values: Any) -> dict[str, Any]:
    merged: dict[str, Any] = {
        "page_type": "ingestion_event",
        "page_id": f"event-{name}",
        "updated_at": "2026-07-02",
    }
    merged.update(values)
    return {"path": f"{EVENTS_DIR}/{name}.md", "values": merged}


def _event_page(name: str) -> dict[str, Any]:
    return _page(
        f"event-{name}",
        path=f"{EVENTS_DIR}/{name}.md",
        page_type="ingestion_event",
    )


def _edge(source: str, target: str, type_: str, **over: Any) -> dict[str, Any]:
    record = {
        "id": f"edge-{source}-{target}-{type_}",
        "source": source,
        "target": target,
        "type": type_,
        "basis": "frontmatter",
        "observed_at": "2026-07-01",
    }
    record.update(over)
    return record


def _build(
    *,
    pages: list[dict[str, Any]] | None = None,
    sources: list[dict[str, Any]] | None = None,
    lifecycle: list[dict[str, Any]] | None = None,
    events: list[dict[str, Any]] | None = None,
    edges: list[dict[str, Any]] | None = None,
    **over: Any,
) -> dict[str, Any]:
    sources = sources or []
    kwargs: dict[str, Any] = {
        "repo_id": "kit-test",
        "revision": "rev-1",
        "generated_at": GENERATED_AT,
        "pages_payload": {"schema_version": "wiki_web_pages.v1", "pages": pages or []},
        "graph_payload": {"schema_version": "wiki_web_graph.v2", "edges": edges or []},
        "source_entities_payload": {
            "schema_version": "wiki_web_source_entities.v1",
            "sources": sources,
        },
        "source_lifecycle_payload": {
            "schema_version": "wiki_source_lifecycle.v2",
            "sources": (
                lifecycle
                if lifecycle is not None
                else [_lifecycle(s["source_id"]) for s in sources]
            ),
        },
        "ingestion_events": events or [],
        "events_dir": EVENTS_DIR,
    }
    kwargs.update(over)
    return build_source_foundation_payload(**kwargs)


def _diags(payload: dict[str, Any], code: str) -> list[dict[str, Any]]:
    return [d for d in payload["diagnostics"] if d["code"] == code]


def _station(payload: dict[str, Any], station_id: str) -> dict[str, Any]:
    return next(s for s in payload["stations"] if s["station_id"] == station_id)


# ------------------------------------------------------------------- cases


def test_zero_sources_yields_empty_deterministic_topology() -> None:
    payload = _build()
    assert payload["schema_version"] == SOURCE_FOUNDATION_SCHEMA_VERSION
    for key in ("stations", "streams", "pipelines", "emissions", "targets", "diagnostics"):
        assert payload[key] == []
    assert payload["summary"] == {
        "sources": 0,
        "channels": 0,
        "streams": 0,
        "pipelines": 0,
        "emissions": 0,
        "targets": 0,
        "gaps": 0,
        "blocked_sources": 0,
        "pending_streams": 0,
    }
    assert len(payload["topology_sha256"]) == 64
    assert _build()["topology_sha256"] == payload["topology_sha256"]


def test_source_without_recipe_is_missing_with_diagnostic() -> None:
    payload = _build(sources=[_bare_source("src-a")])
    station = _station(payload, "station:src-a")
    assert station["recipe_state"] == "missing"
    assert "source_recipe_missing" in station["diagnostic_codes"]
    (diag,) = _diags(payload, "source_recipe_missing")
    assert diag["severity"] == "warning" and diag["subject_ref"] == "src-a"
    assert _diags(payload, "source_never_synced")


def test_invalid_recipe_reports_structure_codes_not_missing() -> None:
    payload = _build(
        sources=[
            _source(
                "src-a",
                recipe_ok=False,
                recipe_errors=["source_recipe_streams_invalid"],
            )
        ]
    )
    assert _station(payload, "station:src-a")["recipe_state"] == "invalid"
    (diag,) = _diags(payload, "source_recipe_invalid")
    assert diag["related_refs"] == ["source_recipe_streams_invalid"]


def test_valid_recipe_single_stream_builds_port_with_resolved_target() -> None:
    payload = _build(
        pages=[_page("page-fin", path="memories/finance/index.md")],
        sources=[
            _source(
                "src-a",
                streams=[
                    _stream(
                        "#general",
                        filters={"channel": "general", "since": "2026-01-01"},
                        target_pages=["memories/finance/index.md"],
                    )
                ],
            )
        ],
    )
    (stream,) = payload["streams"]
    assert stream["stream_id"] == "stream:src-a:#general"
    assert stream["source_id"] == "src-a"
    assert stream["recipe_stream_id"] == "#general"
    assert stream["freshness_state"] == "fresh"
    assert stream["target_page_ids"] == ["page-fin"]
    assert stream["filter_keys"] == ["channel", "since"]
    station = _station(payload, "station:src-a")
    assert station["stream_ids"] == ["stream:src-a:#general"]
    assert station["target_page_ids"] == ["page-fin"]


def test_multiple_streams_and_pipelines_are_registered_per_source() -> None:
    payload = _build(
        sources=[
            _source(
                "src-a",
                pipelines=[
                    {"kind": "content", "cadence_days": 7},
                    {"kind": "metadata", "cadence_days": 30},
                ],
                streams=[_stream("#one"), _stream("#two")],
            )
        ],
        lifecycle=[
            _lifecycle(
                "src-a",
                pipeline_stage="indexed",
                pipeline_stage_timestamps={"indexed": "2026-07-01T00:00:00Z"},
            )
        ],
    )
    assert [p["pipeline_id"] for p in payload["pipelines"]] == [
        "pipeline:src-a:content",
        "pipeline:src-a:metadata",
    ]
    for pipeline in payload["pipelines"]:
        assert pipeline["stream_ids"] == ["stream:src-a:#one", "stream:src-a:#two"]
        assert pipeline["current_stage"] == "indexed"
        assert pipeline["last_transition_at"] == "2026-07-01T00:00:00Z"
    assert payload["summary"]["streams"] == 2 and payload["summary"]["pipelines"] == 2


def test_unselected_stream_is_disabled_without_freshness_diagnostics() -> None:
    payload = _build(
        sources=[
            _source(
                "src-a",
                streams=[
                    _stream("#on", cursor_age_days=None, breached=True),
                    _stream(
                        "#off",
                        selected=False,
                        cursor_age_days=None,
                        breached=False,
                        skip_reason="low_signal",
                    ),
                ],
            )
        ]
    )
    by_id = {s["recipe_stream_id"]: s for s in payload["streams"]}
    assert by_id["#off"]["freshness_state"] == "disabled"
    assert by_id["#off"]["skip_reason_code"] == "low_signal"
    assert by_id["#on"]["freshness_state"] == "never"
    subjects = {d["subject_ref"] for d in _diags(payload, "stream_never_observed")}
    assert subjects == {"stream:src-a:#on"}


def test_cursor_fresh_stale_never_states_and_diagnostics() -> None:
    payload = _build(
        sources=[
            _source(
                "src-a",
                streams=[
                    _stream("#fresh", cursor_age_days=2, breached=False),
                    _stream("#stale", cursor_age_days=30, breached=True),
                    _stream("#never", cursor_age_days=None, breached=True),
                ],
            )
        ]
    )
    states = {s["recipe_stream_id"]: s["freshness_state"] for s in payload["streams"]}
    assert states == {"#fresh": "fresh", "#stale": "stale", "#never": "never"}
    assert {d["subject_ref"] for d in _diags(payload, "stream_past_cadence")} == {
        "stream:src-a:#stale"
    }
    assert {d["subject_ref"] for d in _diags(payload, "stream_never_observed")} == {
        "stream:src-a:#never"
    }


def test_lifecycle_complete_projects_stage_and_adoption() -> None:
    payload = _build(
        sources=[_source("src-a")],
        lifecycle=[
            _lifecycle(
                "src-a",
                lifecycle_state="ingested",
                adoption_state="accepted",
                pipeline_stage="complete",
                pipeline_stage_timestamps={"complete": "2026-07-02T00:00:00Z"},
            )
        ],
    )
    station = _station(payload, "station:src-a")
    assert station["lifecycle_state"] == "ingested"
    assert station["adoption_state"] == "accepted"
    assert station["pipeline_stage"] == "complete"
    (pipeline,) = payload["pipelines"]
    assert pipeline["last_transition_at"] == "2026-07-02T00:00:00Z"
    assert not _diags(payload, "source_lifecycle_missing")


def test_lifecycle_blocked_is_counted_and_free_text_reason_never_travels() -> None:
    reason = "credential leaked in a private note"
    payload = _build(
        sources=[_source("src-a")],
        lifecycle=[
            _lifecycle(
                "src-a",
                lifecycle_state="blocked",
                blocked_reason=reason,
            )
        ],
    )
    (diag,) = _diags(payload, "source_blocked")
    assert diag["severity"] == "error" and diag["subject_ref"] == "src-a"
    assert payload["summary"]["blocked_sources"] == 1
    assert reason not in json.dumps(payload, sort_keys=True)


def test_missing_lifecycle_record_is_a_typed_gap() -> None:
    payload = _build(sources=[_source("src-a")], lifecycle=[])
    (diag,) = _diags(payload, "source_lifecycle_missing")
    assert diag["subject_ref"] == "src-a"
    assert _station(payload, "station:src-a")["lifecycle_state"] == ""


def test_accepted_event_emits_with_closure_and_stream_attribution() -> None:
    payload = _build(
        pages=[
            _page("page-fin", path="memories/finance/index.md"),
            _event_page("sync-1"),
        ],
        sources=[
            _source(
                "src-a",
                streams=[_stream("#gen", target_pages=["memories/finance/index.md"])],
            )
        ],
        events=[
            _event("sync-1", source_refs=["src-a"], consolidated_into=["page-fin"])
        ],
    )
    (emission,) = payload["emissions"]
    assert emission["source_id"] == "src-a"
    assert emission["event_page_id"] == "event-sync-1"
    assert emission["target_page_id"] == "page-fin"
    assert emission["relation_type"] == "source_emission"
    assert emission["closure_state"] == "accepted"
    assert emission["stream_id"] == "stream:src-a:#gen"
    assert emission["provenance_basis"] == "ingestion_event"
    (target,) = payload["targets"]
    assert target["page_id"] == "page-fin"
    assert target["accepted_count"] == 1 and target["closure_state"] == "accepted"
    assert not _diags(payload, "event_without_closure")


def test_reviewed_no_change_event_closes_without_target_diagnostic() -> None:
    payload = _build(
        pages=[_event_page("rev-1")],
        sources=[_source("src-a")],
        events=[
            _event(
                "rev-1",
                source_refs=["src-a"],
                impact_closure={"no_change": ["reviewed 2026-07-02"]},
            )
        ],
    )
    (emission,) = payload["emissions"]
    assert emission["closure_state"] == "reviewed_no_change"
    assert emission["target_page_id"] is None
    assert not _diags(payload, "emission_without_target")
    assert not _diags(payload, "event_without_closure")


def test_open_event_is_pending_with_closure_gap() -> None:
    payload = _build(
        pages=[_event_page("open-1")],
        sources=[_source("src-a")],
        events=[_event("open-1", source_refs=["src-a"], gate_state="open")],
    )
    (emission,) = payload["emissions"]
    assert emission["closure_state"] == "pending"
    (diag,) = _diags(payload, "event_without_closure")
    assert diag["subject_ref"] == "event-open-1"
    # An open event legitimately has no target yet — no target gap.
    assert not _diags(payload, "emission_without_target")


def test_declared_target_without_emission_is_declared_only() -> None:
    payload = _build(
        pages=[_page("page-fin", path="memories/finance/index.md")],
        sources=[
            _source(
                "src-a",
                streams=[_stream("#gen", target_pages=["memories/finance/index.md"])],
            )
        ],
    )
    (target,) = payload["targets"]
    assert target["closure_state"] == "declared_only"
    assert target["emission_count"] == 0
    assert target["target_declared_by_stream_ids"] == ["stream:src-a:#gen"]
    (diag,) = _diags(payload, "target_without_emission")
    assert diag["subject_ref"] == "page-fin"


def test_accepted_event_without_consolidated_target_is_flagged() -> None:
    payload = _build(
        pages=[_event_page("acc-1")],
        sources=[_source("src-a")],
        events=[_event("acc-1", source_refs=["src-a"], gate_state="accepted")],
    )
    (emission,) = payload["emissions"]
    assert emission["closure_state"] == "accepted"
    assert emission["target_page_id"] is None
    (diag,) = _diags(payload, "emission_without_target")
    assert diag["subject_ref"] == emission["emission_id"]


def test_event_without_any_source_is_an_error_gap_not_an_emission() -> None:
    payload = _build(
        pages=[_event_page("orphan-1")],
        sources=[_source("src-a")],
        events=[_event("orphan-1", consolidated_into=[])],
    )
    assert payload["emissions"] == []
    (diag,) = _diags(payload, "emission_without_source")
    assert diag["severity"] == "error" and diag["subject_ref"] == "event-orphan-1"


def test_two_source_target_is_never_collapsed() -> None:
    payload = _build(
        pages=[_page("page-fin"), _event_page("multi-1")],
        sources=[_source("src-a"), _source("src-b")],
        events=[
            _event(
                "multi-1",
                source_refs=["src-a", "src-b"],
                consolidated_into=["page-fin"],
            )
        ],
    )
    assert len(payload["emissions"]) == 2
    assert {e["source_id"] for e in payload["emissions"]} == {"src-a", "src-b"}
    (target,) = payload["targets"]
    assert target["source_ids"] == ["src-a", "src-b"]
    assert target["emission_count"] == 2
    (diag,) = _diags(payload, "multiple_sources_supported")
    assert diag["subject_ref"] == "page-fin"
    assert diag["related_refs"] == ["src-a", "src-b"]


def test_source_config_is_governance_never_an_emitter() -> None:
    config_page = _page(
        "config-a",
        path="memories/sources/config/src-a.md",
        page_type="source_config",
        source_refs=["src-a"],
    )
    payload = _build(
        pages=[config_page, _page("src-a", page_type="source")],
        sources=[_source("src-a", config_ref="memories/sources/config/src-a.md")],
        edges=[_edge("config-a", "src-a", "source_ref")],
        # A config passed through the events input must also be ignored: its
        # PLURAL source_refs declares governance, not an ingestion emission.
        events=[
            {
                "path": f"{EVENTS_DIR}/src-a-config.md",
                "values": {
                    "page_type": "source_config",
                    "page_id": "config-a",
                    "source_refs": ["src-a"],
                },
            }
        ],
    )
    assert payload["emissions"] == []
    assert payload["targets"] == []
    assert _station(payload, "station:src-a")["config_page_id"] == "config-a"


def test_frontmatter_source_ref_emission_from_knowledge_page() -> None:
    payload = _build(
        pages=[
            _page("page-note", source_refs=["src-a"]),
            _page("src-a", page_type="source"),
        ],
        sources=[_source("src-a")],
        edges=[_edge("page-note", "src-a", "source_ref")],
    )
    (emission,) = payload["emissions"]
    assert emission["relation_type"] == "source_ref"
    assert emission["source_id"] == "src-a"
    assert emission["target_page_id"] == "page-note"
    assert emission["event_page_id"] is None
    assert emission["closure_state"] == "accepted"


def test_channel_groups_sources_through_real_relation() -> None:
    channel = _page(
        "chan-comms",
        path="memories/channels/comms.md",
        page_type="input_channel",
        source_refs=["src-a", "src-b"],
    )
    payload = _build(
        pages=[channel, _page("src-a", page_type="source"), _page("src-b", page_type="source")],
        sources=[
            _source("src-a", pending_streams=2),
            _source("src-b", pending_streams=1),
            _source("src-c"),
        ],
    )
    station = _station(payload, "channel:chan-comms")
    assert station["kind"] == "input_channel"
    assert station["pending_stream_count"] == 3
    assert _station(payload, "station:src-a")["channel_station_id"] == "channel:chan-comms"
    assert _station(payload, "station:src-b")["channel_station_id"] == "channel:chan-comms"
    assert _station(payload, "station:src-c")["channel_station_id"] is None
    assert payload["summary"]["channels"] == 1
    assert payload["summary"]["sources"] == 3


def test_relation_outside_vocabulary_is_reported_not_projected() -> None:
    payload = _build(
        pages=[_page("page-x"), _page("src-a", page_type="source")],
        sources=[_source("src-a")],
        edges=[
            _edge("src-a", "page-x", "related_page"),
            _edge("page-x", "src-a", "markdown_link"),  # orientation: silent
        ],
    )
    assert payload["emissions"] == []
    (diag,) = _diags(payload, "relation_outside_source_vocabulary")
    assert diag["subject_ref"] == "src-a"
    assert "related_page" in diag["related_refs"]


def test_derived_ids_are_stable_literals() -> None:
    payload = _build(
        pages=[_page("page-fin"), _event_page("sync-1")],
        sources=[
            _source("src-a", streams=[_stream("#gen", target_pages=["page-fin"])])
        ],
        events=[_event("sync-1", source_refs=["src-a"], consolidated_into=["page-fin"])],
    )
    assert _station(payload, "station:src-a")["station_id"] == "station:src-a"
    (stream,) = payload["streams"]
    assert stream["stream_id"] == "stream:src-a:#gen"
    (pipeline,) = payload["pipelines"]
    assert pipeline["pipeline_id"] == "pipeline:src-a:content"
    (emission,) = payload["emissions"]
    assert emission["emission_id"].startswith("emission:")
    assert len(emission["emission_id"]) == len("emission:") + 20
    for diag in payload["diagnostics"]:
        assert diag["gap_id"].startswith(f"gap:{diag['code']}:")
    rebuilt = _build(
        pages=[_page("page-fin"), _event_page("sync-1")],
        sources=[
            _source("src-a", streams=[_stream("#gen", target_pages=["page-fin"])])
        ],
        events=[_event("sync-1", source_refs=["src-a"], consolidated_into=["page-fin"])],
    )
    assert rebuilt == payload


def test_derived_id_collision_with_page_id_fails_loudly() -> None:
    with pytest.raises(ValueError, match="collide"):
        _build(
            pages=[_page("station:src-a")],
            sources=[_source("src-a")],
        )


def test_ordering_is_independent_of_input_order() -> None:
    pages = [_page("page-b"), _page("page-a"), _event_page("sync-1")]
    sources = [
        _source("src-b", streams=[_stream("#two"), _stream("#one")]),
        _source("src-a", streams=[_stream("#gen", target_pages=["page-a", "page-b"])]),
    ]
    events = [_event("sync-1", source_refs=["src-a"], consolidated_into=["page-a"])]
    edges = [_edge("page-b", "src-b", "source_ref")]
    forward = _build(pages=pages, sources=sources, events=events, edges=edges)
    reverse = _build(
        pages=list(reversed(pages)),
        sources=list(reversed(sources)),
        events=list(reversed(events)),
        edges=list(reversed(edges)),
    )
    assert forward == reverse
    assert [s["station_id"] for s in forward["stations"]] == sorted(
        s["station_id"] for s in forward["stations"]
    )
    assert [s["stream_id"] for s in forward["streams"]] == sorted(
        s["stream_id"] for s in forward["streams"]
    )


def test_topology_hash_ignores_revision_and_tracks_topology() -> None:
    sources = [_source("src-a")]
    first = _build(sources=sources)
    second = _build(
        sources=copy.deepcopy(sources),
        revision="rev-2",
        generated_at="2026-07-18T12:00:00Z",
    )
    assert first["topology_sha256"] == second["topology_sha256"]
    changed = _build(sources=[_source("src-a"), _source("src-b")])
    assert changed["topology_sha256"] != first["topology_sha256"]


# ------------------------------------------------- end-to-end repo fixtures


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _repo(root: Path, recipe: dict[str, Any]) -> WikiConfig:
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True
    )
    _write(root / "wiki.config.yaml", "repo_id: src-foundation-test\ndefault_context: system\n")
    _write(
        root / "memories/sources/slack-fin.md",
        """---
page_id: source-slack-fin
page_type: source
title: "Slack finance"
context: system
owner: person-kim
config_ref: memories/sources/config/slack-fin.md
updated_at: 2026-07-01
---

# Slack finance source
""",
    )
    rendered = yaml.safe_dump({"recipe": recipe}, sort_keys=False)
    _write(
        root / "memories/sources/config/slack-fin.md",
        "---\npage_id: source-config-slack-fin\npage_type: source_config\n"
        f"context: system\n---\n\n# config\n\n```yaml\n{rendered}```\n",
    )
    return load_config(root)


def _base_recipe() -> dict[str, Any]:
    return {
        "schema_version": "wiki_source_recipe.v1",
        "platform": "slack",
        "locator": "T024/finance",
        "auth": {"method": "env", "ref": "SLACK_TOKEN_POINTER"},
        "pipelines": [{"kind": "content", "cadence_days": 7}],
        "streams": [
            {
                "id": "#financeiro",
                "selected": True,
                "filters": {"channel": "very-private-filter-value"},
                "target_pages": ["memories/finance/index.md"],
            }
        ],
        "how_to_export": "Open the private export console.",
    }


def _foundation_from_repo(root: Path, config: WikiConfig) -> dict[str, Any]:
    entities = build_sources_payload(root, config, today=dt.date(2026, 7, 3))
    pages = [
        _page("source-slack-fin", path="memories/sources/slack-fin.md", page_type="source"),
        _page(
            "source-config-slack-fin",
            path="memories/sources/config/slack-fin.md",
            page_type="source_config",
        ),
        _page("page-fin", path="memories/finance/index.md"),
    ]
    return _build(
        pages=pages,
        sources=list(entities["sources"]),
        lifecycle=[_lifecycle("source-slack-fin")],
    )


def test_secret_recipe_fails_closed_end_to_end(tmp_path: Path) -> None:
    secret = "sk-" + "S" * 24
    recipe = _base_recipe()
    recipe["locator"] = secret
    config = _repo(tmp_path, recipe)
    payload = _foundation_from_repo(tmp_path, config)
    station = _station(payload, "station:source-slack-fin")
    assert station["recipe_state"] == "secret_blocked"
    assert station["platform"] == ""
    assert station["stream_ids"] == [] and station["pipeline_ids"] == []
    (diag,) = _diags(payload, SOURCE_RECIPE_SAFETY_ERROR_CODE)
    assert diag["code"] == "source_recipe_secret_detected"
    assert diag["severity"] == "error"
    serialized = json.dumps(payload, sort_keys=True)
    assert secret not in serialized
    assert "source_recipe_secret_blocked" not in serialized  # one vocabulary only


def test_public_sanitization_keeps_locator_filters_manual_and_auth_out(
    tmp_path: Path,
) -> None:
    config = _repo(tmp_path, _base_recipe())
    payload = _foundation_from_repo(tmp_path, config)
    station = _station(payload, "station:source-slack-fin")
    assert station["recipe_state"] == "valid"
    (stream,) = payload["streams"]
    assert stream["filter_keys"] == ["channel"]
    serialized = json.dumps(payload, sort_keys=True)
    assert "T024/finance" not in serialized
    assert "very-private-filter-value" not in serialized
    assert "Open the private export console." not in serialized
    assert "SLACK_TOKEN_POINTER" not in serialized


def test_private_mode_is_identical_and_unknown_mode_rejected() -> None:
    sources = [_source("src-a")]
    assert _build(sources=sources, mode="private") == _build(
        sources=copy.deepcopy(sources)
    )
    with pytest.raises(ValueError, match="mode"):
        _build(sources=[_source("src-a")], mode="secret")


def test_path_containment_refuses_escaping_refs() -> None:
    payload = _build(
        pages=[_page("page-fin", path="memories/finance/index.md")],
        sources=[
            _source(
                "src-a",
                path="../outside/escape.md",
                streams=[
                    _stream(
                        "#gen",
                        target_pages=[
                            "../../etc/passwd",
                            "/etc/passwd",
                            "memories/finance/index.md",
                        ],
                    )
                ],
            )
        ],
    )
    station = _station(payload, "station:src-a")
    assert station["path"] == ""
    (stream,) = payload["streams"]
    assert stream["target_page_ids"] == ["page-fin"]
    missing = _diags(payload, "stream_target_missing")
    assert missing and missing[0]["subject_ref"] == "stream:src-a:#gen"
    serialized = json.dumps(payload, sort_keys=True)
    assert "../" not in serialized
    assert "/etc/passwd" not in serialized


def _rich_payload() -> dict[str, Any]:
    channel = _page(
        "chan-comms",
        path="memories/channels/comms.md",
        page_type="input_channel",
        source_refs=["src-a"],
    )
    return _build(
        pages=[
            channel,
            _page("src-a", page_type="source"),
            _page("src-b", page_type="source"),
            _page("page-fin", path="memories/finance/index.md"),
            _event_page("sync-1"),
        ],
        sources=[
            _source(
                "src-a",
                streams=[
                    _stream("#gen", target_pages=["memories/finance/index.md"]),
                    _stream("#quiet", selected=False, cursor_age_days=None),
                ],
                pending_streams=1,
                next_due_days=3,
            ),
            _bare_source("src-b"),
        ],
        lifecycle=[
            _lifecycle("src-a"),
            _lifecycle("src-b", lifecycle_state="blocked", blocked_reason="auth"),
        ],
        events=[
            _event(
                "sync-1",
                source_refs=["src-a", "src-b"],
                consolidated_into=["page-fin"],
                proposal_ids=["proposal-1"],
                evidence_refs=["memories/raw/export-1.txt"],
            )
        ],
        edges=[_edge("page-fin", "src-a", "source_ref")],
    )


def test_payload_validates_against_published_schema_exactly() -> None:
    payload = _rich_payload()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(payload)
    # Exactness: every record carries exactly the schema's declared keys.
    for section, def_name in (
        ("stations", "station"),
        ("streams", "stream"),
        ("pipelines", "pipeline"),
        ("emissions", "emission"),
        ("targets", "target"),
        ("diagnostics", "diagnostic"),
    ):
        declared = set(schema["$defs"][def_name]["properties"])
        assert set(schema["$defs"][def_name]["required"]) == declared
        for record in payload[section]:
            assert set(record) == declared, (section, record)
    assert set(payload) == set(schema["properties"])
    assert set(payload["summary"]) == set(schema["$defs"]["summary"]["properties"])


def test_every_reference_in_payload_resolves() -> None:
    payload = _rich_payload()
    station_pages = {s["canonical_page_id"] for s in payload["stations"]}
    station_ids = {s["station_id"] for s in payload["stations"]}
    stream_ids = {s["stream_id"] for s in payload["streams"]}
    pipeline_ids = {p["pipeline_id"] for p in payload["pipelines"]}
    emission_ids = {e["emission_id"] for e in payload["emissions"]}
    target_ids = {t["page_id"] for t in payload["targets"]}
    for station in payload["stations"]:
        assert set(station["stream_ids"]) <= stream_ids
        assert set(station["pipeline_ids"]) <= pipeline_ids
        assert set(station["emission_ids"]) <= emission_ids
        assert set(station["target_page_ids"]) <= target_ids
        if station["channel_station_id"] is not None:
            assert station["channel_station_id"] in station_ids
    for stream in payload["streams"]:
        assert stream["source_id"] in station_pages
        assert set(stream["target_page_ids"]) <= target_ids
    for pipeline in payload["pipelines"]:
        assert pipeline["source_id"] in station_pages
        assert set(pipeline["stream_ids"]) <= stream_ids
    for emission in payload["emissions"]:
        assert emission["source_id"] in station_pages
        if emission["stream_id"] is not None:
            assert emission["stream_id"] in stream_ids
        if emission["target_page_id"] is not None:
            assert emission["target_page_id"] in target_ids
    for target in payload["targets"]:
        assert set(target["source_ids"]) <= station_pages
        assert set(target["target_declared_by_stream_ids"]) <= stream_ids


def test_legacy_event_page_type_and_singular_source_ref_resolve() -> None:
    legacy = {
        "path": f"{EVENTS_DIR}/2026-07-01-whatsapp.md",
        "values": {
            # Real private-consumer shape: legacy page_type + SINGULAR ref.
            "page_type": "source_catalog",
            "page_id": "event-legacy-whatsapp",
            "source_ref": "src-a",
            "consolidated_into": ["page-fin"],
            "updated_at": "2026-07-01",
        },
    }
    payload = _build(
        pages=[
            _page("page-fin"),
            _page(
                "event-legacy-whatsapp",
                path=f"{EVENTS_DIR}/2026-07-01-whatsapp.md",
                page_type="source_catalog",
            ),
        ],
        sources=[_source("src-a")],
        events=[legacy],
    )
    (emission,) = payload["emissions"]
    assert emission["source_id"] == "src-a"
    assert emission["event_page_id"] == "event-legacy-whatsapp"
    assert emission["target_page_id"] == "page-fin"
    assert emission["closure_state"] == "accepted"
    assert emission["provenance_basis"] == "ingestion_event_legacy"
    # Outside the events directory the same legacy shape is NOT an event.
    outside = dict(legacy, path="memories/notes/2026-07-01-whatsapp.md")
    no_event = _build(
        pages=[_page("page-fin")],
        sources=[_source("src-a")],
        events=[outside],
    )
    assert no_event["emissions"] == []


def test_day_one_mass_diagnostics_stay_linear_and_severity_honest() -> None:
    count = 40
    sources = [_bare_source(f"src-{index:02d}") for index in range(count)]
    sources.append(
        _source("src-failed", sync={"last_run_at": "2026-07-01", "last_status": "failed"})
    )
    payload = _build(sources=sources, lifecycle=[])
    assert payload["summary"]["sources"] == count + 1
    assert len(_diags(payload, "source_recipe_missing")) == count
    assert len(_diags(payload, "source_never_synced")) == count
    assert len(_diags(payload, "source_lifecycle_missing")) == count + 1
    # One aggregated record per (code, subject): linear, no blowup.
    assert len(payload["diagnostics"]) == 3 * count + 2
    assert payload["summary"]["gaps"] == 3 * count + 2
    # The lone error is not masked by the mass of warnings.
    (failed,) = _diags(payload, "source_sync_failed")
    assert failed["severity"] == "error" and failed["subject_ref"] == "src-failed"
    severities = {d["severity"] for d in payload["diagnostics"]}
    assert severities == {"info", "warning", "error"}
