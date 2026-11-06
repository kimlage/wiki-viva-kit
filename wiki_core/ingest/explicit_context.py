"""Explicit ingestion context over bodies already delivered by an authorized packet.

The selection is supplied by the caller on each stage. These helpers do not
look up pages, read files or grant access: the existing bound packet builder
must authorize each evidence selector for every reader before loading its body.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace

from wiki_core.frontmatter import list_values, parse_frontmatter
from wiki_core.input_stage import (_channel_payload, _quadrant_boundary_rule,
    _quadrant_semantics, _resolved_perspectives, _root_payload)
from wiki_core.quadrants import DEFAULT_QUADRANT_MAP
from wiki_core.repository_reader import canonical_path


class ExplicitContextError(ValueError):
    """An explicit interpretation selection is missing or inconsistent."""


def _is_path_reference(ref):
    return isinstance(ref, str) and ('/' in ref or '\\' in ref or ref.strip().lower().endswith('.md'))


def _canonical_selected_path(ref):
    path = canonical_path(ref)
    if path != ref or ref != ref.strip():
        raise ExplicitContextError('noncanonical context path')
    return path


def _declared_targets(value):
    if value is None:
        return []
    values = value if isinstance(value, (list, tuple)) else [value]
    if any(not isinstance(item, str) or item != item.strip() for item in values):
        raise ExplicitContextError('noncanonical target declaration')
    for item in values:
        if _is_path_reference(item):
            _canonical_selected_path(item)
    return [item for item in values if item]


def declared_reference_matches(ref, page):
    """Treat path-shaped references as paths, even when another page uses one as ID."""
    return (isinstance(ref, str) and isinstance(page, dict) and
            (ref == page.get('path') or (not _is_path_reference(ref) and ref == page.get('page_id'))))


def _selection(selection):
    keys = {'source_page', 'source_config', 'input_channel', 'root_entity',
            'omit_root_entity', 'templates', 'target_pages', 'target_selection',
            'repository_source_pages'}
    if not isinstance(selection, dict) or set(selection) - keys:
        raise ExplicitContextError('invalid explicit context selection')
    omitted = selection.get('omit_root_entity', False)
    if not isinstance(omitted, bool):
        raise ExplicitContextError('invalid root selection')
    root = selection.get('root_entity')
    if bool(root) == omitted:
        raise ExplicitContextError('select or explicitly omit the business root')
    clean = {'omit_root_entity': omitted}
    if 'target_selection' in selection:
        mode = selection['target_selection']
        if mode not in ('declared', 'explicit'):
            raise ExplicitContextError('invalid target selection')
        if mode == 'explicit' and 'target_pages' not in selection:
            raise ExplicitContextError('explicit target selection requires target_pages')
        clean['target_selection'] = mode
    for name in ('source_page', 'source_config', 'input_channel', 'root_entity'):
        value = selection.get(name)
        if value is not None:
            try:
                clean[name] = _canonical_selected_path(value)
            except (ValueError, TypeError) as exc:
                raise ExplicitContextError('invalid context path') from exc
    for name in ('templates', 'target_pages'):
        values = selection.get(name, [])
        if not isinstance(values, list) or len(values) > 32:
            raise ExplicitContextError('invalid context paths')
        try:
            clean[name] = [_canonical_selected_path(value) for value in values]
        except (ValueError, TypeError) as exc:
            raise ExplicitContextError('invalid context path') from exc
    repository_pages = selection.get('repository_source_pages', {})
    if (not isinstance(repository_pages, dict) or len(repository_pages) > 8
            or any(not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', key)
                   for key in repository_pages)):
        raise ExplicitContextError('invalid repository source selection')
    try:
        clean['repository_source_pages'] = {key: _canonical_selected_path(repository_pages[key]) for key in sorted(repository_pages)}
    except (ValueError, TypeError) as exc:
        raise ExplicitContextError('invalid repository source selection') from exc
    refs = [clean[name] for name in ('source_page', 'source_config', 'input_channel', 'root_entity') if name in clean]
    refs += clean['templates'] + clean['target_pages']
    if len(refs) != len(set(refs)):
        raise ExplicitContextError('context selections must be distinct')
    return clean


def explicit_ingestion_evidence(policy, selection):
    """Return literal packet selectors, without opening or authorizing bodies."""
    selected = _selection(selection)
    rows = []
    refs = [(name, selected[name]) for name in
            ('source_page', 'source_config', 'input_channel', 'root_entity') if name in selected]
    refs += [('template', ref) for ref in selected['templates']]
    refs += [('target_page', ref) for ref in selected['target_pages']]
    refs += [('repository_source_page:' + key, ref) for key, ref in selected['repository_source_pages'].items()]
    for role, ref in refs:
        rows.append({'ref': ref, 'producer': policy.owner_of(ref),
            'reason': 'Explicit ingestion ' + role, 'use': 'interpretation',
            'classification': 'source' if role == 'source_page' or role.startswith('repository_source_page:') else 'context'})
    return rows


def connected_ingestion_selection(packet, selection):
    """Extend a selection from declared links in already authorized bodies.

    Return selectors only. The caller must authorize and read them through the
    same packet builder before interpreting them. Hub links select candidates,
    never establish consumption or permission to update a subject.
    """
    selected = _selection(selection)
    pages = {}
    for row in packet['inputs']:
        if row.get('kind') == 'evidence' or row.get('ref') == packet.get('entry_index'):
            values, body = parse_frontmatter(row['text'])
            pages[row['ref']] = (values, body)
    by_id = {}
    for ref, (values, _) in pages.items():
        if values.get('page_id'):
            by_id.setdefault(values['page_id'], []).append(ref)

    def path(value):
        if not isinstance(value, str) or not value:
            return None
        if _is_path_reference(value):
            return _canonical_selected_path(value)
        if len(by_id.get(value, [])) == 1:
            return by_id[value][0]
        return None  # An unresolved page ID is not permission to scan the wiki.

    def values(role):
        return pages.get(selected.get(role), ({}, ''))[0]

    for role, refs in (
        ('source_config', [values('source_page').get('config_ref')]),
        ('input_channel', [values('source_page').get('input_channel_ref'),
                           values('source_config').get('input_channel_ref')]),
    ):
        if role not in selected:
            choices = {ref for value in refs if (ref := path(value))}
            if len(choices) > 1:
                raise ExplicitContextError('conflicting declared ingestion references')
            if choices:
                selected[role] = choices.pop()

    targets = list(selected['target_pages'])
    if selected.get('target_selection') != 'explicit':
        for role in ('source_page', 'source_config', 'input_channel'):
            targets.extend(ref for value in _declared_targets(values(role).get('target_pages')) if (ref := path(value)))
    roles = {selected[name] for name in ('source_page', 'source_config', 'input_channel', 'root_entity') if name in selected}
    selected['target_pages'] = list(dict.fromkeys(ref for ref in targets if ref not in roles and ref not in selected['templates']))
    return _selection(selected)


def connected_ingestion_candidates(packet, targets):
    """Select subjects linked by connected hubs; reads still require authority."""
    from wiki_core.graph.page_graph import MARKDOWN_LINK_RE
    from wiki_core.information_relations import _path_from_link
    refs = list(targets)
    for row in packet['inputs']:
        if row.get('ref') not in targets:
            continue
        metadata, body = parse_frontmatter(row['text'])
        if metadata.get('page_type') in ('context_hub', 'moc', 'root_entity'):
            refs.extend(target for match in MARKDOWN_LINK_RE.finditer(body)
                if (target := _path_from_link(None, row['ref'], match.group(1))) and target.endswith('.md'))
    return list(dict.fromkeys(refs))


def resolve_explicit_ingestion_context(packet, selection, config):
    """Project selected packet bodies into the established request metadata.

    The caller must use the host-bound builder and revalidate its policy and
    exact selection on every operation. Packet digests and paths are consistency
    checks, not proof of authority or of the agent having read the documents.
    """
    selected = _selection(selection)
    if not isinstance(packet, dict) or packet.get('authority_format') != 'folder':
        raise ExplicitContextError('approved folder packet required')
    payload = {key: value for key, value in packet.items() if key != 'packet_digest'}
    expected = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode('utf-8')).hexdigest()
    if packet.get('packet_digest') != expected or not isinstance(packet.get('inputs'), list):
        raise ExplicitContextError('context packet unavailable')

    def body(ref, role):
        rows = [row for row in packet['inputs'] if isinstance(row, dict)
                and row.get('ref') == ref and row.get('kind') == 'evidence'
                and row.get('reason') == 'Explicit ingestion ' + role
                and row.get('use') == 'interpretation'
                and row.get('classification') == ('source' if role == 'source_page' or role.startswith('repository_source_page:') else 'context')]
        if len(rows) != 1 or not isinstance(rows[0].get('text'), str):
            raise ExplicitContextError('selected context body unavailable')
        row = rows[0]
        text = row['text']
        digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
        if (row.get('section') is not None or row.get('field') is not None
                or row.get('sha256') != digest or row.get('document_sha256') != digest
                or row.get('revision') != packet.get('content_revision')):
            raise ExplicitContextError('selected context body unavailable')
        return text

    def page(name, expected_type=None):
        ref = selected.get(name)
        if not ref:
            return None
        values, _ = parse_frontmatter(body(ref, name))
        page_id, page_type = values.get('page_id'), values.get('page_type')
        if (not isinstance(page_id, str) or not page_id.strip()
                or not isinstance(page_type, str) or not page_type.strip()
                or expected_type is not None and page_type != expected_type):
            raise ExplicitContextError('selected context page invalid')
        return {'path': ref, 'page_id': page_id, 'page_type': page_type,
                'title': str(values.get('title') or page_id),
                'context': str(values.get('context') or ''), 'values': values}

    source = page('source_page', 'source')
    config_page = page('source_config', 'source_config')
    channel_page = page('input_channel', 'input_channel')
    root_page = page('root_entity')
    if root_page and root_page['page_type'] not in ('root_entity', 'context_hub'):
        raise ExplicitContextError('selected business root type is not qualified')
    repository_sources = {}
    for key, ref in selected['repository_source_pages'].items():
        values, _ = parse_frontmatter(body(ref, 'repository_source_page:' + key))
        if (values.get('page_type') != 'source' or values.get('platform') != 'repo'
                or not isinstance(values.get('page_id'), str) or not values['page_id'].strip()
                or not isinstance(values.get('source_locator'), str) or not values['source_locator'].strip()):
            raise ExplicitContextError('repository source page invalid')
        repository_sources[key] = {'path': ref, 'page_id': values['page_id'],
                                   'source_locator': values['source_locator']}
    # Validate every explicitly requested body even when it is only a template
    # or destination candidate. A link from a page never counts as a read.
    for name, role in (('templates', 'template'), ('target_pages', 'target_page')):
        for ref in selected[name]:
            body(ref, role)

    def verify_link(expected_ref, page_):
        if expected_ref and not declared_reference_matches(expected_ref, page_):
            raise ExplicitContextError('declared context reference requires explicit matching selection')

    def declared_ref(value):
        if value is None or value == '':
            return ''
        if not isinstance(value, str):
            raise ExplicitContextError('invalid declared context reference')
        return value

    values = (source or {}).get('values', {})
    config_ref = declared_ref(values.get('config_ref'))
    verify_link(config_ref, config_page)
    channel_refs = [declared_ref(values.get('input_channel_ref')),
                    declared_ref((config_page or {}).get('values', {}).get('input_channel_ref'))]
    for ref in channel_refs:
        verify_link(ref, channel_page)

    source_config = None
    if config_page:
        values = config_page['values']
        source_config = {'path': config_page['path'], 'page_id': config_page['page_id'],
            **{key: list_values(values.get(key)) for key in ('perspectives_required',
                'perspectives_optional', 'perspectives_skip_with_reason', 'process_refs',
                'quadrants')},
            'target_pages': _declared_targets(values.get('target_pages')),
            'input_channel_ref': str(values.get('input_channel_ref') or '')}
    channel = _channel_payload(channel_page) if channel_page else None
    if channel is not None:
        channel['target_pages'] = _declared_targets(channel_page['values'].get('target_pages'))
    root = None
    if root_page:
        # A locally selected root does not inherit the global business bundle
        # unless it is the configured business root itself.
        root_config = config
        if (config.root_entity or {}).get('page') != root_page['path']:
            root_config = replace(config, root_entity={'page': root_page['path'],
                'entity_type': str(root_page['values'].get('root_entity_type') or root_page['page_type']),
                'perspective_bundle': {'required': [], 'optional': []}, 'input_stage_page': ''})
        root = _root_payload(root_page, root_config)
    perspectives = _resolved_perspectives(root, channel, source_config)
    gaps = []
    if selected['omit_root_entity']:
        gaps.append('Business root intentionally omitted; if required, block substantive interpretation until selected.')
    if not source:
        gaps.append('Source page and linked configuration not inspected.')
    elif not config_page:
        gaps.append('Source configuration not selected; other source links not inspected.')
    if not channel_page:
        gaps.append('Input channel not selected.')
    for perspective in perspectives['skipped']:
        gaps.append('Perspective ' + perspective + ' skipped; its justification requires review.')
    for ref in (source_config or {}).get('process_refs', []):
        gaps.append('Source process reference ' + ref + ' not inspected.')
    target_ids = {parse_frontmatter(body(ref, 'target_page'))[0].get('page_id')
                  for ref in selected['target_pages']}
    for origin, fields in (('Source', (source or {}).get('values', {})),
                           ('Source configuration', (config_page or {}).get('values', {})),
                           ('Input channel', (channel_page or {}).get('values', {}))):
        for ref in _declared_targets(fields.get('target_pages')):
            # A path-like declaration denotes that path, even if a different
            # selected page happens to use the same string as its page_id.
            covered = ref in selected['target_pages'] or (not _is_path_reference(ref) and ref in target_ids)
            if not covered:
                gaps.append(origin + ' target ' + str(ref) + ' not selected.')
    if selected['target_pages']:
        gaps.append('Selected target pages are candidates; selection does not grant write access.')
    gaps.append('Other linked sources and unselected targets not inspected.')
    return {'source_config': source_config, 'root_entity': root, 'input_channel': channel,
        'quadrant_map': DEFAULT_QUADRANT_MAP, 'quadrant_semantics': _quadrant_semantics(config),
        'quadrant_boundary_rule': _quadrant_boundary_rule(config),
        'target_pages': list(selected['target_pages']),
        'perspectives_required': perspectives['required'], 'perspectives_optional': perspectives['optional'],
        'perspectives_skipped': perspectives['skipped'],
        'repository_sources': repository_sources,
        'input_stage_status': 'explicit_authorized_refs_only', 'context_omissions': gaps,
        'source_page_association': 'operator_selected_unverified' if source else 'not_selected',
        'source_config_association': ('declared_reference_matched' if config_ref else
            'operator_selected_unverified' if config_page else 'not_selected'),
        'input_channel_association': ('declared_reference_matched' if any(channel_refs) else
            'operator_selected_unverified' if channel_page else 'not_selected')}
