"""Tests for the wiki_core.gate state machine and rebase/supersede logic."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wiki_core.gate import (
    STATES,
    TRANSITIONS,
    Proposal,
    can_transition,
    read_proposal,
    rebase_pending,
    write_state,
)
from wiki_core.gate.state_machine import PENDING_STATES, _load_frontmatter


def _make_proposal(
    directory: Path,
    name: str,
    *,
    page_id: str,
    context: str = "system",
    gate_state: str | None = None,
    created_at: str = "2026-06-08",
    rebase_key: str | None = None,
    body: str = "proposal body\n",
) -> Path:
    fields: dict[str, object] = {
        "page_id": page_id,
        "context": context,
        "created_at": created_at,
    }
    if gate_state is not None:
        fields["gate_state"] = gate_state
    if rebase_key is not None:
        fields["rebase_key"] = rebase_key
    frontmatter = yaml.safe_dump(fields, sort_keys=False, allow_unicode=True)
    path = directory / name
    path.write_text(f"---\n{frontmatter}---\n\n# Proposal\n\n{body}", encoding="utf-8")
    return path


def test_states_and_transitions_are_consistent() -> None:
    assert set(STATES) == set(TRANSITIONS)
    for nexts in TRANSITIONS.values():
        assert nexts <= set(STATES)
    # blocked is a valid state but never pending: rebase must not touch it.
    assert "blocked" in STATES
    assert "blocked" not in PENDING_STATES


def test_can_transition_valid() -> None:
    assert can_transition("created", "compiling")
    assert can_transition("ready_for_review", "needs_human_gate")
    assert can_transition("needs_human_gate", "approved")
    assert can_transition("approved", "published")
    assert can_transition("ready_for_review", "superseded")
    assert can_transition("published", "archived")
    # blocked (secret in the source): clean source -> restart, or archive.
    assert can_transition("blocked", "created")
    assert can_transition("blocked", "archived")


def test_can_transition_invalid() -> None:
    assert not can_transition("created", "approved")
    assert not can_transition("approved", "created")
    assert not can_transition("archived", "compiling")
    assert not can_transition("rejected", "approved")
    assert not can_transition("published", "created")
    assert not can_transition("unknown", "compiling")
    # blocked has no incoming edges and cannot skip straight to review/approval.
    assert not can_transition("created", "blocked")
    assert not can_transition("blocked", "compiling")
    assert not can_transition("blocked", "approved")


def test_blocked_state_restarts_or_archives(tmp_path: Path) -> None:
    # The pipeline emits gate_state="blocked" when a secret blocks the source;
    # the state machine must accept it as a valid state with exits limited to
    # "created" (clean source, restart) and "archived".
    path = _make_proposal(tmp_path, "a.md", page_id="pg-a", gate_state="blocked")
    with pytest.raises(ValueError):
        write_state(path, "compiling")
    assert read_proposal(path).gate_state == "blocked"
    updated = write_state(path, "created", reason="source cleaned, restarting")
    assert updated.gate_state == "created"

    archived = _make_proposal(tmp_path, "b.md", page_id="pg-b", gate_state="blocked")
    assert write_state(archived, "archived").gate_state == "archived"


def test_read_proposal_defaults_state_to_created(tmp_path: Path) -> None:
    path = _make_proposal(tmp_path, "a.md", page_id="pg-a", gate_state=None)
    proposal = read_proposal(path)
    assert isinstance(proposal, Proposal)
    assert proposal.page_id == "pg-a"
    assert proposal.context == "system"
    assert proposal.gate_state == "created"
    assert proposal.created_at == "2026-06-08"
    assert len(proposal.proposal_hash) == 64


def test_write_state_applies_valid_transition(tmp_path: Path) -> None:
    path = _make_proposal(tmp_path, "a.md", page_id="pg-a", gate_state="created")
    updated = write_state(path, "compiling", reason="starting compilation")
    assert updated.gate_state == "compiling"

    frontmatter = _load_frontmatter(path.read_text(encoding="utf-8"))
    assert frontmatter["gate_state"] == "compiling"
    history = frontmatter["gate_history"]
    assert history == [{"from": "created", "to": "compiling", "reason": "starting compilation"}]
    # body preserved and other fields intact
    assert "# Proposal" in path.read_text(encoding="utf-8")
    assert frontmatter["page_id"] == "pg-a"
    assert frontmatter["context"] == "system"


def test_write_state_rejects_invalid_transition(tmp_path: Path) -> None:
    path = _make_proposal(tmp_path, "a.md", page_id="pg-a", gate_state="created")
    with pytest.raises(ValueError):
        write_state(path, "approved")
    # state did not change after rejection
    assert read_proposal(path).gate_state == "created"


def test_write_state_rejects_unknown_state(tmp_path: Path) -> None:
    path = _make_proposal(tmp_path, "a.md", page_id="pg-a", gate_state="created")
    with pytest.raises(ValueError):
        write_state(path, "frozen")


def test_write_state_appends_history(tmp_path: Path) -> None:
    path = _make_proposal(tmp_path, "a.md", page_id="pg-a", gate_state="created")
    write_state(path, "compiling")
    write_state(path, "ready_for_review")
    frontmatter = _load_frontmatter(path.read_text(encoding="utf-8"))
    assert [h["to"] for h in frontmatter["gate_history"]] == ["compiling", "ready_for_review"]


def test_rebase_pending_keeps_newest_supersedes_rest(tmp_path: Path) -> None:
    old = _make_proposal(
        tmp_path, "old.md", page_id="pg-x", created_at="2026-06-01", gate_state="ready_for_review"
    )
    mid = _make_proposal(
        tmp_path, "mid.md", page_id="pg-x", created_at="2026-06-05", gate_state="created"
    )
    new = _make_proposal(
        tmp_path, "new.md", page_id="pg-x", created_at="2026-06-08", gate_state="needs_human_gate"
    )
    # a proposal for another page must not be touched
    other = _make_proposal(
        tmp_path, "other.md", page_id="pg-y", created_at="2026-06-09", gate_state="created"
    )
    # an already-approved proposal must not be superseded by the rebase
    approved = _make_proposal(
        tmp_path, "approved.md", page_id="pg-x", created_at="2026-06-02", gate_state="approved"
    )

    result = rebase_pending(tmp_path, page_id="pg-x")

    assert result["kept"] == new
    assert set(result["superseded"]) == {old, mid}

    assert read_proposal(new).gate_state == "needs_human_gate"
    assert read_proposal(old).gate_state == "superseded"
    assert read_proposal(mid).gate_state == "superseded"
    # not touched
    assert read_proposal(other).gate_state == "created"
    assert read_proposal(approved).gate_state == "approved"


def test_rebase_pending_records_history(tmp_path: Path) -> None:
    _make_proposal(tmp_path, "a.md", page_id="pg", created_at="2026-06-01", gate_state="created")
    loser = _make_proposal(
        tmp_path, "b.md", page_id="pg", created_at="2026-06-02", gate_state="created"
    )
    # b is newer, so a becomes superseded
    a_path = tmp_path / "a.md"
    rebase_pending(tmp_path, page_id="pg")
    frontmatter = _load_frontmatter(a_path.read_text(encoding="utf-8"))
    assert frontmatter["gate_state"] == "superseded"
    assert frontmatter["gate_history"][-1]["to"] == "superseded"
    assert read_proposal(loser).gate_state == "created"


def test_rebase_pending_tie_break_by_hash(tmp_path: Path) -> None:
    # same created_at: stable tie-break by proposal_hash (the highest stays)
    a = _make_proposal(
        tmp_path, "a.md", page_id="pg", created_at="2026-06-01", gate_state="created", body="alpha\n"
    )
    b = _make_proposal(
        tmp_path, "b.md", page_id="pg", created_at="2026-06-01", gate_state="created", body="beta\n"
    )
    result = rebase_pending(tmp_path, page_id="pg")
    hashes = {p: read_proposal(p).proposal_hash for p in (a, b)}
    expected_keeper = max((a, b), key=lambda p: hashes[p])
    assert result["kept"] == expected_keeper


def test_rebase_pending_all_groups_without_filter(tmp_path: Path) -> None:
    _make_proposal(tmp_path, "x_old.md", page_id="pg-x", created_at="2026-06-01", gate_state="created")
    x_new = _make_proposal(
        tmp_path, "x_new.md", page_id="pg-x", created_at="2026-06-08", gate_state="created"
    )
    _make_proposal(tmp_path, "y_old.md", page_id="pg-y", created_at="2026-06-01", gate_state="created")
    y_new = _make_proposal(
        tmp_path, "y_new.md", page_id="pg-y", created_at="2026-06-08", gate_state="created"
    )
    result = rebase_pending(tmp_path)
    assert set(result["kept"]) == {x_new, y_new}
    assert len(result["superseded"]) == 2


def test_rebase_groups_by_rebase_key(tmp_path: Path) -> None:
    # Same logical target (rebase_key), distinct page_id per date (re-ingestion).
    _make_proposal(tmp_path, "a.md", page_id="ingestion-2026-06-01-system-source",
                   gate_state="created", created_at="2026-06-01", rebase_key="system-source")
    _make_proposal(tmp_path, "b.md", page_id="ingestion-2026-06-03-system-source",
                   gate_state="created", created_at="2026-06-03", rebase_key="system-source")
    newest = _make_proposal(tmp_path, "c.md", page_id="ingestion-2026-06-05-system-source",
                            gate_state="created", created_at="2026-06-05", rebase_key="system-source")
    # Distinct target: must not be touched even though it is in the same context.
    other = _make_proposal(tmp_path, "z.md", page_id="ingestion-2026-06-05-system-other",
                           gate_state="created", created_at="2026-06-05", rebase_key="system-other")

    result = rebase_pending(tmp_path, rebase_key="system-source")
    assert Path(result["kept"]).name == "c.md"
    assert {Path(p).name for p in result["superseded"]} == {"a.md", "b.md"}
    assert read_proposal(newest).gate_state == "created"
    assert read_proposal(other).gate_state == "created"
    assert read_proposal(tmp_path / "a.md").gate_state == "superseded"


def test_force_only_enables_superseded(tmp_path: Path) -> None:
    # _force does NOT open invalid voluntary transitions (rejected -> approved).
    rejected = _make_proposal(tmp_path, "r.md", page_id="pg", gate_state="rejected")
    with pytest.raises(ValueError):
        write_state(rejected, "approved", _force=True)
    # but it enables supersede-by-rebase from a pending state.
    created = _make_proposal(tmp_path, "c.md", page_id="pg2", gate_state="created")
    assert write_state(created, "superseded", _force=True).gate_state == "superseded"
