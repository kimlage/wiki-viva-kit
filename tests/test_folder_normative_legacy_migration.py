"""Folder migration of the original inherited normative lifecycle fixture."""
import hashlib
import json
from pathlib import Path

import pytest
import yaml
from jsonschema import validate

from tests.test_context_flow import repo, git, approve
from tests.test_coordination_protected import folderize
from wiki_core.context_policy import load_policy
from wiki_core.context_packet import build_packet
from wiki_core.context_integration import preflight, IntegrationError
from wiki_core.context_impact import ImpactError, report_review
from wiki_core.context_requirements import assess_approved_impact, requirements_from_result

BASE = Path(__file__).resolve().parents[1]


def policy(root):
    return load_policy(root, 'refs/remotes/origin/main', 'wiki.config.yaml')


def run_inherited_normative_requirement_flow_folder(repo, context, output):
    folderize(repo)
    config_path = repo / 'wiki.config.yaml'
    config = yaml.safe_load(config_path.read_text())
    tax_rule = {'from_context': '.', 'to_context': 'finance/tax', 'selector': 'AGENTS.md',
                'use': 'interpretation', 'classification': 'context', 'expires': '2099-01-01'}
    config['context_access']['.']['exports'].append(tax_rule)
    config['context_access']['finance/tax']['imports'] = [tax_rule]
    config['context_access']['finance/tax']['policy']['read'] = ['self', 'AGENTS.md']
    config_path.write_text(yaml.safe_dump(config))
    (repo / 'AGENTS.md').write_text('---\ntitle: Original\n---\nApproved rule\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'normative metadata'); approve(repo)
    base = git(repo, 'rev-parse', 'HEAD'); p = policy(repo)
    base_branch = git(repo, 'branch', '--show-current')
    index = context + '/index.md'
    packet = build_packet(repo, p, context, base, [], 20000, task_id='norm', goal='interpret rule',
                          output=output, integrator='reviewer', entry_folder=context)
    req = {'target': 'AGENTS.md', 'fields': ['*'], 'temporal': 'current', 'max_age_days': 30,
           'consumed_revision': base, 'use': 'normative', 'source_kind': 'mandatory',
           'classification': 'context', 'authority_format': 'folder', 'entry_folder': context, 'entry_index': index}
    suffix = context.rsplit('/', 1)[-1]
    branch = 'wiki/norm-' + suffix; git(repo, 'checkout', '-qb', branch)
    (repo / output).write_text('---\n' + yaml.safe_dump({'information_requirements': [req]}) + '---\nIndependent interpretation\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'interpret approved rule'); head = git(repo, 'rev-parse', 'HEAD')
    result = {'schema_version': 'wiki.task-result/v1', 'status': 'completed', 'task_id': 'norm',
              'context_id': context, 'packet_digest': packet['packet_digest'],
              'changes': [{'path': output, 'action': 'modified'}],
              'read_coverage': {'observed_refs': packet['declared_read_set'], 'missing': packet['coverage']['missing']}, 'blockers': []}
    assert preflight(repo, p, context_id=context, base=base, head=head, branch=branch, packet=packet, result=result)['state'] == 'independent_review_required'
    git(repo, 'checkout', '-q', base_branch); git(repo, 'merge', '--no-ff', '--no-edit', branch); approve(repo)
    derived = requirements_from_result(repo, policy(repo), packet=packet, result=result, output_path=output,
                                       proposal_head=head, temporal='current', max_age_days=30)
    child_req = {**req, 'target': context + '/AGENTS.md'}
    index_req = {'target': index, 'fields': ['*'], 'temporal': 'current', 'max_age_days': 30,
                 'consumed_revision': base, 'use': 'interpretation', 'classification': 'context'}
    assert derived['information_requirements'] == [req, child_req, index_req]
    (repo / 'unrelated.md').write_text('Unrelated\n'); git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'unrelated'); approve(repo)
    same = git(repo, 'rev-parse', 'HEAD')
    same_packet = build_packet(repo, policy(repo), context, same, [], 20000, task_id='same-rule', goal='edit',
                               output=output, integrator='reviewer', entry_folder=context)
    git(repo, 'checkout', '-qb', 'wiki/same-' + suffix); (repo / output).write_text((repo / output).read_text() + 'Unrelated edit\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'edit consumer'); same_head = git(repo, 'rev-parse', 'HEAD')
    same_result = {'schema_version': 'wiki.task-result/v1', 'status': 'completed', 'task_id': 'same-rule',
                   'context_id': context, 'packet_digest': same_packet['packet_digest'], 'changes': [{'path': output, 'action': 'modified'}],
                   'read_coverage': {'observed_refs': same_packet['declared_read_set'], 'missing': same_packet['coverage']['missing']}, 'blockers': []}
    assert preflight(repo, policy(repo), context_id=context, base=same, head=same_head, branch='wiki/same-' + suffix,
                     packet=same_packet, result=same_result)['state'] == 'independent_review_required'
    git(repo, 'checkout', '-q', base_branch)
    (repo / 'AGENTS.md').write_text('---\ntitle: Updated\n---\nApproved rule\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'rule metadata revision'); approve(repo); current = git(repo, 'rev-parse', 'HEAD')
    out = assess_approved_impact(repo, policy(repo), consumers=[output], before=base, after=current, destination_context=context)
    candidate = out['candidates'][0]
    validate(out, json.loads((BASE / 'docs/references/schemas/wiki-context-impact-v1.schema.json').read_text()))
    assert candidate['use'] == 'normative' and candidate['before_revision'] == base and candidate['state'] == 'review_pending'
    forged = {**candidate}; forged.pop('source_kind')
    with pytest.raises(ImpactError, match='invalid candidate'):
        report_review(repo, policy(repo), forged, disposition='still_valid', reason='forged origin', evidence_revision=current)
    assert report_review(repo, policy(repo), candidate, disposition='still_valid', reason='Reviewed rule', evidence_revision=current)['verification'] == 'reported_not_verified'
    fresh = build_packet(repo, policy(repo), context, current, [], 20000, task_id='stale-norm', goal='edit',
                         output=output, integrator='reviewer', entry_folder=context)
    git(repo, 'checkout', '-qb', 'wiki/stale-' + suffix); (repo / output).write_text((repo / output).read_text() + 'Unrelated edit\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'edit consumer'); newer = git(repo, 'rev-parse', 'HEAD')
    new_result = {'schema_version': 'wiki.task-result/v1', 'status': 'completed', 'task_id': 'stale-norm',
                  'context_id': context, 'packet_digest': fresh['packet_digest'], 'changes': [{'path': output, 'action': 'modified'}],
                  'read_coverage': {'observed_refs': fresh['declared_read_set'], 'missing': fresh['coverage']['missing']}, 'blockers': []}
    with pytest.raises(IntegrationError, match='normative requirement requires requalification'):
        preflight(repo, policy(repo), context_id=context, base=current, head=newer, branch='wiki/stale-' + suffix,
                  packet=fresh, result=new_result)


def test_changed_rule_helper_does_not_prove_rest_of_chain(repo):
    from wiki_core.context_packet import qualify_folder_context
    from wiki_core.context_normative import folder_normative_changed
    folderize(repo)
    old = git(repo, 'rev-parse', 'HEAD')
    (repo / 'AGENTS.md').write_text('# Changed root rule\n')
    (repo / 'finance/costs/index.md').write_text('# Changed index too\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'change rule and index'); approve(repo)
    current = policy(repo)
    qualify_folder_context(repo, current, 'finance/costs', 'finance/costs', 'finance/costs/index.md', 20000)
    # The changed index prevents proof of the historical selection.
    assert not folder_normative_changed(current, 'finance/costs', 'AGENTS.md', old,
                                        entry_folder='finance/costs', entry_index='finance/costs/index.md')


@pytest.mark.parametrize('mutation', ['other_instruction', 'index', 'owner', 'old_grant', 'old_override'])
def test_changed_instruction_requires_proved_rest_of_chain(repo, monkeypatch, mutation):
    from wiki_core.context_packet import qualify_folder_context
    from wiki_core.context_normative import folder_normative_changed
    from wiki_core.repository_reader import RepositoryReader
    folderize(repo)
    config_path = repo / 'wiki.config.yaml'
    config = yaml.safe_load(config_path.read_text())
    root_exports = list(config['context_access']['.']['exports'])
    if mutation == 'old_grant':
        config['context_access']['.']['exports'] = []
        config_path.write_text(yaml.safe_dump(config))
        git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'old grant unavailable'); approve(repo)
    if mutation == 'old_override':
        (repo / 'AGENTS.override.md').write_text('# Old override\n')
        git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'old override'); approve(repo)
    old = git(repo, 'rev-parse', 'HEAD')
    if mutation == 'old_grant':
        config['context_access']['.']['exports'] = root_exports
        config_path.write_text(yaml.safe_dump(config))
    if mutation == 'old_override': (repo / 'AGENTS.override.md').unlink()
    if mutation == 'other_instruction': (repo / 'finance/costs/AGENTS.md').write_text('# Other changed rule\n')
    if mutation == 'index': (repo / 'finance/costs/index.md').write_text('# Changed index\n')
    if mutation == 'owner':
        config['context_access']['.']['owner'] = 'new owner'
        config_path.write_text(yaml.safe_dump(config))
    (repo / 'AGENTS.md').write_text('# Changed root rule\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'current policy'); approve(repo)
    p = policy(repo)
    qualify_folder_context(repo, p, 'finance/costs', 'finance/costs', 'finance/costs/index.md', 20000)
    original = RepositoryReader.read
    def guard(reader, path, **kwargs):
        assert not (reader.revision == old and path == 'AGENTS.md'), 'unqualified historical body opened'
        return original(reader, path, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', guard)
    assert not folder_normative_changed(p, 'finance/costs', 'AGENTS.md', old,
                                        entry_folder='finance/costs', entry_index='finance/costs/index.md')


def test_current_grant_revocation_blocks_before_historical_read(repo, monkeypatch):
    from wiki_core.context_packet import qualify_folder_context
    from wiki_core.context_policy import PolicyError
    from wiki_core.repository_reader import RepositoryReader
    folderize(repo)
    old = git(repo, 'rev-parse', 'HEAD')
    config_path = repo / 'wiki.config.yaml'
    config = yaml.safe_load(config_path.read_text()); config['context_access']['.']['exports'] = []
    config_path.write_text(yaml.safe_dump(config)); (repo / 'AGENTS.md').write_text('# Changed root rule\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'revoke current grant'); approve(repo)
    original = RepositoryReader.read
    def guard(reader, path, **kwargs):
        assert not (reader.revision == old and path == 'AGENTS.md'), 'historical body opened after revocation'
        return original(reader, path, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', guard)
    with pytest.raises(PolicyError, match='not authorized'):
        qualify_folder_context(repo, policy(repo), 'finance/costs', 'finance/costs', 'finance/costs/index.md', 20000)


def test_approval_move_between_size_and_old_blob_denies_read(repo, monkeypatch):
    from wiki_core.context_packet import qualify_folder_context
    from wiki_core.context_normative import folder_normative_changed
    from wiki_core.repository_reader import RepositoryReader
    folderize(repo)
    old = git(repo, 'rev-parse', 'HEAD'); old_oid = git(repo, 'rev-parse', old + ':AGENTS.md')
    (repo / 'AGENTS.md').write_text('# Changed root rule\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'changed root rule'); approve(repo)
    p = policy(repo)
    qualify_folder_context(repo, p, 'finance/costs', 'finance/costs', 'finance/costs/index.md', 20000)
    new_ref = git(repo, 'commit-tree', 'HEAD^{tree}', '-p', 'HEAD', '-m', 'new approved ref')
    real_size, real_git = RepositoryReader.blob_size, RepositoryReader._git
    moved = []
    def move_on_old_size(reader, path):
        result = real_size(reader, path)
        if reader.revision == old and path == 'AGENTS.md':
            git(repo, 'update-ref', 'refs/remotes/origin/main', new_ref); moved.append(True)
        return result
    def guard_blob(reader, *args):
        assert not (getattr(reader, 'revision', None) == old and args == ('cat-file', 'blob', old_oid)), 'historical body opened after policy moved'
        return real_git(reader, *args)
    monkeypatch.setattr(RepositoryReader, 'blob_size', move_on_old_size)
    monkeypatch.setattr(RepositoryReader, '_git', guard_blob)
    assert not folder_normative_changed(p, 'finance/costs', 'AGENTS.md', old,
                                        entry_folder='finance/costs', entry_index='finance/costs/index.md')
    assert moved


def test_nested_git_boundary_blocks_chain_qualification_before_historical_read(repo, monkeypatch):
    from wiki_core.context_packet import qualify_folder_context
    from wiki_core.context_policy import PolicyError
    from wiki_core.repository_reader import RepositoryReader
    folderize(repo)
    old = git(repo, 'rev-parse', 'HEAD')
    (repo / 'finance/costs/AGENTS.md').write_text('# Changed costs rule\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'changed rule'); approve(repo)
    git(repo / 'finance/costs', 'init', '-q')
    original = RepositoryReader.read
    def guard(reader, path, **kwargs):
        assert not (reader.revision == old and path.startswith('finance/costs/')), 'nested Git body opened'
        return original(reader, path, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', guard)
    with pytest.raises(PolicyError):
        qualify_folder_context(repo, policy(repo), 'finance/costs', 'finance/costs', 'finance/costs/index.md', 20000)


def test_normative_review_rechecks_current_source_digest(repo):
    from wiki_core.context_impact import assess_impact
    folderize(repo)
    old = git(repo, 'rev-parse', 'HEAD')
    req = {'target': 'AGENTS.md', 'fields': ['*'], 'temporal': 'current', 'max_age_days': 30,
           'consumed_revision': old, 'use': 'normative', 'source_kind': 'mandatory',
           'classification': 'context', 'authority_format': 'folder',
           'entry_folder': 'finance/costs', 'entry_index': 'finance/costs/index.md'}
    graph = {'edges': [{'type': 'operational_prerequisite', 'field': 'information_requirements',
                        'source': 'finance/costs/result.md', 'target': 'AGENTS.md', 'requirement': req}]}
    (repo / 'AGENTS.md').write_text('# First changed rule\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'first rule'); approve(repo)
    first = git(repo, 'rev-parse', 'HEAD')
    candidate = assess_impact(repo, policy(repo), graph, before=old, after=first,
                              destination_context='finance/costs')['candidates'][0]
    (repo / 'AGENTS.md').write_text('# Second changed rule\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'second rule'); approve(repo)
    current = git(repo, 'rev-parse', 'HEAD')
    with pytest.raises(ImpactError, match='source changed since candidate'):
        report_review(repo, policy(repo), candidate, disposition='still_valid', reason='review', evidence_revision=current)


@pytest.mark.parametrize('mutation', ['before_digest', 'no_change'])
def test_normative_review_rejects_forged_consumption_digest(repo, mutation):
    from wiki_core.context_impact import assess_impact
    folderize(repo)
    old = git(repo, 'rev-parse', 'HEAD')
    req = {'target': 'AGENTS.md', 'fields': ['*'], 'temporal': 'current', 'max_age_days': 30,
           'consumed_revision': old, 'use': 'normative', 'source_kind': 'mandatory',
           'classification': 'context', 'authority_format': 'folder',
           'entry_folder': 'finance/costs', 'entry_index': 'finance/costs/index.md'}
    graph = {'edges': [{'type': 'operational_prerequisite', 'field': 'information_requirements',
                        'source': 'finance/costs/result.md', 'target': 'AGENTS.md', 'requirement': req}]}
    (repo / 'AGENTS.md').write_text('# Changed rule\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'changed rule'); approve(repo)
    current = git(repo, 'rev-parse', 'HEAD')
    candidate = assess_impact(repo, policy(repo), graph, before=old, after=current,
                              destination_context='finance/costs')['candidates'][0]
    if mutation == 'before_digest':
        candidate['before_digest'] = '0' * 64
    else:
        candidate['before_revision'] = candidate['after_revision']
        candidate['before_digest'] = candidate['after_digest']
        key = (candidate['target'], candidate['before_revision'], candidate['after_revision'], candidate['rule'],
               candidate['source'], candidate['selector'], candidate['use'], candidate['classification'],
               candidate['target_digest'], 'mandatory', candidate['authority_format'],
               candidate['entry_folder'], candidate['entry_index'])
        candidate['event_id'] = hashlib.sha256(json.dumps(key, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    with pytest.raises(ImpactError, match='candidate source digest mismatch'):
        report_review(repo, policy(repo), candidate, disposition='still_valid', reason='review', evidence_revision=current)


@pytest.mark.parametrize('mutation', ['after_digest', 'unapproved_after'])
def test_normative_review_rejects_forged_post_change_proof(repo, mutation):
    from wiki_core.context_impact import assess_impact
    folderize(repo)
    old = git(repo, 'rev-parse', 'HEAD')
    req = {'target': 'AGENTS.md', 'fields': ['*'], 'temporal': 'current', 'max_age_days': 30,
           'consumed_revision': old, 'use': 'normative', 'source_kind': 'mandatory',
           'classification': 'context', 'authority_format': 'folder',
           'entry_folder': 'finance/costs', 'entry_index': 'finance/costs/index.md'}
    graph = {'edges': [{'type': 'operational_prerequisite', 'field': 'information_requirements',
                        'source': 'finance/costs/result.md', 'target': 'AGENTS.md', 'requirement': req}]}
    (repo / 'AGENTS.md').write_text('# First changed rule\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'first rule'); approve(repo)
    first = git(repo, 'rev-parse', 'HEAD')
    candidate = assess_impact(repo, policy(repo), graph, before=old, after=first,
                              destination_context='finance/costs')['candidates'][0]
    if mutation == 'after_digest':
        (repo / 'AGENTS.md').write_text('# Second changed rule\n')
        git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'second rule'); approve(repo)
        evidence = git(repo, 'rev-parse', 'HEAD')
        candidate['after_digest'] = hashlib.sha256((repo / 'AGENTS.md').read_bytes()).hexdigest()
    else:
        evidence = first
        candidate['after_revision'] = git(repo, 'commit-tree', first + '^{tree}', '-p', first, '-m', 'unapproved proposal')
        key = (candidate['target'], candidate['before_revision'], candidate['after_revision'], candidate['rule'],
               candidate['source'], candidate['selector'], candidate['use'], candidate['classification'],
               candidate['target_digest'], 'mandatory', candidate['authority_format'],
               candidate['entry_folder'], candidate['entry_index'])
        candidate['event_id'] = hashlib.sha256(json.dumps(key, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    with pytest.raises(ImpactError):
        report_review(repo, policy(repo), candidate, disposition='still_valid', reason='review', evidence_revision=evidence)
