"""Read-only preflight for a short branch; does not approve, merge or run code."""
from __future__ import annotations
import re
import json
import subprocess
from pathlib import Path
from wiki_core.context_policy import PolicyError, safe_path
from wiki_core.context_packet import build_packet, validate_result
from wiki_core.repository_reader import RepositoryReader
from wiki_core.detectors import scan_text
from wiki_core.information_relations import information_requirements

class IntegrationError(ValueError): pass

def _git(root,*args):
    p=subprocess.run(['git','-C',str(root),*args],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if p.returncode: raise IntegrationError('Git precondition failed')
    return p.stdout

def preflight(root, policy, *, context_id, base, head, branch, packet, result):
    """Return a review candidate, never an approval or merge authorization.

    External independent reviewer and final-head gates remain mandatory. The
    caller is responsible for ensuring its trusted ref is independently kept.
    """
    if not getattr(policy,'_binding',None) or Path(policy._binding[0])!=Path(root).resolve(): raise IntegrationError('unbound policy')
    policy=policy.fresh()
    if not isinstance(branch,str) or not re.fullmatch(r'wiki/[A-Za-z0-9][A-Za-z0-9._-]*',branch) or '..' in branch or branch.endswith('.'):
        raise IntegrationError('invalid short branch')
    base_reader=RepositoryReader(root,base); proposal=RepositoryReader(root,head)
    if base_reader.revision!=policy.policy_revision: raise IntegrationError('approved base moved')
    branch_head=_git(root,'rev-parse','--verify','refs/heads/'+branch+'^{commit}').decode().strip()
    if branch_head!=proposal.revision: raise IntegrationError('branch head changed')
    _git(root,'merge-base','--is-ancestor',base_reader.revision,proposal.revision)
    try: validate_result(result,packet)
    except (PolicyError,KeyError,TypeError) as exc: raise IntegrationError('invalid task result or packet') from exc
    if packet.get('context_id')!=context_id or packet.get('policy_revision')!=policy.policy_revision or result['status']!='completed': raise IntegrationError('task or policy not current')
    evidence=[]
    for item in packet['inputs']:
        if item['kind']!='evidence': continue
        entry={k:item[k] for k in ('ref','producer','reason','use','classification')}
        for k in ('section','field'):
            if item[k] is not None: entry[k]=item[k]
        evidence.append(entry)
    try:
        rebuilt=build_packet(root,policy,context_id,packet['content_revision'],evidence,packet['max_bytes'],adapter_report=packet['capability_evidence'],required_capabilities=packet['required_capabilities'],omissions=packet['coverage']['missing'],task_id=packet['task_id'],goal=packet['goal'],output=packet['output'],integrator=packet['integrator'])
    except (PolicyError, ValueError, KeyError, TypeError) as exc: raise IntegrationError('packet authorization cannot be reproduced') from exc
    if rebuilt!=packet: raise IntegrationError('packet contents cannot be reproduced')
    # A historical read may still be used only if its selected bytes remain
    # identical at the current approved base; no fallback to a larger slice.
    for item in packet['inputs']:
        try: now=base_reader.read(item['ref'],section=item['section'],field=item['field'])
        except ValueError as exc: raise IntegrationError('consumed input unavailable at approved base') from exc
        if now['content_digest']!=item['sha256']: raise IntegrationError('consumed input changed since task')
    raw=_git(root,'diff','--no-ext-diff','--no-textconv','--no-renames','--name-status','-z',base_reader.revision,proposal.revision).split(b'\0')
    if raw and raw[-1]==b'': raw.pop()
    if len(raw)%2: raise IntegrationError('unsupported diff')
    actual=[]
    # Active normative inputs require the separate policy-review path even if
    # the acting context would otherwise have read/write access to the file.
    normative={ref for c in policy.contexts.values() for k in ('instructions','skills','templates') for ref in c[k]}
    for i in range(0,len(raw),2):
        try: status=raw[i].decode(); path=safe_path(raw[i+1].decode())
        except (UnicodeError,PolicyError) as exc: raise IntegrationError('invalid diff path') from exc
        if status not in ('A','M','D') or path.endswith('/context.yaml') or path=='context.yaml': raise IntegrationError('unsupported or policy change')
        if path in normative: raise IntegrationError('normative input requires separate policy review')
        if policy.owner_of(path)!=context_id or not policy.permits(context_id,'write',path): raise IntegrationError('write outside context')
        if not policy.permits(context_id,'read',path): raise IntegrationError('proposal read denied')
        if status!='D':
            try: proposed_file=proposal.read(path); text=proposed_file['text']
            except ValueError as exc: raise IntegrationError('unsupported or unsafe proposed file') from exc
            if any(x.category=='secret' for x in scan_text(text)): raise IntegrationError('secret detected in proposal')
            if path.endswith('.md'):
                prior=base_reader.read(path)['frontmatter'] if path in base_reader.paths else {}
                raw_before=prior.get('information_requirements',[])
                raw_after=proposed_file['frontmatter'].get('information_requirements',[])
                if raw_before!=raw_after:
                    def resolve(ref): return [ref] if isinstance(ref,str) and ref in base_reader.paths else []
                    try: declared=information_requirements(proposed_file['frontmatter'],resolve)
                    except (ValueError,TypeError) as exc: raise IntegrationError('invalid proposed information requirement') from exc
                    # Only newly introduced/changed requirements need this
                    # task's proof; legacy entries are not silently upgraded.
                    try: previous=information_requirements(prior,resolve)
                    except (ValueError,TypeError) as exc: raise IntegrationError('invalid existing information requirement') from exc
                    for requirement in declared:
                        if requirement in previous: continue
                        if requirement['target']==path: raise IntegrationError('new self dependency is not allowed')
                        consumed=requirement.get('consumed_revision')
                        if consumed is None: raise IntegrationError('new requirement is unpinned')
                        for selector in requirement['fields']:
                            def matches(item):
                                if item['kind']!='evidence' or item['ref']!=requirement['target'] or item['revision']!=consumed: return False
                                observed={k:item[k] for k in ('ref','section','field','revision')}
                                if observed not in result['read_coverage']['observed_refs']: return False
                                actual=('section:'+item['section'].removeprefix('section:') if item['section'] is not None else 'field:'+item['field'] if item['field'] is not None else '*')
                                wanted=selector if selector in ('*','body') or ':' in selector else 'field:'+selector
                                if wanted=='body' and actual=='*': wanted='*'
                                return actual==wanted and item['use']==requirement.get('use','interpret') and item['classification']==requirement.get('classification','internal')
                            if not any(matches(item) for item in packet['inputs']): raise IntegrationError('requirement does not match task evidence')
        actual.append({'path':path,'action':{'A':'created','M':'modified','D':'deleted'}[status]})
    if not actual: raise IntegrationError('empty proposal')
    if sorted(actual,key=lambda x:(x['path'],x['action']))!=sorted(result['changes'],key=lambda x:(x['path'],x['action'])): raise IntegrationError('result changes do not match branch')
    policy.fresh()
    if _git(root,'rev-parse','--verify','refs/heads/'+branch+'^{commit}').decode().strip()!=proposal.revision: raise IntegrationError('branch head changed')
    output={'schema_version':'wiki.context-integration/v1','state':'independent_review_required','context_id':context_id,'base':base_reader.revision,'head':proposal.revision,'branch':branch,'task_id':packet['task_id'],'packet_digest':packet['packet_digest'],'changes':actual,'review':'not_performed','gates':'not_performed','merge':'not_performed'}
    if any(x.category=='secret' for x in scan_text(json.dumps(output,ensure_ascii=False))): raise IntegrationError('secret detected in integration metadata')
    return output
