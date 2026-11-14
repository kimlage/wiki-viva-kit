"""Construct bounded, revision-bound context packets from authorized paths."""
from __future__ import annotations
import hashlib
import json
import copy
import datetime as dt
from pathlib import Path, PurePosixPath
from .context_policy import PolicyError, capability_status, safe_path, within, valid_adapter_report, policy_stage_cache, _exact_read_path
from .repository_reader import RepositoryReader
from .detectors import contains_secret_structure
from .context_selection import select_query, digest


def _reject_secrets(value):
    try:
        found = contains_secret_structure(value)
    except (ValueError, TypeError, RecursionError) as exc:
        raise PolicyError('invalid packet input') from exc
    if found: raise PolicyError('secret detected in packet input')


def declared_reads_from_inputs(inputs, *, folder_mode):
    """Return the ordered read set, retaining distinct revisions and selectors."""
    keys = ('ref', 'section', 'field', 'revision')
    reads = [{**{key: item[key] for key in keys},
              **({'range': copy.deepcopy(item['range'])} if 'range' in item else {})}
             for item in inputs]
    if not folder_mode:
        return reads  # Preserve the historical v1 representation.
    unique = {}
    for item in reads:
        unique.setdefault(json.dumps(item, sort_keys=True, separators=(',', ':')), item)
    return list(unique.values())


def blocker(action, target, reason, owner, required_action, resume_condition, status='pending', interface=None):
    if status not in ('pending', 'denied', 'uncertain'):
        raise PolicyError('invalid blocker status')
    if not all(isinstance(x, str) and x for x in (action, target, reason, owner, required_action, resume_condition)):
        raise PolicyError('incomplete blocker')
    return {'action': action, 'target': target, 'reason': reason, 'owner': owner,
            'required_action': required_action, 'interface': interface,
            'resume_condition': resume_condition, 'status': status}


def connection_proposal(source, destination, selector, purpose, classification, expiry, *, section=None, field=None):
    """A proposal contains selectors, never content; it grants no access."""
    safe_path(selector)
    if not all(isinstance(x, str) and x for x in (source, destination, purpose, classification, expiry)):
        raise PolicyError('incomplete connection proposal')
    try: dt.date.fromisoformat(expiry)
    except ValueError as exc: raise PolicyError('invalid proposal expiry') from exc
    if section is not None and field is not None: raise PolicyError('section and field mutually exclusive')
    if any(x is not None and (not isinstance(x, str) or not x) for x in (section, field)):
        raise PolicyError('invalid proposal selector')
    return {'source': source, 'destination': destination, 'selector': selector, 'section': section, 'field': field,
            'purpose': purpose, 'classification': classification, 'expiry': expiry,
            'status': 'pending', 'grants_access': False}


def _context_view(policy, context_id):
    """Expose the selected context and authorized limits without sibling leaks."""
    c = policy.contexts[context_id]; effective = policy.effective[context_id]; root = c['root']
    def owned_intersections(scopes):
        values = []
        for scope in scopes:
            exact = _exact_read_path(scope)
            if exact is not None:
                if not within(exact, root) or policy.owner_of(exact) != context_id: continue
                value = scope
            elif within(scope, root): value = scope
            elif within(root, scope): value = root
            else: continue
            # Paths owned by another context are not disclosed merely by a
            # broad ancestor ceiling; the owner/connection rule handles them.
            if exact is None and value != '.' and policy.owner_of(value) != context_id: continue
            if value not in values: values.append(value)
        return sorted(values)
    imports = []
    for rule in c['imports']:
        if policy.connection(rule['from_context'], context_id, rule['selector'], rule['use'], rule['classification'], section=rule.get('section'), field=rule.get('field')) == 'approved':
            imports.append({k: rule[k] for k in ('from_context','selector','section','field','use','classification','expires') if k in rule})
    return {'id': context_id, 'purpose': c['purpose'], 'owner': c['owner'], 'root': root,
            'lineage': [x['id'] for x in policy.lineage(context_id)],
            'owned_scopes': {'read': owned_intersections(effective['read']), 'write': owned_intersections(effective['write']),
                'deny_read': owned_intersections(effective['deny']['read']), 'deny_write': owned_intersections(effective['deny']['write'])},
            'capabilities': sorted(set(effective['capabilities']) - set(effective['deny']['capabilities'])),
            'denied_capabilities': sorted(set(effective['deny']['capabilities']) & set(effective['capabilities'])),
            'publication': sorted(set(effective['publication']) - set(effective['deny']['publication'])),
            'denied_publication': sorted(set(effective['deny']['publication']) & set(effective['publication'])),
            'approved_imports': sorted(imports, key=lambda r: json.dumps(r, sort_keys=True)),
            'boundary': 'Path scopes are ceilings. Only the canonical owner may write; cross-context reads require exact current bilateral approval. This is not sandbox enforcement.'}


def guard_folder_blob(root, policy, ref):
    """Recheck the pinned approval and repository boundary immediately before a read."""
    from wiki_core.context_policy import revision
    from wiki_core.traversal import require_wiki_boundaries
    binding = getattr(policy, '_binding', None)
    if not binding or Path(binding[0]) != Path(root).resolve(): raise PolicyError('folder authority unavailable')
    if revision(root, binding[1]) != policy.policy_revision: raise PolicyError('folder policy changed during read')
    try: require_wiki_boundaries(Path(root), files=(Path(root) / ref,))
    except (ValueError, OSError) as exc: raise PolicyError('context body unavailable') from exc


def guarded_context_read(reader, policy, ref, **selectors):
    """Recheck freshness and Git boundary; caller must authorize the ref first."""
    if getattr(policy, 'format_version', None) == 'folder':
        guard_folder_blob(reader.root, policy, ref)
        return reader.read(ref, before_blob=lambda path: guard_folder_blob(reader.root, policy, path), **selectors)
    return reader.read(ref, **selectors)


@policy_stage_cache()
def qualify_folder_context(root, policy, context_id, entry_folder, entry_index, max_bytes, *, additional_readers=()):
    """Qualify the lineage after exact authorization for every reader.

    The caller must independently bind every reader to its trusted host; this
    function checks policy connections but does not establish actor authority.
    """
    if getattr(policy, 'format_version', None) != 'folder' or not getattr(policy, '_binding', None):
        raise PolicyError('folder authority required')
    if Path(policy._binding[0]) != Path(root).resolve(): raise PolicyError('mismatched policy root')
    policy.fresh()
    entry_folder = safe_path(entry_folder, allow_root=True)
    from wiki_core.traversal import require_wiki_path
    try:
        if not require_wiki_path(Path(root), entry_folder).is_dir(): raise ValueError('entry folder unavailable')
    except (ValueError, OSError) as exc:
        raise PolicyError('entry folder unavailable') from exc
    if context_id not in policy.contexts or (entry_folder == '.' and context_id != '.'):
        raise PolicyError('entry context unavailable')
    if (not isinstance(additional_readers, (list, tuple)) or len(additional_readers) > 8
            or any(not isinstance(reader, str) or reader not in policy.contexts for reader in additional_readers)
            or len(set(additional_readers)) != len(additional_readers)):
        raise PolicyError('additional reader selection unavailable')
    if entry_folder != '.' and policy.owner_of(entry_folder) != context_id: raise PolicyError('entry context unavailable')
    entry_index = safe_path(entry_index)
    if str(PurePosixPath(entry_index).parent) != policy.contexts[context_id]['root']:
        raise PolicyError('entry index unavailable')
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 0:
        raise PolicyError('invalid byte budget')
    reader = RepositoryReader(Path(root), policy.policy_revision)
    if entry_folder != '.' and not any(ref.startswith(entry_folder + '/') for ref in reader.paths):
        raise PolicyError('entry folder unavailable in approved tree')
    lineage = policy.lineage(context_id)
    qualification_bytes = 0
    inspected = set()
    inspection_order = []
    nonempty = {}
    def check_authorized(ref):
        producer = policy.owner_of(ref)
        if policy._connection(producer, context_id, ref, 'interpretation', 'context', qualified=False) != 'approved':
            raise PolicyError('context body not authorized')
        for reader_context in additional_readers:
            if policy._connection(producer, reader_context, ref, 'interpretation', 'context', qualified=False) != 'approved':
                raise PolicyError('additional reader not authorized for context body')

    # A negative metadata check avoids opening instructions for a lineage whose
    # required index is already denied. It does not qualify or authorize reads.
    for context in lineage:
        folder = context['root']
        if folder != '.' or context_id == '.':
            index = entry_index if folder == context_id else policy._context_indexes.get(folder)
            if index not in reader.paths: raise PolicyError('context index empty or unavailable')
            check_authorized(index)

    def inspect_authorized(ref):
        nonlocal qualification_bytes
        guard_folder_blob(root, policy, ref)
        check_authorized(ref)
        from wiki_core.traversal import require_wiki_boundaries
        try: require_wiki_boundaries(Path(root), files=(Path(root) / ref,))
        except (ValueError, OSError) as exc: raise PolicyError('context body unavailable') from exc
        if ref not in inspected:
            qualification_bytes += reader.blob_size(ref)
            if qualification_bytes > max_bytes: raise PolicyError('context qualification exceeds byte budget')
            inspected.add(ref)
            inspection_order.append(ref)
        guard_folder_blob(root, policy, ref)
        item = reader.read(ref, before_blob=lambda path: guard_folder_blob(root, policy, path))
        _reject_secrets(item['text'])
        nonempty[ref] = bool(item['text'].strip())
        return item['text']
    for context in lineage:
        folder = context['root']
        prefix = '' if folder == '.' else folder + '/'
        instructions = [prefix + name for name in ('AGENTS.override.md', 'AGENTS.md')
                        if prefix + name in policy._folder_names]
        if not instructions or not any(inspect_authorized(ref).strip() for ref in instructions):
            raise PolicyError('context instruction empty or unavailable')
        if folder != '.' or context_id == '.':
            index = entry_index if folder == context_id else policy._context_indexes.get(folder)
            if index not in reader.paths or not inspect_authorized(index).strip():
                raise PolicyError('context index empty or unavailable')
    # AGENTS files in auxiliary folders still participate in native physical
    # discovery even though those folders do not create context ownership.
    context_folders = {context['root'] for context in lineage}
    parts = [] if entry_folder == '.' else entry_folder.split('/')
    for folder in ['/'.join(parts[:i]) for i in range(1, len(parts) + 1)]:
        if folder in context_folders: continue
        prefix = folder + '/'
        refs = [prefix + name for name in ('AGENTS.override.md', 'AGENTS.md')
                if prefix + name in policy._folder_names]
        # Empty auxiliary instructions contribute nothing; fallback is read
        # only after the exact grant for that file has been checked.
        if refs: any(inspect_authorized(ref).strip() for ref in refs)
    policy.fresh()
    policy._qualified_contexts.update(context['id'] for context in lineage)
    if not hasattr(policy, '_folder_qualifications'): policy._folder_qualifications = {}
    policy._folder_qualifications[(context_id, entry_folder, entry_index)] = {
        'context_id': context_id, 'entry_folder': entry_folder, 'entry_index': entry_index,
        'refs': tuple(inspection_order), 'nonempty': nonempty, 'additional_readers': tuple(additional_readers)}
    return reader, inspection_order


def _check_trusted_binding(root, policy, context_id, trusted_binding, additional_readers=()):
    """Validate an optional host binding before opening any context body."""
    if trusted_binding is None: return
    from wiki_core.coordination_context import CoordinationBinding
    binding = getattr(policy, '_binding', None)
    if (not isinstance(trusted_binding, CoordinationBinding) or not binding or
            Path(binding[0]) != Path(root).resolve() or binding[2] != 'wiki.config.yaml' or
            trusted_binding.manifest != binding[2] or trusted_binding.trusted_ref != binding[1] or
            context_id not in trusted_binding.contexts or
            not isinstance(additional_readers, (tuple, list)) or
            any(reader not in trusted_binding.contexts for reader in additional_readers)):
        raise PolicyError('host binding requires authorized requalification')


def _qualify_trusted_producers(root, policy, context_id, evidence, max_bytes, *, trusted_binding=None, additional_readers=()):
    """Qualify selected foreign producers under a host binding, not packet claims.

    Callers must obtain ``trusted_binding`` out of band from their trusted host.
    This helper is an in-process policy check, not a filesystem security boundary.
    """
    if getattr(policy, 'format_version', None) != 'folder' or not getattr(policy, '_binding', None):
        raise PolicyError('folder authority required')
    if not isinstance(evidence, list) or len(evidence) > 128:
        raise PolicyError('invalid evidence')
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 0:
        raise PolicyError('invalid byte budget')
    _check_trusted_binding(root, policy, context_id, trusted_binding, additional_readers)
    policy.fresh()
    producers = []
    for item in evidence:
        allowed = {'ref', 'producer', 'reason', 'use', 'classification', 'section', 'field'}
        if (not isinstance(item, dict) or set(item) - allowed or
                not all(isinstance(item.get(key), str) and item[key] for key in ('ref', 'producer', 'reason', 'use', 'classification'))):
            raise PolicyError('invalid evidence')
        for value in item.values():
            if isinstance(value, str): _reject_secrets(value)
        ref = safe_path(item['ref'])
        if any(key in item and (not isinstance(item[key], str) or not item[key]) for key in ('section', 'field')) or ('section' in item and 'field' in item):
            raise PolicyError('invalid evidence selector')
        producer = item['producer']
        if policy.owner_of(ref) != producer: raise PolicyError('connection denied')
        if producer != context_id:
            if producer not in producers: producers.append(producer)
            if policy._connection(producer, context_id, ref, item['use'], item['classification'],
                                  section=item.get('section'), field=item.get('field'), qualified=False) != 'approved':
                raise PolicyError('connection not approved')
            for reader in additional_readers:
                if policy._connection(producer, reader, ref, item['use'], item['classification'],
                                      section=item.get('section'), field=item.get('field'), qualified=False) != 'approved':
                    raise PolicyError('additional reader not authorized for selected body')
    if not producers: return
    from wiki_core.coordination_context import CoordinationBinding
    root_binding, trusted_ref, manifest = policy._binding
    if (not isinstance(trusted_binding, CoordinationBinding) or
            Path(root_binding) != Path(root).resolve() or manifest != 'wiki.config.yaml' or
            trusted_binding.manifest != manifest or trusted_binding.trusted_ref != trusted_ref or
            context_id not in trusted_binding.contexts or
            any(context not in trusted_binding.contexts for context in (*producers, *additional_readers))):
        raise PolicyError('producer context requires authorized requalification')
    if len(producers) > 8: raise PolicyError('producer qualification exceeds limit')
    remaining = max_bytes
    for producer in producers:
        index = policy._context_indexes.get(producer)
        if index is None: raise PolicyError('producer context requires authorized requalification')
        reader, refs = qualify_folder_context(root, policy, producer, producer, index, remaining)
        for ref in refs:
            guard_folder_blob(root, policy, ref)
            remaining -= reader.blob_size(ref)
            guard_folder_blob(root, policy, ref)
            if remaining < 0: raise PolicyError('producer qualification exceeds byte budget')
    policy.fresh()


def _finalize_packet(packet, max_bytes):
    _reject_secrets(packet)
    packet['packet_digest'] = '0' * 64
    while True:
        length = len(json.dumps(packet, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8'))
        if packet['bytes_used'] == length: break
        packet['bytes_used'] = length
    if packet['bytes_used'] > max_bytes: raise PolicyError('complete packet exceeds byte budget')
    payload = {k: v for k, v in packet.items() if k != 'packet_digest'}
    packet['packet_digest'] = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
    return packet


def _packet_with_omissions(packet, omissions, policy):
    """Reframe an already qualified packet; this helper does not authorize it."""
    if (not isinstance(packet, dict) or packet.get('authority_format') != 'folder'
            or packet.get('policy_revision') != policy.policy_revision or not getattr(policy, '_binding', None)
            or not isinstance(omissions, list) or any(not isinstance(x, str) or not x for x in omissions)):
        raise PolicyError('packet unavailable')
    original = {k: v for k, v in packet.items() if k != 'packet_digest'}
    expected = hashlib.sha256(json.dumps(original, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
    if packet.get('packet_digest') != expected: raise PolicyError('packet unavailable')
    policy.fresh()
    updated = copy.deepcopy(packet)
    updated['coverage']['missing'] = list(omissions)
    if 'linked sources not inspected' not in updated['coverage']['missing']:
        updated['coverage']['missing'].append('linked sources not inspected')
    result = _finalize_packet(updated, updated['max_bytes'])
    policy.fresh()
    return result


@policy_stage_cache()
def build_packet(root, policy, context_id, content_revision, evidence, max_bytes, *, adapter_report=None,
                 required_capabilities=(), query_fingerprint=None, omissions=(), task_id=None, goal=None, output=None, integrator=None, queries=(),
                 entry_folder=None, entry_index=None, additional_readers=(), trusted_binding=None, allow_owned_range=False, allow_owned_ranges=False):
    if getattr(policy, 'format_version', None) not in (None, 'folder'):
        raise PolicyError('v2 policy requires a v2 packet; v1 receipts require explicit migration')
    if not all(isinstance(x, str) and x.strip() for x in (task_id, goal, output, integrator)): raise PolicyError('task identity, goal, output and integrator required')
    if not getattr(policy, '_binding', None) or Path(policy._binding[0]) != Path(root).resolve(): raise PolicyError('unbound or mismatched policy')
    policy = policy.fresh()
    folder_mode = getattr(policy, 'format_version', None) == 'folder'
    if not folder_mode and (entry_folder is not None or entry_index is not None or additional_readers):
        raise PolicyError('folder selection requires folder authority')
    if folder_mode:
        if entry_folder is None: raise PolicyError('entry folder required')
        entry_folder = safe_path(entry_folder, allow_root=True)
        from wiki_core.traversal import require_wiki_path
        try:
            if not require_wiki_path(Path(root), entry_folder).is_dir():
                raise ValueError('entry folder unavailable')
        except (ValueError, OSError) as exc:
            raise PolicyError('entry folder unavailable') from exc
        if context_id not in policy.contexts or (entry_folder == '.' and context_id != '.'):
            raise PolicyError('entry context unavailable')
        if entry_folder != '.' and policy.owner_of(entry_folder) != context_id:
            raise PolicyError('entry context unavailable')
        if entry_index is None:
            entry_index = policy._context_indexes.get(context_id)
            if entry_index is None: raise PolicyError('entry index unavailable')
        entry_index = safe_path(entry_index)
        if str(PurePosixPath(entry_index).parent) != policy.contexts[context_id]['root']:
            raise PolicyError('entry index unavailable')
        if additional_readers and queries:
            raise PolicyError('additional reader query authorization requires explicit requalification')
    for value in (task_id, goal, output, integrator, context_id):
        if isinstance(value, str): _reject_secrets(value)
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 0:
        raise PolicyError('invalid byte budget')
    if query_fingerprint is not None: raise PolicyError('dynamic query fingerprint must be computed by the builder')
    if not isinstance(queries, (list, tuple)) or len(queries) > 8: raise PolicyError('invalid query list')
    if not isinstance(omissions, (list, tuple)) or any(not isinstance(x, str) or not x for x in omissions): raise PolicyError('invalid omissions')
    if not isinstance(evidence, list): raise PolicyError('evidence must be a list')
    has_range = any(isinstance(item, dict) and 'range' in item for item in evidence)
    if allow_owned_ranges and (allow_owned_range or not has_range):
        raise PolicyError('owned ranges unavailable')
    if allow_owned_range is True and not has_range:
        raise PolicyError('owned range required')
    if has_range:
        from wiki_core.coordination_context import CoordinationBinding
        if ((allow_owned_range is not True and allow_owned_ranges is not True) or not folder_mode
                or (allow_owned_range is True and len(evidence) != 1) or queries or additional_readers
                or not isinstance(trusted_binding, CoordinationBinding)):
            raise PolicyError('owned range unavailable')
        if allow_owned_ranges:
            if sum(isinstance(item, dict) and 'range' in item for item in evidence) != 1:
                raise PolicyError('exactly one owned range required')
            if any(not isinstance(item, dict) or item.get('producer') != context_id
                   or not isinstance(item.get('ref'), str)
                   or policy.owner_of(safe_path(item['ref'])) != context_id for item in evidence):
                raise PolicyError('owned ranges unavailable')
        for item in (item for item in evidence if isinstance(item, dict) and 'range' in item):
            if (item.get('producer') != context_id or (allow_owned_range and item.get('ref') != output) or 'section' in item or 'field' in item
                or not isinstance(item.get('ref'), str) or policy.owner_of(safe_path(item['ref'])) != context_id
                or not isinstance(item.get('range'), dict)):
                raise PolicyError('owned range unavailable')
            # Context instructions and indexes are always delivered in full.
            if (item['ref'] in policy._folder_names or item['ref'] == entry_index
                or item['ref'] in policy._context_indexes.values()):
                raise PolicyError('owned range conflicts with context qualification')
    lineage = policy.lineage(context_id)
    if folder_mode:
        qualification_evidence = [{k: v for k, v in item.items() if k != 'range'} for item in evidence] if has_range else evidence
        _qualify_trusted_producers(root, policy, context_id, qualification_evidence, max_bytes,
                                   trusted_binding=trusted_binding, additional_readers=additional_readers)
        policy_reader, qualification_refs = qualify_folder_context(root, policy, context_id, entry_folder, entry_index, max_bytes,
                                                                    additional_readers=additional_readers)
    else:
        policy_reader, qualification_refs = RepositoryReader(Path(root), policy.policy_revision), []
    if adapter_report is not None and not valid_adapter_report(adapter_report): raise PolicyError('invalid adapter report')
    if adapter_report is not None: _reject_secrets(adapter_report)
    if not isinstance(required_capabilities, (list, tuple)):
        raise PolicyError('invalid required capabilities')
    for effect in required_capabilities:
        if not isinstance(effect, dict) or set(effect) != {'capability', 'target'} or not all(isinstance(x, str) and x.strip() for x in effect.values()):
            raise PolicyError('capability and exact target required')
        if capability_status(policy, context_id, effect['capability'], adapter_report, target=effect['target']) != 'available':
            raise PolicyError('required capability lacks verified adapter evidence')
    reader = RepositoryReader(Path(root), content_revision)
    if folder_mode and reader.revision != policy.policy_revision:
        from wiki_core.context_policy import _git
        try: _git(Path(root), 'merge-base', '--is-ancestor', reader.revision, policy.policy_revision)
        except PolicyError as exc: raise PolicyError('content revision is not approved') from exc
    selected = []
    seen = set()
    historical_policies = {}
    # Rules are read from the approved policy revision, never historical content.
    if folder_mode and entry_folder != '.' and not any(ref.startswith(entry_folder + '/') for ref in policy_reader.paths):
        raise PolicyError('entry folder unavailable in approved tree')
    def add(reader_, ref, reason, kind, section=None, field=None, producer=None, use=None, classification=None, byte_range=None):
        ref = safe_path(ref)
        denied = any(within(ref, scope) for scope in policy.effective[context_id]['deny']['read'])
        if denied or (kind != 'mandatory' and not policy.permits(context_id, 'read', ref)): raise PolicyError('read denied')
        if folder_mode:
            for reader_context in additional_readers:
                if policy._connection(producer, reader_context, ref, use or 'interpretation', classification or 'context',
                                      section=section, field=field, qualified=False) != 'approved':
                    raise PolicyError('additional reader not authorized for selected body')
            if kind != 'mandatory' and reader_.revision != policy.policy_revision:
                from wiki_core.context_policy import historical_policy
                if reader_.revision not in historical_policies:
                    historical_policies[reader_.revision] = historical_policy(policy, reader_.revision, authority_format='folder')
                prior = historical_policies[reader_.revision]
                try:
                    if (prior.owner_of(ref) != producer or
                            prior.contexts[producer]['owner'] != policy.contexts[producer]['owner'] or any(
                            prior.contexts[ctx]['owner'] != policy.contexts[ctx]['owner'] or
                            prior._connection(producer, ctx, ref, use or 'interpretation', classification or 'context',
                                section=section, field=field, qualified=False) != 'approved'
                            for ctx in (context_id, *additional_readers))):
                        raise PolicyError('historical evidence read not authorized')
                except (KeyError, ValueError) as exc:
                    raise PolicyError('historical evidence read not authorized') from exc
            from wiki_core.traversal import require_wiki_boundaries
            try: require_wiki_boundaries(Path(root), files=(Path(root) / ref,))
            except (ValueError, OSError) as exc: raise PolicyError('context body unavailable') from exc
        if folder_mode:
            guard_folder_blob(root, policy, ref)
            item = reader_.read(ref, section=section, field=field, byte_range=byte_range,
                                before_blob=lambda path: guard_folder_blob(root, policy, path))
        else:
            item = reader_.read(ref, section=section, field=field)
        text = item['text']
        if not isinstance(text, str): raise PolicyError('reader returned non-text')
        _reject_secrets(text)
        data = text.encode('utf-8')
        digest = hashlib.sha256(data).hexdigest()
        if item['content_digest'] != digest: raise PolicyError('reader digest mismatch')
        selected.append({'kind': kind, 'ref': ref, 'section': section, 'field': field,
                         'text': text, 'byte_length': len(data), 'sha256': digest,
                         'revision': item['revision'], 'document_sha256': item['content_sha256'],
                         'origin': item['origin'], 'reason': reason, 'producer': producer, 'use': use, 'classification': classification})
        if byte_range is not None: selected[-1]['range'] = copy.deepcopy(byte_range)
    if folder_mode:
        parts = [] if entry_folder == '.' else entry_folder.split('/')
        folders = ['.'] + ['/'.join(parts[:i]) for i in range(1, len(parts) + 1)]
        for folder in folders:
            prefix = '' if folder == '.' else folder + '/'
            for name in ('AGENTS.override.md', 'AGENTS.md'):
                ref = prefix + name
                if ref not in policy._folder_names: continue
                producer = policy.owner_of(ref)
                if policy.connection(producer, context_id, ref, 'interpretation', 'context') != 'approved':
                    raise PolicyError('instruction read not authorized')
                add(policy_reader, ref, f'mandatory instructions from {producer}', 'mandatory', producer=producer)
                if not selected[-1]['text'].strip():
                    selected.pop()
                    continue
                seen.add(ref)
                break
        if not seen: raise PolicyError('context instructions unavailable')
        if entry_index not in policy_reader.paths or policy.connection(
                context_id, context_id, entry_index, 'interpretation', 'context') != 'approved':
            raise PolicyError('index read not authorized or unavailable')
        add(policy_reader, entry_index, 'selected context index', 'evidence',
            producer=context_id, use='interpretation', classification='context')
        if not selected[-1]['text'].strip(): raise PolicyError('context index empty')
        for ref in qualification_refs:
            if ref in {item['ref'] for item in selected}: continue
            producer = policy.owner_of(ref)
            if policy.connection(producer, context_id, ref, 'interpretation', 'context') != 'approved':
                raise PolicyError('context body not authorized')
            add(policy_reader, ref, 'qualified context boundary', 'evidence',
                producer=producer, use='interpretation', classification='context')
    else:
        for c in lineage:
            for key in ('instructions', 'skills', 'templates'):
                for ref in c[key]:
                    if ref not in seen:
                        add(policy_reader, ref, f"mandatory {key} from {c['id']}", 'mandatory', producer=c['id'])
                        seen.add(ref)
    mandatory_bytes = sum(x['byte_length'] for x in selected)
    if mandatory_bytes > max_bytes: raise PolicyError('mandatory content exceeds byte budget')
    if not isinstance(evidence, list): raise PolicyError('evidence must be a list')
    for e in evidence:
        allowed = {'ref','producer','reason','use','classification','section','field'} | ({'range'} if has_range else set())
        if not isinstance(e, dict) or set(e) - allowed or not all(isinstance(e.get(k), str) and e[k] for k in ('ref','producer','reason','use','classification')):
            raise PolicyError('invalid evidence')
        for value in e.values():
            if isinstance(value, str): _reject_secrets(value)
        ref = safe_path(e['ref'])
        if any(k in e and (not isinstance(e[k], str) or not e[k]) for k in ('section','field')) or ('section' in e and 'field' in e): raise PolicyError('invalid evidence selector')
        status = policy.connection(e['producer'], context_id, ref, e['use'], e['classification'], section=e.get('section'), field=e.get('field'))
        if folder_mode and e['producer'] not in policy._qualified_contexts:
            preliminary = policy._connection(e['producer'], context_id, ref, e['use'], e['classification'],
                                             section=e.get('section'), field=e.get('field'), qualified=False)
            if preliminary == 'approved': raise PolicyError('producer context requires authorized requalification')
            status = preliminary
        if status != 'approved': raise PolicyError('connection ' + status)
        add(reader, ref, e['reason'], 'evidence', e.get('section'), e.get('field'), e['producer'], e['use'], e['classification'], byte_range=e.get('range'))
    query_selections = []
    for entry in queries:
        receipt, anchor, members = select_query(policy, context_id, reader, entry,
                                                entry_folder=entry_folder if folder_mode else None,
                                                entry_index=entry_index if folder_mode else None)
        if receipt['query_id'] in {r['query_id'] for r in query_selections}: raise PolicyError('duplicate query')
        for item in [anchor, *members]:
            section = entry['query'].get('section') if item is not anchor else None
            field = entry['query'].get('field') if item is not anchor else None
            add(reader, item['path'], entry['reason'], 'evidence', section, field, context_id, entry['use'], entry['classification'])
            selected[-1]['query_id'] = receipt['query_id']
        query_selections.append(receipt)
    total = sum(x['byte_length'] for x in selected)
    if total > max_bytes: raise PolicyError('selected content exceeds byte budget')
    policy.fresh()  # Fail if approval moved during composition.
    # Inputs retain their separate roles even when they refer to the same read.
    declared_read_set = declared_reads_from_inputs(selected, folder_mode=folder_mode)
    packet = {'schema_version': 'wiki.task-context/v3' if allow_owned_ranges else 'wiki.task-context/v2' if has_range else 'wiki.task-context/v1', 'task_id': task_id, 'goal': goal, 'output': output, 'integrator': integrator, 'context_id': context_id,
            'content_revision': reader.revision, 'policy_revision': policy.policy_revision, 'context': _context_view(policy, context_id),
            'inputs': selected, 'declared_read_set': declared_read_set,
            'query_fingerprint': None, 'coverage': {'mode': 'explicit_read_set', 'complete': False, 'missing': list(omissions)},
            'max_bytes': max_bytes, 'bytes_used': 0, 'selected_text_bytes': total,
            'capability_evidence': adapter_report, 'required_capabilities': list(required_capabilities), 'enforcement_claim': 'none; adapter report is supplied by the caller'}
    if folder_mode:
        packet.update(authority_format='folder', entry_folder=entry_folder, entry_index=entry_index)
        if additional_readers: packet['additional_readers'] = list(additional_readers)
        if 'linked sources not inspected' not in packet['coverage']['missing']:
            packet['coverage']['missing'].append('linked sources not inspected')
    if query_selections:
        packet['query_selections'] = query_selections
        packet['query_fingerprint'] = digest(query_selections)
        packet['coverage']['mode'] = 'authorized_owner_queries_and_explicit_read_set'
    # A fixed-width digest lets the reported byte count include the digest itself.
    return _finalize_packet(packet, max_bytes)


def validate_result(result, packet):
    """Validate a reported result and bind it to the actual canonical packet."""
    from jsonschema import ValidationError, validate
    if not isinstance(packet, dict) or packet.get('schema_version') not in ('wiki.task-context/v1', 'wiki.task-context/v2', 'wiki.task-context/v3'):
        raise PolicyError('invalid packet')
    version = packet['schema_version'].rsplit('/', 1)[1]
    schema_path = Path(__file__).resolve().parents[1] / f'docs/references/schemas/wiki-task-result-{version}.schema.json'
    try:
        validate(result, json.loads(schema_path.read_text(encoding='utf-8')))
    except (ValidationError, OSError, ValueError) as exc:
        raise PolicyError('invalid task result') from exc
    if not isinstance(packet, dict) or not isinstance(packet.get('packet_digest'), str): raise PolicyError('invalid packet')
    payload = {k: v for k, v in packet.items() if k != 'packet_digest'}
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if digest != packet['packet_digest'] or any(result[k] != packet.get(k) for k in ('task_id', 'context_id', 'packet_digest')):
        raise PolicyError('result is not bound to this packet')
    queries = {row['query_id'] for row in packet.get('query_selections', [])}
    observed_queries = set(result['read_coverage'].get('observed_queries', []))
    if not observed_queries.issubset(queries) or (queries and result['status'] == 'completed' and observed_queries != queries):
        raise PolicyError('result query coverage differs from packet')
    declared = {json.dumps(item, sort_keys=True) for item in packet['declared_read_set']}
    observed = {json.dumps(item, sort_keys=True) for item in result['read_coverage']['observed_refs']}
    if queries and result['status'] == 'completed' and observed != declared: raise PolicyError('query task must report every delivered input')
    if packet.get('authority_format') == 'folder' and result['status'] == 'completed' and observed != declared:
        raise PolicyError('folder task must report every delivered input')
    if packet.get('authority_format') == 'folder' and result['status'] == 'completed':
        if not set(packet['coverage']['missing']).issubset(result['read_coverage']['missing']):
            raise PolicyError('folder task must preserve missing coverage')
    if not observed.issubset(declared): raise PolicyError('result reports undeclared reads')
    return True
