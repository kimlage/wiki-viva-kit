from __future__ import annotations

import json
import subprocess
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from wiki_core.config import WikiConfig, load_config
from wiki_core.web.server import CockpitServer


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _repo(root: Path) -> WikiConfig:
    subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
    _write(root / "AGENTS.md", "# Agents\nHard rules.\n")
    _write(root / "wiki.config.yaml", "repo_id: srv-test\ndefault_context: system\n")
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

    def get(self, path: str) -> tuple[int, dict[str, Any]]:
        try:
            with urllib.request.urlopen(self.url(path)) as resp:  # noqa: S310 - localhost test
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # 4xx still carry a JSON envelope
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def post(self, path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            self.url(path), data=data, headers={"content-type": "application/json"}, method="POST"
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
