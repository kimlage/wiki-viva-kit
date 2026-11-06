"""Synthetic, explicitly selected interpretation context for folder ingestion."""
import copy
import json

import pytest
import yaml

from tests.test_folder_policy_core import repo, write, git
from wiki_core.config import config_from_mapping
from wiki_core.context_packet import build_packet
from wiki_core.context_policy import PolicyError, load_policy
from wiki_core.ingest.explicit_context import (ExplicitContextError,
    explicit_ingestion_evidence, resolve_explicit_ingestion_context)
from tests.test_protected_ingestion import prepared_repo


@pytest.fixture
def selected_repo(repo):
    write(repo, 'index.md', '# Root index\n')
    write(repo, 'source-page.md', '---\npage_id: source-a\npage_type: source\nconfig_ref: source-config.md\n---\n# Source A\n')
    write(repo, 'source-config.md', '---\npage_id: config-a\npage_type: source_config\ninput_channel_ref: channel-a\nperspectives_required: [source-lens]\ntarget_pages: [target.md]\n---\n# Selected config\n')
    write(repo, 'channel.md', '---\npage_id: channel-a\npage_type: input_channel\nperspectives_required: [channel-lens]\n---\n# Selected channel\n')
    write(repo, 'local-root.md', '---\npage_id: local-root\npage_type: context_hub\nperspective_bundle_required: [local-lens]\n---\n# Local root\n')
    write(repo, 'global-root.md', '---\npage_id: global-root\npage_type: root_entity\n---\n# Global root\n')
    write(repo, 'template.md', '# Selected template body\n')
    write(repo, 'target.md', '---\npage_id: target\npage_type: note\n---\n# Target\n')
    cfg = yaml.safe_load((repo / 'wiki.config.yaml').read_text())
    cfg['root_entity'] = {'page': 'global-root.md', 'entity_type': 'root_entity',
                          'perspective_bundle': {'required': ['global-lens'], 'optional': []}}
    write(repo, 'wiki.config.yaml', yaml.safe_dump(cfg))
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'selected context')
    git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    return repo, config_from_mapping(cfg)


def packet_for(repo, selection):
    policy = load_policy(repo, 'HEAD', 'wiki.config.yaml')
    return build_packet(repo, policy, '.', 'HEAD', explicit_ingestion_evidence(policy, selection),
        100_000, entry_folder='.', entry_index='index.md', task_id='task', goal='interpret',
        output='proposal', integrator='synthetic')


def test_explicit_source_channel_local_root_and_template(selected_repo):
    repo, config = selected_repo
    selection = {'source_page': 'source-page.md', 'source_config': 'source-config.md',
                 'input_channel': 'channel.md', 'root_entity': 'local-root.md',
                 'templates': ['template.md'], 'target_pages': ['target.md']}
    packet = packet_for(repo, selection)
    resolved = resolve_explicit_ingestion_context(packet, selection, config)
    assert resolved['root_entity']['page_id'] == 'local-root'
    assert resolved['input_channel']['page_id'] == 'channel-a'
    assert resolved['source_config']['page_id'] == 'config-a'
    assert resolved['perspectives_required'] == ['local-lens', 'channel-lens', 'source-lens']
    assert 'global-lens' not in json.dumps(resolved)
    assert resolved['target_pages'] == ['target.md']
    assert resolved['source_page_association'] == 'operator_selected_unverified'
    assert resolved['source_config_association'] == 'declared_reference_matched'
    assert resolved['input_channel_association'] == 'declared_reference_matched'
    assert 'Selected template body' in next(row['text'] for row in packet['inputs'] if row['ref'] == 'template.md')
    assert any('does not grant write' in gap for gap in resolved['context_omissions'])


def test_explicit_target_mode_preserves_declared_context_and_records_omissions(prepared_repo, monkeypatch):
    """One target can be selected without reading another owner's declared target."""
    import datetime as dt
    import hashlib
    from wiki_core.coordination_context import CoordinationBinding
    from wiki_core.ingest.cache_partition import partition_component
    from wiki_core.ingest.protected import prepare, record, consolidate, inspect
    from wiki_core.repository_reader import RepositoryReader
    from tests.test_protected_ingestion import _result_for

    root, _ = prepared_repo
    write(root, 'memories/sources/synthetic.md',
          '---\npage_id: source-synthetic\npage_type: source\nconfig_ref: memories/source-config.md\n---\n# Source\n')
    write(root, 'memories/source-config.md',
          '---\npage_id: config-a\npage_type: source_config\ninput_channel_ref: memories/channel.md\n---\n# Config\n')
    write(root, 'memories/channel.md',
          '---\npage_id: channel-a\npage_type: input_channel\n'
          'target_pages: [alpha/index.md, beta/index.md]\n---\n# Channel\n')
    write(root, 'alpha/index.md',
          '---\npage_id: beta/index.md\npage_type: context_hub\n---\n# Alpha\n')
    write(root, 'beta/index.md',
          '---\npage_id: beta\npage_type: context_hub\n---\n# UNAUTHORIZED SENTINEL\n')
    cfg = yaml.safe_load((root / 'wiki.config.yaml').read_text())
    cfg['llm'] = {'protected_cache_mode': 'by_source_v1'}
    cfg['context_access']['alpha']['policy']['read'] = ['.']
    root_rule = {'from_context': '.', 'to_context': 'alpha', 'selector': 'AGENTS.md',
                 'use': 'interpretation', 'classification': 'context', 'expires': '2099-01-01'}
    cfg['context_access']['.']['exports'] = [root_rule]
    cfg['context_access']['alpha']['imports'] = [copy.deepcopy(root_rule)]
    rules = [{'from_context': 'alpha', 'to_context': '.', 'selector': ref,
              'use': 'interpretation', 'classification': classification, 'expires': '2099-01-01'}
             for ref, classification in [('alpha/AGENTS.override.md', 'context'),
                                         ('alpha/index.md', 'context'), ('alpha/index.md', 'artifact')]]
    cfg['context_access']['alpha']['exports'] = rules
    cfg['context_access']['.']['imports'] = copy.deepcopy(rules)
    write(root, 'wiki.config.yaml', yaml.safe_dump(cfg))
    git(root, 'add', '.'); git(root, 'commit', '-qm', 'scoped synthetic targets')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    sha = git(root, 'rev-parse', 'HEAD')
    binding = CoordinationBinding(('.', 'alpha'), 'refs/remotes/origin/main', 'wiki.config.yaml')
    original_read = RepositoryReader.read
    def no_beta(reader, ref, **kwargs):
        if ref.startswith('beta/'):
            pytest.fail('unauthorized target body was read')
        return original_read(reader, ref, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', no_beta)
    selection = {'omit_root_entity': True, 'source_page': 'memories/sources/synthetic.md',
                 'target_selection': 'explicit', 'target_pages': ['alpha/index.md']}
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md',
                source_ref='source.txt', context_selection=selection)
    prepared = prepare(root, binding, **args, source_context='synthetic')
    partition = root / 'data/derived/wiki/.wiki-viva-protected' / partition_component('.', '.', 'source.txt')
    assert (partition / 'source-manifests' / (prepared['source_id'] + '.json')).is_file()
    request = prepared['request']
    assert request['target_pages'] == ['alpha/index.md']
    assert request['source_authorization']['context_selection']['target_selection'] == 'explicit'
    assert any('beta/index.md not selected' in gap for gap in request['block_context_package']['coverage']['missing'])
    assert 'UNAUTHORIZED SENTINEL' not in json.dumps(request)
    assert {'memories/source-config.md', 'memories/channel.md'} <= {
        item['ref'] for item in request['block_context_package']['inputs']}
    ids = {'source_id': prepared['source_id'], 'request_id': prepared['request_id']}
    result = _result_for(request)
    assert record(root, binding, **args, **ids, results=[result])['recorded'] == 1
    row = request['chunks'][0]
    assert inspect(root, binding, **args, **ids, view='results', chunk_ids=[row['chunk_id']])['results']
    event = ('memories/system/ingestion/events/2026-11-05-' +
             hashlib.sha256(ids['source_id'].encode()).hexdigest() + '-' + ids['request_id'] + '.md')
    out = consolidate(root, binding, **args, **ids, source_page='memories/sources/synthetic.md',
                      event_target=event, date=dt.date(2026, 11, 5))
    assert out['integration'] == 'pending review and incorporation'
    packet = inspect(root, binding, **args, **ids, view='integration', candidates=[])['packet']
    assert 'UNAUTHORIZED SENTINEL' not in json.dumps(packet)
    assert any('incomplete' in warning for warning in packet['warnings']) or request['block_context_package']['coverage']['missing']
    changed = {**selection, 'target_selection': 'declared'}
    with pytest.raises(ValueError):
        inspect(root, binding, **{**args, 'context_selection': changed}, **ids,
                view='results', chunk_ids=[row['chunk_id']])
    denied = {**selection, 'target_pages': ['beta/index.md']}
    with pytest.raises(ValueError):
        prepare(root, binding, **{**args, 'context_selection': denied}, source_context='synthetic')
    with pytest.raises(ValueError):
        prepare(root, binding, **{**args, 'context_selection': {k: v for k, v in selection.items()
                                                                 if k != 'target_selection'}},
                source_context='synthetic')
    no_list = {k: v for k, v in selection.items() if k != 'target_pages'}
    with pytest.raises(ValueError):
        prepare(root, binding, **{**args, 'context_selection': no_list}, source_context='synthetic')
    from pathlib import Path
    from wiki_core.traversal import is_protected_artifact
    original_open = Path.open
    def no_artifact(path, *values, **kwargs):
        if is_protected_artifact(path):
            pytest.fail('artifact read without explicit target list')
        return original_open(path, *values, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'open', no_artifact)
        with pytest.raises(ValueError):
            inspect(root, binding, **{**args, 'context_selection': no_list}, **ids,
                    view='results', chunk_ids=[row['chunk_id']])


def test_target_selection_mode_is_explicit_and_validated(selected_repo):
    from wiki_core.ingest.explicit_context import (_selection, connected_ingestion_selection,
                                                   declared_reference_matches)
    repo, _ = selected_repo
    base = {'omit_root_entity': True, 'source_page': 'source-page.md',
            'source_config': 'source-config.md', 'input_channel': 'channel.md'}
    initial = packet_for(repo, base)
    assert connected_ingestion_selection(initial, base)['target_pages'] == ['target.md']
    explicit = {**base, 'target_selection': 'explicit', 'target_pages': []}
    assert connected_ingestion_selection(initial, explicit)['target_pages'] == []
    with pytest.raises(ExplicitContextError, match='requires target_pages'):
        _selection({**base, 'target_selection': 'explicit'})
    assert not declared_reference_matches(r'beta\config', {'path': 'alpha/config.md', 'page_id': r'beta\config'})
    assert 'target_selection' not in _selection(base)
    for invalid in ('other', None, False, ['explicit']):
        with pytest.raises(ExplicitContextError, match='invalid target selection'):
            _selection({**base, 'target_selection': invalid})


@pytest.mark.parametrize('suffix', ['.md', '.MD', ''])
def test_unselected_declared_path_is_not_hidden_by_another_page_id(selected_repo, suffix):
    from wiki_core.ingest.explicit_context import connected_ingestion_selection
    repo, config = selected_repo
    declared_path = f'beta/index{suffix}'
    write(repo, 'target.md', f'---\npage_id: {declared_path}\npage_type: note\n---\n# Target\n')
    write(repo, 'channel.md', '---\npage_id: channel-a\npage_type: input_channel\n'
          f'target_pages: [{declared_path}]\n---\n# Channel\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'ambiguous target ID')
    git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    selection = {'omit_root_entity': True, 'source_page': 'source-page.md',
                 'source_config': 'source-config.md', 'input_channel': 'channel.md',
                 'target_selection': 'explicit', 'target_pages': ['target.md']}
    resolved = resolve_explicit_ingestion_context(packet_for(repo, selection), selection, config)
    assert any(f'{declared_path} not selected' in gap for gap in resolved['context_omissions'])
    declared = {**selection, 'target_selection': 'declared'}
    assert declared_path in connected_ingestion_selection(packet_for(repo, declared), declared)['target_pages']


@pytest.mark.parametrize('role', ['source_config', 'input_channel'])
@pytest.mark.parametrize('suffix', ['.md', '.MD', ''])
def test_declared_context_path_cannot_match_another_page_id(selected_repo, role, suffix):
    repo, config = selected_repo
    if role == 'source_config':
        write(repo, 'source-page.md', '---\npage_id: source-a\npage_type: source\n'
              f'config_ref: beta/config{suffix}\n---\n# Source\n')
        write(repo, 'source-config.md', f'---\npage_id: beta/config{suffix}\npage_type: source_config\n'
              'input_channel_ref: channel-a\n---\n# Config\n')
    else:
        write(repo, 'source-config.md', '---\npage_id: config-a\npage_type: source_config\n'
              f'input_channel_ref: beta/channel{suffix}\n---\n# Config\n')
        write(repo, 'channel.md', f'---\npage_id: beta/channel{suffix}\npage_type: input_channel\n---\n# Channel\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'ambiguous declared context path')
    git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    selection = {'omit_root_entity': True, 'source_page': 'source-page.md',
                 'source_config': 'source-config.md', 'input_channel': 'channel.md'}
    with pytest.raises(ExplicitContextError, match='declared context reference'):
        resolve_explicit_ingestion_context(packet_for(repo, selection), selection, config)


@pytest.mark.parametrize(('field', 'role'), [('config_ref', 'source_config'), ('input_channel_ref', 'input_channel')])
@pytest.mark.parametrize('suffix', ['.md', '.MD', ''])
def test_captured_source_path_cannot_match_another_page_id(field, role, suffix):
    from types import SimpleNamespace
    from wiki_core.ingest.protected import _validate_source_context

    source = SimpleNamespace(text=f'---\n{field}: beta/selected{suffix}\n---\n# Source\n')
    projected = {role: {'path': 'alpha/selected.md', 'page_id': f'beta/selected{suffix}'}}
    with pytest.raises(ValueError, match='explicit qualification'):
        _validate_source_context(source, projected)
    projected[role]['path'] = f'beta/selected{suffix}'
    _validate_source_context(source, projected)
    source.text = f'---\n{field}: selected-id\n---\n# Source\n'
    projected[role]['page_id'] = 'selected-id'
    _validate_source_context(source, projected)


def test_global_root_only_when_explicit_and_omission_is_recorded(selected_repo):
    repo, config = selected_repo
    selected = {'root_entity': 'global-root.md'}
    result = resolve_explicit_ingestion_context(packet_for(repo, selected), selected, config)
    assert result['perspectives_required'] == ['global-lens']
    omitted = {'omit_root_entity': True}
    packet = packet_for(repo, omitted)
    result = resolve_explicit_ingestion_context(packet, omitted, config)
    assert result['root_entity'] is None and result['perspectives_required'] == []
    assert any('intentionally omitted' in value for value in result['context_omissions'])
    assert 'global-root.md' not in {row['ref'] for row in packet['inputs']}
    with pytest.raises(ExplicitContextError, match='select or explicitly omit'):
        packet_for(repo, {})
    with pytest.raises(ExplicitContextError, match='select or explicitly omit'):
        packet_for(repo, {'root_entity': 'global-root.md', 'omit_root_entity': True})


def test_packet_omissions_reframe_matches_rebuilding_and_rejects_tamper(selected_repo):
    from wiki_core.context_packet import _packet_with_omissions
    repo, _ = selected_repo
    selection = {'omit_root_entity': True}
    policy = load_policy(repo, 'HEAD', 'wiki.config.yaml')
    initial = build_packet(repo, policy, '.', 'HEAD', explicit_ingestion_evidence(policy, selection),
        100_000, entry_folder='.', entry_index='index.md', task_id='task', goal='interpret',
        output='proposal', integrator='synthetic')
    omissions = ['Synthetic explicit coverage gap.']
    updated = _packet_with_omissions(initial, omissions, policy)
    rebuilt = build_packet(repo, policy, '.', 'HEAD', explicit_ingestion_evidence(policy, selection),
        100_000, entry_folder='.', entry_index='index.md', task_id='task', goal='interpret',
        output='proposal', integrator='synthetic', omissions=omissions)
    assert updated == rebuilt
    initial['inputs'][0]['text'] = 'tampered'
    with pytest.raises(PolicyError): _packet_with_omissions(initial, omissions, policy)


def test_stage_policy_cache_does_not_share_qualified_or_mutated_state(selected_repo):
    from wiki_core.context_policy import policy_stage_cache
    repo, _ = selected_repo
    with policy_stage_cache():
        first = load_policy(repo, 'HEAD', 'wiki.config.yaml')
        first._qualified_contexts.add('.')
        first.contexts['.']['owner'] = 'untrusted mutation'
        second = load_policy(repo, first.policy_revision, 'wiki.config.yaml')
        assert not second._qualified_contexts
        assert second.contexts['.']['owner'] != 'untrusted mutation'
        write(repo, 'new.md', '# New approved ref\n')
        git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'advance')
        git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
        with pytest.raises(PolicyError): first.fresh()


def test_declared_config_and_channel_must_match_explicit_selected_bodies(selected_repo):
    repo, config = selected_repo
    selection = {'source_page': 'source-page.md', 'omit_root_entity': True}
    with pytest.raises(ExplicitContextError, match='matching selection'):
        resolve_explicit_ingestion_context(packet_for(repo, selection), selection, config)
    selection['source_config'] = 'source-config.md'
    with pytest.raises(ExplicitContextError, match='matching selection'):
        resolve_explicit_ingestion_context(packet_for(repo, selection), selection, config)
    selection['input_channel'] = 'channel.md'
    result = resolve_explicit_ingestion_context(packet_for(repo, selection), selection, config)
    assert result['source_config']['input_channel_ref'] == 'channel-a'


def test_selection_must_match_packet_and_untrusted_paths_are_refused(selected_repo):
    repo, config = selected_repo
    selection = {'root_entity': 'local-root.md'}
    packet = packet_for(repo, selection)
    with pytest.raises(ExplicitContextError, match='body unavailable'):
        resolve_explicit_ingestion_context(packet, {'root_entity': 'global-root.md'}, config)
    changed = copy.deepcopy(packet)
    changed['inputs'][-1]['text'] = 'unbound replacement'
    with pytest.raises(ExplicitContextError, match='packet unavailable'):
        resolve_explicit_ingestion_context(changed, selection, config)
    with pytest.raises(ExplicitContextError, match='invalid context path'):
        packet_for(repo, {'root_entity': '../outside.md'})
    with pytest.raises(ExplicitContextError, match='distinct'):
        packet_for(repo, {'root_entity': 'local-root.md', 'templates': ['local-root.md']})


def test_explicit_context_does_not_bypass_reader_grants(selected_repo):
    repo, config = selected_repo
    selection = {'root_entity': 'local-root.md', 'templates': ['beta/private.md']}
    # No beta grant/qualification: the packet builder denies the selector.
    with pytest.raises(PolicyError):
        packet_for(repo, selection)


def test_arbitrary_note_cannot_be_business_root(selected_repo):
    repo, config = selected_repo
    selection = {'root_entity': 'target.md'}
    with pytest.raises(ExplicitContextError, match='root type'):
        resolve_explicit_ingestion_context(packet_for(repo, selection), selection, config)


def test_skipped_perspective_and_pending_reason_remain_visible(selected_repo):
    repo, config = selected_repo
    path = repo / 'source-config.md'
    path.write_text(path.read_text().replace('perspectives_required: [source-lens]',
        'perspectives_required: [source-lens]\nperspectives_skip_with_reason: [source-lens]'))
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'skip with review pending')
    git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    selection = {'source_page': 'source-page.md', 'source_config': 'source-config.md',
                 'input_channel': 'channel.md', 'omit_root_entity': True}
    result = resolve_explicit_ingestion_context(packet_for(repo, selection), selection, config)
    assert result['perspectives_skipped'] == ['source-lens']
    assert any('source-lens' in gap and 'justification requires review' in gap
               for gap in result['context_omissions'])


def test_two_files_of_same_repo_may_reference_one_authorized_source_page(selected_repo):
    repo, config = selected_repo
    write(repo, 'repo-source.md', '---\npage_id: repo-source\npage_type: source\nplatform: repo\n'
        'source_locator: example.test/team/repo\n---\n# Repo\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'repository source')
    git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    selection = {'omit_root_entity': True, 'repository_source_pages': {'first': 'repo-source.md', 'second': 'repo-source.md'}}
    result = resolve_explicit_ingestion_context(packet_for(repo, selection), selection, config)
    assert result['repository_sources']['first']['path'] == result['repository_sources']['second']['path']


def test_selected_context_is_requalified_across_source_stages(prepared_repo, monkeypatch):
    from wiki_core.coordination_context import CoordinationBinding
    from wiki_core.ingest.protected import prepare, record, consolidate
    from pathlib import Path
    import datetime
    import hashlib
    root, _ = prepared_repo
    write(root, 'memories/sources/synthetic.md', '---\npage_id: source-synthetic\npage_type: source\nconfig_ref: memories/config.md\n---\n# Source\n')
    write(root, 'memories/config.md', '---\npage_id: config\npage_type: source_config\ninput_channel_ref: channel\nperspectives_required: [lens]\n---\n# Config\n')
    write(root, 'memories/channel.md', '---\npage_id: channel\npage_type: input_channel\n---\n# Channel\n')
    write(root, 'memories/lens.md', '---\npage_id: lens\npage_type: perspective\n---\n# Lens\nHonor limitations.\n')
    write(root, 'memories/template.md', '# Explicit template\n')
    git(root, 'add', '.'); git(root, 'commit', '-qm', 'selected context')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    sha = git(root, 'rev-parse', 'HEAD')
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    selection = {'omit_root_entity': True, 'source_page': 'memories/sources/synthetic.md',
        'source_config': 'memories/config.md', 'input_channel': 'memories/channel.md',
        'templates': ['memories/template.md']}
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md',
        source_ref='source.txt', context_selection=selection, perspective_refs={'lens': 'memories/lens.md'})
    prepared = prepare(root, binding, **args, source_context='system')
    request = prepared['request']; row = request['chunks'][0]
    assert request['perspectives_required'] == ['lens']
    assert request['input_channel']['page_id'] == 'channel'
    assert any('intentionally omitted' in gap for gap in request['block_context_package']['coverage']['missing'])
    assert any(row['ref'] == 'memories/template.md' for row in request['block_context_package']['inputs'])
    sample = json.loads((Path(__file__).parent / 'fixtures/e2e/context_pass_result.sample.json').read_text())
    result = {**sample, **{key: request[key] for key in ('source_id', 'prompt_version', 'schema_version', 'model_profile')},
        **{key: row[key] for key in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')},
        'perspectives_required': ['lens'], 'perspectives': {'lens': {'status': 'extracted'}}}
    ids = {'source_id': prepared['source_id'], 'request_id': prepared['request_id']}
    with monkeypatch.context() as patch:
        import wiki_core.ingest.protected as protected
        patch.setattr(protected, '_read_json', lambda *a, **k: pytest.fail('request opened with changed selection'))
        with pytest.raises(ValueError):
            record(root, binding, **{**args, 'context_selection': {'omit_root_entity': True}}, **ids, results=[result])
    assert record(root, binding, **args, **ids, results=[result])['recorded'] == 1
    event = ('memories/system/ingestion/events/2026-11-04-' +
        hashlib.sha256(prepared['source_id'].encode()).hexdigest() + '-' + prepared['request_id'] + '.md')
    output = consolidate(root, binding, **args, **ids, source_page=selection['source_page'],
        event_target=event, date=datetime.date(2026, 11, 4))
    assert output['integration'] == 'pending review and incorporation'
