"""Fictional adapter reports; no account, provider, login or real grant."""
import copy
import datetime as dt
import hashlib
import json

import pytest
import yaml

from wiki_core.source_config import ACCESS_SCHEMA, project_source_access
from wiki_core.web.source_operations import preview_source_operation, apply_source_operation, preview_source_refresh, run_source_refresh
from test_source_operations import _repo

NOW = dt.datetime(2026, 10, 20, 12, tzinfo=dt.timezone.utc)


def policy():
    return {"schema_version": ACCESS_SCHEMA, "expected_identity": "reader@example.test",
            "coordinator": "research", "executor": "fixture-executor", "requested_scopes": ["read"]}


def source():
    return {"source_id": "source-a", "context": "research", "platform": "drive", "locator": "collection-a",
            "auth": {"method": "mcp", "ref": "fixture-connector", "scopes": ["read"], "note": ""}, "access_policy": policy()}


def probe(s=None, **changes):
    s = s or source()
    return {"schema_version": ACCESS_SCHEMA, "binding_sha256": project_source_access(s)["binding_sha256"],
            "outcome": "verified", "confirmed_identity": "reader@example.test", "granted_scopes": ["read"],
            "checked_at": "2026-10-20T11:59:00Z", "valid_until": "2026-10-20T12:30:00Z",
            "evidence_ref": "receipt:fictional-read-001", "error_code": "", **changes}


def test_configuration_capability_exit_zero_are_not_identity_evidence():
    s = source()
    assert project_source_access(s, now=NOW)["verified"] is False
    assert project_source_access(s, {"ok": True, "returncode": 0}, now=NOW)["status"] == "technical_blocked"
    before = copy.deepcopy(s)
    observation = probe(s)
    original = copy.deepcopy(observation)
    result = project_source_access(s, observation, now=NOW)
    assert result["verified"] and result["business_authority"] == "unknown" and not result["execution_ready"]
    assert s == before and observation == original


@pytest.mark.parametrize("field,value,status", [
    ("confirmed_identity", "other@example.test", "identity_mismatch"),
    ("granted_scopes", [], "authority_blocked"),
    ("valid_until", "2026-10-20T11:59:30Z", "unknown"),
    ("checked_at", "2026-10-20T12:01:00Z", "technical_blocked"),
    ("valid_until", "invalid", "technical_blocked"),
    ("evidence_ref", "", "technical_blocked"),
    ("evidence_ref", "https://example.test/login?code=private", "technical_blocked"),
    ("outcome", "awaiting_auth", "awaiting_auth"),
    ("outcome", "awaiting_approval", "awaiting_approval"),
    ("outcome", "authority_blocked", "authority_blocked"),
    ("outcome", "technical_blocked", "technical_blocked"),
    ("outcome", "execution_unknown", "execution_unknown"),
    ("outcome", "revoked", "revoked"),
    ("outcome", "wrong_account", "wrong_account"),
    ("outcome", "executor_unavailable", "executor_unavailable"),
    ("outcome", "session_expired", "session_expired"),
    ("outcome", "authorization_missing", "authorization_missing"),
])
def test_probe_failures_remain_distinct(field, value, status):
    result = project_source_access(source(), probe(**{field: value}), now=NOW)
    assert result["status"] == status and not result["verified"]


@pytest.mark.parametrize("field,value", [("context", "other"), ("locator", "another"), ("source_id", "other-source")])
def test_same_title_does_not_allow_cross_source_or_context_evidence(field, value):
    s = {**source(), field: value, "title": "The same name"}
    assert project_source_access(s, probe(), now=NOW)["status"] == "identity_mismatch"


def test_account_executor_and_scope_changes_invalidate_prior_probe():
    for updates in [{"expected_identity": "second@example.test"}, {"executor": "other"}, {"requested_scopes": ["write"]}]:
        s = source(); s["access_policy"].update(updates)
        assert project_source_access(s, probe(), now=NOW)["status"] == "identity_mismatch"


def test_metadata_update_uses_existing_preview_cas_without_grant(tmp_path):
    config = _repo(tmp_path)
    p = tmp_path / "memories/sources/config/source-a.md"
    original = p.read_bytes()
    updates = {"access": policy()}
    preview = preview_source_operation(tmp_path, config, "source-a", "__source__", updates)
    assert p.read_bytes() == original
    with pytest.raises(ValueError, match="preview_stale"):
        apply_source_operation(tmp_path, config, "source-a", "__source__", updates, "wrong")
    out = apply_source_operation(tmp_path, config, "source-a", "__source__", updates, preview["preview_token"])
    assert out["source"]["access_policy"] == policy()
    assert not out["source"]["access"]["verified"]
    with pytest.raises(ValueError, match="preview_stale|no_changes"):
        apply_source_operation(tmp_path, config, "source-a", "__source__", updates, preview["preview_token"])


def test_fictional_adapter_pipeline_reports_probe_but_no_claim_of_real_login(tmp_path, monkeypatch):
    config = _repo(tmp_path)
    config_path = tmp_path / "memories/sources/config/source-a.md"
    text = config_path.read_text().replace("  auth:", "  access:\n" + "\n".join("    " + line for line in yaml.safe_dump(policy(), sort_keys=False).splitlines()) + "\n  refresh:\n    argv: [python3, scripts/fictional.py]\n  auth:")
    config_path.write_text(text)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/fictional.py").write_text("# Never executed: adapter is explicitly mocked.\n")
    import wiki_core.web.source_operations as operations
    from wiki_core.web.sources import build_sources_payload
    s = build_sources_payload(tmp_path, config)["sources"][0]
    frozen = dt.datetime.now(dt.timezone.utc)
    report = probe(s, checked_at=(frozen-dt.timedelta(seconds=5)).isoformat(), valid_until=(frozen+dt.timedelta(minutes=5)).isoformat())
    payload = {"schema_version": "wiki_source_inventory.v1", "source_id": "source-a", "locator": "folder-a", "records": [], "access_probe": report}
    monkeypatch.setattr(operations, "_run_refresh_adapter", lambda *a, **k: (copy.deepcopy(payload), ""))
    first = preview_source_refresh(tmp_path, config, "source-a")
    assert first["access"]["verified"] and first["execution"]["runnable"]
    # Revocation between preview and apply is re-observed; it cannot import data.
    payload["access_probe"]["outcome"] = "revoked"
    with pytest.raises(ValueError, match="access_not_verified"):
        run_source_refresh(tmp_path, config, "source-a", "__source__", "", first["preview_token"])
    assert not (tmp_path / "data/derived/wiki/source-operations").exists()
    payload["access_probe"]["outcome"] = "awaiting_auth"
    expired = preview_source_refresh(tmp_path, config, "source-a")
    assert expired["access"]["status"] == "awaiting_auth" and not expired["execution"]["runnable"]
    payload["access_probe"]["outcome"] = "verified"
    resumed = preview_source_refresh(tmp_path, config, "source-a")
    assert resumed["preview_token"] == first["preview_token"] and resumed["source_id"] == first["source_id"]


@pytest.mark.parametrize("ref", ["Bearer abcdefghijkl", "https://example.test/auth?code=opaque", "x"*60])
def test_auth_ref_cannot_hide_a_secret_for_any_pointer_method(tmp_path, ref):
    from wiki_core.source_recipe import parse_recipe, validate_recipe
    for method in ["env", "keychain", "onepassword", "oauth_file", "mcp"]:
        recipe = parse_recipe({"auth": {"method": method, "ref": ref}})
        errors = validate_recipe(recipe)
        assert errors == ["source_recipe_secret_detected"] and ref not in str(errors)


def test_probe_and_adapter_diagnostics_never_retain_login_material():
    from wiki_core.web.source_operations import _redacted_output
    marker = "fictional-login-code"
    diagnostic = f"adapter failed: https://example.test/login?code={marker}&state=fixture Bearer fictional-bearer-value"
    redacted = _redacted_output(diagnostic)
    assert marker not in redacted and "fictional-bearer-value" not in redacted and "?code" not in redacted
    result = project_source_access(source(), probe(confirmed_identity="Bearer fictional-bearer-value"), now=NOW)
    assert result["error_code"] == "unsafe_probe" and "fictional-bearer-value" not in str(result)


@pytest.mark.parametrize("material", ["https://example.test/login?code=opaque&state=fixture", "code=opaque&state=fixture"])
@pytest.mark.parametrize("outcome", ["verified", "awaiting_auth", "revoked"])
def test_authorization_material_is_rejected_before_identity_projection(material, outcome):
    from wiki_core.source_config import source_access_metadata
    result = project_source_access(source(), probe(confirmed_identity=material, outcome=outcome), now=NOW)
    assert result["status"] == "technical_blocked" and not result["verified"]
    assert result["confirmed_identity"] == "" and material not in str(result)
    for field in ["expected_identity", "coordinator", "executor"]:
        with pytest.raises(ValueError, match="^source_access_metadata_invalid$"):
            source_access_metadata({**policy(), field: material})


def test_explicit_connection_test_reports_unsupported_executor_and_persists_failure(tmp_path):
    from wiki_core.web.source_operations import probe_source_connection, list_source_operation_receipts
    cfg = _repo(tmp_path)
    path = tmp_path / 'memories/sources/config/source-a.md'
    before = path.read_bytes()
    receipt = probe_source_connection(tmp_path, cfg, 'source-a')
    assert receipt['kind'] == 'access_test' and receipt['method'] == 'agent_connector'
    assert receipt['access']['status'] == 'executor_unavailable'
    assert receipt['access']['error_code'] == 'source_access_adapter_not_implemented'
    assert not receipt['access']['verified'] and not receipt['access']['execution_ready']
    assert not receipt['access']['confirmed_identity']
    assert list_source_operation_receipts(tmp_path, cfg, 'source-a')[0] == {k:v for k,v in receipt.items() if k not in {'ok','receipt_path'}}
    assert path.read_bytes() == before


@pytest.mark.parametrize('outcome', ['verified','wrong_account','executor_unavailable','session_expired','authorization_missing'])
def test_connection_test_uses_bound_adapter_report_without_running_ingestion(tmp_path, monkeypatch, outcome):
    from wiki_core.web.source_operations import probe_source_connection
    import wiki_core.web.source_operations as ops
    from wiki_core.web.sources import build_sources_payload
    cfg = _repo(tmp_path)
    path = tmp_path / 'memories/sources/config/source-a.md'
    text = path.read_text().replace('  auth:', '  access:\n' + '\n'.join('    '+line for line in yaml.safe_dump(policy(),sort_keys=False).splitlines()) + '\n  refresh:\n    argv: [python3, scripts/fictional.py]\n  auth:')
    path.write_text(text)
    (tmp_path/'scripts').mkdir(); (tmp_path/'scripts/fictional.py').write_text('# fictional adapter\n')
    s = build_sources_payload(tmp_path,cfg)['sources'][0]
    now = dt.datetime.now(dt.timezone.utc)
    observation = probe(s,outcome=outcome,checked_at=(now-dt.timedelta(seconds=5)).isoformat(),valid_until=(now+dt.timedelta(minutes=5)).isoformat())
    calls=[]
    def adapter(argv,**kwargs):
        calls.append(argv)
        return {'access_probe':observation}, ''
    monkeypatch.setattr(ops,'_run_refresh_adapter',adapter)
    receipt = probe_source_connection(tmp_path,cfg,'source-a')
    assert len(calls)==1 and calls[0][1]=='scripts/fictional.py'
    assert receipt['access']['status']==outcome
    assert receipt['access']['verified'] is (outcome=='verified')
    assert receipt['access']['execution_ready'] is False
    assert path.read_text()==text and receipt['changes']==[]


def test_first_setup_has_unverified_binding_without_authored_access(tmp_path):
    from wiki_core.web.sources import build_sources_payload
    cfg = _repo(tmp_path)
    s = build_sources_payload(tmp_path, cfg)['sources'][0]
    assert s['access_policy'] == {}
    assert s['access']['status'] == 'not_configured' and not s['access']['verified']
    assert len(s['access']['binding_sha256']) == 64


def test_native_session_binding_is_context_not_account_evidence():
    from wiki_core.source_config import source_access_metadata
    execution = dict(connection_id='fixture', profile='research', target_profile='research', method='native_session', stored_session_id='stored-fixture')
    value = {**policy(), 'expected_identity': '', 'execution': execution}
    assert source_access_metadata(value)['expected_identity'] == ''
    s = source(); s['access_policy'] = value
    result = project_source_access(s, probe(s), now=NOW)
    assert not result['verified'] and result['status'] == 'execution_unknown'
    for method in ['local_git', 'managed_connector', 'mcp', 'browser_controller']:
        with pytest.raises(ValueError, match='execution_invalid|metadata_invalid'):
            source_access_metadata({**value, 'execution': {**execution, 'method': method}})


def test_saved_native_execution_cannot_fall_back_to_legacy_adapter(tmp_path, monkeypatch):
    import wiki_core.web.source_operations as ops
    cfg = _repo(tmp_path)
    path = tmp_path / 'memories/sources/config/source-a.md'
    value = {**policy(), 'execution': dict(connection_id='fixture',profile='research',target_profile='research',method='native_session',stored_session_id='stored-fixture')}
    text = path.read_text().replace('  auth:', '  access:\n'+'\n'.join('    '+line for line in yaml.safe_dump(value,sort_keys=False).splitlines())+'\n  auth:')
    path.write_text(text)
    monkeypatch.setattr(ops, '_run_refresh_adapter', lambda *args, **kwargs: pytest.fail('wrong executor'))
    with pytest.raises(ValueError, match='requires_native_executor'):
        ops.probe_source_connection(tmp_path, cfg, 'source-a')
    with pytest.raises(ValueError, match='requires_native_executor'):
        ops.preview_source_refresh(tmp_path, cfg, 'source-a')
    with pytest.raises(ValueError, match='requires_native_executor'):
        ops.run_source_refresh(tmp_path, cfg, 'source-a', '__source__', '', 'stale-token')
    assert path.read_text() == text


def test_connection_metadata_needs_no_conversation_and_never_changes_legacy_owner():
    from wiki_core.source_config import source_access_metadata
    connection = dict(connection_id='fixture', profile='research', target_profile='research')
    value = {**policy(), 'connection': connection}
    assert source_access_metadata(value) == value
    assert 'execution' not in source_access_metadata(value)
    legacy = {**connection, 'method': 'native_session', 'stored_session_id': 'existing-owner'}
    both = {**value, 'execution': legacy}
    assert source_access_metadata(both)['execution'] == legacy
    with pytest.raises(ValueError, match='owner_conflict'):
        source_access_metadata({**both, 'connection': {**connection, 'profile': 'another'}})
    for extra in [{'stored_session_id': 'forbidden'}, {'grant': 'all'}, {'account_id': 'partial'}]:
        with pytest.raises(ValueError, match='connection_invalid'):
            source_access_metadata({**value, 'connection': {**connection, **extra}})
    s = {**source(), 'access_policy': value}
    assert not project_source_access(s, probe(s), now=NOW)['verified']


def test_connection_preview_confirmation_preserves_canonical_auth_and_requires_cas(tmp_path):
    from wiki_core.web.source_operations import source_access_binding
    cfg = _repo(tmp_path)
    path = tmp_path/'memories/sources/config/source-a.md'
    text = path.read_text()
    # A generic restrictive pointer, not a provider-specific reader or a grant.
    auth = dict(method='mcp', ref='browser-controller', scopes=['read'], note='Browser-only corporate access; never use a personal account or API.')
    before_recipe = yaml.safe_load(text.split('```yaml\n')[1].split('```')[0])
    before_recipe['recipe']['auth'] = auth
    path.write_text(text.split('```yaml\n')[0] + '```yaml\n' + yaml.safe_dump(before_recipe, sort_keys=False) + '```\n')
    before = path.read_bytes()
    value = {**policy(), 'connection': dict(connection_id='fixture', profile='research', target_profile='research')}
    updates = {'access': value}
    preview = preview_source_operation(tmp_path, cfg, 'source-a', '__source__', updates)
    assert path.read_bytes() == before
    with pytest.raises(ValueError):
        apply_source_operation(tmp_path, cfg, 'source-a', '__source__', updates, 'wrong-token')
    assert path.read_bytes() == before
    applied = apply_source_operation(tmp_path, cfg, 'source-a', '__source__', updates, preview['preview_token'])
    assert applied['ok']
    binding = source_access_binding(tmp_path, cfg, 'source-a')
    assert binding['auth'] == auth
    assert binding['access_policy']['connection'] == value['connection']
    assert 'execution' not in binding['access_policy']
    with pytest.raises(ValueError):
        preview_source_operation(tmp_path, cfg, 'source-a', '__source__', {'auth': {'method': 'none'}})
