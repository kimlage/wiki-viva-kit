from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from wiki_core.action_adoption import (
    ACTION_ADOPTION_SCHEMA_VERSION,
    action_documents_at_commit,
    action_inventory,
    compile_action_adoption_receipt,
    render_action_adoption_receipt,
    verify_action_adoption_git_contract,
)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def _action(state: str = "open") -> str:
    return (
        "---\n"
        "page_id: action-adoption\n"
        "page_type: action\n"
        f"action_state: {state}\n"
        "next_action: Review the adoption fixture.\n"
        "updated_at: 2026-07-11\n"
        "---\n\n"
        "# Action adoption\n"
    )


def _repo(tmp_path: Path) -> tuple[str, str]:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    action = tmp_path / "memories/actions/action.md"
    action.parent.mkdir(parents=True)
    action.write_text(_action(), encoding="utf-8")
    script = tmp_path / "scripts/wiki_audit.py"
    script.parent.mkdir(parents=True)
    script.write_text("def audit_contract():\n    return True\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "pre-gate baseline")
    baseline = _git(tmp_path, "rev-parse", "HEAD")

    script.write_text(
        "def audit_action_state_transitions(errors):\n    return None\n",
        encoding="utf-8",
    )
    _git(tmp_path, "add", "scripts/wiki_audit.py")
    _git(tmp_path, "commit", "-m", "introduce action gate")
    gate = _git(tmp_path, "rev-parse", "HEAD")
    return baseline, gate


def test_action_inventory_is_content_bound_and_ignores_non_actions() -> None:
    documents = {
        "memories/actions/action.md": _action(),
        "memories/actions/index.md": (
            "---\npage_id: actions-index\npage_type: ontology_index\n---\n"
        ),
    }

    rows, digest = action_inventory(documents)

    assert len(rows) == 1
    assert rows[0]["page_id"] == "action-adoption"
    assert rows[0]["state"] == "open"
    assert len(digest) == 64
    changed = {**documents, "memories/actions/action.md": _action("in_progress")}
    assert action_inventory(changed)[1] != digest


def test_action_adoption_receipt_verifies_exact_gate_parent_and_inventory(
    tmp_path: Path,
) -> None:
    baseline, gate = _repo(tmp_path)
    documents = action_documents_at_commit(tmp_path, baseline, "memories")
    receipt = compile_action_adoption_receipt(
        repo_id="fixture",
        audit_base_commit=baseline,
        baseline_commit=baseline,
        gate_introduced_commit=gate,
        recorded_at="2026-07-11T18:00:00Z",
        reason="Adopt the exact action tree that predates the receipt gate.",
        documents=documents,
    )

    assert receipt["schema_version"] == ACTION_ADOPTION_SCHEMA_VERSION
    assert receipt["action_count"] == 1
    assert receipt["receipt_id"].startswith("sha256:")
    assert verify_action_adoption_git_contract(
        tmp_path,
        receipt,
        repo_id="fixture",
        memory_root="memories",
        audit_base_commit=baseline,
    ) == []
    rendered = render_action_adoption_receipt(receipt)
    assert "action_inventory_sha256:" in rendered
    assert yaml.safe_load(rendered)["recorded_at"] == "2026-07-11T18:00:00Z"

    tampered = {**receipt, "action_count": 2}
    errors = verify_action_adoption_git_contract(
        tmp_path,
        tampered,
        repo_id="fixture",
        memory_root="memories",
        audit_base_commit=baseline,
    )
    assert "action_adoption_count_mismatch" in errors
    assert "action_adoption_receipt_id_mismatch" in errors


def test_action_adoption_rejects_non_parent_baseline(tmp_path: Path) -> None:
    baseline, gate = _repo(tmp_path)
    documents = action_documents_at_commit(tmp_path, baseline, "memories")
    receipt = compile_action_adoption_receipt(
        repo_id="fixture",
        audit_base_commit=baseline,
        baseline_commit=gate,
        gate_introduced_commit=gate,
        recorded_at="2026-07-11T18:00:00Z",
        reason="Synthetic invalid parent proof.",
        documents=documents,
    )

    assert "action_adoption_baseline_is_not_gate_parent" in (
        verify_action_adoption_git_contract(
            tmp_path,
            receipt,
            repo_id="fixture",
            memory_root="memories",
            audit_base_commit=baseline,
        )
    )


def test_action_adoption_rejects_invalid_calendar_instant() -> None:
    with pytest.raises(ValueError, match="invalid_action_adoption_recorded_at"):
        compile_action_adoption_receipt(
            repo_id="fixture",
            audit_base_commit="a" * 40,
            baseline_commit="b" * 40,
            gate_introduced_commit="c" * 40,
            recorded_at="2026-99-99T18:00:00Z",
            reason="Synthetic invalid timestamp proof.",
            documents={"memories/actions/action.md": _action()},
        )


def test_action_documents_reject_absolute_memory_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsafe_action_adoption_memory_root"):
        action_documents_at_commit(tmp_path, "a" * 40, "/memories")


def test_action_adoption_requires_audit_base_ancestry(tmp_path: Path) -> None:
    baseline, gate = _repo(tmp_path)
    _git(tmp_path, "checkout", "--orphan", "unrelated")
    unrelated_file = tmp_path / "unrelated.txt"
    unrelated_file.write_text("unrelated\n", encoding="utf-8")
    _git(tmp_path, "add", "unrelated.txt")
    _git(tmp_path, "commit", "-m", "unrelated base")
    unrelated = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "checkout", "main")
    documents = action_documents_at_commit(tmp_path, baseline, "memories")
    receipt = compile_action_adoption_receipt(
        repo_id="fixture",
        audit_base_commit=unrelated,
        baseline_commit=baseline,
        gate_introduced_commit=gate,
        recorded_at="2026-07-11T18:00:00Z",
        reason="Synthetic unrelated audit base proof.",
        documents=documents,
    )

    assert "action_adoption_audit_base_not_ancestor_of_gate" in (
        verify_action_adoption_git_contract(
            tmp_path,
            receipt,
            repo_id="fixture",
            memory_root="memories",
            audit_base_commit=unrelated,
        )
    )
