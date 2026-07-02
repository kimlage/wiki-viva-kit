from __future__ import annotations

import subprocess
import time
from pathlib import Path

from wiki_core.config import WikiConfig, load_config
from wiki_core.web.briefs import BriefStore, compose_brief
from wiki_core.web.codex_jobs import JobRunner, build_codex_argv
from wiki_core.web.snapshot import build_snapshot

SHIM = str(Path(__file__).parent / "fixtures" / "codex_shim.py")
SNAPSHOT_AT = "2026-07-01"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _repo(root: Path) -> WikiConfig:
    subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@e.test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=root, check=True)
    # The derived tree (briefs, jobs, snapshots) is git-ignored just like the
    # real repo, so writing a brief never dirties the worktree.
    _write(root / ".gitignore", "data/derived/\n")
    _write(root / "AGENTS.md", "# Agents\n")
    _write(root / "wiki.config.yaml", "repo_id: jobs-test\ndefault_context: system\n")
    _write(
        root / "memories/index.md",
        """---
page_id: root
page_type: root_index
title: "Root"
context: system
visibility: private_self
updated_at: 2026-01-01
stale_after_days: 30
---

# Root

Body to edit.
""",
    )
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=root, check=True, capture_output=True)
    return load_config(root)


def _saved_brief(root: Path, config: WikiConfig):
    snapshot = build_snapshot(root, config, mode="local_operator", generated_at=SNAPSHOT_AT)
    composed = compose_brief(root, config, snapshot, spec={"mission_kind": "refresh", "theme": "fix root",
                                                           "grounding": {"page_ids": ["root"]}})
    return BriefStore(root, config).save_new(composed)


def _runner(root: Path, config: WikiConfig, *, autostart: bool = False, **env) -> JobRunner:
    return JobRunner(root, config, codex_cmd=["python3", SHIM], timeout_seconds=30, autostart=autostart)


def test_build_argv_is_sandboxed_and_never_yolo() -> None:
    argv = build_codex_argv("codex", Path("/repo"), Path("/repo/final.md"))
    assert argv[:3] == ["codex", "exec", "-"]
    assert "--sandbox" in argv and "workspace-write" in argv
    assert "--json" in argv
    assert not any("yolo" in a or "dangerous" in a for a in argv)


def test_pipeline_dry_run_reaches_delivered(tmp_path, monkeypatch) -> None:
    config = _repo(tmp_path)
    brief = _saved_brief(tmp_path, config)
    runner = _runner(tmp_path, config)
    result = runner.submit(brief_id=brief["brief_id"], brief_sha=brief["brief_sha"], dry_run=True)
    assert result["ok"] is True
    job_id = result["job_id"]
    runner.run_job(job_id)  # synchronous (autostart off)
    record = runner.get(job_id)
    assert record["status"] == "delivered"
    assert record["branch"].startswith("wiki/")
    assert record["draft_pr_url"] is None  # dry run: local branch only
    # A real commit exists on the proposal branch.
    log = subprocess.run(["git", "log", "--oneline", "-1"], cwd=tmp_path, capture_output=True, text=True)
    assert "codex:" in log.stdout
    # The brief page was actually edited by the shim.
    assert "codex shim edit" in (tmp_path / "memories/index.md").read_text()


def test_sha_mismatch_rejected(tmp_path) -> None:
    config = _repo(tmp_path)
    brief = _saved_brief(tmp_path, config)
    runner = _runner(tmp_path, config)
    result = runner.submit(brief_id=brief["brief_id"], brief_sha="deadbeef", dry_run=True)
    assert result["ok"] is False
    assert result["reason"] == "sha_mismatch"


def test_stale_targets_blocked_then_forced(tmp_path) -> None:
    config = _repo(tmp_path)
    brief = _saved_brief(tmp_path, config)
    # Move the wiki under the brief.
    (tmp_path / "memories/index.md").write_text("changed after compose\n", encoding="utf-8")
    runner = _runner(tmp_path, config)
    blocked = runner.submit(brief_id=brief["brief_id"], brief_sha=brief["brief_sha"], dry_run=True)
    assert blocked["ok"] is False and blocked["reason"] == "targets_stale"
    # Commit so the worktree is clean, then force past the guard.
    subprocess.run(["git", "commit", "-am", "moved the page"], cwd=tmp_path, check=True, capture_output=True)
    forced = runner.submit(brief_id=brief["brief_id"], brief_sha=brief["brief_sha"], dry_run=True, force=True)
    assert forced["ok"] is True


def test_no_edit_fails_honestly(tmp_path, monkeypatch) -> None:
    config = _repo(tmp_path)
    brief = _saved_brief(tmp_path, config)
    monkeypatch.setenv("CODEX_SHIM_NOEDIT", "1")
    runner = _runner(tmp_path, config)
    result = runner.submit(brief_id=brief["brief_id"], brief_sha=brief["brief_sha"], dry_run=True)
    runner.run_job(result["job_id"])
    record = runner.get(result["job_id"])
    assert record["status"] == "failed"
    assert "no file change" in record["reason"].lower()


def test_codex_failure_aborts_branch(tmp_path, monkeypatch) -> None:
    config = _repo(tmp_path)
    brief = _saved_brief(tmp_path, config)
    monkeypatch.setenv("CODEX_SHIM_RC", "3")
    runner = _runner(tmp_path, config)
    result = runner.submit(brief_id=brief["brief_id"], brief_sha=brief["brief_sha"], dry_run=True)
    runner.run_job(result["job_id"])
    record = runner.get(result["job_id"])
    assert record["status"] == "failed"
    assert "codex exited 3" in record["reason"]
    # The failed run left the checkout back on main, not stranded on wiki/.
    branch = subprocess.run(["git", "branch", "--show-current"], cwd=tmp_path, capture_output=True, text=True)
    assert branch.stdout.strip() == "main"


def test_log_is_redacted(tmp_path, monkeypatch) -> None:
    config = _repo(tmp_path)
    brief = _saved_brief(tmp_path, config)
    monkeypatch.setenv("CODEX_SHIM_LEAK", "1")
    runner = _runner(tmp_path, config)
    result = runner.submit(brief_id=brief["brief_id"], brief_sha=brief["brief_sha"], dry_run=True)
    runner.run_job(result["job_id"])
    log = runner.read_log(result["job_id"])
    assert "[REDACTED]" in log
    # Both the KEY=value and JSON "key":"value" forms must be scrubbed.
    assert "sk-test1234567890" not in log
    assert "sk-jsonleak0987654321" not in log


def test_commit_hook_failure_unwinds_the_branch(tmp_path) -> None:
    config = _repo(tmp_path)
    brief = _saved_brief(tmp_path, config)
    # A pre-commit hook that always rejects the commit.
    hook = tmp_path / ".git/hooks/pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    runner = _runner(tmp_path, config)
    result = runner.submit(brief_id=brief["brief_id"], brief_sha=brief["brief_sha"], dry_run=True)
    runner.run_job(result["job_id"])
    record = runner.get(result["job_id"])
    assert record["status"] == "failed"
    assert "commit" in record["reason"]
    # The failed commit must NOT strand the checkout on the proposal branch.
    branch = subprocess.run(["git", "branch", "--show-current"], cwd=tmp_path, capture_output=True, text=True)
    assert branch.stdout.strip() == "main"
    status = subprocess.run(["git", "status", "--porcelain"], cwd=tmp_path, capture_output=True, text=True)
    assert status.stdout.strip() == ""  # no staged edits left behind


def test_brief_tampered_on_disk_after_submit_is_blocked(tmp_path) -> None:
    config = _repo(tmp_path)
    brief = _saved_brief(tmp_path, config)
    runner = _runner(tmp_path, config)
    result = runner.submit(brief_id=brief["brief_id"], brief_sha=brief["brief_sha"], dry_run=True)
    # Tamper with the persisted brief text AFTER submit (sha no longer matches).
    store = BriefStore(tmp_path, config)
    store._text_path(brief["brief_id"]).write_text("malicious replacement text", encoding="utf-8")
    runner.run_job(result["job_id"])
    record = runner.get(result["job_id"])
    assert record["status"] == "failed"
    assert "changed on disk" in record["reason"]


def test_return_continues_the_same_branch(tmp_path) -> None:
    from wiki_core.web.briefs import compose_return_brief

    config = _repo(tmp_path)
    brief = _saved_brief(tmp_path, config)
    runner = _runner(tmp_path, config)
    first = runner.submit(brief_id=brief["brief_id"], brief_sha=brief["brief_sha"], dry_run=True)
    runner.run_job(first["job_id"])
    parent = runner.get(first["job_id"])
    assert parent["status"] == "delivered"
    branch = parent["branch"]

    # Get back onto a clean default branch (the forward run leaves us on wiki/).
    subprocess.run(["git", "switch", "main"], cwd=tmp_path, capture_output=True)

    snapshot = build_snapshot(tmp_path, config, mode="local_operator", generated_at=SNAPSHOT_AT)
    follow = compose_return_brief(tmp_path, config, snapshot, parent_job=parent, feedback="tighten the wording")
    assert follow is not None
    assert "RETURN" in follow["text"]
    assert branch in follow["text"]

    second = runner.submit(brief_id=follow["brief_id"], brief_sha=follow["brief_sha"], dry_run=True)
    assert second["ok"] is True
    assert second["resume_branch"] == branch
    assert second["parent_job_id"] == parent["job_id"]
    runner.run_job(second["job_id"])
    child = runner.get(second["job_id"])
    assert child["status"] == "delivered"
    # The follow-up committed onto the SAME branch, not a new one.
    assert child["branch"] == branch
    branches = subprocess.run(["git", "branch"], cwd=tmp_path, capture_output=True, text=True).stdout
    assert branches.count(branch.split("/")[-1]) == 1


def test_cancel_interrupts_a_running_job(tmp_path, monkeypatch) -> None:
    config = _repo(tmp_path)
    brief = _saved_brief(tmp_path, config)
    monkeypatch.setenv("CODEX_SHIM_SLEEP", "3")
    runner = _runner(tmp_path, config, autostart=True)  # real worker drains the queue
    result = runner.submit(brief_id=brief["brief_id"], brief_sha=brief["brief_sha"], dry_run=True)
    job_id = result["job_id"]
    # Wait until it is actually running the shim, then cancel.
    for _ in range(50):
        if runner.get(job_id)["status"] == "running":
            break
        time.sleep(0.1)
    runner.cancel(job_id)
    for _ in range(50):
        if runner.get(job_id)["status"] == "cancelled":
            break
        time.sleep(0.1)
    assert runner.get(job_id)["status"] == "cancelled"
