from __future__ import annotations

import datetime as dt
import subprocess
from pathlib import Path

from wiki_core.config import WikiConfig, load_config
from wiki_core.paths import WikiPaths
from wiki_core.source_state import write_stream_cursor
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
  pipelines:
    - { kind: content, cadence_days: 7 }
  streams:
    - id: "#financeiro"
      selected: true
      target_pages: [memories/financeiro/index.md]
    - id: "#custos"
      selected: true
  how_to_export: "Slack export."
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
    assert source["recipe_ok"] is True
    streams = {s["id"]: s for s in source["streams"]}
    assert streams["#financeiro"]["breached"] is False
    assert streams["#custos"]["breached"] is True
    assert source["pending_streams"] == 1
    # The machine sync block is surfaced verbatim.
    assert source["sync"]["last_status"] == "partial"


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
    assert streams["#financeiro"]["freshness_basis"] == "versioned_source_sync"
    assert streams["#financeiro"]["breached"] is False
    assert payload["sources"][0]["pending_streams"] == 0
