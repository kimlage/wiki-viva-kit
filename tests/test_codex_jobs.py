from __future__ import annotations

import json
import subprocess
import threading
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


def _runner(
    root: Path,
    config: WikiConfig,
    *,
    autostart: bool = False,
    timeout_seconds: int = 30,
    **env,
) -> JobRunner:
    return JobRunner(
        root,
        config,
        codex_cmd=["python3", SHIM],
        timeout_seconds=timeout_seconds,
        autostart=autostart,
        **env,
    )


def test_job_state_writes_notify_the_snapshot_cache_owner(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    brief = _saved_brief(tmp_path, config)
    notifications: list[str] = []
    runner = _runner(
        tmp_path,
        config,
        on_change=lambda: notifications.append("changed"),
    )

    result = runner.submit(
        brief_id=brief["brief_id"],
        brief_sha=brief["brief_sha"],
        dry_run=True,
    )
    assert result["ok"] is True
    submitted_notifications = len(notifications)
    assert submitted_notifications >= 1
    runner.run_job(result["job_id"])
    assert len(notifications) > submitted_notifications
    assert runner.get(result["job_id"])["status"] == "delivered"


def test_build_argv_is_sandboxed_and_never_yolo() -> None:
    argv = build_codex_argv("codex", Path("/repo"), Path("/repo/final.md"))
    assert argv[:3] == ["codex", "exec", "-"]
    assert "--sandbox" in argv and "workspace-write" in argv
    assert "--json" in argv
    assert not any("yolo" in a or "dangerous" in a for a in argv)
    # codex exec is non-interactive: it has no approvals flag, and passing -a
    # makes the CLI exit 2 before doing anything (regression: codex-cli 0.142).
    assert "-a" not in argv


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


def test_codex_timeout_reaps_process_closes_pipes_and_joins_helpers(tmp_path, monkeypatch) -> None:
    config = _repo(tmp_path)
    brief = _saved_brief(tmp_path, config)
    monkeypatch.setenv("CODEX_SHIM_SLEEP", "3")
    runner = _runner(tmp_path, config, timeout_seconds=1)
    spawned: list[subprocess.Popen[str]] = []
    original_popen = subprocess.Popen

    def tracking_popen(*args, **kwargs):
        proc = original_popen(*args, **kwargs)
        argv = args[0] if args else kwargs.get("args")
        if isinstance(argv, list) and len(argv) > 1 and argv[1] == SHIM:
            spawned.append(proc)
        return proc

    monkeypatch.setattr("wiki_core.web.codex_jobs.subprocess.Popen", tracking_popen)
    result = runner.submit(
        brief_id=brief["brief_id"],
        brief_sha=brief["brief_sha"],
        dry_run=True,
    )
    runner.run_job(result["job_id"])

    record = runner.get(result["job_id"])
    assert record["status"] == "failed"
    assert "codex exited" in record["reason"]
    assert len(spawned) == 1
    proc = spawned[0]
    assert proc.poll() is not None
    assert proc.stdin is not None and proc.stdin.closed
    assert proc.stdout is not None and proc.stdout.closed
    helper_names = {thread.name for thread in threading.enumerate()}
    assert f"wiki-codex-feed-{result['job_id']}" not in helper_names
    assert f"wiki-codex-watchdog-{result['job_id']}" not in helper_names


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


def test_job_record_write_replaces_complete_json_atomically(tmp_path, monkeypatch) -> None:
    config = _repo(tmp_path)
    runner = _runner(tmp_path, config)
    job_id = "job-atomic-write"
    runner._write({"job_id": job_id, "status": "queued"})
    target = runner._record_path(job_id)
    original_replace = Path.replace
    observed: list[tuple[str, str]] = []

    def inspect_replace(temporary: Path, destination: Path) -> Path:
        observed.append(
            (
                json.loads(destination.read_text(encoding="utf-8"))["status"],
                json.loads(temporary.read_text(encoding="utf-8"))["status"],
            )
        )
        return original_replace(temporary, destination)

    monkeypatch.setattr(Path, "replace", inspect_replace)
    runner._write({"job_id": job_id, "status": "running"})

    assert observed == [("queued", "running")]
    assert runner.get(job_id)["status"] == "running"
    assert not list(target.parent.glob(f".{target.name}.*.tmp"))


def test_continue_current_branch_commits_only_codex_delta(tmp_path) -> None:
    """The operator's normal state: ALREADY on a proposal branch with in-progress
    edits. A fresh job must work in place and commit ONLY Codex's delta — the
    owner's dirty files are never swept into the job commit nor reset."""
    config = _repo(tmp_path)
    brief = _saved_brief(tmp_path, config)
    subprocess.run(["git", "switch", "-c", "wiki/in-progress"], cwd=tmp_path, check=True, capture_output=True)
    # Owner's in-progress edits: one tracked file modified + one untracked file.
    (tmp_path / "AGENTS.md").write_text("# Agents\n\nowner wip\n", encoding="utf-8")
    _write(tmp_path / "notes.md", "owner scratch\n")

    runner = _runner(tmp_path, config)
    result = runner.submit(brief_id=brief["brief_id"], brief_sha=brief["brief_sha"], dry_run=True)
    assert result["ok"] is True
    runner.run_job(result["job_id"])
    record = runner.get(result["job_id"])
    assert record["status"] == "delivered", record["reason"]
    assert record["branch"] == "wiki/in-progress"
    assert record["branch_mode"] == "continue_current"
    # The commit contains ONLY the file Codex edited.
    committed = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"], cwd=tmp_path, capture_output=True, text=True
    ).stdout.split()
    assert committed == ["memories/index.md"]
    # The owner's edits survive, uncommitted, exactly as they were.
    status = subprocess.run(["git", "status", "--short"], cwd=tmp_path, capture_output=True, text=True).stdout
    assert " AGENTS.md" in status and "notes.md" in status
    assert "owner wip" in (tmp_path / "AGENTS.md").read_text()
    branch = subprocess.run(["git", "branch", "--show-current"], cwd=tmp_path, capture_output=True, text=True).stdout.strip()
    assert branch == "wiki/in-progress"


def test_continue_current_overlap_only_fails_without_destroying_edits(tmp_path, monkeypatch) -> None:
    """If Codex only touches files the owner already had dirty, the edits are
    inseparable: the job fails honestly and NOTHING is reset — both the owner's
    and Codex's lines stay in the worktree for review."""
    config = _repo(tmp_path)
    brief = _saved_brief(tmp_path, config)
    subprocess.run(["git", "switch", "-c", "wiki/in-progress"], cwd=tmp_path, check=True, capture_output=True)
    target = tmp_path / "memories/index.md"
    target.write_text(target.read_text() + "\nowner edit\n", encoding="utf-8")

    runner = _runner(tmp_path, config)
    # The owner's edit moved the brief's target — force past the staleness guard
    # (that guard is exactly for this; the overlap protection is what we test).
    result = runner.submit(brief_id=brief["brief_id"], brief_sha=brief["brief_sha"], dry_run=True, force=True)
    assert result["ok"] is True
    runner.run_job(result["job_id"])
    record = runner.get(result["job_id"])
    assert record["status"] == "failed"
    assert "uncommitted edits" in record["reason"]
    assert "memories/index.md" in record["reason"]
    # No reset --hard: both edits are still in the file, still uncommitted.
    text = target.read_text()
    assert "owner edit" in text and "codex shim edit" in text
    branch = subprocess.run(["git", "branch", "--show-current"], cwd=tmp_path, capture_output=True, text=True).stdout.strip()
    assert branch == "wiki/in-progress"
    log = subprocess.run(["git", "log", "--oneline", "-1"], cwd=tmp_path, capture_output=True, text=True).stdout
    assert "codex:" not in log


def test_runner_reanchors_when_agent_switches_branches(tmp_path, monkeypatch) -> None:
    """An agent that follows the brief's external contract and creates the
    proposal branch itself must not derail the job: the runner re-anchors to
    ITS branch, deletes the stray one, and commits where the record says."""
    config = _repo(tmp_path)
    brief = _saved_brief(tmp_path, config)
    subprocess.run(["git", "switch", "-c", "wiki/in-progress"], cwd=tmp_path, check=True, capture_output=True)
    monkeypatch.setenv("CODEX_SHIM_SWITCH_BRANCH", "wiki/stray-agent-branch")

    runner = _runner(tmp_path, config)
    result = runner.submit(brief_id=brief["brief_id"], brief_sha=brief["brief_sha"], dry_run=True)
    runner.run_job(result["job_id"])
    record = runner.get(result["job_id"])
    assert record["status"] == "delivered", record["reason"]
    assert record["branch"] == "wiki/in-progress"
    branch = subprocess.run(["git", "branch", "--show-current"], cwd=tmp_path, capture_output=True, text=True).stdout.strip()
    assert branch == "wiki/in-progress"
    branches = subprocess.run(["git", "branch"], cwd=tmp_path, capture_output=True, text=True).stdout
    assert "stray-agent-branch" not in branches
    log = subprocess.run(["git", "log", "--oneline", "-1"], cwd=tmp_path, capture_output=True, text=True).stdout
    assert "codex:" in log


def test_runner_preamble_reaches_codex_and_the_artifact(tmp_path) -> None:
    """What ran is what the artifact shows: the executed stdin carries the
    runner-context preamble (runner owns git) on top of the composed brief."""
    config = _repo(tmp_path)
    brief = _saved_brief(tmp_path, config)
    runner = _runner(tmp_path, config)
    result = runner.submit(brief_id=brief["brief_id"], brief_sha=brief["brief_sha"], dry_run=True)
    runner.run_job(result["job_id"])
    record = runner.get(result["job_id"])
    assert record["status"] == "delivered", record["reason"]
    matches = list(tmp_path.rglob(f"codex-jobs/{result['job_id']}/brief.md"))
    assert matches, "job brief.md artifact not found"
    artifact = matches[0].read_text(encoding="utf-8")
    assert artifact.startswith("<runner-context>")
    assert record["branch"] in artifact
    assert "do NOT create or switch branches" in artifact
