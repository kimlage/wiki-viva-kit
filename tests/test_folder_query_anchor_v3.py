"""Synthetic separate-anchor query; no private data or model execution."""
from copy import deepcopy

import pytest
import yaml

from tests.test_folder_policy_v2 import project, put, commit, git
from wiki_core.folder_packet_v2 import build_folder_packet_v2
from wiki_core.folder_policy_v2 import load_folder_policy_v2
from wiki_core.folder_query_anchor_v3 import (FolderAnchorQueryError, _observed,
        build_anchor_query_packet_v3, preflight_anchor_query_v3)
from wiki_core.repository_reader import RepositoryReader


def fixture(repo, evidence=()):
    put(repo,'a/index.md','Context index\n')
    put(repo,'a/collection.md','---\npage_id: catalog\npage_type: source_catalog\n---\nCollection contract\n')
    put(repo,'a/items/one.md','---\npage_id: one\nstatus: active\namount: 11\n---\nFirst\n')
    put(repo,'a/items/two.md','---\npage_id: two\nstatus: inactive\namount: 22\n---\nSecond\n')
    commit(repo); p=load_folder_policy_v2(repo,'HEAD')
    base=build_folder_packet_v2(repo,p,'a',50000,index_path='a/index.md',content_revision='HEAD',
                               task_id='synthetic',goal='review',output='a/result.md',integrator='independent',evidence=evidence)
    req={'target':'a/collection.md','reason':'synthetic','use':'interpret','classification':'synthetic',
         'query':{'scope':'a/items','filters':{'status':'active'},'field':'amount',
                  'max_enumerated':20,'max_matches':10,'max_scan_bytes':100000}}
    return p,base,req


def report(packet, action):
    base=packet['base_packet']
    return {'schema_version':'wiki.folder-anchor-query-task-result/v3','status':'completed',
            'task_id':base['task_id'],'context_id':base['context_id'],'packet_digest':packet['packet_digest'],
            'observed':_observed(packet),'observed_queries':[packet['query']['receipt']['query_id']],
            'changes':[{'path':'a/result.md','action':action}]}


def test_separate_index_and_anchor_are_bound_and_delivered(project):
    from wiki_core.context_selection import digest, normalize_query, query_identity
    p,base,req=fixture(project)
    out=build_anchor_query_packet_v3(project,p,base_packet=base,request=req)
    assert out['base_packet']['index_path']=='a/index.md'
    assert out['query']['anchor']['path']=='a/collection.md'
    assert out['query']['receipt']['schema_version']=='wiki.folder-query-receipt/v3'
    assert out['query']['receipt']['anchor_path']=='a/collection.md'
    new_id=out['query']['receipt']['query_id']
    assert new_id != query_identity(normalize_query(req))
    assert new_id != digest({'schema_version':'wiki.folder-query-identity/v2',
                             'context_id':base['context_id'],'request':normalize_query(req)})
    assert out['query']['selected'][0]['text']=='11'
    assert len(out['query']['receipt']['members'])==1
    assert len(out['packet_digest'])==64


def test_anchor_denied_before_any_body(project,monkeypatch):
    _,_,req=fixture(project)
    conf=project/'wiki-context-controls.yaml'; data=yaml.safe_load(conf.read_text())
    data['controls']['a']['policy']['deny']={'read':['a/collection.md']}
    conf.write_text(yaml.safe_dump(data)); commit(project)
    p=load_folder_policy_v2(project,'HEAD')
    # Packet metadata is deliberately supplied without a valid body; denial
    # must happen before any attempt to open instructions or query content.
    base={'schema_version':'wiki.folder-task-context/v2','context_folder':'a','index_path':'a/index.md',
          'index_section':None,'start_folder':None,'max_bytes':50000,'inputs':[]}
    original=RepositoryReader.read
    def sentinel(self,path,*args,**kwargs):
        if path!='wiki-context-controls.yaml': raise AssertionError('body opened before anchor authority')
        return original(self,path,*args,**kwargs)
    monkeypatch.setattr(RepositoryReader,'read',sentinel)
    with pytest.raises(FolderAnchorQueryError,match='anchor authority'):
        build_anchor_query_packet_v3(project,p,base_packet=base,request=req)


def test_other_owner_and_nested_scope_are_denied(project,monkeypatch):
    p,base,req=fixture(project)
    sibling=deepcopy(req); sibling['target']='a/aux/b/index.md'; sibling['query']['scope']='a/aux/b'
    with pytest.raises(FolderAnchorQueryError):
        build_anchor_query_packet_v3(project,p,base_packet=base,request=sibling)
    put(project,'a/items/child/AGENTS.md','Child\n'); put(project,'a/items/child/index.md','Index\n'); commit(project)
    p=load_folder_policy_v2(project,'HEAD')
    base=build_folder_packet_v2(project,p,'a',50000,index_path='a/index.md',content_revision='HEAD',
                                task_id='synthetic',goal='review',output='a/result.md',integrator='independent')
    original=RepositoryReader.read
    def sentinel(self,path,*args,**kwargs):
        if path.startswith('a/items/'): raise AssertionError('query body opened before nested boundary denial')
        return original(self,path,*args,**kwargs)
    monkeypatch.setattr(RepositoryReader,'read',sentinel)
    with pytest.raises(FolderAnchorQueryError):
        build_anchor_query_packet_v3(project,p,base_packet=base,request=req)


def test_budget_secrets_and_historical_revision_fail_closed(project):
    p,base,req=fixture(project)
    bounded=deepcopy(req); bounded['query']['max_scan_bytes']=1
    with pytest.raises(FolderAnchorQueryError,match='byte limit'):
        build_anchor_query_packet_v3(project,p,base_packet=base,request=bounded)
    bad=deepcopy(req); bad['reason']='https://example.invalid/?X-Goog-Signature=synthetic'
    with pytest.raises(FolderAnchorQueryError,match='secret'):
        build_anchor_query_packet_v3(project,p,base_packet=base,request=bad)
    older=deepcopy(base); older['content_revision']='0'*40
    with pytest.raises(FolderAnchorQueryError):
        build_anchor_query_packet_v3(project,p,base_packet=older,request=req)


@pytest.mark.parametrize('action',['modified','deleted'])
def test_preflight_requires_anchor_and_whole_prior_output(project,action):
    put(project,'a/result.md','---\npage_type: claim\n---\nPrior\n')
    evidence=[{'path':'a/result.md','producer_folder':'a','reason':'prior','use':'interpret','classification':'synthetic'}]
    p,base,req=fixture(project,evidence=evidence); before=git(project,'rev-parse','HEAD')
    packet=build_anchor_query_packet_v3(project,p,base_packet=base,request=req)
    git(project,'checkout','-qb','wiki/anchor-v3')
    if action=='deleted': (project/'a/result.md').unlink()
    else: put(project,'a/result.md','---\npage_type: claim\n---\nUpdated\n')
    git(project,'add','-A');git(project,'commit','-qm','output');head=git(project,'rev-parse','HEAD')
    result=report(packet,action)
    outcome=preflight_anchor_query_v3(project,p,base=before,head=head,branch='wiki/anchor-v3',packet=packet,result=result)
    assert outcome['state']=='independent_review_required' and outcome['merge']=='not_performed'
    missing=deepcopy(result); missing['observed']=[r for r in missing['observed'] if r['kind']!='query_anchor']
    with pytest.raises(FolderAnchorQueryError,match='readset differs'):
        preflight_anchor_query_v3(project,p,base=before,head=head,branch='wiki/anchor-v3',packet=packet,result=missing)


def test_preflight_denies_anchor_change_before_proposed_body(project,monkeypatch):
    p,base,req=fixture(project);before=git(project,'rev-parse','HEAD')
    packet=build_anchor_query_packet_v3(project,p,base_packet=base,request=req)
    git(project,'checkout','-qb','wiki/anchor-change');put(project,'a/collection.md','Changed\n')
    git(project,'add','-A');git(project,'commit','-qm','changed');head=git(project,'rev-parse','HEAD')
    original=RepositoryReader.read
    def sentinel(self,path,*args,**kwargs):
        if self.revision==head and path=='a/collection.md': raise AssertionError('proposed anchor opened')
        return original(self,path,*args,**kwargs)
    monkeypatch.setattr(RepositoryReader,'read',sentinel)
    with pytest.raises(FolderAnchorQueryError,match='scope or anchor'):
        preflight_anchor_query_v3(project,p,base=before,head=head,branch='wiki/anchor-change',packet=packet,result=report(packet,'created'))


def test_preflight_rejects_modification_without_whole_prior_output(project):
    put(project,'a/result.md','---\npage_type: claim\n---\nPrior\n')
    p,base,req=fixture(project);before=git(project,'rev-parse','HEAD')
    packet=build_anchor_query_packet_v3(project,p,base_packet=base,request=req)
    git(project,'checkout','-qb','wiki/anchor-no-prior')
    put(project,'a/result.md','---\npage_type: claim\n---\nUpdated\n')
    git(project,'add','-A');git(project,'commit','-qm','output');head=git(project,'rev-parse','HEAD')
    with pytest.raises(FolderAnchorQueryError):
        preflight_anchor_query_v3(project,p,base=before,head=head,branch='wiki/anchor-no-prior',
                                  packet=packet,result=report(packet,'modified'))


def test_revoked_packet_evidence_blocks_before_index_or_anchor_body(project,monkeypatch):
    put(project,'a/extra.md','Synthetic evidence\n')
    evidence=[{'path':'a/extra.md','producer_folder':'a','reason':'extra','use':'interpret','classification':'synthetic'}]
    _,base,req=fixture(project,evidence=evidence)
    conf=project/'wiki-context-controls.yaml'; data=yaml.safe_load(conf.read_text())
    data['controls']['a']['policy']['deny']={'read':['a/extra.md']}
    conf.write_text(yaml.safe_dump(data));commit(project);p=load_folder_policy_v2(project,'HEAD')
    # Only metadata is needed to check current authority; the packet is then
    # deliberately stale but no body should be read on the way to rejection.
    metadata=deepcopy(base);metadata['policy_revision']=p.policy_revision;metadata['content_revision']=p.policy_revision
    original=RepositoryReader.read
    def sentinel(self,path,*args,**kwargs):
        if path!='wiki-context-controls.yaml': raise AssertionError('body opened before all evidence authority')
        return original(self,path,*args,**kwargs)
    monkeypatch.setattr(RepositoryReader,'read',sentinel)
    with pytest.raises(FolderAnchorQueryError):
        build_anchor_query_packet_v3(project,p,base_packet=metadata,request=req)
