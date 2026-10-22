"""Inactive native controller authority: authenticated ingress, native rows, one run.

No file/env policy loader, credential reader, provider adapter or task writer.
Only the controller owns the registry publisher. Workers receive a read-only
process-bound endpoint (native_host_wire), never this publisher or its snapshot.
"""
from __future__ import annotations

from contextvars import ContextVar
from contextlib import contextmanager
from concurrent.futures import CancelledError as FutureCancelled
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from urllib.parse import quote
import sqlite3
import threading
import time

from .runtime_authority import AuthorityDenied, Mandate, Principal, sha
from .native_projection import Correlation, ProjectionHold, project_native_task

_SEAL = object()
_ingress = ContextVar("wiki_native_authenticated_ingress", default=None)


@dataclass(frozen=True)
class NativeActor:
    requester: str
    provider: str
    expires_at: int
    _seal: object
    org_id: str = ""


@dataclass(frozen=True)
class NativeGrant:
    """Operator task policy; a worker session is bound by native construction."""
    bot: str
    requester: str
    profile: str
    task: str
    action: str
    run: str
    claim: str
    revision: str
    packet_sha256: str
    refs: tuple
    operations: tuple
    expires_at: int
    lease_until: int
    native_grant: bool = False
    stopped: bool = False
    approval_pending: bool = False
    revoked: bool = False

    def mandate(self, native_session):
        return Mandate(Principal(self.bot, self.requester, self.profile, native_session,
            self.task, self.action, self.run, self.claim), self.revision, self.packet_sha256,
            self.refs, self.operations, self.expires_at, self.lease_until,
            self.native_grant, self.stopped, self.approval_pending, self.revoked)


@dataclass(frozen=True)
class Enrollment:
    board: str
    intent_id: str
    auth_provider: str
    grant: NativeGrant
    auth_org: str = ""


@dataclass(frozen=True)
class RegistrySnapshot:
    revision: str
    entries: tuple[Enrollment, ...]


class RegistryReader:
    """Read-only interface handed to the controller, not to the worker."""
    __slots__ = ("__read",)

    def __init__(self, read, seal):
        if seal is not _SEAL:
            raise AuthorityDenied("authority_protected_registry_required")
        self.__read = read

    def snapshot(self):
        snapshot = self.__read()
        if type(snapshot) is not RegistrySnapshot or not snapshot.revision or type(snapshot.entries) is not tuple:
            raise AuthorityDenied("authority_invalid_registry")
        for entry in snapshot.entries:
            if type(entry) is not Enrollment or type(entry.grant) is not NativeGrant:
                raise AuthorityDenied("authority_invalid_registry")
            grant = entry.grant
            if (type(entry.auth_org) is not str or any(type(v) is not str or not v for v in (entry.board, entry.intent_id, entry.auth_provider,
                    grant.bot, grant.requester, grant.profile, grant.task, grant.action, grant.run, grant.claim,
                    grant.revision, grant.packet_sha256))
                    or any(type(v) is not bool for v in (grant.native_grant, grant.stopped, grant.approval_pending, grant.revoked))
                    or type(grant.refs) is not tuple or type(grant.operations) is not tuple):
                raise AuthorityDenied("authority_invalid_registry")
        return snapshot


class RegistryPublisher:
    """Host-only in-memory publisher; no HTTP/tool/RPC registration or grants.

    A future trusted host adoption supplies its approved snapshot. This class
    does not make a worker-writable config or Managed Scope into a registry.
    """
    def __init__(self, snapshot: RegistrySnapshot):
        self.__lock = threading.RLock()
        self.__snapshot = snapshot
        self.reader = RegistryReader(self._read, _SEAL)
        self.reader.snapshot()

    def _read(self):
        with self.__lock:
            return self.__snapshot

    def replace(self, snapshot: RegistrySnapshot, *, expected_revision: str):
        with self.__lock:
            if self.__snapshot.revision != expected_revision or snapshot.revision == expected_revision:
                raise AuthorityDenied("authority_registry_revision_mismatch")
            if type(snapshot) is not RegistrySnapshot or not snapshot.revision or type(snapshot.entries) is not tuple:
                raise AuthorityDenied("authority_invalid_registry")
            self.__snapshot = snapshot


class NativeBoardReader:
    """Trusted host board map; opens existing native DBs read-only, no migrations."""
    def __init__(self, boards):
        self._boards = MappingProxyType({key: Path(path).resolve() for key, path in boards.items()})

    def __call__(self, board):
        if board not in self._boards:
            raise AuthorityDenied("authority_native_board_required")
        conn = sqlite3.connect("file:" + quote(str(self._boards[board])) + "?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        return conn


async def serve_verified_session(session, request, call_next):
    """Called ONLY at native middleware's already-verified Session branches.

    Reads identity/expiry metadata, never access_token/refresh_token/cookies.
    Loopback bypass and TokenPrincipal routes do not mint this attestation.
    """
    from hermes_cli.dashboard_auth.base import Session
    if not isinstance(session, Session):
        raise AuthorityDenied("authority_authenticated_controller_required")
    actor = NativeActor(session.user_id, session.provider, session.expires_at, _SEAL, session.org_id)
    host = getattr(request.app.state, "wiki_native_host", None)
    if host is not None and not isinstance(host, NativeHost):
        raise AuthorityDenied("authority_protected_host_required")
    token = _ingress.set((host, actor))
    try:
        return await call_next(request)
    finally:
        _ingress.reset(token)


def current_controller():
    value = _ingress.get()
    if value is None or not isinstance(value[0], NativeHost) or value[1]._seal is not _SEAL:
        raise AuthorityDenied("authority_authenticated_controller_required")
    return value


class NativeHost:
    """Controller-owned concrete resolver over native read-only SQLite readers.

    kb is the existing native kanban_db module; connect returns a read-only
    connection pinned by the trusted host to the explicit board. context is the
    existing Wiki context source, not a policy or identity callback.
    """
    def __init__(self, registry: RegistryReader, *, connect, kb, workflow, context, clock=time.time):
        if type(registry) is not RegistryReader:
            raise AuthorityDenied("authority_protected_registry_required")
        self.registry, self.connect, self.kb = registry, connect, kb
        self.workflow, self.context, self.clock = workflow, context, clock
        self._channels = {}
        self._lock = threading.RLock()

    def close(self):
        for channel in list(self._channels.values()):
            channel.close()

    def enrollment(self, actor: NativeActor, task: str, board: str, *, live=True):
        if (type(actor) is not NativeActor or actor._seal is not _SEAL or not actor.requester
                or not actor.provider or type(actor.org_id) is not str):
            raise AuthorityDenied("authority_authenticated_controller_required")
        if type(actor.expires_at) is not int or actor.expires_at <= self.clock():
            raise AuthorityDenied("authority_controller_expired")
        if not task or not board:
            raise AuthorityDenied("authority_native_binding_required")
        snapshot = self.registry.snapshot()
        matches = [e for e in snapshot.entries if type(e) is Enrollment and e.board == board
                   and e.grant.task == task and e.auth_provider == actor.provider
                   and e.auth_org == actor.org_id
                   and e.grant.requester == actor.requester]
        if len(matches) != 1:
            raise AuthorityDenied("authority_operator_mandate_required")
        entry = matches[0]
        m = entry.grant
        if type(m) is not NativeGrant or m.native_grant is not True or m.revoked or m.stopped or m.approval_pending:
            raise AuthorityDenied("authority_native_hold")
        if m.expires_at <= self.clock() or (live and m.lease_until <= self.clock()) or not entry.intent_id:
            raise AuthorityDenied("authority_claim_expired")
        # Registry revision is part of every mandate, not a worker-selected hash.
        return entry, replace(m, revision=sha([snapshot.revision, m.revision]),
                              expires_at=min(m.expires_at, actor.expires_at))

    def rows(self, entry: Enrollment):
        p = entry.grant
        conn = None
        try:
            conn = self.connect(entry.board)
            conn.execute("BEGIN")
            # Native metadata-only branches exclude title/body/result/summary,
            # even before creating a Python Task/Run object.
            task = self.kb.get_task(conn, p.task, metadata_only=True)
            run = self.kb.get_run(conn, int(p.run), metadata_only=True)
            if task is None or run is None:
                raise AuthorityDenied("authority_native_binding_unknown")
            return dict(task), dict(run)
        except AuthorityDenied:
            raise
        except FutureCancelled:
            raise FutureCancelled() from None
        except Exception:
            raise AuthorityDenied("authority_native_snapshot_unavailable") from None
        finally:
            if conn is not None:
                conn.close()

    def validate(self, channel, *, live=True):
        entry, grant = self.enrollment(channel.actor, channel.task, channel.board, live=live)
        if entry != channel.entry or grant.revision != channel.policy_revision:
            raise AuthorityDenied("authority_native_binding_changed")
        task, run = self.rows(entry)
        if not channel.session:
            raise AuthorityDenied("authority_native_session_unbound")
        mandate = grant.mandate(channel.session)
        p = mandate.principal
        closed_native_run = task["current_run_id"] is None and run["ended_at"] is not None
        if ((str(task["current_run_id"]) != p.run and not (not live and closed_native_run))
                or str(run["id"]) != p.run or run["task_id"] != p.task
                or task["assignee"] != p.profile or run["profile"] != p.profile
                or task["idempotency_key"] != entry.intent_id):
            raise AuthorityDenied("authority_native_binding_changed")
        if (not isinstance(run["claim_lock"], str) or not run["claim_lock"]
                or sha(run["claim_lock"]) != p.claim
                or (not closed_native_run and (not isinstance(task["claim_lock"], str)
                    or not task["claim_lock"] or sha(task["claim_lock"]) != p.claim))):
            raise AuthorityDenied("authority_native_claim_changed")
        # Historical metadata stays tied to the originally registered native
        # worker. Its process need not remain alive after native completion.
        if (channel.pid is None or run["worker_pid"] != channel.pid
                or not channel.fingerprint or run["worker_started_at"] != channel.fingerprint):
            raise AuthorityDenied("authority_native_worker_unverified")
        if live:
            if (task["status"] != "running" or run["status"] != "running" or run["ended_at"] is not None
                    or channel.pid is None or task["worker_pid"] != channel.pid or run["worker_pid"] != channel.pid
                    or not channel.fingerprint or task["worker_started_at"] != channel.fingerprint
                    or run["worker_started_at"] != channel.fingerprint or not self.kb._claim_is_live(task)):
                raise AuthorityDenied("authority_native_worker_unverified")
            expiries = [task["claim_expires"], run["claim_expires"], mandate.lease_until]
            if any(type(v) is not int or v <= self.clock() for v in expiries):
                # No reclaim/heartbeat here. Native code owns renewal/liveness.
                raise AuthorityDenied("authority_claim_expired")
            mandate = replace(mandate, lease_until=min(expiries))
            approved = dict(mandate.refs)
            def authorize_ref(path, digest):
                if path not in approved or (digest and approved[path] != digest):
                    raise AuthorityDenied("authority_context_ref_denied")
            packet = self.context.packet(mandate, authorize_ref)
            if packet.get("context_sha256") != mandate.packet_sha256:
                raise AuthorityDenied("authority_context_changed")
        return mandate, task, run

    def _launch_state(self, actor, task, board):
        entry, grant = self.enrollment(actor, task, board)
        task_row, run = self.rows(entry)
        p = entry.grant
        if (task_row["status"] != "running" or run["status"] != "running" or run["ended_at"] is not None
                or str(task_row["current_run_id"]) != p.run or run["task_id"] != task
                or task_row["assignee"] != p.profile or run["profile"] != p.profile
                or not task_row["claim_lock"] or not run["claim_lock"]
                or sha(task_row["claim_lock"]) != p.claim or sha(run["claim_lock"]) != p.claim
                or task_row["worker_pid"] is not None or run["worker_pid"] is not None
                or task_row["idempotency_key"] != entry.intent_id
                or any(type(v) is not int or v <= self.clock() for v in (task_row["claim_expires"], run["claim_expires"]))):
            raise AuthorityDenied("authority_native_launch_unqualified")
        return entry, grant

    def before_spawn(self, channel):
        entry, grant = self._launch_state(channel.actor, channel.task, channel.board)
        if entry != channel.entry or grant.revision != channel.policy_revision:
            raise AuthorityDenied("authority_native_binding_changed")

    def launch(self, actor, task, board):
        entry, grant = self._launch_state(actor, task, board)
        from .native_host_wire import Launch
        with self._lock:
            if task in self._channels:
                raise AuthorityDenied("authority_native_run_already_bound")
            channel = Launch(self, actor, entry, grant.revision)
            self._channels[task] = channel
            return channel

    def registered(self, task, pid, fingerprint):
        with self._lock:
            channel = self._channels.get(task)
            if channel is None or channel.pid != pid or not fingerprint:
                raise AuthorityDenied("authority_native_worker_unverified")
            channel.fingerprint = fingerprint
            # Session is bound by the real native constructor only after the
            # registered worker's kernel peer PID is verified on the channel.
            channel.ready.set()

    def before_registration(self, actor, task, pid, connection):
        channel = self._channels.get(task)
        if channel is None or channel.actor != actor or channel.pid != pid:
            raise AuthorityDenied("authority_native_worker_unverified")
        self.before_spawn(channel)
        reader = self.connect(channel.board)
        try:
            expected = next(row[2] for row in reader.execute("PRAGMA database_list") if row[1] == "main")
            actual = next(row[2] for row in connection.execute("PRAGMA database_list") if row[1] == "main")
            if not expected or Path(actual).resolve() != Path(expected).resolve():
                raise AuthorityDenied("authority_native_board_required")
        finally:
            reader.close()
        row, _ = self.rows(channel.entry)
        return int(channel.entry.grant.run), row["claim_lock"]

    def projection(self, channel):
        # Projection is an explicit independently permitted metadata operation.
        mandate, task, run = self.validate(channel, live=False)
        args = {"task": channel.task, "intent": channel.entry.intent_id}
        op = _operation(mandate, "native_projection", args)
        if (op.kind != "projection" or op.sensitivity != "public" or op.binding is not None
                or "native_relay" not in op.disclosure_surfaces or not op.destination):
            raise AuthorityDenied("authority_audience_denied")
        p = mandate.principal
        correlation = Correlation(p.action, p.task, p.run, p.claim, channel.entry.intent_id)
        native = {"wiki_action_id": p.action, "task_id": p.task, "run_id": p.run, "claim_id": p.claim,
                  "intent_id": channel.entry.intent_id, "status": task["status"],
                  "revision": sha([task, run, mandate.revision]), "delivery": "unknown",
                  "claim_live": bool(self.kb._claim_is_live(task))}
        columns = tuple(c["key"] for c in self.workflow.to_dict()["columns"])
        try:
            result = project_native_task(correlation, native, authorize=lambda *_: None, native_columns=columns)
        except ProjectionHold:
            # A native terminal column alone proves no source effect/ACK.
            result = {"wiki_action_id": p.action, "task_id": p.task, "run_id": p.run,
                      "claim_id": p.claim, "intent_id": channel.entry.intent_id,
                      "native_revision": native["revision"], "native_status": task["status"],
                      "delivery": "unknown", "reconcile_required": True, "retry_authorized": False}
        self.validate(channel, live=False)
        result["projection_id"] = sha(result)
        return result


def _operation(mandate, tool, arguments):
    matches = [op for op in mandate.operations if op.tool == tool and op.arguments_sha256 == sha(arguments)]
    if len(matches) != 1:
        raise AuthorityDenied("authority_operation_denied")
    return matches[0]


class ChannelBackend:
    """Real controller-side backend used by Authority before packet materialization."""
    def __init__(self, channel):
        self.channel = channel

    def resolve(self, session, task):
        mandate, _, _ = self.channel.host.validate(self.channel)
        if (session, task) != (mandate.principal.session, mandate.principal.task):
            raise AuthorityDenied("authority_principal_mismatch")
        return mandate

    def packet(self, mandate, authorize_ref):
        current = self.resolve(mandate.principal.session, mandate.principal.task)
        if current != mandate:
            raise AuthorityDenied("authority_changed")
        packet = self.channel.host.context.packet(mandate, authorize_ref)
        self.resolve(mandate.principal.session, mandate.principal.task)
        return packet

    def operation(self, mandate, tool, arguments, phase):
        self.resolve(mandate.principal.session, mandate.principal.task)
        return _operation(mandate, tool, arguments)


def prepare_worker(task, board):
    host, actor = current_controller()
    return host.launch(actor, task, board)


def register_worker(task, pid, fingerprint):
    host, _ = current_controller()
    host.registered(task, pid, fingerprint)


def before_worker_registration(task, pid, connection):
    host, actor = current_controller()
    return host.before_registration(actor, task, pid, connection)


@dataclass(frozen=True)
class NativeHostProvider:
    """Host-owned startup object, never parsed from a worker request or config."""
    registry: RegistryReader
    boards: tuple
    context: object


@contextmanager
def native_host_scope(app):
    """Real dashboard lifespan hook. Missing trust holds reads, not the UI."""
    app.state.wiki_native_host = None
    provider = getattr(app.state, "wiki_native_host_provider", None)
    if provider is None:
        app.state.wiki_native_hold_code = "authority_protected_registry_required"
    elif type(provider) is not NativeHostProvider or type(provider.registry) is not RegistryReader:
        app.state.wiki_native_hold_code = "authority_invalid_registry"
    else:
        try:
            provider.registry.snapshot()
            from hermes_cli import kanban_db
            from hermes_cli.kanban_workflow import DEFAULT_WORKFLOW
            app.state.wiki_native_host = NativeHost(provider.registry, connect=NativeBoardReader(dict(provider.boards)),
                kb=kanban_db, workflow=DEFAULT_WORKFLOW, context=provider.context)
            app.state.wiki_native_hold_code = None
        except FutureCancelled:
            raise FutureCancelled() from None
        except Exception:
            app.state.wiki_native_hold_code = "authority_protected_registry_required"
    try:
        yield
    finally:
        host = app.state.wiki_native_host
        if host is not None:
            host.close()
        app.state.wiki_native_host = None
