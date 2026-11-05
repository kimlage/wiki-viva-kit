import datetime as dt
import os
import yaml
import pytest
from wiki_core.config import load_config
from wiki_core.information_relations import authored_graph, dependency_edges
from wiki_core.information_use import assess_information_use
from wiki_core.freshness_impact import repository_report
from tests.test_context_flow import repo, git, approve, policy


@pytest.fixture
def folder_normative_repo(repo):
    """Physical instruction owners and exact inherited-read connections."""
    for name, body in (
        ('AGENTS.md', 'Root normative instruction\n'),
        ('index.md', '# Root index\n'),
        ('finance/AGENTS.md', 'Finance normative instruction\n'),
        ('finance/index.md', '# Finance index\n'),
        ('finance/costs/AGENTS.md', 'Costs instruction\n'),
        ('finance/costs/index.md', '# Costs index\n'),
        ('finance/tax/AGENTS.md', 'Tax instruction\n'),
        ('finance/tax/index.md', '# Tax index\n'),
    ):
        (repo/name).write_text(body)
    def connection(producer, consumer, selector):
        return {'from_context':producer,'to_context':consumer,'selector':selector,
                'use':'interpretation','classification':'context','expires':'2099-01-01'}
    root_targets=['finance','finance/costs','finance/tax']
    root_rules=[connection('.',target,'AGENTS.md') for target in root_targets]
    finance_rules=[connection('finance',target,ref)
        for target in ('finance/costs','finance/tax')
        for ref in ('finance/AGENTS.md','finance/index.md')]
    access={
        '.':{'owner':'root','policy':{'read':['self'],'write':['self']},'exports':root_rules},
        'finance':{'owner':'finance','policy':{'read':['self','AGENTS.md'],'write':['self']},
                   'imports':[root_rules[0]],'exports':finance_rules},
    }
    for context in ('finance/costs','finance/tax'):
        access[context]={'owner':context,'policy':{'read':['self','AGENTS.md','finance/AGENTS.md','finance/index.md'],
                                                 'write':['self']},
                         'imports':[rule for rule in root_rules+finance_rules if rule['to_context']==context]}
    config={'paths':{'memory_root':'finance'},'audit':{'freshness_scope':'impact','information_impact':'use_scoped'},
            'context_access':access}
    (repo/'wiki.config.yaml').write_text(yaml.safe_dump(config))
    git(repo,'add','.'); git(repo,'commit','-qm','physical folder authority'); approve(repo)
    return repo


def physical_policy(repo):
    from wiki_core.context_policy import load_policy
    return load_policy(repo,'refs/remotes/origin/main','wiki.config.yaml')


def test_real_inventory_and_readiness_for_tracked_ancestor_rule(repo,monkeypatch):
    revision=git(repo,'rev-parse','HEAD')
    req={'target':'rules.md','fields':['*'],'temporal':'current','max_age_days':30,
         'consumed_revision':revision,'use':'normative','source_kind':'mandatory','classification':'internal'}
    target=repo/'finance/costs/result.md'
    target.write_text('---\n'+yaml.safe_dump({'page_id':'cost-task','page_type':'action','action_state':'open','information_requirements':[req]})+'---\nTask\n')
    (repo/'wiki.config.yaml').write_text('paths:\n  memory_root: finance\naudit:\n  information_impact: use_scoped\n')
    git(repo,'add','.'); git(repo,'commit','-qm','consumer'); approve(repo); base=git(repo,'rev-parse','HEAD')
    graph=authored_graph(repo,load_config(repo)); edges,_=dependency_edges(graph)
    assert not graph['errors']
    assert any(e['prerequisite']=='rules.md' and e['dependent']=='finance/costs/result.md' for e in edges)
    row=assess_information_use(graph,'finance/costs/result.md',now=dt.datetime.now(dt.timezone.utc))['requirements'][0]
    assert row['blockers']==['information_normative_authority_required']
    (repo/'rules.md').write_text('Updated approved rule\n'); git(repo,'add','.'); git(repo,'commit','-qm','rule changed'); approve(repo)
    from pathlib import Path
    original=Path.read_bytes
    def spy(path):
        if path==repo/'rules.md': raise AssertionError('global audit opened external rule body')
        return original(path)
    with monkeypatch.context() as m:
        m.setattr(Path,'read_bytes',spy)
        report=repository_report(repo,load_config(repo),base)
    assert not report['relation_errors']
    assert any(r['path']=='finance/costs/result.md' and r['reason']=='information_changed' and r['seed']=='rules.md' for r in report['pending_reviews'])
    changed=git(repo,'rev-parse','HEAD')
    with (repo/'context.yaml').open('a') as f: f.write('\n# policy review\n')
    git(repo,'add','.'); git(repo,'commit','-qm','policy change'); approve(repo)
    report=repository_report(repo,load_config(repo),changed)
    assert any(r['reason']=='normative_policy_requalification_required' for r in report['pending_reviews'])
    before_delete=git(repo,'rev-parse','HEAD'); git(repo,'rm','rules.md'); git(repo,'commit','-qm','remove rule'); approve(repo)
    report=repository_report(repo,load_config(repo),before_delete)
    assert report['relation_errors']
    assert any(r['path']=='finance/costs/result.md' and r['seed']=='rules.md' for r in report['pending_reviews'])


@pytest.mark.parametrize('inside',[False,True])
@pytest.mark.skipif(os.name=='nt',reason='worktree ctime cannot safely qualify unchanged rules on Windows')
def test_bound_full_audit_qualifies_only_current_inherited_rule(folder_normative_repo,inside,monkeypatch,capsys):
    from wiki_core.information_use import bind_verification_coverage, bind_normative_coverage
    repo=folder_normative_repo
    rule='finance/AGENTS.md' if inside else 'AGENTS.md'
    rev=git(repo,'rev-parse','HEAD')
    req={'target':rule,'fields':['*'],'temporal':'current','max_age_days':30,'consumed_revision':rev,'use':'normative','source_kind':'mandatory','classification':'internal',
         'authority_format':'folder','entry_folder':'finance/costs','entry_index':'finance/costs/index.md'}
    target='finance/costs/result.md'; (repo/target).write_text('---\n'+yaml.safe_dump({'page_id':'cost-task','page_type':'action','action_state':'open','information_requirements':[req]})+'---\nTask\n')
    git(repo,'add','.'); git(repo,'commit','-qm','consumer'); approve(repo); head=git(repo,'rev-parse','HEAD')
    graph=authored_graph(repo,load_config(repo)); qualified=bind_verification_coverage(repo,graph)
    assert not assess_information_use(qualified,target,now=dt.datetime.now(dt.timezone.utc))['ready']
    qualified=bind_normative_coverage(repo,qualified,physical_policy(repo),'finance/costs',head=head)
    row=assess_information_use(qualified,target,now=dt.datetime.now(dt.timezone.utc))['requirements'][0]
    assert row['ready'] and row['verified_at'] is None and row['evidence_refs']==[]
    assert row['source_kind']=='mandatory' and row['normative_status']=='equivalent' and row['policy_revision']==head
    assert row['review']=='not_assessed' and row['fact_freshness']=='not_assessed'
    other=bind_normative_coverage(repo,graph,physical_policy(repo),'finance/tax',head=head)
    assert assess_information_use(other,target,now=dt.datetime.now(dt.timezone.utc))['requirements'][0]['blockers']==['information_normative_authority_required']
    report=repository_report(repo,load_config(repo),head,query_context='finance/costs',query_policy_revision=head,query_head=head)
    assert not report['relation_errors']
    assert next(row for row in report['information_use'] if row['consumer']==target)['ready']
    assert report['query_revalidation']['normative_scope']=='selected_context_only_not_auditor_acl'
    if not inside:
        import sys
        from scripts import wiki_audit as audit
        monkeypatch.setattr(audit,'ROOT',repo)
        monkeypatch.setattr(sys,'argv',['wiki_audit.py','--check','--only','freshness_budget','--freshness-base',head,
            '--query-context','finance/costs','--query-policy-revision',head,'--query-head',head])
        code=audit.main(); output=capsys.readouterr().out
        assert code==0,output
    (repo/rule).write_text('Changed rule\n');git(repo,'add','.');git(repo,'commit','-qm','rule revision');new=git(repo,'rev-parse','HEAD')
    proposed=repository_report(repo,load_config(repo),head,query_context='finance/costs',query_policy_revision=head,query_head=new)
    row=next(row for row in proposed['information_use'] if row['consumer']==target)
    assert row['requirements'][0]['blockers']==['information_normative_changed']
    assert any(r['path']==target and r['reason']=='information_changed' for r in proposed['pending_reviews'])
    approve(repo)
    changed=bind_normative_coverage(repo,authored_graph(repo,load_config(repo)),physical_policy(repo),'finance/costs',head=new)
    assert assess_information_use(changed,target,now=dt.datetime.now(dt.timezone.utc))['requirements'][0]['blockers']==['information_normative_changed']


def test_bound_normative_revocation_never_reads_denied_rule(folder_normative_repo,monkeypatch):
    from wiki_core.information_use import bind_normative_coverage
    from wiki_core.context_impact import ImpactError
    from wiki_core.repository_reader import RepositoryReader
    repo=folder_normative_repo
    rev=git(repo,'rev-parse','HEAD'); req={'target':'AGENTS.md','fields':['*'],'temporal':'current','max_age_days':30,'consumed_revision':rev,'use':'normative','source_kind':'mandatory','classification':'internal',
        'authority_format':'folder','entry_folder':'finance/costs','entry_index':'finance/costs/index.md'}
    target='finance/costs/result.md'; (repo/target).write_text('---\n'+yaml.safe_dump({'page_id':'task','page_type':'action','action_state':'open','information_requirements':[req]})+'---\nTask\n')
    config=yaml.safe_load((repo/'wiki.config.yaml').read_text()); config['context_access']['finance/costs']['policy']['deny']={'read':['AGENTS.md']}
    (repo/'wiki.config.yaml').write_text(yaml.safe_dump(config))
    git(repo,'add','.'); git(repo,'commit','-qm','denied'); approve(repo); head=git(repo,'rev-parse','HEAD')
    graph=authored_graph(repo,load_config(repo)); original=RepositoryReader.read
    def spy(self,ref,*a,**kw):
        if ref=='AGENTS.md': raise AssertionError('denied rule read')
        return original(self,ref,*a,**kw)
    monkeypatch.setattr(RepositoryReader,'read',spy)
    # Revoking an inherited instruction prevents qualifying the physical
    # context altogether; both callers fail closed before opening the body.
    with pytest.raises(ImpactError,match='requires authorized requalification'):
        bind_normative_coverage(repo,graph,physical_policy(repo),'finance/costs',head=head)
    with pytest.raises(ValueError,match='requires authorized requalification'):
        repository_report(repo,load_config(repo),head,query_context='finance/costs',query_policy_revision=head,query_head=head)


@pytest.mark.parametrize('case',['unapproved_requirement','historical_override'])
def test_changed_folder_rule_needs_approved_and_unambiguous_history(folder_normative_repo,monkeypatch,case):
    from wiki_core.information_use import bind_normative_coverage
    from wiki_core.repository_reader import RepositoryReader
    repo=folder_normative_repo
    if case=='historical_override':
        (repo/'AGENTS.override.md').write_text('Earlier override\n')
        git(repo,'add','.');git(repo,'commit','-qm','earlier override');approve(repo)
    old=git(repo,'rev-parse','HEAD')
    req={'target':'AGENTS.md','fields':['*'],'temporal':'current','max_age_days':30,
         'consumed_revision':old,'use':'normative','source_kind':'mandatory','classification':'internal',
         'authority_format':'folder','entry_folder':'finance/costs','entry_index':'finance/costs/index.md'}
    target='finance/costs/result.md'
    body='---\n'+yaml.safe_dump({'page_id':'cost-task','page_type':'action','action_state':'open',
                                 'information_requirements':[req]})+'---\nTask\n'
    (repo/'AGENTS.md').write_text('Changed root instruction\n')
    if case=='historical_override':
        (repo/'AGENTS.override.md').unlink()
        (repo/target).write_text(body)
    git(repo,'add','.');git(repo,'commit','-qm','change root instruction');approve(repo)
    head=git(repo,'rev-parse','HEAD')
    if case=='unapproved_requirement': (repo/target).write_text(body)
    original=RepositoryReader.read
    def spy(self,ref,*args,**kwargs):
        if ref=='AGENTS.md' and self.revision==old:
            raise AssertionError('unqualified historical instruction read')
        return original(self,ref,*args,**kwargs)
    monkeypatch.setattr(RepositoryReader,'read',spy)
    graph=authored_graph(repo,load_config(repo))
    bound=bind_normative_coverage(repo,graph,physical_policy(repo),'finance/costs',head=head)
    row=assess_information_use(bound,target,now=dt.datetime.now(dt.timezone.utc))['requirements'][0]
    assert row['blockers']==['information_normative_authority_required']


def test_untracked_or_ordinary_external_reference_is_not_granted(repo):
    from copy import deepcopy
    rev=git(repo,'rev-parse','HEAD'); req={'target':'rules.md','fields':['*'],'temporal':'current','max_age_days':30,'consumed_revision':rev,'use':'normative','source_kind':'mandatory','classification':'internal'}
    target=repo/'finance/costs/result.md'; config=repo/'wiki.config.yaml'; config.write_text('paths:\n  memory_root: finance\n')
    fake=deepcopy(req); fake.pop('source_kind'); target.write_text('---\n'+yaml.safe_dump({'information_requirements':[fake]})+'---\nTask\n')
    assert authored_graph(repo,load_config(repo))['errors']
    fake=deepcopy(req); fake['target']='untracked-rule.md'; (repo/'untracked-rule.md').write_text('Not approved\n')
    target.write_text('---\n'+yaml.safe_dump({'information_requirements':[fake]})+'---\nTask\n')
    assert authored_graph(repo,load_config(repo))['errors']


def test_external_rule_inventory_uses_metadata_without_opening_body(repo,monkeypatch):
    from pathlib import Path
    rev=git(repo,'rev-parse','HEAD'); req={'target':'rules.md','fields':['*'],'temporal':'current','max_age_days':30,'consumed_revision':rev,'use':'normative','source_kind':'mandatory','classification':'internal'}
    (repo/'finance/costs/result.md').write_text('---\n'+yaml.safe_dump({'information_requirements':[req]})+'---\nTask\n')
    (repo/'wiki.config.yaml').write_text('paths:\n  memory_root: finance\n')
    orig=Path.read_bytes
    def spy(path):
        if path==repo/'rules.md': raise AssertionError('external rule body opened by inventory')
        return orig(path)
    monkeypatch.setattr(Path,'read_bytes',spy)
    assert not authored_graph(repo,load_config(repo))['errors']


def test_untracked_mandatory_inside_memory_is_not_resolved(repo):
    rev=git(repo,'rev-parse','HEAD');req={'target':'finance/costs/new-rule.md','fields':['*'],'temporal':'current','max_age_days':30,'consumed_revision':rev,'use':'normative','source_kind':'mandatory','classification':'internal'}
    (repo/'finance/costs/new-rule.md').write_text('Untracked\n')
    (repo/'finance/costs/result.md').write_text('---\n'+yaml.safe_dump({'information_requirements':[req]})+'---\nTask\n')
    (repo/'wiki.config.yaml').write_text('paths:\n  memory_root: finance\n')
    assert authored_graph(repo,load_config(repo))['errors']


@pytest.mark.skipif(os.name=='nt',reason='creating symlinks may require Windows developer privileges')
def test_tracked_symlink_cannot_resolve_normative_artifact(repo):
    rev=git(repo,'rev-parse','HEAD'); req={'target':'rules.md','fields':['*'],'temporal':'current','max_age_days':30,'consumed_revision':rev,'use':'normative','source_kind':'mandatory','classification':'internal'}
    (repo/'finance/costs/result.md').write_text('---\n'+yaml.safe_dump({'information_requirements':[req]})+'---\nTask\n')
    (repo/'wiki.config.yaml').write_text('paths:\n  memory_root: finance\n')
    (repo/'rules.md').unlink(); (repo/'rules.md').symlink_to('finance/costs/result.md')
    git(repo,'add','.');git(repo,'commit','-qm','replace rule with symlink')
    assert authored_graph(repo,load_config(repo))['errors']


def test_binder_rejects_unapproved_requirement_and_changed_rule_without_read(repo,monkeypatch):
    from wiki_core.information_use import bind_normative_coverage
    from wiki_core.repository_reader import RepositoryReader
    context='costs';target='finance/costs/result.md';base_branch=git(repo,'branch','--show-current')
    (repo/'wiki.config.yaml').write_text('paths:\n  memory_root: finance\n')
    (repo/target).write_text('---\npage_id: task\npage_type: action\n---\nTask\n')
    git(repo,'add','.');git(repo,'commit','-qm','approved consumer');approve(repo);base=git(repo,'rev-parse','HEAD')
    req={'target':'rules.md','fields':['*'],'temporal':'current','max_age_days':30,'consumed_revision':base,'use':'normative','source_kind':'mandatory','classification':'internal'}
    body='---\n'+yaml.safe_dump({'page_id':'task','page_type':'action','information_requirements':[req]})+'---\nTask\n'
    git(repo,'checkout','-qb','wiki/unapproved-requirement');(repo/target).write_text(body);git(repo,'add','.');git(repo,'commit','-qm','unapproved requirement');head=git(repo,'rev-parse','HEAD')
    original=RepositoryReader.read
    def spy(self,ref,*a,**kw):
        if ref=='rules.md': raise AssertionError('unapproved rule body read')
        return original(self,ref,*a,**kw)
    monkeypatch.setattr(RepositoryReader,'read',spy)
    graph=authored_graph(repo,load_config(repo));bound=bind_normative_coverage(repo,graph,policy(repo),context,head=head)
    row=assess_information_use(bound,target,now=dt.datetime.now(dt.timezone.utc))['requirements'][0]
    assert not row['ready'] and row['blockers']==['information_normative_authority_required']
    git(repo,'checkout','-q',base_branch);(repo/target).write_text(body);git(repo,'add','.');git(repo,'commit','-qm','approved requirement');approve(repo);approved=git(repo,'rev-parse','HEAD')
    git(repo,'checkout','-qb','wiki/unapproved-rule');(repo/'rules.md').write_text('Unapproved proposed rule\n');git(repo,'add','.');git(repo,'commit','-qm','unapproved rule');head=git(repo,'rev-parse','HEAD')
    graph=authored_graph(repo,load_config(repo));bound=bind_normative_coverage(repo,graph,policy(repo),context,head=head)
    assert assess_information_use(bound,target,now=dt.datetime.now(dt.timezone.utc))['requirements'][0]['blockers']==['information_normative_changed']
    git(repo,'checkout','-q',base_branch);(repo/'rules.md').write_text('Unapproved worktree rule\n')
    graph=authored_graph(repo,load_config(repo));bound=bind_normative_coverage(repo,graph,policy(repo),context,head=approved)
    expected='information_normative_authority_required' if os.name=='nt' else 'information_normative_changed'
    assert assess_information_use(bound,target,now=dt.datetime.now(dt.timezone.utc))['requirements'][0]['blockers']==[expected]
