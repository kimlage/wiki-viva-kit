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
from wiki_core.context_packet import validate_result, _context_view
from wiki_core.context_impact import assess_impact, ImpactError
from wiki_core.detectors import scan_text
from wiki_core.information_relations import operational_consumption_edges
from wiki_core.repository_reader import RepositoryReader

class RequirementError(ValueError): pass

def _fresh(root,policy):
    if not getattr(policy,'_binding',None) or Path(policy._binding[0])!=Path(root).resolve(): raise RequirementError('unbound policy')
    return policy.fresh()

def assess_approved_impact(root,policy,*,consumers,before,after,destination_context,**kwargs):
    """Derive edges from approved consumer pages and expose only authorized impact."""
    policy=_fresh(root,policy)
    if not isinstance(consumers,list) or not consumers or len(consumers)>1000: raise RequirementError('bounded consumer paths required')
    reader=RepositoryReader(root,policy.policy_revision); edges=[]
    for path in dict.fromkeys(consumers):
        try: path=safe_path(path)
        except PolicyError as exc: raise RequirementError('invalid consumer') from exc
        if policy.owner_of(path)!=destination_context or not policy.permits(destination_context,'read',path): raise RequirementError('consumer not authorized')
        try: page=reader.read(path)
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

def requirements_from_result(root,policy,*,packet,result,output_path,proposal_head,temporal,max_age_days):
    """Propose page requirements from reported reads; never write a page.

    Git bytes are verified at input, current base and proposal output. The task
    result reports its reads; this is not proof of semantic comprehension.
    """
    policy=_fresh(root,policy)
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
    if subprocess.run(['git','-C',str(root),'merge-base','--is-ancestor',packet['policy_revision'],policy.policy_revision],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode: raise RequirementError('packet policy revision is not an approved ancestor')
    if packet['context']!=_context_view(policy,packet['context_id']): raise RequirementError('packet context policy changed')
    expected_read_set=[{k:item[k] for k in ('ref','section','field','revision')} for item in packet['inputs']]
    if packet['declared_read_set']!=expected_read_set: raise RequirementError('packet read set differs from inputs')
    if any(item['revision'] != (packet['policy_revision'] if item['kind']=='mandatory' else packet['content_revision']) for item in packet['inputs']): raise RequirementError('packet input revisions differ')

    try: output_path=safe_path(output_path)
    except PolicyError as exc: raise RequirementError('invalid output') from exc
    context=packet['context_id']
    if policy.owner_of(output_path)!=context or not policy.permits(context,'read',output_path): raise RequirementError('output not authorized')
    if output_path not in {c['path'] for c in result['changes'] if c['action'] in ('created','modified')}: raise RequirementError('output absent from result')
    source_revision=packet['content_revision']
    if not isinstance(source_revision,str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}',source_revision): raise RequirementError('packet content revision is not fixed')
    if subprocess.run(['git','-C',str(root),'merge-base','--is-ancestor',source_revision,proposal_head],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode: raise RequirementError('packet content revision is not an ancestor of proposal')
    diff=subprocess.run(['git','-C',str(root),'diff','--no-ext-diff','--no-textconv','--no-renames','--name-only','-z',source_revision,proposal_head,'--',output_path],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    if diff.returncode or diff.stdout != output_path.encode('utf-8')+b'\0': raise RequirementError('output was not changed by proposal')
    if subprocess.run(['git','-C',str(root),'merge-base','--is-ancestor',proposal_head,policy.policy_revision],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:
        raise RequirementError('proposal is not incorporated in approved revision')
    current=RepositoryReader(root,policy.policy_revision); proposed=RepositoryReader(root,proposal_head)
    try:
        approved_output=current.read(output_path); proposal_output=proposed.read(output_path)
    except ValueError as exc: raise RequirementError('approved output unavailable') from exc
    if approved_output['content_sha256']!=proposal_output['content_sha256']: raise RequirementError('approved output differs from proposal')
    if any(x.category=='secret' for x in scan_text(approved_output['text'])): raise RequirementError('secret detected in output')
    observed={json.dumps(x,sort_keys=True) for x in result['read_coverage']['observed_refs']}
    mandatory=[]; seen=set()
    for c in policy.lineage(context):
        for key in ('instructions','skills','templates'):
            for ref in c[key]:
                if ref not in seen:
                    mandatory.append((ref,c['id'],f"mandatory {key} from {c['id']}")); seen.add(ref)
    actual=[(x['ref'],x['producer'],x['reason']) for x in packet['inputs'] if x['kind']=='mandatory']
    if actual!=mandatory or any(x['kind']!='mandatory' for x in packet['inputs'][:len(mandatory)]) or any(x['kind']=='mandatory' for x in packet['inputs'][len(mandatory):]): raise RequirementError('mandatory policy inputs changed')
    if any(x['section'] is not None or x['field'] is not None or x['use'] is not None or x['classification'] is not None for x in packet['inputs'][:len(mandatory)]): raise RequirementError('mandatory policy input must be complete')
    if packet['selected_text_bytes']!=sum(x['byte_length'] for x in packet['inputs']): raise RequirementError('invalid selected text accounting')
    requirements=[]; self_input_read=False
    for item in packet['inputs']:
        if not isinstance(item.get('revision'),str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}',item['revision']): raise RequirementError('reported input revision is not fixed')
        readref={k:item[k] for k in ('ref','section','field','revision')}
        if json.dumps(readref,sort_keys=True) not in observed: raise RequirementError('input was not reported read')
        if any(within(item['ref'], scope) for scope in policy.effective[context]['deny']['read']): raise RequirementError('input authorization unavailable')
        if item['kind']=='evidence':
            if policy.connection(item['producer'],context,item['ref'],item['use'],item['classification'],section=item['section'],field=item['field'])!='approved': raise RequirementError('evidence authorization unavailable')
        try:
            historical=RepositoryReader(root,item['revision']).read(item['ref'],section=item['section'],field=item['field'])
            now=current.read(item['ref'],section=item['section'],field=item['field'])
        except ValueError as exc: raise RequirementError('reported input unavailable') from exc
        self_input = item['kind']=='evidence' and item['ref']==output_path
        raw=item['text'].encode('utf-8')
        if item['text']!=historical['text'] or item['byte_length']!=len(raw) or item['sha256']!=hashlib.sha256(raw).hexdigest(): raise RequirementError('reported input bytes differ')
        if item['origin']!=historical['origin'] or item['document_sha256']!=historical['content_sha256']: raise RequirementError('reported provenance differs')
        if item['sha256']!=historical['content_digest'] or (not self_input and item['sha256']!=now['content_digest']): raise RequirementError('reported input changed')
        if self_input: self_input_read=True
        if any(x.category=='secret' for x in scan_text(now['text'])): raise RequirementError('secret detected in input')
        if item['kind']=='evidence' and not self_input:
            selector=('section:'+item['section'].removeprefix('section:') if item['section'] is not None else 'field:'+item['field'] if item['field'] is not None else '*')
            entry={'target':item['ref'],'fields':[selector],'temporal':temporal,'max_age_days':max_age_days,'consumed_revision':item['revision'],'use':item['use'],'classification':item['classification']}
            if entry not in requirements: requirements.append(entry)
    if any(x.category=='secret' for x in scan_text(json.dumps(requirements,ensure_ascii=False))): raise RequirementError('secret detected in requirement metadata')
    policy.fresh()
    output={'schema_version':'wiki.context-requirements/v1','output_path':output_path,'approved_revision':policy.policy_revision,'proposal_head':proposal_head,'task_id':packet['task_id'],'packet_digest':packet['packet_digest'],'information_requirements':requirements,'self_input_read':self_input_read,'read_claim':'reported_not_verified','write':'not_performed'}
    if any(f.category=='secret' for f in scan_text(json.dumps(output,ensure_ascii=False))): raise RequirementError('secret detected in requirement metadata')
    return output
