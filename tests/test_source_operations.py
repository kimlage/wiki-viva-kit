from pathlib import Path

import pytest

from wiki_core.config import WikiConfig
from wiki_core.web.source_operations import (
    _inventory_diff,
    apply_source_operation,
    preview_source_operation,
    preview_source_refresh,
    run_source_refresh,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _repo(tmp_path: Path) -> WikiConfig:
    _write(
        tmp_path / "memories/sources/source-a.md",
        """---
page_id: source-a
page_type: source
title: Source A
context: system
visibility: private_self
updated_at: 2026-08-26
stale_after_days: 30
config_ref: memories/sources/config/source-a.md
platform: drive
source_locator: folder-a
sync: {last_run_at: '2026-08-26', last_status: ok, last_event_ref: ''}
---
# Source A
""",
    )
    _write(
        tmp_path / "memories/sources/config/source-a.md",
        """---
page_id: source-config-a
page_type: source_config
title: Config A
context: system
visibility: private_self
updated_at: 2026-08-26
stale_after_days: 30
---
# Config A

```yaml
recipe:
  schema_version: wiki_source_recipe.v1
  platform: drive
  locator: folder-a
  source_kind: collection
  pipelines:
  - kind: metadata
    cadence_days: 7
  streams:
  - id: file-a
    label: File A
    selected: true
    filters:
      file_id: drive-123
      processing_state: discovered
    privacy: private_self
    target_pages:
    - memories/index.md
    skip_reason: ''
    cadence_days: 7
  how_to_export: List Drive folder metadata.
  ingest:
    argv: []
    mcp_hint: google-drive
  auth:
    method: mcp
    ref: google-drive
    scopes: [read]
    note: ''
  schedule:
    mode: recurring
    cadence_days: 7
    cron_hint: ''
```
""",
    )
    return WikiConfig(
        paths={**WikiConfig().paths, "memories": "memories", "sources": "memories/sources", "derived": "data/derived/wiki"}
    )


def test_preview_is_content_bound_and_exposes_raw_inventory(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    result = preview_source_operation(
        tmp_path, config, "source-a", "file-a", {"processing_state": "reviewed", "cadence_days": 14}
    )
    assert result["ok"] is True
    assert result["execution"]["mode"] == "agent_connector"
    assert result["raw_inventory"]["filters"]["file_id"] == "drive-123"
    assert {change["field"] for change in result["changes"]} == {"processing_state", "cadence_days"}
    assert len(result["preview_token"]) == 64
    assert "reviewed" not in (tmp_path / result["config_ref"]).read_text(encoding="utf-8")


def test_apply_requires_exact_preview_and_writes_receipt(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    updates = {"label": "Reviewed file", "selected": False, "skip_reason": "Covered elsewhere"}
    preview = preview_source_operation(tmp_path, config, "source-a", "file-a", updates)
    result = apply_source_operation(tmp_path, config, "source-a", "file-a", updates, preview["preview_token"])
    assert result["status"] == "applied"
    assert Path(tmp_path / result["receipt_path"]).is_file()
    text = (tmp_path / result["config_ref"]).read_text(encoding="utf-8")
    assert "Reviewed file" in text
    assert "Covered elsewhere" in text
    assert result["source"]["streams"][0]["selected"] is False


def test_source_scope_can_change_type_and_disable_time_based_staleness(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    updates = {"source_kind": "item", "schedule_mode": "one_shot", "schedule_cadence_days": 0}
    preview = preview_source_operation(tmp_path, config, "source-a", "__source__", updates)
    assert preview["raw_inventory"]["scope"] == "source"
    assert {change["field"] for change in preview["changes"]} == set(updates)
    result = apply_source_operation(tmp_path, config, "source-a", "__source__", updates, preview["preview_token"])
    assert result["source"]["source_kind"] == "item"
    assert result["source"]["schedule"] == {"mode": "one_shot", "cadence_days": 0, "cron_hint": ""}
    assert result["source"]["pending_streams"] == 1
    assert result["source"]["streams"][0]["freshness_basis"] == "processing_state"


def test_source_scope_rejects_cadence_for_non_recurring_lifecycle(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    with pytest.raises(ValueError, match="source_operation_non_recurring_cadence"):
        preview_source_operation(
            tmp_path,
            config,
            "source-a",
            "__source__",
            {"schedule_mode": "one_shot", "schedule_cadence_days": 7},
        )


def test_apply_rejects_stale_preview(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    updates = {"label": "Reviewed file"}
    preview = preview_source_operation(tmp_path, config, "source-a", "file-a", updates)
    config_path = tmp_path / preview["config_ref"]
    config_path.write_text(config_path.read_text(encoding="utf-8") + "\nexternal edit\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source_operation_preview_stale"):
        apply_source_operation(tmp_path, config, "source-a", "file-a", updates, preview["preview_token"])


def test_unknown_and_unsafe_fields_are_rejected(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    with pytest.raises(ValueError, match="source_operation_unknown_field"):
        preview_source_operation(tmp_path, config, "source-a", "file-a", {"argv": ["rm", "-rf"]})
    with pytest.raises(ValueError, match="source_operation_invalid_targets"):
        preview_source_operation(tmp_path, config, "source-a", "file-a", {"target_pages": ["../outside"]})


def test_refresh_preview_for_connector_is_honest_and_not_locally_runnable(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    result = preview_source_refresh(tmp_path, config, "source-a", "file-a")
    assert result["execution"]["mode"] == "agent_connector"
    assert result["execution"]["requires_agent"] is True
    assert result["execution"]["runnable"] is False
    with pytest.raises(ValueError, match="requires_agent_or_manual_export"):
        run_source_refresh(tmp_path, config, "source-a", "file-a", "", result["preview_token"])


def test_refresh_runs_only_allowlisted_script_against_hashed_raw(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    config_path = tmp_path / "memories/sources/config/source-a.md"
    text = config_path.read_text(encoding="utf-8")
    text = text.replace("argv: []\n    mcp_hint: google-drive", "argv: [python3, scripts/ingest_test.py, --source, '{path}']\n    mcp_hint: ''")
    config_path.write_text(text, encoding="utf-8")
    _write(tmp_path / "scripts/ingest_test.py", "import sys\nprint('ingested', sys.argv[-1])\n")
    _write(tmp_path / "data/raw/input.txt", "raw evidence\n")

    preview = preview_source_refresh(tmp_path, config, "source-a", "file-a", "data/raw/input.txt")
    assert preview["execution"]["mode"] == "script"
    assert preview["raw_inventory"]["local_raw"]["sha256"]
    result = run_source_refresh(
        tmp_path, config, "source-a", "file-a", "data/raw/input.txt", preview["preview_token"]
    )
    assert result["ok"] is True
    assert result["status"] == "script_complete"
    assert "ingested" in result["stdout"]
    assert (tmp_path / result["receipt_path"]).is_file()


def _enable_inventory_adapter(tmp_path: Path, records: list[dict[str, object]]) -> None:
    config_path = tmp_path / "memories/sources/config/source-a.md"
    text = config_path.read_text(encoding="utf-8")
    text = text.replace(
        "  ingest:\n    argv: []\n    mcp_hint: google-drive\n",
        "  refresh:\n    argv: [python3, scripts/inventory_test.py, --source, '{source_id}', --locator, '{locator}']\n"
        "  ingest:\n    argv: []\n    mcp_hint: google-drive\n",
    )
    config_path.write_text(text, encoding="utf-8")
    payload = {
        "schema_version": "wiki_source_inventory.v1",
        "source_id": "source-a",
        "locator": "folder-a",
        "records": records,
    }
    _write(
        tmp_path / "scripts/inventory_test.py",
        "import json\n"
        f"print(json.dumps({payload!r}, sort_keys=True))\n",
    )


def test_deterministic_connector_previews_collection_diff_and_applies_selected_records(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    _enable_inventory_adapter(
        tmp_path,
        [
            {
                "external_id": "drive-123",
                "label": "File A",
                "filters": {"file_id": "drive-123"},
            },
            {
                "external_id": "drive-456",
                "label": "New recording.m4a",
                "filters": {"file_id": "drive-456", "mime_type": "audio/mp4", "size_bytes": 42},
            },
        ],
    )

    preview = preview_source_refresh(tmp_path, config, "source-a")

    assert preview["execution"]["mode"] == "deterministic_connector"
    assert preview["execution"]["runnable"] is True
    assert preview["discovery"]["counts"] == {"new": 1, "changed": 0, "enriched": 0, "unchanged": 1}
    assert preview["raw_inventory"]["external_inventory"]["records"][1]["external_id"] == "drive-456"

    result = run_source_refresh(
        tmp_path,
        config,
        "source-a",
        "__source__",
        "",
        preview["preview_token"],
        ["drive-456"],
    )

    assert result["ok"] is True
    assert result["status"] == "inventory_applied"
    assert result["summary"] == {"new": 1, "changed": 0, "enriched": 0, "unchanged": 1, "applied": 1}
    assert result["source"]["pending_streams"] == 2
    added = next(stream for stream in result["source"]["streams"] if stream["filters"].get("external_id") == "drive-456")
    assert added["filters"]["processing_state"] == "discovered"
    assert added["target_pages"] == ["memories/index.md"]


def test_deterministic_connector_records_an_honest_no_change_check(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    _enable_inventory_adapter(
        tmp_path,
        [{"external_id": "drive-123", "label": "File A", "filters": {"file_id": "drive-123"}}],
    )
    preview = preview_source_refresh(tmp_path, config, "source-a")
    result = run_source_refresh(tmp_path, config, "source-a", "__source__", "", preview["preview_token"], [])
    assert result["status"] == "inventory_no_change"
    assert result["changed_files"] == []
    assert Path(tmp_path / result["receipt_path"]).is_file()


def test_deterministic_connector_enriches_metadata_without_reopening_ingestion(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    _enable_inventory_adapter(
        tmp_path,
        [{"external_id": "drive-123", "label": "File A", "filters": {"file_id": "drive-123", "md5_checksum": "abc", "size_bytes": 42}}],
    )
    preview = preview_source_refresh(tmp_path, config, "source-a")
    assert preview["discovery"]["counts"] == {"new": 0, "changed": 0, "enriched": 1, "unchanged": 0}
    result = run_source_refresh(tmp_path, config, "source-a", "__source__", "", preview["preview_token"], ["drive-123"])
    stream = result["source"]["streams"][0]
    assert result["summary"]["enriched"] == 1
    assert stream["filters"]["processing_state"] == "discovered"
    assert stream["filters"]["md5_checksum"] == "abc"


def test_inventory_diff_uses_content_fingerprint_not_modified_timestamp() -> None:
    source = {
        "streams": [
            {
                "id": "file-a",
                "label": "File A",
                "filters": {"external_id": "drive-123", "md5_checksum": "abc", "modified_at": "old"},
            }
        ]
    }
    inventory = {
        "records": [
            {
                "external_id": "drive-123",
                "label": "File A",
                "filters": {"md5_checksum": "abc", "modified_at": "new"},
            }
        ]
    }
    assert _inventory_diff(source, inventory)["records"][0]["status"] == "enriched"
    inventory["records"][0]["filters"]["md5_checksum"] = "def"
    assert _inventory_diff(source, inventory)["records"][0]["status"] == "changed"
