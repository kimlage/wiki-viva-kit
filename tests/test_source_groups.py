from pathlib import Path

import pytest

from wiki_core.config import WikiConfig
from wiki_core.web.source_groups import (
    apply_source_groups_operation,
    build_source_groups_payload,
    preview_source_groups_operation,
)


def _sources() -> list[dict[str, str]]:
    return [
        {"source_id": "source-local", "platform": "file", "source_kind": "collection"},
        {"source_id": "source-drive", "platform": "drive", "source_kind": "collection"},
        {"source_id": "source-mail", "platform": "gmail", "source_kind": "account"},
        {"source_id": "source-feed", "platform": "web", "source_kind": "endpoint"},
        {"source_id": "source-repo", "platform": "repo", "source_kind": "repository"},
    ]


def test_default_groups_are_operational_not_semantic_channels(tmp_path: Path) -> None:
    payload = build_source_groups_payload(tmp_path, WikiConfig(language="pt"), _sources())

    assert payload["configured"] is False
    groups = {group["id"]: group for group in payload["groups"]}
    assert groups["local"]["label"] == "Pastas locais"
    assert groups["remote-folders"]["source_ids"] == ["source-drive"]
    assert groups["cloud"]["source_ids"] == ["source-mail"]
    assert groups["web"]["source_ids"] == ["source-feed"]
    assert groups["repositories"]["source_ids"] == ["source-repo"]


def test_group_write_is_preview_bound_and_versioned(tmp_path: Path) -> None:
    config = WikiConfig(language="pt")
    groups = build_source_groups_payload(tmp_path, config, _sources())["groups"]
    groups[0]["label"] = "Arquivos neste Mac"
    groups[0]["source_ids"].append("source-mail")
    groups[2]["source_ids"].remove("source-mail")

    preview = preview_source_groups_operation(tmp_path, config, groups, _sources())
    assert preview["ok"] is True
    assert not (tmp_path / "wiki.source-groups.yaml").exists()

    result = apply_source_groups_operation(
        tmp_path,
        config,
        groups,
        _sources(),
        preview["preview_token"],
    )
    assert result["status"] == "applied"
    assert (tmp_path / "wiki.source-groups.yaml").is_file()
    assert (tmp_path / result["receipt_path"]).is_file()
    configured = build_source_groups_payload(tmp_path, config, _sources())
    assert configured["configured"] is True
    assert configured["groups"][0]["label"] == "Arquivos neste Mac"
    assert "source-mail" in configured["groups"][0]["source_ids"]


def test_group_write_rejects_duplicate_or_unassigned_sources(tmp_path: Path) -> None:
    config = WikiConfig()
    groups = build_source_groups_payload(tmp_path, config, _sources())["groups"]
    groups[1]["source_ids"].append("source-local")
    with pytest.raises(ValueError, match="source_groups_duplicate_source"):
        preview_source_groups_operation(tmp_path, config, groups, _sources())

    groups = build_source_groups_payload(tmp_path, config, _sources())["groups"]
    groups[0]["source_ids"].remove("source-local")
    with pytest.raises(ValueError, match="source_groups_unassigned_source"):
        preview_source_groups_operation(tmp_path, config, groups, _sources())


def test_new_source_is_added_without_overwriting_custom_grouping(tmp_path: Path) -> None:
    config = WikiConfig()
    base_sources = _sources()
    groups = build_source_groups_payload(tmp_path, config, base_sources)["groups"]
    groups[0]["label"] = "My machine"
    preview = preview_source_groups_operation(tmp_path, config, groups, base_sources)
    apply_source_groups_operation(tmp_path, config, groups, base_sources, preview["preview_token"])

    expanded_sources = [*base_sources, {"source_id": "source-new", "platform": "drive", "source_kind": "collection"}]
    payload = build_source_groups_payload(tmp_path, config, expanded_sources)
    by_id = {group["id"]: group for group in payload["groups"]}
    assert by_id["local"]["label"] == "My machine"
    assert "source-new" in by_id["remote-folders"]["source_ids"]
