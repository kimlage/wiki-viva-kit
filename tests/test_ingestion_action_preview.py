"""Composed real local helpers over fictional files. No executor or network."""
import copy
import hashlib
import socket
import subprocess
from pathlib import Path

import pytest
import yaml

from wiki_core.config import load_config
from wiki_core.page_creation import create_action_page
from wiki_core.web.ingestion_plan import build_ingestion_plan, compose_event_action_preview
from test_page_creation import fixture


def inputs():
    event = {"page_type": "ingestion_event", "page_id": "event-one", "event_id": "evt-one",
             "source_refs": ["source-logical"], "source_account": "reader@example.test", "context": "example"}
    binding = {"repo_id": "synthetic", "source_key": "source-logical", "account_id": "reader@example.test",
               "context": "example", "event_id": "evt-one", "event_sha256": "a"*64,
               "action_id": "task-one", "action_sha256": "b"*64, "owner_ref": "synthetic-owner", "coordinator": "research",
               "required_sources": ["corporate", "tasks"]}
    actions = [{"action_id": "task-one", "content_sha256": "b"*64, "context": "example", "owner_ref": "synthetic-owner",
                "coordinator": "research", "state": "open", "stop": False, "blockers": []}]
    return event, {"hash_sha256": "a"*64, "context": "example"}, binding, actions


def compose(values):
    return compose_event_action_preview("event.md", *values, repo_id="synthetic")


def test_replay_is_same_target_and_no_execution_or_io(monkeypatch):
    values = inputs(); before = copy.deepcopy(values)
    def refuse(*a, **k):
        pytest.fail("pure preview performed I/O")
    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(Path, "write_text", refuse)
    one = compose(values); two = compose(values)
    assert one == two and one["status"] == "reuse" and values == before
    assert one["task_ref"] == {"repo_id": "synthetic", "action_id": "task-one"}
    assert not one["execution_ready"] and not one["writes"]
    assert one["source_checks"] == {"corporate": "unknown", "tasks": "unknown"}


@pytest.mark.parametrize("field", ["event", "action"])
def test_revision_change_requires_reconciliation_without_new_target(field):
    values = inputs(); baseline = compose(values)
    if field == "event": values[1]["hash_sha256"] = "c"*64
    else: values[3][0]["content_sha256"] = "c"*64
    result = compose(values)
    assert result["status"] == "reconcile" and result["task_ref"] == baseline["task_ref"]
    assert result["preview_key"] == baseline["preview_key"]


@pytest.mark.parametrize("change", ["account", "context", "owner", "route", "duplicate", "source"])
def test_names_are_not_identity_and_crossed_bindings_conflict(change):
    values = inputs(); event, _, binding, actions = values
    event["title"] = actions[0]["title"] = "The same name"
    if change == "account": event["source_account"] = "second@example.test"
    if change == "context": actions[0]["context"] = "another"
    if change == "owner": actions[0]["owner_ref"] = "other-owner"
    if change == "route": actions[0]["coordinator"] = "another"
    if change == "duplicate": actions.append(dict(actions[0]))
    if change == "source": event["source_refs"] = ["unrelated"]
    assert compose(values)["status"] == "conflict"


@pytest.mark.parametrize("state", ["blocked", "waiting_human", "done", "cancelled"])
def test_reuse_is_only_a_link_and_preserves_waits_and_terminal_state(state):
    values = inputs(); values[3][0].update(state=state, stop=True, blockers=["retained"])
    out = compose(values)
    assert out["status"] == "reuse" and {state, "STOP", "retained"} <= set(out["blockers"])
    assert not out["execution_ready"] and values[3][0]["state"] == state


def test_missing_binding_and_new_card_are_unexecuted_proposals():
    event, manifest, _, actions = inputs()
    assert compose((event, manifest, None, actions))["status"] == "unmapped"
    values = inputs(); values[3].clear(); values[2]["action_sha256"] = ""
    result = compose(values)
    assert result["status"] == "propose" and result["blockers"] == ["coordinator_binding_pending"]
    assert not result["execution_ready"]


def test_real_manifest_template_creation_and_coordination_feed_existing_plan(tmp_path):
    root = fixture(tmp_path)
    cfg = load_config(root)
    created = create_action_page(root, title="Fictional source review", context="example", next_action="Review only", owner_kind="human", owner_ref="synthetic-owner")
    action = root / created["page_ref"]
    event_path = "notes/event.md"
    event, _, binding, _ = inputs()
    event["config_ref"] = "notes/source-config.md"
    raw = "---\n" + yaml.safe_dump(event) + "---\n# Fictional observation\n"
    (root / event_path).write_text(raw)
    binding.update(event_sha256=hashlib.sha256(raw.encode()).hexdigest(), action_id=created["page_id"], action_sha256=created["after_sha256"])
    (root / "notes/source-config.md").write_text("---\n" + yaml.safe_dump({"page_type": "source_config", "page_id": "config-one", "context": "example", "action_binding": binding}) + "---\n")
    (root / "wiki.coordination.yaml").write_text(yaml.safe_dump({"schema_version": "wiki_coordination.v1", "profiles": {
        "research": {"label": "Research", "scope": "Fictional local review", "action_ids": [created["page_id"]]}}}))
    snapshot = {"manifest.json": {"snapshot_id": "fictional"}, "pages.json": {"pages": [{
        "id": created["page_id"], "path": created["page_ref"], "page_type": "action", "context": "example", "content_sha256": created["after_sha256"],
        "work": {"state": "open", "owner_ref": "synthetic-owner"}}]}}
    original = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    first = build_ingestion_plan(root, cfg, event_path, context="example", snapshot=snapshot)
    second = build_ingestion_plan(root, cfg, event_path, context="example", snapshot=snapshot)
    assert first["action_preview"] == second["action_preview"]
    assert first["action_preview"]["status"] == "reuse"
    assert first["action_preview"]["task_ref"]["action_id"] == created["page_id"]
    assert {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()} == original
    assert action.read_bytes() == original[created["page_ref"]]
    assert build_ingestion_plan(root, cfg, event_path)["action_preview"]["reason"] == "canonical_snapshot_required"
