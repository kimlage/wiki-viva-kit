"""Actual native entry bodies and local process channel, synthetic data only."""
from __future__ import annotations

import ast
import asyncio
from dataclasses import replace
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from types import SimpleNamespace as NS

import pytest
from wiki_core import native_host as nh, native_host_wire as wire
from wiki_core.runtime_authority import Authority, AuthorityDenied, sha
from test_hermes_kernel_candidate import function, KERNEL
from test_runtime_authority import Host


def native_source(candidate, path):
    if path in candidate:
        return candidate[path][1]
    return (Path(os.environ["WIKI_HERMES_KERNEL_SOURCE"]) / path).read_text()


@pytest.fixture(scope="module")
def native_candidate():
    path = os.environ.get("WIKI_NATIVE_TEST_BUILDER", str(KERNEL / "build_candidate.py"))
    spec = importlib.util.spec_from_file_location("native_host_candidate", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = os.environ.get("WIKI_HERMES_KERNEL_SOURCE")
    if not root:
        pytest.skip("requires pinned public native source")
    return module.candidate(Path(root))


@pytest.fixture
def native_modules(monkeypatch):
    monkeypatch.setitem(sys.modules, "tools.wiki_native_host", nh)
    monkeypatch.setitem(sys.modules, "tools.wiki_native_host_wire", wire)
    from wiki_core import runtime_authority as auth
    monkeypatch.setattr(auth,"_host",None)
    monkeypatch.setitem(sys.modules, "tools.wiki_authority", auth)
    monkeypatch.setattr(wire, "_client", None)
    from wiki_core import native_startup_guard
    monkeypatch.setattr(native_startup_guard, "_restricted", False)
    monkeypatch.setitem(sys.modules, "tools.wiki_native_startup_guard", native_startup_guard)
    monkeypatch.delenv("HERMES_WIKI_NATIVE_CHANNEL", raising=False)


def test_real_spawn_refuses_before_profile_or_credential_resolution(native_candidate, native_modules):
    class Task:
        id = "task"
        @property
        def assignee(self):
            raise RuntimeError("SYNTHETIC-PRIVATE-PROFILE-MUST-NOT-BE-READ")
    spawn = function(native_source(native_candidate,"hermes_cli/kanban_db_dispatch.py"), "_default_spawn")
    with pytest.raises(AuthorityDenied):
        spawn(Task(), "/synthetic/workspace", board="board-a")


def native_constructor(native_candidate, **namespace):
    tree = ast.parse(native_candidate["run_agent.py"][1])
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "AIAgent")
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    return function(ast.unparse(method), "__init__", sys=sys, **namespace)


def test_real_constructor_refuses_before_agent_factory(native_candidate, native_modules, monkeypatch):
    built = []
    monkeypatch.setitem(sys.modules, "agent.agent_init", NS(init_agent=lambda *a, **kw: built.append(kw)))
    ctor = native_constructor(native_candidate)
    with pytest.raises(AuthorityDenied):
        ctor(NS(), session_id="forged-session")
    assert built == []


@pytest.fixture
def stack(tmp_path, native_candidate, native_modules, monkeypatch):
    source = native_candidate["hermes_cli/kanban_db.py"][1]
    (tmp_path / "wiki").mkdir()
    fixture = Host(tmp_path / "wiki")
    now = int(time.time())
    grant = nh.NativeGrant("research-bot", "requester-a", "research", "task", "task", "1", sha("native-claim"),
        "grant-1", fixture.state.packet_sha256, fixture.state.refs, fixture.state.operations, now+1000, now+800, native_grant=True)
    projection_op = replace(fixture.op, tool="native_projection",
        arguments_sha256=sha({"task":"task","intent":"intent-a"}), kind="projection")
    grant = replace(grant, operations=grant.operations + (projection_op,))
    enrollment = nh.Enrollment("board-a", "intent-a", "native-test", grant)
    owner = nh.RegistryPublisher(nh.RegistrySnapshot("registry-1", (enrollment,)))
    db = tmp_path / "native.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript("""
CREATE TABLE tasks(id TEXT,assignee TEXT,status TEXT,current_run_id INTEGER,claim_lock TEXT,claim_expires INTEGER,
worker_pid INTEGER,worker_started_at TEXT,idempotency_key TEXT,title TEXT,body TEXT,result TEXT);
CREATE TABLE task_runs(id INTEGER,task_id TEXT,profile TEXT,status TEXT,claim_lock TEXT,claim_expires INTEGER,
worker_pid INTEGER,worker_started_at TEXT,ended_at INTEGER,summary TEXT,error TEXT);
INSERT INTO tasks VALUES('task','research','running',1,'native-claim',180,NULL,NULL,'intent-a',
'PRIVATE-TITLE-CANARY','PRIVATE-BODY-CANARY','PRIVATE-RESULT-CANARY');
INSERT INTO task_runs VALUES(1,'task','research','running','native-claim',180,NULL,NULL,NULL,
'PRIVATE-SUMMARY-CANARY','PRIVATE-ERROR-CANARY');
""")
    conn.execute("UPDATE tasks SET claim_expires=?",(now+800,))
    conn.execute("UPDATE task_runs SET claim_expires=?",(now+800,))
    conn.commit()
    conn.close()
    reads = []
    real_reader = nh.NativeBoardReader({"board-a":db})
    def reader(board):
        conn = real_reader(board)
        def authorize(action, table, column, *_):
            if action == sqlite3.SQLITE_READ:
                reads.append((table,column))
                if column in {"title","body","result","summary","error"}:
                    return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        conn.set_authorizer(authorize)
        return conn
    state = NS(alive=True)
    live = function(source, "_claim_is_live", _worker_alive=lambda pid, fp: state.alive)
    kb = NS(get_task=function(source,"get_task"), get_run=function(source,"get_run"), _claim_is_live=live)
    host = nh.NativeHost(owner.reader, connect=reader, kb=kb,
        workflow=NS(to_dict=lambda:{"columns":[{"key":"running"},{"key":"done"},{"key":"review"}]}),
        context=fixture, clock=lambda:now)
    class Session:
        user_id, provider, expires_at = "requester-a", "native-test", now+1000
        org_id = ""
        @property
        def access_token(self):
            raise AssertionError("credential accessed")
        @property
        def refresh_token(self):
            raise AssertionError("credential accessed")
    monkeypatch.setitem(sys.modules,"hermes_cli.dashboard_auth.base",NS(Session=Session))
    request = NS(app=NS(state=NS(auth_required=True,wiki_native_host=host)),state=NS(),url=NS(path="/api/dispatch"))
    middleware = function(native_candidate["hermes_cli/dashboard_auth/middleware.py"][1],"gated_auth_middleware",
        _path_is_public=lambda path:False, _extract_bearer=lambda request:"synthetic-auth-input",
        _verify_access_token=lambda *a,**kw:Session(), ProviderError=type("ProviderError",(Exception,),{}))
    async def authenticated(callback):
        async def next_handler(request):
            return callback()
        return await middleware(request,next_handler)
    def update(sql,args=()):
        conn=sqlite3.connect(db)
        conn.execute(sql,args)
        conn.commit()
        conn.close()
    state.authenticated,state.host,state.owner,state.enrollment = authenticated,host,owner,enrollment
    state.request,state.reads,state.update,state.db,state.now = request,reads,update,db,now
    return state


def registered_channel(stack):
    launch = asyncio.run(stack.authenticated(lambda:nh.prepare_worker("task","board-a")))
    launch.spawned(os.getpid())
    stack.update("UPDATE tasks SET worker_pid=?,worker_started_at='start-a'",(os.getpid(),))
    stack.update("UPDATE task_runs SET worker_pid=?,worker_started_at='start-a'",(os.getpid(),))
    stack.host.registered("task",os.getpid(),"start-a")
    client = wire.WorkerBackend(launch.path,expected_controller_pid=os.getpid(),native_session="native-worker-session")
    return launch,client


def test_real_metadata_queries_and_os_channel_complete_public_context(stack):
    launch,client = registered_channel(stack)
    try:
        gate=Authority(client,clock=lambda:stack.now)
        packet=json.loads(gate.admit("native-worker-session","task"))
        assert packet["context_sha256"] == stack.enrollment.grant.packet_sha256
        assert gate.require("read_public",{"resource":"source","query":"public capabilities"}).kind == "read"
        assert not any(c in {"body","title","result","summary","error"} for _,c in stack.reads)
        projection=client._call("projection",session="native-worker-session",task="task")
        assert projection == client._call("projection",session="native-worker-session",task="task")
        assert projection["retry_authorized"] is False and projection["reconcile_required"] is True
        assert "PRIVATE-" not in json.dumps(projection)
    finally:
        client.close()
        launch.close()


@pytest.mark.parametrize("change",["session","run","claim","lease","stop","approval","revoked","registry","dead","context"])
def test_live_native_changes_deny_before_effect_and_return(stack,change):
    launch,client = registered_channel(stack)
    try:
        gate=Authority(client,clock=lambda:stack.now)
        gate.admit("native-worker-session","task")
        if change=="run": stack.update("UPDATE tasks SET current_run_id=2")
        elif change=="claim": stack.update("UPDATE task_runs SET claim_lock='replaced'")
        elif change=="lease": stack.update("UPDATE tasks SET claim_expires=99")
        elif change=="dead": stack.alive=False
        elif change=="context":
            path=stack.host.context.root / stack.enrollment.grant.refs[0][0]
            path.write_text(path.read_text()+"\nchanged synthetic context\n")
        elif change!="session":
            fields={"stopped":True} if change=="stop" else {"approval_pending":True} if change=="approval" else {"revoked":True} if change=="revoked" else {}
            entry=replace(stack.enrollment,grant=replace(stack.enrollment.grant,**fields))
            stack.owner.replace(nh.RegistrySnapshot("registry-2",(entry,)),expected_revision="registry-1")
        for phase in ("effect","disclose"):
            with pytest.raises(AuthorityDenied):
                gate.require("read_public",{"resource":"source","query":"public capabilities"},
                    session="forged-session" if change=="session" else "native-worker-session",task="task",phase=phase)
    finally:
        client.close()
        launch.close()


def test_unverified_ingress_and_worker_policy_mutation_have_no_authority(stack):
    with pytest.raises(AuthorityDenied): nh.prepare_worker("task","board-a")
    with pytest.raises(AuthorityDenied): nh.RegistryReader(lambda:nh.RegistrySnapshot("forged",()),None)
    assert not hasattr(stack.owner.reader,"replace")
    stack.request.app.state.auth_required=False
    with pytest.raises(AuthorityDenied):
        asyncio.run(stack.authenticated(lambda:nh.prepare_worker("task","board-a")))


def test_terminal_without_effect_receipt_is_native_state_with_reconciliation_hold(stack, monkeypatch):
    launch,client=registered_channel(stack)
    try:
        gate=Authority(client,clock=lambda:stack.host.clock())
        gate.admit("native-worker-session","task")
        stack.update("UPDATE tasks SET status='done',current_run_id=NULL,claim_lock=NULL,claim_expires=NULL,worker_pid=NULL")
        stack.update("UPDATE task_runs SET status='done',ended_at=110,claim_expires=NULL")
        monkeypatch.setattr(wire,"_client",client)
        # The native claim lease may expire after completion; this does not
        # extend the operator mandate or permit another effect/model call.
        stack.host.clock=lambda:stack.now+850
        agent=NS(session_id="native-worker-session")
        projection=wire.project_native_result(agent,"task")
        assert wire.project_native_result(agent,"task")==projection
        assert projection["native_status"]=="done" and projection["delivery"]=="unknown"
        assert projection["reconcile_required"] is True and projection["retry_authorized"] is False
        assert "PRIVATE-" not in json.dumps(projection)
        effects=[]
        with pytest.raises(AuthorityDenied):
            gate.invoke("read_public",{"resource":"source","query":"public capabilities"},
                lambda args:effects.append(args),session="native-worker-session",task="task")
        assert effects==[]
        with pytest.raises(AuthorityDenied): wire.bound_task(agent,"task")
        with pytest.raises(AuthorityDenied): client.resolve("native-worker-session","task")
    finally:
        client.close()
        launch.close()


@pytest.mark.parametrize("change", ["session", "task", "run", "pid", "fingerprint",
    "revoked", "audience", "expired"])
def test_public_terminal_projection_retains_identity_policy_and_audience_checks(stack, monkeypatch, change):
    launch,client=registered_channel(stack)
    try:
        monkeypatch.setattr(wire,"_client",client)
        stack.update("UPDATE tasks SET status='done',current_run_id=NULL,claim_lock=NULL,claim_expires=NULL,worker_pid=NULL")
        stack.update("UPDATE task_runs SET status='done',ended_at=110,claim_expires=NULL")
        agent=NS(session_id="other-session" if change=="session" else "native-worker-session")
        task="other-task" if change=="task" else "task"
        if change=="run": stack.update("UPDATE tasks SET current_run_id=2")
        if change=="pid": stack.update("UPDATE task_runs SET worker_pid=worker_pid+1")
        if change=="fingerprint": stack.update("UPDATE task_runs SET worker_started_at='other-start'")
        if change in {"revoked","audience"}:
            grant=stack.enrollment.grant
            if change=="revoked": grant=replace(grant,revoked=True)
            else: grant=replace(grant,operations=tuple(op for op in grant.operations if op.tool!="native_projection"))
            stack.owner.replace(nh.RegistrySnapshot("registry-2",(replace(stack.enrollment,grant=grant),)),
                expected_revision="registry-1")
        if change=="expired": stack.host.clock=lambda:stack.now+1100
        with pytest.raises(AuthorityDenied): wire.project_native_result(agent,task)
        assert not any(c in {"body","title","result","summary","error"} for _,c in stack.reads)
    finally:
        client.close()
        launch.close()


@pytest.mark.parametrize("mismatch", ["peer", "claim", "requester", "provider", "organization"])
def test_native_identity_cannot_be_forged_by_task_fields_or_channel_hint(stack, mismatch):
    if mismatch in {"requester","provider","organization"}:
        entry=replace(stack.enrollment,grant=replace(stack.enrollment.grant,requester="other-user")) if mismatch=="requester" else replace(stack.enrollment,auth_provider="other-provider") if mismatch=="provider" else replace(stack.enrollment,auth_org="other-org")
        stack.owner.replace(nh.RegistrySnapshot("registry-2",(entry,)),expected_revision="registry-1")
        with pytest.raises(AuthorityDenied):
            asyncio.run(stack.authenticated(lambda:nh.prepare_worker("task","board-a")))
        assert not stack.reads
        return
    launch=asyncio.run(stack.authenticated(lambda:nh.prepare_worker("task","board-a")))
    pid=os.getpid()+1 if mismatch=="peer" else os.getpid()
    launch.spawned(pid)
    stack.update("UPDATE tasks SET worker_pid=?,worker_started_at='start-a'",(pid,))
    stack.update("UPDATE task_runs SET worker_pid=?,worker_started_at='start-a'",(pid,))
    if mismatch=="claim": stack.update("UPDATE tasks SET claim_lock='forged-claim'")
    stack.host.registered("task",pid,"start-a")
    try:
        with pytest.raises(AuthorityDenied):
            wire.WorkerBackend(launch.path,expected_controller_pid=os.getpid(),native_session="native-worker-session")
    finally:launch.close()


def test_wrapper_and_replayed_launch_do_not_select_another_executor(stack):
    launch=asyncio.run(stack.authenticated(lambda:nh.prepare_worker("task","board-a")))
    try:
        with pytest.raises(AuthorityDenied):launch.qualify(["native"],["wrapper","native"])
        with pytest.raises(AuthorityDenied):
            asyncio.run(stack.authenticated(lambda:nh.prepare_worker("task","board-a")))
        entry=replace(stack.enrollment,grant=replace(stack.enrollment.grant,stopped=True))
        stack.owner.replace(nh.RegistrySnapshot("registry-2",(entry,)),expected_revision="registry-1")
        with pytest.raises(AuthorityDenied):launch.before_spawn()
    finally:launch.close()


def test_native_readonly_connection_cannot_update_or_create_state(stack):
    conn=nh.NativeBoardReader({"board-a":stack.db})("board-a")
    try:
        with pytest.raises(sqlite3.OperationalError):conn.execute("UPDATE tasks SET status='done'")
        with pytest.raises(sqlite3.OperationalError):conn.execute("CREATE TABLE another_lifecycle(id TEXT)")
    finally:conn.close()


def test_real_spawn_registration_constructor_and_public_return_chain(stack,native_candidate,monkeypatch,tmp_path):
    """Only the final Python process/factory/destination are synthetic, not native hooks."""
    import io
    import subprocess
    from test_hermes_kernel_candidate import ROOT
    tree=ast.parse(native_candidate["run_agent.py"][1])
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=="AIAgent")
    ctor=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=="__init__")
    def body(path,name):
        tree=ast.parse(native_source(native_candidate,path))
        return ast.unparse(next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name==name))
    child=tmp_path/"synthetic-worker.py"
    ctor_source=ast.unparse(ctor)
    child.write_text(
        "from __future__ import annotations\nimport sys,json,os\nfrom datetime import datetime\nfrom pathlib import Path\nfrom types import SimpleNamespace as NS\n"
        "from wiki_core import native_host_wire as wire, runtime_authority as auth\n"
        "sys.modules['tools.wiki_native_host_wire']=wire\nsys.modules['tools.wiki_authority']=auth\n"
        "sys.modules['hermes_state_ids']=NS(new_session_id=lambda:'native-worker-session')\n"
        "_mcp_server_filter=None\n"
        +body("hermes_cli/mcp_startup.py","set_mcp_server_filter")+"\n"
        "sys.modules['hermes_cli.mcp_startup']=NS(set_mcp_server_filter=set_mcp_server_filter)\n"
        +body("hermes_cli/main.py","_prepare_agent_startup")+"\n"
        "_prepare_agent_startup(NS(command='chat',query='public synthetic question',toolsets='synthetic-native',resume=None,yolo=False,accept_hooks=False))\n"
        "assert _mcp_server_filter==['synthetic-native']\n"
        "sys.modules['cli']=NS(_hermes_home=Path('/synthetic/home'))\n"
        "new_session_id=lambda *a:'SHOULD-NOT-ALLOCATE-ANOTHER-SESSION'\n"
        +body("hermes_cli/cli_init_mixin.py","_init_runtime_state")+"\n"
        "cli=NS(_init_session_store=lambda:None,_init_ui_state=lambda:None)\n"
        "_init_runtime_state(cli,None)\n"
        "seen=[]\n"
        "def initialize(agent,**kw):\n"
        "    auth.require('read_public',{'resource':'source','query':'public capabilities'})\n"
        "    agent.session_id=kw['session_id']\n"
        "    seen.append({'skip_context_files':kw['skip_context_files'],'skip_memory':kw['skip_memory']})\n"
        "sys.modules['agent.agent_init']=NS(init_agent=initialize)\n"
        +ctor_source+"\n"
        "agent=NS()\n__init__(agent,session_id=cli.session_id)\n"
        "projection=wire.project_native_result(agent,wire.bound_task(agent,None))\n"
        "print(json.dumps({'session':agent.session_id,'factory':seen,'projection':projection}))\n")
    processes=[]
    def popen(*a,**kw):
        proc=subprocess.Popen([sys.executable,str(child)],env=kw["env"],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        processes.append(proc)
        return proc
    monkeypatch.setitem(sys.modules,"hermes_cli.profiles",NS(normalize_profile_name=lambda v:v,resolve_profile_env=lambda v:None))
    monkeypatch.setitem(sys.modules,"agent.secret_scope",NS(is_multiplex_active=lambda:False))
    monkeypatch.setitem(sys.modules,"tools.environments.local",NS(_is_routed_home=lambda p:False,
        build_subprocess_env=lambda **kw:{"PATH":os.defpath,"PYTHONPATH":str(ROOT)},strip_launch_profile_env=lambda *a:None))
    monkeypatch.setitem(sys.modules,"gateway.session_context",NS(_VAR_MAP={}))
    monkeypatch.setitem(sys.modules,"agent.delegation_context",NS(DELEGATED_CHILD_ENV_MARKER="SYNTHETIC_CHILD_MARKER"))
    monkeypatch.setitem(sys.modules,"tools.process_registry",NS(systemd_user_bus_env=lambda env:env))
    kb=NS(_IS_WINDOWS=False,kanban_db_path=lambda **kw:stack.db,workspaces_root=lambda **kw:tmp_path,
        _normalize_board_slug=lambda v:v,get_current_board=lambda:"board-a")
    spawn=function(native_candidate["hermes_cli/kanban_db_dispatch.py"][1],"_default_spawn",os=os,
        contextlib=__import__('contextlib'),subprocess=NS(Popen=popen,DEVNULL=subprocess.DEVNULL,STDOUT=subprocess.STDOUT),
        _kb=kb,_retag_legacy_worker_sessions=lambda *a:None,_worker_terminal_timeout_env=lambda *a:None,
        _worker_argv=lambda *a:["synthetic-native"],_propagate_module_import_root=lambda *a:None,
        _restart_safe_worker_argv=lambda task,cmd:cmd,_open_worker_log=lambda *a:io.BytesIO())
    events=[]
    writer_kb=NS(write_txn=lambda conn:conn,_current_run_id=lambda conn,task:1,
        _append_event=lambda *a,**kw:events.append(("spawned",kw["run_id"])))
    register=function(native_candidate["hermes_cli/kanban_db_dispatch.py"][1],"_set_worker_pid",
        _kb=writer_kb,_process_fingerprint=lambda pid:"start-a",UNVERIFIED_WORKER_FINGERPRINT="unverified")
    task=NS(id="task",assignee="research",tenant=None,branch_name=None,current_run_id=1,
        claim_lock="native-claim",goal_mode=False,max_runtime_seconds=None)
    def dispatch():
        pid=spawn(task,str(tmp_path),board="board-a")
        conn=sqlite3.connect(stack.db)
        try:register(conn,"task",pid)
        finally:conn.close()
    asyncio.run(stack.authenticated(dispatch))
    proc=processes[0]
    try:
        stdout,stderr=proc.communicate(timeout=12)
        assert proc.returncode==0,stderr.decode()
        result=json.loads(stdout)
        assert result["session"]=="native-worker-session"
        assert result["factory"]==[{"skip_context_files":True,"skip_memory":True}]
        assert result["projection"]["task_id"]=="task"
        assert result["projection"]["retry_authorized"] is False
        assert "PRIVATE-" not in stdout.decode()+stderr.decode()
        assert events==[("spawned",1)] and len(processes)==1
    finally:
        if proc.poll() is None:proc.kill();proc.wait()
        for channel in list(stack.host._channels.values()):channel.close()


def test_missing_or_untyped_registry_holds_reads_without_replacing_native_ui():
    for provider in (None, {"native_grant":True}):
        app=NS(state=NS(wiki_native_host_provider=provider))
        with nh.native_host_scope(app):
            assert app.state.wiki_native_host is None
            assert app.state.wiki_native_hold_code.startswith("authority_")
        assert app.state.wiki_native_host is None


def test_real_host_startup_uses_native_readers_and_closes_channels(stack,monkeypatch):
    from types import ModuleType
    parent=ModuleType("hermes_cli")
    parent.__path__=[]
    parent.kanban_db=stack.host.kb
    monkeypatch.setitem(sys.modules,"hermes_cli",parent)
    monkeypatch.setitem(sys.modules,"hermes_cli.kanban_db",stack.host.kb)
    monkeypatch.setitem(sys.modules,"hermes_cli.kanban_workflow",NS(DEFAULT_WORKFLOW=stack.host.workflow))
    provider=nh.NativeHostProvider(stack.owner.reader,(("board-a",stack.db),),stack.host.context)
    app=NS(state=NS(wiki_native_host_provider=provider))
    with nh.native_host_scope(app):
        assert isinstance(app.state.wiki_native_host,nh.NativeHost)
        assert isinstance(app.state.wiki_native_host.connect,nh.NativeBoardReader)
    assert app.state.wiki_native_host is None


def test_real_env_registration_refuses_before_legacy_board_write(native_candidate,native_modules):
    reads=[]
    register=function(native_candidate["tools/kanban_tools.py"][1],"register_current_worker_from_env",
        os=NS(environ={"HERMES_KANBAN_TASK":"forged-task"}),_worker_run_id=lambda *a:reads.append(True))
    with pytest.raises(AuthorityDenied):
        register(native_session="forged-session")
    assert reads==[]


@pytest.mark.parametrize("key",["HERMES_KANBAN_TASK","HERMES_KANBAN_RUN_ID","HERMES_KANBAN_CLAIM_LOCK","HERMES_KANBAN_BOARD"])
def test_env_pins_do_not_change_authenticated_worker_authority(stack,monkeypatch,key):
    from wiki_core import runtime_authority as auth
    launch,client=registered_channel(stack)
    try:
        monkeypatch.setattr(wire,"_client",client)
        auth.install_host_backend(client)
        for k,v in {"HERMES_KANBAN_TASK":"task","HERMES_KANBAN_RUN_ID":"1",
                    "HERMES_KANBAN_CLAIM_LOCK":"native-claim","HERMES_KANBAN_BOARD":"board-a"}.items():
            monkeypatch.setenv(k,v)
        monkeypatch.setenv(key,"forged-value")
        with pytest.raises(AuthorityDenied):
            wire.admit_worker_registration("native-worker-session")
    finally:
        client.close()
        launch.close()


@pytest.mark.parametrize("kind",["keyboard","async","future"])
def test_native_channel_cancellation_has_native_control_flow_and_no_payload(stack,kind):
    from asyncio import CancelledError as AsyncCancel
    from concurrent.futures import CancelledError as FutureCancel
    launch,client=registered_channel(stack)
    original=stack.host.context.packet
    error={"keyboard":KeyboardInterrupt,"async":AsyncCancel,"future":FutureCancel}[kind]
    def cancel(*a,**kw):
        raise error("SYNTHETIC-PRIVATE-ERROR-MUST-NOT-ESCAPE")
    stack.host.context.packet=cancel
    try:
        with pytest.raises(error) as caught:
            client.resolve("native-worker-session","task")
        assert caught.value.args==()
    finally:
        stack.host.context.packet=original
        client.close()
        launch.close()


@pytest.mark.parametrize("mismatch",["reclaimed","other-board"])
def test_real_registration_refuses_changed_claim_or_database_before_write(stack,native_candidate,tmp_path,mismatch):
    launch=asyncio.run(stack.authenticated(lambda:nh.prepare_worker("task","board-a")))
    launch.spawned(os.getpid())
    if mismatch=="reclaimed":
        stack.update("UPDATE tasks SET current_run_id=2,claim_lock='new-claim'")
    path=tmp_path/"unrelated.sqlite" if mismatch=="other-board" else stack.db
    calls=[]
    kb=NS(write_txn=lambda c:c,_current_run_id=lambda *a:1,_append_event=lambda *a,**kw:calls.append(True))
    register=function(native_candidate["hermes_cli/kanban_db_dispatch.py"][1],"_set_worker_pid",
        _kb=kb,_process_fingerprint=lambda pid:"start-a",UNVERIFIED_WORKER_FINGERPRINT="unverified")
    conn=sqlite3.connect(path)
    try:
        def attempt():
            with pytest.raises(AuthorityDenied):register(conn,"task",os.getpid())
        asyncio.run(stack.authenticated(attempt))
        assert calls==[]
        probe=sqlite3.connect(stack.db)
        try:assert probe.execute("SELECT worker_pid FROM tasks WHERE id='task'").fetchone()==(None,)
        finally:probe.close()
    finally:conn.close();launch.close()


def test_actual_registry_return_revalidates_native_identity_and_policy(stack,native_candidate,monkeypatch):
    from wiki_core import runtime_authority as auth
    launch,client=registered_channel(stack)
    gate=Authority(client)
    monkeypatch.setattr(auth,"_host",gate)
    args={"resource":"source","query":"public capabilities"}
    observed=[]
    def handler(args):
        entry=replace(stack.enrollment,grant=replace(stack.enrollment.grant,revoked=True))
        stack.owner.replace(nh.RegistrySnapshot("registry-2",(entry,)),expected_revision="registry-1")
        return "SYNTHETIC-RESULT-MUST-NOT-ESCAPE"
    registry=NS(get_entry=lambda *a,**kw:NS(handler=handler,is_async=False),
        _normalize_handler_result=lambda *a:observed.append(a) or a[-1])
    dispatch=function(native_candidate["tools/registry.py"][1],"dispatch",_kwargs_accepted_by=lambda *a:{})
    try:
        gate.admit("native-worker-session","task")
        with pytest.raises(AuthorityDenied):
            dispatch(registry,"read_public",args,session_id="native-worker-session",task_id="task")
        assert observed==[]
    finally:
        client.close()
        launch.close()
