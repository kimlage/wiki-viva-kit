"""Adversarial independent-review regressions on real entry bodies, synthetic data.

No Hermes module, account, credential or running service is imported/called.
"""
from contextvars import Context, copy_context
from dataclasses import replace
import json
import os
from pathlib import Path
from types import SimpleNamespace as NS
import threading
import time
import contextlib
import traceback
from concurrent.futures import ThreadPoolExecutor

import pytest

from wiki_core import runtime_authority as authority
from test_hermes_kernel_candidate import candidate, host, function

CANARY = "SYNTHETIC-RESULT-MUST-NOT-ESCAPE"


def source(candidate, path):
    if path in candidate:
        return candidate[path][1]
    # RED phase also exercises the omitted, unchanged native entry.
    return (Path(os.environ["WIKI_HERMES_KERNEL_SOURCE"]) / path).read_text()


def allow(host, tool="memory", args=None):
    backend, gate = host
    backend.op = replace(backend.op, tool=tool, arguments_sha256=authority.sha(args or backend.args))
    backend.state = replace(backend.state, operations=(backend.op,))
    gate.admit("session-a", "task")
    return backend, gate


@pytest.fixture
def inline(candidate, host, monkeypatch):
    backend, gate = allow(host)
    events = []
    agent = NS(session_id="session-a", _tool_guardrails=NS(before_call=lambda *a: NS(allows_execution=True)),
               _context_engine_tool_names=set(), _memory_manager=None)
    lane = NS(rewrite=None, request_rewrite=None, execution_rewrite=None, after_handler=lambda: None)

    def handler(agent, args, ctx):
        events.append(("handler", dict(args)))
        lane.after_handler()
        return CANARY

    native = source(candidate, "agent/tool_executor.py")
    resolve = function(native, "_resolve_sequential_dispatch", INLINE_TOOL_EXECUTORS={"memory": handler},
        InlineToolContext=lambda **kw: NS(**kw),
        _SequentialDispatch=lambda execute=None, **kw: NS(execute=execute, **kw))
    make_ref = lambda name, args, task, call, trace: NS(name=name, args=args, task_id=task, call_id=call, trace=trace)
    ref = make_ref("memory", dict(backend.args), "task", "call-a", [])
    dispatch = resolve(agent, ref, [])
    monkeypatch.setitem(__import__('sys').modules, "agent.terminal_approval_batch", NS(
        prepare_current_terminal=lambda *a: None, bind_prepared_dispatch=lambda cb: cb))
    namespaces = dict(
        _pre_tool_block=lambda agent, ref: (None, lane.rewrite or ref.args),
        _context_pruned_argument_paths=lambda *a: [],
        _begin_tool_execution=lambda *a: None,
        _run_with_activity_heartbeat=lambda agent, tool, cb: cb(),
    )
    dispatch_once = function(native, "_dispatch_authorized_once", **namespaces)

    def call():
        state = NS(args=dict(backend.args), blocked=False, dispatched=False)
        current = make_ref("memory", state.args, "task", "call-a", [])
        return dispatch_once(agent, state, current, execute=dispatch.execute, scope_block=None,
                             display_index=1, begin_execution=None, authorization_gate=None)

    monkeypatch.setitem(__import__('sys').modules, "agent.dialogue_policy", NS(require_tools_allowed=lambda *a: None))
    middleware = NS(
        apply_tool_request_middleware=lambda name, args, **kw: NS(payload=lane.request_rewrite or args, trace=[]),
        run_tool_execution_middleware=lambda name, args, cb, **kw: cb(lane.execution_rewrite or args))
    monkeypatch.setitem(__import__('sys').modules, "hermes_cli.middleware", middleware)
    relay = NS(execute=lambda name, args, cb, **kw: (cb(args), args))
    monkeypatch.setitem(__import__('sys').modules, "agent", NS(relay_tools=relay))
    run_pipeline = function(native, "_run_agent_tool_execution_middleware", threading=threading,
        _ManagedToolResult=lambda **kw: NS(**kw), _ToolCallRef=make_ref,
        _dispatch_authorized_once=dispatch_once, tool_hook_ids=lambda *a: {})
    lane.call = call
    lane.run_pipeline = run_pipeline
    lane.pipeline = lambda: run_pipeline(agent, function_name="memory", function_args=dict(backend.args),
        effective_task_id="task", tool_call_id="call-a", execute=dispatch.execute)
    lane.agent, lane.events, lane.backend, lane.gate = agent, events, backend, gate
    return lane


@pytest.fixture
def native_invoke(candidate, inline, monkeypatch):
    """Real concurrent invocation/INLINE helper bodies with metadata-only stubs."""
    module = source(candidate, "agent/inline_tool_executors.py")
    observations = []
    changed = NS(coerce=None, after_hook=lambda: None)
    def observer(**kw):
        observations.append(("hook", kw["result"]))
        changed.after_hook()
    monkeypatch.setitem(__import__('sys').modules, "model_tools", NS(
        _emit_post_tool_call_hook=observer, _CallIds=lambda **kw: NS(**kw),
        _apply_transform_tool_result_hook=lambda *a: observations.append(("transform", a[2])) or a[2]))
    ids = lambda agent, task, call: {"session_id": agent.session_id, "task_id": task}
    emit = function(module, "emit_terminal_post_tool_call", tool_hook_ids=ids)
    transform = function(module, "apply_transform_tool_result", tool_hook_ids=ids)
    def handler(agent, args, ctx):
        inline.events.append(("handler", dict(args)))
        inline.after_handler()
        return CANARY
    coerce = function(module, "_coerced", coerce_tool_args=lambda name, args: changed.coerce or args)
    resolve = function(module, "resolve_invoke_tool_executor", INLINE_TOOL_EXECUTORS={"memory": coerce("memory", handler)},
        INVOKE_TOOL_PRE_MEMORY_MANAGER_NAMES=frozenset({"memory"}))
    monkeypatch.setitem(__import__('sys').modules, "agent.inline_tool_executors", NS(
        InlineToolContext=lambda **kw: NS(**kw), apply_transform_tool_result=transform,
        emit_terminal_post_tool_call=emit, resolve_invoke_tool_executor=resolve, tool_hook_ids=ids))
    invoke = function(source(candidate, "agent/agent_runtime_helpers.py"), "invoke_tool", time=time,
        logger=NS(debug=lambda *a: None), _pre_tool_block_message=lambda *a: (None, a[2]))
    inline.agent._invoke_tool = lambda name, args, task, call, **kw: invoke(inline.agent, name, args, task, call, **kw)
    changed.invoke = lambda **kw: invoke(inline.agent, "memory", dict(inline.backend.args), "task", "call-a", **kw)
    changed.inline, changed.observations, changed.native = inline, observations, invoke
    return changed


def test_native_direct_inline_and_coercion_keep_the_final_boundary(native_invoke):
    assert native_invoke.invoke(skip_tool_execution_middleware=True) == CANARY
    assert [x[0] for x in native_invoke.observations] == ["hook", "transform"]
    native_invoke.coerce = {**native_invoke.inline.backend.args, "resource": "another-resource"}
    with pytest.raises(authority.AuthorityDenied):
        native_invoke.invoke(skip_tool_execution_middleware=True)
    assert len(native_invoke.inline.events) == 1


def test_native_hook_revocation_prevents_transform_and_return(native_invoke):
    native_invoke.after_hook = lambda: setattr(native_invoke.inline.backend, "state", replace(native_invoke.inline.backend.state, revoked=True))
    with pytest.raises(authority.AuthorityDenied):
        native_invoke.invoke(skip_tool_execution_middleware=True)
    assert [x[0] for x in native_invoke.observations] == ["hook"]


@pytest.mark.parametrize("change", [{"revoked": True}, {"lease_until": 99}])
def test_real_concurrent_worker_revalidates_each_call_and_its_return(candidate, native_invoke, change):
    lane = native_invoke.inline
    log = []
    worker = function(source(candidate, "agent/tool_executor.py"), "_dispatch_worker", time=time, contextlib=contextlib,
        _run_agent_tool_execution_middleware=lane.run_pipeline,
        _BatchAbandoned=type("Abandoned", (BaseException,), {}),
        _ToolOutcome=lambda ref, result, duration, error, blocked: NS(result=result),
        _detect_tool_failure=lambda *a: (False, None),
        logger=NS(info=lambda *a: log.append(a), error=lambda *a, **kw: log.append(a)))
    ref = NS(name="memory", args=lane.backend.args, task_id="task", call_id="call-a", trace=[],
             middleware_kwargs=lambda: dict(function_name="memory", function_args=lane.backend.args,
                 effective_task_id="task", tool_call_id="call-a", middleware_trace=[]))
    start = NS(advance=lambda cb=None: cb() if cb else None)
    batch = NS(agent=lane.agent, messages=[], authorization_gate=None)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(copy_context().run, worker, batch, 0, ref, None, start)
        assert first.result().result == CANARY
        lane.backend.state = replace(lane.backend.state, **change)
        second = executor.submit(copy_context().run, worker, batch, 1, ref, None, start)
        with pytest.raises(authority.AuthorityDenied): second.result()
    assert len(lane.events) == 1
    assert CANARY not in str(log)


@pytest.mark.parametrize("handler_error", [ValueError(CANARY), TimeoutError(CANARY)])
def test_allowed_registry_error_is_content_free_and_never_authorizes_retry(candidate, host, handler_error):
    backend, gate = allow(host, "read_public")
    def fail(args): raise handler_error
    entry = NS(handler=fail, is_async=False)
    registry = NS(get_entry=lambda *a, **kw: entry, _normalize_handler_result=lambda name, value: value)
    dispatch = function(candidate["tools/registry.py"][1], "dispatch", _kwargs_accepted_by=lambda fn, kw: {})
    result = json.loads(dispatch(registry, "read_public", backend.args, session_id="session-a", task_id="task"))
    assert result == {"error": "tool_execution_failed", "effect_disposition": "unknown", "retry_authorized": False}
    assert CANARY not in str(result)


def test_read_permission_does_not_grant_observer_audience(candidate, host):
    backend, gate = allow(host)
    backend.op = replace(backend.op, disclosure_surfaces=("tool_return",))
    backend.state = replace(backend.state, operations=(backend.op,))
    gate.admit("session-a", "task")
    observed = []
    emit = function(source(candidate, "agent/tool_executor.py"), "emit_post",
                    _emit_terminal_post_tool_call=lambda *a, **kw: observed.append(kw))
    ref = NS(name="memory", args=backend.args, task_id="task", call_id="call-a", trace=[])
    with pytest.raises(authority.AuthorityDenied, match="audience_denied"):
        emit(ref, NS(session_id="session-a"), CANARY)
    assert observed == []


@pytest.mark.parametrize("marker", ["success", "error", "timeout", "cancelled"])
def test_actual_commit_revalidates_before_observation_storage_and_model(candidate, host, monkeypatch, marker):
    backend, gate = allow(host)
    events = []
    fake_log = NS(warning=lambda *a, **kw: events.append(("log", a)), info=lambda *a, **kw: events.append(("log", a)), debug=lambda *a, **kw: events.append(("log", a)))
    monkeypatch.setitem(__import__('sys').modules, "hermes_cli.observability.shared_metrics_harness", NS(observe_tool_outcome=lambda *a: None))
    agent = NS(session_id="session-a", verbose_logging=True,
        _append_guardrail_observation=lambda name, args, value, **kw: events.append(("observe", value)) or value,
        _record_file_mutation_result=lambda *a, **kw: events.append(("record", a)),
        _touch_activity=lambda *a: None, _subdirectory_hints=NS(check_tool_call=lambda *a: None),
        _tool_result_content_for_active_model=lambda name, value: value, tool_result_metadata_callback=None,
        tool_progress_callback=lambda *a, **kw: events.append(("callback", kw)))
    ref = NS(name="memory", args=backend.args, task_id="task", call_id="call-a")
    commit = function(source(candidate, "agent/tool_executor.py"), "_commit_tool_result", logger=fake_log, logging=fake_log,
        _is_multimodal_tool_result=lambda *a: False,
        maybe_persist_tool_result=lambda **kw: events.append(("persist", kw["content"])) or kw["content"],
        get_active_env=lambda *a: None, _record_persisted_path_for_stub=lambda *a: None,
        note_tool_result=lambda *a: events.append(("note", a)), make_tool_result_message=lambda name, value, call, **kw: {"content": value},
        _flush_session_db_after_tool_progress=lambda *a, **kw: True, _safe_callback=lambda cb, label, *a, **kw: cb(*a, **kw),
        _LARGE_TOOL_RESULT_TRIM_CHARS=1000000)
    backend.state = replace(backend.state, revoked=True)
    messages = []
    with pytest.raises(authority.AuthorityDenied):
        commit(agent, messages, ref, CANARY, budget=None, tool_duration=1, is_error=marker!="success",
               blocked=False, effect_disposition="unknown" if marker in {"timeout", "cancelled"} else None, observed=True)
    assert events == [] and messages == []


def test_inline_legitimate_call_still_uses_the_native_handler(inline):
    assert inline.call() == CANARY
    assert inline.events == [("handler", inline.backend.args)]


@pytest.mark.parametrize("rewrite_at", ["rewrite", "request_rewrite", "execution_rewrite"])
@pytest.mark.parametrize("field", ["query", "resource", "destination"])
def test_inline_rewrites_are_checked_at_effective_handler_boundary(inline, rewrite_at, field):
    setattr(inline, rewrite_at, {**inline.backend.args, field: "another-resource-or-recipient"})
    with pytest.raises(authority.AuthorityDenied):
        inline.pipeline()
    assert inline.events == []


@pytest.mark.parametrize("change", [{"revoked": True}, {"lease_until": 99}, {"revision": "policy-r2"}])
def test_second_inline_call_revalidates_after_first_call(inline, change):
    assert inline.call() == CANARY
    inline.backend.state = replace(inline.backend.state, **change)
    with pytest.raises(authority.AuthorityDenied):
        inline.call()
    assert len(inline.events) == 1


def test_inline_handler_revocation_blocks_result_before_return(inline):
    inline.after_handler = lambda: setattr(inline.backend, "state", replace(inline.backend.state, revoked=True))
    with pytest.raises(authority.AuthorityDenied):
        inline.call()
    assert len(inline.events) == 1


def test_sequential_publisher_blocks_canary_before_hook_transform_or_persistence(candidate, host):
    backend, gate = allow(host)
    events = []
    native = source(candidate, "agent/tool_executor.py")
    agent = NS(session_id="session-a", verbose_logging=False)
    ref = NS(name="memory", args=backend.args, task_id="task", call_id="call-a", trace=[],
             emit_post=lambda *a, **kw: events.append(("hook", a)))
    managed = NS(args=backend.args, middleware_trace=[], result=CANARY, blocked=False)
    publish = function(native, "_publish_sequential_result", _ToolTimeoutResult=type("Timeout", (str,), {}),
        _ToolCancelledResult=type("Cancelled", (str,), {}),
        apply_transform_tool_result=lambda agent, **kw: events.append(("transform", kw)) or CANARY,
        _detect_tool_failure=lambda *a: (False, None),
        _commit_tool_result=lambda *a, **kw: events.append(("persist", a)) or None,
        _multimodal_text_summary=str)
    backend.state = replace(backend.state, revoked=True)
    with pytest.raises(authority.AuthorityDenied):
        publish(agent, [], ref, managed, tool_duration=1, index=1, budget=None, transform_applied=False)
    assert events == []


@pytest.mark.parametrize("change", ["revoked", "lease", "unavailable"])
def test_direct_registry_error_never_leaks_canary_to_output_or_logger(candidate, host, monkeypatch, change):
    backend, gate = allow(host, "read_public")
    logs = []
    def fail(args):
        if change == "revoked": backend.state = replace(backend.state, revoked=True)
        elif change == "lease": backend.state = replace(backend.state, lease_until=99)
        else: backend.failure = True
        raise ValueError(CANARY)
    entry = NS(handler=fail, is_async=False)
    registry = NS(get_entry=lambda *a, **kw: entry, _normalize_handler_result=lambda name, value: value)
    monkeypatch.setitem(__import__('sys').modules, "model_tools", NS(_sanitize_tool_error=str))
    dispatch = function(candidate["tools/registry.py"][1], "dispatch", _kwargs_accepted_by=lambda fn, kw: {},
        tool_error=lambda text: {"error": text}, _bound_error_text=str,
        logger=NS(exception=lambda *a, **kw: logs.append((a, kw)), error=lambda *a, **kw: logs.append((a, kw))))
    try:
        result = copy_context().run(dispatch, registry, "read_public", backend.args, session_id="session-a", task_id="task")
    except authority.AuthorityDenied as denied:
        assert CANARY not in "".join(traceback.format_exception(denied))
        result = "authority_denied"
    assert CANARY not in str(result)
    assert CANARY not in str(logs)


def test_registry_revocation_blocks_normalizer_and_callback_observers(candidate, host):
    backend, gate = allow(host, "read_public")
    normalizations = []
    def handler(args):
        backend.state = replace(backend.state, revoked=True)
        return CANARY
    registry = NS(get_entry=lambda *a, **kw: NS(handler=handler, is_async=False),
                  _normalize_handler_result=lambda name, result: normalizations.append(result) or result)
    dispatch = function(candidate["tools/registry.py"][1], "dispatch", _kwargs_accepted_by=lambda fn, kw: {})
    with pytest.raises(authority.AuthorityDenied):
        copy_context().run(dispatch, registry, "read_public", backend.args, session_id="session-a", task_id="task")
    assert normalizations == []


@pytest.mark.parametrize("wrong", [False, True, "task", "contextless"])
def test_model_checks_concrete_agent_even_with_inherited_nonempty_context(candidate, host, monkeypatch, wrong):
    backend, gate = host
    request = {"messages": ["synthetic context"]}
    agent = NS(session_id="session-b" if wrong is True else "session-a", provider="same-provider", base_url="https://model.example.test",
               model="same-model", api_mode="chat_completions", _interruptible_api_call=lambda *a: "ok")
    args = {"provider": agent.provider, "base_url": agent.base_url, "model": agent.model, "request": request}
    allow(host, "model_call", args)
    calls = []
    monkeypatch.setitem(__import__('sys').modules, "agent.dialogue_policy", NS(dialogue_request=lambda agent, args: args))
    monkeypatch.setitem(__import__('sys').modules, "agent", NS(relay_llm=NS(execute=lambda *a, **kw: calls.append(a) or "ok")))
    invoke = function(candidate["agent/turn_api_call.py"][1], "_perform_api_call", agent=agent,
        effective_task_id="task-b" if wrong == "task" else "task", _use_streaming=False, api_request_id="call-a", retry_count=0)
    if wrong:
        context = Context() if wrong == "contextless" else copy_context()
        with pytest.raises(authority.AuthorityDenied): context.run(invoke, request)
        assert calls == []
    else:
        assert invoke(request) == "ok" and len(calls) == 1


@pytest.mark.parametrize("wrong", [False, True, "task", "contextless", "missing-agent"])
def test_relay_checks_concrete_agent_task_before_deriving_sender_home(candidate, host, wrong):
    backend, gate = host
    args = {"target": "reviewer-a", "message": "synthetic permitted summary"}
    allow(host, "message_agent", args)
    homes = []
    class SenderResolved(Exception): pass
    def home(agent):
        homes.append(agent.session_id)
        raise SenderResolved()
    relay = function(candidate["tools/bot_mode_dm.py"][1], "message_agent_tool", _agent_home=home)
    agent = NS(session_id="session-b" if wrong is True else "session-a") if wrong != "missing-agent" else None
    if wrong:
        context = Context() if wrong == "contextless" else copy_context()
        with pytest.raises(authority.AuthorityDenied):
            context.run(relay, **args, task_id="task-b" if wrong is True or wrong == "task" else "task", agent=agent)
        assert homes == []
    else:
        with pytest.raises(SenderResolved): relay(**args, task_id="task", agent=agent)
        assert homes == ["session-a"]


def test_model_revalidates_concrete_agent_after_request_preflight(candidate, host, monkeypatch):
    backend, gate = host
    request = {"messages": ["synthetic"]}
    agent = NS(session_id="session-a", provider="same", base_url="https://model.example.test", model="same", api_mode="chat_completions")
    allow(host, "model_call", {"provider":agent.provider,"base_url":agent.base_url,"model":agent.model,"request":request})
    calls = []
    def preflight(agent, args):
        agent.session_id = "session-b"
        return args
    monkeypatch.setitem(__import__('sys').modules, "agent.dialogue_policy", NS(dialogue_request=preflight))
    monkeypatch.setitem(__import__('sys').modules, "agent", NS(relay_llm=NS(execute=lambda *a, **kw: calls.append(a))))
    invoke = function(candidate["agent/turn_api_call.py"][1], "_perform_api_call", agent=agent,
        effective_task_id="task", _use_streaming=False, api_request_id="call-a", retry_count=0)
    with pytest.raises(authority.AuthorityDenied): invoke(request)
    assert calls == []


def test_cancellation_keeps_native_control_flow_without_exception_body(candidate, host):
    from asyncio import CancelledError
    backend, gate = allow(host, "read_public")
    for error in (KeyboardInterrupt(CANARY), CancelledError(CANARY)):
        def stop(args): raise error
        entry = NS(handler=stop, is_async=False)
        registry = NS(get_entry=lambda *a, **kw: entry)
        dispatch = function(candidate["tools/registry.py"][1], "dispatch", _kwargs_accepted_by=lambda fn, kw: {})
        with pytest.raises(type(error)) as caught:
            dispatch(registry, "read_public", backend.args, session_id="session-a", task_id="task")
        assert caught.value.args == ()


@pytest.fixture
def publication(candidate, host, monkeypatch):
    """The real native publishers, completion callbacks and stdout formatter."""
    backend, gate = allow(host)
    native = source(candidate, "agent/tool_executor.py")
    events = []
    state = NS(revoke_at=None, callback_error=False)
    def callback(label, value):
        events.append((label, value))
        if state.revoke_at == label:
            backend.state = replace(backend.state, revoked=True)
        if isinstance(state.callback_error, BaseException):
            raise state.callback_error
        if state.callback_error:
            raise ValueError(CANARY)
    agent = NS(session_id="session-a", quiet_mode=False, verbose_logging=True,
        tool_progress_mode="all", log_prefix_chars=1000, _wrap_verbose=lambda label, value: label + value,
        tool_complete_callback=lambda *a: callback("complete", a[-1]),
        tool_progress_callback=lambda *a, **kw: callback("risk", kw["risk_metadata"]),
        _should_emit_quiet_tool_messages=lambda: False, _safe_print=print)
    ref = NS(name="memory", args=backend.args, task_id="task", call_id="call-a", trace=[], emit_post=lambda *a, **kw: None)
    safe_callback = function(native, "_safe_callback", logging=__import__('logging'))
    emit = function(native, "_emit_tool_complete_and_risk", _redact_tool_args_for_display=lambda name, args: args,
        _safe_callback=safe_callback)
    printer = function(native, "_print_tool_completed", _preview=lambda value, limit: value[:limit])
    def commit(*a, **kw):
        return CANARY, CANARY, {"risk": "high", "detail": CANARY}
    ns = dict(_commit_tool_result=commit, _emit_tool_complete_and_risk=emit, _print_tool_completed=printer,
        _tool_progress_enabled=lambda agent: True, _multimodal_text_summary=str)
    monkeypatch.setitem(__import__('sys').modules, "agent.terminal_approval_batch", NS(mark_batch_outcome=lambda value: None))
    sequential = function(native, "_publish_sequential_result", **ns,
        _ToolTimeoutResult=type("Timeout", (str,), {}), _ToolCancelledResult=type("Cancelled", (str,), {}),
        _detect_tool_failure=lambda *a: (False, None))
    concurrent = function(native, "_append_batch_results", **ns,
        _get_cute_tool_message_impl=lambda *a, **kw: callback("cute", kw["result"]) or CANARY)
    state.sequential = lambda: sequential(agent, [], ref,
        NS(args=backend.args, middleware_trace=[], result=CANARY, blocked=False),
        tool_duration=1, index=1, budget=None, transform_applied=True)
    state.concurrent = lambda: concurrent(agent, [], "task", NS(parsed_calls=[NS(parse_error=None)],
        results=[NS(ref=ref, result=CANARY, duration=1, is_error=False, blocked=False)]), None)
    state.agent, state.events, state.backend = agent, events, backend
    return state


@pytest.mark.parametrize("lane", ["sequential", "concurrent"])
@pytest.mark.parametrize("revoke", [False, True])
@pytest.mark.parametrize("callback_error", [False, True])
def test_native_publication_rechecks_after_completion_before_next_destination(publication, capsys, caplog, lane, revoke, callback_error):
    publication.revoke_at = "complete" if revoke else None
    publication.callback_error = callback_error
    caplog.set_level(__import__('logging').DEBUG)
    if revoke:
        with pytest.raises(authority.AuthorityDenied): getattr(publication, lane)()
    else:
        assert getattr(publication, lane)() is True
    assert [x[0] for x in publication.events] == (["complete"] if revoke else ["complete", "risk"])
    # Concurrent stdout occurs before completion, sequential stdout after it.
    output = capsys.readouterr().out
    assert (CANARY in output) is (not revoke or lane == "concurrent")
    assert CANARY not in caplog.text and not any(record.exc_info for record in caplog.records)


def test_native_concurrent_quiet_format_callback_cannot_authorize_stdout(publication, capsys):
    publication.agent._should_emit_quiet_tool_messages = lambda: True
    publication.revoke_at = "cute"
    with pytest.raises(authority.AuthorityDenied): publication.concurrent()
    assert publication.events == [("cute", CANARY)]
    assert CANARY not in capsys.readouterr().out


@pytest.fixture
def native_commit(candidate, host, monkeypatch):
    backend, gate = allow(host)
    events = []
    state = NS(revoke_at=None, error_at=None, error=None, result=CANARY)
    def observe(label, value):
        events.append((label, value))
        if state.revoke_at == label: backend.state = replace(backend.state, revoked=True)
        if state.error_at == label: raise state.error
        return value
    log = NS(warning=lambda *a, **kw: None, info=lambda *a, **kw: None, debug=lambda *a, **kw: None)
    monkeypatch.setitem(__import__('sys').modules, "hermes_cli.observability.shared_metrics_harness", NS(observe_tool_outcome=lambda *a: None))
    agent = NS(session_id="session-a", verbose_logging=False,
        _append_guardrail_observation=lambda name, args, value, **kw: observe("guardrail", value),
        _record_file_mutation_result=lambda name, args, value, *a, **kw: observe("mutation", value),
        _touch_activity=lambda *a: None, _subdirectory_hints=NS(check_tool_call=lambda *a: None),
        _tool_result_content_for_active_model=lambda name, value: observe("model-content", value),
        tool_result_metadata_callback=lambda *a: observe("metadata", a[-1]) and None,
        tool_progress_callback=lambda *a, **kw: observe("progress", kw["result"]))
    ref = NS(name="memory", args=backend.args, task_id="task", call_id="call-a")
    commit = function(source(candidate, "agent/tool_executor.py"), "_commit_tool_result", logger=log, logging=log,
        _is_multimodal_tool_result=lambda *a: False,
        maybe_persist_tool_result=lambda **kw: observe("persist", kw["content"]),
        get_active_env=lambda *a: None, _record_persisted_path_for_stub=lambda agent, call, value: observe("stub", value),
        note_tool_result=lambda *a: observe("note", a[-1]),
        make_tool_result_message=lambda name, value, call, **kw: observe("message", value) and {"content": value},
        _flush_session_db_after_tool_progress=lambda agent, messages, **kw: observe("flush", messages[-1]["content"]) and True,
        _safe_callback=lambda cb, label, *a, **kw: cb(*a, **kw),
        _redact_tool_args_for_display=lambda name, args: args, _LARGE_TOOL_RESULT_TRIM_CHARS=1000000)
    messages = []
    state.call = lambda: commit(agent, messages, ref, state.result, budget=None, tool_duration=1,
        is_error=False, blocked=False, effect_disposition=None, observed=True)
    state.backend, state.gate, state.events, state.messages, state.agent = backend, gate, events, messages, agent
    return state


def test_native_commit_store_permission_does_not_grant_guardrail_observer(native_commit):
    backend = native_commit.backend
    backend.op = replace(backend.op, disclosure_surfaces=("native_store", "tool_return"))
    backend.state = replace(backend.state, operations=(backend.op,))
    native_commit.gate.admit("session-a", "task")
    with pytest.raises(authority.AuthorityDenied, match="audience_denied"): native_commit.call()
    assert native_commit.events == [] and native_commit.messages == []


@pytest.mark.parametrize("revoke_at,next_destination", [
    ("guardrail", "mutation"), ("mutation", "persist"), ("persist", "stub"),
    ("note", "model-content"), ("model-content", "message"), ("metadata", "flush"), ("flush", "progress"), ("progress", "return"),
])
def test_native_commit_rechecks_between_result_destinations(native_commit, revoke_at, next_destination):
    native_commit.revoke_at = revoke_at
    with pytest.raises(authority.AuthorityDenied): native_commit.call()
    labels = [x[0] for x in native_commit.events]
    assert labels[-1] == revoke_at and next_destination not in labels


def test_native_commit_allowed_destinations_keep_original_order(native_commit):
    assert native_commit.call()[:2] == (CANARY, CANARY)
    assert [x[0] for x in native_commit.events] == ["guardrail", "mutation", "persist", "stub", "note",
        "model-content", "message", "metadata", "flush", "progress"]
    assert native_commit.messages == [{"content": CANARY}]


@pytest.mark.parametrize("entry", ["request", "pre_hook", "edit_approval", "native_request"])
@pytest.mark.parametrize("change", ["valid", "revoked", "lease", "unavailable"])
def test_native_request_and_pre_hook_errors_never_log_exception_contents(candidate, host, native_invoke,
        monkeypatch, caplog, capsys, entry, change):
    import logging
    backend, gate = allow(host)
    error_canary = "SYNTHETIC-MIDDLEWARE-ERROR-MUST-NOT-ESCAPE"
    reached = []
    def fail(*a, **kw):
        if change == "revoked": backend.state = replace(backend.state, revoked=True)
        elif change == "lease": backend.state = replace(backend.state, lease_until=99)
        elif change == "unavailable": backend.failure = True
        raise ValueError(error_canary)
    middleware = NS(apply_tool_request_middleware=fail)
    monkeypatch.setitem(__import__('sys').modules, "hermes_cli.middleware", middleware)
    monkeypatch.setitem(__import__('sys').modules, "hermes_cli.plugins", NS(
        _dispatch_pre_tool_call_hooks=fail if entry == "pre_hook" else lambda *a, **kw: (None, None)))
    monkeypatch.setitem(__import__('sys').modules, "acp_adapter.edit_approval", NS(
        maybe_require_edit_approval=fail if entry == "edit_approval" else lambda *a: reached.append("approval") or None))
    log = logging.getLogger("synthetic-native-test")
    ids = NS(session_id="session-a", task_id="task", hook_kwargs=lambda: {})
    native = source(candidate, "model_tools.py")
    if entry == "request":
        call = lambda: function(native, "_apply_request_middleware", logger=log)("memory", backend.args, ids, [])
    elif entry == "native_request":
        native_invoke.native.__globals__["logger"] = log
        call = lambda: native_invoke.invoke(skip_tool_execution_middleware=True)
    else:
        call = lambda: function(native, "_pre_dispatch_guards", logger=log, tool_error=lambda value: value)(
            "memory", backend.args, False, ids, [])
    caplog.set_level(logging.DEBUG, logger=log.name)
    if change == "valid":
        result = call()
        assert error_canary not in str(result)
        assert caplog.records, "safe failure metadata must remain observable"
    else:
        with pytest.raises(authority.AuthorityDenied) as caught: call()
        assert error_canary not in "".join(traceback.format_exception(caught.value))
        assert reached == []
    assert error_canary not in caplog.text
    assert not any(record.exc_info for record in caplog.records)
    assert error_canary not in str(capsys.readouterr())


@pytest.mark.parametrize("revoke_at", [None, "redact", "wrap", "progress", "start"])
def test_native_begin_rechecks_between_argument_callbacks_and_stdout(candidate, host, capsys, revoke_at):
    args = {"resource": "source", "query": CANARY}
    backend, gate = allow(host, "memory", args)
    backend.args = args
    events = []
    def step(label, value):
        events.append(label)
        if label == revoke_at: backend.state = replace(backend.state, revoked=True)
        return value
    agent = NS(session_id="session-a", verbose_logging=True, log_prefix_chars=1000,
        _wrap_verbose=lambda label, value: step("wrap", label + value),
        _touch_activity=lambda *a: None, _checkpoint_mgr=NS(enabled=False),
        tool_progress_callback=lambda *a: step("progress", None), tool_start_callback=lambda *a: step("start", None))
    ref = NS(name="memory", args=backend.args, task_id="task", call_id="call-a")
    begin = function(source(candidate, "agent/tool_executor.py"), "_begin_tool_execution", json=json,
        _tool_progress_enabled=lambda agent: True, _set_worker_activity_callback=lambda agent: None,
        _redact_tool_args_for_display=lambda name, args: step("redact", args),
        _build_tool_preview=lambda name, args: "preview", _safe_callback=lambda cb, label, *a: cb(*a))
    if revoke_at:
        with pytest.raises(authority.AuthorityDenied): begin(agent, ref, 1)
        assert events[-1] == revoke_at
    else:
        begin(agent, ref, 1)
        assert events == ["redact", "wrap", "progress", "start"]
    assert (CANARY in capsys.readouterr().out) is (revoke_at not in {"redact", "wrap"})


@pytest.mark.parametrize("entry", ["persisted_stub", "session_flush"])
@pytest.mark.parametrize("change", ["valid", "revoked", "lease", "unavailable"])
def test_native_persistence_error_helpers_keep_only_safe_metadata(candidate, host, monkeypatch, caplog, entry, change):
    import logging
    backend, gate = allow(host)
    def fail(*a, **kw):
        if change == "revoked": backend.state = replace(backend.state, revoked=True)
        elif change == "lease": backend.state = replace(backend.state, lease_until=99)
        elif change == "unavailable": backend.failure = True
        raise ValueError(CANARY)
    log = logging.getLogger("synthetic-persistence-test")
    caplog.set_level(logging.DEBUG, logger=log.name)
    native = source(candidate, "agent/tool_executor.py")
    if entry == "persisted_stub":
        helper = function(native, "_record_persisted_path_for_stub", logger=log, extract_persisted_path=fail)
        agent = NS(_tool_guardrails=None)
        result = helper(agent, "call-a", CANARY)
        assert result is None
    else:
        monkeypatch.setitem(__import__('sys').modules, "agent.conversation_loop", NS(_maybe_inject_run_budget_wrapup=lambda *a: None))
        monkeypatch.setitem(__import__('sys').modules, "agent.turn_iteration_prep", NS(_maybe_inject_iteration_budget_warning=lambda *a: None))
        monkeypatch.setitem(__import__('sys').modules, "hermes_state", NS(classify_persistence_error=lambda exc: "unknown"))
        helper = function(native, "_flush_session_db_after_tool_progress", logger=log)
        agent = NS(session_id="session-a", _flush_messages_to_session_db=fail)
        ref = NS(name="memory", args=backend.args, task_id="task")
        result = helper(agent, [{"content": CANARY}], stage="tool result memory", ref=ref)
        assert result is False and agent._incremental_persistence_failed
        assert agent._last_persistence_error_cause == "unknown"
    assert caplog.records
    assert CANARY not in caplog.text and not any(record.exc_info for record in caplog.records)


@pytest.mark.parametrize("revoke_at", [None, "budget", "iteration"])
def test_native_flush_rechecks_after_each_preparation_callback(candidate, host, monkeypatch, revoke_at):
    backend, gate = allow(host)
    events = []
    def step(label):
        events.append(label)
        if label == revoke_at: backend.state = replace(backend.state, revoked=True)
    monkeypatch.setitem(__import__('sys').modules, "agent.conversation_loop", NS(_maybe_inject_run_budget_wrapup=lambda *a: step("budget")))
    monkeypatch.setitem(__import__('sys').modules, "agent.turn_iteration_prep", NS(_maybe_inject_iteration_budget_warning=lambda *a: step("iteration")))
    agent = NS(session_id="session-a", _flush_messages_to_session_db=lambda *a: step("flush") or True)
    helper = function(source(candidate, "agent/tool_executor.py"), "_flush_session_db_after_tool_progress")
    ref = NS(name="memory", args=backend.args, task_id="task")
    if revoke_at:
        with pytest.raises(authority.AuthorityDenied): helper(agent, [{"content": CANARY}], stage="result", ref=ref)
        assert events[-1] == revoke_at
    else:
        assert helper(agent, [{"content": CANARY}], stage="result", ref=ref)
        assert events == ["budget", "iteration", "flush"]


@pytest.mark.parametrize("spinner", [False, True])
@pytest.mark.parametrize("revoke", [False, True])
def test_native_spinner_rechecks_after_result_formatter(candidate, host, capsys, spinner, revoke):
    backend, gate = allow(host)
    def cute(*a, **kw):
        if revoke: backend.state = replace(backend.state, revoked=True)
        return CANARY
    agent = NS(session_id="session-a", _should_emit_quiet_tool_messages=lambda: True, _vprint=print)
    helper = function(source(candidate, "agent/tool_executor.py"), "_finish_quiet_tool_spinner", _get_cute_tool_message_impl=cute)
    if revoke:
        with pytest.raises(authority.AuthorityDenied):
            helper(agent, NS(stop=print) if spinner else None, "memory", backend.args, 1, CANARY, task_id="task")
    else:
        helper(agent, NS(stop=print) if spinner else None, "memory", backend.args, 1, CANARY, task_id="task")
    assert (CANARY in capsys.readouterr().out) is not revoke


@pytest.mark.parametrize("error_kind,destination", [
    (kind, destination) for destination in ("guardrail", "model-content", "metadata")
    for kind in ("error", "interrupt", "async_cancel", "future_cancel")
    if (kind, destination) != ("error", "metadata")  # Optional metadata errors are already safely caught.
])
def test_unhandled_native_observer_failure_never_exports_exception_body(native_commit, error_kind, destination):
    from asyncio import CancelledError as AsyncCancel
    from concurrent.futures import CancelledError as FutureCancel
    kinds = {"error": ValueError, "interrupt": KeyboardInterrupt, "async_cancel": AsyncCancel, "future_cancel": FutureCancel}
    native_commit.error_at, native_commit.error = destination, kinds[error_kind](CANARY)
    expected = authority.AuthorityDenied if error_kind == "error" else kinds[error_kind]
    with pytest.raises(expected) as caught: native_commit.call()
    assert CANARY not in "".join(traceback.format_exception(caught.value))
    if error_kind == "error":
        assert "unknown_no_retry" in str(caught.value)
    else:
        assert caught.value.args == ()
    assert [x[0] for x in native_commit.events][-1] == destination


@pytest.mark.parametrize("lane", ["sequential", "concurrent"])
@pytest.mark.parametrize("error_kind", ["interrupt", "async_cancel", "future_cancel"])
def test_native_callback_cancellation_stays_cancellation_without_body(publication, lane, error_kind):
    from asyncio import CancelledError as AsyncCancel
    from concurrent.futures import CancelledError as FutureCancel
    kind = {"interrupt": KeyboardInterrupt, "async_cancel": AsyncCancel, "future_cancel": FutureCancel}[error_kind]
    publication.callback_error = kind(CANARY)
    with pytest.raises(kind) as caught: getattr(publication, lane)()
    assert caught.value.args == ()
    assert CANARY not in "".join(traceback.format_exception(caught.value))
    assert [x[0] for x in publication.events] == ["complete"]


@pytest.mark.parametrize("lane", ["sequential", "concurrent"])
def test_last_native_callback_revocation_does_not_report_publication_complete(publication, lane):
    publication.revoke_at = "risk"
    with pytest.raises(authority.AuthorityDenied): getattr(publication, lane)()
    assert [x[0] for x in publication.events] == ["complete", "risk"]


@pytest.mark.parametrize("hook", ["post_tool_call", "transform_tool_result"])
def test_native_hook_discovery_cannot_authorize_later_private_observer(candidate, host, monkeypatch, hook):
    backend, gate = allow(host)
    seen = []
    def has_hook(name):
        backend.state = replace(backend.state, revoked=True)
        return True
    monkeypatch.setitem(__import__('sys').modules, "hermes_cli.lifecycle", NS(has_hook=has_hook, invoke_hook=lambda *a, **kw: seen.append(kw)))
    native = source(candidate, "model_tools.py")
    log = NS(debug=lambda *a: None)
    ns = dict(logger=log, _tool_result_observer_fields=lambda *a: seen.append(a) or ("ok", None, None))
    if hook == "post_tool_call":
        call = function(native, "_emit_post_tool_call_hook", **ns, _post_tool_call_hook_suppressed=NS(get=lambda: False))
        with pytest.raises(authority.AuthorityDenied):
            call(function_name="memory", function_args=backend.args, result=CANARY, session_id="session-a", task_id="task")
    else:
        call = function(native, "_apply_transform_tool_result_hook", **ns)
        with pytest.raises(authority.AuthorityDenied):
            call("memory", backend.args, CANARY, 1, NS(session_id="session-a", task_id="task", hook_kwargs=lambda: {}))
    assert seen == []


@pytest.fixture
def inner_observer(candidate, host):
    """Compile the native primitive itself; only its guardrail dependencies fake."""
    import logging
    import inspect
    backend, gate = allow(host)
    events = []
    state = NS(change=None, error=None, change_at="observe", action="allow", notice=None)
    decision = NS(action="allow", should_halt=False)
    def live_change(label):
        if state.change_at != label: return
        if state.change == "revoked": backend.state = replace(backend.state, revoked=True)
        elif state.change == "lease": backend.state = replace(backend.state, lease_until=99)
        elif state.change == "unavailable": backend.failure = True
    def after(*a, **kw):
        events.append("after")
        live_change("after")
        decision.action, decision.should_halt = state.action, state.action == "halt"
        return decision
    def observe(*a, **kw):
        events.append("observe")
        live_change("observe")
        if state.error: raise state.error
        return NS(notice=state.notice, stub=None, kind="identical_call_streak")
    def warnings(*a):
        events.append("warnings")
        live_change("warnings")
    agent = NS(session_id="session-a", _tool_guardrails=NS(after_call=after, observe_call=observe, halt_decision=None),
        _stall_guards_enabled=lambda: True, _set_tool_guardrail_halt=lambda *a: events.append("halt"))
    native = function(source(candidate, "run_agent.py"), "_append_guardrail_observation",
        logger=logging.getLogger("synthetic-inner-observer"),
        record_guardrail_warnings=warnings, append_toolguard_guidance=lambda result, decision: result + "|guidance")
    # Permit RED to exercise the actual unpatched 711 signature, rather than
    # failing in the test harness before reaching its internal catch/logger.
    kw = {"task_id": "task"} if "task_id" in inspect.signature(native).parameters else {}
    state.call = lambda: native(agent, "memory", backend.args, "approved synthetic result", failed=False, tool_call_id="call-a", **kw)
    state.events, state.backend, state.agent, state.native = events, backend, agent, native
    return state


@pytest.mark.parametrize("change", [None, "revoked", "lease", "unavailable"])
def test_actual_inner_observe_call_error_has_no_private_log_or_return(inner_observer, caplog, capsys, change):
    caplog.set_level(__import__('logging').DEBUG)
    inner_observer.change, inner_observer.error = change, ValueError(CANARY)
    if change:
        with pytest.raises(authority.AuthorityDenied) as caught: inner_observer.call()
        assert CANARY not in "".join(traceback.format_exception(caught.value))
        assert inner_observer.events == ["after", "observe"]
    else:
        assert inner_observer.call() == "approved synthetic result"
        assert inner_observer.events == ["after", "observe", "warnings"]
        assert caplog.records, "safe optional observer failure metadata remains visible"
    assert CANARY not in caplog.text and not any(r.exc_info for r in caplog.records)
    assert CANARY not in str(capsys.readouterr())


@pytest.mark.parametrize("kind", ["denied", "interrupt", "async_cancel", "future_cancel"])
def test_actual_inner_observer_does_not_swallow_denial_or_cancellation(inner_observer, kind, caplog):
    from asyncio import CancelledError as AsyncCancel
    from concurrent.futures import CancelledError as FutureCancel
    classes = {"denied": authority.AuthorityDenied, "interrupt": KeyboardInterrupt,
               "async_cancel": AsyncCancel, "future_cancel": FutureCancel}
    inner_observer.error = classes[kind]("authority_audience_denied" if kind == "denied" else CANARY)
    caplog.set_level(__import__('logging').DEBUG)
    with pytest.raises(classes[kind]) as caught: inner_observer.call()
    assert CANARY not in "".join(traceback.format_exception(caught.value))
    if kind != "denied": assert caught.value.args == ()
    assert inner_observer.events == ["after", "observe"]
    assert not caplog.records


@pytest.mark.parametrize("change_at", ["after", "observe", "warnings"])
def test_actual_inner_observer_revalidates_between_its_native_callees(inner_observer, change_at):
    inner_observer.change, inner_observer.change_at = "revoked", change_at
    with pytest.raises(authority.AuthorityDenied): inner_observer.call()
    assert inner_observer.events[-1] == change_at


@pytest.mark.parametrize("action,notice", [("allow", None), ("warn", "synthetic stall notice"), ("halt", None)])
def test_actual_inner_observer_keeps_legitimate_guidance_and_halt(inner_observer, action, notice):
    inner_observer.action, inner_observer.notice = action, notice
    expected = "approved synthetic result" + ("|guidance" if action in {"warn", "halt"} else "")
    if notice: expected += "\n\n" + notice
    assert inner_observer.call() == expected
    assert inner_observer.events == ["after", "observe", "warnings"] + (["halt"] if action == "halt" else [])


@pytest.mark.parametrize("primitive", ["note_tool_result", "record_tool_batch", "observe_tool_outcome", "record_guardrail_decision", "_record", "_guarded"])
@pytest.mark.parametrize("error_kind", ["error", "denied", "future_cancel"])
def test_actual_observation_metric_catches_do_not_log_private_tracebacks(candidate, host, monkeypatch, caplog, primitive, error_kind):
    import logging
    from concurrent.futures import CancelledError
    allow(host)
    error = {"error": ValueError(CANARY), "denied": authority.AuthorityDenied("authority_audience_denied"), "future_cancel": CancelledError(CANARY)}[error_kind]
    reached = []
    def fail(*a, **kw):
        reached.append(True)
        raise error
    log = logging.getLogger("synthetic-inner-metrics")
    caplog.set_level(logging.DEBUG)
    root = "hermes_cli/observability/"
    if primitive in {"note_tool_result", "record_tool_batch"}:
        ns = dict(logger=log, _internal_agent=lambda *a: False, _enabled=lambda: True,
            _PENDING_OUTPUTS_ATTR="_pending", _PENDING_OUTPUTS_MAX=256, _result_size=fail)
        entry = function(source(candidate, root + "shared_metrics_efficiency.py"), primitive, **ns)
        if primitive == "note_tool_result":
            call = lambda: entry(NS(), "memory", "call-a", CANARY, CANARY)
        else:
            monkeypatch.setitem(__import__('sys').modules, "hermes_cli.observability.relay_shared_metrics", NS(record_process_mark=fail))
            entry.__globals__.update(__package__="hermes_cli.observability", contract=NS(TOOL_OUTPUT_TRUNCATION_MARK="tool_output"), output_size_bucket=lambda *a: "small")
            call = lambda: entry(NS(_pending={"call-a": ["memory", 12, False]}), [], [])
    elif primitive == "_guarded":
        entry = function(source(candidate, root + "relay_shared_metrics.py"), primitive, logger=log)
        call = lambda: entry("safe constant metric failure", fail)
    else:
        ns = dict(logger=log, _active=lambda *a: True, _turn_state=fail,
            _GUARD_DETECTORS={"repeated_exact_failure_warning": "exact"}, _record_guard=fail)
        entry = function(source(candidate, root + "shared_metrics_harness.py"), primitive, **ns)
        if primitive == "observe_tool_outcome": call = lambda: entry(NS(), "memory", False)
        elif primitive == "record_guardrail_decision": call = lambda: entry(NS(), "warn", "repeated_exact_failure_warning")
        else:
            from types import ModuleType
            entry.__globals__["__package__"] = "hermes_cli.observability"
            package = ModuleType("hermes_cli.observability")
            package.__path__ = []
            package.shared_metrics_contract = NS(LOOP_GUARD_MARK="loop")
            monkeypatch.setitem(__import__('sys').modules, "hermes_cli.observability", package)
            monkeypatch.setitem(__import__('sys').modules, "hermes_cli.observability.shared_metrics_contract", package.shared_metrics_contract)
            monkeypatch.setitem(__import__('sys').modules, "hermes_cli.observability.relay_shared_metrics", NS(record_process_mark=fail))
            call = lambda: entry("LOOP_GUARD_MARK", {"signal": "loop"})
    if error_kind == "error":
        assert call() is None
        assert caplog.records
    else:
        with pytest.raises(type(error)) as caught: call()
        assert CANARY not in "".join(traceback.format_exception(caught.value))
        if error_kind == "future_cancel": assert caught.value.args == ()
    assert CANARY not in caplog.text and not any(r.exc_info for r in caplog.records)
    assert reached == [True], "the real primitive must reach its failing inner dependency"


@pytest.mark.parametrize("change", [None, "revoked", "lease", "unavailable"])
def test_actual_commit_uses_real_inner_observer_before_persistence(native_commit, inner_observer, caplog, change):
    from types import MethodType
    agent = native_commit.agent
    agent._tool_guardrails = inner_observer.agent._tool_guardrails
    agent._stall_guards_enabled = inner_observer.agent._stall_guards_enabled
    agent._set_tool_guardrail_halt = inner_observer.agent._set_tool_guardrail_halt
    agent._append_guardrail_observation = MethodType(inner_observer.native, agent)
    native_commit.result = "approved synthetic result"
    inner_observer.change, inner_observer.error = change, ValueError(CANARY)
    caplog.set_level(__import__('logging').DEBUG)
    if change:
        with pytest.raises(authority.AuthorityDenied): native_commit.call()
        assert native_commit.events == [] and native_commit.messages == []
    else:
        assert native_commit.call()[0] == "approved synthetic result"
        assert native_commit.messages == [{"content": "approved synthetic result"}]
    assert CANARY not in caplog.text and not any(r.exc_info for r in caplog.records)
    assert inner_observer.events.count("observe") == 1


@pytest.mark.parametrize("outcome", ["success", "error", "denied", "future_cancel"])
def test_real_guardrail_metric_chain_reaches_safe_native_relay_sink(candidate, host, monkeypatch, caplog, outcome):
    """Warnings -> decision -> record -> process mark -> safe -> guarded -> sink."""
    import logging
    from types import ModuleType
    from concurrent.futures import CancelledError
    allow(host)
    root = "hermes_cli/observability/"
    harness = source(candidate, root + "shared_metrics_harness.py")
    relay = source(candidate, root + "relay_shared_metrics.py")
    log = logging.getLogger("synthetic-real-metric-chain")
    caplog.set_level(logging.DEBUG)
    sinks = []
    def sink(mark, data):
        sinks.append((mark, data))
        if outcome == "error": raise ValueError(CANARY)
        if outcome == "denied": raise authority.AuthorityDenied("authority_audience_denied")
        if outcome == "future_cancel": raise CancelledError(CANARY)
    guarded = function(relay, "_guarded", logger=log)
    safe = function(relay, "_safe")
    runtime = NS(_guarded=guarded, record_process_mark=sink)
    runtime._safe = lambda cb, *a, **kw: safe(runtime, cb, *a, **kw)
    # The module function and the _Runtime method share this native name.
    # Select the actual module entry explicitly; neither body is substituted.
    import ast
    module_entries = [n for n in ast.parse(relay).body if isinstance(n, ast.FunctionDef) and n.name == "record_process_mark"]
    assert len(module_entries) == 1
    process = function(ast.unparse(module_entries[0]), "record_process_mark", enabled=lambda: True,
        relay_runtime=NS(relay_instrumentation_enabled=lambda: True), _get_runtime=lambda **kw: runtime)
    package = ModuleType("hermes_cli.observability")
    package.__path__ = []
    package.shared_metrics_contract = NS(LOOP_GUARD_MARK="loop_guard")
    monkeypatch.setitem(__import__('sys').modules, "hermes_cli.observability", package)
    monkeypatch.setitem(__import__('sys').modules, "hermes_cli.observability.shared_metrics_contract", package.shared_metrics_contract)
    monkeypatch.setitem(__import__('sys').modules, "hermes_cli.observability.relay_shared_metrics", NS(record_process_mark=process))
    record = function(harness, "_record", logger=log, __package__="hermes_cli.observability")
    state = NS(guard_signals=set())
    guard = function(harness, "_record_guard", _turn_state=lambda agent: state,
        _route=lambda agent: {"model": "model-a"}, _record=record)
    decide = function(harness, "record_guardrail_decision", logger=log, _active=lambda agent: True,
        _GUARD_DETECTORS={"repeated_exact_failure_warning": "exact"}, _record_guard=guard)
    warnings = function(harness, "record_guardrail_warnings", record_guardrail_decision=decide)
    call = lambda: warnings(NS(), NS(action="warn", code="repeated_exact_failure_warning"), None)
    if outcome in {"success", "error"}: assert call() is None
    else:
        expected = authority.AuthorityDenied if outcome == "denied" else CancelledError
        with pytest.raises(expected) as caught: call()
        assert CANARY not in "".join(traceback.format_exception(caught.value))
        if outcome == "future_cancel": assert caught.value.args == ()
    assert sinks == [("loop_guard", {"model": "model-a", "detector": "exact", "signal": "repeated_tool_call"})]
    assert CANARY not in caplog.text and not any(r.exc_info for r in caplog.records)
    if outcome == "success": assert not caplog.records
    if outcome == "error": assert caplog.records, "safe failure metadata remains observable"
