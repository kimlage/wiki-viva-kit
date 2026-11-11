"""Synthetic exact-read scope contract; no host or symlink claim."""
import copy
import subprocess

import pytest
import yaml

from wiki_core.context_packet import build_packet, qualify_folder_context
from wiki_core.context_policy import ContextPolicy, PolicyError, load_policy, safe_path
from wiki_core.coordination_context import CoordinationBinding
from wiki_core.context_selection import select_query


def context(cid, parent, root, read, *, deny=(), imports=(), exports=()):
    return {'id': cid, 'parent': parent, 'root': root, 'purpose': 'synthetic', 'owner': 'synthetic',
            'instructions': [], 'skills': [], 'templates': [],
            'policy': {'read': read, 'write': [], 'capabilities': [], 'publication': [],
                       'deny': {'read': list(deny)}}, 'imports': list(imports), 'exports': list(exports)}


def make_policy(contexts):
    return ContextPolicy({'schema_version': 'wiki.context/v1', 'contexts': contexts}, 'synthetic')


def test_exact_read_and_existing_prefix_are_distinct():
    exact = make_policy([context('root', None, '.', ['file[docs/item.md]'])])
    assert exact.permits('root', 'read', 'docs/item.md')
    assert not exact.permits('root', 'read', 'docs/item.md/child')
    assert not exact.permits('root', 'read', 'docs/item.md2')
    prefix = make_policy([context('root', None, '.', ['docs/item.md'])])
    assert prefix.permits('root', 'read', 'docs/item.md/child')
    # The existing path parser (and earlier versions) reject the explicit form
    # rather than interpreting it as a legacy path grant.
    with pytest.raises(PolicyError): safe_path('file[docs/item.md]')


def test_deny_still_wins_and_invalid_forms_fail_closed():
    exact = make_policy([context('root', None, '.', ['file[docs/item.md]'], deny=['docs'])])
    assert not exact.permits('root', 'read', 'docs/item.md')
    for scope in ('file[]', 'file[../outside]', 'file[docs/*]', 'file[docs/item.md/]',
                  'file[file[docs/item.md]]', 'file[.]'):
        with pytest.raises(PolicyError): make_policy([context('root', None, '.', [scope])])
    with pytest.raises(PolicyError):
        make_policy([context('root', None, '.', ['.'], deny=['file[docs/item.md]'])])
    root = context('root', None, '.', ['.'])
    root['policy']['write'] = ['file[docs/item.md]']
    with pytest.raises(PolicyError): make_policy([root])


def test_exact_parent_cannot_be_widened_by_child():
    parent = context('root', None, '.', ['file[docs/item.md]'])
    child = context('child', 'root', 'child', ['file[docs/item.md]'])
    assert make_policy([parent, child]).permits('child', 'read', 'docs/item.md')
    for widening in ('docs/item.md', 'file[docs/item.md/child]', 'docs'):
        child['policy']['read'] = [widening]
        with pytest.raises(PolicyError, match='widens'):
            make_policy([parent, child])


def test_exact_relative_scope_and_denied_child_do_not_open_siblings():
    root = context('root', None, '.', ['.'])
    child = context('child', 'root', 'docs', ['file[self/item.md]'], deny=['self/item.md/child'])
    p = make_policy([root, child])
    assert p.effective['child']['read'] == ['file[docs/item.md]']
    assert p.permits('child', 'read', 'docs/item.md')
    assert not p.permits('child', 'read', 'docs/item.md/child')
    assert not p.permits('child', 'read', 'docs/item.md/other')


def test_exact_read_does_not_authorize_a_directory_query():
    p = make_policy([context('root', None, '.', ['file[docs/item.md]'])])
    query = {'target': 'docs/item.md', 'reason': 'synthetic', 'use': 'interpret',
             'classification': 'synthetic', 'query': {'scope': 'docs', 'filters': {'status': 'active'},
             'field': 'status', 'max_enumerated': 20, 'max_matches': 10, 'max_scan_bytes': 1000}}
    with pytest.raises(PolicyError, match='query scope not authorized'):
        select_query(p, 'root', object(), query)


def test_exact_scope_does_not_replace_bilateral_connection():
    root = context('root', None, '.', ['.'])
    producer = context('docs', 'root', 'docs', ['self'])
    consumer = context('consumer', 'root', 'consumer', ['file[docs/item.md]'])
    rule = {'from_context': 'docs', 'to_context': 'consumer', 'selector': 'docs/item.md',
            'use': 'interpret', 'classification': 'synthetic', 'expires': '2099-01-01'}
    consumer['imports'] = [copy.deepcopy(rule)]
    pending = make_policy([root, producer, consumer])
    assert pending.connection('docs', 'consumer', 'docs/item.md', 'interpret', 'synthetic') == 'pending'
    producer['exports'] = [copy.deepcopy(rule)]
    approved = make_policy([root, producer, consumer])
    assert approved.connection('docs', 'consumer', 'docs/item.md', 'interpret', 'synthetic') == 'approved'
    assert approved.connection('docs', 'consumer', 'docs/item.md', 'wrong-use', 'synthetic') == 'pending'
    assert approved.connection('docs', 'consumer', 'docs/item.md/child', 'interpret', 'synthetic') == 'denied'


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def test_folder_qualification_packet_and_later_directory_do_not_widen(tmp_path, monkeypatch):
    root = tmp_path / 'synthetic'
    root.mkdir()
    git(root, 'init', '-q'); git(root, 'config', 'user.name', 'Synthetic'); git(root, 'config', 'user.email', 'synthetic@example.invalid')
    (root / 'AGENTS.md').write_text('# Synthetic instructions\n')
    (root / 'index.md').write_text('# Synthetic index\n')
    (root / 'docs').mkdir()
    (root / 'docs/item.md').write_text('# Synthetic document\n')
    config = {'context_access': {'.': {'owner': 'Synthetic', 'policy': {
        'read': ['file[AGENTS.md]', 'file[index.md]', 'file[docs/item.md]'],
        'write': ['self'], 'capabilities': [], 'publication': [], 'deny': {}}}}}
    (root / 'wiki.config.yaml').write_text(yaml.safe_dump(config))
    git(root, 'add', '.'); git(root, 'commit', '-qm', 'synthetic approved file'); git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    base = git(root, 'rev-parse', 'HEAD')
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main')
    p = load_policy(root, base, 'wiki.config.yaml')
    assert not p.permits('.', 'read', 'docs/item.md')
    qualify_folder_context(root, p, '.', '.', 'index.md', 100_000)
    assert p.permits('.', 'read', 'docs/item.md') and not p.permits('.', 'read', 'docs/item.md/child')
    packet = build_packet(root, p, '.', base, [], 100_000, task_id='synthetic', goal='test',
                          output='synthetic', integrator='synthetic', entry_folder='.', trusted_binding=binding)
    assert 'file[docs/item.md]' in packet['context']['owned_scopes']['read']
    (root / 'docs/item.md').unlink(); (root / 'docs/item.md').mkdir()
    (root / 'docs/item.md/child').write_text('synthetic child\n')
    git(root, 'add', '-A'); git(root, 'commit', '-qm', 'synthetic later directory'); git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    newer = git(root, 'rev-parse', 'HEAD')
    p = load_policy(root, newer, 'wiki.config.yaml')
    qualify_folder_context(root, p, '.', '.', 'index.md', 100_000)
    assert not p.permits('.', 'read', 'docs/item.md/child')
    from wiki_core.repository_reader import RepositoryReader
    original = RepositoryReader._document
    def observe(reader, path, *args, **kwargs):
        if path == 'docs/item.md/child':
            pytest.fail('unqualified child body opened')
        return original(reader, path, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, '_document', observe)
    evidence = [{'ref': 'docs/item.md/child', 'producer': '.', 'reason': 'synthetic',
                 'use': 'interpretation', 'classification': 'context'}]
    with pytest.raises(PolicyError):
        build_packet(root, p, '.', newer, evidence, 100_000, task_id='synthetic', goal='test',
                     output='synthetic', integrator='synthetic', entry_folder='.', trusted_binding=binding)
