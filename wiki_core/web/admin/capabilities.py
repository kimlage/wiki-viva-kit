"""Administrative capability discovery (god-mode plan §6.3, §8, §12.1, §12.6).

The payloads here are deliberately boring: deterministic dictionaries built
from the startup-pinned config plus an optional already-validated session
description, with no secrets and no session token. Discovery NEVER grants
anything by itself — grants only appear when the caller (the server) has
validated a session header against the in-memory store (sessions.py), and
even then the payload carries the grant flags, never the credential.
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

# Role -> capability groups (plan §8.3). Roles COMPOSE: each row builds on
# the previous one. session.manage belongs to every role — a session may
# always renew or lock itself.
_OBSERVER_CAPABILITIES = (
    "system.inspect",
    "config.inspect",
    "templates.inspect",
    "views.inspect",
    "graph.diagnose",
    "sources.inspect",
    "git.inspect",
    "agents.inspect",
    "audit.inspect",
    "session.manage",
)
_OPERATOR_CAPABILITIES = _OBSERVER_CAPABILITIES + (
    "gates.run",
    "sources.plan",
    "sources.execute",
    "snapshot.rebuild",
)
_MAINTAINER_CAPABILITIES = _OPERATOR_CAPABILITIES + (
    "config.validate",
    "config.propose",
    "templates.propose",
    "views.discover",
    "views.preview",
    "views.propose",
    "git.propose",
)
_PUBLISHER_CAPABILITIES = _MAINTAINER_CAPABILITIES + ("git.publish",)
_ADMIN_CAPABILITIES = tuple(
    capability
    for capability in ADMIN_CAPABILITY_GROUPS
    if capability != "break_glass.local"
)
ROLE_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "observer": _OBSERVER_CAPABILITIES,
    "operator": _OPERATOR_CAPABILITIES,
    "maintainer": _MAINTAINER_CAPABILITIES,
    "publisher": _PUBLISHER_CAPABILITIES,
    "admin": _ADMIN_CAPABILITIES,
    "rescue_admin": ADMIN_CAPABILITY_GROUPS,
}

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


def admin_capabilities_payload(
    config: WikiConfig, session: dict[str, Any] | None = None
) -> dict[str, Any]:
    """GET /api/admin/capabilities (plan §12.1) — session-state aware.

    Without a validated session the honest outputs are `unavailable` (admin
    disabled by config) and `locked` (operator present, nothing authorized).
    With a session — validated by the caller against the in-memory store,
    NEVER by this function — grants follow the session role (§8.3). Every
    capability group is listed with a granted flag plus the reason when not
    granted, so the Admin Dock renders present-vs-absent chips without
    inventing authority. The URL that fetches this payload never authorizes
    anything (plan §14.1), and no token ever appears in it: the session block
    carries only public description fields.
    """

    available = config.admin_enabled
    break_glass_allowed = config.admin_break_glass_allowed
    role = str(session.get("role") or "") if session else ""
    granted_set = frozenset(ROLE_CAPABILITIES.get(role, ())) if session else frozenset()
    capabilities = []
    for capability_id in ADMIN_CAPABILITY_GROUPS:
        if not available:
            granted, reason = False, "admin_disabled"
        elif capability_id == "break_glass.local" and not break_glass_allowed:
            granted, reason = False, "disabled_by_config"
        elif session is None:
            granted, reason = False, "session_not_authorized"
        elif capability_id in granted_set:
            granted, reason = True, None
        else:
            granted, reason = False, "role_not_authorized"
        entry: dict[str, Any] = {"id": capability_id, "granted": granted}
        if reason is not None:
            entry["reason"] = reason
        capabilities.append(entry)

    if not available:
        session_state = "unavailable"
    elif session is None:
        session_state = "locked"
    else:
        session_state = str(session.get("state") or "active_partial")

    session_block = None
    if session is not None and available:
        # Public description only (plan §13.2): the token stays in the
        # client's memory and the server's digest store — never here.
        session_block = {
            "session_id": session.get("session_id"),
            "role": role or None,
            "state": session_state,
            "expires_in_s": session.get("expires_in_s"),
            "idle_remaining_s": session.get("idle_remaining_s"),
        }

    return {
        "ok": True,
        "schema_version": ADMIN_CAPABILITY_SCHEMA_VERSION,
        "server_version": ADMIN_SERVER_VERSION,
        "adapter": _adapter_id(config),
        "session_state": session_state,
        "session": session_block,
        "read_only": session_block is None or role == "observer",
        "session_states": list(ADMIN_SESSION_STATES),
        "capabilities": capabilities,
    }
