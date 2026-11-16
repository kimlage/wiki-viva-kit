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


def test_pointer_contract_matches_both_full_gates(tmp_path, monkeypatch, capsys):
    import os
    import subprocess
    import sys

    from scripts import wiki_action_queue

    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    write(tmp_path / "wiki.config.yaml", "repo_id: synthetic\nowner_label: Test\n"
          "approval:\n  require_log_update: false\naudit:\n  core_pages: []\n")
    metadata = ("---\npage_id: queue\npage_type: ontology_index\ncontext: system\n"
                "visibility: private_self\nupdated_at: 2026-11-15\nstale_after_days: 30\n"
                "sources_policy: test\ngate: github_pr\n"
                "sensitive_data_policy: private_sensitive_allowed\n")
    pointer = tmp_path / "memories/actions/pending.md"
    write(pointer, metadata + "---\n\n" + DERIVED_POINTER + "\n")
    write(tmp_path / "memories/operations.md", metadata.replace("page_id: queue", "page_id: operations")
          .replace("page_type: ontology_index", "page_type: dashboard")
          .replace("stale_after_days: 30", "stale_after_days: 1")
          + "purpose: synthetic test\n---\n\n# Operations\n")
    write(tmp_path / "memories/system/ingestion/events/.gitkeep", "")
    git("add", ".")
    git("-c", "user.name=Test", "-c", "user.email=test@example.org", "commit", "-qm", "base")
    monkeypatch.setattr(wiki_action_queue, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["wiki_action_queue.py", "--check", "--base", "main"])

    def both_gates():
        queue_result = wiki_action_queue.main()
        capsys.readouterr()
        env = {**os.environ, "WIKI_INSTALLED_CONTENT_ROOT": str(tmp_path)}
        result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] /
                               "scripts/wiki_audit.py"), "--check"], env=env, cwd=tmp_path,
                                text=True, capture_output=True, check=False)
        return queue_result, result

    queue_result, audit = both_gates()
    assert queue_result == 0
    assert audit.returncode == 0, audit.stdout + audit.stderr
    for altered in (
        metadata + "actions: [action-phantom]\n---\n\n" + DERIVED_POINTER + "\n",
        metadata + "---\n\n" + DERIVED_POINTER + "\nExtra text\n",
        metadata + "---\n\n" + DERIVED_POINTER + "\n| Action | State |\n| --- | --- |\n| x | open |\n",
    ):
        write(pointer, altered)
        queue_result, audit = both_gates()
        assert queue_result == 1
        assert audit.returncode == 1
        assert "queue must contain only the exact derived pointer" in audit.stdout or \
               "pointer contains unsupported or materialized metadata" in audit.stdout
