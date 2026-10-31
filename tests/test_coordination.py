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


def add_common_policy_pages(root, snapshot, policy):
    policy_pages = []
    for name in ("approvals", "operational-contract", "ingestion-process"):
        raw = f"---\npage_id: {name}\npage_type: operational_rule\n---\n# {name}\nCurrent synthetic policy.\n"
        path = f"memories/{name}.md"
        (root / path).write_text(raw)
        page = {"id": name, "path": path, "title": name, "page_type": "operational_rule",
                "content_sha256": hashlib.sha256(raw.encode()).hexdigest()}
        snapshot["pages.json"]["pages"].append(page)
        policy["common_context"].append(path)
        policy_pages.append(page)
    (root / "wiki.coordination.yaml").write_text(yaml.safe_dump(policy))
    return policy_pages


@pytest.mark.parametrize("profile,action", [("research", "task"), ("other", None)])
def test_common_policies_reach_each_profile_without_claiming_access(tmp_path, profile, action):
    config, snapshot, policy = fixture(tmp_path)
    common_pages = add_common_policy_pages(tmp_path, snapshot, policy)

    packet = context_packet(tmp_path, config, snapshot, profile, action)

    by_id = {page["id"]: page for page in packet["pages"]}
    for page in common_pages:
        assert by_id[page["id"]]["content_sha256"] == page["content_sha256"]
        assert by_id[page["id"]]["path"] == page["path"]
    assert packet["access_verified"] is False
    assert packet["runtime_connected"] is False
    assert packet["execution_ready"] is False
    assert {a["action_id"] for a in packet["actions"]} == ({action} if action else set())


def test_current_policy_change_requires_fresh_context_for_every_profile(tmp_path):
    config, snapshot, policy = fixture(tmp_path)
    common_pages = add_common_policy_pages(tmp_path, snapshot, policy)
    routes = [("research", "task"), ("other", None)]
    before = {profile: context_packet(tmp_path, config, snapshot, profile, action)
              for profile, action in routes}
    changed = common_pages[0]
    path = tmp_path / changed["path"]
    raw = path.read_text().replace("Current synthetic policy.", "Updated synthetic scope; preserve independent review.")
    path.write_text(raw)

    for profile, action in routes:
        with pytest.raises(CoordinationError, match="revision changed"):
            context_packet(tmp_path, config, snapshot, profile, action)

    changed["content_sha256"] = hashlib.sha256(raw.encode()).hexdigest()
    for profile, action in routes:
        packet = context_packet(tmp_path, config, snapshot, profile, action)
        assert packet["policy_sha256"] == before[profile]["policy_sha256"]
        assert packet["context_sha256"] != before[profile]["context_sha256"]
        current = next(page for page in packet["pages"] if page["id"] == changed["id"])
        assert current["content_sha256"] == changed["content_sha256"]
        assert current["body"] != next(page for page in before[profile]["pages"] if page["id"] == changed["id"])["body"]


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
    requirement = policy['profiles']['research']['access_requirements'][0]
    requirement.update(action_ids=['task'], operation='read', resource='Review inbox',
                       recovery='Select the expected account; do not create grants')
    (tmp_path / 'wiki.coordination.yaml').write_text(yaml.safe_dump(policy))
    packet = context_packet(tmp_path, config, snapshot, 'research', 'task')
    assert packet['access_requirements'][0]['operation'] == 'read'
    assert not packet['access_verified']
    requirement['action_ids'] = ['foreign-action']
    (tmp_path / 'wiki.coordination.yaml').write_text(yaml.safe_dump(policy))
    with pytest.raises(CoordinationError, match='another coordinator'):
        coordination_index(tmp_path, snapshot)

@pytest.mark.parametrize('dialogue', [['broken'], [{'kind': 'question'}], {}, False, 0])
def test_malformed_dialogue_has_controlled_error(tmp_path, dialogue):
    _, snapshot, _ = fixture(tmp_path)
    path = tmp_path / 'memories/task.md'
    raw = path.read_text().replace('source_refs: [source]', 'action_dialogue: ' + yaml.safe_dump(dialogue, default_flow_style=True).strip().removesuffix('...').strip() + '\nsource_refs: [source]')
    path.write_text(raw)
    next(p for p in snapshot['pages.json']['pages'] if p['id'] == 'task')['content_sha256'] = hashlib.sha256(raw.encode()).hexdigest()
    with pytest.raises(CoordinationError, match='invalid_action_dialogue'):
        coordination_index(tmp_path, snapshot)


def _front(root, snapshot, name, kind, fields):
    values = {"page_id": name, "page_type": kind, **fields}
    raw = "---\n" + yaml.safe_dump(values) + "---\n# Synthetic front\nExisting scope.\n"
    path = f"memories/{name}.md"
    (root / path).write_text(raw)
    page = {"id": name, "path": path, "title": name, "page_type": kind,
            "updated_at": "2026-07-01", "summary": "Existing scope.",
            "content_sha256": hashlib.sha256(raw.encode()).hexdigest()}
    snapshot['pages.json']['pages'].append(page)
    return page


def test_fronts_project_existing_pages_without_reopening_or_inventing_work(tmp_path):
    _, snapshot, policy = fixture(tmp_path)
    project = _front(tmp_path, snapshot, 'project', 'project',
                     {'status': 'paused', 'actions': ['task', 'archived'], 'owner': 'human',
                      'verified_at': '2026-06-30', 'next_action': 'Await existing decision'})
    _front(tmp_path, snapshot, 'context', 'context_note', {'tags': ['status/active']})
    policy['profiles']['research']['front_refs'] = ['context', 'missing-front']
    (tmp_path / 'wiki.coordination.yaml').write_text(yaml.safe_dump(policy))
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    payload = coordination_index(tmp_path, snapshot)
    fronts = {f['page_id']: f for f in payload['fronts']}
    assert set(fronts) == {'project', 'context'}
    assert fronts['project']['declared_status'] == 'paused'
    assert fronts['project']['active_action_ids'] == ['task']
    assert fronts['project']['action_ids'] == ['archived', 'task']
    assert fronts['project']['recorded_at'] == '2026-06-30'
    assert fronts['project']['live_execution'] == 'unknown'
    assert fronts['context']['declared_status'] == 'unknown'
    assert fronts['context']['action_ids'] == []
    assert payload['front_warnings'] == [{'code': 'front_reference_unresolved', 'ref': 'missing-front'}]
    assert all(p.read_bytes() == raw for p, raw in before.items())
    assert set(before) == {p for p in tmp_path.rglob('*') if p.is_file()}
    # Without any coordinator or executor, projects remain discoverable.
    (tmp_path / 'wiki.coordination.yaml').unlink()
    unconfigured = coordination_index(tmp_path, snapshot)
    assert not unconfigured['configured']
    assert [f['page_id'] for f in unconfigured['fronts']] == ['project']
    assert project['content_sha256'] == fronts['project']['content_sha256']


def test_front_drift_is_visible_without_expanding_protected_action_context(tmp_path):
    config, snapshot, policy = fixture(tmp_path)
    page = _front(tmp_path, snapshot, 'project', 'project', {})
    (tmp_path / page['path']).write_text('Changed outside this snapshot')
    payload = coordination_index(tmp_path, snapshot)
    assert payload['fronts'] == []
    assert payload['front_warnings'] == [{'code': 'front_revision_changed', 'ref': 'project'}]
    reads = []
    packet = context_packet(tmp_path, config, snapshot, 'research', 'task',
                            authorize_ref=lambda path, sha: reads.append(path))
    assert packet['actions'][0]['action_id'] == 'task'
    assert page['path'] not in reads
