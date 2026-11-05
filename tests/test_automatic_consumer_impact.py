import json
import os
import subprocess
import sys
from pathlib import Path

import yaml
import pytest

from tests.test_folder_context_impact import repo, git, write
from wiki_core.context_impact import report_review
from wiki_core.context_policy import load_policy


def test_approved_change_discovers_owner_review_and_reads_back(repo):
    config = yaml.safe_load((repo / 'wiki.config.yaml').read_text())
    config['paths'] = {'memory_root': 'alpha/memories'}
    grant = {'from_context': '.', 'to_context': 'alpha', 'selector': 'wiki.coordination.yaml',
             'use': 'interpretation', 'classification': 'artifact', 'expires': '2099-01-01'}
    config['context_access']['.']['exports'].append(grant)
    config['context_access']['alpha']['imports'].append(grant.copy())
    write(repo, 'wiki.config.yaml', yaml.safe_dump(config))
    route = {'schema_version': 'wiki_coordination.v1', 'profiles': {'research': {
        'label': 'Research', 'scope': 'Review', 'action_ids': ['review-action']}}}
    write(repo, 'wiki.coordination.yaml', yaml.safe_dump(route))
    action_path = 'alpha/memories/actions/review.md'
    write(repo, action_path, '---\npage_id: review-action\npage_type: action\naction_state: open\nnext_action: Existing work\n---\nExisting work\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'declare existing action route')
    git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    initial = git(repo, 'rev-parse', 'HEAD')
    requirement = {'target': 'alpha/source.md', 'fields': ['*'], 'temporal': 'current',
                   'max_age_days': 30, 'consumed_revision': initial,
                   'use': 'interpret', 'classification': 'internal'}
    values = {'page_id': 'interpretation', 'page_type': 'claim', 'information_requirements': [requirement]}
    write(repo, 'alpha/result.md', '---\n' + yaml.safe_dump(values) + '---\nInitial interpretation\n')
    other = {'page_id': 'other-consumer', 'page_type': 'claim', 'information_requirements': [requirement.copy()]}
    write(repo, 'alpha/other.md', '---\n' + yaml.safe_dump(other) + '---\nOther interpretation\n')
    historical = {'page_id': 'history', 'page_type': 'claim', 'information_requirements': [
        {**requirement, 'temporal': 'historical'}]}
    write(repo, 'alpha/history.md', '---\n' + yaml.safe_dump(historical) + '---\nHistorical interpretation\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'declare consumption')
    result_revision = git(repo, 'rev-parse', 'HEAD')
    downstream = {'page_id': 'downstream', 'page_type': 'claim', 'information_requirements': [{
        'target': 'alpha/result.md', 'fields': ['*'], 'temporal': 'current',
        'max_age_days': 30, 'consumed_revision': result_revision,
        'use': 'interpret', 'classification': 'internal'}]}
    write(repo, 'alpha/final.md', '---\n' + yaml.safe_dump(downstream) + '---\nFinal interpretation\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'declare downstream consumption')
    before = git(repo, 'rev-parse', 'HEAD')
    git(repo, 'update-ref', 'refs/remotes/origin/main', before)
    base_branch = git(repo, 'branch', '--show-current')
    git(repo, 'checkout', '-qb', 'wiki/synthetic-source')
    write(repo, 'alpha/source.md', '# Approved source change\n')
    git(repo, 'add', 'alpha/source.md'); git(repo, 'commit', '-qm', 'source proposal')
    proposal = git(repo, 'rev-parse', 'HEAD')
    cli = str(Path(__file__).resolve().parents[1] / 'scripts/wiki_context_flow.py')
    def impact(approved, after, previous=before, routing=()):
        return subprocess.run([sys.executable, cli, '--repo', str(repo), '--approved-revision', approved,
            'impact', '--context', 'alpha', '--before', previous, '--after', after, *routing],
            cwd=repo / 'alpha', text=True, capture_output=True,
            env={**os.environ, 'WIKI_COORDINATION_ALLOWED_CONTEXTS': '.,alpha',
                 'WIKI_COORDINATION_CONTEXT_MODE': 'folder',
                 'WIKI_COORDINATION_TRUSTED_REF': 'refs/remotes/origin/main'})
    assert impact(before, proposal).returncode != 0
    git(repo, 'checkout', '-q', base_branch); git(repo, 'merge', '--ff-only', 'wiki/synthetic-source')
    git(repo, 'update-ref', 'refs/remotes/origin/main', proposal)
    first = impact(proposal, proposal)
    assert first.returncode == 0, first.stderr
    output = json.loads(first.stdout)
    assert output['propagation'] == 'one_hop_only'
    assert [(row['target'], row['destination_context'], row['state']) for row in output['candidates']] == [
        ('alpha/other.md', 'alpha', 'review_pending'), ('alpha/result.md', 'alpha', 'review_pending')]
    candidate = next(row for row in output['candidates'] if row['target'] == 'alpha/result.md')
    other_candidate = next(row for row in output['candidates'] if row['target'] == 'alpha/other.md')
    import hashlib
    action_file = repo / action_path
    action_sha = lambda: hashlib.sha256(action_file.read_bytes()).hexdigest()
    def selected(event, sha, profile='research'):
        return ('--event-id', event, '--action-id', 'review-action', '--action-path', action_path,
                '--profile', profile, '--expected-sha256', sha)
    # Exercise the CLI on the successful path below. Other routing cases use
    # the same production entry point directly, avoiding a second full impact
    # scan and a new Python process for every guard and retry.
    from wiki_core.context_requirements import route_impact_to_action
    from wiki_core.coordination_context import CoordinationBinding
    binding = CoordinationBinding(('.', 'alpha'), 'refs/remotes/origin/main', 'wiki.config.yaml')
    def route(event, sha, *, profile='research', path=action_path, trace=()):
        return route_impact_to_action(repo, binding, destination_context='alpha', before=before,
            after=proposal, scope='alpha', event_id=event, action_id='review-action',
            action_path=path, profile=profile, expected_sha256=sha, trace=trace)
    original = action_file.read_bytes()
    import pytest
    with pytest.raises(ValueError): route(candidate['event_id'], action_sha(), trace=[candidate['event_id']])
    with pytest.raises(ValueError): route(candidate['event_id'], action_sha(), profile='other')
    with pytest.raises(ValueError): route(candidate['event_id'], '0' * 64)
    with pytest.raises(ValueError): route('0' * 64, action_sha())
    with pytest.raises(ValueError): route(candidate['event_id'], action_sha(), path='root-result.md')
    assert action_file.read_bytes() == original
    action_file.write_bytes(original + b'\nUnrelated work in progress\n')
    dirty = action_file.read_bytes()
    with pytest.raises(ValueError): route(candidate['event_id'], action_sha())
    assert action_file.read_bytes() == dirty
    action_file.write_bytes(original)
    routed = impact(proposal, proposal, routing=selected(candidate['event_id'], action_sha()))
    assert routed.returncode == 0, routed.stderr
    assert json.loads(routed.stdout)['action']['status'] == 'recorded'
    assert route(other_candidate['event_id'], action_sha())['status'] == 'recorded'
    assert route(candidate['event_id'], action_sha())['status'] == 'already_recorded'
    recorded_action = action_file.read_bytes()
    action_file.write_bytes(recorded_action + b'\nUnrelated change\n')
    with pytest.raises(ValueError): route(candidate['event_id'], action_sha())
    assert action_file.read_bytes().endswith(b'Unrelated change\n')
    action_file.write_bytes(recorded_action)
    assert 'Existing work' in action_file.read_text()
    git(repo, 'checkout', '-qb', 'wiki/synthetic-review')
    values['information_requirements'][0]['consumed_revision'] = proposal
    other['information_requirements'][0]['consumed_revision'] = proposal
    write(repo, 'alpha/result.md', '---\n' + yaml.safe_dump(values) + '---\nReviewed interpretation\n')
    write(repo, 'alpha/other.md', '---\n' + yaml.safe_dump(other) + '---\nReviewed other interpretation\n')
    git(repo, 'add', 'alpha/result.md', 'alpha/other.md', action_path); git(repo, 'commit', '-qm', 'review interpretation')
    reviewed = git(repo, 'rev-parse', 'HEAD')
    git(repo, 'checkout', '-q', base_branch); git(repo, 'merge', '--ff-only', 'wiki/synthetic-review')
    git(repo, 'update-ref', 'refs/remotes/origin/main', reviewed)
    receipt = report_review(repo, load_policy(repo, reviewed, 'wiki.config.yaml'), candidate,
        disposition='updated', reason='Synthetic independent review', evidence_revision=reviewed)
    assert receipt['verification'] == 'reported_not_verified'
    assert receipt['next_impact_allowed']
    other_receipt = report_review(repo, load_policy(repo, reviewed, 'wiki.config.yaml'), other_candidate,
        disposition='updated', reason='Synthetic independent review', evidence_revision=reviewed)
    assert other_receipt['next_impact_allowed']
    assert 'Reviewed interpretation' in git(repo, 'show', reviewed + ':alpha/result.md')
    second = impact(reviewed, reviewed, proposal)
    assert second.returncode == 0, second.stderr
    candidates = json.loads(second.stdout)['candidates']
    assert [row['target'] for row in candidates] == ['alpha/final.md']
    second_route = impact(reviewed, reviewed, proposal, selected(candidates[0]['event_id'], action_sha()))
    assert second_route.returncode == 0, second_route.stderr
    assert json.loads(second_route.stdout)['action']['status'] == 'recorded'
    git(repo, 'checkout', '-qb', 'wiki/synthetic-final-review')
    downstream['information_requirements'][0]['consumed_revision'] = reviewed
    write(repo, 'alpha/final.md', '---\n' + yaml.safe_dump(downstream) + '---\nReviewed final interpretation\n')
    git(repo, 'add', 'alpha/final.md', action_path); git(repo, 'commit', '-qm', 'review downstream')
    final_revision = git(repo, 'rev-parse', 'HEAD')
    git(repo, 'checkout', '-q', base_branch); git(repo, 'merge', '--ff-only', 'wiki/synthetic-final-review')
    git(repo, 'update-ref', 'refs/remotes/origin/main', final_revision)
    second_receipt = report_review(repo, load_policy(repo, final_revision, 'wiki.config.yaml'), candidates[0],
        disposition='updated', reason='Synthetic independent review', evidence_revision=final_revision)
    assert second_receipt['next_impact_allowed']
    recorded = git(repo, 'show', final_revision + ':' + action_path)
    assert all(event in recorded for event in (candidate['event_id'], other_candidate['event_id'], candidates[0]['event_id']))
    assert 'Reviewed final interpretation' in git(repo, 'show', final_revision + ':alpha/final.md')


def test_automatic_discovery_does_not_read_denied_consumer(repo, monkeypatch):
    from wiki_core.context_requirements import assess_approved_impact
    from wiki_core.coordination_context import CoordinationBinding
    from wiki_core.repository_reader import RepositoryReader
    config = yaml.safe_load((repo / 'wiki.config.yaml').read_text())
    config['context_access']['alpha']['policy']['deny'] = {'read': ['alpha/private.md']}
    write(repo, 'wiki.config.yaml', yaml.safe_dump(config))
    write(repo, 'alpha/private.md', '---\ninformation_requirements: []\n---\nprivate\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'deny private')
    before = git(repo, 'rev-parse', 'HEAD')
    write(repo, 'alpha/source.md', '# Changed\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'change source')
    after = git(repo, 'rev-parse', 'HEAD'); git(repo, 'update-ref', 'refs/remotes/origin/main', after)
    original = RepositoryReader.read
    def guarded(reader, ref, *args, **kwargs):
        assert ref != 'alpha/private.md', 'denied body opened'
        return original(reader, ref, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', guarded)
    result = assess_approved_impact(repo, load_policy(repo, after, 'wiki.config.yaml'),
        consumers=None, scope='alpha', before=before, after=after, destination_context='alpha',
        trusted_binding=CoordinationBinding(('.', 'alpha'), 'refs/remotes/origin/main', 'wiki.config.yaml'))
    assert result['candidates'] == []
    assert 'completeness not asserted' in result['coverage']


def test_removed_source_reports_incomplete_association_coverage(repo):
    from wiki_core.context_requirements import assess_approved_impact
    from wiki_core.coordination_context import CoordinationBinding

    write(repo, 'alpha/source.md', '---\npage_id: source-demo\npage_type: source\n---\n# Source\n')
    write(repo, 'alpha/result.md', '---\npage_id: result-demo\npage_type: claim\nsource_refs: [source-demo]\n---\n# Interpretation\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'declare source and consumer')
    before = git(repo, 'rev-parse', 'HEAD')
    git(repo, 'rm', '-q', 'alpha/source.md'); git(repo, 'commit', '-qm', 'remove source')
    after = git(repo, 'rev-parse', 'HEAD')
    git(repo, 'update-ref', 'refs/remotes/origin/main', after)
    result = assess_approved_impact(repo, load_policy(repo, after, 'wiki.config.yaml'),
        consumers=None, scope='alpha', before=before, after=after, destination_context='alpha',
        trusted_binding=CoordinationBinding(('.', 'alpha'), 'refs/remotes/origin/main', 'wiki.config.yaml'))
    assert result['candidates'] == []
    assert 'some source associations unavailable' in result['coverage']


def test_root_folder_discovery_does_not_read_child_context(repo, monkeypatch):
    from wiki_core.context_requirements import assess_approved_impact
    from wiki_core.coordination_context import CoordinationBinding
    from wiki_core.repository_reader import RepositoryReader

    write(repo, 'index.md', '# Root index\n')
    write(repo, 'source.md', '---\npage_id: source-demo\npage_type: source\n---\nBefore\n')
    write(repo, 'result.md', '---\npage_id: result-demo\npage_type: claim\nsource_refs: [source-demo]\n---\nInterpretation\n')
    write(repo, 'alpha/private.md', '---\npage_id: private\nsource_refs: [source-demo]\n---\nPrivate\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'declare root consumer')
    before = git(repo, 'rev-parse', 'HEAD')
    write(repo, 'source.md', '---\npage_id: source-demo\npage_type: source\n---\nAfter\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'change source')
    after = git(repo, 'rev-parse', 'HEAD')
    git(repo, 'update-ref', 'refs/remotes/origin/main', after)
    original = RepositoryReader.read
    def guarded(reader, ref, *args, **kwargs):
        assert not ref.startswith('alpha/'), 'child context body opened'
        return original(reader, ref, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', guarded)
    result = assess_approved_impact(repo, load_policy(repo, after, 'wiki.config.yaml'),
        consumers=None, scope='.', before=before, after=after, destination_context='.',
        trusted_binding=CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml'))
    assert [(row['target'], row['state']) for row in result['candidates']] == [
        ('result.md', 'blocked_unpinned_dependency')]


def test_discovery_stops_if_trusted_policy_moves_during_read(repo, monkeypatch):
    import pytest
    from wiki_core.context_requirements import assess_approved_impact
    from wiki_core.coordination_context import CoordinationBinding
    from wiki_core.repository_reader import RepositoryReader

    write(repo, 'alpha/source.md', '---\npage_id: source-demo\npage_type: source\n---\nBefore\n')
    write(repo, 'alpha/result.md', '---\npage_id: result-demo\nsource_refs: [source-demo]\n---\nResult\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'declare source')
    before = git(repo, 'rev-parse', 'HEAD')
    write(repo, 'alpha/source.md', '---\npage_id: source-demo\npage_type: source\n---\nAfter\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'change source')
    after = git(repo, 'rev-parse', 'HEAD')
    config = yaml.safe_load((repo / 'wiki.config.yaml').read_text())
    config['context_access']['alpha']['policy']['read'] = []
    write(repo, 'wiki.config.yaml', yaml.safe_dump(config))
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'revoke access')
    revoked = git(repo, 'rev-parse', 'HEAD')
    git(repo, 'checkout', '-q', '--detach', after)
    git(repo, 'update-ref', 'refs/remotes/origin/main', after)
    policy = load_policy(repo, after, 'wiki.config.yaml')
    original = RepositoryReader.read
    opened_after_move = []
    moved = False
    def move(reader, ref, *args, **kwargs):
        nonlocal moved
        if moved: opened_after_move.append(ref)
        result = original(reader, ref, *args, **kwargs)
        if ref == 'alpha/result.md':
            git(repo, 'update-ref', 'refs/remotes/origin/main', revoked)
            moved = True
        return result
    monkeypatch.setattr(RepositoryReader, 'read', move)
    with pytest.raises(ValueError):
        assess_approved_impact(repo, policy, consumers=None, scope='alpha', before=before, after=after,
            destination_context='alpha',
            trusted_binding=CoordinationBinding(('.', 'alpha'), 'refs/remotes/origin/main', 'wiki.config.yaml'))
    assert moved and not opened_after_move


@pytest.mark.parametrize('invalid_history', ['denied', 'unapproved'])
def test_impact_never_reads_unqualified_same_owner_history(repo, monkeypatch, invalid_history):
    from wiki_core.context_requirements import assess_approved_impact
    from wiki_core.coordination_context import CoordinationBinding
    from wiki_core.repository_reader import RepositoryReader

    config = yaml.safe_load((repo / 'wiki.config.yaml').read_text())
    if invalid_history == 'denied':
        config['context_access']['alpha']['policy']['deny'] = {'read': ['alpha/source.md']}
        write(repo, 'wiki.config.yaml', yaml.safe_dump(config))
    write(repo, 'alpha/source.md', '# Before\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'historical source')
    before = git(repo, 'rev-parse', 'HEAD')
    original_branch = git(repo, 'branch', '--show-current')
    consumed = before
    if invalid_history == 'unapproved':
        git(repo, 'checkout', '-qb', 'wiki/unapproved')
        write(repo, 'alpha/source.md', '# Unapproved source\n')
        git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'unapproved change')
        consumed = git(repo, 'rev-parse', 'HEAD')
        git(repo, 'checkout', '-q', original_branch)
    config['context_access']['alpha']['policy'].pop('deny', None)
    write(repo, 'wiki.config.yaml', yaml.safe_dump(config))
    write(repo, 'alpha/source.md', '# Approved source\n')
    requirement = {'target': 'alpha/source.md', 'fields': ['*'], 'temporal': 'current',
        'max_age_days': 30, 'consumed_revision': consumed, 'use': 'interpret', 'classification': 'internal'}
    write(repo, 'alpha/result.md', '---\n' + yaml.safe_dump({'page_id': 'result',
        'information_requirements': [requirement]}) + '---\nInterpretation\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'current source')
    after = git(repo, 'rev-parse', 'HEAD')
    git(repo, 'update-ref', 'refs/remotes/origin/main', after)
    original = RepositoryReader.read
    def guarded(reader, ref, *args, **kwargs):
        assert not (ref == 'alpha/source.md' and reader.revision == consumed), 'unqualified historical body opened'
        return original(reader, ref, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', guarded)
    binding = CoordinationBinding(('.', 'alpha'), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(consumers=['alpha/result.md'], before=before, after=after,
                destination_context='alpha', trusted_binding=binding)
    if invalid_history == 'unapproved':
        with pytest.raises(ValueError, match='approved ancestors'):
            assess_approved_impact(repo, load_policy(repo, after, 'wiki.config.yaml'), **args)
    else:
        result = assess_approved_impact(repo, load_policy(repo, after, 'wiki.config.yaml'), **args)
        assert not result['candidates']
        assert 'some connections unavailable' in result['coverage']
