"""Bridge approved Markdown requirements and revision-bound task receipts.

No graph/receipt is persisted here: the page remains the canonical declaration.
"""
from __future__ import annotations
import json
import hashlib
import re
import subprocess
from pathlib import Path
from wiki_core.context_policy import PolicyError, safe_path, within
from wiki_core.context_packet import validate_result, _context_view, guarded_context_read, declared_reads_from_inputs
from wiki_core.context_impact import assess_impact, ImpactError
from wiki_core.detectors import scan_text
from wiki_core.information_relations import operational_consumption_edges
from wiki_core.repository_reader import RepositoryReader
from wiki_core.git_env import local_git_environment, local_git_executable
from wiki_core.context_selection import revalidate_packet_queries, requirement_query, select_query, same_selection, reproduce_query

class RequirementError(ValueError): pass

def _fresh(root,policy):
    if getattr(policy, 'format_version', None) not in (None, 'folder'): raise RequirementError('unsupported policy format')
    if not getattr(policy,'_binding',None) or Path(policy._binding[0])!=Path(root).resolve(): raise RequirementError('unbound policy')
    return policy.fresh()

def assess_approved_impact(root,policy,*,consumers,before,after,destination_context,**kwargs):
    """Derive edges from approved consumer pages and expose only authorized impact."""
    policy=_fresh(root,policy)
    from wiki_core.context_impact import _folder_context, _folder_ref
    try: _folder_context(root, policy, destination_context)
    except ImpactError as exc: raise RequirementError('folder context requires authorized requalification') from exc
    if not isinstance(consumers,list) or not consumers or len(consumers)>1000: raise RequirementError('bounded consumer paths required')
    reader=RepositoryReader(root,policy.policy_revision); edges=[]
    for path in dict.fromkeys(consumers):
        try: path=safe_path(path)
        except PolicyError as exc: raise RequirementError('invalid consumer') from exc
        if policy.owner_of(path)!=destination_context or not policy.permits(destination_context,'read',path): raise RequirementError('consumer not authorized')
        try: _folder_ref(root, policy, path)
        except ImpactError as exc: raise RequirementError('consumer unavailable') from exc
        try: page=guarded_context_read(reader,policy,path)
        except ValueError as exc: raise RequirementError('approved consumer unavailable') from exc
        if any(f.category=='secret' for f in scan_text(page['text'])): raise RequirementError('secret detected in consumer')
        # Requirements use explicit repo paths. No global page-ID lookup or
        # unauthorized source blob is read during this resolution.
        def resolve(ref):
            try: return [safe_path(ref)] if '/' in ref or ref.endswith('.md') else []
            except PolicyError: return []
        try:
            derived=operational_consumption_edges(Path(root),path,page['frontmatter'],page['body'],resolve)
        except (ValueError,TypeError) as exc: raise RequirementError('invalid approved information requirement') from exc
        edges.extend(e for e in derived if e.get('field')=='information_requirements')
    # Raw edges can contain protected source metadata and remain internal.
    result=assess_impact(root,policy,{'edges':edges},before=before,after=after,destination_context=destination_context,**kwargs)
    policy.fresh()
    return result

def requirements_from_result(root,policy,*,packet,result,output_path,proposal_head,temporal,max_age_days,trusted_additional_readers=(),trusted_binding=None):
    """Propose page requirements from reported reads; never write a page.

    Git bytes are verified at input, current base and proposal output. The task
    result reports its reads; this is not proof of semantic comprehension.
    """
    if getattr(policy, 'format_version', None) != 'folder':
        raise RequirementError('new requirements require folder authority; v1 is historical only')
    from wiki_core.context_packet import _check_trusted_binding
    try: _check_trusted_binding(root, policy, packet.get('context_id') if isinstance(packet, dict) else None,
                                trusted_binding, trusted_additional_readers)
    except PolicyError as exc: raise RequirementError('host binding unavailable') from exc
    policy=_fresh(root,policy)
    folder_mode = getattr(policy, 'format_version', None) == 'folder'
    if not isinstance(packet, dict) or folder_mode != (packet.get('authority_format') == 'folder'):
        raise RequirementError('packet authority format differs; requalification required')
    packet_readers = packet.get('additional_readers', ())
    if (not isinstance(trusted_additional_readers, (tuple, list)) or not isinstance(packet_readers, (tuple, list))
            or tuple(packet_readers) != tuple(trusted_additional_readers)):
        raise RequirementError('additional reader host binding unavailable')
    if temporal not in ('current','historical') or type(max_age_days) is not int or not 0<=max_age_days<=3650: raise RequirementError('invalid temporal policy')
    if not isinstance(proposal_head,str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}',proposal_head): raise RequirementError('fixed proposal SHA required')
    try: validate_result(result,packet)
    except (PolicyError,KeyError,TypeError) as exc: raise RequirementError('invalid packet or result') from exc
    if result['status']!='completed': raise RequirementError('completed task required')
    from jsonschema import ValidationError, validate
    try:
        schema=json.loads((Path(__file__).resolve().parents[1]/'docs/references/schemas/wiki-task-context-v1.schema.json').read_text(encoding='utf-8'))
        validate(packet,schema)
    except (ValidationError,OSError,ValueError) as exc: raise RequirementError('invalid packet contract') from exc
    if any(f.category=='secret' for f in scan_text(json.dumps({'packet':packet,'result':result},ensure_ascii=False))): raise RequirementError('secret detected in task metadata')
    encoded=json.dumps(packet,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
    if len(encoded)!=packet['bytes_used'] or len(encoded)>packet['max_bytes']: raise RequirementError('invalid packet byte accounting')
    if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}',packet['policy_revision']): raise RequirementError('packet policy revision is not fixed')
    if subprocess.run([local_git_executable(), '--no-lazy-fetch','-C',str(root),'merge-base','--is-ancestor',packet['policy_revision'],policy.policy_revision],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=local_git_environment()).returncode: raise RequirementError('packet policy revision is not an approved ancestor')
    automatic_count = 0
    if folder_mode:
        from wiki_core.context_packet import build_packet, qualify_folder_context, _qualify_trusted_producers
        try:
            qualify_folder_context(root, policy, packet['context_id'], packet['entry_folder'], packet['entry_index'], packet['max_bytes'],additional_readers=trusted_additional_readers)
            automatic = build_packet(root, policy, packet['context_id'], packet['content_revision'], [], packet['max_bytes'],
                task_id=packet['task_id'], goal=packet['goal'], output=packet['output'], integrator=packet['integrator'],
                omissions=packet['coverage']['missing'], entry_folder=packet['entry_folder'], entry_index=packet['entry_index'],additional_readers=trusted_additional_readers)
            keys = ('kind', 'ref', 'producer', 'reason', 'section', 'field', 'use', 'classification')
            automatic_count = len(automatic['inputs'])
            if ([{key: row[key] for key in keys} for row in packet['inputs'][:automatic_count]] !=
                    [{key: row[key] for key in keys} for row in automatic['inputs']]):
                raise ValueError('folder context input selection changed')
            evidence = []
            for item in packet['inputs'][automatic_count:]:
                if item['kind'] != 'evidence' or 'query_id' in item: continue
                row = {key: item[key] for key in ('ref', 'producer', 'reason', 'use', 'classification')}
                for key in ('section', 'field'):
                    if item[key] is not None: row[key] = item[key]
                evidence.append(row)
            _qualify_trusted_producers(root, policy, packet['context_id'], evidence, packet['max_bytes'],
                                       trusted_binding=trusted_binding, additional_readers=trusted_additional_readers)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            raise RequirementError('folder context input requires requalification') from exc
    if packet['context']!=_context_view(policy,packet['context_id']): raise RequirementError('packet context policy changed')
    expected_read_set=declared_reads_from_inputs(packet['inputs'], folder_mode=folder_mode)
    if packet['declared_read_set']!=expected_read_set: raise RequirementError('packet read set differs from inputs')
    if any(item['revision'] != (packet['policy_revision'] if (item['kind']=='mandatory' or (folder_mode and i < automatic_count)) else packet['content_revision']) for i, item in enumerate(packet['inputs'])): raise RequirementError('packet input revisions differ')

    try: output_path=safe_path(output_path)
    except PolicyError as exc: raise RequirementError('invalid output') from exc
    context=packet['context_id']
    if policy.owner_of(output_path)!=context or not policy.permits(context,'read',output_path): raise RequirementError('output not authorized')
    for reader_context in trusted_additional_readers:
        if policy._connection(context,reader_context,output_path,'interpretation','context',qualified=False) != 'approved':
            raise RequirementError('additional reader not authorized for output')
    if folder_mode:
        from wiki_core.context_impact import _folder_ref
        try: _folder_ref(root, policy, output_path)
        except ImpactError as exc: raise RequirementError('output unavailable') from exc
    if output_path not in {c['path'] for c in result['changes'] if c['action'] in ('created','modified')}: raise RequirementError('output absent from result')
    source_revision=packet['content_revision']
    if not isinstance(source_revision,str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}',source_revision): raise RequirementError('packet content revision is not fixed')
    if subprocess.run([local_git_executable(), '--no-lazy-fetch','-C',str(root),'merge-base','--is-ancestor',source_revision,proposal_head],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=local_git_environment()).returncode: raise RequirementError('packet content revision is not an ancestor of proposal')
    diff=subprocess.run([local_git_executable(), '--no-lazy-fetch','-C',str(root),'diff','--no-ext-diff','--no-textconv','--no-renames','--name-only','-z',source_revision,proposal_head,'--',output_path],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env=local_git_environment())
    if diff.returncode or diff.stdout != output_path.encode('utf-8')+b'\0': raise RequirementError('output was not changed by proposal')
    if subprocess.run([local_git_executable(), '--no-lazy-fetch','-C',str(root),'merge-base','--is-ancestor',proposal_head,policy.policy_revision],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=local_git_environment()).returncode:
        raise RequirementError('proposal is not incorporated in approved revision')
    current=RepositoryReader(root,policy.policy_revision); proposed=RepositoryReader(root,proposal_head)
    try:
        approved_output=guarded_context_read(current,policy,output_path); proposal_output=guarded_context_read(proposed,policy,output_path)
    except ValueError as exc: raise RequirementError('approved output unavailable') from exc
    if approved_output['content_sha256']!=proposal_output['content_sha256']: raise RequirementError('approved output differs from proposal')
    if any(x.category=='secret' for x in scan_text(approved_output['text'])): raise RequirementError('secret detected in output')
    observed={json.dumps(x,sort_keys=True) for x in result['read_coverage']['observed_refs']}
    mandatory=[]; seen=set()
    if folder_mode:
        mandatory = [(x['ref'], x['producer'], x['reason']) for x in automatic['inputs'] if x['kind'] == 'mandatory']
    else:
        for c in policy.lineage(context):
            for key in ('instructions','skills','templates'):
                for ref in c[key]:
                    if ref not in seen:
                        mandatory.append((ref,c['id'],f"mandatory {key} from {c['id']}")); seen.add(ref)
    actual=[(x['ref'],x['producer'],x['reason']) for x in packet['inputs'] if x['kind']=='mandatory']
    if actual!=mandatory or any(x['kind']!='mandatory' for x in packet['inputs'][:len(mandatory)]) or any(x['kind']=='mandatory' for x in packet['inputs'][len(mandatory):]): raise RequirementError('mandatory policy inputs changed')
    if any(x['section'] is not None or x['field'] is not None or x['use'] is not None or x['classification'] is not None for x in packet['inputs'][:len(mandatory)]): raise RequirementError('mandatory policy input must be complete')
    if packet['selected_text_bytes']!=sum(x['byte_length'] for x in packet['inputs']): raise RequirementError('invalid selected text accounting')
    try: revalidate_packet_queries(policy,packet,RepositoryReader(root,source_revision),current)
    except (ValueError,KeyError,TypeError) as exc: raise RequirementError('query selection cannot be revalidated') from exc
    requirements=[]; self_input_read=False
    for row in packet.get('query_selections', []):
        e = row['request']
        if e['target']==output_path or output_path in {m['ref'] for m in row['members']}: raise RequirementError('query anchor cannot be its own consumer')
        requirements.append({'target':e['target'],'fields':['*'],'temporal':temporal,'max_age_days':max_age_days,
            'consumed_revision':row['revision'],'use':e['use'],'classification':e['classification'],
            'query':e['query'],'members_digest':row['members_digest'],'selected_digest':row['selected_digest'],
            'query_policy_revision':row['policy_revision'],'authority_digest':row['authority_digest'],
            **({key:row[key] for key in ('authority_format','entry_folder','entry_index')} if row.get('authority_format') else {})})
    for item in packet['inputs']:
        if not isinstance(item.get('revision'),str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}',item['revision']): raise RequirementError('reported input revision is not fixed')
        readref={k:item[k] for k in ('ref','section','field','revision')}
        if json.dumps(readref,sort_keys=True) not in observed: raise RequirementError('input was not reported read')
        if any(within(item['ref'], scope) for scope in policy.effective[context]['deny']['read']): raise RequirementError('input authorization unavailable')
        if item['kind']=='evidence':
            if policy.connection(item['producer'],context,item['ref'],item['use'],item['classification'],section=item['section'],field=item['field'])!='approved': raise RequirementError('evidence authorization unavailable')
        elif folder_mode and policy.connection(item['producer'],context,item['ref'],'interpretation','context')!='approved':
            raise RequirementError('mandatory input authorization unavailable')
        for reader_context in trusted_additional_readers:
            if policy._connection(item['producer'],reader_context,item['ref'],item['use'] or 'interpretation',
                                  item['classification'] or 'context',section=item['section'],field=item['field'],
                                  qualified=False) != 'approved':
                raise RequirementError('additional reader input authorization unavailable')
        if folder_mode:
            try: _folder_ref(root, policy, item['ref'])
            except ImpactError as exc: raise RequirementError('reported input unavailable') from exc
        try:
            historical=guarded_context_read(RepositoryReader(root,item['revision']),policy,item['ref'],section=item['section'],field=item['field'])
            now=guarded_context_read(current,policy,item['ref'],section=item['section'],field=item['field'])
        except ValueError as exc: raise RequirementError('reported input unavailable') from exc
        self_input = item['kind']=='evidence' and item['ref']==output_path
        raw=item['text'].encode('utf-8')
        if item['text']!=historical['text'] or item['byte_length']!=len(raw) or item['sha256']!=hashlib.sha256(raw).hexdigest(): raise RequirementError('reported input bytes differ')
        if item['origin']!=historical['origin'] or item['document_sha256']!=historical['content_sha256']: raise RequirementError('reported provenance differs')
        if item['sha256']!=historical['content_digest'] or (not self_input and item['sha256']!=now['content_digest']): raise RequirementError('reported input changed')
        if self_input: self_input_read=True
        if any(x.category=='secret' for x in scan_text(now['text'])): raise RequirementError('secret detected in input')
        if item['kind']=='evidence' and not self_input and 'query_id' not in item:
            selector=('section:'+item['section'].removeprefix('section:') if item['section'] is not None else 'field:'+item['field'] if item['field'] is not None else '*')
            entry={'target':item['ref'],'fields':[selector],'temporal':temporal,'max_age_days':max_age_days,'consumed_revision':item['revision'],'use':item['use'],'classification':item['classification']}
            if entry not in requirements: requirements.append(entry)
        elif folder_mode and item['kind']=='mandatory':
            entry={'target':item['ref'],'fields':['*'],'temporal':'current','max_age_days':max_age_days,
                   'consumed_revision':item['revision'],'use':'normative','classification':'context',
                   'source_kind':'mandatory','authority_format':'folder',
                   'entry_folder':packet['entry_folder'],'entry_index':packet['entry_index']}
            if entry not in requirements: requirements.append(entry)
    if any(x.category=='secret' for x in scan_text(json.dumps(requirements,ensure_ascii=False))): raise RequirementError('secret detected in requirement metadata')
    policy.fresh()
    output={'schema_version':'wiki.context-requirements/v1','output_path':output_path,'approved_revision':policy.policy_revision,'proposal_head':proposal_head,'task_id':packet['task_id'],'packet_digest':packet['packet_digest'],'information_requirements':requirements,'self_input_read':self_input_read,'read_claim':'reported_not_verified','write':'not_performed'}
    if folder_mode:
        output['coverage_missing'] = sorted(set(packet['coverage']['missing']) | set(result['read_coverage']['missing']))
    if any(f.category=='secret' for f in scan_text(json.dumps(output,ensure_ascii=False))): raise RequirementError('secret detected in requirement metadata')
    return output


def revalidate_approved_queries(root, policy, *, consumer, context_id):
    """Useful current set/byte checks, explicitly separate from factual readiness."""
    from wiki_core.information_relations import information_requirements
    policy = _fresh(root, policy); consumer = safe_path(consumer)
    from wiki_core.context_impact import _folder_context, _folder_ref
    try:
        _folder_context(root, policy, context_id)
        _folder_ref(root, policy, consumer)
    except ImpactError as exc: raise RequirementError('folder context requires authorized requalification') from exc
    if policy.owner_of(consumer) != context_id or not policy.permits(context_id, 'read', consumer):
        raise RequirementError('consumer not authorized')
    current = RepositoryReader(root, policy.policy_revision)
    page = guarded_context_read(current,policy,consumer)
    if any(f.category == 'secret' for f in scan_text(page['text'])): raise RequirementError('secret detected in consumer')
    requirements = information_requirements(page['frontmatter'], lambda p: [p] if isinstance(p,str) and p in current.paths else [])
    rows = []; query_read_budget = [32_000_000]
    for req in requirements:
        if 'query' not in req: continue
        if req['target']==consumer: raise RequirementError('query anchor cannot be its own consumer')
        prior, _, _ = reproduce_query(policy, context_id, RepositoryReader(root, req['consumed_revision']), requirement_query(req), policy_revision=req['query_policy_revision'], expected_authority=req['authority_digest'], read_budget=query_read_budget, authority_format=req.get('authority_format'), entry_folder=req.get('entry_folder'), entry_index=req.get('entry_index'))
        if any(prior[k] != req[k] for k in ('members_digest', 'selected_digest')):
            raise RequirementError('canonical query receipt differs from consumed selection')
        if consumer in {m['ref'] for m in prior['members']}: raise RequirementError('query consumer cannot be a member')
        now, _, _ = select_query(policy, context_id, current, requirement_query(req), read_budget=query_read_budget, entry_folder=req.get('entry_folder'), entry_index=req.get('entry_index'))
        if consumer in {m['ref'] for m in now['members']}: raise RequirementError('query consumer cannot be a member')
        rows.append({'target':req['target'],'query_id':prior['query_id'],
            'members_equivalent':prior['members_digest']==now['members_digest'],
            'selected_bytes_equivalent':prior['selected_digest']==now['selected_digest'],
            'state':'equivalent' if same_selection(prior,now) else 'review_required'})
    policy.fresh()
    return {'schema_version':'wiki.context-query-revalidation/v1','consumer':consumer,'policy_revision':policy.policy_revision,
        'queries':rows,'equivalent':all(row['state']=='equivalent' for row in rows),
        'coverage':'declared_queries_in_authorized_owner_scope_only','fact_freshness':'not_assessed','effect':'not_performed'}
