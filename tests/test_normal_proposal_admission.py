"""Actual documentary writer/C2/Git effects use native revocable admission."""
from __future__ import annotations

import hashlib
import json
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from tests.test_admin_commands import _execute, _plan
from tests.test_admin_sessions import _arm, _code
from tests.test_web_server import _repo, _server_action, _Server
from wiki_core.config import load_config
from wiki_core.paths import WikiPaths
from wiki_core.web.admin.sessions import ADMIN_SESSION_HEADER


def _git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def _sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture()
def prepared(tmp_path: Path, monkeypatch):
    # Presentation metadata is not part of this native authority proof; keep
    # the synthetic Git origin entirely offline, even on an authenticated host.
    monkeypatch.setattr("wiki_core.web.git_ops._gh_pr_metadata", lambda *args: None)
    config = _repo(tmp_path)
    action = _server_action(tmp_path)
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "Synthetic reviewer")
    _git(tmp_path, "config", "user.email", "synthetic@example.invalid")
    _git(tmp_path, "remote", "add", "origin", "git@github.com:synthetic/wiki.git")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "Initial synthetic context")
    _git(tmp_path, "switch", "-c", "wiki/synthetic-proposal")
    material = {
        "schema_version": "wiki_normal_proposal.v1", "base_head": _git(tmp_path, "rev-parse", "HEAD"),
        "branch": "wiki/synthetic-proposal",
        "action": {"page_ref": action.relative_to(tmp_path).as_posix(),
                   "page_id": "action-server-synthetic", "effect_key": "synthetic-material-1",
                   "run_id": "synthetic-run-1", "expected_sha256": _sha(action.read_bytes()),
                   "body": "\n# Synthetic server action\n\nReviewed synthetic result.\n",
                   "recorded_at": "2026-10-25T05:00:00Z",
                   "contribution": {"effect_key": "synthetic-material-1", "run_id": "synthetic-run-1",
                                    "material_sha256": _sha(b"Reviewed synthetic result.")}},
        "documents": [{"path": "memories/index.md", "before_sha256": _sha((tmp_path / "memories/index.md").read_bytes()),
                       "after_text": (tmp_path / "memories/index.md").read_text().replace(
                           "Stale root for the server test.", "Reviewed local policy, without renewing external facts.")}],
        "c2": ["operation"], "generated_at": "2026-10-25T05:00:00Z",
        "commit_message": "Record a reviewed synthetic result",
    }
    material_path = WikiPaths(tmp_path, config).derived_root / "proposal-material.json"
    material_path.parent.mkdir(parents=True, exist_ok=True)
    material_path.write_text(json.dumps(material))
    params = {"material_path": material_path.relative_to(tmp_path).as_posix(),
              "material_sha256": _sha(material_path.read_bytes())}
    srv = _Server(tmp_path, config)
    lines, clock = _arm(srv)

    def unlock():
        status, challenge = srv.post("/api/admin/session/challenge", {})
        assert status == 200
        status, result = srv.post("/api/admin/session/unlock", {"challenge": challenge["challenge"], "code": _code(lines)})
        assert status == 200 and result["ok"]
        return result["token"]

    try:
        yield srv, tmp_path, params, unlock, clock
    finally:
        srv.close()


def _state(root):
    # Auth-audit receipts are a separate security record, not a domain effect.
    files = {p.relative_to(root).as_posix(): _sha(p.read_bytes())
             for p in (root / "memories").rglob("*") if p.is_file()}
    return {"files": files, "head": _git(root, "rev-parse", "HEAD"),
            "index": _sha((root / ".git/index").read_bytes()),
            "refs": _git(root, "show-ref"),
            "status": _git(root, "status", "--porcelain", "--untracked-files=all")}


def test_lock_after_plan_and_new_session_same_material_real_prepare(prepared):
    srv, root, params, unlock, _clock = prepared
    token = unlock()
    status, plan = _plan(srv, token, "wiki.proposal.prepare", params=params)
    assert status == 200, plan
    before = _state(root)
    status, locked = srv.post("/api/admin/session/lock", {}, headers={ADMIN_SESSION_HEADER: token})
    assert status == 200 and locked["state"] == "locked"
    status, refused = _execute(srv, token, plan, confirmation=plan["plan"]["confirmation"]["text"])
    assert status == 403 and refused["error_code"] == "admin_session_invalid"
    assert _state(root) == before
    fresh_token = unlock()
    status, stale = _execute(srv, fresh_token, plan, confirmation=plan["plan"]["confirmation"]["text"])
    assert status == 409 and stale["error_code"] == "admin_plan_stale"
    status, new_plan = _plan(srv, fresh_token, "wiki.proposal.prepare", params=params)
    assert status == 200, new_plan
    assert new_plan["plan"]["diff"] == plan["plan"]["diff"]
    status, executed = _execute(srv, fresh_token, new_plan, confirmation=new_plan["plan"]["confirmation"]["text"])
    assert status == 200 and executed["ok"], executed
    assert executed["output"]["prepared"] and not executed["output"]["published"]
    assert executed["output"]["effect_key"] == "synthetic-material-1"
    assert _git(root, "rev-parse", "HEAD") != before["head"]
    assert _git(root, "rev-parse", "main") == before["head"]
    action = root / "memories/actions/action-server-synthetic.md"
    assert "body_integration" in action.read_text()
    assert "Reviewed synthetic result." in action.read_text()
    assert WikiPaths(root, load_config(root)).operation_page.exists()
    status, replay = _execute(srv, fresh_token, new_plan, confirmation=new_plan["plan"]["confirmation"]["text"])
    assert status == 409 and replay["error_code"] == "admin_plan_already_executed"


def test_material_mutation_without_git_status_change_refuses(prepared):
    srv, root, params, unlock, _clock = prepared
    token = unlock()
    status, plan = _plan(srv, token, "wiki.proposal.prepare", params=params)
    assert status == 200, plan
    path = root / params["material_path"]
    path.write_text(path.read_text().replace("Reviewed synthetic result.", "A different synthetic result."))
    before = _state(root)
    status, denied = _execute(srv, token, plan, confirmation=plan["plan"]["confirmation"]["text"])
    assert status != 200 and not denied["ok"]
    assert _state(root) == before


def test_native_revocation_after_initial_validation_before_effect(prepared, monkeypatch):
    from wiki_core.web.admin import plans
    srv, root, params, unlock, _clock = prepared
    token = unlock()
    status, plan = _plan(srv, token, "wiki.proposal.prepare", params=params)
    assert status == 200, plan
    before = _state(root)
    original = plans._failed_preconditions

    def revoke_after_preconditions(*args):
        failed = original(*args)
        assert srv.server.admin_sessions.lock(token)["state"] == "locked"
        return failed

    monkeypatch.setattr(plans, "_failed_preconditions", revoke_after_preconditions)
    status, denied = _execute(srv, token, plan, confirmation=plan["plan"]["confirmation"]["text"])
    assert status == 403 and denied["error_code"] == "admin_session_invalid", denied
    assert _state(root) == before


def test_lock_during_real_c2_waits_and_prevents_installation(prepared, monkeypatch):
    from scripts import wiki_operation_compile
    srv, root, params, unlock, _clock = prepared
    token = unlock()
    status, plan = _plan(srv, token, "wiki.proposal.prepare", params=params)
    assert status == 200, plan
    before = _state(root)
    started, release = threading.Event(), threading.Event()
    original = wiki_operation_compile.build_page

    def long_real_c2(*args, **kwargs):
        result = original(*args, **kwargs)
        started.set()
        assert release.wait(5)
        return result

    monkeypatch.setattr(wiki_operation_compile, "build_page", long_real_c2)
    with ThreadPoolExecutor(1) as executor:
        future = executor.submit(_execute, srv, token, plan, confirmation=plan["plan"]["confirmation"]["text"])
        assert started.wait(5)
        status, pending = srv.post("/api/admin/session/lock", {}, headers={ADMIN_SESSION_HEADER: token})
        assert status == 409 and pending["error_code"] == "admin_revocation_pending"
        assert pending["state"] != "locked"
        release.set()
        status, denied = future.result(timeout=5)
    assert status == 403 and denied["output"]["canonical_main_changed"] is False, denied
    status, locked = srv.post("/api/admin/session/lock", {}, headers={ADMIN_SESSION_HEADER: token})
    assert status == 200 and locked["state"] == "locked"
    assert _state(root) == before


@pytest.mark.parametrize("path,payload", [
    ("/api/actions/create", {"title": "Another synthetic action"}),
    ("/api/actions/transition", {"page_ref": "memories/actions/action-server-synthetic.md", "next_state": "in_progress", "expected_sha256": "a" * 64}),
    ("/api/actions/run", {"action_id": "refresh-cockpit-write"}),
    ("/api/git/workflow", {"operation": "stage_paths", "paths": ["memories/index.md"], "dry_run": False}),
])
def test_legacy_nonce_only_cannot_bypass(prepared, path, payload):
    srv, root, _params, _unlock, _clock = prepared
    before = _state(root)
    status, denied = srv.post(path, payload, headers={})
    assert status == 403 and denied["error_code"] == "admin_session_invalid"
    assert _state(root) == before


@pytest.mark.parametrize("operation", ["publish_proposal", "publish_contribution", "integrate_contribution"])
def test_maintainer_cannot_publish_via_legacy_workflow(prepared, operation):
    srv, root, _params, unlock, _clock = prepared
    token = unlock()
    srv.server.admin_sessions._session.role = "maintainer"
    before = _state(root)
    status, denied = srv.post("/api/git/workflow", {"operation": operation, "dry_run": False},
                              headers={ADMIN_SESSION_HEADER: token})
    assert status == 403 and denied["error_code"] == "admin_capability_denied"
    assert _state(root) == before


def test_unrelated_input_bytes_are_pinned_even_when_git_status_is_unchanged(prepared):
    srv, root, params, unlock, _clock = prepared
    target = root / "memories/context.md"
    target.write_text("# A context\n")
    _git(root, "add", target.relative_to(root).as_posix())
    _git(root, "commit", "-m", "Add synthetic input")
    material_path = root / params["material_path"]
    material = json.loads(material_path.read_text())
    material["base_head"] = _git(root, "rev-parse", "HEAD")
    material_path.write_text(json.dumps(material))
    params["material_sha256"] = _sha(material_path.read_bytes())
    target.write_text("# Already modified context\n")
    token = unlock()
    status, plan = _plan(srv, token, "wiki.proposal.prepare", params=params)
    assert status == 200, plan
    status_before = _git(root, "status", "--porcelain")
    target.write_text("# Changed again, same Git status\n")
    assert _git(root, "status", "--porcelain") == status_before
    before = _state(root)
    status, denied = _execute(srv, token, plan, confirmation=plan["plan"]["confirmation"]["text"])
    assert status == 409 and denied["error_code"] == "admin_plan_stale", denied
    assert denied["failed_preconditions"] == ["proposal_planned_readset_changed"]
    assert _state(root) == before


@pytest.mark.parametrize("kind", ["new_action", "changed_page_type", "mismatched_run"])
def test_document_adapter_cannot_forge_action_or_execution_identity(prepared, kind):
    srv, root, params, unlock, _clock = prepared
    path = root / params["material_path"]
    material = json.loads(path.read_text())
    if kind == "mismatched_run":
        material["action"]["contribution"]["run_id"] = "another-run"
    else:
        action_text = (root / material["action"]["page_ref"]).read_text()
        material["documents"] = [{"path": "memories/forged.md" if kind == "new_action" else "memories/index.md",
            "before_sha256": None if kind == "new_action" else _sha((root / "memories/index.md").read_bytes()),
            "after_text": action_text}]
    path.write_text(json.dumps(material))
    params["material_sha256"] = _sha(path.read_bytes())
    token = unlock()
    before = _state(root)
    status, denied = _plan(srv, token, "wiki.proposal.prepare", params=params)
    assert status == 400 and denied["error_code"] == "admin_invalid_params"
    assert _state(root) == before


def test_exception_after_real_writer_is_reported_as_partial(prepared, monkeypatch):
    from wiki_core.web import normal_proposal
    srv, root, params, unlock, _clock = prepared
    token = unlock()
    status, plan = _plan(srv, token, "wiki.proposal.prepare", params=params)
    assert status == 200, plan
    head = _git(root, "rev-parse", "HEAD")
    original = normal_proposal._write_action

    def interrupted_after_write(where, action):
        original(where, action)
        if where == root:
            raise OSError("controlled interruption after the real canonical writer")

    monkeypatch.setattr(normal_proposal, "_write_action", interrupted_after_write)
    status, partial = _execute(srv, token, plan, confirmation=plan["plan"]["confirmation"]["text"])
    assert status != 200 and partial["status"] == "partial", partial
    assert "memories/actions/action-server-synthetic.md" in partial["affected_paths"]
    assert "body_integration" in (root / "memories/actions/action-server-synthetic.md").read_text()
    assert _git(root, "rev-parse", "HEAD") == head
    assert _git(root, "diff", "--cached", "--name-only") == ""


def test_failed_c2_never_installs_or_commits_and_releases_effect(prepared, monkeypatch):
    from scripts import wiki_operation_compile
    srv, root, params, unlock, _clock = prepared
    token = unlock()
    status, plan = _plan(srv, token, "wiki.proposal.prepare", params=params)
    assert status == 200, plan
    before = _state(root)
    original = wiki_operation_compile.build_page
    def failed_c2(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("controlled C2 failure before installation")
    monkeypatch.setattr(wiki_operation_compile, "build_page", failed_c2)
    status, denied = _execute(srv, token, plan, confirmation=plan["plan"]["confirmation"]["text"])
    assert status == 400 and not denied["ok"]
    assert _state(root) == before
    status, locked = srv.post("/api/admin/session/lock", {}, headers={ADMIN_SESSION_HEADER: token})
    assert status == 200 and locked["state"] == "locked"


def test_installer_does_not_follow_parent_swapped_after_preflight(tmp_path, monkeypatch):
    import os
    from wiki_core.web.normal_proposal import _install
    root = tmp_path / "checkout"
    parent = root / "memories"
    parent.mkdir(parents=True)
    (parent / "canary.md").write_bytes(b"before")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "canary.md").write_bytes(b"foreign canary")
    original = os.open
    swapped = False
    def swap_after_root_open(path, flags, *args, **kwargs):
        nonlocal swapped
        descriptor = original(path, flags, *args, **kwargs)
        if not swapped and Path(path) == root.resolve():
            swapped = True
            parent.rename(root / "original-parent")
            parent.symlink_to(outside, target_is_directory=True)
        return descriptor
    monkeypatch.setattr(os, "open", swap_after_root_open)
    with pytest.raises(OSError):
        _install(root, "memories/canary.md", b"before", b"after")
    assert (outside / "canary.md").read_bytes() == b"foreign canary"
    assert (root / "original-parent/canary.md").read_bytes() == b"before"


@pytest.mark.parametrize("changed_after_plan", [False, True])
def test_real_c2_reads_and_pins_its_local_cache_inputs(prepared, changed_after_plan):
    import datetime as dt
    from scripts.wiki_operation_compile import build_page
    from wiki_core.score import record_event
    srv, root, params, unlock, _clock = prepared
    paths = WikiPaths(root, srv.server.config)
    request = paths.extraction_events / "synthetic-llm-context-request.json"
    request.parent.mkdir(parents=True, exist_ok=True)
    request.write_text(json.dumps({"source_id": "synthetic-source", "chunks": [{"cache_key": "synthetic-cache"}]}))
    cached = paths.llm_cache / "synthetic-cache.json"
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text("{}")
    ledger = paths.derived_root / "score-events.jsonl"
    record_event(ledger, event_type="recompilar_pagina_antiga", actor="synthetic", context="system", dedup_key="synthetic-c2")
    token = unlock()
    status, plan = _plan(srv, token, "wiki.proposal.prepare", params=params)
    assert status == 200, plan
    assert {p.relative_to(root).as_posix() for p in (request, cached, ledger)} <= set(plan["plan"]["effects"]["files_read"])
    if changed_after_plan:
        cached.write_text("not valid JSON")
    before = _state(root)
    status, result = _execute(srv, token, plan, confirmation=plan["plan"]["confirmation"]["text"])
    if changed_after_plan:
        assert status == 409 and result["error_code"] == "admin_plan_stale"
        assert _state(root) == before
    else:
        assert status == 200 and result["output"]["prepared"], result
        capture = dt.datetime.fromisoformat(result["output"]["c2_captured_at"].replace("Z", "+00:00"))
        assert paths.operation_page.read_text() == build_page(root, srv.server.config, generated_at=capture)
