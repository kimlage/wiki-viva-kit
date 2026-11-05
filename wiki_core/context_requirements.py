"""Bridge approved Markdown requirements and revision-bound task receipts.

No graph/receipt is persisted here: the page remains the canonical declaration.
"""
from __future__ import annotations
import json
import hashlib
import os
import re
import subprocess
from pathlib import Path
from wiki_core.context_policy import PolicyError, safe_path, within, policy_stage_cache
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

@policy_stage_cache()
def assess_approved_impact(root,policy,*,consumers,before,after,destination_context,scope=None,trusted_binding=None,**kwargs):
    """Derive edges from approved consumer pages and expose only authorized impact."""
    policy=_fresh(root,policy)
    if consumers is None and trusted_binding is None:
        raise RequirementError('coordination host binding required')
    if trusted_binding is not None:
        from wiki_core.context_packet import _check_trusted_binding
        _check_trusted_binding(root, policy, destination_context, trusted_binding)
    from wiki_core.context_impact import _folder_context, _folder_ref
    try: _folder_context(root, policy, destination_context)
    except ImpactError as exc: raise RequirementError('folder context requires authorized requalification') from exc
    reader=RepositoryReader(root,policy.policy_revision); edges=[]
    automatic = consumers is None
    referenced_sources = set()
    if automatic:
        from wiki_core.traversal import require_wiki_path
        from wiki_core.context_packet import guard_folder_blob
        try:
            scope = safe_path(scope, allow_root=True)
            directory = require_wiki_path(Path(root), scope)
            sentinel = '_wiki_scope_.md' if scope == '.' else scope + '/_wiki_scope_.md'
            if not directory.is_dir() or policy.owner_of(sentinel) != destination_context:
                raise ValueError('scope owner differs')
        except (PolicyError, ValueError, OSError, TypeError) as exc:
            raise RequirementError('authorized discovery folder required') from exc
        if (not isinstance(before, str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', before)
                or after != policy.policy_revision or subprocess.run(
                    [local_git_executable(), '--no-lazy-fetch', '-C', str(root), 'merge-base', '--is-ancestor', before, after],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=local_git_environment()).returncode):
            raise RequirementError('approved before and after revisions required')
        refs = [ref for ref in reader.paths if ref.endswith('.md') and within(ref, scope)
                and policy.owner_of(ref) == destination_context and policy.permits(destination_context, 'read', ref)]
        if len(refs) > 1000: raise RequirementError('discovery limit exceeded; narrow the folder')
        consumers = []
        remaining = 2_000_000
        for ref in refs:
            try:
                _folder_ref(root, policy, ref)
                guard_folder_blob(root, policy, ref)
                size = reader.blob_size(ref)
                if size > remaining: raise RequirementError('discovery limit exceeded; narrow the folder')
                page = guarded_context_read(reader, policy, ref)
            except RequirementError:
                raise
            except (ValueError, OSError) as exc:
                raise RequirementError('authorized discovery incomplete') from exc
            remaining -= size
            if any(f.category == 'secret' for f in scan_text(page['text'])):
                raise RequirementError('authorized discovery incomplete')
            if page['frontmatter'].get('information_requirements') or page['frontmatter'].get('source_refs'):
                consumers.append(ref)
            raw_refs = page['frontmatter'].get('source_refs', [])
            if isinstance(raw_refs, list):
                referenced_sources.update(item for item in raw_refs if isinstance(item, str))
        policy.fresh()
    elif not isinstance(consumers,list) or not consumers or len(consumers)>1000:
        raise RequirementError('bounded consumer paths required')
    source_ids = {}
    source_coverage_missing = False
    if automatic and referenced_sources:
        from wiki_core.context_packet import _qualify_trusted_producers, guard_folder_blob
        changed = subprocess.run([local_git_executable(), '--no-lazy-fetch', '-C', str(root), 'diff',
            '--no-ext-diff', '--no-textconv', '--no-renames', '--name-only', '-z', before, after, '--'],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=local_git_environment())
        if changed.returncode or len(changed.stdout) > 1_000_000:
            raise RequirementError('approved changes unavailable')
        changed_refs = changed.stdout.split(b'\0')
        if len(changed_refs) > 1001: raise RequirementError('discovery limit exceeded; narrow the change')
        for encoded in changed_refs:
            if not encoded: continue
            try:
                ref = safe_path(encoded.decode('utf-8'))
                if not ref.endswith('.md'):
                    continue
                if ref not in reader.paths:
                    # A removed page may have been a referenced source. Its
                    # former identity cannot be inferred from the new tree,
                    # and reading its past requires separate authorization.
                    source_coverage_missing = True
                    continue
                producer = policy.owner_of(ref)
                if producer != destination_context:
                    if policy._connection(producer, destination_context, ref, 'interpret', 'internal', qualified=False) != 'approved':
                        source_coverage_missing = True; continue
                    _qualify_trusted_producers(root, policy, destination_context, [{'ref': ref,
                        'producer': producer, 'reason': 'Declared source reference', 'use': 'interpret',
                        'classification': 'internal'}], 2_000_000, trusted_binding=trusted_binding)
                elif not policy.permits(destination_context, 'read', ref):
                    source_coverage_missing = True; continue
                guard_folder_blob(root, policy, ref)
                if reader.blob_size(ref) > 1_000_000: raise ValueError('source too large')
                page = guarded_context_read(reader, policy, ref)
                if any(f.category == 'secret' for f in scan_text(page['text'])): raise ValueError('source unavailable')
                meta = page['frontmatter']
                if meta.get('page_type') != 'source': continue
                for identity in (meta.get('page_id'), meta.get('source_id'), ref):
                    if isinstance(identity, str) and identity:
                        matches = source_ids.setdefault(identity, [])
                        if ref not in matches: matches.append(ref)
            except (ValueError, OSError, UnicodeError):
                source_coverage_missing = True
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
        edges.extend(e for e in derived if e.get('field')=='information_requirements'
                     and (not automatic or e.get('requirement', {}).get('temporal') == 'current'))
        if automatic:
            refs = page['frontmatter'].get('source_refs', [])
            if isinstance(refs, list):
                for item in refs:
                    matches = source_ids.get(item, []) if isinstance(item, str) else []
                    if not matches and isinstance(item, str):
                        from wiki_core.consolidate import _SOURCE_V2
                        prior = _SOURCE_V2.fullmatch(item)
                        if prior:
                            matches = sorted({ref for identity, paths in source_ids.items()
                                if (current := _SOURCE_V2.fullmatch(identity))
                                and current.group(1, 2) == prior.group(1, 2) for ref in paths})
                    if len(matches) == 1 and matches[0] != path:
                        edges.append({'source': path, 'target': matches[0], 'type': 'source_ref',
                            'direction': 'directed', 'basis': 'frontmatter', 'field': 'source_refs',
                            'consumed_fields': ['*'], 'use': 'interpret', 'classification': 'internal'})
                    elif len(matches) > 1:
                        source_coverage_missing = True
    # Raw edges can contain protected source metadata and remain internal.
    result=assess_impact(root,policy,{'edges':edges},before=before,after=after,destination_context=destination_context,trusted_binding=trusted_binding,**kwargs)
    if source_coverage_missing:
        result['coverage'] += '; some source associations unavailable'
    policy.fresh()
    return result


@policy_stage_cache()
def route_impact_to_action(root, binding, *, destination_context, before, after, scope,
                           event_id, action_path, action_id, profile, expected_sha256, trace=()):
    """Record one requalified impact on an existing authorized routed action."""
    if os.name == 'nt':
        raise RequirementError('review route unavailable')
    from wiki_core.action_dialogue import validate_history
    from wiki_core.action_transition import (_TRANSITION_LOCK, _action_file_lock,
        _contained_action_path, _parse_document, _sha256_text, _transition_action_page_locked,
        operational_comment_receipt, _comment_suffix_preserves_content, _render_document)
    from wiki_core.coordination import POLICY_FILE, dialogue_action
    from wiki_core.coordination_context import _policy
    from wiki_core.context_packet import guard_folder_blob
    from wiki_core.context_impact import _folder_context, _folder_ref

    root = Path(root).resolve(strict=True)
    policy = _policy(root, binding, destination_context, after)
    _folder_context(root, policy, destination_context)
    action_path = safe_path(action_path)
    if (policy.owner_of(action_path) != destination_context
            or not policy.permits(destination_context, 'read', action_path)
            or not policy.permits(destination_context, 'write', action_path)):
        raise RequirementError('review route unavailable')
    route_owner = policy.owner_of(POLICY_FILE)
    if policy.connection(route_owner, destination_context, POLICY_FILE, 'interpretation', 'artifact') != 'approved':
        raise RequirementError('review route unavailable')
    if not isinstance(expected_sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', expected_sha256):
        raise RequirementError('review route unavailable')
    impact = assess_approved_impact(root, policy, consumers=None, scope=scope, before=before,
        after=after, destination_context=destination_context, max_fanout=1000,
        trusted_binding=binding, trace=trace)
    matches = [row for row in impact['candidates'] if row.get('event_id') == event_id
               and row.get('state') in ('review_pending', 'blocked_unpinned_dependency')]
    if len(matches) != 1 or impact.get('authorized_remaining'):
        raise RequirementError('review route unavailable')
    def event_for(candidate):
        unqualified = candidate['state'] == 'blocked_unpinned_dependency'
        return {'event_id': candidate['event_id'], 'kind': 'comment', 'coordinator': profile,
                'text': (('Review suggested for ' if unqualified else 'Review requested for ')
                         + candidate['target'] + ': ' + candidate['source']
                         + ' (' + candidate['selector'] + ') changed in approved revision ' + after
                         + ('. Declared relation only; consumption is unverified and qualification is required.' if unqualified
                            else '. Independent interpretation and integration remain pending.'))}
    event = event_for(matches[0])
    _folder_ref(root, policy, action_path)
    _folder_ref(root, policy, POLICY_FILE)
    guard_folder_blob(root, policy, POLICY_FILE)
    route_reader = RepositoryReader(root, after, exact_path=POLICY_FILE)
    if route_reader.blob_size(POLICY_FILE) > 2_000_000:
        raise RequirementError('review route unavailable')
    route = guarded_context_read(route_reader, policy, POLICY_FILE)
    guard_folder_blob(root, policy, action_path)
    action_reader = RepositoryReader(root, after, exact_path=action_path)
    if action_reader.blob_size(action_path) > 2_000_000:
        raise RequirementError('review route unavailable')
    approved_action = guarded_context_read(action_reader, policy, action_path)
    with _TRANSITION_LOCK, _action_file_lock(root, action_path):
        policy.fresh()
        _folder_ref(root, policy, action_path)
        _folder_ref(root, policy, POLICY_FILE)
        if (root / POLICY_FILE).stat().st_size > 2_000_000:
            raise RequirementError('review route unavailable')
        route_bytes = (root / POLICY_FILE).read_bytes()
        if hashlib.sha256(route_bytes).hexdigest() != route['content_sha256']:
            raise RequirementError('review route unavailable')
        path, ref = _contained_action_path(root, action_path)
        raw = path.read_text(encoding='utf-8')
        current_sha = _sha256_text(raw)
        if current_sha != expected_sha256:
            raise RequirementError('review action revision changed')
        try:
            action = dialogue_action(root, ref, action_id, event)
        except (ValueError, OSError) as exc:
            raise RequirementError('review route unavailable') from exc
        frontmatter, body = _parse_document(raw)
        history = frontmatter.get('action_dialogue') or []
        validate_history(history)
        if current_sha != approved_action['content_sha256']:
            baseline, baseline_body = _parse_document(approved_action['text'])
            old_events = baseline.get('action_dialogue') or []
            old_receipts = baseline.get('action_state_history') or []
            new_events = history[len(old_events):]
            new_receipts = (frontmatter.get('action_state_history') or [])[len(old_receipts):]
            candidates = {item['event_id']: item for item in impact['candidates']
                          if item.get('state') in ('review_pending', 'blocked_unpinned_dependency')}
            if (not _comment_suffix_preserves_content(baseline, frontmatter, baseline_body, body)
                    or not 1 <= len(new_events) <= 128 or len(new_events) != len(new_receipts)):
                raise RequirementError('review action has unapproved changes; preserved')
            prior = approved_action['text']
            for index, item in enumerate(new_events):
                expected = event_for(candidates[item['event_id']]) if item['event_id'] in candidates else None
                if (expected is None or any(item.get(key) != value for key, value in expected.items())
                        or item.get('actor') != 'operator'):
                    raise RequirementError('review action has unapproved changes; preserved')
                intermediate = dict(baseline)
                intermediate['action_dialogue'] = [*old_events, *new_events[:index + 1]]
                intermediate['action_state_history'] = [*old_receipts, *new_receipts[:index + 1]]
                rendered = _render_document(intermediate, baseline_body)
                proof = operational_comment_receipt(prior, rendered)
                if not proof or proof.get('event_id') != item['event_id']:
                    raise RequirementError('review action has unapproved changes; preserved')
                prior = rendered
            if prior != raw:
                raise RequirementError('review action has unapproved changes; preserved')
        previous = [row for row in history if row['event_id'] == event_id]
        if previous:
            row = previous[0]
            if any(row.get(key) != value for key, value in event.items()) or row['actor'] != 'operator':
                raise RequirementError('review route unavailable')
            policy.fresh()
            return {'status': 'already_recorded', 'event_id': event_id,
                    'action_id': action_id, 'after_sha256': current_sha,
                    'execution': 'not_dispatched'}
        policy.fresh()
        receipt = _transition_action_page_locked(root, ref, action['state'], expected_sha256=current_sha,
            dialogue_event=event, dialogue_actor='operator')
        try:
            policy.fresh()
            _folder_ref(root, policy, POLICY_FILE)
            if hashlib.sha256((root / POLICY_FILE).read_bytes()).hexdigest() != route['content_sha256']:
                raise ValueError('route changed')
            _folder_ref(root, policy, action_path)
            if hashlib.sha256(path.read_bytes()).hexdigest() != receipt.after_sha256:
                raise ValueError('action changed')
        except (ValueError, OSError) as exc:
            raise RequirementError('review action may have been recorded; inspect before retry') from exc
        return {'status': 'recorded', 'event_id': event_id, 'action_id': action_id,
                'after_sha256': receipt.after_sha256, 'execution': 'not_dispatched'}

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
