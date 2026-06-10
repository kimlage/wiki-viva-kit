from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from ..ids import sha256_text

# Living gate states (v5). The order reflects a proposal's natural lifecycle.
# "blocked" is the alternative ENTRY state emitted by the ingestion pipeline when
# a secret blocks the source (scan-first: nothing is persisted). It has no
# incoming edges in the voluntary graph; the only ways out are restarting from a
# clean source ("created") or archiving.
STATES: tuple[str, ...] = (
    "blocked",
    "created",
    "compiling",
    "ready_for_review",
    "needs_human_gate",
    "approved",
    "published",
    "superseded",
    "rejected",
    "archived",
)

# Valid transitions: current state -> set of allowed next states.
TRANSITIONS: dict[str, set[str]] = {
    "blocked": {"created", "archived"},  # clean source -> restart; or archive
    "created": {"compiling", "rejected", "archived"},
    "compiling": {"ready_for_review", "rejected", "archived"},
    "ready_for_review": {"needs_human_gate", "superseded", "rejected", "archived"},
    "needs_human_gate": {"approved", "rejected", "superseded", "archived"},
    "approved": {"published", "superseded", "archived"},
    "published": {"superseded", "archived"},
    "superseded": {"archived"},
    "rejected": {"archived"},
    "archived": set(),
}

# States in which a proposal is still "alive" and competes for the same page/context.
PENDING_STATES: frozenset[str] = frozenset(
    {"created", "compiling", "ready_for_review", "needs_human_gate"}
)

DEFAULT_STATE = "created"

_FRONTMATTER_MARKER = "---"


def can_transition(a: str, b: str) -> bool:
    """Return True if the transition from state ``a`` to ``b`` is valid."""
    return b in TRANSITIONS.get(a, set())


@dataclass(frozen=True)
class Proposal:
    path: Path
    page_id: str
    context: str
    gate_state: str
    created_at: str
    proposal_hash: str
    rebase_key: str = ""


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Split the YAML frontmatter block from the remaining body.

    Returns ``(frontmatter_text, body)``. If there is no frontmatter delimited
    by ``---`` at the start of the file, ``frontmatter_text`` comes back empty
    and ``body`` is the full text.
    """
    if not text.startswith(_FRONTMATTER_MARKER):
        return "", text
    lines = text.splitlines(keepends=True)
    # The first line is the opening marker; we look for the closing one.
    for index in range(1, len(lines)):
        if lines[index].rstrip("\n").rstrip("\r") == _FRONTMATTER_MARKER:
            frontmatter = "".join(lines[1:index])
            body = "".join(lines[index + 1 :])
            return frontmatter, body
    return "", text


def _load_frontmatter(text: str) -> dict[str, object]:
    frontmatter_text, _ = _split_frontmatter(text)
    if not frontmatter_text.strip():
        return {}
    data = yaml.safe_load(frontmatter_text)
    if not isinstance(data, dict):
        return {}
    return data


def _dump_frontmatter(data: dict[str, object]) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False)


def read_proposal(path: Path) -> Proposal:
    """Read a proposal ``.md`` file and return a :class:`Proposal`.

    The ``proposal_hash`` is the sha256 of the body (without the frontmatter),
    so that edits to the frontmatter (state, history) do not change the identity
    of the proposed content.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    frontmatter = _load_frontmatter(text)
    _, body = _split_frontmatter(text)

    page_id = str(frontmatter.get("page_id", "")) if frontmatter.get("page_id") is not None else ""
    context = str(frontmatter.get("context", "")) if frontmatter.get("context") is not None else ""
    gate_state = frontmatter.get("gate_state") or DEFAULT_STATE
    created_at = frontmatter.get("created_at")
    created_at = str(created_at) if created_at is not None else ""
    rebase_key = frontmatter.get("rebase_key")
    rebase_key = str(rebase_key) if rebase_key is not None else ""

    return Proposal(
        path=path,
        page_id=page_id,
        context=context,
        gate_state=str(gate_state),
        created_at=created_at,
        proposal_hash=sha256_text(body),
        rebase_key=rebase_key,
    )


def write_state(
    path: Path,
    new_state: str,
    *,
    reason: str | None = None,
    _force: bool = False,
) -> Proposal:
    """Apply a state transition in a proposal's frontmatter.

    Validates the transition from the current ``gate_state``; if invalid, raises
    :class:`ValueError`. Updates only the ``gate_state`` field and appends an
    audit record to ``gate_history`` (list of ``{from, to, reason}``),
    preserving the rest of the frontmatter and the file body.

    ``_force`` is an internal detail used by :func:`rebase_pending` to
    supersede pending proposals (which may still be in ``created`` or
    ``compiling``, states with no direct edge to ``superseded`` in the graph of
    voluntary transitions). Supersede by rebase is a system action, not a
    manual transition, but remains audited via ``gate_history``.
    """
    path = Path(path)
    if new_state not in STATES:
        raise ValueError(f"unknown state: {new_state!r}")

    text = path.read_text(encoding="utf-8")
    frontmatter = _load_frontmatter(text)
    _, body = _split_frontmatter(text)

    current = frontmatter.get("gate_state") or DEFAULT_STATE
    current = str(current)
    # _force only enables the system supersede-by-rebase action; it never opens
    # invalid voluntary transitions (e.g. rejected -> approved, archived -> *).
    if not can_transition(current, new_state) and not (_force and new_state == "superseded"):
        raise ValueError(
            f"invalid transition {current!r} -> {new_state!r} for {path}"
        )

    frontmatter["gate_state"] = new_state

    history = frontmatter.get("gate_history")
    if not isinstance(history, list):
        history = []
    entry: dict[str, object] = {"from": current, "to": new_state, "reason": reason}
    history.append(entry)
    frontmatter["gate_history"] = history

    new_text = f"{_FRONTMATTER_MARKER}\n{_dump_frontmatter(frontmatter)}{_FRONTMATTER_MARKER}\n{body}"
    path.write_text(new_text, encoding="utf-8")
    return read_proposal(path)


def _matches(
    proposal: Proposal,
    page_id: str | None,
    context: str | None,
    rebase_key: str | None = None,
) -> bool:
    if page_id is not None and proposal.page_id != page_id:
        return False
    if context is not None and proposal.context != context:
        return False
    if rebase_key is not None and proposal.rebase_key != rebase_key:
        return False
    return True


def _group_key(proposal: Proposal) -> tuple[str, str]:
    # Group by the logical target (rebase_key) when present; otherwise by page_id,
    # so re-ingestions of the same target (distinct page_id per date) rebase together.
    return (proposal.rebase_key or proposal.page_id, proposal.context)


def rebase_pending(
    proposals_dir: Path,
    page_id: str | None = None,
    context: str | None = None,
    rebase_key: str | None = None,
) -> dict[str, object]:
    """Rebase pending proposals targeting the same page/context.

    Finds proposals with ``gate_state`` in :data:`PENDING_STATES` that target the
    same ``page_id`` (and/or ``context``), keeps the most recent one (by
    ``created_at``; ties broken by ``proposal_hash``) and marks the rest as
    ``superseded`` via :func:`write_state`.

    When ``page_id`` and/or ``context`` are given, the universe is restricted to
    proposals matching that target. When neither is given, all pending proposals
    are grouped by ``(page_id, context)`` and each group is rebased.

    Returns ``{"kept": <Path|None>, "superseded": [<Path>, ...]}``. When no
    filter is given and there are several groups, ``kept`` is the list of kept ones.
    """
    proposals_dir = Path(proposals_dir)
    if not proposals_dir.is_dir():
        raise FileNotFoundError(f"proposals directory does not exist: {proposals_dir}")

    pending: list[Proposal] = []
    for md_path in sorted(proposals_dir.glob("*.md")):
        proposal = read_proposal(md_path)
        if proposal.gate_state not in PENDING_STATES:
            continue
        if not _matches(proposal, page_id, context, rebase_key):
            continue
        if not proposal.page_id:
            # Without a page_id there is no safe way to group; skip it.
            continue
        pending.append(proposal)

    # Group by (page_id, context) so distinct pages are never rebased together.
    groups: dict[tuple[str, str], list[Proposal]] = {}
    for proposal in pending:
        groups.setdefault(_group_key(proposal), []).append(proposal)

    kept_paths: list[Path] = []
    superseded_paths: list[Path] = []

    for _, members in sorted(groups.items()):
        # Most recent: highest created_at; ties broken by the highest proposal_hash (stable).
        members.sort(key=lambda p: (p.created_at, p.proposal_hash), reverse=True)
        keeper = members[0]
        kept_paths.append(keeper.path)
        for loser in members[1:]:
            updated = write_state(
                loser.path,
                "superseded",
                reason=f"superseded by {keeper.path.name}",
                _force=True,
            )
            superseded_paths.append(updated.path)

    explicit_target = page_id is not None or context is not None or rebase_key is not None
    if explicit_target:
        kept: object = kept_paths[0] if len(kept_paths) == 1 else kept_paths
    else:
        kept = kept_paths

    return {"kept": kept, "superseded": superseded_paths}
