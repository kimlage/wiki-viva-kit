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
from tests.test_coordination_protected import bound_server
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
        'query_policy_revision':r['policy_revision'],'authority_digest':r['authority_digest']}

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


def test_canonical_cycle_preflight_merge_derive_inventory_revalidation_and_impact(collection):
    root=collection;base=git(root,'rev-parse','HEAD');p=packet(root);r=requirement(p)
    git(root,'checkout','-qb','wiki/query-task');declare(root,r);git(root,'add','.');git(root,'commit','-qm','query interpretation');head=git(root,'rev-parse','HEAD')
    done=result(p,[{'path':'finance/costs/result.md','action':'modified'}])
    assert preflight(root,policy(root),context_id='costs',base=base,head=head,branch='wiki/query-task',packet=p,result=done)['state']=='independent_review_required'
    forged=deepcopy(r);forged['query']['filters']={'status':'inactive'};declare(root,forged);git(root,'add','.');git(root,'commit','-qm','forged dependency')
    with pytest.raises(IntegrationError,match='query requirement'): preflight(root,policy(root),context_id='costs',base=base,head=git(root,'rev-parse','HEAD'),branch='wiki/query-task',packet=p,result=done)
    git(root,'reset','--hard',head);approve(root)  # Synthetic approval/merge simulation only.
    proposed=requirements_from_result(root,policy(root),packet=p,result=done,output_path='finance/costs/result.md',proposal_head=head,temporal='current',max_age_days=30)
    assert proposed['information_requirements']==[r]
    validate(proposed,json.loads((BASE/'docs/references/schemas/wiki-context-requirements-v1.schema.json').read_text()))
    inventory=authored_graph(root,load_config(root));edges,_=dependency_edges(inventory)
    edge=next(e for e in edges if 'query' in e.get('requirement',{}))
    assert edge['requirement']['query']==r['query'] and edge['prerequisite']==ANCHOR
    readiness=assess_information_use(inventory,'finance/costs/result.md',now=dt.datetime.now(dt.timezone.utc))
    assert not readiness['ready'] and 'information_query_requires_authorized_revalidation' in str(readiness)
    current_check=revalidate_approved_queries(root,policy(root),consumer='finance/costs/result.md',context_id='costs')
    validate(current_check,json.loads((BASE/'docs/references/schemas/wiki-context-query-revalidation-v1.schema.json').read_text()))
    assert current_check['equivalent']
    page(root,'new.md');after=commit(root)
    impact=assess_approved_impact(root,policy(root),consumers=['finance/costs/result.md'],before=head,after=after,destination_context='costs')
    assert len(impact['candidates'])==1 and impact['candidates'][0]['source']==ANCHOR
    assert impact['candidates'][0]['members_digest_before']!=impact['candidates'][0]['members_digest_after']
    validate(impact,json.loads((BASE/'docs/references/schemas/wiki-context-impact-v1.schema.json').read_text()))
    assert not revalidate_approved_queries(root,policy(root),consumer='finance/costs/result.md',context_id='costs')['equivalent']
    from wiki_core.context_impact import report_review
    report=report_review(root,policy(root),impact['candidates'][0],disposition='still_valid',reason='Synthetic reported review',evidence_revision=after)
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
    payload={'context_id':'costs','approved_revision':sha,'content_revision':sha,'task':task}
    assert srv.post('/api/coordination/protected/packet',payload,headers={})[0]==403
    status,response=srv.post('/api/coordination/protected/packet',payload,headers=headers)
    assert status==200;p=response['packet'];taskfile=tmp_path.parent/(tmp_path.name+'-query-request.json');taskfile.write_text(json.dumps(task))
    cmd=[sys.executable,str(BASE/'scripts/wiki_coordination.py'),'--root',str(root),'--context-id','costs','--approved-revision',sha,'--revision',sha,'--packet-request',str(taskfile)]
    assert json.loads(subprocess.check_output(cmd))['packet']==p
    empty=deepcopy(payload);empty['task']['queries']=[query(filters={'status':'absent'})]
    status,body=srv.post('/api/coordination/protected/packet',empty,headers=headers)
    assert status==200 and body['packet']['query_selections'][0]['members']==[]
    git(root,'checkout','-qb','wiki/http-query');declare(root,requirement(p));git(root,'add','.');git(root,'commit','-qm','canonical interpretation');head=git(root,'rev-parse','HEAD')
    done=result(p,[{'path':'finance/costs/result.md','action':'modified'}])
    check={'context_id':'costs','approved_revision':sha,'base':sha,'head':head,'branch':'wiki/http-query','packet':p,'result':done}
    status,checked=srv.post('/api/coordination/protected/preflight',check,headers=headers)
    assert status==200 and checked['preflight']['state']=='independent_review_required'
    approve(root)
    command=[sys.executable,str(BASE/'scripts/wiki_context_flow.py'),'--repo',str(root),'--approved-revision',head,'revalidate','--consumer','finance/costs/result.md','--context','costs']
    assert json.loads(subprocess.check_output(command))['equivalent']
    status,stale=srv.post('/api/coordination/protected/packet',payload,headers=headers)
    assert status==409 and stale['error_code']=='coordination_policy_unavailable' and 'packet' not in stale


def test_protected_limits_secrets_and_denied_scope_are_opaque(collection,bound_server):
    srv,token=bound_server;sha=git(collection,'rev-parse','HEAD');headers={ADMIN_SESSION_HEADER:token}
    payload={'context_id':'costs','approved_revision':sha,'content_revision':sha,'task':{**TASK,'max_bytes':50000,'evidence':[],'queries':[query()]}}
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
    sha=git(collection,'rev-parse','HEAD')
    command=[sys.executable,str(BASE/'scripts/wiki_coordination.py'),'--root',str(collection),'--context-id','costs','--approved-revision',sha,'--revision',sha,'--packet-request',str(taskfile)]
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
    assert error.value.code==400
    assert 'packet' not in json.loads(error.value.read())


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
