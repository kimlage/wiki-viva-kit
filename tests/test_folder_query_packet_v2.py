"""Explicit v2 query packet and conservative preflight, synthetic only."""
from copy import deepcopy

import pytest

from tests.test_folder_query_v2 import project, fixture_query, put, commit, git
from wiki_core.folder_query_packet_v2 import (FolderQueryPacketError, build_folder_query_packet_v2,
                                               preflight_folder_query_v2)
from wiki_core.repository_reader import RepositoryReader


def setup_query(project):
    policy,base,entry=fixture_query(project)
    packet=build_folder_query_packet_v2(project,policy,base_packet=base,queries=[entry])
    return policy,base,entry,packet


def result_for(packet,changes):
    base=packet['base_packet']
    observed=[{'path':r['path'],'kind':r['kind'],'revision':r['revision'],'sha256':r['sha256'],
               'section':r.get('section'),'field':r.get('field')} for r in base['inputs']]
    for item in packet['queries']:
        for row in item['selected']:
            observed.append({'kind':'query_evidence','path':row['path'],'revision':row['revision'],
                             'sha256':row['sha256'],'section':row['section'],'field':row['field'],
                             'query_id':item['receipt']['query_id']})
    return {'schema_version':'wiki.folder-query-task-result/v2','status':'completed',
            'task_id':base['task_id'],'context_id':base['context_id'],'packet_digest':packet['packet_digest'],
            'observed':observed,'observed_queries':[item['receipt']['query_id'] for item in packet['queries']],
            'changes':changes}


def test_query_packet_and_preflight_exact_readset(project):
    import json
    from pathlib import Path
    from jsonschema import validate
    p,base,entry,packet=setup_query(project)
    assert packet['schema_version']=='wiki.folder-query-task-context/v2'
    assert packet['queries'][0]['receipt']['packet_digest']==base['packet_digest']
    assert packet['queries'][0]['selected'][0]['text']=='11'
    before=git(project,'rev-parse','HEAD'); git(project,'checkout','-qb','wiki/query-v2')
    put(project,'a/result.md','---\npage_type: claim\n---\nInterpretation\n')
    git(project,'add','-A'); git(project,'commit','-qm','interpretation'); head=git(project,'rev-parse','HEAD')
    result=result_for(packet,[{'path':'a/result.md','action':'created'}])
    out=preflight_folder_query_v2(project,p,base=before,head=head,branch='wiki/query-v2',packet=packet,result=result)
    assert out['state']=='independent_review_required' and out['merge']=='not_performed'
    schemas=Path(__file__).resolve().parents[1]/'docs/references/schemas'
    for name,value in [('wiki-folder-query-receipt-v2.schema.json',packet['queries'][0]['receipt']),
                       ('wiki-folder-query-task-context-v2.schema.json',packet),
                       ('wiki-folder-query-task-result-v2.schema.json',result),
                       ('wiki-folder-query-preflight-v2.schema.json',out)]:
        validate(value,json.loads((schemas/name).read_text()))
    missing=deepcopy(result); missing['observed_queries']=[]
    with pytest.raises(FolderQueryPacketError,match='exact reported coverage'):
        preflight_folder_query_v2(project,p,base=before,head=head,branch='wiki/query-v2',packet=packet,result=missing)
    forged=deepcopy(packet); forged['queries'][0]['receipt']['selected_digest']='0'*64
    with pytest.raises(FolderQueryPacketError,match='cannot be reproduced'):
        preflight_folder_query_v2(project,p,base=before,head=head,branch='wiki/query-v2',packet=forged,result=result)


def test_preflight_rejects_scope_change_before_reading_proposed_member(project,monkeypatch):
    p,_,_,packet=setup_query(project); before=git(project,'rev-parse','HEAD')
    git(project,'checkout','-qb','wiki/query-scope-change')
    put(project,'a/items/new.md','---\npage_type: claim\npage_id: new\nstatus: active\namount: 13\n---\nNew\n')
    git(project,'add','-A'); git(project,'commit','-qm','change collection'); head=git(project,'rev-parse','HEAD')
    result=result_for(packet,[{'path':'a/items/new.md','action':'created'}])
    original=RepositoryReader.read
    def spy(self,ref,*args,**kwargs):
        if self.revision==head and ref.startswith('a/items/'):
            raise AssertionError('proposed query member opened before scope invalidation')
        return original(self,ref,*args,**kwargs)
    monkeypatch.setattr(RepositoryReader,'read',spy)
    with pytest.raises(FolderQueryPacketError,match='proposal changes query scope'):
        preflight_folder_query_v2(project,p,base=before,head=head,branch='wiki/query-scope-change',packet=packet,result=result)


def test_query_packet_refuses_v1_base_and_excess_combined_scan(project,monkeypatch):
    p,base,entry=fixture_query(project)
    with pytest.raises(FolderQueryPacketError,match='v2 base packet required'):
        build_folder_query_packet_v2(project,p,base_packet={'schema_version':'wiki.task-context/v1'},queries=[entry])
    large={**entry,'query':{**entry['query'],'max_scan_bytes':2_000_000}}
    original=RepositoryReader.read
    def spy(self,ref,*args,**kwargs):
        if ref.startswith('a/items/'): raise AssertionError('members read before combined budget check')
        return original(self,ref,*args,**kwargs)
    monkeypatch.setattr(RepositoryReader,'read',spy)
    with pytest.raises(FolderQueryPacketError,match='combined query scan limit exceeded'):
        build_folder_query_packet_v2(project,p,base_packet=base,queries=[large,entry])


def test_shared_noncyclic_query_objects_do_not_bypass_secret_scan():
    from wiki_core.repo_read import contains_access_secrets
    shared={'link':'https://example.invalid/path?X-Goog-Signature=synthetic'}
    assert contains_access_secrets([shared,shared])
    clean={'status':'active'}
    assert not contains_access_secrets([clean,clean])
    cycle=[]; cycle.append(cycle)
    with pytest.raises(ValueError):
        contains_access_secrets(cycle)


def test_query_packet_and_preflight_clis_use_versioned_contract(project,tmp_path):
    import json
    import subprocess
    import sys
    from pathlib import Path
    _,_,entry=fixture_query(project); before=git(project,'rev-parse','HEAD')
    request=tmp_path.parent/(tmp_path.name+'-queries.json'); request.write_text(json.dumps([entry]))
    scripts=Path(__file__).resolve().parents[1]/'scripts'
    built=subprocess.run([sys.executable,str(scripts/'wiki_folder_packet_v2.py'),'--repo',str(project),
        '--approved-revision','HEAD','--content-revision','HEAD','--index','a/index.md','--max-bytes','50000',
        '--task-id','x','--goal','x','--output','a/result.md','--integrator','x','--queries',str(request),'a'],
        text=True,capture_output=True,check=True)
    packet=json.loads(built.stdout)
    assert packet['schema_version']=='wiki.folder-query-task-context/v2'
    git(project,'checkout','-qb','wiki/query-cli')
    put(project,'a/result.md','---\npage_type: claim\n---\nInterpretation\n')
    git(project,'add','-A'); git(project,'commit','-qm','result'); head=git(project,'rev-parse','HEAD')
    result=result_for(packet,[{'path':'a/result.md','action':'created'}])
    pp=tmp_path.parent/(tmp_path.name+'-packet.json'); rp=tmp_path.parent/(tmp_path.name+'-result.json')
    pp.write_text(json.dumps(packet)); rp.write_text(json.dumps(result))
    checked=subprocess.run([sys.executable,str(scripts/'wiki_folder_preflight_v2.py'),'--repo',str(project),
        '--approved-revision',before,'--base',before,'--head',head,'--branch','wiki/query-cli',
        '--packet',str(pp),'--result',str(rp)],text=True,capture_output=True,check=True)
    out=json.loads(checked.stdout)
    assert out['schema_version']=='wiki.folder-query-preflight/v2'
    assert out['state']=='independent_review_required' and out['merge']=='not_performed'


@pytest.mark.parametrize('operation',['modified','deleted'])
def test_query_preflight_accepts_existing_output_only_with_whole_prior_read(project,operation):
    import json
    from pathlib import Path
    from jsonschema import validate
    from wiki_core.folder_packet_v2 import build_folder_packet_v2
    from wiki_core.folder_policy_v2 import load_folder_policy_v2
    _,_,entry=fixture_query(project)
    put(project,'a/result.md','---\npage_type: claim\n---\nEarlier interpretation\n'); commit(project)
    before=git(project,'rev-parse','HEAD'); p=load_folder_policy_v2(project,'HEAD')
    evidence=[{'path':'a/result.md','producer_folder':'a','reason':'prior output','use':'interpret','classification':'synthetic'}]
    base=build_folder_packet_v2(project,p,'a',50000,index_path='a/index.md',content_revision=before,
                                task_id='x',goal='x',output='a/result.md',integrator='x',evidence=evidence)
    packet=build_folder_query_packet_v2(project,p,base_packet=base,queries=[entry])
    git(project,'checkout','-qb','wiki/query-existing')
    if operation=='deleted': (project/'a/result.md').unlink()
    else: put(project,'a/result.md','---\npage_type: claim\n---\nRevised interpretation\n')
    git(project,'add','-A'); git(project,'commit','-qm','output'); head=git(project,'rev-parse','HEAD')
    result=result_for(packet,[{'path':'a/result.md','action':operation}])
    schema=Path(__file__).resolve().parents[1]/'docs/references/schemas/wiki-folder-query-task-result-v2.schema.json'
    validate(result,json.loads(schema.read_text()))
    out=preflight_folder_query_v2(project,p,base=before,head=head,branch='wiki/query-existing',packet=packet,result=result)
    assert out['state']=='independent_review_required' and out['merge']=='not_performed'


def test_query_preflight_still_rejects_existing_output_without_whole_prior_read(project):
    p,_,entry=fixture_query(project)
    put(project,'a/result.md','---\npage_type: claim\n---\nEarlier\n'); commit(project)
    from wiki_core.folder_packet_v2 import build_folder_packet_v2
    from wiki_core.folder_policy_v2 import load_folder_policy_v2
    p=load_folder_policy_v2(project,'HEAD'); before=git(project,'rev-parse','HEAD')
    base=build_folder_packet_v2(project,p,'a',50000,index_path='a/index.md',content_revision=before,
                                task_id='x',goal='x',output='a/result.md',integrator='x')
    packet=build_folder_query_packet_v2(project,p,base_packet=base,queries=[entry])
    git(project,'checkout','-qb','wiki/query-no-prior')
    put(project,'a/result.md','---\npage_type: claim\n---\nChanged\n')
    git(project,'add','-A'); git(project,'commit','-qm','output'); head=git(project,'rev-parse','HEAD')
    result=result_for(packet,[{'path':'a/result.md','action':'modified'}])
    with pytest.raises(FolderQueryPacketError,match='preflight unavailable'):
        preflight_folder_query_v2(project,p,base=before,head=head,branch='wiki/query-no-prior',packet=packet,result=result)


def test_query_checks_all_evidence_authority_before_replaying_any_body(project,monkeypatch):
    import yaml
    from wiki_core.folder_packet_v2 import build_folder_packet_v2
    from wiki_core.folder_policy_v2 import load_folder_policy_v2
    from wiki_core.folder_query_v2 import select_folder_query_v2, FolderQueryError
    _,_,entry=fixture_query(project)
    put(project,'a/first.md','First authorized source\n'); put(project,'a/second.md','Later revoked source\n'); commit(project)
    p=load_folder_policy_v2(project,'HEAD')
    evidence=[{'path':f'a/{name}.md','producer_folder':'a','reason':'synthetic','use':'interpret','classification':'synthetic'}
              for name in ('first','second')]
    packet=build_folder_packet_v2(project,p,'a',50000,index_path='a/index.md',content_revision='HEAD',
                                  task_id='x',goal='x',output='a/result.md',integrator='x',evidence=evidence)
    config=project/'wiki-context-controls.yaml'; data=yaml.safe_load(config.read_text())
    data['controls']['a']['policy']['deny']={'read':['a/second.md']}
    config.write_text(yaml.safe_dump(data)); commit(project)
    current=load_folder_policy_v2(project,'HEAD')
    forged={**packet,'policy_revision':current.policy_revision,'content_revision':current.policy_revision}
    original=RepositoryReader.read
    def spy(self,ref,*args,**kwargs):
        if ref in ('a/first.md','a/second.md'):
            raise AssertionError('evidence body read before all current permissions')
        return original(self,ref,*args,**kwargs)
    monkeypatch.setattr(RepositoryReader,'read',spy)
    with pytest.raises(FolderQueryError,match='input authority unavailable'):
        select_folder_query_v2(project,current,packet=forged,content_revision='HEAD',request=entry)
