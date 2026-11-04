"""Secondary claim provenance is preserved without unselected source reads."""
from copy import deepcopy
import json
import sys
import pytest
import yaml

from tests.test_folder_consolidate_v2 import fixture_inputs, metadata
from tests.test_folder_ingestion_v2 import _recording_cli, _synthetic_result
from tests.test_folder_multi_provenance_v2 import prior_raw, prior_repo
from tests.test_folder_policy_v2 import project, put, git, commit
from wiki_core.config import load_config
from wiki_core.consolidate import prepare_folder_consolidation
from wiki_core.folder_coordination_v2 import prepare_folder_preflight
from wiki_core.folder_ingestion_v2 import FolderIngestionSelection
from wiki_core.folder_packet_v2 import build_folder_packet_v2
from wiki_core.folder_policy_v2 import load_folder_policy_v2
from wiki_core.folder_integration_v2 import preflight_folder_v2
from wiki_core.folder_source_provenance_v2 import add_projection
from wiki_core.ingest import run
from wiki_core.repository_reader import RepositoryReader


def secondary_metadata(kind):
    prior = prior_repo() if kind in ('repository', 'multi') else prior_raw()
    old_req = {'target':'a/old-source.md', 'fields':['*'], 'temporal':'current', 'max_age_days':30,
               'consumed_revision':'0'*40, 'use':'interpretation', 'classification':'source'}
    data = {'page_id':'claim-secondary', 'page_type':'claim', 'source_refs':['source-earlier'],
            'information_requirements':[old_req], **prior}
    if kind == 'multi':
        capture = {'source_kind':'staged_raw', 'ref':'a/raw/second.md', 'source_revision':None,
            'source_sha256':'5'*64, 'source_origin':{'kind':'repository_path'}, 'canonical_ref':'a/second-source.md',
            'canonical_revision':'6'*40, 'canonical_sha256':'7'*64, 'association':'caller_selected_unverified',
            'external_origin_verification':'not_verified', 'external_freshness':'not_verified'}
        data.update(add_projection(data, capture))
        data['information_requirements'].append({**old_req, 'target':'a/second-source.md', 'consumed_revision':'6'*40})
        data['source_refs'].append('source-second')
    return data


@pytest.mark.parametrize('kind', ['raw', 'repository', 'multi'])
@pytest.mark.parametrize('flow', ['generic', 'ingestion'])
def test_secondary_preservation_and_alteration(project, monkeypatch, tmp_path, capsys, kind, flow):
    if flow == 'ingestion':
        binding, _, _ = fixture_inputs(project, monkeypatch, tmp_path, capsys)
    put(project, 'a/old-source.md', 'Old source\n')
    put(project, 'a/second-source.md', 'Second source\n')
    meta = secondary_metadata(kind)
    class NoAliasesDumper(yaml.SafeDumper):
        def ignore_aliases(self, data):
            return True
    def secondary(value, body):
        return '---\n' + yaml.dump(value, Dumper=NoAliasesDumper, sort_keys=False) + '---\n' + body + '\n'
    put(project, 'a/secondary.md', secondary(meta, 'Original secondary'))
    commit(project); base = git(project, 'rev-parse', 'HEAD'); policy = load_folder_policy_v2(project, base)
    if flow == 'ingestion':
        selection = FolderIngestionSelection(binding, 'a', 'a/index.md', 'a/claims/result.md')
        captured = run(str(project / 'a/source.md'), 'system', project, load_config(project),
            approved_revision=base, folder_selection=selection, root_entity_ref='a/secondary.md')
        assert not captured.blocked
        request = json.loads((project / captured.request_path).read_text())
        chunk_result = _synthetic_result(request)
        module = _recording_cli(project, base, request, monkeypatch, tmp_path, source='a/source.md')
        argv = list(sys.argv); argv[argv.index('--folder-output') + 1] = selection.output_path
        argv += ['--root-entity-ref', 'a/secondary.md']; monkeypatch.setattr(sys, 'argv', argv)
        assert module.main() == 0
        capsys.readouterr()
        preview = prepare_folder_consolidation(project, binding, request, [chunk_result],
            candidates=[], max_age_days=30, page_metadata=metadata())
        packet = request['block_context_package']; output = preview['output']; output_text = preview['markdown']
        assert any(row['path'] == 'a/secondary.md' and row['kind'] == 'evidence' for row in packet['inputs'])
    else:
        output = 'a/result.md'; output_text = '---\npage_type: claim\n---\nResult\n'
        packet = build_folder_packet_v2(project, policy, 'a', 100000, content_revision=base,
            index_path='a/index.md', task_id='secondary', goal='review', output=output,
            integrator='independent', evidence=[{'path':'a/secondary.md', 'producer_folder':'a',
                'reason':'prior secondary', 'use':'interpretation', 'classification':'context'}])
    git(project, 'checkout', '-qb', 'wiki/secondary-preserved')
    put(project, output, output_text); put(project, 'a/secondary.md', secondary(meta, 'Revised secondary'))
    git(project, 'add', output, 'a/secondary.md'); git(project, 'commit', '-qm', 'selected changes')
    result = {'schema_version':'wiki.folder-task-result/v2', 'status':'completed',
        'task_id':packet['task_id'], 'context_id':packet['context_id'], 'packet_digest':packet['packet_digest'],
        'observed':[{'path':r['path'], 'kind':r['kind'], 'revision':r['revision'], 'sha256':r['sha256'],
                     'section':r.get('section'), 'field':r.get('field')} for r in packet['inputs']],
        'changes':sorted([{'path':output, 'action':'created'}, {'path':'a/secondary.md', 'action':'modified'}], key=lambda row:row['path'])}
    payload = {'folder':'a', 'approved_revision':base, 'base':base, 'head':git(project, 'rev-parse', 'HEAD'),
               'branch':'wiki/secondary-preserved', 'packet':packet, 'result':result}
    original_read = RepositoryReader.read
    def guarded(reader, path, *args, **kwargs):
        if path in ('a/old-source.md', 'a/second-source.md'):
            pytest.fail('unselected prior source opened')
        return original_read(reader, path, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', guarded)
    if flow == 'ingestion':
        payload['source_request'] = request
        outcome = prepare_folder_preflight(project, binding, payload)['preflight']
    else:
        outcome = preflight_folder_v2(project, policy, base=base, head=payload['head'],
            branch=payload['branch'], packet=packet, result=result)
    assert outcome['prior_requirements_handling'] == 'preserved_not_revalidated'
    assert outcome['prior_ingestion_provenance']['capture' if kind != 'repository' else 'repository'] == 'preserved_not_revalidated'
    if kind == 'multi':
        assert outcome['prior_ingestion_provenance']['repository'] == 'preserved_not_revalidated'
    altered = deepcopy(meta)
    if kind == 'raw': altered['source_authorization']['source_sha256'] = 'f'*64
    elif kind == 'repository': altered['independent_repo_read']['content_sha256'] = 'f'*64
    else: altered['folder_source_provenance']['entries'][0]['source_authorization']['source_sha256'] = 'f'*64
    put(project, 'a/secondary.md', secondary(altered, 'Revised secondary'))
    git(project, 'add', 'a/secondary.md'); git(project, 'commit', '--amend', '-qm', 'alter secondary provenance')
    payload['head'] = git(project, 'rev-parse', 'HEAD')
    with pytest.raises(ValueError):
        if flow == 'ingestion': prepare_folder_preflight(project, binding, payload)
        else: preflight_folder_v2(project, policy, base=base, head=payload['head'],
                                   branch=payload['branch'], packet=packet, result=result)
