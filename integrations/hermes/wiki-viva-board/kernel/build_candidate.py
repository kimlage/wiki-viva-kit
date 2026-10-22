"""Generate an inert patch against the reviewed Hermes 711 source. Never apply it.

Only pinned public code is read. There is deliberately no install/restart mode.
"""
from __future__ import annotations

import argparse
import ast
import difflib
import hashlib
import json
from pathlib import Path

BASE = "71177446eec8d0e2ce107d69f67c4ee4492d81c4"
HERE = Path(__file__).resolve().parent
KIT = HERE.parents[3]


def _entry(source: str, function: str, statements: str) -> str:
    tree = ast.parse(source)
    matches = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == function]
    if len(matches) != 1:
        raise ValueError(f"ambiguous kernel entry: {function}")
    node = matches[0]
    first = node.body[1] if isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str) else node.body[0]
    lines = source.splitlines(keepends=True)
    lines.insert(first.lineno - 1, "".join(" " * first.col_offset + line + "\n" for line in statements.splitlines()))
    return "".join(lines)


def _replace(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError("kernel source anchor changed: " + old[:100])
    return source.replace(old, new)


def _class_entry(source: str, cls: str, name: str, statements: str) -> str:
    classes = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.ClassDef) and n.name == cls]
    matches = [n for c in classes for n in c.body if isinstance(n, ast.FunctionDef) and n.name == name]
    if len(matches) != 1:
        raise ValueError(f"ambiguous native method: {cls}.{name}")
    node = matches[0]
    first = node.body[1] if isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str) else node.body[0]
    lines = source.splitlines(keepends=True)
    lines.insert(first.lineno - 1, "".join(" " * first.col_offset + line + "\n" for line in statements.splitlines()))
    return "".join(lines)


def _with_native_launch(source: str) -> str:
    nodes = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef) and n.name == "_default_spawn"]
    if len(nodes) != 1:
        raise ValueError("native spawn contract changed")
    node = nodes[0]
    first = node.body[1]
    lines = source.splitlines(keepends=True)
    body = lines[first.lineno-1:node.end_lineno]
    lines[first.lineno-1:node.end_lineno] = ["    from tools.wiki_native_host import prepare_worker\n",
        "    with prepare_worker(task.id, board) as _wiki_launch:\n",
        *("    " + line if line.strip() else "\n" for line in body)]
    return "".join(lines)


def _with_native_host_lifespan(source: str) -> str:
    nodes = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.AsyncFunctionDef) and n.name == "_lifespan"]
    if len(nodes) != 1:
        raise ValueError("native host lifespan contract changed")
    node = nodes[0]
    lines = source.splitlines(keepends=True)
    start = node.body[0].lineno - 1
    body = lines[start:node.end_lineno]
    lines[start:node.end_lineno] = ["    from tools.wiki_native_host import native_host_scope\n",
        "    with native_host_scope(app):\n", *("    " + line if line.strip() else "\n" for line in body)]
    return "".join(lines)


def _body(source: str, name: str, statements: str) -> str:
    """Replace one small native entry body, retaining its signature/docstring."""
    matches = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef) and n.name == name]
    if len(matches) != 1:
        raise ValueError(f"ambiguous kernel body: {name}")
    node = matches[0]
    first = node.body[1] if isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str) else node.body[0]
    lines = source.splitlines(keepends=True)
    lines[first.lineno - 1:node.end_lineno] = ["".join(" " * first.col_offset + line + "\n" for line in statements.splitlines())]
    return "".join(lines)


def _return_guard(source: str, name: str, guard: str) -> str:
    matches = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef) and n.name == name]
    if len(matches) != 1:
        raise ValueError(f"ambiguous kernel continuation: {name}")
    returns = [n for n in matches[0].body if isinstance(n, ast.Return)]
    if len(returns) != 1:
        raise ValueError(f"kernel continuation return changed: {name}")
    node = returns[0]
    lines = source.splitlines(keepends=True)
    lines[node.lineno - 1] = lines[node.lineno - 1].replace("return ", "_wiki_result = ", 1)
    indent = " " * node.col_offset
    lines.insert(node.end_lineno, indent + guard + "\n" + indent + "return _wiki_result\n")
    return "".join(lines)


def _tail_guard(source: str, name: str, guard: str) -> str:
    matches = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef) and n.name == name]
    if len(matches) != 1 or any(isinstance(n, ast.Return) for n in ast.walk(matches[0])):
        raise ValueError(f"kernel tail contract changed: {name}")
    node = matches[0]
    lines = source.splitlines(keepends=True)
    lines.insert(node.end_lineno, " " * node.body[-1].col_offset + guard + "\n")
    return "".join(lines)


def _content_free_boundary(source: str, name: str) -> str:
    """Preserve native returns and handled failures; seal unhandled error egress.

    Publication may already have followed an effect, so an unexpected extension
    failure is an explicit unknown/no-retry hold, never a new tool invocation.
    This does not bypass any authorization or catch-and-continue on a denial.
    """
    matches = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef) and n.name == name]
    if len(matches) != 1:
        raise ValueError(f"ambiguous kernel error boundary: {name}")
    node = matches[0]
    first = node.body[1] if isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str) else node.body[0]
    lines = source.splitlines(keepends=True)
    indent = " " * first.col_offset
    original = lines[first.lineno - 1:node.end_lineno]
    # Optional native handlers must not swallow the mandatory gate's denial.
    handlers = [n for n in ast.walk(node) if isinstance(n, ast.ExceptHandler)
                and isinstance(n.type, ast.Name) and n.type.id == "Exception"]
    for handler in sorted(handlers, key=lambda n: n.lineno, reverse=True):
        prefix = " " * handler.col_offset
        original[handler.lineno - first.lineno:handler.lineno - first.lineno] = [
            prefix + "except (AuthorityDenied, _FutureCancelled):\n", prefix + "    raise\n"]
    cleanup = """except BaseException as _wiki_error:
    from tools.wiki_authority import AuthorityDenied
    from asyncio import CancelledError as _AsyncCancelled
    from concurrent.futures import CancelledError as _FutureCancelled
    if isinstance(_wiki_error, AuthorityDenied):
        raise _wiki_error from None
    if isinstance(_wiki_error, KeyboardInterrupt):
        raise KeyboardInterrupt() from None
    if isinstance(_wiki_error, SystemExit):
        raise SystemExit(1) from None
    if isinstance(_wiki_error, (_AsyncCancelled, _FutureCancelled)):
        raise type(_wiki_error)() from None
    raise AuthorityDenied('authority_native_failure_unknown_no_retry') from None
"""
    lines[first.lineno - 1:node.end_lineno] = [indent + "from tools.wiki_authority import AuthorityDenied\n",
        indent + "from concurrent.futures import CancelledError as _FutureCancelled\n",
        indent + "try:\n", *("    " + line for line in original),
        *(indent + line + "\n" for line in cleanup.splitlines())]
    return "".join(lines)


def _mcp_entries(source: str) -> str:
    handlers = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef) and n.name == "_handler"]
    if len(handlers) != 2:
        raise ValueError("MCP handler contract changed")
    lines = source.splitlines(keepends=True)
    for node in sorted(handlers, key=lambda n: n.lineno, reverse=True):
        first = node.body[0]
        prefix = " " * first.col_offset
        lines.insert(first.lineno - 1, prefix + "from tools.wiki_authority import AuthorityDenied\n" + prefix + "raise AuthorityDenied('authority_account_enforcement_required')\n")
    return "".join(lines)


def source_digest(pin):
    """Explicit public digest metadata; legacy string pins remain readable."""
    if type(pin) is str:
        return pin
    if type(pin) is dict and set(pin) == {"sha256"} and type(pin["sha256"]) is str:
        return pin["sha256"]
    raise ValueError("kernel source pin format invalid")


def candidate(source_root: Path) -> dict[str, tuple[str, str]]:
    pins = json.loads((HERE / "source-pins.json").read_text())
    changes = {}
    for path, expected in pins["files"].items():
        raw = (source_root / path).read_bytes()
        expected = source_digest(expected)
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError(f"kernel source revision mismatch: {path}")
        changes[path] = (raw.decode(), raw.decode())

    def edit(path, fn):
        old, new = changes[path]
        changes[path] = (old, fn(new))

    edit("hermes_cli/web_server.py", _with_native_host_lifespan)

    # Establish process restriction/admission at complete-module import time,
    # before native launch preparation, dotenv, user plugins or built-in tools.
    # Native stdlib bootstrap still hardens the import path first.
    import_guard = "from tools.wiki_native_startup_guard import prepare_process_import as _wiki_prepare_import\n_wiki_prepare_import()\n"
    edit("hermes_bootstrap.py", lambda s: _replace(s,
        "_settle_interrupted_update()\n", "_settle_interrupted_update()\n\n" + import_guard))
    edit("hermes_cli/main.py", lambda s: _replace(s,
        "if _early_recovery_mod.restore_interrupted_pull():\n    _early_recovery_mod.relaunch_after_restore()\n",
        "if _early_recovery_mod.restore_interrupted_pull():\n    _early_recovery_mod.relaunch_after_restore()\n\n" + import_guard))
    edit("model_tools.py", lambda s: _replace(s, "\nimport os\n", "\n" + import_guard + "\nimport os\n"))
    edit("tools/registry.py", lambda s: _entry(s, "discover_builtin_tools",
        "from tools.wiki_native_startup_guard import protected_worker\nif protected_worker():\n    return []"))
    # Public admission never qualifies credential materialization. Preserve
    # administrative loader behavior outside the protected worker; guard the
    # lower read/hydration paths too, including direct reload calls.
    edit("hermes_cli/env_loader.py", lambda s: _entry(s, "load_hermes_dotenv",
        "from tools.wiki_native_startup_guard import protected_worker\nif protected_worker():\n    return []"))
    for name in ("_env_keys_defined_in_dotenv", "_clear_known_keys_missing_from_dotenv",
                 "get_secret_source_values", "hydrate_profile_secret_sources", "_hydrate_profile_secret_sources",
                 "_sanitize_loaded_credentials", "_load_dotenv_with_fallback", "_sanitize_env_file_if_needed",
                 "_apply_managed_env", "_apply_external_secret_sources", "_load_secrets_config"):
        edit("hermes_cli/env_loader.py", lambda s, n=name: _entry(s, n,
            "from tools.wiki_native_startup_guard import require_secret_materialization\nrequire_secret_materialization()"))
    edit("hermes_cli/env_loader.py", lambda s: _entry(s, "reset_secret_source_cache",
        "from tools.wiki_native_startup_guard import protected_worker\nif protected_worker():\n    return"))
    for name in ("set_secret_scope", "current_secret_scope", "get_secret", "load_env_file",
                 "build_profile_secret_scope", "refresh_installed_secret_scope"):
        edit("agent/secret_scope.py", lambda s, n=name: _entry(s, n,
            "from tools.wiki_native_startup_guard import require_secret_materialization\nrequire_secret_materialization()"))
    for name in ("discover_plugins", "start_background_plugin_discovery", "_persist_plugin_toolset_keys"):
        edit("hermes_cli/plugins.py", lambda s, n=name: _entry(s, n,
            "from tools.wiki_native_startup_guard import protected_worker\nif protected_worker():\n    return"))
    for name in ("discover_and_load", "_refresh_secret_sources_after_discovery", "_discover_and_load_inner",
                 "_re_register_config_hooks_after_force"):
        edit("hermes_cli/plugins.py", lambda s, n=name: _class_entry(s, "PluginManager", n,
            "from tools.wiki_native_startup_guard import protected_worker\nif protected_worker():\n    return"))
    edit("hermes_cli/plugins.py", lambda s: _class_entry(s, "PluginManager", "__init__",
        "from tools.wiki_native_startup_guard import require_secret_materialization\nrequire_secret_materialization()"))
    edit("hermes_cli/plugins.py", lambda s: _entry(s, "get_plugin_manager",
        "from tools.wiki_native_startup_guard import require_secret_materialization\nrequire_secret_materialization()"))

    # Native metadata reads exclude text at SQL selection time, not after a
    # Task/Run object containing private body/result has already materialized.
    edit("hermes_cli/kanban_db.py", lambda s: _replace(s,
        "def get_task(conn: sqlite3.Connection, task_id: str) -> Optional[Task]:\n",
        "def get_task(conn: sqlite3.Connection, task_id: str, *, metadata_only: bool = False):\n    if metadata_only:\n        return conn.execute('SELECT id,assignee,status,current_run_id,claim_lock,claim_expires,worker_pid,worker_started_at,idempotency_key FROM tasks WHERE id = ?', (task_id,)).fetchone()\n"))
    edit("hermes_cli/kanban_db.py", lambda s: _replace(s,
        "def get_run(conn: sqlite3.Connection, run_id: int) -> Optional[Run]:\n",
        "def get_run(conn: sqlite3.Connection, run_id: int, *, metadata_only: bool = False):\n    if metadata_only:\n        return conn.execute('SELECT id,task_id,profile,status,claim_lock,claim_expires,worker_pid,worker_started_at,ended_at FROM task_runs WHERE id = ?', (int(run_id),)).fetchone()\n"))
    # Only success branches of the real provider verification mint ingress.
    edit("hermes_cli/dashboard_auth/middleware.py", lambda s: _entry(s, "gated_auth_middleware",
        "from tools.wiki_native_host import serve_verified_session"))
    edit("hermes_cli/dashboard_auth/middleware.py", lambda s: _entry(s, "_serve_refreshed",
        "from tools.wiki_native_host import serve_verified_session"))
    edit("hermes_cli/dashboard_auth/middleware.py", lambda s: _replace(s,
        "    request.state.session = new_session\n    response = await call_next(request)",
        "    request.state.session = new_session\n    response = await serve_verified_session(new_session, request, call_next)"))
    edit("hermes_cli/dashboard_auth/middleware.py", lambda s: _replace(s,
        "            request.state.session = bearer_session\n            return await call_next(request)",
        "            request.state.session = bearer_session\n            return await serve_verified_session(bearer_session, request, call_next)"))
    edit("hermes_cli/dashboard_auth/middleware.py", lambda s: _replace(s,
        "    request.state.session = session\n    response = await call_next(request)",
        "    request.state.session = session\n    response = await serve_verified_session(session, request, call_next)"))
    # Controller producer, native registration, real constructor and turn
    # consumer are connected in this candidate. No installation is performed.
    edit("hermes_cli/kanban_db_dispatch.py", lambda s: _replace(s,
        "    cmd = _restart_safe_worker_argv(task, cmd)",
        "    _wiki_direct_cmd = list(cmd)\n    cmd = _restart_safe_worker_argv(task, cmd)\n    _wiki_launch.qualify(_wiki_direct_cmd, cmd)"))
    edit("hermes_cli/kanban_db_dispatch.py", lambda s: _replace(s,
        "    log_f = _open_worker_log(task, board)",
        "    _wiki_launch.configure(env)\n    log_f = _open_worker_log(task, board)"))
    edit("hermes_cli/kanban_db_dispatch.py", lambda s: _replace(s,
        "        proc = subprocess.Popen(\n",
        "        _wiki_launch.before_spawn()\n        proc = subprocess.Popen(\n"))
    edit("hermes_cli/kanban_db_dispatch.py", lambda s: _replace(s,
        "    if _kb._IS_WINDOWS:\n        _live_worker_procs[proc.pid] = proc",
        "    _wiki_launch.spawned(proc.pid)\n    if _kb._IS_WINDOWS:\n        _live_worker_procs[proc.pid] = proc"))
    edit("hermes_cli/kanban_db_dispatch.py", _with_native_launch)
    edit("hermes_cli/kanban_db_dispatch.py", lambda s: _replace(s,
        '        # Workers run under a profile-scoped HERMES_HOME and so see that\n        # profile\'s shell-hook allowlist; pass --accept-hooks explicitly so\n        # configured hooks still register.\n        "--accept-hooks",\n',
        '        # A protected read worker does not auto-approve startup shell hooks.\n'))
    edit("hermes_cli/kanban_db_dispatch.py", lambda s: _replace(s,
        '        _kb._append_event(conn, task_id, "spawned", {"pid": int(pid), "started_at": started_at}, run_id=run_id)',
        '        _kb._append_event(conn, task_id, "spawned", {"pid": int(pid), "started_at": started_at}, run_id=run_id)\n    from tools.wiki_native_host import register_worker\n    register_worker(task_id, int(pid), started_at)'))
    edit("hermes_cli/kanban_db_dispatch.py", lambda s: _entry(s, "_set_worker_pid",
        "from tools.wiki_native_host import before_worker_registration\n_wiki_run, _wiki_claim = before_worker_registration(task_id, int(pid), conn)"))
    edit("hermes_cli/kanban_db_dispatch.py", lambda s: _replace(s,
        '        conn.execute("UPDATE tasks SET worker_pid = ?, worker_started_at = ? WHERE id = ?",\n                     (int(pid), started_at, task_id))',
        '        _wiki_changed = conn.execute("UPDATE tasks SET worker_pid = ?, worker_started_at = ? WHERE id = ? AND current_run_id = ? AND claim_lock = ? AND status = \'running\'",\n                     (int(pid), started_at, task_id, _wiki_run, _wiki_claim)).rowcount\n        if _wiki_changed != 1:\n            from tools.wiki_authority import AuthorityDenied\n            raise AuthorityDenied("authority_native_claim_changed")'))
    edit("hermes_cli/kanban_db_dispatch.py", lambda s: _replace(s,
        '            conn.execute("UPDATE task_runs SET worker_pid = ?, worker_started_at = ? WHERE id = ?",\n                         (int(pid), started_at, run_id))',
        '            _wiki_run_changed = conn.execute("UPDATE task_runs SET worker_pid = ?, worker_started_at = ? WHERE id = ? AND task_id = ? AND claim_lock = ? AND status = \'running\' AND ended_at IS NULL",\n                         (int(pid), started_at, _wiki_run, task_id, _wiki_claim)).rowcount\n            if _wiki_run_changed != 1:\n                from tools.wiki_authority import AuthorityDenied\n                raise AuthorityDenied("authority_native_claim_changed")'))
    edit("run_agent.py", lambda s: _class_entry(s, "AIAgent", "__init__",
        "session_id = __import__('tools.wiki_native_host_wire', fromlist=['bootstrap_agent']).bootstrap_agent(session_id)\nskip_context_files = True\nskip_memory = True\nskip_background_review = True"))
    edit("tools/kanban_tools.py", lambda s: _replace(s,
        "def register_current_worker_from_env() -> bool:",
        "def register_current_worker_from_env(*, native_session=None) -> bool:"))
    edit("tools/kanban_tools.py", lambda s: _entry(s, "register_current_worker_from_env",
        "from tools.wiki_native_host_wire import admit_worker_registration\nadmit_worker_registration(native_session)"))
    edit("hermes_cli/cli_single_query.py", lambda s: _replace(s,
        "        if not register_current_worker_from_env():",
        "        if not register_current_worker_from_env(native_session=cli.session_id):"))

    # Both native main and fast-chat enter here BEFORE one-shot registration
    # or AIAgent. Authenticate/admit first; public context is not permission
    # to scan plugins, initialize private MCP transports or register hooks.
    edit("hermes_cli/main.py", lambda s: _entry(s, "_prepare_agent_startup",
        "from tools.wiki_native_host_wire import prepare_cli_startup\nif prepare_cli_startup(args):\n    from hermes_cli.mcp_startup import set_mcp_server_filter\n    set_mcp_server_filter(getattr(args, 'toolsets', None))\n    return"))
    edit("hermes_cli/cli_init_mixin.py", lambda s: _entry(s, "_init_runtime_state",
        "from tools.wiki_native_host_wire import prepared_cli_session\n_wiki_session = prepared_cli_session(resume)"))
    edit("hermes_cli/cli_init_mixin.py", lambda s: _replace(s,
        "        self.session_id = resume or new_session_id(self.session_start)",
        "        self.session_id = _wiki_session or resume or new_session_id(self.session_start)"))
    # Restriction persists after env-hint consumption, across deferred threads.
    # Administrative/non-worker configuration and the native filter stay intact.
    for name in ("start_background_mcp_discovery", "defer_background_mcp_discovery",
                 "start_deferred_mcp_discovery_now", "_discover_mcp_tools_without_interactive_oauth"):
        edit("hermes_cli/mcp_startup.py", lambda s, n=name: _entry(s, n,
            "from tools.wiki_native_host_wire import protected_worker\nif protected_worker():\n    return"))
    # Every actual hydration/connection path rechecks the generic restriction.
    # No service-specific connector or account-proof fabrication is introduced.
    for name in ("_owner_secret_mapping", "_owner_secret_scope", "_install_owner_secret_scope",
                 "_connect_server", "discover_mcp_tools"):
        edit("tools/mcp_tool_discovery.py", lambda s, n=name: _entry(s, n,
            "from tools.wiki_native_host_wire import require_mcp_connection_authority\nrequire_mcp_connection_authority()"))

    guard = "from tools.wiki_authority import require\nrequire(function_name, function_args, session=getattr(ids, 'session_id', ''), task=getattr(ids, 'task_id', ''))"
    edit("model_tools.py", lambda s: _entry(s, "_pre_dispatch_guards", guard))
    edit("model_tools.py", lambda s: _entry(s, "handle_function_call",
        "from tools.wiki_authority import require\nrequire(function_name, function_args, session=session_id or '', task=task_id or '')"))
    edit("model_tools.py", lambda s: _entry(s, "_apply_request_middleware", guard))
    edit("model_tools.py", lambda s: _replace(s,
        "        return mw.payload, mw.original_payload, mw.trace",
        "        require(function_name, mw.payload, session=ids.session_id or '', task=ids.task_id or '')\n        return mw.payload, mw.original_payload, mw.trace"))
    # Native request/pre-hook failures retain metadata, never exception bodies or
    # tracebacks. Revalidate outside the extension's failure before continuing.
    for old, message in [
        ('        logger.debug("tool_request middleware error: %s", _mw_err)', "tool_request middleware failed"),
        ('            logger.debug("pre_tool_call hook error: %s", _hook_err)', "pre_tool_call hook failed"),
        ('        logger.debug("ACP edit approval guard error: %s", _edit_approval_err)', "ACP edit approval guard failed"),
    ]:
        indent = old[:len(old) - len(old.lstrip())]
        replacement = indent + "require(function_name, function_args, session=ids.session_id or '', task=ids.task_id or '')\n"
        replacement += indent + "logger.debug('" + message + "; exception content omitted')"
        edit("model_tools.py", lambda s, a=old, b=replacement: _replace(s, a, b))
    edit("model_tools.py", lambda s: _replace(s,
        "        if block_message is not None:\n            return function_args, (tool_error(block_message),",
        "        require(function_name, function_args, session=ids.session_id or '', task=ids.task_id or '')\n        if block_message is not None:\n            return function_args, (tool_error(block_message),"))
    edit("model_tools.py", lambda s: _replace(s,
        "        edit_block_message = maybe_require_edit_approval(function_name, function_args)\n",
        "        edit_block_message = maybe_require_edit_approval(function_name, function_args)\n        require(function_name, function_args, session=ids.session_id or '', task=ids.task_id or '')\n"))
    # One final handler boundary covers success, handler errors and normalizer
    # failures. The former catch/logger must never see raw exception bodies.
    edit("tools/registry.py", lambda s: _body(s, "dispatch", """from tools.wiki_authority import invoke, require
def _wiki_dispatch(actual_args):
    entry = self.get_entry(name, scope=scope)
    if not entry:
        return tool_error('unknown_tool')
    accepted = _kwargs_accepted_by(entry.handler, kwargs)
    if entry.is_async:
        from model_tools import _run_async
        result = _run_async(entry.handler(actual_args, **accepted))
    else:
        result = entry.handler(actual_args, **accepted)
    require(name, actual_args, phase='disclose', session=kwargs.get('session_id', ''), task=kwargs.get('task_id', ''), surface='tool_return')
    return self._normalize_handler_result(name, result)
return invoke(name, args, _wiki_dispatch, session=kwargs.get('session_id', ''), task=kwargs.get('task_id', ''))"""))
    # Recheck before post hooks/result transforms can observe returned content.
    edit("model_tools.py", lambda s: _replace(s,
        "        duration_ms = _elapsed_ms(start)\n        _emit(result, duration_ms=duration_ms)",
        "        require(function_name, function_args, phase='disclose', session=session_id or '', task=task_id or '', surface='tool_return')\n        duration_ms = _elapsed_ms(start)\n        _emit(result, duration_ms=duration_ms)"))
    edit("model_tools.py", lambda s: _entry(s, "_emit_post_tool_call_hook",
        "from tools.wiki_authority import require\nrequire(function_name, function_args, phase='disclose', session=session_id or '', task=task_id or '', surface='tool_observer')"))
    edit("model_tools.py", lambda s: _replace(s,
        "        if status is None:\n            status, error_type, error_message = _tool_result_observer_fields(function_name, result)\n        invoke_hook(",
        "        require(function_name, function_args, phase='disclose', session=session_id or '', task=task_id or '', surface='tool_observer')\n        if status is None:\n            status, error_type, error_message = _tool_result_observer_fields(function_name, result)\n        require(function_name, function_args, phase='disclose', session=session_id or '', task=task_id or '', surface='tool_observer')\n        invoke_hook("))
    edit("model_tools.py", lambda s: _body(s, "_apply_transform_tool_result_hook", """from tools.wiki_authority import require
require(function_name, function_args, phase='disclose', session=ids.session_id or '', task=ids.task_id or '', surface='tool_transform')
transformed = result
try:
    from hermes_cli.lifecycle import has_hook, invoke_hook
    if has_hook('transform_tool_result'):
        require(function_name, function_args, phase='disclose', session=ids.session_id or '', task=ids.task_id or '', surface='tool_transform')
        status, error_type, error_message = _tool_result_observer_fields(function_name, result)
        require(function_name, function_args, phase='disclose', session=ids.session_id or '', task=ids.task_id or '', surface='tool_transform')
        hook_results = invoke_hook('transform_tool_result', tool_name=function_name, args=function_args, result=result, **ids.hook_kwargs(), duration_ms=duration_ms, status=status, error_type=error_type, error_message=error_message)
        transformed = next((r for r in hook_results if isinstance(r, str)), result)
except Exception:
    logger.debug('transform_tool_result hook failed; exception content omitted')
require(function_name, function_args, phase='disclose', session=ids.session_id or '', task=ids.task_id or '', surface='tool_return')
return transformed"""))
    edit("model_tools.py", lambda s: _replace(s,
        '        logger.debug("post_tool_call hook error: %s", _hook_err)',
        '        logger.debug("post_tool_call hook failed; exception content omitted")'))
    edit("model_tools.py", lambda s: _replace(s,
        '        error_msg = f"Error executing {function_name}: {e!s}"\n        logger.exception(error_msg)\n        return _emit(tool_error(_sanitize_tool_error(error_msg)), duration_ms=_elapsed_ms(start),\n                     status="error", error_type=type(e).__name__, error_message=str(e))',
        "        from tools.wiki_authority import safe_tool_failure\n        require(function_name, function_args, phase='disclose', session=session_id or '', task=task_id or '', surface='tool_return')\n        return _emit(safe_tool_failure(), duration_ms=_elapsed_ms(start), status='error', error_type='tool_execution_failed', error_message='reconcile_existing_operation')"))
    edit("tools/connectors/dispatch.py", lambda s: _entry(s, "dispatch_connector_call",
        "from tools.wiki_authority import require\nrequire(name, arguments)"))
    # 711 has no effective immutable account pin in execute. A wire field alone
    # cannot close that boundary. Deny BEFORE factory/credential/transport work.
    edit("tools/connectors/gateway/client.py", lambda s: _entry(s, "execute",
        "from tools.wiki_authority import AuthorityDenied\nraise AuthorityDenied('authority_account_enforcement_required')"))
    edit("tools/connectors/gateway/client.py", lambda s: _entry(s, "_request",
        "from tools.wiki_authority import AuthorityDenied\nif path == wire.CONNECTOR_EXECUTE_PATH:\n    raise AuthorityDenied('authority_account_enforcement_required')"))
    # MCP has no proven account binding for this candidate either; direct RPC and
    # retry/reconnect paths stay closed without opening or copying auth stores.
    edit("tools/mcp_tool_handlers.py", lambda s: _entry(s, "_dispatch",
        "from tools.wiki_authority import AuthorityDenied\nraise AuthorityDenied('authority_account_enforcement_required')"))
    edit("tools/mcp_tool_handlers.py", _mcp_entries)
    edit("agent/turn_context.py", lambda s: _entry(s, "build_turn_context",
        "from tools.wiki_native_host_wire import bound_task\nfrom tools.wiki_authority import admit\ntask_id = bound_task(agent, task_id)\nrequired_wiki_context = admit(agent.session_id, task_id)"))
    edit("agent/turn_context.py", lambda s: _replace(s,
        "    # Every turn, not only on a prompt restore:",
        "    plugin_user_context = required_wiki_context + '\\n\\n' + plugin_user_context\n    # Every turn, not only on a prompt restore:"))
    # This is inside the actual middleware continuation, after argument rewrites.
    edit("agent/turn_api_call.py", lambda s: _entry(s, "_perform_api_call",
        "from tools.wiki_authority import require_agent\nrequire_agent('model_call', {'provider': agent.provider, 'base_url': agent.base_url, 'model': agent.model, 'request': next_api_kwargs}, agent, task=effective_task_id, phase='disclose', surface='model_provider')"))
    edit("agent/turn_api_call.py", lambda s: _replace(s,
        "        next_api_kwargs = dialogue_request(agent, next_api_kwargs)\n",
        "        next_api_kwargs = dialogue_request(agent, next_api_kwargs)\n        require_agent('model_call', {'provider': agent.provider, 'base_url': agent.base_url, 'model': agent.model, 'request': next_api_kwargs}, agent, task=effective_task_id, phase='disclose', surface='model_provider')\n"))
    edit("tools/bot_mode_dm.py", lambda s: _entry(s, "message_agent_tool",
        "from tools.wiki_authority import require_agent\nrequire_agent('message_agent', {'target': target, 'message': message}, agent, task=task_id, phase='disclose', surface='bot_relay')"))
    edit("run_agent.py", lambda s: _entry(s, "_execute_tool_calls",
        "from tools.wiki_authority import require\nimport json as _wiki_json\nfor _wiki_call in assistant_message.tool_calls:\n    _wiki_args = _wiki_call.function.arguments\n    require(_wiki_call.function.name, _wiki_json.loads(_wiki_args) if isinstance(_wiki_args, str) else _wiki_args, session=self.session_id, task=effective_task_id)"))
    edit("run_agent.py", lambda s: _entry(s, "_dispatch_delegate_task",
        "from tools.wiki_authority import AuthorityDenied\nraise AuthorityDenied('authority_worker_unqualified')"))
    # Guard the real observer body, including its internally handled failure.
    # The concrete task is supplied by the one native commit caller, never
    # recovered from ambient context or a title.
    edit("run_agent.py", lambda s: _replace(s,
        '                                      failed: bool, tool_call_id: str = "") -> str:',
        '                                      failed: bool, tool_call_id: str = "", task_id: str) -> str:'))
    edit("run_agent.py", lambda s: _entry(s, "_append_guardrail_observation",
        "from tools.wiki_authority import require_agent\nrequire_agent(tool_name, function_args, self, task=task_id, phase='disclose', surface='tool_observer')"))
    edit("run_agent.py", lambda s: _replace(s,
        "                observation = self._tool_guardrails.observe_call(",
        "                require_agent(tool_name, function_args, self, task=task_id, phase='disclose', surface='tool_observer')\n                observation = self._tool_guardrails.observe_call("))
    edit("run_agent.py", lambda s: _replace(s,
        '                logger.debug("stall-guard identical-call observation failed: %s", exc)',
        "                require_agent(tool_name, function_args, self, task=task_id, phase='disclose', surface='tool_observer')\n                logger.debug('stall-guard identical-call observation failed; exception content omitted')"))
    edit("run_agent.py", lambda s: _replace(s,
        "        record_guardrail_warnings(self, decision, stall_kind if stall_notice else None)",
        "        require_agent(tool_name, function_args, self, task=task_id, phase='disclose', surface='tool_observer')\n        record_guardrail_warnings(self, decision, stall_kind if stall_notice else None)"))
    edit("run_agent.py", lambda s: _return_guard(s, "_append_guardrail_observation",
        "require_agent(tool_name, function_args, self, task=task_id, phase='disclose', surface='tool_observer')"))
    edit("agent/tool_executor.py", lambda s: _replace(s,
        "                function_name, function_args, function_result, failed=is_error, tool_call_id=tool_call_id,",
        "                function_name, function_args, function_result, failed=is_error, tool_call_id=tool_call_id, task_id=effective_task_id,"))
    # Observation metrics have their own inner catches. Sanitize at those real
    # sinks; an outer publication wrapper cannot intercept a swallowed traceback.
    for path, replacements in {
        "hermes_cli/observability/shared_metrics_efficiency.py": [
            ('logger.debug("Shared-metrics tool output not noted", exc_info=True)', 'logger.debug("Shared-metrics tool output not noted; exception content omitted")'),
            ('logger.debug("Shared-metrics tool output truncation not recorded", exc_info=True)', 'logger.debug("Shared-metrics tool output truncation not recorded; exception content omitted")'),
        ],
        "hermes_cli/observability/shared_metrics_harness.py": [
            ('logger.debug("Shared-metrics %s not recorded", mark_attr, exc_info=True)', 'logger.debug("Shared-metrics %s not recorded; exception content omitted", mark_attr)'),
            ('logger.debug("Shared-metrics loop guard not recorded", exc_info=True)', 'logger.debug("Shared-metrics loop guard not recorded; exception content omitted")'),
            ('logger.debug("Shared-metrics tool outcome not observed", exc_info=True)', 'logger.debug("Shared-metrics tool outcome not observed; exception content omitted")'),
        ],
        "hermes_cli/observability/relay_shared_metrics.py": [
            ('logger.warning(message, exc_info=True)', 'logger.warning("%s; exception content omitted", message)'),
            ('logger.warning("Hermes shared metrics hook failed: %s", hook_name, exc_info=True)', 'logger.warning("Hermes shared metrics hook failed: %s; exception content omitted", hook_name)'),
            ('logger.debug("Unable to read Hermes shared-metrics policy", exc_info=True)', 'logger.debug("Unable to read Hermes shared-metrics policy; exception content omitted")'),
            ('logger.warning("Hermes shared metrics initialization failed", exc_info=True)', 'logger.warning("Hermes shared metrics initialization failed; exception content omitted")'),
        ],
    }.items():
        for old, new in replacements:
            edit(path, lambda s, a=old, b=new: _replace(s, a, b))
    # Actual inline/context/memory handlers, shared by sequential and concurrent
    # lanes, must check AFTER all argument rewrites and at publication boundaries.
    edit("agent/tool_executor.py", lambda s: _entry(s, "_dispatch_authorized_once",
        "from tools.wiki_authority import require_agent, invoke_agent"))
    edit("agent/tool_executor.py", lambda s: _replace(s,
        '    block_body = None if block_message is None else {"error": block_message}',
        "    require_agent(ref.name, ref.args, agent, task=ref.task_id)\n" +
        '    block_body = None if block_message is None else {"error": block_message}'))
    edit("agent/tool_executor.py", lambda s: _replace(s,
        "    return _run_with_activity_heartbeat(agent, ref.name, lambda: execute(ref.args))",
        "    return _run_with_activity_heartbeat(agent, ref.name, lambda: invoke_agent(ref.name, ref.args, execute, agent, task=ref.task_id))"))
    edit("agent/tool_executor.py", lambda s: _entry(s, "_run_agent_tool_execution_middleware",
        "from tools.wiki_authority import require_agent\nrequire_agent(function_name, function_args, agent, task=effective_task_id)"))
    edit("agent/tool_executor.py", lambda s: _return_guard(s, "_hermes_pipeline",
        "require_agent(function_name, state.args, agent, task=effective_task_id, phase='disclose', surface='native_relay')"))
    edit("agent/tool_executor.py", lambda s: _replace(s,
        "    return state\n\n\n# Sequential wait-loop poll cadence:",
        "    require_agent(function_name, state.args, agent, task=effective_task_id, phase='disclose')\n    return state\n\n\n# Sequential wait-loop poll cadence:"))
    for name, args, surface in [
        ("emit_post", "self.name, self.args, agent, task=self.task_id", "tool_observer"),
        ("_begin_tool_execution", "ref.name, ref.args, agent, task=ref.task_id", "native_ui"),
        ("_publish_sequential_result", "ref.name, managed.args, agent, task=ref.task_id", "tool_return"),
        ("_commit_tool_result", "ref.name, ref.args, agent, task=ref.task_id", "native_store"),
        ("_emit_tool_complete_and_risk", "ref.name, ref.args, agent, task=ref.task_id", "native_ui"),
        ("_abandoned_sequential_result", "ref.name, ref.args, agent, task=ref.task_id", "tool_return"),
        ("_unfinished_tool_result", "ref.name, ref.args, agent, task=ref.task_id", "tool_return"),
    ]:
        edit("agent/tool_executor.py", lambda s, n=name, a=args, surf=surface: _entry(s, n,
            "from tools.wiki_authority import require_agent\nrequire_agent(" + a + ", phase='disclose', surface='" + surf + "')"))
    for anchor, surface in [("    persisted_result = function_result\n", "native_store"), ("    note_tool_result(agent, function_name, tool_call_id, function_result, persisted_result)\n", "tool_observer"), ("    messages.append(tool_message)\n", "native_store"), ("    _tool_content = agent._tool_result_content_for_active_model(function_name, persisted_result)\n", "tool_return")]:
        edit("agent/tool_executor.py", lambda s, a=anchor, surf=surface: _replace(s, a,
            "    require_agent(ref.name, ref.args, agent, task=ref.task_id, phase='disclose', surface='" + surf + "')\n" + a))
    edit("agent/tool_executor.py", lambda s: _replace(s,
        "        if not blocked:\n            function_result = agent._append_guardrail_observation(",
        "        if not blocked:\n            require_agent(ref.name, ref.args, agent, task=ref.task_id, phase='disclose', surface='tool_observer')\n            function_result = agent._append_guardrail_observation("))
    for anchor, surface in [
        ("    _record_persisted_path_for_stub(agent, tool_call_id, persisted_result)\n", "native_store"),
        ("    tool_message = make_tool_result_message(function_name, _tool_content, tool_call_id, effect_disposition=effect_disposition)\n", "tool_return"),
        ("    if not _flush_session_db_after_tool_progress(agent, messages, stage=f\"tool result {function_name}\"):\n", "native_store"),
    ]:
        edit("agent/tool_executor.py", lambda s, a=anchor, surf=surface: _replace(s, a,
            "    require_agent(ref.name, ref.args, agent, task=ref.task_id, phase='disclose', surface='" + surf + "')\n" + a))
    edit("agent/tool_executor.py", lambda s: _replace(s,
        "        if not blocked:\n            try:\n                agent._record_file_mutation_result(",
        "        if not blocked:\n            require_agent(ref.name, ref.args, agent, task=ref.task_id, phase='disclose', surface='tool_observer')\n            try:\n                agent._record_file_mutation_result("))
    edit("agent/tool_executor.py", lambda s: _replace(s,
        "    if not blocked and prepare_metadata:\n        try:",
        "    if not blocked and prepare_metadata:\n        require_agent(ref.name, ref.args, agent, task=ref.task_id, phase='disclose', surface='native_ui')\n        try:"))
    edit("agent/tool_executor.py", lambda s: _replace(s,
        "            metadata = prepare_metadata(tool_call_id, function_name, display_args, function_result)",
        "            require_agent(ref.name, ref.args, agent, task=ref.task_id, phase='disclose', surface='native_ui')\n            metadata = prepare_metadata(tool_call_id, function_name, display_args, function_result)"))
    edit("agent/tool_executor.py", lambda s: _replace(s,
        "    if not blocked:\n        # ``tool.completed`` projects AFTER",
        "    if not blocked:\n        require_agent(ref.name, ref.args, agent, task=ref.task_id, phase='disclose', surface='native_ui')\n        # ``tool.completed`` projects AFTER"))
    edit("agent/tool_executor.py", lambda s: _replace(s,
        '    return persisted_result, function_result, tool_message.get("_tool_output_risk")',
        '    require_agent(ref.name, ref.args, agent, task=ref.task_id, phase="disclose", surface="tool_return")\n    agent._wiki_native_projection = __import__("tools.wiki_native_host_wire", fromlist=["project_native_result"]).project_native_result(agent, ref.task_id)\n    require_agent(ref.name, ref.args, agent, task=ref.task_id, phase="disclose", surface="tool_return")\n    return persisted_result, function_result, tool_message.get("_tool_output_risk")'))
    # The durability helper itself has two preparation callbacks. Carry the
    # concrete native ref into it; entry authorization cannot cover later sends.
    edit("agent/tool_executor.py", lambda s: _replace(s,
        "def _flush_session_db_after_tool_progress(agent, messages: list, *, stage: str) -> bool:",
        "def _flush_session_db_after_tool_progress(agent, messages: list, *, stage: str, ref: _ToolCallRef) -> bool:"))
    edit("agent/tool_executor.py", lambda s: _entry(s, "_flush_session_db_after_tool_progress",
        "from tools.wiki_authority import require_agent\nrequire_agent(ref.name, ref.args, agent, task=ref.task_id, phase='disclose', surface='native_store')"))
    edit("agent/tool_executor.py", lambda s: _replace(s,
        "    _maybe_inject_iteration_budget_warning(agent, messages)\n",
        "    require_agent(ref.name, ref.args, agent, task=ref.task_id, phase='disclose', surface='native_store')\n    _maybe_inject_iteration_budget_warning(agent, messages)\n"))
    edit("agent/tool_executor.py", lambda s: _replace(s,
        "    try:\n        persisted = agent._flush_messages_to_session_db(messages) is not False\n",
        "    require_agent(ref.name, ref.args, agent, task=ref.task_id, phase='disclose', surface='native_store')\n    try:\n        persisted = agent._flush_messages_to_session_db(messages) is not False\n"))
    for old, new in [
        ('_flush_session_db_after_tool_progress(agent, messages, stage=f"tool result {function_name}")', '_flush_session_db_after_tool_progress(agent, messages, stage=f"tool result {function_name}", ref=ref)'),
        ('_flush_session_db_after_tool_progress(agent, messages, stage=f"invalid tool arguments {ref.name}")', '_flush_session_db_after_tool_progress(agent, messages, stage=f"invalid tool arguments {ref.name}", ref=ref)'),
        ('_flush_session_db_after_tool_progress(agent, messages, stage=f"{flush_stage} {name}")', '_flush_session_db_after_tool_progress(agent, messages, stage=f"{flush_stage} {name}", ref=ref)'),
    ]:
        edit("agent/tool_executor.py", lambda s, a=old, b=new: _replace(s, a, b))
    edit("agent/tool_executor.py", lambda s: _entry(s, "_append_skipped_tool_results", "from tools.wiki_authority import require_agent"))
    edit("agent/tool_executor.py", lambda s: _replace(s,
        '        result = content.replace("{name}", name)\n        messages.append(',
        '        result = content.replace("{name}", name)\n        ref = _parse_tool_call(agent, tc).ref(effective_task_id)\n        require_agent(ref.name, ref.args, agent, task=ref.task_id, phase="disclose", surface="native_store")\n        messages.append('))
    edit("agent/tool_executor.py", lambda s: _entry(s, "_append_invalid_arguments_result",
        "from tools.wiki_authority import require_agent\nrequire_agent(ref.name, ref.args, agent, task=ref.task_id, phase='disclose', surface='tool_observer')"))
    edit("agent/tool_executor.py", lambda s: _replace(s,
        "    ref.emit_invalid_arguments(agent, parse_error)\n    messages.append(",
        "    ref.emit_invalid_arguments(agent, parse_error)\n    require_agent(ref.name, ref.args, agent, task=ref.task_id, phase='disclose', surface='native_store')\n    messages.append("))
    edit("agent/tool_executor.py", lambda s: _replace(s,
        '            _ToolCallRef(name, {}, effective_task_id, (hook_id or _pairing_tool_call_id)(tc), []).emit_post(',
        '            ref.call_id = (hook_id or _pairing_tool_call_id)(tc)\n            ref.emit_post('))
    edit("agent/tool_executor.py", lambda s: _replace(s,
        '        from hermes_state import classify_persistence_error\n        agent._last_persistence_error_cause = classify_persistence_error(exc)\n        logger.warning("Incremental tool-call persistence failed after %s: %s", stage, exc)',
        '        agent._last_persistence_error_cause = "unknown"\n        logger.warning("Incremental tool-call persistence failed after %s; exception content omitted", stage)'))
    edit("agent/tool_executor.py", lambda s: _replace(s,
        '        logger.debug("persisted-path record for result stub failed: %s", exc)',
        '        logger.debug("persisted-path record for result stub failed; exception content omitted")'))
    # Result formatters and argument preview callbacks are separate recipients;
    # an earlier callback may have invalidated the permit before the next one.
    edit("agent/tool_executor.py", lambda s: _replace(s,
        "            _log_result = verbose_text(function_result)",
        "            require_agent(ref.name, ref.args, agent, task=ref.task_id, phase='disclose', surface='tool_transform')\n            _log_result = verbose_text(function_result)"))
    edit("agent/tool_executor.py", lambda s: _replace(s,
        "    display_args = _redact_tool_args_for_display(function_name, function_args) or function_args\n    if _tool_progress_enabled(agent):",
        "    display_args = _redact_tool_args_for_display(function_name, function_args) or function_args\n    require_agent(ref.name, ref.args, agent, task=ref.task_id, phase='disclose', surface='native_ui')\n    if _tool_progress_enabled(agent):"))
    edit("agent/tool_executor.py", lambda s: _replace(s,
        '            print(agent._wrap_verbose("Args: ", json.dumps(display_args, indent=2, ensure_ascii=False)))',
        '            rendered_args = agent._wrap_verbose("Args: ", json.dumps(display_args, indent=2, ensure_ascii=False))\n            require_agent(ref.name, ref.args, agent, task=ref.task_id, phase="disclose", surface="native_ui")\n            print(rendered_args)'))
    edit("agent/tool_executor.py", lambda s: _replace(s,
        '            _safe_callback(agent.tool_progress_callback, "Tool progress", "tool.started",',
        '            require_agent(ref.name, ref.args, agent, task=ref.task_id, phase="disclose", surface="native_ui")\n            _safe_callback(agent.tool_progress_callback, "Tool progress", "tool.started",'))
    edit("agent/tool_executor.py", lambda s: _replace(s,
        '    _safe_callback(agent.tool_start_callback, "Tool start", tool_call_id, function_name, display_args)',
        '    require_agent(ref.name, ref.args, agent, task=ref.task_id, phase="disclose", surface="native_ui")\n    _safe_callback(agent.tool_start_callback, "Tool start", tool_call_id, function_name, display_args)\n    require_agent(ref.name, ref.args, agent, task=ref.task_id)'))
    edit("agent/tool_executor.py", lambda s: _replace(s,
        "def _finish_quiet_tool_spinner(agent, spinner, function_name: str, function_args: dict, tool_duration: float, result) -> None:",
        "def _finish_quiet_tool_spinner(agent, spinner, function_name: str, function_args: dict, tool_duration: float, result, *, task_id: str) -> None:"))
    edit("agent/tool_executor.py", lambda s: _entry(s, "_finish_quiet_tool_spinner",
        "from tools.wiki_authority import require_agent\nrequire_agent(function_name, function_args, agent, task=task_id, phase='disclose', surface='native_ui')"))
    edit("agent/tool_executor.py", lambda s: _replace(s,
        "        cute = _get_cute_tool_message_impl(function_name, function_args, tool_duration, result=result)\n        spinner.stop(cute)",
        "        require_agent(function_name, function_args, agent, task=task_id, phase='disclose', surface='native_ui')\n        cute = _get_cute_tool_message_impl(function_name, function_args, tool_duration, result=result)\n        require_agent(function_name, function_args, agent, task=task_id, phase='disclose', surface='native_ui')\n        spinner.stop(cute)"))
    edit("agent/tool_executor.py", lambda s: _replace(s,
        "            _safe_callback(agent.tool_complete_callback, \"Tool complete\",",
        "            require_agent(ref.name, ref.args, agent, task=ref.task_id, phase='disclose', surface='native_ui')\n            _safe_callback(agent.tool_complete_callback, \"Tool complete\","))
    edit("agent/tool_executor.py", lambda s: _replace(s,
        '    if risk_metadata is not None and risk_metadata.get("risk") != "low":\n        _safe_callback(',
        '    if risk_metadata is not None and risk_metadata.get("risk") != "low":\n        require_agent(ref.name, ref.args, agent, task=ref.task_id, phase="disclose", surface="native_ui")\n        _safe_callback('))
    edit("agent/tool_executor.py", lambda s: _tail_guard(s, "_emit_tool_complete_and_risk",
        "require_agent(ref.name, ref.args, agent, task=ref.task_id, phase='disclose', surface='native_ui')"))
    # Stdout is a destination too. Pass the concrete call into both native
    # publishers and recheck after result formatting, before the next print.
    edit("agent/tool_executor.py", lambda s: _replace(s,
        "def _print_tool_completed(agent, index: int, tool_duration: float, result) -> None:",
        "def _print_tool_completed(agent, index: int, tool_duration: float, result, *, ref: _ToolCallRef) -> None:"))
    edit("agent/tool_executor.py", lambda s: _body(s, "_print_tool_completed", """from tools.wiki_authority import require_agent
require_agent(ref.name, ref.args, agent, task=ref.task_id, phase='disclose', surface='native_ui')
if agent.verbose_logging:
    print(f'  ✅ Tool {index} completed in {tool_duration:.2f}s')
    rendered = agent._wrap_verbose('Result: ', result)
else:
    rendered = f'  ✅ Tool {index} completed in {tool_duration:.2f}s - {_preview(result if isinstance(result, str) else str(result), agent.log_prefix_chars)}'
require_agent(ref.name, ref.args, agent, task=ref.task_id, phase='disclose', surface='native_ui')
print(rendered)"""))
    for old, new in [
        ("_print_tool_completed(agent, index, tool_duration, function_result)", "_print_tool_completed(agent, index, tool_duration, function_result, ref=ref)"),
        ("_print_tool_completed(agent, i + 1, tool_duration, _multimodal_text_summary(display_function_result))", "_print_tool_completed(agent, i + 1, tool_duration, _multimodal_text_summary(display_function_result), ref=ref)"),
    ]:
        edit("agent/tool_executor.py", lambda s, a=old, b=new: _replace(s, a, b))
    edit("agent/tool_executor.py", lambda s: _replace(s,
        "            cute_msg = _get_cute_tool_message_impl(ref.name, ref.args, tool_duration, result=display_function_result)\n            agent._safe_print(",
        "            require_agent(ref.name, ref.args, agent, task=ref.task_id, phase='disclose', surface='native_ui')\n            cute_msg = _get_cute_tool_message_impl(ref.name, ref.args, tool_duration, result=display_function_result)\n            require_agent(ref.name, ref.args, agent, task=ref.task_id, phase='disclose', surface='native_ui')\n            agent._safe_print("))
    # Both native callers now supply their concrete task, never ambient context.
    edit("agent/tool_executor.py", lambda s: s.replace(
        "_finish_quiet_tool_spinner(agent, dispatch.spinner, ref.name, ref.args, tool_duration, _spinner_result)",
        "_finish_quiet_tool_spinner(agent, dispatch.spinner, ref.name, ref.args, tool_duration, _spinner_result, task_id=ref.task_id)"))
    for old, new in [
        ('logging.debug("%s callback error: %s", label, callback_error)', 'logging.debug("%s callback failed; exception content omitted", label)'),
        ('logging.debug("Tool progress callback error: %s", callback_error)', 'logging.debug("Tool progress callback failed; exception content omitted")'),
        ('logging.debug("Tool complete callback error: %s", cb_err)', 'logging.debug("Tool complete callback failed; exception content omitted")'),
        ('logging.debug("Tool result metadata callback error: %s", callback_error)', 'logging.debug("Tool result metadata callback failed; exception content omitted")'),
        ('logging.debug("file-mutation verifier record failed: %s", _ver_err)', 'logging.debug("file-mutation verifier record failed; exception content omitted")'),
    ]:
        edit("agent/tool_executor.py", lambda s, a=old, b=new: _replace(s, a, b))
    edit("agent/tool_executor.py", lambda s: _replace(s,
        '            logger.warning("Tool %s returned error (%.2fs): %s", function_name, tool_duration, error_preview(function_result))',
        '            require_agent(ref.name, ref.args, agent, task=ref.task_id, phase="disclose")\n            logger.warning("Tool %s returned error (%.2fs); content retained in authorized result only", function_name, tool_duration)'))
    edit("agent/tool_executor.py", lambda s: _replace(s,
        '            logging.debug("Tool result (%d chars): %s", len(_log_result), _log_result)',
        '            require_agent(ref.name, ref.args, agent, task=ref.task_id, phase="disclose")\n            logging.debug("Tool result retained under current authority (%d chars)", len(_log_result))'))
    edit("agent/tool_executor.py", lambda s: _replace(s,
        "        function_result = dispatch.error_result(tool_error)\n        logger.error(dispatch.error_log, ref.name, tool_error, exc_info=True)",
        "        from tools.wiki_authority import require_agent, safe_tool_failure\n        require_agent(ref.name, ref.args, agent, task=ref.task_id, phase='disclose')\n        function_result = safe_tool_failure()"))
    edit("agent/tool_executor.py", lambda s: _replace(s,
        '            result = f"Error executing tool \'{ref.name}\': {tool_error}"\n            logger.error("_invoke_tool raised for %s: %s", ref.name, tool_error, exc_info=True)',
        "            from tools.wiki_authority import require_agent, safe_tool_failure\n            require_agent(ref.name, ref.args, agent, task=ref.task_id, phase='disclose')\n            result = safe_tool_failure()"))
    edit("agent/tool_executor.py", lambda s: _entry(s, "_dispatch_worker",
        "from tools.wiki_authority import require_agent\nrequire_agent(ref.name, ref.args, self.agent, task=ref.task_id)"))
    edit("agent/tool_executor.py", lambda s: _replace(s,
        "        duration = time.time() - start\n        if not blocked and not dispatched:",
        "        require_agent(ref.name, ref.args, agent, task=ref.task_id, phase='disclose')\n        duration = time.time() - start\n        if not blocked and not dispatched:"))
    edit("agent/tool_executor.py", lambda s: _replace(s,
        '            logger.info("tool %s failed (%.2fs): %s", ref.name, duration, str(result)[:200])',
        '            logger.info("tool %s failed (%.2fs); result content omitted", ref.name, duration)'))
    edit("agent/tool_executor.py", lambda s: _replace(s,
        "        _persisted, display_function_result, risk_metadata = committed\n",
        "        _persisted, display_function_result, risk_metadata = committed\n        from tools.wiki_authority import require_agent\n        require_agent(ref.name, ref.args, agent, task=ref.task_id, phase='disclose')\n"))
    # Direct native invoke/INLINE entry is separate from registry and the batch.
    edit("agent/agent_runtime_helpers.py", lambda s: _entry(s, "invoke_tool",
        "from tools.wiki_authority import require_agent, invoke_agent\nrequire_agent(function_name, function_args, agent, task=effective_task_id)"))
    edit("agent/agent_runtime_helpers.py", lambda s: _replace(s,
        '        logger.debug("tool_request middleware error: %s", _mw_err)',
        "        require_agent(function_name, function_args, agent, task=effective_task_id)\n        logger.debug('tool_request middleware failed; exception content omitted')"))
    edit("agent/agent_runtime_helpers.py", lambda s: _replace(s,
        "    if block_message is not None:\n        result = json.dumps(",
        "    require_agent(function_name, function_args, agent, task=effective_task_id)\n    if block_message is not None:\n        result = json.dumps("))
    edit("agent/agent_runtime_helpers.py", lambda s: _replace(s,
        "            result = inline_executor(agent, next_args, inline_ctx)",
        "            result = invoke_agent(function_name, next_args, lambda actual: inline_executor(agent, actual, inline_ctx), agent, task=effective_task_id)"))
    edit("agent/agent_runtime_helpers.py", lambda s: _replace(s,
        "            return apply_transform_tool_result(\n                agent, function_name=function_name, function_args=call_args, result=result,",
        "            _wiki_result = apply_transform_tool_result(\n                agent, function_name=function_name, function_args=call_args, result=result,"))
    edit("agent/agent_runtime_helpers.py", lambda s: _replace(s,
        "                effective_task_id=effective_task_id, tool_call_id=tool_call_id, duration_ms=duration_ms,\n            )\n    else:",
        "                effective_task_id=effective_task_id, tool_call_id=tool_call_id, duration_ms=duration_ms,\n            )\n            require_agent(function_name, call_args, agent, task=effective_task_id, phase='disclose')\n            return _wiki_result\n    else:"))
    edit("agent/agent_runtime_helpers.py", lambda s: _return_guard(s, "invoke_tool",
        "require_agent(function_name, function_args, agent, task=effective_task_id, phase='disclose')"))
    edit("agent/inline_tool_executors.py", lambda s: _body(s, "_coerced", """def _exec(agent, args: dict, ctx: InlineToolContext) -> Any:
    from tools.wiki_authority import invoke_agent
    actual_args = coerce_tool_args(name, args)
    return invoke_agent(name, actual_args, lambda actual: executor(agent, actual, ctx), agent, task=ctx.effective_task_id)
return _exec"""))
    edit("agent/inline_tool_executors.py", lambda s: _entry(s, "emit_terminal_post_tool_call",
        "from tools.wiki_authority import require_agent\nrequire_agent(function_name, function_args, agent, task=effective_task_id, phase='disclose', surface='tool_observer')"))
    edit("agent/inline_tool_executors.py", lambda s: _body(s, "apply_transform_tool_result", """from tools.wiki_authority import require_agent
require_agent(function_name, function_args, agent, task=effective_task_id, phase='disclose', surface='tool_transform')
transformed = result
try:
    from model_tools import _CallIds, _apply_transform_tool_result_hook
    transformed = _apply_transform_tool_result_hook(function_name, function_args, result, duration_ms, _CallIds(**tool_hook_ids(agent, effective_task_id, tool_call_id)))
except Exception:
    pass
require_agent(function_name, function_args, agent, task=effective_task_id, phase='disclose', surface='tool_return')
return transformed"""))
    # A native observer/formatter can itself throw or cancel after seeing a
    # legitimate result. Its raw exception must not escape via an outer native
    # logger/traceback. Existing handled failures keep their metadata and native
    # behavior; unhandled failures stop, with content-free uncertainty.
    for path, names in {
        "run_agent.py": ("_append_guardrail_observation",),
        "hermes_cli/observability/shared_metrics_efficiency.py": ("note_tool_result", "record_tool_batch"),
        "hermes_cli/observability/shared_metrics_harness.py": ("_enabled", "_record", "record_guardrail_decision", "observe_tool_outcome"),
        "hermes_cli/observability/relay_shared_metrics.py": ("_guarded", "observe_lifecycle", "enabled", "_get_runtime"),
        "hermes_cli/kanban_db_dispatch.py": ("_default_spawn", "_set_worker_pid"),
        "tools/kanban_tools.py": ("register_current_worker_from_env",),
        "model_tools.py": ("handle_function_call", "_apply_request_middleware", "_pre_dispatch_guards", "_emit_post_tool_call_hook", "_apply_transform_tool_result_hook"),
        "agent/agent_runtime_helpers.py": ("invoke_tool",),
        "agent/inline_tool_executors.py": ("emit_terminal_post_tool_call", "apply_transform_tool_result"),
        "agent/tool_executor.py": ("_safe_callback", "_begin_tool_execution", "_commit_tool_result", "_emit_tool_complete_and_risk", "_publish_sequential_result", "_append_batch_results", "_finish_quiet_tool_spinner", "_flush_session_db_after_tool_progress", "_record_persisted_path_for_stub"),
    }.items():
        for name in names:
            edit(path, lambda s, n=name: _content_free_boundary(s, n))
    # No Codex delegation/callback is admitted in this public control. Registry
    # callbacks still require fresh task context; lost ContextVars fail closed.
    # Native runtime vendoring is deterministic. The policy bootstrap has no
    # default registry, file loader or provider grants; the host supplies it.
    for original, target in [("native_projection", "wiki_native_projection"), ("native_host", "wiki_native_host"), ("native_host_wire", "wiki_native_host_wire"), ("native_startup_guard", "wiki_native_startup_guard")]:
        vendored = (KIT / ("wiki_core/" + original + ".py")).read_text()
        for old, new in [("runtime_authority", "wiki_authority"), ("native_projection", "wiki_native_projection"), ("native_host_wire", "wiki_native_host_wire"), ("native_host", "wiki_native_host"), ("native_startup_guard", "wiki_native_startup_guard")]:
            vendored = vendored.replace("from ." + old + " import", "from tools." + new + " import")
        changes["tools/" + target + ".py"] = ("", vendored)
    changes["tools/wiki_authority.py"] = ("", (KIT / "wiki_core/runtime_authority.py").read_text())
    for _, text in changes.values():
        ast.parse(text)
    return changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.resolve().is_relative_to(args.source.resolve()):
        parser.error("output must be outside the Hermes source checkout")
    changes = candidate(args.source)
    patch = "".join("".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
        fromfile="a/" + path if before else "/dev/null", tofile="b/" + path)) for path, (before, after) in changes.items())
    args.output.write_text(patch)
    print(json.dumps({"base": BASE, "files": len(changes), "patch_sha256": hashlib.sha256(patch.encode()).hexdigest(), "applied": False}))


if __name__ == "__main__":
    main()
