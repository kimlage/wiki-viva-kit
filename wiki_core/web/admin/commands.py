"""Server-side administrative command registry (god-mode plan §9, §11, §12.2).

The browser sends ``{"command_id": ..., "params": {...}}`` and NOTHING else —
never argv, never a script path, never shell text. Every command is a frozen
:class:`AdminCommandSpec` declared here, and its planner/executor names map to
Python callables in plans.py that delegate to EXISTING repo paths (the
allowlisted ActionCard catalog behind ``operator_commands.json``, the snapshot
derive path, ``load_config``). Declaring a spec grants nothing: capabilities
are granted per session (capabilities.py) and revalidated on execute.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from wiki_core.config import WikiConfig
from wiki_core.web.admin.capabilities import ROLE_CAPABILITIES
from wiki_core.web.commands import (
    RISK_LEVEL_DERIVE,
    RISK_LEVEL_READ,
    RISK_LEVELS,
)
from wiki_core.web.schemas import WEB_ACTION_SCHEMA_VERSION

ADMIN_COMMANDS_SCHEMA_VERSION = "wiki_admin_commands.v1"


@dataclass(frozen=True)
class AdminCommandSpec:
    """One bus command (plan §11.1). ``planner``/``executor`` are names
    resolved by plans.py — specs stay declarative and serializable."""

    id: str
    title: str
    capability: tuple[str, ...]
    risk_level: str
    supports_dry_run: bool
    parameter_schema: dict[str, Any]
    planner: str
    executor: str
    undo_strategy: str | None


# Initial adapters (PR4): wrap EXISTING read/derive behavior only. The write
# levels (proposal_write/external_write/destructive) are canonical vocabulary
# already (commands.py RISK_LEVELS) but no command uses them until the domain
# administration PR ships planners with proposal branches and typed targets.
ADMIN_COMMAND_SPECS: tuple[AdminCommandSpec, ...] = (
    AdminCommandSpec(
        id="system.inspect",
        title="Inspect system state",
        capability=("system.inspect",),
        risk_level=RISK_LEVEL_READ,
        supports_dry_run=False,
        parameter_schema={},
        planner="system_inspect",
        executor="system_inspect",
        undo_strategy=None,
    ),
    AdminCommandSpec(
        id="config.inspect",
        title="Inspect effective configuration",
        capability=("config.inspect",),
        risk_level=RISK_LEVEL_READ,
        supports_dry_run=False,
        parameter_schema={},
        planner="config_inspect",
        executor="config_inspect",
        undo_strategy=None,
    ),
    AdminCommandSpec(
        id="config.validate",
        title="Validate configuration",
        capability=("config.validate",),
        risk_level=RISK_LEVEL_DERIVE,
        supports_dry_run=False,
        parameter_schema={},
        planner="config_validate",
        executor="config_validate",
        undo_strategy=None,
    ),
    AdminCommandSpec(
        id="snapshot.rebuild",
        title="Rebuild the published web snapshot",
        capability=("snapshot.rebuild",),
        risk_level=RISK_LEVEL_DERIVE,
        supports_dry_run=True,
        parameter_schema={},
        planner="snapshot_rebuild",
        executor="snapshot_rebuild",
        undo_strategy="restore_previous_snapshot_revision",
    ),
)

_SPEC_BY_ID = {spec.id: spec for spec in ADMIN_COMMAND_SPECS}

for _spec in ADMIN_COMMAND_SPECS:
    if _spec.risk_level not in RISK_LEVELS:  # pragma: no cover - import guard
        raise ValueError(f"unknown risk level on {_spec.id}: {_spec.risk_level}")


def admin_command_spec(command_id: str) -> AdminCommandSpec | None:
    return _SPEC_BY_ID.get(str(command_id or ""))


def command_capabilities_granted(
    config: WikiConfig, spec: AdminCommandSpec, session: dict[str, Any] | None
) -> tuple[bool, str | None]:
    """Whether the CURRENT session grants every capability the spec needs.

    Mirrors the reason vocabulary of capabilities.py so the catalog and the
    capability chips tell one coherent story.
    """

    if not config.admin_enabled:
        return False, "admin_disabled"
    if session is None:
        return False, "session_not_authorized"
    role = str(session.get("role") or "")
    granted = frozenset(ROLE_CAPABILITIES.get(role, ()))
    if all(capability in granted for capability in spec.capability):
        return True, None
    return False, "role_not_authorized"


def admin_commands_payload(
    config: WikiConfig, session: dict[str, Any] | None = None
) -> dict[str, Any]:
    """GET /api/admin/commands (plan §12.2): the reviewable catalog.

    Extends the operator command read model rather than replacing it: the
    ``action_schema_version`` ties this catalog to ``operator_commands.json``
    (wiki_web_actions.v1), whose allowlisted cards several executors reuse.
    Listing a command NEVER grants it — ``granted`` mirrors the session's
    server-side role and is revalidated again on plan AND on execute.
    """

    commands = []
    for spec in ADMIN_COMMAND_SPECS:
        granted, reason = command_capabilities_granted(config, spec, session)
        entry: dict[str, Any] = {
            "id": spec.id,
            "title": spec.title,
            "capability": list(spec.capability),
            "risk_level": spec.risk_level,
            "supports_dry_run": spec.supports_dry_run,
            "parameter_schema": dict(spec.parameter_schema),
            "undo_strategy": spec.undo_strategy,
            "granted": granted,
        }
        if reason is not None:
            entry["reason"] = reason
        commands.append(entry)
    return {
        "ok": True,
        "schema_version": ADMIN_COMMANDS_SCHEMA_VERSION,
        "action_schema_version": WEB_ACTION_SCHEMA_VERSION,
        "risk_levels": list(RISK_LEVELS),
        "commands": commands,
    }
