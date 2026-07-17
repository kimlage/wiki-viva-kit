"""Administrative capability discovery (god-mode plan §6.3, §8, §12.1, §12.6).

The payloads here are deliberately boring: deterministic dictionaries built
from the startup-pinned config, with no timestamps, no secrets and no session
material. Discovery NEVER grants anything — it only tells the cockpit which
capability groups exist on this operator and why none of them is granted yet
(`locked`: an operator exists but no session is authorized; `unavailable`:
the config turned the admin surface off). The unlock/session machinery is a
later milestone (plan PR3); shipping discovery first lets the Admin Dock be
honest about its own locked state instead of pretending.
"""

from __future__ import annotations

from typing import Any

from wiki_core.config import WikiConfig

ADMIN_SERVER_VERSION = "wiki_admin.v1"
ADMIN_CAPABILITY_SCHEMA_VERSION = "wiki_admin_capabilities.v1"

# The §6.3 visual-state vocabulary. The server can only produce the first two
# until sessions exist; the full closed set ships now so the frontend mirror
# and tests pin one shared vocabulary instead of two drifting copies.
ADMIN_SESSION_STATES = (
    "unavailable",
    "locked",
    "unlocking",
    "active_readonly",
    "active_partial",
    "active_full",
    "expiring",
    "revoked",
)

# Capability groups (plan §8.1). Declaring a group here only names it for
# discovery; granting happens per session, server-side, and is revalidated on
# execute (plan §8.2) — none of that exists in this milestone.
ADMIN_CAPABILITY_GROUPS = (
    "system.inspect",
    "snapshot.rebuild",
    "config.inspect",
    "config.validate",
    "config.propose",
    "templates.inspect",
    "templates.propose",
    "views.inspect",
    "views.discover",
    "views.preview",
    "views.propose",
    "graph.diagnose",
    "sources.inspect",
    "sources.plan",
    "sources.execute",
    "gates.run",
    "git.inspect",
    "git.propose",
    "git.publish",
    "agents.inspect",
    "agents.execute",
    "audit.inspect",
    "recovery.execute",
    "session.manage",
    "break_glass.local",
)

# config `admin.local_unlock` value -> adapter id advertised in discovery.
_ADAPTER_IDS = {"startup_code": "local_startup_code"}


def _adapter_id(config: WikiConfig) -> str | None:
    if not config.admin_enabled:
        return None
    return _ADAPTER_IDS.get(str(config.admin.get("local_unlock") or ""))


def admin_health_summary(config: WikiConfig) -> dict[str, Any]:
    """The non-sensitive `admin` block for /api/health (plan §12.6).

    No token, no unlock code, no role detail, no internal policy — only what
    a cockpit needs to know that an admin-capable operator exists at all.
    """

    return {
        "available": config.admin_enabled,
        "adapter": _adapter_id(config),
        "server_version": ADMIN_SERVER_VERSION,
        "capability_schema": ADMIN_CAPABILITY_SCHEMA_VERSION,
    }


def admin_capabilities_payload(config: WikiConfig) -> dict[str, Any]:
    """GET /api/admin/capabilities (plan §12.1) — locked/read-only aware.

    Without a session subsystem the state machine has exactly two honest
    outputs: `unavailable` (admin disabled by config) and `locked` (operator
    present, nothing authorized). Every capability group is listed with
    `granted: false` plus the reason, so the read-only Admin Dock can render
    present-vs-absent chips without inventing authority. The URL that fetches
    this payload never authorizes anything (plan §14.1).
    """

    available = config.admin_enabled
    break_glass_allowed = config.admin_break_glass_allowed
    capabilities = []
    for capability_id in ADMIN_CAPABILITY_GROUPS:
        if not available:
            reason = "admin_disabled"
        elif capability_id == "break_glass.local" and not break_glass_allowed:
            reason = "disabled_by_config"
        else:
            reason = "session_not_authorized"
        capabilities.append(
            {"id": capability_id, "granted": False, "reason": reason}
        )
    return {
        "ok": True,
        "schema_version": ADMIN_CAPABILITY_SCHEMA_VERSION,
        "server_version": ADMIN_SERVER_VERSION,
        "adapter": _adapter_id(config),
        "session_state": "locked" if available else "unavailable",
        # Session material is structurally absent, not empty: there is no
        # token, code or challenge anywhere in this payload by construction.
        "session": None,
        "read_only": True,
        "session_states": list(ADMIN_SESSION_STATES),
        "capabilities": capabilities,
    }
