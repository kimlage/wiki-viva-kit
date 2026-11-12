"""Qualified synthetic C3 scopes, never consumer data or operational grants."""
import hashlib

import pytest
import yaml

from tests.test_navigation_migration import repo, move, sha, audit_action
from tests.test_freshness_impact import page, commit, git
from tests.test_action_transition import _write_action
from wiki_core.action_transition import _parse_document, transition_action_page
from wiki_core.coordination_context import (
    CoordinationBinding, ProtectedCoordinationError, prepare_packet, prepare_preflight,
)
from wiki_core.markdown_link_roles import declare_link_role
from wiki_core.navigation import NavigationHistory


def physical_hierarchy(root, *, writable=True):
    """Existing root-owned scope, with editorial organization/project indexes.

    Indexes alone do not create ACL contexts. They inherit the physical root
    instructions and explicit existing scope, qualified by the normal packet.
    """
    config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
    config['context_access'] = {'.': {'owner': 'synthetic operator', 'policy': {
        'read': ['self'], 'write': ['self'] if writable else [],
        'capabilities': [], 'deny': {}, 'publication': []}}}
    (root / 'wiki.config.yaml').write_text(yaml.safe_dump(config))
    (root / 'AGENTS.md').write_text('# Synthetic root instructions\nC3 retains action history.\n')
    (root / 'index.md').write_text('# Synthetic physical entry\n')
    (root / '.gitignore').write_text('data/derived/\n')
    page(root, 'index')
    alpha = page(root, 'alpha', context='alpha-editorial', sources_policy='old-curation')
    alpha.write_text(alpha.read_text().replace('page_type: project', 'page_type: context_hub'))
    page(root, 'organization-beta/index', context='beta-editorial', sources_policy='organization-curation',
         moc_parent='memories/index.md')
    project = page(root, 'organization-beta/project-gamma/index', context='gamma-editorial',
                   sources_policy='project-curation', moc_parent='memories/organization-beta/index.md')
    return project


def bound_packet(root, base, refs):
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    packet = prepare_packet(root, binding, dict(context_id='.', approved_revision=base,
        content_revision=base, entry_folder='memories', task=dict(task_id='synthetic-c3',
            goal='Reframe the selected alpha action under organization beta / project gamma.',
            output='memories/organization-beta/project-gamma/action.md', integrator='synthetic operator',
            max_bytes=100000, evidence=[dict(ref=ref, reason='selected C3 scope',
                use='interpretation', classification='context',
                expected_document_sha256=hashlib.sha256((root / ref).read_bytes()).hexdigest())
                for ref in refs])))['packet']
    return binding, packet


@pytest.mark.parametrize('mutation', ['none', 'read_only', 'missing_instructions', 'owner',
    'action_context', 'action_owner', 'expanded_authority', 'false_parent', 'outside', 'missing_binding'])
def test_qualified_project_reframing_preserves_action_and_uses_normal_host_preflight(repo, monkeypatch, mutation):
    project = physical_hierarchy(repo, writable=mutation != 'read_only')
    if mutation != 'read_only':
        config = yaml.safe_load((repo / 'wiki.config.yaml').read_text())
        config['context_access']['.']['policy']['write'] = [
            'memories/actions', 'memories/organization-beta/project-gamma']
        (repo / 'wiki.config.yaml').write_text(yaml.safe_dump(config))
    action = _write_action(repo, extra={'moc_parent': 'memories/alpha.md',
                                      'owner_kind': 'human', 'owner_ref': 'synthetic operator'})
    before = action.read_bytes()
    old_ref = action.relative_to(repo).as_posix()
    if mutation == 'missing_instructions':
        (repo / 'AGENTS.md').unlink()
    elif mutation == 'owner':
        project.write_bytes(project.read_bytes().replace(b'page_type: project', b'page_type: project\nowner_ref: other'))
    elif mutation == 'false_parent':
        project.write_bytes(project.read_bytes().replace(b'moc_parent: memories/organization-beta/index.md',
                                                        b'moc_parent: memories/alpha.md'))
    elif mutation == 'expanded_authority':
        project.parent.joinpath('AGENTS.md').write_text('# Separate physical context\n')
        # A common human owner and read access are not a write grant across
        # contexts. No new access entry or bilateral connection is invented.
    base = commit(repo); git(repo, 'update-ref', 'refs/remotes/origin/main', base)
    binding = packet = None
    if mutation not in {'missing_instructions', 'expanded_authority'}:
        binding, packet = bound_packet(repo, base, [old_ref, 'memories/alpha.md',
            'memories/organization-beta/index.md', project.relative_to(repo).as_posix()])
    git(repo, 'checkout', '-qb', 'wiki/qualified-c3')
    destination = 'memories/organization-beta/project-gamma/action.md'
    if mutation == 'outside':
        destination = 'memories/outside/action.md'
    move(repo, old_ref, destination)
    action = repo / destination
    # Keep the real exact move, then the exact structural stage.
    commit(repo)
    action.write_bytes(before.replace(b'moc_parent: memories/alpha.md',
        b'moc_parent: memories/organization-beta/project-gamma/index.md'))
    if mutation == 'action_context':
        action.write_bytes(action.read_bytes().replace(b'context: example', b'context: gamma-editorial'))
    elif mutation == 'action_owner':
        action.write_bytes(action.read_bytes().replace(b'owner_ref: synthetic operator', b'owner_ref: other'))
    structural = action.read_bytes(); stage = commit(repo)
    transition_action_page(repo, action, 'open', page_edit={'title': 'Reviewed synthetic title'},
                           expected_sha256=sha(action), recorded_at='2026-07-12T12:00:00Z')
    head = commit(repo)
    errors = audit_action(repo, monkeypatch)
    assert bool(errors) == (mutation not in {'none', 'missing_binding'})
    if packet:
        result = dict(schema_version='wiki.task-result/v1', status='completed',
            task_id=packet['task_id'], context_id='.', packet_digest=packet['packet_digest'],
            changes=[dict(path=old_ref, action='deleted'), dict(path=destination, action='created')],
            read_coverage=dict(observed_refs=packet['declared_read_set'], missing=packet['coverage']['missing']), blockers=[])
        payload = dict(context_id='.', approved_revision=base, base=base, head=head,
            branch='wiki/qualified-c3', packet=packet, result=result)
        if mutation in {'read_only', 'missing_binding'}:
            with pytest.raises(ProtectedCoordinationError):
                prepare_preflight(repo, None if mutation == 'missing_binding' else binding, payload)
        elif mutation == 'none':
            preflight = prepare_preflight(repo, binding, payload)['preflight']
            assert preflight['state'] == 'independent_review_required'
            assert preflight['review'] == preflight['merge'] == 'not_performed'
    if mutation == 'none':
        original, original_body = _parse_document(before.decode())
        staged, staged_body = _parse_document(structural.decode())
        assert staged_body == original_body
        assert {k: v for k, v in original.items() if k != 'moc_parent'} == {
            k: v for k, v in staged.items() if k != 'moc_parent'}
        assert git(repo, 'show', stage + ':' + destination) + '\n' == structural.decode()
        assert git(repo, 'rev-parse', 'main') == base


@pytest.mark.parametrize('newline', ['\n', '\r\n'], ids=['lf', 'crlf'])
@pytest.mark.parametrize('mutation', ['none', 'metadata', 'metadata_only', 'new_url', 'copy',
    'transplant', 'reorder', 'duplicate', 'role', 'pin', 'digest', 'revert', 'authority'])
def test_preserved_records_map_prepend_offsets_and_structural_metadata(repo, newline, mutation):
    physical_hierarchy(repo)
    page(repo, 'guide')
    role = declare_link_role('[Observed](guide.md)', 'review_record')
    old_record = '## [2026-07-10] Original\n\n' + role + '\n'
    second = '## [2026-07-09] Earlier\n\nA different observation.\n'
    log = page(repo, 'log', body='# Log\n\n' + old_record + '\n' + second,
               moc_parent='memories/alpha.md', consumed_revision='a' * 40)
    log.write_bytes(log.read_bytes().replace(b'\n', newline.encode()))
    original = log.read_bytes(); origin = commit(repo)
    move(repo, 'memories/guide.md', 'memories/navigation/guide.md'); commit(repo)
    if mutation == 'revert':
        log.write_bytes(original.replace(b'Original', b'Factual detour')); commit(repo)
        log.write_bytes(original); commit(repo)
    if mutation in {'metadata', 'metadata_only', 'authority'}:
        move(repo, 'memories/log.md', 'memories/organization-beta/project-gamma/log.md'); commit(repo)
        log = repo / 'memories/organization-beta/project-gamma/log.md'
    addition = '## [2026-07-11] New\n\n' + (role if mutation == 'new_url' else 'New entry.') + '\n\n'
    if mutation != 'metadata_only':
        log.write_bytes(log.read_bytes().replace(old_record.replace('\n', newline).encode(),
            (addition + old_record).replace('\n', newline).encode()))
    if mutation in {'metadata', 'metadata_only', 'authority'}:
        log.write_bytes(log.read_bytes().replace(b'moc_parent: memories/alpha.md',
            b'moc_parent: memories/organization-beta/project-gamma/index.md'))
    if mutation == 'authority':
        log.write_bytes(log.read_bytes().replace(b'page_type: project', b'page_type: project\nowner_ref: other'))
    elif mutation == 'copy':
        copied = log.with_name('copy.md'); copied.write_bytes(log.read_bytes()); log = copied
    elif mutation == 'transplant':
        log.write_bytes(log.read_bytes().replace(b'page_id: log', b'page_id: other-log'))
    elif mutation == 'reorder':
        body = '# Log\n\n' + addition + second + '\n' + old_record
        prefix = log.read_bytes().decode().split('---', 2)[:2]
        log.write_bytes(('---'.join(prefix) + '---' + newline + body.replace('\n', newline)).encode())
    elif mutation == 'duplicate':
        log.write_bytes(log.read_bytes() + (newline + old_record.replace('\n', newline)).encode())
    elif mutation == 'role':
        log.write_bytes(log.read_bytes().replace(b'review_record', b'factual_support'))
    elif mutation == 'pin':
        log.write_bytes(log.read_bytes().replace(('a' * 40).encode(), ('b' * 40).encode()))
    elif mutation == 'digest':
        log.write_bytes(log.read_bytes().replace(b'sha256:', b'sha256:0'))
    commit(repo)
    raw = log.read_bytes().decode(); _, body = _parse_document(raw)
    ref = log.relative_to(repo).as_posix(); offset = body.rindex('[Observed]')
    nav = NavigationHistory(repo)
    resolved = nav.resolve(ref, raw, 'guide.md', href=True, body_offset=offset)
    if mutation in {'none', 'metadata', 'metadata_only', 'new_url'}:
        assert resolved == 'memories/navigation/guide.md'
        proof = nav.last_proof
        assert proof['source_revision'] == origin
        assert proof['occurrence']['current_body_offset'] == offset
        assert proof['occurrence']['body_offset'] == _parse_document(original.decode())[1].index('[Observed]')
        assert old_record.replace('\n', newline).encode() in log.read_bytes()
        if mutation == 'new_url':
            assert nav.resolve(ref, raw, 'guide.md', href=True, body_offset=body.index('[Observed]')) is None
    else:
        assert resolved is None
