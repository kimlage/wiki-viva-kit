"""Canonical action lifecycle shared by every deterministic wiki surface.

``action_state`` is the only authored machine state. Older repositories may be
read through the explicit compatibility adapter below, but once the canonical
field exists neither editorial ``status`` nor a body ``State:`` line can alter
the lifecycle verdict.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Mapping


CANONICAL_ACTION_STATES = frozenset(
    {"open", "in_progress", "blocked", "waiting_human", "done", "cancelled"}
)
TERMINAL_ACTION_STATES = frozenset({"done", "cancelled"})
NON_TERMINAL_ACTION_STATES = CANONICAL_ACTION_STATES - TERMINAL_ACTION_STATES

# This table is intentionally explicit. Callers that mutate action pages must
# reject every transition not listed here rather than inferring from labels.
ACTION_STATE_TRANSITIONS: dict[str, frozenset[str]] = {
    "open": frozenset(
        {"in_progress", "blocked", "waiting_human", "done", "cancelled"}
    ),
    "in_progress": frozenset({"blocked", "waiting_human", "done", "cancelled"}),
    "blocked": frozenset({"open", "in_progress", "waiting_human", "cancelled"}),
    "waiting_human": frozenset({"in_progress", "blocked", "done", "cancelled"}),
    "done": frozenset(),
    "cancelled": frozenset(),
}

_LEGACY_DONE = frozenset(
    {
        "closed",
        "complete",
        "completed",
        "concluded",
        "concluida",
        "concluido",
        "done",
        "resolved",
        "resolvida",
        "resolvido",
    }
)
_LEGACY_DONE_PREFIXES = (
    "closed_at_",
    "closed_em_",
    "completed_at_",
    "completed_em_",
    "concluida_at_",
    "concluida_em_",
    "concluido_at_",
    "concluido_em_",
    "concluded_at_",
    "concluded_em_",
    "done_at_",
    "done_em_",
    "resolved_at_",
    "resolved_em_",
    "resolvida_at_",
    "resolvida_em_",
    "resolvido_at_",
    "resolvido_em_",
)
_LEGACY_CANCELLED = frozenset(
    {"cancelled", "canceled", "cancelada", "cancelado"}
)
_LEGACY_BLOCKED = frozenset({"blocked", "bloqueada", "bloqueado"})
_LEGACY_WAITING = frozenset(
    {
        "waiting_human",
        "waiting_for_human",
        "aguardando_humano",
        "aguardando_pessoa",
    }
)
_LEGACY_IN_PROGRESS = frozenset(
    {"in_progress", "doing", "em_andamento", "em_progresso"}
)
_LEGACY_BODY_STATE_RE = re.compile(
    r"^(?:Estado|State):\s*(.+?)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ActionStateResolution:
    state: str
    raw: str
    source: str
    compatibility: bool
    warnings: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return self.state in CANONICAL_ACTION_STATES

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL_ACTION_STATES


def legacy_action_state_from_body(body: str) -> str:
    """Read the first legacy ``State:``/``Estado:`` line from Markdown.

    All deterministic action surfaces use this parser before calling
    :func:`resolve_action_state`.  Keeping it here prevents subtle differences
    in punctuation/backtick handling from changing whether the cockpit,
    operational pass, template summaries and web snapshot consider the same
    legacy action open or closed.
    """

    for line in body.splitlines():
        match = _LEGACY_BODY_STATE_RE.match(line.strip())
        if not match:
            continue
        raw = match.group(1).strip()
        if raw.startswith("`"):
            end = raw.find("`", 1)
            if end > 1:
                return raw[1:end].strip()
        for separator in (" — ", " -- "):
            if separator in raw:
                raw = raw.split(separator, 1)[0].strip()
        return raw.rstrip(".").strip()
    return ""


def _slug(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", ascii_value.lower()).strip("_")


def _legacy_state(raw: str) -> str:
    slug = _slug(raw)
    if slug in _LEGACY_CANCELLED:
        return "cancelled"
    if slug in _LEGACY_DONE or any(
        slug.startswith(prefix) for prefix in _LEGACY_DONE_PREFIXES
    ):
        return "done"
    if slug in _LEGACY_BLOCKED:
        return "blocked"
    if slug in _LEGACY_WAITING:
        return "waiting_human"
    if slug in _LEGACY_IN_PROGRESS:
        return "in_progress"
    # Legacy editorial states such as pending/recurring/active never close an
    # action. Unknown legacy copy remains open and is surfaced as a warning.
    return "open"


def resolve_action_state(
    values: Mapping[str, Any],
    *,
    legacy_state: Any = "",
) -> ActionStateResolution:
    """Resolve one action without letting editorial status override truth.

    ``legacy_state`` is the parsed body ``State:``/``Estado:`` line when a
    caller supports old pages. It is considered only when ``action_state`` is
    absent. An invalid canonical value returns ``unknown`` and never falls back
    to a contradictory legacy value.
    """

    canonical_raw = str(values.get("action_state") or "").strip()
    if canonical_raw:
        canonical = canonical_raw.lower()
        if canonical in CANONICAL_ACTION_STATES:
            return ActionStateResolution(
                state=canonical,
                raw=canonical_raw,
                source="action_state",
                compatibility=False,
            )
        return ActionStateResolution(
            state="unknown",
            raw=canonical_raw,
            source="action_state",
            compatibility=False,
            warnings=("invalid_action_state",),
        )

    candidates = (
        ("state", values.get("state")),
        ("status", values.get("status")),
        ("body_state", legacy_state),
    )
    for source, candidate in candidates:
        raw = str(candidate or "").strip()
        if not raw:
            continue
        state = _legacy_state(raw)
        warnings = ["legacy_action_state"]
        if _slug(raw) not in {
            *CANONICAL_ACTION_STATES,
            *_LEGACY_DONE,
            *_LEGACY_CANCELLED,
            *_LEGACY_BLOCKED,
            *_LEGACY_WAITING,
            *_LEGACY_IN_PROGRESS,
        } and not any(
            _slug(raw).startswith(prefix) for prefix in _LEGACY_DONE_PREFIXES
        ):
            warnings.append("unknown_legacy_action_state")
        return ActionStateResolution(
            state=state,
            raw=raw,
            source=source,
            compatibility=True,
            warnings=tuple(warnings),
        )

    return ActionStateResolution(
        state="open",
        raw="",
        source="default",
        compatibility=True,
        warnings=("missing_action_state",),
    )


def action_is_terminal(values: Mapping[str, Any], *, legacy_state: Any = "") -> bool:
    return resolve_action_state(values, legacy_state=legacy_state).terminal


def valid_action_transition(previous: str, next_state: str) -> bool:
    if previous == next_state and previous in CANONICAL_ACTION_STATES:
        return True
    return next_state in ACTION_STATE_TRANSITIONS.get(previous, frozenset())
