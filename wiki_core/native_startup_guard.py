"""Restriction before native import effects; stdlib-only, no grants or secrets.

The process is a protected worker if any native routing hint is present, even
empty. A hint only restricts. Admission still comes from the process-bound host.
Reload does not clear an established restriction after the hint is consumed.
"""
from __future__ import annotations

import os

# Reload must not republish a stale False if another thread has restricted the
# process. Never assign this state again once the module has initialized it.
if "_restricted" not in globals():
    _restricted = False


def restrict_worker():
    global _restricted
    _restricted = True


def protected_worker():
    if any(key in os.environ for key in ("HERMES_WIKI_NATIVE_CHANNEL", "HERMES_KANBAN_TASK",
            "HERMES_KANBAN_RUN_ID", "HERMES_KANBAN_CLAIM_LOCK")):
        restrict_worker()
    return _restricted


def prepare_process_import():
    if protected_worker():
        # Lazy and stdlib-only dependency chain: no native config/provider import.
        from .native_host_wire import bootstrap_agent
        bootstrap_agent(None)


def require_secret_materialization():
    if protected_worker():
        from .runtime_authority import AuthorityDenied
        # No native account/transport enforcement has been qualified here.
        raise AuthorityDenied("authority_account_enforcement_required")
