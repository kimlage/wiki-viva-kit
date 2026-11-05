"""Owner-authorized dynamic sets through real packet/result/canonical callers."""
from copy import deepcopy
import datetime as dt
import json
from pathlib import Path
import subprocess
import sys
import pytest
import yaml
from jsonschema import validate
from tests.test_context_flow import repo, git, approve, policy, manifest, save
from wiki_core.context_packet import build_packet, validate_result
from wiki_core.context_policy import PolicyError
from wiki_core.context_integration import preflight, IntegrationError
from wiki_core.context_requirements import (requirements_from_result, assess_approved_impact,
    revalidate_approved_queries, RequirementError)
from wiki_core.context_selection import select_query, same_selection, digest
from wiki_core.repository_reader import RepositoryReader
from wiki_core.information_relations import authored_graph, dependency_edges
from wiki_core.information_use import assess_information_use
from wiki_core.config import load_config
from tests.test_coordination_protected import bound_server, folderize
from wiki_core.web.admin.sessions import ADMIN_SESSION_HEADER

BASE=Path(__file__).resolve().parents[1]
TASK={'task_id':'dynamic-task','goal':'Assess bounded collection','output':'finance/costs/result.md','integrator':'independent reviewer'}
ANCHOR='finance/costs/index.md'; SCOPE='finance/costs/items'

def page(root, name, *, status='active', amount=10, page_id=None):
    path=root/SCOPE/name; path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text('---\n'+yaml.safe_dump({'page_id':page_id or name,'page_type':'claim','status':status,'amount':amount,'updated_at':dt.date(2026,11,3)})+'---\nBody not selected.\n',encoding='utf-8')
    return path

def commit(root, message='synthetic selection change'):
    git(root,'add','.'); git(root,'commit','-qm',message); approve(root)
    return git(root,'rev-parse','HEAD')

@pytest.fixture
def collection(repo):
    (repo/ANCHOR).write_text('---\npage_id: cost-collection\npage_type: source_catalog\n---\n# Cost collection contract\n')
    page(repo,'first.md'); page(repo,'inactive.md',status='inactive')
    (repo/'wiki.config.yaml').write_text('paths:\n  memory_root: finance\n')
    commit(repo)
    return repo

def query(**overrides):
    q={'scope':SCOPE,'filters':{'status':'active'},'field':'amount','max_enumerated':20,'max_matches':10,'max_scan_bytes':100000}
    q.update(overrides)
    return {'target':ANCHOR,'query':q,'reason':'collection assessment','use':'interpret','classification':'synthetic'}

def packet(root, queries=None, revision=None, **kwargs):
    return build_packet(root,policy(root),'costs',revision or git(root,'rev-parse','HEAD'),[],50000,queries=queries or [query()],**TASK,**kwargs)

def result(p, changes=()):
    return {'schema_version':'wiki.task-result/v1','task_id':p['task_id'],'context_id':p['context_id'],'packet_digest':p['packet_digest'],
        'status':'completed','blockers':[],'changes':list(changes),
        'read_coverage':{'observed_refs':p['declared_read_set'],'observed_queries':[r['query_id'] for r in p['query_selections']],'missing':[]}}

def requirement(p):
    r=p['query_selections'][0]; e=r['request']
    return {'target':e['target'],'fields':['*'],'temporal':'current','max_age_days':30,'consumed_revision':r['revision'],
        'use':e['use'],'classification':e['classification'],'query':e['query'],'members_digest':r['members_digest'],'selected_digest':r['selected_digest'],
        'query_policy_revision':r['policy_revision'],'authority_digest':r['authority_digest'],
        **{key: r[key] for key in ('authority_format', 'entry_folder', 'entry_index') if key in r}}


AUDIT_CONTEXT = 'finance/costs'


@pytest.fixture
def audit_collection(collection):
    """The current scoped-audit contract uses physical folder authority.

    Keep ``collection`` unchanged so the independent historical v1 reader tests
    continue exercising their original receipts and explicit authority.
    """
    (collection/'AGENTS.md').write_text('# Synthetic root instructions\n')
    (collection/'finance/costs/AGENTS.md').write_text('# Synthetic cost instructions\n')
    (collection/'finance/tax/AGENTS.md').write_text('# Synthetic tax instructions\n')
    (collection/'finance/tax/index.md').write_text('# Synthetic tax index\n')
    rules = [{
        'from_context': '.', 'to_context': target, 'selector': 'AGENTS.md',
        'use': 'interpretation', 'classification': 'context', 'expires': '2099-01-01',
    } for target in (AUDIT_CONTEXT, 'finance/tax')]
    access = {
        '.': {'owner': 'root operator', 'policy': {'read': ['self'], 'write': ['self']}, 'exports': rules},
        AUDIT_CONTEXT: {'owner': 'cost operator', 'policy': {'read': ['self', 'AGENTS.md'], 'write': ['self']}, 'imports': [rules[0]]},
        'finance/tax': {'owner': 'tax operator', 'policy': {'read': ['self', 'AGENTS.md'], 'write': ['self']}, 'imports': [rules[1]]},
    }
    (collection/'wiki.config.yaml').write_text(yaml.safe_dump({'paths': {'memory_root': 'finance'}, 'context_access': access}))
    commit(collection)
    return collection


def configure_audit(root):
    config = yaml.safe_load((root/'wiki.config.yaml').read_text())
    config['paths'] = {'memory_root': 'finance'}
    config['audit'] = {'freshness_scope': 'impact', 'information_impact': 'use_scoped'}
    (root/'wiki.config.yaml').write_text(yaml.safe_dump(config))


def folder_policy(root, context=AUDIT_CONTEXT):
    from wiki_core.context_policy import load_policy
    from wiki_core.context_packet import qualify_folder_context
    p = load_policy(root, 'refs/remotes/origin/main', 'wiki.config.yaml')
    qualify_folder_context(root, p, context, context, context+'/index.md', 100000)
    return p


def folder_build_packet(root, p, context, revision, evidence, max_bytes, **kwargs):
    return build_packet(root, p, context, revision, evidence, max_bytes, entry_folder=context, **kwargs)


def folder_packet(root, queries=None, revision=None, **kwargs):
    return folder_build_packet(root, folder_policy(root), AUDIT_CONTEXT, revision or git(root,'rev-parse','HEAD'),
                               [], 50000, queries=queries or [query()], **TASK, **kwargs)


def folder_requirement(p):
    req = requirement(p)
    row = p['query_selections'][0]
    req.update(authority_format='folder', entry_folder=row['entry_folder'], entry_index=row['entry_index'])
    return req


def folder_result(p, changes=()):
    output = result(p, changes)
    output['read_coverage']['missing'] = list(p['coverage']['missing'])
    return output


def set_folder_deny(root, scope):
    config = yaml.safe_load((root/'wiki.config.yaml').read_text())
    config['context_access'][AUDIT_CONTEXT]['policy']['deny'] = {'read': [scope]} if scope else {}
    (root/'wiki.config.yaml').write_text(yaml.safe_dump(config))


def test_folder_read_set_keeps_distinct_revisions_of_query_anchor(audit_collection):
    old = git(audit_collection, 'rev-parse', 'HEAD')
    index = audit_collection/ANCHOR
    index.write_text(index.read_text()+'Changed approved index.\n')
    current = commit(audit_collection)
    selected = folder_packet(audit_collection, revision=old)
    refs = [item for item in selected['declared_read_set'] if item['ref'] == ANCHOR]
    assert {item['revision'] for item in refs} == {old, current}
    assert validate_result(folder_result(selected), selected)

def declare(root, req):
    (root/'finance/costs/result.md').write_text('---\n'+yaml.safe_dump({'page_id':'cost-result','page_type':'claim','information_requirements':[req]})+'---\nInterpretation.\n')

def test_nonempty_empty_digest_provenance_and_exact_budget(collection):
    p=packet(collection); row=p['query_selections'][0]
    validate(p,json.loads((BASE/'docs/references/schemas/wiki-task-context-v1.schema.json').read_text()))
    assert row['members']==[{'ref':SCOPE+'/first.md','page_id':'first.md'}]
    assert p['inputs'][-1]['text']=='10' and p['inputs'][-1]['field']=='amount'
    assert p['coverage']['complete'] is False and row['coverage'].startswith('complete_only_within')
    assert p['bytes_used']==len(json.dumps(p,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
    assert validate_result(result(p),p)
    empty=packet(collection,[query(filters={'status':'absent'})]); assert empty['query_selections'][0]['members']==[]
    assert validate_result(result(empty),empty)
    before=git(collection,'rev-parse','HEAD'); (collection/'finance/costs/other.md').write_text('irrelevant\n'); commit(collection)
    after=packet(collection); assert same_selection(row,after['query_selections'][0])
    assert p['query_fingerprint']!=after['query_fingerprint']  # Revision provenance, not member equivalence.
    assert same_selection(empty['query_selections'][0],packet(collection,[query(filters={'status':'absent'})])['query_selections'][0])
    tight=build_packet(collection,policy(collection),'costs',before,[],p['bytes_used'],queries=[query()],**TASK)
    with pytest.raises(PolicyError,match='complete packet exceeds'):
        build_packet(collection,policy(collection),'costs',before,[],tight['bytes_used']-1,queries=[query()],**TASK)

@pytest.mark.parametrize('change',['addition','removal','entry','exit','selected','identity','irrelevant_metadata'])
def test_semantic_members_and_values_across_commits(collection,change):
    prior=packet(collection)['query_selections'][0]
    if change=='addition': page(collection,'new.md')
    elif change=='removal': (collection/SCOPE/'first.md').unlink()
    elif change=='entry': page(collection,'inactive.md',status='active')
    elif change=='exit': page(collection,'first.md',status='inactive')
    elif change=='selected': page(collection,'first.md',amount=11)
    elif change=='identity': page(collection,'first.md',page_id='renamed-stable-identity')
    else: (collection/SCOPE/'first.md').write_text((collection/SCOPE/'first.md').read_text().replace('Body not selected.','Irrelevant body and title.'))
    commit(collection); now=packet(collection)['query_selections'][0]
    if change=='irrelevant_metadata': assert same_selection(prior,now)
    else:
        assert not same_selection(prior,now)
        assert (prior['members_digest']==now['members_digest']) == (change=='selected')
    assert prior['query_id']!=packet(collection,[query(filters={'status':'inactive'})])['query_selections'][0]['query_id']

@pytest.mark.parametrize('limit, value', [('max_enumerated',1),('max_matches',1),('max_scan_bytes',1)])
def test_no_silent_limits(collection,limit,value):
    page(collection,'second.md');commit(collection)
    with pytest.raises(PolicyError,match='limit exceeded'): packet(collection,[query(**{limit:value})])

@pytest.mark.parametrize('scope',[SCOPE+'/child',SCOPE+'/denied','../escape','finance/tax'])
def test_child_denied_and_escape_scope_refused(collection,scope):
    save(collection,SCOPE+'/child/context.yaml',manifest('nested','costs',SCOPE+'/child',{'read':['self']}))
    page(collection,'child/secret.md');page(collection,'denied/hidden.md')
    path=collection/'finance/costs/context.yaml';d=yaml.safe_load(path.read_text());d['policy']['deny']={'read':[SCOPE+'/denied']};path.write_text(yaml.safe_dump(d));commit(collection)
    with pytest.raises(ValueError): packet(collection,[query(scope=scope)])

def test_authorized_paths_before_metadata_and_no_global_snapshot(collection,monkeypatch):
    save(collection,SCOPE+'/child/context.yaml',manifest('nested','costs',SCOPE+'/child',{'read':['self']}))
    page(collection,'child/hidden.md');page(collection,'denied/hidden.md')
    child=collection/'finance/costs/context.yaml';d=yaml.safe_load(child.read_text());d['policy']['deny']={'read':[SCOPE+'/denied']};child.write_text(yaml.safe_dump(d));commit(collection)
    original=RepositoryReader._document
    def guarded(reader,path):
        assert '/child/' not in path and '/denied/' not in path and 'finance/tax' not in path
        return original(reader,path)
    monkeypatch.setattr(RepositoryReader,'_document',guarded)
    from wiki_core.web import snapshot
    monkeypatch.setattr(snapshot,'build_snapshot',lambda *a,**k: pytest.fail('global snapshot'))
    out=packet(collection)
    encoded=json.dumps(out)
    assert 'hidden.md' not in encoded and 'nested' not in encoded and out['query_selections'][0]['enumerated']==2

@pytest.mark.parametrize('bad',['secret_filter','secret_metadata','duplicate_id','duplicate_yaml','invalid_utf8','symlink','bad_anchor','yaml_alias'])
def test_untrusted_data_and_ambiguity_fail_closed(collection,bad):
    secret='AKIA'+'IOSFODNN7EXAMPLE'
    queries=[query()]
    if bad=='secret_filter': queries=[query(filters={'credential':secret})]
    elif bad=='secret_metadata': page(collection,'first.md',status=secret)
    elif bad=='duplicate_id': page(collection,'second.md',page_id='first.md')
    elif bad=='duplicate_yaml': (collection/SCOPE/'first.md').write_text('---\npage_id: a\nstatus: active\nstatus: inactive\n---\n')
    elif bad=='yaml_alias': (collection/SCOPE/'first.md').write_text('---\npage_id: first\nstatus: &s active\nalias: *s\n---\n')
    elif bad=='invalid_utf8': (collection/SCOPE/'first.md').write_bytes(b'\xff')
    elif bad=='symlink': (collection/SCOPE/'link.md').symlink_to('first.md')
    else: (collection/ANCHOR).write_text('---\npage_id: cost-collection\npage_type: claim\n---\nNot a collection\n')
    if bad != 'secret_filter': commit(collection)
    with pytest.raises(ValueError) as error: packet(collection,queries)
    assert secret not in str(error.value)


def test_canonical_cycle_preflight_merge_derive_inventory_revalidation_and_impact(audit_collection):
    root=audit_collection;base=git(root,'rev-parse','HEAD');p=folder_packet(root);r=folder_requirement(p)
    git(root,'checkout','-qb','wiki/query-task');declare(root,r);git(root,'add','.');git(root,'commit','-qm','query interpretation');head=git(root,'rev-parse','HEAD')
    done=folder_result(p,[{'path':'finance/costs/result.md','action':'modified'}])
    assert preflight(root,folder_policy(root),context_id=AUDIT_CONTEXT,base=base,head=head,branch='wiki/query-task',packet=p,result=done)['state']=='independent_review_required'
    forged=deepcopy(r);forged['query']['filters']={'status':'inactive'};declare(root,forged);git(root,'add','.');git(root,'commit','-qm','forged dependency')
    with pytest.raises(IntegrationError,match='query requirement'): preflight(root,folder_policy(root),context_id=AUDIT_CONTEXT,base=base,head=git(root,'rev-parse','HEAD'),branch='wiki/query-task',packet=p,result=done)
    git(root,'reset','--hard',head);approve(root)  # Synthetic approval/merge simulation only.
    proposed=requirements_from_result(root,folder_policy(root),packet=p,result=done,output_path='finance/costs/result.md',proposal_head=head,temporal='current',max_age_days=30)
    assert [item for item in proposed['information_requirements'] if 'query' in item]==[r]
    assert {item['target'] for item in proposed['information_requirements']} == {item['ref'] for item in p['inputs'] if 'query_id' not in item}
    validate(proposed,json.loads((BASE/'docs/references/schemas/wiki-context-requirements-v1.schema.json').read_text()))
    inventory=authored_graph(root,load_config(root));edges,_=dependency_edges(inventory)
    edge=next(e for e in edges if 'query' in e.get('requirement',{}))
    assert edge['requirement']['query']==r['query'] and edge['prerequisite']==ANCHOR
    readiness=assess_information_use(inventory,'finance/costs/result.md',now=dt.datetime.now(dt.timezone.utc))
    assert not readiness['ready'] and 'information_query_requires_authorized_revalidation' in str(readiness)
    current_check=revalidate_approved_queries(root,folder_policy(root),consumer='finance/costs/result.md',context_id=AUDIT_CONTEXT)
    validate(current_check,json.loads((BASE/'docs/references/schemas/wiki-context-query-revalidation-v1.schema.json').read_text()))
    assert current_check['equivalent']
    page(root,'new.md');after=commit(root)
    impact=assess_approved_impact(root,folder_policy(root),consumers=['finance/costs/result.md'],before=head,after=after,destination_context=AUDIT_CONTEXT)
    assert len(impact['candidates'])==1 and impact['candidates'][0]['source']==ANCHOR
    assert impact['candidates'][0]['members_digest_before']!=impact['candidates'][0]['members_digest_after']
    validate(impact,json.loads((BASE/'docs/references/schemas/wiki-context-impact-v1.schema.json').read_text()))
    assert not revalidate_approved_queries(root,folder_policy(root),consumer='finance/costs/result.md',context_id=AUDIT_CONTEXT)['equivalent']
    from wiki_core.context_impact import report_review
    report=report_review(root,folder_policy(root),impact['candidates'][0],disposition='still_valid',reason='Synthetic reported review',evidence_revision=after)
    assert report['verification']=='reported_not_verified' and not report['next_impact_allowed']

@pytest.mark.parametrize('change',['addition','removal','entry','exit','selected','identity','outside','irrelevant_body'])
def test_canonical_query_impact_does_not_depend_on_hub_edits(collection,change):
    p=packet(collection);declare(collection,requirement(p));before=commit(collection)
    anchor_bytes=(collection/ANCHOR).read_bytes()
    if change=='addition': page(collection,'second.md')
    elif change=='removal': (collection/SCOPE/'first.md').unlink()
    elif change=='entry': page(collection,'inactive.md',status='active')
    elif change=='exit': page(collection,'first.md',status='inactive')
    elif change=='selected': page(collection,'first.md',amount=15)
    elif change=='identity': page(collection,'first.md',page_id='different-identity')
    elif change=='outside': (collection/'finance/tax/outside.md').write_bytes(b'\xff')
    else: (collection/SCOPE/'first.md').write_text((collection/SCOPE/'first.md').read_text().replace('Body not selected.','Unselected content changed.'))
    after=commit(collection)
    out=assess_approved_impact(collection,policy(collection),consumers=['finance/costs/result.md'],before=before,after=after,destination_context='costs')
    assert (collection/ANCHOR).read_bytes()==anchor_bytes
    if change in ('outside','irrelevant_body'): assert out['candidates']==[]
    else: assert len(out['candidates'])==1 and out['candidates'][0]['state']=='review_pending'


def test_empty_query_becomes_nonempty_and_generic_graph_reports_unsupported(collection):
    from wiki_core.information_impact import evaluate_information_impact
    p=packet(collection,[query(filters={'status':'new'})]);declare(collection,requirement(p));before=commit(collection)
    graph=authored_graph(collection,load_config(collection))
    generic=evaluate_information_impact(graph,graph,set(),today=dt.date(2026,11,3))
    assert generic['ok'] and generic['integrity_blockers']==[]
    generic=evaluate_information_impact(graph,graph,{SCOPE+'/new.md'},today=dt.date(2026,11,3))
    assert not generic['ok'] and any(row['reason']=='dynamic_query_requires_authorized_revalidation' for row in generic['integrity_blockers'])
    page(collection,'new.md',status='new');after=commit(collection)
    out=assess_approved_impact(collection,policy(collection),consumers=['finance/costs/result.md'],before=before,after=after,destination_context='costs')
    assert len(out['candidates'])==1


def test_invalid_outside_scope_never_opened_and_invalid_filename_inside_fails(collection,monkeypatch):
    import os
    (collection/'finance/tax/invalid.md').write_bytes(b'\xff')
    (collection/'finance/tax/link.md').symlink_to('source.md');commit(collection)
    # macOS rejects invalid UTF-8 filenames on disk. Build the same Git tree
    # entry directly, without a checkout or a platform-specific filename.
    blob=subprocess.check_output(['git','-C',str(collection),'hash-object','-w','--stdin'],input=b'Invalid filename fixture\n').strip()
    def raw_entry(path):
        subprocess.run([b'git',b'-C',os.fsencode(collection),b'update-index',b'--add',b'--cacheinfo',b'100644',blob,path],check=True)
        git(collection,'commit','-qm','invalid filename in Git only');approve(collection)
    raw_entry(b'finance/tax/bad-\xff.md')
    assert len(packet(collection)['query_selections'][0]['members'])==1
    raw_entry(SCOPE.encode()+b'/bad-\xff.md')
    with pytest.raises(PolicyError,match='path is not UTF-8'): packet(collection)


def test_preflight_detects_new_member_at_current_base_and_requires_observed_queries(collection):
    historic=git(collection,'rev-parse','HEAD');page(collection,'new.md');base=commit(collection)
    p=packet(collection,revision=historic);done=result(p,[{'path':'finance/costs/result.md','action':'modified'}])
    git(collection,'checkout','-qb','wiki/stale-query');(collection/'finance/costs/result.md').write_text('Proposal from stale selection\n');git(collection,'add','.');git(collection,'commit','-qm','proposal');head=git(collection,'rev-parse','HEAD')
    with pytest.raises(IntegrationError,match='query selection'): preflight(collection,policy(collection),context_id='costs',base=base,head=head,branch='wiki/stale-query',packet=p,result=done)
    no_observation=deepcopy(done);del no_observation['read_coverage']['observed_queries']
    with pytest.raises(PolicyError,match='query coverage'): validate_result(no_observation,p)
    changed=deepcopy(p);changed['query_selections'][0]['request']['query']['filters']={'status':'inactive'}
    with pytest.raises(PolicyError,match='bound'): validate_result(done,changed)


def test_policy_reference_changes_during_composition_fail_closed(collection,monkeypatch):
    original=RepositoryReader.read; moved=[]
    def move(reader,ref,*args,**kwargs):
        item=original(reader,ref,*args,**kwargs)
        if ref==SCOPE+'/first.md' and not moved:
            moved.append(True);page(collection,'new.md');commit(collection)
        return item
    monkeypatch.setattr(RepositoryReader,'read',move)
    with pytest.raises(PolicyError,match='not current trusted'): packet(collection)


def test_real_protected_cli_http_preflight_and_canonical_revalidation(collection,bound_server,tmp_path):
    srv,token=bound_server;root=collection;sha=git(root,'rev-parse','HEAD');headers={ADMIN_SESSION_HEADER:token}
    task={**TASK,'max_bytes':50000,'evidence':[],'queries':[query()]}
    payload={'context_id':'finance/costs','approved_revision':sha,'content_revision':sha,
             'entry_folder':'finance/costs','entry_index':'finance/costs/index.md','task':task}
    assert srv.post('/api/coordination/protected/packet',payload,headers={})[0]==403
    status,response=srv.post('/api/coordination/protected/packet',payload,headers=headers)
    assert status==200;p=response['packet'];taskfile=tmp_path.parent/(tmp_path.name+'-query-request.json');taskfile.write_text(json.dumps(task))
    cmd=[sys.executable,str(BASE/'scripts/wiki_coordination.py'),'--root',str(root),'--context-id','finance/costs','--approved-revision',sha,'--revision',sha,'--packet-request',str(taskfile),'--folder','finance/costs','--index','finance/costs/index.md']
    assert json.loads(subprocess.check_output(cmd))['packet']==p
    empty=deepcopy(payload);empty['task']['queries']=[query(filters={'status':'absent'})]
    status,body=srv.post('/api/coordination/protected/packet',empty,headers=headers)
    assert status==200 and body['packet']['query_selections'][0]['members']==[]
    git(root,'checkout','-qb','wiki/http-query');declare(root,requirement(p));git(root,'add','.');git(root,'commit','-qm','canonical interpretation');head=git(root,'rev-parse','HEAD')
    done=result(p,[{'path':'finance/costs/result.md','action':'modified'}])
    done['read_coverage']['missing'] = p['coverage']['missing']
    done['read_coverage']['observed_refs'] = list({json.dumps(row, sort_keys=True): row
                                                   for row in p['declared_read_set']}.values())
    check={'context_id':'finance/costs','approved_revision':sha,'base':sha,'head':head,'branch':'wiki/http-query','packet':p,'result':done}
    status,checked=srv.post('/api/coordination/protected/preflight',check,headers=headers)
    assert status==200 and checked['preflight']['state']=='independent_review_required'
    approve(root)
    command=[sys.executable,str(BASE/'scripts/wiki_context_flow.py'),'--repo',str(root),'--approved-revision',head,'revalidate','--consumer','finance/costs/result.md','--context','costs']
    # New CLI operations do not select the legacy YAML hierarchy as authority.
    assert subprocess.run(command, capture_output=True).returncode != 0
    status,stale=srv.post('/api/coordination/protected/packet',payload,headers=headers)
    assert status==409 and stale['error_code']=='coordination_policy_unavailable' and 'packet' not in stale


def test_protected_limits_secrets_and_denied_scope_are_opaque(collection,bound_server):
    srv,token=bound_server;sha=git(collection,'rev-parse','HEAD');headers={ADMIN_SESSION_HEADER:token}
    payload={'context_id':'finance/costs','approved_revision':sha,'content_revision':sha,
             'entry_folder':'finance/costs','entry_index':'finance/costs/index.md',
             'task':{**TASK,'max_bytes':50000,'evidence':[],'queries':[query()]}}
    secret='AKIA'+'IOSFODNN7EXAMPLE'
    for q in (query(max_scan_bytes=1),query(filters={'key':secret}),query(scope='finance/tax')):
        data=deepcopy(payload);data['task']['queries']=[q]
        status,body=srv.post('/api/coordination/protected/packet',data,headers=headers)
        assert status==409 and 'packet' not in body and 'finance/' not in json.dumps(body) and secret not in json.dumps(body)

@pytest.mark.parametrize('anchor_type',['ontology_index','context_hub','source_catalog','root_entity'])
def test_registered_anchor_roles_and_physical_owner_override_historical_context_tag(collection,anchor_type):
    path=collection/ANCHOR
    path.write_text('---\n'+yaml.safe_dump({'page_id':'stable-cost-hub','page_type':anchor_type,'context':'historical-label'})+'---\nCollection contract.\n')
    commit(collection)
    assert packet(collection)['query_selections'][0]['members'][0]['ref']==SCOPE+'/first.md'


def test_scan_size_admitted_before_candidate_blob_and_no_selector_fallback(collection,monkeypatch):
    reader=RepositoryReader(collection);anchor_bytes=len((collection/ANCHOR).read_bytes());size=len((collection/SCOPE/'first.md').read_bytes())
    original=reader._document
    def guard(path):
        assert path==ANCHOR, 'over-budget candidate was opened'
        return original(path)
    monkeypatch.setattr(reader,'_document',guard)
    with pytest.raises(PolicyError,match='scan byte limit'):
        select_query(policy(collection),'costs',reader,query(max_scan_bytes=anchor_bytes+size-1))
    with pytest.raises(ValueError,match='missing frontmatter field'):
        packet(collection,[query(field='absent')])


def test_current_revocation_blocks_historical_query_and_durable_revalidation(collection):
    p=packet(collection);declare(collection,requirement(p));commit(collection)
    path=collection/'finance/costs/context.yaml';d=yaml.safe_load(path.read_text());d['policy']['deny']={'read':[SCOPE]};path.write_text(yaml.safe_dump(d));commit(collection)
    with pytest.raises(PolicyError,match='not authorized'): packet(collection,revision=p['content_revision'])
    with pytest.raises(ValueError,match='authority changed'):
        revalidate_approved_queries(collection,policy(collection),consumer='finance/costs/result.md',context_id='costs')


def test_strict_json_task_rejects_ambiguity_without_echo(collection,tmp_path):
    from wiki_core.context_selection import strict_json_loads
    with pytest.raises(ValueError,match='duplicate JSON key'): strict_json_loads('{"scope":"a","scope":"b"}')
    taskfile=tmp_path.parent/(tmp_path.name+'-ambiguous-request.json');taskfile.write_text('{"queries":[],"queries":[]}')
    folderize(collection)
    sha=git(collection,'rev-parse','HEAD')
    command=[sys.executable,str(BASE/'scripts/wiki_coordination.py'),'--root',str(collection),'--context-id','finance/costs','--approved-revision',sha,'--revision',sha,'--packet-request',str(taskfile),'--folder','finance/costs','--index','finance/costs/index.md']
    out=subprocess.run(command,capture_output=True,text=True)
    assert out.returncode!=0 and json.loads(out.stdout)['error_code']=='coordination_invalid_request'


def test_protected_http_rejects_duplicate_json_keys(collection,bound_server):
    import urllib.request
    import urllib.error
    srv,token=bound_server
    headers={'content-type':'application/json','X-Wiki-Operator-Nonce':srv.server.operator_nonce,
        'X-Wiki-Attempt-Key':'duplicate-query-request',ADMIN_SESSION_HEADER:token}
    request=urllib.request.Request(srv.url('/api/coordination/protected/packet'),
        data=b'{"context_id":"costs","context_id":"tax"}',headers=headers,method='POST')
    with pytest.raises(urllib.error.HTTPError) as error: urllib.request.urlopen(request)
    with error.value as response:
        assert response.code==400
        assert 'packet' not in json.loads(response.read())


def test_preflight_cannot_carry_a_stale_existing_query_via_explicit_only_packet(collection):
    p=packet(collection);declare(collection,requirement(p));commit(collection)
    page(collection,'new.md');base=commit(collection)
    explicit=build_packet(collection,policy(collection),'costs',base,[],10000,**TASK)
    git(collection,'checkout','-qb','wiki/unchanged-dependency')
    path=collection/'finance/costs/result.md';path.write_text(path.read_text()+'An unrelated proposed edit.\n')
    git(collection,'add','.');git(collection,'commit','-qm','keep stale declaration')
    done={'schema_version':'wiki.task-result/v1','task_id':explicit['task_id'],'context_id':'costs','packet_digest':explicit['packet_digest'],
        'status':'completed','blockers':[],'changes':[{'path':'finance/costs/result.md','action':'modified'}],
        'read_coverage':{'observed_refs':explicit['declared_read_set'],'missing':[]}}
    with pytest.raises(IntegrationError,match='existing query requirement'):
        preflight(collection,policy(collection),context_id='costs',base=base,head=git(collection,'rev-parse','HEAD'),branch='wiki/unchanged-dependency',packet=explicit,result=done)


@pytest.mark.parametrize('mutation',['deny','owner'])
def test_empty_receipt_cannot_hide_authority_change_before_new_match(collection,monkeypatch,mutation):
    page(collection,'branch/old.md',status='inactive');commit(collection)
    p=packet(collection,[query(filters={'status':'new'})]);assert p['query_selections'][0]['members']==[]
    declare(collection,requirement(p));before=commit(collection)
    if mutation=='deny':
        path=collection/'finance/costs/context.yaml';doc=yaml.safe_load(path.read_text());doc['policy']['deny']={'read':[SCOPE+'/branch']};path.write_text(yaml.safe_dump(doc))
    else:
        save(collection,SCOPE+'/branch/context.yaml',manifest('new-owner','costs',SCOPE+'/branch',{'read':['self']}))
    page(collection,'branch/new.md',status='new');after=commit(collection)
    original=RepositoryReader._document
    def guarded(reader,path):
        assert '/branch/' not in path, 'newly revoked blob was opened'
        return original(reader,path)
    monkeypatch.setattr(RepositoryReader,'_document',guarded)
    with pytest.raises(ValueError,match='authority changed'):
        revalidate_approved_queries(collection,policy(collection),consumer='finance/costs/result.md',context_id='costs')
    with pytest.raises(ValueError,match='cannot be revalidated'):
        assess_approved_impact(collection,policy(collection),consumers=['finance/costs/result.md'],before=before,after=after,destination_context='costs')


def test_authority_projection_ignores_documentary_commit_but_requires_verified_policy(collection,monkeypatch):
    p=packet(collection,[query(filters={'status':'absent'})]);declare(collection,requirement(p));commit(collection)
    (collection/'finance/costs/unrelated.md').write_text('A documentary change outside the collection.\n');commit(collection)
    out=revalidate_approved_queries(collection,policy(collection),consumer='finance/costs/result.md',context_id='costs')
    assert out['equivalent']
    req=requirement(p);req['query_policy_revision']='0'*40;declare(collection,req);commit(collection)
    with pytest.raises(ValueError): revalidate_approved_queries(collection,policy(collection),consumer='finance/costs/result.md',context_id='costs')


@pytest.mark.parametrize('change',['addition','removal','value','exit'])
def test_proposal_head_cannot_change_its_consumed_collection(collection,change):
    base=git(collection,'rev-parse','HEAD');p=packet(collection)
    git(collection,'checkout','-qb','wiki/query-mutates-itself');declare(collection,requirement(p))
    changed=SCOPE+'/first.md';action='modified'
    if change=='addition': page(collection,'added.md');changed=SCOPE+'/added.md';action='created'
    elif change=='removal': (collection/changed).unlink();action='deleted'
    elif change=='value': page(collection,'first.md',amount=55)
    else: page(collection,'first.md',status='inactive')
    git(collection,'add','.');git(collection,'commit','-qm','proposal changes selection')
    done=result(p,[{'path':'finance/costs/result.md','action':'modified'},{'path':changed,'action':action}])
    with pytest.raises(IntegrationError,match='query selection changed in proposal'):
        preflight(collection,policy(collection),context_id='costs',base=base,head=git(collection,'rev-parse','HEAD'),branch='wiki/query-mutates-itself',packet=p,result=done)


@pytest.mark.parametrize('anchor_type',['context_hub','source_catalog'])
def test_sibling_pages_exclude_anchor_structurally_and_bind_one_anchor_input(collection,anchor_type):
    hub=collection/ANCHOR;hub.write_text('---\n'+yaml.safe_dump({'page_id':'cost-hub','page_type':anchor_type,'status':'active','amount':999})+'---\nHub body.\n')
    commit(collection)
    q=query(scope='finance/costs');p=packet(collection,[q]);row=p['query_selections'][0]
    assert row['excluded_anchor']==ANCHOR and ANCHOR not in {m['ref'] for m in row['members']}
    assert sum(x['ref']==ANCHOR for x in p['inputs'])==1 and 'Hub body.' in next(x['text'] for x in p['inputs'] if x['ref']==ANCHOR)
    assert row['enumerated']==4  # Two item pages + two non-page sibling Markdown files; anchor excluded.
    from wiki_core.context_selection import query_identity,normalize_query
    assert row['query_id']==query_identity(normalize_query(q))


def test_preflight_rejects_consumer_that_is_its_own_selected_member(collection):
    path=collection/'finance/costs/result.md';path.write_text('---\npage_id: cost-result\npage_type: claim\nstatus: active\namount: 10\n---\nInterpretation.\n');base=commit(collection)
    p=packet(collection,[query(scope='finance/costs')]);assert 'finance/costs/result.md' in {m['ref'] for m in p['query_selections'][0]['members']}
    git(collection,'checkout','-qb','wiki/self-member');req=requirement(p)
    path.write_text('---\n'+yaml.safe_dump({'page_id':'cost-result','page_type':'claim','status':'active','amount':10,'information_requirements':[req]})+'---\nInterpretation changed.\n')
    git(collection,'add','.');git(collection,'commit','-qm','self member query')
    with pytest.raises(IntegrationError,match='consumer cannot be a member'):
        preflight(collection,policy(collection),context_id='costs',base=base,head=git(collection,'rev-parse','HEAD'),branch='wiki/self-member',packet=p,result=result(p,[{'path':'finance/costs/result.md','action':'modified'}]))


def test_existing_canonical_receipt_also_checks_proposal_head_with_explicit_only_packet(collection):
    p=packet(collection);declare(collection,requirement(p));base=commit(collection)
    explicit=build_packet(collection,policy(collection),'costs',base,[],10000,**TASK)
    git(collection,'checkout','-qb','wiki/existing-query-change');page(collection,'added.md')
    path=collection/'finance/costs/result.md';path.write_text(path.read_text()+'Proposed edit retaining receipt.\n')
    git(collection,'add','.');git(collection,'commit','-qm','change canonical collection')
    done={'schema_version':'wiki.task-result/v1','task_id':explicit['task_id'],'context_id':'costs','packet_digest':explicit['packet_digest'],
        'status':'completed','blockers':[],'changes':[{'path':'finance/costs/result.md','action':'modified'},{'path':SCOPE+'/added.md','action':'created'}],
        'read_coverage':{'observed_refs':explicit['declared_read_set'],'missing':[]}}
    with pytest.raises(IntegrationError,match='existing query requirement'):
        preflight(collection,policy(collection),context_id='costs',base=base,head=git(collection,'rev-parse','HEAD'),branch='wiki/existing-query-change',packet=explicit,result=done)


def test_query_preflight_and_scoped_audit_cli_recompute_exact_head(audit_collection, monkeypatch, capsys):
    from scripts import wiki_audit as audit
    configure_audit(audit_collection)
    base=commit(audit_collection); p=folder_packet(audit_collection)
    assert len([item for item in p['inputs'] if item['ref'] == ANCHOR]) == 2
    assert len([item for item in p['declared_read_set'] if item['ref'] == ANCHOR]) == 1
    git(audit_collection,'checkout','-qb','wiki/query-audit')
    declare(audit_collection,folder_requirement(p)); git(audit_collection,'add','.'); git(audit_collection,'commit','-qm','declare query')
    head=git(audit_collection,'rev-parse','HEAD')
    assert preflight(audit_collection,folder_policy(audit_collection),context_id=AUDIT_CONTEXT,base=base,head=head,branch='wiki/query-audit',packet=p,
        result=folder_result(p,[{'path':TASK['output'],'action':'modified'}]))['state']=='independent_review_required'
    monkeypatch.setattr(audit,'ROOT',audit_collection)
    def invoke(*options):
        monkeypatch.setattr(sys,'argv',['wiki_audit.py','--check','--only','freshness_budget','--freshness-base',base,*options])
        code=audit.main(); text=capsys.readouterr().out; return code,text
    args=('--query-context',AUDIT_CONTEXT,'--query-policy-revision',base,'--query-head',head)
    assert invoke()[0]==1
    code,output=invoke(*args)
    assert code==0,output
    assert invoke('--query-context','tax','--query-policy-revision',base,'--query-head',head)[0]==1
    assert invoke('--query-context',AUDIT_CONTEXT,'--query-policy-revision',base,'--query-head','f'*40)[0]==1
    (audit_collection/'.git/info/exclude').write_text('ignored.md\n')
    ignored=audit_collection/'finance/costs/ignored.md'; ignored.write_text('---\npage_id: ignored\npage_type: claim\n---\nignored\n')
    assert invoke(*args)[0]==1
    ignored.unlink()
    (audit_collection/'finance/costs/dirty.md').write_text('untracked')
    assert invoke(*args)[0]==1


def test_source_change_pending_then_consumer_reinterprets(audit_collection):
    from wiki_core.freshness_impact import repository_report
    configure_audit(audit_collection)
    commit(audit_collection)
    first=folder_packet(audit_collection); declare(audit_collection,folder_requirement(first)); base=commit(audit_collection)
    git(audit_collection,'checkout','-qb','wiki/source-change')
    page(audit_collection,'new.md'); git(audit_collection,'add','.'); git(audit_collection,'commit','-qm','source addition')
    source_head=git(audit_collection,'rev-parse','HEAD'); config=load_config(audit_collection)
    generic=repository_report(audit_collection,config,base)
    assert any(x['reason']=='dynamic_query_requires_authorized_revalidation' for x in generic['blockers'])
    report=repository_report(audit_collection,config,base,query_context=AUDIT_CONTEXT,query_policy_revision=base,query_head=source_head)
    assert not report['blockers'] and any(x['reason']=='dynamic_query_changed' and x['verification_performed'] is False for x in report['pending_reviews'])
    approve(audit_collection)
    # A second source proposal must remain reviewable even while the first
    # approved change still awaits independent consumer interpretation.
    git(audit_collection,'checkout','-qb','wiki/second-source-change')
    page(audit_collection,'another.md');git(audit_collection,'add','.');git(audit_collection,'commit','-qm','second source addition')
    second_head=git(audit_collection,'rev-parse','HEAD')
    again=repository_report(audit_collection,config,source_head,query_context=AUDIT_CONTEXT,query_policy_revision=source_head,query_head=second_head)
    assert not again['blockers'] and any(x['reason']=='dynamic_query_changed' for x in again['pending_reviews'])
    approve(audit_collection); source_head=second_head
    newpacket=folder_packet(audit_collection)
    git(audit_collection,'checkout','-qb','wiki/consumer-refresh')
    declare(audit_collection,folder_requirement(newpacket)); git(audit_collection,'add','.'); git(audit_collection,'commit','-qm','refresh query')
    head=git(audit_collection,'rev-parse','HEAD')
    assert preflight(audit_collection,folder_policy(audit_collection),context_id=AUDIT_CONTEXT,base=source_head,head=head,branch='wiki/consumer-refresh',packet=newpacket,
        result=folder_result(newpacket,[{'path':TASK['output'],'action':'modified'}]))['state']=='independent_review_required'
    report=repository_report(audit_collection,config,source_head,query_context=AUDIT_CONTEXT,query_policy_revision=source_head,query_head=head)
    assert not report['blockers'], report['blockers']


def test_scoped_query_audit_rejects_forgery_policy_and_self_invalidation(audit_collection):
    from wiki_core.freshness_impact import repository_report
    configure_audit(audit_collection)
    base=commit(audit_collection); p=folder_packet(audit_collection)
    git(audit_collection,'checkout','-qb','wiki/query-negative')
    req=folder_requirement(p); req['selected_digest']='0'*64; declare(audit_collection,req)
    git(audit_collection,'add','.'); git(audit_collection,'commit','-qm','forged digest')
    head=git(audit_collection,'rev-parse','HEAD'); config=load_config(audit_collection)
    options={'query_context':AUDIT_CONTEXT,'query_policy_revision':base,'query_head':head}
    assert repository_report(audit_collection,config,base,**options)['blockers']
    with pytest.raises(ValueError,match='exact context'):
        repository_report(audit_collection,config,base,**{**options,'query_policy_revision':'f'*40})
    # An otherwise valid declaration cannot certify a simultaneous scope change.
    declare(audit_collection,folder_requirement(p)); page(audit_collection,'second.md')
    git(audit_collection,'add','.');git(audit_collection,'commit','-qm','self invalidation');head=git(audit_collection,'rev-parse','HEAD')
    assert repository_report(audit_collection,config,base,**{**options,'query_head':head})['blockers']


def test_historical_query_revision_must_precede_its_policy_before_blob_reads(collection, monkeypatch):
    from wiki_core.context_selection import reproduce_query
    first=packet(collection)['query_selections'][0]
    old_policy=first['policy_revision']
    page(collection,'new.md'); later=commit(collection)
    reader=RepositoryReader(collection,later)
    monkeypatch.setattr(reader,'read',lambda *args,**kwargs: pytest.fail('opened blob before ancestry validation'))
    with pytest.raises(PolicyError,match='not an ancestor'):
        reproduce_query(policy(collection),'costs',reader,query(),policy_revision=old_policy,
                        expected_authority=first['authority_digest'])


def test_unrelated_log_and_normative_input_are_distinguished(audit_collection):
    from wiki_core.freshness_impact import repository_report
    configure_audit(audit_collection)
    commit(audit_collection); p=folder_packet(audit_collection); declare(audit_collection,folder_requirement(p)); base=commit(audit_collection)
    git(audit_collection,'checkout','-qb','wiki/log-only')
    (audit_collection/'other.log').write_text('ordinary synthetic log\n');git(audit_collection,'add','.');git(audit_collection,'commit','-qm','unrelated log')
    config=load_config(audit_collection); report=repository_report(audit_collection,config,base)
    assert not report['blockers']
    (audit_collection/'AGENTS.md').write_text('Changed approved rule\n');git(audit_collection,'add','.');git(audit_collection,'commit','-qm','normative change')
    head=git(audit_collection,'rev-parse','HEAD')
    assert repository_report(audit_collection,config,base)['blockers']
    report=repository_report(audit_collection,config,base,query_context=AUDIT_CONTEXT,query_policy_revision=base,query_head=head)
    assert not report['blockers'] and any(r['reason']=='dynamic_query_requalification_required' for r in report['pending_reviews'])
    (audit_collection/TASK['output']).write_text((audit_collection/TASK['output']).read_text()+'Changed interpretation.\n')
    git(audit_collection,'add','.');git(audit_collection,'commit','-qm','edit consumer with rule');head=git(audit_collection,'rev-parse','HEAD')
    assert repository_report(audit_collection,config,base,query_context=AUDIT_CONTEXT,query_policy_revision=base,query_head=head)['blockers']


def test_revoked_query_can_only_be_replaced_by_current_authorized_receipt(audit_collection,monkeypatch):
    from wiki_core.freshness_impact import repository_report
    configure_audit(audit_collection)
    page(audit_collection,'restricted/old.md'); commit(audit_collection)
    old=folder_packet(audit_collection); declare(audit_collection,folder_requirement(old)); base=commit(audit_collection)
    set_folder_deny(audit_collection, SCOPE+'/restricted')
    git(audit_collection,'checkout','-qb','wiki/revoke-scope');git(audit_collection,'add','.');git(audit_collection,'commit','-qm','approved revocation')
    revocation=git(audit_collection,'rev-parse','HEAD'); config=load_config(audit_collection)
    proposed=repository_report(audit_collection,config,base,query_context=AUDIT_CONTEXT,query_policy_revision=base,query_head=revocation)
    assert not proposed['blockers'] and any(r['reason']=='dynamic_query_requalification_required' for r in proposed['pending_reviews'])
    approve(audit_collection)
    # Once revocation is approved, the old receipt cannot authorize another
    # affected query under the newly reduced authority.
    git(audit_collection,'checkout','-qb','wiki/stale-after-revocation');page(audit_collection,'post-revoke.md')
    git(audit_collection,'add','.');git(audit_collection,'commit','-qm','new source after revocation'); stale_head=git(audit_collection,'rev-parse','HEAD')
    assert repository_report(audit_collection,config,revocation,query_context=AUDIT_CONTEXT,query_policy_revision=revocation,query_head=stale_head)['blockers']
    git(audit_collection,'checkout','-q','wiki/revoke-scope')
    replacement=folder_packet(audit_collection)
    git(audit_collection,'checkout','-qb','wiki/requalify-query');declare(audit_collection,folder_requirement(replacement))
    git(audit_collection,'add','.');git(audit_collection,'commit','-qm','requalify under current policy'); head=git(audit_collection,'rev-parse','HEAD')
    original=RepositoryReader._document
    def guard(reader,path,*args,**kwargs):
        assert path != SCOPE+'/restricted/old.md', 'revoked member opened'
        return original(reader,path,*args,**kwargs)
    monkeypatch.setattr(RepositoryReader,'_document',guard)
    report=repository_report(audit_collection,config,revocation,query_context=AUDIT_CONTEXT,query_policy_revision=revocation,query_head=head)
    assert not report['blockers'],report['blockers']
    forged=folder_requirement(replacement);forged['members_digest']='0'*64;declare(audit_collection,forged)
    git(audit_collection,'add','.');git(audit_collection,'commit','-qm','forged replacement');head=git(audit_collection,'rev-parse','HEAD')
    assert repository_report(audit_collection,config,revocation,query_context=AUDIT_CONTEXT,query_policy_revision=revocation,query_head=head)['blockers']


@pytest.mark.parametrize('forged_old_authority', [False, True])
def test_requalified_query_replaces_receipt_after_approved_instruction_change(audit_collection, monkeypatch, forged_old_authority):
    from wiki_core.freshness_impact import repository_report
    configure_audit(audit_collection)
    commit(audit_collection)
    old_packet = folder_packet(audit_collection)
    old_requirement = folder_requirement(old_packet)
    if forged_old_authority:
        old_requirement['authority_digest'] = '0'*64
    declare(audit_collection, old_requirement)
    commit(audit_collection)
    (audit_collection/'AGENTS.md').write_text('# Updated approved instructions\n')
    approved = commit(audit_collection)
    current = folder_packet(audit_collection)
    git(audit_collection, 'checkout', '-qb', 'wiki/requalify-after-rule-change')
    declare(audit_collection, folder_requirement(current))
    git(audit_collection, 'add', '.')
    git(audit_collection, 'commit', '-qm', 'replace query receipt')
    head = git(audit_collection, 'rev-parse', 'HEAD')
    original = RepositoryReader._document
    def guard(reader, path, *args, **kwargs):
        assert not (reader.revision == old_packet['policy_revision'] and path in {'AGENTS.md', ANCHOR, SCOPE+'/first.md'}), 'historical body opened'
        return original(reader, path, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, '_document', guard)
    report = repository_report(audit_collection, load_config(audit_collection), approved,
        query_context=AUDIT_CONTEXT, query_policy_revision=approved, query_head=head)
    if forged_old_authority:
        assert report['blockers']
    else:
        assert not report['blockers'], report['blockers']


def test_query_graph_bytes_and_parsed_metadata_must_match_head(collection):
    from wiki_core.dynamic_query_audit import revalidate_affected
    p=packet(collection);declare(collection,requirement(p)); base=commit(collection)
    graph=authored_graph(collection,load_config(collection))
    path=TASK['output']
    for mutation in ('bytes','metadata'):
        forged=deepcopy(graph)
        if mutation=='bytes': forged['documents'][path]+='changed during graph construction'
        else: forged['nodes'][path]['information_requirements']=[]
        with pytest.raises(ValueError,match='graph differs'):
            revalidate_affected(collection,base=base,head=base,context_id='costs',affected=[],changed=set(),current=forged)


def test_query_cli_requires_complete_binding_and_freshness_check(collection,monkeypatch,capsys):
    from scripts import wiki_audit as audit
    monkeypatch.setattr(audit,'ROOT',collection)
    for argv in (['--query-context','costs'], ['--only','frontmatter','--query-context','costs','--query-policy-revision','a'*40,'--query-head','b'*40]):
        monkeypatch.setattr(sys,'argv',['wiki_audit.py',*argv])
        with pytest.raises(SystemExit) as error: audit.main()
        assert error.value.code==2


@pytest.mark.parametrize('race',['head','trusted_ref','worktree'])
def test_query_audit_rejects_concurrent_revision_or_input_changes(collection,monkeypatch,race):
    from wiki_core.freshness_impact import repository_report
    import wiki_core.dynamic_query_audit as query_audit
    (collection/'wiki.config.yaml').write_text('paths:\n  memory_root: finance\naudit:\n  freshness_scope: impact\n  information_impact: use_scoped\n')
    base=commit(collection);p=packet(collection)
    git(collection,'checkout','-qb','wiki/race-query');declare(collection,requirement(p));git(collection,'add','.');git(collection,'commit','-qm','proposed query')
    head=git(collection,'rev-parse','HEAD'); config=load_config(collection); original=query_audit.select_query; changed=[False]
    def move(*args,**kwargs):
        result=original(*args,**kwargs)
        if not changed[0]:
            changed[0]=True
            if race=='trusted_ref': git(collection,'update-ref','refs/remotes/origin/main',head)
            elif race=='worktree': (collection/'finance/costs/result.md').write_text('changed concurrently')
            else:
                (collection/'race.log').write_text('changed concurrently');git(collection,'add','.');git(collection,'commit','-qm','move head')
        return result
    monkeypatch.setattr(query_audit,'select_query',move)
    with pytest.raises(ValueError):
        repository_report(collection,config,base,query_context='costs',query_policy_revision=base,query_head=head)


def test_one_context_binding_cannot_clear_another_context_query(audit_collection):
    from wiki_core.freshness_impact import repository_report
    configure_audit(audit_collection)
    (audit_collection/'finance/tax/index.md').write_text('---\npage_id: tax-anchor\npage_type: source_catalog\n---\n# Synthetic\n')
    tax=audit_collection/'finance/tax/items';tax.mkdir();(tax/'one.md').write_text('---\npage_id: tax-one\npage_type: claim\nstatus: active\namount: 1\n---\nSynthetic\n')
    commit(audit_collection)
    cp=folder_packet(audit_collection);declare(audit_collection,folder_requirement(cp))
    tax_query={'target':'finance/tax/index.md','reason':'synthetic','use':'interpret','classification':'synthetic','query':{**query()['query'],'scope':'finance/tax/items'}}
    tp=folder_build_packet(audit_collection,folder_policy(audit_collection,'finance/tax'),'finance/tax',git(audit_collection,'rev-parse','HEAD'),[],50000,queries=[tax_query],
        task_id='tax-task',goal='synthetic',output='finance/tax/result.md',integrator='reviewer')
    (audit_collection/'finance/tax/result.md').write_text('---\n'+yaml.safe_dump({'page_id':'tax-result','page_type':'claim','information_requirements':[folder_requirement(tp)]})+'---\nSynthetic\n')
    base=commit(audit_collection);git(audit_collection,'checkout','-qb','wiki/multiple-contexts')
    page(audit_collection,'extra.md');(tax/'two.md').write_text('---\npage_id: tax-two\npage_type: claim\nstatus: active\namount: 2\n---\nSynthetic\n')
    git(audit_collection,'add','.');git(audit_collection,'commit','-qm','two scopes changed');head=git(audit_collection,'rev-parse','HEAD')
    report=repository_report(audit_collection,load_config(audit_collection),base,query_context=AUDIT_CONTEXT,query_policy_revision=base,query_head=head)
    # The scoped auditor cannot assert the other owner's result is current or
    # expose its private query. Its coverage boundary remains explicit.
    assert report['query_revalidation']['coverage_limit']=='outside_selected_context_not_assessed'
    assert 'finance/tax/result.md' not in json.dumps(report['query_revalidation'])
    assert not any(r['path']==TASK['output'] for r in report['blockers'])
    assert any(r['path']==TASK['output'] and r['reason']=='dynamic_query_changed' for r in report['pending_reviews'])


def test_removing_approved_query_does_not_erase_obligation(audit_collection):
    from wiki_core.freshness_impact import repository_report
    configure_audit(audit_collection)
    commit(audit_collection);p=folder_packet(audit_collection);declare(audit_collection,folder_requirement(p));base=commit(audit_collection)
    git(audit_collection,'checkout','-qb','wiki/remove-query');git(audit_collection,'rm',TASK['output']);git(audit_collection,'commit','-qm','remove consumer')
    head=git(audit_collection,'rev-parse','HEAD')
    assert repository_report(audit_collection,load_config(audit_collection),base,query_context=AUDIT_CONTEXT,query_policy_revision=base,query_head=head)['blockers']


def test_proposed_grant_never_authorizes_query_reads(audit_collection,monkeypatch):
    from wiki_core.freshness_impact import repository_report
    import wiki_core.dynamic_query_audit as qa
    configure_audit(audit_collection)
    page(audit_collection,'restricted/secret.md')
    set_folder_deny(audit_collection, SCOPE+'/restricted');commit(audit_collection)
    p=folder_packet(audit_collection);declare(audit_collection,folder_requirement(p));base=commit(audit_collection)
    git(audit_collection,'checkout','-qb','wiki/proposed-grant');set_folder_deny(audit_collection, None);git(audit_collection,'add','.');git(audit_collection,'commit','-qm','propose grant')
    head=git(audit_collection,'rev-parse','HEAD'); original=RepositoryReader._document; selected=qa.select_query
    def guard(reader,path,*args,**kwargs):
        assert path!=SCOPE+'/restricted/secret.md', 'proposed grant opened revoked blob'
        return original(reader,path,*args,**kwargs)
    def guard_selection(policy,context,reader,entry,**kwargs):
        assert reader.revision!=head, 'proposed policy was used to evaluate selection'
        return selected(policy,context,reader,entry,**kwargs)
    monkeypatch.setattr(RepositoryReader,'_document',guard);monkeypatch.setattr(qa,'select_query',guard_selection)
    report=repository_report(audit_collection,load_config(audit_collection),base,query_context=AUDIT_CONTEXT,query_policy_revision=base,query_head=head)
    assert not report['blockers'] and any(x['reason']=='dynamic_query_requalification_required' for x in report['pending_reviews'])
    assert report['query_revalidation']['audit_authority']=='global_integrator_caller_trust'
    assert report['query_revalidation']['context_scope']=='query_recomputation_only_not_auditor_acl'
