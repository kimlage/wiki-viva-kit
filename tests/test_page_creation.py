"""Public synthetic creation contracts shared by the CLI and HTTP operator."""
from __future__ import annotations

import concurrent.futures
import shutil
from pathlib import Path

import pytest
import yaml

from wiki_core.action_transition import ActionTransitionError
from wiki_core.frontmatter import parse_frontmatter
from wiki_core.page_creation import create_action_page, create_page, prepare_page


def fixture(root: Path) -> Path:
    kit = Path(__file__).resolve().parents[1]
    (root / "wiki.config.yaml").write_text("repo_id: synthetic\ncontexts: example\ndefault_context: example\npaths:\n  memory_root: notes\n")
    registry = yaml.safe_load((kit / "wiki.page-types.yaml").read_text())
    registry["page_types"]["action"]["allowed_dirs"] = ["notes/tasks"]
    (root / "wiki.page-types.yaml").write_text(yaml.safe_dump(registry))
    target = Path("docs/references/templates/wiki/action.md")
    (root / target.parent).mkdir(parents=True)
    shutil.copy2(kit / target, root / target)
    return root


def request(**extra):
    return {"title": "Synthetic task: one page", "context": "example", "body": "# Evidence\n", "next_action": "Read source", **extra}


def test_shared_creation_uses_configured_paths_and_real_initial_dates(tmp_path: Path) -> None:
    root = fixture(tmp_path)
    result = create_action_page(root, **request())
    assert result["page_ref"] == "notes/tasks/synthetic-task-one-page.md"
    text = (root / result["page_ref"]).read_text()
    values, body = parse_frontmatter(text)
    assert body == "# Evidence\n" and values["title"] == request()["title"]
    assert values["action_state"] == "open" and values["action_state_history"] == []
    assert "due_at" not in values and "owner_ref" not in values
    assert values["created_at"] != "YYYY-MM-DD"
    assert not list(root.rglob("kanban.db"))
    # CLI preparation has the same typed action fixes, not another renderer.
    output, text = prepare_page(root, "action", "Another task", "example")
    assert output == "notes/tasks/another-task.md" and "YYYY-MM-DD" not in text.split("---", 2)[1]


def test_parallel_creation_never_overwrites_or_invents_an_alternative_page(tmp_path: Path) -> None:
    root = fixture(tmp_path)
    def attempt():
        try:
            return create_action_page(root, **request())["page_ref"]
        except ActionTransitionError as exc:
            return exc.code
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert sorted(results) == ["action_already_exists", "notes/tasks/synthetic-task-one-page.md"]
    assert len(list(root.glob("notes/tasks/*.md"))) == 1


def test_creation_rejects_symlink_publication_directory(tmp_path: Path) -> None:
    root = fixture(tmp_path)
    (root / "notes").mkdir()
    (root / "other").mkdir()
    (root / "notes/tasks").symlink_to(root / "other", target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        create_action_page(root, **request())
    assert not list((root / "other").iterdir())


@pytest.mark.parametrize("path", ["../outside.md", "elsewhere/task.md", "notes/../task.md", "/tmp/task.md"])
def test_shared_writer_stays_inside_memory_root(tmp_path: Path, path: str) -> None:
    root = fixture(tmp_path)
    with pytest.raises(ValueError):
        create_page(root, path, "# Synthetic")


@pytest.mark.parametrize("extra,code", [
    ({"context": "other"}, "invalid_context"),
    ({"title": "Invalid\ncontext: other"}, "invalid_page_edit"),
    ({"owner_kind": "agent", "owner_ref": ""}, "invalid_owner_ref"),
    ({"next_action": ""}, "invalid_next_action"),
])
def test_invalid_creation_does_not_publish_a_page(tmp_path: Path, extra: dict, code: str) -> None:
    root = fixture(tmp_path)
    with pytest.raises(ActionTransitionError, match=code):
        create_action_page(root, **request(**extra))
    assert not list(root.glob("notes/tasks/*.md"))


@pytest.mark.parametrize("title", ['Review "source": next step', "Owner's task: review"])
def test_creation_keeps_human_title_punctuation(tmp_path: Path, title: str) -> None:
    root = fixture(tmp_path)
    result = create_action_page(root, **request(title=title))
    values, _ = parse_frontmatter((root / result["page_ref"]).read_text())
    assert values["title"] == title
