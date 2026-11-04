"""Versioned current-only query prototype in synthetic single-owner scopes."""
import pytest

from tests.test_folder_policy_v2 import project, put, commit, git
from wiki_core.context_selection import normalize_query, query_identity
from wiki_core.folder_packet_v2 import build_folder_packet_v2
from wiki_core.folder_policy_v2 import load_folder_policy_v2
from wiki_core.folder_query_v2 import FolderQueryError, select_folder_query_v2
from wiki_core.repository_reader import RepositoryReader


def fixture_query(repo):
    put(repo,'a/index.md','---\npage_id: synthetic-catalog\npage_type: source_catalog\n---\nCollection contract\n')
    put(repo,'a/items/one.md','---\npage_id: one\nstatus: active\namount: 11\n---\nSource one\n')
    put(repo,'a/items/two.md','---\npage_id: two\nstatus: inactive\namount: 22\n---\nSource two\n')
    commit(repo)
    p=load_folder_policy_v2(repo,'HEAD')
    packet=build_folder_packet_v2(repo,p,'a',50000,index_path='a/index.md',content_revision='HEAD',
                                  task_id='x',goal='x',output='a/result.md',integrator='x')
    entry={'target':'a/index.md','reason':'synthetic','use':'interpret','classification':'synthetic',
           'query':{'scope':'a/items','filters':{'status':'active'},'field':'amount',
                    'max_enumerated':20,'max_matches':10,'max_scan_bytes':100000}}
    return p,packet,entry


def test_v2_query_uses_own_versioned_identity_and_exact_selection(project):
    p,packet,entry=fixture_query(project)
    out=select_folder_query_v2(project,p,packet=packet,content_revision='HEAD',request=entry)
    r=out['receipt']
    assert r['schema_version']=='wiki.folder-query-receipt/v2'
    assert r['query_id'] != query_identity(normalize_query(entry))
    assert r['members']==[{'ref':'a/items/one.md','page_id':'one'}]
    assert len(r['receipt_digest'])==64 and out['selected'][0]['text']=='11'
    assert r['packet_digest']==packet['packet_digest']
    assert r['content_revision']==p.policy_revision and out['read_verification']=='not_performed'


def test_v2_query_blocks_historical_content_before_opening_body(project,monkeypatch):
    p,packet,entry=fixture_query(project); old=git(project,'rev-parse','HEAD')
    put(project,'a/items/one.md','---\npage_id: one\nstatus: active\namount: 99\n---\nNew\n'); commit(project)
    p=load_folder_policy_v2(project,'HEAD')
    packet=build_folder_packet_v2(project,p,'a',50000,index_path='a/index.md',content_revision='HEAD',
                                  task_id='x',goal='x',output='a/result.md',integrator='x')
    original=RepositoryReader.read
    def spy(self,ref,*a,**kw):
        if self.revision==old and ref.startswith('a/items/'):
            raise AssertionError('historical query content opened before requalification')
        return original(self,ref,*a,**kw)
    monkeypatch.setattr(RepositoryReader,'read',spy)
    with pytest.raises(FolderQueryError,match='historical v2 query requalification unavailable'):
        select_folder_query_v2(project,p,packet=packet,content_revision=old,request=entry)


def test_v2_query_blocks_nested_owner_before_any_member_body(project,monkeypatch):
    _,_,entry=fixture_query(project)
    put(project,'a/items/child/AGENTS.md','Nested instructions\n')
    put(project,'a/items/child/index.md','Nested index\n')
    put(project,'a/items/child/private.md','---\npage_id: hidden\n---\nHidden\n'); commit(project)
    p=load_folder_policy_v2(project,'HEAD')
    packet=build_folder_packet_v2(project,p,'a',50000,index_path='a/index.md',content_revision='HEAD',
                                  task_id='x',goal='x',output='a/result.md',integrator='x')
    original=RepositoryReader.read
    def spy(self,ref,*a,**kw):
        if ref.startswith('a/items/'):
            raise AssertionError('member body read before scope authority check')
        return original(self,ref,*a,**kw)
    monkeypatch.setattr(RepositoryReader,'read',spy)
    with pytest.raises(FolderQueryError,match='narrower authority'):
        select_folder_query_v2(project,p,packet=packet,content_revision='HEAD',request=entry)


def test_v2_query_rejects_v1_packet_and_enforces_scan_budget(project):
    p,packet,entry=fixture_query(project)
    with pytest.raises(FolderQueryError,match='v1 receipts require explicit migration'):
        select_folder_query_v2(project,p,packet={'schema_version':'wiki.task-context/v1'},content_revision='HEAD',request=entry)
    bounded={**entry,'query':{**entry['query'],'max_scan_bytes':1}}
    with pytest.raises(FolderQueryError,match='scan byte limit exceeded'):
        select_folder_query_v2(project,p,packet=packet,content_revision='HEAD',request=bounded)


def test_v2_query_impact_stays_blocked_without_historical_proof(project,monkeypatch):
    from wiki_core.folder_query_v2 import revalidate_folder_query_v2
    p,packet,entry=fixture_query(project)
    receipt=select_folder_query_v2(project,p,packet=packet,content_revision='HEAD',request=entry)['receipt']
    original=RepositoryReader.read
    def spy(self,ref,*a,**kw):
        if ref.startswith('a/items/'): raise AssertionError('historical query body was opened')
        return original(self,ref,*a,**kw)
    monkeypatch.setattr(RepositoryReader,'read',spy)
    with pytest.raises(FolderQueryError,match='historical v2 query requalification unavailable'):
        revalidate_folder_query_v2(project,p,receipt=receipt)
    with pytest.raises(FolderQueryError,match='v1 receipts require explicit migration'):
        revalidate_folder_query_v2(project,p,receipt={'schema_version':'wiki.query-receipt/v1'})
