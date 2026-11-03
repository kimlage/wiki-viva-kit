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



def test_duplicate_primary_refused(tmp_path):
    _, snapshot, policy = fixture(tmp_path)
    policy["profiles"]["other"]["action_ids"] = ["task"]
    (tmp_path / "wiki.coordination.yaml").write_text(yaml.safe_dump(policy))
    with pytest.raises(CoordinationError, match="multiple primary"):
        coordination_index(tmp_path, snapshot)



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


@pytest.mark.parametrize('snapshot', [None, {'pages.json': {'pages': []}}])
def test_retired_profile_packet_is_constant_without_reads(tmp_path, monkeypatch, snapshot):
    from wiki_core import coordination as module
    monkeypatch.setattr(module, '_read', lambda *a: pytest.fail('legacy read'))
    monkeypatch.setattr(module.RepositoryReader, 'catalogue', lambda *a, **k: pytest.fail('catalogue'))
    result = context_packet(tmp_path, None, snapshot, 'private-profile', 'private-action',
                            authorize_ref=lambda *a: pytest.fail('authorization callback'))
    assert result == context_packet(tmp_path, None, None, 'unknown')
    assert result['error_code'] == 'coordination_context_required'
    assert 'private' not in str(result) and 'pages' not in result


def cli_module(monkeypatch):
    import importlib.util
    scripts = Path(__file__).resolve().parents[1] / 'scripts'
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location('convergence_cli', scripts / 'wiki_coordination.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_profile_cli_does_not_load_config_or_snapshot(tmp_path, monkeypatch, capsys):
    import json
    import sys
    module = cli_module(monkeypatch)
    monkeypatch.setattr(module, 'load_config', lambda *a: pytest.fail('config read'))
    monkeypatch.setattr(sys, 'argv', ['wiki_coordination.py', '--root', str(tmp_path / 'absent'), '--profile', 'unknown'])
    module.main()
    assert json.loads(capsys.readouterr().out)['error_code'] == 'coordination_context_required'


def dialogue_fixture(tmp_path):
    config, snapshot, policy = fixture(tmp_path)
    actions = tmp_path / 'memories/actions'
    actions.mkdir()
    path = actions / 'task.md'
    (tmp_path / 'memories/task.md').rename(path)
    raw = path.read_text().replace('action_state: open', 'action_state: open\nnext_action: Review synthetic evidence')
    path.write_text(raw)
    return path, hashlib.sha256(raw.encode()).hexdigest()


def test_cli_dialogue_exact_action_preserves_route_state_and_cas(tmp_path, monkeypatch, capsys):
    import json
    import sys
    module = cli_module(monkeypatch)
    path, sha = dialogue_fixture(tmp_path)
    event = {'event_id': 'comment-0001', 'kind': 'comment', 'text': 'Synthetic note', 'coordinator': 'research'}
    event_file = tmp_path / 'event.json'
    event_file.write_text(json.dumps(event))
    # Other pages can be invalid: event route must never catalogue/read them.
    (tmp_path / 'memories/archived.md').write_text('invalid unrelated action')
    args = ['wiki_coordination.py', '--root', str(tmp_path), '--profile', 'research', '--action-id', 'task', '--action-path', 'memories/actions/task.md', '--event-file', str(event_file), '--expected-sha256', sha]
    monkeypatch.setattr(sys, 'argv', args)
    module.main()
    assert json.loads(capsys.readouterr().out)['ok']
    from wiki_core.frontmatter import parse_frontmatter
    fm, _ = parse_frontmatter(path.read_text())
    assert fm['action_state'] == 'open'
    assert fm['action_dialogue'][0]['coordinator'] == 'research'
    assert fm['action_dialogue'][0]['actor'] == 'coordinator:research'
    before = path.read_bytes()
    # Existing idempotency/guard handling is delegated to the same writer.
    try:
        module.main()
    except ValueError:
        pass
    assert path.read_bytes() == before


@pytest.mark.parametrize('ref,action,coordinator', [('../escape.md','task','research'), ('memories/source.md','task','research'), ('memories/actions/task.md','other','research'), ('memories/actions/task.md','task','other')])
def test_dialogue_invalid_path_identity_or_route_never_writes(tmp_path, ref, action, coordinator):
    from wiki_core.coordination import dialogue_action
    path, _ = dialogue_fixture(tmp_path)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        dialogue_action(tmp_path, ref, action, {'coordinator':coordinator})
    assert path.read_bytes() == before


def test_dialogue_rechecks_assignment_inside_existing_writer_fence(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from wiki_core import action_transition as writer
    from wiki_core.coordination import transition_dialogue_action
    path, sha = dialogue_fixture(tmp_path)
    before = path.read_bytes()
    native_lock = writer._action_file_lock
    @contextmanager
    def changed_route(root, ref):
        with native_lock(root, ref):
            policy_file = root / 'wiki.coordination.yaml'
            policy = yaml.safe_load(policy_file.read_text())
            policy['profiles']['research']['action_ids'].remove('task')
            policy_file.write_text(yaml.safe_dump(policy))
            yield
    monkeypatch.setattr(writer, '_action_file_lock', changed_route)
    with pytest.raises(CoordinationError, match='another coordinator'):
        transition_dialogue_action(tmp_path, 'memories/actions/task.md', 'task',
            {'event_id':'comment-0001','kind':'comment','text':'note','coordinator':'research'}, expected_sha256=sha)
    assert path.read_bytes() == before


@pytest.mark.parametrize('ancestor', [False, True])
def test_dialogue_rejects_symlink_file_and_ancestor(tmp_path, ancestor):
    from wiki_core.coordination import dialogue_action
    path, _ = dialogue_fixture(tmp_path)
    if ancestor:
        directory = path.parent
        directory.rename(directory.with_name('original-actions'))
        directory.symlink_to(directory.with_name('original-actions'), target_is_directory=True)
    else:
        path.rename(path.with_name('original.md'))
        path.symlink_to(path.with_name('original.md'))
    with pytest.raises(ValueError):
        dialogue_action(tmp_path, 'memories/actions/task.md', 'task', {'coordinator':'research'})


def test_index_preserves_transversal_assignment_and_descriptive_access(tmp_path):
    _, snapshot, policy = fixture(tmp_path)
    for item in snapshot['pages.json']['pages']:
        if item['id'] in {'task','archived'}:
            item['context'] = 'first' if item['id']=='task' else 'second'
    policy['profiles']['research']['access_requirements'] = [{'service':'Synthetic mail','expected_identity':'research@example.test','method':'verify identity','source_ref':'source'}]
    policy['profiles']['research']['context_pages'] = ['missing-inert-ref']
    (tmp_path/'wiki.coordination.yaml').write_text(yaml.safe_dump(policy))
    before = {p:p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    index = coordination_index(tmp_path, snapshot)
    assert index['trust_boundary']=='caller_trust' and not index['policy_enforced']
    assert {(a['action_id'],a['coordinator'],a['state']) for a in index['actions']} == {('task','research','open'),('archived','research','done')}
    profile = next(p for p in index['profiles'] if p['id']=='research')
    assert profile['access_requirements'][0]['source_ref']=='source' and not profile['access_verified']
    assert all(p.read_bytes()==raw for p,raw in before.items())


@pytest.mark.parametrize('key,value', [
    ('actions_dirname','/'), ('actions_dirname','../'),
    ('actions_dirname','../actions'), ('actions_dirname','.'),
    ('actions_dirname','nested/actions'), ('actions_dirname','actions/'),
    ('memory_root','/'), ('memory_root','/tmp/memories'),
    ('memory_root','../memories'), ('memory_root','memories/../'),
    ('memory_root','.'), ('memory_root','memories//nested'),
])
def test_invalid_configured_dialogue_root_rejected_before_action_inspection(tmp_path, monkeypatch, key, value):
    from wiki_core import coordination as module
    from wiki_core import action_transition as writer
    fixture(tmp_path)
    (tmp_path/'wiki.config.yaml').write_text(yaml.safe_dump({'paths':{key:value}}))
    monkeypatch.setattr(module, '_read', lambda *a: pytest.fail('action or routing content read'))
    monkeypatch.setattr(writer, '_contained_action_path', lambda *a: pytest.fail('action inspected before configured root validation'))
    with pytest.raises(CoordinationError, match='invalid configured actions directory'):
        module.dialogue_action(tmp_path,'memories/task.md','task',{'coordinator':'research'})


@pytest.mark.parametrize('linked', ['memory','ancestor','actions'])
def test_configured_dialogue_root_symlinks_rejected_before_content(tmp_path, monkeypatch, linked):
    from wiki_core import coordination as module
    path, _ = dialogue_fixture(tmp_path)
    if linked == 'memory':
        original = tmp_path/'memories'
    elif linked == 'actions':
        original = path.parent
    else:
        # A nested memory root also checks each configured ancestor.
        (tmp_path/'container').mkdir()
        (tmp_path/'memories').rename(tmp_path/'container/memories')
        original = tmp_path/'container'
        (tmp_path/'wiki.config.yaml').write_text('paths:\n  memory_root: container/memories\n')
    saved = original.with_name(original.name+'-original')
    original.rename(saved)
    original.symlink_to(saved, target_is_directory=True)
    monkeypatch.setattr(module, '_read', lambda *a: pytest.fail('action or routing content read'))
    with pytest.raises(CoordinationError, match='invalid configured actions directory'):
        module.dialogue_action(tmp_path,'memories/actions/task.md','task',{'coordinator':'research'})


def test_dialogue_valid_custom_relative_layout(tmp_path):
    from wiki_core.coordination import dialogue_action
    path, _ = dialogue_fixture(tmp_path)
    custom = tmp_path/'knowledge/notes/work-items'
    custom.mkdir(parents=True)
    path.rename(custom/'unrelated-filename.md')
    (tmp_path/'wiki.config.yaml').write_text('paths:\n  memory_root: knowledge/notes\n  actions_dirname: work-items\n')
    result = dialogue_action(tmp_path,'knowledge/notes/work-items/unrelated-filename.md','task',{'coordinator':'research'})
    assert result == {'path':'knowledge/notes/work-items/unrelated-filename.md','state':'open'}
