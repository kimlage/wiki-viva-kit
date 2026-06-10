"""Living gate state machine and proposal rebase/supersede (v5)."""

from __future__ import annotations

from .state_machine import (
    STATES,
    TRANSITIONS,
    Proposal,
    can_transition,
    read_proposal,
    rebase_pending,
    write_state,
)

__all__ = [
    "STATES",
    "TRANSITIONS",
    "Proposal",
    "can_transition",
    "read_proposal",
    "rebase_pending",
    "write_state",
]
