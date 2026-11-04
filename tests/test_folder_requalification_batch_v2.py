"""Synthetic caller-trust batch, with current authorization before body reads."""
from copy import deepcopy

import pytest
import yaml

from tests.test_folder_mandatory_v2 import equivalent_repo, put, git, commit
from wiki_core.context_packet import build_packet
from wiki_core.context_policy import load_policy
from wiki_core.folder_policy_v2 import load_folder_policy_v2
from wiki_core.folder_requalification_batch_v2 import (FolderBatchRequalificationError,
    requalify_explicit_batch_as_global_coordinator)
from wiki_core.repository_reader import RepositoryReader


def fixture(repo, cross=False):
    put(repo,'b/AGENTS.md','# Context B\n')
    put(repo,'b/index.md','Synthetic B index\n')
    put(repo,'a/source.md','---\nstatus: ready\n---\nSynthetic A\n')
    put(repo,'b/source.md','---\nstatus: ready\n---\nSynthetic B\n')
    child={'schema_version':'wiki.context/v1','id':'other','parent':'root','root':'b','purpose':'synthetic',
           'owner':'fixture','instructions':[],'skills':[],'templates':[],
           'policy':{'read':['self'],'write':['self']},'imports':[],'exports':[]}
    config=repo/'wiki-context-controls.yaml'; data=yaml.safe_load(config.read_text())
    data['controls']['b']={'policy':{'read':['self'],'write':['self']},'imports':[],'exports':[]}
    if cross:
        old_grant={'from_context':'other','to_context':'area','selector':'b/source.md','field':'status',
                   'use':'interpret','classification':'synthetic','expires':'2099-01-01'}
        a=repo/'a/context.yaml'; old_a=yaml.safe_load(a.read_text())
        old_a['policy']['read']=['self','b/source.md'];old_a['imports']=[old_grant]
        a.write_text(yaml.safe_dump(old_a));child['exports']=[old_grant]
        grant={**old_grant,'from_context':'b','to_context':'a'}
        data['controls']['a']['policy']['read']=['self','b/source.md']
        data['controls']['a']['imports']=[grant];data['controls']['b']['exports']=[grant]
    put(repo,'b/context.yaml',yaml.safe_dump(child))
    config.write_text(yaml.safe_dump(data));commit(repo);old=git(repo,'rev-parse','HEAD')
    p=load_policy(repo,'HEAD');packets=[]
    for folder,old_id in [('a','area'),('b','other')]:
        source='b' if cross and folder=='a' else folder
        producer='other' if cross and folder=='a' else old_id
        evidence=[{'ref':source+'/source.md','producer':producer,'reason':'synthetic',
                   'use':'interpret','classification':'synthetic','field':'status'}]
        packets.append(build_packet(repo,p,old_id,old,evidence,50000,task_id=folder,goal='review',
                                    output=folder+'/result.md',integrator='independent'))
    git(repo,'checkout','-qb','wiki/batch-fixture')
    for folder in ('a','b'):
        source='b' if cross and folder=='a' else folder
        requirement={'target':source+'/source.md','fields':['field:status'],'temporal':'current','max_age_days':30,
                     'consumed_revision':old,'use':'interpret','classification':'synthetic'}
        put(repo,folder+'/result.md','---\n'+yaml.safe_dump({'page_id':folder+'-result','page_type':'claim',
             'information_requirements':[requirement]})+'---\nInterpretation\n')
    git(repo,'add','-A');git(repo,'commit','-qm','synthetic outputs');proposal=git(repo,'rev-parse','HEAD')
    git(repo,'checkout','-q','-');git(repo,'merge','--ff-only','wiki/batch-fixture')
    git(repo,'update-ref','refs/remotes/origin/main','HEAD')
    selections=[]
    for folder,packet in zip(('a','b'),packets):
        result={'schema_version':'wiki.task-result/v1','status':'completed','task_id':packet['task_id'],
                'context_id':packet['context_id'],'packet_digest':packet['packet_digest'],
                'changes':[{'path':folder+'/result.md','action':'created'}],
                'read_coverage':{'observed_refs':packet['declared_read_set'],'missing':[]},'blockers':[]}
        selections.append({'folder':folder,'index_path':folder+'/index.md','consumer':folder+'/result.md',
                           'requirement_index':0,'packet':packet,'result':result,'proposal_head':proposal})
    return selections


def call(repo,selections):
    return requalify_explicit_batch_as_global_coordinator(repo,load_folder_policy_v2(repo,'HEAD'),selections=selections)


def test_two_explicit_owners_remain_review_pending(equivalent_repo):
    selections=fixture(equivalent_repo); outcome=call(equivalent_repo,selections)
    assert outcome['state']=='review_pending' and len(outcome['proposals'])==2
    assert outcome['coverage']=='explicit_selected_requirements_only'
    assert outcome['host_authority']=='caller_trust_not_verified'
    assert outcome['historic_approval']=='not_independently_verified'
    assert outcome['migration']=='not_performed'
    assert all(item['state']=='review_pending' and item['freshness']=='not_assessed' for item in outcome['proposals'])


def test_bilateral_cross_owner_source_stays_review_pending(equivalent_repo):
    outcome=call(equivalent_repo,fixture(equivalent_repo,cross=True))
    assert len(outcome['proposals'])==2 and outcome['state']=='review_pending'
    assert all(item['selectors'][0]['bytes_equivalent'] for item in outcome['proposals'])
    assert all(item['historical_authority']=='ancestor_only_not_independent_approval_proof'
               for item in outcome['proposals'])


def test_revoked_second_owner_blocks_before_any_selected_body(equivalent_repo,monkeypatch):
    selections=fixture(equivalent_repo); path=equivalent_repo/'wiki-context-controls.yaml'
    data=yaml.safe_load(path.read_text());data['controls']['b']['policy']['deny']={'read':['b/source.md']}
    path.write_text(yaml.safe_dump(data));commit(equivalent_repo)
    original=RepositoryReader.read
    def sentinel(self,path,*args,**kwargs):
        if path not in ('wiki-context-controls.yaml',):
            raise AssertionError('selected body read before all owners checked')
        return original(self,path,*args,**kwargs)
    monkeypatch.setattr(RepositoryReader,'read',sentinel)
    with pytest.raises(FolderBatchRequalificationError):
        call(equivalent_repo,selections)


def test_forged_result_and_dynamic_query_block_before_any_selected_body(equivalent_repo,monkeypatch):
    selections=fixture(equivalent_repo)
    forged=deepcopy(selections);forged[1]['result']['packet_digest']='0'*64
    dynamic=deepcopy(selections);dynamic[1]['packet']['query_fingerprint']='0'*64
    original=RepositoryReader.read
    def sentinel(self,path,*args,**kwargs):
        if path!='wiki-context-controls.yaml':raise AssertionError('selected body read before full batch validation')
        return original(self,path,*args,**kwargs)
    monkeypatch.setattr(RepositoryReader,'read',sentinel)
    for batch in (forged,dynamic):
        with pytest.raises(FolderBatchRequalificationError):call(equivalent_repo,batch)


def test_no_sibling_body_or_global_manifest_in_output(equivalent_repo,monkeypatch):
    import json
    selections=fixture(equivalent_repo)
    # A tracked sibling context may appear in the legacy global manifest, but
    # its unrelated body must never be opened or returned.
    put(equivalent_repo,'unused/private.md','unselected-synthetic-body')
    child={'schema_version':'wiki.context/v1','id':'sibling-id','parent':'root','root':'unused',
           'purpose':'synthetic','owner':'fixture','instructions':[],'skills':[],'templates':[],
           'policy':{'read':['self'],'write':['self']},'imports':[],'exports':[]}
    put(equivalent_repo,'unused/context.yaml',yaml.safe_dump(child));commit(equivalent_repo)
    original=RepositoryReader.read
    def sentinel(self,path,*args,**kwargs):
        if path=='unused/private.md':raise AssertionError('unselected sibling body opened')
        return original(self,path,*args,**kwargs)
    monkeypatch.setattr(RepositoryReader,'read',sentinel)
    outcome=call(equivalent_repo,selections)
    assert 'unselected-synthetic-body' not in json.dumps(outcome)
    assert 'sibling-id' not in json.dumps(outcome)


def test_one_sided_cross_owner_grant_blocks_before_any_body(equivalent_repo,monkeypatch):
    from wiki_core.context_selection import digest
    selections=fixture(equivalent_repo)
    config=equivalent_repo/'wiki-context-controls.yaml'; data=yaml.safe_load(config.read_text())
    data['controls']['a']['policy']['read']=['self','b/source.md']
    grant={'from_context':'b','to_context':'a','selector':'b/source.md','field':'status',
           'use':'interpret','classification':'synthetic','expires':'2099-01-01'}
    data['controls']['a']['imports']=[grant]
    config.write_text(yaml.safe_dump(data));commit(equivalent_repo)
    batch=deepcopy(selections); item=batch[0]; packet=item['packet']
    row=next(row for row in packet['inputs'] if row['kind']=='evidence')
    row['ref']='b/source.md';row['producer']='other'
    old_ref=next(row for row in packet['declared_read_set'] if row['ref']=='a/source.md')
    old_ref['ref']='b/source.md'
    packet['packet_digest']=digest({k:v for k,v in packet.items() if k!='packet_digest'})
    item['result']['packet_digest']=packet['packet_digest']
    item['result']['read_coverage']['observed_refs']=deepcopy(packet['declared_read_set'])
    original=RepositoryReader.read
    def sentinel(self,path,*args,**kwargs):
        if path!='wiki-context-controls.yaml':raise AssertionError('body opened before bilateral check')
        return original(self,path,*args,**kwargs)
    monkeypatch.setattr(RepositoryReader,'read',sentinel)
    with pytest.raises(FolderBatchRequalificationError,match='current input authority unavailable'):
        call(equivalent_repo,batch)


def test_undeclared_second_mandatory_blocks_before_any_consumer_or_source(equivalent_repo,monkeypatch):
    from wiki_core.context_selection import digest
    selections=fixture(equivalent_repo)
    put(equivalent_repo,'b/not-declared.md','Synthetic unrelated\n');commit(equivalent_repo)
    batch=deepcopy(selections);item=batch[1];packet=item['packet']
    row=next(row for row in packet['inputs'] if row['kind']=='mandatory' and row['ref']=='docs/contract.md')
    row['ref']='b/not-declared.md'
    old_ref=next(row for row in packet['declared_read_set'] if row['ref']=='docs/contract.md')
    old_ref['ref']='b/not-declared.md'
    packet['packet_digest']=digest({k:v for k,v in packet.items() if k!='packet_digest'})
    item['result']['packet_digest']=packet['packet_digest']
    item['result']['read_coverage']['observed_refs']=deepcopy(packet['declared_read_set'])
    original=RepositoryReader.read
    def sentinel(self,path,*args,**kwargs):
        if path in ('a/result.md','b/result.md','a/source.md','b/source.md','b/not-declared.md'):
            raise AssertionError('body opened before all mandatory references checked')
        return original(self,path,*args,**kwargs)
    monkeypatch.setattr(RepositoryReader,'read',sentinel)
    with pytest.raises(FolderBatchRequalificationError,match='current mandatory authority unavailable'):
        call(equivalent_repo,batch)


def test_earlier_content_without_owner_blocks_before_old_source(equivalent_repo,monkeypatch):
    from wiki_core.context_selection import digest
    earlier=git(equivalent_repo,'rev-parse','HEAD');selections=fixture(equivalent_repo)
    batch=deepcopy(selections);item=batch[1];packet=item['packet'];packet['content_revision']=earlier
    packet['packet_digest']=digest({k:v for k,v in packet.items() if k!='packet_digest'})
    item['result']['packet_digest']=packet['packet_digest']
    original=RepositoryReader.read
    def sentinel(self,path,*args,**kwargs):
        if path in ('a/source.md','b/source.md','a/result.md','b/result.md'):
            raise AssertionError('historical content opened before content-owner check')
        return original(self,path,*args,**kwargs)
    monkeypatch.setattr(RepositoryReader,'read',sentinel)
    with pytest.raises(FolderBatchRequalificationError,match='historical consumer authority unavailable'):
        call(equivalent_repo,batch)


def test_proposal_owner_change_blocks_before_output_body(equivalent_repo,monkeypatch):
    selections=fixture(equivalent_repo)
    manifest=equivalent_repo/'a/context.yaml';original_manifest=manifest.read_text()
    altered=yaml.safe_load(original_manifest);altered['id']='moved-owner'
    manifest.write_text(yaml.safe_dump(altered));commit(equivalent_repo)
    wrong_proposal=git(equivalent_repo,'rev-parse','HEAD')
    manifest.write_text(original_manifest);commit(equivalent_repo)
    batch=deepcopy(selections);batch[0]['proposal_head']=wrong_proposal
    original=RepositoryReader.read
    def sentinel(self,path,*args,**kwargs):
        if path in ('a/source.md','b/source.md','a/result.md','b/result.md'):
            raise AssertionError('selected body opened before proposal-owner check')
        return original(self,path,*args,**kwargs)
    monkeypatch.setattr(RepositoryReader,'read',sentinel)
    with pytest.raises(FolderBatchRequalificationError,match='historical consumer authority unavailable'):
        call(equivalent_repo,batch)


def test_second_packet_policy_revocation_blocks_before_first_consumer(equivalent_repo,monkeypatch):
    from wiki_core.context_selection import digest
    selections=fixture(equivalent_repo)
    manifest=equivalent_repo/'b/context.yaml'; original_manifest=manifest.read_text()
    data=yaml.safe_load(original_manifest); data['policy']['deny']={'read':['b/source.md']}
    manifest.write_text(yaml.safe_dump(data)); commit(equivalent_repo)
    revoked=git(equivalent_repo,'rev-parse','HEAD')
    manifest.write_text(original_manifest); commit(equivalent_repo)
    proposal=git(equivalent_repo,'rev-parse','HEAD')
    batch=deepcopy(selections); item=batch[1]; packet=item['packet']
    packet['policy_revision']=revoked; item['proposal_head']=proposal
    for row in packet['inputs']:
        if row['kind']=='mandatory': row['revision']=revoked
    for row in packet['declared_read_set']:
        if row['ref']!='b/source.md': row['revision']=revoked
    packet['packet_digest']=digest({k:v for k,v in packet.items() if k!='packet_digest'})
    item['result']['packet_digest']=packet['packet_digest']
    item['result']['read_coverage']['observed_refs']=deepcopy(packet['declared_read_set'])
    original=RepositoryReader.read
    def sentinel(self,path,*args,**kwargs):
        if path in ('a/result.md','b/result.md','a/source.md','b/source.md'):
            raise AssertionError('selected body read before second historical policy validation')
        return original(self,path,*args,**kwargs)
    monkeypatch.setattr(RepositoryReader,'read',sentinel)
    with pytest.raises(FolderBatchRequalificationError,match='historical evidence authority unavailable'):
        call(equivalent_repo,batch)


def test_omitted_historical_mandatory_blocks_before_first_consumer(equivalent_repo,monkeypatch):
    from wiki_core.context_selection import digest
    selections=fixture(equivalent_repo)
    manifest=equivalent_repo/'context.yaml'; original_manifest=manifest.read_text()
    historical=yaml.safe_load(original_manifest)
    historical['instructions'].append('docs/secret-synthetic.md')
    manifest.write_text(yaml.safe_dump(historical))
    put(equivalent_repo,'docs/secret-synthetic.md','Synthetic denied body\n');commit(equivalent_repo)
    packet_policy=git(equivalent_repo,'rev-parse','HEAD')
    manifest.write_text(original_manifest)
    controls=equivalent_repo/'wiki-context-controls.yaml'; data=yaml.safe_load(controls.read_text())
    data['controls']['b']['policy']['deny']={'read':['docs/secret-synthetic.md']}
    controls.write_text(yaml.safe_dump(data));commit(equivalent_repo)
    proposal=git(equivalent_repo,'rev-parse','HEAD')
    batch=deepcopy(selections);item=batch[1];packet=item['packet']
    packet['policy_revision']=packet_policy;item['proposal_head']=proposal
    for row in packet['inputs']:
        if row['kind']=='mandatory':row['revision']=packet_policy
    for row in packet['declared_read_set']:
        if row['ref']!='b/source.md':row['revision']=packet_policy
    packet['packet_digest']=digest({k:v for k,v in packet.items() if k!='packet_digest'})
    item['result']['packet_digest']=packet['packet_digest']
    item['result']['read_coverage']['observed_refs']=deepcopy(packet['declared_read_set'])
    original=RepositoryReader.read
    def sentinel(self,path,*args,**kwargs):
        if path in ('docs/secret-synthetic.md','a/result.md','b/result.md','a/source.md','b/source.md'):
            raise AssertionError('body opened before complete historical mandatory validation')
        return original(self,path,*args,**kwargs)
    monkeypatch.setattr(RepositoryReader,'read',sentinel)
    with pytest.raises(FolderBatchRequalificationError,match='historical mandatory readset differs'):
        call(equivalent_repo,batch)
