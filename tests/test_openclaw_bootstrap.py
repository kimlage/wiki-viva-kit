"""Fresh-session bootstrap admission and receipt-chain regressions."""
import copy
import hashlib
import json
import subprocess

import pytest
import yaml

from tests.test_openclaw_commands import runtime
from wiki_core.config import load_config
from wiki_core.web import openclaw as oc


def fresh(runtime):
    root, _, params, history, calls, snapshot = runtime
    settings = yaml.safe_load((root / 'wiki.config.yaml').read_text())
    route = settings['openclaw']['routes']['research']
    route.pop('native_thread_id')
    route['native_thread_binding'] = 'first_turn'
    (root / 'wiki.config.yaml').write_text(yaml.safe_dump(settings))
    subprocess.run(['git', 'add', '.'], cwd=root, check=True, capture_output=True)
    subprocess.run(['git', 'commit', '-qm', 'synthetic fresh binding'], cwd=root, check=True, capture_output=True)
    history['sessionInfo'].update(activeLeafEntryId=None, lastRunId=None, status='idle')
    history.update(totalMessages=0, messages=[], hasMore=False)
    return root, load_config(root), params, history, calls, snapshot


def test_bootstrap_preserves_selection_and_null_leaf_in_native_send(runtime):
    root, cfg, params, history, calls, _ = fresh(runtime)
    plan = oc.plan_dispatch(root, cfg, params)
    assert plan['mission']['native_thread_id'] is None
    assert plan['mission']['native_thread_binding'] == 'first_turn'
    assert plan['expected_leaf'] is None
    oc.dispatch(root, cfg, plan)
    send = next(p for method, p in calls if method == 'chat.send')
    assert send['expectedLeafEntryId'] is None and send['thinking'] == 'high'
    contract = oc.read_receipt(oc.storage(root, cfg, plan['effect_key']) / 'mission.json')
    assert contract['native_thread_binding'] == 'first_turn'
    assert contract['model'] == 'example-model'


@pytest.mark.parametrize('change', ['leaf', 'run', 'messages', 'count', 'more', 'missing_count'])
def test_bootstrap_requires_explicit_empty_history(runtime, change):
    root, cfg, params, h, calls, _ = fresh(runtime)
    if change == 'leaf': h['sessionInfo']['activeLeafEntryId'] = 'previous-leaf'
    if change == 'run': h['sessionInfo']['lastRunId'] = 'prior-run'
    if change == 'messages': h['messages'] = [{'role': 'user', 'content': 'synthetic'}]
    if change == 'count': h['totalMessages'] = 1
    if change == 'more': h['hasMore'] = True
    if change == 'missing_count': h.pop('totalMessages')
    with pytest.raises(ValueError, match='bootstrap_not_empty'):
        oc.plan_dispatch(root, cfg, params)
    assert not any(method == 'chat.send' for method, _ in calls)


def test_activity_between_plan_and_dispatch_has_no_send(runtime):
    root, cfg, params, h, calls, _ = fresh(runtime)
    plan = oc.plan_dispatch(root, cfg, params)
    h['sessionInfo'].update(activeLeafEntryId='concurrent-leaf', lastRunId='concurrent-run')
    with pytest.raises(ValueError, match='session_changed'):
        oc.dispatch(root, cfg, plan)
    assert not any(method == 'chat.send' for method, _ in calls)
    assert not (oc.storage(root, cfg, plan['effect_key']) / 'intent.json').exists()


def test_bootstrap_receipt_requires_creation_and_same_thread_through_terminal(runtime):
    root, cfg, params, _, _, _ = fresh(runtime)
    plan = oc.plan_dispatch(root, cfg, params)
    oc.dispatch(root, cfg, plan)
    directory = oc.storage(root, cfg, plan['effect_key'])
    contract = oc.read_receipt(directory / 'mission.json')
    sha = hashlib.sha256((directory / 'mission.json').read_bytes()).hexdigest()
    common = {'run_id': plan['effect_key'], 'session_id': plan['route']['session_id'], 'contract_sha256': sha}
    thread = {**common, 'thread_id': 'synthetic-created-thread', 'model': contract['model']}
    claim = {**thread, 'schema_version': 'wiki_openclaw_guard_turn.v1', 'effort': 'high'}
    bound = {**claim, 'turn_id': 'synthetic-turn'}
    values = {'guard-bootstrap-admission.json': common, 'guard-bootstrap-start.json': common,
              'guard-bootstrap-thread.json': thread, 'guard-turn.json': claim,
              'guard-bound-turn.json': bound, 'guard-terminal.json': {**bound, 'status': 'completed'}}
    for name, value in values.items(): oc.write_new(directory / name, value)
    (directory / 'guard-inference.jsonl').write_text(json.dumps({**bound, 'path': '/responses'}) + '\n')
    oc.verify_mission_selection(directory, plan, {'model': 'example-model'})
    for name in ('guard-bootstrap-admission.json', 'guard-bootstrap-start.json', 'guard-bootstrap-thread.json'):
        original = (directory / name).read_bytes()
        bad = copy.deepcopy(values[name]); bad['session_id'] = 'wrong-session'
        (directory / name).write_text(json.dumps(bad))
        with pytest.raises(ValueError, match='bootstrap_unproven'):
            oc.verify_mission_selection(directory, plan, {'model': 'example-model'})
        (directory / name).write_bytes(original)
    values['guard-bootstrap-thread.json']['thread_id'] = 'another-thread'
    (directory / 'guard-bootstrap-thread.json').write_text(json.dumps(values['guard-bootstrap-thread.json']))
    with pytest.raises(ValueError, match='bootstrap_unproven'):
        oc.verify_mission_selection(directory, plan, {'model': 'example-model'})


def test_route_refuses_ambiguous_or_unknown_binding(runtime):
    _, cfg, _, _, _, _ = fresh(runtime)
    settings = copy.deepcopy(cfg.openclaw)
    route = settings['routes']['research']
    route['native_thread_id'] = 'synthetic-existing-thread'
    with pytest.raises(ValueError, match='invalid_route'): oc.validated_config(settings)
    route.pop('native_thread_id'); route['native_thread_binding'] = 'automatic'
    with pytest.raises(ValueError, match='invalid_route'): oc.validated_config(settings)
