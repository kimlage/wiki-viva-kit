"""Read-only preflight for a short branch; does not approve, merge or run code."""
from __future__ import annotations
import re
from copy import deepcopy
import json
import subprocess
from pathlib import Path
from wiki_core.context_policy import PolicyError, safe_path, is_context_instruction, policy_stage_cache
from wiki_core.context_packet import build_packet, validate_result, guarded_context_read
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

    def get(self, mode, reader, entry, *, policy_revision=None, expected_authority=None, authority_format=None, entry_folder=None, entry_index=None):
        normalized = normalize_query(entry)
        key = (mode, reader.revision, self.policy.policy_revision, self.context_id,
               policy_revision, expected_authority, authority_format, entry_folder, entry_index,
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
                policy_revision=policy_revision, expected_authority=expected_authority, read_budget=self.budget, authority_format=authority_format, entry_folder=entry_folder, entry_index=entry_index)
        else:
            receipt, _, _ = select_query(self.policy, self.context_id, reader, normalized, read_budget=self.budget,
                                         entry_folder=entry_folder, entry_index=entry_index)
        if len(self.cache) < 96:
            self.cache[key] = (deepcopy(receipt), before - self.budget[0])
        return receipt


@policy_stage_cache()
def preflight(root, policy, *, context_id, base, head, branch, packet, result, trusted_additional_readers=(), trusted_binding=None):
    """Return a review candidate, never an approval or merge authorization.

    External independent reviewer and final-head gates remain mandatory. The
    caller is responsible for ensuring its trusted ref is independently kept.
    """
    if getattr(policy, 'format_version', None) not in (None, 'folder'): raise IntegrationError('unsupported policy format')
    if not getattr(policy,'_binding',None) or Path(policy._binding[0])!=Path(root).resolve(): raise IntegrationError('unbound policy')
    if getattr(policy, 'format_version', None) == 'folder':
        from wiki_core.context_packet import _check_trusted_binding
        try: _check_trusted_binding(root, policy, context_id, trusted_binding, trusted_additional_readers)
        except PolicyError as exc: raise IntegrationError('host binding unavailable') from exc
    policy=policy.fresh()
    folder_mode = getattr(policy, 'format_version', None) == 'folder'
    if not isinstance(packet, dict): raise IntegrationError('invalid task packet')
    if folder_mode != (packet.get('authority_format') == 'folder'):
        raise IntegrationError('packet authority format differs')
    packet_readers = packet.get('additional_readers', ())
    if (not isinstance(trusted_additional_readers, (tuple, list)) or not isinstance(packet_readers, (tuple, list))
            or tuple(packet_readers) != tuple(trusted_additional_readers)):
        raise IntegrationError('additional reader host binding unavailable')
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
    evidence_inputs = [item for item in packet['inputs'] if item['kind']=='evidence' and 'query_id' not in item]
    if folder_mode:
        from wiki_core.context_packet import qualify_folder_context
        try:
            _, qualified_refs = qualify_folder_context(root, policy, context_id, packet['entry_folder'], packet['entry_index'], packet['max_bytes'],additional_readers=trusted_additional_readers)
            mandatory_refs = {item['ref'] for item in packet['inputs'] if item['kind'] == 'mandatory'}
            automatic = [(packet['entry_index'], 'selected context index')]
            automatic.extend((ref, 'qualified context boundary') for ref in qualified_refs
                             if ref not in mandatory_refs and ref != packet['entry_index'])
            actual_automatic = [(item['ref'], item['reason']) for item in evidence_inputs[:len(automatic)]]
            if actual_automatic != automatic: raise ValueError('automatic context evidence differs')
            evidence_inputs = evidence_inputs[len(automatic):]
        except (PolicyError, ValueError, KeyError, TypeError, OSError) as exc:
            raise IntegrationError('folder authority cannot be requalified') from exc
    evidence=[]
    for item in evidence_inputs:
        if item['kind']!='evidence' or 'query_id' in item: continue
        entry={k:item[k] for k in ('ref','producer','reason','use','classification')}
        for k in ('section','field'):
            if item[k] is not None: entry[k]=item[k]
        evidence.append(entry)
    try:
        if folder_mode:
            from wiki_core.context_packet import _qualify_trusted_producers
            _qualify_trusted_producers(root, policy, context_id, evidence, packet['max_bytes'],
                                       trusted_binding=trusted_binding, additional_readers=trusted_additional_readers)
        rebuilt=build_packet(root,policy,context_id,packet['content_revision'],evidence,packet['max_bytes'],adapter_report=packet['capability_evidence'],required_capabilities=packet['required_capabilities'],omissions=packet['coverage']['missing'],task_id=packet['task_id'],goal=packet['goal'],output=packet['output'],integrator=packet['integrator'],queries=packet_queries(packet),entry_folder=packet.get('entry_folder'),entry_index=packet.get('entry_index'),additional_readers=trusted_additional_readers,trusted_binding=trusted_binding)
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
        try: now=guarded_context_read(base_reader,policy,item['ref'],section=item['section'],field=item['field'])
        except ValueError as exc: raise IntegrationError('consumed input unavailable at approved base') from exc
        if now['content_digest']!=item['sha256']: raise IntegrationError('consumed input changed since task')
    raw=_git(root,'diff','--no-ext-diff','--no-textconv','--no-renames','--name-status','-z',base_reader.revision,proposal.revision).split(b'\0')
    if raw and raw[-1]==b'': raw.pop()
    if len(raw)%2: raise IntegrationError('unsupported diff')
    actual=[]
    # Active normative inputs require the separate policy-review path even if
    # the acting context would otherwise have read/write access to the file.
    normative={ref for c in policy.contexts.values() for k in ('instructions','skills','templates') for ref in c[k]}
    changes=[]
    for i in range(0,len(raw),2):
        try: status=raw[i].decode(); path=safe_path(raw[i+1].decode())
        except (UnicodeError,PolicyError) as exc: raise IntegrationError('invalid diff path') from exc
        if status not in ('A','M','D') or path.endswith('/context.yaml') or path=='context.yaml' or (folder_mode and path == 'wiki.config.yaml'): raise IntegrationError('unsupported or policy change')
        if is_context_instruction(path): raise IntegrationError('folder instruction change requires separate policy review')
        folder = str(Path(path).parent).replace('\\', '/')
        prefix = '' if folder == '.' else folder + '/'
        context_index = (folder_mode and Path(path).name in ('index.md', 'README.md') and
                         any(prefix + name in base_reader.paths or prefix + name in proposal.paths
                             for name in ('AGENTS.override.md', 'AGENTS.md')))
        if context_index and status in ('A', 'D'):
            selected_before = next((prefix + name for name in ('index.md', 'README.md') if prefix + name in base_reader.paths), None)
            selected_after = next((prefix + name for name in ('index.md', 'README.md') if prefix + name in proposal.paths), None)
            if selected_before != selected_after or path == packet.get('entry_index'):
                raise IntegrationError('context boundary change requires separate policy review')
        if path in normative: raise IntegrationError('normative input requires separate policy review')
        if policy.owner_of(path)!=context_id or not policy.permits(context_id,'write',path): raise IntegrationError('write outside context')
        if not policy.permits(context_id,'read',path): raise IntegrationError('proposal read denied')
        for reader_context in trusted_additional_readers:
            if policy._connection(context_id,reader_context,path,'interpretation','context',qualified=False) != 'approved':
                raise IntegrationError('additional reader not authorized for proposal')
        changes.append((status, path))
    if folder_mode:
        from wiki_core.traversal import require_wiki_boundaries
        try: require_wiki_boundaries(root, files=tuple(Path(root) / path for _, path in changes))
        except (ValueError, OSError) as exc: raise IntegrationError('proposal crosses repository boundary') from exc
    for status, path in changes:
        if status!='D':
            try: proposed_file=guarded_context_read(proposal,policy,path); text=proposed_file['text']
            except ValueError as exc: raise IntegrationError('unsupported or unsafe proposed file') from exc
            if any(x.category=='secret' for x in scan_text(text)): raise IntegrationError('secret detected in proposal')
            if folder_mode and Path(path).name in ('index.md', 'README.md'):
                folder = str(Path(path).parent).replace('\\', '/')
                prefix = '' if folder == '.' else folder + '/'
                selected_before = next((prefix + name for name in ('index.md', 'README.md') if prefix + name in base_reader.paths), None)
                selected_after = next((prefix + name for name in ('index.md', 'README.md') if prefix + name in proposal.paths), None)
                if (status == 'M' and path in (selected_before, selected_after, packet.get('entry_index'))
                        and any(prefix + name in base_reader.paths or prefix + name in proposal.paths
                                          for name in ('AGENTS.override.md', 'AGENTS.md'))
                        and bool(guarded_context_read(base_reader,policy,path)['text'].strip()) != bool(text.strip())):
                    raise IntegrationError('context boundary change requires separate policy review')
            if path.endswith('.md'):
                prior=guarded_context_read(base_reader,policy,path)['frontmatter'] if path in base_reader.paths else {}
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
                                if not normative_history(policy,context_id,ref,consumed,authority_format=requirement.get('authority_format'),entry_folder=requirement.get('entry_folder'),entry_index=requirement.get('entry_index')):
                                    raise IntegrationError('existing normative requirement requires requalification')
                                item=next((x for x in packet['inputs'] if x['kind']=='mandatory' and x['ref']==ref),None)
                                observed={k:item[k] for k in ('ref','section','field','revision')} if item else None
                                if item is None or observed not in result['read_coverage']['observed_refs']:
                                    raise IntegrationError('existing normative requirement requires reported read')
                                try: previous_rule=guarded_context_read(RepositoryReader(root,consumed),policy,ref)
                                except ValueError as exc: raise IntegrationError('existing normative input unavailable') from exc
                                if previous_rule['content_digest']!=item['sha256']:
                                    raise IntegrationError('existing normative requirement changed; reread and update')
                            if 'query' in requirement:
                                try:
                                    consumed_reader=query_reuse.reader(requirement['consumed_revision'])
                                    entry=requirement_query(requirement)
                                    old_query=query_reuse.get('historical',consumed_reader,entry,policy_revision=requirement['query_policy_revision'],expected_authority=requirement['authority_digest'],authority_format=requirement.get('authority_format'),entry_folder=requirement.get('entry_folder'),entry_index=requirement.get('entry_index'))
                                    now_query=query_reuse.get('base',base_reader,entry,entry_folder=requirement.get('entry_folder'),entry_index=requirement.get('entry_index'))
                                    proposed_query=query_reuse.get('proposal',proposal,entry,entry_folder=requirement.get('entry_folder'),entry_index=requirement.get('entry_index'))
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
                                and r['policy_revision']==requirement['query_policy_revision'] and r['authority_digest']==requirement['authority_digest'] and all(r.get(k)==requirement.get(k) for k in ('authority_format','entry_folder','entry_index'))
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
    if folder_mode:
        output['coverage_missing'] = sorted(set(packet['coverage']['missing']) | set(result['read_coverage']['missing']))
    if any(x.category=='secret' for x in scan_text(json.dumps(output,ensure_ascii=False))): raise IntegrationError('secret detected in integration metadata')
    return output
