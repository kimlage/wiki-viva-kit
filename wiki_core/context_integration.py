"""Read-only preflight for a short branch; does not approve, merge or run code."""
from __future__ import annotations
import re
from copy import deepcopy
import json
import subprocess
from pathlib import Path
from wiki_core.context_policy import PolicyError, safe_path, is_context_instruction
from wiki_core.context_packet import build_packet, validate_result
from wiki_core.repository_reader import RepositoryReader
from wiki_core.git_env import local_git_environment, local_git_executable
from wiki_core.detectors import scan_text
from wiki_core.information_relations import information_requirements
from wiki_core.context_selection import packet_queries, revalidate_packet_queries, requirement_query, select_query, same_selection, reproduce_query, normalize_query

class IntegrationError(ValueError): pass

def _git(root,*args):
    p=subprocess.run([local_git_executable(), '--no-lazy-fetch','-C',str(root),*args],stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=local_git_environment())
    if p.returncode: raise IntegrationError('Git precondition failed')
    return p.stdout

class _QueryReuse:
    """Operation-local reuse; every hit consumes the same logical read budget."""
    def __init__(self, root, policy, context_id, budget, *readers):
        self.root, self.policy, self.context_id, self.budget = root, policy, context_id, budget
        self.readers = {reader.revision: reader for reader in readers}
        self.cache = {}

    def reader(self, revision):
        if revision in self.readers:
            return self.readers[revision]
        reader = RepositoryReader(self.root, revision)
        if len(self.readers) < 18:
            self.readers[revision] = reader
        return reader

    def get(self, mode, reader, entry, *, policy_revision=None, expected_authority=None):
        normalized = normalize_query(entry)
        key = (mode, reader.revision, self.policy.policy_revision, self.context_id,
               policy_revision, expected_authority,
               json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
        if key in self.cache:
            # An immutable content cache does not itself grant authority.
            self.policy.fresh()
            receipt, cost = self.cache[key]
            if cost > self.budget[0]: raise PolicyError('query operation byte limit exceeded')
            self.budget[0] -= cost
            return deepcopy(receipt)
        before = self.budget[0]
        if mode == 'historical':
            receipt, _, _ = reproduce_query(self.policy, self.context_id, reader, normalized,
                policy_revision=policy_revision, expected_authority=expected_authority, read_budget=self.budget)
        else:
            receipt, _, _ = select_query(self.policy, self.context_id, reader, normalized, read_budget=self.budget)
        if len(self.cache) < 96:
            self.cache[key] = (deepcopy(receipt), before - self.budget[0])
        return receipt


def preflight(root, policy, *, context_id, base, head, branch, packet, result):
    """Return a review candidate, never an approval or merge authorization.

    External independent reviewer and final-head gates remain mandatory. The
    caller is responsible for ensuring its trusted ref is independently kept.
    """
    if getattr(policy, 'format_version', None): raise IntegrationError('v2 integration is unavailable; v1 results require explicit migration')
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
        if item['kind']!='evidence' or 'query_id' in item: continue
        entry={k:item[k] for k in ('ref','producer','reason','use','classification')}
        for k in ('section','field'):
            if item[k] is not None: entry[k]=item[k]
        evidence.append(entry)
    try:
        rebuilt=build_packet(root,policy,context_id,packet['content_revision'],evidence,packet['max_bytes'],adapter_report=packet['capability_evidence'],required_capabilities=packet['required_capabilities'],omissions=packet['coverage']['missing'],task_id=packet['task_id'],goal=packet['goal'],output=packet['output'],integrator=packet['integrator'],queries=packet_queries(packet))
    except (PolicyError, ValueError, KeyError, TypeError) as exc: raise IntegrationError('packet authorization cannot be reproduced') from exc
    if rebuilt!=packet: raise IntegrationError('packet contents cannot be reproduced')
    canonical_query_budget=[32_000_000]
    query_reuse = _QueryReuse(root, policy, context_id, canonical_query_budget, base_reader, proposal)
    try: revalidate_packet_queries(policy,packet,RepositoryReader(root,packet['content_revision']),base_reader,read_budget=canonical_query_budget)
    except (ValueError,KeyError,TypeError) as exc: raise IntegrationError('query selection cannot be revalidated') from exc
    try: revalidate_packet_queries(policy,packet,RepositoryReader(root,packet['content_revision']),proposal,read_budget=canonical_query_budget)
    except (ValueError,KeyError,TypeError) as exc: raise IntegrationError('query selection changed in proposal') from exc
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
        if is_context_instruction(path): raise IntegrationError('folder instruction change requires separate policy review')
        if path in normative: raise IntegrationError('normative input requires separate policy review')
        if policy.owner_of(path)!=context_id or not policy.permits(context_id,'write',path): raise IntegrationError('write outside context')
        if not policy.permits(context_id,'read',path): raise IntegrationError('proposal read denied')
        if status=='D' and path.endswith('.md') and path in base_reader.paths:
            if 'folder_source_provenance' in base_reader.read(path)['frontmatter']:
                raise IntegrationError('folder source provenance requires the v2 integration path')
        if status!='D':
            try: proposed_file=proposal.read(path); text=proposed_file['text']
            except ValueError as exc: raise IntegrationError('unsupported or unsafe proposed file') from exc
            if any(x.category=='secret' for x in scan_text(text)): raise IntegrationError('secret detected in proposal')
            if path.endswith('.md'):
                prior=base_reader.read(path)['frontmatter'] if path in base_reader.paths else {}
                if 'folder_source_provenance' in prior or 'folder_source_provenance' in proposed_file['frontmatter']:
                    raise IntegrationError('folder source provenance requires the v2 integration path')
                raw_before=prior.get('information_requirements',[])
                raw_after=proposed_file['frontmatter'].get('information_requirements',[])
                has_query=isinstance(raw_after,list) and any(isinstance(r,dict) and 'query' in r for r in raw_after)
                has_normative=isinstance(raw_after,list) and any(isinstance(r,dict) and r.get('source_kind')=='mandatory' for r in raw_after)
                if raw_before!=raw_after or has_query or has_normative:
                    def resolve(ref): return [ref] if isinstance(ref,str) and ref in base_reader.paths else []
                    try: declared=information_requirements(proposed_file['frontmatter'],resolve)
                    except (ValueError,TypeError) as exc: raise IntegrationError('invalid proposed information requirement') from exc
                    # Only newly introduced/changed requirements need this
                    # task's proof; legacy entries are not silently upgraded.
                    try: previous=information_requirements(prior,resolve)
                    except (ValueError,TypeError) as exc: raise IntegrationError('invalid existing information requirement') from exc
                    for requirement in declared:
                        if requirement in previous:
                            if requirement.get('source_kind') == 'mandatory':
                                from wiki_core.context_normative import normative_history
                                ref=requirement['target']; consumed=requirement['consumed_revision']
                                if not normative_history(policy,context_id,ref,consumed):
                                    raise IntegrationError('existing normative requirement requires requalification')
                                item=next((x for x in packet['inputs'] if x['kind']=='mandatory' and x['ref']==ref),None)
                                observed={k:item[k] for k in ('ref','section','field','revision')} if item else None
                                if item is None or observed not in result['read_coverage']['observed_refs']:
                                    raise IntegrationError('existing normative requirement requires reported read')
                                try: previous_rule=RepositoryReader(root,consumed).read(ref)
                                except ValueError as exc: raise IntegrationError('existing normative input unavailable') from exc
                                if previous_rule['content_digest']!=item['sha256']:
                                    raise IntegrationError('existing normative requirement changed; reread and update')
                            if 'query' in requirement:
                                try:
                                    consumed_reader=query_reuse.reader(requirement['consumed_revision'])
                                    entry=requirement_query(requirement)
                                    old_query=query_reuse.get('historical',consumed_reader,entry,policy_revision=requirement['query_policy_revision'],expected_authority=requirement['authority_digest'])
                                    now_query=query_reuse.get('base',base_reader,entry)
                                    proposed_query=query_reuse.get('proposal',proposal,entry)
                                    if path in {m['ref'] for m in [*old_query['members'],*now_query['members'],*proposed_query['members']]}: raise IntegrationError('query consumer cannot be a member')
                                    if not same_selection(old_query,proposed_query): raise IntegrationError('query selection changed in proposal')
                                    if any(old_query[k]!=requirement[k] for k in ('members_digest','selected_digest')) or not same_selection(old_query,now_query):
                                        raise IntegrationError('existing query requirement changed; reread and update its canonical receipt')
                                except ValueError as exc: raise IntegrationError('existing query requirement cannot be revalidated') from exc
                            continue
                        if requirement['target']==path: raise IntegrationError('new self dependency is not allowed')
                        consumed=requirement.get('consumed_revision')
                        if consumed is None: raise IntegrationError('new requirement is unpinned')
                        if 'query' in requirement:
                            rows = [r for r in packet.get('query_selections', []) if r['request']['target']==requirement['target']
                                and r['request']['query']==requirement['query'] and r['members_digest']==requirement['members_digest']
                                and r['selected_digest']==requirement['selected_digest'] and r['revision']==consumed
                                and r['policy_revision']==requirement['query_policy_revision'] and r['authority_digest']==requirement['authority_digest']
                                and r['request']['use']==requirement['use'] and r['request']['classification']==requirement['classification']]
                            if not rows or any(r['query_id'] not in result['read_coverage'].get('observed_queries', []) for r in rows):
                                raise IntegrationError('query requirement does not match task selection')
                            if any(path in {m['ref'] for m in r['members']} for r in rows): raise IntegrationError('query consumer cannot be a member')
                            continue
                        for selector in requirement['fields']:
                            def matches(item):
                                normative = requirement.get('source_kind') == 'mandatory'
                                if item['kind'] != ('mandatory' if normative else 'evidence') or item['ref']!=requirement['target'] or item['revision']!=consumed: return False
                                observed={k:item[k] for k in ('ref','section','field','revision')}
                                if observed not in result['read_coverage']['observed_refs']: return False
                                if normative:
                                    return selector == '*' and item['section'] is None and item['field'] is None and consumed == packet['policy_revision']
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
