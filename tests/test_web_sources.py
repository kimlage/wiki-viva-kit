from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from wiki_core.config import WikiConfig, load_config
from wiki_core.paths import WikiPaths
from wiki_core.source_recipe import SOURCE_RECIPE_SAFETY_ERROR_CODE
from wiki_core.source_state import write_stream_cursor
from wiki_core.web.snapshot import build_snapshot
from wiki_core.web.sources import build_sources_payload, compose_source_brief_spec

TODAY = dt.date(2026, 7, 3)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _repo(root: Path) -> WikiConfig:
    subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
    _write(root / ".gitignore", "data/derived/\n")
    _write(root / "wiki.config.yaml", "repo_id: src-test\ndefault_context: system\n")
    _write(
        root / "memories/sources/slack-fin.md",
        """---
page_id: source-slack-fin
page_type: source
title: "Slack — Finanças"
context: system
platform: slack
source_locator: "T024/finance"
visual_identity:
  key: finance-team
  label: "Finance team"
  asset_path: /source-icons/finance-team.webp
  background: light
owner: person-kim
config_ref: memories/sources/config/slack-fin.md
updated_at: 2026-07-01
stale_after_days: 30
sync:
  last_run_at: 2026-07-01T10:00:00Z
  last_status: partial
  streams_fresh: 1
  streams_total: 2
---

# Slack finance source
""",
    )
    _write(
        root / "memories/sources/config/slack-fin.md",
        """---
page_id: source-config-slack-fin
page_type: source_config
context: system
---

# config

```yaml
recipe:
  schema_version: wiki_source_recipe.v1
  platform: slack
  locator: "T024/finance"
  source_kind: collection
  pipelines:
    - { kind: content, cadence_days: 7 }
  streams:
    - id: "#financeiro"
      selected: true
      target_pages: [memories/financeiro/index.md]
    - id: "#custos"
      selected: true
  how_to_export: "Slack export."
  schedule: {mode: recurring, cadence_days: 7}
```
""",
    )
    return load_config(root)


def test_payload_rolls_up_identity_recipe_and_freshness(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    # #financeiro was synced 2 days ago (fresh under a 7-day cadence);
    # #custos has no cursor => breached.
    paths = WikiPaths(tmp_path, config)
    write_stream_cursor(paths.source_state, "source-slack-fin", "#financeiro", cursor="c", updated_at="2026-07-01")

    payload = build_sources_payload(tmp_path, config, today=TODAY)
    assert payload["summary"]["total"] == 1
    assert payload["summary"]["with_recipe"] == 1
    source = payload["sources"][0]
    assert source["platform"] == "slack" and source["owner"] == "person-kim"
    assert source["locator"] == "T024/finance"
    assert source["visual_identity"] == {
        "key": "finance-team",
        "label": "Finance team",
        "asset_path": "/source-icons/finance-team.webp",
        "background": "light",
    }
    assert source["recipe_ok"] is True
    assert source["update_route"] == {
        "mode": "manual_export",
        "mcp_hint": "",
        "runnable": False,
        "requires_agent": False,
    }
    streams = {s["id"]: s for s in source["streams"]}
    assert streams["#financeiro"]["breached"] is False
    assert streams["#custos"]["breached"] is True
    assert source["pending_streams"] == 1
    # The machine sync block is surfaced verbatim.
    assert source["sync"]["last_status"] == "partial"


def test_lifecycle_read_model_uses_the_same_flattened_over_nested_precedence(
    tmp_path: Path,
) -> None:
    config = _repo(tmp_path)
    source_path = tmp_path / "memories/sources/slack-fin.md"
    text = source_path.read_text(encoding="utf-8")
    text = text.replace(
        "---\n\n# Slack finance source",
        "source_last_attempt_state: ok\n"
        "source_lifecycle:\n"
        "  last_attempt_state: retrying\n"
        "  pipeline_stage: indexed\n"
        "---\n\n# Slack finance source",
    )
    _write(source_path, text)

    source = build_sources_payload(tmp_path, config, today=TODAY)["sources"][0]

    assert source["lifecycle"]["last_attempt_state"] == "ok"
    assert source["lifecycle"]["pipeline_stage"] == "indexed"


def test_visual_identity_rejects_remote_or_traversing_assets(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    source_path = tmp_path / "memories/sources/slack-fin.md"
    text = source_path.read_text(encoding="utf-8").replace(
        "  asset_path: /source-icons/finance-team.webp",
        "  asset_path: https://example.test/finance-team.webp",
    )
    _write(source_path, text)
    source = build_sources_payload(tmp_path, config, today=TODAY)["sources"][0]
    assert "visual_identity" not in source

    text = source_path.read_text(encoding="utf-8").replace(
        "  asset_path: https://example.test/finance-team.webp",
        "  asset_path: /source-icons/../private.webp",
    )
    _write(source_path, text)
    source = build_sources_payload(tmp_path, config, today=TODAY)["sources"][0]
    assert "visual_identity" not in source


def test_versioned_per_stream_receipts_survive_a_clean_clone(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    source_path = tmp_path / "memories/sources/slack-fin.md"
    text = source_path.read_text(encoding="utf-8").replace(
        "  streams_total: 2\n",
        "  streams_total: 2\n"
        "  streams:\n"
        "    '#financeiro':\n"
        "      last_run_at: 2026-07-01T10:00:00Z\n"
        "      last_status: ok\n"
        "    '#custos':\n"
        "      last_run_at: 2026-06-20T10:00:00Z\n"
        "      last_status: ok\n",
    )
    _write(source_path, text)

    source = build_sources_payload(tmp_path, config, today=TODAY)["sources"][0]
    streams = {stream["id"]: stream for stream in source["streams"]}
    assert streams["#financeiro"]["cursor_age_days"] == 2
    assert streams["#financeiro"]["freshness_basis"] == "versioned_stream_receipt"
    assert streams["#custos"]["cursor_age_days"] == 13
    assert source["pending_streams"] == 1


def test_shared_recipe_exposes_only_stream_for_current_source(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    config_path = tmp_path / "memories/sources/config/slack-fin.md"
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        .replace(
            '    - id: "#financeiro"\n      selected: true\n',
            '    - id: "#financeiro"\n      selected: true\n'
            '      filters: { source_ref: source-slack-fin }\n',
        )
        .replace(
            '    - id: "#custos"\n      selected: true\n',
            '    - id: "#custos"\n      selected: true\n'
            '      filters: { source_ref: source-other }\n',
        ),
        encoding="utf-8",
    )

    source = build_sources_payload(tmp_path, config, today=TODAY)["sources"][0]
    assert [stream["id"] for stream in source["streams"]] == ["#financeiro"]
    assert source["sync"]["streams_total"] == 1


def test_compose_brief_targets_only_stale_streams(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    paths = WikiPaths(tmp_path, config)
    write_stream_cursor(paths.source_state, "source-slack-fin", "#financeiro", cursor="c", updated_at="2026-07-01")

    result = compose_source_brief_spec(tmp_path, config, "source-slack-fin", today=TODAY)
    assert result["ok"] is True
    assert result["pending"] == 1
    spec = result["spec"]
    assert spec["mission_kind"] == "ingest"
    assert spec["theme"] == "ingest-source-slack-fin"
    assert "#custos" in spec["intent"]
    assert spec["grounding"]["attach_context_package"] is True


def test_unknown_source_brief_is_honest(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    result = compose_source_brief_spec(tmp_path, config, "source-nope", today=TODAY)
    assert result["ok"] is False


def test_malformed_recipe_surfaces_errors_not_crash(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    # Break the recipe: unknown platform + no locator.
    _write(
        tmp_path / "memories/sources/config/slack-fin.md",
        "---\npage_id: c\npage_type: source_config\n---\n\n```yaml\nrecipe:\n  platform: telepathy\n  pipelines: []\n  streams: []\n```\n",
    )
    payload = build_sources_payload(tmp_path, config, today=TODAY)
    source = payload["sources"][0]
    assert source["recipe_ok"] is False
    assert any("platform" in e for e in source["recipe_errors"])
    assert "telepathy" in " ".join(source["recipe_errors"])
    brief = compose_source_brief_spec(tmp_path, config, "source-slack-fin", today=TODAY)
    assert brief == {
        "ok": False,
        "error": "source_recipe_invalid",
        "error_code": "source_recipe_invalid",
    }


def test_one_malformed_recipe_does_not_erase_other_valid_sources(
    tmp_path: Path,
) -> None:
    config = _repo(tmp_path)
    _write(
        tmp_path / "memories/sources/broken.md",
        "---\npage_id: source-broken\npage_type: source\ntitle: Broken\n"
        "context: system\nconfig_ref: memories/sources/config/broken.md\n---\n",
    )
    _write(
        tmp_path / "memories/sources/config/broken.md",
            "---\npage_id: source-config-broken\npage_type: source_config\n---\n\n"
            "```yaml\nrecipe:\n  platform: slack\n  locator: broken\n"
            "  source_kind: collection\n"
            "  pipelines:\n    - {kind: content, cadence_days: 7}\n"
            "  streams:\n    - id: broken\n      filters: [not, a, mapping]\n"
            "  schedule: {mode: on_demand, cadence_days: 0}\n"
            "  ingest: not-a-mapping\n```\n",
    )

    payload = build_sources_payload(tmp_path, config, today=TODAY)
    by_id = {source["source_id"]: source for source in payload["sources"]}

    assert set(by_id) == {"source-slack-fin", "source-broken"}
    assert by_id["source-slack-fin"]["recipe_ok"] is True
    assert by_id["source-broken"]["recipe_ok"] is False
    assert by_id["source-broken"]["recipe_errors"] == [
        "source_recipe_ingest_invalid",
        "source_recipe_stream_filters_invalid",
    ]


@pytest.mark.parametrize("secret_location", ["locator", "platform", "nested_filter_auth"])
def test_secret_recipe_is_code_only_and_never_projected_or_composed(
    tmp_path: Path,
    secret_location: str,
) -> None:
    config = _repo(tmp_path)
    secret = (
        "opaque-filter-auth-value-not-for-output"
        if secret_location == "nested_filter_auth"
        else "sk-" + "S" * 24
    )
    recipe: dict[str, object] = {
        "schema_version": "wiki_source_recipe.v1",
        "platform": "slack",
        "locator": "T024/finance",
        "pipelines": [{"kind": "content", "cadence_days": 7}],
        "streams": [
            {
                "id": "#financeiro",
                "selected": True,
                "filters": {"channel": "financeiro"},
                "target_pages": ["memories/financeiro/index.md"],
            }
        ],
        "how_to_export": "Use the approved local export.",
    }
    if secret_location in {"locator", "platform"}:
        recipe[secret_location] = secret
    else:
        streams = recipe["streams"]
        assert isinstance(streams, list) and isinstance(streams[0], dict)
        streams[0]["filters"] = {"auth": f"Authorization: Bearer {secret}"}

    rendered_recipe = yaml.safe_dump({"recipe": recipe}, sort_keys=False)
    _write(
        tmp_path / "memories/sources/config/slack-fin.md",
        "---\npage_id: source-config-slack-fin\npage_type: source_config\n"
        "context: system\n---\n\n# config\n\n```yaml\n"
        f"{rendered_recipe}```\n",
    )

    payload = build_sources_payload(tmp_path, config, today=TODAY)
    source = payload["sources"][0]
    assert source["recipe_ok"] is False
    assert source["recipe_errors"] == [SOURCE_RECIPE_SAFETY_ERROR_CODE]
    assert source["platform"] == ""
    assert source["locator"] == ""
    assert source["how_to_export"] == ""
    assert source["pipelines"] == []
    assert source["streams"] == []
    assert source["auth"] is None
    assert source["schedule"] is None
    assert secret not in json.dumps(payload, sort_keys=True)

    snapshot = build_snapshot(
        tmp_path,
        config,
        generated_at="2026-07-03T00:00:00Z",
    )
    assert secret not in json.dumps(snapshot, sort_keys=True)
    assert snapshot["source_entities.json"]["sources"][0]["recipe_errors"] == [
        SOURCE_RECIPE_SAFETY_ERROR_CODE
    ]

    brief = compose_source_brief_spec(
        tmp_path,
        config,
        "source-slack-fin",
        today=TODAY,
    )
    assert brief == {
        "ok": False,
        "error": SOURCE_RECIPE_SAFETY_ERROR_CODE,
        "error_code": SOURCE_RECIPE_SAFETY_ERROR_CODE,
    }
    assert secret not in json.dumps(brief, sort_keys=True)


@pytest.mark.parametrize(
    "secret",
    [
        "github_" + "pat_" + "A" * 30,
        "sk-" + "ant-" + "A" * 30,
        "sk_" + "live_" + "A" * 20,
        "postgresql" + "://alice:SuperSecret42@db.example",
    ],
)
def test_canonical_recipe_secrets_never_reach_payload_snapshot_or_brief(
    tmp_path: Path,
    secret: str,
) -> None:
    config = _repo(tmp_path)
    recipe = {
        "schema_version": "wiki_source_recipe.v1",
        "platform": "slack",
        "locator": secret,
        "pipelines": [{"kind": "content", "cadence_days": 7}],
        "streams": [{"id": "#financeiro", "selected": True}],
        "how_to_export": "Use the approved local export.",
    }
    rendered_recipe = yaml.safe_dump({"recipe": recipe}, sort_keys=False)
    _write(
        tmp_path / "memories/sources/config/slack-fin.md",
        "---\npage_id: source-config-slack-fin\npage_type: source_config\n"
        "context: system\n---\n\n# config\n\n```yaml\n"
        f"{rendered_recipe}```\n",
    )

    payload = build_sources_payload(tmp_path, config, today=TODAY)
    source = payload["sources"][0]
    assert source["recipe_ok"] is False
    assert source["recipe_errors"] == [SOURCE_RECIPE_SAFETY_ERROR_CODE]
    assert source["platform"] == ""
    assert source["locator"] == ""
    assert source["pipelines"] == []
    assert source["streams"] == []
    assert secret not in json.dumps(payload, sort_keys=True)

    snapshot = build_snapshot(
        tmp_path,
        config,
        generated_at="2026-07-03T00:00:00Z",
    )
    assert secret not in json.dumps(snapshot, sort_keys=True)

    brief = compose_source_brief_spec(
        tmp_path,
        config,
        "source-slack-fin",
        today=TODAY,
    )
    assert brief == {
        "ok": False,
        "error": SOURCE_RECIPE_SAFETY_ERROR_CODE,
        "error_code": SOURCE_RECIPE_SAFETY_ERROR_CODE,
    }
    assert secret not in json.dumps(brief, sort_keys=True)


def test_config_ref_escaping_the_repo_reads_no_recipe(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    # A secret file outside the repo, and a source whose config_ref escapes to it.
    _write(tmp_path.parent / "outside-recipe.md", "```yaml\nrecipe:\n  platform: slack\n  locator: LEAKED\n```\n")
    _write(
        tmp_path / "memories/sources/slack-fin.md",
        "---\npage_id: source-slack-fin\npage_type: source\ncontext: system\n"
        "config_ref: ../outside-recipe.md\n---\n\n# src\n",
    )
    payload = build_sources_payload(tmp_path, config, today=TODAY)
    source = payload["sources"][0]
    # The out-of-repo recipe was NOT read — no locator leaked in.
    assert source["locator"] != "LEAKED"
    assert source["recipe_ok"] is False


def test_freshness_uses_iso_updated_at_not_the_opaque_cursor(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    paths = WikiPaths(tmp_path, config)
    # A cursor written by the standard CLI path: a non-date token, but a REAL ISO
    # updated_at. Freshness must come from updated_at (2 days ago = fresh), never
    # from the opaque token (which would fail to parse and read as "never").
    write_stream_cursor(
        paths.source_state,
        "source-slack-fin",
        "#financeiro",
        cursor="source-slack-fin-a1b2c3d4",  # opaque id, not a date
        updated_at="2026-07-01",
    )
    payload = build_sources_payload(tmp_path, config, today=TODAY)
    streams = {s["id"]: s for s in payload["sources"][0]["streams"]}
    assert streams["#financeiro"]["cursor_age_days"] == 2
    assert streams["#financeiro"]["breached"] is False


def test_single_stream_clean_clone_uses_versioned_successful_sync(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    source_path = tmp_path / "memories/sources/slack-fin.md"
    source_path.write_text(
        source_path.read_text(encoding="utf-8").replace(
            "last_status: partial", "last_status: ok"
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "memories/sources/config/slack-fin.md"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            '    - id: "#custos"\n      selected: true\n',
            '    - id: "#custos"\n      selected: false\n      skip_reason: "not in this source scope"\n',
        ),
        encoding="utf-8",
    )

    # A clean clone has no data/derived cursor state. For one selected stream,
    # the versioned successful receipt is sufficient and survives deployment.
    payload = build_sources_payload(tmp_path, config, today=TODAY)
    streams = {s["id"]: s for s in payload["sources"][0]["streams"]}
    assert streams["#financeiro"]["cursor_age_days"] == 2
    assert streams["#financeiro"]["freshness_basis"] == "source_receipt"
    assert streams["#financeiro"]["breached"] is False
    assert payload["sources"][0]["pending_streams"] == 0


def test_legacy_lifecycle_placeholder_does_not_override_sync_evidence(
    tmp_path: Path,
) -> None:
    config = _repo(tmp_path)
    source_path = tmp_path / "memories/sources/slack-fin.md"
    source_path.write_text(
        source_path.read_text(encoding="utf-8")
        .replace(
            "updated_at: 2026-07-01\n",
            "updated_at: 2026-07-01\n"
            "last_ingested_at: 2026-07-01\n"
            "ingestion_state: ingested\n"
            "source_lifecycle:\n"
            "  state: configured\n"
            "  freshness_state: never_synced\n"
            "  last_attempt_state: never\n"
            "  pipeline_stage: configured\n"
            "  adoption_state: pending\n"
            "  last_sync_success_at: ''\n"
            "  last_ingested_at: ''\n",
        )
        .replace("last_status: partial", "last_status: ok"),
        encoding="utf-8",
    )

    source = build_sources_payload(tmp_path, config, today=TODAY)["sources"][0]
    assert source["lifecycle"]["derived_from_legacy"] is True
    assert source["lifecycle"]["state"] == "ingested"
    assert source["lifecycle"]["last_attempt_state"] == "ok"
    assert source["lifecycle"]["pipeline_stage"] == "complete"


def test_event_driven_discovered_record_is_pending_without_becoming_time_stale(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    config_path = tmp_path / "memories/sources/config/slack-fin.md"
    text = config_path.read_text(encoding="utf-8")
    text = text.replace("schedule: {mode: recurring, cadence_days: 7}", "schedule: {mode: event_driven, cadence_days: 0}")
    text = text.replace(
        '    - id: "#financeiro"\n      selected: true\n',
        '    - id: "#financeiro"\n      selected: true\n      filters: {processing_state: discovered}\n',
    )
    config_path.write_text(text, encoding="utf-8")
    source = build_sources_payload(tmp_path, config, today=TODAY)["sources"][0]
    streams = {stream["id"]: stream for stream in source["streams"]}
    assert streams["#financeiro"]["breached"] is True
    assert streams["#financeiro"]["freshness_basis"] == "processing_state"
    assert source["pending_streams"] == 1


@pytest.mark.parametrize(
    ("schedule", "expected_next_due"),
    [
        ("schedule: {mode: on_demand, cadence_days: 0}", None),
        ("schedule: {mode: recurring, cadence_days: 1}", -1),
    ],
)
def test_append_only_history_separates_discovery_cadence_from_record_processing(
    tmp_path: Path,
    schedule: str,
    expected_next_due: int | None,
) -> None:
    config = _repo(tmp_path)
    source_path = tmp_path / "memories/sources/slack-fin.md"
    source_path.write_text(
        source_path.read_text(encoding="utf-8").replace(
            "last_status: partial", "last_status: ok"
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "memories/sources/config/slack-fin.md"
    _write(
        config_path,
        f'''---
page_id: source-config-slack-fin
page_type: source_config
context: system
---

```yaml
recipe:
  schema_version: wiki_source_recipe.v1
  platform: calendar
  locator: calendar://series/team-daily
  source_kind: collection
  pipelines:
    - {{kind: content, cadence_days: 1}}
  streams:
    - id: 2026-06-30-team-daily
      label: 2026-06-30 - Team daily
      selected: true
      cadence_days: 0
      filters:
        source_ref: source-slack-fin
        occurrence_state: occurred
        processing_state: ingested
    - id: 2026-07-03-team-daily
      label: 2026-07-03 - Team daily
      selected: true
      cadence_days: 0
      filters:
        source_ref: source-slack-fin
        occurrence_state: occurred
        processing_state: discovered
  {schedule}
  ingest:
    mcp_hint: synthetic-calendar
```
''',
    )

    source = build_sources_payload(tmp_path, config, today=TODAY)["sources"][0]
    streams = {stream["id"]: stream for stream in source["streams"]}

    historical = streams["2026-06-30-team-daily"]
    discovered = streams["2026-07-03-team-daily"]
    assert historical["cursor_age_days"] is None
    assert historical["freshness_basis"] == "processing_state"
    assert historical["breached"] is False
    assert discovered["freshness_basis"] == "processing_state"
    assert discovered["breached"] is True
    assert source["pending_streams"] == 1
    assert source["next_due_days"] == expected_next_due
