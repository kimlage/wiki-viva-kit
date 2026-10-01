from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

from wiki_core.config import WikiConfig
from wiki_core.paths import WikiPaths


def registry(tmp_path, monkeypatch, policy=None):
    path = Path(__file__).resolve().parents[1] / "scripts/wiki_source_registry.py"
    spec = importlib.util.spec_from_file_location("registry_policy_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = {"language": "en"}
    if policy is not None:
        config["source_registry"] = policy
    (tmp_path / "wiki.config.yaml").write_text(yaml.safe_dump(config))
    monkeypatch.setattr(module, "ROOT", tmp_path)
    return module, WikiPaths(tmp_path, WikiConfig())


def source(root, rel, page_id, page_type="source"):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\n" + yaml.safe_dump({"page_id": page_id, "page_type": page_type}) + "---\n")


def test_declared_nested_policy_and_exact_collection_are_preserved(tmp_path, monkeypatch):
    reg, paths = registry(tmp_path, monkeypatch, {"nested_sources": ["memories/sources/channel/allowed.md"]})
    source(tmp_path, "memories/sources/direct.md", "source-direct")
    source(tmp_path, "memories/sources/channel/allowed.md", "source-allowed")
    source(tmp_path, "memories/sources/channel/other.md", "source-other")
    source(tmp_path, "memories/sources/catalog.md", "catalog", "source_catalog")
    source(tmp_path, "memories/sources/evidence.md", "evidence", "artifact")
    expected = ["source-allowed", "source-direct"]
    assert [r["page_id"] for r in reg.collect_sources(paths, "2026-06-10")] == expected
    rendered = reg.build_registry(paths, WikiConfig(), "2026-06-10")
    assert rendered == reg.build_registry(paths, WikiConfig(), "2026-06-10")
    metadata = yaml.safe_load(rendered.split("---", 2)[1])
    assert metadata["collection"] == {"member_types": [], "contexts": [], "members": expected}
    assert "source-other" not in rendered and "catalog.md" not in rendered and "evidence.md" not in rendered


def test_no_policy_keeps_recursive_default_and_empty_policy_is_closed(tmp_path, monkeypatch):
    reg, paths = registry(tmp_path, monkeypatch)
    source(tmp_path, "memories/sources/nested/one.md", "source-one")
    assert [r["page_id"] for r in reg.collect_sources(paths)] == ["source-one"]
    (tmp_path / "wiki.config.yaml").write_text("language: en\nsource_registry:\n  nested_sources: []\n")
    assert reg.collect_sources(paths) == []
    metadata = yaml.safe_load(reg.build_registry(paths, WikiConfig(), "2026-06-10").split("---", 2)[1])
    assert metadata["collection"]["members"] == []


@pytest.mark.parametrize("present", [False, True])
def test_missing_or_non_source_allowlist_entry_is_rejected(tmp_path, monkeypatch, present):
    rel = "memories/sources/nested/missing.md"
    reg, paths = registry(tmp_path, monkeypatch, {"nested_sources": [rel]})
    if present:
        source(tmp_path, rel, "not-source", "source_catalog")
    with pytest.raises(ValueError, match="missing or non-source"):
        reg.collect_sources(paths)


@pytest.mark.parametrize("policy", ["invalid", {"nested_sources": "invalid"}, {"nested_sources": [1]}, {"nested_sources": [""]}])
def test_malformed_policy_is_rejected(tmp_path, monkeypatch, policy):
    reg, paths = registry(tmp_path, monkeypatch, policy)
    with pytest.raises(ValueError, match="source_registry"):
        reg.collect_sources(paths)


def test_duplicate_or_missing_source_id_is_rejected(tmp_path, monkeypatch):
    reg, paths = registry(tmp_path, monkeypatch)
    source(tmp_path, "memories/sources/one.md", "same-id")
    source(tmp_path, "memories/sources/two.md", "same-id")
    with pytest.raises(ValueError, match="duplicate page_id"):
        reg.collect_sources(paths)
    source(tmp_path, "memories/sources/two.md", "")
    with pytest.raises(ValueError, match="missing page_id"):
        reg.collect_sources(paths)


def test_collection_keeps_string_ids_through_yaml_serialization(tmp_path, monkeypatch):
    reg, paths = registry(tmp_path, monkeypatch)
    source(tmp_path, "memories/sources/one.md", "123")
    metadata = yaml.safe_load(reg.build_registry(paths, WikiConfig(), "2026-06-10").split("---", 2)[1])
    assert metadata["collection"]["members"] == ["123"]
