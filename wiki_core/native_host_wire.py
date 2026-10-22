"""Inactive process-bound local handoff inside the existing Hermes controller.

No HTTP endpoint, provider connector, credential, serialized actor or update RPC.
The Unix peer PID comes from the kernel, not from the request/environment. A
wrapper that changes the native parent, unsupported peer credentials, missing
registration, lost connection or uncertain delivery all fail closed.
"""
from __future__ import annotations

from dataclasses import asdict
from asyncio import CancelledError as AsyncCancelled
from concurrent.futures import CancelledError as FutureCancelled
import json
import os
from pathlib import Path
import re
import socket
import struct
import sys
import tempfile
import threading

from .runtime_authority import (Authority, AuthorityDenied, Mandate, NativeBinding,
                                Operation, Principal, install_host_backend, admit, sha)
from .native_host import ChannelBackend
from .native_startup_guard import protected_worker, restrict_worker, require_secret_materialization

_ENV = "HERMES_WIKI_NATIVE_CHANNEL"
_MAX = 2_000_000
_client = None


def prepare_cli_startup(args):
    if _client is not None:
        restrict_worker()
    if not protected_worker():
        return False
    if getattr(args, "yolo", False) or getattr(args, "accept_hooks", False):
        raise AuthorityDenied("authority_startup_approval_unqualified")
    # Real CLI startup precedes discovery, hook config and agent construction.
    # The session minted here is reused by native CLI mutable-state setup.
    bootstrap_agent(getattr(args, "resume", None))
    return True


def prepared_cli_session(requested_resume):
    if not protected_worker():
        return None
    return bootstrap_agent(requested_resume)


def require_mcp_connection_authority():
    require_secret_materialization()


def _cancel(error):
    if isinstance(error, KeyboardInterrupt): raise KeyboardInterrupt() from None
    if isinstance(error, SystemExit): raise SystemExit(1) from None
    if isinstance(error, (AsyncCancelled, FutureCancelled)): raise type(error)() from None


def peer_pid(connection):
    if sys.platform == "darwin":
        # Darwin SDK sys/un.h: SOL_LOCAL=0, LOCAL_PEERPID=0x002.
        return struct.unpack("i", connection.getsockopt(0, 0x002, 4))[0]
    if hasattr(socket, "SO_PEERCRED"):
        return struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[0]
    raise AuthorityDenied("authority_peer_identity_unavailable")


def _send(connection, value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    if len(raw) > _MAX:
        raise AuthorityDenied("authority_frame_invalid")
    connection.sendall(struct.pack("!I", len(raw)) + raw)


def _receive(connection):
    def exact(size):
        chunks = bytearray()
        while len(chunks) < size:
            data = connection.recv(size - len(chunks))
            if not data:
                raise AuthorityDenied("authority_delivery_unknown_no_retry")
            chunks.extend(data)
        return bytes(chunks)
    size = struct.unpack("!I", exact(4))[0]
    if not 0 < size <= _MAX:
        raise AuthorityDenied("authority_frame_invalid")
    result = json.loads(exact(size))
    if type(result) is not dict:
        raise AuthorityDenied("authority_frame_invalid")
    return result


def _mandate(data):
    data = dict(data)
    data["principal"] = Principal(**data["principal"])
    data["refs"] = tuple(tuple(row) for row in data["refs"])
    operations = []
    for op in data["operations"]:
        op = dict(op)
        op["disclosure_surfaces"] = tuple(op["disclosure_surfaces"])
        if op.get("binding") is not None:
            op["binding"] = NativeBinding(**op["binding"])
        operations.append(Operation(**op))
    data["operations"] = tuple(operations)
    return Mandate(**data)


class Launch:
    def __init__(self, host, actor, entry, policy_revision):
        if os.name != "posix" or not hasattr(socket, "AF_UNIX"):
            raise AuthorityDenied("authority_native_transport_unqualified")
        self.host, self.actor, self.entry = host, actor, entry
        self.policy_revision = policy_revision
        self.task, self.board = entry.grant.task, entry.board
        self.pid = self.fingerprint = None
        self.session = None
        self._peer = None
        self._connection = None
        self.ready = threading.Event()
        self.closed = threading.Event()
        self._dir = tempfile.TemporaryDirectory(prefix="hermes-wiki-channel-")
        self.path = str(Path(self._dir.name) / "authority.sock")
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._socket.settimeout(30)
        self._socket.bind(self.path)
        self._socket.listen(1)
        self._thread = threading.Thread(target=self._serve, name="hermes-wiki-authority", daemon=True)
        self._thread.start()

    def __enter__(self):
        return self

    def __exit__(self, kind, error, tb):
        if kind is not None or self.pid is None:
            self.close()

    def configure(self, env):
        # A routing hint only; neither its path nor any env claim authenticates.
        env[_ENV] = self.path

    def qualify(self, before, after):
        if before != after:
            raise AuthorityDenied("authority_native_wrapper_unqualified")

    def spawned(self, pid):
        if type(pid) is not int or pid <= 0 or self.pid is not None:
            raise AuthorityDenied("authority_native_worker_unverified")
        self.pid = pid

    def before_spawn(self):
        if self.closed.is_set():
            raise AuthorityDenied("authority_native_channel_unverified")
        self.host.before_spawn(self)

    def close(self):
        self.closed.set()
        self.ready.set()
        self._socket.close()
        if self._connection is not None:
            try:
                self._connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._connection.close()
        self._dir.cleanup()
        with self.host._lock:
            if self.host._channels.get(self.task) is self:
                self.host._channels.pop(self.task)

    def _serve(self):
        try:
            connection, _ = self._socket.accept()
            with connection:
                self._connection = connection
                if not self.ready.wait(5) or self.closed.is_set() or peer_pid(connection) != self.pid:
                    raise AuthorityDenied("authority_native_worker_unverified")
                self._peer = self.pid
                connection.settimeout(None)
                seq = 0
                while not self.closed.is_set():
                    request = _receive(connection)
                    if request.get("seq") != seq + 1:
                        raise AuthorityDenied("authority_request_replayed")
                    seq += 1
                    try:
                        result = self._dispatch(request)
                        _send(connection, {"seq": seq, "result": result})
                    except AuthorityDenied as error:
                        code = str(error)
                        if not re.fullmatch(r"authority_[a-z0-9_]{1,80}", code):
                            code = "authority_native_failure_unknown_no_retry"
                        _send(connection, {"seq": seq, "error": code})
                        break
                    except (KeyboardInterrupt, SystemExit, AsyncCancelled, FutureCancelled) as error:
                        kind = "keyboard" if isinstance(error, KeyboardInterrupt) else "exit" if isinstance(error, SystemExit) else "async" if isinstance(error, AsyncCancelled) else "future"
                        _send(connection, {"seq": seq, "cancelled": kind})
                        break
        except BaseException:
            # No error object, payload, traceback or peer-supplied value logged.
            pass
        finally:
            self.close()

    def _dispatch(self, request):
        if self.pid is None or self._peer != self.pid:
            raise AuthorityDenied("authority_native_worker_unverified")
        backend = ChannelBackend(self)
        method = request.get("method")
        if method == "bootstrap":
            proposed = request.get("session")
            if not isinstance(proposed, str) or not proposed or len(proposed) > 256:
                raise AuthorityDenied("authority_native_session_unbound")
            if self.session is not None and self.session != proposed:
                raise AuthorityDenied("authority_principal_mismatch")
            self.session = proposed
        if self.session is None:
            raise AuthorityDenied("authority_native_session_unbound")
        p = self.entry.grant.mandate(self.session).principal
        if method != "bootstrap" and (request.get("session"), request.get("task")) != (p.session, p.task):
            raise AuthorityDenied("authority_principal_mismatch")
        if method == "projection":
            return self.host.projection(self)
        mandate = backend.resolve(p.session, p.task)
        if method == "bootstrap":
            return {"mandate": asdict(mandate), "board": self.board}
        if method == "resolve":
            result = asdict(mandate)
        elif method == "packet":
            # Existing Authority checks closure BEFORE context source reads.
            gate = Authority(backend, clock=self.host.clock)
            result = json.loads(gate.admit(p.session, p.task))
        elif method == "operation":
            result = asdict(backend.operation(mandate, request["tool"], request["arguments"], request["phase"]))
        else:
            raise AuthorityDenied("authority_rpc_denied")
        backend.resolve(p.session, p.task)
        return result


class WorkerBackend:
    def __init__(self, path, *, expected_controller_pid, native_session):
        self._connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._connection.settimeout(6)
        self._lock = threading.RLock()
        self._seq = 0
        self._closed = False
        try:
            self._connection.connect(path)
            if peer_pid(self._connection) != expected_controller_pid:
                raise AuthorityDenied("authority_controller_peer_mismatch")
            bootstrap = self._call("bootstrap", session=native_session)
            self.mandate = _mandate(bootstrap["mandate"])
            self.board = bootstrap["board"]
            if not isinstance(self.board, str) or not self.board:
                raise AuthorityDenied("authority_native_binding_required")
        except BaseException as error:
            self.close()
            _cancel(error)
            raise AuthorityDenied("authority_native_channel_unverified") from None

    def close(self):
        self._closed = True
        self._connection.close()

    def _call(self, method, **payload):
        with self._lock:
            if self._closed:
                raise AuthorityDenied("authority_delivery_unknown_no_retry")
            self._seq += 1
            known_denial = False
            try:
                _send(self._connection, {"seq": self._seq, "method": method, **payload})
                response = _receive(self._connection)
                if response.get("seq") != self._seq:
                    raise AuthorityDenied("authority_request_replayed")
                cancelled = response.get("cancelled")
                if cancelled == "keyboard": raise KeyboardInterrupt()
                if cancelled == "exit": raise SystemExit(1)
                if cancelled == "async": raise AsyncCancelled()
                if cancelled == "future": raise FutureCancelled()
                if cancelled is not None: raise AuthorityDenied("authority_frame_invalid")
                if "error" in response:
                    # Only fixed native authority codes cross the boundary.
                    if not isinstance(response["error"], str) or not re.fullmatch(r"authority_[a-z0-9_]{1,80}", response["error"]):
                        raise AuthorityDenied("authority_frame_invalid")
                    known_denial = True
                    raise AuthorityDenied(response["error"])
                return response["result"]
            except AuthorityDenied as error:
                self.close()
                if known_denial:
                    raise error from None
                raise AuthorityDenied("authority_delivery_unknown_no_retry") from None
            except BaseException as error:
                self.close()
                _cancel(error)
                raise AuthorityDenied("authority_delivery_unknown_no_retry") from None

    def resolve(self, session, task):
        return _mandate(self._call("resolve", session=session, task=task))

    def packet(self, mandate, authorize_ref):
        packet = self._call("packet", session=mandate.principal.session, task=mandate.principal.task)
        for page in packet["pages"] + packet["procedures"]:
            authorize_ref(page["path"], page["content_sha256"])
        return packet

    def operation(self, mandate, tool, arguments, phase):
        data = self._call("operation", session=mandate.principal.session, task=mandate.principal.task,
                          tool=tool, arguments=arguments, phase=phase)
        data["disclosure_surfaces"] = tuple(data["disclosure_surfaces"])
        if data.get("binding") is not None:
            data["binding"] = NativeBinding(**data["binding"])
        return Operation(**data)


def bootstrap_agent(requested_session):
    global _client
    if _client is not None:
        restrict_worker()
    protected_worker()
    if _client is None:
        path = os.environ.pop(_ENV, None)
        if not path:
            raise AuthorityDenied("authority_native_channel_required")
        from hermes_state_ids import new_session_id
        native_session = requested_session or new_session_id()
        _client = WorkerBackend(path, expected_controller_pid=os.getppid(), native_session=native_session)
        install_host_backend(_client)
    p = _client.mandate.principal
    if requested_session and requested_session != p.session:
        raise AuthorityDenied("authority_principal_mismatch")
    _client.resolve(p.session, p.task)
    admit(p.session, p.task)
    return p.session


def bound_task(agent, requested_task):
    if _client is None:
        raise AuthorityDenied("authority_native_channel_required")
    p = _client.mandate.principal
    if agent.session_id != p.session or (requested_task and requested_task != p.task):
        raise AuthorityDenied("authority_principal_mismatch")
    _client.resolve(p.session, p.task)
    return p.task


def project_native_result(agent, task):
    if _client is None:
        raise AuthorityDenied("authority_native_channel_required")
    p = _client.mandate.principal
    if getattr(agent, "session_id", None) != p.session or task != p.task:
        raise AuthorityDenied("authority_principal_mismatch")
    # Metadata-only result; no tool body/title/exception is sent on this RPC.
    # The host freshly validates ownership, current policy and audience without
    # requiring an already-ended worker to still have a live effect lease.
    return _client._call("projection", session=agent.session_id, task=task)


def admit_worker_registration(native_session):
    # Native env pins corroborate an already authenticated channel. They never
    # create identity, authority, a claim, or a fallback board/executor.
    bootstrap_agent(native_session)
    p = _client.mandate.principal
    if (os.environ.get("HERMES_KANBAN_TASK") != p.task
            or os.environ.get("HERMES_KANBAN_RUN_ID") != p.run
            or sha(os.environ.get("HERMES_KANBAN_CLAIM_LOCK")) != p.claim
            or os.environ.get("HERMES_KANBAN_BOARD") != _client.board):
        raise AuthorityDenied("authority_native_binding_changed")
    _client.resolve(p.session, p.task)
