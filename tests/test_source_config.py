from __future__ import annotations

from pathlib import Path

import pytest

from wiki_core.config import WikiConfig
from wiki_core.source_config import find_source_config, merge_perspectives


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_find_source_config_uses_source_config_ref(tmp_path: Path) -> None:
    cfg = WikiConfig(contexts=("example",))
    _write(
        tmp_path / "memories/sources/example.md",
        """---
page_id: source-example
page_type: source
context: example
config_ref: memories/sources/config/example.md
---

# Source
""",
    )
    _write(
        tmp_path / "memories/sources/config/example.md",
        """---
page_id: source-config-example
page_type: source_config
context: example
source_refs:
  - source-example
perspectives_required:
  - perspective-technical
perspectives_optional:
  - perspective-project
---

# Config
""",
    )

    found = find_source_config(tmp_path, cfg, "memories/sources/example.md")

    assert found == {
        "path": "memories/sources/config/example.md",
        "page_id": "source-config-example",
        "perspectives_required": ["perspective-technical"],
        "perspectives_optional": ["perspective-project"],
        "perspectives_skip_with_reason": [],
        "input_channel_ref": "",
        "process_refs": [],
        "target_pages": [],
        "quadrants": [],
    }


def test_find_source_config_falls_back_to_source_refs(tmp_path: Path) -> None:
    cfg = WikiConfig(contexts=("example",))
    _write(
        tmp_path / "memories/sources/example.md",
        """---
page_id: source-example
page_type: source
context: example
---

# Source
""",
    )
    _write(
        tmp_path / "memories/sources/config/example.md",
        """---
page_id: source-config-example
page_type: source_config
context: example
source_refs:
  - source-example
perspectives_required:
  - perspective-operations
perspectives_optional: []
---

# Config
""",
    )

    found = find_source_config(tmp_path, cfg, str(tmp_path / "memories/sources/example.md"))

    assert found is not None
    assert found["perspectives_required"] == ["perspective-operations"]


def test_merge_perspectives_keeps_required_authoritative_and_inherits() -> None:
    merged_required, merged_optional = merge_perspectives(
        {
            "perspectives_required": ["perspective-technical"],
            "perspectives_optional": ["perspective-project", "perspective-ops"],
            "perspectives_skip_with_reason": ["perspective-root-skip"],
        },
        root_required=["perspective-root", "perspective-root-skip"],
        root_optional=["perspective-root-optional"],
        channel_required=["perspective-channel"],
        channel_optional=["perspective-channel-optional"],
        required=["perspective-project"],
        optional=["perspective-technical", "perspective-extra"],
    )

    assert merged_required == [
        "perspective-root",
        "perspective-channel",
        "perspective-technical",
        "perspective-project",
    ]
    assert merged_optional == [
        "perspective-root-optional",
        "perspective-channel-optional",
        "perspective-ops",
        "perspective-extra",
    ]


@pytest.mark.parametrize('boundary', ['escape', 'symlink-file', 'symlink-directory', 'git-file', 'git-directory'])
def test_source_config_references_cannot_cross_wiki_boundaries(tmp_path, monkeypatch, boundary):
    from tests.test_context_collections import page
    config = WikiConfig()
    source = page(tmp_path / 'memories/team/nested/sources/evidence.md', 'source-one', 'source')
    recipe = page(tmp_path / 'memories/other/config/recipe.md', 'recipe', 'source_config')
    ref = recipe.relative_to(tmp_path).as_posix()
    if boundary == 'escape':
        ref = 'memories/../' + ref
    elif boundary == 'symlink-file':
        recipe.rename(recipe.with_name('saved.md'))
        recipe.symlink_to(recipe.with_name('saved.md'))
    elif boundary == 'symlink-directory':
        recipe.parent.rename(recipe.parent.with_name('saved'))
        recipe.parent.symlink_to(recipe.parent.with_name('saved'), target_is_directory=True)
    elif boundary == 'git-file':
        (recipe.parent / '.git').write_text('gitdir: synthetic-separate-repo')
    else:
        (recipe.parent / '.git').mkdir()
    source.write_text(source.read_text().replace('page_type: source\n', f'page_type: source\nconfig_ref: {ref}\n'))
    original = Path.read_text
    def guarded(path, *args, **kwargs):
        if path != source:
            pytest.fail('unsafe config body read')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', guarded)
    assert find_source_config(tmp_path, config, source.relative_to(tmp_path).as_posix()) is None


def test_fallback_checks_own_context_then_global_without_unrelated_context(tmp_path, monkeypatch):
    from tests.test_context_collections import page
    config = WikiConfig()
    source = page(tmp_path / 'memories/team/nested/sources/evidence.md', 'source-one', 'source')
    local = page(source.parent / 'config/local.md', 'config-local', 'source_config', source_refs=['source-one'])
    global_config = page(tmp_path / 'memories/sources/config/global.md', 'config-global', 'source_config', source_refs=['source-one'])
    unrelated = page(tmp_path / 'memories/other/sources/config/unrelated.md', 'unrelated', 'source_config', source_refs=['source-one'])
    original = Path.read_text
    def guarded(path, *args, **kwargs):
        if path == unrelated:
            pytest.fail('unrelated context config read')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', guarded)
    ref = source.relative_to(tmp_path).as_posix()
    assert find_source_config(tmp_path, config, ref)['page_id'] == 'config-local'
    local.unlink()
    assert find_source_config(tmp_path, config, ref)['page_id'] == 'config-global'
    global_config.unlink()
    assert find_source_config(tmp_path, config, ref) is None
