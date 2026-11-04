"""A later query preserves, without revalidating, prior ingestion projections."""
from copy import deepcopy
import yaml
import pytest

from tests.test_folder_consolidate_v2 import fixture_inputs, metadata
from tests.test_folder_policy_v2 import project, put, git
from tests.test_folder_query_packet_v2 import result_for
from wiki_core.consolidate import prepare_folder_consolidation
from wiki_core.folder_packet_v2 import build_folder_packet_v2
from wiki_core.folder_policy_v2 import load_folder_policy_v2
from wiki_core.folder_query_packet_v2 import build_folder_query_packet_v2, preflight_folder_query_v2
from wiki_core.folder_query_requirements_v2 import query_requirements
from wiki_core.frontmatter import parse_frontmatter


@pytest.mark.parametrize('kind', ['raw', 'repository'])
def test_later_query_keeps_prior_provenance_without_claiming_revalidation(project, monkeypatch, tmp_path, capsys, kind):
    binding, request, results = fixture_inputs(project, monkeypatch, tmp_path, capsys,
        existing=True, with_query=True, raw=kind == 'raw', with_repo=kind == 'repository')
    first_packet = request['folder_query_packet']; base = request['block_context_package']
    first_result = result_for(first_packet, [{'path':base['output'], 'action':'modified'}])
    preview = prepare_folder_consolidation(project, binding, request, results, candidates=[],
        max_age_days=30, page_metadata=metadata(), query_packet=first_packet, query_result=first_result)
    old_branch = git(project, 'branch', '--show-current')
    git(project, 'checkout', '-qb', 'wiki/first-ingestion')
    put(project, base['output'], preview['markdown'])
    git(project, 'add', base['output']); git(project, 'commit', '-qm', 'first ingestion')
    first_head = git(project, 'rev-parse', 'HEAD')
    policy = load_folder_policy_v2(project, base['policy_revision'])
    assert preflight_folder_query_v2(project, policy, base=base['policy_revision'], head=first_head,
        branch='wiki/first-ingestion', packet=first_packet, result=first_result,
        binding=binding, source_request=request)['state'] == 'independent_review_required'
    git(project, 'checkout', '-q', old_branch)
    git(project, 'merge', '--ff-only', 'wiki/first-ingestion')
    git(project, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    if kind == 'raw':
        put(project, 'a/raw/source.md', 'Changed after the earlier capture\n')
    current = git(project, 'rev-parse', 'HEAD'); policy = load_folder_policy_v2(project, current)
    evidence = [{'path':base['output'], 'producer_folder':'a', 'reason':'prior output',
                 'use':'context', 'classification':'context'}]
    later_base = build_folder_packet_v2(project, policy, 'a', 100000, index_path='a/index.md',
        content_revision=current, task_id='later-query', goal='review', output=base['output'],
        integrator='reviewer', evidence=evidence)
    query = deepcopy(first_packet['queries'][0]['receipt']['request']); query['reason'] = 'later interpretation'
    later_packet = build_folder_query_packet_v2(project, policy, base_packet=later_base, queries=[query])
    later_result = result_for(later_packet, [{'path':base['output'], 'action':'modified'}])
    frontmatter, body = parse_frontmatter(preview['markdown'])
    frontmatter['information_requirements'] += query_requirements(later_packet['queries'], 30)
    new_text = '---\n' + yaml.safe_dump(frontmatter, sort_keys=False) + '---\n' + body + '\nLater interpretation\n'
    git(project, 'checkout', '-qb', 'wiki/later-query')
    put(project, base['output'], new_text)
    git(project, 'add', base['output']); git(project, 'commit', '-qm', 'later query')
    later_head = git(project, 'rev-parse', 'HEAD')
    kwargs = {'base':current, 'head':later_head, 'branch':'wiki/later-query',
              'packet':later_packet, 'result':later_result}
    outcome = preflight_folder_query_v2(project, policy, **kwargs)
    assert outcome['prior_ingestion_provenance'] == {
        'capture':'preserved_not_revalidated' if kind == 'raw' else 'absent',
        'repository':'preserved_not_revalidated' if kind == 'repository' else 'absent'}
    from jsonschema import validate
    import json
    from pathlib import Path
    schema = Path(__file__).resolve().parents[1] / 'docs/references/schemas/wiki-folder-query-preflight-v2.schema.json'
    validate(outcome, json.loads(schema.read_text()))
    changed = deepcopy(frontmatter)
    if kind == 'raw': changed['source_authorization']['source_sha256'] = '0' * 64
    else: changed['independent_repo_read']['content_sha256'] = '0' * 64
    put(project, base['output'], '---\n' + yaml.safe_dump(changed, sort_keys=False) + '---\n' + body)
    git(project, 'add', base['output']); git(project, 'commit', '--amend', '-qm', 'changed prior provenance')
    with pytest.raises(ValueError):
        preflight_folder_query_v2(project, policy, **{**kwargs, 'head':git(project, 'rev-parse', 'HEAD')})
