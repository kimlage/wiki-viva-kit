"""Revision-bound, one-hop context impact over the existing relation inventory.

This module persists no graph or queue. Its caller is responsible for access to
its input inventory; results are scoped to one authorized destination context.
"""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path
from markdown_it import MarkdownIt
from wiki_core.context_policy import PolicyError, safe_path
from wiki_core.information_relations import dependency_edges
from wiki_core.repository_reader import RepositoryReader, RepositoryReadError
from wiki_core.content_sections import SectionError
from wiki_core.detectors import scan_text
from wiki_core.context_selection import select_query, requirement_query, reproduce_query
from wiki_core.context_normative import normative_history


class ImpactError(ValueError): pass


def _selector(value):
    if value in ('*', 'body'): return value, None
    if not isinstance(value, str): raise ImpactError('invalid selector')
    if value.startswith('section:') and len(value)>8: return 'section', value[8:]
    if value.startswith('field:') and len(value)>6: return 'field', value[6:]
    # Existing inventory uses bare frontmatter field names.
    if value and all(c.isalnum() or c=='_' for c in value): return 'field', value
    raise ImpactError('invalid selector')


def _selected_digest(reader, path, selector):
    kind, name = _selector(selector)
    try:
        if kind == 'section':
            item=reader.read(path, section=name)
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
            item=reader.read(path, field=name)
            if any(f.category=='secret' for f in scan_text(item['text'])): raise ImpactError('secret detected in selected content')
            return item['content_digest']
        item=reader.read(path)
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
    index = 'index.md' if context == '.' else context + '/index.md'
    try: qualify_folder_context(root, policy, context, context, index, 2_000_000)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise ImpactError('folder context requires authorized requalification') from exc


def _folder_ref(root, policy, path):
    if getattr(policy, 'format_version', None) != 'folder': return
    from wiki_core.traversal import require_wiki_boundaries
    try: require_wiki_boundaries(root, files=(Path(root) / path,))
    except (ValueError, OSError) as exc: raise ImpactError('selected content unavailable') from exc


def assess_impact(root, policy, graph, *, before, after, destination_context, max_fanout=100, offset=0, expected_selection=None, trace=(), max_generation=8):
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
    if destination_context not in policy.contexts: raise ImpactError('unknown destination')
    _folder_context(root, policy, destination_context)
    if type(max_fanout) is not int or not 1 <= max_fanout <= 1000: raise ImpactError('invalid fanout limit')
    if type(offset) is not int or offset < 0: raise ImpactError('invalid offset')
    if not isinstance(trace, (list, tuple)) or len(trace)>64 or any(not isinstance(x,str) or not re.fullmatch(r'[0-9a-f]{64}',x) for x in trace): raise ImpactError('invalid trace')
    if type(max_generation) is not int or not 1 <= max_generation <= 64: raise ImpactError('invalid generation limit')
    if not isinstance(graph,dict) or not isinstance(graph.get('edges'),list) or len(graph['edges'])>10000: raise ImpactError('invalid relation inventory')
    old=RepositoryReader(root,before); new=RepositoryReader(root,after); readers={old.revision:old}
    try: edges,_=dependency_edges(graph)
    except (KeyError,TypeError,AttributeError) as exc: raise ImpactError('malformed relation inventory') from exc
    candidates={}; query_read_budget=[32_000_000]
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
        fields=e.get('consumed_fields')
        if not isinstance(fields,list) or not fields: raise ImpactError('missing consumed selectors')
        normative = e.get('requirement', {}).get('source_kind') == 'mandatory'
        if normative:
            requirement=e.get('requirement')
            if (e.get('type') != 'operational_prerequisite' or e.get('field') != 'information_requirements'
                    or not isinstance(requirement,dict) or requirement.get('use') != 'normative'
                    or requirement.get('target') != source or fields != ['*'] or requirement.get('fields') != ['*']
                    or requirement.get('temporal') != 'current' or consumed_revision is None
                    or new.revision != policy.policy_revision
                    or not normative_history(policy,destination_context,source,consumed_revision)):
                raise ImpactError('normative dependency authorization unavailable; review pending')
        query = e.get('requirement', {}).get('query')
        query_before = query_after = None
        if query is not None:
            if source_owner != destination_context: raise ImpactError('query scope not authorized')
            try:
                req=e['requirement']
                query_before,_,_=reproduce_query(policy,destination_context,edge_old,requirement_query(req),policy_revision=req.get('query_policy_revision'),expected_authority=req.get('authority_digest'),read_budget=query_read_budget,authority_format=req.get('authority_format'),entry_folder=req.get('entry_folder'),entry_index=req.get('entry_index'))
                query_after,_,_=select_query(policy,destination_context,new,requirement_query(req),read_budget=query_read_budget)
                if target in {m['ref'] for m in [*query_before['members'],*query_after['members']]}: raise ImpactError('query consumer cannot be a member')
                if any(query_before[k]!=req.get(k) for k in ('members_digest','selected_digest')):
                    raise ImpactError('canonical query receipt differs from consumed selection')
            except (ValueError,KeyError,TypeError) as exc: raise ImpactError('query requirement cannot be revalidated') from exc
            fields=['query:'+query_before['query_id']]
        for selector in fields:
            kind,name=('query',None) if query is not None else _selector(selector)
            classification=e.get('classification','internal'); use=e.get('use','interpret')
            if not isinstance(classification,str) or not classification or not isinstance(use,str) or not use: raise ImpactError('invalid use or classification')
            if (getattr(policy, 'format_version', None) == 'folder' and source_owner != destination_context
                    and policy._connection(source_owner, destination_context, source, use, classification,
                        section=name if kind=='section' else None, field=name if kind=='field' else None,
                        qualified=False) == 'approved'):
                raise ImpactError('cross-context folder authority requires requalification')
            grant='approved' if normative else policy.connection(source_owner,destination_context,source,use,classification,section=name if kind=='section' else None,field=name if kind=='field' else None)
            if grant!='approved': continue
            _folder_ref(root, policy, source)
            _folder_ref(root, policy, target)
            before_digest=query_before['selected_digest'] if query is not None else _selected_digest(edge_old,source,selector)
            after_digest=query_after['selected_digest'] if query is not None else _selected_digest(new,source,selector)
            if (before_digest==after_digest and before_digest is not None and consumed_revision is not None
                    and (query is None or query_before['members_digest']==query_after['members_digest'])): continue
            rule=str(e.get('type','untyped_reference'))
            target_digest=_selected_digest(new,target,'*')
            key=(target,edge_old.revision,new.revision,rule,source,selector,use,classification,target_digest)
            if normative: key += ('mandatory',)
            if query is not None and query_before.get('authority_format'): key += tuple(query_before[k] for k in ('authority_format','entry_folder','entry_index'))
            event_id=hashlib.sha256(json.dumps(key,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
            cycle=event_id in trace or len(trace)>=max_generation
            candidates[key]={'event_id':event_id, 'trace':list(trace) if cycle else [*trace,event_id], 'generation':len(trace), 'target':target,'destination_context':destination_context,'source':source,'producer_context':source_owner,'selector':selector,'rule':rule,'use':use,'classification':classification,'before_revision':edge_old.revision,'after_revision':new.revision,'before_digest':before_digest,'after_digest':after_digest,'target_digest':target_digest, **({'source_kind':'mandatory'} if normative else {}), 'state':'blocked_cycle_limit' if cycle else ('blocked_missing_target' if target_digest is None else ('blocked_unpinned_dependency' if consumed_revision is None else ('blocked_missing_source' if before_digest is None and after_digest is None else 'review_pending'))),'interpretation':'independent','fact_freshness':'not_assessed'}
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
    return {'schema_version':'wiki.context-impact/v1','policy_revision':policy.policy_revision,'before_revision':old.revision,'after_revision':new.revision,'destination_context':destination_context,'candidates':ordered[offset:end],'authorized_remaining':len(ordered)-end,'selection_digest':selection,'next_offset':end if end<len(ordered) else None,'coverage':'authorized_edges_only; completeness not asserted','propagation':'one_hop_only'}


def report_review(root, policy, candidate, *, disposition, reason, evidence_revision):
    """Prepare a reported disposition for an existing task, without writing it.

    It is not independent-review proof. A changed interpretation is detected
    from approved Git bytes; only that new change may seed a further impact run.
    """
    if getattr(policy, 'format_version', None) not in (None, 'folder'): raise ImpactError('unsupported policy format')
    if not getattr(policy,'_binding',None) or Path(policy._binding[0]) != Path(root).resolve(): raise ImpactError('unbound policy')
    policy=policy.fresh()
    if disposition not in ('updated','still_valid','superseded','blocked') or not isinstance(reason,str) or not reason.strip(): raise ImpactError('invalid disposition')
    if not isinstance(candidate,dict) or candidate.get('state')!='review_pending': raise ImpactError('candidate is not reviewable')
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
            grant='approved' if candidate['use']=='normative' and selector=='*' and normative_history(policy,context,source,candidate['before_revision']) else 'denied'
        else:
            grant=policy.connection(candidate['producer_context'],context,source,candidate['use'],candidate['classification'],section=name if kind=='section' else None,field=name if kind=='field' else None)
            if (getattr(policy, 'format_version', None) == 'folder' and candidate['producer_context'] not in policy._qualified_contexts
                    and policy._connection(candidate['producer_context'],context,source,candidate['use'],candidate['classification'],
                        section=name if kind=='section' else None,field=name if kind=='field' else None,qualified=False) == 'approved'):
                raise ImpactError('cross-context folder authority requires requalification')
        if grant!='approved': raise ImpactError('candidate authorization no longer current')
        _folder_ref(root, policy, source)
        _folder_ref(root, policy, target)
        reader=RepositoryReader(root,evidence_revision)
        if reader.revision!=policy.policy_revision: raise ImpactError('evidence revision not approved current base')
        if kind=='query':
            entry={'target':source,'query':candidate['query'],'reason':'canonical collection requirement','use':candidate['use'],'classification':candidate['classification']}
            receipt,_,_=reproduce_query(policy,context,reader,entry,policy_revision=candidate.get('query_policy_revision'),expected_authority=candidate.get('authority_digest'),authority_format=candidate.get('authority_format'),entry_folder=candidate.get('entry_folder'),entry_index=candidate.get('entry_index'))
            if selector!='query:'+receipt['query_id'] or candidate['members_digest_after']!=receipt['members_digest']:
                raise ImpactError('query candidate selection differs')
            digest=receipt['selected_digest']
        else: digest=_selected_digest(reader,source,selector)
        if digest!=candidate['after_digest']: raise ImpactError('source changed since candidate')
        prior=RepositoryReader(root,candidate['after_revision'])
        before=_selected_digest(prior,target,'*'); after=_selected_digest(reader,target,'*')
        if before!=candidate['target_digest']: raise ImpactError('candidate target digest mismatch')
    except (KeyError,TypeError,PolicyError) as exc:
        raise ImpactError('invalid or unauthorized candidate') from exc
    if disposition=='updated' and (after is None or before==after): raise ImpactError('updated output has no approved change')
    report={'schema_version':'wiki.context-review/v1','event_id':candidate['event_id'],'context_id':context,'target':target,'disposition':disposition,'reason':reason,'evidence_revision':reader.revision,'source_digest':digest,'output_before_digest':before,'output_after_digest':after,'verification':'reported_not_verified','next_impact_allowed':disposition=='updated' and before!=after}
    if any(x.category=='secret' for x in scan_text(json.dumps(report,ensure_ascii=False))): raise ImpactError('secret detected in review metadata')
    policy.fresh()
    return report
