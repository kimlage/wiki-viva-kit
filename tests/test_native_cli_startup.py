"""Real native startup bodies, synthetic config and terminal dependency boundaries.

No native profile, credential, MCP server, plugin or network is opened here.
The configured server and native toolset filter are deliberately nonempty.
"""
import ast
import asyncio
from contextlib import nullcontext
from contextvars import copy_context
from datetime import datetime
import os
from pathlib import Path
import sys
import threading
from types import ModuleType, SimpleNamespace as NS

import pytest

from wiki_core import native_host_wire as wire, runtime_authority as auth
from wiki_core.runtime_authority import AuthorityDenied
from test_hermes_kernel_candidate import function
from test_native_host_integration import (native_candidate, native_modules,
    native_source, registered_channel, stack)


@pytest.fixture
def startup(native_candidate, native_modules, monkeypatch):
    for key in ("HERMES_KANBAN_TASK", "HERMES_KANBAN_RUN_ID", "HERMES_KANBAN_CLAIM_LOCK"):
        monkeypatch.delenv(key, raising=False)
    events = []
    log = NS(debug=lambda *a, **kw: None, warning=lambda *a, **kw: None,
             info=lambda *a, **kw: None)
    config = {"mcp_servers": {"synthetic-native": {"command": "NEVER-EXECUTED"}}}
    monkeypatch.setitem(sys.modules, "hermes_cli.config", NS(
        read_raw_config=lambda: config, load_config=lambda: events.append("hooks-config") or {}))
    monkeypatch.setitem(sys.modules, "agent.shell_hooks", NS(register_from_config=lambda *a, **kw: None))
    monkeypatch.setitem(sys.modules, "agent.outbound_webhooks", NS(register_from_config=lambda *a, **kw: None))
    monkeypatch.setitem(sys.modules, "hermes_cli.plugins", NS(
        start_background_plugin_discovery=lambda: events.append("plugins")))
    monkeypatch.setitem(sys.modules, "tools.mcp_oauth", NS(suppress_interactive_oauth=nullcontext))
    def discover(allowed_mcp_names=None):
        events.append(("discovery", tuple(n for n in config["mcp_servers"]
                                        if allowed_mcp_names is None or n in allowed_mcp_names)))
    monkeypatch.setitem(sys.modules, "tools.mcp_tool_discovery", NS(discover_mcp_tools=discover))
    threads = []
    class Thread:
        def __init__(self, *, target, args=(), **kw):
            self.target, self.args = target, args
        def start(self):
            events.append("thread-start")
            threads.append(self)
        def is_alive(self): return False
    def unexpected_timer(*args, **kw):
        events.append("timer-armed")
        raise AssertionError("protected discovery armed a timer")
    module = ModuleType("hermes_cli.mcp_startup")
    module.__dict__.update(threading=NS(Lock=threading.Lock, Thread=Thread, Timer=unexpected_timer),
        hermes_home_key=lambda: "synthetic-home", _mcp_discovery_lock=threading.Lock(),
        _mcp_discovery_started=set(), _mcp_discovery_thread={}, _mcp_server_filter=None,
        _mcp_discovery_deferred=None,
        copy_context=copy_context, nullcontext=nullcontext, _discovery_gil_budget=nullcontext,
        _any_mcp_connected=lambda: True)
    names = {"set_mcp_server_filter", "get_mcp_server_filter", "_has_configured_mcp_servers",
             "start_background_mcp_discovery", "defer_background_mcp_discovery",
             "start_deferred_mcp_discovery_now", "_discover_mcp_tools_without_interactive_oauth"}
    tree = ast.parse(native_source(native_candidate, "hermes_cli/mcp_startup.py"))
    selected = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)]
        + [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[])
    exec(compile(ast.fix_missing_locations(selected), "native-mcp-startup-body", "exec"), module.__dict__)
    monkeypatch.setitem(sys.modules, "hermes_cli.mcp_startup", module)
    source = native_source(native_candidate, "hermes_cli/main.py")
    prepare = function(source, "_prepare_agent_startup", os=os, logger=log,
        _AGENT_COMMANDS={None, "chat", "rl"}, _is_tui_chat_launch=lambda args: False,
        _command_has_dedicated_mcp_startup=function(source, "_command_has_dedicated_mcp_startup",
            _agent_subcommand_selected=lambda args: False),
        _should_background_mcp_startup=function(source, "_should_background_mcp_startup",
            _is_tui_chat_launch=lambda args: False),
        _apply_safe_mode=lambda args: events.append("safe-mode"),
        _apply_user_config_bypass=lambda args: events.append("config-bypass"),
        _guard_noninteractive_user_config=lambda args: events.append("config-guard"),
        start_background_plugin_discovery=lambda: events.append("plugins"))
    return NS(prepare=prepare, module=module, events=events, config=config, log=log, threads=threads,
        args=NS(command="chat", query="public synthetic question", toolsets="synthetic-native",
                yolo=False, accept_hooks=False, resume=None))


def test_actual_cli_preparation_denies_before_discovery_when_channel_is_missing(startup, monkeypatch):
    monkeypatch.setenv("HERMES_KANBAN_TASK", "task")
    assert startup.module._has_configured_mcp_servers() is True
    with pytest.raises(AuthorityDenied):
        startup.prepare(startup.args)
    assert startup.events == []


def test_actual_cli_preparation_admits_public_context_but_holds_private_mcp(startup, stack, native_candidate, monkeypatch):
    launch, client = registered_channel(stack)
    try:
        monkeypatch.setattr(wire, "_client", client)
        auth.install_host_backend(client)
        startup.prepare(startup.args)
        assert startup.module.get_mcp_server_filter() == ["synthetic-native"]
        assert startup.events == []
        # A delayed caller cannot start a thread after the env hint was consumed.
        startup.module.start_background_mcp_discovery(logger=startup.log, thread_name="synthetic")
        startup.module.defer_background_mcp_discovery(logger=startup.log, thread_name="synthetic", delay=0)
        startup.module.start_deferred_mcp_discovery_now()
        startup.module._discover_mcp_tools_without_interactive_oauth()
        assert startup.events == []
        # Real CLI mutable-state initialization must keep the authenticated
        # native Session, rather than silently allocating another identity.
        monkeypatch.setitem(sys.modules, "cli", NS(_hermes_home=Path("/synthetic/home")))
        init = function(native_source(native_candidate, "hermes_cli/cli_init_mixin.py"),
            "_init_runtime_state", datetime=datetime, new_session_id=lambda *a: "unbound-new-session")
        cli = NS(_init_session_store=lambda: None, _init_ui_state=lambda: None)
        init(cli, None)
        assert cli.session_id == client.mandate.principal.session
        with pytest.raises(AuthorityDenied): init(cli, "other-session")
    finally:
        client.close()
        launch.close()


def test_worker_restriction_survives_consumed_env_without_granting_authority(startup, monkeypatch):
    monkeypatch.setenv("HERMES_KANBAN_TASK", "task")
    assert wire.protected_worker() is True
    monkeypatch.delenv("HERMES_KANBAN_TASK")
    assert wire.protected_worker() is True
    with pytest.raises(AuthorityDenied): wire.require_mcp_connection_authority()
    startup.module.defer_background_mcp_discovery(logger=startup.log, thread_name="synthetic", delay=0)
    assert startup.events == []


def test_native_admin_startup_keeps_nonempty_configuration_and_exact_filter(startup):
    startup.prepare(startup.args)
    for thread in startup.threads: thread.target(*thread.args)
    assert startup.module._has_configured_mcp_servers() is True
    assert startup.module.get_mcp_server_filter() == ["synthetic-native"]
    assert "thread-start" in startup.events
    assert ("discovery", ("synthetic-native",)) in startup.events
    startup.module.set_mcp_server_filter("terminal")
    startup.module._discover_mcp_tools_without_interactive_oauth()
    assert startup.events[-1] == ("discovery", ())


@pytest.mark.parametrize("entry", ["_owner_secret_mapping", "_owner_secret_scope",
    "_install_owner_secret_scope", "_connect_server", "discover_mcp_tools"])
def test_native_mcp_deep_entry_refuses_before_secret_or_transport_boundaries(
        native_candidate, native_modules, monkeypatch, entry):
    from contextlib import contextmanager
    monkeypatch.setenv("HERMES_KANBAN_TASK", "task")
    touched = []
    def forbidden(*args, **kwargs):
        touched.append("secret-or-transport")
        raise AssertionError("native secret/transport boundary reached")
    monkeypatch.setitem(sys.modules, "agent.secret_scope", NS(
        _is_process_home=forbidden, build_profile_secret_scope=forbidden,
        reset_secret_scope=forbidden, set_secret_scope=forbidden))
    monkeypatch.setitem(sys.modules, "hermes_cli.env_loader", NS(hydrate_profile_secret_sources=forbidden))
    body = function(native_source(native_candidate, "tools/mcp_tool_discovery.py"), entry,
        _owner_scope_home=forbidden, _core=NS(MCPServerTask=forbidden),
        _acquire_discovery_lock_with_retry=forbidden)
    with pytest.raises(AuthorityDenied):
        if entry in {"_install_owner_secret_scope", "_connect_server"}:
            asyncio.run(body("synthetic-native", {}) if entry == "_connect_server" else body())
        elif entry == "_owner_secret_scope":
            with contextmanager(body)(): pass
        elif entry == "_owner_secret_mapping": body(Path("/synthetic/home"))
        else: body(allowed_mcp_names=["synthetic-native"])
    assert touched == []
