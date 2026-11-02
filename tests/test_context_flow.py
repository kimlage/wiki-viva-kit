import copy
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
    cmd=[sys.executable,str(BASE/'scripts/wiki_context_flow.py'),'--repo',str(repo),'--approved-revision',after,'impact','--graph',str(file),'--before',before,'--after',after,'--context','costs','--limit','1']
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
