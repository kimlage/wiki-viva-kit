import copy
import datetime as dt
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from tests.test_folder_policy_core import repo, git, write
from tests.test_protected_ingestion import prepared_repo
from tests.test_ingestion_connected_hub import connected
from wiki_core.context_policy import load_policy
from wiki_core.context_requirements import assess_approved_impact, route_impact_to_action
from wiki_core.context_impact import report_review
from wiki_core.coordination_context import CoordinationBinding
from wiki_core.ingest.protected import prepare, record, consolidate, inspect


def test_source_hub_owner_review_and_denied_binding(prepared_repo, monkeypatch):
    root, _ = prepared_repo
    _, args = connected(root)
    child = 'memories/alpha'
    config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
    config.setdefault('paths', {})['actions_dirname'] = 'alpha'
    child_policy = {'read': ['.'], 'write': ['self'], 'capabilities': [], 'deny': {}, 'publication': []}
    rules = [
        {'from_context': '.', 'to_context': child, 'selector': 'AGENTS.md',
         'use': 'interpretation', 'classification': 'context', 'expires': '2099-01-01'},
        *[{'from_context': '.', 'to_context': child, 'selector': ref,
           'use': 'interpret', 'classification': 'internal', 'expires': '2099-01-01'}
          for ref in ('memories/sources/synthetic.md', 'memories/hub.md')],
        {'from_context': '.', 'to_context': child, 'selector': 'wiki.coordination.yaml',
         'use': 'interpretation', 'classification': 'artifact', 'expires': '2099-01-01'},
    ]
    config['context_access']['.']['exports'] = copy.deepcopy(rules)
    config['context_access'][child] = {'owner': 'subject operator', 'policy': child_policy, 'imports': copy.deepcopy(rules)}
    write(root, 'wiki.config.yaml', yaml.safe_dump(config))
    write(root, child + '/AGENTS.md', '# Subject instructions\n')
    write(root, child + '/index.md', '# Subject index\n')
    action = child + '/review.md'
    write(root, action, '---\npage_id: subject-action\npage_type: action\naction_state: open\nnext_action: Existing work\n---\nExisting work\n')
    write(root, 'wiki.coordination.yaml', yaml.safe_dump({'schema_version': 'wiki_coordination.v1',
        'profiles': {'subject': {'label': 'Subject', 'scope': 'Review', 'action_ids': ['subject-action']}}}))
    git(root, 'add', '.'); git(root, 'commit', '-qm', 'configure synthetic owner')
    consumed = git(root, 'rev-parse', 'HEAD')
    requirement = {'target': 'memories/hub.md', 'fields': ['*'], 'temporal': 'current',
        'max_age_days': 30, 'consumed_revision': consumed, 'use': 'interpret', 'classification': 'internal'}
    values = {'page_id': 'subject', 'page_type': 'concept', 'source_refs': ['source-synthetic'],
              'information_requirements': [requirement]}
    subject = child + '/subject.md'
    write(root, subject, '---\n' + yaml.safe_dump(values) + '---\nInitial subject\n')
    git(root, 'add', '.'); git(root, 'commit', '-qm', 'declare synthetic subject')
    before = git(root, 'rev-parse', 'HEAD'); git(root, 'update-ref', 'refs/remotes/origin/main', before)
    args['approved_revision'] = before
    binding = CoordinationBinding(('.', child), 'refs/remotes/origin/main', 'wiki.config.yaml')
    prepared = prepare(root, binding, **args, source_context='system')
    request = prepared['request']; chunk = request['chunks'][0]
    sample = json.loads((Path(__file__).parent / 'fixtures/e2e/context_pass_result.sample.json').read_text())
    result = {**sample, **{k: request[k] for k in ('source_id', 'prompt_version', 'schema_version', 'model_profile')},
        **{k: chunk[k] for k in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')},
        'perspectives_required': [], 'perspectives': {}, 'entities': [], 'claims': []}
    ids = {'source_id': prepared['source_id'], 'request_id': prepared['request_id']}
    record(root, binding, **args, **ids, results=[result])
    event = ('memories/system/ingestion/events/2026-11-04-' + hashlib.sha256(ids['source_id'].encode()).hexdigest()
             + '-' + ids['request_id'] + '.md')
    consolidate(root, binding, **args, **ids, source_page='memories/sources/synthetic.md',
                event_target=event, date=dt.date(2026, 11, 4))
    assert inspect(root, binding, **args, **ids, view='integration', candidates=[])['integration'] == 'not assessed'
    branch = git(root, 'branch', '--show-current')
    git(root, 'checkout', '-qb', 'wiki/synthetic-integrate')
    for ref in ('memories/sources/synthetic.md', 'memories/hub.md'):
        with (root / ref).open('a') as stream: stream.write('\nSynthetic approved integration.\n')
    git(root, 'add', 'memories/sources/synthetic.md', 'memories/hub.md', event)
    git(root, 'commit', '-qm', 'integrate synthetic source and hub')
    after = git(root, 'rev-parse', 'HEAD'); git(root, 'checkout', '-q', branch)
    git(root, 'merge', '--ff-only', 'wiki/synthetic-integrate'); git(root, 'update-ref', 'refs/remotes/origin/main', after)

    from wiki_core.repository_reader import RepositoryReader
    original = RepositoryReader.read
    def guarded(reader, ref, *a, **kw):
        if ref.startswith(child + '/'): pytest.fail('unbound owner body opened')
        return original(reader, ref, *a, **kw)
    with monkeypatch.context() as guard:
        guard.setattr(RepositoryReader, 'read', guarded)
        with pytest.raises(ValueError):
            assess_approved_impact(root, load_policy(root, after, 'wiki.config.yaml'), consumers=None,
                scope=child, before=before, after=after, destination_context=child,
                trusted_binding=CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml'))
    impact = assess_approved_impact(root, load_policy(root, after, 'wiki.config.yaml'), consumers=None,
        scope=child, before=before, after=after, destination_context=child, trusted_binding=binding)
    by_rule = {row['rule']: row for row in impact['candidates']}
    assert by_rule['source_ref']['state'] == 'blocked_unpinned_dependency'
    assert by_rule['operational_prerequisite']['state'] == 'review_pending'
    sha = lambda: hashlib.sha256((root / action).read_bytes()).hexdigest()
    for rule in ('source_ref', 'operational_prerequisite'):
        receipt = route_impact_to_action(root, binding, destination_context=child, before=before, after=after,
            scope=child, event_id=by_rule[rule]['event_id'], action_path=action, action_id='subject-action',
            profile='subject', expected_sha256=sha())
        assert receipt['status'] == 'recorded' and receipt['execution'] == 'not_dispatched'
    text = (root / action).read_text()
    assert 'Declared relation only; consumption is unverified' in text
    git(root, 'checkout', '-qb', 'wiki/synthetic-subject-review')
    values['information_requirements'][0]['consumed_revision'] = after
    write(root, subject, '---\n' + yaml.safe_dump(values) + '---\nReviewed subject\n')
    git(root, 'add', subject, action); git(root, 'commit', '-qm', 'review synthetic subject')
    reviewed = git(root, 'rev-parse', 'HEAD'); git(root, 'checkout', '-q', branch)
    git(root, 'merge', '--ff-only', 'wiki/synthetic-subject-review'); git(root, 'update-ref', 'refs/remotes/origin/main', reviewed)
    review = report_review(root, load_policy(root, reviewed, 'wiki.config.yaml'), by_rule['operational_prerequisite'],
        disposition='updated', reason='Synthetic reported review', evidence_revision=reviewed, trusted_binding=binding)
    assert review['verification'] == 'reported_not_verified' and review['next_impact_allowed']
    assert 'Reviewed subject' in git(root, 'show', reviewed + ':' + subject)
    assert by_rule['source_ref']['event_id'] in git(root, 'show', reviewed + ':' + action)
