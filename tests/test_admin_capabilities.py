"""Admin handshake and discovery (god-mode plan §6.3, §12.1, §12.6, §17.4).

The discovery surface must be honest and inert: it names capability groups,
it never grants one, and no payload may carry session material. Config
parsing for the `admin:`/`features:` blocks is strict — a typo fails loud
instead of silently reshaping the admin surface.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wiki_core.config import WikiConfig, load_config
from wiki_core.web.admin.capabilities import (
    ADMIN_CAPABILITY_GROUPS,
    ADMIN_CAPABILITY_SCHEMA_VERSION,
    ADMIN_SERVER_VERSION,
    ADMIN_SESSION_STATES,
    admin_capabilities_payload,
    admin_health_summary,
)

# Reuse the running-server fixture machinery from the web-server suite.
from tests.test_web_server import _repo, _Server, _write


@pytest.fixture()
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("WIKI_COCKPIT_CORS_ORIGINS", raising=False)
    config = _repo(tmp_path)
    srv = _Server(tmp_path, config)
    try:
        yield srv
    finally:
        srv.close()


# ---------------------------------------------------------------------------
# /api/health admin summary (§12.6)
# ---------------------------------------------------------------------------


def test_health_carries_non_sensitive_admin_summary(server: _Server) -> None:
    status, body = server.get("/api/health")
    assert status == 200
    assert body["admin"] == {
        "available": True,
        "adapter": "local_startup_code",
        "server_version": "wiki_admin.v1",
        "capability_schema": "wiki_admin_capabilities.v1",
    }
    # No token, code, role detail or internal policy in the health block —
    # the four keys above are the whole contract (§12.6).
    flat = json.dumps(body["admin"]).lower()
    for forbidden in ("token", "unlock_code", "password", "secret", "role"):
        assert forbidden not in flat


def test_health_admin_summary_reports_disabled_admin(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("WIKI_COCKPIT_CORS_ORIGINS", raising=False)
    config = _repo(tmp_path)
    _write(
        tmp_path / "wiki.config.yaml",
        "repo_id: srv-test\ndefault_context: system\ncodex:\n  enabled: false\n"
        "admin:\n  enabled: false\n",
    )
    srv = _Server(tmp_path, load_config(tmp_path))
    try:
        status, body = srv.get("/api/health")
        assert status == 200
        assert body["admin"]["available"] is False
        assert body["admin"]["adapter"] is None
    finally:
        srv.close()
    del config


# ---------------------------------------------------------------------------
# GET /api/admin/capabilities (§12.1) — locked / unavailable, never a grant
# ---------------------------------------------------------------------------


def test_capabilities_endpoint_is_locked_and_grants_nothing(server: _Server) -> None:
    status, body = server.get("/api/admin/capabilities")
    assert status == 200
    assert body["ok"] is True
    assert body["schema_version"] == "wiki_admin_capabilities.v1"
    assert body["server_version"] == "wiki_admin.v1"
    assert body["adapter"] == "local_startup_code"
    assert body["session_state"] == "locked"
    assert body["session"] is None
    assert body["read_only"] is True
    ids = [entry["id"] for entry in body["capabilities"]]
    assert ids == list(ADMIN_CAPABILITY_GROUPS)
    assert all(entry["granted"] is False for entry in body["capabilities"])
    # Break-glass is off by default and says so (§17.4).
    break_glass = next(e for e in body["capabilities"] if e["id"] == "break_glass.local")
    assert break_glass["reason"] == "disabled_by_config"
    # The URL never authorizes: fetching twice still grants nothing.
    _status, again = server.get("/api/admin/capabilities")
    assert again["session_state"] == "locked"


def test_capabilities_payload_never_carries_session_material(server: _Server) -> None:
    _status, body = server.get("/api/admin/capabilities")
    flat = json.dumps(body).lower()
    for forbidden in ("token", "nonce", "unlock_code", "password", "secret"):
        assert forbidden not in flat
    assert set(body["session_states"]) == set(ADMIN_SESSION_STATES)


def test_capabilities_endpoint_reports_unavailable_when_disabled(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("WIKI_COCKPIT_CORS_ORIGINS", raising=False)
    _repo(tmp_path)
    _write(
        tmp_path / "wiki.config.yaml",
        "repo_id: srv-test\ndefault_context: system\ncodex:\n  enabled: false\n"
        "admin:\n  enabled: false\n",
    )
    srv = _Server(tmp_path, load_config(tmp_path))
    try:
        status, body = srv.get("/api/admin/capabilities")
        assert status == 200
        assert body["session_state"] == "unavailable"
        assert body["adapter"] is None
        assert all(entry["reason"] == "admin_disabled" for entry in body["capabilities"])
    finally:
        srv.close()


def test_capabilities_endpoint_rejects_post_without_operator_contract(
    server: _Server,
) -> None:
    # POST is not part of the discovery surface; the mutation boundary keeps
    # its normal typed refusal (no admin mutation endpoint exists yet).
    status, body = server.post("/api/admin/capabilities", {})
    assert status == 404
    assert body["ok"] is False


# ---------------------------------------------------------------------------
# Pure payload builders (deterministic; no server needed)
# ---------------------------------------------------------------------------


def test_payload_builders_are_deterministic() -> None:
    config = WikiConfig()
    assert admin_capabilities_payload(config) == admin_capabilities_payload(config)
    assert admin_health_summary(config) == admin_health_summary(config)
    assert admin_health_summary(config)["server_version"] == ADMIN_SERVER_VERSION
    assert (
        admin_health_summary(config)["capability_schema"]
        == ADMIN_CAPABILITY_SCHEMA_VERSION
    )


def test_break_glass_reason_follows_config() -> None:
    config = WikiConfig(admin={**WikiConfig().admin, "allow_break_glass": True})
    payload = admin_capabilities_payload(config)
    break_glass = next(
        e for e in payload["capabilities"] if e["id"] == "break_glass.local"
    )
    assert break_glass == {
        "id": "break_glass.local",
        "granted": False,
        "reason": "session_not_authorized",
    }


# ---------------------------------------------------------------------------
# Strict admin:/features: config parsing (§17.4)
# ---------------------------------------------------------------------------


def _config_with(tmp_path: Path, body: str) -> WikiConfig:
    (tmp_path / "wiki.config.yaml").write_text(body, encoding="utf-8")
    return load_config(tmp_path)


def test_admin_defaults_are_safe(tmp_path: Path) -> None:
    cfg = _config_with(tmp_path, "repo_id: r\nlanguage: en\n")
    assert cfg.admin_enabled is True
    assert cfg.admin_break_glass_allowed is False
    assert cfg.admin["local_unlock"] == "startup_code"
    assert cfg.admin["session_ttl_minutes"] == 15
    assert cfg.admin["idle_lock_minutes"] == 5
    assert cfg.admin["default_role"] == "admin"
    assert cfg.features == {"takezo_easter_egg": True, "takezo_companion": False}


def test_admin_block_parses_documented_shape(tmp_path: Path) -> None:
    cfg = _config_with(
        tmp_path,
        "repo_id: r\nlanguage: en\n"
        "admin:\n"
        "  enabled: true\n"
        "  local_unlock: startup_code\n"
        "  session_ttl_minutes: 30\n"
        "  idle_lock_minutes: 10\n"
        "  allow_break_glass: false\n"
        "  require_plan_sha: true\n"
        "  default_role: observer\n"
        "  audit:\n"
        "    enabled: true\n"
        "    hash_chain: true\n"
        "    retain_events: 500\n"
        "  vision_lab:\n"
        "    enabled: true\n"
        "    discovery_threshold: 0.65\n"
        "    allow_recipe_promotion: true\n"
        "features:\n"
        "  takezo_easter_egg: true\n"
        "  takezo_companion: false\n",
    )
    assert cfg.admin["session_ttl_minutes"] == 30
    assert cfg.admin["idle_lock_minutes"] == 10
    assert cfg.admin["default_role"] == "observer"
    assert cfg.admin["audit"]["retain_events"] == 500
    assert cfg.admin["vision_lab"]["discovery_threshold"] == 0.65
    assert cfg.features["takezo_easter_egg"] is True


@pytest.mark.parametrize(
    "body, match",
    [
        ("admin:\n  enabled: maybe\n", "invalid boolean"),
        ("admin:\n  local_unlock: password_file\n", "local_unlock"),
        ("admin:\n  session_ttl_minutes: 0\n", "session_ttl_minutes"),
        ("admin:\n  session_ttl_minutes: 999999\n", "session_ttl_minutes"),
        ("admin:\n  idle_lock_minutes: -5\n", "idle_lock_minutes"),
        ("admin:\n  default_role: root\n", "default_role"),
        ("admin:\n  allow_break_glas: true\n", "unknown admin key"),
        ("admin:\n  audit:\n    retain_events: 0\n", "retain_events"),
        ("admin:\n  audit:\n    retention: 10\n", "unknown admin.audit"),
        ("admin:\n  vision_lab:\n    discovery_threshold: 1.5\n", "discovery_threshold"),
        ("features:\n  takezo_easter_egg: kinda\n", "invalid boolean"),
        ("features:\n  takezo_super_mode: true\n", "unknown feature flag"),
    ],
)
def test_admin_and_features_parse_strictly(tmp_path: Path, body: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        _config_with(tmp_path, f"repo_id: r\nlanguage: en\n{body}")


@pytest.mark.parametrize(
    "body",
    [
        "admin_token: abc\n",
        "admin:\n  enabled: true\nadmin_password: hunter2\n",
        "github_token: ghp_x\n",
        "llm:\n  nested:\n    admin_token: abc\n",
    ],
)
def test_secret_shaped_keys_fail_closed_anywhere(tmp_path: Path, body: str) -> None:
    with pytest.raises(ValueError, match="forbidden secret key"):
        _config_with(tmp_path, f"repo_id: r\nlanguage: en\n{body}")
