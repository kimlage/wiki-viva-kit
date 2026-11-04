"""Folder consolidation preview: explicit recorded synthetic results, no writes."""
import json
from pathlib import Path

import pytest
import yaml

from tests.test_folder_policy_v2 import project, put, git, commit
from tests.test_folder_ingestion_v2 import setup, _synthetic_result, _recording_cli
from wiki_core.config import load_config
from wiki_core.consolidate import prepare_folder_consolidation
from wiki_core.folder_ingestion_v2 import FolderIngestionSelection
from wiki_core.frontmatter import parse_frontmatter
from wiki_core.ingest import run


def fixture_inputs(project, monkeypatch, tmp_path, capsys, *, raw=False, with_repo=False, with_query=False):
    registry = yaml.safe_load((Path(__file__).resolve().parents[1] / 'wiki.page-types.yaml').read_text())
    registry['page_types']['claim']['allowed_dirs'] = ['a/claims']
    registry['page_types'] = {'claim':registry['page_types']['claim']}
    put(project, 'wiki.page-types.yaml', yaml.safe_dump(registry, sort_keys=False))
    template_ref = registry['page_types']['claim']['template']
    put(project, template_ref, (Path(__file__).resolve().parents[1] / template_ref).read_text())
    put(project, 'AGENTS.md', 'Project instructions\n\n## Wiki v2: mandatory references\n\n'
        '- [Registry](wiki.page-types.yaml)\n- [Claim template](' + template_ref + ')\n')
    put(project, 'a/candidate.md', 'An explicitly selected context page\n')
    put(project, 'a/owner.md', '---\npage_id: person-synthetic\npage_type: person\n---\nSynthetic owner\n')
    put(project, 'a/aux/b/other.md', 'Synthetic other owner\n')
    if with_query:
        put(project, 'a/index.md', '---\npage_id: synthetic-catalog\npage_type: source_catalog\n---\nCollection contract\n')
        put(project, 'a/items/one.md', '---\npage_id: one\nstatus: active\namount: 11\n---\nSynthetic source\n')
    sha, selection = setup(project)
    selection = FolderIngestionSelection(selection.host, 'a', 'a/index.md', 'a/claims/result.md')
    put(project, 'a/source.md', '---\npage_id: source-synthetic\npage_type: source\n---\n'
        '# Synthetic source\n\n' + ('An authorized synthetic observation.\n' * 90))
    commit(project); sha = git(project, 'rev-parse', 'HEAD')
    source = 'a/source.md'
    source_ref = None
    if with_repo:
        put(project, '.gitignore', 'data/derived/\na/clone/\n')
        put(project, 'a/repo-source.md', '---\npage_id: source-repository\npage_type: source\n'
            'platform: repo\nsource_locator: example.test/group/nested\n---\n'
            + ('Synthetic repository node observation.\n' * 90))
        commit(project); sha = git(project, 'rev-parse', 'HEAD')
        clone = project / 'a/clone'; clone.mkdir()
        git(clone, 'init', '-q'); git(clone, 'config', 'user.name', 'Synthetic')
        git(clone, 'config', 'user.email', 'synthetic@example.invalid')
        git(clone, 'remote', 'add', 'origin', 'https://example.test/group/nested.git')
        put(clone, 'AGENTS.md', 'Independent repository instructions\n')
        put(clone, 'guide.md', '---\nalpha: 1\n---\nIndependent synthetic repository\n')
        git(clone, 'add', '-A'); git(clone, 'commit', '-qm', 'synthetic repository source')
    if raw:
        put(project, '.gitignore', 'data/derived/\na/raw/\n')
        put(project, 'a/source-page.md', '---\npage_id: source-synthetic-raw\npage_type: source\n'
            'platform: drive\nsource_locator: synthetic-item\n---\nSynthetic source page\n')
        commit(project); sha = git(project, 'rev-parse', 'HEAD')
        source = 'a/raw/source.md'; source_ref = 'a/source-page.md'
        put(project, source, '# Synthetic RAW\n\n' + ('Unverified local observation.\n' * 80))
        selection = FolderIngestionSelection(selection.host, 'a', 'a/index.md', 'a/claims/result.md', source_ref)
    initial = run(str(project / source), 'system', project, load_config(project),
                  approved_revision=sha, folder_selection=selection)
    assert not initial.blocked and initial.written
    request = json.loads((project / initial.request_path).read_text())
    assert len(request['chunks']) == 1
    result = _synthetic_result(request)
    module = _recording_cli(project, sha, request, monkeypatch, tmp_path,
                            source=source, source_ref=source_ref)
    import sys
    argv = list(sys.argv); argv[argv.index('--folder-output') + 1] = 'a/claims/result.md'
    monkeypatch.setattr(sys, 'argv', argv)
    assert module.main() == 0
    assert json.loads(capsys.readouterr().out)['count'] == 1
    return selection.host, request, [result]


def metadata(page_id='claim-synthetic'):
    return {'page_id':page_id, 'context':'system', 'visibility':'private_self',
            'updated_at':'2026-01-02', 'stale_after_days':'30', 'sources_policy':'synthetic',
            'gate':'github_pr', 'sensitive_data_policy':'private_sensitive_allowed', 'moc_parent':'a/index.md',
            'owner':'person-synthetic'}


@pytest.mark.parametrize('field,path', [
    ('ref', 'a/credentials/example.txt'),
    ('ref', 'a/local/example.pem'),
    ('canonical_ref', 'a/.env.example'),
    ('canonical_ref', 'a/secrets/example.md'),
])
def test_raw_capture_rejects_reserved_paths_before_policy_or_reads(tmp_path, monkeypatch, field, path):
    from wiki_core import folder_capture_v2 as capture_module
    capture = {'source_kind':'staged_raw', 'ref':'a/raw/example.md', 'source_revision':None,
        'source_sha256':'0' * 64, 'source_origin':'a/raw/example.md', 'canonical_ref':'a/source.md',
        'canonical_revision':'1' * 40, 'canonical_sha256':'2' * 64,
        'association':'caller_selected_unverified', 'external_origin_verification':'not_verified',
        'external_freshness':'not_verified'}
    capture[field] = path
    monkeypatch.setattr(capture_module, '_bound_policy',
                        lambda *_args, **_kwargs: pytest.fail('policy or source accessed before path validation'))
    with pytest.raises(ValueError, match='capture unavailable or unauthorized'):
        capture_module.inspect_raw_capture(tmp_path, None, 'a', '1' * 40, capture)


def amend_without_fields(project, preview, fields):
    fm, body = parse_frontmatter(preview['markdown'])
    for field in fields:
        fm.pop(field, None)
    put(project, preview['output'], '---\n' + yaml.safe_dump(fm, sort_keys=False) + '---\n' + body)
    git(project, 'add', preview['output']); git(project, 'commit', '--amend', '-qm', 'synthetic changed proposal')
    return git(project, 'rev-parse', 'HEAD')


def restore_proposal(project, preview):
    put(project, preview['output'], preview['markdown'])
    git(project, 'add', preview['output']); git(project, 'commit', '--amend', '-qm', 'synthetic proposal restored')
    return git(project, 'rev-parse', 'HEAD')


def test_preview_only_uses_selected_pages_and_returns_reviewable_markdown(project, monkeypatch, tmp_path, capsys):
    import wiki_core.consolidate as module
    binding, request, results = fixture_inputs(project, monkeypatch, tmp_path, capsys)
    monkeypatch.setattr(module, '_page_catalog', lambda *_: pytest.fail('global catalog used'))
    monkeypatch.setattr(module, 'search', lambda *_args, **_kwargs: pytest.fail('global FTS used'))
    before = git(project, 'status', '--porcelain')
    out = prepare_folder_consolidation(project, binding, request, results, candidates=['a/candidate.md'], max_age_days=30, page_metadata=metadata())
    assert out['state'] == 'independent_review_required'
    assert out['write'] == out['merge'] == out['preflight'] == 'not_performed'
    assert out['reads'] == 'reported_not_independently_verified'
    assert [row['path'] for row in out['selected_pages']] == ['a/candidate.md']
    fm, body = parse_frontmatter(out['markdown'])
    assert fm['page_type'] == 'claim'
    assert fm['information_requirements'][0]['target'] == 'a/source.md'
    assert fm['information_requirements'][0]['consumed_revision'] == request['block_context_package']['policy_revision']
    assert results[0]['claims'][0] in body
    assert not (project / 'a/claims/result.md').exists()
    assert git(project, 'status', '--porcelain') == before


def test_wrong_owner_and_existing_output_are_rejected(project, monkeypatch, tmp_path, capsys):
    binding, request, results = fixture_inputs(project, monkeypatch, tmp_path, capsys)
    with pytest.raises(ValueError, match='unavailable or unauthorized'):
        prepare_folder_consolidation(project, binding, request, results, candidates=['a/aux/b/other.md'], max_age_days=30, page_metadata=metadata())
    put(project, 'a/claims/result.md', 'Existing work to preserve\n')
    with pytest.raises(ValueError, match='unavailable or unauthorized'):
        prepare_folder_consolidation(project, binding, request, results, candidates=[], max_age_days=30, page_metadata=metadata())
    assert (project / 'a/claims/result.md').read_text() == 'Existing work to preserve\n'


def test_unmatched_result_and_changed_source_are_rejected(project, monkeypatch, tmp_path, capsys):
    binding, request, results = fixture_inputs(project, monkeypatch, tmp_path, capsys)
    with pytest.raises(ValueError):
        prepare_folder_consolidation(project, binding, request, [], candidates=[], max_age_days=30, page_metadata=metadata())
    put(project, 'a/source.md', 'Changed after recording\n')
    with pytest.raises(ValueError):
        prepare_folder_consolidation(project, binding, request, results, candidates=[], max_age_days=30, page_metadata=metadata())


def test_raw_preview_preserves_unverified_association_and_rechecks_bytes(project, monkeypatch, tmp_path, capsys):
    binding, request, results = fixture_inputs(project, monkeypatch, tmp_path, capsys, raw=True)
    out = prepare_folder_consolidation(project, binding, request, results, candidates=[], max_age_days=30, page_metadata=metadata())
    fm, body = parse_frontmatter(out['markdown'])
    assert fm['information_requirements'][0]['target'] == 'a/source-page.md'
    assert 'caller_selected_unverified' in body and 'not_verified' in body
    assert request['source_authorization']['source_revision'] is None
    put(project, 'a/raw/source.md', 'Changed after recording\n')
    with pytest.raises(ValueError):
        prepare_folder_consolidation(project, binding, request, results, candidates=[], max_age_days=30, page_metadata=metadata())


def test_raw_capture_is_revalidated_at_preflight_and_after_local_change(project, monkeypatch, tmp_path, capsys):
    from copy import deepcopy
    import os
    import subprocess
    import sys
    from wiki_core.folder_coordination_v2 import FolderCoordinationError, prepare_folder_preflight
    from wiki_core.folder_integration_v2 import FolderIntegrationError, preflight_folder_v2
    from wiki_core.folder_policy_v2 import load_folder_policy_v2
    from wiki_core.folder_reassessment_host_v2 import prepare_folder_reassessment
    binding, request, results = fixture_inputs(project, monkeypatch, tmp_path, capsys, raw=True)
    preview = prepare_folder_consolidation(project, binding, request, results, candidates=[], max_age_days=30, page_metadata=metadata())
    packet = request['block_context_package']; base = packet['policy_revision']
    raw_original = (project / 'a/raw/source.md').read_text()
    original_branch = git(project, 'branch', '--show-current')
    git(project, 'checkout', '-qb', 'wiki/synthetic-raw')
    put(project, preview['output'], preview['markdown'])
    git(project, 'add', preview['output']); git(project, 'commit', '-qm', 'synthetic raw proposal')
    head = git(project, 'rev-parse', 'HEAD')
    result = {'schema_version':'wiki.folder-task-result/v2', 'status':'completed',
              'task_id':packet['task_id'], 'context_id':packet['context_id'], 'packet_digest':packet['packet_digest'],
              'observed':[{'path':row['path'], 'kind':row['kind'], 'revision':row['revision'],
                           'sha256':row['sha256'], 'section':row.get('section'), 'field':row.get('field')}
                          for row in packet['inputs']], 'changes':[{'path':preview['output'], 'action':'created'}]}
    with pytest.raises(FolderIntegrationError, match='host-bound request'):
        preflight_folder_v2(project, load_folder_policy_v2(project, base), base=base, head=head,
                            branch='wiki/synthetic-raw', packet=packet, result=result)
    payload = {'folder':'a', 'approved_revision':base, 'base':base, 'head':head,
               'branch':'wiki/synthetic-raw', 'packet':packet, 'result':result, 'source_request':request}
    assert packet['ingestion_binding']['source_kind'] == 'staged_raw'
    payload['head'] = amend_without_fields(project, preview, ['source_authorization'])
    with pytest.raises(FolderCoordinationError):
        prepare_folder_preflight(project, binding, payload)
    with pytest.raises(FolderCoordinationError):
        prepare_folder_preflight(project, binding, {key:value for key,value in payload.items() if key != 'source_request'})
    head = payload['head'] = restore_proposal(project, preview)
    downgraded = deepcopy(packet); downgraded.pop('ingestion_binding')
    # Even a rebuilt generic packet cannot use the original task result.
    from wiki_core.folder_packet_v2 import build_folder_packet_v2
    from wiki_core.folder_integration_v2 import _rebuild
    policy = load_folder_policy_v2(project, base)
    by_id = {value:key for key,value in policy.folder_ids.items()}
    evidence = []
    for row in packet['inputs']:
        if row['kind'] == 'evidence':
            item = {key:row[key] for key in ('path', 'reason', 'use', 'classification')}
            item['producer_folder'] = by_id[row['producer_context']]
            for key in ('section', 'field'):
                if row.get(key) is not None: item[key] = row[key]
            evidence.append(item)
    downgraded = build_folder_packet_v2(project, policy, packet['context_folder'], packet['max_bytes'],
        content_revision=packet['content_revision'], index_path=packet['index_path'],
        index_section=packet['index_section'], task_id=packet['task_id'], goal=packet['goal'],
        output=packet['output'], integrator=packet['integrator'], evidence=evidence)
    assert _rebuild(project, policy, downgraded) == downgraded
    with pytest.raises(FolderIntegrationError, match='result does not match'):
        preflight_folder_v2(project, policy, base=base, head=head, branch='wiki/synthetic-raw',
                            packet=downgraded, result=result)
    with pytest.raises(FolderCoordinationError):
        prepare_folder_preflight(project, binding, {key:value for key,value in payload.items() if key != 'source_request'})
    divergent = deepcopy(payload)
    divergent['source_request']['source_authorization']['source_sha256'] = '0' * 64
    with pytest.raises(FolderCoordinationError):
        prepare_folder_preflight(project, binding, divergent)
    put(project, 'a/raw/source.md', 'Changed before preflight\n')
    with pytest.raises(FolderCoordinationError):
        prepare_folder_preflight(project, binding, payload)
    put(project, 'a/raw/source.md', raw_original)
    out = prepare_folder_preflight(project, binding, payload)['preflight']
    assert out['state'] == 'independent_review_required'
    assert out['capture_handling'] == {'local_bytes':'matched', 'external_origin':'not_verified',
                                       'external_freshness':'not_verified', 'execution':'not_proven'}
    packet_file = tmp_path / 'raw-packet.json'; packet_file.write_text(json.dumps(packet))
    result_file = tmp_path / 'raw-task-result.json'; result_file.write_text(json.dumps(result))
    request_file = tmp_path / 'raw-request.json'; request_file.write_text(json.dumps(request))
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_context_flow.py'
    args = [sys.executable, str(script), '--repo', str(project), '--approved-revision', base, 'preflight',
            '--folder', 'a', '--index', 'a/index.md', '--base', base, '--head', head,
            '--branch', 'wiki/synthetic-raw', '--packet', str(packet_file), '--result', str(result_file)]
    env = dict(os.environ, WIKI_FOLDER_INGEST_HOST_ROOT=str(project), WIKI_FOLDER_INGEST_HOST_FOLDERS='a')
    refused = subprocess.run(args, env=env, text=True, capture_output=True)
    assert refused.returncode != 0
    cli = subprocess.run([*args, '--source-request', str(request_file)], env=env, text=True, capture_output=True)
    assert cli.returncode == 0, cli.stderr
    assert json.loads(cli.stdout)['capture_handling']['local_bytes'] == 'matched'
    # The fixture's Git merge is simulated; it does not establish real review.
    git(project, 'checkout', '-q', original_branch); git(project, 'merge', '--ff-only', 'wiki/synthetic-raw')
    git(project, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    assert (project / preview['output']).read_text() == preview['markdown']
    put(project, 'a/raw/source.md', 'Changed local RAW after simulated merge\n')
    reassessment = {'folder':'a',
        'approved_revision':git(project, 'rev-parse', 'HEAD'), 'source':'a/source-page.md',
        'candidates':[preview['output']], 'reports':[{'target':preview['output'], 'section':None,
        'field':None, 'packet':packet, 'result':result}], 'source_request':request}
    with pytest.raises(FolderCoordinationError):
        prepare_folder_reassessment(project, binding, {key:value for key,value in reassessment.items() if key != 'source_request'})
    outcome = prepare_folder_reassessment(project, binding, reassessment)['reassessment']
    row = outcome['consumers'][0]
    assert row['state'] == 'review_pending'
    assert row['raw_capture_impact']['local_state'] == 'changed'
    assert row['raw_capture_impact']['association'] == 'caller_selected_unverified'
    assert row['raw_capture_impact']['external_freshness'] == 'not_verified'
    assert (project / preview['output']).read_text() == preview['markdown']


def test_folder_preview_cli_reads_only_supplied_json_and_does_not_write(project, monkeypatch, tmp_path, capsys):
    import importlib.util
    import io
    import sys
    from pathlib import Path
    _binding, request, results = fixture_inputs(project, monkeypatch, tmp_path, capsys)
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_consolidate.py'
    spec = importlib.util.spec_from_file_location('synthetic_folder_consolidate_cli', script)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'ROOT', project)
    monkeypatch.setattr(sys, 'argv', ['wiki_consolidate.py',
                                     '--folder-candidate', 'a/candidate.md', '--max-age-days', '30'])
    class Input:
        buffer = io.BytesIO(json.dumps({'request':request, 'results':results, 'page_metadata':metadata()}).encode())
    monkeypatch.setattr(sys, 'stdin', Input())
    assert module.main() == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview['state'] == 'independent_review_required'
    assert preview['output'] == 'a/claims/result.md' and preview['write'] == 'not_performed'
    assert not (project / 'a/claims/result.md').exists()


def test_synthetic_ingestion_to_proposal_and_reassessment(project, monkeypatch, tmp_path, capsys):
    """Synthetic Git merge models a gate; it is not a real independent review."""
    import os
    import subprocess
    import sys
    from copy import deepcopy
    from wiki_core.folder_coordination_v2 import FolderHostBinding, prepare_folder_preflight
    from wiki_core.folder_reassessment_host_v2 import prepare_folder_reassessment
    from wiki_core.repo_read import read_independent_repo
    binding, request, results = fixture_inputs(project, monkeypatch, tmp_path, capsys, with_repo=True)
    clone = project / 'a/clone'
    identity = 'example.test/group/nested'
    repo_before = git(clone, 'rev-parse', 'HEAD')
    repo_read = read_independent_repo(clone, identity, repo_before, 'guide.md')
    assert repo_read['repository']['identity_evidence'] == 'configured_origin_not_remote_authentication'
    assert git(project, 'check-ignore', 'a/clone/guide.md') == 'a/clone/guide.md'
    binding = FolderHostBinding(project, ('a',), (('a', clone, identity, 'guide.md'),
                                                  ('a', clone, identity, 'AGENTS.md')))
    packet = request['block_context_package']
    base = packet['policy_revision']
    original_branch = git(project, 'branch', '--show-current')
    preview = prepare_folder_consolidation(project, binding, request, results, candidates=['a/candidate.md'], max_age_days=30, page_metadata=metadata())
    assert preview['write'] == 'not_performed' and not (project / preview['output']).exists()

    git(project, 'checkout', '-qb', 'wiki/synthetic-ingestion')
    put(project, preview['output'], preview['markdown'])
    git(project, 'add', preview['output']); git(project, 'commit', '-qm', 'synthetic proposal')
    head = git(project, 'rev-parse', 'HEAD')
    report = {'schema_version':'wiki.folder-task-result/v2', 'status':'completed',
              'task_id':packet['task_id'], 'context_id':packet['context_id'], 'packet_digest':packet['packet_digest'],
              'observed':[{'path':row['path'], 'kind':row['kind'], 'revision':row['revision'],
                           'sha256':row['sha256'], 'section':row.get('section'), 'field':row.get('field')}
                          for row in packet['inputs']],
              'changes':[{'path':preview['output'], 'action':'created'}]}
    checked = prepare_folder_preflight(project, binding, {'folder':'a', 'approved_revision':base,
                'base':base, 'head':head, 'branch':'wiki/synthetic-ingestion', 'packet':packet, 'result':report,
                'source_request':request})
    assert checked['preflight']['state'] == 'independent_review_required'
    assert checked['preflight']['requirements_handling']['count'] == 1
    assert checked['preflight']['merge'] == 'not_performed'
    # The following synthetic approval and Git merge exercise plumbing only.
    # They are not evidence of a human/agent review or an operational merge.
    assert git(project, 'rev-parse', 'wiki/synthetic-ingestion') == head
    git(project, 'checkout', '-q', original_branch); git(project, 'merge', '--ff-only', 'wiki/synthetic-ingestion')
    git(project, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    assert (project / preview['output']).read_text() == preview['markdown']
    # Run the existing frontmatter and page-type audit checks on the merged
    # synthetic claim. Other project-wide gates remain outside this fixture.
    import scripts.wiki_audit as audit
    audit_config = load_config(project)
    audit_config.paths['memory_root'] = 'a'
    audit_config.audit['core_pages'] = [preview['output']]
    audit_config.audit['page_type_registry_check'] = True
    monkeypatch.setattr(audit, 'ROOT', project)
    monkeypatch.setattr(audit, 'markdown_files', lambda: [preview['output']])
    monkeypatch.setattr(audit, 'context_hub_pages', lambda _config: ([], []))
    audit_errors, audit_warnings = [], []
    audit.audit_frontmatter(audit_errors, audit_warnings, audit_config)
    audit.audit_page_type_registry(audit_errors, audit_config)
    monkeypatch.setattr(audit, 'markdown_files', lambda: [preview['output'], 'a/source.md', 'a/owner.md'])
    audit.audit_relations(audit_errors, audit_config)
    assert audit_errors == []

    # Prepare a second synthetic task for the wiki node that identifies the
    # independent repo. The external Git read remains an explicit report.
    second_base = git(project, 'rev-parse', 'HEAD')
    chosen_repo = (str(clone), identity, repo_before, 'guide.md')
    chosen_agents = (str(clone), identity, repo_before, 'AGENTS.md')
    selection = FolderIngestionSelection(binding, 'a', 'a/index.md', 'a/claims/repo-result.md', None, chosen_repo, (chosen_agents,))
    second_capture = run(str(project / 'a/repo-source.md'), 'system', project, load_config(project),
                         approved_revision=second_base, folder_selection=selection)
    assert not second_capture.blocked and second_capture.written
    second_request = json.loads((project / second_capture.request_path).read_text())
    assert len(second_request['chunks']) == 1
    assert second_request['independent_repo_content'] == repo_read['text']
    assert second_request['source_authorization']['independent_repo_read'] == {key:value for key,value in repo_read.items() if key != 'text'}
    assert second_request['independent_repo_additional_content'] == ['Independent repository instructions\n']
    second_result = _synthetic_result(second_request)
    module = _recording_cli(project, second_base, second_request, monkeypatch, tmp_path, source='a/repo-source.md')
    argv = list(sys.argv); argv[argv.index('--folder-output') + 1] = 'a/claims/repo-result.md'
    argv.extend(['--folder-repo', *chosen_repo, '--folder-repo', *chosen_agents])
    monkeypatch.setenv('WIKI_FOLDER_INGEST_HOST_REPOSITORIES', json.dumps([
        ['a', str(clone), identity, 'guide.md'], ['a', str(clone), identity, 'AGENTS.md']]))
    monkeypatch.setattr(sys, 'argv', argv)
    assert module.main() == 0
    assert json.loads(capsys.readouterr().out)['count'] == 1
    second_packet = second_request['block_context_package']
    second_preview = prepare_folder_consolidation(project, binding, second_request, [second_result], candidates=[], max_age_days=30, page_metadata=metadata('claim-repository'))
    assert repo_read['text'] not in second_preview['markdown']
    assert second_request['independent_repo_additional_content'][0] not in second_preview['markdown']
    git(project, 'checkout', '-qb', 'wiki/synthetic-repository')
    put(project, second_preview['output'], second_preview['markdown'])
    git(project, 'add', second_preview['output']); git(project, 'commit', '-qm', 'synthetic repo proposal')
    second_head = git(project, 'rev-parse', 'HEAD')
    second_report = {'schema_version':'wiki.folder-task-result/v2', 'status':'completed',
        'task_id':second_packet['task_id'], 'context_id':second_packet['context_id'],
        'packet_digest':second_packet['packet_digest'],
        'observed':[{'path':row['path'], 'kind':row['kind'], 'revision':row['revision'],
                     'sha256':row['sha256'], 'section':row.get('section'), 'field':row.get('field')}
                    for row in second_packet['inputs']],
        'changes':[{'path':second_preview['output'], 'action':'created'}]}
    second_payload = {'folder':'a', 'approved_revision':second_base,
        'base':second_base, 'head':second_head, 'branch':'wiki/synthetic-repository',
        'packet':second_packet, 'result':second_report, 'source_request':second_request}
    assert second_packet['ingestion_binding']['source_kind'] == 'git'
    second_payload['head'] = amend_without_fields(project, second_preview, ['independent_repo_additional_reads'])
    with pytest.raises(ValueError):
        prepare_folder_preflight(project, binding, second_payload)
    second_payload['head'] = amend_without_fields(project, second_preview, ['independent_repo_read', 'independent_repo_additional_reads'])
    with pytest.raises(ValueError):
        prepare_folder_preflight(project, binding, second_payload)
    with pytest.raises(ValueError):
        prepare_folder_preflight(project, binding, {key:value for key,value in second_payload.items() if key != 'source_request'})
    second_head = second_payload['head'] = restore_proposal(project, second_preview)
    divergent = deepcopy(second_payload)
    divergent['source_request']['independent_repo_content'] += 'changed'
    with pytest.raises(ValueError):
        prepare_folder_preflight(project, binding, divergent)
    git(clone, 'remote', 'set-url', 'origin', 'https://example.test/group/other.git')
    with pytest.raises(ValueError):
        prepare_folder_preflight(project, binding, second_payload)
    git(clone, 'remote', 'set-url', 'origin', 'https://example.test/group/nested.git')
    second_check = prepare_folder_preflight(project, binding, second_payload)
    assert second_check['preflight']['state'] == 'independent_review_required'
    assert second_check['preflight']['repository_handling']['selection'] == 'matched_request'
    with pytest.raises(ValueError):
        prepare_folder_preflight(project, binding, {'folder':'a', 'approved_revision':second_base,
            'base':second_base, 'head':second_head, 'branch':'wiki/synthetic-repository',
            'packet':second_packet, 'result':second_report})
    packet_file = tmp_path / 'repo-packet.json'; packet_file.write_text(json.dumps(second_packet))
    result_file = tmp_path / 'repo-task-result.json'; result_file.write_text(json.dumps(second_report))
    request_file = tmp_path / 'repo-request.json'; request_file.write_text(json.dumps(second_request))
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_context_flow.py'
    args = [sys.executable, str(script), '--repo', str(project), '--approved-revision', second_base,
            'preflight', '--folder', 'a', '--index', 'a/index.md', '--base', second_base,
            '--head', second_head, '--branch', 'wiki/synthetic-repository',
            '--packet', str(packet_file), '--result', str(result_file)]
    env = dict(os.environ, WIKI_FOLDER_INGEST_HOST_ROOT=str(project), WIKI_FOLDER_INGEST_HOST_FOLDERS='a',
               WIKI_FOLDER_INGEST_HOST_REPOSITORIES=json.dumps([
                   ['a', str(clone), identity, 'guide.md'], ['a', str(clone), identity, 'AGENTS.md']]))
    assert subprocess.run(args, env=env, text=True, capture_output=True).returncode != 0
    cli = subprocess.run([*args, '--source-request', str(request_file)], env=env, text=True, capture_output=True)
    assert cli.returncode == 0, cli.stderr
    assert json.loads(cli.stdout)['repository_handling']['selection'] == 'matched_request'
    assert repo_read['text'] not in cli.stdout
    git(project, 'checkout', '-q', original_branch); git(project, 'merge', '--ff-only', 'wiki/synthetic-repository')
    git(project, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    assert (project / second_preview['output']).read_text() == second_preview['markdown']

    put(project, 'a/source.md', '---\npage_id: source-synthetic\npage_type: source\n---\n'
        '# Synthetic changed source\n\n' + ('A changed observation.\n' * 90))
    git(project, 'add', 'a/source.md'); git(project, 'commit', '-qm', 'synthetic source update')
    git(project, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    outcome = prepare_folder_reassessment(project, binding, {'folder':'a',
        'approved_revision':git(project, 'rev-parse', 'HEAD'), 'source':'a/source.md',
        'candidates':[preview['output']], 'reports':[{'target':preview['output'], 'section':None,
        'field':None, 'packet':packet, 'result':report}], 'source_request':request})['reassessment']
    assert outcome['consumers'][0]['state'] == 'review_pending'
    assert outcome['consumers'][0]['impact']['verification'] == 'reported_not_independently_verified'
    assert (project / preview['output']).read_text() == preview['markdown']
    put(clone, 'guide.md', '---\nalpha: 2\n---\nIndependent synthetic repository changed\n')
    put(clone, 'AGENTS.md', 'Updated independent repository instructions\n')
    git(clone, 'add', 'guide.md', 'AGENTS.md'); git(clone, 'commit', '-qm', 'synthetic repository update')
    selected_revision = git(clone, 'rev-parse', 'HEAD')
    repo_payload = {'folder':'a',
        'approved_revision':git(project, 'rev-parse', 'HEAD'), 'source':'a/repo-source.md',
        'candidates':[second_preview['output']], 'reports':[{'target':second_preview['output'],
        'section':None, 'field':None, 'packet':second_packet, 'result':second_report, 'repo_read':repo_read}],
        'independent_repo':{'root':str(clone), 'identity':identity, 'revision':selected_revision, 'path':'guide.md'},
        'source_request':second_request}
    import wiki_core.folder_reassessment_v2 as reassessment_module
    with monkeypatch.context() as patcher:
        patcher.setattr(reassessment_module, 'read_independent_repo', lambda *_args, **_kwargs: pytest.fail('repo read without contextual request'))
        with pytest.raises(ValueError):
            prepare_folder_reassessment(project, binding, {key:value for key,value in repo_payload.items() if key != 'source_request'})
    repository_outcome = prepare_folder_reassessment(project, binding, repo_payload)['reassessment']
    assert repository_outcome['consumers'][0]['state'] == 'review_pending'
    assert repository_outcome['consumers'][0]['repository_impact']['selected_revision'] == selected_revision
    assert repository_outcome['consumers'][0]['repository_impact']['verification'] == 'caller_reported_not_independently_verified'
    assert repository_outcome['consumers'][0]['additional_repository_impact'][0]['source_state'] == 'changed'
    assert (project / second_preview['output']).read_text() == second_preview['markdown']


def test_legacy_check_requires_explicit_mode_and_remains_effective(project, monkeypatch, capsys):
    import importlib.util
    import sys
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_consolidate.py'
    spec = importlib.util.spec_from_file_location('legacy_folder_consolidate_cli', script)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'ROOT', project)
    monkeypatch.setattr(module, 'pending_consolidations', lambda *_: [{'source_id':'source-legacy', 'state':'missing_event'}])
    monkeypatch.setattr(sys, 'argv', ['wiki_consolidate.py', '--check'])
    with pytest.raises(SystemExit) as rejected:
        module.main()
    assert rejected.value.code == 2
    assert '--mode v1' in capsys.readouterr().err
    monkeypatch.setattr(sys, 'argv', ['wiki_consolidate.py', '--mode', 'v1', '--check'])
    assert module.main() == 1
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result['coverage'] == 'legacy_v1_only'
    assert result['pending'][0]['state'] == 'missing_event'


def test_default_folder_refuses_legacy_flags_and_missing_host(project, monkeypatch, capsys):
    import importlib.util
    import sys
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_consolidate.py'
    spec = importlib.util.spec_from_file_location('default_folder_consolidate_cli', script)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'ROOT', project)
    for args in (['--source', 'source-test', '--packet'], ['--all-pending'], ['--date', '2026-01-01']):
        monkeypatch.setattr(sys, 'argv', ['wiki_consolidate.py', *args])
        with pytest.raises(SystemExit) as rejected:
            module.main()
        assert rejected.value.code == 2
    monkeypatch.delenv('WIKI_FOLDER_INGEST_HOST_ROOT', raising=False)
    monkeypatch.delenv('WIKI_FOLDER_INGEST_HOST_FOLDERS', raising=False)
    monkeypatch.setattr(sys, 'argv', ['wiki_consolidate.py', '--max-age-days', '30'])
    assert module.main() == 1
    assert 'folder_consolidation_unavailable' in capsys.readouterr().err


def test_legacy_mode_does_not_accept_folder_options(project, monkeypatch):
    import importlib.util
    import sys
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_consolidate.py'
    spec = importlib.util.spec_from_file_location('mixed_folder_consolidate_cli', script)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'ROOT', project)
    monkeypatch.setattr(sys, 'argv', ['wiki_consolidate.py', '--mode', 'v1', '--check', '--max-age-days', '30'])
    with pytest.raises(SystemExit) as rejected:
        module.main()
    assert rejected.value.code == 2


def test_legacy_path_does_not_consume_folder_result(project, monkeypatch, tmp_path, capsys):
    import importlib.util
    import sys
    _binding, request, _results = fixture_inputs(project, monkeypatch, tmp_path, capsys)
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_consolidate.py'
    spec = importlib.util.spec_from_file_location('legacy_rejects_folder_consolidation', script)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'ROOT', project)
    monkeypatch.setattr(sys, 'argv', ['wiki_consolidate.py', '--mode', 'v1', '--source', request['source_id'], '--packet'])
    assert module.main() == 1
    assert 'no emitted context request' in capsys.readouterr().err
    assert not (project / 'a/claims/result.md').exists()


def test_legacy_pending_gate_never_consumes_folder_requests(project, monkeypatch):
    import wiki_core.consolidate as module
    seen = []
    monkeypatch.setattr(module, 'load_requests', lambda _: [
        {'source_id':'source-folder', 'context_binding_version':2},
        {'source_id':'source-legacy'},
    ])
    def complete(request, _cache):
        seen.append(request['source_id'])
        return True
    monkeypatch.setattr(module, 'deep_read_complete', complete)
    monkeypatch.setattr(module, 'find_event_for_source', lambda *_: None)
    result = module.pending_consolidations(project, load_config(project))
    assert seen == ['source-legacy']
    assert result == [{'source_id':'source-legacy', 'state':'missing_event'}]
