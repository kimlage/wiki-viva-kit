"""Inactive, transport-neutral Hermes kernel candidate.

The host supplies the live operator registry and native identity/claim resolver.
Nothing here loads a policy from the wiki, issues grants, or resolves credentials.
No host backend is installed by the kit. Missing authority always denies.
This file is also the source of tools/wiki_authority.py in the 711 kernel patch.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from asyncio import CancelledError as AsyncCancelledError
from concurrent.futures import CancelledError as FutureCancelledError
import hashlib
import json
import time
from typing import Callable, Protocol


class AuthorityDenied(PermissionError):
    """Stable, content-free failure safe to return through a shared surface."""

    def __init__(self, code: str):
        super().__init__(code)
        # A policy failure raised while handling a private exception must not
        # chain that exception into a logger, callback or model-facing traceback.
        self.__suppress_context__ = True


def sha(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class Principal:
    bot: str
    requester: str
    profile: str
    session: str
    task: str
    action: str
    run: str
    claim: str


@dataclass(frozen=True)
class NativeBinding:
    connection: str
    account: str
    revision: str
    # Only a trusted native resolver may report these. Labels are not evidence.
    identity_proven: bool = False
    account_enforced: bool = False
    inherited: bool = False


@dataclass(frozen=True)
class Operation:
    tool: str
    arguments_sha256: str
    resource: str
    action: str
    purpose: str
    destination: str
    model: str
    sensitivity: str = "public"
    kind: str = "read"
    binding: NativeBinding | None = None
    disclosure_surfaces: tuple[str, ...] = ()


@dataclass(frozen=True)
class Mandate:
    principal: Principal
    revision: str
    packet_sha256: str
    refs: tuple[tuple[str, str], ...]
    operations: tuple[Operation, ...]
    expires_at: float
    lease_until: float
    native_grant: bool = False
    stopped: bool = False
    approval_pending: bool = False
    revoked: bool = False


class Backend(Protocol):
    """Trusted host only. Implemented outside worker-writable source/config.

    resolve re-reads native session/worker/claim and the operator registry;
    operation resolves actual arguments/resources/destinations, never model
    claims of identity. packet must authorize_ref BEFORE materializing each ref.
    Every binding revision must come from the effective native transport.
    """

    def resolve(self, session: str, task: str) -> Mandate: ...
    def packet(self, mandate: Mandate, authorize_ref: Callable) -> dict: ...
    def operation(self, mandate: Mandate, tool: str, arguments: dict, phase: str) -> Operation: ...


@dataclass(frozen=True)
class Admission:
    principal: Principal
    revision: str
    packet_sha256: str
    refs: tuple[tuple[str, str], ...]
    operations: tuple[Operation, ...]


class Authority:
    def __init__(self, backend: Backend, *, clock=time.time):
        self._backend = backend
        self._clock = clock
        self._current: ContextVar[Admission | None] = ContextVar("wiki_admission", default=None)

    def _live(self, session: str, task: str) -> Mandate:
        try:
            state = self._backend.resolve(session, task)
            if not isinstance(state, Mandate) or not isinstance(state.principal, Principal):
                raise AuthorityDenied("authority_unknown_principal")
            if any(not isinstance(v, str) or not v for v in vars(state.principal).values()):
                raise AuthorityDenied("authority_unknown_principal")
            if state.principal.session != session or state.principal.task != task:
                raise AuthorityDenied("authority_principal_mismatch")
            if (any(type(v) is not bool for v in (state.native_grant, state.stopped, state.approval_pending, state.revoked))
                    or not isinstance(state.refs, tuple) or not isinstance(state.operations, tuple)):
                raise AuthorityDenied("authority_invalid_policy")
            if state.revoked or state.native_grant is not True:
                raise AuthorityDenied("authority_revoked")
            if state.stopped or state.approval_pending:
                raise AuthorityDenied("authority_native_hold")
            if not (self._clock() < state.expires_at and self._clock() < state.lease_until):
                raise AuthorityDenied("authority_claim_expired")
            if not state.revision or not state.packet_sha256 or not state.refs:
                raise AuthorityDenied("authority_context_required")
            if len(dict(state.refs)) != len(state.refs):
                raise AuthorityDenied("authority_context_invalid")
            return state
        except AuthorityDenied:
            raise
        except Exception:
            raise AuthorityDenied("authority_unavailable") from None

    def admit(self, session: str, task: str) -> str:
        # Clear old context even when admission/hook/packet fails on a reused thread.
        self._current.set(None)
        state = self._live(session, task)
        allowed = dict(state.refs)

        def authorize_ref(ref: str, revision: str):
            # Procedures have no snapshot row: authorize the path before reading,
            # then compare its digest before decoding/materializing the body.
            if ref not in allowed or (revision and allowed[ref] != revision):
                raise AuthorityDenied("authority_context_ref_denied")

        try:
            packet = self._backend.packet(state, authorize_ref)
            actual = packet.get("context_sha256")
            if actual != state.packet_sha256 or actual != sha({k: v for k, v in packet.items() if k != "context_sha256"}):
                raise AuthorityDenied("authority_context_changed")
            refs = {p["path"]: p["content_sha256"] for p in packet["pages"] + packet["procedures"]}
            if refs != allowed or packet["profile"] != state.principal.profile:
                raise AuthorityDenied("authority_context_mismatch")
            if [a["action_id"] for a in packet["actions"]] != [state.principal.action] or packet.get("unresolved_context_refs"):
                raise AuthorityDenied("authority_context_mismatch")
            # Native policy/lease can change during packet preparation.
            if self._live(session, task) != state:
                raise AuthorityDenied("authority_changed")
            self._current.set(Admission(state.principal, state.revision, actual, state.refs, state.operations))
            return json.dumps(packet, sort_keys=True, ensure_ascii=False)
        except AuthorityDenied:
            raise
        except Exception:
            raise AuthorityDenied("authority_context_unavailable") from None

    def require(self, tool: str, arguments: dict, *, phase: str = "effect",
                session: str | None = None, task: str | None = None,
                surface: str | None = None) -> Operation:
        admitted = self._current.get()
        if admitted is None:
            raise AuthorityDenied("authority_admission_required")
        if ((session is not None and session != admitted.principal.session)
                or (task is not None and task != admitted.principal.task)):
            raise AuthorityDenied("authority_principal_mismatch")
        state = self._live(admitted.principal.session, admitted.principal.task)
        if (state.principal != admitted.principal or state.revision != admitted.revision
                or state.packet_sha256 != admitted.packet_sha256 or state.refs != admitted.refs
                or state.operations != admitted.operations):
            raise AuthorityDenied("authority_changed")
        if phase not in {"effect", "disclose"}:
            raise AuthorityDenied("authority_phase_denied")
        try:
            op = self._backend.operation(state, tool, arguments, phase)
            if not isinstance(op, Operation) or op not in state.operations:
                raise AuthorityDenied("authority_operation_denied")
            if op.tool != tool or op.arguments_sha256 != sha(arguments):
                raise AuthorityDenied("authority_arguments_changed")
            if surface is not None and (phase != "disclose" or not isinstance(op.disclosure_surfaces, tuple)
                                        or surface not in op.disclosure_surfaces):
                raise AuthorityDenied("authority_audience_denied")
            if (not all((op.resource, op.action, op.purpose, op.destination, op.model))
                    or op.kind not in {"read", "context", "catalog", "projection", "relay", "model"}
                    or op.sensitivity not in {"public", "private"}):
                raise AuthorityDenied("authority_surface_denied")
            if op.sensitivity == "private":
                b = op.binding
                if (not isinstance(b, NativeBinding) or not all((b.connection, b.account, b.revision))
                        or b.identity_proven is not True or b.account_enforced is not True or b.inherited is not False):
                    raise AuthorityDenied("authority_account_enforcement_required")
            elif op.binding is not None:
                # The public control never resolves a private source credential.
                raise AuthorityDenied("authority_public_credential_denied")
            # Recheck after resource/account resolution, before invoking the handler.
            if self._live(admitted.principal.session, admitted.principal.task) != state:
                raise AuthorityDenied("authority_changed")
            return op
        except AuthorityDenied:
            raise
        except Exception:
            raise AuthorityDenied("authority_unavailable") from None

    def require_agent(self, tool: str, arguments: dict, agent, *, task: str,
                      phase: str = "effect", surface: str | None = None) -> Operation:
        """Confront the concrete native caller, never identity inside tool args.

        agent and task are supplied by native server/worker entry points. Missing
        identity cannot fall back to a nonempty inherited ContextVar.
        """
        session = getattr(agent, "session_id", None)
        if not isinstance(session, str) or not session or not isinstance(task, str) or not task:
            raise AuthorityDenied("authority_concrete_identity_required")
        return self.require(tool, arguments, phase=phase, session=session, task=task, surface=surface)

    def invoke(self, tool: str, arguments: dict, execute: Callable, *, session: str, task: str):
        """Final handler boundary, including safe error/cancel disclosure.

        An uncertain effect stays uncertain. No exception body is logged or
        returned, and this wrapper never retries or creates another operation.
        """
        self.require(tool, arguments, session=session, task=task)
        try:
            result = execute(arguments)
        except BaseException as error:
            self.require(tool, arguments, phase="disclose", session=session, task=task, surface="tool_return")
            if isinstance(error, AuthorityDenied):
                raise error from None
            if isinstance(error, KeyboardInterrupt):
                raise KeyboardInterrupt() from None
            if isinstance(error, SystemExit):
                raise SystemExit(1) from None
            if isinstance(error, (AsyncCancelledError, FutureCancelledError)):
                raise type(error)() from None
            if not isinstance(error, Exception):
                raise AuthorityDenied("authority_execution_abandoned") from None
            return safe_tool_failure()
        self.require(tool, arguments, phase="disclose", session=session, task=task, surface="tool_return")
        return result

    def invoke_agent(self, tool: str, arguments: dict, execute: Callable, agent, *, task: str):
        self.require_agent(tool, arguments, agent, task=task)
        try:
            result = self.invoke(tool, arguments, execute, session=agent.session_id, task=task)
        except BaseException:
            # The agent object itself may have changed during an await/callback.
            self.require_agent(tool, arguments, agent, task=task, phase="disclose", surface="tool_return")
            raise
        self.require_agent(tool, arguments, agent, task=task, phase="disclose", surface="tool_return")
        return result


def safe_tool_failure() -> str:
    return json.dumps({"error": "tool_execution_failed", "effect_disposition": "unknown",
                       "retry_authorized": False}, sort_keys=True)


# Wired once by a trusted native bootstrap in a FUTURE reviewed adoption.
# It is intentionally absent from the plugin, iframe and wiki API.
_host: Authority | None = None


def install_host_backend(backend: Backend) -> None:
    global _host
    if _host is not None:
        raise AuthorityDenied("authority_already_installed")
    _host = Authority(backend)


def admit(session: str, task: str) -> str:
    if _host is None:
        raise AuthorityDenied("authority_unavailable")
    return _host.admit(session, task)


def require(tool: str, arguments: dict, *, phase: str = "effect",
            session: str | None = None, task: str | None = None, surface: str | None = None) -> Operation:
    if _host is None:
        raise AuthorityDenied("authority_unavailable")
    return _host.require(tool, arguments, phase=phase, session=session, task=task, surface=surface)


def require_agent(tool: str, arguments: dict, agent, *, task: str, phase: str = "effect", surface: str | None = None) -> Operation:
    if _host is None:
        raise AuthorityDenied("authority_unavailable")
    return _host.require_agent(tool, arguments, agent, task=task, phase=phase, surface=surface)


def invoke(tool: str, arguments: dict, execute: Callable, *, session: str, task: str):
    if _host is None:
        raise AuthorityDenied("authority_unavailable")
    return _host.invoke(tool, arguments, execute, session=session, task=task)


def invoke_agent(tool: str, arguments: dict, execute: Callable, agent, *, task: str):
    if _host is None:
        raise AuthorityDenied("authority_unavailable")
    return _host.invoke_agent(tool, arguments, execute, agent, task=task)
