"""Public synthetic coverage for every derived queue projection."""
from pathlib import Path

import pytest

from scripts import wiki_operation_compile
from wiki_core.action_queue import DERIVED_POINTER
from wiki_core.config import WikiConfig
from wiki_core.operational_pass import build_operational_pass_page, build_operational_pass_report, pending_action_ids
from wiki_core.paths import WikiPaths


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def action(page_id: str, state: str, extra: str) -> str:
    return (f"---\npage_type: action\npage_id: {page_id}\ntitle: {page_id}\n"
            f"context: example\naction_state: {state}\n{extra}---\n\n# {page_id}\n")


@pytest.fixture
def queue_repo(tmp_path):
    directory = tmp_path / "memories" / "actions"
    write(directory / "pending.md", f"---\npage_type: index\n---\n\n{DERIVED_POINTER}\n")
    write(directory / "open.md", action("action-open", "open", "next_action: work\n"))
    write(directory / "waiting.md", action("action-waiting", "waiting_human", "next_action: ask\n"))
    write(directory / "done.md", action("action-done", "done", "completed_at: 2026-01-01\ncompletion_receipt: test\n"))
    write(directory / "cancelled.md", action("action-cancelled", "cancelled", "completed_at: 2026-01-01\ncancellation_receipt: test\n"))
    return tmp_path, WikiConfig(repo_id="synthetic", owner_label="Owner")


def test_pointer_projections_use_exact_active_inventory(queue_repo):
    root, config = queue_repo
    expected = ["action-open", "action-waiting"]
    cockpit = wiki_operation_compile.build_page(root, config)
    section = cockpit.split("## Pending action queue", 1)[1].split("## ", 1)[0]
    assert [line.strip("- `") for line in section.splitlines() if line.startswith("- `")] == expected
    report = build_operational_pass_report(root, config)
    assert list(report.pending_ids) == expected
    operational = build_operational_pass_page(root, config)
    primary = operational.split("### Primary actions", 1)[1].split("### ", 1)[0]
    assert "../actions/open.md" in primary and "../actions/waiting.md" in primary
    assert "../actions/done.md" not in primary and "../actions/cancelled.md" not in primary
    assert "`action-done`" not in section and "`action-cancelled`" not in section


def test_legacy_materialized_queue_is_never_read_by_queue_readers(queue_repo, monkeypatch):
    root, config = queue_repo
    pointer = root / "memories/actions/pending.md"
    write(pointer, "---\npage_type: index\n---\n\n# Pending\n\n- `action-phantom`\n")
    original = Path.read_text

    def read_text(path, *args, **kwargs):
        if path == pointer:
            raise AssertionError("queue readers must not read the materialized page")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    paths = WikiPaths(root, config)
    assert wiki_operation_compile.pending_action_ids(paths) == ["action-open", "action-waiting"]
    assert pending_action_ids(paths) == ("action-open", "action-waiting")


def test_empty_and_invalid_inventory_fail_safely(queue_repo):
    root, config = queue_repo
    for path in (root / "memories/actions").glob("*.md"):
        if path.name != "pending.md":
            path.unlink()
    assert wiki_operation_compile.pending_action_ids(WikiPaths(root, config)) == []
    assert build_operational_pass_report(root, config).pending_ids == ()
    write(root / "memories/actions/bad.md", action("action-bad", "bogus", ""))
    with pytest.raises(ValueError, match="invalid action_state"):
        wiki_operation_compile.build_page(root, config)
    with pytest.raises(ValueError, match="invalid action_state"):
        build_operational_pass_report(root, config)


def test_legacy_actions_and_materialized_queue_migrate_without_stale_rows(queue_repo):
    root, config = queue_repo
    directory = root / "memories/actions"
    write(directory / "legacy.md", "---\npage_type: action\npage_id: action-legacy\n"
          "context: example\n---\n\n# Legacy\n\nState: `pending`.\n")
    write(directory / "pending.md", "---\npage_type: index\n---\n\n# Pending\n\n- `action-phantom`\n")
    expected = {"action-open", "action-waiting", "action-legacy"}
    for body in ("# Pending\n\n- `action-phantom`", DERIVED_POINTER):
        write(directory / "pending.md", "---\npage_type: index\n---\n\n" + body + "\n")
        cockpit = wiki_operation_compile.build_page(root, config)
        section = cockpit.split("## Pending action queue", 1)[1].split("## ", 1)[0]
        assert {line.strip("- `") for line in section.splitlines() if line.startswith("- `")} == expected
        assert set(build_operational_pass_report(root, config).pending_ids) == expected
        assert "action-phantom" not in section
