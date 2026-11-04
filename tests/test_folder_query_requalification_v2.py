"""Explicit query requalification produces a review candidate only."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from tests.test_folder_query_v2 import project, fixture_query, put, git, commit
from tests.test_folder_query_packet_v2 import result_for
from wiki_core.folder_packet_v2 import build_folder_packet_v2
from wiki_core.folder_policy_v2 import load_folder_policy_v2
from wiki_core.folder_query_packet_v2 import build_folder_query_packet_v2, preflight_folder_query_v2
from wiki_core.folder_query_requirements_v2 import query_requirements


def test_selected_requalification_preserves_other_requirements(project, tmp_path):
    _, _, query = fixture_query(project)
    put(project, 'a/extra.md', '---\npage_id: extra\n---\nOther evidence\n'); commit(project)
    old = git(project, 'rev-parse', 'HEAD'); policy = load_folder_policy_v2(project, old)
    evidence = [{'path':'a/extra.md', 'producer_folder':'a', 'reason':'other',
                 'use':'interpret', 'classification':'synthetic'}]
    base = build_folder_packet_v2(project, policy, 'a', 100000, index_path='a/index.md',
        content_revision=old, task_id='original', goal='review', output='a/result.md', integrator='reviewer', evidence=evidence)
    packet = build_folder_query_packet_v2(project, policy, base_packet=base, queries=[query])
    original_req = query_requirements(packet['queries'], 30)[0]
    other = {'target':'a/extra.md', 'fields':['*'], 'temporal':'current', 'max_age_days':60,
             'consumed_revision':old, 'use':'interpret', 'classification':'synthetic'}
    result = result_for(packet, [{'path':'a/result.md', 'action':'created'}])
    initial_branch = git(project, 'branch', '--show-current')
    git(project, 'checkout', '-qb', 'wiki/original-query')
    put(project, 'a/result.md', '---\n' + yaml.safe_dump({'page_type':'claim',
        'information_requirements':[original_req, other]}, sort_keys=False) + '---\nOriginal\n')
    git(project, 'add', 'a/result.md'); git(project, 'commit', '-qm', 'original claim')
    integrated = git(project, 'rev-parse', 'HEAD')
    assert preflight_folder_query_v2(project, policy, base=old, head=integrated,
        branch='wiki/original-query', packet=packet, result=result)['state'] == 'independent_review_required'
    git(project, 'checkout', '-q', initial_branch)
    git(project, 'merge', '--ff-only', 'wiki/original-query')
    git(project, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    put(project, 'a/items/one.md', '---\npage_id: one\nstatus: active\namount: 12\n---\nChanged\n')
    commit(project); current = git(project, 'rev-parse', 'HEAD'); policy = load_folder_policy_v2(project, current)
    evidence = [{'path':'a/result.md', 'producer_folder':'a', 'reason':'prior',
                 'use':'interpret', 'classification':'synthetic'}]
    next_base = build_folder_packet_v2(project, policy, 'a', 100000, index_path='a/index.md',
        content_revision=current, task_id='refresh', goal='review', output='a/result.md', integrator='reviewer', evidence=evidence)
    next_packet = build_folder_query_packet_v2(project, policy, base_packet=next_base, queries=[query])
    updated_req = query_requirements(next_packet['queries'], 30)[0]
    assert updated_req['query_id'] == original_req['query_id']
    next_result = result_for(next_packet, [{'path':'a/result.md', 'action':'modified'}])
    report = {'target':'a/result.md', 'query_id':original_req['query_id'], 'packet':packet,
              'result':result, 'integrated_revision':integrated}
    git(project, 'checkout', '-qb', 'wiki/requalify-query')
    def write(requirements):
        put(project, 'a/result.md', '---\n' + yaml.safe_dump({'page_type':'claim',
            'information_requirements':requirements}, sort_keys=False) + '---\nUpdated\n')
        git(project, 'add', 'a/result.md'); git(project, 'commit', '--amend', '-qm', 'query requalification')
        return git(project, 'rev-parse', 'HEAD')
    put(project, 'a/result.md', '---\n' + yaml.safe_dump({'page_type':'claim',
        'information_requirements':[updated_req, other]}, sort_keys=False) + '---\nUpdated\n')
    git(project, 'add', 'a/result.md'); git(project, 'commit', '-qm', 'query requalification')
    head = git(project, 'rev-parse', 'HEAD')
    common = {'base':current, 'head':head, 'branch':'wiki/requalify-query', 'packet':next_packet, 'result':next_result}
    with pytest.raises(ValueError):
        preflight_folder_query_v2(project, policy, **common)
    out = preflight_folder_query_v2(project, policy, **common, query_requalifications=[report])
    assert out['query_requalification'] == {'count':1, 'state':'independent_review_required',
                                             'review':'not_performed', 'freshness':'not_assessed'}
    assert out['prior_requirements_handling'] == 'preserved_not_revalidated'
    assert out['merge'] == 'not_performed'
    with pytest.raises(ValueError, match='require separate proposals'):
        preflight_folder_query_v2(project, policy, **common, query_requalifications=[report], requalify_source=True)
    from wiki_core.folder_integration_v2 import preflight_folder_v2
    with pytest.raises(ValueError, match='require separate proposals'):
        preflight_folder_v2(project, policy, base=current, head=head, branch='wiki/requalify-query',
            packet=next_base, result={}, query_requalifications=[report], requalify_source=True)
    forged = deepcopy(report); forged['result']['observed_queries'] = []
    with pytest.raises(ValueError):
        preflight_folder_query_v2(project, policy, **common, query_requalifications=[forged])
    changed_other = deepcopy(other); changed_other['max_age_days'] = 59
    with pytest.raises(ValueError):
        preflight_folder_query_v2(project, policy, **{**common, 'head':write([updated_req, changed_other])},
                                  query_requalifications=[report])
    common['head'] = write([updated_req, other])
    wrong_scope = deepcopy(report); wrong_scope['query_id'] = '0' * 64
    with pytest.raises(ValueError):
        preflight_folder_query_v2(project, policy, **common, query_requalifications=[wrong_scope])
    changed_query = deepcopy(query); changed_query['query']['scope'] = 'a/other'
    changed_packet = build_folder_query_packet_v2(project, policy, base_packet=next_base, queries=[changed_query])
    changed_req = query_requirements(changed_packet['queries'], 30)[0]
    changed_result = result_for(changed_packet, [{'path':'a/result.md', 'action':'modified'}])
    changed_head = write([changed_req, other])
    with pytest.raises(ValueError):
        preflight_folder_query_v2(project, policy, base=current, head=changed_head, branch='wiki/requalify-query',
            packet=changed_packet, result=changed_result, query_requalifications=[report])
    (project / 'a/result.md').unlink()
    git(project, 'add', '-A'); git(project, 'commit', '--amend', '-qm', 'deleted output')
    deleted_result = result_for(next_packet, [{'path':'a/result.md', 'action':'deleted'}])
    with pytest.raises(ValueError):
        preflight_folder_query_v2(project, policy, **{**common, 'head':git(project, 'rev-parse', 'HEAD'),
            'result':deleted_result}, query_requalifications=[report])
    common['head'] = write([updated_req, other])
    pp = tmp_path/'packet.json'; rp = tmp_path/'result.json'; hp = tmp_path/'history.json'
    pp.write_text(json.dumps(next_packet)); rp.write_text(json.dumps(next_result)); hp.write_text(json.dumps([report]))
    cli = Path(__file__).resolve().parents[1] / 'scripts/wiki_context_flow.py'
    called = subprocess.run([sys.executable, str(cli), '--repo', str(project), '--approved-revision', current,
        'preflight', '--folder', 'a', '--index', 'a/index.md', '--base', current, '--head', common['head'],
        '--branch', 'wiki/requalify-query', '--packet', str(pp), '--result', str(rp),
        '--query-requalifications', str(hp)], capture_output=True, text=True)
    assert called.returncode == 0, called.stderr
    assert json.loads(called.stdout)['query_requalification']['review'] == 'not_performed'
