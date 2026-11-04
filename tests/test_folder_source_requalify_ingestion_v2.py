"""Requalify one explicit source against the exact prior Git blob."""
import hashlib
import json
import sys
from copy import deepcopy
import pytest
from tests.test_folder_policy_v2 import project, put, git
from tests.test_folder_multi_provenance_v2 import prior_repo, prior_raw
from tests.test_folder_consolidate_v2 import fixture_inputs, metadata
from tests.test_folder_ingestion_v2 import _recording_cli, _synthetic_result
from wiki_core.config import load_config
from wiki_core.consolidate import prepare_folder_consolidation
from wiki_core.folder_coordination_v2 import prepare_folder_preflight, FolderCoordinationError
from wiki_core.folder_ingestion_v2 import FolderIngestionSelection
from wiki_core.frontmatter import parse_frontmatter
from wiki_core.ingest import run


@pytest.mark.parametrize('selected', ['raw', 'repo'])
def test_requalification_updates_only_selected_projection(selected):
    from tests.test_folder_multi_provenance_v2 import prior_raw
    from wiki_core.folder_source_provenance_v2 import add_projection, requalify_projection, selected_projection
    req = lambda target, revision: {'target':target, 'fields':['*'], 'temporal':'current', 'max_age_days':30,
        'consumed_revision':revision, 'use':'interpretation', 'classification':'source'}
    first = prior_repo()
    metadata_old = {**first, 'information_requirements':[req('a/old-source.md', '0'*40)]}
    raw_auth = prior_raw()['source_authorization'] | {'ref':'a/raw/new.md', 'canonical_ref':'a/new-source.md',
                'canonical_revision':'6'*40}
    combined = {**metadata_old, **add_projection(metadata_old, raw_auth),
                'information_requirements':[*metadata_old['information_requirements'], req('a/new-source.md','6'*40)]}
    if selected == 'raw':
        source, other = 'a/new-source.md', 'a/old-source.md'
        auth = {**raw_auth, 'canonical_revision':'7'*40, 'source_sha256':'8'*64}
    else:
        source, other = 'a/old-source.md', 'a/new-source.md'
        auth = {'source_kind':'git', 'canonical_ref':source, 'canonical_revision':'7'*40,
            'independent_repo_read':{'repository':{'identity':'example.test/group/old'}, 'revision':'8'*40,
                'path':'guide.md', 'blob':'9'*40, 'document_sha256':'a'*64, 'content_sha256':'b'*64,
                'section':None, 'field':None}}
    before_other = selected_projection(combined, other)
    updated = deepcopy({**combined, **requalify_projection(combined, auth)})
    for row in updated['information_requirements']:
        if row['target'] == source: row['consumed_revision'] = '7'*40
    assert selected_projection(updated, other) == before_other
    assert selected_projection(updated, source) != selected_projection(combined, source)


@pytest.mark.parametrize('kind', ['raw', 'repo'])
def test_explicit_requalification_preserves_other_source_and_git_history(project, monkeypatch, tmp_path, capsys, kind):
    binding, first_request, first_results = fixture_inputs(project, monkeypatch, tmp_path, capsys,
        existing=True, raw=kind == 'raw', with_repo=kind == 'repo',
        prior_projection=prior_repo() if kind == 'raw' else prior_raw())
    first = prepare_folder_consolidation(project, binding, first_request, first_results,
        candidates=[], max_age_days=30, page_metadata=metadata())
    path = first_request['block_context_package']['output']
    put(project, path, first['markdown'])
    git(project, 'add', path); git(project, 'commit', '-qm', 'synthetic approved claim')
    git(project, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    base = git(project, 'rev-parse', 'HEAD')
    old_fm, old_body = parse_frontmatter(first['markdown'])
    old_hash = hashlib.sha256(first['markdown'].encode()).hexdigest()
    if kind == 'raw':
        source, source_ref = 'a/raw/source.md', 'a/source-page.md'
        put(project, source, '# Revised synthetic RAW\n\n' + 'New observation.\n' * 80)
        selection = FolderIngestionSelection(binding, 'a', 'a/index.md', path, source_ref, existing_output_sha256=old_hash)
    else:
        source, source_ref = 'a/repo-source.md', None
        clone = project/'a/clone'
        put(clone, 'guide.md', '# Updated synthetic repository\n')
        git(clone, 'add', 'guide.md'); git(clone, 'commit', '-qm', 'new selection')
        repo = (str(clone), 'example.test/group/nested', git(clone, 'rev-parse', 'HEAD'), 'guide.md')
        selection = FolderIngestionSelection(binding, 'a', 'a/index.md', path, independent_repo=repo,
                                              existing_output_sha256=old_hash)
    captured = run(str(project/source), 'system', project, load_config(project),
                   approved_revision=base, folder_selection=selection)
    assert not captured.blocked and captured.written
    request = json.loads((project/captured.request_path).read_text())
    result = _synthetic_result(request)
    cli = _recording_cli(project, base, request, monkeypatch, tmp_path,
                         source=source, source_ref=source_ref)
    argv = list(sys.argv); argv[argv.index('--folder-output') + 1] = path
    argv.extend(['--folder-existing-sha256', old_hash])
    if kind == 'repo':
        argv.extend(['--folder-repo', *repo])
        monkeypatch.setenv('WIKI_FOLDER_INGEST_HOST_REPOSITORIES', json.dumps([['a',repo[0],repo[1],repo[3]]]))
    monkeypatch.setattr(sys, 'argv', argv)
    assert cli.main() == 0
    capsys.readouterr()
    kwargs = dict(candidates=[], max_age_days=30, page_metadata=metadata())
    with pytest.raises(ValueError): prepare_folder_consolidation(project, binding, request, [result], **kwargs)
    preview = prepare_folder_consolidation(project, binding, request, [result], requalify_source=True, **kwargs)
    fm, body = parse_frontmatter(preview['markdown'])
    other_field = 'independent_repo_read' if kind == 'raw' else 'source_authorization'
    assert fm[other_field] == old_fm[other_field]
    assert fm['source_refs'] == old_fm['source_refs'] and old_body.strip() in body
    old_req = old_fm['information_requirements']; new_req = fm['information_requirements']
    assert new_req[0] == old_req[0]
    assert new_req[1] == {**old_req[1], 'consumed_revision':base}
    assert fm['folder_source_provenance']['entries'][0] != old_fm['folder_source_provenance']['entries'][0]
    git(project, 'checkout', '-qb', 'wiki/requalify-source')
    put(project, path, preview['markdown']); git(project, 'add', path); git(project, 'commit', '-qm', 'requalify proposal')
    packet = request['block_context_package']
    result_report = {'schema_version':'wiki.folder-task-result/v2', 'status':'completed', 'task_id':packet['task_id'],
        'context_id':packet['context_id'], 'packet_digest':packet['packet_digest'],
        'observed':[{'path':r['path'], 'kind':r['kind'], 'revision':r['revision'], 'sha256':r['sha256'],
                     'section':r.get('section'), 'field':r.get('field')} for r in packet['inputs']],
        'changes':[{'path':path, 'action':'modified'}]}
    payload = {'folder':'a', 'approved_revision':base, 'base':base, 'head':git(project,'rev-parse','HEAD'),
               'branch':'wiki/requalify-source', 'packet':packet, 'result':result_report, 'source_request':request}
    with pytest.raises(FolderCoordinationError): prepare_folder_preflight(project, binding, payload)
    outcome = prepare_folder_preflight(project, binding, {**payload, 'requalify_source':True})['preflight']
    assert outcome['state'] == 'independent_review_required'
    assert git(project, 'show', f'{base}:{path}') == first['markdown'].strip()
    import yaml
    for mutation in ('projection', 'requirement'):
        changed = deepcopy(fm)
        if mutation == 'requirement': changed['information_requirements'][0]['consumed_revision'] = 'f'*40
        elif kind == 'raw': changed['independent_repo_read']['identity'] = 'example.test/forged'
        else: changed['source_authorization']['source_sha256'] = 'f'*64
        put(project, path, '---\n' + yaml.safe_dump(changed, sort_keys=False) + '---\n' + body)
        git(project, 'add', path); git(project, 'commit', '--amend', '-qm', 'synthetic altered proposal')
        with pytest.raises(FolderCoordinationError):
            prepare_folder_preflight(project, binding, {**payload, 'head':git(project,'rev-parse','HEAD'), 'requalify_source':True})
