"""Synthetic principals and native bindings only; no Hermes/provider imports."""
from dataclasses import FrozenInstanceError, replace
from contextvars import Context
import json
import importlib.util
import sys
import yaml

import pytest

from wiki_core import coordination
from wiki_core.host_authority import ReadOnlyHostBackend
from wiki_core.runtime_authority import (
    Authority, AuthorityDenied, Mandate, NativeBinding, Operation, Principal, sha,
)
from test_coordination import fixture


class Host:
    def __init__(self, root):
        self.root = root
        self.config, self.snapshot, _ = fixture(root)
        self.original = coordination.context_packet(root, self.config, self.snapshot, "research", "task")
        self.principal = Principal("research-bot", "requester-a", "research", "session-a", "task", "task", "run-a", "claim-a")
        self.args = {"resource": "source", "query": "public capabilities"}
        self.op = Operation("read_public", sha(self.args), "source", "read", "capabilities",
                            "reviewer-a", "model-a", disclosure_surfaces=("tool_return", "tool_observer", "tool_transform",
                                "native_store", "native_ui", "native_relay", "model_provider", "bot_relay"))
        refs = tuple((p["path"], p["content_sha256"]) for p in self.original["pages"] + self.original["procedures"])
        self.state = Mandate(self.principal, "policy-r1", self.original["context_sha256"], refs,
                             (self.op,), 200, 180, native_grant=True)
        self.materialized = []
        self.failure = False

    def resolve(self, session, task):
        if self.failure:
            raise RuntimeError("sensitive native diagnostic")
        return self.state

    def packet(self, mandate, authorize_ref):
        return coordination.context_packet(self.root, self.config, self.snapshot,
            mandate.principal.profile, mandate.principal.action, authorize_ref=authorize_ref)

    def operation(self, mandate, tool, arguments, phase):
        return replace(self.op, tool=tool, arguments_sha256=sha(arguments))


@pytest.fixture
def runtime(tmp_path):
    host = Host(tmp_path)
    gate = Authority(host, clock=lambda: 100)
    return host, gate


def test_public_cycle_pins_context_and_preserves_unverified_flags(runtime):
    host, gate = runtime
    packet = json.loads(gate.admit("session-a", "task"))
    assert packet["context_sha256"] == host.original["context_sha256"]
    assert not any(packet[x] for x in ("access_verified", "runtime_connected", "execution_ready"))
    assert gate.require("read_public", host.args) == host.op
    assert gate.require("read_public", host.args, phase="disclose") == host.op


@pytest.mark.parametrize("change,code", [
    ({"revoked": True}, "revoked"), ({"native_grant": False}, "revoked"),
    ({"stopped": True}, "native_hold"), ({"approval_pending": True}, "native_hold"),
    ({"expires_at": 100}, "expired"), ({"lease_until": 99}, "expired"),
    ({"revision": "r2"}, "changed"), ({"packet_sha256": "changed"}, "changed"),
    ({"refs": (("unapproved", "sha"),)}, "changed"),
])
def test_live_policy_changes_block_effect_and_disclosure(runtime, change, code):
    host, gate = runtime
    gate.admit("session-a", "task")
    host.state = replace(host.state, **change)
    for phase in ("effect", "disclose"):
        with pytest.raises(AuthorityDenied, match=code):
            gate.require("read_public", host.args, phase=phase)


@pytest.mark.parametrize("field,value", [("bot", "other"), ("requester", "deputy"),
    ("profile", "other"), ("session", "session-b"), ("task", "another-task"), ("action", "archived"),
    ("run", "run-b"), ("claim", "claim-b")])
def test_native_identity_claim_and_resume_cannot_be_substituted(runtime, field, value):
    host, gate = runtime
    gate.admit("session-a", "task")
    host.state = replace(host.state, principal=replace(host.principal, **{field: value}))
    with pytest.raises(AuthorityDenied):
        gate.require("read_public", host.args)


def test_missing_policy_callback_context_or_failed_packet_never_falls_open(runtime):
    host, gate = runtime
    with pytest.raises(AuthorityDenied, match="admission_required"):
        gate.require("read_public", host.args)
    gate.admit("session-a", "task")
    with pytest.raises(AuthorityDenied, match="admission_required"):
        Context().run(gate.require, "read_public", host.args)
    host.failure = True
    with pytest.raises(AuthorityDenied, match="^authority_unavailable$"):
        gate.admit("session-a", "task")
    host.failure = False
    with pytest.raises(AuthorityDenied, match="admission_required"):
        gate.require("read_public", host.args)


@pytest.mark.parametrize("field,value", [("purpose", "other-service"), ("resource", "private-source"),
    ("destination", "shared-board"), ("model", "unapproved-model"), ("action", "write")])
def test_service_and_return_audience_are_independently_scoped(runtime, field, value):
    host, gate = runtime
    gate.admit("session-a", "task")
    host.op = replace(host.op, **{field: value})
    with pytest.raises(AuthorityDenied, match="operation_denied"):
        gate.require("read_public", host.args, phase="disclose")


@pytest.mark.parametrize("kind", ["shell", "execute_code", "admin", "plugin_install", "delegate"])
def test_initial_worker_rejects_unbounded_surfaces_even_if_listed(runtime, kind):
    host, gate = runtime
    host.op = replace(host.op, kind=kind)
    host.state = replace(host.state, operations=(host.op,))
    gate.admit("session-a", "task")
    with pytest.raises(AuthorityDenied, match="surface_denied"):
        gate.require("read_public", host.args)


@pytest.mark.parametrize("binding", [None, NativeBinding("c-a", "a-a", "r1"),
    NativeBinding("c-a", "a-a", "r1", True, False), NativeBinding("c-a", "a-a", "r1", True, True, True)])
def test_private_requires_effective_native_account_and_transport_enforcement(runtime, binding):
    host, gate = runtime
    host.op = replace(host.op, sensitivity="private", binding=binding)
    host.state = replace(host.state, operations=(host.op,))
    gate.admit("session-a", "task")
    with pytest.raises(AuthorityDenied, match="account_enforcement_required"):
        gate.require("read_public", host.args)


def test_reconnect_alias_substitution_and_argument_rewrite_invalidate_permit(runtime):
    host, gate = runtime
    binding = NativeBinding("connection-a", "account-a", "native-r1", True, True)
    host.op = replace(host.op, sensitivity="private", binding=binding)
    host.state = replace(host.state, operations=(host.op,))
    gate.admit("session-a", "task")
    assert gate.require("read_public", host.args).binding == binding
    host.op = replace(host.op, binding=replace(binding, revision="native-r2"))
    with pytest.raises(AuthorityDenied, match="operation_denied"):
        gate.require("read_public", host.args)
    host.op = host.state.operations[0]
    with pytest.raises(AuthorityDenied, match="operation_denied"):
        gate.require("read_public", {**host.args, "account_alias": "account-b"})


def test_one_hop_relation_is_authorized_before_its_body_is_read(runtime, monkeypatch):
    host, gate = runtime
    # Keep source only in the action's relation, not in explicit context_pages:
    # this exercises the relation expansion rather than an earlier direct ref.
    path = host.root / "wiki.coordination.yaml"
    policy = yaml.safe_load(path.read_text())
    policy["profiles"]["research"]["context_pages"] = []
    path.write_text(yaml.safe_dump(policy))
    host.state = replace(host.state, refs=tuple(x for x in host.state.refs if x[0] != "memories/source.md"))
    read = coordination._read
    seen = []
    def spy(root, relative):
        seen.append(relative)
        return read(root, relative)
    monkeypatch.setattr(coordination, "_read", spy)
    with pytest.raises(AuthorityDenied, match="context_ref_denied"):
        gate.admit("session-a", "task")
    assert "memories/source.md" not in seen
    assert "memories/archived.md" not in seen


def test_stale_context_and_unknown_hook_result_block_before_model(runtime):
    host, gate = runtime
    (host.root / "memories/source.md").write_text("Changed source")
    with pytest.raises(AuthorityDenied, match="context_unavailable"):
        gate.admit("session-a", "task")
    with pytest.raises(FrozenInstanceError):
        host.principal.bot = "forged"


def test_authority_failure_after_resolution_blocks_handler(runtime):
    host, gate = runtime
    gate.admit("session-a", "task")
    def resolve_operation(*args):
        host.state = replace(host.state, revoked=True)
        return host.op
    host.operation = resolve_operation
    with pytest.raises(AuthorityDenied, match="revoked"):
        gate.require("read_public", host.args)


def test_native_task_and_wiki_action_are_distinct_explicit_bindings(runtime):
    host, _ = runtime
    principal = replace(host.principal, task="native-task-42")
    state = replace(host.state, principal=principal)
    backend = ReadOnlyHostBackend(host.root, host.config, snapshot=lambda: host.snapshot,
        native_identity=lambda session, task: principal,
        operator_mandate=lambda p: state,
        resolve_operation=lambda p, tool, args, phase: host.op)
    gate = Authority(backend, clock=lambda: 100)
    packet = json.loads(gate.admit("session-a", "native-task-42"))
    assert packet["actions"][0]["action_id"] == "task"
    assert gate.require("read_public", host.args) == host.op
    with pytest.raises(AuthorityDenied, match="principal_mismatch"):
        gate.admit("session-a", "task")


def test_malformed_grants_and_unversioned_policy_widening_fail_closed(runtime):
    host, gate = runtime
    host.state = replace(host.state, native_grant="false")
    with pytest.raises(AuthorityDenied, match="invalid_policy"):
        gate.admit("session-a", "task")
    host.state = replace(host.state, native_grant=True)
    gate.admit("session-a", "task")
    host.state = replace(host.state, operations=host.state.operations + (replace(host.op, destination="another"),))
    with pytest.raises(AuthorityDenied, match="changed"):
        gate.require("read_public", host.args)


def test_host_bridge_accepts_the_actual_vendored_kernel_contract(runtime, monkeypatch):
    from wiki_core import runtime_authority
    host, _ = runtime
    spec = importlib.util.spec_from_file_location("synthetic_kernel_authority", runtime_authority.__file__)
    kernel = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, kernel)
    spec.loader.exec_module(kernel)
    principal = kernel.Principal(**vars(host.principal))
    operation = kernel.Operation(**vars(host.op))
    state = kernel.Mandate(**{**vars(host.state), "principal": principal, "operations": (operation,)})
    backend = ReadOnlyHostBackend(host.root, host.config, snapshot=lambda: host.snapshot,
        native_identity=lambda session, task: principal, operator_mandate=lambda p: state,
        resolve_operation=lambda p, tool, args, phase: operation)
    gate = kernel.Authority(backend, clock=lambda: 100)
    assert gate.admit("session-a", "task")
    assert gate.require("read_public", host.args) == operation
