from __future__ import annotations

from pathlib import Path

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
