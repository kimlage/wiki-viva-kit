import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path
import pytest
import yaml
from jsonschema import validate
from wiki_core.context_policy import load_policy
from wiki_core.context_packet import build_packet
from wiki_core.context_impact import assess_impact, report_review, ImpactError
from wiki_core.context_integration import preflight, IntegrationError

BASE=Path(__file__).resolve().parents[1]
def git(root,*args): return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.PIPE).decode().strip()
def approve(root): git(root,'update-ref','refs/remotes/origin/main',git(root,'rev-parse','HEAD'))
def manifest(id,parent,root,policy,imports=None,exports=None,instructions=None):
    return {'schema_version':'wiki.context/v1','id':id,'parent':parent,'root':root,'purpose':'synthetic','owner':'operator','instructions':instructions or [],'skills':[],'templates':[],'policy':policy,'imports':imports or [],'exports':exports or []}
def save(root,path,obj):
    p=root/path; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(yaml.safe_dump(obj))
@pytest.fixture
def repo(tmp_path):
    git(tmp_path,'init','-q'); git(tmp_path,'config','user.email','test@example.invalid'); git(tmp_path,'config','user.name','Synthetic')
    grant={'from_context':'tax','to_context':'costs','selector':'finance/tax/source.md','section':'amount','use':'interpret','classification':'synthetic','expires':'2099-01-01'}
    save(tmp_path,'context.yaml',manifest('root',None,'.',{'read':['self'],'write':['self'],'capabilities':[],'deny':{},'publication':[]},instructions=['rules.md']))
    save(tmp_path,'finance/context.yaml',manifest('finance','root','finance',{}))
    save(tmp_path,'finance/tax/context.yaml',manifest('tax','finance','finance/tax',{'read':['self'],'write':['self']},exports=[grant]))
    save(tmp_path,'finance/costs/context.yaml',manifest('costs','finance','finance/costs',{'read':['self','finance/tax/source.md'],'write':['self']},imports=[grant]))
    (tmp_path/'rules.md').write_text('Approved rule\n')
    (tmp_path/'finance/tax/interpretation.md').write_text('Independent tax interpretation\n')
    (tmp_path/'finance/tax/source.md').write_text('---\ntitle: First\n---\n<!-- wiki:section id=amount version=1 -->\n## Amount\nOne\n')
    (tmp_path/'finance/costs/result.md').write_text('Independent cost assessment\n')
    (tmp_path/'finance/costs/other.md').write_text('Another independent assessment\n')
    git(tmp_path,'add','.'); git(tmp_path,'commit','-qm','base'); approve(tmp_path)
    return tmp_path

def graph(consumed=None):
    return {'edges':[{'type':'source_ref','source':'finance/costs/result.md','target':'finance/tax/source.md','consumed_fields':['section:amount'],'classification':'synthetic','use':'interpret','owner_context':'costs','producer_context':'tax', **({'consumed_revision':consumed} if consumed else {})}]}
def policy(repo): return load_policy(repo,'refs/remotes/origin/main')
def update(repo,text):
    (repo/'finance/tax/source.md').write_text(text); git(repo,'add','.'); git(repo,'commit','-qm','source change'); approve(repo); return git(repo,'rev-parse','HEAD')

def test_impact_selected_slice_independent_and_heading(repo):
    before=git(repo,'rev-parse','HEAD')
    after=update(repo,'---\ntitle: Renamed\n---\n<!-- wiki:section id=amount version=1 -->\n## Renamed\nOne\n')
    assert assess_impact(repo,policy(repo),graph(before),before=before,after=after,destination_context='costs')['candidates']==[]
    newer=update(repo,'---\ntitle: Renamed\n---\n<!-- wiki:section id=amount version=1 -->\n## Renamed\nTwo\n')
    out=assess_impact(repo,policy(repo),graph(after),before=after,after=newer,destination_context='costs')
    assert len(out['candidates'])==1
    c=out['candidates'][0]; assert c['selector']=='section:amount' and c['state']=='review_pending' and c['interpretation']=='independent' and c['fact_freshness']=='not_assessed'
    assert c['before_digest']!=c['after_digest']
    assert out['propagation']=='one_hop_only'
    validate(out,json.loads((BASE/'docs/references/schemas/wiki-context-impact-v1.schema.json').read_text()))

def test_unauthorized_connection_redaction_fanout_cycle_and_bad_owner(repo):
    before=git(repo,'rev-parse','HEAD'); after=update(repo,'<!-- wiki:section id=amount version=1 -->\n## Amount\nTwo\n')
    g=graph(before); g['edges'].append(copy.deepcopy(g['edges'][0]))
    out=assess_impact(repo,policy(repo),g,before=before,after=after,destination_context='costs')
    assert len(out['candidates'])==1
    event=out['candidates'][0]['event_id']
    assert assess_impact(repo,policy(repo),g,before=before,after=after,destination_context='costs',trace=[event])['candidates'][0]['state']=='blocked_cycle_limit'
    assert assess_impact(repo,policy(repo),g,before=before,after=after,destination_context='costs',trace=['f'*64],max_generation=1)['candidates'][0]['state']=='blocked_cycle_limit'
    bad=graph(before); bad['edges'][0]['producer_context']='costs'
    with pytest.raises(ImpactError,match='owner'): assess_impact(repo,policy(repo),bad,before=before,after=after,destination_context='costs')
    # The policy revision revokes import. Nothing about the blocked source escapes.
    p=repo/'finance/costs/context.yaml'; d=yaml.safe_load(p.read_text()); d['imports']=[]; p.write_text(yaml.safe_dump(d)); git(repo,'add','.'); git(repo,'commit','-qm','revoke'); approve(repo)
    hidden=assess_impact(repo,policy(repo),g,before=before,after=after,destination_context='costs')
    assert not hidden['candidates'] and 'finance/tax/source.md' not in json.dumps(hidden)

def test_fanout_pagination_bound_to_selection(repo):
    before=git(repo,'rev-parse','HEAD'); after=update(repo,'<!-- wiki:section id=amount version=1 -->\n## Amount\nTwo\n')
    g=graph(before); g['edges'].append({**g['edges'][0], 'source':'finance/costs/other.md'})
    out=assess_impact(repo,policy(repo),g,before=before,after=after,destination_context='costs',max_fanout=1)
    assert out['authorized_remaining']==1 and out['next_offset']==1
    page=assess_impact(repo,policy(repo),g,before=before,after=after,destination_context='costs',max_fanout=1,offset=1,expected_selection=out['selection_digest'])
    assert page['authorized_remaining']==0 and page['candidates'][0]['target']!=out['candidates'][0]['target']
    with pytest.raises(ImpactError,match='continuation'): assess_impact(repo,policy(repo),graph(before),before=before,after=after,destination_context='costs',offset=1,expected_selection=out['selection_digest'])

def make_proposal(repo):
    base=git(repo,'rev-parse','HEAD'); p=policy(repo)
    evidence=[{'ref':'finance/tax/source.md','producer':'tax','reason':'selected evidence','use':'interpret','classification':'synthetic','section':'amount'}]
    packet=build_packet(repo,p,'costs',base,evidence,10000,task_id='task-1',goal='assess costs',output='proposal',integrator='independent reviewer')
    git(repo,'checkout','-qb','wiki/costs-task-1')
    (repo/'finance/costs/result.md').write_text('Updated independent cost assessment\n'); git(repo,'add','.'); git(repo,'commit','-qm','cost proposal'); head=git(repo,'rev-parse','HEAD')
    result={'schema_version':'wiki.task-result/v1','status':'completed','task_id':'task-1','context_id':'costs','packet_digest':packet['packet_digest'],'changes':[{'path':'finance/costs/result.md','action':'modified'}],'read_coverage':{'observed_refs':packet['declared_read_set'],'missing':[]},'blockers':[]}
    return p,base,head,packet,result

def test_preflight_real_branch_exact_base_and_read_set(repo):
    p,base,head,packet,result=make_proposal(repo)
    out=preflight(repo,p,context_id='costs',base=base,head=head,branch='wiki/costs-task-1',packet=packet,result=result)
    assert out['state']=='independent_review_required' and out['review']=='not_performed' and out['merge']=='not_performed'
    validate(out,json.loads((BASE/'docs/references/schemas/wiki-context-integration-v1.schema.json').read_text()))
    with pytest.raises(IntegrationError): preflight(repo,p,context_id='costs',base=base,head=head,branch='wiki/costs-task-1',packet=packet,result={**result,'changes':[]})
    with pytest.raises(IntegrationError): preflight(repo,p,context_id='costs',base=base,head=base,branch='wiki/costs-task-1',packet=packet,result=result)
    # Approval revocation/advancement invalidates the old policy object.
    git(repo,'update-ref','refs/remotes/origin/main',head)
    with pytest.raises(ValueError): preflight(repo,p,context_id='costs',base=base,head=head,branch='wiki/costs-task-1',packet=packet,result=result)

def test_preflight_rejects_out_of_scope_and_policy_changes(repo):
    p,base,head,packet,result=make_proposal(repo)
    (repo/'finance/tax/source.md').write_text('Unauthorized edit\n'); git(repo,'add','.'); git(repo,'commit','-qm','outside scope'); head=git(repo,'rev-parse','HEAD')
    result['changes'].append({'path':'finance/tax/source.md','action':'modified'})
    with pytest.raises(IntegrationError,match='outside context'): preflight(repo,p,context_id='costs',base=base,head=head,branch='wiki/costs-task-1',packet=packet,result=result)

def test_actual_consumed_revision_unpinned_and_missing_section(repo):
    consumed=git(repo,'rev-parse','HEAD')
    middle=update(repo,'<!-- wiki:section id=amount version=1 -->\n## Amount\nTwo\n')
    # Comparing only middle -> middle would miss the stale consumer. Its pinned
    # input revision is authoritative for the selected bytes.
    out=assess_impact(repo,policy(repo),graph(consumed),before=middle,after=middle,destination_context='costs')
    assert out['candidates'][0]['before_revision']==consumed
    assert out['candidates'][0]['state']=='review_pending'
    unpinned=assess_impact(repo,policy(repo),graph(),before=middle,after=middle,destination_context='costs')
    assert unpinned['candidates'][0]['state']=='blocked_unpinned_dependency'
    missing=update(repo,'# Source without selected section\n')
    out=assess_impact(repo,policy(repo),graph(consumed),before=middle,after=missing,destination_context='costs')
    assert out['candidates'][0]['after_digest'] is None
    bad=graph(consumed); bad['edges'][0]['consumed_revision']='HEAD'
    with pytest.raises(ImpactError,match='consumed revision'): assess_impact(repo,policy(repo),bad,before=middle,after=missing,destination_context='costs')
    with pytest.raises(ImpactError,match='malformed'): assess_impact(repo,policy(repo),{'edges':[{}]},before=middle,after=missing,destination_context='costs')


def test_reported_review_requires_current_evidence_and_changed_output(repo):
    before=git(repo,'rev-parse','HEAD'); after=update(repo,'<!-- wiki:section id=amount version=1 -->\n## Amount\nTwo\n')
    candidate=assess_impact(repo,policy(repo),graph(before),before=before,after=after,destination_context='costs')['candidates'][0]
    unchanged=report_review(repo,policy(repo),candidate,disposition='still_valid',reason='reviewed against synthetic evidence',evidence_revision=after)
    assert unchanged['verification']=='reported_not_verified' and unchanged['next_impact_allowed'] is False
    validate(unchanged,json.loads((BASE/'docs/references/schemas/wiki-context-review-v1.schema.json').read_text()))
    with pytest.raises(ImpactError,match='no approved change'): report_review(repo,policy(repo),candidate,disposition='updated',reason='reviewed',evidence_revision=after)
    (repo/'finance/costs/result.md').write_text('Updated independent interpretation\n'); git(repo,'add','.'); git(repo,'commit','-qm','approved interpretation'); approve(repo); approved=git(repo,'rev-parse','HEAD')
    result=report_review(repo,policy(repo),candidate,disposition='updated',reason='independent interpretation changed',evidence_revision=approved)
    assert result['next_impact_allowed'] and result['output_before_digest']!=result['output_after_digest']
    update(repo,'<!-- wiki:section id=amount version=1 -->\n## Amount\nThree\n')
    with pytest.raises(ImpactError,match='source changed'): report_review(repo,policy(repo),candidate,disposition='still_valid',reason='stale review',evidence_revision='HEAD')


def test_cli_impact_is_finite_and_revision_bound(repo,tmp_path):
    before=git(repo,'rev-parse','HEAD'); after=update(repo,'<!-- wiki:section id=amount version=1 -->\n## Amount\nTwo\n')
    file=tmp_path/'inventory.json'; file.write_text(json.dumps(graph(before)))
    cmd=[sys.executable,str(BASE/'scripts/wiki_context_flow.py'),'--mode','v1','--repo',str(repo),'--approved-revision',after,'impact','--graph',str(file),'--before',before,'--after',after,'--context','costs','--limit','1']
    out=json.loads(subprocess.check_output(cmd))
    assert out['policy_revision']==after and len(out['candidates'])==1


def test_independent_interpretations_and_no_blind_transitive_cascade(repo):
    before=git(repo,'rev-parse','HEAD'); after=update(repo,'<!-- wiki:section id=amount version=1 -->\n## Amount\nTwo\n')
    inventory=graph(before)
    inventory['edges'] += [
        {'type':'source_ref','source':'finance/tax/interpretation.md','target':'finance/tax/source.md','consumed_fields':['section:amount'],'consumed_revision':before,'use':'interpret','classification':'synthetic'},
        {'type':'source_ref','source':'finance/costs/other.md','target':'finance/costs/result.md','consumed_fields':['*'],'consumed_revision':before,'use':'interpret','classification':'synthetic'},
    ]
    tax=assess_impact(repo,policy(repo),inventory,before=before,after=after,destination_context='tax')
    costs=assess_impact(repo,policy(repo),inventory,before=before,after=after,destination_context='costs')
    assert [x['target'] for x in tax['candidates']]==['finance/tax/interpretation.md']
    assert [x['target'] for x in costs['candidates']]==['finance/costs/result.md']
    (repo/'finance/costs/result.md').write_text('New independent interpretation\n'); git(repo,'add','.'); git(repo,'commit','-qm','accepted cost output'); approve(repo); produced=git(repo,'rev-parse','HEAD')
    # The next edge is triggered by the produced output, not by the original
    # source change alone. The first edge remains stale until its own receipt is updated.
    next_out=assess_impact(repo,policy(repo),inventory,before=after,after=produced,destination_context='costs')
    assert 'finance/costs/other.md' in [x['target'] for x in next_out['candidates']]

def test_impact_blocks_access_secret_without_disclosure(repo):
    before=git(repo,'rev-parse','HEAD'); synthetic='AKIA'+'IOSFODNN7EXAMPLE'
    after=update(repo,'<!-- wiki:section id=amount version=1 -->\n## Amount\n'+synthetic+'\n')
    with pytest.raises(ImpactError,match='secret detected') as error:
        assess_impact(repo,policy(repo),graph(before),before=before,after=after,destination_context='costs')
    assert synthetic not in str(error.value)

def test_preflight_blocks_proposed_policy_and_symlink(repo):
    p,base,head,packet,result=make_proposal(repo)
    path=repo/'finance/costs/context.yaml'; path.write_text(path.read_text()+'\n# proposed policy change\n'); git(repo,'add','.'); git(repo,'commit','-qm','policy proposal')
    result['changes'].append({'path':'finance/costs/context.yaml','action':'modified'})
    with pytest.raises(IntegrationError,match='policy change'):
        preflight(repo,p,context_id='costs',base=base,head=git(repo,'rev-parse','HEAD'),branch='wiki/costs-task-1',packet=packet,result=result)


def test_preflight_blocks_symlink(repo):
    p,base,head,packet,result=make_proposal(repo)
    link=repo/'finance/costs/alias.md'; link.symlink_to('result.md'); git(repo,'add','.'); git(repo,'commit','-qm','symlink proposal')
    result['changes'].append({'path':'finance/costs/alias.md','action':'created'})
    with pytest.raises(IntegrationError,match='unsafe proposed file'):
        preflight(repo,p,context_id='costs',base=base,head=git(repo,'rev-parse','HEAD'),branch='wiki/costs-task-1',packet=packet,result=result)

def test_finance_parent_read_ceiling_is_not_a_child_connection(repo):
    p=policy(repo); source='finance/tax/source.md'
    assert p.permits('finance','read',source)
    assert p.connection('tax','finance',source,'interpret','synthetic',section='amount')=='pending'
    evidence=[{'ref':source,'producer':'tax','reason':'selected evidence','use':'interpret','classification':'synthetic','section':'amount'}]
    with pytest.raises(ValueError,match='connection pending'):
        build_packet(repo,p,'finance','HEAD',evidence,10000,task_id='parent-read',goal='interpret',output='proposal',integrator='reviewer')


def test_finance_parent_write_ceiling_does_not_authorize_child_edit(repo):
    base=git(repo,'rev-parse','HEAD'); p=policy(repo)
    assert p.permits('finance','write','finance/tax/source.md')
    packet=build_packet(repo,p,'finance',base,[],10000,task_id='parent-write',goal='propose',output='report',integrator='reviewer')
    git(repo,'checkout','-qb','wiki/finance-task')
    (repo/'finance/tax/source.md').write_text('unauthorized edit\n'); git(repo,'add','.'); git(repo,'commit','-qm','child edit'); head=git(repo,'rev-parse','HEAD')
    result={'schema_version':'wiki.task-result/v1','status':'completed','task_id':'parent-write','context_id':'finance','packet_digest':packet['packet_digest'],'changes':[{'path':'finance/tax/source.md','action':'modified'}],'read_coverage':{'observed_refs':packet['declared_read_set'],'missing':[]},'blockers':[]}
    with pytest.raises(IntegrationError,match='write outside context'):
        preflight(repo,p,context_id='finance',base=base,head=head,branch='wiki/finance-task',packet=packet,result=result)

@pytest.mark.parametrize('normative_path',['rules.md','finance/costs/rule.md','finance/costs/template.md'])
def test_preflight_rejects_active_ancestor_local_rule_and_template(repo,normative_path):
    manifest_path=repo/'finance/costs/context.yaml'; manifest_data=yaml.safe_load(manifest_path.read_text())
    manifest_data['instructions']=['finance/costs/rule.md']; manifest_data['templates']=['finance/costs/template.md']; manifest_path.write_text(yaml.safe_dump(manifest_data))
    (repo/'finance/costs/rule.md').write_text('Mandatory context rule\n'); (repo/'finance/costs/template.md').write_text('Mandatory template\n')
    git(repo,'add','.'); git(repo,'commit','-qm','approved normative files'); approve(repo)
    base=git(repo,'rev-parse','HEAD'); p=policy(repo)
    packet=build_packet(repo,p,'costs',base,[],10000,task_id='normative-test',goal='content proposal',output='report',integrator='reviewer')
    git(repo,'checkout','-qb','wiki/normative-test'); (repo/normative_path).write_text('proposed normative change\n'); git(repo,'add','.'); git(repo,'commit','-qm','attempt normative change'); head=git(repo,'rev-parse','HEAD')
    result={'schema_version':'wiki.task-result/v1','status':'completed','task_id':packet['task_id'],'context_id':'costs','packet_digest':packet['packet_digest'],'changes':[{'path':normative_path,'action':'modified'}],'read_coverage':{'observed_refs':packet['declared_read_set'],'missing':[]},'blockers':[]}
    with pytest.raises(IntegrationError,match='normative input requires separate policy review'):
        preflight(repo,p,context_id='costs',base=base,head=head,branch='wiki/normative-test',packet=packet,result=result)

def test_markdown_requirement_flows_through_real_inventory_and_authorized_reader(repo):
    from wiki_core.config import load_config
    from wiki_core.information_relations import authored_graph, dependency_edges
    from wiki_core.context_requirements import assess_approved_impact, requirements_from_result
    consumed=git(repo,'rev-parse','HEAD')
    requirement={'target':'finance/tax/source.md','fields':['section:amount'],'temporal':'current','max_age_days':30,'consumed_revision':consumed,'use':'interpret','classification':'synthetic'}
    values={'page_id':'cost-interpretation','page_type':'claim','information_requirements':[requirement]}
    (repo/'finance/costs/result.md').write_text('---\n'+yaml.safe_dump(values)+'---\nIndependent cost assessment\n')
    (repo/'wiki.config.yaml').write_text('paths:\n  memory_root: finance\n')
    git(repo,'add','.'); git(repo,'commit','-qm','canonical requirement'); approve(repo)
    before=git(repo,'rev-parse','HEAD'); after=update(repo,'<!-- wiki:section id=amount version=1 -->\n## Amount\nTwo\n')
    graph_real=authored_graph(repo,load_config(repo)); deps,_=dependency_edges(graph_real)
    edge=next(e for e in deps if e.get('field')=='information_requirements')
    assert edge['consumed_revision']==consumed and edge['consumed_fields']==['section:amount']
    out=assess_impact(repo,policy(repo),graph_real,before=before,after=after,destination_context='costs')
    assert any(c['target']=='finance/costs/result.md' and c['state']=='review_pending' for c in out['candidates'])
    narrowed=assess_approved_impact(repo,policy(repo),consumers=['finance/costs/result.md'],before=before,after=after,destination_context='costs')
    assert [c['target'] for c in narrowed['candidates']]==['finance/costs/result.md']
    cmd=[sys.executable,str(BASE/'scripts/wiki_context_flow.py'),'--mode','v1','--repo',str(repo),'--approved-revision',after,'impact','--consumer','finance/costs/result.md','--before',before,'--after',after,'--context','costs']
    assert json.loads(subprocess.check_output(cmd))['candidates']==narrowed['candidates']

def test_requirements_derived_only_from_reported_verified_approved_output(repo):
    from wiki_core.context_requirements import requirements_from_result, RequirementError
    approved_branch=git(repo,'branch','--show-current'); p,base,head,packet,result=make_proposal(repo)
    args={'packet':packet,'result':result,'output_path':'finance/costs/result.md','proposal_head':head,'temporal':'current','max_age_days':30}
    with pytest.raises(RequirementError,match='not incorporated'): requirements_from_result(repo,p,**args)
    git(repo,'checkout','-q',approved_branch); git(repo,'merge','--no-ff','--no-edit','wiki/costs-task-1'); approve(repo)
    current=policy(repo); out=requirements_from_result(repo,current,**args)
    assert out['write']=='not_performed' and out['read_claim']=='reported_not_verified'
    validate(out,json.loads((BASE/'docs/references/schemas/wiki-context-requirements-v1.schema.json').read_text()))
    assert out['information_requirements']==[{'target':'finance/tax/source.md','fields':['section:amount'],'temporal':'current','max_age_days':30,'consumed_revision':base,'use':'interpret','classification':'synthetic'}]
    packet_path=repo/'packet.json'; result_path=repo/'result.json'; packet_path.write_text(json.dumps(packet)); result_path.write_text(json.dumps(result))
    cmd=[sys.executable,str(BASE/'scripts/wiki_context_flow.py'),'--mode','v1','--repo',str(repo),'--approved-revision',current.policy_revision,'requirements','--packet',str(packet_path),'--result',str(result_path),'--output','finance/costs/result.md','--proposal-head',head,'--temporal','current','--max-age-days','30']
    assert json.loads(subprocess.check_output(cmd))==out
    missing={**result,'read_coverage':{'observed_refs':[],'missing':[]}}
    with pytest.raises(RequirementError,match='not reported read'): requirements_from_result(repo,current,**{**args,'result':missing})
    forged=copy.deepcopy(packet); forged['content_revision']='HEAD'; forged['inputs'][-1]['revision']='HEAD'; forged['declared_read_set'][-1]['revision']='HEAD'
    forged['packet_digest']='0'*64
    while True:
        length=len(json.dumps(forged,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
        if forged['bytes_used']==length: break
        forged['bytes_used']=length
    forged['packet_digest']=hashlib.sha256(json.dumps({k:v for k,v in forged.items() if k!='packet_digest'},ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    forged_result={**result,'packet_digest':forged['packet_digest'],'read_coverage':{'observed_refs':forged['declared_read_set'],'missing':[]}}
    with pytest.raises(RequirementError,match='invalid packet contract'): requirements_from_result(repo,current,**{**args,'packet':forged,'result':forged_result})
    (repo/'finance/tax/source.md').write_text('<!-- wiki:section id=amount version=1 -->\n## Amount\nChanged\n'); git(repo,'add','.'); git(repo,'commit','-qm','subsequent source change'); approve(repo)
    with pytest.raises(RequirementError,match='reported input changed'): requirements_from_result(repo,policy(repo),**args)

def test_packet_delivers_distinct_context_purpose_rules_and_sanitized_limits(repo):
    tax_file=repo/'finance/tax/context.yaml'; costs_file=repo/'finance/costs/context.yaml'
    tax=yaml.safe_load(tax_file.read_text()); costs=yaml.safe_load(costs_file.read_text())
    tax['purpose']='Independent fiscal interpretation'; costs['purpose']='Independent cost interpretation'
    tax['instructions']=['finance/tax/rules.md']; costs['instructions']=['finance/costs/rules.md']
    costs['imports'].append({'from_context':'tax','to_context':'costs','selector':'finance/tax/protected-metadata.md','section':'amount','use':'interpret','classification':'synthetic','expires':'2099-01-01'})
    tax_file.write_text(yaml.safe_dump(tax)); costs_file.write_text(yaml.safe_dump(costs))
    (repo/'finance/tax/rules.md').write_text('Fiscal-specific synthetic rule.\n'); (repo/'finance/costs/rules.md').write_text('Cost-specific synthetic rule.\n')
    git(repo,'add','.'); git(repo,'commit','-qm','distinct approved rules'); approve(repo); current=git(repo,'rev-parse','HEAD'); p=policy(repo)
    evidence=[{'ref':'finance/tax/source.md','producer':'tax','reason':'shared source','use':'interpret','classification':'synthetic','section':'amount'}]
    packets={c:build_packet(repo,p,c,current,evidence,20000,task_id='view-'+c,goal='interpret',output='report',integrator='reviewer') for c in ('tax','costs')}
    assert packets['tax']['context']['purpose']=='Independent fiscal interpretation'
    assert packets['costs']['context']['purpose']=='Independent cost interpretation'
    assert packets['costs']['context']['owner']=='operator' and packets['costs']['context']['lineage']==['root','finance','costs']
    assert packets['costs']['context']['owned_scopes']['write']==['finance/costs']
    assert any('Fiscal-specific' in x['text'] for x in packets['tax']['inputs'])
    assert any('Cost-specific' in x['text'] for x in packets['costs']['inputs'])
    assert 'protected-metadata.md' not in json.dumps(packets['costs'])
    assert packets['costs']['context']['approved_imports'][0]['selector']=='finance/tax/source.md'
    validate(packets['costs'],json.loads((BASE/'docs/references/schemas/wiki-task-context-v1.schema.json').read_text()))

def test_parent_context_view_does_not_disclose_child_denied_metadata(repo):
    path=repo/'context.yaml'; root=yaml.safe_load(path.read_text())
    root['policy']['deny']={'read':['finance/tax/protected-metadata.md'],'capabilities':['sensitive.effect']}
    path.write_text(yaml.safe_dump(root)); git(repo,'add','.'); git(repo,'commit','-qm','deny protected synthetic metadata'); approve(repo)
    packet=build_packet(repo,policy(repo),'root','HEAD',[],20000,task_id='root-view',goal='synthetic',output='report',integrator='reviewer')
    assert 'protected-metadata.md' not in json.dumps(packet['context'])
    assert 'sensitive.effect' not in json.dumps(packet['context'])

def test_preflight_binds_new_canonical_requirement_to_packet_bytes(repo):
    p,base,head,packet,result=make_proposal(repo)
    req={'target':'finance/tax/source.md','fields':['section:amount'],'temporal':'current','max_age_days':30,'consumed_revision':base,'use':'interpret','classification':'synthetic'}
    target=repo/'finance/costs/result.md'; target.write_text('---\n'+yaml.safe_dump({'information_requirements':[req]})+'---\nIndependent interpretation\n')
    git(repo,'add','.'); git(repo,'commit','-qm','record consumed evidence'); head=git(repo,'rev-parse','HEAD')
    assert preflight(repo,p,context_id='costs',base=base,head=head,branch='wiki/costs-task-1',packet=packet,result=result)['state']=='independent_review_required'
    unreported={**result,'read_coverage':{'observed_refs':[],'missing':[]}}
    with pytest.raises(IntegrationError,match='does not match task evidence'):
        preflight(repo,p,context_id='costs',base=base,head=head,branch='wiki/costs-task-1',packet=packet,result=unreported)
    req['consumed_revision']='0'*40; target.write_text('---\n'+yaml.safe_dump({'information_requirements':[req]})+'---\nIndependent interpretation\n')
    git(repo,'add','.'); git(repo,'commit','-qm','forged consumed revision'); head=git(repo,'rev-parse','HEAD')
    with pytest.raises(IntegrationError,match='does not match task evidence'):
        preflight(repo,p,context_id='costs',base=base,head=head,branch='wiki/costs-task-1',packet=packet,result=result)

def test_requirements_allow_historical_self_output_read_without_self_dependency(repo):
    from wiki_core.context_requirements import requirements_from_result
    approved_branch=git(repo,'branch','--show-current'); base=git(repo,'rev-parse','HEAD'); p=policy(repo)
    evidence=[{'ref':'finance/tax/source.md','producer':'tax','reason':'source','use':'interpret','classification':'synthetic','section':'amount'}, {'ref':'finance/costs/result.md','producer':'costs','reason':'existing approved output','use':'interpret','classification':'synthetic'}]
    packet=build_packet(repo,p,'costs',base,evidence,20000,task_id='self-read',goal='edit output',output='finance/costs/result.md',integrator='reviewer')
    git(repo,'checkout','-qb','wiki/self-read'); (repo/'finance/costs/result.md').write_text('Changed output\n'); git(repo,'add','.'); git(repo,'commit','-qm','update output'); head=git(repo,'rev-parse','HEAD')
    result={'schema_version':'wiki.task-result/v1','status':'completed','task_id':packet['task_id'],'context_id':'costs','packet_digest':packet['packet_digest'],'changes':[{'path':'finance/costs/result.md','action':'modified'}],'read_coverage':{'observed_refs':packet['declared_read_set'],'missing':[]},'blockers':[]}
    preflight(repo,p,context_id='costs',base=base,head=head,branch='wiki/self-read',packet=packet,result=result)
    git(repo,'checkout','-q',approved_branch); git(repo,'merge','--no-ff','--no-edit','wiki/self-read'); approve(repo)
    out=requirements_from_result(repo,policy(repo),packet=packet,result=result,output_path='finance/costs/result.md',proposal_head=head,temporal='current',max_age_days=30)
    assert out['self_input_read'] is True and [x['target'] for x in out['information_requirements']]==['finance/tax/source.md']

def _reforge_packet(packet, result, *, sync_selected=True):
    if sync_selected: packet['selected_text_bytes']=sum(x['byte_length'] for x in packet['inputs'])
    packet['declared_read_set']=[{k:x[k] for k in ('ref','section','field','revision')} for x in packet['inputs']]
    packet['packet_digest']='0'*64
    while True:
        n=len(json.dumps(packet,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8'))
        if packet['bytes_used']==n: break
        packet['bytes_used']=n
    packet['packet_digest']=hashlib.sha256(json.dumps({k:v for k,v in packet.items() if k!='packet_digest'},ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    result['packet_digest']=packet['packet_digest']; result['task_id']=packet['task_id']
    result['read_coverage']['observed_refs']=copy.deepcopy(packet['declared_read_set'])


def test_requirements_rejects_forged_text_and_sliced_mandatory_with_recomputed_digest(repo):
    from wiki_core.context_requirements import requirements_from_result, RequirementError
    from wiki_core.repository_reader import RepositoryReader
    (repo/'rules.md').write_text('<!-- wiki:section id=policy version=1 -->\n## Rule\nApproved rule\n')
    git(repo,'add','.'); git(repo,'commit','-qm','approved selectable rule'); approve(repo)
    approved_branch=git(repo,'branch','--show-current'); p,base,head,packet,result=make_proposal(repo)
    git(repo,'checkout','-q',approved_branch); git(repo,'merge','--no-ff','--no-edit','wiki/costs-task-1'); approve(repo)
    current=policy(repo); kwargs={'output_path':'finance/costs/result.md','proposal_head':head,'temporal':'current','max_age_days':30}
    fake=copy.deepcopy(packet); result_fake=copy.deepcopy(result)
    fake['inputs'][-1]['text']='forged selected evidence'; fake['inputs'][-1]['byte_length']=len(fake['inputs'][-1]['text'].encode())
    _reforge_packet(fake,result_fake)
    with pytest.raises(RequirementError,match='reported input bytes differ'):
        requirements_from_result(repo,current,packet=fake,result=result_fake,**kwargs)
    fake=copy.deepcopy(packet); result_fake=copy.deepcopy(result); fake['inputs'][-1]['byte_length']+=1; _reforge_packet(fake,result_fake)
    with pytest.raises(RequirementError,match='reported input bytes differ'):
        requirements_from_result(repo,current,packet=fake,result=result_fake,**kwargs)
    fake=copy.deepcopy(packet); result_fake=copy.deepcopy(result); fake['selected_text_bytes']+=1; _reforge_packet(fake,result_fake,sync_selected=False)
    with pytest.raises(RequirementError,match='invalid selected text accounting'):
        requirements_from_result(repo,current,packet=fake,result=result_fake,**kwargs)
    fake=copy.deepcopy(packet); result_fake=copy.deepcopy(result); fake['inputs'].reverse(); _reforge_packet(fake,result_fake)
    with pytest.raises(RequirementError,match='mandatory policy inputs changed'):
        requirements_from_result(repo,current,packet=fake,result=result_fake,**kwargs)
    fake=copy.deepcopy(packet); result_fake=copy.deepcopy(result); fake['inputs'][0]['producer']='costs'; _reforge_packet(fake,result_fake)
    with pytest.raises(RequirementError,match='mandatory policy inputs changed'):
        requirements_from_result(repo,current,packet=fake,result=result_fake,**kwargs)
    fake=copy.deepcopy(packet); result_fake=copy.deepcopy(result)
    section=RepositoryReader(repo,base).read('rules.md',section='policy'); item=fake['inputs'][0]
    item.update(section='policy',text=section['text'],byte_length=len(section['text'].encode()),sha256=section['content_digest'])
    _reforge_packet(fake,result_fake)
    with pytest.raises(RequirementError,match='mandatory policy input must be complete'):
        requirements_from_result(repo,current,packet=fake,result=result_fake,**kwargs)
    fake=copy.deepcopy(packet); result_fake=copy.deepcopy(result); fake['inputs'][0]['reason']='forged reason'; _reforge_packet(fake,result_fake)
    with pytest.raises(RequirementError,match='mandatory policy inputs changed'):
        requirements_from_result(repo,current,packet=fake,result=result_fake,**kwargs)


def test_requirements_block_secret_in_packet_or_result_metadata(repo):
    from wiki_core.context_requirements import requirements_from_result, RequirementError
    approved_branch=git(repo,'branch','--show-current'); p,base,head,packet,result=make_proposal(repo)
    git(repo,'checkout','-q',approved_branch); git(repo,'merge','--no-ff','--no-edit','wiki/costs-task-1'); approve(repo)
    current=policy(repo); kwargs={'output_path':'finance/costs/result.md','proposal_head':head,'temporal':'current','max_age_days':30}; secret='AKIA'+'IOSFODNN7EXAMPLE'
    fake=copy.deepcopy(packet); result_fake=copy.deepcopy(result); fake['task_id']=secret; _reforge_packet(fake,result_fake)
    with pytest.raises(RequirementError,match='secret detected') as exc:
        requirements_from_result(repo,current,packet=fake,result=result_fake,**kwargs)
    assert secret not in str(exc.value)
    result_fake=copy.deepcopy(result); result_fake['read_coverage']['missing']=[secret]
    with pytest.raises(RequirementError,match='secret detected') as exc:
        requirements_from_result(repo,current,packet=packet,result=result_fake,**kwargs)
    assert secret not in str(exc.value)

@pytest.mark.parametrize(('context','output'), [('tax','finance/tax/interpretation.md'), ('costs','finance/costs/result.md')])
def test_inherited_normative_requirement_flow(repo, context, output):
    from wiki_core.context_requirements import assess_approved_impact, requirements_from_result
    (repo/'rules.md').write_text('---\ntitle: Original\n---\nApproved rule\n')
    git(repo,'add','.'); git(repo,'commit','-qm','normative metadata'); approve(repo)
    base=git(repo,'rev-parse','HEAD'); p=policy(repo)
    base_branch=git(repo,'branch','--show-current')
    packet=build_packet(repo,p,context,base,[],20000,task_id='norm',goal='interpret rule',output=output,integrator='reviewer')
    req={'target':'rules.md','fields':['*'],'temporal':'current','max_age_days':30,'consumed_revision':base,'use':'normative','source_kind':'mandatory','classification':'internal'}
    branch='wiki/norm-'+context; git(repo,'checkout','-qb',branch)
    (repo/output).write_text('---\n'+yaml.safe_dump({'information_requirements':[req]})+'---\nIndependent interpretation\n')
    git(repo,'add','.'); git(repo,'commit','-qm','interpret approved rule'); head=git(repo,'rev-parse','HEAD')
    result={'schema_version':'wiki.task-result/v1','status':'completed','task_id':'norm','context_id':context,'packet_digest':packet['packet_digest'],'changes':[{'path':output,'action':'modified'}],'read_coverage':{'observed_refs':packet['declared_read_set'],'missing':[]},'blockers':[]}
    assert preflight(repo,p,context_id=context,base=base,head=head,branch=branch,packet=packet,result=result)['state']=='independent_review_required'
    git(repo,'checkout','-q',base_branch); git(repo,'merge','--no-ff','--no-edit',branch); approve(repo)
    derived=requirements_from_result(repo,policy(repo),packet=packet,result=result,output_path=output,proposal_head=head,temporal='current',max_age_days=30)
    assert derived['information_requirements']==[]  # explicit declaration only
    # An unrelated approved commit changes the policy SHA but not the rule:
    # retaining the historical consumption is valid, without inventing a reread.
    (repo/'unrelated.md').write_text('Unrelated\n'); git(repo,'add','.'); git(repo,'commit','-qm','unrelated'); approve(repo)
    same=git(repo,'rev-parse','HEAD'); same_packet=build_packet(repo,policy(repo),context,same,[],20000,task_id='same-rule',goal='edit',output=output,integrator='reviewer')
    git(repo,'checkout','-qb','wiki/same-'+context); (repo/output).write_text((repo/output).read_text()+'Unrelated edit\n')
    git(repo,'add','.'); git(repo,'commit','-qm','edit consumer'); same_head=git(repo,'rev-parse','HEAD')
    same_result={'schema_version':'wiki.task-result/v1','status':'completed','task_id':'same-rule','context_id':context,'packet_digest':same_packet['packet_digest'],'changes':[{'path':output,'action':'modified'}],'read_coverage':{'observed_refs':same_packet['declared_read_set'],'missing':[]},'blockers':[]}
    assert preflight(repo,policy(repo),context_id=context,base=same,head=same_head,branch='wiki/same-'+context,packet=same_packet,result=same_result)['state']=='independent_review_required'
    git(repo,'checkout','-q',base_branch)
    (repo/'rules.md').write_text('---\ntitle: Updated\n---\nApproved rule\n'); git(repo,'add','.'); git(repo,'commit','-qm','rule metadata revision'); approve(repo); current=git(repo,'rev-parse','HEAD')
    out=assess_approved_impact(repo,policy(repo),consumers=[output],before=base,after=current,destination_context=context)
    candidate=out['candidates'][0]
    validate(out,json.loads((BASE/'docs/references/schemas/wiki-context-impact-v1.schema.json').read_text()))
    assert candidate['use']=='normative' and candidate['before_revision']==base and candidate['state']=='review_pending'
    forged={**candidate}; forged.pop('source_kind')
    with pytest.raises(ImpactError,match='invalid candidate'):
        report_review(repo,policy(repo),forged,disposition='still_valid',reason='forged origin',evidence_revision=current)
    assert report_review(repo,policy(repo),candidate,disposition='still_valid',reason='Reviewed rule',evidence_revision=current)['verification']=='reported_not_verified'
    fresh=build_packet(repo,policy(repo),context,current,[],20000,task_id='stale-norm',goal='edit',output=output,integrator='reviewer')
    git(repo,'checkout','-qb','wiki/stale-'+context); (repo/output).write_text((repo/output).read_text()+'Unrelated edit\n')
    git(repo,'add','.'); git(repo,'commit','-qm','edit consumer'); newer=git(repo,'rev-parse','HEAD')
    new_result={'schema_version':'wiki.task-result/v1','status':'completed','task_id':'stale-norm','context_id':context,'packet_digest':fresh['packet_digest'],'changes':[{'path':output,'action':'modified'}],'read_coverage':{'observed_refs':fresh['declared_read_set'],'missing':[]},'blockers':[]}
    with pytest.raises(IntegrationError,match='normative requirement changed'):
        preflight(repo,policy(repo),context_id=context,base=current,head=newer,branch='wiki/stale-'+context,packet=fresh,result=new_result)


def test_normative_history_and_revocation_fail_before_source_read(repo, monkeypatch):
    from wiki_core.context_requirements import assess_approved_impact
    from wiki_core.repository_reader import RepositoryReader
    (repo/'old-data.md').write_text('Synthetic formerly ordinary data\n')
    git(repo,'add','.'); git(repo,'commit','-qm','ordinary data'); approve(repo)
    old=git(repo,'rev-parse','HEAD')
    # A newly promoted rule cannot authorize its previous data incarnation.
    d=yaml.safe_load((repo/'context.yaml').read_text()); d['instructions'].append('old-data.md')
    (repo/'old-data.md').write_text('Synthetic rule\n'); (repo/'context.yaml').write_text(yaml.safe_dump(d))
    git(repo,'add','.'); git(repo,'commit','-qm','promote instruction'); approve(repo)
    promoted=git(repo,'rev-parse','HEAD')
    req={'target':'old-data.md','fields':['*'],'temporal':'current','max_age_days':30,'consumed_revision':old,'use':'normative','source_kind':'mandatory','classification':'internal'}
    target='finance/costs/result.md'; (repo/target).write_text('---\n'+yaml.safe_dump({'information_requirements':[req]})+'---\nReport\n')
    git(repo,'add','.'); git(repo,'commit','-qm','consumer'); approve(repo); current=git(repo,'rev-parse','HEAD')
    original=RepositoryReader.read
    def spy(self, ref, *args, **kwargs):
        if ref=='old-data.md': pytest.fail('unauthorized normative body read')
        return original(self,ref,*args,**kwargs)
    monkeypatch.setattr(RepositoryReader,'read',spy)
    with pytest.raises(ImpactError,match='authorization unavailable'): assess_approved_impact(repo,policy(repo),consumers=[target],before=old,after=current,destination_context='costs')
    # A formerly valid declaration that is no longer in the lineage is blocked
    # before its formerly authorized bytes are read.
    req['consumed_revision']=promoted
    (repo/target).write_text('---\n'+yaml.safe_dump({'information_requirements':[req]})+'---\nReport\n')
    d=yaml.safe_load((repo/'context.yaml').read_text()); d['instructions'].remove('old-data.md'); (repo/'context.yaml').write_text(yaml.safe_dump(d))
    git(repo,'add','.'); git(repo,'commit','-qm','remove rule'); approve(repo); current=git(repo,'rev-parse','HEAD')
    with pytest.raises(ImpactError,match='authorization unavailable'): assess_approved_impact(repo,policy(repo),consumers=[target],before=old,after=current,destination_context='costs')
    d['instructions'].append('old-data.md'); (repo/'context.yaml').write_text(yaml.safe_dump(d))
    d=yaml.safe_load((repo/'finance/costs/context.yaml').read_text()); d['policy']['deny']={'read':['old-data.md']}; (repo/'finance/costs/context.yaml').write_text(yaml.safe_dump(d))
    git(repo,'add','.'); git(repo,'commit','-qm','deny'); approve(repo); current=git(repo,'rev-parse','HEAD')
    with pytest.raises(ImpactError,match='authorization unavailable'): assess_approved_impact(repo,policy(repo),consumers=[target],before=old,after=current,destination_context='costs')


def test_normative_label_cannot_authorize_evidence_or_slices(repo):
    from wiki_core.context_policy import PolicyError
    from wiki_core.information_relations import information_requirements
    sha=git(repo,'rev-parse','HEAD'); p=policy(repo)
    evidence=[{'ref':'finance/tax/source.md','producer':'tax','reason':'fake','use':'normative','classification':'internal'}]
    with pytest.raises(PolicyError,match='connection pending'): build_packet(repo,p,'costs',sha,evidence,20000,task_id='fake',goal='fake',output='x',integrator='reviewer')
    req={'target':'rules.md','fields':['section:part'],'temporal':'current','max_age_days':1,'consumed_revision':sha,'use':'normative','source_kind':'mandatory'}
    with pytest.raises(ValueError,match='normative requirement'): information_requirements({'information_requirements':[req]},lambda x:[x])


def test_generic_audit_reports_normative_policy_requalification(repo):
    import datetime
    from wiki_core.information_impact import evaluate_information_impact
    req={'target':'rules.md','fields':['*'],'temporal':'current','max_age_days':30,'consumed_revision':git(repo,'rev-parse','HEAD'),'use':'normative','source_kind':'mandatory','classification':'internal'}
    edge={'source':'finance/costs/result.md','target':'rules.md','type':'operational_prerequisite','field':'information_requirements','requirement':req}
    graph={'nodes':{'rules.md':{},'finance/costs/result.md':{}},'edges':[edge],'errors':[],'missing_evidence':set()}
    out=evaluate_information_impact(graph,graph,{'context.yaml'},today=datetime.date(2026,11,3))
    assert any(x['reason']=='normative_policy_requalification_required' for x in out['pending_reviews'])


def test_preflight_rejects_fake_normative_requirement(repo):
    base=git(repo,'rev-parse','HEAD'); p=policy(repo); context='costs'; output='finance/costs/result.md'
    packet=build_packet(repo,p,context,base,[],20000,task_id='fake-norm',goal='test',output=output,integrator='reviewer')
    git(repo,'checkout','-qb','wiki/fake-norm')
    req={'target':'finance/costs/other.md','fields':['*'],'temporal':'current','max_age_days':30,'consumed_revision':base,'use':'normative','source_kind':'mandatory','classification':'internal'}
    (repo/output).write_text('---\n'+yaml.safe_dump({'information_requirements':[req]})+'---\nFake rule\n')
    git(repo,'add','.'); git(repo,'commit','-qm','fake'); head=git(repo,'rev-parse','HEAD')
    result={'schema_version':'wiki.task-result/v1','status':'completed','task_id':'fake-norm','context_id':context,'packet_digest':packet['packet_digest'],'changes':[{'path':output,'action':'modified'}],'read_coverage':{'observed_refs':packet['declared_read_set'],'missing':[]},'blockers':[]}
    with pytest.raises(IntegrationError,match='does not match task evidence'):
        preflight(repo,p,context_id=context,base=base,head=head,branch='wiki/fake-norm',packet=packet,result=result)


def test_reparent_removing_normative_ancestor_blocks_before_body(repo, monkeypatch):
    from wiki_core.context_requirements import assess_approved_impact
    from wiki_core.repository_reader import RepositoryReader
    finance=yaml.safe_load((repo/'finance/context.yaml').read_text()); finance['instructions']=['finance/rule.md']
    (repo/'finance/context.yaml').write_text(yaml.safe_dump(finance)); (repo/'finance/rule.md').write_text('Financial operating rule\n')
    git(repo,'add','.'); git(repo,'commit','-qm','finance rule'); approve(repo); consumed=git(repo,'rev-parse','HEAD')
    req={'target':'finance/rule.md','fields':['*'],'temporal':'current','max_age_days':30,'consumed_revision':consumed,'use':'normative','source_kind':'mandatory','classification':'internal'}
    target='finance/costs/result.md'; (repo/target).write_text('---\n'+yaml.safe_dump({'information_requirements':[req]})+'---\nReport\n')
    costs=yaml.safe_load((repo/'finance/costs/context.yaml').read_text()); costs['parent']='root'; costs['imports']=[]
    (repo/'finance/costs/context.yaml').write_text(yaml.safe_dump(costs))
    git(repo,'rm','finance/context.yaml','finance/tax/context.yaml'); git(repo,'add','.'); git(repo,'commit','-qm','reparent'); approve(repo); current=git(repo,'rev-parse','HEAD')
    original=RepositoryReader.read
    def spy(self,ref,*args,**kwargs):
        if ref=='finance/rule.md': pytest.fail('revoked ancestor body read')
        return original(self,ref,*args,**kwargs)
    monkeypatch.setattr(RepositoryReader,'read',spy)
    with pytest.raises(ImpactError,match='authorization unavailable'):
        assess_approved_impact(repo,policy(repo),consumers=[target],before=consumed,after=current,destination_context='costs')


def test_bilateral_normative_evidence_retains_legacy_selector(repo):
    base_branch=git(repo,'branch','--show-current')
    grant={'from_context':'tax','to_context':'costs','selector':'finance/tax/source.md','section':'amount','use':'normative','classification':'synthetic','expires':'2099-01-01'}
    for path,key in [('finance/tax/context.yaml','exports'),('finance/costs/context.yaml','imports')]:
        d=yaml.safe_load((repo/path).read_text()); d[key].append(grant); (repo/path).write_text(yaml.safe_dump(d))
    git(repo,'add','.'); git(repo,'commit','-qm','approved bilateral normative evidence'); approve(repo); base=git(repo,'rev-parse','HEAD')
    evidence=[{'ref':'finance/tax/source.md','producer':'tax','reason':'rule evidence','use':'normative','classification':'synthetic','section':'amount'}]
    packet=build_packet(repo,policy(repo),'costs',base,evidence,20000,task_id='bilateral',goal='assess',output='result',integrator='reviewer')
    req={'target':'finance/tax/source.md','fields':['section:amount'],'temporal':'current','max_age_days':30,'consumed_revision':base,'use':'normative','classification':'synthetic'}
    git(repo,'checkout','-qb','wiki/bilateral'); target='finance/costs/result.md'; (repo/target).write_text('---\n'+yaml.safe_dump({'information_requirements':[req]})+'---\nReport\n')
    git(repo,'add','.'); git(repo,'commit','-qm','consume'); head=git(repo,'rev-parse','HEAD')
    result={'schema_version':'wiki.task-result/v1','status':'completed','task_id':'bilateral','context_id':'costs','packet_digest':packet['packet_digest'],'changes':[{'path':target,'action':'modified'}],'read_coverage':{'observed_refs':packet['declared_read_set'],'missing':[]},'blockers':[]}
    assert preflight(repo,policy(repo),context_id='costs',base=base,head=head,branch='wiki/bilateral',packet=packet,result=result)['state']=='independent_review_required'
    req['source_kind']='mandatory'; (repo/target).write_text('---\n'+yaml.safe_dump({'information_requirements':[req]})+'---\nReport\n')
    git(repo,'add','.'); git(repo,'commit','-qm','forge origin'); head=git(repo,'rev-parse','HEAD')
    with pytest.raises(IntegrationError,match='invalid proposed information requirement'):
        preflight(repo,policy(repo),context_id='costs',base=base,head=head,branch='wiki/bilateral',packet=packet,result=result)
    git(repo,'checkout','-q',base_branch)
    after=update(repo,'<!-- wiki:section id=amount version=1 -->\n## Amount\nChanged\n')
    g=graph(base); g['edges'][0]['use']='normative'
    candidate=assess_impact(repo,policy(repo),g,before=base,after=after,destination_context='costs')['candidates'][0]
    assert candidate['selector']=='section:amount' and 'source_kind' not in candidate
    assert report_review(repo,policy(repo),candidate,disposition='still_valid',reason='reviewed',evidence_revision=after)['verification']=='reported_not_verified'
