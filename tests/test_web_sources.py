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
