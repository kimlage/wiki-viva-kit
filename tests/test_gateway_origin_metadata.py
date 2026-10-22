"""Public origin metadata through the actual native config.get registration.

No installed modules, config, account catalogue or gateway are invoked. Native
entry tests use pinned source with synthetic dependency boundaries.
"""
import ast
import builtins
import io
import json
import os
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace as NS

import pytest

from test_hermes_kernel_candidate import function
from test_hermes_kernel_candidate import KERNEL
from test_native_host_integration import native_candidate, native_source


@pytest.fixture
def origin_module():
    # Also run in normal kit CI without an installed Hermes checkout: exercise
    # the complete committed candidate module, not a rewritten test resolver.
    patch = (KERNEL / "candidate-711.patch").read_text()
    section = patch.split("+++ b/tools/wiki_gateway_origin.py\n", 1)[1].split("\n--- ", 1)[0]
    source = "".join(line[1:] for line in section.splitlines(True) if line.startswith("+"))
    module = ModuleType("candidate_gateway_origin")
    exec(compile(source, "candidate-gateway-origin", "exec"), vars(module))
    return module


@pytest.mark.parametrize("env,expected,provenance", [
    ({}, {"scheme": "https", "host": "connector-gateway.nousresearch.com", "port": 443}, "default"),
    ({"CONNECTOR_GATEWAY_URL": " / ", "TOOL_GATEWAY_DOMAIN": " // "}, {"scheme": "https", "host": "connector-gateway.nousresearch.com", "port": 443}, "default"),
    ({"TOOL_GATEWAY_DOMAIN": " /public-fixture.example.test/ ", "TOOL_GATEWAY_SCHEME": " HTTP "}, {"scheme": "http", "host": "connector-gateway.public-fixture.example.test", "port": 80}, "derived"),
    ({"CONNECTOR_GATEWAY_URL": " https://synthetic-user:synthetic-only@fixture.example.test:8443/private?synthetic-only#synthetic-only/ ", "TOOL_GATEWAY_DOMAIN": "ignored", "TOOL_GATEWAY_SCHEME": "invalid"}, {"scheme": "https", "host": "fixture.example.test", "port": 8443}, "override"),
    ({"CONNECTOR_GATEWAY_URL": "http://synthetic-user:synthetic-only@[2001:db8::7]:8080/private?synthetic-only#synthetic-only"}, {"scheme": "http", "host": "2001:db8::7", "port": 8080}, "override"),
    ({"CONNECTOR_GATEWAY_URL": "https://127.0.0.1"}, {"scheme": "https", "host": "127.0.0.1", "port": 443}, "override"),
])
def test_native_precedence_and_sanitization(origin_module, env, expected, provenance):
    result = origin_module.origin_metadata("research", env)
    assert result["status"] == "known" and result["origin"] == expected
    assert result["provenance"] == provenance and result["resolution_scope"] == "process"
    assert result["account_enforced"] is False and result["account_identity_verified"] is False
    assert "synthetic-only" not in json.dumps(result)


@pytest.mark.parametrize("url", ["ftp://fixture.example.test", "file:///private", "https:///missing", "https://",
    "https://fixture.example.test:", "https://fixture.example.test:0", "https://fixture.example.test:65536",
    "https://fixture.example.test:bad", "https://[2001:db8::1", "https://[::1]extra", "https://[fe80::1%25zone]",
    "https://fixture.example.test/\nsynthetic-only", "https://fixture.example.test\\synthetic-only", "https://-invalid.example.test",
    "https://999.1.1.1", "https://fixture..example.test", "https://fixture.example.test:443:44"])
def test_invalid_origin_is_content_free_unknown_without_a_default_fallback(origin_module, url):
    result = origin_module.origin_metadata("research", {"CONNECTOR_GATEWAY_URL": url})
    assert result == origin_module.unknown_origin("gateway_origin_invalid")
    assert url not in json.dumps(result)


def test_only_three_url_settings_are_read_and_invalid_derived_scheme_is_unknown(origin_module):
    reads = []
    class Environment:
        def get(self, key, default):
            assert key in {"CONNECTOR_GATEWAY_URL", "TOOL_GATEWAY_DOMAIN", "TOOL_GATEWAY_SCHEME"}
            reads.append(key)
            return "ftp" if key == "TOOL_GATEWAY_SCHEME" else default
    assert origin_module.origin_metadata("research", Environment()) == origin_module.unknown_origin("gateway_origin_invalid")
    assert len(reads) == 3


@pytest.fixture
def config_entry(native_candidate, tmp_path, monkeypatch):
    package = ModuleType("tui_gateway")
    package.__path__ = []
    monkeypatch.setitem(sys.modules, package.__name__, package)
    ctx = ModuleType("tui_gateway.method_ctx")
    exec(compile(native_source(native_candidate, "tui_gateway/method_ctx.py"), "native-method-ctx", "exec"), vars(ctx))
    monkeypatch.setitem(sys.modules, ctx.__name__, ctx)
    monkeypatch.setitem(sys.modules, "tui_gateway._env", NS(env_int=lambda _key, default: default))
    monkeypatch.setitem(sys.modules, "hermes_constants", NS(DEFAULT_INDICATOR_STYLE="default", INDICATOR_STYLES=[], display_hermes_home=lambda: "unused"))
    module = ModuleType("tui_gateway.methods_config")
    exec(compile(native_source(native_candidate, "tui_gateway/methods_config.py"), "native-methods-config", "exec"), vars(module))
    monkeypatch.setitem(sys.modules, module.__name__, module)
    home = tmp_path / "profiles" / "research"
    home.mkdir(parents=True)
    events = []

    def forbidden(*_a, **_kw):
        events.append("secret-scope")
        raise AssertionError("synthetic secret hydration boundary reached")

    profiles = ModuleType("hermes_cli.profiles")
    # Execute real pure native path/normalization bodies; only the installation
    # root and canonical profile regex are fictitious. They never open a file.
    ns = vars(profiles)
    import re
    ns.update(Path=Path, _get_default_hermes_home=lambda: tmp_path, _get_profiles_root=lambda: tmp_path / "profiles",
              _PROFILE_ID_RE=re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$"), _invalid_profile_name_error=lambda _name: ValueError("invalid profile"))
    for name in ("normalize_profile_name", "get_profile_dir"):
        ns[name] = function(native_source(native_candidate, "hermes_cli/profiles.py"), name, **ns)
    monkeypatch.setitem(sys.modules, profiles.__name__, profiles)
    if "tools/wiki_gateway_origin.py" in native_candidate:
        origin = ModuleType("tools.wiki_gateway_origin")
        exec(compile(native_candidate["tools/wiki_gateway_origin.py"][1], "candidate-origin", "exec"), vars(origin))
        monkeypatch.setitem(sys.modules, origin.__name__, origin)
    handlers = {}
    server = NS(Path=Path, _hermes_home=home, _sessions={}, _session_profile_runtime_scope=forbidden,
                _profile_home=lambda _p: forbidden(), _ok=lambda rid, value: {"id": rid, "result": value},
                _err=lambda rid, code, message: {"id": rid, "error": {"code": code, "message": message}},
                register_method=lambda name, handler: handlers.update({name: handler}))
    server._profile_scoped = function(native_source(native_candidate, "tui_gateway/server.py"), "_profile_scoped", **vars(server))
    module.register(server)
    return handlers["config.get"], events, server


def test_config_get_origin_precedes_native_secret_scope_and_returns_only_process_metadata(config_entry, monkeypatch):
    handler, events, _server = config_entry
    for key in ("CONNECTOR_GATEWAY_URL", "TOOL_GATEWAY_DOMAIN", "TOOL_GATEWAY_SCHEME"):
        monkeypatch.delenv(key, raising=False)
    def no_io(*_a, **_kw):
        raise AssertionError("origin metadata attempted file/network/process I/O")
    import socket
    import subprocess
    monkeypatch.setattr(builtins, "open", no_io)
    monkeypatch.setattr(io, "open", no_io)
    monkeypatch.setattr(socket, "socket", no_io)
    monkeypatch.setattr(subprocess, "Popen", no_io)
    result = handler(7, {"key": "connector_gateway_origin", "profile": "research", "metadata_only": True})
    value = result["result"]["connector_gateway_origin"]
    assert value == {"schema_version": "hermes.connector_gateway_origin.v1", "status": "known", "profile": "research",
                     "origin": {"scheme": "https", "host": "connector-gateway.nousresearch.com", "port": 443},
                     "provenance": "default", "resolution_scope": "process", "reason_code": None,
                     "account_identity_verified": False, "account_enforced": False}
    assert events == []


def test_generated_resolver_retains_exact_pinned_native_bodies(native_candidate):
    native = ast.parse(native_source(native_candidate, "tools/managed_tool_gateway.py"))
    generated = ast.parse(native_candidate["tools/wiki_gateway_origin.py"][1])
    for name in ("get_tool_gateway_scheme", "build_vendor_gateway_url"):
        before = next(n for n in ast.walk(native) if isinstance(n, ast.FunctionDef) and n.name == name)
        after = next(n for n in ast.walk(generated) if isinstance(n, ast.FunctionDef) and n.name == name)
        assert ast.dump(before) == ast.dump(after)


@pytest.mark.parametrize("profile", [None, "", "missing", "default", "Research", "../research", 3])
def test_origin_rejects_missing_invalid_or_other_process_profile_before_env_or_secret_scope(config_entry, monkeypatch, profile):
    handler, events, _server = config_entry
    monkeypatch.setenv("CONNECTOR_GATEWAY_URL", "https://synthetic-user:synthetic-only@fixture.example.test/private?synthetic-only#synthetic-only")
    result = handler(8, {"key": "connector_gateway_origin", "profile": profile, "metadata_only": True})["result"]["connector_gateway_origin"]
    assert result["status"] == "unknown" and result["origin"] is None and result["profile"] is None
    assert result["account_enforced"] is False and result["account_identity_verified"] is False
    assert "synthetic-only" not in json.dumps(result)
    assert events == []


def test_other_config_keys_preserve_native_profile_scoping(config_entry):
    handler, events, _server = config_entry
    with pytest.raises(AssertionError, match="secret hydration boundary"):
        handler(9, {"key": "full", "profile": "research"})
    assert events == ["secret-scope"]


@pytest.mark.parametrize("params", [{"key":"connector_gateway_origin"}, {"key":"connector_gateway_origin","metadata_only":False},
                                  {"key":"full","metadata_only":True}, {"key":"provider","metadata_only":None}])
def test_metadata_parameter_is_required_and_never_qualifies_other_getters(config_entry, params):
    handler, events, _server = config_entry
    assert handler(10, {**params,"profile":"research"})["error"]["code"] == 4000
    assert events == []


def test_native_capability_is_read_from_registered_enforcing_config_handler(native_candidate, config_entry, monkeypatch):
    handler, events, _server = config_entry
    monkeypatch.setitem(sys.modules, "hermes_cli.active_sessions", NS(PER_SESSION_EXCLUSIVE_SUBMIT=True))
    tree = ast.parse(native_source(native_candidate, "tui_gateway/methods_voice.py"))
    entry = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and any(
        isinstance(d, ast.Call) and d.args and isinstance(d.args[0], ast.Constant) and d.args[0].value == "gateway.capabilities" for d in n.decorator_list))
    methods = {"config.get": handler}
    invoke = function(ast.unparse(entry), "_", _methods=methods, _ok=lambda _rid, result: result)
    assert invoke(1, {})["connector_gateway_origin"] == "hermes.connector_gateway_origin.v1"
    methods["config.get"] = lambda *_args: None  # old / partially restored entry
    assert invoke(1, {})["connector_gateway_origin"] is None
    assert events == []
