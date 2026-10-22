"""Read-only bridge from native host authority to the existing wiki context.

No provider adapter or policy store. The trusted host must supply authenticated
native identity/claim reads and a protected operator registry. These dependencies
are intentionally not instantiated by the passive plugin or source configuration.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Any

from wiki_core.coordination import context_packet
from wiki_core.runtime_authority import AuthorityDenied, Mandate, Operation, Principal


class ReadOnlyHostBackend:
    def __init__(self, root: Path, config: Any, *, snapshot: Callable[[], dict],
                 native_identity: Callable[[str, str], Principal],
                 operator_mandate: Callable[[Principal], Mandate],
                 resolve_operation: Callable[[Principal, str, dict, str], Operation]):
        self.root = root
        self.config = config
        self.snapshot = snapshot
        self.native_identity = native_identity
        self.operator_mandate = operator_mandate
        self.resolve_operation = resolve_operation

    def resolve(self, session: str, task: str) -> Mandate:
        principal = self.native_identity(session, task)
        # The deployed kernel vendors the same contract as tools.wiki_authority.
        # Do not require Python class identity across that module boundary; the
        # kernel validates its own immutable types at the final authority entry.
        if principal.session != session or principal.task != task:
            raise AuthorityDenied("authority_principal_mismatch")
        state = self.operator_mandate(principal)
        if state.principal != principal:
            raise AuthorityDenied("authority_principal_mismatch")
        return state

    def packet(self, mandate: Mandate, authorize_ref: Callable) -> dict:
        return context_packet(self.root, self.config, self.snapshot(), mandate.principal.profile,
                              mandate.principal.action, authorize_ref=authorize_ref)

    def operation(self, mandate: Mandate, tool: str, arguments: dict, phase: str) -> Operation:
        return self.resolve_operation(mandate.principal, tool, arguments, phase)
