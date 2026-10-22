"""Exercise real pinned entry bodies with synthetic host/handler dependencies.

Set WIKI_HERMES_KERNEL_SOURCE to a read-only 711 source checkout to run the
entry-body tests. No Hermes modules/configuration/providers are imported.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from contextvars import Context
import sys
import subprocess
from types import SimpleNamespace

import pytest
from wiki_core import runtime_authority as authority
from test_runtime_authority import Host

ROOT = Path(__file__).resolve().parents[1]
KERNEL = ROOT / "integrations/hermes/wiki-viva-board/kernel"
spec = importlib.util.spec_from_file_location("kernel_candidate_builder", KERNEL / "build_candidate.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def test_patch_vendors_exact_authority_and_has_no_operator_or_credential_bootstrap():
    patch = (KERNEL / "candidate-711.patch").read_text()
    vendored = patch.split("+++ b/tools/wiki_authority.py\n", 1)[1]
    source = "".join(line[1:] for line in vendored.splitlines(True) if line.startswith("+"))
    assert source == (ROOT / "wiki_core/runtime_authority.py").read_text()
    wire = patch.split("+++ b/tools/wiki_native_host_wire.py\n", 1)[1].split("--- /dev/null", 1)[0]
    assert "install_host_backend(_client)" in wire
    assert "expected_controller_pid=os.getppid()" in wire
    assert "read_nous_access_token" not in wire


@pytest.fixture
def candidate():
    source = os.environ.get("WIKI_HERMES_KERNEL_SOURCE")
    if not source:
        pytest.skip("pinned source entry test requires WIKI_HERMES_KERNEL_SOURCE")
    return builder.candidate(Path(source))


def function(source, name, **namespace):
    namespace.setdefault("DEFAULT_TIMEOUT_SECONDS", 1)
    namespace.setdefault("_MAX_RETRIES", 0)
    namespace.setdefault("wire", SimpleNamespace(CONNECTOR_EXECUTE_PATH="/execute"))
    nodes = [n for n in ast.walk(ast.parse(source)) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    assert len(nodes) == 1
    node = nodes[0]
    node.decorator_list = []
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), node], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, "pinned-kernel-entry", "exec"), namespace)
    return namespace[name]


@pytest.fixture
def host(tmp_path, monkeypatch):
    backend = Host(tmp_path)
    gate = authority.Authority(backend, clock=lambda: 100)
    monkeypatch.setitem(sys.modules, "tools.wiki_authority", SimpleNamespace(
        require=gate.require, require_agent=gate.require_agent, invoke=gate.invoke,
        invoke_agent=gate.invoke_agent, safe_tool_failure=authority.safe_tool_failure,
        admit=gate.admit, AuthorityDenied=authority.AuthorityDenied))
    # Existing unit boundaries isolate their own native primitive; the real
    # handoff/projection chain is exercised by test_native_host_integration.py.
    monkeypatch.setitem(sys.modules, "tools.wiki_native_host_wire", SimpleNamespace(
        bound_task=lambda agent, task: task, project_native_result=lambda agent, task: {}))
    return backend, gate


def test_missing_admission_blocks_skip_hook_and_registry_before_handler(candidate, host):
    backend, gate = host
    pre = function(candidate["model_tools.py"][1], "_pre_dispatch_guards")
    dispatch = function(candidate["tools/registry.py"][1], "dispatch")
    effects = []
    registry = SimpleNamespace(get_entry=lambda *a, **kw: effects.append("lookup"))
    for skip in (False, True):
        with pytest.raises(authority.AuthorityDenied, match="admission_required"):
            pre("read_public", backend.args, skip, None, [])
    with pytest.raises(authority.AuthorityDenied, match="admission_required"):
        dispatch(registry, "read_public", backend.args)
    assert effects == []


def test_registry_revalidates_actual_arguments_and_callback_context(candidate, host):
    backend, gate = host
    gate.admit("session-a", "task")
    dispatch = function(candidate["tools/registry.py"][1], "dispatch")
    with pytest.raises(authority.AuthorityDenied, match="operation_denied"):
        dispatch(None, "read_public", {**backend.args, "resource": "private"}, session_id="session-a", task_id="task")
    with pytest.raises(authority.AuthorityDenied, match="principal_mismatch"):
        dispatch(None, "read_public", backend.args, session_id="session-b", task_id="task")
    with pytest.raises(authority.AuthorityDenied, match="admission_required"):
        Context().run(dispatch, None, "read_public", backend.args)


def test_actual_registry_allows_public_handler_then_blocks_revoked_disclosure(candidate, host, monkeypatch):
    from dataclasses import replace
    backend, gate = host
    gate.admit("session-a", "task")
    effects = []
    def handler(args):
        effects.append("read")
        return {"body": "synthetic result"}
    entry = SimpleNamespace(handler=handler, is_async=False)
    registry = SimpleNamespace(get_entry=lambda *a, **kw: entry, _normalize_handler_result=lambda name, value: value)
    monkeypatch.setitem(sys.modules, "model_tools", SimpleNamespace(_sanitize_tool_error=lambda text: text))
    dispatch = function(candidate["tools/registry.py"][1], "dispatch",
        _kwargs_accepted_by=lambda fn, kw: {}, tool_error=lambda text: {"error": text},
        logger=SimpleNamespace(exception=lambda *a: None), _bound_error_text=str)
    assert dispatch(registry, "read_public", backend.args, session_id="session-a", task_id="task") == {"body": "synthetic result"}
    def revoked_handler(args):
        backend.state = replace(backend.state, revoked=True)
        return {"body": "must not escape"}
    entry.handler = revoked_handler
    with pytest.raises(authority.AuthorityDenied):
        dispatch(registry, "read_public", backend.args, session_id="session-a", task_id="task")
    assert effects == ["read"]


@pytest.mark.parametrize("path,name,args,kwargs", [
    ("tools/connectors/gateway/client.py", "execute", (None, []), {}),
    ("tools/connectors/gateway/client.py", "_request", (None, "POST", "/execute", None), {"timeout": 1}),
    ("tools/connectors/dispatch.py", "dispatch_connector_call", ("read_public", {}, "tool-id"), {}),
    ("tools/bot_mode_dm.py", "message_agent_tool", (), {"target": "other-bot", "message": "private body"}),
    ("tools/mcp_tool_handlers.py", "_dispatch", (None, None, None, None, None, None, None), {}),
])
def test_alternative_entry_never_reaches_credential_transport_or_recipient(candidate, host, path, name, args, kwargs):
    fn = function(candidate[path][1], name)
    with pytest.raises(authority.AuthorityDenied):
        fn(*args, **kwargs)


def test_mcp_direct_plugin_handlers_deny_before_lazy_server_or_credential_resolution(candidate):
    module = ast.parse(candidate["tools/mcp_tool_handlers.py"][1])
    handlers = [n for n in ast.walk(module) if isinstance(n, ast.FunctionDef) and n.name == "_handler"]
    assert len(handlers) == 2
    for handler in handlers:
        assert isinstance(handler.body[0], ast.ImportFrom) and handler.body[0].module == "tools.wiki_authority"
        assert isinstance(handler.body[1], ast.Raise)


def test_native_connector_configuration_keeps_its_existing_official_path(candidate, host):
    fn = function(candidate["tools/connectors/gateway/client.py"][1], "_request")
    class NativeConfiguration(Exception):
        pass
    def native_resolver():
        raise NativeConfiguration("existing native configuration")
    with pytest.raises(NativeConfiguration):
        fn(SimpleNamespace(_endpoint_resolver=native_resolver), "POST", "/native-connections", {}, timeout=1)


def test_agent_loop_special_tool_and_direct_delegate_are_covered(candidate, host):
    backend, gate = host
    fn = function(candidate["run_agent.py"][1], "_execute_tool_calls")
    message = SimpleNamespace(tool_calls=[SimpleNamespace(function=SimpleNamespace(name="delegate_task", arguments="{}"))])
    with pytest.raises(authority.AuthorityDenied, match="admission_required"):
        fn(SimpleNamespace(session_id="session-a"), message, [], "task")
    gate.admit("session-a", "task")
    with pytest.raises(authority.AuthorityDenied, match="operation_denied"):
        fn(SimpleNamespace(session_id="session-a"), message, [], "task")
    direct = function(candidate["run_agent.py"][1], "_dispatch_delegate_task")
    with pytest.raises(authority.AuthorityDenied, match="worker_unqualified"):
        direct(None, {})


def test_required_context_is_admitted_before_optional_hooks_or_model(candidate, host):
    backend, gate = host
    fn = function(candidate["agent/turn_context.py"][1], "build_turn_context")
    import inspect
    values = {k: None for k in inspect.signature(fn).parameters}
    values.update(agent=SimpleNamespace(session_id="wrong-session"), task_id="task")
    with pytest.raises(authority.AuthorityDenied, match="principal_mismatch"):
        fn(**values)
    # A failed/absent pre_llm_call result cannot remove required context.
    source = candidate["agent/turn_context.py"][1]
    assert "plugin_user_context = required_wiki_context + '\\n\\n' + plugin_user_context" in source


def test_model_destination_is_checked_inside_actual_middleware_continuation(candidate, host):
    backend, gate = host
    fn = function(candidate["agent/turn_api_call.py"][1], "_perform_api_call",
                  agent=SimpleNamespace(session_id="session-a", provider="wrong-provider", base_url="https://model.example.test", model="wrong-model"), effective_task_id="task")
    with pytest.raises(authority.AuthorityDenied, match="admission_required"):
        fn({"messages": ["synthetic"]})
    gate.admit("session-a", "task")
    with pytest.raises(authority.AuthorityDenied, match="operation_denied"):
        fn({"messages": ["synthetic"]})


def test_kernel_generation_rejects_source_drift_and_is_reproducible(candidate):
    patch = "".join("".join(builder.difflib.unified_diff(before.splitlines(True), after.splitlines(True),
        fromfile="a/" + path if before else "/dev/null", tofile="b/" + path)) for path, (before, after) in candidate.items())
    assert patch == (KERNEL / "candidate-711.patch").read_text()
    pins = json.loads((KERNEL / "source-pins.json").read_text())
    for path, (before, _) in candidate.items():
        if before:
            assert hashlib.sha256(before.encode()).hexdigest() == builder.source_digest(pins["files"][path])


def test_patch_applies_only_to_a_disposable_source_copy_and_preserves_pin_check(candidate, tmp_path):
    for path, (before, _) in candidate.items():
        if before:
            target = tmp_path / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(before)
    patch = KERNEL / "candidate-711.patch"
    subprocess.run(["git", "apply", "--check", str(patch)], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "apply", str(patch)], cwd=tmp_path, check=True, capture_output=True)
    for path, (_, after) in candidate.items():
        assert (tmp_path / path).read_text() == after
        if path.endswith(".py"):
            compile(after, path, "exec")
        elif path.endswith(".json"):
            json.loads(after)
    with pytest.raises(ValueError, match="revision mismatch"):
        builder.candidate(tmp_path)
