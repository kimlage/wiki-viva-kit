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
