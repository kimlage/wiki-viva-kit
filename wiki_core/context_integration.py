"""Read-only preflight for a short branch; does not approve, merge or run code."""
from __future__ import annotations
import re
from copy import deepcopy
import hashlib
import json
import math
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


def preflight(root, policy, *, context_id, base, head, branch, packet, result, trusted_additional_readers=(), trusted_binding=None, allow_owned_range=False):
    """Return a review candidate, never an approval or merge authorization.

    External independent reviewer and final-head gates remain mandatory. The
    caller is responsible for ensuring its trusted ref is independently kept.
    """
    with policy_stage_cache():
        return _preflight(root, policy, context_id=context_id, base=base, head=head, branch=branch,
            packet=packet, result=result, trusted_additional_readers=trusted_additional_readers,
            trusted_binding=trusted_binding, allow_owned_range=allow_owned_range)


def _preflight(root, policy, *, context_id, base, head, branch, packet, result,
               trusted_additional_readers=(), trusted_binding=None, _assigned=None, allow_owned_range=False):
    # _assigned is derived internally by preflight_composite, never exposed by
    # the single-context entrypoint. Readers still see the complete Git trees.
    if not isinstance(packet, dict): raise IntegrationError('invalid task packet')
    range_mode = packet.get('schema_version') == 'wiki.task-context/v2'
    if range_mode:
        from wiki_core.coordination_context import CoordinationBinding
        if (allow_owned_range is not True or not isinstance(trusted_binding, CoordinationBinding)
                or trusted_additional_readers or _assigned is not None):
            raise IntegrationError('owned range unavailable')
    if getattr(policy, 'format_version', None) not in (None, 'folder'): raise IntegrationError('unsupported policy format')
    if not getattr(policy,'_binding',None) or Path(policy._binding[0])!=Path(root).resolve(): raise IntegrationError('unbound policy')
    if getattr(policy, 'format_version', None) == 'folder':
        from wiki_core.context_packet import _check_trusted_binding
        try: _check_trusted_binding(root, policy, context_id, trusted_binding, trusted_additional_readers)
        except PolicyError as exc: raise IntegrationError('host binding unavailable') from exc
    policy=policy.fresh()
    folder_mode = getattr(policy, 'format_version', None) == 'folder'
    if range_mode and not folder_mode:
        raise IntegrationError('owned range unavailable')
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
        if 'range' in item: entry['range'] = item['range']
        evidence.append(entry)
    try:
        if folder_mode:
            from wiki_core.context_packet import _qualify_trusted_producers
            qualification_evidence = [{k: v for k, v in row.items() if k != 'range'} for row in evidence] if range_mode else evidence
            _qualify_trusted_producers(root, policy, context_id, qualification_evidence, packet['max_bytes'],
                                       trusted_binding=trusted_binding, additional_readers=trusted_additional_readers)
        rebuilt=build_packet(root,policy,context_id,packet['content_revision'],evidence,packet['max_bytes'],adapter_report=packet['capability_evidence'],required_capabilities=packet['required_capabilities'],omissions=packet['coverage']['missing'],task_id=packet['task_id'],goal=packet['goal'],output=packet['output'],integrator=packet['integrator'],queries=packet_queries(packet),entry_folder=packet.get('entry_folder'),entry_index=packet.get('entry_index'),additional_readers=trusted_additional_readers,trusted_binding=trusted_binding,allow_owned_range=allow_owned_range)
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
        try: now=guarded_context_read(base_reader,policy,item['ref'],section=item['section'],field=item['field'],byte_range=item.get('range'))
        except ValueError as exc: raise IntegrationError('consumed input unavailable at approved base') from exc
        if now['content_digest']!=item['sha256']: raise IntegrationError('consumed input changed since task')
    if range_mode:
        ranged = [item for item in packet['inputs'] if 'range' in item]
        if len(ranged) != 1: raise IntegrationError('owned range unavailable')
        item = ranged[0]
        try:
            source = guarded_context_read(RepositoryReader(root,packet['content_revision']),policy,item['ref'])['content']
            approved = guarded_context_read(base_reader,policy,item['ref'])['content']
            candidate = guarded_context_read(proposal,policy,item['ref'])['content']
            selected = guarded_context_read(proposal,policy,item['ref'],byte_range=item['range'])
        except ValueError as exc:
            raise IntegrationError('owned range unavailable') from exc
        if (not approved.startswith(source) or not candidate.startswith(approved) or len(candidate) <= len(approved)
                or selected['content_digest'] != item['sha256']):
            raise IntegrationError('owned range append cannot be verified')
    raw=_git(root,'diff','--no-ext-diff','--no-textconv','--no-renames','--name-status','-z',base_reader.revision,proposal.revision).split(b'\0')
    if raw and raw[-1]==b'': raw.pop()
    if len(raw)%2: raise IntegrationError('unsupported diff')
    actual=[]
    base_paths, proposal_paths = set(base_reader.paths), set(proposal.paths)
    # Active normative inputs require the separate policy-review path even if
    # the acting context would otherwise have read/write access to the file.
    normative={ref for c in policy.contexts.values() for k in ('instructions','skills','templates') for ref in c[k]}
    changes=[]
    for i in range(0,len(raw),2):
        try: status=raw[i].decode(); path=safe_path(raw[i+1].decode())
        except (UnicodeError,PolicyError) as exc: raise IntegrationError('invalid diff path') from exc
        if _assigned is not None and (status, path) not in _assigned:
            continue
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
        # A deletion has no proposed blob to open. Require its base entry to
        # be an accepted regular file, so symlinks, gitlinks and excluded
        # paths cannot bypass the reader's checks. Modifications require safe
        # entries on both sides; additions must be safe in the proposal.
        if ((status in ('M', 'D') and path not in base_paths)
                or (status in ('A', 'M') and path not in proposal_paths)):
            raise IntegrationError('unsupported or unsafe proposed file')
        for reader_context in trusted_additional_readers:
            if policy._connection(context_id,reader_context,path,'interpretation','context',qualified=False) != 'approved':
                raise IntegrationError('additional reader not authorized for proposal')
        changes.append((status, path))
    if range_mode and changes != [('M', packet['output'])]:
        raise IntegrationError('owned range supports only the selected output append')
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


def _bounded_composite_inputs(value):
    """Reject non-JSON-like or oversized input before copying or serializing it.

    The estimate intentionally counts every UTF-8 byte six times, an upper
    bound for JSON string escaping. It can reject below the nominal limit.
    """
    remaining = 8_000_000
    nodes = 0

    def visit(item, depth):
        nonlocal remaining, nodes
        nodes += 1
        remaining -= 2  # structural punctuation / separators
        if nodes > 100_000 or remaining < 0 or depth > 64:
            raise IntegrationError('composite preflight unavailable')
        if item is None or type(item) is bool:
            remaining -= 5
        elif type(item) is int:
            if item.bit_length() > 63: raise IntegrationError('composite preflight unavailable')
            remaining -= 21
        elif type(item) is float:
            if not math.isfinite(item): raise IntegrationError('composite preflight unavailable')
            remaining -= 32
        elif type(item) is str:
            if len(item) > remaining // 6: raise IntegrationError('composite preflight unavailable')
            try: remaining -= 6 * len(item.encode('utf-8'))
            except UnicodeError: raise IntegrationError('composite preflight unavailable') from None
        elif type(item) in (list, tuple):
            for child in item: visit(child, depth + 1)
        elif type(item) is dict:
            for key, child in item.items():
                if type(key) is not str: raise IntegrationError('composite preflight unavailable')
                visit(key, depth + 1)
                visit(child, depth + 1)
        else:
            raise IntegrationError('composite preflight unavailable')
        if remaining < 0: raise IntegrationError('composite preflight unavailable')

    visit(value, 0)


@policy_stage_cache()
def preflight_composite(root, policy, *, base, head, branch, participants, trusted_binding):
    """Qualify one full diff by owner for a trusted local integrator.

    The host must independently authorize the caller to receive metadata for
    *all* involved contexts. A binding is a ceiling, not that authorization.
    This function is not a sandbox, an identity check, review or merge grant.
    """
    try:
        return _preflight_composite(root, policy, base=base, head=head, branch=branch,
                                    participants=participants, trusted_binding=trusted_binding)
    except (ValueError, KeyError, TypeError, OSError, OverflowError):
        # This trusted host API may combine owners. Do not expose a foreign
        # path or which authority check failed through an error response.
        raise IntegrationError('composite preflight unavailable') from None


def _preflight_composite(root, policy, *, base, head, branch, participants, trusted_binding):
    from wiki_core.context_packet import _check_trusted_binding
    from wiki_core.coordination_context import CoordinationBinding

    if (not isinstance(trusted_binding, CoordinationBinding)
            or getattr(policy, 'format_version', None) != 'folder'
            or type(participants) is not list or not 1 <= len(participants) <= 64):
        raise IntegrationError('composite host binding unavailable')
    if not getattr(policy, '_binding', None) or Path(policy._binding[0]) != Path(root).resolve():
        raise IntegrationError('unbound policy')
    _bounded_composite_inputs([base, head, branch, participants])
    # Freeze the host-supplied packets/results for this operation. They remain
    # intact: no rewritten result or synthetic single-owner receipt is trusted.
    participants = deepcopy(participants)
    rows = {}
    for row in participants:
        if (not isinstance(row, dict) or not {'context_id', 'packet', 'result'} <= set(row)
                or set(row) - {'context_id', 'packet', 'result', 'additional_readers'}):
            raise IntegrationError('invalid composite participant')
        context = row['context_id']
        readers = row.get('additional_readers', ())
        if (not isinstance(context, str) or context in rows
                or not isinstance(readers, (list, tuple)) or len(readers) > 64
                or any(not isinstance(reader, str) for reader in readers)
                or len(set(readers)) != len(readers)):
            raise IntegrationError('invalid composite participant')
        try:
            _check_trusted_binding(root, policy, context, trusted_binding, readers)
        except (PolicyError, ValueError, TypeError) as exc:
            raise IntegrationError('composite host binding unavailable') from exc
        rows[context] = row

    policy = policy.fresh()
    base_reader, proposal = RepositoryReader(root, base), RepositoryReader(root, head)
    if base_reader.revision != policy.policy_revision:
        raise IntegrationError('approved base moved')
    raw = _git(root, 'diff', '--no-ext-diff', '--no-textconv', '--no-renames',
               '--name-status', '-z', base_reader.revision, proposal.revision).split(b'\0')
    if raw and raw[-1] == b'': raw.pop()
    if not raw or len(raw) % 2 or len(raw) > 8192:
        raise IntegrationError('empty or unsupported composite proposal')
    partition = {context: set() for context in rows}
    actual = []
    seen = set()
    for i in range(0, len(raw), 2):
        try:
            status, path = raw[i].decode(), safe_path(raw[i + 1].decode())
            owner = policy.owner_of(path)
        except (UnicodeError, PolicyError, ValueError, TypeError) as exc:
            raise IntegrationError('invalid composite proposal') from exc
        if status not in ('A', 'M', 'D') or path in seen or owner not in partition:
            raise IntegrationError('composite coverage unavailable')
        seen.add(path)
        partition[owner].add((status, path))
        actual.append({'path': path, 'action': {'A': 'created', 'M': 'modified', 'D': 'deleted'}[status]})
    if any(not assigned for assigned in partition.values()):
        raise IntegrationError('composite coverage unavailable')

    summaries = []
    for context in sorted(rows):
        row = rows[context]
        part = _preflight(root, policy, context_id=context, base=base_reader.revision,
            head=proposal.revision, branch=branch, packet=row['packet'], result=row['result'],
            trusted_additional_readers=tuple(row.get('additional_readers', ())),
            trusted_binding=trusted_binding, _assigned=partition[context])
        summaries.append({'context_id': context, 'task_id': part['task_id'],
            'packet_digest': part['packet_digest'], 'changes_count': len(part['changes']),
            'coverage_missing_count': len(part.get('coverage_missing', ()))})

    # A moving approved ref or branch must invalidate the complete operation,
    # not only whichever participant happened to be checked last.
    policy.fresh()
    if _git(root, 'rev-parse', '--verify', 'refs/heads/' + branch + '^{commit}').decode().strip() != proposal.revision:
        raise IntegrationError('branch head changed')
    digest = hashlib.sha256(json.dumps(sorted(actual, key=lambda x: (x['path'], x['action'])),
        ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    output = {'schema_version': 'wiki.context-integration-composite/v1',
        'state': 'independent_review_required', 'base': base_reader.revision,
        'head': proposal.revision, 'branch': branch, 'participants': summaries,
        'changes_count': len(actual), 'diff_sha256': digest,
        'actor_identity': 'not_verified', 'semantic_coherence': 'not_assessed',
        'review': 'not_performed', 'gates': 'not_performed', 'merge': 'not_performed'}
    if any(x.category == 'secret' for x in scan_text(json.dumps(output, ensure_ascii=False))):
        raise IntegrationError('secret detected in integration metadata')
    return output
