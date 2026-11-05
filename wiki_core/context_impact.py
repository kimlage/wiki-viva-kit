"""Revision-bound, one-hop context impact over the existing relation inventory.

This module persists no graph or queue. Its caller is responsible for access to
its input inventory; results are scoped to one authorized destination context.
"""
from __future__ import annotations
import hashlib
import json
import re
import subprocess
from pathlib import Path
from markdown_it import MarkdownIt
from wiki_core.context_policy import PolicyError, safe_path, policy_stage_cache
from wiki_core.information_relations import dependency_edges
from wiki_core.repository_reader import RepositoryReader, RepositoryReadError
from wiki_core.content_sections import SectionError
from wiki_core.detectors import scan_text
from wiki_core.context_selection import select_query, requirement_query, reproduce_query
from wiki_core.context_normative import normative_history, folder_normative_changed
from wiki_core.git_env import local_git_environment, local_git_executable


class ImpactError(ValueError): pass


def _normative_review_authorized(policy, context, ref, revision, selection):
    """Authorize unchanged history or a proved single-instruction change."""
    folder = selection.get('authority_format')
    entry_folder, entry_index = selection.get('entry_folder'), selection.get('entry_index')
    if normative_history(policy, context, ref, revision, authority_format=folder,
                         entry_folder=entry_folder, entry_index=entry_index):
        return True
    return (getattr(policy, 'format_version', None) == 'folder' and folder == 'folder'
            and isinstance(entry_folder, str) and isinstance(entry_index, str)
            and folder_normative_changed(policy, context, ref, revision,
                                         entry_folder=entry_folder, entry_index=entry_index))


def _selector(value):
    if value in ('*', 'body'): return value, None
    if not isinstance(value, str): raise ImpactError('invalid selector')
    if value.startswith('section:') and len(value)>8: return 'section', value[8:]
    if value.startswith('field:') and len(value)>6: return 'field', value[6:]
    # Existing inventory uses bare frontmatter field names.
    if value and all(c.isalnum() or c=='_' for c in value): return 'field', value
    raise ImpactError('invalid selector')


def _selected_digest(reader, path, selector, *, policy=None):
    kind, name = _selector(selector)
    from wiki_core.context_packet import guarded_context_read
    try:
        if kind == 'section':
            item=guarded_context_read(reader, policy, path, section=name)
            if any(f.category=='secret' for f in scan_text(item['text'])): raise ImpactError('secret detected in selected content')
            # The selector means section contents, not the heading label. Version
            # remains part of the contract; title is read as a separate field.
            lines=item['text'].splitlines(keepends=True)
            tokens=MarkdownIt('commonmark').parse(item['text'])
            heading=next((t for t in tokens if t.type=='heading_open' and t.map),None)
            if heading is None: raise ImpactError('section heading unavailable')
            value=json.dumps([item['section_version'], ''.join(lines[heading.map[1]:])],ensure_ascii=False,separators=(',',':'))
            return hashlib.sha256(value.encode()).hexdigest()
        if kind == 'field':
            item=guarded_context_read(reader, policy, path, field=name)
            if any(f.category=='secret' for f in scan_text(item['text'])): raise ImpactError('secret detected in selected content')
            return item['content_digest']
        item=guarded_context_read(reader, policy, path)
        selected=item['body'] if kind == 'body' else item['text']
        if any(f.category=='secret' for f in scan_text(selected)): raise ImpactError('secret detected in selected content')
        if kind == 'body': return hashlib.sha256(item['body'].encode()).hexdigest()
        return item['content_digest']
    except SectionError as exc:
        if str(exc).startswith('missing section id:'): return None
        raise ImpactError('invalid section contract') from exc
    except RepositoryReadError as exc:
        # Missing file or selected field is a change, not a wider fallback.
        if str(exc).startswith(('repository file missing or unsupported:', 'missing frontmatter field:')): return None
        raise ImpactError('selected content unavailable') from exc


def _folder_context(root, policy, context):
    """Qualify only the requested destination before applying its grants."""
    if getattr(policy, 'format_version', None) != 'folder': return
    from wiki_core.context_packet import qualify_folder_context
    index = policy._context_indexes.get(context)
    if index is None: raise ImpactError('folder context requires authorized requalification')
    try: qualify_folder_context(root, policy, context, context, index, 2_000_000)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise ImpactError('folder context requires authorized requalification') from exc


def _folder_ref(root, policy, path):
    if getattr(policy, 'format_version', None) != 'folder': return
    from wiki_core.traversal import require_wiki_boundaries
    try: require_wiki_boundaries(root, files=(Path(root) / path,))
    except (ValueError, OSError) as exc: raise ImpactError('selected content unavailable') from exc


def _historical_edge_allowed(prior, current, source_owner, context, source, target, use, classification, kind, name):
    return (prior.owner_of(source) == source_owner and prior.owner_of(target) == context
            and all(prior.contexts[c]['owner'] == current.contexts[c]['owner'] for c in (source_owner, context))
            and prior._connection(source_owner, context, source, use, classification,
                section=name if kind == 'section' else None, field=name if kind == 'field' else None,
                qualified=False) == 'approved')


@policy_stage_cache()
def assess_impact(root, policy, graph, *, before, after, destination_context, max_fanout=100, offset=0, expected_selection=None, trace=(), max_generation=8, trusted_binding=None):
    """Compare exact consumed slices and return immediate review candidates.

    No transitive update, refresh, observation of facts or write occurs. A
    blocked edge is redacted completely; no protected count/path is returned.
    The graph must be the existing authorized relation inventory for this view.
    Folder mode currently evaluates one qualified owner. An explicitly granted
    cross-context edge requires separate requalification; it is not reported as
    absent merely because the producer is not yet qualified.
    """
    if getattr(policy, 'format_version', None) not in (None, 'folder'): raise ImpactError('unsupported policy format')
    if not getattr(policy,'_binding',None) or Path(policy._binding[0]) != Path(root).resolve(): raise ImpactError('unbound policy')
    policy=policy.fresh()
    if trusted_binding is not None:
        from wiki_core.context_packet import _check_trusted_binding
        _check_trusted_binding(root, policy, destination_context, trusted_binding)
    if destination_context not in policy.contexts: raise ImpactError('unknown destination')
    _folder_context(root, policy, destination_context)
    if type(max_fanout) is not int or not 1 <= max_fanout <= 1000: raise ImpactError('invalid fanout limit')
    if type(offset) is not int or offset < 0: raise ImpactError('invalid offset')
    if not isinstance(trace, (list, tuple)) or len(trace)>64 or any(not isinstance(x,str) or not re.fullmatch(r'[0-9a-f]{64}',x) for x in trace): raise ImpactError('invalid trace')
    if type(max_generation) is not int or not 1 <= max_generation <= 64: raise ImpactError('invalid generation limit')
    if not isinstance(graph,dict) or not isinstance(graph.get('edges'),list) or len(graph['edges'])>10000: raise ImpactError('invalid relation inventory')
    old=RepositoryReader(root,before); new=RepositoryReader(root,after); readers={old.revision:old}
    approved_pairs = set()
    def require_ancestor(older, newer):
        if older == newer or (older, newer) in approved_pairs:
            return
        if subprocess.run([local_git_executable(), '--no-lazy-fetch', '-C', str(root),
                'merge-base', '--is-ancestor', older, newer], stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, env=local_git_environment()).returncode:
            raise ImpactError('impact revisions are not approved ancestors')
        approved_pairs.add((older, newer))
    if getattr(policy, 'format_version', None) == 'folder':
        # A past after-revision can have different read denies. Evaluate the
        # current approved result; historical inputs are checked separately.
        if new.revision != policy.policy_revision:
            raise ImpactError('impact after revision must be current approval')
        require_ancestor(old.revision, new.revision)
    try: edges,_=dependency_edges(graph)
    except (KeyError,TypeError,AttributeError) as exc: raise ImpactError('malformed relation inventory') from exc
    candidates={}; query_read_budget=[32_000_000]; blocked_connection = False
    historical_policies = {}
    for e in edges:
        source=safe_path(e['prerequisite']); target=safe_path(e['dependent'])
        if policy.owner_of(target)!=destination_context: continue
        # No target metadata may escape when the destination itself is denied.
        if not policy.permits(destination_context,'read',target): continue
        source_owner=policy.owner_of(source)
        if e.get('owner_context', destination_context) != destination_context or e.get('producer_context', source_owner) != source_owner: raise ImpactError('relation context does not match owner')
        consumed_revision=e.get('consumed_revision')
        if consumed_revision is not None and (not isinstance(consumed_revision,str) or not re.fullmatch(r'[0-9a-f]{40,64}',consumed_revision)): raise ImpactError('invalid consumed revision')
        if consumed_revision is None:
            edge_old=old
        else:
            if consumed_revision not in readers: readers[consumed_revision]=RepositoryReader(root,consumed_revision)
            edge_old=readers[consumed_revision]
            if edge_old.revision!=consumed_revision: raise ImpactError('consumed revision not fixed')
        if getattr(policy, 'format_version', None) == 'folder':
            require_ancestor(edge_old.revision, new.revision)
        fields=e.get('consumed_fields')
        if not isinstance(fields,list) or not fields: raise ImpactError('missing consumed selectors')
        normative = e.get('requirement', {}).get('source_kind') == 'mandatory'
        if normative:
            requirement=e.get('requirement')
            if (e.get('type') != 'operational_prerequisite' or e.get('field') != 'information_requirements'
                    or not isinstance(requirement,dict) or requirement.get('use') != 'normative'
                    or requirement.get('target') != source or fields != ['*'] or requirement.get('fields') != ['*']
                    or requirement.get('temporal') != 'current' or consumed_revision is None
                    or new.revision != policy.policy_revision):
                raise ImpactError('normative dependency authorization unavailable; review pending')
            if not _normative_review_authorized(policy, destination_context, source, consumed_revision, requirement):
                raise ImpactError('normative dependency authorization unavailable; review pending')
        query = e.get('requirement', {}).get('query')
        query_before = query_after = None
        if query is not None:
            if source_owner != destination_context: raise ImpactError('query scope not authorized')
            try:
                req=e['requirement']
                query_before,_,_=reproduce_query(policy,destination_context,edge_old,requirement_query(req),policy_revision=req.get('query_policy_revision'),expected_authority=req.get('authority_digest'),read_budget=query_read_budget,authority_format=req.get('authority_format'),entry_folder=req.get('entry_folder'),entry_index=req.get('entry_index'))
                query_after,_,_=select_query(policy,destination_context,new,requirement_query(req),read_budget=query_read_budget,entry_folder=req.get('entry_folder'),entry_index=req.get('entry_index'))
                if target in {m['ref'] for m in [*query_before['members'],*query_after['members']]}: raise ImpactError('query consumer cannot be a member')
                if any(query_before[k]!=req.get(k) for k in ('members_digest','selected_digest')):
                    raise ImpactError('canonical query receipt differs from consumed selection')
            except (ValueError,KeyError,TypeError) as exc: raise ImpactError('query requirement cannot be revalidated') from exc
            fields=['query:'+query_before['query_id']]
        for selector in fields:
            kind,name=('query',None) if query is not None else _selector(selector)
            classification=e.get('classification','internal'); use=e.get('use','interpret')
            if not isinstance(classification,str) or not classification or not isinstance(use,str) or not use: raise ImpactError('invalid use or classification')
            # Mandatory inherited instructions were authorized above as
            # normative inputs, not as a bilateral factual connection.
            if (not normative and getattr(policy, 'format_version', None) == 'folder'
                    and source_owner != destination_context):
                declared = policy._connection(source_owner, destination_context, source, use, classification,
                    section=name if kind=='section' else None, field=name if kind=='field' else None,
                    qualified=False)
                if declared == 'approved' and trusted_binding is None:
                    raise ImpactError('cross-context folder authority requires requalification')
                if declared != 'approved':
                    blocked_connection = True
                    continue
                from wiki_core.context_packet import _qualify_trusted_producers
                selector_options = ({'section': name} if kind == 'section' else {'field': name} if kind == 'field' else {})
                try:
                    _qualify_trusted_producers(root, policy, destination_context, [{
                        'ref': source, 'producer': source_owner, 'reason': 'Declared impact input',
                        'use': use, 'classification': classification, **selector_options}], 2_000_000,
                        trusted_binding=trusted_binding)
                except (ValueError, OSError):
                    blocked_connection = True
                    continue
            # Current access does not authorize historical bytes, including
            # within the same owner. Check prior ownership, grants and denies.
            if (not normative and getattr(policy, 'format_version', None) == 'folder'
                    and edge_old.revision != policy.policy_revision):
                try:
                    from wiki_core.context_policy import historical_policy
                    if edge_old.revision not in historical_policies:
                        historical_policies[edge_old.revision] = historical_policy(
                            policy, edge_old.revision, authority_format='folder')
                    prior_policy = historical_policies[edge_old.revision]
                    if not _historical_edge_allowed(prior_policy, policy, source_owner, destination_context,
                            source, target, use, classification, kind, name):
                        raise PolicyError('historical connection unavailable')
                except (ValueError, KeyError, OSError):
                    blocked_connection = True
                    continue
            grant='approved' if normative else policy.connection(source_owner,destination_context,source,use,classification,section=name if kind=='section' else None,field=name if kind=='field' else None)
            if grant!='approved': continue
            _folder_ref(root, policy, source)
            _folder_ref(root, policy, target)
            before_digest=query_before['selected_digest'] if query is not None else _selected_digest(edge_old,source,selector,policy=policy)
            after_digest=query_after['selected_digest'] if query is not None else _selected_digest(new,source,selector,policy=policy)
            if e.get('type') == 'source_ref' and before_digest == after_digest and before_digest is not None:
                continue
            if (before_digest==after_digest and before_digest is not None and consumed_revision is not None
                    and (query is None or query_before['members_digest']==query_after['members_digest'])): continue
            rule=str(e.get('type','untyped_reference'))
            target_digest=_selected_digest(new,target,'*',policy=policy)
            key=(target,edge_old.revision,new.revision,rule,source,selector,use,classification,target_digest)
            if normative:
                key += ('mandatory',)
                if requirement.get('authority_format'): key += tuple(requirement[k] for k in ('authority_format','entry_folder','entry_index'))
            if query is not None and query_before.get('authority_format'): key += tuple(query_before[k] for k in ('authority_format','entry_folder','entry_index'))
            event_id=hashlib.sha256(json.dumps(key,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
            cycle=event_id in trace or len(trace)>=max_generation
            candidates[key]={'event_id':event_id, 'trace':list(trace) if cycle else [*trace,event_id], 'generation':len(trace), 'target':target,'destination_context':destination_context,'source':source,'producer_context':source_owner,'selector':selector,'rule':rule,'use':use,'classification':classification,'before_revision':edge_old.revision,'after_revision':new.revision,'before_digest':before_digest,'after_digest':after_digest,'target_digest':target_digest, **({'source_kind':'mandatory'} if normative else {}), 'state':'blocked_cycle_limit' if cycle else ('blocked_missing_target' if target_digest is None else ('blocked_unpinned_dependency' if consumed_revision is None else ('blocked_missing_source' if before_digest is None and after_digest is None else 'review_pending'))),'interpretation':'independent','fact_freshness':'not_assessed'}
            if normative and requirement.get('authority_format'):
                candidates[key].update({k:requirement[k] for k in ('authority_format','entry_folder','entry_index')})
            if query is not None:
                candidates[key].update(query_policy_revision=query_after['policy_revision'], authority_digest=query_after['authority_digest'],query=query, members_digest_before=query_before['members_digest'], members_digest_after=query_after['members_digest'])
                if query_after.get('authority_format'):
                    candidates[key].update({k:query_after[k] for k in ('authority_format','entry_folder','entry_index')})
    # Avoid silently omitting work: return an explicit continuation offset and
    # total only for the authorized candidate set.
    ordered=[candidates[k] for k in sorted(candidates)]
    selection=hashlib.sha256(json.dumps(ordered,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if offset and expected_selection!=selection: raise ImpactError('continuation selection changed')
    if offset>len(ordered): raise ImpactError('invalid offset')
    if any(x.category=='secret' for x in scan_text(json.dumps(ordered,ensure_ascii=False))): raise ImpactError('secret detected in impact metadata')
    policy.fresh()
    end=min(offset+max_fanout,len(ordered))
    return {'schema_version':'wiki.context-impact/v1','policy_revision':policy.policy_revision,'before_revision':old.revision,'after_revision':new.revision,'destination_context':destination_context,'candidates':ordered[offset:end],'authorized_remaining':len(ordered)-end,'selection_digest':selection,'next_offset':end if end<len(ordered) else None,'coverage':'authorized_edges_only; completeness not asserted' + ('; some connections unavailable' if blocked_connection else ''),'propagation':'one_hop_only'}


def report_review(root, policy, candidate, *, disposition, reason, evidence_revision, trusted_binding=None):
    """Prepare a reported disposition for an existing task, without writing it.

    It is not independent-review proof. A changed interpretation is detected
    from approved Git bytes; only that new change may seed a further impact run.
    """
    if getattr(policy, 'format_version', None) not in (None, 'folder'): raise ImpactError('unsupported policy format')
    if not getattr(policy,'_binding',None) or Path(policy._binding[0]) != Path(root).resolve(): raise ImpactError('unbound policy')
    policy=policy.fresh()
    if disposition not in ('updated','still_valid','superseded','blocked') or not isinstance(reason,str) or not reason.strip(): raise ImpactError('invalid disposition')
    if not isinstance(candidate,dict) or candidate.get('state')!='review_pending': raise ImpactError('candidate is not reviewable')
    if trusted_binding is not None:
        from wiki_core.context_packet import _check_trusted_binding
        _check_trusted_binding(root, policy, candidate.get('destination_context'), trusted_binding)
    folder_normative = getattr(policy, 'format_version', None) == 'folder' and candidate.get('source_kind') == 'mandatory'
    if getattr(policy, 'format_version', None) == 'folder':
        revisions = (candidate.get('before_revision'), candidate.get('after_revision'))
        if any(not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', value) for value in revisions):
            raise ImpactError('candidate revisions unavailable')
        if 'query' in candidate and candidate.get('query_policy_revision') != revisions[1]:
            raise ImpactError('query candidate policy revision differs')
        for older, newer in ((revisions[0], revisions[1]), (revisions[1], policy.policy_revision)):
            if subprocess.run([local_git_executable(), '--no-lazy-fetch', '-C', str(root), 'merge-base', '--is-ancestor', older, newer],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=local_git_environment()).returncode:
                raise ImpactError('candidate revisions not approved ancestors')
    try:
        target=safe_path(candidate['target']); source=safe_path(candidate['source']); context=candidate['destination_context']
        _folder_context(root, policy, context)
        selector=candidate['selector']; kind,name=('query',None) if 'query' in candidate else _selector(selector)
        key=(target,candidate['before_revision'],candidate['after_revision'],candidate['rule'],source,selector,candidate['use'],candidate['classification'],candidate['target_digest'])
        if 'source_kind' in candidate:
            if candidate['source_kind'] != 'mandatory': raise ImpactError('invalid candidate source kind')
            key += ('mandatory',)
        if candidate.get('authority_format'): key += tuple(candidate[k] for k in ('authority_format','entry_folder','entry_index'))
        expected=hashlib.sha256(json.dumps(key,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        if expected!=candidate['event_id'] or policy.owner_of(target)!=context or policy.owner_of(source)!=candidate['producer_context'] or not policy.permits(context,'read',target): raise ImpactError('invalid candidate')
        if candidate.get('source_kind')=='mandatory':
            grant='approved' if candidate['use']=='normative' and selector=='*' and _normative_review_authorized(policy,context,source,candidate['before_revision'],candidate) else 'denied'
        else:
            if trusted_binding is not None and candidate['producer_context'] != context:
                from wiki_core.context_packet import _qualify_trusted_producers
                selector_options = ({'section': name} if kind == 'section' else {'field': name} if kind == 'field' else {})
                _qualify_trusted_producers(root, policy, context, [{'ref': source,
                    'producer': candidate['producer_context'], 'reason': 'Declared review input',
                    'use': candidate['use'], 'classification': candidate['classification'], **selector_options}],
                    2_000_000, trusted_binding=trusted_binding)
            grant=policy.connection(candidate['producer_context'],context,source,candidate['use'],candidate['classification'],section=name if kind=='section' else None,field=name if kind=='field' else None)
            if (getattr(policy, 'format_version', None) == 'folder' and candidate['producer_context'] not in policy._qualified_contexts
                    and policy._connection(candidate['producer_context'],context,source,candidate['use'],candidate['classification'],
                        section=name if kind=='section' else None,field=name if kind=='field' else None,qualified=False) == 'approved'):
                raise ImpactError('cross-context folder authority requires requalification')
        if grant!='approved': raise ImpactError('candidate authorization no longer current')
        if folder_normative:
            from wiki_core.context_selection import _equivalent_folder_chain
            try:
                _equivalent_folder_chain(policy, context, candidate['after_revision'],
                                         candidate['entry_folder'], candidate['entry_index'])
            except PolicyError:
                # If only the selected instruction differs, this candidate is
                # stale; any other ambiguity still requires requalification.
                _equivalent_folder_chain(policy, context, candidate['after_revision'],
                                         candidate['entry_folder'], candidate['entry_index'], changed_ref=source)
                raise ImpactError('source changed since candidate')
        _folder_ref(root, policy, source)
        _folder_ref(root, policy, target)
        reader=RepositoryReader(root,evidence_revision)
        if reader.revision!=policy.policy_revision: raise ImpactError('evidence revision not approved current base')
        if kind=='query':
            entry={'target':source,'query':candidate['query'],'reason':'canonical collection requirement','use':candidate['use'],'classification':candidate['classification']}
            if getattr(policy, 'format_version', None) == 'folder':
                from wiki_core.context_packet import qualify_folder_context
                from wiki_core.context_selection import _equivalent_folder_authority
                qualify_folder_context(root, policy, context, candidate['entry_folder'], candidate['entry_index'], 2_000_000)
                _equivalent_folder_authority(policy, context, candidate['query_policy_revision'], entry,
                                             candidate['entry_folder'], candidate['entry_index'])
                candidate_receipt,_,_=reproduce_query(policy,context,RepositoryReader(root,candidate['after_revision']),entry,
                    policy_revision=candidate['query_policy_revision'],expected_authority=candidate['authority_digest'],
                    authority_format=candidate['authority_format'],entry_folder=candidate['entry_folder'],entry_index=candidate['entry_index'])
                if (candidate_receipt['selected_digest'] != candidate['after_digest'] or
                        candidate_receipt['members_digest'] != candidate['members_digest_after']):
                    raise ImpactError('query candidate selection differs')
                receipt,_,_=select_query(policy,context,reader,entry,entry_folder=candidate['entry_folder'],entry_index=candidate['entry_index'])
                if receipt['authority_digest'] != candidate['authority_digest']:
                    raise ImpactError('query candidate authority differs')
            else:
                receipt,_,_=reproduce_query(policy,context,reader,entry,policy_revision=candidate.get('query_policy_revision'),expected_authority=candidate.get('authority_digest'),authority_format=candidate.get('authority_format'),entry_folder=candidate.get('entry_folder'),entry_index=candidate.get('entry_index'))
            if selector!='query:'+receipt['query_id'] or candidate['members_digest_after']!=receipt['members_digest']:
                raise ImpactError('query candidate selection differs')
            digest=receipt['selected_digest']
        else: digest=_selected_digest(reader,source,selector,policy=policy)
        if digest!=candidate['after_digest']: raise ImpactError('source changed since candidate')
        prior=RepositoryReader(root,candidate['after_revision'])
        if getattr(policy, 'format_version', None) == 'folder' and prior.revision != policy.policy_revision:
            from wiki_core.context_policy import historical_policy
            old_policy = historical_policy(policy, prior.revision, authority_format='folder')
            if (old_policy.owner_of(target) != context or
                    old_policy.contexts[context]['owner'] != policy.contexts[context]['owner'] or
                    not old_policy._permits_unqualified(context, 'read', target)):
                raise ImpactError('historical target requires authorized requalification')
        if getattr(policy, 'format_version', None) == 'folder' and not folder_normative:
            consumed = RepositoryReader(root, candidate['before_revision'])
            if kind == 'query':
                from wiki_core.context_packet import guarded_context_read
                from wiki_core.information_relations import information_requirements
                target_doc = guarded_context_read(prior, policy, target)
                if target_doc['content_digest'] != candidate['target_digest']:
                    raise ImpactError('candidate target digest mismatch')
                requirements = information_requirements(target_doc['frontmatter'], lambda ref: [safe_path(ref)])
                matches = [req for req in requirements if req.get('temporal') == 'current'
                    and req.get('target') == source and req.get('query') == candidate['query']
                    and req.get('consumed_revision') == candidate['before_revision']
                    and req.get('selected_digest') == candidate['before_digest']
                    and req.get('members_digest') == candidate['members_digest_before']
                    and req.get('authority_digest') == candidate['authority_digest']
                    and all(req.get(key) == candidate.get(key) for key in
                            ('use', 'classification', 'authority_format', 'entry_folder', 'entry_index'))]
                if len(matches) != 1:
                    raise ImpactError('canonical query requirement unavailable')
                requirement = matches[0]
                old_receipt,_,_ = reproduce_query(policy, context, consumed, entry,
                    policy_revision=requirement['query_policy_revision'], expected_authority=requirement['authority_digest'],
                    authority_format=candidate['authority_format'], entry_folder=candidate['entry_folder'],
                    entry_index=candidate['entry_index'])
                old_digest = old_receipt['selected_digest']
                if old_receipt['members_digest'] != candidate['members_digest_before']:
                    raise ImpactError('historical query candidate selection differs')
            else:
                from wiki_core.context_policy import historical_policy
                historical = historical_policy(policy, candidate['before_revision'], authority_format='folder')
                if not _historical_edge_allowed(historical, policy, candidate['producer_context'], context,
                        source, target, candidate['use'], candidate['classification'], kind, name):
                    raise ImpactError('historical source requires authorized requalification')
                old_digest = _selected_digest(consumed, source, selector, policy=policy)
            if old_digest != candidate['before_digest']:
                raise ImpactError('candidate source digest mismatch')
            if old_digest == digest and (kind != 'query' or candidate['members_digest_before'] == candidate['members_digest_after']):
                raise ImpactError('candidate source has no approved change')
        if folder_normative:
            prior_source_digest = _selected_digest(prior,source,selector,policy=policy)
            consumed_source_digest = _selected_digest(RepositoryReader(root,candidate['before_revision']),source,selector,policy=policy)
            if (prior_source_digest != candidate['after_digest'] or consumed_source_digest != candidate['before_digest']
                    or prior_source_digest is None or consumed_source_digest is None or prior_source_digest == consumed_source_digest):
                raise ImpactError('candidate source digest mismatch')
        before=_selected_digest(prior,target,'*',policy=policy); after=_selected_digest(reader,target,'*',policy=policy)
        if before!=candidate['target_digest']: raise ImpactError('candidate target digest mismatch')
    except (KeyError,TypeError,PolicyError) as exc:
        raise ImpactError('invalid or unauthorized candidate') from exc
    if disposition=='updated' and (after is None or before==after): raise ImpactError('updated output has no approved change')
    report={'schema_version':'wiki.context-review/v1','event_id':candidate['event_id'],'context_id':context,'target':target,'disposition':disposition,'reason':reason,'evidence_revision':reader.revision,'source_digest':digest,'output_before_digest':before,'output_after_digest':after,'verification':'reported_not_verified','next_impact_allowed':disposition=='updated' and before!=after}
    if any(x.category=='secret' for x in scan_text(json.dumps(report,ensure_ascii=False))): raise ImpactError('secret detected in review metadata')
    policy.fresh()
    return report
