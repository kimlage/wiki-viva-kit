"""Synthetic caller-trust coordinator proof, never wired as executor access."""
import json

import pytest
import yaml

from tests.test_folder_mandatory_v2 import equivalent_repo, put, git, commit
from tests.test_folder_requalification_v2 import prepare
from wiki_core.folder_policy_v2 import load_folder_policy_v2
from wiki_core.folder_requalification_coordinator_v2 import CoordinatorRequalificationError, requalify_v1_as_global_coordinator
from wiki_core.repository_reader import RepositoryReader


def call(repo, packet, result, proposal, *, folder='a', index='a/index.md', consumer='a/result.md'):
    return requalify_v1_as_global_coordinator(repo, load_folder_policy_v2(repo,'HEAD'),
        folder=folder,index_path=index,consumer=consumer,requirement_index=0,packet=packet,result=result,proposal_head=proposal)


def test_coordinator_reconstructs_v1_without_returning_sibling_metadata(equivalent_repo, monkeypatch):
    child={'schema_version':'wiki.context/v1','id':'sibling-sensitive-id','parent':'root','root':'other',
           'purpose':'synthetic','owner':'fixture','instructions':[],'skills':[],'templates':[],
           'policy':{'read':['self'],'write':['self']},'imports':[],'exports':[]}
    put(equivalent_repo,'other/context.yaml',yaml.safe_dump(child))
    put(equivalent_repo,'other/private.md','unselected-synthetic-body'); commit(equivalent_repo)
    base, proposal, packet, result, body=prepare(equivalent_repo)
    original=RepositoryReader.read
    def spy(self,ref,*a,**kw):
        if ref=='other/private.md': raise AssertionError('sibling domain body was read')
        return original(self,ref,*a,**kw)
    monkeypatch.setattr(RepositoryReader,'read',spy)
    out=call(equivalent_repo,packet,result,proposal)
    assert out['state']=='review_pending' and out['consumed_revision']==base
    assert out['selectors'][0]['bytes_equivalent'] and out['normative_bytes']=='changed_review_required'
    assert out['normative_coverage']=='new_or_reordered_rules_require_review'
    assert out['authority']=='caller_trust_not_verified' and out['freshness']=='not_assessed'
    assert 'sibling-sensitive-id' not in json.dumps(out) and 'unselected-synthetic-body' not in json.dumps(out)
    assert (equivalent_repo/'a/result.md').read_text()==body


def test_coordinator_checks_current_revocation_before_global_policy_read(equivalent_repo,monkeypatch):
    _, proposal, packet, result, _=prepare(equivalent_repo)
    path=equivalent_repo/'wiki-context-controls.yaml'; data=yaml.safe_load(path.read_text())
    data['controls']['a']['policy']['deny']={'read':['a/source.md']}
    path.write_text(yaml.safe_dump(data)); commit(equivalent_repo)
    import wiki_core.context_policy as legacy
    monkeypatch.setattr(legacy,'git_file',lambda *a,**k: pytest.fail('global policy body read before current authorization'))
    with pytest.raises(CoordinatorRequalificationError,match='current input authority unavailable'):
        call(equivalent_repo,packet,result,proposal)


def test_coordinator_marks_changed_normative_even_when_source_equal(equivalent_repo):
    base,proposal,packet,result,_=prepare(equivalent_repo)
    put(equivalent_repo,'docs/contract.md','Changed synthetic norm\n'); commit(equivalent_repo)
    out=call(equivalent_repo,packet,result,proposal)
    assert out['selectors'][0]['bytes_equivalent'] and out['normative_bytes']=='changed_review_required'
    assert out['state']=='review_pending' and out['consumed_revision']==base


def test_coordinator_rejects_consumer_owner_move_before_historical_output(equivalent_repo,monkeypatch):
    _,proposal,packet,result,_=prepare(equivalent_repo,output='a/new/result.md')
    put(equivalent_repo,'a/new/AGENTS.md','New context instruction\n')
    put(equivalent_repo,'a/new/index.md','New context index\n')
    path=equivalent_repo/'wiki-context-controls.yaml'; data=yaml.safe_load(path.read_text())
    grant={'from_context':'a','to_context':'a/new','selector':'a/source.md','field':'status',
           'use':'interpret','classification':'synthetic','expires':'2099-01-01'}
    data['controls']['a']['exports']=[grant]
    data['controls']['a/new']={'policy':{'read':['self','a/source.md'],'write':['self']},'imports':[grant],'exports':[]}
    path.write_text(yaml.safe_dump(data)); commit(equivalent_repo)
    original=RepositoryReader.read
    def spy(self,ref,*a,**kw):
        if self.revision==proposal and ref=='a/new/result.md': raise AssertionError('historical output opened before old owner check')
        return original(self,ref,*a,**kw)
    monkeypatch.setattr(RepositoryReader,'read',spy)
    with pytest.raises(CoordinatorRequalificationError,match='historical consumer owner or authority unavailable'):
        call(equivalent_repo,packet,result,proposal,folder='a/new',index='a/new/index.md',consumer='a/new/result.md')


def test_coordinator_rejects_changed_integrated_output_before_old_source_read(equivalent_repo,monkeypatch):
    _,proposal,packet,result,body=prepare(equivalent_repo)
    put(equivalent_repo,'a/result.md',body+'Later change\n'); commit(equivalent_repo)
    original=RepositoryReader.read
    def spy(self,ref,*a,**kw):
        if ref=='a/source.md': raise AssertionError('historical source opened despite mismatched output')
        return original(self,ref,*a,**kw)
    monkeypatch.setattr(RepositoryReader,'read',spy)
    with pytest.raises(CoordinatorRequalificationError,match='approved consumer differs from proposal'):
        call(equivalent_repo,packet,result,proposal)


def test_coordinator_blocks_dynamic_query_without_policy_replay(equivalent_repo,monkeypatch):
    _,proposal,packet,result,body=prepare(equivalent_repo)
    _,fm,rest=body.split('---\n',2); data=yaml.safe_load(fm)
    data['information_requirements'][0]['query']={'scope':'a'}
    put(equivalent_repo,'a/result.md','---\n'+yaml.safe_dump(data)+'---\n'+rest); commit(equivalent_repo)
    import wiki_core.context_policy as legacy
    monkeypatch.setattr(legacy,'git_file',lambda *a,**k: pytest.fail('global policy opened for unsupported query'))
    with pytest.raises(CoordinatorRequalificationError,match='dynamic v1 query requires independent v2 requalification'):
        call(equivalent_repo,packet,result,proposal)


def test_coordinator_requires_packet_output_to_match_selected_consumer(equivalent_repo, monkeypatch):
    _, proposal, packet, result, _ = prepare(equivalent_repo, packet_output='a/unrelated.md')
    import wiki_core.context_policy as legacy
    monkeypatch.setattr(legacy, 'git_file', lambda *a,**k: pytest.fail('global history read before output binding'))
    with pytest.raises(CoordinatorRequalificationError, match='output is not bound'):
        call(equivalent_repo, packet, result, proposal)


def test_coordinator_new_mandatory_rule_never_claims_full_normative_equivalence(equivalent_repo):
    _, proposal, packet, result, _ = prepare(equivalent_repo)
    put(equivalent_repo,'docs/new-rule.md','Synthetic newly required rule\n')
    agent=equivalent_repo/'AGENTS.md'
    agent.write_text(agent.read_text().replace('- [Template](docs/template.md)',
                     '- [Template](docs/template.md)\n- [New rule](docs/new-rule.md)'))
    commit(equivalent_repo)
    out=call(equivalent_repo,packet,result,proposal)
    assert out['selectors'][0]['bytes_equivalent']
    assert out['normative_bytes']=='changed_review_required'
    assert out['normative_coverage']=='new_or_reordered_rules_require_review'
    assert out['state']=='review_pending'
