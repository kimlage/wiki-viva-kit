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
