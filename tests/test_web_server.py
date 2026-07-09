from __future__ import annotations

import json
import subprocess
import threading
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

import pytest

from wiki_core.config import WikiConfig, load_config
from wiki_core.web.server import CockpitServer, main, serve


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
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def get_headers(self, path: str, headers: dict[str, str]) -> tuple[int, dict[str, str]]:
        req = urllib.request.Request(self.url(path), headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req) as resp:  # noqa: S310 - localhost test
                return resp.status, dict(resp.headers.items())
        except urllib.error.HTTPError as exc:
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
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # 4xx still carry a JSON envelope
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture()
def server(tmp_path: Path) -> Any:
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
    assert body["server_version"].startswith("wiki_web_server.")
    assert "codex" in body["schema_capabilities"]
    assert "briefs" in body["schema_capabilities"]
    assert "operator_security_v1" in body["schema_capabilities"]
    assert body["operator_security"]["nonce"] == server.server.operator_nonce
    assert body["operator_security"]["mutations"] == "post_only"


def test_local_cockpit_cors_allows_parallel_vite_previews(server: _Server) -> None:
    status, headers = server.get_headers("/api/health", {"Origin": "http://127.0.0.1:5174"})
    assert status == 200
    assert headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:5174"
    assert headers["Vary"] == "Origin"

    status, headers = server.get_headers("/api/health", {"Origin": "https://example.com"})
    assert status == 200
    assert "Access-Control-Allow-Origin" not in headers


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


def test_snapshot_write_is_post_only(server: _Server) -> None:
    status, body = server.get("/api/snapshot/write")
    assert status == 405 and "POST-only" in body["error"]
