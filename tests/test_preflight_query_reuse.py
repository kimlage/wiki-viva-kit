"""Synthetic repeated-query preflight; operation-local reuse and authority fences."""
import yaml
import pytest
from wiki_core.context_packet import build_packet
from wiki_core.context_integration import IntegrationError
from wiki_core.context_policy import PolicyError
from wiki_core.context_selection import requirement_query
from wiki_core.repository_reader import RepositoryReader
from tests.test_context_flow import repo, git, policy
from tests.test_context_dynamic_selection import collection, packet, requirement, declare, commit, TASK


@pytest.fixture
def proposal(collection):
    p=packet(collection); req=requirement(p); declare(collection,req)
    other=collection/'finance/costs/other.md'
    other.write_text('---\n'+yaml.safe_dump({'page_id':'other-result','page_type':'claim','information_requirements':[req]})+'---\nInterpretation.\n')
    base=commit(collection)
    explicit=build_packet(collection,policy(collection),'costs',base,[],50000,**TASK)
    git(collection,'checkout','-qb','wiki/two-consumers')
    for name in ('result.md','other.md'):
        f=collection/'finance/costs'/name;f.write_text(f.read_text()+'Independent edit.\n')
    git(collection,'add','.');git(collection,'commit','-qm','two consumers');head=git(collection,'rev-parse','HEAD')
    done={'schema_version':'wiki.task-result/v1','task_id':explicit['task_id'],'context_id':'costs','packet_digest':explicit['packet_digest'],
          'status':'completed','blockers':[], 'changes':[{'path':'finance/costs/result.md','action':'modified'}, {'path':'finance/costs/other.md','action':'modified'}],
          'read_coverage':{'observed_refs':explicit['declared_read_set'],'missing':[]}}
    return collection,base,head,explicit,done,req


def execute(data):
    from wiki_core.context_integration import preflight
    root,base,head,p,done,_=data
    return preflight(root,policy(root),context_id='costs',base=base,head=head,branch='wiki/two-consumers',packet=p,result=done)


def test_two_consumers_reduce_duplicate_selection_without_changing_budget_or_output(proposal,monkeypatch):
    import wiki_core.context_integration as module
    Original=module._QueryReuse; counts={'historical':0,'selection':0}; instances=[]
    old_reproduce,old_select=module.reproduce_query,module.select_query
    def count_reproduce(*args,**kwargs): counts['historical']+=1;return old_reproduce(*args,**kwargs)
    def count_select(*args,**kwargs): counts['selection']+=1;return old_select(*args,**kwargs)
    monkeypatch.setattr(module,'reproduce_query',count_reproduce);monkeypatch.setattr(module,'select_query',count_select)
    class NoHits(dict):
        def __contains__(self,key): return False
    class Measured(Original):
        disable=False
        def __init__(self,*args):
            super().__init__(*args)
            if self.disable:self.cache=NoHits()
            instances.append(self)
    monkeypatch.setattr(module,'_QueryReuse',Measured)
    Measured.disable=True; baseline=execute(proposal); baseline_counts=dict(counts); baseline_budget=instances[-1].budget[0]
    counts.update(historical=0,selection=0);Measured.disable=False
    optimized=execute(proposal)
    assert optimized==baseline
    assert baseline_counts=={'historical':2,'selection':4}
    assert counts=={'historical':1,'selection':2}
    assert instances[-1].budget[0]==baseline_budget
    execute(proposal)  # A new invocation cannot reuse the previous invocation's receipts.
    assert counts=={'historical':2,'selection':4}
    assert instances[-1].budget[0]==baseline_budget


def test_reuse_does_not_waive_logical_byte_budget(proposal):
    from wiki_core.context_integration import _QueryReuse
    root,base,_,_,_,req=proposal
    reader=RepositoryReader(root,base);budget=[32_000_000];reuse=_QueryReuse(root,policy(root),'costs',budget,reader)
    reuse.get('base',reader,requirement_query(req)); cost=32_000_000-budget[0]
    assert cost>0
    budget[0]=cost-1
    with pytest.raises(PolicyError,match='byte limit'): reuse.get('base',reader,requirement_query(req))


@pytest.mark.parametrize('race',['policy','branch'])
def test_reuse_does_not_bypass_final_authority_or_branch_fences(proposal,monkeypatch,race):
    import wiki_core.context_integration as module
    root,_,head,_,_,_=proposal; original=module._QueryReuse.get; calls=[0]
    def move(self,*args,**kwargs):
        calls[0]+=1
        if calls[0]==4:
            if race=='policy': git(root,'update-ref','refs/remotes/origin/main',head)
            else: git(root,'update-ref','refs/heads/wiki/two-consumers',git(root,'rev-parse','HEAD^'))
        return original(self,*args,**kwargs)
    monkeypatch.setattr(module._QueryReuse,'get',move)
    with pytest.raises((PolicyError,IntegrationError)): execute(proposal)


def test_changed_proposal_selection_still_fails(proposal):
    from wiki_core.context_integration import preflight
    root,base,_,p,done,_=proposal
    path=root/'finance/costs/items/first.md';path.write_text(path.read_text().replace('amount: 10','amount: 99'))
    git(root,'add','.');git(root,'commit','-qm','change selected source');head=git(root,'rev-parse','HEAD')
    done={**done,'changes':[*done['changes'],{'path':'finance/costs/items/first.md','action':'modified'}]}
    with pytest.raises(IntegrationError,match='existing query requirement'):
        preflight(root,policy(root),context_id='costs',base=base,head=head,branch='wiki/two-consumers',packet=p,result=done)


def test_invalid_authority_failure_is_never_cached(proposal):
    from wiki_core.context_integration import _QueryReuse
    root,base,_,_,_,req=proposal
    reader=RepositoryReader(root,req['consumed_revision']);reuse=_QueryReuse(root,policy(root),'costs',[32_000_000],reader)
    with pytest.raises(PolicyError):
        reuse.get('historical',reader,requirement_query(req),policy_revision=req['query_policy_revision'],expected_authority='0'*64)
    assert not reuse.cache
