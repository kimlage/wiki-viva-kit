"""Administrative surface of the local operator (god-mode plan §12).

This package is the ONLY place that answers administrative discovery
requests. Everything in it is read-only in this milestone: there is no
session, no token and no unlock flow yet (those arrive with the session
work, plan PR3), so the honest answer to "what can this operator do for
an administrator?" is always `locked` or `unavailable` — never a grant.
"""

from wiki_core.web.admin.capabilities import (
    ADMIN_CAPABILITY_SCHEMA_VERSION,
    ADMIN_SERVER_VERSION,
    admin_capabilities_payload,
    admin_health_summary,
)

__all__ = [
    "ADMIN_CAPABILITY_SCHEMA_VERSION",
    "ADMIN_SERVER_VERSION",
    "admin_capabilities_payload",
    "admin_health_summary",
]
