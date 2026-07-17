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
from wiki_core.web.admin.commands import (
    ADMIN_COMMANDS_SCHEMA_VERSION,
    ADMIN_COMMAND_SPECS,
    AdminCommandSpec,
    admin_command_spec,
    admin_commands_payload,
    command_capabilities_granted,
)
from wiki_core.web.admin.plans import (
    ADMIN_PLAN_SCHEMA_VERSION,
    AdminPlanStore,
    build_admin_plan,
    execute_admin_plan,
)
from wiki_core.web.admin.sessions import (
    ADMIN_SESSION_HEADER,
    AdminSessionManager,
)

__all__ = [
    "ADMIN_CAPABILITY_SCHEMA_VERSION",
    "ADMIN_COMMANDS_SCHEMA_VERSION",
    "ADMIN_COMMAND_SPECS",
    "ADMIN_PLAN_SCHEMA_VERSION",
    "ADMIN_SERVER_VERSION",
    "ADMIN_SESSION_HEADER",
    "AUDIT_SCHEMA_VERSION",
    "AdminCommandSpec",
    "AdminPlanStore",
    "AdminSessionManager",
    "ROLE_CAPABILITIES",
    "admin_capabilities_payload",
    "admin_command_spec",
    "admin_commands_payload",
    "admin_health_summary",
    "append_admin_audit_event",
    "audit_log_path",
    "build_admin_plan",
    "command_capabilities_granted",
    "execute_admin_plan",
    "redact_audit_value",
    "verify_admin_audit_chain",
]
