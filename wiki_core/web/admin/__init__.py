"""Administrative surface of the local operator (god-mode plan §12).

This package is the ONLY place that answers administrative discovery
requests and manages local admin sessions. Discovery never grants
anything; a session exists only after the startup-code unlock handshake
(sessions.py) and lives purely in this process's memory. Every session
lifecycle event lands in the append-only, hash-chained, redacted audit
trail (audit.py).
"""

from wiki_core.web.admin.audit import (
    AUDIT_SCHEMA_VERSION,
    append_admin_audit_event,
    audit_log_path,
    redact_audit_value,
    verify_admin_audit_chain,
)
from wiki_core.web.admin.capabilities import (
    ADMIN_CAPABILITY_SCHEMA_VERSION,
    ADMIN_SERVER_VERSION,
    ROLE_CAPABILITIES,
    admin_capabilities_payload,
    admin_health_summary,
)
from wiki_core.web.admin.sessions import (
    ADMIN_SESSION_HEADER,
    AdminSessionManager,
)

__all__ = [
    "ADMIN_CAPABILITY_SCHEMA_VERSION",
    "ADMIN_SERVER_VERSION",
    "ADMIN_SESSION_HEADER",
    "AUDIT_SCHEMA_VERSION",
    "AdminSessionManager",
    "ROLE_CAPABILITIES",
    "admin_capabilities_payload",
    "admin_health_summary",
    "append_admin_audit_event",
    "audit_log_path",
    "redact_audit_value",
    "verify_admin_audit_chain",
]
