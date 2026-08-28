from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import urllib.error
import urllib.request
import uuid
from http import HTTPStatus
from pathlib import Path
from typing import Any

import pytest

import wiki_core.web.server as server_module
from wiki_core.config import WikiConfig, load_config
from wiki_core.frontmatter import parse_frontmatter
from wiki_core.web.schemas import SNAPSHOT_FILES
from wiki_core.web.server import CockpitServer, _allowed_cors_origins, main, serve


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _repo(root: Path) -> WikiConfig:
    subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
    _write(root / "AGENTS.md", "# Agents\nHard rules.\n")
    # Pin codex disabled so the capability gate is deterministic regardless of
    # whether the test machine has a working codex CLI installed.
    _write(root / "wiki.config.yaml", "repo_id: srv-test\ndefault_context: system\ncodex:\n  enabled: false\n")
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

Stale root for the server test.
""",
    )
    return load_config(root)


def _server_action(root: Path, state: str = "open") -> Path:
    path = root / "memories/actions/action-server-synthetic.md"
    receipt = (
        "completion_receipt: commit:synthetic\n"
        if state == "done"
        else "cancellation_receipt: decision:synthetic\n"
        if state == "cancelled"
        else ""
    )
    _write(
        path,
        "---\n"
        "page_id: action-server-synthetic\n"
        "page_type: action\n"
        "title: Synthetic server action\n"
        "context: system\n"
        "visibility: private_self\n"
        "updated_at: 2026-07-11\n"
        "stale_after_days: 30\n"
        f"action_state: {state}\n"
        f"{receipt}"
        "next_action: Review synthetic evidence.\n"
        "owner_kind: unassigned\n"
        "created_at: 2026-07-11\n"
        "priority: normal\n"
        "attention_basis: Synthetic server coverage.\n"
        "source_refs: []\n"
        "moc_parent: memories/index.md\n"
        "---\n\n"
        "# Synthetic server action\n",
    )
    return path


class _Server:
    def __init__(self, root: Path, config: WikiConfig) -> None:
        self.server = CockpitServer(("127.0.0.1", 0), root, config)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def get(self, path: str, headers: dict[str, str] | None = None) -> tuple[int, dict[str, Any]]:
        req = urllib.request.Request(self.url(path), headers=headers or {}, method="GET")
        try:
            with urllib.request.urlopen(req) as resp:  # noqa: S310 - localhost test
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # 4xx still carry a JSON envelope
            with exc:
                return exc.code, json.loads(exc.read().decode("utf-8"))

    def get_headers(
        self, path: str, headers: dict[str, str] | None = None
    ) -> tuple[int, dict[str, str]]:
        req = urllib.request.Request(self.url(path), headers=headers or {}, method="GET")
        try:
            with urllib.request.urlopen(req) as resp:  # noqa: S310 - localhost test
                return resp.status, dict(resp.headers.items())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, dict(exc.headers.items())

    def options_headers(self, path: str, headers: dict[str, str]) -> tuple[int, dict[str, str]]:
        req = urllib.request.Request(self.url(path), headers=headers, method="OPTIONS")
        try:
            with urllib.request.urlopen(req) as resp:  # noqa: S310 - localhost test
                return resp.status, dict(resp.headers.items())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, dict(exc.headers.items())

    def post(
        self,
        path: str,
        body: dict[str, Any],
        *,
        attempt_key: str | None = None,
        nonce: str | None = None,
        origin: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        status, body, _headers = self.post_response(
            path,
            body,
            attempt_key=attempt_key,
            nonce=nonce,
            origin=origin,
        )
        return status, body

    def post_response(
        self,
        path: str,
        body: dict[str, Any],
        *,
        attempt_key: str | None = None,
        nonce: str | None = None,
        origin: str | None = None,
    ) -> tuple[int, dict[str, Any], dict[str, str]]:
        data = json.dumps(body).encode("utf-8")
        headers = {
            "content-type": "application/json",
            "X-Wiki-Operator-Nonce": nonce if nonce is not None else self.server.operator_nonce,
            "X-Wiki-Attempt-Key": attempt_key or f"test-{uuid.uuid4()}",
        }
        if origin is not None:
            headers["Origin"] = origin
        req = urllib.request.Request(
            self.url(path), data=data, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req) as resp:  # noqa: S310 - localhost test
                return (
                    resp.status,
                    json.loads(resp.read().decode("utf-8")),
                    dict(resp.headers.items()),
                )
        except urllib.error.HTTPError as exc:  # 4xx still carry a JSON envelope
            with exc:
                return (
                    exc.code,
                    json.loads(exc.read().decode("utf-8")),
                    dict(exc.headers.items()),
                )

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture()
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.delenv("WIKI_COCKPIT_CORS_ORIGINS", raising=False)
    config = _repo(tmp_path)
    srv = _Server(tmp_path, config)
    try:
        yield srv
    finally:
        srv.close()


def test_health_carries_codex_capability(server: _Server) -> None:
    status, body = server.get("/api/health")
    assert status == 200
    assert body["ok"] is True
    assert "codex" in body
    assert set(body["codex"]) >= {"installed", "authed", "usable", "enabled"}


def test_operator_refuses_non_loopback_bind_before_loading_repo(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="may bind only"):
        serve(tmp_path, host="0.0.0.0", port=0)

    with pytest.raises(SystemExit) as exc:
        main(["--root", str(tmp_path), "--host", "0.0.0.0", "--port", "0"])
    assert exc.value.code == 2


def test_health_carries_operator_handshake(server: _Server) -> None:
    status, body = server.get("/api/health")
    assert status == 200
    # The handshake lets the cockpit detect a stale operator (old process).
    assert body["server_version"] == "wiki_web_server.v6"
    assert "codex" in body["schema_capabilities"]
    assert "briefs" in body["schema_capabilities"]
    assert "operator_security_v2" in body["schema_capabilities"]
    assert "cors_default_deny_v1" in body["schema_capabilities"]
    assert "action_state_transitions_v1" in body["schema_capabilities"]
    assert "filesystem_snapshot_publication_v1" in body["schema_capabilities"]
    assert "snapshot_external_freshness_v1" in body["schema_capabilities"]
    assert "operator_security_v1" not in body["schema_capabilities"]
    assert body["operator_security"]["version"] == "wiki_operator_security.v2"
    assert body["operator_security"]["nonce"] == server.server.operator_nonce
    assert body["operator_security"]["mutations"] == "post_only"
    assert body["operator_security"]["browser_origin_default"] == "deny"
    assert body["operator_security"]["cors_opt_in"] == "exact_loopback_allowlist"
    activation = body["snapshot_publication"]
    assert activation["version"] == "wiki_filesystem_snapshot_publication.v1"
    assert activation["publication_supported"] is True
    assert activation["layout"] == "absent"
    assert activation["active_revision"] is None
    assert activation["reader_contract"] == (
        "filesystem_consumer_resolves_pointer_once_and_validates_envelope"
    )
    assert activation["legacy_directory_migration"]["supported"] is True
    assert activation["durability"] == {
        "live_files_fsynced_before_activation": True,
        "revision_store_and_staging_directories_fsynced_before_commit": True,
        "activation_source_and_destination_parent_fsync_attempted_after_commit": True,
        "archive_source_and_destination_directories_fsync_attempted": True,
        "post_commit_fsync_failures_return_cleanup_warnings": True,
        "flat_build_host_activation_required": True,
    }
    assert body["api_snapshot_serving"] == {
        "source": "live_repository_build_cache",
        "uses_published_snapshot_pointer": False,
        "cache_ttl_seconds": server.server.SNAPSHOT_CACHE_TTL_S,
        "external_freshness": {
            "version": "wiki_snapshot_external_freshness.v1",
            "checked_on_every_snapshot_read": True,
            "validation": "optimistic_source_revision_before_and_after_build",
            "revision_inputs": [
                "git_head_branch_and_refs",
                "git_index_identity",
                "git_dirty_set_and_path_identity",
                "wiki_memory_config_pack_and_derived_inputs",
            ],
            "file_identity": [
                "device",
                "inode",
                "mode",
                "size",
                "mtime_ns",
                "ctime_ns",
            ],
            "stable_build_attempts": 5,
            "concurrent_read_coalescing": (
                "one_linearizable_revision_observation_per_overlapping_burst"
            ),
            "operator_boot_transport": (
                "single_aggregate_without_temporal_graph"
            ),
            "configuration_policy": (
                "startup_pinned_change_requires_operator_restart"
            ),
            "symlink_policy": "snapshot_readable_inputs_fail_closed",
            "local_mutation_behavior": (
                "serve_prior_stable_or_503_until_commit_invalidation"
            ),
            "unstable_source_behavior": "serve_prior_stable_or_503",
            "fingerprint_or_paths_exposed": False,
            "last_result": "not_checked",
        },
    }
    assert str(server.server.root) not in json.dumps(body["api_snapshot_serving"])


def test_operator_restart_rotates_nonce_and_refuses_the_stale_process_nonce(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WIKI_COCKPIT_CORS_ORIGINS", raising=False)
    config = _repo(tmp_path)
    first = _Server(tmp_path, config)
    try:
        first_status, first_health = first.get("/api/health")
        assert first_status == 200
        old_nonce = first_health["operator_security"]["nonce"]
    finally:
        first.close()

    second = _Server(tmp_path, config)
    try:
        second_status, second_health = second.get("/api/health")
        assert second_status == 200
        new_nonce = second_health["operator_security"]["nonce"]
        assert new_nonce != old_nonce
        assert second_health["server_version"] == "wiki_web_server.v6"
        assert second_health["operator_security"]["version"] == (
            "wiki_operator_security.v2"
        )

        stale_status, stale_body = second.post(
            "/api/git/workflow",
            {"operation": "list_proposals", "dry_run": True},
            nonce=old_nonce,
        )
        assert stale_status == 403
        assert "nonce" in stale_body["error"]

        current_status, current_body = second.post(
            "/api/git/workflow",
            {"operation": "list_proposals", "dry_run": True},
        )
        assert current_status == 200
        assert current_body["operation"] == "list_proposals"
    finally:
        second.close()


def test_operator_has_no_direct_cors_trust_by_default(server: _Server) -> None:
    for origin in (
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:5174",
        "http://localhost:5174",
    ):
        status, headers = server.get_headers("/api/health", {"Origin": origin})
        assert status == 200
        assert "Access-Control-Allow-Origin" not in headers

    status, headers = server.options_headers(
        "/api/git/workflow",
        {
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert status == 204
    assert "Access-Control-Allow-Origin" not in headers
    status, body, headers = server.post_response(
        "/api/git/workflow",
        {"operation": "list_proposals", "dry_run": True},
        origin="http://127.0.0.1:5173",
    )
    assert status == 403 and "origin" in body["error"]
    assert "Access-Control-Allow-Origin" not in headers

    # curl and the recommended same-origin proxy do not send Origin to the
    # operator. They still work, but the response must not invent an ACAO.
    status, headers = server.get_headers("/api/health")
    assert status == 200
    assert "Access-Control-Allow-Origin" not in headers
    status, body, headers = server.post_response(
        "/api/git/workflow",
        {"operation": "list_proposals", "dry_run": True},
    )
    assert status == 200 and body["operation"] == "list_proposals"
    assert "Access-Control-Allow-Origin" not in headers


def test_explicit_loopback_cors_origin_supports_preflight_get_and_post(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allowed = "http://127.0.0.1:43219"
    monkeypatch.setenv("WIKI_COCKPIT_CORS_ORIGINS", allowed)
    srv = _Server(tmp_path, _repo(tmp_path))
    try:
        status, headers = srv.options_headers(
            "/api/git/workflow",
            {
                "Origin": allowed,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": (
                    "content-type, x-wiki-operator-nonce, x-wiki-attempt-key"
                ),
            },
        )
        assert status == 204
        assert headers["Access-Control-Allow-Origin"] == allowed
        assert headers["Vary"] == "Origin"
        assert headers["Access-Control-Allow-Methods"] == "GET, POST, OPTIONS"
        assert "x-wiki-operator-nonce" in headers["Access-Control-Allow-Headers"]

        status, headers = srv.get_headers("/api/health", {"Origin": allowed})
        assert status == 200
        assert headers["Access-Control-Allow-Origin"] == allowed

        status, body, headers = srv.post_response(
            "/api/git/workflow",
            {"operation": "list_proposals", "dry_run": True},
            origin=allowed,
        )
        assert status == 200 and (body.get("operation") or body.get("ok"))
        assert headers["Access-Control-Allow-Origin"] == allowed

        other_spelling = "http://localhost:43219"
        status, headers = srv.get_headers("/api/health", {"Origin": other_spelling})
        assert status == 200
        assert "Access-Control-Allow-Origin" not in headers
        status, body = srv.post(
            "/api/git/workflow",
            {"operation": "status", "dry_run": True},
            origin=other_spelling,
        )
        assert status == 403 and "origin" in body["error"]
    finally:
        srv.close()


def test_cors_allowlist_accepts_only_exact_loopback_origins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "WIKI_COCKPIT_CORS_ORIGINS",
        "http://127.0.0.1:5173, https://localhost:4443, http://[::1]:8787",
    )
    assert _allowed_cors_origins() == {
        "http://127.0.0.1:5173",
        "https://localhost:4443",
        "http://[::1]:8787",
    }


@pytest.mark.parametrize(
    "configured",
    [
        "*",
        "http://*",
        "https://example.com",
        "http://user@localhost:5173",
        "http://localhost:5173/",
        "http://localhost:5173/path",
        "http://localhost:5173?mode=operator",
        "http://localhost:5173#operator",
        "ftp://localhost:5173",
        "http://localhost:not-a-port",
        "http://localhost:70000",
        "http://localhost:5173,https://example.com",
    ],
)
def test_invalid_cors_configuration_fails_closed(
    configured: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WIKI_COCKPIT_CORS_ORIGINS", configured)
    with pytest.raises(ValueError, match="invalid WIKI_COCKPIT_CORS_ORIGINS"):
        _allowed_cors_origins()


def test_invalid_cors_configuration_prevents_server_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _repo(tmp_path)
    monkeypatch.setenv("WIKI_COCKPIT_CORS_ORIGINS", "https://remote.example")
    with pytest.raises(ValueError, match="invalid WIKI_COCKPIT_CORS_ORIGINS"):
        CockpitServer(("127.0.0.1", 0), tmp_path, config)


def test_codex_capability_endpoint(server: _Server) -> None:
    status, body = server.get("/api/codex/capability")
    assert status == 200
    assert "usable" in body


def test_brief_lifecycle_over_http(server: _Server) -> None:
    # Compose
    status, body = server.post(
        "/api/briefs",
        {"spec": {"mission_kind": "refresh", "theme": "test theme", "grounding": {"page_ids": ["root"]},
                  "intent": "fix it"}},
    )
    assert status == 200 and body["ok"] is True
    brief_id = body["brief_id"]
    assert "## 5 · Output contract" in body["text"]
    assert "fix it" in body["text"]
    original_sha = body["brief_sha"]

    # List
    status, body = server.get("/api/briefs")
    assert status == 200
    assert any(r["brief_id"] == brief_id for r in body["briefs"])

    # Get single
    status, body = server.get(f"/api/briefs/{brief_id}")
    assert status == 200 and body["brief_id"] == brief_id

    # Edit
    status, body = server.post(f"/api/briefs/{brief_id}", {"text": body["text"] + "\nEDIT\n"})
    assert status == 200 and body["brief_sha"] != original_sha

    # Discard
    status, body = server.post(f"/api/briefs/{brief_id}/discard", {})
    assert status == 200 and body["status"] == "discarded"

    # Edit after discard is rejected
    status, body = server.post(f"/api/briefs/{brief_id}", {"text": "no"})
    assert status == 400 and body.get("ok") is False


def test_unknown_brief_is_404(server: _Server) -> None:
    status, body = server.get("/api/briefs/bdoesnotexist")
    assert status == 404
    assert body.get("ok") is False


def test_codex_jobs_list_empty_and_unknown_404(server: _Server) -> None:
    status, body = server.get("/api/codex/jobs")
    assert status == 200 and body["ok"] is True and body["jobs"] == []
    status, body = server.get("/api/codex/jobs/jnope")
    assert status == 404


def test_codex_job_submit_gated_on_capability(server: _Server) -> None:
    # This machine's codex is not usable (broken/absent), so the launch endpoint
    # must refuse honestly rather than create a doomed branch.
    status, body = server.post("/api/codex/jobs", {"brief_id": "b1", "brief_sha": "x", "dry_run": True})
    assert status == 400
    assert body.get("ok") is False
    assert "codex" in body


def test_existing_endpoints_still_route(server: _Server) -> None:
    # The do_POST refactor must not break the git/workflow allowlist path.
    status, body = server.post("/api/git/workflow", {"operation": "status", "dry_run": True})
    assert "operation" in body or "error" in body
    # And an unknown POST path still 404s (fallthrough guard intact).
    status, body = server.post("/api/nope", {})
    assert status == 404


def test_operator_rejects_untrusted_host_origin_and_nonce(server: _Server) -> None:
    status, body = server.get("/api/health", {"Host": "attacker.example"})
    assert status == 403 and "loopback" in body["error"]

    status, body = server.post("/api/git/workflow", {"operation": "status"}, nonce="wrong-nonce")
    assert status == 403 and "nonce" in body["error"]

    status, body = server.post(
        "/api/git/workflow",
        {"operation": "status"},
        origin="https://attacker.example",
    )
    assert status == 403 and "origin" in body["error"]


def test_operator_attempt_key_is_idempotent_and_input_bound(server: _Server) -> None:
    key = "attempt-fixed-0001"
    first_status, first = server.post(
        "/api/git/workflow", {"operation": "status", "dry_run": True}, attempt_key=key
    )
    second_status, second = server.post(
        "/api/git/workflow", {"operation": "status", "dry_run": True}, attempt_key=key
    )
    assert first_status == second_status
    assert first["attempt_key"] == key and first["replayed"] is False
    assert second["attempt_key"] == key and second["replayed"] is True

    status, body = server.post(
        "/api/git/workflow", {"operation": "diff", "dry_run": True}, attempt_key=key
    )
    assert status == 409 and "different input" in body["error"]


def test_active_attempt_never_expires_or_gets_evicted_while_process_is_alive(
    server: _Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [0.0]
    monkeypatch.setattr(server_module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(server_module, "MAX_ATTEMPT_RECEIPTS", 3)

    for index in range(3):
        claim, _receipt = server.server.claim_attempt(
            f"attempt-active-{index:04d}",
            "/api/gates/run",
            f"payload-{index}",
        )
        assert claim == "claimed"

    clock[0] = 121.0
    claim, _receipt = server.server.claim_attempt(
        "attempt-active-0000",
        "/api/gates/run",
        "payload-0",
    )
    assert claim == "in_flight"

    claim, _receipt = server.server.claim_attempt(
        "attempt-capacity-0001",
        "/api/gates/run",
        "payload-new",
    )
    assert claim == "capacity"
    assert set(server.server._attempt_receipts) == {
        "attempt-active-0000",
        "attempt-active-0001",
        "attempt-active-0002",
    }


def test_attempt_capacity_evicts_only_completed_receipts_and_http_is_typed(
    server: _Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server_module, "MAX_ATTEMPT_RECEIPTS", 2)
    assert server.server.claim_attempt("attempt-live-0001", "/api/gates/run", "one")[0] == "claimed"
    assert server.server.claim_attempt("attempt-live-0002", "/api/gates/run", "two")[0] == "claimed"

    status, body = server.post(
        "/api/git/workflow",
        {"operation": "status", "dry_run": True},
        attempt_key="attempt-capacity-http",
    )
    assert status == 503
    assert body == {
        "ok": False,
        "error": "operator attempt capacity is fully in use",
        "error_code": "attempt_capacity_exhausted",
        "retryable": True,
    }

    server.server.finish_attempt("attempt-live-0001", 200, {"ok": True})
    claim, _receipt = server.server.claim_attempt(
        "attempt-live-0003", "/api/gates/run", "three"
    )
    assert claim == "claimed"
    assert "attempt-live-0001" not in server.server._attempt_receipts
    assert set(server.server._attempt_receipts) == {
        "attempt-live-0002",
        "attempt-live-0003",
    }


def test_unexpected_post_exception_closes_attempt_with_sanitized_replay(
    server: _Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError("private-internal-detail-must-not-leak")

    monkeypatch.setattr(server_module, "run_action", explode)
    key = "attempt-unexpected-0001"
    status, body = server.post(
        "/api/actions/run",
        {"action_id": "synthetic"},
        attempt_key=key,
    )

    assert status == 500
    assert body == {
        "ok": False,
        "error": "operator request failed",
        "error_code": "internal_operator_error",
        "attempt_key": key,
        "replayed": False,
    }
    assert "private-internal" not in json.dumps(body)

    replay_status, replay = server.post(
        "/api/actions/run",
        {"action_id": "synthetic"},
        attempt_key=key,
    )
    assert replay_status == 500
    assert replay["replayed"] is True
    assert replay["attempt_key"] == key


@pytest.mark.parametrize(
    "invalid_result",
    [
        {"ok": True, "value": {"not-json"}},
        {"ok": True, "value": float("nan")},
    ],
)
def test_non_json_operator_result_becomes_safe_replayable_500(
    server: _Server,
    monkeypatch: pytest.MonkeyPatch,
    invalid_result: dict[str, object],
) -> None:
    monkeypatch.setattr(
        server_module,
        "run_action",
        lambda *_args, **_kwargs: invalid_result,
    )
    key = "attempt-invalid-json-0001"

    status, body = server.post(
        "/api/actions/run",
        {"action_id": "synthetic"},
        attempt_key=key,
    )

    assert status == 500
    assert body == {
        "ok": False,
        "error": "operator request failed",
        "error_code": "internal_operator_error",
        "attempt_key": key,
        "replayed": False,
    }
    replay_status, replay = server.post(
        "/api/actions/run",
        {"action_id": "synthetic"},
        attempt_key=key,
    )
    assert replay_status == 500
    assert replay["replayed"] is True
    assert replay["attempt_key"] == key


def test_post_keeps_prior_snapshot_until_mutation_finishes_then_invalidates(
    server: _Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status, before = server.get("/api/snapshot")
    assert status == 200
    before_id = before["manifest.json"]["snapshot_id"]
    entered = threading.Event()
    release = threading.Event()
    source = server.server.root / "memories/index.md"

    def blocked_action(*_args: object, **_kwargs: object) -> dict[str, object]:
        source.write_text(
            source.read_text(encoding="utf-8")
            + "\nPartially visible local mutation.\n",
            encoding="utf-8",
        )
        entered.set()
        assert release.wait(5)
        return {"ok": True, "action_id": "synthetic"}

    monkeypatch.setattr(server_module, "run_action", blocked_action)
    result: list[tuple[int, dict[str, Any]]] = []
    worker = threading.Thread(
        target=lambda: result.append(
            server.post("/api/actions/run", {"action_id": "synthetic"})
        )
    )
    worker.start()
    assert entered.wait(5)

    during_status, during = server.get("/api/snapshot")
    assert during_status == 200
    assert during["manifest.json"]["snapshot_id"] == before_id
    assert server.server._snapshot_cache is not None

    release.set()
    worker.join(5)
    assert result and result[0][0] == 200
    assert server.server._snapshot_cache is None
    after_status, after = server.get("/api/snapshot")
    assert after_status == 200
    assert after["manifest.json"]["snapshot_id"] != before_id


def test_post_response_is_not_observable_before_snapshot_commit_boundary(
    server: _Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status, before = server.get("/api/snapshot")
    assert status == 200
    before_id = before["manifest.json"]["snapshot_id"]
    source = server.server.root / "memories/index.md"
    response_written = threading.Event()
    release_handler = threading.Event()
    client_received = threading.Event()
    original_send = server_module.CockpitRequestHandler._send_json

    def mutate(*_args: object, **_kwargs: object) -> dict[str, object]:
        source.write_text(
            source.read_text(encoding="utf-8")
            + "\nCommitted before response visibility.\n",
            encoding="utf-8",
        )
        return {"ok": True, "action_id": "synthetic"}

    def blocked_after_write(
        handler: server_module.CockpitRequestHandler,
        payload: object,
        *,
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        original_send(handler, payload, status=status)
        if (
            handler.command == "POST"
            and handler.path == "/api/actions/run"
        ):
            response_written.set()
            assert release_handler.wait(5)

    monkeypatch.setattr(server_module, "run_action", mutate)
    monkeypatch.setattr(
        server_module.CockpitRequestHandler,
        "_send_json",
        blocked_after_write,
    )
    result: list[tuple[int, dict[str, Any]]] = []

    def post_action() -> None:
        result.append(server.post("/api/actions/run", {"action_id": "synthetic"}))
        client_received.set()

    worker = threading.Thread(target=post_action)
    worker.start()
    assert response_written.wait(5)
    assert client_received.wait(5)

    # The server handler is deliberately still blocked after socket write. A
    # response-visible commit boundary must already have invalidated A and
    # ended the mutation barrier, so this immediate client refetch sees B.
    after_status, after = server.get("/api/snapshot")
    assert after_status == 200
    assert after["manifest.json"]["snapshot_id"] != before_id

    release_handler.set()
    worker.join(5)
    assert result and result[0][0] == 200


def test_attempt_success_is_not_replayable_before_snapshot_commit_boundary(
    server: _Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status, before = server.get("/api/snapshot")
    assert status == 200
    before_id = before["manifest.json"]["snapshot_id"]
    source = server.server.root / "memories/index.md"
    commit_entered = threading.Event()
    release_commit = threading.Event()
    client_received = threading.Event()
    original_invalidate = server.server.invalidate_snapshot_cache
    first_commit = True

    def mutate(*_args: object, **_kwargs: object) -> dict[str, object]:
        source.write_text(
            source.read_text(encoding="utf-8")
            + "\nAttempt receipt commit boundary.\n",
            encoding="utf-8",
        )
        return {"ok": True, "action_id": "synthetic"}

    def blocked_commit() -> None:
        nonlocal first_commit
        if first_commit:
            first_commit = False
            commit_entered.set()
            assert release_commit.wait(5)
        original_invalidate()

    monkeypatch.setattr(server_module, "run_action", mutate)
    monkeypatch.setattr(server.server, "invalidate_snapshot_cache", blocked_commit)
    key = "attempt-commit-boundary-0001"
    result: list[tuple[int, dict[str, Any]]] = []

    def post_action() -> None:
        result.append(
            server.post(
                "/api/actions/run",
                {"action_id": "synthetic"},
                attempt_key=key,
            )
        )
        client_received.set()

    worker = threading.Thread(target=post_action)
    worker.start()
    assert commit_entered.wait(5)

    retry_status, retry = server.post(
        "/api/actions/run",
        {"action_id": "synthetic"},
        attempt_key=key,
    )
    assert retry_status == 409
    assert retry["error"] == "attempt is already in progress"
    assert client_received.is_set() is False
    during_status, during = server.get("/api/snapshot")
    assert during_status == 200
    assert during["manifest.json"]["snapshot_id"] == before_id

    release_commit.set()
    worker.join(5)
    assert result and result[0][0] == 200
    assert client_received.is_set()
    after_status, after = server.get("/api/snapshot")
    assert after_status == 200
    assert after["manifest.json"]["snapshot_id"] != before_id

    replay_status, replay = server.post(
        "/api/actions/run",
        {"action_id": "synthetic"},
        attempt_key=key,
    )
    assert replay_status == 200
    assert replay["replayed"] is True


def test_snapshot_cache_detects_same_size_external_editor_replacement(
    server: _Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status, first = server.get("/api/snapshot")
    assert status == 200
    first_id = first["manifest.json"]["snapshot_id"]

    original_build = server_module.build_snapshot
    build_calls = 0

    def counted_build(*args: object, **kwargs: object) -> dict[str, dict[str, Any]]:
        nonlocal build_calls
        build_calls += 1
        return original_build(*args, **kwargs)

    monkeypatch.setattr(server_module, "build_snapshot", counted_build)
    status, cached = server.get("/api/snapshot")
    assert status == 200
    assert cached["manifest.json"]["snapshot_id"] == first_id
    assert build_calls == 0

    source = server.server.root / "memories/index.md"
    before = source.stat()
    replacement = source.with_name(".index.md.editor-swap")
    original = source.read_bytes()
    changed = original.replace(b"Stale root", b"Fresh root")
    assert len(changed) == len(original) and changed != original
    replacement.write_bytes(changed)
    os.utime(
        replacement,
        ns=(before.st_atime_ns, before.st_mtime_ns),
    )
    os.replace(replacement, source)
    after = source.stat()
    assert after.st_size == before.st_size
    assert after.st_mtime_ns == before.st_mtime_ns
    assert after.st_ino != before.st_ino

    status, refreshed = server.get("/api/snapshot")
    assert status == 200
    assert refreshed["manifest.json"]["snapshot_id"] != first_id
    assert build_calls == 1
    root_page = next(
        page for page in refreshed["pages.json"]["pages"] if page["id"] == "root"
    )
    assert "Fresh root" in root_page["summary"]

    status, same_revision = server.get("/api/snapshot")
    assert status == 200
    assert (
        same_revision["manifest.json"]["snapshot_id"]
        == refreshed["manifest.json"]["snapshot_id"]
    )
    assert build_calls == 1


def test_snapshot_cache_observes_external_branch_head_and_index_changes(
    server: _Server,
) -> None:
    root = server.server.root
    subprocess.run(
        ["git", "config", "user.email", "snapshot@example.test"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Snapshot Test"],
        cwd=root,
        check=True,
    )
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial snapshot fixture"],
        cwd=root,
        check=True,
        capture_output=True,
    )

    status, main_snapshot = server.get("/api/snapshot")
    assert status == 200, main_snapshot
    assert main_snapshot["git.json"]["current_branch"] == "main"

    subprocess.run(
        ["git", "switch", "-c", "external-freshness"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    status, branch_snapshot = server.get("/api/snapshot")
    assert status == 200
    assert branch_snapshot["git.json"]["current_branch"] == "external-freshness"
    assert (
        branch_snapshot["manifest.json"]["snapshot_id"]
        != main_snapshot["manifest.json"]["snapshot_id"]
    )

    page = root / "memories/index.md"
    page.write_text(
        page.read_text(encoding="utf-8") + "\nStaged external revision.\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "memories/index.md"], cwd=root, check=True)
    status, staged_snapshot = server.get("/api/snapshot")
    assert status == 200
    assert (
        staged_snapshot["manifest.json"]["snapshot_id"]
        != branch_snapshot["manifest.json"]["snapshot_id"]
    )
    changed = staged_snapshot["git.json"]["worktree"]["changed_files"]
    assert any(row["path"] == "memories/index.md" and row["staged"] for row in changed)


def test_linked_worktree_fingerprint_hashes_common_branch_refs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WIKI_COCKPIT_CORS_ORIGINS", raising=False)
    primary = tmp_path / "primary"
    primary.mkdir()
    _repo(primary)
    subprocess.run(
        ["git", "config", "user.email", "worktree@example.test"],
        cwd=primary,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Worktree Test"],
        cwd=primary,
        check=True,
    )
    subprocess.run(["git", "add", "-A"], cwd=primary, check=True)
    subprocess.run(
        ["git", "commit", "-m", "linked worktree fixture"],
        cwd=primary,
        check=True,
        capture_output=True,
    )
    linked = tmp_path / "linked"
    subprocess.run(
        ["git", "worktree", "add", "-b", "feature", str(linked), "HEAD"],
        cwd=primary,
        check=True,
        capture_output=True,
    )
    cockpit = CockpitServer(("127.0.0.1", 0), linked, load_config(linked))
    try:
        before_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=linked,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        before = cockpit._snapshot_source_revision()
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "identical tree successor"],
            cwd=linked,
            check=True,
            capture_output=True,
        )
        after_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=linked,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain=v1"],
            cwd=linked,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        after = cockpit._snapshot_source_revision()

        assert before_head != after_head
        assert status == ""
        assert before.complete and after.complete
        assert before.digest != after.digest
    finally:
        cockpit.server_close()


def test_snapshot_cache_never_commits_an_unstable_external_revision(
    server: _Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status, stable = server.get("/api/snapshot")
    assert status == 200
    stable_id = stable["manifest.json"]["snapshot_id"]
    source = server.server.root / "memories/index.md"
    source.write_text(
        source.read_text(encoding="utf-8") + "\nExternal change begins.\n",
        encoding="utf-8",
    )

    original_build = server_module.build_snapshot
    build_calls = 0

    def racing_build(*args: object, **kwargs: object) -> dict[str, dict[str, Any]]:
        nonlocal build_calls
        build_calls += 1
        payloads = original_build(*args, **kwargs)
        source.write_text(
            source.read_text(encoding="utf-8")
            + f"\nConcurrent writer step {build_calls}.\n",
            encoding="utf-8",
        )
        return payloads

    monkeypatch.setattr(server_module, "build_snapshot", racing_build)
    status, during_write = server.get("/api/snapshot")
    assert status == 200
    assert during_write["manifest.json"]["snapshot_id"] == stable_id
    assert build_calls == server.server.SNAPSHOT_STABLE_BUILD_ATTEMPTS

    health_status, health = server.get("/api/health")
    assert health_status == 200
    assert (
        health["api_snapshot_serving"]["external_freshness"]["last_result"]
        == "served_prior_stable_during_source_change"
    )
    assert str(server.server.root) not in json.dumps(
        health["api_snapshot_serving"]["external_freshness"]
    )

    monkeypatch.setattr(server_module, "build_snapshot", original_build)
    status, settled = server.get("/api/snapshot")
    assert status == 200
    assert settled["manifest.json"]["snapshot_id"] != stable_id


def test_snapshot_config_change_fails_closed_until_operator_restart(
    server: _Server,
) -> None:
    status, stable = server.get("/api/snapshot")
    assert status == 200
    assert stable["manifest.json"]["repo"]["repo_id"] == "srv-test"

    config_path = server.server.root / "wiki.config.yaml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "repo_id: srv-test",
            "repo_id: externally-changed",
        ),
        encoding="utf-8",
    )
    status, blocked = server.get("/api/snapshot")

    assert status == 503
    assert blocked == {
        "ok": False,
        "error": "wiki configuration changed; restart the local operator",
        "error_code": "snapshot_configuration_restart_required",
        "retryable": False,
    }
    assert "srv-test" not in json.dumps(blocked)
    assert "externally-changed" not in json.dumps(blocked)

    health_status, health = server.get("/api/health")
    assert health_status == 200
    assert health["repo"] == "srv-test"
    assert (
        health["api_snapshot_serving"]["external_freshness"]["last_result"]
        == "configuration_changed_restart_required"
    )


def test_snapshot_readable_symlink_fails_closed_without_exposing_paths(
    server: _Server,
) -> None:
    status, _stable = server.get("/api/snapshot")
    assert status == 200
    source = server.server.root / "memories/index.md"
    external_target = server.server.root / "outside-memory-target.md"
    external_target.write_bytes(source.read_bytes())
    source.unlink()
    source.symlink_to(external_target)

    status, blocked = server.get("/api/snapshot")
    assert status == 503
    assert blocked == {
        "ok": False,
        "error": "live snapshot input boundary is unsupported",
        "error_code": "snapshot_source_symlink_blocked",
        "retryable": False,
    }
    assert str(source) not in json.dumps(blocked)
    assert str(external_target) not in json.dumps(blocked)

    health_status, health = server.get("/api/health")
    assert health_status == 200
    assert (
        health["api_snapshot_serving"]["external_freshness"]["last_result"]
        == "unsafe_symlink_input_blocked"
    )


def test_parallel_snapshot_file_burst_coalesces_one_revision_observation(
    server: _Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status, stable = server.get("/api/snapshot")
    assert status == 200
    stable_id = stable["manifest.json"]["snapshot_id"]
    original_revision = server.server._snapshot_source_revision
    revision_calls = 0
    calls_lock = threading.Lock()
    first_entered = threading.Event()
    all_started = threading.Event()
    worker_count = 24
    started = 0
    start_barrier = threading.Barrier(worker_count)

    def observed_revision() -> server_module._SnapshotSourceRevision:
        nonlocal revision_calls
        with calls_lock:
            revision_calls += 1
            current = revision_calls
        if current == 1:
            first_entered.set()
            assert all_started.wait(5)
            # Let every already-started call capture its linearization time and
            # queue on the snapshot lock before this observation completes.
            threading.Event().wait(0.1)
        return original_revision()

    monkeypatch.setattr(
        server.server,
        "_snapshot_source_revision",
        observed_revision,
    )
    results: list[str] = []

    def load_one() -> None:
        nonlocal started
        start_barrier.wait()
        with calls_lock:
            started += 1
            if started == worker_count:
                all_started.set()
        payloads = server.server.snapshot_payloads()
        results.append(payloads["manifest.json"]["snapshot_id"])

    workers = [threading.Thread(target=load_one) for _ in range(worker_count)]
    for worker in workers:
        worker.start()
    assert first_entered.wait(5)
    for worker in workers:
        worker.join(10)

    assert all(not worker.is_alive() for worker in workers)
    assert results == [stable_id] * worker_count
    assert revision_calls == 1

    # Coalescing is overlap-bound, not a time window: a later read performs a
    # new full comparison and can therefore observe an external editor.
    server.server.snapshot_payloads()
    assert revision_calls == 2


def test_snapshot_boot_is_one_revision_check_and_keeps_temporal_history_lazy(
    server: _Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status, stable = server.get("/api/snapshot")
    assert status == 200
    stable_id = stable["manifest.json"]["snapshot_id"]
    original_revision = server.server._snapshot_source_revision
    revision_calls = 0

    def observed_revision() -> server_module._SnapshotSourceRevision:
        nonlocal revision_calls
        revision_calls += 1
        return original_revision()

    monkeypatch.setattr(
        server.server,
        "_snapshot_source_revision",
        observed_revision,
    )
    boot_status, boot = server.get("/api/snapshot/boot")

    assert boot_status == 200
    assert boot["manifest.json"]["snapshot_id"] == stable_id
    assert "temporal_graph.json" not in boot
    assert revision_calls == 1


def test_snapshot_write_is_post_only(server: _Server) -> None:
    status, body = server.get("/api/snapshot/write")
    assert status == 405 and "POST-only" in body["error"]


def test_snapshot_write_reports_committed_revision_and_health_matches(
    server: _Server,
) -> None:
    status, body = server.post("/api/snapshot/write", {})

    assert status == 200
    assert body["ok"] is True
    assert body["committed"] is True
    assert body["publication"] == "immutable_revision_pointer"
    assert body["snapshot_id"]
    assert len(body["active_revision"]) == 64
    assert body["cleanup_warnings"] == []
    assert body["recovery_paths"] == []
    assert set(body["files"]) == set(SNAPSHOT_FILES)

    health_status, health = server.get("/api/health")
    assert health_status == 200
    activation = health["snapshot_publication"]
    assert activation["layout"] == "immutable_revision_relative_pointer"
    assert activation["pointer_state"] == "full_inventory_owner_repo_and_hash_valid"
    assert activation["active_revision"] == body["active_revision"]
    assert activation["active_snapshot_id"] == body["snapshot_id"]
    assert activation["leases_state"] == "safe_directory"

    # Filesystem publication and /api/snapshot are intentionally different
    # surfaces: active disk revision A remains pinned while the live API cache
    # rebuilds source state B. Health must say that it does not consume A.
    source = server.server.root / "memories/index.md"
    source.write_text(
        source.read_text(encoding="utf-8") + "\nLive source B.\n",
        encoding="utf-8",
    )
    server.server.invalidate_snapshot_cache()
    live_status, live = server.get("/api/snapshot")
    assert live_status == 200
    assert live["manifest.json"]["snapshot_id"] != body["snapshot_id"]
    assert (
        json.loads(
            (server.server.snapshot_dir / "manifest.json").read_text(encoding="utf-8")
        )["snapshot_id"]
        == body["snapshot_id"]
    )
    health_status, health = server.get("/api/health")
    assert health_status == 200
    assert health["api_snapshot_serving"]["uses_published_snapshot_pointer"] is False


def test_operator_action_transition_writes_markdown_and_returns_safe_receipt(
    server: _Server,
) -> None:
    path = _server_action(server.server.root)
    before_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    secret_reason = "Synthetic operator review started."

    status, body = server.post(
        "/api/actions/transition",
        {
            "page_ref": "memories/actions/action-server-synthetic.md",
            "next_state": "in_progress",
            "expected_sha256": before_sha,
            "reason": secret_reason,
        },
    )

    assert status == 200
    assert body["ok"] is True
    assert body["changed"] is True
    assert body["previous_state"] == "open"
    assert body["next_state"] == "in_progress"
    assert body["receipt_id"].startswith("sha256:")
    assert secret_reason not in json.dumps(body)
    values, _body = parse_frontmatter(path)
    assert values["action_state"] == "in_progress"
    assert len(values["action_state_history"]) == 1
    # The endpoint mutates the Markdown source. It does not publish a static
    # snapshot; the server-wide POST invalidation makes the next live snapshot
    # read rebuild from that source.
    assert server.server._snapshot_cache is None


def test_operator_blocked_transition_binds_structured_blocker_refs(
    server: _Server,
) -> None:
    path = _server_action(server.server.root)

    status, body = server.post(
        "/api/actions/transition",
        {
            "page_ref": "memories/actions/action-server-synthetic.md",
            "next_state": "blocked",
            "expected_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "blocked_by": ["source-synthetic-dependency"],
            "blocker_reason": "Synthetic dependency is unavailable.",
        },
    )

    assert status == 200
    assert body["next_state"] == "blocked"
    values, _body = parse_frontmatter(path)
    assert values["blocked_by"] == ["source-synthetic-dependency"]
    assert values["blocker_reason"] == "Synthetic dependency is unavailable."
    assert values["action_state_history"][-1]["support_fields"] == [
        "blocked_by",
        "blocker_reason",
    ]


def test_operator_action_transition_is_idempotent_and_content_hash_bound(
    server: _Server,
) -> None:
    path = _server_action(server.server.root)
    first_status, first = server.post(
        "/api/actions/transition",
        {
            "page_ref": "memories/actions/action-server-synthetic.md",
            "next_state": "in_progress",
            "expected_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        },
    )
    after_first = path.read_bytes()
    second_status, second = server.post(
        "/api/actions/transition",
        {
            "page_ref": "memories/actions/action-server-synthetic.md",
            "next_state": "in_progress",
            "expected_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        },
    )

    assert first_status == second_status == 200
    assert first["receipt_id"] == second["receipt_id"]
    assert second["changed"] is False
    assert second["idempotent"] is True
    assert path.read_bytes() == after_first
    assert len(parse_frontmatter(path)[0]["action_state_history"]) == 1


def test_operator_action_transition_refuses_invalid_or_stale_edges_safely(
    server: _Server,
) -> None:
    path = _server_action(server.server.root, state="in_progress")
    before = path.read_bytes()
    page_ref = "memories/actions/action-server-synthetic.md"

    status, invalid = server.post(
        "/api/actions/transition",
        {
            "page_ref": page_ref,
            "next_state": "open",
            "expected_sha256": hashlib.sha256(before).hexdigest(),
        },
    )
    assert status == 409
    assert invalid["error_code"] == "invalid_transition"
    assert invalid["current_state"] == "in_progress"
    assert str(server.server.root) not in json.dumps(invalid)

    status, stale = server.post(
        "/api/actions/transition",
        {
            "page_ref": page_ref,
            "next_state": "done",
            "expected_sha256": "0" * 64,
            "completion_receipt": "commit:synthetic",
        },
    )
    assert status == 409
    assert stale["error_code"] == "stale_action_revision"
    assert path.read_bytes() == before


def test_operator_action_transition_enforces_terminal_receipt_and_required_input(
    server: _Server,
) -> None:
    path = _server_action(server.server.root)
    page_ref = "memories/actions/action-server-synthetic.md"
    before = path.read_bytes()

    status, missing_input = server.post(
        "/api/actions/transition",
        {"page_ref": page_ref, "next_state": "done"},
    )
    assert status == 400
    assert "expected_sha256" in missing_input["error"]

    status, absolute = server.post(
        "/api/actions/transition",
        {
            "page_ref": str(path),
            "next_state": "done",
            "expected_sha256": hashlib.sha256(before).hexdigest(),
            "completion_receipt": "commit:synthetic",
        },
    )
    assert status == 400
    assert absolute["error"] == "page_ref must be repository-relative"
    assert str(path) not in json.dumps(absolute)

    status, missing_receipt = server.post(
        "/api/actions/transition",
        {
            "page_ref": page_ref,
            "next_state": "done",
            "expected_sha256": hashlib.sha256(before).hexdigest(),
        },
    )
    assert status == 400
    assert missing_receipt["error_code"] == "missing_completion_receipt"
    assert path.read_bytes() == before

    status, completed = server.post(
        "/api/actions/transition",
        {
            "page_ref": page_ref,
            "next_state": "done",
            "expected_sha256": hashlib.sha256(before).hexdigest(),
            "completion_receipt": "commit:synthetic",
        },
    )
    assert status == 200
    assert completed["next_state"] == "done"
    values, _body = parse_frontmatter(path)
    assert "next_action" not in values
    assert values["completed_at"] == values["action_state_history"][-1]["at"]
    assert "T" in values["completed_at"] and values["completed_at"].endswith("Z")


def test_operator_action_transition_reports_lock_backend_outage_as_unavailable(
    server: _Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import wiki_core.action_transition as transition_module

    path = _server_action(server.server.root)
    before = path.read_bytes()
    monkeypatch.setattr(transition_module, "_fcntl", None)
    monkeypatch.setattr(transition_module, "_msvcrt", None)

    status, body = server.post(
        "/api/actions/transition",
        {
            "page_ref": "memories/actions/action-server-synthetic.md",
            "next_state": "in_progress",
            "expected_sha256": hashlib.sha256(before).hexdigest(),
        },
    )

    assert status == 503
    assert body["error_code"] == "action_lock_backend_unavailable"
    assert path.read_bytes() == before


def test_operator_command_cards_cannot_be_confused_with_domain_action_pages(
    server: _Server,
) -> None:
    path = _server_action(server.server.root)
    before = path.read_bytes()

    status, body = server.post(
        "/api/actions/run",
        {"action_id": "action-server-synthetic", "dry_run": False},
    )

    assert status == 400
    assert body["error"] == "unknown action"
    assert path.read_bytes() == before


def test_dynamic_reader_rejects_mixed_revision_then_refreshes(server: _Server) -> None:
    status, snapshot_a = server.get("/api/snapshot")
    assert status == 200
    snapshot_a_id = snapshot_a["manifest.json"]["snapshot_id"]
    page_path = server.server.root / "memories/index.md"
    page_path.write_text(
        page_path.read_text(encoding="utf-8") + "\nRevision B body.\n",
        encoding="utf-8",
    )

    # Client B advances the server cache before stale client A opens its reader.
    status, snapshot_b = server.get("/api/snapshot")
    assert status == 200
    snapshot_b_id = snapshot_b["manifest.json"]["snapshot_id"]
    assert snapshot_b_id != snapshot_a_id

    status, conflict = server.get(
        f"/api/pages/root/content?snapshot_id={snapshot_a_id}"
    )
    assert status == 409
    assert conflict["error_code"] == "snapshot_revision_mismatch"
    assert conflict["snapshot_id"] == snapshot_b_id
    assert conflict["expected_snapshot_id"] == snapshot_a_id
    assert "body" not in conflict

    status, content_b = server.get(
        f"/api/pages/root/content?snapshot_id={snapshot_b_id}"
    )
    assert status == 200
    assert content_b["snapshot_id"] == snapshot_b_id
    assert "Revision B body." in content_b["body"]
