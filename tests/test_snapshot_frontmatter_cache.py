"""Compilation reuse is an optimization, not a change to snapshot contents."""
from pathlib import Path

import wiki_core.frontmatter as frontmatter
from wiki_core.config import load_config
from wiki_core.web.snapshot import build_snapshot


def test_snapshot_parity_with_fewer_yaml_parses(tmp_path: Path, monkeypatch):
    (tmp_path / "wiki.config.yaml").write_text("repo_id: synthetic-cache\ndefault_context: system\ncodex:\n  enabled: false\n")
    (tmp_path / "AGENTS.md").write_text("# Synthetic rules\nNo external actions.\n")
    memories = tmp_path / "memories"
    memories.mkdir()
    for number in range(6):
        (memories / f"synthetic-{number}.md").write_text(
            "---\n"
            f"page_id: synthetic-{number}\npage_type: project\ntitle: Synthetic {number}\n"
            "context: system\nvisibility: private_self\nupdated_at: 2026-10-14\n"
            "stale_after_days: 30\nsource_refs: []\n---\n\n# Synthetic project\n"
        )
    config = load_config(tmp_path)
    calls = []
    original = frontmatter.yaml.safe_load

    def tracked(block):
        calls.append(block)
        return original(block)

    monkeypatch.setattr(frontmatter.yaml, "safe_load", tracked)
    kwargs = {"generated_at": "2026-10-14T12:00:00Z"}
    with monkeypatch.context() as disabled:
        disabled.setattr(frontmatter, "_MAX_PARSE_CACHE_ENTRIES", 0)
        expected = build_snapshot(tmp_path, config, **kwargs)
    uncached_calls = len(calls)
    calls.clear()
    actual = build_snapshot(tmp_path, config, **kwargs)
    assert actual == expected
    assert len(calls) < uncached_calls
    assert len(calls) == 6


def test_snapshot_reuses_graph_without_changing_payloads_or_hiding_edits(tmp_path, monkeypatch):
    import wiki_core.quality as quality
    import wiki_core.template_blocks as blocks
    import wiki_core.web.snapshot_projection as projection

    memories = tmp_path / "memories"
    memories.mkdir()
    page = memories / "index.md"
    page.write_text("---\npage_id: root\npage_type: root_entity\n---\n# Root\n[Child](child.md)\n")
    child = memories / "child.md"
    child.write_text("---\npage_id: child\npage_type: project\nmoc_parent: memories/index.md\n---\n# Child\n")
    calls = []
    original = projection.build_page_graph

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    for module in (projection, quality, blocks):
        monkeypatch.setattr(module, "build_page_graph", counted)
    kwargs = {"generated_at": "2026-10-28T12:00:00Z"}
    actual = build_snapshot(tmp_path, **kwargs)
    assert len(calls) == 1

    # Independently rebuild each consumer's graph, as before the optimization.
    with monkeypatch.context() as separate:
        for module, name in ((projection, "_graph_payload"), (quality, "build_quality_report"), (blocks, "blocks_payloads")):
            function = getattr(module, name)

            def rebuild(*args, _function=function, **options):
                options.pop("graph", None)
                return _function(*args, **options)

            separate.setattr(module, name, rebuild)
            if name == "build_quality_report":
                separate.setattr(projection, name, rebuild)
        assert build_snapshot(tmp_path, **kwargs) == actual

    child.write_text(child.read_text() + "\n[New target](new.md)\n")
    (memories / "new.md").write_text("---\npage_id: new\npage_type: project\n---\n# New\n")
    calls.clear()
    changed = build_snapshot(tmp_path, **kwargs)
    assert len(calls) == 1
    assert changed["graph.json"] != actual["graph.json"]
    assert len(changed["pages.json"]["pages"]) == 3
