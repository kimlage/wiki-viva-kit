from __future__ import annotations

from pathlib import Path

from wiki_core.config import WikiConfig
from wiki_core.page_types import load_page_type_registry
from wiki_core.templates import default_output_path, instantiate_template, resolve_template


def test_resolve_and_instantiate_template_with_overlay(tmp_path: Path) -> None:
    (tmp_path / "docs/references/templates/wiki").mkdir(parents=True)
    (tmp_path / "docs/references/templates/overlays").mkdir(parents=True)
    (tmp_path / "docs/references/templates/wiki/perspective.md").write_text(
        "```yaml\n"
        "---\n"
        "page_id: old\n"
        "page_type: perspective\n"
        "title: Old\n"
        "context: old\n"
        "visibility: private_self\n"
        "updated_at: 2000-01-01\n"
        "stale_after_days: 1\n"
        "---\n"
        "```\n"
        "# Body\n",
        encoding="utf-8",
    )
    (tmp_path / "docs/references/templates/overlays/perspective.md").write_text(
        "## Overlay\n\nExtra.\n", encoding="utf-8"
    )
    (tmp_path / "wiki.page-types.yaml").write_text(
        "schema_version: wiki_page_types.v1\n"
        "page_types:\n"
        "  perspective:\n"
        "    template: docs/references/templates/wiki/perspective.md\n"
        "    allowed_dirs:\n"
        "      - memories/system/perspectives\n",
        encoding="utf-8",
    )
    config = WikiConfig(
        templates={
            **WikiConfig().templates,
            "page_type_overrides": {
                "perspective": {"overlay": "docs/references/templates/overlays/perspective.md"}
            },
        }
    )
    registry = load_page_type_registry(tmp_path)
    assert registry is not None

    resolved = resolve_template(tmp_path, config, registry, "perspective")
    text = instantiate_template(resolved, title="Technical Lens", context="system", config=config)

    assert "page_id: perspective-technical-lens" in text
    assert text.count("---") == 2
    assert "page_id: old" not in text
    assert "title: Technical Lens" in text
    assert "template_id: perspective-default" in text
    assert "template_overlay: docs/references/templates/overlays/perspective.md" in text
    assert "## Overlay" in text
    assert default_output_path(registry, "perspective", "Technical Lens") == (
        "memories/system/perspectives/technical-lens.md"
    )
