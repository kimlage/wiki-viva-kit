import hashlib
from pathlib import Path

import pytest
import yaml

from wiki_core.config import load_config
from wiki_core.coordination import CoordinationError, context_packet, coordination_index, digest


def fixture(root: Path):
    (root / "AGENTS.md").write_text("Read sources; preserve ownership.")
    (root / "wiki.config.yaml").write_text("repo_id: synthetic\n")
    (root / "memories").mkdir()
    pages = []
    for name, kind in [("root", "context_hub"), ("source", "source"), ("task", "action"), ("archived", "action")]:
        state = "done" if name == "archived" else "open"
        raw = f"---\npage_id: {name}\npage_type: {kind}\naction_state: {state}\nexecutor_label: Existing external worker\nsource_refs: [source]\n---\n# {name}\nSynthetic evidence.\n"
        path = f"memories/{name}.md"
        (root / path).write_text(raw)
        pages.append({"id": name, "path": path, "title": name, "page_type": kind,
                      "content_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                      "work": {"state": state, "owner_ref": "human", "executor_label": "Existing external worker"}})
    policy = {"schema_version": "wiki_coordination.v1", "common_context": ["AGENTS.md", "root"],
              "profiles": {"research": {"label": "Research", "scope": "Research; preserve external worker.",
                                        "context_pages": ["source"], "action_ids": ["task", "archived"]},
                           "other": {"label": "Other", "scope": "Other scope.", "context_pages": ["root"], "action_ids": []}}}
    (root / "wiki.coordination.yaml").write_text(yaml.safe_dump(policy))
    snapshot = {"manifest.json": {"snapshot_id": "synthetic-snapshot"}, "pages.json": {"pages": pages}}
    return load_config(root), snapshot, policy


def test_packet_is_bound_to_profile_pages_sources_and_revisions(tmp_path):
    config, snapshot, _ = fixture(tmp_path)
    packet = context_packet(tmp_path, config, snapshot, "research", "task")
    assert {p["id"] for p in packet["pages"]} == {"root", "source", "task"}
    assert packet["actions"][0]["owner_ref"] == "human"
    assert packet["actions"][0]["executor_label"] == "Existing external worker"
    assert packet["execution_ready"] is False
    sha = packet.pop("context_sha256")
    assert sha == digest(packet)
    assert coordination_index(tmp_path, snapshot)["unmapped_action_ids"] == []


def test_terminal_history_is_never_reopened(tmp_path):
    config, snapshot, _ = fixture(tmp_path)
    p = context_packet(tmp_path, config, snapshot, "research", "archived")
    assert p["actions"][0]["state"] == "done"
    assert not p["actions"][0]["execution_ready"]


def test_mismatched_coordinator_refused(tmp_path):
    config, snapshot, _ = fixture(tmp_path)
    with pytest.raises(CoordinationError, match="another coordinator"):
        context_packet(tmp_path, config, snapshot, "other", "task")


def test_duplicate_primary_refused(tmp_path):
    _, snapshot, policy = fixture(tmp_path)
    policy["profiles"]["other"]["action_ids"] = ["task"]
    (tmp_path / "wiki.coordination.yaml").write_text(yaml.safe_dump(policy))
    with pytest.raises(CoordinationError, match="multiple primary"):
        coordination_index(tmp_path, snapshot)


@pytest.mark.parametrize("ref", ["../secret", "/etc/passwd", ".env", "missing"])
def test_unknown_or_sensitive_context_not_ingested(tmp_path, ref):
    config, snapshot, policy = fixture(tmp_path)
    policy["common_context"].append(ref)
    (tmp_path / "wiki.coordination.yaml").write_text(yaml.safe_dump(policy))
    with pytest.raises(CoordinationError, match="unknown context"):
        context_packet(tmp_path, config, snapshot, "research")


def test_changed_content_refused(tmp_path):
    config, snapshot, _ = fixture(tmp_path)
    (tmp_path / "memories/source.md").write_text("Changed after snapshot")
    with pytest.raises(CoordinationError, match="revision changed"):
        context_packet(tmp_path, config, snapshot, "research")


def test_symlink_context_refused(tmp_path):
    config, snapshot, _ = fixture(tmp_path)
    path = tmp_path / "memories/source.md"
    path.rename(tmp_path / "original.md")
    path.symlink_to(tmp_path / "original.md")
    with pytest.raises(CoordinationError, match="symlink"):
        context_packet(tmp_path, config, snapshot, "research")


def test_new_actions_remain_unmapped_not_auto_assigned(tmp_path):
    _, snapshot, _ = fixture(tmp_path)
    raw = "---\npage_id: new-action\npage_type: action\naction_state: open\n---\nNew evidence."
    (tmp_path / "memories/new.md").write_text(raw)
    snapshot["pages.json"]["pages"].append({"id": "new-action", "path": "memories/new.md", "page_type": "action", "content_sha256": hashlib.sha256(raw.encode()).hexdigest()})
    assert coordination_index(tmp_path, snapshot)["unmapped_action_ids"] == ["new-action"]


def test_duplicate_policy_keys_rejected(tmp_path):
    _, snapshot, _ = fixture(tmp_path)
    with (tmp_path / 'wiki.coordination.yaml').open('a') as f:
        f.write('\nprofiles: {}\n')
    with pytest.raises(CoordinationError, match='duplicate'):
        coordination_index(tmp_path, snapshot)


def test_access_requirements_are_context_not_verified_credentials(tmp_path):
    config, snapshot, policy = fixture(tmp_path)
    policy['profiles']['research']['access_requirements'] = [{'service':'Synthetic mail','expected_identity':'research@example.test','method':'browser identity check','source_ref':'source'}]
    policy['profiles']['research']['required_tools'] = ['browser']
    (tmp_path / 'wiki.coordination.yaml').write_text(yaml.safe_dump(policy))
    packet = context_packet(tmp_path, config, snapshot, 'research', 'task')
    assert packet['access_requirements'][0]['expected_identity'] == 'research@example.test'
    assert not packet['access_verified']
