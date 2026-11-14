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


def test_registry_respects_exempt_source_and_keeps_overdue_control(tmp_path, monkeypatch):
    reg, paths = registry(tmp_path, monkeypatch)
    for name, exempt in (("Historical", True), ("Recurring", False)):
        page = tmp_path / "memories" / "sources" / f"{name.lower()}.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        fields = {
            "page_id": f"source-{name.lower()}", "page_type": "source", "title": name,
            "last_ingested_at": "2020-01-01", "stale_after_days": 45,
            "stale_exempt": exempt, "refresh_policy": "archival" if exempt else "recurring",
        }
        page.write_text("---\n" + yaml.safe_dump(fields) + "---\n", encoding="utf-8")

    rendered = reg.build_registry(paths, WikiConfig(), "2026-06-10")
    historical = next(line for line in rendered.splitlines() if "[Historical]" in line)
    recurring = next(line for line in rendered.splitlines() if "[Recurring]" in line)
    assert "| — | not time-based | archival |" in historical
    assert "| due | recurring (45d) |" in recurring
    assert "stale_exempt" in historical and "stale_exempt" in recurring
    assert rendered == reg.build_registry(paths, WikiConfig(), "2026-06-10")


@pytest.mark.parametrize("existing, expected", [
    ({"context": "team: research", "moc_parent": "memories/team/index.md"},
     ("team: research", "memories/team/index.md")),
    ({"context": "team", "moc_parent": "memories/team/index.md"},
     ("team", "memories/team/index.md")),
    ({"context": "team"}, ("team", "memories/index.md")),
    (None, ("system", "memories/index.md")),
])
def test_registry_keeps_existing_context_and_parent(tmp_path, monkeypatch, existing, expected):
    reg, paths = registry(tmp_path, monkeypatch)
    if existing is not None:
        paths.source_registry_page.parent.mkdir(parents=True, exist_ok=True)
        paths.source_registry_page.write_text("---\n" + yaml.safe_dump(existing) + "---\n")
    content = reg.build_registry(paths, WikiConfig(), "2026-06-10")
    metadata = yaml.safe_load(content.split("---", 2)[1])
    assert (metadata["context"], metadata["moc_parent"]) == expected
    paths.source_registry_page.parent.mkdir(parents=True, exist_ok=True)
    paths.source_registry_page.write_text(content)
    assert reg.build_registry(paths, WikiConfig(), "2026-06-10") == content


@pytest.mark.parametrize("content", [
    "---\ncontext: team\nmoc_parent: memories/team/index.md\nother: [bad\n---\n",
    "---\ncontext: team\nmoc_parent: memories/team/index.md\n---suffix\n",
])
def test_writer_refuses_invalid_existing_registry_without_mutation(tmp_path, monkeypatch, content):
    reg, paths = registry(tmp_path, monkeypatch)
    target = paths.source_registry_page
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    monkeypatch.setattr(reg.sys, "argv", ["wiki_source_registry.py", "--write"])
    with pytest.raises(ValueError, match="source registry frontmatter"):
        reg.main()
    assert target.read_text(encoding="utf-8") == content


@pytest.mark.parametrize("freshness, expected", [
    ({"default": 30, "system": 7, "team": 90}, 90),
    ({"default": 30, "system": 7, "team": 90, "type:source_registry": 14}, 14),
])
def test_registry_freshness_uses_preserved_context(tmp_path, monkeypatch, freshness, expected):
    reg, paths = registry(tmp_path, monkeypatch)
    paths.source_registry_page.parent.mkdir(parents=True, exist_ok=True)
    paths.source_registry_page.write_text("---\ncontext: team\nmoc_parent: memories/team/index.md\n---\n")
    config = WikiConfig(freshness=freshness)
    metadata = yaml.safe_load(reg.build_registry(paths, config, "2026-06-10").split("---", 2)[1])
    assert metadata["context"] == "team"
    assert metadata["stale_after_days"] == expected
