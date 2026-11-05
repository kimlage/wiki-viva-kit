"""Explicit ingestion context over bodies already delivered by an authorized packet.

The selection is supplied by the caller on each stage. These helpers do not
look up pages, read files or grant access: the existing bound packet builder
must authorize each evidence selector for every reader before loading its body.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace

from wiki_core.frontmatter import list_values, parse_frontmatter
from wiki_core.input_stage import (_channel_payload, _quadrant_boundary_rule,
    _quadrant_semantics, _resolved_perspectives, _root_payload)
from wiki_core.quadrants import DEFAULT_QUADRANT_MAP
from wiki_core.repository_reader import canonical_path


class ExplicitContextError(ValueError):
    """An explicit interpretation selection is missing or inconsistent."""


def _selection(selection):
    keys = {'source_page', 'source_config', 'input_channel', 'root_entity',
            'omit_root_entity', 'templates', 'target_pages'}
    if not isinstance(selection, dict) or set(selection) - keys:
        raise ExplicitContextError('invalid explicit context selection')
    omitted = selection.get('omit_root_entity', False)
    if not isinstance(omitted, bool):
        raise ExplicitContextError('invalid root selection')
    root = selection.get('root_entity')
    if bool(root) == omitted:
        raise ExplicitContextError('select or explicitly omit the business root')
    clean = {'omit_root_entity': omitted}
    for name in ('source_page', 'source_config', 'input_channel', 'root_entity'):
        value = selection.get(name)
        if value is not None:
            try:
                clean[name] = canonical_path(value)
            except (ValueError, TypeError) as exc:
                raise ExplicitContextError('invalid context path') from exc
    for name in ('templates', 'target_pages'):
        values = selection.get(name, [])
        if not isinstance(values, list) or len(values) > 32:
            raise ExplicitContextError('invalid context paths')
        try:
            clean[name] = [canonical_path(value) for value in values]
        except (ValueError, TypeError) as exc:
            raise ExplicitContextError('invalid context path') from exc
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
    for role, ref in refs:
        rows.append({'ref': ref, 'producer': policy.owner_of(ref),
            'reason': 'Explicit ingestion ' + role, 'use': 'interpretation',
            'classification': 'source' if role == 'source_page' else 'context'})
    return rows


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
                and row.get('classification') == ('source' if role == 'source_page' else 'context')]
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
    # Validate every explicitly requested body even when it is only a template
    # or destination candidate. A link from a page never counts as a read.
    for name, role in (('templates', 'template'), ('target_pages', 'target_page')):
        for ref in selected[name]:
            body(ref, role)

    def verify_link(expected_ref, page_):
        if expected_ref and (page_ is None or expected_ref not in (page_['path'], page_['page_id'])):
            raise ExplicitContextError('declared context reference requires explicit matching selection')

    values = (source or {}).get('values', {})
    config_ref = str(values.get('config_ref') or '')
    verify_link(config_ref, config_page)
    channel_refs = [str(values.get('input_channel_ref') or ''),
                    str((config_page or {}).get('values', {}).get('input_channel_ref') or '')]
    for ref in channel_refs:
        verify_link(ref, channel_page)

    source_config = None
    if config_page:
        values = config_page['values']
        source_config = {'path': config_page['path'], 'page_id': config_page['page_id'],
            **{key: list_values(values.get(key)) for key in ('perspectives_required',
                'perspectives_optional', 'perspectives_skip_with_reason', 'process_refs',
                'target_pages', 'quadrants')},
            'input_channel_ref': str(values.get('input_channel_ref') or '')}
    channel = _channel_payload(channel_page) if channel_page else None
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
    if selected['target_pages']:
        gaps.append('Selected target pages are candidates; selection does not grant write access.')
    gaps.append('Other linked sources and unselected targets not inspected.')
    return {'source_config': source_config, 'root_entity': root, 'input_channel': channel,
        'quadrant_map': DEFAULT_QUADRANT_MAP, 'quadrant_semantics': _quadrant_semantics(config),
        'quadrant_boundary_rule': _quadrant_boundary_rule(config),
        'target_pages': list(selected['target_pages']),
        'perspectives_required': perspectives['required'], 'perspectives_optional': perspectives['optional'],
        'input_stage_status': 'explicit_authorized_refs_only', 'context_omissions': gaps,
        'source_page_association': 'operator_selected_unverified' if source else 'not_selected',
        'source_config_association': ('declared_reference_matched' if config_ref else
            'operator_selected_unverified' if config_page else 'not_selected'),
        'input_channel_association': ('declared_reference_matched' if any(channel_refs) else
            'operator_selected_unverified' if channel_page else 'not_selected')}
