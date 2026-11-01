"""Pure runtime projection: synthetic evidence, no native account or RPC."""
import datetime as dt
import copy
import hashlib
import json
import subprocess
from dataclasses import replace

import pytest
import yaml

from tests.test_openclaw_commands import runtime, complete
from tests.test_openclaw_recurring import scheduled
from tests.test_web_server import _Server
from wiki_core.web import openclaw as oc, openclaw_recurring as recurring, server as web
from wiki_core.web.admin.audit import append_admin_audit_event, audit_log_path
from wiki_core.config import load_config

_REAL_GATEWAY_CALL = oc.Gateway.call


def enable_native_observation(root):
    config = yaml.safe_load((root / "wiki.config.yaml").read_text())
    config["openclaw"]["observation"] = {"mode": "resident", "profile": "research"}
    (root / "wiki.config.yaml").write_text(yaml.safe_dump(config))
    return load_config(root)


def resident_payload():
    return {"schema_version": "wiki_resident_observation.v1", "agentId": "research", "sessionKey": "agent:research:synthetic",
        "sessionId": "synthetic-session", "process_instance_id": "synthetic-process", "observed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "scope": "resident_gateway_owners", "complete": False, "resident_complete": True, "persisted_queue_count": None,
        "status": "observed", "has_active_run": True, "active_run_ids": ["synthetic-active"], "ids_truncated": False,
        "active_count": 1, "terminal_persistence_count": 2, "terminal_cleanup_count": 3, "queued_turn_count": 4,
        "pending_admission_count": 5, "error_code": None}


def test_get_qualifies_one_native_session_caches_in_ram_and_keeps_domain_writers_unreachable(runtime, monkeypatch):
    root, _, *_ = runtime
    cfg = enable_native_observation(root)
    native_calls = []
    def native(self, method, params):
        native_calls.append((method, params))
        assert method == "sessions.describe" and params == {"key": "agent:research:synthetic", "agentId": "research",
            "wikiObservation": {"version": 1, "sessionId": "synthetic-session"}}
        return resident_payload()
    monkeypatch.setattr(oc.Gateway, "call", native)
    monkeypatch.setattr(oc, "transport_observation", lambda config: {"status": "reachable", "scope": "loopback_tcp_only", "observed_at": None})
    for name in ("dispatch", "inspect", "release_mission_lock", "write_new"):
        monkeypatch.setattr(oc, name, forbidden)
    srv = _Server(root, cfg)
    before = {str(path): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    try:
        payload = srv.get("/api/runtime/observations")[1]
        observed = payload["openclaw"]["native_observations"][0]
        assert observed["status"] == "observed" and observed["active_count"] == 1 and observed["terminal_cleanup_count"] == 3
        assert observed["complete"] is False and observed["persisted_queue_count"] is None
        assert payload["openclaw"]["active_run"] is None and payload["openclaw"]["pending_inputs"] is None
        assert srv.get("/api/runtime/observations")[1]["openclaw"]["native_observations"][0] == observed
        assert len(native_calls) == 1
        srv.server._native_observation_cache = None
        monkeypatch.setattr(oc.Gateway, "call", lambda *a: {**resident_payload(), "sessionId": "rebound"})
        unknown = srv.get("/api/runtime/observations")[1]["openclaw"]["native_observations"][0]
        assert unknown["status"] == "unavailable" and unknown["active_count"] is None
        assert before == {str(path): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    finally:
        srv.close()


@pytest.mark.parametrize("change", [
    {"sessionId": "another-session"}, {"agentId": "another-agent"}, {"sessionKey": "agent:research:alias"},
    {"complete": True}, {"resident_complete": False}, {"persisted_queue_count": 0}, {"active_count": True},
    {"has_active_run": False}, {"active_run_ids": []}, {"ids_truncated": True}, {"unknown": "untrusted"},
    {"observed_at": "2020-01-01T00:00:00Z"}, {"observed_at": "2026-01-01T00:00:00"}, {"process_instance_id": "invalid/path"},
])
def test_native_response_fails_closed_without_fallback_or_stale_idle(runtime, monkeypatch, change):
    root, *_ = runtime
    cfg = enable_native_observation(root)
    calls = []
    monkeypatch.setattr(oc.Gateway, "call", lambda self, method, params: calls.append(method) or {**resident_payload(), **change})
    row = oc.native_runtime_observation(cfg)
    assert row["status"] == "unavailable" and row["active_run_ids"] is None and row["queued_turn_count"] is None
    assert calls == ["sessions.describe"]


def test_native_facade_uses_closed_params_existing_auth_and_bounded_timeout(runtime, monkeypatch):
    root, *_ = runtime
    cfg = enable_native_observation(root)
    recorded = []
    def run(argv, **kwargs):
        recorded.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, json.dumps(resident_payload()), "")
    monkeypatch.setattr(oc.Gateway, "call", _REAL_GATEWAY_CALL)
    monkeypatch.setattr(oc.subprocess, "run", run)
    assert oc.native_runtime_observation(cfg)["status"] == "observed"
    argv, options = recorded[0]
    assert argv[0] == "/synthetic/node" and argv[1].endswith("/scripts/openclaw/mission-rpc.mjs")
    assert options["timeout"] == 12
    assert set(json.loads(options["input"])) == {"method", "params", "expectUrl"}
    assert "synthetic-session" not in " ".join(argv)
    gateway = oc.Gateway(cfg.openclaw, cfg.openclaw["routes"]["research"])
    with pytest.raises(ValueError, match="method_not_allowed"):
        gateway.call("sessions.describe", {"key": "agent:research:synthetic"})
    assert len(recorded) == 1


@pytest.mark.parametrize("legacy", [False, True])
def test_observation_policy_does_not_reidentify_retained_execution(runtime, legacy):
    root, cfg, params, *_ = runtime
    plan = oc.plan_dispatch(root, cfg, params)
    if legacy:
        plan.pop("runtime_identity_sha256")
    oc.dispatch(root, cfg, plan)
    query = {"profile": "research", "action_id": "task", "effect_key": plan["effect_key"]}
    changed = enable_native_observation(root)
    oc.retained_intent(root, changed, query)
    data = yaml.safe_load((root / "wiki.config.yaml").read_text())
    data["openclaw"].pop("observation")
    (root / "wiki.config.yaml").write_text(yaml.safe_dump(data))
    oc.retained_intent(root, load_config(root), query)
    for key in ("node_binary", "entrypoint", "gateway"):
        altered = copy.deepcopy(data)
        altered["openclaw"][key] = "ws://127.0.0.1:19881" if key == "gateway" else "/synthetic/replacement"
        (root / "wiki.config.yaml").write_text(yaml.safe_dump(altered))
        with pytest.raises(ValueError, match="route_changed"):
            oc.retained_intent(root, load_config(root), query)


def forbidden(*args, **kwargs):
    raise AssertionError("observation entered a native API, account probe or writer")


def commit(root, message):
    for args in [("add", "."), ("commit", "-qm", message)]:
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.mark.parametrize("captured", [False, True])
def test_get_is_pure_and_retained_result_never_claims_current_activity(runtime, monkeypatch, captured):
    root, cfg, params, _, calls, _ = runtime
    plan = oc.plan_dispatch(root, cfg, params)
    oc.dispatch(root, cfg, plan)
    if captured:
        complete(runtime, plan)
        oc.inspect(root, cfg, {**params, "effect_key": plan["effect_key"]})
    srv = _Server(root, cfg)
    probes = []
    monkeypatch.setattr(oc, "transport_observation", lambda config: probes.append(True) or {
        "status": "reachable", "scope": "loopback_tcp_only", "observed_at": "2026-01-01T10:00:00Z"})
    monkeypatch.setattr(oc.Gateway, "call", forbidden)
    for name in ("inspect", "write_new", "release_mission_lock", "dispatch"):
        monkeypatch.setattr(oc, name, forbidden)
    for name in ("probe_codex_for", "probe_claude_for", "append_admin_audit_event", "build_admin_plan", "execute_admin_plan"):
        monkeypatch.setattr(web, name, forbidden)
    monkeypatch.setattr(srv.server, "snapshot_payloads", forbidden)
    before = {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    native_calls = list(calls)
    try:
        status, payload = srv.get("/api/runtime/observations")
        assert status == 200 and payload["schema_version"] == "wiki_runtime_observations.v1"
        local = payload["openclaw"]
        assert local["transport"]["status"] == "reachable"
        assert local["gateway_status"] == "not_observed"
        assert local["active_run"] is None and local["pending_inputs"] is None
        assert local["usage"] == {"status": "not_measured", "tokens": None, "cost": None}
        assert local["native_observations"] == [{"profile": "research", "observed_at": None,
            "status": "unavailable", "has_active_run": None, "active_run_ids": None,
            "session_status": None, "error_code": "native_read_api_may_write"}]
        attempt = local["attempts"][0]
        assert attempt["effect_key"] == plan["effect_key"] and attempt["has_result"] is captured
        assert attempt["status"] == ("result_retained" if captured else "awaiting_reconciliation")
        assert bool(attempt["result_captured_at"]) is captured
        assert attempt["run_id"] == plan["effect_key"] and attempt["action_path"] == plan["binding"]["action_path"]
        assert attempt["authorization"] == {"status": "not_observed"}
        assert attempt["review"] == {"status": "not_observed", "head": None}
        if captured:
            assert attempt["result"] == {"excerpt": "Synthetic result.", "truncated": False,
                "text_sha256": hashlib.sha256(b"Synthetic result.").hexdigest()}
            assert attempt["guard_admission"] == {"status": "retained_chain_verified",
                "model": "example-model", "effort": "high", "error_code": None}
        else:
            assert attempt["result"] is None and attempt["guard_admission"]["status"] == "not_observed"
        assert "synthetic-session" not in json.dumps(payload) and "/synthetic/state" not in json.dumps(payload)
        assert srv.get("/api/runtime/observations")[0] == 200 and len(probes) == 1
        assert calls == native_calls
        assert before == {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    finally:
        srv.close()


@pytest.mark.parametrize("damage", ["incomplete", "corrupt"])
def test_result_remains_readable_when_retained_guard_chain_is_unavailable(runtime, monkeypatch, damage):
    root, cfg, params, *_ = runtime
    plan = oc.plan_dispatch(root, cfg, params)
    oc.dispatch(root, cfg, plan)
    complete(runtime, plan)
    oc.inspect(root, cfg, {**params, "effect_key": plan["effect_key"]})
    directory = oc.storage(root, cfg, plan["effect_key"])
    if damage == "incomplete":
        (directory / "guard-bound-turn.json").unlink()
    else:
        guard = json.loads((directory / "guard-terminal.json").read_text())
        guard["turn_id"] = "unrelated-turn"
        (directory / "guard-terminal.json").write_text(json.dumps(guard))
    monkeypatch.setattr(oc.Gateway, "call", forbidden)
    monkeypatch.setattr(oc, "inspect", forbidden)
    before = {file.name: file.read_bytes() for file in directory.iterdir() if file.is_file()}
    attempt = oc.runtime_observations(root, cfg)["attempts"][0]
    assert attempt["result"]["excerpt"] == "Synthetic result."
    assert attempt["guard_admission"] == {"status": "unavailable", "model": None,
        "effort": None, "error_code": "retained_guard_chain_unavailable"}
    assert attempt["authorization"]["status"] == "not_observed"
    assert before == {file.name: file.read_bytes() for file in directory.iterdir() if file.is_file()}


def test_result_excerpt_is_bounded_and_hash_covers_the_complete_retained_text(runtime, monkeypatch):
    root, cfg, params, history, *_ = runtime
    plan = oc.plan_dispatch(root, cfg, params)
    oc.dispatch(root, cfg, plan)
    complete(runtime, plan)
    text = "Synthetic retained result. " * 100
    history["messages"][0]["content"][0]["text"] = text
    oc.inspect(root, cfg, {**params, "effect_key": plan["effect_key"]})
    monkeypatch.setattr(oc.Gateway, "call", forbidden)
    monkeypatch.setattr(oc, "inspect", forbidden)
    result = oc.runtime_observations(root, cfg)["attempts"][0]["result"]
    assert result == {"excerpt": text[:1_600], "truncated": True,
        "text_sha256": hashlib.sha256(text.encode()).hexdigest()}
    path = oc.storage(root, cfg, plan["effect_key"]) / "result.json"
    stored = json.loads(path.read_text())
    stored["text"] = "sk-" + "a1B2" * 12  # Synthetic detector-shaped value, never a real credential.
    stored["text_sha256"] = hashlib.sha256(stored["text"].encode()).hexdigest()
    path.write_text(json.dumps(stored))
    blocked = oc.runtime_observations(root, cfg)
    assert blocked["attempts"] == [] and "openclaw_receipt_unavailable_reconcile" in blocked["errors"]


def test_reviewed_failure_is_distinct_from_authorization_and_result(runtime, monkeypatch):
    from tests.test_openclaw_failure import failed
    root, cfg, *_ = runtime
    plan, query, _, _ = failed(runtime)
    prepared = oc.plan_failure_resolution(root, cfg, query)
    oc.resolve_failed(root, cfg, query, prepared)
    monkeypatch.setattr(oc.Gateway, "call", forbidden)
    attempt = oc.runtime_observations(root, cfg)["attempts"][0]
    assert attempt["status"] == "resolved_without_result" and attempt["result"] is None
    assert attempt["review"] == {"status": "failure_resolution_reviewed", "head": prepared["review"]["head"]}
    assert attempt["authorization"]["status"] == "not_observed"
    assert attempt["run_id"] == plan["effect_key"]


def test_one_corrupt_receipt_does_not_erase_healthy_retained_evidence(runtime):
    root, cfg, params, *_ = runtime
    plan = oc.plan_dispatch(root, cfg, params)
    oc.dispatch(root, cfg, plan)
    corrupt = oc.storage(root, cfg, "wiki-run-" + "a" * 32) / "intent.json"
    corrupt.parent.mkdir()
    corrupt.write_text("untrusted receipt text")
    observed = oc.runtime_observations(root, cfg)
    assert observed["attempts"][0]["effect_key"] == plan["effect_key"]
    assert "openclaw_receipt_unavailable_reconcile" in observed["errors"]
    assert "untrusted receipt text" not in json.dumps(observed)


def test_tcp_observation_is_bounded_and_not_gateway_or_session_authentication(runtime, monkeypatch):
    _, cfg, *_ = runtime
    connections = []
    class Connection:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
    monkeypatch.setattr(oc.socket, "create_connection", lambda address, timeout: connections.append((address, timeout)) or Connection())
    monkeypatch.setattr(oc.Gateway, "call", forbidden)
    assert oc.transport_observation(cfg)["status"] == "reachable"
    assert connections == [(("127.0.0.1", 19880), 2)]
    monkeypatch.setattr(oc.socket, "create_connection", lambda *a, **k: (_ for _ in ()).throw(OSError("untrusted network diagnostic")))
    assert oc.transport_observation(cfg)["status"] == "unreachable"
    monkeypatch.setattr(oc.socket, "create_connection", forbidden)
    disabled = replace(cfg, openclaw={"enabled": False})
    assert oc.transport_observation(disabled)["status"] == "not_configured"
    assert oc.runtime_observations(runtime[0], disabled)["native_observations"] == []


def test_versions_separate_code_boot_content_and_served_frontend(runtime, monkeypatch, tmp_path_factory):
    root, cfg, *_ = runtime
    code = tmp_path_factory.mktemp("synthetic-operator-code")
    (code / "wiki_core").mkdir()
    module = code / "wiki_core/operator.py"
    module.write_text("version = 1\n")
    for args in [("init", "-b", "main"), ("config", "user.name", "Synthetic"),
                 ("config", "user.email", "fixture@example.test")]:
        subprocess.run(["git", *args], cwd=code, check=True, capture_output=True)
    commit(code, "code at startup")
    monkeypatch.setattr(web, "_operator_code_root", lambda: code)
    probes = []
    monkeypatch.setattr(oc, "transport_observation", lambda config: probes.append(True) or {
        "status": "unreachable", "scope": "loopback_tcp_only", "observed_at": "2026-01-01T10:00:00Z"})
    srv = _Server(root, cfg)
    try:
        first = srv.get("/api/runtime/observations")[1]["operator"]
        assert first["boot_source_commit"] == first["current_source_commit"] == oc.git(code, "rev-parse", "HEAD")
        assert first["content_source_commit"] == oc.git(root, "rev-parse", "HEAD")
        assert first["restart_required"] is False
        (root / "memories/task.md").write_text("Synthetic changed content\n")
        commit(root, "content update")
        (code / "README.md").write_text("Synthetic documentation only\n")
        commit(code, "documentation update")
        second = srv.get("/api/runtime/observations")[1]["operator"]
        assert second["content_source_commit"] != first["content_source_commit"]
        assert second["current_source_commit"] != first["current_source_commit"]
        assert second["boot_source_commit"] == first["boot_source_commit"] and second["restart_required"] is False
        frontend = root / "frontend"
        frontend.mkdir()
        (frontend / "index.html").write_text("<html>Synthetic entry</html>")
        srv.server.frontend_dir = frontend
        module.write_text("version = 2\n")
        third = srv.get("/api/runtime/observations")[1]["operator"]
        assert third["restart_required"] is True and third["boot_code_sha256"] != third["current_code_sha256"]
        assert third["frontend"] == {"status": "observed", "source_commit": None,
            "entry_sha256": hashlib.sha256((frontend / "index.html").read_bytes()).hexdigest()}
        config_file = root / "wiki.config.yaml"
        raw = yaml.safe_load(config_file.read_text())
        raw["openclaw"] = {"enabled": False}
        config_file.write_text(yaml.safe_dump(raw))
        changed = srv.get("/api/runtime/observations")[1]
        assert changed["operator"]["restart_required"] is True
        assert changed["openclaw"]["transport"]["status"] == "unavailable" and len(probes) == 1
    finally:
        srv.close()


def test_wake_uses_existing_verified_audit_and_unknown_does_not_become_idle(scheduled):
    (root, cfg, *_), _ = scheduled
    prepared = {"rule_id": "review", "rule_sha256": oc.digest(cfg.openclaw["recurring"]["review"]),
                "slot": 1, "mode": "unchanged"}
    content = {"command_id": "agents.openclaw.tick", "dry_run": False, "diff": prepared}
    summary = recurring.wake_summary(content, {"ok": True, "output": {"new_dispatch": False, "message": "not exposed"}})
    event = append_admin_audit_event(root, cfg, {"command_id": "agents.openclaw.tick", "output_summary": summary})
    path = audit_log_path(root, cfg)
    before = path.read_bytes()
    result = oc.runtime_observations(root, cfg)
    wake = result["rules"][0]["last_wake"]
    assert wake["mode"] == "unchanged" and wake["new_dispatch"] is False and wake["status"] == "success"
    assert result["rules"][0]["scheduler_status"] == "not_observed"
    assert dt.datetime.fromisoformat(result["rules"][0]["next_expected_observation_at"]) == (
        dt.datetime.fromisoformat(event["event"]["timestamp"].replace("Z", "+00:00")) + dt.timedelta(hours=2))
    assert path.read_bytes() == before and "not exposed" not in json.dumps(result)
    failed = json.loads(recurring.wake_summary(content, {"ok": False, "error_code": "admin_command_failed"}))
    assert failed["new_dispatch"] is None and failed["status"] == "failure"
    assert recurring.wake_summary({**content, "dry_run": True}, {"ok": True}) is None
    disabled = replace(cfg, admin={**cfg.admin, "audit": {"enabled": False}})
    assert recurring.latest_wakes(root, disabled) == ({}, "openclaw_wake_audit_disabled")
    corrupt = json.loads(before)
    corrupt["output_summary"] = "untrusted changed audit"
    path.write_text(json.dumps(corrupt) + "\n")
    degraded = oc.runtime_observations(root, cfg)
    assert degraded["rules"][0]["last_wake"] is None
    assert degraded["rules"][0]["next_expected_observation_at"] is None
    assert "openclaw_wake_audit_corrupt" in degraded["errors"]
    assert "untrusted" not in json.dumps(degraded)


def test_wake_absent_unverified_or_partial_is_unknown(scheduled):
    (root, cfg, *_), _ = scheduled
    assert recurring.latest_wakes(root, cfg) == ({}, "openclaw_wake_not_recorded")
    unchecked = replace(cfg, admin={**cfg.admin, "audit": {"hash_chain": False}})
    assert recurring.latest_wakes(root, unchecked) == ({}, "openclaw_wake_audit_unverified")
    path = audit_log_path(root, cfg)
    path.parent.mkdir(parents=True)
    path.write_text('{"incomplete":')
    assert recurring.latest_wakes(root, cfg) == ({}, "openclaw_wake_audit_unavailable")


def test_valid_audit_hash_cannot_bless_a_malformed_wake_timestamp(scheduled):
    from wiki_core.web.admin.audit import _event_hash
    (root, cfg, *_), _ = scheduled
    content = {"command_id": "agents.openclaw.tick", "dry_run": False,
               "diff": {"rule_id": "review", "rule_sha256": oc.digest(cfg.openclaw["recurring"]["review"]),
                        "slot": 1, "mode": "unchanged"}}
    summary = recurring.wake_summary(content, {"ok": True, "output": {"new_dispatch": False}})
    record = append_admin_audit_event(root, cfg, {
        "command_id": "agents.openclaw.tick", "output_summary": summary})["event"]
    record["timestamp"] = None
    record["event_hash"] = _event_hash(record)
    path = audit_log_path(root, cfg)
    path.write_text(json.dumps(record) + "\n")
    before = path.read_bytes()
    assert recurring.latest_wakes(root, cfg) == ({}, "openclaw_wake_audit_corrupt")
    assert path.read_bytes() == before


@pytest.mark.parametrize("field,value", [("action_id", "another-task"), ("interval_minutes", 60)])
def test_wake_is_bound_to_the_exact_rule_and_legacy_summaries_stay_unknown(scheduled, monkeypatch, field, value):
    (root, cfg, *_), _ = scheduled
    rule = cfg.openclaw["recurring"]["review"]
    content = {"command_id": "agents.openclaw.tick", "dry_run": False,
        "diff": {"rule_id": "review", "rule_sha256": oc.digest(rule), "slot": 1, "mode": "unchanged"}}
    summary = recurring.wake_summary(content, {"ok": True, "output": {"new_dispatch": False}})
    append_admin_audit_event(root, cfg, {"command_id": "agents.openclaw.tick", "output_summary": summary})
    path = audit_log_path(root, cfg)
    before = path.read_bytes()
    monkeypatch.setattr(oc.Gateway, "call", forbidden)
    assert recurring.latest_wakes(root, cfg)[0]["review"]["mode"] == "unchanged"
    changed = replace(cfg, openclaw={**cfg.openclaw, "recurring": {"review": {**rule, field: value}}})
    observed = oc.runtime_observations(root, changed)
    assert observed["rules"][0]["last_wake"] is None
    assert observed["rules"][0]["next_expected_observation_at"] is None
    assert "openclaw_wake_not_recorded" in observed["errors"]
    assert path.read_bytes() == before
    # A valid old audit chain still cannot supply the missing rule binding.
    legacy = json.loads(summary)
    del legacy["rule_sha256"]
    path.unlink()
    append_admin_audit_event(root, cfg, {"command_id": "agents.openclaw.tick", "output_summary": json.dumps(legacy)})
    assert recurring.latest_wakes(root, cfg) == ({}, "openclaw_wake_not_recorded")
